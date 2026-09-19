# v0.1 implementation contract

Python 3.11+ stdlib. No server, web UI, API subscription proxy, or automatic installation.
Herdr runs a persistent ordinary supervisor command in an explicitly created workspace.
Native agent CLIs run as bounded subprocesses, with structured output captured to private logs.
One implementation lane initially; planner/coder/reviewer are independently configured roles.

## Files and ownership

- `maf/agents.py`: runtime adapters and result parsing (Codex, Claude, Pi, Hermes).
- `maf/core.py`: config/task validation, atomic state, worktree, stage machine, tests.
- `maf/github.py`: publication and conservative exact-SHA merge policy.
- `maf/progress.py`: read-only terminal summary, optional Herdr pane metadata, todo.md checklist projection.
- `maf/cli.py`: CLI and Herdr launcher.
- `tests/`: stdlib unittest, fake subprocesses and temporary Git repositories, no model charges.
- `README.md`: Traditional Chinese quickstart, walkthrough, safety and recovery.

## Agent adapter contract

`run_agent(role: dict, prompt: str, cwd: Path, log: Path, timeout: int) -> dict`

Return keys: `status` (`ok`, `quota`, `blocked`, `error`), `text` (final response only),
`session_id` (string or null), `usage` (provider-reported dict or null), `detail` (brief).
No implicit latest-session resume. Reviewer is a new session every time.
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
not a remotely enforceable spending cap. No model invocation until it exists.
Private state under the repository's common Git directory `maf/runs/<id>`; atomic JSON and flock.
Worktrees under the target repository `.maf-worktrees/`, excluded through Git info/exclude;
never under `.git`, because native agent safety modes correctly deny edits there.
Task JSON: `id`, `title`, `instructions`, `paths` (explicit relative path/glob allowlist),
`tests` (nonempty arrays of argv arrays), `risk` (`manual`, `docs`, `style`, `tests`).
Task/config snapshots pin each run. Worktrees and branches are unique; never overwrite/reuse unrelated ones.

Commands: `init`, `doctor`, `confirm-billing`, `plan`, `submit`, `work`, `status`, `progress`, `resume`,
`publish`, `merge`, `herdr` (launch work in new no-focus Herdr workspace).
`submit` only queues. `work --once` executes one runnable task; `work` polls local state.
Execution: queued -> coding -> testing -> reviewing -> verified -> PR / needs-human / merged.
Every agent stage records a running checkpoint BEFORE invocation. An interrupted/ambiguous stage
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
