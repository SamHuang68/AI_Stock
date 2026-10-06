# AGENTS.md — Stock Terminal (AI_Stock) 專案入口

這份檔案只記 **Stock Terminal 專屬的位置、環境與操作事實**。全域規則不在這裡，也不複製：

1. `C:\Users\Sam\AI-Workspace\AGENTS.md`：目錄協議（每個專案一份 current、任務工作樹、一位寫入 owner、刪除暫緩）。索引在 `AI-Workspace\workspace.json`。
2. `C:\Users\Sam\AI-Workspace\projects\shared-ai-memory`：**權威共用規則**。先讀 `_rules/0005-collaboration-boundaries.md` 與 `sessions/handoff-current.md`；程式進版、授權分層與修訂歷史見 `_rules/0007`；證據與如實回報見 `_rules/0008`；本專案發布流程見 `procedures/ai-stock-private-web-release.md`。
3. 本專案的 `.cursorrules`（鐵律）。

**共同對齊來源（Sam 2026-10-07 指示）：共用記憶（AI-Workspace 的 `shared-ai-memory`）與 GitHub 是 Codex、Claude、Antigravity 三者共通的對齊來源，不應因本機或雲端專案而出現歧異。** 因此雲端與本機的副本都不是各自的真源；只存在於某一邊的事實（路徑、環境、流程）要記進 GitHub（本檔、`docs/revision.md`）或共用記憶（寫入需 Sam 授權，規則 `0012`），不要只留在單一代理人的私有記憶或對話裡。

與共用規則或使用者的最新指示衝突時，以後者為準。雲端工作階段**讀不到上述本機檔案**：開工前請使用者貼上相關檔案，或請使用者明說不需要。本檔內容只含從使用者機器輸出與倉庫文件驗證過的事實。

## 1. 位置與角色

