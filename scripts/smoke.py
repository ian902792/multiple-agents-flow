"""Explicit live subscription smoke; leaves private evidence under .git/maf/smoke/."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maf import agents, core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True, help="Authorize three small subscription model calls")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    _, config = core.execution_config(project)
    core.billing_check(project, config)
    directory = core.root_for(project) / "smoke" / str(time.time_ns())
    directory.mkdir(parents=True, mode=0o700)
    repo = Path(tempfile.mkdtemp(prefix="maf-live-"))
    core.command(["git", "init", "-q", "-b", "main", str(repo)], project)
    core.git(repo, "config", "user.email", "smoke@example.invalid")
    core.git(repo, "config", "user.name", "Flow Smoke")
    (repo / "README.md").write_text("# Smoke fixture\n")
    core.git(repo, "add", ".")
    core.git(repo, "commit", "-qm", "Initial smoke fixture")
    core.init(repo, "economy")
    core.atomic(repo / ".maf.json", config)
    core.confirm_billing(repo, config)
    print(f"Live smoke evidence: {directory}", flush=True)
    planner = agents.run_agent(config["roles"]["planner"], "Do not use tools. Reply only FLOW_SMOKE_OK.", repo, directory / "planner.log", 180)
    core.atomic(directory / "planner-result.json", planner)
    if planner["status"] != "ok" or "FLOW_SMOKE_OK" not in planner["text"]:
        raise core.FlowError(f"Planner smoke failed: {planner['status']} {planner['detail']}")
    print("Planner protocol OK; testing real coder -> command -> reviewer.", flush=True)
    task = {"id": "live-smoke", "title": "Add smoke verification marker",
            "instructions": "Only edit README.md. Append exactly one line FLOW_SMOKE_OK. No other changes. Do not run commands or commit.",
            "paths": ["README.md"], "risk": "docs",
            "tests": [[sys.executable, "-c", "from pathlib import Path; assert Path('README.md').read_text().splitlines().count('FLOW_SMOKE_OK') == 1"]]}
    with core.exclusive(repo):
        run = core.submit(repo, task)
        core.process(repo, run)
    summary = {"status": run["status"], "run_id": run["id"], "tested_sha": run.get("tested_sha"),
               "reviewed_sha": run.get("reviewed_sha"), "feedback": run.get("feedback"),
               "agents": run["agents"], "evidence": str(directory), "fixture": str(repo)}
    core.atomic(directory / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if run["status"] != "verified":
        raise core.FlowError("Live workflow did not reach verified; inspect saved evidence.")


if __name__ == "__main__":
    main()
