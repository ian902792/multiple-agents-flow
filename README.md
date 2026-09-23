# multiple-agents-flow

在 Herdr 裡使用不同 agent 完成程式開發：**規畫 → 實作 → 程式測試 → 獨立審查 → PR**。
模型處理需要判斷的工作；Python 處理排程、狀態、驗收與 GitHub。

預設組合：Codex / GPT-6 Astra 按需規畫、Pi / DeepSeek V4.1 Flash 實作與獨立審查。
也可選 Claude Opus 5 實作、Codex Sol 審查。`risk` 控制合併政策，不暗中更換模型。
提供 Claude／Codex 共用 skill，底層使用 Python 3.11+ CLI，零第三方 Python 依賴，macOS/Linux。

## 建議使用方式：在主 agent 呼叫 skill

本專案的 `.claude/skills/maf`、`.agents/skills/maf` 都指向同一份 [MAF skill](skills/maf/SKILL.md)。
在本專案開啟 Claude Code 或 Codex；若既有對話尚未顯示 skill，重新開啟專案對話。

| 操作 | Claude Code | Codex CLI／IDE |
|---|---|---|
| 初次設定 | `/maf setup opus-sol` | `$maf setup opus-sol` |
| 切換省額度組合 | `/maf mode economy` | `$maf mode economy` |
| 切換 Opus＋Sol | `/maf mode opus-sol` | `$maf mode opus-sol` |
| 開發需求 | `/maf run 修正登入表單的空白驗證` | `$maf run 修正登入表單的空白驗證` |
| 查進度與阻塞 | `/maf status` | `$maf status` |
| 處理後恢復 | `/maf resume RUN_ID` | `$maf resume RUN_ID` |
| 在另一個 repo 註冊 | `/maf install /path/to/repo` | `$maf install /path/to/repo` |

