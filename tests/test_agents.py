import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from maf import agents

CODEX = {"runtime": "codex", "provider": "chatgpt", "model": "gpt-6-astra", "access": "read"}
CLAUDE = {"runtime": "claude", "provider": "claude-subscription", "model": "claude-opus-5", "access": "edit"}
PI = {"runtime": "pi", "provider": "opencode-go", "model": "deepseek-v4.1-flash", "access": "read"}
HERMES = {"runtime": "hermes", "provider": "opencode-go", "model": "glm-5.3", "access": "edit", "profile": "coder"}
FORBIDDEN = {"--yolo", "--dangerously-skip-permissions", "danger-full-access", "--bare", "--api-key",
             "bypassPermissions", "--approve", "-a"}
AUTH_OK = {"codex": "Logged in using ChatGPT\n",
           "claude": json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}),
           "pi": json.dumps({"status": "ready", "provider": "opencode-go"}),
           "hermes": "opencode-go: logged in\n"}


def jl(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


class FakeExec:
    """Records calls; first call answers the auth check, second the agent run."""

    def __init__(self, auth_out, run=(0, "", "", False)):
        self.auth_out, self.run, self.calls = auth_out, run, []

    def __call__(self, argv, *, stdin, timeout, cwd=None, on_start=None):
        self.calls.append({"argv": list(argv), "stdin": stdin, "timeout": timeout, "cwd": cwd})
        if on_start:
            on_start(4242)
        if isinstance(self.run, BaseException) and len(self.calls) > 1:
            raise self.run
        return (0, self.auth_out, "", False) if len(self.calls) == 1 else self.run


class RoleValidation(unittest.TestCase):
    def test_valid_roles_and_configurable_models(self):
        for role in (CODEX, CLAUDE, PI, HERMES, dict(CODEX, model="gpt-5.5-codex"), dict(CLAUDE, model="claude-sonnet-5"),
                     dict(PI, model="glm-5.3", effort="high")):
            agents.validate_role(role)

    def test_rejections(self):
        bad = [
            dict(CODEX, model=""), dict(CLAUDE, model=None), dict(CODEX, provider="openai"), dict(PI, provider="opencode-zen"),
            dict(HERMES, access="read"), dict(CODEX, extra_args=["--yolo"]), dict(CODEX, endpoint="x"),
            dict(PI, model="--api-key"), dict(PI, model="m; rm -rf /"), dict(CODEX, access="yolo"),
            dict(HERMES, profile="../x"), dict(CODEX, profile="p"), dict(CODEX, runtime="opencode"), "codex",
            dict(PI, model="openai/gpt-6-astra"), dict(PI, model="glm-5.3:high"),
            dict(PI, model="deepseek-v4.1-flash\n"), dict(PI, effort="unlimited"),
        ]
        for role in bad:
            with self.subTest(role=role), self.assertRaises(ValueError):
                agents.validate_role(role)

    def test_doctor_reports_validation_problem_only(self):
        self.assertEqual(len(agents.doctor_role(dict(HERMES, access="read"))), 1)
        self.assertIn("read-only", agents.doctor_role(dict(HERMES, access="read"))[0])
        self.assertEqual(agents._argv(dict(CODEX, model="gpt-5.5-codex"), 9)[agents._argv(CODEX, 9).index("-m") + 1], "gpt-5.5-codex")


class Environment(unittest.TestCase):
    def test_clean_env_scrubs_overrides(self):
        dirty = {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "u", "OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "u",
                 "OPENCODE_GO_API_KEY": "k", "CLAUDECODE": "1", "CLAUDE_CODE_USE_BEDROCK": "1",
                 "FOO_API_KEY": "k", "BAR_BASE_URL": "u", "PI_API_KEY": "k", "HERMES_KANBAN_TASK": "1",
                 "HERMES_YOLO": "1", "HERMES_HOME": "/h/.hermes", "PATH": "/bin", "HOME": "/h"}
        with mock.patch.dict(os.environ, dirty, clear=True):
            env = agents.clean_env()
        self.assertEqual(set(env), {"PATH", "HOME", "HERMES_HOME", "NO_COLOR"})


class ArgvSafety(unittest.TestCase):
    def check(self, role, prompt="rm -rf / && echo $(secret)"):
        fake = FakeExec(AUTH_OK[role["runtime"]])
        with mock.patch.object(agents, "_exec", fake), mock.patch.object(agents.shutil, "which", return_value="/x"):
            agents.run_agent(role, prompt, Path("/tmp"), Path(tempfile.mkdtemp()) / "l.log", 90)
        auth, run = fake.calls
        for call in fake.calls:
            self.assertTrue(all(isinstance(a, str) for a in call["argv"]))
            self.assertFalse(FORBIDDEN & set(call["argv"]), call["argv"])
            self.assertNotIn("--credentials", call["argv"])
            self.assertNotIn("print-api-key", call["argv"])
        self.assertNotIn(prompt, " ".join(run["argv"]))
        self.assertEqual(run["stdin"], prompt)
        self.assertEqual(run["timeout"], 90)
        self.assertEqual(auth["argv"][0], run["argv"][0])
        return run["argv"]

    def test_codex(self):
        argv = self.check(CODEX)
        self.assertEqual(argv[-1], "-")
        self.assertIn("read-only", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-astra")
        self.assertIn("workspace-write", self.check(dict(CODEX, access="edit")))

    def test_claude(self):
        argv = self.check(CLAUDE)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep,Edit,Write")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "Read,Glob,Grep,Edit,Write")
        self.assertIn("--restricted", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertEqual(self.check(dict(CLAUDE, access="read"))[argv.index("--tools") + 1], "Read,Glob,Grep")

    def test_pi(self):
        argv = self.check(PI)
        self.assertEqual(argv[argv.index("--tools") + 1], "read,grep,find,ls")
        for flag in ("--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files",
                     "--no-approve", "--offline", "--print"):
            self.assertIn(flag, argv)
        self.assertNotIn("bash", self.check(dict(PI, access="edit"))[argv.index("--tools") + 1])
        self.assertIn("edit,write", self.check(dict(PI, access="edit"))[argv.index("--tools") + 1])

    def test_hermes(self):
        argv = self.check(HERMES)
        self.assertEqual(argv[:4], ["hermes", "-p", "coder", "chat"])
        self.assertEqual(argv[argv.index("--toolsets") + 1], "file")
        self.assertEqual(argv[argv.index("--query-file") + 1], "-")
        self.assertEqual(argv[argv.index("--run-budget") + 1], "90")
        self.assertIn("--safe-mode", argv)  # no hooks, plugins, MCP servers, or user config customizations
        self.assertNotIn("terminal", argv)
        self.assertEqual(self.check({k: v for k, v in HERMES.items() if k != "profile"})[:2], ["hermes", "chat"])


class Parsers(unittest.TestCase):
    def test_claude_permission_denial_is_blocked_even_with_success(self):
        out = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                          "result": "Could not edit", "permission_denials": [{"tool_name": "Edit"}]})
        self.assertEqual(agents._parse_claude(out)["status"], "blocked")

    def test_codex(self):
        ok = jl({"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
                {"type": "error", "message": "stream disconnected, retrying"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "draft"}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "final"}},
                {"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}})
        self.assertEqual(agents._parse_codex(ok), {"status": "ok", "text": "final", "session_id": "t1",
                                                   "usage": {"input_tokens": 3, "output_tokens": 2}, "detail": "completed"})
        quota = jl({"type": "thread.started", "thread_id": "t2"},
                   {"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again at 3pm."}})
        self.assertEqual(agents._parse_codex(quota)["status"], "quota")
        self.assertIsNone(agents._parse_codex(jl({"type": "thread.started", "thread_id": "t3"}, {"type": "turn.started"})))
        self.assertIsNone(agents._parse_codex("not json\n{broken"))
        no_msg = jl({"type": "turn.completed", "usage": {}})
        self.assertEqual(agents._parse_codex(no_msg)["status"], "error")

    def test_claude(self):
        ok = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done",
                         "session_id": "s1", "usage": {"input_tokens": 1}})
        self.assertEqual(agents._parse_claude(ok)["text"], "done")
        self.assertEqual(agents._parse_claude(ok)["session_id"], "s1")
        quota = json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                            "result": "Rate limit reached: out of extra usage", "session_id": "s2"})
        self.assertEqual(agents._parse_claude(quota)["status"], "quota")
        zero_exit_error = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "", "errors": ["max turns"]})
        self.assertEqual(agents._parse_claude(zero_exit_error)["status"], "error")
        auth = json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": "Not logged in. Please run /login"})
        self.assertEqual(agents._parse_claude(auth)["status"], "blocked")
        self.assertIsNone(agents._parse_claude("garbage"))
        self.assertIsNone(agents._parse_claude(json.dumps({"type": "system"})))

    def test_pi(self):
        msg = {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "hi "},
                                                {"type": "text", "text": "there"}],
               "usage": {"input": 5, "output": 2}, "stopReason": "stop"}
        ok = jl({"type": "session", "id": "p1"}, {"type": "agent_start"}, {"type": "message_end", "message": msg},
                {"type": "agent_end", "messages": []})
        self.assertEqual(agents._parse_pi(ok), {"status": "ok", "text": "hi there", "session_id": "p1",
                                                "usage": {"input": 5, "output": 2}, "detail": "completed"})
        partial = jl({"type": "session", "id": "p2"}, {"type": "message_end", "message": msg})
        self.assertEqual(agents._parse_pi(partial)["status"], "error")
        err = jl({"type": "session", "id": "p3"}, {"type": "message_end", "message": dict(
            msg, stopReason="error", errorMessage="429 quota exceeded")}, {"type": "agent_end"})
        self.assertEqual(agents._parse_pi(err)["status"], "quota")
        self.assertIsNone(agents._parse_pi(jl({"type": "session", "id": "p4"}, {"type": "agent_start"})))

    def test_hermes(self):
        ok = jl({"type": "system", "subtype": "init", "model": "glm-5.3", "session_id": "h1"},
                {"type": "text", "text": "partial"},
                {"type": "result", "session_id": "h1", "exit_code": 0, "text": "final",
                 "tokens": {"input": 1, "output": 1, "total": 2, "cache_read": 0, "cache_write": 0}})
        r = agents._parse_hermes(ok)
        self.assertEqual((r["status"], r["text"], r["session_id"], r["usage"]["total"]), ("ok", "final", "h1", 2))
        bad = jl({"type": "result", "session_id": "h2", "exit_code": 1, "text": "", "error": "credentials exhausted"})
        self.assertEqual(agents._parse_hermes(bad)["status"], "quota")
        self.assertEqual(agents._parse_hermes(jl({"type": "result", "exit_code": 1, "text": "x"}))["status"], "error")
        self.assertIsNone(agents._parse_hermes(jl({"type": "system", "subtype": "init"})))


