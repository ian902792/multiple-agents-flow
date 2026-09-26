# 指令參考

這份文件是主 Agent skill 與維護者的詳細指令參考。一般使用者可先看 [README](../README.md)，直接在 Claude Code 或 Codex 描述需求；不必逐條輸入委派、驗證或交接指令。需要手動查詢進度、切換 flow 或規畫時，再使用相應的對話指令。

以下範例先設定工具與目標專案的路徑。目標必須是已有第一個 commit 的 Git repository；`--repo` 放在子命令前。

```sh
FLOW=/absolute/path/multiple-agents-flow/flow.py
TARGET=/absolute/path/your-project
python3 "$FLOW" --repo "$TARGET" --main codex mode
```

## 指令一覽

| 指令 | 用途與主要輸出 |
| --- | --- |
| `install-skills` | 全域註冊 Claude／Codex skills 一次；回傳安裝路徑。 |
| `ui` | 開啟本機 Flow Studio；印出本機網址。 |
| `flows`、`flow-save FILE` | 列出或匯入全域命名 flow；回傳 flow JSON。 |
| `settings [herdr on\|off]`、`settings default-flow NAME` | 查詢或變更全域 Herdr 開關與 Claude／Codex 各自的新專案預設 flow；回傳設定 JSON。 |
| `init [--preset NAME]` | 可選：建立專案專用 `.maf.json` 政策，不覆寫既有檔案；回傳路徑。 |
| `mode [NAME\|default]` | 查詢或覆寫此主 Agent 在本專案後續任務的 flow；`default` 清除覆寫。 |
| `doctor` | 檢查 CLI、登入與訂閱確認紀錄，不呼叫模型；有問題時非零結束。 |
| `confirm-billing --no-overage` | 在任意目錄確認全域預設 flow 的模型路由；若加 `--repo` 則確認該專案目前 mode。 |
| `plan --goal-file FILE [--mode NAME]` | 只讀規畫：規畫者交回結構化計畫，MAF 驗證後存在私人目錄並印出計畫 ID 與中文摘要；不排入任務。 |
| `decide PLAN_ID 題號 答案` | 記下計畫中一個問題的答案；還有未決定的問題時，`night --plan` 不會執行。 |
| `delegate TASK.json [--depends-on RUN_ID]` | 把明確小任務排給所選 flow 的 Pi／Antigravity／Codex；回傳 run ID 與狀態。加 `--depends-on` 時等該 run `tested` 後，從它測試通過的 commit 接著做。 |
| `verify TASK.json` | 排入目前 commit 的測試；若 flow 啟用獨立審查才呼叫 reviewer。回傳 run ID 與來源 SHA。 |
| `submit TASK.json` | 排入獨立 coder 的批次任務；回傳 run ID 與狀態。 |
| `approve RUN_ID` | 放行一份已檢視的凍結任務範圍；回傳更新後的 run。 |
| `work [--once] [--run-id ID ...] [--delegate-concurrency N]` | 執行佇列；多個獨立 Pi／Antigravity／Codex 任務預設最多同時 3 個，印出各自階段與結果。 |
| `status [RUN_ID]`、`progress [--json\|--watch]` | 查 run 的證據或只讀進度摘要；有用量時列出每次 agent 呼叫的快取命中率（`cache hit`）。 |
| `night --plan PLAN_ID [--approve]` | 所有問題都決定後，本機試跑每個驗收指令（不呼叫模型），再依序執行計畫中的鏈並印出報告。 |
| `night 任務.json … [+ 任務.json …] [--approve]` | 把依序列出的任務串成鏈（`+` 分開不同的鏈）、依序執行到全部完成或卡住，最後印出中文報告。`--approve` 代表你已看過任務檔並核准需要核准的範圍。 |
| `report [--hours N] [--json]` | 無人看管批次的中文總結：需要你處理的、仍在等待的、已完成的，依賴鏈進度，以及可直接整合的 commit 範圍。見[一晚跑一批任務](OVERNIGHT.md)。 |
| `handoff RUN_ID` | 完成任務的精確 SHA、測試與可選審查摘要，以及各次 agent 呼叫的快取命中率。 |
| `resume RUN_ID` | 診斷中斷後明確恢復；回傳更新後的 run。 |
| `publish RUN_ID`、`merge RUN_ID` | 在已有授權下發布或核對 PR、合併結果。 |
| `herdr` | 在 Herdr pane 內啟動背景 supervisor；回傳 workspace／pane ID。 |

