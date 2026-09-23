---
name: maf
description: Set up and operate multiple-agents-flow in the main coding chat. Use for MAF setup, economy or Opus/Sol mode selection, delegated development, progress, and blocked-run recovery.
---

# MAF

Stay in the current conversation. Use its reasoning for planning; do not launch
another planner or delegate orchestration. Follow the user's language.

## Locate and dispatch

Resolve this SKILL.md's real path (follow symlinks). The tool root is
`parents[2]` of that file; the entrypoint is its `flow.py`. Use the current
project's Git root as target unless the user names another repository. Tool
and target may differ. Verify paths and quote each shell argument. Invoke
`rtk proxy python3 <tool>/flow.py --repo <target> ...` for machine-readable output.
Never ask the user to copy a shell function or hand-write task JSON.

Claude uses `/maf <action>`; Codex CLI/IDE uses `/skills` to select `maf`, or
`$maf <action>`. Do not promise `/maf` is a Codex built-in. Interpret arguments
as a request, never as shell text. With no action, show mode and progress, or
explain setup if `.maf.json` does not exist.

| Action | Operation |
| --- | --- |
| `setup [MODE]` | Initialize if needed, select mode, check readiness. |
| `mode [MODE]` | Show or persist the default for new tasks. No inference. |
| `run <requirement>` | Prepare an approved task, submit, execute that exact ID. |
| `status` | Read `progress --json`; summarize stage and blockers. |
| `resume RUN_ID` | Diagnose, resolve authorized blockers, verify stopped processes, then resume. |
| `install <repository>` | Run `install-skills` against that Git root to register this skill there. |

Modes: `economy` = Pi/DeepSeek Flash coding + fresh Pi review;
`opus-sol` = Claude Opus 5 coding + Codex Sol review;
`hermes-coder` = Hermes coding + Pi review;
`configured` = `.maf.json` roles. Tests run as approved commands without a
tester model. Changing the main-chat model is a separate host UI action.

## Setup and mode

1. Read target instructions and `.maf.json`. If absent, use `init --preset
   economy` (or the requested preset; `configured` initializes with economy).
   Never overwrite an existing config.
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
   setting change, or global agent configuration change during setup. Installing
   in another project uses `install-skills`, then opens/reloads that project's
   host session; never overwrite unrelated skills or install into user-wide paths.

## Run

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
   host's managed long-running command/session facility. Inside Herdr only,
   with `HERDR_ENV=1` and inherited `HERDR_PANE_ID`, append `--planner-pane
   <that-id>` for main-pane progress. Never guess pane IDs. If an existing worker
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