class RunAgent(unittest.TestCase):
    def run_with(self, role, run, auth=None):
        fake = FakeExec(AUTH_OK[role["runtime"]] if auth is None else auth, run)
        log = Path(tempfile.mkdtemp()) / "runs" / "a.log"
        with mock.patch.object(agents, "_exec", fake), mock.patch.object(agents.shutil, "which", return_value="/x"):
            return agents.run_agent(role, "do it", Path("/tmp"), log, 30), fake, log

    def test_ok_and_log(self):
        out = jl({"type": "thread.started", "thread_id": "t"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
                 {"type": "turn.completed", "usage": {"input_tokens": 1}})
        res, fake, log = self.run_with(CODEX, (0, out, "warn\n", False))
        self.assertEqual(set(res), {"status", "text", "session_id", "usage", "detail"})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(fake.calls[1]["cwd"], "/tmp")
        body = log.read_text()
        self.assertLess(body.index("== checkpoint =="), body.index("pid=4242"))
        self.assertLess(body.index("pid=4242"), body.index("turn.completed"))
        self.assertIn("warn", body)
        self.assertEqual(oct(log.stat().st_mode & 0o777), "0o600")

    def test_checkpoint_survives_interrupt_without_prompt(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_with(CODEX, KeyboardInterrupt())
        log = max(Path(tempfile.gettempdir()).glob("*/runs/a.log"), key=lambda p: p.stat().st_mtime)
        body = log.read_text()
        self.assertIn('"argv": ["codex", "exec"', body)
        self.assertIn("pid=4242", body)
        self.assertNotIn("do it", body)
        self.assertNotIn("== exit ==", body)

    def test_zero_exit_quota(self):
        out = jl({"type": "turn.failed", "error": {"message": "usage limit reached"}})
        self.assertEqual(self.run_with(CODEX, (0, out, "", False))[0]["status"], "quota")

    def test_zero_exit_no_result_is_error(self):
        res = self.run_with(PI, (0, jl({"type": "session", "id": "x"}), "", False))[0]
        self.assertEqual(res["status"], "error")

    def test_nonzero_exit_overrides_success(self):
        out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "x", "session_id": "s"})
        res = self.run_with(CLAUDE, (1, out, "", False))[0]
        self.assertEqual((res["status"], res["text"], res["session_id"]), ("error", "", "s"))

    def test_stderr_classification_without_events(self):
        res = self.run_with(HERMES, (2, "", "Error: opencode-go not logged in", False))[0]
        self.assertEqual(res["status"], "blocked")
        res = self.run_with(HERMES, (2, "", "HTTP 429 too many requests", False))[0]
        self.assertEqual(res["status"], "quota")

    def test_auth_blocked_before_inference(self):
        for role, auth in ((CODEX, "Logged in using an API key\n"), (CLAUDE, json.dumps({"loggedIn": False})),
                           (CLAUDE, json.dumps({"loggedIn": True, "authMethod": "console", "apiProvider": "firstParty"})),
                           (PI, json.dumps({"status": "missing"})), (HERMES, "opencode-go: not logged in\n")):
            res, fake, _ = self.run_with(role, (0, "never", "", False), auth=auth)
            self.assertEqual(res["status"], "blocked", role)
            self.assertEqual(len(fake.calls), 1)

    def test_missing_binary(self):
        with mock.patch.object(agents.shutil, "which", return_value=None):
            self.assertEqual(agents.doctor_role(CODEX), ["codex not found on PATH"])
            self.assertEqual(agents.run_agent(CODEX, "p", Path("/tmp"), Path("/tmp/x.log"), 5)["status"], "blocked")

    def test_doctor_ok(self):
        with mock.patch.object(agents, "_exec", FakeExec(AUTH_OK["pi"])), mock.patch.object(agents.shutil, "which", return_value="/x"):
            self.assertEqual(agents.doctor_role(PI), [])

    def test_timeout_result(self):
        res = self.run_with(CODEX, (-9, "", "", True))[0]
        self.assertEqual(res["status"], "error")
        self.assertIn("timeout", res["detail"])


