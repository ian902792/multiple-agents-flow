# v0.1 implementation contract

Python 3.11+ stdlib. Optional local-only web UI; no API subscription proxy or automatic installation.
Herdr runs a persistent ordinary supervisor command in an explicitly created workspace.
Native agent CLIs run as bounded subprocesses, with structured output captured to private logs.
One implementation lane initially; planner/coder/reviewer are independently configured roles.
The economy preset uses Astra for optional planning and Pi/DeepSeek for coding and review, with one repair.
The opus-sol preset uses Claude Opus 5 coding and Codex Sol review. Risk never overrides the reviewer role.
Claude is the main developer. Only the manually invoked `/maf-plan` skill calls the read-only Codex planner.

## Files and ownership

- `maf/agents.py`: runtime adapters and result parsing (Codex, Claude, Pi, Hermes).
- `maf/core.py`: config/task validation, atomic state, worktree, stage machine, tests.
- `maf/github.py`: publication and conservative exact-SHA merge policy.
- `maf/progress.py`: read-only terminal summary, optional Herdr pane metadata, todo.md checklist projection.
- `maf/cli.py`: CLI and Herdr launcher.
- `maf/flows.py`: named, project-private role profiles; `.maf.json` remains policy.
- `maf/ui.py` and `maf/static/index.html`: loopback-only flow editor and read-only run table.
- `maf/skills.py`: project-only Claude/Codex discovery links; refuses conflicting skills and redirected parents.
- `skills/maf/SKILL.md`: shared main-chat workflow, referenced by both hosts using relative symlinks.
- `skills/maf-plan/SKILL.md`: Claude manual-only planner entrypoint.
- `tests/`: stdlib unittest, fake subprocesses and temporary Git repositories, no model charges.
- `README.md`: Traditional Chinese quickstart, walkthrough, safety and recovery.

## Agent adapter contract

`run_agent(role: dict, prompt: str, cwd: Path, log: Path, timeout: int) -> dict`

Return keys: `status` (`ok`, `quota`, `blocked`, `error`), `text` (final response only),
`session_id` (string or null), `usage` (provider-reported dict or null), `detail` (brief).
No implicit latest-session resume. Reviewer is a new session every time.
Pi usage sums assistant message_end usage across all model calls, excluding agent_end copies. Missing or
truncated counts remain unknown; cache and reasoning counters are not added again to output/total.
Timeout results retain only usage already emitted, not an estimate of unreported usage.
`role` fields: `runtime`, `model`, `provider`, optional `profile`, `access` (`read`/`edit`).
Optional `effort`: low/medium/high. Model IDs are configurable but cannot contain provider prefixes.
Allowed subscription routes: Codex ChatGPT login; Claude first-party subscription login;
Pi OpenCode Go; Hermes explicitly OpenCode Go. No arbitrary commands, CLI extra args or endpoints.
Hermes currently supports coder/edit only, with native safe mode and file toolset. The shipped
alternative is `hermes-coder`, not a misleading full-Hermes preset that cannot constrain a reviewer.
Codex uses JSONL, Claude JSON, Pi JSONL; Hermes stream JSON shape must be verified before declaring support.
Adapters must not mistake exit code 0 for a successful model turn (especially quota/error events).
Pi 0.85.1 的最後 assistant 必須 `stop` 且其後有本輪最終 `agent_settled`；舊 settled 或
低層 `agent_end`（可能早於 retries）不能證明完成。Claude `--restricted --safe-mode` 停用自動
CLAUDE.md／skills／plugins／hooks，保留訂閱 auth 與 permissions；禁止 API-only `--bare`。
Pi 停用自動 extensions／skills／prompt templates／context files；明確 AGENTS／task 指示仍有效，
需要的技能與上下文由任務明確提供。Claude monthly spend limit／session limit 為 quota；原生
is_error quota 優先於附帶 permission_denials，其他權限拒絕仍 blocked，不改 billing 或猜測 reset。
No YOLO, no automatic API fallback. Scrub conflicting API/provider environment overrides from children.
Never print/read credentials. Auth status checks can inspect safe CLI status output only.
Bounded subprocess timeouts terminate their own process group; do not kill unrelated agents.

## State and CLI

