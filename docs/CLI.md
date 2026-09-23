# 指令參考

這份文件給想直接使用 Python CLI、排查阻塞或設定進階流程的人。日常開發可先看 [README](../README.md)，在 Claude Code 中使用 `/maf`，由 skill 準備任務資料。

以下範例先設定工具與目標專案的路徑。目標必須是已有第一個 commit 的 Git repository；`--repo` 放在子命令前。

```sh
FLOW=/absolute/path/multiple-agents-flow/flow.py
TARGET=/absolute/path/your-project
python3 "$FLOW" --repo "$TARGET" status
```

## 指令一覽

| 指令 | 用途與主要輸出 |
| --- | --- |
| `install-skills` | 全域註冊 Claude／Codex skills 一次；回傳安裝路徑。 |
| `ui` | 開啟本機 Flow Studio；印出本機網址。 |
| `flows`、`flow-save FILE` | 列出或匯入全域命名 flow；回傳 flow JSON。 |
| `settings [herdr on\|off]` | 查詢或變更全域 Herdr 開關；回傳設定 JSON。 |
| `init [--preset NAME]` | 建立專案 `.maf.json`，不覆寫既有檔案；回傳路徑。 |
| `mode [NAME]` | 查詢或選擇本專案後續任務的 flow；回傳角色與模型。 |
| `doctor` | 檢查 CLI、登入與訂閱確認紀錄，不呼叫模型；有問題時非零結束。 |
| `confirm-billing --no-overage` | 記錄你已核對訂閱與額外用量設定；回傳確認結果。 |
| `plan --goal-file FILE [--mode NAME]` | 只讀規畫，印出建議與私有結果路徑；不排入任務。 |
| `delegate TASK.json` | 把明確小任務排給 Pi；回傳 run ID 與狀態。 |
| `verify TASK.json` | 排入目前 commit 的測試與獨立審查；回傳 run ID 與來源 SHA。 |
| `submit TASK.json` | 排入獨立 coder 的批次任務；回傳 run ID 與狀態。 |
| `approve RUN_ID` | 放行一份已檢視的凍結任務範圍；回傳更新後的 run。 |
| `work [--once] [--run-id ID ...] [--pi-concurrency N]` | 執行佇列；多個獨立 Pi 任務預設最多同時 3 個，印出各自階段與結果。 |
| `status [RUN_ID]`、`progress [--json\|--watch]` | 查 run 的證據或只讀進度摘要。 |
| `handoff RUN_ID` | 已驗證任務的精確 SHA、測試與審查摘要。 |
| `resume RUN_ID` | 診斷中斷後明確恢復；回傳更新後的 run。 |
| `publish RUN_ID`、`merge RUN_ID` | 在已有授權下發布或核對 PR、合併結果。 |
| `herdr` | 在 Herdr pane 內啟動背景 supervisor；回傳 workspace／pane ID。 |

在專案外也能使用 `install-skills`、`ui`、`flows`、`flow-save`、`settings`。其餘指令操作指定 repository。更多參數可用 `python3 "$FLOW" --help` 及 `python3 "$FLOW" 子命令 --help` 查看。

## 初次設定

```sh
python3 "$FLOW" install-skills
python3 "$FLOW" --repo "$TARGET" init
python3 "$FLOW" --repo "$TARGET" mode quick
python3 "$FLOW" --repo "$TARGET" doctor
```

`init` 預設建立 `economy` 的 `.maf.json`；`mode quick` 再選 Claude 主開發、Codex Sol 審查的日常 flow。建議把 `.maf.json` 納入專案版本控制。全域 skill 安裝一次即可，每個新專案只做 `init`／`mode`。若想改用其他內建角色，可查看 `init --help`；自訂 runtime／provider 則編輯 `.maf.json` 並選 `mode configured`。

在供應商控制台確認登入、模型包含在現有訂閱、沒有啟用額外付費用量，且 OpenCode Go 的 **Use balance** 關閉後，再記錄確認：

```sh
python3 "$FLOW" --repo "$TARGET" confirm-billing --no-overage
python3 "$FLOW" --repo "$TARGET" doctor
```

`doctor` 不發模型請求，因此不能證明模型實際可用。`confirm-billing` 是人的確認紀錄，不會替你修改或限制供應商帳單設定。模型／路由改變後須重新核對；切回已確認的相同設定不需重複確認。

Flow Studio 用 `python3 "$FLOW" ui` 開啟，僅監聽 `127.0.0.1`。它儲存全域 flow 與 Herdr 開關；專案 mode 仍在 terminal 使用 `mode NAME` 切換。新模型 ID 可直接輸入 GUI，建議清單不等於模型可用性檢查。主 Claude 對話的模型需用 Claude 的 `/model`、`/effort` 切換。

大型需求若要先規畫，由你明確執行 `/maf-plan 需求`，或直接呼叫 CLI：

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

`tests` 是一個或多個 argv 陣列，須換成該專案真正能驗收需求、已核准執行的命令；不要用空檢查。路徑是相對專案根目錄的精確檔案或 glob；`*` 不跨目錄，`**` 可跨多層。風險可用 `manual`、`docs`、`style`、`tests`；不確定時選 `manual`。Pi delegate 可額外使用布林欄位 `"independent": true`，明確表示它不依賴其他任務或共用測試資源；未標記時依序執行。任務以已提交的 HEAD 建立 worktree，開始前需檢查工作樹。

