# multiple-agents-flow

**讓 Claude Code 當主開發者，其他 agent 在需要時接手明確的工作。** MAF（multiple-agents-flow）會替子任務建立獨立工作樹、執行專案測試，並記錄另一個 agent 對同一個 Git commit 的審查結果。你留在原本的 Claude 對話，不必為每個專案重裝工具。

日常流程是：**Claude 開發 → 可選 Pi 小任務 → 測試 → Codex 獨立審查**。大型任務只有在你手動輸入 `/maf-plan` 時，才會先請 Codex 規畫。工具使用現有訂閱，不會偷偷改用付費 API。

## 先了解三個詞

| 名稱 | 意思 |
| --- | --- |
| **Flow** | Planner、Pi、Reviewer 等角色的模型與 effort 設定。內建 `quick`、`planned`，也可在本機畫面儲存自己的 flow。 |
| **Mode** | 某個專案目前選用的 flow。在 terminal 用 `/maf mode 名稱` 切換；不影響已開始的任務。 |
| **Verified** | 測試通過，且獨立 reviewer 審查了**同一個 commit**。這不代表已 push、建立 PR 或合併。 |

MAF 的網頁是**設定畫面**；任務的呼叫、mode 切換及進度查詢都在 terminal 完成。

## 快速開始

需要 macOS 或 Linux、Python 3.11+、Git 和 Claude Code。預設的 `quick`／`planned` flow 也需要 Codex CLI 與 Pi CLI：初次檢查會確認所有角色的登入狀態，即使你暫時不委派 Pi。目標專案必須是已有第一個 commit 的 Git repository。

**1. 在電腦上安裝一次：**

```sh
git clone https://github.com/ian902792/multiple-agents-flow.git
cd multiple-agents-flow
python3 flow.py install-skills
```

`install-skills` 註冊全域的 Claude `/maf`、`/maf-plan` 及 Codex `maf` skill。想用畫面編輯 flow，再執行 `python3 flow.py ui` 開啟只監聽本機的 Flow Studio。若 Claude 對話已經開著，請重新開一個 session，讓它載入 skill。

**2. 在每個要使用 MAF 的專案設定一次：**進入該專案的 Claude 對話，輸入：

```text
/maf setup quick
```

這會建立專案的 `.maf.json`、選擇 `quick` 並檢查工具是否可用。**不用再次安裝 skill。** 首次使用某組模型前，請依提示到供應商控制台確認：模型包含在你的訂閱內，而且額外付費用量／OpenCode Go 的 Use balance 已關閉。MAF 會記錄你的確認，不能代替供應商設定費用上限。直接使用 CLI 的做法見[指令參考](docs/CLI.md#初次設定)。

**3. 開始工作：**照常請 Claude 修改程式。需要獨立驗證時：

```text
/maf verify 這次修改要達成的結果
/maf status
```

`verify` 會針對已提交、乾淨的目前 commit 執行測試與獨立審查；Claude 的 `/maf` skill 會準備所需的任務資料。若你還沒 commit，先讓 Claude 完成本次修改並提交。看到 `verified`，才表示這個 commit 已通過驗證。

## 選擇適合的 flow

| 情境 | 在 Claude terminal 輸入 | 接下來 |
| --- | --- | --- |
| **日常小任務** | `/maf mode quick` | Claude 實作；需要時用 `/maf delegate 需求` 交給 Pi；完成後用 `/maf verify 需求`。 |
| **中大型任務** | `/maf mode planned` | 你決定是否手動輸入 `/maf-plan 需求`；看過規畫後由 Claude 實作、整合與驗證。 |
| **自己的工作方式** | `/maf mode 我的-flow` | 先在 Flow Studio 儲存命名 flow，再於各專案的 terminal 選用。 |

`planned` 只設定角色及提醒；**選到它不會自動啟動 Planner**。Pi 適合路徑明確、可獨立驗收的小任務。Pi 做完後，Claude 仍需檢查並整合變更，再對整合後的新 commit 執行 `verify`。

Flow Studio 可複製 flow，設定各角色 model／effort，並把新輸入的模型 ID 加入建議清單。畫面不會切換目前 Claude 對話的模型；要切換主對話，請在 Claude 輸入 `/model` 或 `/effort`。新模型是否可用，仍要以你自己的 CLI 與訂閱確認。

## 想讓 Claude 自動遵循這套流程

安裝 skill 後，你仍可決定是否讓 Claude 在一般開發需求中**主動**套用 MAF。把[可複製的個人提示詞](docs/AGENT-INSTRUCTIONS.md)放進 `~/.claude/CLAUDE.md`，就不必在每個專案重貼；它只對已有 `.maf.json` 的專案生效。這份規則保留你的偏好：Claude 主導、小工作才交 Pi、大型任務的 Codex 規畫只由你手動啟動。

提示詞是行為指引，不是權限機制。人工核准仍由你確認，MAF 程式會檢查凍結的任務範圍與驗證證據。團隊共享的規範可放在專案 `AGENTS.md`；詳細載入方式與檢查步驟也寫在[提示詞文件](docs/AGENT-INSTRUCTIONS.md)。

## 核准與進度

一般小任務照你的需求直接做。對敏感、範圍較大或需求不明的任務，Claude 先提出可檢查的計畫；你確認一次後，MAF 會在核准範圍內接續測試、審查與有限次修正。只有需求有誤、資安或權限風險、額度不足等情況，才停下來請你決定。

`/maf status` 會顯示目前的任務與下一步。常見狀態是 `awaiting_approval`（等待你檢視範圍）、`running`、`verified`、`waiting_quota`、`needs_human`。核准本機執行**不等於**允許 push 或合併；這兩項需要另外明確授權。詳見[指令與恢復流程](docs/CLI.md#核准阻塞與恢復)。

## 可選：在 Herdr 觀看 agent 進度

若你在 Herdr 開不同專案 workspace，可開啟全域 Herdr 整合，然後**在 Herdr pane 內**啟動背景 supervisor：

```sh
FLOW=/absolute/path/multiple-agents-flow/flow.py
TARGET=/absolute/path/your-project
python3 "$FLOW" settings herdr on
python3 "$FLOW" --repo "$TARGET" herdr
```

主 pane 會顯示進度標題。Coder、Reviewer 執行時會開暫時 pane 顯示即時事件摘要，結束後自動關閉；你手動執行 `/maf-plan` 時也會有 Planner pane。Agent 仍由 MAF supervisor 執行與驗證。目前任務依序處理，所以同時最多一個 MAF agent 觀察 pane。Herdr 整合預設關閉；沒有 Herdr 也能正常使用 MAF。

## 使用界線與延伸閱讀

- 只使用你已確認的訂閱路線；額度或登入不明時會停止，不會改用 API 計費。
- 只在你信任的 repository 使用。工作樹不是安全沙箱，專案測試會執行你核准的命令。
- 預設只做到本機驗證；發布 PR 或合併需要額外明確授權。
- 目前只有一條任務執行線；多個任務會排隊，不會自動並行。

需要直接使用 Python CLI、編寫任務 JSON、處理中斷或設定 PR 政策，請看[指令參考](docs/CLI.md)。想了解狀態機與安全檢查，請看[實作契約](docs/IMPLEMENTATION.md)；給 LLM 的詳細規則在[MAF skill](skills/maf/SKILL.md)，已實測與尚未實測的範圍記在[驗證紀錄](docs/VALIDATION.md)。

專案以 [MIT](LICENSE) 授權。開發者可執行 `python3 -m unittest discover -s tests -v`。
