"""Structured plans from the read-only planner: validate, summarize, record decisions, preflight tests, queue.

A plan never authorizes work by itself. The planner cannot edit the repository; MAF stores its output in private
state, a person answers every decision, and `night --plan` runs only after all decisions are answered and every
acceptance command can at least start.
"""
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from . import agents, core

PLAN_KEYS = {"version", "goal", "interfaces", "main_agent", "decisions", "chains", "risks"}
PLAN_ID = re.compile(r"plan-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}")
SCHEMA = (
    'Return ONLY one JSON object: {"version": 1, "goal": str, '
    '"interfaces": [{"name": str, "spec": str}], '
    '"main_agent": [{"title": str, "why": str, "paths": [str]}], '
    '"decisions": [{"question": str, "options": [str], "blocks": [task id], "answer": null}], '
    '"chains": [{"name": str, "tasks": [{"id", "title", "instructions", "paths", "tests", "acceptance_why", "risk"}]}], '
    '"risks": [str]}. '
    "main_agent is the judgment-heavy core the main chat builds and commits first (shared models, interface "
    "skeletons); chains are small, clearly testable tasks for the lightweight coder, run in order, each starting from "
    "the previous task's tested commit. decisions are open questions only a person can settle; list them instead of "
    "guessing. Task ids: lowercase letters, digits and hyphens, unique. tests: nonempty argv arrays that fail before "
    "the task and pass after it. risk: manual, docs, style or tests (default manual). Write text in the user's language."
)


def _strings(value, name, allow_empty=True):
    if not isinstance(value, list) or (not allow_empty and not value) or any(
            not isinstance(v, str) or not v.strip() for v in value):
        raise core.FlowError(f"Plan {name} must be a list of nonempty strings.")


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS or plan["version"] != 1:
        raise core.FlowError("Plan needs exactly version 1, goal, interfaces, main_agent, decisions, chains and risks.")
    if not isinstance(plan["goal"], str) or not plan["goal"].strip():
        raise core.FlowError("Plan goal must be a nonempty string.")
    for item in plan["interfaces"] if isinstance(plan["interfaces"], list) else [None]:
        if not isinstance(item, dict) or set(item) != {"name", "spec"} or not all(
                isinstance(item[k], str) and item[k].strip() for k in item):
            raise core.FlowError("Each interface needs a nonempty name and spec.")
    for item in plan["main_agent"] if isinstance(plan["main_agent"], list) else [None]:
        if not isinstance(item, dict) or set(item) != {"title", "why", "paths"} or not all(
                isinstance(item[k], str) and item[k].strip() for k in ("title", "why")):
            raise core.FlowError("Each main_agent item needs title, why and paths.")
        _strings(item["paths"], "main_agent paths")
    if not isinstance(plan["chains"], list) or not plan["chains"]:
        raise core.FlowError("Plan needs at least one chain of tasks.")
    ids = []
    for chain in plan["chains"]:
        if (not isinstance(chain, dict) or set(chain) != {"name", "tasks"} or not isinstance(chain["name"], str)
                or not chain["name"].strip() or not isinstance(chain["tasks"], list) or not chain["tasks"]):
            raise core.FlowError("Each chain needs a name and at least one task.")
        for task in chain["tasks"]:
            core.validate_task(task)
            ids.append(task["id"])
    if len(ids) != len(set(ids)):
        raise core.FlowError("Task ids must be unique across the plan.")
    for item in plan["decisions"] if isinstance(plan["decisions"], list) else [None]:
        if (not isinstance(item, dict) or set(item) != {"question", "options", "blocks", "answer"}
                or not isinstance(item["question"], str) or not item["question"].strip()
                or not (item["answer"] is None or isinstance(item["answer"], str) and item["answer"].strip())):
            raise core.FlowError("Each decision needs question, options, blocks and answer (null until decided).")
        _strings(item["options"], "decision options")
        _strings(item["blocks"], "decision blocks")
        if set(item["blocks"]) - set(ids):
            raise core.FlowError("Decision blocks must name task ids in this plan.")
    _strings(plan["risks"], "risks")
    return plan


