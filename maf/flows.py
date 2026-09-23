"""Named, project-private role profiles for future work. Claude remains the main chat."""
from __future__ import annotations

from copy import deepcopy
import re

from . import core


def templates():
    roles = core.default_config("economy")["roles"]
    roles["reviewer"] = {"runtime": "codex", "provider": "chatgpt", "model": "gpt-5.6-sol",
                         "access": "read", "effort": "medium"}
    planned = deepcopy(roles)
    planned["reviewer"]["effort"] = "high"
    return {
        "quick": {"description": "Claude develops; Codex reviews. Pi is available for small delegated work.",
                  "manual_plan": False, "main": {"model": "claude-opus-5", "effort": "medium"}, "roles": roles},
        "planned": {"description": "Run /maf-plan manually; Claude develops and delegates scoped work to Pi.",
                    "manual_plan": True, "main": {"model": "claude-opus-5", "effort": "high"}, "roles": planned},
    }


def validate(repo, name, flow):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name) or name in core.MODES:
        raise core.FlowError("Flow name must be lowercase kebab-case and must not be a built-in mode.")
    if (not isinstance(flow, dict) or set(flow) != {"description", "manual_plan", "main", "roles"}
            or not isinstance(flow["description"], str) or len(flow["description"]) > 200
            or type(flow["manual_plan"]) is not bool or not isinstance(flow["roles"], dict)
            or not isinstance(flow["main"], dict) or set(flow["main"]) != {"model", "effort"}
            or not isinstance(flow["main"]["model"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", flow["main"]["model"])
            or flow["main"]["effort"] not in ("low", "medium", "high")):
        raise core.FlowError("Flow needs description, manual_plan, main Claude model/effort, and roles.")
    config = core.config_for(repo)
    config["roles"] = flow["roles"]
    core.validate_config(repo, config)
    return deepcopy(flow)


def catalog(repo):
    path = core.root_for(repo) / "flows.json"
    custom = core.read_json(path) if path.exists() else {}
    if not isinstance(custom, dict):
        raise core.FlowError("Invalid flows.json; expected an object of named flows.")
    result = templates()
    for name, flow in custom.items():
        result[name] = validate(repo, name, flow)
    return result


def save(repo, name, flow):
    validated = validate(repo, name, flow)
    catalog(repo)  # Refuse to write over an invalid existing profile set.
    path = core.root_for(repo) / "flows.json"
    custom = core.read_json(path) if path.exists() else {}
    if not isinstance(custom, dict):
        raise core.FlowError("Invalid flows.json; inspect it before saving.")
    custom[name] = validated
    core.atomic(path, custom)
    return validated
