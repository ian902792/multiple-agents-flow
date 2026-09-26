"""Simulate an unattended overnight batch in a few seconds, with fake agents and no model calls.

It builds a throwaway Git repository and an isolated MAF config, queues two task chains plus one
independent task with the same calls as `flow.py night ... --approve`, and prints the morning report:

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
        text = "MAF_NEEDS_HUMAN: 退款超過 30 天的規則和現有政策衝突，要以哪一個為準？"
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
        files = " + ".join(" ".join(f"{name}.json" for name in chain) for chain in CHAINS)
        print("睡前：一個指令排好三條鏈，依序執行（docs-update 的路徑含 orders，--approve 代表你已看過並核准）")
        print(f"  $ flow.py night {files} --approve\n")
        with patch.object(core.agents, "run_agent", side_effect=fake_agent), \
                contextlib.redirect_stdout(io.StringIO()):
            runs = core.queue_chains(repo, [[task(name) for name in chain] for chain in CHAINS], approve_all=True)
            core.run_until_settled(repo, [run["id"] for run in runs], poll=1)
        print("隔天早上：$ flow.py report\n")
        print(progress.render_report(progress.report(repo)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
