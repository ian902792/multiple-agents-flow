"""Read-only progress views and the opt-in todo.md checklist projection. Zero model calls."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tempfile
import time

from . import core

TODO = "todo.md"
MARKER = re.compile(r"^\s*- \[( |x)\] .*<!-- maf:([a-z][a-z0-9-]{0,39}) -->\s*$")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
PANE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
# Stages past independent review. Checked never means merged; merged is its own column.
DONE = ("verified", "publishing", "pr", "merging", "merged")
COLUMNS = ("task", "run", "stage", "status", "tested", "reviewed", "verified", "merged", "checklist")
TTL_MS = 15000
sleep = time.sleep  # Watch pause only; subprocess waits keep the real time.sleep even when tests stub this.


def clean(text, width=120):
    """Terminal-safe: untrusted titles/feedback lose control and escape characters, then are bounded."""
    text = CONTROL.sub("?", str(text)).strip()
    return text if len(text) <= width else text[:width - 3] + "..."


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


def eligible(repo, run):
    """Evidence gate: passing tests, independent approval and the current worktree HEAD bind to one SHA."""
    if run.get("status") not in DONE or run.get("stage") not in DONE:
        raise core.FlowError(f"Run is {run.get('status')}; only tested and independently reviewed runs are projected.")
    tests = run.get("tests") or []
    if not tests or any(item.get("exit_code") for item in tests):
        raise core.FlowError("No passing test evidence.")
    head, review = run.get("tested_sha"), run.get("review") or {}
    if not head or review.get("decision") != "approve" or review.get("head_sha") != head or run.get("reviewed_sha") != head:
        raise core.FlowError("Independent approval does not bind to the tested SHA.")
    return core.verified(repo, run)


def replace_bytes(path, data):
    if path.is_symlink():
        raise core.FlowError("Refusing to write todo.md through a symlink.")
    mode = path.stat().st_mode & 0o777
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-todo-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def project(repo, record):
    """Flip the snapshotted unchecked line to [x]; every other byte of the root todo.md is preserved."""
    path = checklist_file(repo)
    if path is None:
        raise core.FlowError("todo.md no longer exists.")
    target = record["line"].encode("utf-8")
    done = target.replace(b"[ ]", b"[x]", 1)
    lines = path.read_bytes().splitlines(keepends=True)
    stripped = [line.rstrip(b"\r\n") for line in lines]
    if target not in stripped:
        if stripped.count(done) == 1:
            return "already"
        raise core.FlowError("Snapshotted todo.md line is missing or edited; update the checklist manually.")
    if stripped.count(target) > 1 or done in stripped:
        raise core.FlowError("Snapshotted todo.md line is duplicated; update the checklist manually.")
    index = stripped.index(target)
    lines[index] = done + lines[index][len(target):]
    replace_bytes(path, b"".join(lines))
    return "marked"


def sync(repo, run):
    """Project one run's verified evidence into the root checklist. Never raises; the outcome is run evidence."""
    record = run.get("checklist")
    if not record:
        return None
    if run.get("status") not in DONE:
        return "pending"  # Queued/running/quota/error: nothing to project, nothing to record.
    try:
        eligible(repo, run)
        state, detail = project(repo, record), ""
    except (core.FlowError, OSError, ValueError, KeyError, TypeError) as exc:
        state, detail = "failed", str(exc)
    record["synced"] = {"state": state, "detail": detail, "at": time.time()}
    core.save(repo, run)
    if state == "failed":
        print(f"[{clean(run['id'], 80)}] checklist not updated: {clean(detail)}", file=sys.stderr, flush=True)
    return state


def sync_all(repo):
    """Explicit reconcile for every run with a snapshot. Caller holds the writer lock."""
    for run in core.list_runs(repo):
        if run.get("status") != "corrupt" and run.get("checklist"):
            sync(repo, run)


def row_for(run):
    """Evidence-only row: verified means tested and independently reviewed at one SHA; merged means GitHub confirmed."""
    if run.get("status") == "corrupt":
        return {"task": "?", "run": clean(run.get("id", "?"), 80), "stage": "corrupt", "status": "corrupt",
                "tested": "-", "reviewed": "-", "verified": "no", "merged": "no", "checklist": "-",
                "created": 0, "note": clean(run.get("feedback", ""))}
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
    return {"task": clean(task.get("id", "?"), 40), "run": clean(run.get("id", "?"), 80),
            "stage": clean(run.get("stage", "?"), 40), "status": status,
            "tested": tested[:7] or "-", "reviewed": reviewed[:7] or "-",
            "verified": "yes" if tested and tested == reviewed and run.get("status") in DONE else "no",
            "merged": "yes" if run.get("status") == "merged" else "no", "checklist": checklist,
            "created": float(run.get("created_at") or 0), "note": note}


def rows(repo):
    """One row per run, grouped by task id then age. Reads state only; no lock, no agents."""
    result = []
    for run in core.list_runs(repo):
        try:
            result.append(row_for(run))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            result.append(row_for({"id": str(run.get("id", "?")), "status": "corrupt", "feedback": str(exc)}))
    result.sort(key=lambda row: (row["task"], row["created"], row["run"]))
    return result


def counts_for(rows):
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def render(rows):
    widths = {column: max([len(column)] + [len(row[column]) for row in rows]) for column in COLUMNS}
    lines = ["  ".join(column.upper().ljust(widths[column]) for column in COLUMNS).rstrip()]
    for row in rows:
        lines.append("  ".join(row[column].ljust(widths[column]) for column in COLUMNS).rstrip())
        if row["note"]:
            lines.append("    " + row["note"])
    counts = counts_for(rows)
    lines.append(f"{len(rows)} run(s)" + ("; " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) if counts else ""))
    lines.append("verified/checked = tests + independent review on the run worktree; not merged, not released.")
    return "\n".join(lines)


def title_for(rows):
    counts = counts_for(rows)
    return clean("maf: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "no runs"), 80)


def check_pane(repo, pane):
    """Explicit live pane only: no focused-pane guessing, no input, no lifecycle changes."""
    if os.environ.get("HERDR_ENV") != "1":
        raise core.FlowError("--planner-pane needs HERDR_ENV=1 (run inside Herdr) and the current live pane id.")
    if not isinstance(pane, str) or not PANE_ID.fullmatch(pane):
        raise core.FlowError("Invalid pane id.")
    core.command(["herdr", "pane", "get", pane], repo, timeout=15)


def report_pane(repo, pane, title):
    core.command(["herdr", "pane", "report-metadata", pane, "--source", "maf-progress",
                  "--title", title, "--ttl-ms", str(TTL_MS)], repo, timeout=15)


def show(repo, watch=False, poll=5, pane=None):
    """Print the summary; with watch, reprint only on change. Pane metadata refreshes every poll to renew its TTL."""
    if pane:
        check_pane(repo, pane)
    last = herdr_error = None
    try:
        while True:
            current = rows(repo)
            body = render(current)
            if body != last:
                print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{body}", flush=True)
                last = body
            if pane:
                try:
                    report_pane(repo, pane, title_for(current))
                    herdr_error = None
                except (core.FlowError, OSError) as exc:
                    if str(exc) != herdr_error:
                        print(f"progress: pane metadata not refreshed: {clean(str(exc))}", file=sys.stderr, flush=True)
                        herdr_error = str(exc)
            if not watch:
                return
            sleep(poll)
    except KeyboardInterrupt:
        print("\nprogress: watch stopped.", file=sys.stderr, flush=True)
