# v0.1 implementation contract

Python 3.11+ stdlib. Local-only web UI edits user-wide flows and settings; no API subscription proxy.
Herdr is opt-in and runs a persistent ordinary supervisor command in an explicitly created workspace.
Native agent CLIs run as bounded subprocesses, with structured output captured to private logs.
Independent Pi, Antigravity or Codex delegates can occupy up to three execution lanes; planner/coder/reviewer are independently configured roles.
The economy preset uses Astra for optional planning and Pi/DeepSeek for coding, with one repair. The opus-sol preset uses Claude Opus 5.5 coding and a configured Codex Sol reviewer. Independent review is disabled until explicitly enabled in the selected flow.
The main chat is the developer. Only the manually invoked `/maf-plan` (Claude) or `$maf-plan` (Codex) skill calls the read-only planner, and `plan` refuses a planner whose runtime equals `--main` (Claude main: Codex planner; `codex-pi`: Claude Opus 5.5 planner).

## Retry

`retry RUN_ID [--note]` accepts a delegate that is `needs_human` or `waiting_quota` and not yet superseded. It submits
the same frozen task (same mode, same `depends_on`, same `plan_id`) with the previous feedback, up to two failing test
tails and the note appended to the instructions, marks the old run `superseded_by`, and re-points dependents that wait
on the old run (or failed at stage `dependency` because of it) to the new run, recomputing their approval scope hash:
their approved task is unchanged, only the identical delegate they start from is replaced. `report` hides superseded
runs. Plan tasks carry the plan's interface contracts in their instructions. A Codex coder is asked to run the task's
tests inside its sandbox before finishing; the supervisor still reruns them.

## Versioning

`maf/__init__.py` holds the only `__version__` (semantic versioning). `flow.py --version` and `doctor` print it with the
checkout commit, and each run records `maf_version` at submit. `CHANGELOG.md` must lead with the same version (tested);
pushing tag `vX.Y.Z` runs `.github/workflows/release.yml`, which checks the tag against `__version__`, runs the offline
tests and creates the GitHub release from that CHANGELOG section (`scripts/changelog.py`).

## Files and ownership

- `maf/agents.py`: runtime adapters and result parsing (Codex, Claude, Pi, Hermes, Antigravity).
- `maf/core.py`: config/task validation, atomic state, worktree, stage machine, tests.
- `maf/github.py`: publication and conservative exact-SHA merge policy.
- `maf/progress.py`: read-only terminal summary, optional Herdr pane metadata, todo.md checklist projection.
- `maf/cli.py`: CLI and Herdr launcher.
- `maf/flows.py`: user-wide named role profiles, default flow and Herdr setting; `.maf.json` is optional project policy.
- `maf/ui.py` and `maf/static/index.html`: loopback-only flow, default and integration settings editor; `maf/static/guide.html` separately explains setup, commands and design. No project mode switching or run control.
- `maf/skills.py`: one-time user-wide Claude/Codex discovery links; refuses conflicting skills and redirected parents.
- `skills/maf/SKILL.md`: shared main-chat workflow, referenced by both hosts using relative symlinks.
- `skills/maf-plan/SKILL.md`: manual-only planner entrypoint for both hosts; `agents/openai.yaml` disables implicit Codex invocation.
- `tests/`: stdlib unittest, fake subprocesses and temporary Git repositories, no model charges.
- `README.md`: human-oriented Traditional Chinese overview and quickstart.
- `docs/CLI.md`: direct commands, task format, approval and recovery reference.
- `docs/AGENT-INSTRUCTIONS.md`: optional personal Claude instruction template.

## Agent adapter contract

`run_agent(role: dict, prompt: str, cwd: Path, log: Path, timeout: int, *, live_log: Path | None = None) -> dict`

