"""Local historical evidence, not live eligibility. Never read transcripts or call models."""
from collections import Counter
import json
import math
from pathlib import Path
import time

from . import agents, core, progress


def proof(run):
    """Validate the saved test/review contract even after a worktree has been cleaned."""
    try:
        results = run.get("tests") or []
        head = run.get("tested_sha")
        if (not progress.completed(run) or not isinstance(head, str) or not head
                or not results or [r["argv"] for r in results] != run["task"]["tests"]
                or any(type(r["exit_code"]) is not int or r["exit_code"] != 0 for r in results)):
            return False
        if core.review_enabled(run["config"]):
            return (run.get("reviewed_sha") == head
                    and core.review_result(json.dumps(run.get("review")), head)["decision"] == "approve")
        return run["stage"] == "tested" and not run.get("review") and not run.get("reviewed_sha")
    except progress.CAUGHT:
        return False


def causes(run):
    fields = [run.get(key) or [] for key in ("failures", "tests", "agents")]
    if (any(not isinstance(items, list) or any(not isinstance(item, dict) for item in items) for items in fields)
            or not isinstance(run.get("review") or {}, dict)):
        return [("unknown", "unknown")]
    recorded = [f["kind"] for f in run.get("failures", []) if isinstance(f, dict) and isinstance(f.get("kind"), str)]
    if recorded:
        return [(kind, "recorded") for kind in recorded]
    # ponytail: infer only explicit saved evidence; unknown history stays unknown rather than parsing transcripts.
    if any(t.get("exit_code") for t in run.get("tests") or []):
        return [("tests_failed", "inferred")]
    if (run.get("review") or {}).get("decision") == "changes_requested":
        return [("review_rejected", "inferred")]
    if run.get("feedback") == "Reviewer must return valid JSON.":
        return [("review_format", "inferred")]
    if progress.completed(run) and not proof(run):
        return [("invalid_evidence", "inferred")]
    attempts = run.get("agents") or []
    if attempts and attempts[-1].get("status") != "ok":
        status = attempts[-1].get("status")
        # Older adapters saved explicit quota/auth failures as generic errors. Diagnose only; never rewrite state.
        if status == "error" and isinstance(run.get("feedback"), str):
            status = agents._classify(run["feedback"])["status"]
        return [({"quota": "quota", "blocked": "authentication", "error": "agent_error"}
                 .get(status, "unknown"), "inferred")]
    if not proof(run) and run.get("status") in ("needs_human", "corrupt", "waiting_quota"):
        return [("unknown", "unknown")]
    return []


ADVICE = {
    "review_format": "保留原始審查，只修復格式；加入同型回歸案例，避免重跑整份審查。",
    "review_invalid": "檢查 SHA、schema 或修復前後欄位；保持阻擋，不把格式問題轉成通過。",
    "invalid_evidence": "完成狀態缺少完整且一致的測試／審查證據；不得整合，先找出缺失。",
    "tests_failed": "先確認測試有執行且斷言對應需求，再修根因；新 commit 重新驗證。",
    "review_rejected": "把可重現的審查 finding 加成回歸測試；分開追蹤真正缺陷與誤報。",
    "quota": "確認額度重置後恢復同一 run；保持已通過的測試證據，不切換帳號或付費路由。",
    "authentication": "修復原有登入或權限；不要把驗證失敗算成模型能力不足。",
    "agent_error": "先查對應 attempt 的執行錯誤；用最小案例重現，不盲目重試整件任務。",
    "unknown": "先補足可確認的原因；不要據此調模型、推理強度或宣稱準確率改善。",
}


