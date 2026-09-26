"""Read-only progress views and the opt-in todo.md checklist projection. Zero model calls."""
from __future__ import annotations

import contextlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

from . import core

TODO = "todo.md"
MARKER = re.compile(r"^\s*- \[( |x)\] .*<!-- maf:([a-z][a-z0-9-]{0,39}) -->\s*$")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
PANE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
# Completed stages. Checked never means merged; merged is its own column.
DONE = ("tested", "verified", "publishing", "pr", "merging", "merged")
COLUMNS = ("task", "run", "stage", "status", "tested", "reviewed", "verified", "merged", "checklist")
TTL_MS = 15000
COMPACT_WIDTH = 100
# Everything a local evidence check may raise; sync/display must survive all of it without touching run evidence.
CAUGHT = (core.FlowError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError)
sleep = time.sleep  # Watch pause only; subprocess waits keep the real time.sleep even when tests stub this.


def clean(text, width=120):
    """Terminal-safe: untrusted titles/feedback lose control and escape characters, then are bounded."""
    text = CONTROL.sub("?", str(text)).strip()
    return text if len(text) <= width else text[:width - 3] + "..."


def warn(text):
    print(clean(text, 400), file=sys.stderr, flush=True)


def checklist_file(repo):
    """Root todo.md as a regular file inside the repository, or None when absent. Symlinks fail closed."""
    repo = Path(repo).resolve()
    path = repo / TODO
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise core.FlowError("todo.md must be a regular file, not a symlink or directory.")
    if not path.exists():
        return None
    if not path.resolve().is_relative_to(repo):
        raise core.FlowError("todo.md escapes the repository.")
    return path


def marker_lines(content, task_id):
    """Lines carrying this task's marker, as (index, text, checked). Byte-based splitting matches project()."""
    found = []
    for index, raw in enumerate(content.splitlines()):
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise core.FlowError("todo.md must be UTF-8.") from exc
        match = MARKER.match(line)
        if match and match.group(2) == task_id:
            found.append((index, line, match.group(1) == "x"))
    return found


def snapshot(repo, task):
    """Called by submit before any agent runs. Only an unchecked marker line opts a task into the checklist."""
    path = checklist_file(repo)
    if path is None:
        return None
    found = marker_lines(path.read_bytes(), task["id"])
    if not found:
        return None
    if core.git(repo, "ls-files", "--", TODO) != TODO:
        raise core.FlowError("todo.md carries a maf marker but is not tracked by Git.")
    if len(found) > 1:
        raise core.FlowError(f"todo.md has {len(found)} lines marked maf:{task['id']}; keep exactly one.")
    if found[0][2]:
        return None
    if core.matches(TODO, task["paths"]):
        raise core.FlowError("Task paths must not cover todo.md while it carries this task's marker; "
                             "the coder cannot sign off its own checklist.")
    return {"path": TODO, "line": found[0][1]}


def completed(run):
    """Agent stages finished with test evidence, and review evidence when selected."""
    return run.get("stage") in DONE and (run.get("status") in DONE or run.get("status") == "needs_human")


def eligible(repo, run):
    """Evidence gate: passing tests and optional review bind to the current HEAD."""
    if not completed(run):
        raise core.FlowError(f"Run is {run.get('stage')}/{run.get('status')}; only completed runs are projected.")
    tests = run.get("tests") or []
    if (not tests or any(type(item.get("exit_code")) is not int or item["exit_code"] != 0 for item in tests)
            or [item.get("argv") for item in tests] != run["task"]["tests"]):
        raise core.FlowError("No passing test evidence.")
    if not core.review_enabled(run["config"]):
        if run["stage"] != "tested" or run.get("review") or run.get("reviewed_sha"):
            raise core.FlowError("Test-only run has inconsistent review state.")
        return core.tested(repo, run)
    return core.verified(repo, run)


def eligible_now(repo, run):
    """Display-only re-check of the evidence gate with cheap local Git reads. Never raises, never writes."""
    try:
        eligible(repo, run)
    except CAUGHT:
        return False
    return True


def projection_root(repo, base):
    if core.git(repo, "ls-files", "--", TODO) != TODO:
        raise core.FlowError("todo.md is no longer tracked by Git.")
    if core.git(repo, "branch", "--show-current") != base:
        raise core.FlowError(f"Repository root is not on the configured base branch {base}.")


