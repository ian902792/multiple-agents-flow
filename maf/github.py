"""Only this module publishes. Agents receive neither a publish task nor a merge tool."""
from __future__ import annotations

import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote

from .core import FlowError, command, git, matches, save, sensitive_path, verified


class ChecksPending(FlowError):
    """Expected external wait; do not rerun agents to poll CI."""


def risk_reasons(run):
    """Deny first; task labels and a model's low-risk opinion cannot bypass paths."""
    task, config = run["task"], run["config"]
    category = task["risk"]
    if category == "manual":
        return ["Task is classified manual."]
    allowed = config["auto_paths"].get(category, [])
    if not allowed:
        return [f"No approved {category} auto-merge paths."]
    raw = git(run["worktree"], "diff", "--no-renames", "--name-status", "-z", run["base_sha"], run["tested_sha"], "--")
    fields = raw.split("\0")
    reasons = []
    for index in range(0, len(fields) - 1, 2):
        status, path = fields[index:index + 2]
        lower = path.lower()
        if sensitive_path(path, config):
            reasons.append(f"Protected path: {path}")
            continue
        if not matches(path, allowed):
            reasons.append(f"Not in approved {category} paths: {path}")
        if status not in ("A", "M"):
            reasons.append(f"Deletion/type change/rename is manual: {path}")
        if category == "docs" and not lower.endswith(".md"):
            reasons.append(f"Not Markdown documentation: {path}")
        if category == "style" and not lower.endswith(".css"):
            reasons.append(f"Not a standalone stylesheet: {path}")
        if category == "tests" and (status != "A" or not (lower.startswith("tests/") and PurePosixPath(lower).name.startswith("test_") and lower.endswith(".py"))):
            reasons.append(f"Only new isolated tests/test_*.py are eligible: {path}")
        mode = git(run["worktree"], "ls-tree", run["tested_sha"], "--", path).split(" ", 1)[0]
        if mode != "100644":
            reasons.append(f"Executable, symlink or submodule is manual: {path}")
    if len(fields) < 2:
        reasons.append("No changed files.")
    if run.get("review", {}).get("risk") != "low":
        reasons.append("Independent reviewer did not classify this change as low risk.")
    return reasons


def slug_for(run):
    remote = git(run["worktree"], "remote", "get-url", "origin")
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", remote)
    if not match:
        raise FlowError("Publishing requires an explicit github.com origin (SSH or HTTPS, no embedded credentials).")
    return match.group(1)


def gh(run, *args, json_output=False):
    output = command(["gh", *args], run["worktree"], timeout=120)
    return json.loads(output) if json_output else output


def remote_base_matches(run):
    base = run["config"]["base_branch"]
    git(run["worktree"], "fetch", "--no-tags", "origin", f"refs/heads/{base}")
    if git(run["worktree"], "rev-parse", "FETCH_HEAD") != run["base_sha"]:
        raise FlowError("Remote base moved. Replan/rebase manually, then submit and re-test; no stale merge.")


def publish(repo, run):
    head = verified(repo, run)
    slug = slug_for(run)
    existing = gh(run, "pr", "list", "--repo", slug, "--head", run["branch"], "--state", "all",
                  "--json", "number,url,state,headRefOid,baseRefName", json_output=True)
    if len(existing) > 1:
        raise FlowError("Multiple PRs for this branch; reconcile manually.")
    if existing:
        pr = existing[0]
        if pr["baseRefName"] != run["config"]["base_branch"]:
            raise FlowError("Existing PR targets another base.")
        if pr["state"] == "MERGED" and pr["headRefOid"] == head:
            run.update(status="merged", pr=pr["number"], pr_url=pr["url"])
            save(repo, run)
            return
        if pr["state"] != "OPEN":
            raise FlowError("Existing PR is closed; refusing to create a duplicate.")
    remote_base_matches(run)
    run.update(status="publishing", stage="publishing")
    save(repo, run)
    git(run["worktree"], "push", "origin", f"HEAD:refs/heads/{run['branch']}")
    if not existing:
        body = (f"## Task\n{run['task']['title']}\n\n"
                f"Run: `{run['id']}`\nTested and independently reviewed: `{head}`\n\n"
                "## Verification commands\n" + "\n".join(f"- `{json.dumps(item['argv'])}` — exit {item['exit_code']}" for item in run["tests"])
                + "\n\n## Independent review\n" + run["review"]["summary"]
                + "\n\nCreated by multiple-agents-flow. Local logs are not uploaded. Auto-merge policy is checked separately.")
        # If the network response is lost, the next explicit publish reconciles by branch.
        gh(run, "pr", "create", "--repo", slug, "--base", run["config"]["base_branch"],
           "--head", run["branch"], "--title", run["task"]["title"], "--body", body, "--draft")
        existing = gh(run, "pr", "list", "--repo", slug, "--head", run["branch"], "--state", "open",
                      "--json", "number,url,headRefOid", json_output=True)
    if len(existing) != 1:
        raise FlowError("Cannot confirm exactly one PR; retry publish to reconcile.")
    pr = gh(run, "pr", "view", str(existing[0]["number"]), "--repo", slug,
            "--json", "number,url,headRefOid", json_output=True)
    if pr["headRefOid"] != head:
        raise FlowError("Remote PR head does not match verified commit.")
    run.update(status="pr", stage="pr", pr=pr["number"], pr_url=pr["url"])
    save(repo, run)


