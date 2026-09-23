"""Small, explicit CLI. No hidden network/model calls in init/submit/status."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from . import agents, core, flows, github, progress, skills


def parser():
    cli = argparse.ArgumentParser(description="Subscription-first multi-agent workflow (Python 3.11+, macOS/Linux).")
    cli.add_argument("--repo", type=Path, default=Path.cwd(), help="Target Git repository root (default: cwd)")
    commands = cli.add_subparsers(dest="action", required=True)
    commands.add_parser("install-skills", help="Register MAF skills once for this user in Claude and Codex")
    p = commands.add_parser("settings", help="Show or change user-wide optional integrations")
    p.add_argument("key", nargs="?", choices=("herdr",))
    p.add_argument("value", nargs="?", choices=("on", "off"))
    p = commands.add_parser("init", help="Create .maf.json without overwriting existing configuration")
    p.add_argument("--preset", choices=core.PRESETS, default="economy")
    p = commands.add_parser("mode", help="Show or select the local default for new tasks; existing runs stay pinned")
    p.add_argument("name", nargs="?")
    commands.add_parser("flows", help="List user-wide named flows")
    p = commands.add_parser("flow-save", help="Save a named flow from a JSON file")
    p.add_argument("file", type=Path)
    commands.add_parser("doctor", help="Check runtime/auth availability without model inference")
    p = commands.add_parser("confirm-billing", help="Record your manual confirmation of subscription-only billing")
    p.add_argument("--no-overage", action="store_true", required=True)
    p = commands.add_parser("plan", help="Ask planner for a plan; never execute its output automatically")
    p.add_argument("--goal-file", type=Path, required=True)
    p.add_argument("--mode", help="Use this named flow's planner for this request only")
    p = commands.add_parser("submit", help="Snapshot an approved task and queue its independent worktree")
    p.add_argument("task", type=Path)
    p.add_argument("--mode", help="Use this mode or named flow for this task only")
    p.add_argument("--publish", action="store_true", help="Authorize pushing this task branch and creating a draft PR")
    p.add_argument("--auto-merge", action="store_true", help="Authorize low-risk merge if all policy/GitHub gates pass")
    for name in ("delegate", "verify"):
        p = commands.add_parser(name, help="Queue Pi work or verify the current committed Claude work")
        p.add_argument("task", type=Path)
        p.add_argument("--mode", help="Use this mode or named flow for this task only")
        if name == "verify":
            p.add_argument("--base", help="Exact ancestor ref to compare with HEAD; default is merge-base with base branch")
    p = commands.add_parser("work", help="Process queued work; waits consume no model tokens")
    p.add_argument("--once", action="store_true")
    p.add_argument("--run-id", help="Only process this run, without consuming other queued tasks")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--planner-pane", metavar="PANE_ID", help="Inside Herdr: update the main task pane while this worker runs")
    p = commands.add_parser("status", help="Print local run states, or one run's full evidence")
    p.add_argument("run_id", nargs="?")
    p = commands.add_parser("handoff", help="Show compact, exact-SHA evidence for a verified run")
    p.add_argument("run_id")
    p = commands.add_parser("progress", help="Read-only terminal summary of every run; no lock, no model calls")
    p.add_argument("--watch", action="store_true", help="Keep polling and print only when the summary changes; Ctrl-C exits")
    p.add_argument("--poll", type=int, default=5)
    p.add_argument("--planner-pane", metavar="PANE_ID", help="Inside Herdr only: refresh this live pane's metadata title each poll")
    p.add_argument("--sync", action="store_true", help="First project verified runs into todo.md under the writer lock")
    p.add_argument("--json", action="store_true", help="One compact snapshot, including blockers and per-attempt usage; no transcripts")
    p = commands.add_parser("resume", help="Resume only after inspecting an interrupted/quota-blocked run")
    p.add_argument("run_id")
    p.add_argument("--acknowledge-stopped", action="store_true")
    p.add_argument("--after", help="Known reset time with timezone; not a guess, e.g. 2026-09-20T08:00:00+08:00")
    for name in ("publish", "merge"):
        p = commands.add_parser(name, help=f"Explicitly {name} or reconcile an uncertain prior result")
        p.add_argument("run_id")
    commands.add_parser("herdr", help="Start one supervisor in a new no-focus Herdr workspace")
    p = commands.add_parser("ui", help="Open the local user-wide flow and integration settings editor")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-open", action="store_true")
    return cli


def launch_herdr(repo):
    if os.environ.get("HERDR_ENV") != "1":
        raise core.FlowError("Run this command inside Herdr (HERDR_ENV=1); no focused-session guessing.")
    caller = os.environ.get("HERDR_PANE_ID")
    if not caller:
        raise core.FlowError("HERDR_PANE_ID is missing; cannot report progress to the main task pane.")
    progress.check_pane(repo, caller)
    core.command(["herdr", "status"], repo)
    result = json.loads(core.command(["herdr", "workspace", "create", "--cwd", str(repo),
                                      "--label", "flow: " + repo.name, "--no-focus"], repo))
    pane = result["result"]["root_pane"]["pane_id"]
    launcher = Path(__file__).resolve().parent.parent / "flow.py"
    argv = [sys.executable, "-u", str(launcher), "--repo", str(repo), "work", "--planner-pane", caller]
    core.command(["herdr", "pane", "run", pane, shlex.join(argv)], repo)
    return {"pane": pane, "planner_pane": caller, "workspace": result["result"]["workspace"]["workspace_id"],
            "note": "Supervisor persists independently of planner chat. Do not stop the Herdr server. Ctrl-C pauses this worker."}


def plan(repo, config, goal_file):
    core.billing_check(repo, config)
    role = config["roles"]["planner"]
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


def mode_info(repo):
    mode, config = core.execution_config(repo)
    result = {"mode": mode, "available": core.available_modes(repo), "roles": config["roles"],
              "scope": "New tasks only; existing run snapshots are unchanged.", "billing": []}
    result["flow"] = flows.catalog().get(mode)
    try:
        core.billing_check(repo, config)
    except core.FlowError as exc:
        result["billing"] = [str(exc)]
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.action == "install-skills":
            result = skills.install()
        elif args.action == "settings":
            if args.value:
                result = flows.set_herdr(args.value == "on")
            else:
                result = flows.settings()
        elif args.action == "flows":
            result = {"flows": flows.catalog()}
        elif args.action == "flow-save":
            data = core.read_json(args.file)
            if not isinstance(data, dict) or set(data) != {"name", "flow"}:
                raise core.FlowError("Flow file needs name and flow, as exported by Flow Studio.")
            result = flows.save(data["name"], data["flow"])
        elif args.action == "ui":
            from . import ui
            ui.serve(args.port, not args.no_open)
            return
        else:
            result = None
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        core.root_for(repo)
        if args.action == "mode" and not args.name:
            result = mode_info(repo)
        elif args.action == "status":
            result = core.load(repo, args.run_id) if args.run_id else [
                {k: run.get(k) for k in ("id", "status", "stage", "repairs", "not_before", "pr_url", "feedback")}
                for run in core.list_runs(repo)]
        elif args.action == "handoff":
            result = core.handoff(repo, core.load(repo, args.run_id))
        elif args.action == "work":
            if not 1 <= args.poll <= 3600:
                raise core.FlowError("--poll must be 1..3600 seconds.")
            with progress.monitor(repo, args.planner_pane):
                core.work(repo, args.once, args.poll, args.run_id)
            return
        elif args.action == "progress":
            if not 1 <= args.poll <= 3600:
                raise core.FlowError("--poll must be 1..3600 seconds.")
            if args.json and (args.watch or args.planner_pane or args.sync):
                raise core.FlowError("--json is a read-only snapshot; use it without --watch, --planner-pane or --sync.")
            if args.json:
                print(json.dumps(progress.rows(repo), ensure_ascii=False, indent=2))
                return
            if args.sync:
                with core.exclusive(repo):
                    progress.sync_all(repo)
            progress.show(repo, args.watch, args.poll, args.planner_pane)
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
                    if args.action in ("doctor", "confirm-billing", "plan"):
                        _, config = core.execution_config(repo, args.mode if args.action == "plan" else None)
                    if args.action == "mode":
                        core.select_mode(repo, args.name)
                        result = mode_info(repo)
                    elif args.action == "doctor":
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
                        core.confirm_billing(repo, config)
                        result = {"confirmed": True, "warning": "Human attestation only; provider billing settings remain authoritative."}
                    elif args.action == "plan":
                        plan(repo, config, args.goal_file)
                        return
                    elif args.action == "submit":
                        result = core.submit(repo, core.read_json(args.task), args.publish, args.auto_merge, args.mode)
                    elif args.action in ("delegate", "verify"):
                        result = core.submit(repo, core.read_json(args.task), mode=args.mode, kind=args.action,
                                             base_ref=getattr(args, "base", None))
                    elif args.action == "resume":
                        result = core.resume(repo, args.run_id, args.acknowledge_stopped, args.after)
                    else:
                        run = core.load(repo, args.run_id)
                        getattr(github, args.action)(repo, run)
                        progress.sync(repo, run)
                        result = run
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (core.FlowError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"flow: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nWorker stopped. Saved tasks remain; inspect status before resuming.", file=sys.stderr)
        raise SystemExit(130)
