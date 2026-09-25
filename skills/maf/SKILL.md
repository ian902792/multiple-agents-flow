---
name: maf
description: Operate multiple-agents-flow from the main coding chat. Use for global or project flow selection, scoped Pi or Antigravity delegation, exact-commit verification, progress, and blocked-run recovery.
---

# MAF

Stay in the current conversation. Its agent is the main developer for ordinary
tasks. Select a flow whose `main.runtime` matches that agent; do not silently
switch the human to another chat. Never call the Codex planner automatically:
only the human's explicit `/maf-plan` invocation may do that. Follow the user's language.

## Locate and dispatch

Resolve this SKILL.md's real path (follow symlinks). The tool root is
`parents[2]` of that file; the entrypoint is its `flow.py`. Use the current
project's Git root as target unless the user names another repository. Tool
and target may differ. Verify paths and quote each shell argument. Invoke
`python3 <tool>/flow.py --repo <target> --main claude ...` from Claude, or
`python3 <tool>/flow.py --repo <target> --main codex ...` from Codex, for
machine-readable output. The caller's runtime selects its own global default
and project mode; never rewrite the other main agent's choice.
Never ask the user to copy a shell function or hand-write task JSON.

Claude uses `/maf <action>`; Codex CLI/IDE uses `/skills` to select `maf`, or
`$maf <action>`. Do not promise `/maf` is a Codex built-in. Interpret arguments
as a request, never as shell text. With no action, show mode and progress.

| Action | Operation |
| --- | --- |
| `setup [MODE]` | Check readiness; optional mode sets a project override. |
| `mode [MODE\|default]` | Show or persist a project override; `default` restores the global flow. No inference. |
| `delegate <requirements>` | Give one or more bounded tasks to the selected lightweight coder, in separate worktrees. |
| `verify <requirement>` | Test the main agent's current committed HEAD; independently review only when the selected flow enables it. |
| `handoff RUN_ID` | Read a completed run's concise exact-SHA evidence. |
| `run <requirement>` | Explicit legacy batch run with a separate coder. |
| `approve RUN_ID` | After the human accepts a frozen task plan, release its one-time execution gate. |
| `status` | Read `progress --json`; summarize stage and blockers. |
| `resume RUN_ID` | Diagnose, resolve authorized blockers, verify stopped processes, then resume. |
| `install` | Register this skill once in the user's Claude and Codex skill directories. |

Modes: `economy` = Pi/DeepSeek Flash coding;
`opus-sol` = pinned Claude Opus 5.5 coding with Codex GPT-6 Sol available for review;
`hermes-coder` = Hermes coding with Pi available for review;
`configured` = project `.maf.json` roles when present, built-in economy otherwise.
`quick`, `planned`, `quick-antigravity`, `codex-pi`, and user-created names are user-wide role
profiles; use `flows` to inspect them. `quick-antigravity` uses the signed-in
`agy` account with Gemini 3.8 Flash High for narrow coding tasks. Profiles select future
MAF agents, not the current main session. `codex-pi` records Codex GPT-6 Sol as
main, Pi for small tasks, and optional Claude Opus 5.5 review. Tests run as
approved commands, without a tester model. Change the current session's model
in its own CLI/app; saving a flow does not switch it. Review is off
unless `roles.reviewer.enabled` is true; do not turn it on without the user's request.

## Setup and mode

1. Read target instructions and `mode` using this caller's `--main` value. New
   Git repositories with an initial commit use that runtime's global default
   flow immediately; do not create `.maf.json`
   unless project policy needs its own base branch, protected paths, or timeouts.
   Never overwrite an existing config. `ui` edits user-wide flows, the global
   default and the optional Herdr setting; it never starts an agent.
2. Use `mode MODE` only when a project needs an override; `mode default`
   restores this main runtime's global selection. `mode` alone reports effective
   roles and billing readiness. Claude and Codex project selections live in
   separate private Git state, affect new submissions only, and preserve
   existing runs. Do not edit `.maf.json` to switch modes. `submit --mode MODE`
   overrides just one task.
3. Run `doctor` for setup/readiness, not every status poll. It checks the
   selected mode without inference; it cannot prove model availability.
