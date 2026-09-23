# 驗證紀錄

這份文件區分離線測試與真正的 provider / GitHub 驗證，避免把 mock 當成實際成功。

## 2026-09-20：主 agent skill 與模式切換

- 88 項離線 unittest 通過，新增模式切換保留任務／政策、Opus 5＋Sol 的 manual 任務路由、各設定獨立確認、單次模式覆寫、指定 run 不誤跑其他佇列，以及舊角色路由不隱含重播。
- Claude、Codex 專案內連結已建立，共用 `skills/maf/SKILL.md`；安裝重入、既有 skill 衝突及 symlink 父目錄拒絕有測試。
- Codex 原生 app-server `skills/list` 實際回傳 `maf`、`scope: repo`、`enabled: true`，未開啟 model turn。skill-creator 的 `quick_validate.py` 使用本機既有 Hermes Python 環境驗證通過，未新增套件。
- 使用方式已依 Claude／Codex 官方文件核對；實際發起模型工作的 `/maf run`／`$maf run` 尚未 live smoke，不宣稱已驗證宿主 UI 或真實模型審查結果。
- 移除 manual 任務隱含的 Planner 審查路由；風險分類不再更改選定的 Reviewer。

## 2026-09-20：用量與主任務進度

- 82 項工作樹離線 unittest 通過，包含 Pi 多次呼叫用量加總、缺失用量、逾時、權限停止不重試，以及 manual 任務使用獨立強模型審查。
- 主任務 JSON 快照、階段時限、處理提示、設定失效、Herdr 呼叫端 pane 傳遞與監看器結束前的最終回報皆有回歸測試。
- 真實本機的 `progress`／`progress --json` 已讀取既有狀態；新 Pi parser 已唯讀重算既有 log，沒有重寫歷史用量。
- 本次未發出模型請求；Herdr 呼叫以 mock 驗證，尚未在 Herdr pane 實測新的自動回報流程。
- 新角色設定使原有 billing 確認失效；啟動新的模型任務前，須依現有規則重新核對並執行 `confirm-billing --no-overage`。

## 已完成

- 使用者指定的本機資料夾與 private GitHub repository 已建立並確認 visibility。
- Herdr 0.9.0：新建不切換焦點的工作區、Claude Opus 5 實作、Pi DeepSeek V4.1 Flash 唯讀審查。
- Codex 與 Claude 的訂閱登入，以及 Pi 的 Go provider / V4.1 預設已核對。
- 使用者明確確認三種訂閱均不使用超額額度。
- 55 個離線 unittest 已通過；包含獨立審查發現與真實 permission denial 的回歸測試。
- GitHub Actions 已在 Ubuntu 24.04 通過同一套測試（初版 commit `3a9084c`）。
- 假 agent 的完整流程：隔離 worktree → 實作 → 真正執行測試程式 → 新 session reviewer → verified。
- 額度等待、不重播 running 狀態、SHA 漂移、設定變動、scope／symlink、有限修正、既有 PR 核對及 strict-check 阻擋。
- 真實非互動 smoke 已通過：Codex GPT-6 Astra 回應、Claude Opus 5 修改獨立暫存 worktree、Python 驗收、Pi DeepSeek V4.1 Flash medium 獨立審查，tested_sha 與 reviewed_sha 相同。
- 首次 live smoke 發現 `.git` 內 worktree 被 Claude 視為敏感檔案；已改放 `.maf-worktrees/`，保留安全模式後重跑成功。
- Pi 獨立審查提出的恢復重播、symlink、glob、損壞狀態、agent 自行 commit、GitHub UNKNOWN 等問題已修正並補測試。
- Hermes adapter 可切換 coder profile（safe mode）；**完整 Hermes 三角色 preset 未提供**，因原生 file toolset 不支援可靠的唯讀限制。這是已確認的限制，不是測試通過。
- 使用工具自己的 `submit --publish --auto-merge` 與 `herdr` 完成真實文件任務：Claude 編輯 → 55 項測試及文件檢查 → Pi approve / low → [draft PR #1](https://github.com/ian902792/multiple-agents-flow/pull/1)。GitHub CI 也通過。
- PR #1 的 tested_sha、reviewed_sha、GitHub head 均為 `d56515cefd6df9fc5e68439a29fc5097f73accde`；因下述分支保護 403，狀態正確停在 `needs_human / pr`，沒有合併。
- 另一次較大範圍的發布前複查在 300 秒上限中止，程序群組已停止，沒有被當作批准。首輪審查的具體問題由回歸測試逐項驗證；不宣稱額外全量複查通過。

## 尚待完成／不宣稱完成

- GitHub 自動合併的真實成功路徑尚未完成；單元測試包含成功／拒絕路徑，實際 private repo 被方案限制安全阻擋。
- Hermes coder 的真實模型呼叫尚未測試；只完成 CLI／登入探測與 parser／argv 單元測試。
- 任意專案的 UI／E2E、睡眠／重開機實機恢復、多人或多 lane 並行。

## 本帳號的 GitHub 限制

對此 private repository 查詢 required status checks protection，GitHub 實際回覆 HTTP 403，要求 GitHub Pro 或 public repository。
依使用者「不新增費用、保持 private」的選擇，未升級、未改公開、未降低合併門檻。
因此此 repo 可建立 draft PR、執行 CI，但目前自動合併會停在人工確認。這是方案限制，不是已完成的自動合併實測。

## 重跑

`python3 -m unittest discover -s tests -v`

測試不發模型請求、不安裝依賴、不寫 GitHub。真實模型測試須另外確認訂閱設定。

真實小型測試：`python3 scripts/smoke.py --live`。會使用訂閱額度，保留本機私人證據；不 push、不建立 PR。
CLI 顯示的 `cost` 是供應商估算的用量數據，不代表另行 API 扣款；本次路線均為確認過的訂閱登入。
