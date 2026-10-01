import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import subprocess
import time
import unittest
from unittest.mock import patch

from maf import cli, core, history


class HistoryTests(unittest.TestCase):
    def test_cli_on_empty_repository_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cli.main(["--repo", str(repo), "analyze", "--json"])
            self.assertEqual(json.loads(output.getvalue())["runs"], 0)
            self.assertFalse((repo / ".git" / "maf").exists())

    def run_case(self, run_id, **extra):
        return {"id": run_id, "kind": "verify", "mode": "quick", "created_at": time.time(),
                "stage": "verified", "status": "verified", "tested_sha": "a", "reviewed_sha": "a",
                "config": {"roles": {"reviewer": {"enabled": True}}},
                "task": {"id": "same-task", "tests": [["python3", "tests.py"]]},
                "tests": [{"argv": ["python3", "tests.py"], "exit_code": 0}],
                "review": {"decision": "approve", "head_sha": "a", "risk": "low", "summary": "ok", "findings": []},
                "agents": [{"role": "reviewer", "runtime": "pi", "model": "flash", "status": "ok",
                            "duration_seconds": 20, "usage": {"input": 100, "output": 10, "cacheRead": 0, "cacheWrite": 0,
                                                              "cost": {"total": .01}}}], **extra}

    def test_history_separates_native_success_proof_failures_and_work_kinds(self):
        failed = self.run_case("failed", status="needs_human", stage="reviewing",
                               feedback="Reviewer must return valid JSON.", superseded_by="retry")
        retry = self.run_case("retry", failures=[{"kind": "review_format"}])
        # Same task/commit without a retry link remains its own work item.
        separate = self.run_case("separate")
        delegate = self.run_case("delegate", kind="delegate", cleaned_at=time.time())
        invalid = self.run_case("invalid", tests=[{"argv": ["true"], "exit_code": 0}])
        unknown = self.run_case("unknown", status="needs_human", stage="reviewing")
        runs = [failed, retry, separate, delegate, invalid, unknown]
        before = copy.deepcopy(runs)
        with patch.object(core, "list_runs", return_value=runs), \
                patch.object(core.agents, "run_agent", side_effect=AssertionError("model called")):
            data = history.analyze(Path.cwd())
        self.assertEqual(runs, before)
        verify = next(g for g in data["groups"] if g["kind"] == "verify")
        self.assertEqual((verify["runs"], verify["work_items"], verify["historical_completed"]), (5, 4, 2))
        self.assertEqual(verify["per_completed"]["seconds"], 50)
        self.assertTrue(next(c for c in data["cases"] if c["run"] == "delegate")["historical_proof"])
        self.assertFalse(next(c for c in data["cases"] if c["run"] == "invalid")["historical_proof"])
        cause = data["recommendations"][0]
        self.assertEqual((cause["cause"], cause["runs"], cause["recorded"], cause["inferred"]),
                         ("review_format", ["failed", "retry"], 1, 1))
        self.assertNotIn("feedback", json.dumps(data))
        self.assertIn("不是模型排名", history.render(data))

    def test_baseline_only_counts_new_runs_and_checks_repository(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, "list_runs", return_value=[self.run_case("old")]):
            path = Path(tmp) / "before.json"
            core.atomic(path, history.analyze(Path.cwd()))
            with patch.object(core, "list_runs", return_value=[self.run_case("old"), self.run_case("new")]):
                data = history.analyze(Path.cwd(), baseline=path)
            self.assertEqual((data["runs"], data["excluded_baseline_runs"]), (1, 1))
            self.assertEqual(data["cases"][0]["run"], "new")
            with self.assertRaisesRegex(core.FlowError, "this repository"):
                history.analyze(Path(tmp), baseline=path)
            for days in (0, -1, float("inf"), float("nan")):
                with self.assertRaises(core.FlowError):
                    history.analyze(Path.cwd(), days)

    def test_history_missing_usage_is_not_zero_and_proof_does_not_accept_stale_review(self):
        runs = [self.run_case("clean"), self.run_case("missing", agents=[{"status": "ok", "usage": None}]),
                self.run_case("stale", reviewed_sha="old")]
        with patch.object(core, "list_runs", return_value=runs):
            data = history.analyze(Path.cwd())
        group = data["groups"][0]
        self.assertIsNone(group["per_completed"]["seconds"])
        self.assertEqual(group["seconds"]["reported"], 2)
        self.assertEqual(group["historical_completed"], 2)

    def test_legacy_agent_error_uses_saved_failure_feedback_for_diagnosis_only(self):
        runs = [self.run_case(run_id, status="needs_human", stage="coding",
                              agents=[{"status": "error"}], feedback=feedback)
                for run_id, feedback in (
                    ("limited", "success: You've hit your monthly spend limit"),
                    ("logged-out", "Not logged in. Please run /login"),
                    ("ordinary", "incomplete turn (stopReason=stop)"),
                    ("missing", None))]
        runs.append(self.run_case("clean", feedback="Handled a monthly spend limit message"))
        runs.append(dict(runs[0], id="recorded", failures=[{"kind": "agent_error"}]))
        before = copy.deepcopy(runs)
        with patch.object(core, "list_runs", return_value=runs):
            data = history.analyze(Path.cwd())
        kinds = {case["run"]: case["causes"] for case in data["cases"]}
        self.assertEqual(kinds["limited"], [{"kind": "quota", "source": "inferred"}])
        self.assertEqual(kinds["logged-out"], [{"kind": "authentication", "source": "inferred"}])
        for run_id in ("ordinary", "missing"):
            self.assertEqual(kinds[run_id], [{"kind": "agent_error", "source": "inferred"}])
        self.assertEqual(kinds["clean"], [])
        self.assertEqual(kinds["recorded"], [{"kind": "agent_error", "source": "recorded"}])
        self.assertEqual(runs, before)  # Never change native status, evidence or retry eligibility.
        self.assertFalse(next(c for c in data["cases"] if c["run"] == "limited")["historical_proof"])

    def test_corrupt_or_malformed_history_stays_unknown_without_aborting(self):
        runs = [{"id": "corrupt", "status": "corrupt"}, self.run_case("broken", tests=[None]),
                self.run_case("missing-agents", agents=None)]
        with patch.object(core, "list_runs", return_value=runs):
            data = history.analyze(Path.cwd())
        corrupt = next(c for c in data["cases"] if c["run"] == "corrupt")
        self.assertIsNone(corrupt["seconds"])
        self.assertIsNone(corrupt["calls"])
        self.assertFalse(corrupt["historical_proof"])
        self.assertEqual(corrupt["causes"], [{"kind": "unknown", "source": "unknown"}])
        self.assertEqual(next(c for c in data["cases"] if c["run"] == "broken")["causes"],
                         [{"kind": "unknown", "source": "unknown"}])
        self.assertIsNone(next(c for c in data["cases"] if c["run"] == "missing-agents")["seconds"])


if __name__ == "__main__":
    unittest.main()
