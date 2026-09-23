# multiple-agents-flow

**讓 Claude Code 當主開發者，其他 agent 在需要時接手明確的工作。** MAF（multiple-agents-flow）會替子任務建立獨立工作樹、執行專案測試；你也可以選擇讓另一個 agent 審查同一個 Git commit。你留在原本的 Claude 對話，不必為每個專案重裝工具。

日常流程是：**Claude 開發 → 可選 Pi 或 Antigravity 小任務 → 測試 → 可選獨立審查**。你平常只要在 Claude 對話描述需求；Claude 會使用 MAF skill 處理委派與驗證。大型任務只有在你手動輸入 `/maf-plan` 時，才會先請 Codex 規畫。工具使用現有訂閱，不會偷偷改用付費 API。

## 先了解三個詞

| 名稱 | 意思 |
| --- | --- |
| **Flow** | Planner、小任務 Agent、Reviewer 等角色的模型與 effort 設定。內建 `quick`、`planned`、`quick-antigravity`，也可在本機畫面儲存自己的 flow。 |
| **Mode** | 新專案直接使用全域預設 flow；對 Claude 說「這個專案改用某個 flow」可覆寫單一專案，也可手動使用 `/maf mode 名稱`。不影響已開始的任務。 |
| **Tested** | 未啟用獨立審查時，指定測試已對目前 commit 通過。 |
| **Verified** | 已啟用獨立審查，測試與 reviewer 都通過**同一個 commit**。兩種狀態都不代表已 push 或合併。 |

MAF 的網頁是**全域設定畫面**；任務的呼叫、單一專案的 mode 切換及進度查詢都在 terminal 完成。

## 快速開始

需要 macOS 或 Linux、Python 3.11+、Git 和 Claude Code。預設 `quick`／`planned` 另需 Codex CLI 與 Pi CLI；若選 `quick-antigravity`，小任務 Agent 改用已登入的 `agy` CLI。目標專案必須是已有第一個 commit 的 Git repository。

**1. 在電腦上安裝一次：**

```sh
git clone https://github.com/ian902792/multiple-agents-flow.git
cd multiple-agents-flow
python3 flow.py install-skills
```

`install-skills` 註冊全域的 Claude `/maf`、`/maf-plan` 及 Codex `maf` skill。執行 `python3 flow.py ui` 會開啟只監聽本機的設定頁；「說明與理念」在另一頁。若 Claude 對話已經開著，請重新開一個 session，讓它載入 skill。

**2. 設定全域預設一次：**用 Flow Studio 選 flow 並按「設為全域預設」，或在 MAF 專案 terminal 輸入：

```sh
python3 flow.py settings default-flow quick-antigravity
python3 flow.py settings
```

預設原本是 `quick`；上例把明確的小任務改交 Antigravity 的 Gemini 3.8 Flash High。主 Claude 偏好現為 **Opus 5.5**。獨立審查預設關閉，在設定頁勾選後才會呼叫 reviewer。首次使用某組角色前，請先在供應商確認模型包含在現有訂閱、額外付費用量／OpenCode Go 的 Use balance 已關閉，再執行：

```sh
python3 flow.py confirm-billing --no-overage
```

這份確認按模型角色組合**全域記錄一次**；換新模型或路由時須再次確認。從舊版的專案內確認升級時，也須重新執行一次全域確認。MAF 不會代你更改供應商帳單設定。

**3. 在任何 Git 專案開始工作：**不用 `init`，也不用每專案重新安裝 skill。照常在 Claude 對話描述工作，例如：

> 請按目前 flow 完成這項修改。路徑與驗收明確的小工作可以委派；完成後測試已提交的變更，告訴我結果與 commit SHA。

Claude 的 `/maf` skill 會準備任務資料，並在需要時執行委派與驗證。驗證針對已提交、乾淨的目前 commit 執行測試；若該 flow 勾選「獨立審查」，才會再呼叫 reviewer。結果為 `tested` 或 `verified`，清楚區分是否完成審查。

## 選擇適合的 flow

| 情境 | 對 Claude 說 | 接下來 |
| --- | --- | --- |
| **日常小任務** | 「這個專案改用 quick，請完成這項修改。」 | Claude 實作；明確的小工作可交 Pi。 |
| **Gemini 小任務** | 「這個專案改用 quick-antigravity。」 | 明確的小工作可交 Antigravity Gemini 3.8 Flash High。 |
| **中大型任務** | 「這個專案改用 planned，先整理需求。」 | 只有你手動輸入 `/maf-plan 需求` 才會請 Codex 規畫；Claude 負責後續實作、整合與驗證。 |
| **自己的工作方式** | 「這個專案改用我的 flow。」 | 先在 Flow Studio 儲存命名 flow，設為全域預設或於單一專案選用。 |

`planned` 只設定角色及提醒；**選到它不會自動啟動 Planner**。Pi 與 Antigravity 適合路徑明確、可獨立驗收的小任務。委派完成後，Claude 仍需檢查並整合變更，再驗證整合後的新 commit。要回全域預設，可對 Claude 說「改回全域預設 flow」，或手動使用 `/maf mode default`。切到尚未確認訂閱的角色組合時，先核對供應商設定，再從 MAF 資料夾執行 `python3 flow.py --repo /path/to/project confirm-billing --no-overage`。