4. If billing confirmation is missing, show exact active provider/model routes and
   ask the human to confirm subscription coverage with extra usage / Go Use
   balance disabled. Existing authorization for that exact role/model set is
   sufficient. Only then run `confirm-billing --no-overage` with `--repo`
   for a project override, or without it for the global default. Login success
   or a setup request is not billing attestation. Approved role/model sets are
   remembered globally, so switching back needs no repeated attestation.
5. Report the mode and remaining blockers. No inference, commit, push, provider
   setting change, or global agent configuration change during setup. The skill
   is installed once for this user via `install-skills`; other Git projects need
   no MAF configuration. Never overwrite unrelated skills.

## Main-chat work

For ordinary tasks, implement in this main conversation. Do not start a
separate coder for the main agent's work. Use the selected Pi or Antigravity coder only for narrow
edits or test-writing tasks with explicit paths and approved test argv. The
lightweight coder must not execute shell tests; the
supervisor runs them. Do not delegate planning, broad integration, or final
sign-off to the lightweight coder. Mark a delegated task `"independent": true` only when it has its own
clear acceptance criteria, exact non-overlapping editable file paths, and no
dependency on another task or shared test resource. Queue all independent tasks
from the same clean HEAD before starting the worker. MAF runs up to three at once
by default; broad, sensitive, or approval-gated work remains serial. Do not
claim that parallel execution alone reduces total tokens.

Before substantial work, show the concrete goal, editable paths, test argv,
model roles, repair limit and any publication action once. Ask for a decision
only if this plan is not already covered by the user's request or prior approval.
After approval, continue within that scope without asking at each agent/test/
repair step. Ordinary small tasks within the user's request need no extra prompt.
Use `--require-approval` for security, permission, financial, deployment, data
loss, or ambiguous requirements even if the file names look harmless. MAF also
holds manual-risk batch tasks, sensitive/broad path scopes and shell verification
commands automatically. An `awaiting_approval` run cannot start an agent or test.
Read `status RUN_ID` and show its frozen instructions, paths, tests, roles and
approval reasons. Invoke `approve RUN_ID` only after the human confirms that
scope, or when their existing approval clearly covers this exact scope. Never
approve a changed plan by inference. New paths, commands or requirements need
a new task and approval. Approval is for local execution only; publication and
merge still require their own explicit authorization.

Prepare private task JSON with `id`, `title`, `instructions`, `paths`, `tests`,
`risk`, optional boolean `independent`, and optional `acceptance_why` (the real purpose the tests
must protect, so passing tests that assert nothing are caught), as described below. Keep it outside the Git worktree. Before
`delegate` or `verify`, commit the current work and ensure the tree is fully
clean; these commands snapshot exact HEAD. Do not stash or reset user changes.
Read `mode` first. Follow the selected global or project flow; do not switch
to another flow unless the user requests it.

- `delegate <task-file> [--mode NAME]` queues the selected Pi or Antigravity coder in an isolated
  worktree at HEAD. For multiple independent requirements, prepare and submit
  each task before starting the worker. Resolve any `awaiting_approval` gate,
  then run `work --once --run-id ID` with one `--run-id` per submitted task;
  the worker runs eligible tasks concurrently and drains those IDs without
  consuming unrelated queued work. Read each `handoff ID` after `tested` or `verified`
  completion. Inspect each scoped diff and integrate its commit range into the
  main branch yourself. A cherry-pick creates a new SHA, so run `verify` on
  that combined commit before calling it complete.
- `verify <task-file> [--base ANCESTOR] [--mode NAME]` tests the current HEAD
  and calls the selected independent reviewer only when enabled. The reviewer
  must use a different runtime from the selected flow's main agent. By default it
  compares with the merge-base of the configured base branch. For work on the
  base branch, pass an exact ancestor with `--base`. Run its ID through
  `work --once --run-id ID`; `handoff ID` gives the tested SHA and optional review.
  On failure, the main agent fixes the source branch, commits, and starts a new verify
  run. Resolve any `awaiting_approval` gate before `work`. Never let a delegated coder
  repair an external main-agent commit.

If the coder returns `MAF_NEEDS_HUMAN:` or the reviewer marks a security,
permission or requirements finding as manual risk, stop and report the concrete
question. Do not resume that run; settle the issue and submit a new scoped task.
Ordinary test/review failures use the configured repair budget automatically.

