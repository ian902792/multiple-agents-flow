import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from maf import cli, core, flows, progress

TODO = ("# Todo\r\n\n- [x] Old work <!-- maf:old-task -->\n"
        "- [ ] Improve docs <!-- maf:improve-docs -->\n- [ ] Unrelated item\n\tindented\n")
MARKED = TODO.replace("- [ ] Improve docs", "- [x] Improve docs")


class ProgressTests(unittest.TestCase):
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
        self.todo = self.repo / "todo.md"
        self.todo.write_bytes(TODO.encode())
        self.commit("Initial")
        core.init(self.repo, "economy")
        core.select_mode(self.repo, "configured")
        self.config = core.config_for(self.repo)
        core.confirm_billing(self.repo, self.config)
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
        for content in (edited.replace("Improve docs <!--", "Improve the docs <!--"),  # edited line
                        edited.replace("New line <!-- maf:other -->", "Improve docs <!-- maf:improve-docs -->")):  # duplicate
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
        self.todo.write_bytes(TODO.encode())
        core.git(self.repo, "rm", "-q", "--cached", "todo.md")
        core.git(self.repo, "commit", "-qm", "Untracked todo")  # File stays on disk but is no longer tracked.
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
        self.assertEqual(progress.clean("normal spaces\u2028next\u2029end"), "normal spaces?next?end")
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
        with patch.object(progress, "sleep", side_effect=sleeper):
            text = self.output(["progress", "--watch", "--poll", "2"])
        self.assertEqual(text.count("--- "), 2)
        self.assertEqual(sleeper.calls, 3)
        with self.assertRaises(SystemExit):
            self.output(["progress", "--watch", "--poll", "0"])

    def test_main_task_snapshot_reports_deadlines_blockers_and_usage_without_transcripts(self):
        run = core.submit(self.repo, self.task)
        run.update(status="running", activity={"label": "coder: pi/deepseek-v4.1-flash", "started_at": 100,
                                               "timeout": 120, "log": "/tmp/agent.log"})
        core.save(self.repo, run)
        before = core.run_path(self.repo, run["id"]).read_bytes()
        with patch.object(progress.time, "time", return_value=180), patch.object(core.agents, "run_agent") as agent:
            snapshot = json.loads(self.output(["progress", "--json"]))[0]
        self.assertEqual(snapshot["elapsed"], "1m/2m")
        self.assertFalse(snapshot["attention"])
        self.assertNotIn("instructions", snapshot)
        agent.assert_not_called()
        with patch.object(progress.time, "time", return_value=240):
            row = progress.rows(self.repo)[0]
        self.assertTrue(row["attention"])
        self.assertIn("Deadline exceeded", row["next"])
        self.assertIn("attention", progress.title_for([row]))
        self.assertEqual(core.run_path(self.repo, run["id"]).read_bytes(), before)
        run.update(status="needs_human", agents=[{"role": "coder", "runtime": "pi", "model": "deepseek-v4.1-flash",
                                                "status": "blocked", "usage": {"input": 10, "output": 2}}])
        core.save(self.repo, run)
        row = json.loads(self.output(["progress", "--json"]))[0]
        self.assertIn("login/permissions", row["next"])
        self.assertIn("--acknowledge-stopped", row["next"])
        self.assertEqual(row["agents"][0]["usage"], {"input": 10, "output": 2})
        run["repairs"] = run["config"]["max_repairs"] + 1
        self.assertIn("Repair budget exhausted", progress.row_for(self.repo, run)["next"])
        run.update(status="waiting_quota", not_before=None)
        self.assertTrue(progress.row_for(self.repo, run)["attention"])
        run["not_before"] = 4070880000
        self.assertFalse(progress.row_for(self.repo, run)["attention"])
        for flag in ("--sync", "--watch", "--planner-pane=x"):
            with self.assertRaises(SystemExit):
                self.output(["progress", "--json", flag])
        run["config_hash"] = "changed"
        row = progress.row_for(self.repo, run)
        self.assertTrue(row["attention"])
        self.assertIn("Do not resume/publish", row["next"])

    def test_herdr_launch_reports_to_inherited_main_pane(self):
        calls = []
        def command(argv, *_args, **_kwargs):
            calls.append(argv)
            if argv[:3] == ["herdr", "workspace", "create"]:
                return json.dumps({"result": {"root_pane": {"pane_id": "w2:p2"}, "workspace": {"workspace_id": "w2"}}})
            return "{}"
        with patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1"}), patch.object(core, "command", side_effect=command):
            with self.assertRaisesRegex(core.FlowError, "integration is off"):
                cli.launch_herdr(self.repo)
            self.assertEqual(calls, [])
            flows.set_herdr(True)
            result = cli.launch_herdr(self.repo)
        self.assertEqual(result["planner_pane"], "w1:p1")
        self.assertEqual(calls[0], ["herdr", "pane", "get", "w1:p1"])
        launch = calls[-1]
        self.assertEqual(launch[:4], ["herdr", "pane", "run", "w2:p2"])
        self.assertEqual(shlex.split(launch[-1])[-4:], ["work", "--planner-pane", "w1:p1", "--agent-panes"])
        self.assertIn("--no-focus", calls[-2])
        with patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_PANE_ID": ""}), patch.object(core, "command") as command:
            with self.assertRaises(core.FlowError):
                cli.launch_herdr(self.repo)
        command.assert_not_called()

    def test_agent_pane_shows_live_log_and_closes_only_its_own_pane(self):
        flows.set_herdr(True)
        calls = []
        def command(argv, *_args, **_kwargs):
            calls.append(argv)
            if argv[:3] == ["herdr", "pane", "split"]:
                splits = sum(call[:3] == ["herdr", "pane", "split"] for call in calls)
                return json.dumps({"result": {"pane": {"pane_id": f"w1:p{splits + 1}"}}})
            return "{}"
        live = core.run_path(self.repo, "sample-run").parent / "coder.live"
        other_live = core.run_path(self.repo, "other-run").parent / "coder.live"
        with patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1"}), \
                patch.object(core, "command", side_effect=command):
            with progress.agent_pane(self.repo, "MAF coder", self.repo, live, True) as pane:
                self.assertEqual(pane, "w1:p2")
                self.assertTrue(live.exists())
                with progress.agent_pane(self.repo, "MAF other coder", self.repo, other_live, True) as other:
                    self.assertEqual(other, "w1:p3")
                    self.assertTrue(other_live.exists())
        self.assertEqual(calls[0], ["herdr", "pane", "get", "w1:p1"])
        self.assertEqual(calls[1][:5], ["herdr", "pane", "split", "w1:p1", "--direction"])
        self.assertIn("--no-focus", calls[1])
        self.assertEqual(calls[2][:4], ["herdr", "pane", "rename", "w1:p2"])
        self.assertEqual(calls[3][:4], ["herdr", "pane", "run", "w1:p2"])
        self.assertEqual(shlex.split(calls[3][-1])[-2:], ["live-view", str(live)])
        self.assertEqual([call for call in calls if call[:3] == ["herdr", "pane", "close"]],
                         [["herdr", "pane", "close", "w1:p3"], ["herdr", "pane", "close", "w1:p2"]])
        self.assertFalse(any(argv[-1] == "w1:p1" for argv in calls if argv[:3] == ["herdr", "pane", "close"]))

    def test_live_event_shows_status_without_agent_content(self):
        event = json.dumps({"type": "item.started", "item": {"type": "command_execution", "name": "Read",
                                                         "text": "private prompt"}, "status": "running"}).encode()
        self.assertEqual(progress.live_event(event), "item.started command_execution Read running")
        self.assertEqual(progress.live_event(b"secret stderr text\n"), "unstructured output")
        self.assertEqual(progress.live_event(b'{"type":"result","subtype":"success","result":"private"}'),
                         "result success")
        self.assertEqual(progress.live_event(b'{"type":"assistant","message":{"content":['
                                             b'{"type":"tool_use","name":"Read","input":{"secret":"private"}}]}}'),
                         "assistant Read")

    def test_main_pane_monitor_runs_during_work_and_stops_on_failure(self):
        started, finished = threading.Event(), threading.Event()
        def watcher(*_args, **kwargs):
            started.set()
            kwargs["stop"].wait(3)
            if kwargs["stop"].is_set():
                finished.set()
        with patch.object(progress, "check_pane"), patch.object(progress, "show", side_effect=watcher):
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                with progress.monitor(self.repo, "w1:p1"):
                    self.assertTrue(started.wait(1))
                    raise RuntimeError("worker failed")
        self.assertTrue(finished.wait(1))

    def test_monitor_reports_final_snapshot_when_stopped(self):
        run = core.submit(self.repo, self.task)
        stop = threading.Event()
        def finish(_poll):
            run["status"] = "needs_human"
            core.save(self.repo, run)
            stop.set()
        with patch.object(stop, "wait", side_effect=finish), patch.object(progress, "check_pane"), \
                patch.object(progress, "report_pane") as report, contextlib.redirect_stdout(io.StringIO()):
            progress.show(self.repo, watch=True, pane="w1:p1", stop=stop)
        self.assertEqual(report.call_count, 2)
        self.assertIn("needs_human", report.call_args.args[2])

    def test_herdr_pane_metadata_is_explicit_and_refreshed(self):
        core.submit(self.repo, self.task)
        flows.set_herdr(True)
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
            with patch.object(progress, "sleep", side_effect=[None, KeyboardInterrupt]):
                self.output(["progress", "--watch", "--planner-pane", "pane-1"])
        self.assertEqual(calls[0], ["herdr", "pane", "get", "pane-1"])
        reports = [argv for argv in calls if argv[:3] == ["herdr", "pane", "report-metadata"]]
        self.assertEqual(len(reports), 2)  # Unchanged display still renews the TTL every poll.
        self.assertEqual(reports[0][3:7], ["pane-1", "--source", "maf-progress", "--title"])
        self.assertEqual(reports[0][8:], ["--ttl-ms", "20000"])
        self.assertIn("0/1 verified", reports[0][7])
        self.assertIn("queued coding improve-docs", reports[0][7])
        self.assertFalse(any("input" in argv or "send" in argv or "kill" in argv for argv in calls))
        flows.set_herdr(False)
        with patch.object(core, "command") as command, self.assertRaisesRegex(core.FlowError, "integration is off"):
            progress.report_pane(self.repo, "pane-1", "status")
        command.assert_not_called()

    def test_duplicate_id_with_different_description(self):
        run = self.verified_run()
        for original in (TODO, MARKED):
            for extra in ("- [ ] Different", "- [x] Different", "Plain text"):
                content = original + extra + " <!-- maf:improve-docs -->\n"
                self.todo.write_bytes(content.encode())
                with self.assertRaises(core.FlowError):
                    progress.project(self.repo, run)
                self.assertEqual(self.todo.read_bytes(), content.encode())

    def test_projection_rechecks_tracking_and_base(self):
        run = self.verified_run()
        core.git(self.repo, "checkout", "-qb", "other")
        with self.assertRaises(core.FlowError):
            progress.project(self.repo, run)
        core.git(self.repo, "checkout", "main")
        core.git(self.repo, "rm", "--cached", "todo.md")
        with self.assertRaises(core.FlowError):
            progress.project(self.repo, run)
        self.assertEqual(self.todo.read_bytes(), TODO.encode())

    def test_projection_detects_changes_during_temp_flush(self):
        run = self.verified_run()
        for replacement in (False, True):
            self.todo.write_bytes(TODO.encode())
            def edit(_fd):
                if replacement:
                    other = self.repo / "replacement.md"
                    other.write_bytes(TODO.encode())
                    os.replace(other, self.todo)
                else:
                    self.todo.write_bytes((TODO + "User edit\n").encode())
            with patch.object(progress.os, "fsync", side_effect=edit), self.assertRaises(core.FlowError):
                progress.project(self.repo, run)
            expected = TODO if replacement else TODO + "User edit\n"
            self.assertEqual(self.todo.read_bytes(), expected.encode())
            self.assertEqual(list(self.repo.glob(".tmp-todo-*")), [])

    def test_completed_publish_stops_remain_verified(self):
        run = self.verified_run()
        run["status"] = "needs_human"
        for stage in ("verified", "publishing", "pr", "merging", "merged"):
            run["stage"] = stage
            self.assertEqual(progress.row_for(self.repo, run)["verified"], "yes")
            self.assertIn(progress.sync(self.repo, run), ("marked", "already"))
        for stage in ("coding", "testing", "reviewing"):
            run["stage"] = stage
            self.assertEqual(progress.sync(self.repo, run), "pending")
            self.assertEqual(progress.row_for(self.repo, run)["verified"], "no")

    def test_display_checks_real_evidence_without_writes(self):
        run = self.verified_run()
        state = core.run_path(self.repo, run["id"])
        before = state.read_bytes()
        for change in ({"tests": [{}]}, {"tests": []},
                       {"tests": [dict(run["tests"][0], exit_code=1)]},
                       {"tests": [dict(run["tests"][0], argv=["wrong-command"])]},
                       {"review": dict(run["review"], risk="invalid")},
                       {"review": dict(run["review"], findings=["fix this"])},
                       {"reviewed_sha": "stale"}):
            self.assertEqual(progress.row_for(self.repo, dict(run, **change))["verified"], "no")
        with patch.object(core.agents, "run_agent") as agent:
            (Path(run["worktree"]) / "README.md").write_text("Dirty\n")
            self.assertEqual(progress.rows(self.repo)[0]["verified"], "no")
        agent.assert_not_called()
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(self.todo.read_bytes(), TODO.encode())

    def test_sync_timeout_and_save_error_preserve_evidence(self):
        run = self.verified_run()
        before = copy.deepcopy(run)
        err = io.StringIO()
        with patch.object(core, "verified", side_effect=subprocess.TimeoutExpired("git\x1b\u2028", 60)), \
                patch.object(core, "save", side_effect=OSError("disk\x1b\u2029 full")), contextlib.redirect_stderr(err):
            self.assertEqual(progress.sync(self.repo, run), "failed")
        for key in ("status", "stage", "tests", "review", "tested_sha", "reviewed_sha"):
            self.assertEqual(run[key], before[key])
        self.assertIn("outcome not saved", err.getvalue())
        for char in ("\x1b", "\u2028", "\u2029"):
            self.assertNotIn(char, err.getvalue())
        with patch.object(core, "save", side_effect=OSError("disk full")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(progress.sync(self.repo, run), "marked")
        self.assertEqual(self.todo.read_bytes(), MARKED.encode())
        saved = core.load(self.repo, run["id"])
        for key in ("status", "stage", "tests", "review", "tested_sha", "reviewed_sha"):
            self.assertEqual(saved[key], before[key])

    def test_compact_38_columns_and_long_poll(self):
        run = core.submit(self.repo, self.task)
        rows = progress.rows(self.repo)
        with patch.object(progress.shutil, "get_terminal_size", return_value=os.terminal_size((38, 24))), \
                patch.object(progress.sys.stdout, "isatty", return_value=True):
            self.assertTrue(progress.compact())
            self.assertTrue(all(len(line) <= 38 for line in progress.render(rows, True).splitlines()))
        with patch.object(progress.sys.stdout, "isatty", return_value=False):
            self.assertFalse(progress.compact())
        self.assertIn("CHECKLIST", progress.render(rows))
        self.assertGreater(progress.ttl_for(60), 60000)
        self.assertIn(run["task"]["id"], progress.title_for(rows))

    def test_disappearing_pane_warns_and_returns(self):
        with patch.object(progress, "rows", return_value=[]), \
                patch.object(progress, "check_pane", side_effect=[None, core.FlowError("gone")]), \
                patch.object(progress, "report_pane", side_effect=subprocess.TimeoutExpired("herdr", 15)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            progress.show(self.repo, pane="pane-1", poll=60)
        self.assertIn("continuing without pane metadata", err.getvalue())


if __name__ == "__main__":
    unittest.main()