**指令分工：**你可視需要手動用 `/maf status` 看進度、`/maf mode` 切換專案 flow、`/maf-plan` 請 Codex 規畫；`/model` 和 `/effort` 控制目前 Claude 對話。`/maf delegate`、`/maf verify`、`/maf handoff` 等是主 Claude 依需求使用的工作指令，平常不必逐條輸入。完整用途與輸出見 Flow Studio 的「說明與理念」頁。

### 同時交給多個小任務 Agent

如果有幾件**互不依賴**的小工作，可以在同一則需求中列出來，例如：「同時處理 1. 補 `docs/install.md` 安裝範例；2. 補 `docs/faq.md` 常見問題；3. 補 `docs/troubleshooting.md` 疑難排解，各自驗收」。Claude 會先拆成不同任務、標記可並行，再一起排入；MAF 預設同時執行最多 **3 個 Pi／Antigravity delegate**。每個任務都有自己的 worktree、測試與 commit 證據；審查只在勾選時執行。編輯路徑重疊、使用通配路徑、需要人工核准，或不是同一來源 commit 的任務會等前一件完成。

同時執行主要縮短等待時間；小範圍委派也可減少主 Claude 對話的上下文負擔，但**並行本身不保證總 token 變少**。Claude 仍負責逐件檢查、整合，最後驗證整合後的 commit。[CLI 範例](docs/CLI.md#任務資料與執行)說明如何指定 run ID 和調整並行上限。

Flow Studio 可複製 flow，切換小任務與審查工具、設定各角色 model／effort，並把新輸入的模型 ID 加入建議清單。畫面不會切換目前 Claude 對話的模型；要使用 Opus 5.5，請在 Claude 輸入 `/model claude-opus-5-5`，effort 用 `/effort` 切換。新模型是否可用，仍要以你自己的 CLI 與訂閱確認。

## 想讓 Claude 自動遵循這套流程

安裝 skill 後，你仍可決定是否讓 Claude 在一般開發需求中**主動**套用 MAF。把[可複製的個人提示詞](docs/AGENT-INSTRUCTIONS.md)放進 `~/.claude/CLAUDE.md`，就不必在每個專案重貼。這份規則保留你的偏好：Claude 主導、小工作才交所選的小任務 Agent、大型任務的 Codex 規畫只由你手動啟動。

提示詞是行為指引，不是權限機制。人工核准仍由你確認，MAF 程式會檢查凍結的任務範圍與驗證證據。團隊共享的規範可放在專案 `AGENTS.md`；詳細載入方式與檢查步驟也寫在[提示詞文件](docs/AGENT-INSTRUCTIONS.md)。

## 核准與進度

一般小任務照你的需求直接做。對敏感、範圍較大或需求不明的任務，Claude 先提出可檢查的計畫；你確認一次後，MAF 會在核准範圍內接續測試、可選審查與有限次修正。只有需求有誤、資安或權限風險、額度不足等情況，才停下來請你決定。

`/maf status` 會顯示目前的任務與下一步。常見狀態是 `awaiting_approval`（等待你檢視範圍）、`running`、`tested`、`verified`、`waiting_quota`、`needs_human`。核准本機執行**不等於**允許 push 或合併；這兩項需要另外明確授權，且 MAF 發布／自動合併仍要求獨立審查。詳見[指令與恢復流程](docs/CLI.md#核准阻塞與恢復)。

## 可選：在 Herdr 觀看 agent 進度

若你在 Herdr 開不同專案 workspace，可開啟全域 Herdr 整合，然後**在 Herdr pane 內**啟動背景 supervisor：

```sh
FLOW=/absolute/path/multiple-agents-flow/flow.py
TARGET=/absolute/path/your-project
python3 "$FLOW" settings herdr on
python3 "$FLOW" --repo "$TARGET" herdr
```

主 pane 會顯示進度標題。各個同時執行的 Pi／Antigravity 任務，其 Coder 與已啟用的 Reviewer 會各自開暫時 pane 顯示即時事件摘要，結束後自動關閉；你手動執行 `/maf-plan` 時也會有 Planner pane。Agent 仍由 MAF supervisor 執行與驗證。Herdr 整合預設關閉；沒有 Herdr 也能正常使用 MAF。

## 使用界線與延伸閱讀

- 只使用你已確認的訂閱路線；額度或登入不明時會停止，不會改用 API 計費。
- 只在你信任的 repository 使用。工作樹不是安全沙箱，專案測試會執行你核准的命令。
- 預設只做到本機驗證；發布 PR 或合併需要額外明確授權。
- Antigravity 使用 `agy` 的 Google 帳號登入、`--sandbox` 與受限權限；MAF 拒絕 API key 路由或預先放行工具。`doctor` 會查詢模型清單，但**不會呼叫模型**。授權／額度不明時停止。
- 並行只用於明確標記為獨立的窄範圍 Pi／Antigravity delegate；其他任務依序執行。

需要直接使用 Python CLI、編寫任務 JSON、處理中斷或設定 PR 政策，請看[指令參考](docs/CLI.md)。想了解狀態機與安全檢查，請看[實作契約](docs/IMPLEMENTATION.md)；給 LLM 的詳細規則在[MAF skill](skills/maf/SKILL.md)，已實測與尚未實測的範圍記在[驗證紀錄](docs/VALIDATION.md)。

專案以 [MIT](LICENSE) 授權。開發者可執行 `python3 -m unittest discover -s tests -v`。
