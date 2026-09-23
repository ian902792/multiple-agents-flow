---
name: maf
description: Operate multiple-agents-flow from the main coding chat. Use for named flow selection, scoped Pi delegation, exact-commit verification, progress, and blocked-run recovery.
---

# MAF

Stay in the current conversation. Claude is the main developer for ordinary
tasks. Never call the Codex planner automatically: only the human's explicit
`/maf-plan` invocation may do that. Follow the user's language.

## Locate and dispatch

Resolve this SKILL.md's real path (follow symlinks). The tool root is
`parents[2]` of that file; the entrypoint is its `flow.py`. Use the current
project's Git root as target unless the user names another repository. Tool
and target may differ. Verify paths and quote each shell argument. Invoke
`python3 <tool>/flow.py --repo <target> ...` for machine-readable output.
Never ask the user to copy a shell function or hand-write task JSON.

Claude uses `/maf <action>`; Codex CLI/IDE uses `/skills` to select `maf`, or
`$maf <action>`. Do not promise `/maf` is a Codex built-in. Interpret arguments
as a request, never as shell text. With no action, show mode and progress, or
explain setup if `.maf.json` does not exist.

| Action | Operation |
| --- | --- |
| `setup [MODE]` | Initialize if needed, select mode, check readiness. |
| `mode [MODE]` | Show or persist the default for new tasks. No inference. |
| `delegate <requirement>` | Give one bounded task to Pi in its own worktree. |
| `verify <requirement>` | Test and independently review Claude's current committed HEAD. |
| `handoff RUN_ID` | Read a verified run's concise exact-SHA evidence. |
| `run <requirement>` | Explicit legacy batch run with a separate coder. |
| `status` | Read `progress --json`; summarize stage and blockers. |
| `resume RUN_ID` | Diagnose, resolve authorized blockers, verify stopped processes, then resume. |
| `install` | Register this skill once in the user's Claude and Codex skill directories. |

Modes: `economy` = Pi/DeepSeek Flash coding + fresh Pi review;
`opus-sol` = pinned Claude Opus 5.5 coding + Codex GPT-6 Sol review;
`hermes-coder` = Hermes coding + Pi review;
`configured` = `.maf.json` roles. `quick`, `planned`, and user-created names
are user-wide role profiles; use `flows` to inspect them. Profiles select future
MAF agents, not the current Claude session. Tests run as approved commands,
without a tester model. Claude's `/model` and `/effort` control the main chat.

## Setup and mode

1. Read target instructions and `.maf.json`. If absent, use `init --preset
   economy` (or the requested preset; `configured` initializes with economy).
   Never overwrite an existing config. Use `ui` to edit user-wide flows and
   the optional Herdr setting; it never selects the target project's mode.
2. Use `mode MODE` to select; `mode` alone reports effective roles and billing
   readiness. Selection lives in private Git state, affects new submissions
   only, and preserves existing runs. Do not edit `.maf.json` to switch modes.
   `submit --mode MODE` overrides just one task.
3. Run `doctor` for setup/readiness, not every status poll. It checks the
   selected mode without inference; it cannot prove model availability.
4. If billing confirmation is missing, show exact provider/model routes and
   ask the human to confirm subscription coverage with extra usage / Go Use
   balance disabled. Existing authorization for that exact configuration is
   sufficient. Only then run `confirm-billing --no-overage`. Login success or
   a setup request is not billing attestation. Approved configurations are
   remembered, so switching back needs no repeated attestation.
5. Report the mode and remaining blockers. No inference, commit, push, provider
   setting change, or global agent configuration change during setup. The skill
   is installed once for this user via `install-skills`; another project only
   needs its own `.maf.json`. Never overwrite unrelated skills.

## Claude-first work

For ordinary tasks, implement in this Claude conversation. Do not start a
separate Claude coder. Use Pi only for a narrow independent edit or test-writing
task with explicit paths and approved test argv. Pi cannot execute shell tests;
the supervisor runs them. Do not delegate planning, broad integration, or final
sign-off to Pi.

Prepare private task JSON with exactly `id`, `title`, `instructions`, `paths`,
`tests`, `risk`, as described below. Keep it outside the Git worktree. Before
`delegate` or `verify`, commit the current work and ensure the tree is fully
clean; these commands snapshot exact HEAD. Do not stash or reset user changes.
Read `mode` first. If it is still `configured` and the user has not selected
another profile, use `--mode quick` for Claude-first delegation and review so
the default independent reviewer is Codex Sol.

- `delegate <task-file> [--mode NAME]` starts a Pi coder in an isolated
  worktree at HEAD. Run `work --once --run-id ID`, then read `handoff ID` only
  after verified completion. Inspect the scoped diff and integrate its commit
  range into the main branch yourself. A cherry-pick creates a new SHA, so run
  `verify` on that combined commit before calling it verified.
- `verify <task-file> [--base ANCESTOR] [--mode NAME]` tests the current HEAD
  and calls the selected independent non-Claude reviewer. By default it
  compares with the merge-base of the configured base branch. For work on the
  base branch, pass an exact ancestor with `--base`. Run its ID through
  `work --once --run-id ID`; `handoff ID` gives the tested and reviewed SHA.
  On failure, Claude fixes the source branch, commits, and starts a new verify
  run. Never let a Pi coder repair an external Claude commit.

Only claim verification if `handoff` succeeds for the current exact commit.
If current HEAD has moved since submission, the evidence is for the earlier
SHA; submit a new verify run. Never auto-publish or merge a delegated run.

## Explicit batch run

1. Read `mode` and `progress --json`. Honor billing/auth blockers. If a previous
   submission response was interrupted, inspect existing IDs before resubmitting.
2. Read only relevant source and project instructions. Make one bounded task per
   independently verifiable change. Reuse the current conversation's plan.
3. Generate JSON with exactly `id`, `title`, `instructions`, `paths`, `tests`,
   `risk`. ID: lowercase letters/digits/hyphens, max 40 chars. Paths: narrow,
   relative edit scopes. Tests: nonempty argv arrays of trusted, approved project
   commands. Risk defaults `manual`; it controls merge eligibility, never the
   reviewer model. No dummy tests to satisfy the schema.
4. Briefly state scope, coding/review models, and acceptance commands. Proceed
   when authorized by the user or applicable project instructions. If approval
   is missing, prepare this concrete task before asking. Do not repeatedly ask
   for authorization already given in the conversation.
5. Save JSON in a private temporary file outside tracked files; call `submit
   <task-file>` (optionally the explicitly requested `--mode MODE`). Respect the
   clean tracked tree and configured base branch. If dirty, identify blocking
   files; do not stash, reset, or commit them automatically. Never add `--publish`
   or `--auto-merge` without explicit authorization.
6. Capture the returned ID and run `work --once --run-id RUN_ID` through the
   host's managed long-running command/session facility. Only if the user-wide
   `settings` has `herdr_enabled=true` and this session is inside Herdr with
   `HERDR_ENV=1` and inherited `HERDR_PANE_ID`, append `--planner-pane <that-id>`
   for main-pane progress. Never guess pane IDs. If an existing worker
   owns the lock, inspect its status; do not start competing workers or resubmit.
7. Report meaningful progress in the main chat. Read `progress --json` at useful
   intervals or on request, not every few seconds through model turns. Herdr
   metadata polls locally without model calls; a worker does not automatically
   wake an idle chat. Do not detach using untracked `nohup` or promise persistence
   if the host cannot retain the command session.
8. Read the final snapshot. Report ID, status/stage, coding/review models,
   exact-SHA verification, blocker and next action. Verified is not merged;
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
commits, tests, independent review, retries, and GitHub policy.
