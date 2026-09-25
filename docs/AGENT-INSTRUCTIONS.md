# 讓主對話自動使用 MAF

安裝 skill 後，主 Agent 只有在你提到 maf 時才會用它。想讓它在一般開發中**主動**委派與驗證，把下面這段短提示詞放進全域指令檔。先依 [README](../README.md#快速開始) 完成一次全域 skill 與預設 flow 設定。

## 為什麼這麼短

指令檔會在每個專案、每一輪對話都載入，多寫一行就每輪多花一次 token。所以這段提示詞只說**何時用、為什麼用**；**怎麼用**寫在 [`maf` skill](../skills/maf/SKILL.md)，只有用到時才載入；任務範圍、核准、精確 SHA 驗證、訂閱檢查則由 MAF 程式強制執行，不必靠提示詞提醒。現在的模型夠聰明，給它目標與取捨原則，比列出步驟更省、也更能應變。

## 可直接複製的提示詞

Claude 與 Codex 共用同一段：

```md
## MAF
- 以「maf」開頭的話是在指揮 MAF；沒有 maf 時，flow、mode 等字照一般意思理解。
- 你是主開發者。在 Git 專案可以依 `maf` skill 委派小任務與驗證 commit。
- 委派是為了省你的上下文與等待時間：範圍清楚、測試能驗收、自己做得讀很多檔或寫大量樣板的工作才交出去；小改動或需要全局判斷的直接做。互不依賴的工作一次排入，讓它們並行。
- 交出去後只看 handoff 與 diff，不重讀它讀過的檔；卡住時才看 log。整合完對最終 commit 驗證一次，不必每個小改動都跑。
- 大型或需求不明的任務，建議我用 maf-plan，不要自己啟動。
- 宣稱完成要有目前 commit 的 MAF 證據，並只提交本次變更；push、PR、合併要我明說。
```

## 放在哪裡

- **自己的所有專案**：Claude 貼到 `~/.claude/CLAUDE.md`，Codex 貼到 `~/.codex/AGENTS.md`。不必逐一修改 repository。
- **與團隊共享**：專案的 `AGENTS.md` 只放第一、二、五行這類通用約定；個人模型、訂閱與絕對路徑不要提交進 Git。
- **檢查是否載入**：開新對話後，Claude 用 `/context` 查看。`AGENTS.md` 的載入方式依工具版本與設定而異，詳見 [Claude Code 文件](https://code.claude.com/docs/en/memory)。

## 不需要寫進提示詞的事

以下已由 skill 或程式負責，重複寫只會浪費 token：

- 跟隨全域 flow 與專案 mode、不擅自改模型或 `.maf.json`。
- `tested` 與 `verified` 的用詞、`independent: true` 的並行條件。
- 敏感範圍的核准流程、額度或登入不明時停下。
- 規畫者與審查者必須和主對話不同家；它們以受限的非互動模式執行，不讀專案 `AGENTS.md`。

主對話的模型與 effort 仍由你在各自的 CLI 切換（Claude 用 `/model`、`/effort`）；這段提示詞也不會安裝 CLI、登入供應商或啟用 Herdr。
