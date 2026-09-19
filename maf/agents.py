"""Runtime adapters: build safe argv, run bounded subprocesses, parse structured output.

Contract: run_agent(role, prompt, cwd, log, timeout) -> {status, text, session_id, usage, detail}
status in ok | quota | blocked | error. Exit code 0 is never trusted on its own.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

# Fixed subscription routes (runtime -> provider). Model IDs come from config; only the token shape is checked.
_ROUTES = {"codex": "chatgpt", "claude": "claude-subscription", "pi": "opencode-go", "hermes": "opencode-go"}
_OUTPUT_LIMIT = 8_000_000  # bytes kept per stream (tail); result events are at the end
_ROLE_KEYS = {"runtime", "model", "provider", "profile", "access", "effort"}
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_QUOTA = re.compile(
    r"usage limit|rate[ _-]?limit|quota|too many requests|\b429\b|out of (?:extra )?usage"
    r"|hit your limit|monthly spend limit|session limit|insufficient (?:credits?|balance)|exhausted", re.I)
_AUTH = re.compile(r"not logged in|log ?in|unauthori[sz]ed|authenticat|\b401\b|permission|approval", re.I)
_SCRUB_PREFIX = ("ANTHROPIC_", "OPENAI_", "OPENCODE_", "OPENROUTER_", "AZURE_OPENAI_", "CLAUDE_", "PI_")
_SCRUB_SUFFIX = ("_API_KEY", "_BASE_URL", "_AUTH_TOKEN", "_API_BASE")
_SCRUB_EXACT = {"CLAUDECODE", "CODEX_API_KEY"}
_KEEP = {"HERMES_HOME"}  # profile/home selection only; every other HERMES_* override is dropped


def clean_env() -> dict:
    """Child environment without API-key/endpoint overrides that could bypass subscription auth."""
    env = {k: v for k, v in os.environ.items() if k in _KEEP or not (
        k.startswith(_SCRUB_PREFIX) or k.startswith("HERMES_") or k.endswith(_SCRUB_SUFFIX) or k in _SCRUB_EXACT)}
    env["NO_COLOR"] = "1"
    return env


def validate_role(role) -> None:
    """Raise ValueError unless the role is an allowed, fully constrained subscription route."""
    if not isinstance(role, dict):
        raise ValueError("role must be a dict")
    extra = set(role) - _ROLE_KEYS
    if extra:
        raise ValueError(f"unknown role keys: {sorted(extra)}")
    provider = _ROUTES.get(role.get("runtime"))
    if provider is None:
        raise ValueError(f"unsupported runtime: {role.get('runtime')!r}")
    if role.get("provider") != provider:
        raise ValueError(f"{role['runtime']} provider must be {provider!r}")
    model = role.get("model")
    if not isinstance(model, str) or not _SAFE_TOKEN.fullmatch(model):
        raise ValueError(f"unsafe model name: {model!r}")
    if role.get("access") not in ("read", "edit"):
        raise ValueError("access must be 'read' or 'edit'")
    profile = role.get("profile")
    if profile is not None and (role["runtime"] != "hermes" or not isinstance(profile, str)
                                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile)):
        raise ValueError("profile is only valid for hermes and must be a safe name")
    if role.get("effort", "medium") not in ("low", "medium", "high"):
        raise ValueError("effort must be low, medium or high")
    if role["runtime"] == "hermes" and role["access"] == "read":
        # Verified in hermes-agent toolsets.py/model_tools.py/tools_config.py: every selection surface
        # (-t, platform_toolsets, agent.disabled_toolsets, `hermes tools disable`) works on toolset names;
        # `file` bundles read_file with write_file/patch and bare tool names are dropped as unknown.
        # Only a zero-tool session would be write-safe, and that cannot read the repository.
        raise ValueError("hermes has no native read-only toolset; only access 'edit' is supported")


def _hermes_prefix(role):
    return ["hermes"] + (["-p", role["profile"]] if role.get("profile") else [])


def _argv(role: dict, timeout: int) -> list[str]:
    rt, edit, model = role["runtime"], role["access"] == "edit", role["model"]
    effort = role.get("effort", "medium")
    if rt == "codex":
        return ["codex", "exec", "--json", "--ignore-user-config", "--ignore-rules",
                "-s", "workspace-write" if edit else "read-only", "-m", model,
                "-c", 'model_reasoning_effort="' + effort + '"', "-"]
    if rt == "claude":
        tools = "Read,Glob,Grep" + (",Edit,Write" if edit else "")
        return ["claude", "-p", "--output-format", "json", "--model", model, "--effort", effort, "--restricted", "--safe-mode",
                "--tools", tools, "--allowedTools", tools, "--permission-mode", "acceptEdits",
                "--permission-prompts", "none", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    if rt == "pi":
        tools = "read,grep,find,ls" + (",edit,write" if edit else "")
        return ["pi", "--print", "--mode", "json", "--provider", "opencode-go", "--model", model,
                "--thinking", effort, "--tools", tools, "--no-extensions", "--no-skills", "--no-prompt-templates",
                "--no-context-files", "--no-approve", "--offline"]
    return _hermes_prefix(role) + ["chat", "--query-file", "-", "--oneshot", "--format", "stream-json",
                                   "--provider", "opencode-go", "--model", model, "--toolsets", "file",
                                   "--safe-mode", "--reasoning", effort, "--max-turns", "30", "--run-budget", str(int(timeout))]


def _pump(stream, buf: bytearray):
    """Copy a pipe into buf, keeping only the last _OUTPUT_LIMIT bytes."""
    try:
        while chunk := stream.read1(65536):
            buf += chunk
            if len(buf) > _OUTPUT_LIMIT:
                del buf[:len(buf) - _OUTPUT_LIMIT]
    except (OSError, ValueError):
        pass
    finally:
        stream.close()


def _feed(stream, data: str):
    try:
        stream.write(data.encode())
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _killpg(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def _exec(argv, *, stdin: str, timeout: float, cwd=None, on_start=None):
    """Run argv in its own process group. The group is killed on timeout, KeyboardInterrupt or any other
    exception; an escaped grandchild holding the pipes cannot hang the return. -> (rc, out, err, timed_out)."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, env=clean_env(), start_new_session=True)
    out, err, timed_out = bytearray(), bytearray(), False
    threads = [threading.Thread(target=_pump, args=(proc.stdout, out), daemon=True),
               threading.Thread(target=_pump, args=(proc.stderr, err), daemon=True),
               threading.Thread(target=_feed, args=(proc.stdin, stdin), daemon=True)]
    try:
        if on_start:
            on_start(proc.pid)
        for t in threads:
            t.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        _killpg(proc)
        deadline = time.monotonic() + 5
        for t, stream in zip(threads, (proc.stdout, proc.stderr, proc.stdin)):
            if t.ident is None:
                stream.close()
            else:
                t.join(timeout=max(0.0, deadline - time.monotonic()))
    return proc.returncode, bytes(out).decode(errors="replace"), bytes(err).decode(errors="replace"), timed_out


