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
    cli.add_argument("--repo", type=Path, help="Target Git repository root (default: cwd)")
    cli.add_argument("--main", choices=("claude", "codex"), default="claude",
                     help="Main chat sending this request; use codex from Codex skill (default: claude)")
    commands = cli.add_subparsers(dest="action", required=True)
    commands.add_parser("install-skills", help="Register MAF skills once for this user in Claude and Codex")
    p = commands.add_parser("settings", help="Show or change user-wide optional integrations")
    p.add_argument("key", nargs="?", choices=("herdr", "default-flow"))
    p.add_argument("value", nargs="?", help="on/off for Herdr, or a saved flow name")
    p = commands.add_parser("init", help="Create .maf.json without overwriting existing configuration")
    p.add_argument("--preset", choices=core.PRESETS, default="economy")
    p = commands.add_parser("mode", help="Show or select a project override; 'default' restores the global flow")
    p.add_argument("name", nargs="?")
    commands.add_parser("flows", help="List user-wide named flows")
    p = commands.add_parser("flow-save", help="Save a named flow from a JSON file")
    p.add_argument("file", type=Path)
    commands.add_parser("doctor", help="Check runtime/auth availability without model inference")
    p = commands.add_parser("confirm-billing", help="Confirm model routes globally; --repo confirms its selected mode")
    p.add_argument("--no-overage", action="store_true", required=True)
    p = commands.add_parser("plan", help="Ask planner for a plan; never execute its output automatically")
    p.add_argument("--goal-file", type=Path, required=True)
    p.add_argument("--mode", help="Use this named flow's planner for this request only")
    p = commands.add_parser("submit", help="Snapshot an approved task and queue its independent worktree")
    p.add_argument("task", type=Path)
    p.add_argument("--mode", help="Use this mode or named flow for this task only")
    p.add_argument("--publish", action="store_true", help="Authorize pushing this task branch and creating a draft PR")
    p.add_argument("--auto-merge", action="store_true", help="Authorize low-risk merge if all policy/GitHub gates pass")
    p.add_argument("--require-approval", action="store_true", help="Hold execution for one plan/scope approval")
    for name in ("delegate", "verify"):
        p = commands.add_parser(name, help="Queue lightweight work or verify the current main chat's commit")
        p.add_argument("task", type=Path)
        p.add_argument("--mode", help="Use this mode or named flow for this task only")
        p.add_argument("--require-approval", action="store_true", help="Hold execution for one plan/scope approval")
        if name == "verify":
            p.add_argument("--base", help="Exact ancestor ref to compare with HEAD; default is merge-base with base branch")
    p = commands.add_parser("work", help="Process queued work; waits consume no model tokens")
    p.add_argument("--once", action="store_true")
    p.add_argument("--run-id", action="append", help="Only process these runs; repeat for independent delegates")
    p.add_argument("--delegate-concurrency", type=int, default=3, help="Maximum simultaneous independent delegates (default: 3; range: 1..3)")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--planner-pane", metavar="PANE_ID", help="Inside Herdr: update the main task pane while this worker runs")
    p.add_argument("--agent-panes", action="store_true", help="Inside Herdr: show each supervised agent's live output in a temporary pane")
    p = commands.add_parser("live-view", help=argparse.SUPPRESS)
    p.add_argument("file", type=Path)
    p.add_argument("--worktree", type=Path, help=argparse.SUPPRESS)
    p = commands.add_parser("status", help="Print local run states, or one run's full evidence")
    p.add_argument("run_id", nargs="?")
    p = commands.add_parser("approve", help="Approve one frozen task scope, tests and repair budget before execution")
    p.add_argument("run_id")
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
    argv = [sys.executable, "-u", str(launcher), "--repo", str(repo), "work", "--planner-pane", caller,
            "--agent-panes"]
    core.command(["herdr", "pane", "run", pane, shlex.join(argv)], repo)
    return {"pane": pane, "planner_pane": caller, "workspace": result["result"]["workspace"]["workspace_id"],
            "note": "Supervisor persists independently of planner chat. Ctrl-C stops new work and waits for active delegates to finish."}


