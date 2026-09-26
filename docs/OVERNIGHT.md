# 一晚跑一批任務

睡前讓另一家的強模型規畫、主對話做好核心，再由小任務 Agent 一件接一件做完；起床看一份中文報告，整合後自己做實際使用測試。

先看模擬（幾秒完成，不呼叫模型、不花額度）：

```sh
python3 examples/overnight/demo.py
```

## 你只要說三句話

1. **提需求**：`/maf-plan 訂單功能：資料模型、API、頁面、文件，今晚做完`（Codex 用 `$maf-plan`）
2. **回答問題並確認**：主 Agent 整理計畫摘要，問你需要決定的事；回答後它先做核心並 commit，你說「確認，開始吧」
3. **起床**：「maf 報告」

## 背後發生什麼

| 步驟 | 誰做 | 內容 |
| --- | --- | --- |
| 規畫 | Astra（Claude 主對話時）或 Claude（Codex 主對話時），只讀 | 交回完整計畫：介面約定、主對話先做的核心、需要你決定的問題、依序執行的任務鏈與驗收測試、風險 |
| 審閱 | 主對話 | 看計畫、把問題問你，用 `decide` 記下答案 |
| 核心 | 主對話 | 先做計畫中「主對話先做」的部分（例如資料模型骨架），commit 並驗證 |
| 試跑 | MAF，本機執行 | 在起點把每個驗收指令跑一次：應該失敗；已經通過或無法執行都會先報告，不呼叫模型、不花 token |
| 夜間 | 小任務 Agent（Pi、Antigravity 或 Codex） | 每條鏈依序執行，後一件從前一件測試通過的 commit 接著做 |
| 早上 | 主對話 | 看 `report`，整合完成的鏈並對新的 commit 驗證一次 |

**只要還有問題沒決定，整份計畫都不會執行**：方向對比做得快重要。計畫存在私人目錄（不進 Git），規畫者不能改 repo，計畫本身也不會自動授權任何執行。

## 對應的指令

主 Agent 會替你執行，平常不必自己打：

```sh
python3 flow.py --repo 專案 plan --goal-file 需求.md          # /maf-plan 在背後做的事，印出計畫 ID 與摘要
python3 flow.py --repo 專案 decide 計畫ID 1 現有政策          # 記下第 1 個問題的答案
python3 flow.py --repo 專案 night --plan 計畫ID --approve      # 試跑測試後依序執行，最後印出報告
python3 flow.py --repo 專案 report                            # 早上再看一次
```

`--approve` 代表你已看過計畫範圍，一次核准需要核准的任務（例如路徑含 auth、billing、order）。

## 報告長這樣

```
MAF 報告：最近 24 小時共 5 件任務（5 件測試通過）

已完成（5）
  orders-api-…  測試通過
  ...

依賴鏈
  orders-api-…（測試通過） → orders-page-…（測試通過）

可以整合（先看 diff，整合後對新的 commit 執行一次 verify）
  orders-api-… → orders-page-…
    git cherry-pick 起點..終點
```

有任務卡住時，會在最上面的「需要你處理」列出原因與下一步。

## 出狀況時會怎樣

| 情況 | 這件任務 | 接在它後面的任務 |
| --- | --- | --- |
| 測試失敗 | 自動修一輪；仍失敗就卡住 | 繼續等 |
| 需求衝突或安全疑慮 | 卡住，需要你決定 | 不會執行，報告會說明原因 |
| 額度用完 | 等額度 | 繼續等；額度恢復並通過後接著做 |
| 登入或權限問題 | 卡住，修好後可 `resume` | 繼續等 |

額度用完時，若知道重置時間，執行 `resume RUN_ID --acknowledge-stopped --after 時間`，它會在那之後自動繼續，後面的任務也會接上。

## 不用規畫也可以

需求已經很清楚時，直接列出任務檔即可：`night 資料模型.json 訂單API.json + 文件.json --approve`（依序串成鏈，`+` 分開不同的鏈）。想逐件控制：`delegate 任務.json --depends-on RUN_ID`，再用 `work --delegate-concurrency 1` 執行。
