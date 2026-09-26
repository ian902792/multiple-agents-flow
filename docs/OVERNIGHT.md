# 一晚跑一批任務

睡前排好一整串小任務，讓 MAF 一件接一件做完；起床看一份報告，整合後自己做最後的實際使用測試。先跑模擬範例看看整個流程（幾秒完成，不呼叫模型、不花額度）：

```sh
python3 examples/overnight/demo.py
```

## 關鍵：睡前把會卡住的事先做完

晚上沒人能回答問題，所以成敗在規畫。

- **拆小**：每件任務只改少數檔案，驗收測試要真的能證明它做完了，並寫好 `acceptance_why`。
- **先規畫**：大需求先用 `/maf-plan`（Codex 用 `$maf-plan`）請另一家的強模型排出順序與依賴。
- **需要判斷的事睡前決定**：規格衝突、取捨、命名，留到晚上只會讓任務停在 `needs_human`。
- **敏感範圍先核准**：路徑含 auth、billing、order 等字的任務會停在 `awaiting_approval`，睡前 `approve`。
- **確認環境**：`doctor` 與訂閱確認都通過。

## 睡前：排入任務

有先後順序的任務用 `--depends-on` 串成鏈。下游會等上游 `tested`，再從上游測試通過的 commit 接著做；互不相依的任務直接排入即可。

```sh
python3 "$FLOW" --repo "$TARGET" delegate data-model.json
# 回傳 data-model-9b4840e5ad
python3 "$FLOW" --repo "$TARGET" delegate orders-api.json  --depends-on data-model-9b4840e5ad
python3 "$FLOW" --repo "$TARGET" delegate orders-page.json --depends-on orders-api-883edf53be
python3 "$FLOW" --repo "$TARGET" delegate docs-update.json
python3 "$FLOW" --repo "$TARGET" approve docs-update-55efc916ec   # 若有 awaiting_approval
```

平常只要對主 Agent 說「maf 今晚依序做完這些任務：1. … 2. 依賴 1 … 3. 依賴 2 …」，它會替你寫任務檔、串好依賴並核准你確認過的範圍。

然後啟動常駐的 supervisor，一件一件做：

```sh
python3 "$FLOW" --repo "$TARGET" work --delegate-concurrency 1
```

在 Herdr 裡可用 `herdr` 指令改為背景執行，並在暫時 pane 看每件任務的工具步驟。晚上時間多，依序執行比並行更容易看出是哪件出錯，也比較不會被供應商限流；互不相依的任務想加快，再調回 `--delegate-concurrency 3`。

## 起床：看報告、整合

```sh
python3 "$FLOW" --repo "$TARGET" report          # 預設看最近 24 小時；--hours 12、--json 皆可
```

報告依「先處理哪件」排序：

- **Needs you**：卡住的任務，附原因與下一步。
- **Waiting**：還在等額度、等上游或排隊中的任務。
- **Done**：通過測試的任務，並列出 coder 自己標出的存疑項。
- **Chains**：每條依賴鏈目前走到哪裡。
- **Ready to integrate**：整條完成的鏈或獨立任務，直接給出 `git cherry-pick 起點..終點`。檢查 diff、整合後，對新的 commit 跑一次 `verify`，再做你的實際使用測試。

## 出狀況時會怎樣

| 情況 | 上游任務 | 下游任務 |
| --- | --- | --- |
| 測試失敗 | 自動修一輪；仍失敗就停在 `needs_human` | 繼續等待 |
| 需求衝突或安全疑慮 | 停在 `needs_human`（需要重新規畫） | 標記為依賴失敗，不會執行 |
| 額度用完 | 停在 `waiting_quota` | 繼續等待；上游恢復並通過後接著做 |
| 登入或權限問題 | 停在 `needs_human`，修好後可 `resume` | 繼續等待 |

額度用完時，若供應商告訴你重置時間，用 `resume RUN_ID --acknowledge-stopped --after 時間` 讓它在那之後自動繼續，下游會跟著接上。依賴失敗的任務不會被重跑：處理完上游後，從那裡重新排一條鏈。

## 模擬範例在做什麼

`examples/overnight/demo.py` 用假的 agent，在暫時的 repo 與隔離的 MAF 設定裡模擬一晚：

- 一條成功的鏈：資料模型 → 訂單 API → 訂單頁面；
- 一件獨立任務：更新文件（路徑含 orders，睡前先核准）；
- 一條會卡住的鏈：退款規則與既有政策衝突，退款頁面因此不執行。

最後印出的正是早上會看到的 `report`。