def replace_bytes(path, before, content, data, base):
    """Atomic replace guarded by an identity/content recheck just before the rename. Remaining race: an editor
    that is not a maf command (no writer lock) can still write inside the window between this recheck and
    os.replace; that write would be lost. Git history keeps the last committed checklist."""
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-todo-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, before.st_mode & 0o777)
        projection_root(path.parent, base)
        current = path.lstat()
        if (not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
                or path.read_bytes() != content):
            raise core.FlowError("todo.md changed while syncing; nothing written. Retry with progress --sync.")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def project(repo, run):
    """Flip the snapshotted unchecked line to [x]; every other byte of the root todo.md is preserved."""
    record, task_id = run["checklist"], run["task"]["id"]
    path = checklist_file(repo)
    if path is None:
        raise core.FlowError("todo.md no longer exists.")
    base = run["config"]["base_branch"]
    projection_root(repo, base)
    target = record["line"].encode("utf-8")
    done = target.replace(b"[ ]", b"[x]", 1)
    before = path.stat()
    content = path.read_bytes()
    if content.count(f"<!-- maf:{task_id} -->".encode()) != 1:
        raise core.FlowError(f"todo.md must have exactly one maf:{task_id} marker.")
    found = marker_lines(content, task_id)  # Any line with this marker counts, whatever its text or state.
    if len(found) != 1:
        raise core.FlowError(f"todo.md has {len(found)} lines marked maf:{task_id}; keep exactly one, then run progress --sync.")
    index, line, _ = found[0]
    current = line.encode("utf-8")
    if current == done:
        return "already"
    if current != target:
        raise core.FlowError("Snapshotted todo.md line was edited; update the checklist manually.")
    lines = content.splitlines(keepends=True)
    lines[index] = done + lines[index][len(target):]
    replace_bytes(path, before, content, b"".join(lines), base)
    return "marked"


def sync(repo, run):
    """Project one run's verified evidence into the root checklist. Never raises; the outcome is run evidence.
    Only run.checklist.synced is written; status, stage, SHAs, tests and review are never touched."""
    record = run.get("checklist")
    if not isinstance(record, dict) or not record:
        return None
    if not completed(run):
        return "pending"  # Queued/running/quota/repair: nothing to project, nothing to record.
    try:
        eligible(repo, run)
        state, detail = project(repo, run), ""
    except CAUGHT as exc:
        state, detail = "failed", clean(str(exc), 400)
    record["synced"] = {"state": state, "detail": detail, "at": time.time()}
    run_id = clean(run.get("id", "?"), 80)
    try:
        core.save(repo, run)
    except CAUGHT as exc:
        warn(f"[{run_id}] checklist outcome not saved: {exc}")
    if state == "failed":
        warn(f"[{run_id}] checklist not updated: {detail}")
    return state


def sync_all(repo):
    """Explicit reconcile for every run with a snapshot. Caller holds the writer lock."""
    for run in core.list_runs(repo):
        if run.get("status") != "corrupt" and run.get("checklist"):
            sync(repo, run)


def diagnostics(run):
    """Observed deadlines and actionable stops; silence never proves a dead agent."""
    status, stage = run.get("status"), run.get("stage")
    activity = run.get("activity") or {}
    result = {"activity": clean(activity.get("label", "-")), "elapsed": "-",
              "log": clean(activity.get("log", ""), 1000), "attention": False, "next": ""}
    resume = f"resume {clean(run['id'], 80)} --acknowledge-stopped"
    if status == "running":
        if not activity:
            result.update(attention=True, next="Missing execution checkpoint. Inspect worker; never assume it stopped.")
        else:
            started, limit = float(activity["started_at"]), float(activity["timeout"])
            if not math.isfinite(started) or not math.isfinite(limit) or started <= 0 or limit <= 0:
                raise ValueError("Invalid execution checkpoint")
            elapsed = max(0, time.time() - started)
            result["elapsed"] = f"{int(elapsed // 60)}m/{math.ceil(limit / 60)}m"
            if elapsed > limit + 15:  # Allow bounded process-group cleanup after the deadline.
                result.update(attention=True, next="Deadline exceeded; inspect supervisor/log and confirm all processes stopped before " + resume)
    elif status == "waiting_quota":
        if run.get("not_before") is not None:
            reset = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(run["not_before"]))
            result["next"] = f"Wait until confirmed reset {reset}; worker will retry."
        else:
            result.update(attention=True, next="Confirm quota reset and stopped process, then " + resume + " [--after TIME_WITH_ZONE].")
    elif status == "awaiting_approval":
        result.update(attention=True, next=f"Inspect status {clean(run['id'], 80)} (task, paths, tests, roles); then approve {clean(run['id'], 80)} once.")
    elif status in ("needs_human", "creating"):
        result["attention"] = True
        if stage == "replan":
            result["next"] = "Requirements or security risk need a human decision; submit a new scoped task after resolving it."
        elif stage == "external_fix":
            result["next"] = "Fix the source branch, commit, and start a new verify run for the new SHA."
        elif stage in DONE:
            result["next"] = "Inspect feedback; reconcile with publish/merge. Do not replay agents."
        elif run.get("repairs", 0) > run["config"]["max_repairs"]:
            result["next"] = "Repair budget exhausted. Ask planner to diagnose the failure and submit a new scoped task."
        else:
            attempts = run.get("agents") or []
            blocked = attempts and attempts[-1].get("status") == "blocked"
            prefix = "Resolve runtime login/permissions; run doctor. " if blocked else "Inspect feedback/log; resolve the cause. "
            result["next"] = prefix + "Confirm previous processes stopped before " + resume
    return result