Tracked `.maf.json` holds roles and policy. Untracked `.maf-local.json` holds a human's
confirmation that provider extra usage / Go Use balance are disabled. This is attestation,
not a remotely enforceable spending cap. `config_hashes` remembers each explicitly confirmed effective
configuration. A former singular `config_hash` is not accepted or migrated into approval.
No model invocation until the exact execution configuration is confirmed.
`maf/mode.json` under the common Git directory stores the local default mode, initially `configured`.
`maf/flows.json` in the same private directory stores editable named flows; built-in `quick` and `planned`
are available without writing that file. Import/export uses explicit JSON, never user-wide configuration.
Named modes replace only roles; policy/timeouts stay in `.maf.json`. Submit snapshots the effective config
and selected mode, with `config_hash` separately binding the base `.maf.json`. Changing selection never
rewrites a run or invalidates its verification; changing base configuration still invalidates existing runs.
Runs without an explicit supported mode cannot replay models under the new routing rules; inspect and
submit a new task instead. Existing evidence remains readable, with no migration or silent role substitution.
Private state under the repository's common Git directory `maf/runs/<id>`; atomic JSON and flock.
Worktrees under the target repository `.maf-worktrees/`, excluded through Git info/exclude;
never under `.git`, because native agent safety modes correctly deny edits there.
Task JSON: `id`, `title`, `instructions`, `paths` (explicit relative path/glob allowlist),
`tests` (nonempty arrays of argv arrays), `risk` (`manual`, `docs`, `style`, `tests`).
Task/config snapshots pin each run. Worktrees and branches are unique; never overwrite/reuse unrelated ones.

Commands: `install-skills`, `init`, `mode`, `flows`, `flow-save`, `ui`, `doctor`, `confirm-billing`, `plan`,
`submit`, `delegate`, `verify`, `work`, `status`, `handoff`, `progress`, `resume`, `publish`, `merge`, `herdr`.
`submit` only queues. `work --once` executes one runnable task; `work` polls local state.
`submit --mode NAME` overrides the mode for one task without changing the local default.
`work --once --run-id ID` processes only that run, never another queued task and never implicitly replays
an interrupted stage. The skill uses this form after submit/resume. Selection changes still use the writer lock.
`install-skills` registers one shared skill in `.agents/skills/maf` and `.claude/skills/maf` in a Git repository,
plus manual-only `.claude/skills/maf-plan`; never user-wide configuration. External-repo registration paths are locally excluded from Git.
Execution: queued -> coding -> testing -> reviewing -> verified -> PR / needs-human / merged.
`delegate` snapshots a fully clean current branch HEAD, runs a Pi coder in a new worktree, then tests/reviews
the resulting commit. It never integrates the result into the source branch. `verify` snapshots a fully clean
current HEAD, checks the changed paths against an exact base/merge-base, and starts at testing without a coder.
Failed tests or review of external work stop for Claude to fix and require a new run at the new SHA. `handoff`
returns compact evidence only after tests, independent approval and the worktree HEAD all match.
Every agent stage records a running checkpoint BEFORE invocation, with an activity label,
start time, timeout (including up to 60 seconds for auth), and diagnostic log path.
Each test command records its own activity checkpoint. Agent attempts also record provider and elapsed time.
Authentication is checked once by the adapter, not again by the supervisor. An interrupted/ambiguous stage
requires explicit recovery acknowledgement; never blindly resend. Quota waits remain pinned
to the same role; default requires user-supplied reset time before automatic retry.
Bounded repair rounds, separate reviewer, exact tested SHA, clean tree required after verification.
Planner outputs a plan for human inspection; its output cannot silently authorize task execution.

## Progress and checklist