Return keys: `status` (`ok`, `quota`, `blocked`, `error`), `text` (final response only),
`session_id` (string or null), `usage` (provider-reported dict or null), `detail` (brief).
No implicit latest-session resume. Reviewer is a new session every time.
Pi usage sums assistant message_end usage across all model calls, excluding agent_end copies. Missing or
truncated counts remain unknown; cache and reasoning counters are not added again to output/total.
Timeout results retain only usage already emitted, not an estimate of unreported usage.
`role` fields: `runtime`, `model`, `provider`, optional `profile`, `access` (`read`/`edit`). Reviewer alone may carry boolean `enabled`; missing means disabled.
Optional `effort` follows each CLI: Codex and Claude low/medium/high/xhigh/max; Pi off/minimal/low/medium/high/xhigh/max (Pi 0.86.1 `--thinking`); Hermes and Antigravity low/medium/high; an Antigravity model ID ending in -low/-medium/-high must match its effort, because agy rejects a mismatched --model/--effort pair. Model IDs are configurable but cannot contain provider prefixes.
Allowed subscription routes: Codex ChatGPT login; Claude first-party subscription login;
Pi OpenCode Go; Hermes explicitly OpenCode Go; Antigravity signed-in Google account. No arbitrary CLI extra args or endpoints.
Hermes and Antigravity support coder/edit only. Antigravity uses `agy` NDJSON stdin/stdout,
`--sandbox`, `--mode accept-edits`, and a pinned model/effort. Before inference it rejects
`modelProvider` API-key routing and preapproved CLI tools, and checks `agy models` for the exact
model. Its terminal `result` must be `SUCCESS` and its `init.permission_mode` must be
`request-review`. Headless Antigravity has no native file-only tool list; the worker asks it
to use file tools, runs trusted repositories only, and independently checks changed paths.
Hermes uses native safe mode and file toolset. The shipped
alternative is `hermes-coder`, not a misleading full-Hermes preset that cannot constrain a reviewer.
Codex, Claude, Pi and Antigravity use JSONL; Hermes stream JSON shape must be verified before declaring support.
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

Optional tracked `.maf.json` holds project roles and policy. Without it, built-in policy chooses
local `main`, then `master`, then the current branch as base. Global `billing.json` holds a human's
confirmation that provider extra usage / Go Use balance are disabled for each active role/model set. Effort is excluded from that set: it changes how long a model thinks, not how it is billed. A disabled reviewer does not participate in billing checks or doctor auth checks.
This is attestation, not a remotely enforceable spending cap. No model invocation until that
role/model set is confirmed. Project policy changes still invalidate existing runs, but do not
require billing reconfirmation if model routes are unchanged.
`maf/mode.json` under the common Git directory stores an optional project override. Without it,
new work uses the global default flow. `mode default` removes the override.
`$XDG_CONFIG_HOME/multiple-agents-flow/flows.json` (default `~/.config/multiple-agents-flow/flows.json`)
stores editable user-wide named flows; built-in `quick`, `quick-antigravity`, `quick-codex`, `planned` and `codex-pi` are available without writing that file.
The adjacent `settings.json` holds `default_flow` (default `quick`) and `herdr_enabled` (default false). Import/export uses explicit JSON.
Named modes replace only roles; policy/timeouts stay in the optional `.maf.json` or built-in defaults. Submit snapshots the effective config
and selected mode, with `config_hash` separately binding the project policy. Changing selection never
rewrites a run or invalidates its verification; changing base configuration still invalidates existing runs.
Runs without an explicit supported mode cannot replay models under the new routing rules; inspect and
submit a new task instead. Existing evidence remains readable, with no migration or silent role substitution.
Private state under the repository's common Git directory `maf/runs/<id>`; atomic JSON and flock.
Worktrees under the target repository `.maf-worktrees/`, excluded through Git info/exclude;
never under `.git`, because native agent safety modes correctly deny edits there.
Task JSON: `id`, `title`, `instructions`, `paths` (explicit relative path/glob allowlist),
`tests` (nonempty arrays of argv arrays), `risk` (`manual`, `docs`, `style`, `tests`), and optional
boolean `independent` for Pi, Antigravity or Codex delegates.
Optional `acceptance_why` states the purpose tests must protect; it reaches coder and reviewer via the task JSON.
`handoff` also returns `coder_notes`, the tail of the coder's final reply ending in `UNVERIFIED:` items.
Task/config snapshots pin each run. Worktrees and branches are unique; never overwrite/reuse unrelated ones.

