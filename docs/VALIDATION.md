# 驗證紀錄

這份文件區分離線測試與真正的 provider / GitHub 驗證，避免把 mock 當成實際成功。

## 已完成

- 使用者指定的本機資料夾與 private GitHub repository 已建立並確認 visibility。
- Herdr 0.9.0：新建不切換焦點的工作區、Claude Opus 5 實作、Pi DeepSeek V4.1 Flash 唯讀審查。
- Codex 與 Claude 的訂閱登入，以及 Pi 的 Go provider / V4.1 預設已核對。
- 使用者明確確認三種訂閱均不使用超額額度。
- 54 個離線 unittest 已通過；包含獨立審查發現的回歸測試。
- 假 agent 的完整流程：隔離 worktree → 實作 → 真正執行測試程式 → 新 session reviewer → verified。
- 額度等待、不重播 running 狀態、SHA 漂移、設定變動、scope／symlink、有限修正、既有 PR 核對及 strict-check 阻擋。
- 真實非互動 smoke 已通過：Codex GPT-6 Astra 回應、Claude Opus 5 修改獨立暫存 worktree、Python 驗收、Pi DeepSeek V4.1 Flash medium 獨立審查，tested_sha 與 reviewed_sha 相同。
- 首次 live smoke 發現 `.git` 內 worktree 被 Claude 視為敏感檔案；已改放 `.maf-worktrees/`，保留安全模式後重跑成功。
- Pi 獨立審查提出的恢復重播、symlink、glob、損壞狀態、agent 自行 commit、GitHub UNKNOWN 等問題已修正並補測試。
- Hermes adapter 可切換 coder profile（safe mode）；**完整 Hermes 三角色 preset 未提供**，因原生 file toolset 不支援可靠的唯讀限制。這是已確認的限制，不是測試通過。

## 尚待完成／不宣稱完成

- GitHub PR 實際發布與分支保護合併；單元測試使用 mock，不能證明帳號具有 branch-protection 功能。
- Hermes coder 的真實模型呼叫尚未測試；只完成 CLI／登入探測與 parser／argv 單元測試。
- 任意專案的 UI／E2E、睡眠／重開機實機恢復、多人或多 lane 並行。

## 重跑

`python3 -m unittest discover -s tests -v`

測試不發模型請求、不安裝依賴、不寫 GitHub。真實模型測試須另外確認訂閱設定。

真實小型測試：`python3 scripts/smoke.py --live`。會使用訂閱額度，保留本機私人證據；不 push、不建立 PR。
CLI 顯示的 `cost` 是供應商估算的用量數據，不代表另行 API 扣款；本次路線均為確認過的訂閱登入。