在專案外也能使用 `install-skills`、`ui`、`flows`、`flow-save`、`settings`、全域 `confirm-billing`。其餘指令操作指定 repository。從 Codex 主對話呼叫時，在子命令前加 `--main codex`；Claude 用預設的 `--main claude`。MAF 依此選擇各自的全域預設與專案 mode，無須改寫共享設定。更多參數可用 `python3 "$FLOW" --help` 及 `python3 "$FLOW" 子命令 --help` 查看。

## 初次設定

```sh
python3 "$FLOW" install-skills
python3 "$FLOW" settings default-flow quick-antigravity  # 或 quick（Pi）、quick-codex（Codex GPT-6 Luna，none）
python3 "$FLOW" settings default-flow codex-pi           # Codex 的預設，與 Claude 分開
python3 "$FLOW" confirm-billing --no-overage              # 在供應商核對後，全域確認一次
python3 "$FLOW" --main codex confirm-billing --no-overage
python3 "$FLOW" --repo "$TARGET" doctor
python3 "$FLOW" --repo "$TARGET" --main codex doctor
```

全域 skill 與 flow 只需設定一次。新 Git 專案不需要 `.maf.json` 或 `mode`；Claude 與 Codex 各自沿用全域預設。MAF 會優先以本機 `main`、`master` 作為 base branch，否則使用目前分支。若要指定 base branch、保護路徑或 timeout，才在該專案執行 `init` 並編輯 `.maf.json`；可把它納入版本控制。`mode configured` 使用其角色設定；`mode default` 只清除目前主 Agent 的專案覆寫。

在供應商控制台確認登入、模型包含在現有訂閱、沒有啟用額外付費用量，且 OpenCode Go 的 **Use balance** 關閉後，再記錄確認：

```sh
python3 "$FLOW" confirm-billing --no-overage
python3 "$FLOW" --repo "$TARGET" doctor
```

`doctor` 不發模型請求，因此不能證明模型實際可用；選用 Antigravity 時會用 `agy models` 檢查該 ID 是否列在帳號模型清單。`confirm-billing` 是人的確認紀錄，按角色模型組合全域儲存，不會替你修改或限制供應商帳單設定。舊版專案內的確認紀錄不再使用；升級後須重新確認一次。模型／路由改變後須重新核對；切回已確認的相同組合不需重複確認。已為某專案選另一個 mode 時，使用 `--repo "$TARGET" confirm-billing --no-overage` 確認該組合。

Flow Studio 用 `python3 "$FLOW" ui` 開啟，僅監聽 `127.0.0.1`。設定頁儲存全域 flow、Claude／Codex 各自的預設 flow、獨立審查開關與 Herdr 開關；安裝、指令及設計理念在獨立的 `/guide` 頁。專案覆寫仍在 terminal 使用 `mode NAME` 切換，並依 `--main` 分開保存。小任務與審查 Agent 可在畫面切換工具；新模型 ID 可直接輸入，建議清單不等於模型可用性檢查。主對話模型是偏好記錄，目前 session 仍須在 Claude 或 Codex 自身切換。

大型需求若要先規畫，由你明確執行 `/maf-plan 需求`（Codex 為 `$maf-plan 需求`），或直接呼叫 CLI。規畫者是所選 flow 的 `planner` 角色，必須與 `--main` 不同：Claude 主對話預設用 Codex GPT-6 Astra，`codex-pi` 預設用 Claude Opus 5.5，可在 Flow Studio 改成 Claude Fable 5.1 等模型。

```sh
python3 "$FLOW" --repo "$TARGET" plan --mode planned --goal-file /private/path/goal.md
```

Planner 只回傳建議與私有結果檔，不會自動排隊或執行計畫。

## 任務資料與執行

用 `/maf delegate 需求` 或 `/maf verify 需求` 時，skill 會替你準備 JSON。直接使用 CLI 時，請把下列資料放在 repository 之外的私人檔案：

```json
{
  "id": "document-quickstart",
  "title": "補上本機啟動說明",
  "instructions": "核對實際指令，只修改 README.md。",
  "paths": ["README.md"],
  "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]],
  "risk": "docs"
}
```

`tests` 是一個或多個 argv 陣列，須換成該專案真正能驗收需求、已核准執行的命令；不要用空檢查。路徑是相對專案根目錄的精確檔案或 glob；`*` 不跨目錄，`**` 可跨多層。風險可用 `manual`、`docs`、`style`、`tests`；不確定時選 `manual`。Pi／Antigravity／Codex delegate 可額外使用布林欄位 `"independent": true`，明確表示它不依賴其他任務或共用測試資源；未標記時依序執行。可選字串 `acceptance_why` 寫出這些測試要保住的真正目的（例如「重新整理後仍保持登入」），coder 與 reviewer 都會看到，reviewer 會檢查測試是否真的斷言到它。`handoff` 另回傳 `coder_notes`：coder 最後回覆中的 `UNVERIFIED:` 存疑項，驗收時必讀。任務以已提交的 HEAD 建立 worktree，開始前需檢查工作樹。

