import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from maf import cli, core, flows, github, skills


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
        core.init(self.repo, "economy")
        self.config = core.config_for(self.repo)
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

    def test_pi_default_and_manual_review_use_separate_sessions(self):
        self.assertEqual(self.config["roles"]["coder"]["runtime"], "pi")
        self.assertEqual(self.config["max_repairs"], 1)
        self.task["risk"] = "manual"
        self.task["tests"][0][-1] += "; print('NOISY_TEST_OUTPUT')"
        run = core.submit(self.repo, self.task)
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
        core.billing_check(self.repo, self.config)  # Confirming one mode does not revoke another.
        core.select_mode(self.repo, "economy")
        with patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            core.execute(self.repo, old)
            core.execute(self.repo, new)
        self.assertEqual([a["runtime"] for a in old["agents"]], ["pi", "pi"])
        self.assertEqual([a["model"] for a in new["agents"]], ["claude-opus-5-5", "gpt-6-sol"])
        self.assertEqual(new["mode"], "opus-sol")
        core.verified(self.repo, old)
        core.verified(self.repo, new)
        self.config["test_timeout"] += 1
        core.atomic(self.repo / ".maf.json", self.config)
        with self.assertRaises(core.FlowError):
            core.verified(self.repo, new)
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, core.execution_config(self.repo, "opus-sol")[1])

    def test_named_flow_selects_models_without_changing_project_policy(self):
        before = (self.repo / ".maf.json").read_bytes()
        flow = flows.templates()["quick"]
        flow["roles"]["coder"]["effort"] = "high"
        flows.save(self.repo, "my-flow", flow)
        core.select_mode(self.repo, "my-flow")
        self.assertEqual(core.execution_config(self.repo)[1]["roles"]["coder"]["effort"], "high")
        self.assertEqual((self.repo / ".maf.json").read_bytes(), before)
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, core.execution_config(self.repo)[1])
        with self.assertRaises(core.FlowError):
            flows.save(self.repo, "bad", dict(flow, roles={"coder": {}}))

    def test_current_model_suggestions_allow_deeper_codex_effort_but_not_pi(self):
        flow = flows.templates()["quick"]
        flow["main"]["effort"] = "max"
        flow["roles"]["reviewer"]["effort"] = "xhigh"
        flows.save(self.repo, "deep-review", flow)
        flow["roles"]["coder"]["effort"] = "xhigh"
        with self.assertRaises(ValueError):
            flows.save(self.repo, "invalid-pi-effort", flow)

    def test_claude_commit_verify_and_pi_delegate_bind_exact_sha(self):
        core.git(self.repo, "add", ".maf.json")
        core.git(self.repo, "commit", "-qm", "Configure MAF")
        core.git(self.repo, "switch", "-c", "feature")
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
        other = core.submit(self.repo, self.task)
        task_file = self.repo / "task.json"
        core.atomic(task_file, self.task)
        run = json.loads(call("submit", str(task_file), "--mode", "economy"))
        self.assertEqual(run["mode"], "economy")
        with core.exclusive(self.repo):
            self.assertEqual(json.loads(call("mode"))["mode"], "opus-sol")
        with patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            call("work", "--once", "--run-id", run["id"])
        self.assertEqual(core.load(self.repo, run["id"])["status"], "verified")
        self.assertEqual(core.load(self.repo, other["id"])["status"], "queued")

    def test_unknown_modes_and_obsolete_billing_evidence_fail_closed(self):
        for value in ("unknown", {}, None):
            core.atomic(core.root_for(self.repo) / "mode.json", value)
            with self.subTest(value=value), self.assertRaises(core.FlowError):
                core.submit(self.repo, self.task)
        core.select_mode(self.repo, "configured")
        core.atomic(self.repo / ".maf-local.json", {"subscription_only_confirmed": True,
                                                   "config_hash": core.digest(self.config)})
        with self.assertRaises(core.FlowError):
            core.billing_check(self.repo, self.config)

    def test_runs_without_explicit_routing_cannot_replay_models(self):
        run = core.submit(self.repo, self.task)
        del run["mode"]
        with patch.object(core.agents, "run_agent") as agent, self.assertRaisesRegex(core.FlowError, "role routing"):
            core.execute(self.repo, run)
        agent.assert_not_called()

    def test_project_skill_registration_is_shared_idempotent_and_excluded(self):
        result = skills.install(self.repo)
        self.assertEqual(skills.install(self.repo), result)
        paths = [Path(p) for p in result["skills"]]
        self.assertEqual(paths[0].resolve(), paths[1].resolve())
        for path in paths:
            self.assertTrue((path / "SKILL.md").is_file())
            self.assertFalse(Path(os.readlink(path)).is_absolute())
            self.assertEqual((path / "SKILL.md").resolve().parents[2] / "flow.py",
                             Path(__file__).resolve().parents[1] / "flow.py")
            core.git(self.repo, "check-ignore", str(path))

    def test_skill_registration_refuses_conflicts_and_redirected_parents(self):
        folder = self.repo / ".claude" / "skills" / "maf"
        folder.mkdir(parents=True)
        with self.assertRaises(core.FlowError):
            skills.install(self.repo)
        self.assertFalse((self.repo / ".agents").exists())
        folder.rmdir()
        redirected = self.repo / ".agents"
        redirected.symlink_to(self.repo / ".claude", target_is_directory=True)
        with self.assertRaises(core.FlowError):
            skills.install(self.repo)
        self.assertFalse(folder.exists())

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
        for preset in core.PRESETS:
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
