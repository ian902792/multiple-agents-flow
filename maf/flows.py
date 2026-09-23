"""User-wide flow profiles and optional integrations. Claude remains the main chat."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import os
from pathlib import Path
import re

from . import core


def templates():
    roles = core.default_config("economy")["roles"]
    roles["reviewer"] = {"runtime": "codex", "provider": "chatgpt", "model": "gpt-6-sol",
                         "access": "read", "effort": "medium"}
    planned = deepcopy(roles)
    planned["reviewer"]["effort"] = "high"
    return {
        "quick": {"description": "小任務：Claude 主對話開發；必要時交給 Pi；Codex 獨立審查。",
                  "manual_plan": False, "main": {"model": "opus", "effort": "medium"}, "roles": roles},
        "planned": {"description": "中大型任務：手動 /maf-plan 規畫；Claude 實作，可交 Pi 處理明確小任務。",
                    "manual_plan": True, "main": {"model": "opus", "effort": "high"}, "roles": planned},
    }


def home():
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    if not root.is_absolute():
        raise core.FlowError("XDG_CONFIG_HOME must be an absolute path.")
    return root / "multiple-agents-flow"


@contextmanager
def exclusive():
    root = home()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def settings():
    path = home() / "settings.json"
    data = core.read_json(path) if path.exists() or path.is_symlink() else {"herdr_enabled": False}
    if not isinstance(data, dict) or set(data) != {"herdr_enabled"} or type(data["herdr_enabled"]) is not bool:
        raise core.FlowError("Invalid global settings.json; expected a boolean herdr_enabled.")
    return data


def set_herdr(enabled):
    if type(enabled) is not bool:
        raise core.FlowError("Herdr setting must be true or false.")
    with exclusive():
        settings()
        core.atomic(home() / "settings.json", {"herdr_enabled": enabled})
    return settings()


def validate(name, flow):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name) or name in core.MODES:
        raise core.FlowError("Flow name must be lowercase kebab-case and must not be a built-in mode.")
    if (not isinstance(flow, dict) or set(flow) != {"description", "manual_plan", "main", "roles"}
            or not isinstance(flow["description"], str) or len(flow["description"]) > 200
            or type(flow["manual_plan"]) is not bool or not isinstance(flow["roles"], dict)
            or not isinstance(flow["main"], dict) or set(flow["main"]) != {"model", "effort"}
            or not isinstance(flow["main"]["model"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", flow["main"]["model"])
            or flow["main"]["effort"] not in ("low", "medium", "high", "xhigh", "max")):
        raise core.FlowError("Flow needs description, manual_plan, main Claude model/effort, and roles.")
    core.validate_roles(flow["roles"])
    return deepcopy(flow)


def catalog():
    path = home() / "flows.json"
    custom = core.read_json(path) if path.exists() or path.is_symlink() else {}
    if not isinstance(custom, dict):
        raise core.FlowError("Invalid flows.json; expected an object of named flows.")
    result = templates()
    for name, flow in custom.items():
        result[name] = validate(name, flow)
    return result


def save(name, flow):
    validated = validate(name, flow)
    with exclusive():
        catalog()  # Refuse to write over an invalid existing profile set.
        path = home() / "flows.json"
        custom = core.read_json(path) if path.exists() or path.is_symlink() else {}
        custom[name] = validated
        core.atomic(path, custom)
    return validated