網站專案可把既有的 Playwright 等 E2E 命令列入 `tests`；MAF 執行該命令，並依退出碼判定。若審查需要看截圖，須在任務說明指定輸出位置與可讀圖的 reviewer；測試產物也應由目標專案忽略，避免污染乾淨工作樹檢查。

**驗證主 Agent 已做的工作：**

```sh
python3 "$FLOW" --repo "$TARGET" verify /private/path/task.json --mode quick
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff RUN_ID
```

`verify` 只針對乾淨的目前 HEAD 跑測試，不啟動新 coder。flow 的獨立審查預設關閉；開啟後才會呼叫與主 Agent 不同的 reviewer。Codex 主導且啟用審查時，可用 Claude Opus 5.5。測試通過時，關閉審查的 run 為 `tested`，開啟並通過審查的 run 為 `verified`。預設與 base branch 的共同祖先比較；若直接在 base branch 驗證單一 commit，可明確加 `--base HEAD^`。來源 commit 一旦改變，舊證據不能套用到新 SHA，應重新建立 verify run。

**委派 Pi／Antigravity／Codex 小任務：**

```sh
python3 "$FLOW" --repo "$TARGET" delegate /private/path/task.json
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff RUN_ID
```

所選小任務 Agent 在獨立 worktree 工作；MAF 不會自動把結果合進主 Agent 的分支。主 Agent 檢查並整合後，對新的整合 commit 再執行 `verify`。Agent 不負責執行 shell 驗收測試；測試由 supervisor 執行。

### 多個 Pi／Antigravity／Codex 任務並行

例如把「安裝說明」、「常見問題」與「疑難排解」拆成三份任務 JSON，各有自己的精確檔案路徑與驗收命令；先從**同一個乾淨 HEAD** 排入，再一起執行：

```json
{"id":"install-docs","title":"補安裝說明","instructions":"新增 docs/install.md 的實際安裝步驟。","paths":["docs/install.md"],"tests":[["python3","-c","from pathlib import Path; assert Path('docs/install.md').is_file()"]],"risk":"docs","independent":true}
```

第二、三份分別只修改 `docs/faq.md` 與 `docs/troubleshooting.md`，並各用自己的測試檢查。儲存為三份私人 JSON 後：

```sh
python3 "$FLOW" --repo "$TARGET" delegate /private/path/install.json
python3 "$FLOW" --repo "$TARGET" delegate /private/path/faq.json
python3 "$FLOW" --repo "$TARGET" delegate /private/path/troubleshooting.json
python3 "$FLOW" --repo "$TARGET" work --once --run-id INSTALL_RUN_ID --run-id FAQ_RUN_ID --run-id TROUBLESHOOTING_RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff INSTALL_RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff FAQ_RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff TROUBLESHOOTING_RUN_ID
```

`delegate` 回傳的 JSON 有各自的 run ID；請把它填入後續指令。`work --once` 會把指定 ID 各處理一次，不會帶入其他排隊任務。預設最多同時 **3** 個 Pi／Antigravity／Codex delegate；用 `--delegate-concurrency N` 調整上限（1–3），設為 `1` 會依序執行。只有標記獨立、相同來源 SHA、編輯檔案不重疊、無通配路徑且無人工核准門檻的低風險 delegate 會並行；其他任務照順序處理。即使所有 worktree 都已驗證，整合後仍要對新 commit 執行 `verify`。Herdr supervisor 已在執行時，只需排入任務，讓它自行接手。

`submit TASK.json` 是明確要求 MAF 啟動獨立 coder 的批次入口。它只排隊，真正執行靠 `work`；可加 `--mode NAME` 覆寫單一任務的角色設定，不改專案下次的預設。任務使用受限的修改路徑、測試與修復次數；Coder 不能替自己批准 review。

## 核准、阻塞與恢復

若任務回傳 `awaiting_approval`，先看完整的凍結範圍與原因；確認後放行該 run 一次：

```sh
python3 "$FLOW" --repo "$TARGET" status RUN_ID
python3 "$FLOW" --repo "$TARGET" approve RUN_ID
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
```

敏感或過寬路徑、shell 測試、手動風險的獨立 coder 任務可能自動停在這裡；語意上高風險的任務可在 `submit`、`delegate` 或 `verify` 加 `--require-approval`。核准綁定當時的任務、測試、設定與來源 SHA。一般失敗可在已核准的修復次數內自動處理；需求或安全風險需人決定時會停下。變更範圍要建立新任務，不能讓舊核准延伸過去。

`progress` 只讀狀態，不會叫模型：