def row_for(repo, run):
    """Evidence-only row: verified means the gate passes right now on the run worktree; merged means GitHub confirmed."""
    if run.get("status") == "corrupt":
        return {"task": "?", "run": clean(run.get("id", "?"), 80), "stage": "corrupt", "status": "corrupt",
                "tested": "-", "reviewed": "-", "verified": "no", "complete": "no", "merged": "no", "checklist": "-",
                "created": 0, "note": clean(run.get("feedback", "")), "activity": "-", "elapsed": "-",
                "attention": True, "next": "Inspect the corrupt state file; do not retry or delete evidence.", "log": "", "agents": []}
    task = run.get("task") if isinstance(run.get("task"), dict) else {}
    tested, reviewed = str(run.get("tested_sha") or ""), str(run.get("reviewed_sha") or "")
    status = clean(run.get("status", "?"), 40)
    record = run.get("checklist") if isinstance(run.get("checklist"), dict) else None
    if not record:
        checklist = "none"
    elif not isinstance(record.get("synced"), dict):
        checklist = "pending"
    else:
        checklist = clean(record["synced"].get("state", "?"), 20)
        if checklist == "failed":
            checklist += ": " + clean(record["synced"].get("detail", ""), 80)
    note = clean(task.get("title", ""), 80)
    if status in ("needs_human", "waiting_quota") and run.get("feedback"):
        note += " | " + clean(run["feedback"])
    valid = completed(run) and eligible_now(repo, run)
    row = {"task": clean(task.get("id", "?"), 40), "run": clean(run.get("id", "?"), 80),
            "mode": clean(run.get("mode", "unknown"), 40),
            "stage": clean(run.get("stage", "?"), 40), "status": status,
            "tested": tested[:7] or "-", "reviewed": reviewed[:7] or "-",
            "verified": "yes" if valid and core.review_enabled(run["config"]) else "no",
            "complete": "yes" if valid else "no",
            "merged": "yes" if run.get("status") == "merged" else "no", "checklist": checklist,
            "created": float(run.get("created_at") or 0), "note": note,
            "agents": [{**{k: attempt.get(k) for k in ("role", "runtime", "provider", "model", "status", "duration_seconds", "usage_scope", "usage")},
                        "cache_hit": cache_hit(attempt.get("usage"))}
                       for attempt in run.get("agents", [])], **diagnostics(run)}
    if run["config_hash"] != core.digest(core.config_for(repo)):
        row.update(attention=True, next="Configuration changed since submission. Do not resume/publish this run; inspect the old worker and submit a new task.")
    elif completed(run) and not valid:
        row.update(attention=True, next="Saved completion no longer has valid evidence. Inspect tests, review and worktree HEAD.")
    return row


def cache_hit(usage):
    """Share of prompt tokens served from the provider cache, or None when counts are missing."""
    if not isinstance(usage, dict):
        return None
    count = lambda key: usage.get(key, 0) if type(usage.get(key, 0)) is int and usage.get(key, 0) >= 0 else None
    if "cacheRead" in usage:  # Pi: input excludes cache reads and writes
        parts = [count("cacheRead"), count("input"), count("cacheWrite")]
    elif "cache_read_input_tokens" in usage:  # Claude: same split, different names
        parts = [count("cache_read_input_tokens"), count("input_tokens"), count("cache_creation_input_tokens")]
    elif "cache_read_tokens" in usage:  # Antigravity: input_tokens excludes cache reads
        parts = [count("cache_read_tokens"), count("input_tokens"), 0]
    elif "cached_input_tokens" in usage:  # Codex: input_tokens already includes cached tokens
        parts = [count("cached_input_tokens"), count("input_tokens"), 0]
        if None not in parts:
            parts[1] -= parts[0]
    else:
        return None
    if None in parts or parts[1] < 0 or not sum(parts):
        return None
    return round(parts[0] / sum(parts), 3)


