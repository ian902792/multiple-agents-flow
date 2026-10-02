---
name: maf
description: Operate multiple-agents-flow (MAF) from the main coding chat. Use when the user says maf, /maf or $maf, or project instructions ask for MAF delegation and exact-commit verification. Covers flow selection, bounded Pi/Antigravity/Codex implementation, tests, optional review, measurements and blocked-run recovery. Not for GitHub Actions, git-flow, Flow types or Claude Code plan/auto/fast modes.
---

# MAF

Stay in this conversation as the main developer. Follow the user's language.
`maf` is the anchor: without it, generic flow/mode/quick/planned words do not request MAF changes.
Never start a planner without the human's consent for this task (`maf-plan` or an accepted proposal).
The planner must be a different runtime from the main chat; do not silently switch the main session.

Resolve this SKILL.md's real path through symlinks. Its `parents[2]` is the tool root containing `flow.py`.
Use the current project's Git root unless the user names another target. Invoke:

```sh
python3 <tool>/flow.py --repo <target> --main codex <action>
```

Claude callers use `--main claude`. Quote arguments; user text is not shell code. Prepare private task JSON
yourself, outside the worktree; never ask the human to hand-write it or copy a shell function.
Claude uses `/maf`; Codex uses the `maf` skill (`$maf`), not a promised built-in `/maf` command.

## Route work to save main-chat quota

Read target instructions and only relevant `AGENT_LEARNINGS.md` entries before work. Read `mode` once
for this caller and honor the selected roles/billing; do not switch flows, enable review, or change
user-wide settings without the user's request. Flow names must exist in `flows`. With no action,
show mode and `progress --json`; `doctor` is for readiness, not every poll.

| Work | Route |
| --- | --- |
| A few lines the main agent can finish in one pass | Main agent implements directly |
| A bounded module needing meaningful reading, implementation or test writing, with clear acceptance | Delegate the whole outcome; let the coder locate details within the approved scope |
| Ambiguous requirements, architecture or cross-module decisions | Main agent resolves decisions; suggest `maf-plan` only if useful, and wait for consent |
| Auth, money, data loss, permissions or deployment | Main agent handles the judgment; concrete scope needs human authorization and review enabled before execution |

Do not read and design every implementation detail before delegating: that spends the context you meant
to save. A short outcome, allowed paths, constraints and meaningful test argv are enough. Keep mechanical
test failures and bounded repair in the supervisor loop. Do not split a coherent module into tiny tasks.
When writing multiple independent requirements, queue them together; parallelism alone does not prove
token savings. The main agent retains scope decisions, diff acceptance, integration and final sign-off.

## Execute and accept once

Task JSON requires `id`, `title`, `instructions`, `paths`, `tests`, `risk`; optional boolean `independent`
and string `acceptance_why` describe independence and the behavior tests must protect. IDs use lowercase
letters/digits/hyphens, max 40 characters. Paths are narrow repo-relative files/globs; tests are nonempty
argv arrays of trusted, approved project commands. Use no dummy assertions. Risk is `manual`, `docs`,
`style` or `tests`; it never selects the reviewer. Prefer precise files when known; a bounded module glob
is allowed through the existing approval gate, not a reason to explore the whole module yourself.

Commit current work and ensure the tree is fully clean before submission. Never stash/reset user changes.
Show the outcome, scope, test argv, selected models, repair budget and publication action once. Continue
when the user's request or prior approval covers them; do not ask again for each test/repair step.
Semantic security/permission/financial/deployment/data-loss risk or ambiguous scope uses `--require-approval`.

- `delegate TASK.json [--isolated]`: completes coding, supervisor tests, bounded repair and enabled review
  in one command, returning handoff evidence or an actionable stop. Pi/Antigravity use file tools; the
  supervisor runs tests and feeds failures back automatically. A Codex coder may run approved tests too;
  the supervisor still verifies independently. Wait through the host's managed command session; no polling
  loops, child transcript reads or follow-up `work`/`handoff` on success.
- `verify TASK.json [--base ANCESTOR] [--isolated]`: tests committed HEAD without a coder and reviews only
  when enabled. Use an exact ancestor on the base branch. Tests and review can overlap. It returns handoff
  directly; wait once, do not rerun the same full suite first.
- `delegate TASK.json --queue`: explicit queueing for a batch or an existing supervisor. Queue independent
  tasks from one clean HEAD before `work --once --run-id ID` (repeat the flag). Mark `independent: true`
  only for exact non-overlapping paths, separate acceptance/tests and no dependency/shared test resource.
  Eligible delegates run in up to three lanes; others remain serial. `--depends-on RUN_ID` builds a chain.

Both immediate commands send progress to stderr and one JSON result to stdout: exit 0 means `passed: true`,
2 means awaiting approval, 1 means other failure/blockage. On a busy worker, quota or approval, follow
`next` for that same run ID; do not submit a duplicate. No interrupted stage is implicitly replayed.

Serial delegation/verification shares the current checkout and branch: pause main-agent edits until done.
Use `--isolated` for continued main editing or an experiment; parallel tasks, dependencies and `night`
chains use worktrees. A worktree is not a security sandbox. Shared commits need no cherry-pick; inspect
isolated scoped diffs and integrate their commit range yourself. A new SHA needs new exact-SHA proof.