| 角色 | 位置 | 埠 | 備註 |
| --- | --- | --- | --- |
| 開發工作樹（current） | `C:\Users\Sam\AI-Workspace\projects\stock-terminal` | — | 登記為受管安裝的 `originalCheckout`。新的開發任務依全域協議使用 `AI-Workspace\worktrees\stock-terminal\<task>` |
| 本機受管安裝 | `%LOCALAPPDATA%\StockTerminalLocal\current` | `127.0.0.1:18432` | 跟隨正式站的 SHA，有自己的 `data/`，與正式站不共用 DB |
| 正式站（private web） | `%LOCALAPPDATA%\StockTerminalPrivateWeb\current` | 後端 `18435`、閘道 `18434` | 只透過 stage → promote 更新 |
| 稽核證據與發布工具 | `C:\Users\Sam\AI-Workspace\docs\stock-terminal\<task>\`（不在 Git 內） | — | `release\` 證據、`release-tools\` 發布腳本（`deploy.ps1`、`sync-local.ps1` 等），最新一份在 `st-evidence-presentation` |
| 舊路徑（已退役） | `C:\Users\Sam\AI_Stock` | — | 2026-10-03 遷移到上列 current（`local_install.json` 的 `checkoutPathMigration`）。僅留作備份，**不得在此啟動、更新或部署** |

機制細節：`docs/本機與正式版本同步.md`、`docs/PRIVATE_WEB_ST.md`、`docs/私有發布完整性.md`。

## 2. 本專案的操作規則

1. **先唯讀檢查，再給任何更新、啟動或部署指令**（第 4 節）。
2. **不要在未登記的資料夾執行 `START_TIP.cmd` 或 `scripts\go.ps1`。** 在非登記資料夾它走開發流程，會關掉 18432 埠上的程序（含本機受管 ST）。`go.ps1` 現會在這種情況下拒絕執行；要刻意在別處開發必須明確加 `-Worktree`。
3. **不要依埠 taskkill 18432。** 受管程序的命令列是 `python -B -u "%LOCALAPPDATA%\StockTerminalLocal\current\server\server.py"`，且須與 `local_process.json` 登記相符；`start_local.ps1` 遇到 18432 上的其他程序會拒絕啟動、不會終止它。開發程序是 `python -u server\server.py`，兩者不要同時跑。
4. **發布不由雲端代理人執行。** 發布走 stage → promote，工具與證據格式見第 1 節；授權分層與發布前提（CI、完整 SQLite 備份、停止服務）以共用規則 `0007` 與 `procedures/ai-stock-private-web-release.md` 為準，發布器本身不備份、不停服務。雲端代理人只提供精確 SHA、CI 結果與驗收標準，交給本機發布者。
5. **更新開發工作樹：** `stock_terminal_v2.html` 是啟動時重建的產物，更新前 `git stash push -- stock_terminal_v2.html` 保留，不要丟棄；`data/` 的修改是執行期資料，不要還原；用 `git pull --ff-only origin main`。被未追蹤檔擋住時，把檔案搬到備份資料夾再 pull，不刪除；不用 `reset --hard`、`clean`、強制推送。
6. **給使用者的指令一律是 PowerShell。** 讀 UTF-8 檔案要加 `-Encoding UTF8`（Windows PowerShell 5.1 預設用本機碼頁，中文會變成無法復原的亂碼）；要讓輸出可貼回，用 `& { … } *>&1 | Tee-Object -FilePath $log`，再 `Get-Content $log -Raw | Set-Clipboard`。
7. **雲端工作階段的 Git 做法**（共用規則 `0007`）：只用明確檔案清單暫存（不用 `git add -A` 或 `git add .`），並用 `git diff --cached --name-only` 核對；比對與回報用完整 SHA；不 force push。在已合併 PR 的工作分支上接續工作時，把 `origin/main` 合併進分支，不要 reset 後強推。 完整 Python 測試套件與全倉庫靜態或安全掃描屬「完整掃描測試」（規則 `0008` 第 13 條）：執行前先向 Sam 說明範圍、影響與耗時並取得同意（每個 PR 推送前問一次，或依 Sam 的常設同意）；針對本次改動的測試直接跑。

## 3. 版本與修訂歷史

程式的任何進版都要在 `docs/revision.md` 留下紀錄（共用規則 `0007`）：基底 SHA、實作與合併 SHA、原因、修正後行為、驗證、**發布狀態**。`VERSION` 不因修正而變；「已合併」不等於「已發布」，以正式站與本機的 runtimeCommit 為準。歷史段落不覆寫，後續狀態以新段落補記。新增檔案與目錄用英文命名（共用規則 `0013`）。

## 4. 唯讀檢查（確認路徑與版本，不改任何東西）

```powershell
$lr = Join-Path $env:LOCALAPPDATA 'StockTerminalLocal'
$pr = Join-Path $env:LOCALAPPDATA 'StockTerminalPrivateWeb'
$cfg = Get-Content (Join-Path $lr 'local_install.json') -Raw -Encoding UTF8 | ConvertFrom-Json
"originalCheckout    : " + $cfg.originalCheckout
"LOCAL current commit : " + (Get-Content (Join-Path $lr 'current\.private_web_release.json') -Raw -Encoding UTF8 | ConvertFrom-Json).commit
"PROD  current commit : " + (Get-Content (Join-Path $pr 'current\.private_web_release.json') -Raw -Encoding UTF8 | ConvertFrom-Json).commit
Get-NetTCPConnection -LocalPort 18432 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  "18432 listener PID " + $_.OwningProcess + " : " + (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)").CommandLine }
```

## 5. 事故紀錄

2026-10-07：雲端代理人沿用已退役的 `C:\Users\Sam\AI_Stock`，指示使用者在該資料夾執行 `START_TIP.cmd`。該資料夾不是登記的 `originalCheckout`，`go.ps1` 走開發流程並關掉 18432 埠上的程序，改跑一份未受管的開發版（03:33:05 啟動）。處置：改由 `%LOCALAPPDATA%\StockTerminalLocal\start_local.ps1` 啟動受管安裝（03:48:00 啟動，runtimeCommit `e0b1147…`）。根因：路徑遷移沒有記錄在倉庫、`go.ps1` 沒有防呆。對應修正：本檔、`go.ps1` 的拒絕檢查，以及把同類的 `scripts\apply.bat`（強制 checkout、`stash -u`、依埠 taskkill）改為停用的存根。事後證據：前一份受管程序的 log 最後寫入 2026-10-05 18:41，距事發約 33 小時，事發當時 18432 上很可能沒有受管程序在運行，因此很可能沒有關閉任何受管程序；這是推論，不是證明（前一份 receipt 已被新啟動覆寫，無法查看）。
