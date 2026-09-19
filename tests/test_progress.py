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

from maf import cli, core, progress

TODO = ("# Todo\r\n\n- [x] Old work <!-- maf:old-task -->\n"
        "- [ ] Improve docs <!-- maf:improve-docs -->\n- [ ] Unrelated item\n\tindented\n")
MARKED = TODO.replace("- [ ] Improve docs", "- [x] Improve docs")


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        core.git(self.repo, "config", "user.email", "test@example.invalid")
        core.git(self.repo, "config", "user.name", "Flow Test")
        (self.repo / "README.md").write_text("Before\n")
        (self.repo / ".gitignore").write_text("__pycache__/\n.maf-local.json\n")
        self.todo = self.repo / "todo.md"
        self.todo.write_bytes(TODO.encode())
        self.commit("Initial")
        core.init(self.repo, "mixed")
        self.config = core.config_for(self.repo)
        core.atomic(self.repo / ".maf-local.json", {"subscription_only_confirmed": True, "config_hash": core.digest(self.config)})
        self.task = {"id": "improve-docs", "title": "Improve docs", "instructions": "Add usage paragraph.",
                     "paths": ["README.md"], "tests": [[sys.executable, "-c", "from pathlib import Path; assert 'After' in Path('README.md').read_text()"]],
                     "risk": "docs"}

    def commit(self, message):
        core.git(self.repo, "add", "--all")
        core.git(self.repo, "commit", "-qm", message)

    def fake_agent(self, role, prompt, cwd, log, timeout):
        if role["access"] == "edit":
            (cwd / "README.md").write_text("After\n")
            text = "Done"
        else:
            text = json.dumps({"decision": "approve", "head_sha": core.git(cwd, "rev-parse", "HEAD"),
                               "risk": "low", "summary": "Reviewed.", "findings": []})
        return {"status": "ok", "text": text, "session_id": "fake-" + role["runtime"], "usage": None, "detail": ""}

    def drive(self, run, method=core.process):
        with patch.object(core.agents, "doctor_role", return_value=[]), patch.object(core.agents, "run_agent", side_effect=self.fake_agent):
            method(self.repo, run)
        return run

    def verified_run(self):
        run = self.drive(core.submit(self.repo, self.task), core.execute)  # execute alone does not sync
        self.assertEqual(run["status"], "verified")
        self.assertEqual(self.todo.read_bytes(), TODO.encode())
        return run

    def output(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--repo", str(self.repo), *argv])
        return out.getvalue()

    def test_end_to_end_marks_root_checklist_only(self):
        run = core.submit(self.repo, self.task)
        self.assertEqual(run["checklist"], {"path": "todo.md", "line": "- [ ] Improve docs <!-- maf:improve-docs -->"})
        self.drive(run)
        self.assertEqual(run["status"], "verified")
        self.assertEqual(self.todo.read_bytes(), MARKED.encode())
        self.assertEqual((Path(run["worktree"]) / "todo.md").read_bytes(), TODO.encode())
        self.assertEqual(core.load(self.repo, run["id"])["checklist"]["synced"]["state"], "marked")
        self.assertIn("todo.md", core.git(self.repo, "status", "--porcelain"))
        with self.assertRaises(core.FlowError):  # Clean-tree rule is untouched: commit the projection first.
            core.submit(self.repo, dict(self.task, id="second"))
        self.commit("Record progress")
        self.assertNotIn("checklist", core.submit(self.repo, dict(self.task, id="second")))

    def test_no_mark_on_failure_or_stale_sha(self):
        self.task["tests"] = [[sys.executable, "-c", "raise SystemExit(1)"]]
        run = self.drive(core.submit(self.repo, self.task))
        self.assertEqual(run["status"], "needs_human")
        self.assertNotIn("synced", run["checklist"])
        self.assertEqual(self.todo.read_bytes(), TODO.encode())
        run["status"] = run["stage"] = "verified"  # A bare claim without evidence is still not projected.
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(progress.sync(self.repo, run), "failed")
        self.assertEqual(self.todo.read_bytes(), TODO.encode())

    def test_stale_sha_fails_closed_without_erasing_verified(self):
        run = self.verified_run()
        (Path(run["worktree"]) / "README.md").write_text("Later\n")
        core.git(run["worktree"], "commit", "-qam", "Later change")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(progress.sync(self.repo, run), "failed")
        self.assertIn("checklist not updated", err.getvalue())
        self.assertEqual(self.todo.read_bytes(), TODO.encode())
        saved = core.load(self.repo, run["id"])
        self.assertEqual((saved["status"], saved["stage"], saved["reviewed_sha"]), ("verified", "verified", run["tested_sha"]))
        self.assertEqual(saved["checklist"]["synced"]["state"], "failed")

    def test_sync_is_idempotent_and_recoverable(self):
        run = self.verified_run()
        self.assertEqual(progress.sync(self.repo, run), "marked")
        self.assertEqual(progress.sync(self.repo, run), "already")
        del run["checklist"]["synced"]  # Crash between todo write and state save.
        core.save(self.repo, run)
        with core.exclusive(self.repo):
            progress.sync_all(self.repo)
        self.assertEqual(core.load(self.repo, run["id"])["checklist"]["synced"]["state"], "already")
        self.assertEqual(self.todo.read_bytes(), MARKED.encode())
        self.assertIn("already", self.output(["progress", "--sync"]))

    def test_user_edits_preserved_and_conflicts_fail_closed(self):
        run = self.verified_run()
        edited = TODO.replace("- [ ] Unrelated item", "- [x] Unrelated item\n- [ ] New line <!-- maf:other -->")
        self.todo.write_bytes(edited.encode())
        self.commit("User edits")
        self.assertEqual(progress.sync(self.repo, run), "marked")
        self.assertEqual(self.todo.read_bytes(), edited.replace("- [ ] Improve docs", "- [x] Improve docs").encode())
        for content in (edited.replace("Improve docs <!--", "Improve the docs <!--"),
                        edited.replace("- [ ] Unrelated item", "- [ ] Improve docs <!-- maf:improve-docs -->")):
            self.todo.write_bytes(content.encode())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(progress.sync(self.repo, run), "failed")
            self.assertEqual(self.todo.read_bytes(), content.encode())
            self.assertEqual(core.load(self.repo, run["id"])["status"], "verified")

    def test_symlink_duplicate_untracked_and_scope_rejected(self):
        with self.assertRaises(core.FlowError):
            core.submit(self.repo, dict(self.task, paths=["*.md"]))
        run = self.verified_run()  # Snapshotted while todo.md was still a tracked regular file.
        self.todo.write_bytes(TODO.replace("- [ ] Unrelated item", "- [ ] Improve docs <!-- maf:improve-docs -->").encode())
        self.commit("Duplicate marker")
        with self.assertRaises(core.FlowError):
            core.submit(self.repo, self.task)
        core.git(self.repo, "rm", "-q", "--cached", "todo.md")
        self.commit("Untracked todo")
        with self.assertRaises(core.FlowError):
            core.submit(self.repo, self.task)
        self.todo.unlink()
        (self.repo / "real.md").write_bytes(TODO.encode())
        self.todo.symlink_to("real.md")
        self.commit("Symlinked todo")
        with self.assertRaises(core.FlowError):
            core.submit(self.repo, self.task)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(progress.sync(self.repo, run), "failed")  # Refused at write time too.
        self.assertTrue(self.todo.is_symlink())
        self.assertEqual((self.repo / "real.md").read_bytes(), TODO.encode())

    def test_progress_is_read_only_and_needs_no_lock(self):
        run = core.submit(self.repo, self.task)
        core.atomic(core.run_path(self.repo, "broken-1234"), None)
        state = core.run_path(self.repo, run["id"])
        before = state.read_bytes()
        with core.exclusive(self.repo), patch.object(core.agents, "run_agent") as agent:
            text = self.output(["progress"])
            with self.assertRaises(SystemExit):
                self.output(["progress", "--sync"])
        agent.assert_not_called()
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(self.todo.read_bytes(), TODO.encode())
        self.assertIn("corrupt", text)
        self.assertIn("pending", text)
        self.assertIn("not merged", text)
        self.assertEqual(self.drive(run)["status"], "verified")
        text = self.output(["progress"])
        self.assertRegex(text, r"verified\s+" + run["tested_sha"][:7] + r"\s+" + run["tested_sha"][:7] + r"\s+yes\s+no\s+marked")

    def test_terminal_output_is_sanitized(self):
        self.task.update(id="evil", title="Evil \x1b[2J\x1b]0;x\x07 title\r\n  done")
        run = core.submit(self.repo, self.task)
        run.update(status="needs_human", feedback="bad \x1b[31mred\x1b[0m \x07 news")
        core.save(self.repo, run)
        text = progress.render(progress.rows(self.repo)) + progress.title_for(progress.rows(self.repo))
        for char in ("\x1b", "\x07", "\r", " "):
            self.assertNotIn(char, text)
        self.assertIn("Evil ?", text)
        self.assertIn("news", text)

    def test_watch_prints_only_changes_and_exits_cleanly(self):
        run = core.submit(self.repo, self.task)
        def sleeper(seconds):
            sleeper.calls += 1
            self.assertEqual(seconds, 2)
            if sleeper.calls == 2:
                run["status"] = "needs_human"
                core.save(self.repo, run)
            if sleeper.calls == 3:
                raise KeyboardInterrupt
        sleeper.calls = 0
        with patch.object(progress.time, "sleep", side_effect=sleeper):
            text = self.output(["progress", "--watch", "--poll", "2"])
        self.assertEqual(text.count("--- "), 2)
        self.assertEqual(sleeper.calls, 3)
        with self.assertRaises(SystemExit):
            self.output(["progress", "--watch", "--poll", "0"])

    def test_herdr_pane_metadata_is_explicit_and_refreshed(self):
        core.submit(self.repo, self.task)
        original, calls = core.command, []
        def fake(argv, cwd, **kwargs):
            if argv[0] == "herdr":
                calls.append(argv)
                return "{}"
            return original(argv, cwd, **kwargs)
        with patch.dict(os.environ, {"HERDR_ENV": "0"}), self.assertRaises(core.FlowError):
            progress.show(self.repo, pane="pane-1")
        with patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(core, "command", side_effect=fake):
            with self.assertRaises(core.FlowError):
                progress.show(self.repo, pane="--pane")
            with patch.object(progress.time, "sleep", side_effect=[None, KeyboardInterrupt]):
                self.output(["progress", "--watch", "--planner-pane", "pane-1"])
        self.assertEqual(calls[0], ["herdr", "pane", "get", "pane-1"])
        reports = [argv for argv in calls if argv[:3] == ["herdr", "pane", "report-metadata"]]
        self.assertEqual(len(reports), 2)  # Unchanged display still renews the TTL every poll.
        self.assertEqual(reports[0][3:7], ["pane-1", "--source", "maf-progress", "--title"])
        self.assertEqual(reports[0][8:], ["--ttl-ms", "15000"])
        self.assertIn("1 queued", reports[0][7])
        self.assertFalse(any("input" in argv or "send" in argv or "kill" in argv for argv in calls))


if __name__ == "__main__":
    unittest.main()