def plan(repo, config, goal_file, main_runtime="claude"):
    role = config["roles"]["planner"]
    if role["runtime"] == main_runtime:
        raise core.FlowError("Planner must use a different runtime from the main chat; pick a flow whose planner is another agent.")
    core.billing_check(repo, config)
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
    live_log = directory / "planner.live"
    show_pane = flows.settings()["herdr_enabled"] and os.environ.get("HERDR_ENV") == "1"
    with progress.agent_pane(repo, "MAF planner", repo, live_log, show_pane) as pane:
        result = agents.run_agent(role, prompt, repo, directory / "planner.jsonl", config["agent_timeout"],
                                  **({"live_log": live_log} if pane else {}))
    core.atomic(directory / "result.json", result)
    if result["status"] != "ok":
        raise core.FlowError(f"Planner {result['status']}: {result.get('detail', '')}. Evidence: {directory}")
    print(result["text"])
    print(f"\nSaved: {directory / 'result.json'}\nReview the plan, then explicitly submit approved tasks.")


def mode_info(repo, main_runtime="claude"):
    mode, config = core.execution_config(repo, main_runtime=main_runtime)
    result = {"mode": mode, "main": main_runtime, "available": core.available_modes(repo), "roles": config["roles"],
              "scope": "New tasks only; existing run snapshots are unchanged.", "billing": []}
    result["flow"] = flows.catalog().get(mode)
    try:
        core.billing_check(repo, config)
    except core.FlowError as exc:
        result["billing"] = [str(exc)]
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    repo = (args.repo or Path.cwd()).resolve()
    try:
        if args.action == "install-skills":
            result = skills.install()
        elif args.action == "settings":
            if args.key == "herdr" and args.value in ("on", "off"):
                result = flows.set_herdr(args.value == "on")
            elif args.key == "default-flow" and args.value:
                result = flows.set_default(args.value)
            elif args.key is not None:
                raise core.FlowError("Use settings herdr on|off or settings default-flow NAME.")
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
        elif args.action == "confirm-billing" and args.repo is None:
            key = "default_flow" if args.main == "claude" else "codex_default_flow"
            name = flows.settings()[key]
            roles = flows.catalog()[name]["roles"]
            core.confirm_billing(None, {"roles": roles})
            result = {"confirmed": True, "flow": name, "roles": roles,
                      "warning": "Human attestation only; provider billing settings remain authoritative."}
        else:
            result = None
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        core.root_for(repo)
        if args.action == "mode" and not args.name:
            result = mode_info(repo, args.main)
        elif args.action == "status":
            result = core.load(repo, args.run_id) if args.run_id else [
                {k: run.get(k) for k in ("id", "status", "stage", "repairs", "not_before", "pr_url", "feedback")}
                for run in core.list_runs(repo)]
        elif args.action == "handoff":
            result = core.handoff(repo, core.load(repo, args.run_id))
        elif args.action == "live-view":
            progress.follow_live(repo, args.file, args.worktree)
            return
        elif args.action == "work":
            if not 1 <= args.poll <= 3600:
                raise core.FlowError("--poll must be 1..3600 seconds.")
            if args.agent_panes:
                progress.check_pane(repo, os.environ.get("HERDR_PANE_ID"))
            with progress.monitor(repo, args.planner_pane):
                core.work(repo, args.once, args.poll, args.run_id, args.agent_panes, args.delegate_concurrency)
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
            with core.worker_exclusive(repo):
                pass  # Release before the new supervisor tries to claim the lock.
            result = launch_herdr(repo)
        else:
            with core.exclusive(repo):
                if args.action == "init":
                    result = {"config": str(core.init(repo, args.preset)), "next": "Inspect configuration; run doctor and confirm-billing."}
                else:
                    config = core.config_for(repo)
                    if args.action in ("doctor", "confirm-billing", "plan"):
                        _, config = core.execution_config(repo, args.mode if args.action == "plan" else None, args.main)
                    if args.action == "mode":
                        core.select_mode(repo, args.name, args.main)
                        result = mode_info(repo, args.main)
                    elif args.action == "doctor":
                        result = {name: agents.doctor_role(role) if name != "reviewer" or core.review_enabled(config) else []
                                  for name, role in config["roles"].items()}
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
                        plan(repo, config, args.goal_file, args.main)
                        return
                    elif args.action == "submit":
                        result = core.submit(repo, core.read_json(args.task), args.publish, args.auto_merge, args.mode,
                                             require_approval=args.require_approval, main_runtime=args.main)
                    elif args.action in ("delegate", "verify"):
                        result = core.submit(repo, core.read_json(args.task), mode=args.mode, kind=args.action,
                                             base_ref=getattr(args, "base", None), require_approval=args.require_approval,
                                             main_runtime=args.main)
                    elif args.action == "approve":
                        result = core.approve(repo, args.run_id)
                    elif args.action == "resume":
                        with core.run_exclusive(repo, args.run_id):
                            result = core.resume(repo, args.run_id, args.acknowledge_stopped, args.after)
                    else:
                        with core.run_exclusive(repo, args.run_id):
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
