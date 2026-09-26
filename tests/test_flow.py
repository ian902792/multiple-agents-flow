import copy
import contextlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from maf import cli, core, flows, github, plans, progress, skills


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_temp.cleanup)
        env = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.config_temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        core.git(self.repo, "config", "user.email", "test@example.invalid")
        core.git(self.repo, "config", "user.name", "Flow Test")
        (self.repo / "README.md").write_text("Before\n")
        (self.repo / ".gitignore").write_text("__pycache__/\n")
        core.git(self.repo, "add", ".")
        core.git(self.repo, "commit", "-qm", "Initial")
        core.init(self.repo, "economy")
        core.select_mode(self.repo, "configured")
        self.config = core.config_for(self.repo)
        self.config["roles"]["reviewer"]["enabled"] = True
        core.atomic(self.repo / ".maf.json", self.config)
        core.confirm_billing(self.repo, self.config)
        self.task = {"id": "improve-docs", "title": "Improve docs", "instructions": "Add usage paragraph.",
                     "paths": ["README.md"], "tests": [[sys.executable, "-c", "from pathlib import Path; assert 'After' in Path('README.md').read_text()"]],
                     "risk": "docs"}

    def fake_agent(self, role, prompt, cwd, log, timeout):
        if role["access"] == "edit":
            (cwd / "README.md").write_text("After\n")
            text = "Done"
        else:
            text = json.dumps({"decision": "approve", "head_sha": core.git(cwd, "rev-parse", "HEAD"),
                               "risk": "low", "summary": "Reviewed implementation and tests.", "findings": []})
        return {"status": "ok", "text": text, "session_id": "fake-" + role["runtime"], "usage": None, "detail": ""}

    def complete(self, **kwargs):
        run = core.submit(self.repo, self.task, **kwargs)
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=self.fake_agent) as agent:
            core.execute(self.repo, run)
        self.assertEqual(agent.call_count, 2)
        self.assertEqual(run["status"], "verified")
        return run

    def test_offline_full_workflow(self):
        run = self.complete()
        self.assertEqual(core.verified(self.repo, run), run["tested_sha"])
        self.assertEqual(run["reviewed_sha"], run["tested_sha"])
        self.assertEqual(github.risk_reasons(run), [])
        self.assertEqual((self.repo / "README.md").read_text(), "Before\n")
        self.assertEqual([a["role"] for a in run["agents"]], ["coder", "reviewer"])
        self.assertEqual(core.handoff(self.repo, run)["coder_notes"], "Done")
        self.assertEqual(core.handoff(self.repo, run)["cache_hit"],
                         [{"role": "coder", "runtime": "pi", "cache_hit": None}, {"role": "reviewer", "runtime": "pi", "cache_hit": None}])
        tampered = copy.deepcopy(run)
        tampered["review"] = {}
        with self.assertRaises(core.FlowError):
            core.verified(self.repo, tampered)

    def test_unchecked_review_stops_after_tests_and_cannot_publish(self):
        config = copy.deepcopy(self.config)
        config["roles"]["reviewer"]["enabled"] = False
        core.atomic(self.repo / ".maf.json", config)
        core.confirm_billing(self.repo, config)
        changed_reviewer = copy.deepcopy(config)
        changed_reviewer["roles"]["reviewer"]["model"] = "deepseek-v4.1-flash-next"
        core.billing_check(self.repo, changed_reviewer)
        changed_reviewer["roles"]["reviewer"]["enabled"] = True
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, changed_reviewer)
        changed_effort = copy.deepcopy(config)
        changed_effort["roles"]["coder"]["effort"] = "max"
        core.billing_check(self.repo, changed_effort)
        changed_effort["roles"]["coder"]["model"] = "deepseek-v4.1-pro"
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, changed_effort)
        run = core.submit(self.repo, self.task)
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=self.fake_agent) as agent:
            core.execute(self.repo, run)
        self.assertEqual(agent.call_count, 1)
        self.assertEqual(run["status"], "tested")
        self.assertNotIn("reviewed_sha", run)
        self.assertIsNone(core.handoff(self.repo, run)["review"])
        self.assertEqual(progress.row_for(self.repo, run)["complete"], "yes")
        self.assertEqual(progress.row_for(self.repo, run)["verified"], "no")
        with self.assertRaises(core.FlowError):
            core.verified(self.repo, run)
        with self.assertRaisesRegex(core.FlowError, "requires independent review"):
            core.submit(self.repo, self.task, publish=True)

    def test_pi_default_and_manual_review_use_separate_sessions(self):
        self.assertEqual(self.config["roles"]["coder"]["runtime"], "pi")
        self.assertEqual(self.config["max_repairs"], 1)
        self.task["risk"] = "manual"
        self.task["tests"][0][-1] += "; print('NOISY_TEST_OUTPUT')"
        run = core.submit(self.repo, self.task)
        self.assertEqual(run["status"], "awaiting_approval")
        run = core.approve(self.repo, run["id"])
        snapshots, prompts = [], []
        def agent(role, prompt, cwd, log, timeout):
            saved = core.load(self.repo, run["id"])
            snapshots.append(saved)
            prompts.append(prompt)
            self.assertEqual(saved["status"], "running")
            self.assertEqual(saved["activity"]["log"], str(log))
            self.assertIn(role["model"], saved["activity"]["label"])
            return self.fake_agent(role, prompt, cwd, log, timeout)
        with patch.object(core.agents, "run_agent", side_effect=agent), patch.object(core.agents, "doctor_role") as doctor:
            core.execute(self.repo, run)
        doctor.assert_not_called()  # run_agent owns the single preflight auth check.
        self.assertEqual([a["runtime"] for a in run["agents"]], ["pi", "pi"])
        self.assertEqual([s["stage"] for s in snapshots], ["coding", "reviewing"])
        self.assertNotIn('"tail"', prompts[1])
        self.assertEqual(run["tested_sha"], run["reviewed_sha"])
        self.assertTrue(all(a["duration_seconds"] >= 0 for a in run["agents"]))
        self.assertIn("NOISY_TEST_OUTPUT", run["tests"][0]["tail"])

    def test_permission_stop_is_recorded_and_never_retried_automatically(self):
        run = core.submit(self.repo, self.task)
        with patch.object(core.agents, "run_agent", return_value={"status": "blocked", "detail": "Permission denied"}) as agent:
            core.process(self.repo, run)
            core.work(self.repo, once=True)
        self.assertEqual(agent.call_count, 1)
        self.assertEqual(run["status"], "needs_human")
        self.assertEqual(run["agents"][-1]["status"], "blocked")
        self.assertEqual(core.load(self.repo, run["id"])["feedback"], "Permission denied")

    def test_mode_switch_preserves_runs_policy_and_confirmed_configurations(self):
        original = (self.repo / ".maf.json").read_bytes()
        old = core.submit(self.repo, self.task)
        selected = core.select_mode(self.repo, "opus-sol")
        self.assertEqual(selected["auto_paths"], self.config["auto_paths"])
        self.assertEqual((self.repo / ".maf.json").read_bytes(), original)
        self.task["risk"] = "manual"
        new = core.submit(self.repo, self.task)
        with patch.object(core.agents, "run_agent") as agent, self.assertRaises(core.FlowError):
            core.execute(self.repo, new)
        agent.assert_not_called()
        core.confirm_billing(self.repo, selected)
        new = core.approve(self.repo, new["id"])
        core.billing_check(self.repo, self.config)  # Confirming one mode does not revoke another.
        core.select_mode(self.repo, "economy")
        with patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            core.execute(self.repo, old)
            core.execute(self.repo, new)
        self.assertEqual([a["runtime"] for a in old["agents"]], ["pi", "pi"])
        self.assertEqual([a["model"] for a in new["agents"]], ["claude-opus-5-5"])
        self.assertEqual(new["mode"], "opus-sol")
        core.verified(self.repo, old)
        core.tested(self.repo, new)
        self.config["test_timeout"] += 1
        core.atomic(self.repo / ".maf.json", self.config)
        with self.assertRaises(core.FlowError):
            core.tested(self.repo, new)
        core.billing_check(self.repo, core.execution_config(self.repo, "opus-sol")[1])

    def test_sensitive_task_waits_for_one_scope_approval(self):
        task = dict(self.task, paths=["AGENTS.md"])
        run = core.submit(self.repo, task)
        self.assertEqual(run["status"], "awaiting_approval")
        self.assertTrue(run["approval"]["reasons"])
        with patch.object(core.agents, "run_agent") as agent:
            core.work(self.repo, once=True, run_id=run["id"])
            with self.assertRaisesRegex(core.FlowError, "awaits approval"):
                core.execute(self.repo, run)
        agent.assert_not_called()
        run = core.approve(self.repo, run["id"])
        self.assertEqual(run["status"], "queued")
        with self.assertRaises(core.FlowError):
            core.approve(self.repo, run["id"])
        (Path(run["worktree"]) / "AGENTS.md").write_text("Unapproved edit")
        with patch.object(core.agents, "run_agent") as agent, self.assertRaisesRegex(core.FlowError, "Worktree changed"):
            core.execute(self.repo, run)
        agent.assert_not_called()
        (Path(run["worktree"]) / "AGENTS.md").unlink()
        run["task"]["tests"] = [["true"]]
        with patch.object(core.agents, "run_agent") as agent, self.assertRaisesRegex(core.FlowError, "scope"):
            core.execute(self.repo, run)
        agent.assert_not_called()

        shell_task = dict(self.task, id="shell-check", tests=[["bash", "-c", "true"]])
        self.assertEqual(core.submit(self.repo, shell_task)["status"], "awaiting_approval")

    def test_escalations_stop_without_an_automatic_repair(self):
        run = core.submit(self.repo, self.task)
        with patch.object(core.agents, "run_agent", return_value={"status": "ok", "text": "MAF_NEEDS_HUMAN: unclear permission change", "usage": None, "detail": ""}) as agent:
            core.execute(self.repo, run)
        self.assertEqual(agent.call_count, 1)
        self.assertEqual((run["status"], run["stage"]), ("needs_human", "replan"))
        with self.assertRaisesRegex(core.FlowError, "new approved task"):
            core.resume(self.repo, run["id"], True)

        next_run = core.submit(self.repo, dict(self.task, id="review-risk"))
        def security_review(role, prompt, cwd, log, timeout):
            if role["access"] == "edit":
                return self.fake_agent(role, prompt, cwd, log, timeout)
            return {"status": "ok", "text": json.dumps({"decision": "changes_requested",
                    "head_sha": core.git(cwd, "rev-parse", "HEAD"), "risk": "manual",
                    "summary": "Security concern", "findings": ["Permission scope unclear"]}),
                    "usage": None, "detail": ""}
        with patch.object(core.agents, "run_agent", side_effect=security_review) as agent:
            core.execute(self.repo, next_run)
        self.assertEqual(agent.call_count, 2)
        self.assertEqual((next_run["status"], next_run["stage"]), ("needs_human", "replan"))
        self.assertEqual(next_run["repairs"], 0)

    def test_named_flow_selects_models_without_changing_project_policy(self):
        before = (self.repo / ".maf.json").read_bytes()
        flow = flows.templates()["quick"]
        flow["roles"]["coder"]["effort"] = "high"
        flows.save("my-flow", flow)
        core.select_mode(self.repo, "my-flow")
        self.assertEqual(core.execution_config(self.repo)[1]["roles"]["coder"]["effort"], "high")
        self.assertEqual((self.repo / ".maf.json").read_bytes(), before)
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, core.execution_config(self.repo)[1])
        with self.assertRaises(core.FlowError):
            flows.save("bad", dict(flow, roles={"coder": {}}))
        with tempfile.TemporaryDirectory() as other_dir:
            other = Path(other_dir)
            subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
            core.init(other, "economy")
            core.select_mode(other, "my-flow")
            self.assertEqual(core.execution_config(other)[0], "my-flow")
            self.assertEqual(core.execution_config(self.repo)[0], "my-flow")
            core.select_mode(other, "quick")
            self.assertEqual(core.execution_config(self.repo)[0], "my-flow")

    def test_global_commands_work_without_a_git_repository(self):
        missing_repo = Path(self.config_temp.name) / "not-a-repo"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--repo", str(missing_repo), "settings"])
            cli.main(["--repo", str(missing_repo), "settings", "herdr", "on"])
            cli.main(["--repo", str(missing_repo), "settings", "default-flow", "quick-antigravity"])
            cli.main(["--repo", str(missing_repo), "flows"])
            cli.main(["confirm-billing", "--no-overage"])
        lines = out.getvalue()
        self.assertIn('"herdr_enabled": false', lines)
        self.assertIn('"herdr_enabled": true', lines)
        self.assertIn('"quick"', lines)
        self.assertIn('"quick-antigravity"', lines)

    def test_new_repository_uses_global_flow_without_init(self):
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
            core.git(other, "config", "user.email", "test@example.invalid")
            core.git(other, "config", "user.name", "Flow Test")
            (other / "README.md").write_text("Before\n")
            core.git(other, "add", "README.md")
            core.git(other, "commit", "-qm", "Initial")
            self.assertFalse((other / ".maf.json").exists())
            self.assertEqual(core.execution_config(other)[0], "quick")
            flows.set_default("quick-antigravity")
            mode, config = core.execution_config(other)
            self.assertEqual((mode, config["roles"]["coder"]["model"]),
                             ("quick-antigravity", "gemini-3.8-flash-low"))
            with self.assertRaises(core.FlowError):
                core.billing_check(other, config)
            core.confirm_billing(other, config)
            core.billing_check(self.repo, config)
            run = core.submit(other, dict(self.task, independent=True), kind="delegate")
            self.assertEqual(run["config"]["roles"]["coder"]["runtime"], "antigravity")
            self.assertTrue(core.parallel_lightweight(run))
            self.assertFalse((other / ".maf.json").exists())
            core.select_mode(other, "planned")
            self.assertEqual(core.execution_config(other)[0], "planned")
            core.select_mode(other, "default")
            self.assertEqual(core.execution_config(other)[0], "quick-antigravity")

    def test_effort_levels_follow_each_cli(self):
        flow = flows.templates()["quick"]
        flow["main"]["effort"] = "max"
        flow["roles"]["reviewer"]["effort"] = "xhigh"
        flows.save("deep-review", flow)
        for effort in ("off", "minimal", "xhigh", "max"):
            flow["roles"]["coder"]["effort"] = effort
            flows.save("pi-" + effort, flow)
        flow["roles"]["coder"]["effort"] = "unlimited"
        with self.assertRaises(ValueError):
            flows.save("invalid-pi-effort", flow)
        flow["roles"]["coder"] = {"runtime": "antigravity", "provider": "google-account",
                                  "model": "gemini-3.8-flash-high", "access": "edit", "effort": "off"}
        with self.assertRaises(ValueError):
            flows.save("invalid-agy-effort", flow)

    def test_codex_main_flow_keeps_claude_review_optional_and_independent(self):
        flow = flows.templates()["codex-pi"]
        self.assertEqual(flow["main"], {"runtime": "codex", "model": "gpt-6-sol", "effort": "high"})
        self.assertEqual((flow["roles"]["coder"]["runtime"], flow["roles"]["coder"]["effort"]), ("pi", "low"))
        self.assertEqual(flow["roles"]["reviewer"]["model"], "claude-opus-5-5")
        self.assertFalse(flow["roles"]["reviewer"]["enabled"])
        self.assertEqual((flow["roles"]["planner"]["runtime"], flow["roles"]["planner"]["model"]), ("claude", "claude-opus-5-5"))
        flow["roles"]["reviewer"]["enabled"] = True
        flows.save("codex-with-review", flow)
        self.assertEqual(core.execution_config(self.repo, "codex-with-review", "codex")[1]["roles"]["reviewer"]["runtime"], "claude")
        flow["roles"]["reviewer"]["runtime"] = "codex"
        flow["roles"]["reviewer"]["provider"] = "chatgpt"
        with self.assertRaises(core.FlowError):
            flows.save("self-review", flow)

    def test_main_chats_keep_separate_defaults_and_project_modes(self):
        self.assertEqual(core.execution_config(self.repo, main_runtime="codex")[0], "codex-pi")
        flows.set_default("planned")
        flows.set_default("codex-pi")
        self.assertEqual(flows.settings()["default_flow"], "planned")
        self.assertEqual(flows.settings()["codex_default_flow"], "codex-pi")
        core.select_mode(self.repo, "quick", "claude")
        core.select_mode(self.repo, "codex-pi", "codex")
        self.assertEqual(core.execution_config(self.repo, main_runtime="claude")[0], "quick")
        self.assertEqual(core.execution_config(self.repo, main_runtime="codex")[0], "codex-pi")
        with self.assertRaises(core.FlowError):
            core.select_mode(self.repo, "quick", "codex")
        core.select_mode(self.repo, "default", "codex")
        self.assertEqual(core.execution_config(self.repo, main_runtime="claude")[0], "quick")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main(["--repo", str(self.repo), "--main", "codex", "mode"])
        self.assertEqual(json.loads(output.getvalue())["mode"], "codex-pi")

    def test_codex_main_can_verify_with_claude_reviewer(self):
        flow = flows.templates()["codex-pi"]
        flow["roles"]["reviewer"]["enabled"] = True
        flows.save("codex-reviewed", flow)
        core.select_mode(self.repo, "codex-reviewed", "codex")
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        core.confirm_billing(self.repo, core.execution_config(self.repo, main_runtime="codex")[1])
        (self.repo / "README.md").write_text("After\n")
        core.git(self.repo, "add", "README.md")
        core.git(self.repo, "commit", "-qm", "Codex implementation")
        run = core.submit(self.repo, self.task, kind="verify", base_ref="HEAD^", main_runtime="codex")
        self.assertEqual(run["config"]["roles"]["reviewer"]["runtime"], "claude")

    def test_claude_commit_verify_and_pi_delegate_bind_exact_sha(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        core.git(self.repo, "switch", "-c", "feature")
        flow = flows.templates()["quick"]
        flow["roles"]["reviewer"]["enabled"] = True
        flows.save("quick", flow)
        core.select_mode(self.repo, "quick")
        core.confirm_billing(self.repo, core.execution_config(self.repo)[1])
        (self.repo / "README.md").write_text("After from Claude\n")
        core.git(self.repo, "add", "README.md")
        core.git(self.repo, "commit", "-qm", "Claude implementation")
        source = core.git(self.repo, "rev-parse", "HEAD")
        review = core.submit(self.repo, self.task, kind="verify")
        with patch.object(core.agents, "run_agent", side_effect=self.fake_agent) as agent:
            core.execute(self.repo, review)
        self.assertEqual(agent.call_count, 1)
        self.assertEqual([a["role"] for a in review["agents"]], ["reviewer"])
        self.assertEqual(core.handoff(self.repo, review)["head_sha"], source)
        self.assertEqual(review["tested_sha"], review["reviewed_sha"])
        delegate = core.submit(self.repo, dict(self.task, id="small-fix"), kind="delegate")
        with patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            core.execute(self.repo, delegate)
        self.assertEqual([a["runtime"] for a in delegate["agents"]], ["pi", "codex"])
        self.assertEqual(delegate["source_sha"], source)
        self.assertNotEqual(core.handoff(self.repo, delegate)["head_sha"], source)
        self.assertEqual(core.git(self.repo, "rev-parse", "HEAD"), source)

    def test_independent_pi_delegates_overlap_and_allow_new_submission(self):
        self.assertEqual(cli.parser().parse_args(["work", "--run-id", "a", "--run-id", "b"]).run_id, ["a", "b"])
        self.assertEqual(cli.parser().parse_args(["work"]).delegate_concurrency, 3)
        with self.assertRaisesRegex(core.FlowError, "1..3"):
            core.work(self.repo, once=True, delegate_concurrency=4)
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        tasks = []
        for name, path in (("a", "docs/a.md"), ("b", "docs/b.md"),
                           ("c", "docs/a.md"), ("d", "docs/d.md"), ("e", "docs/e.md")):
            task = {"id": f"parallel-{name}", "title": f"Write {name}", "instructions": f"Create {path}.",
                    "paths": [path], "tests": [[sys.executable, "-c",
                    f"from pathlib import Path; assert Path('{path}').read_text() == 'After\\n'"]],
                    "risk": "docs", "independent": True}
            tasks.append(core.submit(self.repo, task, kind="delegate"))
        entered, release = threading.Event(), threading.Event()
        barrier = threading.Barrier(3, timeout=10)
        errors = []

        def agent(role, prompt, cwd, log, timeout):
            if role["access"] == "edit":
                if cwd.name.startswith(("parallel-a-", "parallel-b-", "parallel-d-")):
                    barrier.wait()
                    entered.set()
                    if not release.wait(10):
                        raise AssertionError("parallel agents did not finish")
                path = ("docs/b.md" if cwd.name.startswith("parallel-b-") else
                        "docs/d.md" if cwd.name.startswith("parallel-d-") else
                        "docs/e.md" if cwd.name.startswith("parallel-e-") else "docs/a.md")
                (cwd / "docs").mkdir(exist_ok=True)
                (cwd / path).write_text("After\n")
                text = "Done"
            else:
                text = json.dumps({"decision": "approve", "head_sha": core.git(cwd, "rev-parse", "HEAD"),
                                   "risk": "low", "summary": "Reviewed", "findings": []})
            return {"status": "ok", "text": text, "session_id": "fake", "usage": None, "detail": ""}

        def worker():
            try:
                core.work(self.repo, once=True, poll=0.1, run_id=[run["id"] for run in tasks])
            except BaseException as exc:
                errors.append(exc)

        with patch.object(core.agents, "run_agent", side_effect=agent):
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(10), "three Pi coders did not overlap")
                time.sleep(0.25)  # Let the scheduler try to refill while all slots are occupied.
                self.assertIn("3 running", progress.title_for(progress.rows(self.repo)))
                for _ in range(20):
                    try:
                        with core.exclusive(self.repo):
                            later = core.submit(self.repo, dict(tasks[1]["task"], id="parallel-later"), kind="delegate")
                        break
                    except core.FlowError as exc:
                        if "Another flow command" not in str(exc):
                            raise
                        time.sleep(0.02)
                else:
                    self.fail("new work could not be submitted while Pi agents were active")
                self.assertEqual(core.load(self.repo, tasks[2]["id"])["status"], "queued")
                self.assertEqual(core.load(self.repo, tasks[4]["id"])["status"], "queued")
            finally:
                release.set()
                thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        for run in tasks:
            completed = core.load(self.repo, run["id"])
            self.assertEqual(completed["status"], "verified")
            self.assertEqual(core.handoff(self.repo, completed)["head_sha"], completed["tested_sha"])
        self.assertEqual(later["status"], "queued")

    def night_task(self, name, needs=()):
        files = [f"docs/{item}.md" for item in (*needs, name)]
        check = "; ".join(f"assert Path('{path}').read_text() == 'After\\n'" for path in files)
        return {"id": f"night-{name}", "title": f"Write {name}", "instructions": f"Create docs/{name}.md.",
                "paths": [f"docs/{name}.md"], "tests": [[sys.executable, "-c", "from pathlib import Path; " + check]],
                "risk": "docs"}

    def night_agent(self, stuck=(), quota=()):
        def agent(role, prompt, cwd, log, timeout):
            name = cwd.name.split("-")[1]
            if role["access"] == "edit":
                if name in quota:
                    return {"status": "quota", "text": "", "session_id": None, "usage": None, "detail": "usage limit"}
                if name in stuck:
                    return {"status": "ok", "text": "MAF_NEEDS_HUMAN: requirements conflict", "session_id": "fake",
                            "usage": None, "detail": ""}
                (cwd / "docs").mkdir(exist_ok=True)
                (cwd / "docs" / f"{name}.md").write_text("After\n")
                text = "Done\nUNVERIFIED: none"
            else:
                text = json.dumps({"decision": "approve", "head_sha": core.git(cwd, "rev-parse", "HEAD"),
                                   "risk": "low", "summary": "Reviewed", "findings": []})
            return {"status": "ok", "text": text, "session_id": "fake", "usage": None, "detail": ""}
        return agent

    def test_overnight_chain_starts_each_task_from_its_dependency(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        a = core.submit(self.repo, self.night_task("a"), kind="delegate")
        b = core.submit(self.repo, self.night_task("b", ["a"]), kind="delegate", depends_on=a["id"])
        c = core.submit(self.repo, self.night_task("c", ["a", "b"]), kind="delegate", depends_on=b["id"])
        d = core.submit(self.repo, self.night_task("d"), kind="delegate")
        self.assertEqual((b["status"], b["source_sha"]), ("waiting_dependency", None))
        self.assertFalse(Path(b["worktree"]).exists())
        ids = [run["id"] for run in (a, b, c, d)]
        with patch.object(core.agents, "run_agent", side_effect=self.night_agent()), \
                contextlib.redirect_stdout(io.StringIO()):
            core.work(self.repo, once=True, poll=0.1, run_id=ids, delegate_concurrency=1)
        a, b, c, d = (core.load(self.repo, run_id) for run_id in ids)
        self.assertEqual([run["status"] for run in (a, b, c, d)], ["verified"] * 4)
        self.assertEqual(b["source_sha"], a["tested_sha"])
        self.assertEqual(c["source_sha"], b["tested_sha"])
        self.assertEqual(core.handoff(self.repo, c)["depends_on"], b["id"])
        data = progress.report(self.repo)
        self.assertEqual(data["chains"], [[a["id"], b["id"], c["id"]]])
        self.assertIn({"runs": [a["id"], b["id"], c["id"]], "range": f"{a['source_sha']}..{c['tested_sha']}"},
                      data["integrate"])
        self.assertIn({"runs": [d["id"]], "range": f"{d['source_sha']}..{d['tested_sha']}"}, data["integrate"])
        text = progress.render_report(data)
        self.assertIn("可以整合", text)
        self.assertIn(f"git cherry-pick {a['source_sha']}..{c['tested_sha']}", text)
        self.assertNotIn("需要你處理", text)

    def test_overnight_chain_stops_downstream_but_waits_for_quota(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        a = core.submit(self.repo, self.night_task("a"), kind="delegate")
        b = core.submit(self.repo, self.night_task("b", ["a"]), kind="delegate", depends_on=a["id"])
        c = core.submit(self.repo, self.night_task("c", ["a", "b"]), kind="delegate", depends_on=b["id"])
        x = core.submit(self.repo, self.night_task("x"), kind="delegate")
        y = core.submit(self.repo, self.night_task("y", ["x"]), kind="delegate", depends_on=x["id"])
        ids = [run["id"] for run in (a, b, c, x, y)]
        with patch.object(core.agents, "doctor_role", return_value=[]), \
                patch.object(core.agents, "run_agent", side_effect=self.night_agent(stuck={"b"}, quota={"x"})), \
                contextlib.redirect_stdout(io.StringIO()):
            core.work(self.repo, once=True, poll=0.1, run_id=ids, delegate_concurrency=1)
        a, b, c, x, y = (core.load(self.repo, run_id) for run_id in ids)
        self.assertEqual(a["status"], "verified")
        self.assertEqual((b["status"], b["stage"]), ("needs_human", "replan"))
        self.assertEqual((c["status"], c["stage"]), ("needs_human", "dependency"))
        self.assertIn(b["id"], c["feedback"])
        self.assertEqual(x["status"], "waiting_quota")
        self.assertEqual(y["status"], "waiting_dependency")  # Quota is not failure: it continues once x finishes.
        with self.assertRaisesRegex(core.FlowError, "dependency cannot finish"):
            core.resume(self.repo, c["id"], acknowledge=True)
        text = progress.render_report(progress.report(self.repo))
        self.assertIn("需要你處理", text)
        self.assertIn("上游無法完成", text)
        self.assertIn(f"{a['id']}（測試與審查通過） → {b['id']}（卡住） → {c['id']}（卡住）", text)
        self.assertIn(f"等 {x['id']} 完成後自動開始", text)
        self.assertNotIn("可以整合", text)

    def test_night_command_chains_files_and_prints_chinese_report(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        folder = Path(self.config_temp.name) / "tasks"
        folder.mkdir()
        files = {}
        for name, needs in (("a", []), ("b", ["a"]), ("d", [])):
            files[name] = folder / f"{name}.json"
            files[name].write_text(json.dumps(self.night_task(name, needs)))
        output = io.StringIO()
        with patch.object(core.agents, "run_agent", side_effect=self.night_agent()), contextlib.redirect_stdout(output):
            cli.main(["--repo", str(self.repo), "night", str(files["a"]), str(files["b"]), "+", str(files["d"]), "--poll", "1"])
        runs = {run["task"]["id"]: run for run in core.list_runs(self.repo)}
        self.assertEqual({run["status"] for run in runs.values()}, {"verified"})
        self.assertEqual(runs["night-b"]["depends_on"], runs["night-a"]["id"])
        self.assertNotIn("depends_on", runs["night-d"])
        text = output.getvalue()
        self.assertIn(f"排入 {runs['night-b']['id']}  等上游  （接在 {runs['night-a']['id']} 之後）", text)
        self.assertIn("MAF 報告", text)
        self.assertIn("已完成（3）", text)
        errors = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(errors):
            cli.main(["--repo", str(self.repo), "night", "+", str(files["d"])])
        self.assertIn("at least one task", errors.getvalue())

    def sample_plan(self):
        return {"version": 1, "goal": "訂單功能", "interfaces": [{"name": "Order", "spec": "id:int"}],
                "main_agent": [{"title": "訂單模型骨架", "why": "其他任務都依賴它", "paths": ["app/models.py"]}],
                "decisions": [{"question": "退款以哪個為準？", "options": ["新規則", "現有政策"],
                               "blocks": ["night-b"], "answer": None}],
                "chains": [{"name": "訂單", "tasks": [dict(self.night_task("a"), acceptance_why="a 存在"),
                                                     self.night_task("b", ["a"])]},
                           {"name": "文件", "tasks": [self.night_task("d")]}],
                "risks": ["介面改了下游要一起調整"]}

    def test_plan_is_parsed_validated_and_summarized(self):
        plan = self.sample_plan()
        parsed = plans.parse("好的，計畫如下：\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```\n")
        self.assertEqual(parsed["chains"][1]["tasks"][0]["id"], "night-d")
        for broken in (dict(plan, extra=1), dict(plan, chains=[]),
                       dict(plan, decisions=[dict(plan["decisions"][0], blocks=["missing"])]),
                       dict(plan, chains=[{"name": "x", "tasks": [self.night_task("a"), self.night_task("a")]}])):
            with self.assertRaises(core.FlowError):
                plans.validate_plan(broken)
        with self.assertRaisesRegex(core.FlowError, "not a valid plan"):
            plans.parse("I could not plan this.")
        text = plans.render("plan-20260926-231000-abcd", plan)
        for expected in ("需要你決定", "尚未決定", "主對話先做", "訂單：night-a → night-b", "decide plan-20260926-231000-abcd"):
            self.assertIn(expected, text)

    def test_plan_command_stores_the_planners_structured_plan(self):
        goal = Path(self.config_temp.name) / "goal.md"
        goal.write_text("訂單功能\n")
        reply = {"status": "ok", "text": json.dumps(self.sample_plan(), ensure_ascii=False), "session_id": "p",
                 "usage": None, "detail": ""}
        output = io.StringIO()
        with patch.object(cli.agents, "run_agent", return_value=reply) as agent, contextlib.redirect_stdout(output):
            cli.main(["--repo", str(self.repo), "plan", "--goal-file", str(goal)])
        self.assertIn("Return ONLY one JSON object", agent.call_args.args[1])
        plan_id = re.search(r"# 計畫 (plan-\S+)", output.getvalue()).group(1)
        self.assertEqual(plans.load(self.repo, plan_id)["goal"], "訂單功能")
        self.assertTrue((plans.directory(self.repo, plan_id) / "plan.md").is_file())

    def test_night_plan_waits_for_every_decision_then_preflights_and_runs(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        plan_id = plans.new_id()
        plans.save(self.repo, plan_id, self.sample_plan())
        errors = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(errors), patch.object(core.agents, "run_agent") as agent:
            cli.main(["--repo", str(self.repo), "night", "--plan", plan_id])
        self.assertIn("退款以哪個為準", errors.getvalue())
        agent.assert_not_called()
        self.assertEqual(core.list_runs(self.repo), [])
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["--repo", str(self.repo), "decide", plan_id, "1", "現有政策"])
        output = io.StringIO()
        with patch.object(core.agents, "run_agent", side_effect=self.night_agent()), contextlib.redirect_stdout(output):
            cli.main(["--repo", str(self.repo), "night", "--plan", plan_id, "--poll", "1"])
        text = output.getvalue()
        self.assertEqual(text.count("✓ 尚未通過（正常）"), 3)
        self.assertIn("已完成（3）", text)
        runs = {run["task"]["id"]: run for run in core.list_runs(self.repo)}
        self.assertEqual({run["status"] for run in runs.values()}, {"verified"})
        self.assertEqual(runs["night-b"]["depends_on"], runs["night-a"]["id"])
        self.assertIn("Decided: 退款以哪個為準？ -> 現有政策", runs["night-b"]["task"]["instructions"])
        self.assertNotIn("Decided", runs["night-a"]["task"]["instructions"])
        self.assertEqual([p.name for p in (self.repo / ".maf-worktrees").iterdir() if p.name.startswith("preflight-")], [])

    def test_preflight_flags_passing_and_broken_acceptance_commands(self):
        plan = self.sample_plan()
        plan["decisions"] = []
        plan["chains"] = [{"name": "檢查", "tasks": [
            dict(self.night_task("a"), tests=[[sys.executable, "-c", "pass"]]),
            dict(self.night_task("b"), tests=[["definitely-not-a-maf-command"]]),
            self.night_task("c")]}]
        results = {r["task"]: r["outcome"] for r in plans.preflight(self.repo, plan, 30)}
        self.assertEqual(results, {"night-a": "passes", "night-b": "cannot_run", "night-c": "fails"})
        self.assertIn("⚠ 已經通過", plans.render_preflight(plans.preflight(self.repo, plan, 30)))
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        plan_id = plans.new_id()
        plans.save(self.repo, plan_id, plan)
        errors = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["--repo", str(self.repo), "night", "--plan", plan_id])
        self.assertIn("無法執行", errors.getvalue())
        self.assertEqual(core.list_runs(self.repo), [])

    def test_chained_task_approval_waits_without_a_worktree(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        a = core.submit(self.repo, self.night_task("a"), kind="delegate")
        sensitive = dict(self.night_task("b", ["a"]), paths=["docs/auth.md"])
        b = core.submit(self.repo, sensitive, kind="delegate", depends_on=a["id"])
        self.assertEqual(b["status"], "awaiting_approval")
        b = core.approve(self.repo, b["id"])
        self.assertEqual(b["status"], "waiting_dependency")
        self.assertFalse(Path(b["worktree"]).exists())
        core.check_approval(b)
        with self.assertRaisesRegex(core.FlowError, "Only delegate"):
            core.submit(self.repo, self.night_task("v"), kind="verify", depends_on=a["id"])
        with self.assertRaises(core.FlowError):
            core.submit(self.repo, self.night_task("z"), kind="delegate", depends_on="night-missing-0123456789")

    def test_failed_external_verify_never_starts_a_coder(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        core.git(self.repo, "switch", "-c", "feature")
        (self.repo / "README.md").write_text("Still wrong\n")
        core.git(self.repo, "add", "README.md")
        core.git(self.repo, "commit", "-qm", "Claude implementation")
        run = core.submit(self.repo, self.task, kind="verify")
        with patch.object(core.agents, "run_agent") as agent:
            core.execute(self.repo, run)
        agent.assert_not_called()
        self.assertEqual(run["status"], "needs_human")
        self.assertEqual(run["stage"], "external_fix")
        with self.assertRaisesRegex(core.FlowError, "new verify"):
            core.resume(self.repo, run["id"], True)

    def test_cli_mode_override_and_worker_target_do_not_consume_other_tasks(self):
        def call(*args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--repo", str(self.repo), *args])
            return out.getvalue()
        result = json.loads(call("mode", "opus-sol"))
        self.assertEqual(result["mode"], "opus-sol")
        self.assertTrue(result["billing"])
        call("confirm-billing", "--no-overage")
        core.confirm_billing(self.repo, core.execution_config(self.repo, "economy")[1])
        other = core.submit(self.repo, self.task)
        task_file = self.repo / "task.json"
        core.atomic(task_file, self.task)
        run = json.loads(call("submit", str(task_file), "--mode", "economy"))
        self.assertEqual(run["mode"], "economy")
        with core.exclusive(self.repo):
            self.assertEqual(json.loads(call("mode"))["mode"], "opus-sol")
        with patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            call("work", "--once", "--run-id", run["id"])
        self.assertEqual(core.load(self.repo, run["id"])["status"], "tested")
        self.assertEqual(core.load(self.repo, other["id"])["status"], "queued")

    def test_unknown_modes_and_obsolete_billing_evidence_fail_closed(self):
        for value in ("unknown", {}, None):
            core.atomic(core.root_for(self.repo) / "mode.json", value)
            with self.subTest(value=value), self.assertRaises(core.FlowError):
                core.submit(self.repo, self.task)
        core.select_mode(self.repo, "configured")
        core.atomic(flows.home() / "billing.json", {"config_hash": core.digest(self.config)})
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, self.config)

    def test_runs_without_explicit_routing_cannot_replay_models(self):
        run = core.submit(self.repo, self.task)
        del run["mode"]
        with patch.object(core.agents, "run_agent") as agent, self.assertRaisesRegex(core.FlowError, "role routing"):
            core.execute(self.repo, run)
        agent.assert_not_called()

    def test_global_skill_registration_is_shared_and_idempotent(self):
        home = Path(self.config_temp.name) / "home"
        result = skills.install(home)
        self.assertEqual(skills.install(home), result)
        paths = [Path(p) for p in result["skills"]]
        self.assertEqual(paths[0].resolve(), paths[1].resolve())
        for path in paths:
            self.assertTrue((path / "SKILL.md").is_file())
            self.assertFalse(Path(os.readlink(path)).is_absolute())
            self.assertEqual((path / "SKILL.md").resolve().parents[2] / "flow.py",
                             Path(__file__).resolve().parents[1] / "flow.py")
        self.assertEqual(paths, [home / ".agents/skills/maf", home / ".claude/skills/maf"])
        for host in (".agents", ".claude"):
            self.assertTrue((home / host / "skills/maf-plan/SKILL.md").is_file())
        self.assertTrue((home / ".agents/skills/maf-plan/agents/openai.yaml").is_file())

    def test_planner_must_differ_from_main_chat(self):
        goal = Path(self.config_temp.name) / "goal.md"
        goal.write_text("Plan docs.\n")
        config = core.execution_config(self.repo, "quick", "claude")[1]
        with patch.object(cli.agents, "run_agent") as agent:
            with self.assertRaisesRegex(core.FlowError, "different runtime"):
                cli.plan(self.repo, config, goal, "codex")
        agent.assert_not_called()

    def test_skill_registration_refuses_conflicts_and_redirected_parents(self):
        home = Path(self.config_temp.name) / "home"
        folder = home / ".claude" / "skills" / "maf"
        folder.mkdir(parents=True)
        with self.assertRaises(core.FlowError):
            skills.install(home)
        self.assertFalse((home / ".agents").exists())
        folder.rmdir()
        redirected = home / ".agents"
        redirected.symlink_to(home / ".claude", target_is_directory=True)
        with self.assertRaises(core.FlowError):
            skills.install(home)
        self.assertFalse(folder.exists())

    def test_invalid_tasks(self):
        for field, value in [("id", "../escape"), ("paths", ["../a"]), ("paths", ["/tmp/a"]),
                             ("paths", [".git/config"]), ("tests", []), ("tests", ["pytest"]),
                             ("risk", "safe"), ("independent", "yes"), ("acceptance_why", " "),
                             ("acceptance_why", 1)]:
            with self.subTest(field=field, value=value):
                task = dict(self.task, **{field: value})
                with self.assertRaises(core.FlowError):
                    core.validate_task(task)
        with self.assertRaisesRegex(core.FlowError, "Only lightweight delegate"):
            core.submit(self.repo, dict(self.task, independent=True))

    def test_no_implicit_billing_approval(self):
        (flows.home() / "billing.json").unlink()
        run = core.submit(self.repo, self.task)
        with self.assertRaises(core.FlowError), patch.object(core.agents, "run_agent") as agent:
            core.execute(self.repo, run)
        agent.assert_not_called()

    def test_quota_does_not_retry_without_reset_acknowledgement(self):
        run = core.submit(self.repo, self.task)
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", return_value={"status": "quota", "text": "", "detail": "Limit reached"}) as agent:
            core.process(self.repo, run)
            core.work(self.repo, once=True)
            self.assertEqual(agent.call_count, 1)
        self.assertEqual(core.load(self.repo, run["id"])["status"], "waiting_quota")
        with self.assertRaises(core.FlowError):
            core.resume(self.repo, run["id"])
        result = core.resume(self.repo, run["id"], True, "2099-01-01T00:00:00+08:00")
        self.assertEqual(result["status"], "waiting_quota")

    def test_ambiguous_running_never_replayed(self):
        run = core.submit(self.repo, self.task)
        run["status"] = "running"
        core.save(self.repo, run)
        with patch.object(core.agents, "run_agent") as agent:
            core.work(self.repo, once=True)
        agent.assert_not_called()

    def test_reviewer_invalid_json_is_not_approval(self):
        run = core.submit(self.repo, self.task)
        def runner(role, *args):
            if role["access"] == "edit":
                return self.fake_agent(role, *args)
            return {"status": "ok", "text": "Looks fine", "detail": ""}
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=runner):
            core.process(self.repo, run)
        self.assertEqual(run["status"], "needs_human")
        self.assertNotIn("reviewed_sha", run)

    def test_scope_escape_is_blocked(self):
        run = core.submit(self.repo, self.task)
        (Path(run["worktree"]) / "outside.py").write_text("bad")
        with self.assertRaises(core.FlowError):
            core.check_scope(run)

    def test_symlink_is_blocked(self):
        run = core.submit(self.repo, self.task)
        path = Path(run["worktree"]) / "README.md"
        path.unlink()
        path.symlink_to(self.repo / "README.md")
        with self.assertRaises(core.FlowError):
            core.check_scope(run)

    def test_stale_sha_and_dirty_tree_are_blocked(self):
        run = self.complete()
        (Path(run["worktree"]) / "README.md").write_text("Another change")
        with self.assertRaises(core.FlowError):
            core.verified(self.repo, run)
        core.git(run["worktree"], "add", ".")
        core.git(run["worktree"], "commit", "-qm", "Later change")
        with self.assertRaises(core.FlowError):
            core.verified(self.repo, run)

    def test_policy_changes_invalidate_run(self):
        run = self.complete()
        self.config["auto_paths"]["style"] = ["*.css"]
        core.atomic(self.repo / ".maf.json", self.config)
        with self.assertRaises(core.FlowError):
            core.verified(self.repo, run)
        core.billing_check(self.repo, self.config)

    def test_repair_budget_is_bounded(self):
        self.task["tests"] = [[sys.executable, "-c", "raise SystemExit(1)"]]
        self.task["risk"] = "manual"
        run = core.submit(self.repo, self.task)
        run = core.approve(self.repo, run["id"])
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=self.fake_agent) as agent:
            core.process(self.repo, run)
        self.assertEqual(run["status"], "needs_human")
        self.assertIsNotNone(run["approval"]["approved_at"])
        self.assertEqual(agent.call_count, self.config["max_repairs"] + 1)

    def test_test_command_cannot_mutate_verified_tree(self):
        self.task["tests"] = [[sys.executable, "-c", "from pathlib import Path; Path('README.md').write_text('tamper')"]]
        run = core.submit(self.repo, self.task)
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            core.process(self.repo, run)
        self.assertEqual(run["status"], "needs_human")
        self.assertNotIn("tested_sha", run)

    def test_protected_files_override_allowlist(self):
        self.task["paths"] = ["AGENTS.md"]
        run = core.submit(self.repo, self.task)
        run["config"]["auto_paths"]["docs"] = ["*.md"]
        (Path(run["worktree"]) / "AGENTS.md").write_text("Disable safeguards")
        core.git(run["worktree"], "add", ".")
        core.git(run["worktree"], "commit", "-qm", "Add agent policy")
        run["tested_sha"] = core.git(run["worktree"], "rev-parse", "HEAD")
        run["review"] = {"risk": "low"}
        self.assertTrue(any("Protected" in reason for reason in github.risk_reasons(run)))

    def test_review_contract_stale_or_contradictory(self):
        base = {"decision": "approve", "head_sha": "a", "risk": "low", "summary": "ok", "findings": []}
        for value in [dict(base, head_sha="b"), dict(base, findings=["bug"]), dict(base, risk="safe")]:
            with self.assertRaises(core.FlowError):
                core.review_result(json.dumps(value), "a")

    def test_checks_fail_closed(self):
        for checks in (None, [], [{"status": "IN_PROGRESS"}], [{"status": "COMPLETED", "conclusion": "FAILURE"}]):
            self.assertFalse(github.checks_pass({"statusCheckRollup": checks}))
        self.assertTrue(github.checks_pass({"statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}]}))

    def test_publish_reconciles_existing_pr(self):
        run = self.complete()
        core.git(self.repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
        pr = {"number": 4, "url": "https://github.com/owner/repo/pull/4", "state": "OPEN",
              "headRefOid": run["tested_sha"], "baseRefName": "main"}
        calls = []
        def fake_gh(run, *args, **kwargs):
            calls.append(args)
            return [pr] if args[:2] == ("pr", "list") else pr
        original_git = core.git
        def fake_git(repo, *args):
            return "" if args[0] == "push" else original_git(repo, *args)
        with patch.object(github, "gh", side_effect=fake_gh), patch.object(github, "git", side_effect=fake_git), patch.object(github, "remote_base_matches"):
            github.publish(self.repo, run)
            github.publish(self.repo, run)
        self.assertFalse(any(args[:2] == ("pr", "create") for args in calls))
        self.assertEqual(run["pr"], 4)

    def test_merge_never_bypasses_missing_strict_checks(self):
        run = self.complete(publish=True, auto_merge=True)
        run["pr"] = 1
        core.git(self.repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
        pr = {"state": "OPEN", "headRefOid": run["tested_sha"], "baseRefName": "main", "isDraft": False,
              "statusCheckRollup": [{"state": "SUCCESS"}], "reviewDecision": "", "mergeStateStatus": "CLEAN"}
        with patch.object(github, "remote_base_matches"), patch.object(github, "gh", side_effect=[pr, {"strict": False, "contexts": ["test"]}]) as gh:
            with self.assertRaises(core.FlowError):
                github.merge(self.repo, run)
        self.assertFalse(any(call.args[1:3] == ("pr", "merge") for call in gh.call_args_list))

    def test_no_review_replay_after_publication_failure(self):
        run = self.complete()
        run.update(status="needs_human", stage="publishing")
        core.save(self.repo, run)
        with patch.object(core.agents, "run_agent") as agent, self.assertRaises(core.FlowError):
            core.resume(self.repo, run["id"], True)
        agent.assert_not_called()

    def test_unknown_stage_does_not_spin(self):
        run = core.submit(self.repo, self.task)
        run["stage"] = "unknown"
        core.process(self.repo, run)
        self.assertEqual(run["status"], "needs_human")

    def test_all_shipped_presets_validate(self):
        for preset in core.PRESETS:
            core.validate_config(self.repo, core.default_config(preset))
        invalid = core.default_config("economy")
        invalid["roles"]["reviewer"]["enabled"] = "yes"
        with self.assertRaises((core.FlowError, ValueError)):
            core.validate_config(self.repo, invalid)
        invalid = core.default_config("economy")
        invalid["roles"]["coder"]["enabled"] = True
        with self.assertRaises(core.FlowError):
            core.validate_config(self.repo, invalid)
        with self.assertRaises(core.FlowError):
            core.default_config("hermes")

    def test_dangling_symlink_blocked(self):
        run = core.submit(self.repo, self.task)
        path = Path(run["worktree"]) / "README.md"
        path.unlink()
        path.symlink_to(self.repo / "nonexistent")
        with self.assertRaises(core.FlowError):
            core.check_scope(run)

    def test_segment_globs_and_protected_plural_names(self):
        self.assertFalse(core.matches("docs/deep/a.md", ["docs/*.md"]))
        self.assertFalse(core.matches("src/README.md", ["README.md"]))
        self.assertTrue(core.matches("docs/deep/a.md", ["docs/**/*.md"]))
        self.assertTrue(core.matches("docs/a.md", ["docs/**/*.md"]))
        for name in ("secrets", "payments", "orders", "deployments", "policies"):
            self.assertIsNotNone(core.SENSITIVE_WORDS.search(f"docs/usage/{name}.md"))

    def test_corrupt_attestation_and_run_are_reported(self):
        core.atomic(flows.home() / "billing.json", None)
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, self.config)
        run = core.submit(self.repo, self.task)
        core.atomic(core.run_path(self.repo, run["id"]), None)
        self.assertEqual(core.list_runs(self.repo)[0]["status"], "corrupt")
        core.work(self.repo, once=True)

    def test_coder_commit_is_rejected_even_on_quota(self):
        run = core.submit(self.repo, self.task)
        def committing_coder(role, prompt, cwd, log, timeout):
            (cwd / "README.md").write_text("After")
            core.git(cwd, "add", ".")
            core.git(cwd, "commit", "-qm", "Unexpected commit")
            return {"status": "quota", "text": "", "detail": "Limit"}
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=committing_coder):
            core.process(self.repo, run)
        self.assertEqual(run["status"], "needs_human")
        self.assertIn("history", run["feedback"])

    def test_creating_checkpoint_can_recover_existing_pristine_worktree(self):
        run = core.submit(self.repo, self.task)
        run["status"] = "creating"
        core.save(self.repo, run)
        restored = core.resume(self.repo, run["id"], True)
        self.assertEqual(restored["status"], "queued")

    def test_merge_happy_path_exact_sha_and_no_admin(self):
        run = self.complete(publish=True, auto_merge=True)
        run["pr"] = 1
        core.git(self.repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
        pr = {"state": "OPEN", "headRefOid": run["tested_sha"], "baseRefName": "main", "isDraft": False,
              "statusCheckRollup": [{"state": "SUCCESS"}], "reviewDecision": "", "mergeStateStatus": "CLEAN"}
        with patch.object(github, "remote_base_matches"), patch.object(github, "gh", side_effect=[pr, {"strict": True, "contexts": ["test"]}, "", dict(pr, state="MERGED")]) as gh:
            github.merge(self.repo, run)
        merge_args = gh.call_args_list[2].args
        self.assertIn("--match-head-commit", merge_args)
        self.assertIn(run["tested_sha"], merge_args)
        self.assertNotIn("--admin", merge_args)
        self.assertEqual(run["status"], "merged")

    def test_unknown_mergeability_waits_without_agent(self):
        run = self.complete(publish=True, auto_merge=True)
        run.update(pr=1, status="pr", stage="pr")
        core.git(self.repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
        pr = {"state": "OPEN", "headRefOid": run["tested_sha"], "baseRefName": "main", "isDraft": False,
              "statusCheckRollup": [{"state": "SUCCESS"}], "reviewDecision": "", "mergeStateStatus": "UNKNOWN"}
        with patch.object(github, "remote_base_matches"), patch.object(github, "gh", side_effect=[pr, {"strict": True, "contexts": ["test"]}]), patch.object(core.agents, "run_agent") as agent:
            core.process(self.repo, run)
        agent.assert_not_called()
        self.assertEqual(run["status"], "pr")
        self.assertIn("next_check", run)


if __name__ == "__main__":
    unittest.main()