Codex 也可以輸入 **`/skills` → 選取 `maf`**，再輸入上述動作；不把 `/maf` 宣稱為 Codex 原生指令。
Claude 的 `/maf` 與 Codex 的 `/skills`／`$maf` 使用方式依據
[Claude 官方文件](https://code.claude.com/docs/en/skills)與
[Codex 官方文件](https://learn.chatgpt.com/docs/build-skills)。其他介面使用該介面的 skill 選擇器。

`run` 讓主 agent 整理任務及驗收指令、自動產生 task JSON、啟動指定任務、回報驗收與阻塞；
不必複製 function 或手寫 JSON。現有授權足夠就執行；欠缺信任／驗收指令授權或訂閱費用確認時才補問。
主任務直接負責規畫，不再額外呼叫 Planner；獨立 Coder、程式測試、獨立 Reviewer 由 supervisor 執行。
Skill 不會改變**目前對話**的模型；你可在 Claude Opus 或 Codex Astra/Sol 的主對話中使用同一份 skill。

| 模式 | Coder | 獨立 Reviewer |
|---|---|---|
| `economy` | Pi / DeepSeek V4.1 Flash | Pi / DeepSeek V4.1 Flash，新 session |
| `opus-sol` | Claude Opus 5，medium | Codex GPT-5.6 Sol，medium |
| `hermes-coder` | Hermes coder / DeepSeek | Pi / DeepSeek |
| `configured` | `.maf.json` 的 coder | `.maf.json` 的 reviewer |

模式只影響**之後提交**的任務，存在 Git 私有狀態，不需要改設定檔再 commit；既有任務保留模型快照。
每種有效設定第一次使用須有人的訂閱確認，之後切回已確認的組合不重問。
設定或合併政策實際改變仍會使舊 run／確認失效。舊版單一 `config_hash` billing 紀錄不會被自動當作新版批准。
沒有明確 mode 快照的舊任務可查看證據，但不可重跑模型；需重新建立任務，避免沿用已移除的隱含角色規則。
只切換模式不呼叫模型；單次任務可用 `submit --mode opus-sol`，不改下次的預設。

Herdr 內執行時會回報主任務 pane；其他環境依主 agent 的命令 session 回報進度。
權限、登入、額度或模糊中斷會停在具體原因，`resume` 先診斷及確認程序停止，不能直接略過。
主對話閒置時不會自動被 worker 喚醒；可用 `status` 取得最新摘要。

想從尚未安裝 skill 的另一個專案直接開始，也可只執行一次：

```sh
rtk proxy python3 /path/to/multiple-agents-flow/flow.py --repo /path/to/repo install-skills
```

這會建立兩個專案內的 symlink，不改使用者全域設定；遇到同名 skill 或 symlink 父目錄會拒絕覆寫。
其他專案的連結加入本機 Git exclude，避免把機器路徑提交出去；移動工具資料夾前需處理這些連結。
以下為底層 CLI 細節，日常可直接使用 skill。

## 先知道的限制

- **只用現有訂閱。** 不切換付費 API、不加購、不自動換 provider。額度耗盡會停等。
- **第一版一條實作線。** 多個任務排隊，不會同時啟動很多昂貴 coder。
- **只操作你信任的 repository。** worktree 不是安全沙箱；專案測試是你批准執行的程式。
- **預設只做到本機驗證。** `--publish` 才授權 push / draft PR；`--auto-merge` 才授權低風險合併。
- **不自動執行 Planner 的輸出。** 你先看過計劃與測試指令，再 submit 任務。
- **不保證無人介入。** 登入、未知額度重置時間、權限、模糊中斷及高風險變更都會停下來。
- CLI 會以非互動模式運作，Herdr 顯示 supervisor 進度；完整輸出保存在本機。不是靠抓取 TUI 畫面判定成功。

## 1. 安裝／準備

先用自己的 GitHub 帳號取得本專案；分享 private repo 前需由擁有者加入 collaborator。

```sh
git clone git@github.com:ian902792/multiple-agents-flow.git
cd multiple-agents-flow
python3 flow.py --help
python3 -m unittest discover -s tests -v
```

工具不會自動安裝或替你登入。先備妥 `git`、Python 3.11+、所選 agent CLI；使用 Herdr / PR 時再需要 `herdr` / `gh`。
Economy 配置需要 `codex login`（ChatGPT）及 Pi 中的 OpenCode Go 登入。
若自行選用 Claude 角色，再使用 `claude auth login`（Claude 訂閱）。
OpenCode Go 可經 Pi 使用，不需要另外安裝 OpenCode CLI。

目前 Pi 0.85.1 必須收到最後 assistant 的 `stop`，以及其後本輪最終 `agent_settled` 才算完成；
`agent_end` 是可能早於重試的底層事件，不算成功。Pi 停用自動 extensions／skills／templates／context files。
Claude 使用 `--restricted --safe-mode`，停用自動 CLAUDE.md／skills／plugins／hooks，但保留訂閱登入與權限檢查；
不使用僅支援 API 的 `--bare`。任務明確提供的 AGENTS／task 指示仍須遵守，需要的技能與上下文須明確指定。

請在供應商控制台確認：

1. Codex / Claude 沒有可自動扣用的超額 credits，未啟用額外用量。
2. OpenCode Go 的 **Use balance** 關閉。
3. 所選模型包含在自己的訂閱中。

程式會移除子程序的 API key／endpoint 環境覆寫並檢查登入路線，但**不能替供應商強制設定費用上限**。
`confirm-billing` 是你的確認紀錄，不是查帳 API；控制台設定改變後請重新核對。
不複製 OAuth token、不建立訂閱轉 API 的代理，也不將憑證寫入專案。

## 2. 在任何專案啟用

以下將 `FLOW` 改成此工具的實際位置；`TARGET` 是要開發的 Git repository。
命令需從 shell 執行，`--repo` 放在子命令**前面**。目標 repo 必須已有第一個 commit。

```sh
FLOW=/absolute/path/multiple-agents-flow/flow.py
TARGET=/absolute/path/your-project

python3 "$FLOW" --repo "$TARGET" init
python3 "$FLOW" --repo "$TARGET" doctor
```

`init` 建立 `.maf.json`，不覆寫既有檔案。先閱讀設定：模型、角色、主分支、timeout、最多修正次數及合併白名單。
`doctor` 只查 CLI／登入，不發出模型推論；尚未確認 billing 時顯示問題是正常的。

```sh
# 僅在完成上述控制台檢查後執行
python3 "$FLOW" --repo "$TARGET" confirm-billing --no-overage
python3 "$FLOW" --repo "$TARGET" doctor
```

建議將 `.maf.json` 加入目標專案版本控制。`.maf-local.json` 是本機確認紀錄，init 會把它加入 Git exclude，不可提交或分享。
**設定修改會使舊 run 失效**；重新確認 billing 並提交新任務，不會讓正在執行的任務偷偷換模型或政策。

## 3. 規畫與提交任務

已經有明確小任務，可以跳過 Planner，省一次強模型呼叫。
大型任務則先寫目標文字檔：

```sh
python3 "$FLOW" --repo "$TARGET" plan --goal-file /absolute/path/goal.md
```

輸出會保存於目標 repo 的 Git 私有狀態區，包含建議拆工、依賴與測試。先由你檢查，再為要執行的任務建立 JSON。
例如：

```json
{
  "id": "document-quickstart",
  "title": "補上本機啟動說明",
  "instructions": "閱讀既有程式與 README，補上可實際執行的啟動與測試指令。只修改 README.md，不推測不存在的指令。",
  "paths": ["README.md"],
  "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]],
  "risk": "docs"
}
```

這裡的測試指令只是 Python 專案範例。**換成該專案真正能驗收需求的指令**，不能用 `true` 之類的空檢查。
`tests` 是 argv 陣列，不是 shell 字串；需要多步驟請用多個陣列或已審查過的專案腳本。
`paths` 使用區分大小寫的 glob（`*` 不跨目錄，`**` 可跨任意層）；請儘量精確列檔案。`risk` 預設應選 `manual`。

```sh
# 只排入佇列，不呼叫模型、不 push
python3 "$FLOW" --repo "$TARGET" submit /absolute/path/task.json

# 執行一個已排隊任務；會印出 run id
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID

# 查看結果
python3 "$FLOW" --repo "$TARGET" status
python3 "$FLOW" --repo "$TARGET" status RUN_ID
```

提交時須位於設定的主分支，已追蹤檔案不可有未提交變更。
任務以 **HEAD 的已提交內容**建立獨立 worktree；主資料夾的未追蹤檔案不會被帶入。
每個階段保存狀態；測試失敗或審查要求修改時，預設最多再修正一輪（可設 0–5），仍失敗就交回主控診斷。
Reviewer 每次是新 session；不得由 Coder 自己批准自己的變更。

## 4. 在 Herdr 長時間執行

在 Herdr pane 內執行：

```sh
python3 "$FLOW" --repo "$TARGET" herdr
```

會建立新的背景 workspace／pane，保留目前焦點，啟動持續處理佇列的 supervisor。
啟動時會記住呼叫端的 `HERDR_PANE_ID`，每 5 秒自動更新**主任務 pane 的標題**：完成數、進行中的階段／任務、需要處理的數量。
不需要再手動開 watcher，也不需要觀看子任務輸出。標題出現 `!N attention` 時，請主控讀取 `progress --json`，取得原因與下一步。
這是本機狀態輪詢，不向主控輸入訊息、不喚醒模型；看板會更新，但不會自動觸發主任務的新一輪對話。
之後可從另一個 pane `submit` 與 `status`。第一版使用單一寫入鎖：agent 工作中 submit 可能要求等目前任務完成；不會同時改壞狀態。
沒有任務、等待重置、等待 GitHub CI 都不會喚醒 Planner。

- 關閉 Planner 對話不會結束 supervisor。
- 不要停止 Herdr server，否則其中的程序也可能結束。
- 在 supervisor pane 按 Ctrl-C 停止 worker；已保存任務與 worktree 保留。
- 電腦重新啟動後，重新進入 Herdr、查看 `status`、處理模糊中斷，再執行 `herdr`。第一版不自動安裝 launchd。
- 沒有 Herdr 也能手動執行 `work`；`herdr` 指令本身必須在 `HERDR_ENV=1` 的 pane 內執行。

## 5. 進度摘要與 todo.md 勾選

`progress` 只讀取本機 run 狀態與有時限的本機 Git 證據檢查，不呼叫模型、不取寫入鎖，agent 工作中也能隨時查看：

```sh
python3 "$FLOW" --repo "$TARGET" progress            # 一次性摘要
python3 "$FLOW" --repo "$TARGET" progress --json     # 給主控的快照：進度、阻塞、下一步、各次用量
python3 "$FLOW" --repo "$TARGET" progress --watch    # 只在內容改變時重印；Ctrl-C 結束
python3 "$FLOW" --repo "$TARGET" progress --watch --poll 10 --planner-pane PANE_ID
```

每個 run 顯示 stage／status、測試與審查對應的 commit、`verified` 與 `merged` 兩個獨立欄位，以及 checklist 同步結果。
執行中另顯示角色／模型（測試時為第幾個命令）、耗時與時限。Agent 時限含最多 60 秒登入檢查；
超過時限及 15 秒清理緩衝仍是 running，會提示檢查 supervisor，**不假設程序已死、不自動重送**。
權限／登入拒絕、未知額度重置時間、修復次數耗盡與發布受阻，會顯示各自的處理提示和診斷 log 路徑。
`--json` 只做一次唯讀查詢，不和 watch／sync／pane 回報混用；包含每次 agent 的角色、模型、狀態、耗時、原生 usage，不包含任務全文或 transcript。
已完成審查的候選 run 會重新檢查證據與 worktree；僅兩個保存的 SHA 相同不算 verified。TTY 小於 100 欄時換成多行並依寬度折行（含 38 欄 pane），非 TTY 保留完整表格。
損壞的狀態檔顯示為 `corrupt`；任務標題與 feedback 中的控制字元會被替換，不會注入終端。
`--planner-pane` 只能在 Herdr 內（`HERDR_ENV=1`）使用，須明確給目前存活的 pane id；工具用 `herdr pane get` 核對，
再以 `herdr pane report-metadata` 每次輪詢更新 verified／總數及進行中的 stage／task；TTL 至少 15 秒並涵蓋 poll 加 15 秒。pane 消失時警告並繼續顯示。不送輸入、不改 agent 生命週期。

若目標 repo 根目錄有已追蹤的 `todo.md`，可在**唯一一行** checkbox 加註記，把任務接上清單：

```markdown
- [ ] 補上本機啟動說明 <!-- maf:document-quickstart -->
```

submit 時記下這一行（沒有註記＝不接清單；任務 `paths` 不得涵蓋 `todo.md`，避免 Coder 自己簽收）。
測試通過且 Reviewer 以相同 commit 獨立 approve 後，`work` 會把根目錄 `todo.md` 的這一行改成 `[x]`，其餘位元組不動；
也可用 `progress --sync` 明確重做。限制：

- 打勾只代表 **worktree 上已測試並獨立審查**，不代表已合併或釋出；`merged` 欄位另行顯示。
- 這一行被改過、消失或重複時不打勾，只顯示警告，run 的 verified 狀態不受影響；修好清單後 `progress --sync` 即可。
- 同 task-id 即使描述或勾選狀態不同也算重複。寫入時根目錄仍須在設定的 base branch，todo 仍須為已追蹤的一般檔案。
- 暫存內容 flush 後、replace 前重查檔案 identity／內容；保留其他編輯。未共用鎖的編輯器仍可能在最後檢查與 replace 之間競爭寫入，請避免同時編輯。
- 僅 publish／merge 受阻的 `needs_human`，若已完成審查且當前證據全數有效，仍可打勾；未完成 coding／testing／reviewing 不可。同步或狀態儲存失敗只警告，不清除驗證證據。
- 同步後根目錄 `todo.md` 會變成未提交變更，**先 commit 這個進度紀錄再 submit 下一個任務**；乾淨工作樹與合併檢查都不放寬。
- 之後的失敗嘗試不會自動取消先前的勾；`todo.md` 為 symlink、未追蹤或註記重複時拒絕。
- 舊 run 沒有快照就沒有清單，不做遷移。

## 6. 額度與中斷恢復

Claude monthly spend limit／session limit 都視為額度停止；原生 `is_error` 額度結果優先於附帶的 permission_denials，真正權限拒絕仍封鎖。不提高額度、不自動重試未知重置時間。

| 狀態 | 意義／下一步 |
|---|---|
| `queued` | 等待 worker |
| `creating` | worktree 建立中斷；確認沒有程序仍在建立後，以 resume 核對並繼續 |
| `corrupt` | 狀態檔損壞；不執行此任務，保留檔案供人工檢查 |
| `running` | 可能仍在執行；不會因為程式重啟就重送 |
| `waiting_quota` | 額度不足；不切換 API、不反覆試探 |
| `needs_human` | 看 feedback 與 log，處理後明確恢復 |
| `verified` | 本機測試與獨立審查通過，尚未發布 |
| `publishing` / `merging` | 網路操作可能已完成，先 reconcile，不能盲目重做 |
| `pr` | PR 已建立；符合條件的自動合併會等待 CI |
| `merged` | 已由 GitHub 確認合併 |

先確認前一次 agent／測試程序真的停止，再恢復：

```sh
python3 "$FLOW" --repo "$TARGET" resume RUN_ID --acknowledge-stopped

# 供應商明確告知重置時間時，才排定恢復；一定要附時區
python3 "$FLOW" --repo "$TARGET" resume RUN_ID --acknowledge-stopped \
  --after '2026-09-20T08:00:00+08:00'
```

沒有可靠重置時間就保持等待，由你確認額度恢復後 resume。每次再遇 quota 都重新等待，不無限重試。
達到修正上限則重新規畫、建立新任務。網路發布不明時使用 `publish RUN_ID`；合併不明時使用 `merge RUN_ID` 核對既有 PR。
`needs_human` 若已在 `verified`／`publishing`／`pr`／`merging` 階段，不使用 resume 重跑模型；依 feedback 處理發布或合併門檻。
不要刪除 worktree、強制 reset 或重複開 PR 來「修復」狀態。

## 7. PR 與低風險自動合併

```sh
# 先完成本機驗證，再明確發布
python3 "$FLOW" --repo "$TARGET" publish RUN_ID

# 或在排隊時就授權完成後發布 draft PR
python3 "$FLOW" --repo "$TARGET" submit task.json --publish

# 額外授權符合政策的低風險 PR 自動合併
python3 "$FLOW" --repo "$TARGET" submit task.json --publish --auto-merge
```

只有下列條件全部通過才會合併：

1. 變更位於任務 paths 與 `.maf.json` 的該類 `auto_paths` 交集。
2. 不含政策、AGENTS／CLAUDE／SOUL、CI、依賴、登入、交易、金額等保護檔案，也沒有刪除、執行檔、symlink／submodule。
3. Reviewer 獨立通過且判定 low risk；測試與審查對應目前 commit，worktree 乾淨。
4. GitHub PR head 與 base 正確，base 沒有前進；現有 GitHub 檢查成功，沒有尚待滿足的 review。
5. **GitHub 分支保護有 strict required status checks**，避免檢查後 base 又改變的競態。沒有權限讀取、方案不支援、只使用尚未整合的 ruleset，皆停在人工處理，不開付費方案、不繞過。

預設只開放 `README.md` 與 `docs/usage/*.md`。樣式及測試目錄需要你先在設定中明確加入。
`style` 只允許獨立 `.css`；需要排除安全提示／交易狀態等敏感顯示。
`tests` 第一版只允許新增 `tests/test_*.py`，不自動合併修改／刪除既有測試。
使用 `protected_paths` 補上專案特有的重要路徑；自動分類不是語意安全的證明。

程式不使用 `--admin`、force push 或刪除分支／worktree。保留你現有 GitHub 保護規則。
多人／多 PR 合併後 base 會前進；下一個舊基底任務須人工同步與重新驗證。第一版不自動解衝突或批次 rebase。

## 8. 更換工具與模型

編輯 `.maf.json` 的 `roles`，不要改程式碼：

```json
"reviewer": {
  "runtime": "pi",
  "provider": "opencode-go",
  "model": "deepseek-v4.1-flash",
  "access": "read",
  "effort": "medium"
}
```

`runtime` 是 agent CLI，`provider` 是訂閱路線，`model` 是模型，Hermes 另有 `profile`。
自訂角色使用 `mode configured`；內建模式會套用自己的角色組合，但仍保留 `.maf.json` 的 timeout、修正上限與政策。
`effort` 可選 low／medium／high；預設 Planner 為 high，Pi Coder／Reviewer 為 medium。模型 ID 不含 provider 前綴或冒號推理設定，避免繞過已核准路線。
Planner／Reviewer 必須 `read`，Coder 必須 `edit`；不接受任意 shell command、額外 CLI 參數或 endpoint 覆寫。
保留固定訂閱路線，不把「自由切換」做成意外付費的後門。模型必須是該帳號實際可用的名稱；doctor 不發推論，所以不能證明模型可用。
模型／CLI 的行為可能隨更新改變，換版本後先跑測試與小任務，不在執行中的 run 偷換設定。

`init --preset hermes-coder` 可把實作角色換成 Hermes coder profile，仍用 Codex 規畫、Pi 唯讀審查。
所有任務都使用所選模式的 Reviewer，且是全新唯讀 session。GitHub 保護路徑與合併門檻仍獨立判斷，不信任任務的低風險標籤。
完整 Hermes default/coder/tester 組合暫不提供：目前 Hermes 原生 file 工具組包含寫入，不能滿足本工作流的唯讀角色要求。
Hermes adapter 使用 safe mode，停用 profile 的額外 hooks／MCP／skills，profile 僅供帳號與隔離目錄選擇，模型由本工具明確指定。
實際支援與限制見 [實測紀錄](docs/VALIDATION.md)。不要將 profile 名稱誤認成獨立額度。

## 9. UI／E2E 與省 token

將目標專案既有的 Playwright／其他 E2E 指令列入 task.tests；測試由程式執行，不由 LLM 每次重新點擊。
若需要視覺審查，請在 instructions 明確要求 Reviewer 讀取測試產出的截圖路徑，並選用已實測可讀圖的 runtime／模型。
測試報告與截圖需由目標專案 `.gitignore` 排除，否則乾淨 worktree 檢查會阻擋。
本工具本身沒有前端，因此自己的 E2E 是 CLI／Git／假 agent 流程測試；不宣稱已測過任意網站或 Tauri 原生 UI。

第一版每次 agent invocation 是新 session，保存 session id 作追蹤但不自動續接；交接使用短任務與有限失敗摘要。
這犧牲部分 session 快取，換取不混用對話與可重現的獨立審查。長 session 的精確恢復等實際量測後再做。
不會每分鐘用模型「巡邏」。供應商回傳 usage 時會保存；沒有就記 unknown，不換算成虛假的訂閱剩餘百分比。
Pi usage 加總本次執行的所有 assistant `message_end`，包含工具循環與已回報的失敗／重試；不重算 `agent_end` 的重複訊息。
輸出被截斷或任一次呼叫缺少必要用量時記 unknown；逾時只能保留已收到的用量，未回報部分未知。
input／cacheRead／cacheWrite／output 分開保留，reasoning 不再加進 output 或 total；`cost` 是 provider 估算，不能當訂閱帳單。
新 Pi 紀錄的 `usage_scope` 是 `model_calls`；舊 run 沒有這個標記，用量不會被自動重寫，不能把舊最後一輪數字與新加總直接比較。
通過的測試只交接命令、exit code 與 log 路徑，避免每次 review 都帶完整成功 log；需要時 Reviewer 可自行讀 log。
已在主任務完成規畫就直接 submit；一個可獨立驗收的功能交給一個 Coder，避免逐檔派工及重複規畫。

## 狀態、分享與開發

狀態在目標 repo 的 **Git common directory / maf/**，不進 Git，包括 run snapshots、agent logs 與測試證據。
Worktrees 在目標 repo 的 `.maf-worktrees/`（由 init 加入 Git exclude），不放進 `.git`，避免觸發 agent 的敏感檔案保護。
Logs 可能含程式片段與敏感資訊，僅供本機診斷；分享前人工檢查。不要分享 `.maf-local.json`、token、個人 agent 設定或整份 transcript。
分享時只提供此 repository、設定範例與任務範例；對方使用自己的訂閱與登入。

```sh
python3 -m unittest discover -s tests -v
```

架構／實作契約：[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)。實際驗證範圍：[docs/VALIDATION.md](docs/VALIDATION.md)。
本工具產出的每日操作速查可見 [PR #1](https://github.com/ian902792/multiple-agents-flow/pull/1)，目前因 private repo 分支保護方案限制保留為 draft，需人工確認。

設計參考 [bestony/herdr-dispatch](https://github.com/bestony/herdr-dispatch) 的 task/worktree/驗收分離；本實作未複製其程式。
介面查證：[Codex 非互動模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[Claude 程式化使用](https://code.claude.com/docs/en/headless)、[Hermes CLI](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)、[OpenCode Go](https://opencode.ai/docs/go/)。