```sh
python3 "$FLOW" --repo "$TARGET" progress
python3 "$FLOW" --repo "$TARGET" progress --json
python3 "$FLOW" --repo "$TARGET" progress --watch
```

`waiting_quota` 不會自動改 provider 或猜重置時間；`running` 在中斷後也不會被直接重送。先確認舊程序確實停止，檢查 `status RUN_ID` 與相關 log，再視情況恢復：

```sh
python3 "$FLOW" --repo "$TARGET" resume RUN_ID --acknowledge-stopped
```

若供應商明確給出重置時間，才用 `--after` 傳入含時區的 ISO 8601 時間。狀態損壞、權限拒絕或修復次數用盡，需要先處理實際原因。詳細狀態機與不得重播的條件見 [實作契約](IMPLEMENTATION.md#state-and-cli)。

## Herdr 與清單

Herdr 整合預設關閉。啟用後，在 Herdr pane 內執行：

```sh
python3 "$FLOW" settings herdr on
python3 "$FLOW" --repo "$TARGET" herdr
```

`herdr` 建立不搶焦點的 supervisor workspace，更新呼叫端 pane 標題；每個執行中的 Coder／Reviewer 都有自己的暫時觀察 pane，完成後關閉。Planner 仍需你手動使用 `/maf-plan`。沒有常駐 supervisor 時，在 Herdr 內可用 `work --once --run-id RUN_ID --agent-panes`；多個任務就重複 `--run-id`。這些 pane 顯示進度，不是驗證證據。
在 supervisor pane 按 Ctrl-C 會停止接新任務，並等待正在執行的 delegate 到達安全完成點後退出；狀態和工作樹保留。再次啟動前先用 `status` 檢查中斷的 run，不要假設正在執行的 agent 已正常完成。

若專案根目錄有已追蹤的 `todo.md`，可把任務 ID 接到唯一一行：

```md
- [ ] 補上本機啟動說明 <!-- maf:document-quickstart -->
```

同一個 commit 的測試通過後，MAF 才會將該行改為 `[x]`；若啟用獨立審查，還須同一 SHA 的審查通過。這代表 worktree 已按所選檢查完成，**不代表已合併**。清單有衝突時只警告；修正後可用 `progress --sync` 再投影。根目錄 `todo.md` 變成未提交修改時，先提交清單再排下一個任務。

## PR、模型與本機資料

本機驗證完成後，明確使用 `publish RUN_ID` 才會發布。獨立 coder 任務也可在 `submit` 時加 `--publish`，或再加 `--auto-merge` 授權符合政策的低風險 PR 合併：

```sh
python3 "$FLOW" --repo "$TARGET" publish RUN_ID
python3 "$FLOW" --repo "$TARGET" submit /private/path/task.json --publish --auto-merge
```

發布與自動合併仍要求先啟用獨立審查。自動合併還要求同一 SHA 的測試與 review、乾淨 worktree、GitHub checks 成功，以及 strict required status checks；條件不明就停下，不使用管理員繞過。細節見 [GitHub 政策](IMPLEMENTATION.md#github)。

在 Flow Studio 可直接切換小任務 Agent 的 runtime、model、effort 並儲存全域 flow。若要讓新專案沿用，按「設為全域預設」；若只影響目前專案，使用 `mode NAME`。模型必須是該訂閱實際支援的 ID；不要把登入成功當成模型可用性證明。已開始的任務保留自己的模型快照。

Codex coder（`quick-codex`）使用 `codex exec -s workspace-write`，預設模型 `gpt-6-luna`、推理 `none`（Luna 支援 none／low／medium／high／xhigh／max，不支援 minimal），走 ChatGPT 登入。Antigravity coder 預設使用 `agy --model gemini-3.8-flash-low --effort low`；每個強度是不同的模型 ID（`-low`／`-medium`／`-high`），兩者必須一致，模型清單可用 `agy models` 查看。MAF 只接受 Google 帳號登入，不允許 `modelProvider: gemini` 的 API key 路由或預先放行工具；使用 CLI sandbox 與 headless `request-review` 權限，且只讓 Antigravity 擔任可編輯 coder。這個 CLI 沒有像 Pi 一樣的工具白名單；請只在信任的 repository 使用，正式測試仍由 MAF supervisor 執行。登入、額度或模型可用性不明時停止，不自動換模型。

Run 狀態、agent log、測試證據存在目標 repo 的 Git common directory 下 `maf/`，不進 Git；工作樹在 `.maf-worktrees/`。全域 flow、設定與角色模型確認存在使用者設定目錄，不進 Git。Log 可能含程式片段或敏感資訊，分享前先檢查。不要提交 token、個人設定或完整 transcript。