def rows(repo):
    """One row per run, grouped by task id then age. Reads state and local Git only; no lock, no agents."""
    result = []
    for run in core.list_runs(repo):
        try:
            result.append(row_for(repo, run))
        except CAUGHT as exc:
            result.append(row_for(repo, {"id": str(run.get("id", "?")), "status": "corrupt", "feedback": str(exc)}))
    result.sort(key=lambda row: (row["task"], row["created"], row["run"]))
    return result


def counts_for(rows):
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def compact():
    """Narrow interactive terminals (Herdr panes are ~38 columns) get the multi-line layout; pipes keep the table."""
    try:
        return sys.stdout.isatty() and shutil.get_terminal_size((COMPACT_WIDTH, 24)).columns < COMPACT_WIDTH
    except (AttributeError, ValueError, OSError):
        return False


def render(rows, compact=False):
    if compact:
        lines = []
        for row in rows:
            lines += [f"{row['task']}  {row['run']}",
                      f"  {row['stage']}/{row['status']}  t {row['tested']}  r {row['reviewed']}",
                      f"  verified {row['verified']}  merged {row['merged']}  list {row['checklist']}"]
            if row["note"]:
                lines.append("  " + row["note"])
            lines.extend(detail_lines(row))
    else:
        widths = {column: max([len(column)] + [len(row[column]) for row in rows]) for column in COLUMNS}
        lines = ["  ".join(column.upper().ljust(widths[column]) for column in COLUMNS).rstrip()]
        for row in rows:
            lines.append("  ".join(row[column].ljust(widths[column]) for column in COLUMNS).rstrip())
            if row["note"]:
                lines.append("    " + row["note"])
            lines.extend(detail_lines(row))
    counts = counts_for(rows)
    lines.append(f"{len(rows)} run(s)" + ("; " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) if counts else ""))
    lines.append("tested = tests at HEAD; verified = tests + independent review; not merged or released.")
    if compact:
        width = max(1, shutil.get_terminal_size((38, 24)).columns)
        lines = [part for line in lines for part in textwrap.wrap(line, width=width)]
    return "\n".join(lines)


def detail_lines(row):
    lines = []
    hits = [f"{a['role']} {a['runtime']} {a['cache_hit']:.1%}" for a in row.get("agents", []) if a.get("cache_hit") is not None]
    if hits:
        lines.append("  cache hit: " + " | ".join(hits))
    if row["status"] == "running":
        lines.append(f"  {row['activity']} | elapsed/limit {row['elapsed']}")
    if row["next"]:
        lines.append(f"  {'ATTENTION' if row['attention'] else 'NEXT'}: {row['next']}")
    if row["attention"] and row["log"]:
        lines.append("  log: " + row["log"])
    return lines


def title_for(rows):
    """Pane title: verified/total, the active (running, else queued) stage and task, then attention counts."""
    done = sum(row["complete"] == "yes" for row in rows)
    parts = [f"maf {done}/{len(rows)} done"]
    attention = sum(row["attention"] for row in rows)
    if attention:
        parts.append(f"!{attention} attention")
    running = sum(row["status"] == "running" for row in rows)
    if running > 1:
        parts.append(f"{running} running")
    active = next((row for status in ("running", "queued", "waiting_quota") for row in rows if row["status"] == status), None)
    if active:
        parts.append(f"{active['status']} {active['stage']} {active['task']}")
    elif attention:
        blocked = next(row for row in rows if row["attention"])
        parts.append(f"{blocked['status']} {blocked['stage']} {blocked['task']}")
    return clean(" | ".join(parts), 80)


def check_pane(repo, pane):
    """Explicit live pane only: no focused-pane guessing, no input, no lifecycle changes."""
    from . import flows
    if not flows.settings()["herdr_enabled"]:
        raise core.FlowError("Herdr integration is off; enable it with settings herdr on or in Flow Studio.")
    if os.environ.get("HERDR_ENV") != "1":
        raise core.FlowError("--planner-pane needs HERDR_ENV=1 (run inside Herdr) and the current live pane id.")
    if not isinstance(pane, str) or not PANE_ID.fullmatch(pane):
        raise core.FlowError("Invalid pane id.")
    core.command(["herdr", "pane", "get", pane], repo, timeout=15)


