# 新增 agent adapter

MAF 沒有外掛機制，這是刻意的：每種 agent 都用一組經過審核的固定參數呼叫。開放任意 CLI 參數或端點，會讓訂閱檢查、只讀權限與範圍限制被繞過。要支援新的 agent，就在 `maf/agents.py` 加一個 adapter，走一般的 PR 審查。

## 先判斷是哪一種擴充

| 想做的事 | 需要什麼 |
| --- | --- |
| 同一個工具換模型（例如 Pi 改跑另一個 DeepSeek 模型） | 不用改程式。在 Flow Studio 輸入模型 ID，再執行一次 `confirm-billing`。 |
| 新的 agent CLI（例如某家的 coding agent） | 新增 adapter，依本文步驟。 |
| 讓既有工具載入外掛或設定包（例如 Pi 的 extensions） | 先開 issue 討論。MAF 目前會關閉 Pi 自動載入的 extensions、skills、prompt templates 與 context files，讓每次執行可預測。若該外掛是有自己執行檔的分支版本，就當成新的 agent CLI。 |

## 收件條件

新的 adapter 必須全部符合，否則不合併：

- **只走訂閱登入**：使用 CLI 自己的帳號登入，不接受 API key 路由。只能用按量計費 API key 的工具，不符合 MAF 的原則，請自行 fork。
- **無頭模式與結構化輸出**：能從 stdin 或參數收 prompt 一次執行完，輸出可解析的 JSON 或 JSONL，並有明確的「本輪完成」事件。
- **分得出失敗原因**：能辨識額度用完、未登入、權限被拒，對應到 `quota`、`blocked`。結束代碼 0 本身不代表成功。
- **固定參數**：模型、effort、工具清單由 MAF 決定；不預先放行所有工具，不接受使用者額外傳入的參數或端點。
- **權限對應角色**：當 coder 需要可編輯模式；要當規畫者或審查者，必須有**原生的只讀模式**（不是靠 prompt 要求它別改檔）。沒有只讀模式的，就只能當 coder，比照 `hermes`、`antigravity`。
- **登入檢查不呼叫模型**：`doctor` 只能用 CLI 的登入狀態指令或讀設定檔，不能送出推論請求，也不能印出或讀取憑證。

## 要改的地方

以最單純的 Pi adapter 為樣板，所有位置都在 `maf/agents.py`：

1. **`_ROUTES`**：登記 runtime 名稱與它唯一允許的 provider，例如 `"pi": "opencode-go"`。
2. **`validate_role`**：若這個 agent 沒有只讀模式，在這裡拒絕 `access: "read"`；若 effort 選項不同，也在這裡限制。
3. **`_argv`**：組出固定參數。Pi 的例子：

   ```python
   tools = "read,grep,find,ls" + (",edit,write" if edit else "")
   return ["pi", "--print", "--mode", "json", "--provider", "opencode-go", "--model", model,
           "--thinking", effort, "--tools", tools, "--no-extensions", "--no-skills", "--no-prompt-templates",
           "--no-context-files", "--no-approve", "--offline"]
   ```

   重點是：工具清單依 `access` 決定；關閉會改變行為的自動載入；prompt 一律走 stdin，不放在 argv（argv 會寫進 log）。
4. **`_auth_problems`**：加入登入狀態指令與判斷，例如 Pi 用 `pi auth check --provider opencode-go --json`，只接受 `status == "ready"`。
5. **`_parse_<runtime>` 與 `_PARSERS`**：從輸出找出最後一輪的助理回覆，回傳 `_ok(text, session_id, usage)` 或 `_classify(錯誤訊息)`。規則：
   - 找不到任何結果事件時回傳 `None`，`run_agent` 會改用 stderr 判斷原因。
   - 回合沒有正常結束（例如被截斷、後面又開始新一輪）要回傳 `error`，不能把半截回覆當成功。
   - `usage` 只加總供應商實際回報的數字；缺漏或不完整時回傳 `None`，不要估算。
6. **`clean_env`**：若這個 CLI 會讀某些環境變數改變端點或金鑰，把前綴加進 `_SCRUB_PREFIX`，避免子行程被導到 API 計費。

`run_agent` 已經統一處理逾時、結束代碼非 0 卻回報成功、log 與 live pane，一般不需要改。

## 其他要一起改的

- **Flow Studio**（`maf/static/index.html`）：在工具選單加入新的 runtime，並在 `coderRoutes`、`suggestedModels` 加上 provider 與預設模型。能當審查者或規畫者的，才加進對應選單。
- **文件**：`docs/IMPLEMENTATION.md` 的 adapter 規範與 allowed subscription routes；`README.md` 若有使用者需要知道的差異。
- **驗證紀錄**：`docs/VALIDATION.md` 記下用哪個 CLI 版本、在真實訂閱上跑過什麼；沒跑過就寫「尚未實測」。

## 測試

`tests/test_agents.py` 不呼叫任何模型，新 adapter 至少要在這幾個類別各加案例：

- **`RoleValidation`**：合法角色、錯誤 provider、不支援的 `access` 被拒。
- **`ArgvSafety`**：可編輯與只讀的參數確實不同；沒有預先放行或繞過旗標。
- **`Parsers`**：用 `jl(...)` 把**真實 CLI 錄下的事件**組成樣本，至少涵蓋成功、額度用完、未登入、回合未完成、沒有結果事件。樣本要刪掉 session 以外的個人資訊與任何憑證。
- **`RunAgent`**：用 `FakeExec` 確認登入失敗會在推論前擋下。

執行 `python3 -m unittest discover -s tests -v` 全部通過再送 PR。