def checks_pass(pr):
    checks = pr.get("statusCheckRollup")
    if not isinstance(checks, list) or not checks:
        return False
    return all((item.get("status") == "COMPLETED" and item.get("conclusion") == "SUCCESS")
               or item.get("state") == "SUCCESS" for item in checks)


def merge(repo, run):
    head = verified(repo, run)
    if not run.get("auto_merge") or not run.get("pr"):
        raise FlowError("This run did not authorize auto merge or has no PR.")
    reasons = risk_reasons(run)
    if reasons:
        raise FlowError("Auto merge denied: " + "; ".join(reasons))
    slug = slug_for(run)
    pr = gh(run, "pr", "view", str(run["pr"]), "--repo", slug,
            "--json", "state,headRefOid,baseRefName,isDraft,statusCheckRollup,reviewDecision,mergeStateStatus", json_output=True)
    if pr["headRefOid"] != head or pr["baseRefName"] != run["config"]["base_branch"]:
        raise FlowError("PR identity changed.")
    if pr["state"] == "MERGED":
        run["status"] = "merged"
        save(repo, run)
        return
    if pr["state"] != "OPEN":
        raise FlowError("PR is not open.")
    remote_base_matches(run)
    # Server-side strict required checks close the race between our base check and merge.
    protection = gh(run, "api", f"repos/{slug}/branches/{quote(run['config']['base_branch'], safe='')}/protection/required_status_checks", json_output=True)
    if protection.get("strict") is not True or not (protection.get("contexts") or protection.get("checks")):
        raise FlowError("Auto merge needs strict required GitHub status checks. Never bypass branch protection.")
    if pr.get("reviewDecision") in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
        raise FlowError("GitHub requires review changes or an authorized reviewer. No bypass.")
    if not checks_pass(pr):
        checks = pr.get("statusCheckRollup") or []
        failed = any(item.get("conclusion") in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED")
                     or item.get("state") in ("FAILURE", "ERROR") for item in checks)
        if failed:
            raise FlowError("GitHub check failed. Inspect it before submitting a repair task.")
        raise ChecksPending("Waiting for successful GitHub checks; no model call needed.")
    if pr["isDraft"]:
        gh(run, "pr", "ready", str(run["pr"]), "--repo", slug)
        pr = gh(run, "pr", "view", str(run["pr"]), "--repo", slug,
                "--json", "headRefOid,mergeStateStatus,statusCheckRollup,reviewDecision", json_output=True)
    if pr["headRefOid"] == head and pr.get("mergeStateStatus") in (None, "UNKNOWN"):
        raise ChecksPending("Waiting for GitHub to compute mergeability.")
    if (pr["headRefOid"] != head or pr.get("mergeStateStatus") != "CLEAN" or not checks_pass(pr)
            or pr.get("reviewDecision") in ("CHANGES_REQUESTED", "REVIEW_REQUIRED")):
        raise FlowError("PR is not clean/mergeable; no bypass.")
    run.update(status="merging", stage="merging")
    save(repo, run)
    gh(run, "pr", "merge", str(run["pr"]), "--repo", slug, "--squash", "--match-head-commit", head)
    confirmed = gh(run, "pr", "view", str(run["pr"]), "--repo", slug, "--json", "state,headRefOid", json_output=True)
    if confirmed["state"] != "MERGED" or confirmed["headRefOid"] != head:
        raise FlowError("Merge result unknown. Retry merge to reconcile; do not blindly publish again.")
    run["status"] = "merged"
    save(repo, run)
