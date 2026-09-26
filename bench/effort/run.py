"""Compare Pi coder thinking levels on one fixed task through the normal MAF delegate flow.

Each level runs in a fresh temporary Git repository with an isolated MAF config directory, so the
user's global flows, defaults and billing confirmations are never touched. This makes real model
calls on your Pi / OpenCode Go subscription; pass --confirm-subscription-only to attest that the
route is subscription-only (OpenCode Go "Use balance" off) before anything runs.
"""
import argparse
import json
import os
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


def run_level(level, model, env, keep):
    repo = Path(tempfile.mkdtemp(prefix=f"maf-bench-{level}-"))
    try:
        for name in ("duration.py", "test_duration.py", ".gitignore"):
            shutil.copy(HERE / "fixture" / name, repo / name)
        for argv in (["init", "-q", "-b", "main"], ["add", "."],
                     ["-c", "user.name=MAF bench", "-c", "user.email=bench@example.invalid", "commit", "-qm", "Fixture"]):
            subprocess.run(["git", *argv], cwd=repo, check=True)
        flow_cli(env, "mode", f"bench-{level}", repo=repo)
        flow_cli(env, "confirm-billing", "--no-overage", repo=repo)
        run_id = json.loads(flow_cli(env, "delegate", str(HERE / "task.json"), repo=repo))["id"]
        started = time.time()
        flow_cli(env, "work", "--once", "--run-id", run_id, repo=repo)
        wall = time.time() - started
        row = next(r for r in json.loads(flow_cli(env, "progress", "--json", repo=repo)) if r["run"] == run_id)
        coder = [a for a in row["agents"] if a["role"] == "coder"]
        total = {k: sum((a.get("usage") or {}).get(k, 0) for a in coder)
                 for k in ("input", "cacheRead", "cacheWrite", "output", "reasoning")}
        cost = sum(((a.get("usage") or {}).get("cost") or {}).get("total", 0) for a in coder)
        prompt = total["input"] + total["cacheRead"] + total["cacheWrite"]
        return {"level": level, "status": row["status"], "attempts": len(coder), "wall_seconds": round(wall, 1),
                **total, "cache_hit": round(total["cacheRead"] / prompt, 3) if prompt else None,
                "cost": round(cost, 5), "note": row.get("note", ""), "repo": str(repo) if keep else None}
    finally:
        if not keep:
            shutil.rmtree(repo, ignore_errors=True)


def table(results):
    lines = ["| level | result | attempts | seconds | output | reasoning | cache hit | cost |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in results:
        hit = "-" if r["cache_hit"] is None else f"{r['cache_hit']:.1%}"
        lines.append(f"| {r['level']} | {r['status']} | {r['attempts']} | {r['wall_seconds']} | {r['output']:,} | "
                     f"{r['reasoning']:,} | {hit} | ${r['cost']:.4f} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--levels", default="off,low,medium,max",
                        help="comma-separated Pi thinking levels (off, minimal, low, medium, high, xhigh, max)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per level (default 1)")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--confirm-subscription-only", action="store_true",
                        help="attest that the Pi / OpenCode Go route has no extra-usage billing enabled")
    parser.add_argument("--keep", action="store_true", help="keep the temporary repositories for inspection")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a Markdown table")
    args = parser.parse_args()
    if not args.confirm_subscription_only:
        raise SystemExit("This makes real Pi calls. Check that OpenCode Go 'Use balance' is off, "
                         "then rerun with --confirm-subscription-only.")
    levels = [level.strip() for level in args.levels.split(",") if level.strip()]
    config = Path(tempfile.mkdtemp(prefix="maf-bench-config-"))
    env = dict(os.environ, XDG_CONFIG_HOME=str(config))
    results = []
    try:
        for level in levels:
            flow = flows.templates()["quick"]
            flow["description"] = f"Effort benchmark: Pi coder thinking {level}."
            flow["roles"]["coder"].update(model=args.model, effort=level)
            spec = config / f"bench-{level}.json"
            spec.write_text(json.dumps({"name": f"bench-{level}", "flow": flow}))
            flow_cli(env, "flow-save", str(spec))
        for level in levels:
            for _ in range(max(1, args.repeat)):
                print(f"running {level} ...", file=sys.stderr, flush=True)
                results.append(run_level(level, args.model, env, args.keep))
    finally:
        shutil.rmtree(config, ignore_errors=True)
    print(json.dumps(results, indent=2) if args.json else table(results))


if __name__ == "__main__":
    main()