def ttl_for(poll):
    """Metadata must outlive one poll plus the report itself, even when --poll exceeds the 15 s default."""
    return max(TTL_MS, (int(poll) + 15) * 1000)


def report_pane(repo, pane, title, poll=5):
    from . import flows
    if not flows.settings()["herdr_enabled"]:
        raise core.FlowError("Herdr integration is off; pane reporting stopped.")
    core.command(["herdr", "pane", "report-metadata", pane, "--source", "maf-progress",
                  "--title", title, "--ttl-ms", str(ttl_for(poll))], repo, timeout=15)


PATH_KEYS = ("path", "file_path", "filePath", "target_file", "TargetFile", "AbsolutePath")


class LiveSummary:
    """Turn a private agent event stream into one line per tool call.

    Shows the tool name and, when it stays inside the worktree, the repo-relative path it touches.
    Never shows prompts, model text, file contents, search patterns or shell commands; the raw
    private log remains the diagnostic source.
    """

    def __init__(self, root=None, now=None):
        self.root = Path(root).resolve() if root else None
        self.started = self.last = now

    def path(self, value):
        if not isinstance(value, str) or not value or "\x00" in value:
            return ""
        path = Path(value)
        if path.is_absolute():
            if self.root is None:
                return ""
            try:
                path = path.resolve().relative_to(self.root)
            except (ValueError, OSError):
                return ""
        if ".." in path.parts or not str(path) or str(path) == ".":
            return ""
        return clean(path.as_posix(), 80)

    def target(self, *sources):
        for source in sources:
            if isinstance(source, dict):
                found = next((self.path(source[k]) for k in PATH_KEYS if k in source), "")
                if found:
                    return found
        return ""

    def steps(self, event):
        """(tool, path) calls, 'done' or 'error <status>' from Pi, Claude, Codex or Antigravity events."""
        kind = event.get("type")
        if kind == "tool_execution_start":  # Pi
            return [(event.get("toolName"), self.target(event.get("args")))]
        if kind == "agent_settled":
            return ["done"]
        if kind == "assistant":  # Claude stream-json
            blocks = (event.get("message") or {}).get("content") if isinstance(event.get("message"), dict) else []
            return [(b.get("name"), self.target(b.get("input"))) for b in blocks or []
                    if isinstance(b, dict) and b.get("type") == "tool_use"]
        if kind == "result":
            return ["done" if event.get("subtype") == "success" else f"error {event.get('subtype')}"]
        if kind in ("item.started", "item.completed"):  # Codex
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            if kind == "item.started" and item.get("type") == "command_execution":
                return [("command", "")]
            if kind == "item.completed" and item.get("type") == "file_change":
                changes = item.get("changes") if isinstance(item.get("changes"), list) else []
                return [("edit", self.target(c)) for c in changes if isinstance(c, dict)] or [("edit", "")]
            return []
        if kind == "turn.completed":
            return ["done"]
        if kind in ("turn.failed", "error"):
            return ["error"]
        if event.get("event") == "step_update":  # Antigravity
            step = event.get("step_update") if isinstance(event.get("step_update"), dict) else {}
            tool = step.get("tool_name")
            info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
            return [(tool, self.target(info.get("args"), info.get("input"), info))] if tool else []
        if event.get("event") == "result":
            status = (event.get("result") or {}).get("status") if isinstance(event.get("result"), dict) else None
            return ["done" if status == "SUCCESS" else f"error {status}"]
        return []

    def feed(self, raw, now):
        """Lines to print for one raw event line; message streaming and unknown events print nothing."""
        if self.started is None:
            self.started = self.last = now
        if raw is None:
            steps = [("step", "details omitted")]
        else:
            try:
                event = json.loads(raw)
            except ValueError:
                return []
            steps = self.steps(event) if isinstance(event, dict) else []
        lines = []
        for step in steps:
            if isinstance(step, tuple):
                tool, where = step
                if not isinstance(tool, str) or not tool:
                    continue
                text = clean(tool, 30) + (f" {where}" if where else "")
                lines.append(f"{text}  (+{max(0, now - self.last):.0f}s)")
            else:
                lines.append(f"{clean(step, 40)}  ({max(0, now - self.started):.0f}s total)")
            self.last = now
        return lines


