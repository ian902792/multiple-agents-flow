"""Simulate an unattended overnight batch in a few seconds, with fake agents and no model calls.

It builds a throwaway Git repository and an isolated MAF config, queues two task chains plus one
independent task the way you would before bed, runs the worker, and prints the morning report:

    python3 examples/overnight/demo.py
"""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from maf import core, progress  # noqa: E402  (after sys.path so the checkout's own package is used)

# task id -> (file it writes, files that must already exist, whether the fake coder gets stuck)
PLAN = {
    "data-model": ("app/models.py", [], False),
    "orders-api": ("app/api.py", ["app/models.py"], False),
    "orders-page": ("app/page.html", ["app/models.py", "app/api.py"], False),
    "docs-update": ("docs/orders.md", [], False),
    "refund-rules": ("app/refunds.py", [], True),
    "refund-page": ("app/refund_page.html", ["app/refunds.py"], False),
}
CHAINS = [["data-model", "orders-api", "orders-page"], ["docs-update"], ["refund-rules", "refund-page"]]


def task(name):
    path, needs, _ = PLAN[name]
    check = "; ".join(f"assert Path({p!r}).is_file()" for p in [*needs, path])
    return {"id": name, "title": f"Build {name}", "instructions": f"Create {path}.", "paths": [path],
            "tests": [[sys.executable, "-c", "from pathlib import Path; " + check]], "risk": "docs"}


def fake_agent(role, prompt, cwd, log, timeout):
    name = next(n for n in PLAN if cwd.name.startswith(n + "-"))
    path, _, stuck = PLAN[name]
    if stuck:
        text = "MAF_NEEDS_HUMAN: refunds after 30 days conflict with the existing policy; which one wins?"
    else:
        (cwd / path).parent.mkdir(parents=True, exist_ok=True)
        (cwd / path).write_text(f"# {name}\n")
        text = f"Created {path}.\nUNVERIFIED: none"
    return {"status": "ok", "text": text, "session_id": "demo", "usage": None, "detail": ""}


def main():
    work = Path(tempfile.mkdtemp(prefix="maf-overnight-demo-"))
    os.environ["XDG_CONFIG_HOME"] = str(work / "config")  # Isolated: your real flows and confirmations are untouched.
    repo = work / "shop"
    repo.mkdir()
    try:
        for argv in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "Start"]):
            subprocess.run(["git", "-c", "user.name=MAF demo", "-c", "user.email=demo@example.invalid", *argv],
                           cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "MAF demo"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "demo@example.invalid"], cwd=repo, check=True)
        core.confirm_billing(repo, core.execution_config(repo)[1])  # Fake agents only; nothing is billed.
        print("Before bed: queue two chains and one independent task")
        ids = []
        for chain in CHAINS:
            previous = None
            for name in chain:
                run = core.submit(repo, task(name), kind="delegate", depends_on=previous)
                after = f" --depends-on {previous}" if previous else ""
                print(f"  $ flow.py delegate {name}.json{after}   -> {run['id']} ({run['status']})")
                ids.append(run["id"])
                previous = run["id"]
        for run_id in ids:  # Approve sensitive scopes before bed; nobody can answer at 3 a.m.
            if core.load(repo, run_id)["status"] == "awaiting_approval":
                print(f"  $ flow.py approve {run_id}   (path mentions orders, a sensitive word)")
                core.approve(repo, run_id)
        print("  $ flow.py work --delegate-concurrency 1   (runs one task at a time overnight)\n")
        with patch.object(core.agents, "run_agent", side_effect=fake_agent), \
                contextlib.redirect_stdout(io.StringIO()):
            core.work(repo, once=True, poll=0.1, run_id=ids, delegate_concurrency=1)
        print("Next morning: $ flow.py report\n")
        print(progress.render_report(progress.report(repo)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