def analyze(repo, days=30, baseline=None):
    if not math.isfinite(days) or days <= 0:
        raise core.FlowError("--days must be a positive finite number.")
    prior = set()
    if baseline is not None:
        data = core.read_json(baseline)
        if (not isinstance(data, dict) or data.get("schema") != 1
                or data.get("repository") != str(Path(repo).resolve()) or not isinstance(data.get("cases"), list)
                or any(not isinstance(c, dict) or not isinstance(c.get("run"), str) for c in data["cases"])):
            raise core.FlowError("Baseline must be an analyze JSON snapshot from this repository.")
        prior = {c["run"] for c in data["cases"]}
    every = core.list_runs(repo, others=True)
    since = time.time() - days * 86400
    runs = [r for r in every if r["id"] not in prior and
            (r.get("status") == "corrupt" or float(r.get("created_at") or 0) >= since)]
    # Only explicit retry links combine logical work. Identical task IDs, titles or SHAs are not links.
    parents = {r["superseded_by"]: r["id"] for r in every if r.get("superseded_by")}
    def work_id(run):
        current, seen = run["id"], set()
        while current in parents and current not in seen:
            seen.add(current)
            current = parents[current]
        return current if current not in seen else run["id"]
    cases, problems, groups = [], {}, {}
    for run in runs:
        good = proof(run)
        raw_agents = run.get("agents")
        known_agents = isinstance(raw_agents, list) and all(isinstance(a, dict) for a in raw_agents)
        agents = raw_agents if known_agents else []
        tests = run.get("test_attempts")
        known_tests = isinstance(tests, list) and all(isinstance(t, dict) for t in tests)
        usage = progress.total_usage(agents) if agents else dict.fromkeys(progress.USAGE_KEYS, 0 if known_agents else None)
        case = {"run": progress.clean(run["id"], 80), "work": work_id(run),
                "kind": run.get("kind", "unknown"), "flow": progress.clean(run.get("mode", "unknown"), 40),
                "status": run.get("status"), "stage": run.get("stage"), "historical_proof": good,
                "head_sha": run.get("tested_sha"), "calls": len(agents) if known_agents else None,
                "native_ok": sum(a.get("status") == "ok" for a in agents) if known_agents else None,
                "format_repairs": sum(a.get("purpose") == "format_repair" for a in agents),
                "causes": [{"kind": k, "source": s} for k, s in causes(run)],
                "main_runtime": run.get("main_runtime"), "maf_version": run.get("maf_version"),
                "environment": run.get("environment"), "timings": core.timings(run),
                "repairs": run.get("repairs"), "failures": run.get("failures", []),
                "agent_attempts": [{k: a.get(k) for k in ("role", "runtime", "provider", "model", "status", "purpose",
                                                       "outcome", "duration_seconds", "started_at", "head_sha",
                                                       "prompt_bytes", "prompt_sha256", "usage_scope", "usage")}
                                   for a in agents] if known_agents else None,
                "test_history_complete": known_tests and run.get("test_history_complete") is True,
                "test_attempts": [{k: t.get(k) for k in ("argv", "exit_code", "duration_seconds", "head_sha", "repair", "started_at")}
                                  for t in tests] if known_tests else None,
                "observations": run.get("observations", []),
                **{k: usage[k] for k in progress.USAGE_KEYS}}
        cases.append(case)
        groups.setdefault((case["kind"], case["flow"]), []).append(case)
        for kind, count in Counter(c["kind"] for c in case["causes"]).items():
            row = problems.setdefault(kind, {"cause": kind, "events": 0, "runs": [], "recorded": 0, "inferred": 0})
            row["events"] += count
            row["runs"].append(case["run"])
            row["recorded"] += sum(c["source"] == "recorded" for c in case["causes"] if c["kind"] == kind)
            row["inferred"] += sum(c["source"] == "inferred" for c in case["causes"] if c["kind"] == kind)
    summaries = []
    for (kind, flow), items in sorted(groups.items()):
        works = {c["work"] for c in items}
        done = {c["work"] for c in items if c["historical_proof"]}
        summaries.append({"kind": kind, "flow": flow, "runs": len(items), "work_items": len(works),
                          "historical_completed": len(done),
                          "per_completed": {k: round(sum(c[k] for c in items) / len(done), 4)
                                            if done and all(c[k] is not None for c in items) else None
                                            for k in progress.USAGE_KEYS},
                          **{k: progress._mean([c[k] for c in items]) for k in progress.USAGE_KEYS}})
    recommendations = sorted(problems.values(), key=lambda r: (-len(r["runs"]), -r["events"], r["cause"]))
    for row in recommendations:
        row["suggestion"] = ADVICE.get(row["cause"], ADVICE["unknown"])
    return {"schema": 1, "repository": str(Path(repo).resolve()), "days": days, "created_at": time.time(),
            "excluded_baseline_runs": len(prior), "runs": len(cases), "groups": summaries,
            "recommendations": recommendations, "cases": cases,
            "limits": ["歷史證據不等於目前可整合；目前 SHA 仍須通過 handoff。",
                       "無法讀取的 corrupt run 沒有可靠日期，會列入分析並將用量保留為未知。",
                       "沒有已標註的真實缺陷與乾淨對照案例，不能估算審查誤報率或漏報率。",
                       "baseline 排除已看過的 run；重試的部分花費可能在上一期，不能視為完整生命週期成本。"]}


def render(data):
    lines = [f"MAF 歷史分析：最近 {data['days']:g} 天，{data['runs']} 個 run（已排除 baseline {data['excluded_baseline_runs']} 個）"]
    for group in data["groups"]:
        seconds = group["per_completed"]["seconds"]
        lines.append(f"  {group['kind']} / {group['flow']}：{group['runs']} run，{group['work_items']} 件工作，"
                     f"歷史完成 {group['historical_completed']}；每完成 agent 耗時 "
                     + (progress.fmt_seconds(seconds) if seconds is not None else "未完整回報"))
    lines.append("\n改善優先序（依受影響 run 數；不是模型排名）")
    for row in data["recommendations"]:
        lines.extend([f"  {row['cause']}：{len(row['runs'])} run / {row['events']} 次（記錄 {row['recorded']}，推定 {row['inferred']}）",
                      "    " + row["suggestion"], "    案例：" + ", ".join(row["runs"])])
    if not data["recommendations"]:
        lines.append("  沒有已記錄的失敗原因。")
    lines.extend("\n" + line for line in data["limits"])
    return "\n".join(lines)