def follow_live(repo, path, worktree=None):
    """Follow a private agent event stream until the owned Herdr pane closes."""
    root = core.root_for(repo)
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise core.FlowError("Live log must be a regular file in this repository's private MAF state.")
    print("MAF live view: tool calls and repo paths only; prompts, replies and contents stay private.", flush=True)
    summary = LiveSummary(worktree)
    pending, too_large = bytearray(), False
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.readline(4096)
                if not chunk:
                    time.sleep(.2)
                    continue
                if len(pending) + len(chunk) > 65536:
                    too_large = True
                if not too_large:
                    pending.extend(chunk)
                if chunk.endswith(b"\n"):
                    for line in summary.feed(None if too_large else bytes(pending), time.monotonic()):
                        print(f"{time.strftime('%H:%M:%S')}  {line}", flush=True)
                    pending.clear()
                    too_large = False
    except KeyboardInterrupt:
        return


@contextlib.contextmanager
def agent_pane(repo, label, cwd, live_log, enabled):
    """Display a supervised agent's live output; never delegate execution or verification to the pane."""
    if not enabled:
        yield None
        return
    parent, pane = os.environ.get("HERDR_PANE_ID"), None
    try:
        check_pane(repo, parent)
        live_log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        live_log.touch(mode=0o600, exist_ok=True)
        created = json.loads(core.command(["herdr", "pane", "split", parent, "--direction", "right",
                                           "--cwd", str(cwd), "--no-focus"], repo, timeout=15))
        pane = created["result"]["pane"]["pane_id"]
        if not isinstance(pane, str) or not PANE_ID.fullmatch(pane) or pane == parent:
            raise core.FlowError("Herdr returned an invalid child pane id.")
        core.command(["herdr", "pane", "rename", pane, clean(label, 80)], repo, timeout=15)
        launcher = Path(__file__).resolve().parent.parent / "flow.py"
        viewer = [sys.executable, "-u", str(launcher), "--repo", str(repo), "live-view", str(live_log),
                  "--worktree", str(cwd)]
        core.command(["herdr", "pane", "run", pane, shlex.join(viewer)], repo, timeout=15)
    except CAUGHT as exc:
        warn(f"agent pane unavailable: {exc}; agent continues in the supervisor.")
        if isinstance(pane, str) and PANE_ID.fullmatch(pane) and pane != parent:
            try:
                core.command(["herdr", "pane", "close", pane], repo, timeout=15)
            except CAUGHT as close_exc:
                warn(f"agent pane {pane} could not be closed: {close_exc}")
        pane = None
    try:
        yield pane
    finally:
        if pane:
            try:
                core.command(["herdr", "pane", "close", pane], repo, timeout=15)
            except CAUGHT as exc:
                warn(f"agent pane {pane} could not be closed: {exc}")


def show(repo, watch=False, poll=5, pane=None, stop=None):
    """Print the summary; with watch, reprint only on change. Pane metadata refreshes every poll to renew its TTL."""
    if pane:
        check_pane(repo, pane)
    last = herdr_error = None
    try:
        while True:
            current = rows(repo)
            body = render(current, compact())
            if body != last:
                print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{body}", flush=True)
                last = body
            if pane:
                try:
                    report_pane(repo, pane, title_for(current), poll)
                    herdr_error = None
                except (core.FlowError, OSError, subprocess.SubprocessError) as exc:
                    try:
                        check_pane(repo, pane)
                    except (core.FlowError, OSError, subprocess.SubprocessError):
                        warn(f"progress: pane {pane} is gone; continuing without pane metadata.")
                        pane = None
                    if pane and str(exc) != herdr_error:
                        warn(f"progress: pane metadata not refreshed: {exc}")
                        herdr_error = str(exc)
            if not watch or (stop is not None and stop.is_set()):
                return
            if stop is None:
                sleep(poll)
            else:
                stop.wait(poll)
    except KeyboardInterrupt:
        print("\nprogress: watch stopped.", file=sys.stderr, flush=True)


@contextlib.contextmanager
def monitor(repo, pane):
    """Keep the calling Herdr pane informed while the worker holds the writer lock."""
    if not pane:
        yield
        return
    check_pane(repo, pane)
    stop = threading.Event()
    def watch():
        try:
            show(repo, watch=True, pane=pane, stop=stop)
        except CAUGHT as exc:
            warn(f"progress: main pane monitor stopped: {exc}; use progress --json.")
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=35)
        if thread.is_alive():
            warn("progress: monitor did not stop in time; pane metadata will expire. Use progress --json.")