Commands: `install-skills`, `settings`, `init`, `mode`, `flows`, `flow-save`, `ui`, `doctor`, `confirm-billing`, `plan`,
`submit`, `delegate`, `verify`, `approve`, `work`, `status`, `handoff`, `progress`, `resume`, `publish`, `merge`, `herdr`.
`submit` only queues. `work --once` executes one runnable task or one parallel wave of eligible lightweight
delegates; with repeated `--run-id`, it drains those IDs once each. `work` polls local state.
`submit --mode NAME` overrides the mode for one task without changing the local default.
`work --once --run-id ID` processes only that run; repeating `--run-id` names a bounded set without
consuming other queued tasks. Interrupted stages are never implicitly replayed. `--delegate-concurrency N`
sets the Pi/Antigravity delegate limit from 1 to 3 (default 3). The skill uses explicit IDs after delegation.
Selection changes still use the repository writer lock.
`delegate --depends-on RUN_ID` records `depends_on` (a delegate run) and leaves base/source unset and no worktree:
status `awaiting_approval` or `waiting_dependency`. Its approval scope binds `depends_on` instead of base/source.
Each worker pass advances waiting runs: once the dependency passes the evidence gate (`tested`/`verified`), the
worktree is created from that tested SHA and base/source/owned head are set to it; a dependency at stage
`replan`/`external_fix`/`dependency` or corrupt marks the run `needs_human` at stage `dependency`, which resume
rejects. Queued, running, quota-waiting or resumable dependencies keep it waiting. `report [--hours N] [--json]`
is a read-only summary grouped by attention, with dependency chains and `source..tested` integration ranges for
fully completed delegate chains.
`night FILE … [+ FILE …] [--approve]` queues each list as a chain (`queue_chains`), approving frozen scopes only
with `--approve`, then `run_until_settled` repeats a one-at-a-time `work --once` over those IDs until none is
queued or running and no confirmed quota reset is pending, and prints the report. Report text is Chinese.
`install-skills` registers one shared skill in the user's `~/.agents/skills/maf` and `~/.claude/skills/maf`,
plus manual-only `maf-plan` in both `~/.agents/skills` and `~/.claude/skills`. Global commands, including default-flow billing confirmation, work outside a Git repository; `mode` remains per repository.
Execution: awaiting_approval (when required) -> queued -> coding -> testing -> `tested` when review is off, or reviewing -> `verified` when review is on. Publishing requires the latter.
The frozen task/config/mode/kind/source SHA/publication flags are hashed at submit. Sensitive/broad edit
paths, shell tests and manual-risk batch runs wait for `approve RUN_ID`; callers can explicitly request the
gate for semantic high-risk work. Approval checks the pristine worktree and exact frozen scope once before
release. The worker ignores pending runs and rechecks the scope hash before execution/publication. Bounded
repair within that scope needs no new approval. A coder escalation or reviewer manual-risk finding stops
at `needs_human/replan`; resume cannot silently replay it. A changed scope requires a new run.
`delegate` snapshots a fully clean current branch HEAD, runs the selected Pi, Antigravity or Codex coder in a new worktree, then tests and optionally reviews
the resulting commit. It never integrates the result into the source branch. `verify` snapshots a fully clean
current HEAD, checks the changed paths against an exact base/merge-base, and starts at testing without a coder.
Failed tests or review of external work stop for Claude to fix and require a new run at the new SHA. `handoff`
returns compact evidence only after the selected checks and worktree HEAD match; its `review` value is null when review is off.
The scheduler runs up to three `independent: true` Pi, Antigravity or Codex delegates at once. Parallel eligibility
requires narrow literal file paths, disjoint paths (case-insensitive comparison), the same source SHA,
non-manual risk and no approval gate. An explicit marker is the caller's assertion that requirements and
test resources are independent; the scheduler cannot infer semantic independence. Other runs remain serial.
One worker lock prevents competing supervisors; the repository writer lock protects queue selection and
serial execution, then is released during parallel delegate execution so more work can be submitted.
Per-run locks prevent resume/publication of a run while its parallel worker is active. Worker interruption
stops new scheduling and waits for active delegates to reach a safe checkpoint before exiting.
After each test command MAF kills that command's whole process group, and after each agent attempt and each
test pass it kills orphaned processes (parent pid 1) whose working directory is still inside the run's worktree;
the count is recorded as `reaped_orphans`. A person's shell in the worktree has a live parent and is never touched.
`work` without `--once` exits once none of the selected runs (or, without `--run-id`, no run at all) can progress
without a person (`can_progress`: queued, running, a confirmed quota reset, an auto-merge PR check, or a dependency
that can itself progress); `night` relies on the same rule. A caller running it in the background is therefore
always notified instead of waiting on an idle loop. Only `work --daemon`, used by the Herdr supervisor, keeps
polling for new submissions.
`night` computes `approval_reasons` for every task before queueing and, without `--approve`, refuses with the whole
list. Preflight treats a command argument that is missing at HEAD but inside the chain's editable paths so far as an
expected failure. `night --integrate` then calls `integrate`: with a clean tree, it cherry-picks each fully tested
chain's `base..tested` range onto the current branch (a conflicting chain is aborted and reset to the commit before
it), submits one verify run over the union of paths and tests with base = the pre-integration HEAD, approves it only
under `--approve`, and runs it to completion.
Every agent stage records a running checkpoint BEFORE invocation, with an activity label,
start time, timeout (including up to 60 seconds for auth), and diagnostic log path.
Each test command records its own activity checkpoint. Agent attempts also record provider and elapsed time.
Authentication is checked once by the adapter, not again by the supervisor. An interrupted/ambiguous stage
requires explicit recovery acknowledgement; never blindly resend. Quota waits remain pinned
to the same role; default requires user-supplied reset time before automatic retry.
Bounded repair rounds, optional separate reviewer, exact tested SHA, clean tree required after completion.
Planner outputs a plan for human inspection; its output cannot silently authorize task execution. `plan` asks for one JSON object
(version, goal, interfaces, main_agent, decisions, chains, risks); `maf/plans.py` validates every task with the task
schema, rejects duplicate ids and unknown decision blocks, and stores `plans/<plan-id>/plan.json` plus a Chinese
`plan.md` in private state. An invalid reply stores nothing runnable. `decide` records answers; `night --plan` refuses
while any answer is null, then preflights each distinct acceptance argv once at HEAD in a throwaway detached worktree
(clean env, test timeout, no model): a pass is a warning, a command that cannot start or times out stops the plan.
Settled decisions are appended to the instructions of the tasks they block before `queue_chains`.

