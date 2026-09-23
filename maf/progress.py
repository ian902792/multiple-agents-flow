"""Read-only progress views and the opt-in todo.md checklist projection. Zero model calls."""
from __future__ import annotations

import contextlib
import json
import math
import os
from pathlib import Path
import re
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
# Stages past independent review. Checked never means merged; merged is its own column.
DONE = ("verified", "publishing", "pr", "merging", "merged")
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
    """Agent stages are finished: stage is past independent review and status is either past review or a
    publish/merge stop (needs_human). Incomplete coding/testing/reviewing never qualifies, whatever the status."""
    return run.get("stage") in DONE and (run.get("status") in DONE or run.get("status") == "needs_human")


def eligible(repo, run):
    """Evidence gate: passing tests, independent approval and the current worktree HEAD bind to one SHA."""
    if not completed(run):
        raise core.FlowError(f"Run is {run.get('stage')}/{run.get('status')}; only tested and independently reviewed runs are projected.")
    tests = run.get("tests") or []
    if (not tests or any(type(item.get("exit_code")) is not int or item["exit_code"] != 0 for item in tests)
            or [item.get("argv") for item in tests] != run["task"]["tests"]):
        raise core.FlowError("No passing test evidence.")
    head, review = run.get("tested_sha"), run.get("review") or {}
    core.review_result(json.dumps(review), head)
    if (not head or review.get("decision") != "approve" or review.get("head_sha") != head
            or review.get("findings") or run.get("reviewed_sha") != head):
        raise core.FlowError("Independent approval does not bind to the tested SHA.")
    return core.verified(repo, run)


def verified_now(repo, run):
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
    elif status in ("needs_human", "creating"):
        result["attention"] = True
        if stage in DONE:
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
                "tested": "-", "reviewed": "-", "verified": "no", "merged": "no", "checklist": "-",
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
    row = {"task": clean(task.get("id", "?"), 40), "run": clean(run.get("id", "?"), 80),
            "mode": clean(run.get("mode", "unknown"), 40),
            "stage": clean(run.get("stage", "?"), 40), "status": status,
            "tested": tested[:7] or "-", "reviewed": reviewed[:7] or "-",
            "verified": "yes" if completed(run) and verified_now(repo, run) else "no",
            "merged": "yes" if run.get("status") == "merged" else "no", "checklist": checklist,
            "created": float(run.get("created_at") or 0), "note": note,
            "agents": [{k: attempt.get(k) for k in ("role", "runtime", "provider", "model", "status", "duration_seconds", "usage_scope", "usage")}
                       for attempt in run.get("agents", [])], **diagnostics(run)}
    if run["config_hash"] != core.digest(core.read_json(Path(repo) / ".maf.json")):
        row.update(attention=True, next="Configuration changed since submission. Do not resume/publish this run; inspect the old worker and submit a new task.")
    elif completed(run) and row["verified"] == "no":
        row.update(attention=True, next="Saved completion no longer verifies. Inspect tests, review and worktree HEAD before publication.")
    return row


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
    lines.append("verified = tests + independent review at HEAD; not merged, not released." if compact else
                 "verified/checked = tests + independent review on the run worktree; not merged, not released.")
    if compact:
        width = max(1, shutil.get_terminal_size((38, 24)).columns)
        lines = [part for line in lines for part in textwrap.wrap(line, width=width)]
    return "\n".join(lines)


def detail_lines(row):
    lines = []
    if row["status"] == "running":
        lines.append(f"  {row['activity']} | elapsed/limit {row['elapsed']}")
    if row["next"]:
        lines.append(f"  {'ATTENTION' if row['attention'] else 'NEXT'}: {row['next']}")
    if row["attention"] and row["log"]:
        lines.append("  log: " + row["log"])
    return lines


def title_for(rows):
    """Pane title: verified/total, the active (running, else queued) stage and task, then attention counts."""
    verified = sum(row["verified"] == "yes" for row in rows)
    parts = [f"maf {verified}/{len(rows)} verified"]
    attention = sum(row["attention"] for row in rows)
    if attention:
        parts.append(f"!{attention} attention")
    active = next((row for status in ("running", "queued", "waiting_quota") for row in rows if row["status"] == status), None)
    if active:
        parts.append(f"{active['status']} {active['stage']} {active['task']}")
    elif attention:
        blocked = next(row for row in rows if row["attention"])
        parts.append(f"{blocked['status']} {blocked['stage']} {blocked['task']}")
    return clean(" | ".join(parts), 80)


def check_pane(repo, pane):
    """Explicit live pane only: no focused-pane guessing, no input, no lifecycle changes."""
    if os.environ.get("HERDR_ENV") != "1":
        raise core.FlowError("--planner-pane needs HERDR_ENV=1 (run inside Herdr) and the current live pane id.")
    if not isinstance(pane, str) or not PANE_ID.fullmatch(pane):
        raise core.FlowError("Invalid pane id.")
    core.command(["herdr", "pane", "get", pane], repo, timeout=15)


def ttl_for(poll):
    """Metadata must outlive one poll plus the report itself, even when --poll exceeds the 15 s default."""
    return max(TTL_MS, (int(poll) + 15) * 1000)


def report_pane(repo, pane, title, poll=5):
    core.command(["herdr", "pane", "report-metadata", pane, "--source", "maf-progress",
                  "--title", title, "--ttl-ms", str(ttl_for(poll))], repo, timeout=15)


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
