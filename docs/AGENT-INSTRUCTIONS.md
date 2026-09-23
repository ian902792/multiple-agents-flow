# 讓 Claude 自動使用 MAF

這份文件提供可複製到 Claude Code 指令檔的**個人工作偏好**。先依 [README](../README.md#快速開始) 完成一次全域 skill 與預設 flow 設定。任何已有 commit 的 Git 專案都可直接使用；`.maf.json` 只用於專案特別政策。MAF 的操作細節已在 [`maf` skill](../skills/maf/SKILL.md)，這裡只指定何時使用它。

## 放在哪裡

- **自己的所有專案：**貼到 `~/.claude/CLAUDE.md`。這是建議的預設做法，不必逐一修改 repository。
- **與團隊共享：**把通用規則放在專案的 `AGENTS.md`。避免把個人模型、訂閱或絕對路徑提交進 Git。
- **檢查是否載入：**開新的 Claude 對話後使用 `/context`。Claude Code 對 `AGENTS.md` 的載入會受版本、設定及專案是否已有 `CLAUDE.md` 影響；詳見 [Claude Code 文件](https://code.claude.com/docs/en/memory)。

## 可直接複製的個人提示詞

```md
## MAF 工作方式

- 在已有 commit 的 Git 專案依已安裝的 `maf` skill 使用 MAF；預設跟隨全域 flow，尊重目前專案的 mode 覆寫。除非我要求，否則不改全域 flow、模型或 effort；不自行建立 `.maf.json`。
- Claude 是主要開發者。小任務直接完成；只有範圍清楚、可獨立驗收的小工作才交給目前 flow 的 Pi 或 Antigravity，不為了使用多個 agent 而拆任務。若有多件功能互不依賴、可修改檔案互不重疊的小工作，先全部排入 delegate 並標記 `independent: true`，再讓 MAF 併發執行；有依賴或共用資源的工作依序執行。
- 程式碼完成後，只提交本次變更，不納入其他未提交修改；對乾淨的目前 HEAD 使用 `maf` skill 的 `verify` 動作。使用真實的專案測試；handoff 對應目前 commit 才能宣稱完成。未啟用獨立審查時說 `tested`，啟用且通過同一 SHA 的審查才說 `verified`。
- 大型任務先整理範圍與驗收標準。只有我明確輸入 `/maf-plan` 時才呼叫 Codex Planner；不要因任務規模自動啟動 Planner。
- 需要起點核准時，先列出目標、可修改路徑、測試命令、角色模型與風險供我確認一次。核准後在原範圍內自動執行；需求衝突、資安、權限、額度或核准範圍變化時才再次詢問。
- 進度先讀 MAF 摘要，阻塞時才讀相關 log。除非我已明確授權，否則不要發布 PR、push 或合併。
```

這段提示詞不會替代 MAF 的任務快照、核准與精確 SHA 驗證。它也不會自動安裝 CLI、登入供應商或啟用 Herdr。Claude 主對話的模型仍由你在 Claude terminal 用 `/model`、`/effort` 切換。

專案的 `AGENTS.md` 若要提供給不同使用者，建議只保留「遵守 mode、需要時使用 maf skill、`/maf-plan` 必須手動呼叫」等通用約定。MAF 自己啟動的 Codex Planner／Reviewer 使用受限的非互動模式，**不會靠專案 `AGENTS.md` 設定其模型或審查權限**；這些角色由 flow 與 MAF 政策決定。