Read `coder_notes` (the coder's `UNVERIFIED:` items) before integrating; they often name the next task.
Reviewers misread code: open each review finding's path:line and confirm it before acting; state a
one-line reason for any finding you reject.

Only claim completion if `handoff` succeeds for the current exact commit.
When review is off, report `tested` and do not claim independent review. When
enabled and approved on the same SHA, report `verified`. Publish/auto-merge
requires enabled independent review.
If current HEAD has moved since submission, the evidence is for the earlier
SHA; submit a new verify run. Never auto-publish or merge a delegated run.

## Explicit batch run

1. Read `mode` and `progress --json`. Honor billing/auth blockers. If a previous
   submission response was interrupted, inspect existing IDs before resubmitting.
2. Read only relevant source and project instructions. Make one bounded task per
   independently verifiable change. Reuse the current conversation's plan.
3. Generate JSON with exactly `id`, `title`, `instructions`, `paths`, `tests`,
   `risk`, plus optional `acceptance_why`. ID: lowercase letters/digits/hyphens, max 40 chars. Paths: narrow,
   relative edit scopes. Tests: nonempty argv arrays of trusted, approved project
   commands. Risk defaults `manual`; it controls merge eligibility, never the
   reviewer model. No dummy tests to satisfy the schema.
4. Briefly state scope, coding model, optional reviewer, and acceptance commands. Proceed
   when authorized by the user or applicable project instructions. If approval
   is missing, prepare this concrete task before asking. Do not repeatedly ask
   for authorization already given in the conversation. Mark semantic high-risk
   tasks with `--require-approval`.
5. Save JSON in a private temporary file outside tracked files; call `submit
   <task-file>` (optionally the explicitly requested `--mode MODE`). Respect the
   clean tracked tree and configured base branch. If dirty, identify blocking
   files; do not stash, reset, or commit them automatically. Never add `--publish`
   or `--auto-merge` without explicit authorization.
6. Capture the returned ID. If status is `awaiting_approval`, inspect the frozen
   run and release it as described above. Then run `work --once --run-id RUN_ID` through the
   host's managed long-running command/session facility. Only if the user-wide
   `settings` has `herdr_enabled=true` and this session is inside Herdr with
   `HERDR_ENV=1` and inherited `HERDR_PANE_ID`, append `--planner-pane <that-id>`
   for main-pane progress. Never guess pane IDs. If an existing worker
   owns the lock, inspect its status; do not start competing workers or resubmit.
   If the human enabled Herdr and explicitly wants a visible agent pane for an
   ad hoc run inside Herdr, add `--agent-panes`; the `herdr` supervisor launcher
   enables these temporary observer panes automatically. They close after each
   role, and their display is never verification evidence.
7. Report meaningful progress in the main chat. Read `progress --json` at useful
   intervals or on request, not every few seconds through model turns. Herdr
   metadata polls locally without model calls; a worker does not automatically
   wake an idle chat. Do not detach using untracked `nohup` or promise persistence
   if the host cannot retain the command session.
8. Read the final snapshot. Report ID, status/stage, coding model, optional reviewer,
   exact-SHA test/review evidence, blocker and next action. Tested or verified is not merged;
   worker exit code zero alone is not success. Skip child transcripts unless
   needed for a specific failure.

## Status and recovery

For status use `progress --json` without starting workers or reading transcripts.
Show stage, elapsed/limit, and `attention`/`next`. Read `status RUN_ID` and the
relevant log tail only to diagnose a blocker.

For resume, inspect saved roles/evidence, find the cause, and perform safe
authorized fixes. Authentication/account actions remain with the user. Do not
bypass permissions or switch provider after quota failure. An overdue timer is
not evidence that a process stopped. Confirm the supervisor/owned process group
ended, or obtain the user's explicit stopped confirmation before `resume RUN_ID
--acknowledge-stopped`. `--after` requires a provider-confirmed reset time with
timezone. Then execute only `work --once --run-id RUN_ID`, preserving saved roles.

Unknown quota, exhausted repairs, corrupt state, and policy changes stay blocked
until resolved. Publication/merge uncertainty uses explicit `publish`/`merge`
reconciliation within existing authorization, never coder/reviewer replay.
Explain the exact blocker and smallest required user action.

The skill is an entrypoint, not a safety boundary. The supervisor owns worktrees,
commits, tests, optional independent review, retries, and GitHub policy.
