# 工程經驗記憶（AGENT_LEARNINGS.md）

讓下一次任務不再踩同一個坑，又不把每次失誤都變成永久規則。原則：**Learning 不等於 Rule**。

| 檔案 | 代表 | 誰能改 |
| --- | --- | --- |
| `<project>/AGENTS.md` | 現在必須遵守的專案規則 | 主對話，且每次 promotion 先問人 |
| `<project>/AGENT_LEARNINGS.md` | 經驗紀錄，可被淘汰 | 主對話（curator） |
| `~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md` | 全域規則 | 只有人 |

Coder 只能「提出」：在最後回覆寫 `LEARNING: observation | cause | better approach | scope`，`handoff` 會解析成 `learning_candidates`。它不能改上面任何檔案（MAF 的路徑白名單也會擋下）。

只在自己的 repo 建立並提交 `AGENT_LEARNINGS.md`。別人的 repo 不建檔，只在對話中提出建議。專案之間不共用；某個 learning 若看來適用所有專案，只能向人提出全域規則建議。

## 任務開始：只取相關的

不論是自己做還是委派都要查。觸發點寫在全域指令檔（見[讓主對話自動使用 MAF](AGENT-INSTRUCTIONS.md)），因為主對話自己做的任務不會載入 skill。

用任務關鍵字（模組、工具、概念）搜尋，例如 `rg -n -i -C12 'migration|schema' AGENT_LEARNINGS.md`，只把命中且 `Status` 為 `validated`／`candidate` 的條目貼進 task 的 `instructions`。reviewer 會從 TASK 看到它們，並檢查實作有沒有違反。不要整份塞給 worker。

## 任務結束：Learning review

先問：**事先知道這件事，會不會明顯改善下一次類似任務？**不會就 `NO_ACTION`。typo、偶發 timeout、單次 flaky test、暫時環境問題、程式碼或官方文件已寫明的事，都不記。

失敗是最好的來源：`handoff` 的 `repairs` 與 `first_failure` 會說明第一次為什麼沒通過，`report` 也會把卡住的 run 的 `LEARNING:` 列成「經驗」。`analyze` 排出的反覆失敗原因也算：occurrences 用它的案例數，evidence 寫案例 ID。

只選一個動作：

- `NO_ACTION`
- `CREATE`：先搜尋，確定沒有等價條目才新增。
- `UPDATE`：已有等價條目時，`Occurrences` +1、更新 `Last verified`、補 `Evidence`，並重新評估 `Confidence`。
- `PROPOSE_PROMOTION`：條目已 `validated`、confidence 不是 low，而且曾重複發生或違反會造成嚴重後果。先問人；同意後把一句可執行規則寫進 `AGENTS.md`，條目改為 `promoted`（保留證據），並以獨立 commit 提交。
- `RETIRE`：架構、依賴或流程改變後不再適用；改 `Status: retired` 並寫原因，不要直接刪除。

一般 learning 的修改跟該任務的 commit 一起提交。

## 格式

```md
## L-001 — 一句話標題

Status: candidate | validated | promoted | retired
Scope: database/migrations
Category: concurrency
Confidence: low | medium | high
Occurrences: 1
Last verified: YYYY-MM-DD

- Observation: 看到了什麼（事實）
- Cause: 為什麼（推論要標明）
- Evidence: run ID、commit、測試名稱
- Better approach: 下次怎麼做
- Applies when / Does NOT apply when: 適用範圍
```

Confidence：`low` 是單次觀察；`medium` 是經過重現、review 或多次觀察；`high` 是重複發生，或有架構、測試、文件的強證據。`low` 不得直接升級成規則。

成功的標準不是條目數量，而是同類錯誤變少、context 維持精簡。條目上百筆、keyword 搜尋開始漏掉時，再考慮 SQLite 或 embeddings。
