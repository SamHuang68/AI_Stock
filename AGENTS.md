# AGENTS.md — 所有 AI 協作者（Claude／Codex／Cursor 等）開工前必讀

這份檔案是路徑、環境與部署規則的**單一來源**。`CLAUDE.md` 與 `.cursorrules` 都指向這裡；
與其他舊文件衝突時，以這裡為準。**不要憑記憶或舊對話假設任何本機路徑。**

## 1. 位置與角色

| 角色 | 位置 | 埠 | 備註 |
| --- | --- | --- | --- |
| 開發工作樹（唯一） | `C:\Users\Sam\AI-Workspace\projects\stock-terminal` | — | 登記為 `originalCheckout`（見下方唯讀檢查）。開發資料夾永遠不是正式資料夾 |
| 本機受管安裝 | `%LOCALAPPDATA%\StockTerminalLocal\current` | `127.0.0.1:18432` | 跟隨正式網站的 SHA，有自己的 `data/`，與正式網站不共用 DB |
| 正式網站（private web） | `%LOCALAPPDATA%\StockTerminalPrivateWeb\current` | 後端 `18435`、閘道 `18434` | 只透過 stage → promote 更新 |
| 舊路徑（已退役） | `C:\Users\Sam\AI_Stock` | — | 2026-10-03 已遷移到上列開發工作樹（`local_install.json` 的 `checkoutPathMigration` 有紀錄）。僅留作備份，**不得在此啟動、更新或部署** |
| 發布稽核證據 | `C:\Users\Sam\AI-Workspace\docs\stock-terminal\…`（不在 Git 內） | — | 見 `docs/revision.md` |

詳細機制：`docs/本機與正式版本同步.md`、`docs/PRIVATE_WEB_ST.md`、`docs/私有發布完整性.md`。

## 2. 規則

1. **先唯讀檢查，再給任何更新／啟動／部署指令。** 雲端 agent 看不到使用者的電腦：請使用者執行下方檢查並把輸出貼回，再動作。
2. **不要在未登記的資料夾執行 `START_TIP.cmd` 或 `scripts\go.ps1`。** 在非登記資料夾它會走開發流程，並關掉 18432 埠上的任何程序（包含正在使用的本機受管 ST）。`go.ps1` 現已在這種情況下拒絕執行；要刻意在別的資料夾開發，必須明確加 `-Worktree`。
3. **不要依埠 taskkill 18432。** 受管程序的身分是 `python -B -u "%LOCALAPPDATA%\StockTerminalLocal\current\server\server.py"`，且須與 `local_process.json` 登記相符（`start_local.ps1` 遇到 18432 上的其他程序會拒絕啟動、不會終止它）；開發程序是 `python -u server\server.py`。兩者不要同時跑。
4. **部署只走 stage → promote。** 先 `private_web_release.py stage --ref <完整 SHA>`（不動正式網站），再 `promote --release <id> --approve`，**需要使用者明確核准**。promote 前必須由發布流程完成：CI 全綠、完整且已驗證的 SQLite 一致備份、停止服務（`docs/私有發布完整性.md`）。發布器本身不備份、不停服務。雲端 agent 不得自行 promote，應交棒給本機發布者並附上 SHA 與驗收標準。
5. **更新開發工作樹：** `stock_terminal_v2.html` 是啟動時重建的產物，更新前用 `git stash push -- stock_terminal_v2.html` 保留（不要丟棄）；`data/` 內的修改是執行期資料，不要還原；用 `git pull --ff-only origin main`。被未追蹤檔擋住時，把檔案**搬到備份資料夾**再 pull，不要刪除；不得使用 `reset --hard`、`clean`、強制推送。
6. **給使用者的指令一律是 PowerShell**，並盡量讓輸出可貼回（`& { … } *>&1 | Tee-Object -FilePath $log`，再 `Get-Content $log -Raw | Set-Clipboard`）。
7. 動手前先掃描既有資源與契約，不平行另建資料管線（見 `.cursorrules` 鐵律）。

## 3. 唯讀檢查（確認路徑與版本，不改任何東西）

```powershell
$lr = Join-Path $env:LOCALAPPDATA 'StockTerminalLocal'
$pr = Join-Path $env:LOCALAPPDATA 'StockTerminalPrivateWeb'
$cfg = Get-Content (Join-Path $lr 'local_install.json') -Raw -Encoding UTF8 | ConvertFrom-Json
"originalCheckout    : " + $cfg.originalCheckout
"LOCAL current commit : " + (Get-Content (Join-Path $lr 'current\.private_web_release.json') -Raw | ConvertFrom-Json).commit
"PROD  current commit : " + (Get-Content (Join-Path $pr 'current\.private_web_release.json') -Raw | ConvertFrom-Json).commit
Get-NetTCPConnection -LocalPort 18432 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  "18432 listener PID " + $_.OwningProcess + " : " + (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)").CommandLine }
```

## 4. 事故紀錄

2026-10-07：雲端 agent 沿用舊路徑 `C:\Users\Sam\AI_Stock`，指示使用者在該資料夾執行 `START_TIP.cmd`。該資料夾不是登記的 `originalCheckout`，
`go.ps1` 走開發流程並關掉 18432 埠上的程序，改跑一份未受管的開發版。處置：停止開發程序，改由
`%LOCALAPPDATA%\StockTerminalLocal\start_local.ps1` 啟動受管安裝。根因：路徑遷移沒有記錄在倉庫、`go.ps1` 沒有防呆。對應修正：本檔與 `go.ps1` 的拒絕檢查。
