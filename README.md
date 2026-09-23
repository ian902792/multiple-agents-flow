# multiple-agents-flow

以 **Claude Code 為主對話**開發：小任務由 Claude 完成，必要時交給 Pi 處理明確的小範圍工作；完成後由程式執行測試，交給獨立 agent review。只有你手動輸入 `/maf-plan`，才會使用 Codex GPT-6 Astra 規畫大型任務。
Herdr 可用來分專案 workspace；Python 負責 worktree、狀態、測試證據與精確 commit SHA。Python 3.11+ 標準函式庫即可執行，支援 macOS/Linux。

這也是可自行擴充的開源工具：全域儲存命名 flow、調整各 MAF agent 的 model／effort、匯入匯出 flow JSON。授權為 [MIT](LICENSE)。

## 最短安裝流程

先準備 Python 3.11+、Git、Claude Code；預設的 `quick`／`planned` flow 也需要已登入的 Codex CLI 與 Pi CLI，因為 `doctor` 會檢查所有角色。目標專案須是已有第一個 commit 的 Git repository。先在一般 terminal **全域安裝一次**：

```sh
git clone https://github.com/ian902792/multiple-agents-flow.git
cd multiple-agents-flow
FLOW="$PWD/flow.py"
python3 "$FLOW" install-skills
python3 "$FLOW" ui
```

`install-skills` 會在使用者目錄建立 Claude 的 `~/.claude/skills/maf`、`~/.claude/skills/maf-plan`，以及 Codex 的 `~/.agents/skills/maf` symlink。之後在任何專案都能使用；遇到既有同名 skill 會拒絕覆寫。`ui` 只監聽 `127.0.0.1`，用於設定全域 flow 及可選的 Herdr 整合，**不會選 mode 或執行任務**。

每個專案只需要建立自己的 `.maf.json` 政策並在 terminal 選 mode；不需再安裝 skill。在該專案的 Claude 對話輸入 `/maf setup quick`，或直接用 CLI：

```sh
TARGET="/path/to/your-git-project"
python3 "$FLOW" --repo "$TARGET" init
python3 "$FLOW" --repo "$TARGET" mode quick
python3 "$FLOW" --repo "$TARGET" doctor
```

若 `doctor` 顯示 billing 未確認，先核對供應商控制台中的登入、訂閱模型與額外用量設定。**只有核對完成後**才執行：

```sh
python3 "$FLOW" --repo "$TARGET" confirm-billing --no-overage
python3 "$FLOW" --repo "$TARGET" doctor
```

在目標專案重新開啟 Claude 對話，輸入 `/maf status`。日常小任務用 `/maf mode quick`，在 Claude 完成並提交後用 `/maf verify 需求`；大型任務用 `/maf mode planned`，**需要時由你手動**輸入 `/maf-plan 需求`。Claude 可以透過 `/maf delegate 需求` 把明確的小任務交給 Pi。這些 skill 會準備 task JSON；使用者不用手寫。下方有更多 CLI 範例與限制。

## 建議使用方式：在主 agent 呼叫 skill

全域安裝的 Claude／Codex 入口指向同一份 [MAF skill](skills/maf/SKILL.md)；Claude 的 [maf-plan skill](skills/maf-plan/SKILL.md) 設為只接受手動呼叫。若既有對話尚未顯示 skill，重新開啟對話。

| 操作 | Claude Code | Codex CLI／IDE |
|---|---|---|
| 初次設定 | `/maf setup quick` | `$maf setup quick` |
| 切換日常 flow | `/maf mode quick` | `$maf mode quick` |
| 切換大型任務 flow | `/maf mode planned` | `$maf mode planned` |
| 大型任務規畫 | **手動** `/maf-plan 需求` | `plan --mode planned --goal-file ...` |
| Pi 小範圍工作 | `/maf delegate 需求` | `$maf delegate 需求` |
| 完成後驗證 | `/maf verify 需求` | `$maf verify 需求` |
| 查進度與阻塞 | `/maf status` | `$maf status` |
| 處理後恢復 | `/maf resume RUN_ID` | `$maf resume RUN_ID` |
| 補做全域註冊 | `/maf install` | `$maf install` |