class RealSubprocess(unittest.TestCase):
    def test_timeout_kills_own_process_group(self):
        rc, out, err, timed_out = agents._exec(["sh", "-c", "sleep 30 & echo $!; wait"], stdin="", timeout=0.3)
        self.assertTrue(timed_out)
        self.assert_dead(int(out.strip().splitlines()[0]))

    def test_interrupt_kills_own_process_group(self):
        pids = []

        def boom(pid):
            pids.append(pid)
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            agents._exec(["sleep", "30"], stdin="", timeout=30, on_start=boom)
        self.assert_dead(pids[0])

    def test_escaped_grandchild_cannot_hang_return(self):
        code = ("import subprocess,sys,time; p=subprocess.Popen(['sleep','30'], start_new_session=True);"
                "print(p.pid, flush=True); time.sleep(30)")
        t0 = time.monotonic()
        rc, out, err, timed_out = agents._exec([sys.executable, "-c", code], stdin="", timeout=0.5)
        self.assertTrue(timed_out)
        self.assertLess(time.monotonic() - t0, 15)
        os.kill(int(out.split()[0]), 9)  # escaped sleep was deliberately left alive; not our group

    def test_output_is_bounded_to_tail(self):
        with mock.patch.object(agents, "_OUTPUT_LIMIT", 1000):
            rc, out, err, _ = agents._exec([sys.executable, "-c", "print('a'*5000+'END')"], stdin="", timeout=10)
        self.assertEqual(rc, 0)
        self.assertLessEqual(len(out), 1000)
        self.assertTrue(out.endswith("END\n"))

    def assert_dead(self, pid):
        for _ in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.02)
            except ProcessLookupError:
                return
        self.fail(f"pid {pid} survived")

    def test_stdin_and_env(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "leak"}):
            rc, out, err, timed_out = agents._exec(["sh", "-c", "cat; echo \"[$ANTHROPIC_API_KEY]\""], stdin="prompt", timeout=5)
        self.assertEqual((rc, timed_out), (0, False))
        self.assertEqual(out, "prompt[]\n")


if __name__ == "__main__":
    unittest.main()
