# 用歷史案例持續改善 MAF

在主對話說「maf 分析歷史案例並改善效率」，或自己執行：

```sh
python3 flow.py analyze --days 30
python3 flow.py stats --days 30
```

兩個指令只讀本機 run state，不讀 transcript、不啟動 agent、不改設定。`analyze` 列出失敗原因、案例 ID、改善優先序，並把 verify、delegate 與未知種類分開。完成數需要保存的測試命令完整通過，啟用審查時還需要同 SHA 的 approve；清理過 worktree 的案例仍能分析，但不能拿歷史完成數代替當下的 `handoff`。只有明確 `superseded_by` 相連的重試會合併成一件工作；相同 task ID 或 SHA 不會被猜成同一件成果。

`stats` 的「正常結束」表示原生 CLI 正常結束，不表示審查通過。原因有三種來源：新 run 記錄的 `recorded`、從舊 run 明確證據推得的 `inferred`、無法確認的 `unknown`。缺少用量仍是未知，不算零。改善優先序按受影響 run 數排列，不能據此排名模型或推定因果。

舊 adapter 曾把額度或登入失敗記為一般 `error`；沒有 recorded 原因時，`analyze` 用保存的失敗 feedback 與現行 adapter 分類器辨識，仍標為 inferred。這只改善診斷，不改原始 run、正常結束率、驗證證據或恢復條件。

## 主對話與委派的量測

`delegate TASK.json` 一次完成限定範圍的實作、supervisor 測試、預算內修復與已啟用審查；`--queue` 才只排隊。主對話給目標、邊界與真正的驗收條件，讓 coder 在範圍內定位細節，再檢查 diff 和 handoff。幾行的小改動直接做，架構與需求判斷由主對話處理。這是減少主對話工作量的設計，尚不代表已量出 Opus 額度節省。

新 run 自動保存主 runtime、Python/platform、每次 agent 的模型、原生用量、耗時、狀態、request bytes/hash，以及完成測試命令的 SHA、退出碼、耗時、修復輪次與獨立 log。修復後不刪除早先失敗的紀錄。`tests` 仍只表示最終驗收；`test_history_complete` 表示是否從任務建立時完整記錄已完成的測試命令，中斷命令保留 activity/log，沒有退出碼就不假造結果。`timings.tests_seconds` 包含完整歷史中的失敗與重跑；舊或不完整歷史留 `null`。`stats` 的秒數仍是 child agent 耗時，完整執行耗時看 `timings`。

主對話用量不在 child agent 的原生回報裡。用 `observe RUN_ID FILE.json` 追加量測，例如下列私人 JSON；它可以在 run 清理之後記錄，不修改驗證狀態：

```json
{
  "experiment": "delegation-pilot",
  "case": "bounded-module",
  "strategy": "delegate",
  "main_runtime": "codex",
  "source": "Main-chat usage unavailable in this host",
  "scope": "task",
  "input_tokens": null,
  "output_tokens": null,
  "cache_read_tokens": null,
  "cache_write_tokens": null,
  "seconds": null
}
```

`strategy` 是 `direct` 或 `delegate`，`main_runtime` 是 `codex` 或 `claude`，`scope` 是 `task` 或 `session`。來源要寫實際取得方法，token 欄位分開記錄未快取輸入、輸出、cache read/write；若來源只提供含快取的總 input，無法拆分就留 null，不能重複計算。tokens 須為非負整數，秒數須為有限非負數；未知用 null，不用零。字串不得有控制字元；不要填 token、私人 transcript 或帳號秘密。每筆追加伺服器記錄時間和當時 run 的 tested/owned SHA；舊紀錄不覆寫，session 用量不加到 task 或 child 總數。

選一小批工作量相近的任務，以相同 `experiment`、可比較的 `case` 記錄兩種策略。保存主 agent 實際用量（含快取分類）、總等待時間、失敗與返工，再比較每件完成工作的代價。不同模型、測試、依賴、任務難度或只有 session 總數時，不能宣稱差額由委派造成。只有 Pi 成功率或花費，不足以證明主 agent 更省；本次由 Codex 主導的 pilot 也不能直接推算 Opus 節省比例。

```sh
python3 flow.py --repo "$TARGET" --main codex observe RUN_ID /private/path/observation.json
python3 flow.py --repo "$TARGET" --main codex analyze --json > /private/path/analysis.json
```

`analyze --json` 的 cases 包含各次 agent 原生用量、測試命令歷史、耗時、主對話 observations 和工具版本，沒有 transcript 或測試 tail。快照可能含本機路徑，留在 Git 私有目錄。`clean --apply` 只清理已整合工作樹/分支，仍保留 run state、測試 log 與模型呼叫 log。缺少舊資料就保持未知，不回填推估數字。

## 一次改善的循環

1. 先保存原始快照；它含本機 repository 路徑與 run ID，留在 Git 私有資料中：

   ```sh
   python3 flow.py analyze --json > .git/maf/improvement-baseline.json
   ```