`progress [--watch] [--poll N] [--planner-pane ID] [--sync]` reads run state without the writer lock
and without any model call. Completed candidates also pass the current evidence gate and bounded local Git
reads (`core.verified`); matching saved SHAs alone never suffice. It shows stage/status, tested and reviewed SHAs, and `verified` and `merged`
as separate columns; corrupt runs are listed, not skipped. Titles and feedback are stripped of control
characters before printing. `--watch` prints only on change, sleeps the bounded poll interval, and exits
cleanly on Ctrl-C. `--planner-pane` requires `HERDR_ENV=1` and an explicit live pane id verified with
`herdr pane get`; each poll runs `herdr pane report-metadata PANE --source maf-progress --title TEXT
--ttl-ms TTL` (max of 15000 and `(poll + 15) * 1000`) to renew the TTL even when the display is unchanged.
Titles include verified/total and active stage/task. A disappearing pane disables metadata with a warning.
TTY widths below 100 use multiple lines wrapped to terminal width, including 38 columns; pipes retain the table.
No input is sent and no agent
lifecycle is touched; Herdr failures are warnings only.
`progress --json` is a standalone read-only snapshot with activity, minute-level elapsed/limit, attention,
next steps and per-attempt native usage; no prompt or transcript. It cannot be combined with sync/watch/pane.
Deadlines overdue by more than 15 seconds request inspection, not an inferred exit or permission to retry.
Permission/auth stops, quota resets, exhausted repairs and publication recovery have distinct guidance.
`herdr` validates the inherited HERDR_PANE_ID before creating its workspace and passes it to
`work --planner-pane ID`. A local monitor thread reuses progress.show every five seconds while the worker
holds the writer lock. It refreshes the main pane's metadata without injecting prompts or invoking models.
The observer stops with the worker; no additional per-agent panes or streaming transcripts are needed.
Successful test logs stay in local evidence; review prompts carry only argv, exit_code and log path.

Checklist: a task opts in when the tracked, regular root `todo.md` has exactly one unchecked line
`- [ ] text <!-- maf:task-id -->`. `submit` snapshots that full line before any agent runs (`run.checklist`);
no marker means no integration, and runs without a snapshot need no migration. Task `paths` must not
cover `todo.md` (no coder self-signoff); symlinks, untracked files and duplicate markers are rejected.
After `process` returns, and on explicit `progress --sync` under the writer lock, a run whose status is
past independent review (`verified`/`publishing`/`pr`/`merging`/`merged`, or `needs_human` only at one of those
completed stages), whose full configured test list all passed, whose
review approves the tested SHA and whose worktree HEAD still equals it (`core.verified`) has the exact
snapshotted line replaced by `[x]` in the ROOT `todo.md`; all other bytes are preserved and the write is an
atomic replace that refuses symlinks. A missing, edited or duplicated line fails closed with a visible
warning; the outcome (`marked`, `already`, `failed` + detail) is recorded in `run.checklist.synced` without
touching status/stage or replaying agents. Retry is idempotent. Nothing is ever unchecked automatically.
同 task-id 的任何重複 marker 都拒絕，包括不同描述與已勾選行。寫入時再次確認 todo 已追蹤、
根目錄位於設定 base branch；暫存內容 flush 後，在 os.replace 前立即重查一般檔案 identity／內容。
未共用 writer lock 的編輯器仍可能在最後檢查與 replace 之間競爭，這個剩餘競態無法由 rename 消除。
Git timeout／state-save OSError 只產生已清理控制字元的警告，保留 verified 狀態與原測試／審查證據。
A checked box means tested and independently reviewed on the run worktree; it does NOT mean merged or
released. The root `todo.md` becomes intentionally dirty: commit that progress record before the next
`submit`; the clean-tree and merge checks are not relaxed.

## GitHub

Push only owned branch without force. Reconcile existing PR after uncertain network outcomes.
Default create draft PR. Publish on explicit command; automatic publication is an explicit
per-submission flag. Auto merge is opt-in per task and requires nonempty approved path policy.
Run tests on final commit; review attests same commit; base must still match remote base.
Required GitHub checks must pass (pending/failed/unknown block); no `--admin`, no bypass.
General docs/static CSS/test-addition categories only; protected files deny before allow.
AGENTS/CLAUDE/SOUL, workflow/policy, CI, dependencies, auth, finance/trading never low risk.
Test removals/modifications are manual; v0.1 auto merge supports NEW isolated test files only.
No auto merge based solely on model-supplied risk or completion text.

## Acceptance

Offline fake-agent end-to-end coding -> command tests -> independent review -> verified.
Recovery, quota, invalid reviewer JSON, stale commit, path escape, policy changes, empty tests,
failed checks, base movement, and duplicate publication covered by runnable tests.
Real subscription smoke only after billing confirmation. No claim that fake tests establish
live provider, screenshot, or GitHub branch-protection behavior.
