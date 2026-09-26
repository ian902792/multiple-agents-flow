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

## 回報問題

開 issue 時請附上足以重現問題的資訊，缺少這些我們通常只能猜：

- MAF 版本（`python3 flow.py --version`）、你的作業系統與 Python 版本（`python3 --version`）。
- `python3 flow.py --repo <專案> doctor` 的完整輸出；這個指令不會呼叫模型，可以安心貼上。
- run ID，以及 `python3 flow.py --repo <專案> progress --json` 中與問題相關的片段。
- 你預期會發生什麼，以及實際上發生了什麼；有錯誤訊息就整段附上。
- 不要把 API 密鑰、token、完整對話紀錄或個人絕對路徑貼進來；請先把它們塗掉，或改成 `/path/to/...`、`$FLOW` 這類佔位。

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

## 發布新版本

版本號只寫在 `maf/__init__.py` 的 `__version__`，採用語意化版本（1.0 以前：次版號代表新功能或行為改變，修訂號代表修正）。

1. 在同一個 PR 裡更新 `__version__`，並在 `CHANGELOG.md` 最上面新增該版本的段落（`## [X.Y.Z] - 日期`）；測試會檢查兩者一致。
2. 合併進 `main`。
3. 打上對應的 tag 並推送：`git tag vX.Y.Z && git push origin vX.Y.Z`。

推送 tag 後，`Release` workflow 會確認 tag 與 `__version__` 相同、跑完測試，再以 `CHANGELOG.md` 對應段落建立 GitHub Release。

## 寫作慣例

- 使用者文件用繁體中文，程式碼、註解與 commit 訊息用英文。
- 中文粗體的標點放在 `**` 外面，例如 `**重點**：說明`。寫成 `**重點：**說明` 在 GitHub 會顯示成字面的星號。
- 範例指令用 `/path/to/...` 或 `$FLOW` 這類佔位，不放自己的絕對路徑。