def _auth_problems(role: dict) -> list[str]:
    """Safe status-only auth checks (never prints or reads credentials)."""
    rt = role["runtime"]
    binary = rt
    if shutil.which(binary) is None:
        return [f"{binary} not found on PATH"]
    argv = {"codex": ["codex", "login", "status"],
            "claude": ["claude", "auth", "status", "--json"],
            "pi": ["pi", "auth", "check", "--provider", "opencode-go", "--json"],
            "hermes": _hermes_prefix(role) + ["auth", "status", "opencode-go"]}[rt]
    try:
        rc, out, err, timed_out = _exec(argv, stdin="", timeout=60)
    except OSError as e:
        return [f"{binary} auth check failed to start: {e}"]
    if timed_out or rc != 0:
        return [f"{binary} auth status exit {rc}{' (timeout)' if timed_out else ''}"]
    if rt == "codex":  # codex prints status on stderr
        return [] if "Logged in using ChatGPT" in out + err else ["codex is not logged in with ChatGPT"]
    if rt == "claude":
        try:
            st = json.loads(out)
        except ValueError:
            return ["claude auth status returned invalid JSON"]
        ok = st.get("loggedIn") is True and st.get("authMethod") == "claude.ai" and st.get("apiProvider") == "firstParty"
        return [] if ok else ["claude is not logged in with a first-party claude.ai subscription"]
    if rt == "pi":
        try:
            ok = json.loads(out).get("status") == "ready"
        except ValueError:
            ok = False
        return [] if ok else ["pi opencode-go credentials not ready"]
    low = out.lower()
    return [] if "logged in" in low and "not logged in" not in low else ["hermes opencode-go not logged in"]


def doctor_role(role) -> list[str]:
    """Problems only. No model inference."""
    try:
        validate_role(role)
    except ValueError as e:
        return [str(e)]
    return _auth_problems(role)


def _result(status, text="", session_id=None, usage=None, detail=""):
    return {"status": status, "text": text, "session_id": session_id, "usage": usage, "detail": detail}


def _classify(message, session_id=None, usage=None):
    message = " ".join(str(message).split())[:300] or "unknown failure"
    status = "quota" if _QUOTA.search(message) else "blocked" if _AUTH.search(message) else "error"
    return _result(status, session_id=session_id, usage=usage, detail=message)


def _jsonl(out: str) -> list[dict]:
    events = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            events.append(e)
    return events


def _ok(text, sid, usage):
    return _result("ok", text, sid, usage, "completed") if text else _result("error", "", sid, usage, "empty response")


