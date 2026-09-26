# Pi coder 推理強度基準測試

用固定題目，比較 Pi coder 在不同推理強度（`off`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`）下的成功率、時間、token 與成本。題目走正常的 MAF `delegate` 流程，不需要安裝任何套件。

```sh
python3 bench/effort/run.py --task duration --levels off,low,medium,max --repeat 2 --confirm-subscription-only
python3 bench/effort/run.py --task webapp   --levels off,low,medium,max --repeat 2 --confirm-subscription-only
python3 bench/effort/run.py --flow quick-antigravity --task webapp --levels low,medium,high --repeat 2 --confirm-subscription-only
```

- **會花額度**：使用真實的 Pi／OpenCode Go 額度，每行指令約 $0.05～0.08 等值。先確認 Use balance 已關閉，再加 `--confirm-subscription-only`。
- **不動你的設定**：每個強度都在全新的暫時 repo 與隔離的 MAF 設定裡執行，你的全域 flow 與確認紀錄不受影響。
- **其他選項**：`--flow` 換成其他內建 flow（例如 `quick-antigravity`）、`--model` 換模型、`--keep` 保留暫時 repo 以便檢查、`--json` 輸出原始數字。Antigravity 的每個強度是不同的模型 ID（`gemini-3.8-flash-low`／`-medium`／`-high`），腳本會自動對應。

## 題目

| 題目 | 內容 | 測試 |
| --- | --- | --- |
| `duration` | 時間長度解析器：`1h30m`、`2d 4h`、ISO 8601 `PT1H30M`，拒絕各種不合法輸入，並能來回轉換。 | 8 個測試、兩百多個案例 |
| `webapp` | 標準庫 WSGI 待辦事項網站：HTML 表單頁（`<label>`、跳脫防 XSS）、表單轉址，JSON API 的 201／204／400／404／405／422 與 `Location`、`Allow` 標頭。 | 11 個測試 |

新增題目：在 `tasks/<名稱>/` 放題目檔、測試與 `task.json`（格式同一般 MAF 任務），`--task` 就會列出它。

## 2026-09-26 結果

DeepSeek V4.1 Flash，每題每個強度 2 次，16 次最後全部通過：

| 強度 | duration 一次通過 | webapp 一次通過 | duration 平均成本 | webapp 平均成本 | webapp 平均秒數 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `off` | 1/2 | 2/2 | $0.0043 | $0.0058 | 49 |
| `low` | 2/2 | 2/2 | $0.0031 | $0.0065 | 49 |
| `medium` | 1/2 | 1/2 | $0.0064 | $0.0104 | 84 |
| `max` | 2/2 | 2/2 | $0.0081 | $0.0143 | 102 |

`low` 是唯一兩題都一次通過、成本又最低或接近最低的強度，因此成為內建 Pi coder 的預設。`max` 同樣穩定，但成本約 2.4 倍、時間約 2 倍；`off` 在網頁題與 `low` 打平，卻在另一題失敗一次，而且這個模型在 `off` 仍會產生推理 token。快取命中率主要跟來回輪數有關，和強度關係不大。

### Antigravity（Gemini 3.8 Flash）

同日以 `--flow quick-antigravity` 跑同樣兩題，每題每個強度 2 次，12 次最後全部通過。Antigravity 走 Google 帳號額度，不回報金額：

| 強度 | duration 一次通過 | webapp 一次通過 | duration 平均秒數 | webapp 平均秒數 | 平均輸出 token | 其中思考 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `low` | 1/2 | 2/2 | 42 | 32 | 3,671 | 0 |
| `medium` | 2/2 | 2/2 | 127 | 108 | 41,197 | 38,235 |
| `high` | 2/2 | 2/2 | 151 | 166 | 52,990 | 50,069 |

`low` 完全不產生思考 token，速度約是 `high` 的 4 倍、輸出少了 90% 以上，唯一一次未一次通過也在一輪自動修復後通過。`medium` 與 `high` 都一次通過，但 `medium` 更快、用量更少。依此結果，`quick-antigravity` 的預設改為 `gemini-3.8-flash-low`（`low`）。和 Pi `low`（duration 28 秒、webapp 49 秒，4/4 一次通過）相比，Antigravity `low` 速度相當，一次通過率略低。

### Codex（GPT-6 Luna）

GPT-6 Luna 支援的推理強度是 `none`、`low`、`medium`、`high`、`xhigh`、`max`（不支援 `minimal`，API 會回 400）。以 `--flow quick-codex --levels none,low,medium,high --repeat 3` 跑兩題，共 24 次，**最後全部通過**。Codex 走 ChatGPT 訂閱額度，只回報 token、不回報金額：

| 強度 | 一次通過 | 最後通過 | duration 平均秒數 | webapp 平均秒數 | 平均總輸入（含快取） | 快取命中 | 平均輸出 | 平均推理 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `none` | 5/6 | 6/6 | 52 | 56 | 121,427 | 81.8% | 1,735 | 0 |
| `low` | 3/6 | 6/6 | 50 | 55 | 134,149 | 80.3% | 1,720 | 0 |
| `medium` | 5/6 | 6/6 | 70 | 59 | 139,486 | 86.0% | 1,994 | 313 |
| `high` | 5/6 | 6/6 | 81 | 111 | 164,688 | 86.9% | 3,384 | 1,330 |

第一次沒通過的 6 次，都在一輪自動修復後通過，原因是：

| 原因 | 次數 | 強度 |
| --- | ---: | --- |
| duration：接受了數字與單位之間有空格的 `1 h`（規格要求拒絕） | 3 | none、low、low |
| duration：簡寫格式實作錯誤（大寫 `1H 5S` 報錯、61 秒起來回轉換失敗） | 2 | low、medium |
| webapp：用了 `urllib` 卻沒有 import | 1 | low |
| webapp：`/api/todos/1/extra` 回 405，應該是 404 | 1 | high |

`none` 與 `low` 在 Luna 上都不產生推理 token，行為相同，一次通過率的差異（5/6 對 3/6）在這個樣本量下只是雜訊。`medium`、`high` 沒有提高一次通過率，只讓速度變慢、用量變多，所以 `quick-codex` 預設用 `none`。每次請求固定約 1.85 萬 token 是 Codex CLI 自己的系統提示與工具定義，總輸入因此是 Pi 的 5 倍以上，其中八成多命中快取。和 Pi `low`（4/4 一次通過，duration 28 秒）相比，Luna 較慢、一次通過率較低，但輸出 token 最少。

樣本很少，不同任務的結果也會不同，建議用自己的工作再跑一次。
