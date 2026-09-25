# 參與貢獻

歡迎送 issue 與 PR。MAF 的價值來自幾條固定原則，送 PR 前請先確認沒有違反：

- **只用 Python 3.11+ 標準庫**，不新增相依套件。
- **只用現有訂閱**：不加入 API 計費的備援路線或繞過旗標。
- **agent 的說法不算驗證**：測試與獨立審查必須綁定精確的 Git commit。
- **狀態不明就停下**：額度、登入、核准過期或任何無法確認的狀態，一律失敗關閉。
- **不改使用者的帳號、帳單、全域設定或分支保護。**
- **Git 裡不放密鑰、對話紀錄、執行狀態或個人絕對路徑。**
- **adapter、確定性的編排、GitHub 政策三者分開**，不要混在同一個模組。

## 開發

```sh
git clone https://github.com/ian902792/multiple-agents-flow.git
cd multiple-agents-flow
python3 -m unittest discover -s tests -v
```

測試全部離線執行，用假的 agent 與暫時的 Git repository，不會呼叫模型，也不需要登入。

## 先開 issue 的情況

以下變更請先開 issue 討論方向，避免白做：

- 新增 agent adapter，或讓既有工具載入外掛（見[新增 agent adapter](docs/ADAPTERS.md)）。
- 改變核准、帳單確認、發布或自動合併政策。
- 新增指令或改變任務 JSON 格式。

錯字、文件補充與小修正可以直接送 PR。

## PR 檢查清單

- [ ] `python3 -m unittest discover -s tests -v` 全部通過。
- [ ] 新行為有對應的測試；修 bug 時附上能重現問題的測試。
- [ ] 使用者看得到的改變，已更新 `README.md`、`docs/CLI.md` 或導覽網站 `site/index.html`。
- [ ] 規則或狀態機的改變，已更新 `docs/IMPLEMENTATION.md`。
- [ ] 新增 adapter 時：附上 CLI 名稱與版本、使用的訂閱路線、已去除個資的真實輸出樣本，並在 `docs/VALIDATION.md` 記下是否實測。

## 寫作慣例

- 使用者文件用繁體中文，程式碼、註解與 commit 訊息用英文。
- 中文粗體的標點放在 `**` 外面，例如 `**重點**：說明`。寫成 `**重點：**說明` 在 GitHub 會顯示成字面的星號。
- 範例指令用 `/path/to/...` 或 `$FLOW` 這類佔位，不放自己的絕對路徑。
