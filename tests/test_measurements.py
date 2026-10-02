import contextlib
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from maf import core, measurements


def observation(**extra):
    base = {"experiment": "exp-1", "case": "case-1", "strategy": "direct",
            "main_runtime": "codex", "source": "main chat / codex", "scope": "task"}
    base.update(extra)
    return base


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.run = {"id": "run-0000000001", "tested_sha": "a" * 40, "owned_head": "b" * 40,
                    "main_runtime": "codex", "status": "verified", "stage": "verified", "agents": []}
        self.state = copy.deepcopy(self.run)
        self.saved = None

    def fake_load(self, repo, run_id):
        return copy.deepcopy(self.state)

    def fake_save(self, repo, run):
        self.saved = copy.deepcopy(run)
        self.state = copy.deepcopy(run)

    def record(self, data):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(core, "exclusive", lambda repo, wait=False: contextlib.nullcontext()))
            stack.enter_context(patch.object(core, "run_exclusive", lambda repo, run_id: contextlib.nullcontext()))
            stack.enter_context(patch.object(core, "load", side_effect=self.fake_load))
            stack.enter_context(patch.object(core, "save", side_effect=self.fake_save))
            return measurements.record(Path("/repo"), self.run["id"], data)

    def test_valid_unknown_values_stay_null_and_bind_to_evidence(self):
        data = observation()
        original = copy.deepcopy(data)
        result = self.record(data)
        entry = result["observation"]
        self.assertEqual(result["run"], self.run["id"])
        self.assertEqual(data, original)  # The caller's object is not mutated.
        self.assertEqual([entry[key] for key in measurements.TOKENS], [None] * 4)
        self.assertIsNone(entry["seconds"])
        self.assertEqual(entry["head_sha"], "a" * 40)  # tested_sha wins over owned_head.
        self.assertIsInstance(entry["recorded_at"], float)
        self.assertEqual(self.saved["observations"], [entry])

    def test_owned_head_is_used_without_tested_sha(self):
        del self.state["tested_sha"]
        entry = self.record(observation())["observation"]
        self.assertEqual(entry["head_sha"], "b" * 40)

    def test_explicit_zero_is_kept_not_treated_as_unknown(self):
        entry = self.record(observation(input_tokens=0, output_tokens=0, cache_read_tokens=0,
                                        cache_write_tokens=0, seconds=0))["observation"]
        self.assertEqual([entry[key] for key in measurements.TOKENS], [0, 0, 0, 0])
        self.assertEqual(entry["seconds"], 0)

    def test_multiple_observations_are_appended_in_order_and_preserved(self):
        existing = {"experiment": "before", "head_sha": "c" * 40}
        previous = [copy.deepcopy(existing)]
        self.state["observations"] = previous
        first = self.record(observation(case="one"))["observation"]
        second = self.record(observation(case="two"))["observation"]
        saved = self.saved["observations"]
        self.assertEqual([e.get("experiment") for e in saved], ["before", "exp-1", "exp-1"])
        self.assertEqual(saved[0], existing)
        self.assertEqual(saved[1], first)
        self.assertEqual(saved[2], second)
        self.assertEqual(previous, [existing])  # The loaded list is copied, never extended in place.

    def test_cleaned_run_still_records_historical_observation(self):
        self.state.update(cleaned_at=123.0, status="merged", stage="merged")
        entry = self.record(observation(scope="session"))["observation"]
        self.assertEqual(entry["scope"], "session")
        self.assertEqual(self.saved["cleaned_at"], 123.0)
        self.assertEqual(len(self.saved["observations"]), 1)

    def test_runtime_mismatch_is_rejected_without_state_change(self):
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(core.FlowError, "runtime"):
            self.record(observation(main_runtime="claude"))
        self.assertIsNone(self.saved)
        self.assertEqual(self.state, before)

    def test_run_without_commit_is_rejected_without_state_change(self):
        del self.state["tested_sha"]
        del self.state["owned_head"]
        with self.assertRaisesRegex(core.FlowError, "no tested or owned commit"):
            self.record(observation())
        self.assertIsNone(self.saved)

    def test_corrupt_previous_observations_are_not_overwritten(self):
        self.state["observations"] = {"not": "a list"}
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(core.FlowError, "corrupt"):
            self.record(observation())
        self.assertIsNone(self.saved)
        self.assertEqual(self.state, before)
        self.state["observations"] = [None]
        with self.assertRaisesRegex(core.FlowError, "corrupt"):
            self.record(observation())
        self.assertIsNone(self.saved)

    def test_invalid_inputs_leave_state_unchanged(self):
        too_long = "x" * 81
        cases = [
            None, [], "text",
            {"experiment": "e", "case": "c", "strategy": "direct", "main_runtime": "codex", "source": "s"},
            observation(experiment=""),
            observation(experiment="   "),
            observation(experiment=too_long),
            observation(case=too_long),
            observation(source=""),
            observation(source="y" * 201),
            observation(source="bad\x01value"),
            observation(source="line\nbreak"),
            observation(strategy="batch"),
            observation(main_runtime="pi"),
            observation(scope="repo"),
            observation(head_sha="c" * 40),  # Callers may not supply a SHA.
            observation(unknown="value"),
            {**observation(), 1: "value"},
            observation(input_tokens=True),
            observation(input_tokens=-1),
            observation(input_tokens=1.0),
            observation(output_tokens="5"),
            observation(seconds=True),
            observation(seconds=-1),
            observation(seconds=float("nan")),
            observation(seconds=float("inf")),
            observation(seconds="1.0"),
        ]
        for index, data in enumerate(cases):
            with self.subTest(index=index):
                before = copy.deepcopy(self.state)
                with self.assertRaises(core.FlowError):
                    self.record(data)
                self.assertIsNone(self.saved)
                self.assertEqual(self.state, before)

    def test_validation_accepts_float_seconds_and_returns_copy(self):
        data = observation(seconds=1.5, input_tokens=7)
        first = measurements.validate(data)
        second = measurements.validate(data)
        self.assertEqual(first["seconds"], 1.5)
        self.assertEqual(first["input_tokens"], 7)
        first["experiment"] = "changed"
        self.assertEqual(data["experiment"], "exp-1")
        self.assertEqual(second["experiment"], "exp-1")
        self.assertEqual(measurements.validate(observation(seconds=10 ** 400))["seconds"], 10 ** 400)


if __name__ == "__main__":
    unittest.main()
