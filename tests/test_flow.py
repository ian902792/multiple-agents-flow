import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from maf import core, github


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        core.git(self.repo, "config", "user.email", "test@example.invalid")
        core.git(self.repo, "config", "user.name", "Flow Test")
        (self.repo / "README.md").write_text("Before\n")
        (self.repo / ".gitignore").write_text("__pycache__/\n.maf-local.json\n")
        core.git(self.repo, "add", ".")
        core.git(self.repo, "commit", "-qm", "Initial")
        core.init(self.repo, "mixed")
        self.config = core.config_for(self.repo)
        core.atomic(self.repo / ".maf-local.json", {"subscription_only_confirmed": True, "config_hash": core.digest(self.config)})
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

    def test_invalid_tasks(self):
        for field, value in [("id", "../escape"), ("paths", ["../a"]), ("paths", ["/tmp/a"]),
                             ("paths", [".git/config"]), ("tests", []), ("tests", ["pytest"]), ("risk", "safe")]:
            with self.subTest(field=field, value=value):
                task = dict(self.task, **{field: value})
                with self.assertRaises(core.FlowError):
                    core.validate_task(task)

    def test_no_implicit_billing_approval(self):
        (self.repo / ".maf-local.json").unlink()
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
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, self.config)

    def test_repair_budget_is_bounded(self):
        self.task["tests"] = [[sys.executable, "-c", "raise SystemExit(1)"]]
        run = core.submit(self.repo, self.task)
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=self.fake_agent) as agent:
            core.process(self.repo, run)
        self.assertEqual(run["status"], "needs_human")
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
        for preset in ("mixed", "hermes-coder"):
            core.validate_config(self.repo, core.default_config(preset))
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
            self.assertIsNotNone(github.PROTECTED_WORDS.search(f"docs/usage/{name}.md"))

    def test_corrupt_attestation_and_run_are_reported(self):
        core.atomic(self.repo / ".maf-local.json", None)
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
