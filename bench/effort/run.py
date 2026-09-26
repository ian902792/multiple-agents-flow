"""Compare coder effort levels (Pi by default, or any built-in flow) on one fixed task through the normal MAF delegate flow.

Each level runs in a fresh temporary Git repository with an isolated MAF config directory, so the
user's global flows, defaults and billing confirmations are never touched. This makes real model
calls on the flow's subscription routes; pass --confirm-subscription-only to attest that they are
subscription-only (for example OpenCode Go "Use balance" off) before anything runs.
"""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from maf import flows  # noqa: E402  (after sys.path so the checkout's own package is used)


def flow_cli(env, *args, repo=None):
    argv = [sys.executable, str(ROOT / "flow.py")] + (["--repo", str(repo)] if repo else []) + list(args)
    result = subprocess.run(argv, env=env, text=True, capture_output=True)
    if result.returncode:
        raise SystemExit(f"{' '.join(args)} failed:\n{result.stdout}{result.stderr}")
    return result.stdout


def normalize(usage):
    """One token breakdown from Pi, Antigravity or Codex usage; input never includes cache reads."""
    n = lambda key: usage.get(key) if type(usage.get(key)) is int else 0
    if "cacheRead" in usage or "output" in usage:  # Pi
        return {"input": n("input"), "cacheRead": n("cacheRead"), "cacheWrite": n("cacheWrite"),
                "output": n("output"), "reasoning": n("reasoning")}
    if "cache_read_tokens" in usage:  # Antigravity: input_tokens excludes cache reads
        return {"input": n("input_tokens"), "cacheRead": n("cache_read_tokens"), "cacheWrite": 0,
                "output": n("output_tokens"), "reasoning": n("thinking_tokens")}
    if "cached_input_tokens" in usage:  # Codex: input_tokens already includes cached tokens
        return {"input": n("input_tokens") - n("cached_input_tokens"), "cacheRead": n("cached_input_tokens"),
                "cacheWrite": 0, "output": n("output_tokens"), "reasoning": n("reasoning_output_tokens")}
    return None


def run_level(task, flow_name, level, env, keep):
    source = HERE / "tasks" / task
    repo = Path(tempfile.mkdtemp(prefix=f"maf-bench-{task}-{level}-"))
    try:
        shutil.copytree(source, repo, dirs_exist_ok=True, ignore=shutil.ignore_patterns("task.json", "__pycache__"))
        for argv in (["init", "-q", "-b", "main"], ["add", "."],
                     ["-c", "user.name=MAF bench", "-c", "user.email=bench@example.invalid", "commit", "-qm", "Fixture"]):
            subprocess.run(["git", *argv], cwd=repo, check=True)
        flow_cli(env, "mode", f"bench-{flow_name}-{level}", repo=repo)
        flow_cli(env, "confirm-billing", "--no-overage", repo=repo)
        run_id = json.loads(flow_cli(env, "delegate", str(source / "task.json"), repo=repo))["id"]
        started = time.time()
        flow_cli(env, "work", "--once", "--run-id", run_id, repo=repo)
        wall = time.time() - started
        row = next(r for r in json.loads(flow_cli(env, "progress", "--json", repo=repo)) if r["run"] == run_id)
        coder = [a for a in row["agents"] if a["role"] == "coder"]
        usages = [a.get("usage") or {} for a in coder]
        counts = [normalize(u) for u in usages]
        known = bool(counts) and all(c is not None for c in counts)
        total = {k: sum(c[k] for c in counts) if known else None
                 for k in ("input", "cacheRead", "cacheWrite", "output", "reasoning")}
        costs = [(u.get("cost") or {}).get("total") for u in usages]
        cost = sum(costs) if known and all(isinstance(c, (int, float)) for c in costs) else None  # agy reports none
        prompt = (total["input"] + total["cacheRead"] + total["cacheWrite"]) if known else 0
        return {"task": task, "flow": flow_name, "level": level, "status": row["status"], "attempts": len(coder), "wall_seconds": round(wall, 1),
                **total, "cache_hit": round(total["cacheRead"] / prompt, 3) if prompt else None,
                "cost": None if cost is None else round(cost, 5), "usage": usages, "note": row.get("note", ""), "repo": str(repo) if keep else None}
    finally:
        if not keep:
            shutil.rmtree(repo, ignore_errors=True)


def table(results):
    lines = ["| task | flow / level | result | attempts | seconds | output | reasoning | cache hit | cost |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in results:
        hit = "-" if r["cache_hit"] is None else f"{r['cache_hit']:.1%}"
        num = lambda v: "-" if v is None else f"{v:,}"
        cost = "-" if r["cost"] is None else f"${r['cost']:.4f}"
        lines.append(f"| {r['task']} | {r['flow']} {r['level']} | {r['status']} | {r['attempts']} | {r['wall_seconds']} | "
                     f"{num(r['output'])} | {num(r['reasoning'])} | {hit} | {cost} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    tasks = sorted(p.name for p in (HERE / "tasks").iterdir() if (p / "task.json").is_file())
    parser.add_argument("--task", choices=tasks, default="duration", help="benchmark task (default duration)")
    parser.add_argument("--flow", default="quick", choices=sorted(flows.templates()),
                        help="built-in flow whose coder runs the task (default quick = Pi)")
    parser.add_argument("--levels", help="comma-separated coder effort levels (default: the flow's own effort)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per level (default 1)")
    parser.add_argument("--model", help="override the coder model")
    parser.add_argument("--confirm-subscription-only", action="store_true",
                        help="attest that the Pi / OpenCode Go route has no extra-usage billing enabled")
    parser.add_argument("--keep", action="store_true", help="keep the temporary repositories for inspection")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a Markdown table")
    args = parser.parse_args()
    if not args.confirm_subscription_only:
        raise SystemExit("This makes real Pi calls. Check that OpenCode Go 'Use balance' is off, "
                         "then rerun with --confirm-subscription-only.")
    base = flows.templates()[args.flow]
    levels = ([level.strip() for level in args.levels.split(",") if level.strip()] if args.levels
              else [base["roles"]["coder"].get("effort", "medium")])
    config = Path(tempfile.mkdtemp(prefix="maf-bench-config-"))
    env = dict(os.environ, XDG_CONFIG_HOME=str(config))
    results = []
    try:
        for level in levels:
            flow = flows.templates()[args.flow]
            flow["description"] = f"Benchmark: {args.flow} coder effort {level}."
            coder = flow["roles"]["coder"]
            coder["effort"] = level
            if args.model:
                coder["model"] = args.model
            elif coder["runtime"] == "antigravity":  # each Gemini level is its own model ID
                coder["model"] = re.sub(r"-(low|medium|high)$", "-" + level, coder["model"])
            name = f"bench-{args.flow}-{level}"
            spec = config / f"{name}.json"
            spec.write_text(json.dumps({"name": name, "flow": flow}))
            flow_cli(env, "flow-save", str(spec))
        for level in levels:
            for _ in range(max(1, args.repeat)):
                print(f"running {level} ...", file=sys.stderr, flush=True)
                results.append(run_level(args.task, args.flow, level, env, args.keep))
    finally:
        shutil.rmtree(config, ignore_errors=True)
    print(json.dumps(results, indent=2) if args.json else table(results))


if __name__ == "__main__":
    main()
