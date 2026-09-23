# 驗證紀錄

這份文件區分離線測試與真正的 provider / GitHub 驗證，避免把 mock 當成實際成功。

## 2026-09-23：設定頁排版與人／Agent 指令分工

- 103 項 unittest 全數通過，`git diff --check` 無問題；此次只改設定頁樣式及說明文件，沒有發出模型請求。
- 在隔離的暫存全域設定中實測 Flow Studio：原本 800px 視窗的整頁 `scrollWidth` 為 857px；修正後 1998、950、900、800、770、760、390px 視窗均無整頁橫向溢出。寬螢幕「工具／Model／Effort」控制項頂線一致，窄桌面改為兩行。
- `/guide` 先顯示人可直接說的自然語言範例與四項可選指令；主 Claude 的八項工作指令和維護者 CLI 預設收合。瀏覽器操作確認展開後可讀；390px 說明頁沒有整頁橫向溢出。未修改使用者實際全域設定。

## 2026-09-23：Opus 5.5、可選審查與獨立說明頁

- 103 項 unittest 全數通過。離線完整流程證實未勾選審查時只呼叫 coder，通過測試後停在 `tested`；`handoff` 回傳精確 SHA 與測試結果、`review: null`，不宣稱 `verified`，也拒絕發布。勾選審查的既有 SHA 證據與發布路徑仍通過。
- Flow Studio 在隔離的暫存全域設定目錄進行瀏覽器測試：新 flow 的主 Claude 偏好是 `claude-opus-5-5`，審查預設未勾選；切到 Antigravity、勾選與取消審查、把審查工具切為 Pi、儲存全域預設、重新載入皆正確。獨立 `/guide` 頁顯示理念、安裝、flow 範例與指令輸出。設定與說明頁在 390px 手機寬度均無整頁水平溢出。
- 未呼叫真實模型，未修改使用者實際全域 MAF 設定。畫面的主 Claude 模型是偏好記錄；現有 Claude session 仍需以 `/model` 切換。

## 2026-09-23：Antigravity 與零專案設定的全域預設

- 102 項 unittest 全數通過；新增測試涵蓋無 `.maf.json` 的 Git 專案繼承全域 flow、切換回全域預設、角色模型確認跨專案共用，以及 Antigravity 的帳號路由、stdin、sandbox、成功／額度／權限拒絕解析。
- 本機已安裝 `agy` 1.2.9；唯讀 `agy models` 列出 `gemini-3.8-flash-high`。未呼叫真實 Gemini 模型，也未替使用者更改登入、供應商費用設定或使用者全域 MAF 設定。新路由仍需使用者先確認訂閱涵蓋與沒有額外計費。
- Flow Studio 在隔離的暫存全域設定目錄中完成瀏覽器互動：把 coder 從 Pi 切到 Antigravity，模型自動改為 Gemini 3.8 Flash High、effort high，儲存並設為全域預設；重新載入後設定仍正確。390px 手機視窗 `scrollWidth=390`，無整頁橫向溢出。GUI 選單定位錯誤在實測時發現並修正。
- Antigravity CLI 沒有與 Pi 相同的原生 file-only 工具白名單；MAF 使用 headless request-review、sandbox、無預先放行工具與獨立路徑／測試／review 檢查。此版未做真實 Antigravity 編輯、Herdr pane 或並行模型 smoke。

## 2026-09-23：全域 flow 與 terminal 操作

- 94 項 unittest 在允許 loopback 的環境全數通過；涵蓋全域 skill 安裝與衝突拒絕、跨專案 flow 可見而 mode 各自獨立、無 Git repository 時的全域 CLI、GUI token／Origin、Herdr 預設關閉與停用後拒絕 pane 回報。
- 已在本機使用者目錄建立 `~/.agents/skills/maf`、`~/.claude/skills/maf`、`~/.claude/skills/maf-plan` 三個 symlink，未覆寫同名 skill。從非 Git 目錄執行 `settings` 回傳 `{"herdr_enabled": false}`。
- 用瀏覽器在隔離的暫存全域設定目錄新增 `docs-review` flow、儲存 Herdr 開關；畫面提示 terminal 使用 `/maf mode docs-review`，且沒有 mode 切換按鈕。說明頁列出 32 筆 skill／CLI 指令；390px 手機寬度沒有整頁水平溢出。
- 沒有在 Herdr pane 或真實模型上執行新整合；Herdr 命令與 pane metadata 以 mock 測試。下列較早紀錄描述當時的專案內安裝與 GUI 切換，已被目前設計取代。

## 2026-09-23：獨立 Pi 任務並行

- 100 項 unittest 全數通過。
- 離線測試使用三個假 Pi coder 的同步屏障，確認同時執行；在它們工作時仍可排入新任務。測試也確認第四個任務排隊、重疊編輯路徑延後、各自測試與 review 綁定各自精確 SHA。
- Herdr 觀察 pane 的模擬測試確認兩個 pane 可同時開啟並各自關閉；尚未在真實 Herdr 與模型供應商上執行並行驗證。

## 2026-09-23：Claude-first flow 與本機畫面

- 92 項 unittest 在允許 loopback 的環境全數通過；一般 sandbox 禁止 bind 時，UI HTTP 測試會跳過，其餘通過。HTTP 測試涵蓋 token／Origin 限制、flow 儲存與選取。
- 假 agent 的 `delegate` 與 `verify` 流程驗證：Pi 在獨立 worktree 編輯；Claude 既有 commit 只跑測試與非 Claude reviewer；`handoff` 要求同一 tested/reviewed SHA。失敗的外部 commit 不轉給 Pi 修復。
- 本機 Flow Studio 用瀏覽器實看桌面與 390px 手機版：切換 quick/planned、檢查真實 run 表格及無整頁水平溢出；另在臨時 Git 專案透過畫面新增 flow、修改 Pi effort、儲存並選用，CLI 讀回相同設定，複製 `/model` 指令成功。畫面不會自動呼叫模型。
- 視覺對照檢查了側欄寬度、白底／藍色強調、主要按鈕、三個 agent 列的文字與控制項、近期任務表格及手機版收合。相對概念圖，產品加入使用者要求的 Claude 主對話模型控制與匯入匯出；模型 ID 和任務資料改用真實值。1586×992 原生桌面視窗需向下捲動看完整表格；1586×1330 全頁截圖已覆蓋整個畫面，無裁切或整頁水平溢出。
- 新的 `/maf-plan` Claude skill 設為手動觸發；未呼叫真實 Codex/Claude/Pi 模型，也未驗證 Claude 宿主實際列出此 skill。

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
- 任意專案的 UI／E2E、睡眠／重開機實機恢復、多人跨程序同時操作、真實 Pi／Herdr 併發。

## 本帳號的 GitHub 限制

對此 private repository 查詢 required status checks protection，GitHub 實際回覆 HTTP 403，要求 GitHub Pro 或 public repository。
依使用者「不新增費用、保持 private」的選擇，未升級、未改公開、未降低合併門檻。
因此此 repo 可建立 draft PR、執行 CI，但目前自動合併會停在人工確認。這是方案限制，不是已完成的自動合併實測。

## 重跑

`python3 -m unittest discover -s tests -v`

測試不發模型請求、不安裝依賴、不寫 GitHub。真實模型測試須另外確認訂閱設定。

真實小型測試：`python3 scripts/smoke.py --live`。會使用訂閱額度，保留本機私人證據；不 push、不建立 PR。
CLI 顯示的 `cost` 是供應商估算的用量數據，不代表另行 API 扣款；本次路線均為確認過的訂閱登入。
