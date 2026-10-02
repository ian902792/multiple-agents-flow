"""Attributed main-chat measurements. Historical observations only: recording never changes eligibility,
verification status, approvals, tests or configuration, and it never aggregates session level usage into a
run's task totals. No model is called and no provider data is read."""
from __future__ import annotations

import copy
import math
import re
import time

from . import core

# Same control set as progress.CONTROL: C0/C1, DEL and the Unicode line/paragraph separators.
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
STRINGS = (("experiment", 80), ("case", 80), ("source", 200))
REQUIRED = ("experiment", "case", "strategy", "main_runtime", "source", "scope")
TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
OPTIONAL = (*TOKENS, "seconds")
STRATEGIES = ("direct", "delegate")
RUNTIMES = ("claude", "codex")
SCOPES = ("task", "session")


def _string(data, key, limit):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or CONTROL.search(value):
        raise core.FlowError(f"{key} must be a nonempty string of at most {limit} characters without control characters.")
    return value


def _count(value, key):
    if value is None:
        return None
    if type(value) is not int or value < 0:  # bool is not int here: type(True) is bool.
        raise core.FlowError(f"{key} must be a nonnegative integer or null.")
    return value


def _seconds(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:  # bool is not in (int, float).
        raise core.FlowError("seconds must be a finite nonnegative number or null.")
    return value


def validate(data):
    """A copy of the accepted observation, or FlowError before any caller touches run state."""
    if not isinstance(data, dict):
        raise core.FlowError("Observation must be a JSON object.")
    missing = [key for key in REQUIRED if key not in data]
    unknown = [key for key in data if key not in REQUIRED and key not in OPTIONAL]
    if missing:
        raise core.FlowError("Missing observation fields: " + ", ".join(missing))
    if unknown:
        raise core.FlowError("Unknown observation fields: " + ", ".join(sorted(str(key) for key in unknown)))
    observation = {key: _string(data, key, limit) for key, limit in STRINGS}
    if data["strategy"] not in STRATEGIES:
        raise core.FlowError("strategy must be direct or delegate.")
    if data["main_runtime"] not in RUNTIMES:
        raise core.FlowError("main_runtime must be claude or codex.")
    if data["scope"] not in SCOPES:
        raise core.FlowError("scope must be task or session.")
    observation["strategy"] = data["strategy"]
    observation["main_runtime"] = data["main_runtime"]
    observation["scope"] = data["scope"]
    for key in TOKENS:
        observation[key] = _count(data.get(key), key)
    observation["seconds"] = _seconds(data.get("seconds"))
    return observation


def record(repo, run_id, data):
    """Append one validated main-chat observation to the run's private history and return it.

    The observation is bound to the run's tested_sha or owned_head, never to a caller supplied SHA. The run
    may be completed or cleaned: this is historical evidence, not an eligibility check."""
    observation = validate(data)  # Reject every malformed input before reading or writing any state.
    with core.exclusive(repo), core.run_exclusive(repo, run_id):
        run = core.load(repo, run_id)
        if "main_runtime" in run and run["main_runtime"] != observation["main_runtime"]:
            raise core.FlowError("Observation main_runtime does not match the run's main runtime.")
        head = run.get("tested_sha") or run.get("owned_head")
        if not isinstance(head, str) or not head:
            raise core.FlowError("Run has no tested or owned commit to bind the observation to.")
        previous = run.get("observations")
        if previous is None:
            previous = []
        elif not isinstance(previous, list):
            raise core.FlowError("Saved run observations are corrupt; refusing to overwrite them.")
        entry = copy.deepcopy(observation)
        entry["recorded_at"] = time.time()
        entry["head_sha"] = head
        # Append a fresh list and deep copies so neither the input nor earlier entries can be mutated or aliased.
        run["observations"] = copy.deepcopy(previous) + [entry]
        core.save(repo, run)
        return {"run": run["id"], "observation": copy.deepcopy(entry)}