def _parse_codex(out):
    ev = _jsonl(out)
    sid = next((e.get("thread_id") for e in ev if e.get("type") == "thread.started"), None)
    done = [i for i, e in enumerate(ev) if e.get("type") == "turn.completed"]
    # A recovered transient error before turn.completed is fine; anything after (or without) it is not.
    fails = [e for e in ev[(done[-1] + 1 if done else 0):] if e.get("type") in ("turn.failed", "error")]
    if fails:
        e = fails[-1]
        return _classify((e.get("error") or {}).get("message") or e.get("message") or e["type"], sid)
    if not done:
        return None
    msgs = [e["item"].get("text", "") for e in ev if e.get("type") == "item.completed"
            and isinstance(e.get("item"), dict) and e["item"].get("type") == "agent_message"]
    return _ok(msgs[-1] if msgs else "", sid, ev[done[-1]].get("usage"))


def _parse_claude(out):
    objs = _jsonl(out)
    if not objs:
        try:
            objs = [json.loads(out)]
        except ValueError:
            return None
    res = [o for o in objs if o.get("type") == "result"]
    if not res:
        return None
    r = res[-1]
    sid, usage = r.get("session_id"), r.get("usage")
    failure = None
    if r.get("is_error") or r.get("subtype") != "success":
        errs = r.get("errors") or []
        failure = _classify(f"{r.get('subtype')}: {r.get('result') or ' '.join(map(str, errs))}", sid, usage)
        if r.get("is_error") and failure["status"] == "quota":
            return failure
    if r.get("permission_denials"):
        return _result("blocked", session_id=sid, usage=usage, detail="Claude reported permission denials; no approval bypass.")
    if failure:
        return failure
    return _ok(r.get("result") or "", sid, usage)


def _parse_pi(out):
    ev = _jsonl(out)
    sid = next((e.get("id") for e in ev if e.get("type") == "session"), None)
    msgs = [(i, e["message"]) for i, e in enumerate(ev) if e.get("type") == "message_end"
            and isinstance(e.get("message"), dict) and e["message"].get("role") == "assistant"]
    if not msgs:
        return None
    index, m = msgs[-1]
    usage = m.get("usage")
    if m.get("stopReason") == "error":
        return _classify(m.get("errorMessage") or "assistant error", sid, usage)
    if (m.get("stopReason") != "stop" or ev[-1].get("type") != "agent_settled"
            or any(e.get("type") in ("agent_start", "message_start") for e in ev[index + 1:])):
        return _result("error", "", sid, usage, f"incomplete turn (stopReason={m.get('stopReason')})")
    text = "".join(c.get("text", "") for c in m.get("content") or [] if isinstance(c, dict) and c.get("type") == "text")
    return _ok(text, sid, usage)


def _parse_hermes(out):
    res = [e for e in _jsonl(out) if e.get("type") == "result"]
    if not res:
        return None
    r = res[-1]
    sid, usage = r.get("session_id"), r.get("tokens")
    if r.get("error") or r.get("exit_code", 1) != 0:
        return _classify(r.get("error") or f"hermes exit_code {r.get('exit_code')}", sid, usage)
    return _ok(r.get("text") or "", sid, usage)


_PARSERS = {"codex": _parse_codex, "claude": _parse_claude, "pi": _parse_pi, "hermes": _parse_hermes}


def _append_log(log: Path, text: str):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as f:
        f.write(text)


def run_agent(role: dict, prompt: str, cwd: Path, log: Path, timeout: int) -> dict:
    """Run one fresh agent session. Prompt goes over stdin; argv is fixed per role."""
    validate_role(role)
    problems = _auth_problems(role)
    if problems:
        return _result("blocked", detail="; ".join(problems))
    argv = _argv(role, timeout)
    # Live checkpoint before invocation: argv + pid only (prompt goes over stdin, never logged here).
    _append_log(log, f"== checkpoint ==\n{json.dumps({'argv': argv, 'started': time.time(), 'timeout': timeout})}\n")
    try:
        rc, out, err, timed_out = _exec(argv, stdin=prompt, timeout=timeout, cwd=str(cwd),
                                        on_start=lambda pid: _append_log(log, f"pid={pid}\n"))
    except OSError as e:
        _append_log(log, f"== exit ==\nfailed to start: {e}\n")
        return _result("error", detail=f"failed to start {argv[0]}: {e}")
    _append_log(log, f"== exit ==\n{rc} timed_out={timed_out}\n== stdout ==\n{out}\n== stderr ==\n{err}\n")
    if timed_out:
        return _result("error", detail=f"timeout after {timeout}s; process group killed")
    res = _PARSERS[role["runtime"]](out) or _classify(err.strip()[-300:] or f"exit {rc}: no result event")
    if rc != 0 and res["status"] == "ok":
        res = _result("error", "", res["session_id"], res["usage"], f"exit {rc} despite success event")
    return res
