# 用歷史案例持續改善 MAF

在主對話說「maf 分析歷史案例並改善效率」，或自己執行：

```sh
python3 flow.py analyze --days 30
python3 flow.py stats --days 30
```

兩個指令只讀本機 run state，不讀 transcript、不啟動 agent、不改設定。`analyze` 列出失敗原因、案例 ID、改善優先序，並把 verify、delegate 與未知種類分開。完成數需要保存的測試命令完整通過，啟用審查時還需要同 SHA 的 approve；清理過 worktree 的案例仍能分析，但不能拿歷史完成數代替當下的 `handoff`。只有明確 `superseded_by` 相連的重試會合併成一件工作；相同 task ID 或 SHA 不會被猜成同一件成果。

`stats` 的「正常結束」表示原生 CLI 正常結束，不表示審查通過。原因有三種來源：新 run 記錄的 `recorded`、從舊 run 明確證據推得的 `inferred`、無法確認的 `unknown`。缺少用量仍是未知，不算零。改善優先序按受影響 run 數排列，不能據此排名模型或推定因果。

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
