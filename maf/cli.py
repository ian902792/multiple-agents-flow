"""Small, explicit CLI. No hidden network/model calls in init/submit/status."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from . import agents, core, github


def parser():
    cli = argparse.ArgumentParser(description="Subscription-first multi-agent workflow (Python 3.11+, macOS/Linux).")
    cli.add_argument("--repo", type=Path, default=Path.cwd(), help="Target Git repository root (default: cwd)")
    commands = cli.add_subparsers(dest="action", required=True)
    p = commands.add_parser("init", help="Create .maf.json without overwriting existing configuration")
    p.add_argument("--preset", choices=("mixed", "hermes-coder"), default="mixed")
    commands.add_parser("doctor", help="Check runtime/auth availability without model inference")
    p = commands.add_parser("confirm-billing", help="Record your manual confirmation of subscription-only billing")
    p.add_argument("--no-overage", action="store_true", required=True)
    p = commands.add_parser("plan", help="Ask planner for a plan; never execute its output automatically")
    p.add_argument("--goal-file", type=Path, required=True)
    p = commands.add_parser("submit", help="Snapshot an approved task and queue its independent worktree")
    p.add_argument("task", type=Path)
    p.add_argument("--publish", action="store_true", help="Authorize pushing this task branch and creating a draft PR")
    p.add_argument("--auto-merge", action="store_true", help="Authorize low-risk merge if all policy/GitHub gates pass")
    p = commands.add_parser("work", help="Process queued work; waits consume no model tokens")
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll", type=int, default=30)
    p = commands.add_parser("status", help="Print local run states, or one run's full evidence")
    p.add_argument("run_id", nargs="?")
    p = commands.add_parser("resume", help="Resume only after inspecting an interrupted/quota-blocked run")
    p.add_argument("run_id")
    p.add_argument("--acknowledge-stopped", action="store_true")
    p.add_argument("--after", help="Known reset time with timezone; not a guess, e.g. 2026-09-20T08:00:00+08:00")
    for name in ("publish", "merge"):
        p = commands.add_parser(name, help=f"Explicitly {name} or reconcile an uncertain prior result")
        p.add_argument("run_id")
    commands.add_parser("herdr", help="Start one supervisor in a new no-focus Herdr workspace")
    return cli


def launch_herdr(repo):
    if os.environ.get("HERDR_ENV") != "1":
        raise core.FlowError("Run this command inside Herdr (HERDR_ENV=1); no focused-session guessing.")
    core.command(["herdr", "status"], repo)
    result = json.loads(core.command(["herdr", "workspace", "create", "--cwd", str(repo),
                                      "--label", "flow: " + repo.name, "--no-focus"], repo))
    pane = result["result"]["root_pane"]["pane_id"]
    launcher = Path(__file__).resolve().parent.parent / "flow.py"
    argv = [sys.executable, "-u", str(launcher), "--repo", str(repo), "work"]
    core.command(["herdr", "pane", "run", pane, shlex.join(argv)], repo)
    return {"pane": pane, "workspace": result["result"]["workspace"]["workspace_id"],
            "note": "Supervisor persists independently of planner chat. Do not stop the Herdr server. Ctrl-C pauses this worker."}


def plan(repo, config, goal_file):
    core.billing_check(repo, config)
    role = config["roles"]["planner"]
    problems = agents.doctor_role(role)
    if problems:
        raise core.FlowError("; ".join(problems))
    goal = goal_file.read_text()
    if not goal.strip() or len(goal) > 50000:
        raise core.FlowError("Goal must be nonempty and at most 50,000 characters.")
    directory = core.root_for(repo) / "plans" / str(time.time_ns())
    directory.mkdir(parents=True, mode=0o700)
    prompt = ("Read-only planning. Inspect only relevant files. Do not edit files or run commands that mutate state. "
              "Return a concise plan with dependencies, interface contracts, scope, risks and runnable acceptance commands. "
              "Suggest small independent task JSON objects with exactly id,title,instructions,paths,tests,risk. "
              "tests must be nonempty argv arrays. risk defaults manual. No task is authorized by your output; a human will inspect it.\n"
              + goal)
    result = agents.run_agent(role, prompt, repo, directory / "planner.jsonl", config["agent_timeout"])
    core.atomic(directory / "result.json", result)
    if result["status"] != "ok":
        raise core.FlowError(f"Planner {result['status']}: {result.get('detail', '')}. Evidence: {directory}")
    print(result["text"])
    print(f"\nSaved: {directory / 'result.json'}\nReview the plan, then explicitly submit approved tasks.")


def main(argv=None):
    args = parser().parse_args(argv)
    repo = args.repo.resolve()
    try:
        core.root_for(repo)
        if args.action == "status":
            result = core.load(repo, args.run_id) if args.run_id else [
                {k: run.get(k) for k in ("id", "status", "stage", "repairs", "not_before", "pr_url", "feedback")}
                for run in core.list_runs(repo)]
        elif args.action == "work":
            if not 1 <= args.poll <= 3600:
                raise core.FlowError("--poll must be 1..3600 seconds.")
            core.work(repo, args.once, args.poll)
            return
        elif args.action == "herdr":
            core.config_for(repo)
            with core.exclusive(repo):
                pass  # Release before the new supervisor tries to claim the lock.
            result = launch_herdr(repo)
        else:
            with core.exclusive(repo):
                if args.action == "init":
                    result = {"config": str(core.init(repo, args.preset)), "next": "Inspect configuration; run doctor and confirm-billing."}
                else:
                    config = core.config_for(repo)
                    if args.action == "doctor":
                        result = {name: agents.doctor_role(role) for name, role in config["roles"].items()}
                        try:
                            core.billing_check(repo, config)
                            result["billing"] = []
                        except core.FlowError as exc:
                            result["billing"] = [str(exc)]
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                        if any(result.values()):
                            raise SystemExit(1)
                        return
                    elif args.action == "confirm-billing":
                        core.atomic(repo / ".maf-local.json", {"subscription_only_confirmed": True,
                                    "config_hash": core.digest(config), "confirmed_at": time.time()})
                        result = {"confirmed": True, "warning": "Human attestation only; provider billing settings remain authoritative."}
                    elif args.action == "plan":
                        plan(repo, config, args.goal_file)
                        return
                    elif args.action == "submit":
                        result = core.submit(repo, core.read_json(args.task), args.publish, args.auto_merge)
                    elif args.action == "resume":
                        result = core.resume(repo, args.run_id, args.acknowledge_stopped, args.after)
                    else:
                        run = core.load(repo, args.run_id)
                        getattr(github, args.action)(repo, run)
                        result = run
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (core.FlowError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"flow: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nWorker stopped. Saved tasks remain; inspect status before resuming.", file=sys.stderr)
        raise SystemExit(130)