Codex 也可以輸入 **`/skills` → 選取 `maf`**，再輸入上述動作；不把 `/maf` 宣稱為 Codex 原生指令。
Claude 的 `/maf` 與 Codex 的 `/skills`／`$maf` 使用方式依據
[Claude 官方文件](https://code.claude.com/docs/en/skills)與
[Codex 官方文件](https://learn.chatgpt.com/docs/build-skills)。其他介面使用該介面的 skill 選擇器。

`delegate` 讓 Pi 在獨立 worktree 編輯，`verify` 直接測試 Claude 已提交的 HEAD 並讓非 Claude agent 獨立審查，`handoff RUN_ID` 回傳簡短證據。Claude 在主對話整理任務 JSON，使用者不用手寫。Pi 目前不能執行 shell 測試；由 supervisor 執行已核准的測試指令。整合 Pi 的 commit 後 SHA 會改變，須對整合後的 commit 再執行 `verify`。

`run` 保留為明確要求的獨立 coder 批次流程。Skill 不會直接改變**目前 Claude 對話**的模型；GUI 可記住主對話建議偏好，實際切換請在 Claude terminal 使用 `/model`、`/effort`。其他角色的設定影響之後啟動的 MAF agent。

## 本機 Flow Studio

```sh
python3 "$FLOW" ui
```

它只監聽 `127.0.0.1`，**只負責全域 flow 的定義與適用範圍、各角色 model／effort、Herdr 開關**。畫面內有安裝步驟、原理、各指令用法和輸出，以及操作範例。`quick` 是 Claude 開發、Codex Sol 審查；`planned` 提醒手動 `/maf-plan`，並提高 reviewer effort。兩者都能在需要時把明確小任務交給 Pi；規畫絕不因為選到 `planned` 自動啟動。

儲存後，在**目標專案的 terminal** 輸入 `/maf mode quick`、`/maf mode planned` 或 `/maf mode 你的名稱`。這才切換該專案的後續任務。CLI 等價指令是 `python3 "$FLOW" --repo "$TARGET" mode 名稱`。Flow 預設存在 `~/.config/multiple-agents-flow/flows.json`；若設定絕對路徑的 `XDG_CONFIG_HOME`，則存在該目錄下的 `multiple-agents-flow/flows.json`。每個專案目前選用的 mode 仍存在該專案 Git 的私有狀態。GUI 不展示或控制任務執行；使用 `/maf status` 或 `progress` 看進度。變更 MAF agent 模型後，使用前須重新確認該精確訂閱路由。

Model 欄位可直接挑常用選項，並會把全域已儲存 flow 的模型加入建議清單；新模型只需在一個 flow 輸入並儲存一次。主 Claude 偏好可用 `opus`，由 Claude Code 依供應商更新到最新 Opus；自動執行的 Claude 角色使用固定 ID，例如 `claude-opus-5-5`。Codex 使用明確的 `gpt-6-sol` 等 ID；日後推出新版本時可直接輸入新 ID，無須改程式。建議清單不是可用性檢查，仍須用自己的訂閱／CLI 確認。Claude／Codex 可選 `xhigh`、`max` effort；Pi 保留 `low`／`medium`／`high`。參考 [Claude Code 模型設定](https://code.claude.com/docs/en/model-config)與 [Codex 模型](https://learn.chatgpt.com/docs/models)。

主 Claude 的偏好僅顯示，不會改目前對話。直接在 Claude terminal 輸入 `/model` 或 `/effort` 切換；若 Herdr 中不同 pane 想各自用不同設定，在 Claude Code 2.1.257+ 開啟 `/model`／`/effort` 選單，選好按 `s` 只套用本 session；新 pane 也可用 `claude --model opus --effort medium` 啟動。

CLI 也能操作：`flows` 列出全域 profile、`flow-save my-flow.json` 匯入；`mode quick`／`mode planned` 在指定專案選用。

| 模式 | Coder | 獨立 Reviewer |
|---|---|---|
| `economy` | Pi / DeepSeek V4.1 Flash | Pi / DeepSeek V4.1 Flash，新 session |
| `opus-sol` | Claude Opus 5.5（固定 ID），medium | Codex GPT-6 Sol，medium |
| `hermes-coder` | Hermes coder / DeepSeek | Pi / DeepSeek |
| `configured` | `.maf.json` 的 coder | `.maf.json` 的 reviewer |
| `quick`／`planned`／自訂名稱 | Pi 小任務；Claude 留在主對話 | 預設 Codex Sol，可在 GUI 調整 |

模式只影響**之後提交**的任務，存在 Git 私有狀態，不需要改設定檔再 commit；既有任務保留模型快照。
每種有效設定第一次使用須有人的訂閱確認，之後切回已確認的組合不重問。
設定或合併政策實際改變仍會使舊 run／確認失效。舊版單一 `config_hash` billing 紀錄不會被自動當作新版批准。
沒有明確 mode 快照的舊任務可查看證據，但不可重跑模型；需重新建立任務，避免沿用已移除的隱含角色規則。
只切換模式不呼叫模型；單次任務可用 `submit --mode opus-sol`，不改下次的預設。

Herdr 整合預設關閉。啟用後且在 Herdr 內明確執行 `herdr` 才會建立背景 supervisor，並回報主任務 pane；其他環境依主 agent 的命令 session 回報進度。
權限、登入、額度或模糊中斷會停在具體原因，`resume` 先診斷及確認程序停止，不能直接略過。
主對話閒置時不會自動被 worker 喚醒；可用 `status` 取得最新摘要。

想從另一個專案直接開始，只需在那個專案初始化政策，**不用再安裝 skill**：

```sh
python3 /path/to/multiple-agents-flow/flow.py --repo /path/to/repo init
```

全域安裝的 symlink 指向此工具資料夾；移動工具資料夾後需在使用者 skill 目錄移除失效連結，再執行 `install-skills`。
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

若 repository 尚未公開，clone 前須先取得存取權。

```sh
git clone https://github.com/ian902792/multiple-agents-flow.git
cd multiple-agents-flow
python3 flow.py --help
python3 flow.py install-skills
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

全域 skill 已在上一節安裝，以下不用再次執行 `install-skills`。將 `FLOW` 改成此工具的實際位置；`TARGET` 是要開發的 Git repository。
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
python3 "$FLOW" --repo "$TARGET" plan --mode planned --goal-file /absolute/path/goal.md
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

Claude 主導時，task JSON 放在 repo 外的私人暫存檔，先提交目前程式碼並確認工作樹完全乾淨：

```sh
# 在 feature branch 上，驗證 Claude 的目前 HEAD；預設比較與 base branch 的共同祖先
python3 "$FLOW" --repo "$TARGET" verify /absolute/path/task.json --mode quick
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff RUN_ID

# 把明確小任務交給 Pi；完成後檢查 handoff 的 source/head SHA 與變更範圍
python3 "$FLOW" --repo "$TARGET" delegate /absolute/path/task.json --mode planned
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff RUN_ID
```

`delegate` 不會自行把 Pi commit 合進目前分支。Claude 檢查後整合，再以新 task／新 SHA 執行 `verify`。在 base branch 直接驗證某個 commit 時，使用 `verify ... --base HEAD^` 明確指定比較起點。測試或審查失敗的 Claude commit 不會自動交給 Pi 修改；Claude 修好、重新提交後建立新的 `verify` run。

以下 `submit` 是保留的獨立 coder 批次流程：

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

Herdr 是**全域可選**整合，預設關閉。先在 Flow Studio 勾選「啟用 MAF 的 Herdr 整合」並儲存，或在一般 terminal 執行：

```sh
python3 "$FLOW" settings            # 印出 {"herdr_enabled": false} 或 true
python3 "$FLOW" settings herdr on   # 印出 {"herdr_enabled": true}
```

**關閉時：**用 `work --once --run-id RUN_ID` 或一般持續 `work` 處理佇列，用 `progress`／`/maf status` 看狀態。MAF 不建立 Herdr workspace，也不更新 pane 標題；即使系統已安裝 Herdr 也不會碰它。

**啟用時：**在 Herdr pane 內明確執行：

```sh
python3 "$FLOW" --repo "$TARGET" herdr
```

會建立新的背景 workspace／pane，保留目前焦點，啟動持續處理佇列的 supervisor。指令會印出 `workspace`、`pane`、`planner_pane` ID。
啟動時會記住呼叫端的 `HERDR_PANE_ID`，每 5 秒自動更新**主任務 pane 的標題**：完成數、進行中的階段／任務、需要處理的數量。
不需要再手動開 watcher，也不需要觀看子任務輸出。標題出現 `!N attention` 時，請主控讀取 `progress --json`，取得原因與下一步。
這是本機狀態輪詢，不向主控輸入訊息、不喚醒模型；看板會更新，但不會自動觸發主任務的新一輪對話。
之後可從另一個 pane `submit` 與 `status`。第一版使用單一寫入鎖：agent 工作中 submit 可能要求等目前任務完成；不會同時改壞狀態。
沒有任務、等待重置、等待 GitHub CI 都不會喚醒 Planner。

- 關閉 Claude 主對話不會結束 supervisor。
- 不要停止 Herdr server，否則其中的程序也可能結束。
- 在 supervisor pane 按 Ctrl-C 停止 worker；已保存任務與 worktree 保留。
- 電腦重新啟動後，重新進入 Herdr、查看 `status`、處理模糊中斷，再執行 `herdr`。第一版不自動安裝 launchd。
- 沒有 Herdr 也能手動執行 `work`；`herdr` 指令本身必須在 `HERDR_ENV=1` 的 pane 內執行，且全域開關必須已啟用。關閉開關可用 `python3 "$FLOW" settings herdr off`；新的 pane 回報會拒絕。

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

只換模型／effort 時，直接在 Flow Studio 複製並儲存命名 flow。若要更換 agent runtime／provider，才編輯 `.maf.json` 的 `roles`，並使用 `mode configured`：

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
Pi／Hermes 的 `effort` 可選 low／medium／high；Claude／Codex 另可選 xhigh／max。預設 Planner 為 high，Pi Coder／Reviewer 為 medium。模型 ID 不含 provider 前綴或冒號推理設定，避免繞過已核准路線。
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
工具的 Flow Studio 是本機設定畫面；目標專案的網站 E2E 仍須由該專案自己的測試指令驗證，不因 Flow Studio 可用就視為通過。

第一版每次 agent invocation 是新 session，保存 session id 作追蹤但不自動續接；交接使用短任務與有限失敗摘要。
這犧牲部分 session 快取，換取不混用對話與可重現的獨立審查。長 session 的精確恢復等實際量測後再做。
不會每分鐘用模型「巡邏」。供應商回傳 usage 時會保存；沒有就記 unknown，不換算成虛假的訂閱剩餘百分比。
Pi usage 加總本次執行的所有 assistant `message_end`，包含工具循環與已回報的失敗／重試；不重算 `agent_end` 的重複訊息。
輸出被截斷或任一次呼叫缺少必要用量時記 unknown；逾時只能保留已收到的用量，未回報部分未知。
input／cacheRead／cacheWrite／output 分開保留，reasoning 不再加進 output 或 total；`cost` 是 provider 估算，不能當訂閱帳單。
新 Pi 紀錄的 `usage_scope` 是 `model_calls`；舊 run 沒有這個標記，用量不會被自動重寫，不能把舊最後一輪數字與新加總直接比較。
通過的測試只交接命令、exit code 與 log 路徑，避免每次 review 都帶完整成功 log；需要時 Reviewer 可自行讀 log。
小任務由 Claude 在主對話直接處理；只把有清楚邊界與驗收方式的小工作交給 Pi，避免逐檔派工與重複規畫。

## 狀態、分享與開發

狀態在目標 repo 的 **Git common directory / maf/**，不進 Git，包括 run snapshots、agent logs 與測試證據。
Worktrees 在目標 repo 的 `.maf-worktrees/`（由 init 加入 Git exclude），不放進 `.git`，避免觸發 agent 的敏感檔案保護。
Logs 可能含程式片段與敏感資訊，僅供本機診斷；分享前人工檢查。不要分享 `.maf-local.json`、token、個人 agent 設定或整份 transcript。
分享時只提供此 repository、設定範例與任務範例；對方使用自己的訂閱與登入。

```sh
python3 -m unittest discover -s tests -v
```

架構／實作契約：[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)。實際驗證範圍：[docs/VALIDATION.md](docs/VALIDATION.md)。

設計參考 [bestony/herdr-dispatch](https://github.com/bestony/herdr-dispatch) 的 task/worktree/驗收分離；本實作未複製其程式。
介面查證：[Codex 非互動模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[Claude 程式化使用](https://code.claude.com/docs/en/headless)、[Hermes CLI](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)、[OpenCode Go](https://opencode.ai/docs/go/)。