2. 選一個有證據、出現頻繁或耗時高的原因。用 `status RUN_ID` 看保存的任務、測試、角色與失敗；只有診斷特定案例時才讀相關 log。記錄可重現觸發條件、預期結果與驗收指令。不要把真實 transcript 或個人路徑加入 Git。
3. 把案例縮成不含私人資料的回歸測試，同時保留應該通過與應該被阻擋的對照。先使測試重現問題，再修共用流程中的根因。新邊界案例直接加入現有測試，避免另建資料庫。
4. 在新 branch 上修改，由 MAF 對最終 commit 執行完整測試及已授權的獨立審查。通過 `handoff` 才整合；新 SHA 不沿用舊證據。
5. 累積新的實際案例後，比較新增的 run：

   ```sh
   python3 flow.py analyze --baseline .git/maf/improvement-baseline.json
   ```

   baseline 排除已看過的 run，避免把原先案例反覆算成新結果。它不是跨期完整生命週期成本：如果 retry 跨過 baseline，舊 attempt 的花費在上一期。樣本少、任務或環境不同時，結果只代表觀察，不宣稱速度或準確率已改善。保存新的完整快照再開始下一輪。

## 審查上下文與一次最終驗證

審查 prompt 優先提供變更檔案，再以 Python AST 找出它們直接引用的本地模組與 package `__init__.py`。所有內容都從同一 HEAD 讀取，共用 200,000 bytes 上限；超出上限的檔案只列名稱，不先載入。只補一層、repo 根目錄的絕對 import 或檔案所在 package 的相對 import，不解析執行環境、動態 import 或其他語言；reviewer 仍可讀必要的其他相依檔案。

2026-10-01，以 Pi DeepSeek V4.1 Flash / low 各跑一次舊版（`02d57cd`）與新版。沿用 effort benchmark 的 bug-chunk、clean-chunk，但在兩組暫存 fixture 都把原實作移到 base 的 `helper.py`，change 的 `chunks.py` 只保留 `from helper import chunk`；bug-path 保持原樣作無 import 對照。

| 案例 | 舊版秒數 / 模型呼叫 | 新版秒數 / 模型呼叫 | 兩組判斷 |
| --- | ---: | ---: | --- |
| bug-chunk（直接 import） | 18.4 / 3 | 10.2 / 1 | changes_requested |
| clean-chunk（直接 import） | 20.7 / 5 | 15.3 / 2 | approve |
| bug-path（無 import） | 8.0 / 1 | 9.8 / 1 | changes_requested |

這是每組每題一次的小樣本，只支持減少取得相依內容的來回，不宣稱一般加速倍率或完整審查準確率。200 KB 是預載預算，超出可按需讀取，不要求拆 commit；既有 120,000 字元 diff 硬限制維持，超過仍需拆任務。

實作 commit 與 merge commit 的 tree 可以完全相同，兩次驗證不是內容檢查的必要條件。要保留 exact-SHA 證據又只驗證一次，可以在獨立 branch 先建立包含實作的最終 merge commit，對它執行完整測試與審查。CI 通過後，確認 main 仍在原 base，再讓 main fast-forward 到這個已驗證的 merge commit；其 merge 歷史保留，SHA 也不變。若 main 移動、解衝突或新增任何 commit，重新準備最終 commit 並驗證。GitHub 另行產生 merge commit 時也要驗證它的新 SHA，不能只憑 tree 相同沿用證據。

## 格式修復與證據重用

原始審查回覆另存於 run 的私有 `review-response.json`，以雜湊、run ID、task/config scope 與 tested SHA 綁定。嚴格 parser 保持不變：只有一個完整、符合 schema 且 SHA 正確的 fenced JSON 候選才進入格式修復。多個候選、外部結構、重複欄位、過大回覆、失效 SHA 與矛盾 approve/findings 都阻擋。

同一個已選定的 reviewer 只接收保存的回覆，確認前後文字沒有相反決定或未解 finding，然後原樣輸出 JSON；不重新讀程式或執行測試。Pi 使用 `--no-tools`，Claude 使用空的 `--tools` 並關閉 MCP；只有這兩個已確認原生停用工具能力的 runtime 能做轉換，其餘保持阻擋，需提交新審查。模型、帳號與推理強度沿用原 reviewer。修復後全部欄位值必須等於原候選，且每份回覆最多一次完成的轉換。拒絕、改值或再次輸出錯誤都不會成為通過；quota/服務中斷則可在確認前一程序停止、額度已重置後恢復同一 run 的轉換階段。

恢復 reviewing/review_format 前仍檢查完整測試命令、通過結果、目前 SHA、工作樹、approval 與 config；不重跑已通過的測試。操作人仍須確認測試的外部服務與安裝環境沒有改變；無法確認就提交新 verify run，不能把乾淨 Git 工作樹當成環境未變的證明。第一版不做跨 run／跨 SHA 快取。

可重複執行的檢查：

```sh
python3 -m unittest tests.test_history -v
python3 -m unittest tests.test_flow.FlowTests.test_review_format_repair_preserves_original_without_retesting tests.test_flow.FlowTests.test_format_repair_quota_resumes_only_conversion_and_rejects_changed_fields tests.test_flow.FlowTests.test_ambiguous_and_contradictory_review_recovery_stays_blocked -v
```

這些測試驗證恢復、安全邊界與統計，沒有宣稱模型能找出所有程式缺陷。若要衡量誤報、漏報，沿用 [effort benchmark](../bench/effort/README.md) 的固定缺陷與乾淨對照，明確標註預期 finding；真實模型 benchmark 另外執行，不混進一般測試或自動新增付費路由。改善流程產生建議，不自行修改 flow、模型、帳號或全域設定。