網站專案可把既有的 Playwright 等 E2E 命令列入 `tests`；MAF 執行該命令，並依退出碼判定。若審查需要看截圖，須在任務說明指定輸出位置與可讀圖的 reviewer；測試產物也應由目標專案忽略，避免污染乾淨工作樹檢查。

**驗證 Claude 已做的工作：**

```sh
python3 "$FLOW" --repo "$TARGET" verify /private/path/task.json --mode quick
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff RUN_ID
```

`verify` 只針對乾淨的目前 HEAD 跑測試與非 Claude reviewer，不啟動新 coder。預設與 base branch 的共同祖先比較；若直接在 base branch 驗證單一 commit，可明確加 `--base HEAD^`。來源 commit 一旦改變，舊審查不能套用到新 SHA，應重新建立 verify run。

**委派 Pi 小任務：**

```sh
python3 "$FLOW" --repo "$TARGET" delegate /private/path/task.json --mode quick
python3 "$FLOW" --repo "$TARGET" work --once --run-id RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff RUN_ID
```

Pi 在獨立 worktree 工作；MAF 不會自動把結果合進 Claude 的分支。Claude 檢查並整合後，對新的整合 commit 再執行 `verify`。Pi 不能自行執行 shell 測試；測試由 supervisor 執行。

### 多個 Pi 任務並行

例如把「安裝說明」、「常見問題」與「疑難排解」拆成三份任務 JSON，各有自己的精確檔案路徑與驗收命令；先從**同一個乾淨 HEAD** 排入，再一起執行：

```json
{"id":"install-docs","title":"補安裝說明","instructions":"新增 docs/install.md 的實際安裝步驟。","paths":["docs/install.md"],"tests":[["python3","-c","from pathlib import Path; assert Path('docs/install.md').is_file()"]],"risk":"docs","independent":true}
```

第二、三份分別只修改 `docs/faq.md` 與 `docs/troubleshooting.md`，並各用自己的測試檢查。儲存為三份私人 JSON 後：

```sh
python3 "$FLOW" --repo "$TARGET" delegate /private/path/install.json --mode quick
python3 "$FLOW" --repo "$TARGET" delegate /private/path/faq.json --mode quick
python3 "$FLOW" --repo "$TARGET" delegate /private/path/troubleshooting.json --mode quick
python3 "$FLOW" --repo "$TARGET" work --once --run-id INSTALL_RUN_ID --run-id FAQ_RUN_ID --run-id TROUBLESHOOTING_RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff INSTALL_RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff FAQ_RUN_ID
python3 "$FLOW" --repo "$TARGET" handoff TROUBLESHOOTING_RUN_ID
```

`delegate` 回傳的 JSON 有各自的 run ID；請把它填入後續指令。`work --once` 會把指定 ID 各處理一次，不會帶入其他排隊任務。預設最多同時 **3** 個 Pi delegate；用 `--pi-concurrency N` 調整上限（1–3），設為 `1` 會依序執行。只有標記獨立、相同來源 SHA、編輯檔案不重疊、無通配路徑且無人工核准門檻的低風險 Pi delegate 會並行；其他任務照順序處理。即使所有 worktree 都已驗證，整合後仍要對新 commit 執行 `verify`。Herdr supervisor 已在執行時，只需排入任務，讓它自行接手。

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
在 supervisor pane 按 Ctrl-C 會停止接新任務，並等待正在執行的 Pi delegate 到達安全完成點後退出；狀態和工作樹保留。再次啟動前先用 `status` 檢查中斷的 run，不要假設正在執行的 agent 已正常完成。

若專案根目錄有已追蹤的 `todo.md`，可把任務 ID 接到唯一一行：

```md
- [ ] 補上本機啟動說明 <!-- maf:document-quickstart -->
```

同一個 commit 的測試與審查都通過後，MAF 才會將該行改為 `[x]`。這代表 worktree 已驗證，**不代表已合併**。清單有衝突時只警告；修正後可用 `progress --sync` 再投影。根目錄 `todo.md` 變成未提交修改時，先提交清單再排下一個任務。

## PR、模型與本機資料

本機驗證完成後，明確使用 `publish RUN_ID` 才會發布。獨立 coder 任務也可在 `submit` 時加 `--publish`，或再加 `--auto-merge` 授權符合政策的低風險 PR 合併：

```sh
python3 "$FLOW" --repo "$TARGET" publish RUN_ID
python3 "$FLOW" --repo "$TARGET" submit /private/path/task.json --publish --auto-merge
```

自動合併仍要求同一 SHA 的測試與 review、乾淨 worktree、GitHub checks 成功，以及 strict required status checks；條件不明就停下，不使用管理員繞過。細節見 [GitHub 政策](IMPLEMENTATION.md#github)。

僅換模型／effort 時，在 Flow Studio 複製並儲存 flow 即可。要換 runtime／provider 才編輯專案的 `.maf.json` 角色，並選 `mode configured`。模型必須是該訂閱實際支援的 ID；不要把登入成功當成模型可用性證明。已開始的任務保留自己的模型快照。

Run 狀態、agent log、測試證據存在目標 repo 的 Git common directory 下 `maf/`，不進 Git；工作樹在 `.maf-worktrees/`。Log 可能含程式片段或敏感資訊，分享前先檢查。不要提交 `.maf-local.json`、token、個人設定或完整 transcript。