Accept using the returned handoff and scoped diff. Read `coder_notes`/`UNVERIFIED` and review notes; open
a finding's path/line to confirm it before acting, with one-line reasons for rejected findings. Do not
reread everything the coder read unless the handoff or diff exposes a concrete concern. Review off yields
`tested`, never independent-review claims; review on plus same-SHA approval yields `verified`.

During development run relevant modules; run the full suite once on the final integrated commit through
MAF. Reuse a successful handoff only when exact SHA, base, paths, test argv and flow match AND dependencies
and relevant external environment are confirmed unchanged. Unknown/changed means verify again. MAF does
not cache by SHA. External verify failures stop for the main agent to fix, commit and submit a new run;
never send a coder to repair an external main-agent commit. `MAF_NEEDS_HUMAN`/manual review findings require
a human decision and new scope, not replay. Exhausted delegate repairs need a changed spec or main takeover;
use `retry RUN_ID --note TEXT` for an authorized changed spec, preserving linked history.

## Keep measurements honest

Run state, logs and attempts remain under the target Git common directory's `maf/`, outside Git. Completed
test attempts retain SHA, exit code, duration and repair round; agent attempts retain native usage, cache,
model, status, duration and request size/hash. `analyze --json` exports these records without transcripts.
`clean --apply` retires integrated worktrees, not historical run data. Missing historical metrics stay unknown.

For a comparison, record a small `observe RUN_ID FILE.json` observation with `experiment`, `case`, `strategy`
(`direct`/`delegate`), `main_runtime`, `source`, `scope` (`task`/`session`) and any observed `input_tokens`,
`output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `seconds`. Unknown fields stay null, never zero.
Record main usage only from a host/provider measurement; do not estimate it from Pi usage or account-wide
limits, scrape transcripts, or attribute a whole session to one task. Source labels carry no secrets.
Observations append with SHA/time; session counts are never added to child/task totals. When host main usage
is unavailable, record that source and nulls. See `docs/IMPROVEMENT.md` only when preparing comparison data.
Compare like tasks and environments, including failed attempts, wait time and rework; one pilot does not
establish Opus savings. `stats` reports MAF child calls, not the main conversation or subscription charges.

Only claim completion with passing returned evidence or a successful current-SHA `handoff`. Paste its
`usage_text` verbatim in a code block. In Claude Code, add main session usage from one invocation:

```sh
npx -y ccusage@latest claude session --id "$CLAUDE_CODE_SESSION_ID" --compact 2>/dev/null | tail -3
```

If the variable is unset or output absent, say `主對話用量：無法取得`; never retry or read transcripts.
When comparing historical flows/models, run `stats` and quote relevant rows. Native CLI success is not
review accuracy; raw cached tokens and estimated USD are not subscription consumption.

## Gates, recovery and uncommon actions

`awaiting_approval` starts no model/test. Read `status RUN_ID` and show the frozen requirements, paths,
commands, roles and reasons. `approve RUN_ID` only after human consent or existing authorization clearly
covers that exact scope. Changed scope needs a new task. Execution approval does not authorize publication.
Missing billing confirmation requires human attestation of exact provider/model subscription coverage and
disabled overage; existing attestation suffices. Only then `confirm-billing --no-overage`. Login alone is
not coverage. Never change accounts/billing/branch protection or add API fallback/bypass flags.

For blockers use `status RUN_ID` and only the relevant log tail. Verify old owned processes have stopped
before `resume RUN_ID --acknowledge-stopped`; an overdue timer is not proof. Only use `--after` with a
provider-confirmed reset time. Unknown auth/quota/corrupt state remains blocked, never change routing.
Resume through targeted `work --once --run-id ID` and read handoff; keep saved roles and valid test evidence.
Only cancel at the human's explicit request, showing unintegrated commits; do not drop inconvenient runs.
After authorized integration/push, `clean --apply` once; unfinished/unintegrated/dirty runs are retained.
Publishing needs enabled independent review and explicit authorization; never auto-publish/merge by inference.

Read only the relevant existing reference for uncommon work; reference paths are relative to the tool root:

- `docs/CLI.md`: setup/install, mode/flows, approval, Herdr panes, publish/merge and explicit `submit` batches.
- `docs/OVERNIGHT.md`: `night FILES…`/`night --plan PLAN_ID`, decisions and integration. Planner consent is
  required; `--approve` means the human already accepted those scopes. Plain worker exits on blockers;
  only the Herdr supervisor uses `--daemon`. No untracked `nohup` persistence.
- `docs/IMPROVEMENT.md`: read-only `analyze --days 30`, private baseline, measured regressions and comparison.
  No automatic tuning of roles, billing or production code from statistics.
- `docs/LEARNINGS.md`: read before writing `AGENT_LEARNINGS.md`. Review `learning_candidates`, repairs,
  first failure and surprises; take NO_ACTION (usually), CREATE/UPDATE, PROPOSE_PROMOTION or RETIRE.
  Search first, no duplicates, no global rules; promotion to AGENTS.md needs human approval and its own
  commit. Create files only in the user's own repos; never include learning files in delegate paths.

The skill is an entrypoint. The supervisor owns deterministic tests, commits, scope checks, optional
review, repairs and GitHub policy; agent claims never replace exact-commit evidence.