## Progress and checklist

`progress [--watch] [--poll N] [--planner-pane ID] [--sync]` reads run state without the writer lock
and without any model call. Completed candidates also pass the current evidence gate and bounded local Git
reads (`core.tested` or `core.verified`); matching saved SHAs alone never suffice. It shows stage/status, tested and reviewed SHAs, and `verified` and `merged`
as separate columns; corrupt runs are listed, not skipped. Titles and feedback are stripped of control
characters before printing. `--watch` prints only on change, sleeps the bounded poll interval, and exits
cleanly on Ctrl-C. `--planner-pane` requires `HERDR_ENV=1` and an explicit live pane id verified with
`herdr pane get`; each poll runs `herdr pane report-metadata PANE --source maf-progress --title TEXT
--ttl-ms TTL` (max of 15000 and `(poll + 15) * 1000`) to renew the TTL even when the display is unchanged.
Titles include completed/total, the concurrent running count when greater than one, and an active stage/task. A disappearing pane disables metadata with a warning.
TTY widths below 100 use multiple lines wrapped to terminal width, including 38 columns; pipes retain the table.
No input is sent and no agent
lifecycle is touched; Herdr failures are warnings only.
`progress --json` is a standalone read-only snapshot with activity, minute-level elapsed/limit, attention,
next steps and per-attempt native usage plus `cache_hit` (cached ÷ all prompt tokens, from each provider's own fields: Pi cacheRead/input/cacheWrite, Claude cache_read/input/cache_creation, Codex cached_input_tokens within input_tokens, Antigravity cache_read_tokens beside input_tokens; null when any count is missing); no prompt or transcript. `handoff` carries the same per-attempt `cache_hit`. It cannot be combined with sync/watch/pane.
Deadlines overdue by more than 15 seconds request inspection, not an inferred exit or permission to retry.
Permission/auth stops, quota resets, exhausted repairs and publication recovery have distinct guidance.
`herdr` validates the inherited HERDR_PANE_ID before creating its workspace and passes it to
`work --planner-pane ID --agent-panes`. A local monitor thread reuses progress.show every five seconds while the worker
runs. It refreshes the main pane's metadata without injecting prompts or invoking models.
For each active coder/reviewer (and an explicitly invoked planner inside Herdr), MAF splits a no-focus pane
from its own Herdr pane, labels it, and runs the private `live-view` observer. The adapter tees native
stdout into a private live event file while retaining its bounded parser and final evidence log.
The observer (`LiveSummary`) prints one line per tool call: the tool name, the repo-relative path it touches when that path stays inside the worktree, and seconds since the previous step, plus a done/error line. Streaming message events are skipped; prompts, model text, file contents, search patterns and shell commands are never shown. Only the pane ID
returned by that split is closed after the role finishes; pane failures warn without replaying the agent.
Agents still run as supervisor-owned subprocesses; Herdr's agent lifecycle display is not verification.
Parallel Pi, Antigravity or Codex delegates can show multiple observer panes at once. A manually invoked `work` needs
`--agent-panes` to opt in; plain `work` keeps its previous terminal behavior.
Successful test logs stay in local evidence; review prompts carry only argv, exit_code and log path.

Checklist: a task opts in when the tracked, regular root `todo.md` has exactly one unchecked line
`- [ ] text <!-- maf:task-id -->`. `submit` snapshots that full line before any agent runs (`run.checklist`);
no marker means no integration, and runs without a snapshot need no migration. Task `paths` must not
cover `todo.md` (no coder self-signoff); symlinks, untracked files and duplicate markers are rejected.
After `process` returns, and on explicit `progress --sync` under the writer lock, a run whose status is
`tested` or past independent review (`verified`/`publishing`/`pr`/`merging`/`merged`, or `needs_human` only at a
completed stage), whose full configured test list all passed, and whose worktree HEAD still equals the
tested SHA (`core.tested`), plus an approving review of that SHA when enabled (`core.verified`), has the exact
snapshotted line replaced by `[x]` in the ROOT `todo.md`; all other bytes are preserved and the write is an
atomic replace that refuses symlinks. A missing, edited or duplicated line fails closed with a visible
warning; the outcome (`marked`, `already`, `failed` + detail) is recorded in `run.checklist.synced` without
touching status/stage or replaying agents. Retry is idempotent. Nothing is ever unchecked automatically.
同 task-id 的任何重複 marker 都拒絕，包括不同描述與已勾選行。寫入時再次確認 todo 已追蹤、
根目錄位於設定 base branch；暫存內容 flush 後，在 os.replace 前立即重查一般檔案 identity／內容。
未共用 writer lock 的編輯器仍可能在最後檢查與 replace 之間競爭，這個剩餘競態無法由 rename 消除。
Git timeout／state-save OSError 只產生已清理控制字元的警告，保留完成狀態與原測試／可選審查證據。
A checked box means the selected test/review checks passed on the run worktree; it does NOT mean merged or
released. The root `todo.md` becomes intentionally dirty: commit that progress record before the next
`submit`; the clean-tree and merge checks are not relaxed.

## GitHub

Push only owned branch without force. Reconcile existing PR after uncertain network outcomes.
Default create draft PR. Publish on explicit command; automatic publication is an explicit
per-submission flag. Auto merge is opt-in per task and requires nonempty approved path policy.
Publishing requires enabled independent review. Run tests on final commit; review attests same commit; base must still match remote base.
Required GitHub checks must pass (pending/failed/unknown block); no `--admin`, no bypass.
General docs/static CSS/test-addition categories only; protected files deny before allow.
AGENTS/CLAUDE/SOUL, workflow/policy, CI, dependencies, auth, finance/trading never low risk.
Test removals/modifications are manual; v0.1 auto merge supports NEW isolated test files only.
No auto merge based solely on model-supplied risk or completion text.

## Acceptance

Offline fake-agent end-to-end coding -> command tests -> tested, or optional independent review -> verified.
Recovery, quota, invalid reviewer JSON, stale commit, path escape, policy changes, empty tests,
failed checks, base movement, and duplicate publication covered by runnable tests.
Real subscription smoke only after billing confirmation. No claim that fake tests establish
live provider, screenshot, or GitHub branch-protection behavior.