def parse(text):
    """The planner's JSON object, from a bare reply or a fenced block."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    try:
        return validate_plan(json.loads(raw))
    except ValueError as exc:
        raise core.FlowError(f"Planner reply is not a valid plan: {exc}") from exc


def directory(repo, plan_id):
    if not isinstance(plan_id, str) or not PLAN_ID.fullmatch(plan_id):
        raise core.FlowError("Unknown plan id; use the id printed by plan.")
    return core.root_for(repo) / "plans" / plan_id


def new_id():
    return time.strftime("plan-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def load(repo, plan_id):
    path = directory(repo, plan_id) / "plan.json"
    if not path.is_file():
        raise core.FlowError(f"No structured plan saved as {plan_id}.")
    return validate_plan(core.read_json(path))


def save(repo, plan_id, plan):
    folder = directory(repo, plan_id)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    core.atomic(folder / "plan.json", validate_plan(plan))
    (folder / "plan.md").write_text(render(plan_id, plan))


def open_decisions(plan):
    return [(n, d) for n, d in enumerate(plan["decisions"], 1) if d["answer"] is None]


def render(plan_id, plan):
    lines = [f"# 計畫 {plan_id}", "", plan["goal"]]
    if plan["decisions"]:
        lines += ["", "## 需要你決定（全部決定前，整份計畫不會執行）"]
        for n, d in enumerate(plan["decisions"], 1):
            state = f"已決定：{d['answer']}" if d["answer"] else "尚未決定"
            options = f"（選項：{' / '.join(d['options'])}）" if d["options"] else ""
            lines.append(f"{n}. {d['question']}{options} → {state}")
    if plan["main_agent"]:
        lines += ["", "## 主對話先做（做完並 commit，再執行 night）"]
        lines += [f"- {m['title']}：{m['why']}" + (f"（{', '.join(m['paths'])}）" if m["paths"] else "")
                  for m in plan["main_agent"]]
    if plan["interfaces"]:
        lines += ["", "## 介面約定"] + [f"- {i['name']}：{i['spec']}" for i in plan["interfaces"]]
    lines += ["", "## 交給小任務 Agent（每條鏈依序執行）"]
    lines += [f"- {c['name']}：" + " → ".join(t["id"] for t in c["tasks"]) for c in plan["chains"]]
    if plan["risks"]:
        lines += ["", "## 風險"] + [f"- {r}" for r in plan["risks"]]
    waiting = open_decisions(plan)
    lines += ["", "下一步：" + (f"回答 {len(waiting)} 個問題（decide {plan_id} 題號 答案），" if waiting else "")
              + f"主對話完成「主對話先做」並 commit 後，執行 night --plan {plan_id}。"]
    return "\n".join(lines) + "\n"


def decide(repo, plan_id, number, answer):
    plan = load(repo, plan_id)
    if not isinstance(answer, str) or not answer.strip():
        raise core.FlowError("Answer must be nonempty.")
    if not 1 <= number <= len(plan["decisions"]):
        raise core.FlowError(f"Decision number must be 1..{len(plan['decisions'])}.")
    plan["decisions"][number - 1]["answer"] = answer.strip()
    save(repo, plan_id, plan)
    return plan


def chains_for(plan):
    """Task chains with each settled decision appended to the instructions of the tasks it affects."""
    chains = []
    for chain in plan["chains"]:
        tasks = []
        for task in chain["tasks"]:
            task = dict(task)
            notes = [f"Decided: {d['question']} -> {d['answer']}" for d in plan["decisions"]
                     if not d["blocks"] or task["id"] in d["blocks"]]
            if notes:
                task["instructions"] = task["instructions"] + "\n" + "\n".join(notes)
            tasks.append(core.validate_task(task))
        chains.append(tasks)
    return chains


def preflight(repo, plan, timeout):
    """Run each distinct acceptance command once at HEAD, in a throwaway worktree, with no model involved.

    Before any task runs its tests should fail: passing means the test may not check the task; failing to start
    means the command is broken. Neither needs model tokens.
    """
    folder = core.worktrees_for(repo) / f"preflight-{uuid.uuid4().hex[:8]}"
    folder.parent.mkdir(exist_ok=True, mode=0o700)
    core.git(repo, "worktree", "add", "--detach", str(folder), "HEAD")
    results, seen = [], set()
    try:
        for chain in plan["chains"]:
            for task in chain["tasks"]:
                for argv in task["tests"]:
                    key = json.dumps(argv)
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        proc = subprocess.Popen(argv, cwd=folder, env=agents.clean_env(), stdin=subprocess.DEVNULL,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                start_new_session=True)
                    except OSError as exc:
                        results.append({"task": task["id"], "argv": argv, "outcome": "cannot_run", "detail": str(exc)})
                        continue
                    try:
                        code = proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        core.terminate(proc)
                        results.append({"task": task["id"], "argv": argv, "outcome": "timeout", "detail": f"{timeout}s"})
                        continue
                    core.reap_group(proc)
                    outcome = "passes" if code == 0 else "cannot_run" if code in (126, 127) else "fails"
                    results.append({"task": task["id"], "argv": argv, "outcome": outcome, "detail": f"exit {code}"})
    finally:
        core.reap_orphans(folder)
        core.git(repo, "worktree", "remove", "--force", str(folder))
    return results


def render_preflight(results):
    marks = {"fails": "✓ 尚未通過（正常）", "passes": "⚠ 已經通過：測試可能沒在檢查這件任務",
             "cannot_run": "✗ 無法執行：指令或檔案不存在", "timeout": "✗ 逾時"}
    lines = [f"試跑 {len(results)} 個驗收指令（本機執行，不呼叫模型）"]
    lines += [f"  {marks[r['outcome']]}  {r['task']}: {' '.join(r['argv'])}" for r in results]
    return "\n".join(lines)
