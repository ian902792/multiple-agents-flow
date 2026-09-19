# 日常使用速查

已完成 [README](../../README.md) 的安裝、`init`、`doctor` 與 `confirm-billing` 之後，每天實際會用到的指令都在這裡。
完整說明與限制仍以 README 為準。

## 先設定變數

```sh
FLOW=/absolute/path/multiple-agents-flow/flow.py
TARGET=/absolute/path/your-project
```

`--repo` 是全域選項，**一定放在子命令前面**；省略時以目前資料夾為目標 repo。

```sh
python3 "$FLOW" --repo "$TARGET" status     # 正確
python3 "$FLOW" status --repo "$TARGET"     # 錯誤：argparse 不接受
```

## 一天的流程

```sh
# 1. 排入任務：只快照 task.json 與 HEAD，不呼叫模型、不 push
python3 "$FLOW" --repo "$TARGET" submit /absolute/path/task.json

# 2. 執行一個已排隊任務，完成後結束；會印出 run id
python3 "$FLOW" --repo "$TARGET" work --once

# 3. 查看所有 run 的狀態，或某一個 run 的完整證據
python3 "$FLOW" --repo "$TARGET" status
python3 "$FLOW" --repo "$TARGET" status RUN_ID

# 4. 本機 verified 之後，明確授權 push 與 draft PR
python3 "$FLOW" --repo "$TARGET" publish RUN_ID
```

`submit` 時須位於設定的主分支，已追蹤檔案不可有未提交變更；任務以 HEAD 已提交內容建立獨立 worktree。
`work` 不加 `--once` 會持續處理佇列（預設每 30 秒輪詢，`--poll` 可調 1–3600）。

## 在 Herdr 長時間執行

在 `HERDR_ENV=1` 的 Herdr pane 內執行：

```sh
python3 "$FLOW" --repo "$TARGET" herdr
```

會建立不搶焦點的背景 workspace，並在其中啟動 `work` supervisor。之後從其他 pane `submit`／`status` 即可。
Ctrl-C 只停 worker，已保存任務與 worktree 保留；不要停止 Herdr server。

## 等待不花模型額度

沒有任務、`waiting_quota`、等待 GitHub CI，supervisor 都只是本機輪詢，**不會呼叫任何模型**。
放著等不會消耗訂閱額度；只有 plan、實作、測試後修正與獨立審查階段才會呼叫模型。

## 中斷後恢復

先確認前一次 agent／測試程序真的已停止，再恢復：

```sh
python3 "$FLOW" --repo "$TARGET" resume RUN_ID --acknowledge-stopped

# 供應商明確告知額度重置時間時才使用，必須附時區
python3 "$FLOW" --repo "$TARGET" resume RUN_ID --acknowledge-stopped \
  --after '2026-09-20T08:00:00+08:00'
```

| 看到的狀態 | 下一步 |
|---|---|
| `queued` | 等 worker，或執行 `work --once` |
| `waiting_quota` | 等額度恢復後 `resume`；不切換 API |
| `needs_human` | 讀 `status RUN_ID` 的 feedback 與 log，處理後 `resume` |
| `verified` | 本機測試與審查通過，可 `publish` |
| `publishing` / `pr` | 網路操作結果不明時再跑一次 `publish RUN_ID` 核對，不會重複開 PR |

不要刪 worktree、強制 reset 或另開 PR 來「修復」狀態。

## 這個 private repo 的合併方式

本 repository 目前查詢 required status checks 分支保護時，GitHub 回覆 403（需 GitHub Pro 或 public repo）。
依「不新增費用、保持 private」的決定，未升級也未降低合併門檻，因此：

- `publish` 可以正常建立 draft PR、跑 CI。
- `--auto-merge` 會停在人工確認，**PR 需由你在 GitHub 上手動合併**。
- 這是方案限制，不代表自動合併已在此 repo 實測通過。

## 目前不支援的組合

- 預設是 Codex 規畫、Claude Code 實作、Pi 審查。
- `init --preset hermes-coder` 只把實作角色換成 Hermes coder profile；Hermes 的真實模型呼叫尚未實測。
- **不提供 Hermes 擔任 Reviewer／Planner**：其原生 file 工具組包含寫入，無法滿足唯讀角色要求。

實際驗證範圍見 [docs/VALIDATION.md](../VALIDATION.md)。
