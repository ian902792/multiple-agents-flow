"""Simulate a planned overnight batch in a few seconds, with fake agents and no model calls.

It builds a throwaway Git repository and an isolated MAF config, then walks the real flow:
the planner's structured plan (examples/overnight/plan.json stands in for Astra), your decision,
the main chat's core commit, `night --plan` with its test preflight, and the morning report.

    python3 examples/overnight/demo.py
"""
import contextlib
import io
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from maf import core, plans, progress  # noqa: E402  (after sys.path so the checkout's own package is used)


def fake_agent(role, prompt, cwd, log, timeout):
    """Stands in for the Pi coder: writes the one file its task allows."""
    path = re.search(r"依介面約定建立 ([\w./-]+)。", prompt).group(1)
    (cwd / path).parent.mkdir(parents=True, exist_ok=True)
    (cwd / path).write_text(f"# {path}\n")
    return {"status": "ok", "text": f"Created {path}.\nUNVERIFIED: none", "session_id": "demo", "usage": None, "detail": ""}


def git(repo, *argv):
    subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)


def main():
    work = Path(tempfile.mkdtemp(prefix="maf-overnight-demo-"))
    os.environ["XDG_CONFIG_HOME"] = str(work / "config")  # Isolated: your real flows and confirmations are untouched.
    repo = work / "shop"
    repo.mkdir()
    try:
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", "MAF demo")
        git(repo, "config", "user.email", "demo@example.invalid")
        git(repo, "commit", "-q", "--allow-empty", "-m", "Start")
        core.confirm_billing(repo, core.execution_config(repo)[1])  # Fake agents only; nothing is billed.

        print("1. 你：/maf-plan 訂單功能：資料模型、API、頁面、文件，以及退款規則與退款頁，今晚做完")
        print("   Astra 只讀規畫，交回完整計畫（這裡用 examples/overnight/plan.json 代替）：\n")
        plan_id = plans.new_id()
        plans.save(repo, plan_id, core.read_json(HERE / "plan.json"))
        print(plans.render(plan_id, plans.load(repo, plan_id)))

        print("2. 你回答問題：現有政策為準")
        print(f"   $ flow.py decide {plan_id} 1 現有政策\n")
        plans.decide(repo, plan_id, 1, "現有政策")

        print("3. 主對話（Claude）先做核心：訂單資料模型骨架，commit 並驗證")
        (repo / "app").mkdir()
        (repo / "app" / "models.py").write_text("class Order: ...\n")
        git(repo, "add", "app/models.py")
        git(repo, "commit", "-q", "-m", "Add order model skeleton")
        print(f"   commit {core.git(repo, 'rev-parse', '--short', 'HEAD')}\n")

        print("4. 你：確認，開始吧，晚安")
        print(f"   $ flow.py night --plan {plan_id} --approve\n")
        plan = plans.load(repo, plan_id)
        print(plans.render_preflight(plans.preflight(repo, plan, 60)) + "\n")
        with patch.object(core.agents, "run_agent", side_effect=fake_agent), contextlib.redirect_stdout(io.StringIO()):
            runs = core.queue_chains(repo, plans.chains_for(plan), approve_all=True)
            core.run_until_settled(repo, [run["id"] for run in runs], poll=1)

        print("5. 隔天早上：maf 報告\n")
        print(progress.render_report(progress.report(repo)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
