# Revision History（內部文件 — 不對外分享）

> 各版本「改了什麼 / 修了什麼」的詳細紀錄,內部追蹤用。
> 對外分享的功能介紹在 `README.md`;本檔由 `scripts/build_dist.bat` 排除,不進分享包。

---

## v5.0 修訂 — 2026-10-07 選擇權結構收盤後自動更新（本機候選，已提交，未發布）

產品版本仍為 **5.0**；基底 `e0b11475f40a980289553d18029b916be3d1e457`，分支 `claude/st-options-daily-refresh`。可追溯提交 SHA 見該分支提交與 PR；本節不在檔內預寫自身 SHA。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 選擇權每日更新排程 | 選擇權結構只能手動更新，兩個 runtime 快取分別停在 2026-08-16 與 2026-09-09；新增交易日 18:30／19:30／20:30 檢查，當日資料已入快取即停止，沿用既有 `options` 更新工作，預設關閉，需擁有者同意檔 `data/options_daily_schedule.json`。 | 6 個新單元案例，加上 options、統一更新中心、dist 相關共 55 個測試通過；未實際啟動服務觀察 18:30 觸發。 |
| 發布白名單 | 新模組與測試加入 `scripts/build_dist.py` 必要檔案與 dist 測試清單，避免發布包漏檔。 | `test_dist_scrub` 通過。 |

已知限制：只在服務運行時檢查；既有品質保護在現貨日與資料日不同時仍會把工作標為失敗，TAIFEX 當日資料晚於 20:30 發布時當天落空。詳見 [說明](st-options-daily-refresh.md)。狀態：本機候選／已提交；未發布，部署與啟用同意檔仍待確認。

---

## v5.0 修訂 — 2026-10-07 備援路徑可觀測性與靜默例外棘輪（候選，未發布）

產品版本仍為根目錄 `VERSION` 的 **5.0**。補記：PR #166 已於 2026-10-07 合併，合併（squash）修訂 `fd6efb77e08e7aae718d0ed085cbd013e66779a5`；先前「候選（尚未合併）」是當時快照，不覆寫。**發布狀態**：#164、#165、#166 與本段都未發布，正式站與受管理本機的 runtimeCommit 仍為 `e0b11475f40a980289553d18029b916be3d1e457`（2026-10-07 確認）。

### 候選（本 PR）：備援路徑可觀測性、靜默例外棘輪、接線檢查

- 基底：`fd6efb77e08e7aae718d0ed085cbd013e66779a5`。實作提交以本 PR 的分支歷史為準（避免在自身檔案內預先寫入自己的 SHA）。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `server/log_once.py` 與備援路徑記錄 | #165 的 `import math` 之所以悄悄失效五天，是因為 `except Exception: return None` 吞掉 NameError。新增限頻記錄函式（同 key＋例外型別 10 分鐘一行；新的例外型別一定立刻記錄），並接到四個備援路徑：`_db_screener_arrays`（DB 失敗仍回 None，由呼叫端退回 Yahoo）、`_handle_quote_batch` 的單檔候選與 worker 例外。行為不變，只多一行記錄。 | `tests/test_log_once.py` 6 項；`tests/test_fallback_observability.py` 4 項，其中 3 項在舊 `server.py` 上失敗。 |
| 數字解析只吞解析失敗 | `_fetch_day_movers`、`_handle_twquote` 內的 `fnum` 原本 `except Exception: return None`，會連 NameError 一起吞。改為只抓 `TypeError`、`ValueError`、`OverflowError`。**行為差異**：解析以外的程式錯誤現在會往外傳，由外層既有的處理印出（例如 `[movers] TWSE ingest …`），不再悄悄回「無資料」。 | 缺全域名稱時會印出 `[movers] TWSE ingest … name 'math' is not defined` 的測試；健康模組下排行照常有資料。 |
| 靜默例外棘輪 | 共用規則 0014：寬鬆且靜默的例外處理（`except Exception` 等，只有 `pass`／`continue`／`break`／`return` 常數）數量只能下降。`server/` 目前 207 個（39 個檔案；`server.py` 69 個），新增或減少都使測試失敗，減少時要同步降低 `tests/silent_except_baseline.json`。本 PR 讓總數從 212 降到 207。 | `tests/test_no_new_silent_exceptions.py` 2 項；人為新增一個靜默處理時測試失敗（已驗證）。尚未清理其餘 207 個，屬後續工作。 |
| 接線檢查 | `server.py` 內 150 個不同的 `self._xxx()` 呼叫都要在 `server/` 內有同名定義，抓拼錯的方法名稱（pyflakes 抓不到）。名稱層級，不啟動伺服器、不碰 `data/`。 | `tests/test_server_handler_wiring.py` 2 項；目前沒有缺少的定義。 |
| 協作入口文件 | `AGENTS.md`、`CLAUDE.md` 記入：共用記憶的 GitHub 遠端與雲端唯讀讀取方式、遠端可能落後本機、8D 與「8D 後新增規則不需授權」的範圍、規則 0014 的做法。 | 文件變更；事實來自使用者回覆（遠端 repo 名稱）與雲端對遠端的唯讀核對。 |

驗證：只跑了本次相關的測試與 `test_bundle_fresh`；完整 Python 套件由 CI 執行，沒有在雲端另外跑（規則 0008 第 13 條）。限制：未用即時供應商資料驗證；路由煙霧測試（啟動真實伺服器）**沒有做**——它會寫入 `data/`、啟動背景執行緒並對外連線，與規則 0007 的執行期資料保護衝突，改以上列的接線檢查代替，煙霧測試待 Sam 決定隔離方式。審查：僅作者自審，沒有跨供應商或同供應商隔離審查。使用者可見資訊：沒有減少。

---

## v5.0 修訂 — 2026-10-06／07 決策中心時效、台指期時間與啟動器防呆（已推送並合併；未發布）

產品版本仍為根目錄 `VERSION` 的 **5.0**；沿用「產品版本 + 精確 Git／runtime commit」辨識修訂，沒有改動版本號。以下 PR #164、#165 已合併到 `main`，PR #166 為候選；**2026-10-07 實測正式站與受管理本機的 runtimeCommit 仍為 `e0b11475f40a980289553d18029b916be3d1e457`**（正式 `.private_web_release.json` 與本機 `/health` 一致），所以全部屬「未發布」。發布須依既有 stage／promote 流程由本機發布者執行；此處不宣稱已部署。

### 已推送並合併、未發布：PR #164，決策中心時效與台指期夜盤時間

- 基底：`e0b11475f40a980289553d18029b916be3d1e457`。
- 分支提交（由舊到新）：`e8125daaf2da194af7614e533101b74679632ebd`、`44e6de5704b39f294ba81fc5b4340ff54feb6fa8`、`e3ecead7e739784238580147cc33acba9c4a391f`、`0e701f1852e8a7b703225d6863074b2ac748f417`、`2c0efcc874907b7fe75b86194c9df1e88b9864a8`、`af0c8c87bebab3078c384649259acda85e45050a`。
- [PR #164](https://github.com/SamHuang68/AI_Stock/pull/164) 合併（squash）修訂：`a525885a24dc53b36441e81d161bbe0c37097b1e`。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 台指期夜盤午夜後的日期 | TAIFEX MIS 在 00:00–05:59 的夜盤報價，`CDate` 仍是場次開始日（2026-10-06 01:50 回 `20261005`；2026-10-07 02:56 回 `20261006`）。直接組合 CDate＋CTime 會使 asOf 早 24 小時，證據列顯示「1 日前」，決策中心也把新鮮報價當過期。現在夜盤且時間早於 06:00 時日期加一天；日盤與午夜前不調整；調整後若超前本機時鐘超過 120 秒，仍標「時間未核實」，不悄悄移位。 | 上述兩份使用者機器上的真實樣本進入測試，另有跨月、跨年、週末與 06:00 邊界案例。使用者以 `88c5139` 程式在舊開發資料夾（非受管安裝）實測 `/txf`：asOf 為當日、`timeUnverified` 為 false、`timeCheck.verified` 為 true；該次輸出沒有存入證據資料夾。**午夜前（15:00–23:59）的 CDate 語意尚未用真實樣本確認**：若為下一個交易日，該時段報價會顯示為時間未核實。 |
| 時間驗證失敗時保留報價 | 過去 CDate／CTime 驗證失敗會整筆丟棄，Pulse 與決策中心看不到夜盤，且沒有紀錄。現保留價格，asOf 明確為未知並標 `timeUnverified`，原始 CDate／CTime 與原因寫入 `timeCheck`，同一場次與原因每 10 分鐘最多記一行；決策中心不採用時間未知的報價，Pulse 評分排除。 | 原「缺 CDate 回 None」的斷言依新契約改為保留價格、時間未知；其餘既有測試不變。 |
| 台指期時效 | 場次結束後、下一場次開始前（夜盤 05:00–08:45、日盤 13:45–15:00、週末與休市到下個開盤前，依交易所日曆），最後一筆視為 `completed_session` 而非過期；過去 05:30–08:45 完全不採用夜盤收盤。 | 完整時間軸測試，含週末、休市與「非場次最後一筆不得被救回」。 |
| Pulse 快照的台指期選擇 | 快照過去一律取夜盤區塊，日盤時段會顯示昨夜報價。現取夜盤區塊與日盤報價中時間較新且已核實者；快取為空的日盤時段直接取日盤報價。 | 選擇邏輯單元測試。 |
| Key Levels 時效與偏離 | 參考日須為最近完成交易日（18:00 截止、依交易所日曆），否則 `stale`；現價（指數與期貨中較新且可用者）偏離參考收盤達 `max(2%, 2×ATR%)` 時標 `offReference`，保留價位但不再產生「守穩 R1／收破 S1」確認與失效條件，並加 `key_levels_off_reference` 限制。`calculate_key_levels` 回傳 `referenceBar`。 | 19 個定向測試（含已回報的 45–48k 數值對 50k 現價）。2%／3% 門檻是經驗值，未用資料校準；期現貨基差未扣除。 |
| 選擇權結構 | 現價偏離選擇權參考現貨 3% 以上時停用情境模型（Flip Band、GEX），保留官方 OI 事實與方向中立的密度，原因為 `LIVE_PRICE_FAR_FROM_CHAIN_SPOT`。 | 併入上列測試。 |
| 決策頁呈現 | Key Levels 上方顯示參考日、現價與偏離（偏離為琥珀色、過期為紅色）；選擇權格顯示現價，模型停用時說明兩個價格。 | 以真實後端輸出對決策頁做 Playwright 檢查（已回報情境、過期參考、正常情境），無 pageerror。 |

驗證：全套 Python 1431 項通過（15 項略過，為 Windows 專用或選用套件）、22 項 JS 自測、`compileall`、`build_order`、bundle 新鮮度測試。[PR CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37352435070)、[分支 push CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37352430089)、[主線 CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37353820420) 各四項成功。限制：TAIFEX、TWSE、Yahoo 無法從開發沙箱連線，沒有以即時供應商資料驗證；未部署。審查：僅作者自審，沒有跨供應商或同供應商隔離審查。

使用者可見資訊的減少（共用規則 0009 第 1 條）：本 PR 在下列情況會減少決策中心顯示的內容，都不是悄悄進行，畫面會寫出原因。(1) Key Levels 為 off-reference 或 stale 時，不再輸出「守穩 R1／收破 S1」確認與失效條件文字；價位與波動度統計照常顯示，上方多一行參考日、現價與偏離。(2) 選擇權現價偏離 3% 以上時停用情境模型（Flip Band、GEX 情境與壓力測試數字），改顯示原因；官方 OI 與方向中立的密度仍顯示。(3) 時間未核實的台指期報價不再供決策中心與 Pulse 評分使用；價格與原始 CDate／CTime 仍由 `/txf` 提供。PR 說明已列出這些項目，Sam 以「合併」核准該 PR。

### 已推送並合併、未發布：PR #165，補 `import math`

- 基底：`a525885a24dc53b36441e81d161bbe0c37097b1e`；實作：`1f5319ba011ece91cfec9b04743e1400a54f7959`。
- [PR #165](https://github.com/SamHuang68/AI_Stock/pull/165) 合併（squash）修訂：`88c5139c17a6095703903e7f33c3cdc97246bd03`。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `server.py` 缺 `import math` | `_fetch_day_movers`、`_handle_twquote`、`_handle_quote_batch`、`_db_screener_arrays`、`_tag_industry` 使用 `math.isfinite`，且都包在 `except Exception` 內，NameError 被吞掉：總覽漲跌幅排行永遠「無資料」、個股即時報價的 Yahoo 備援取不到數字等，沒有任何錯誤訊息。由 `a02436a`（2026-10-02）與 `bd6b75f`（2026-10-03）引入，**已包含在目前部署的 `e0b1147`**。既有測試用 AST 取出單一函式並手動注入 `math`，因此沒有發現。 | 以真實模組與假 TWSE 資料重現：修正前 `ok=False`、無排行，補 import 後 `ok=True`。新增 pyflakes 全專案 undefined-name 掃描（修正前 5 處、修正後 0 處）與不注入全域的行為測試，兩者在舊程式上失敗；pyflakes 釘版於 `requirements-ci.txt`。另四處只以靜態掃描涵蓋，未逐一用即時資料執行。 |

驗證：全套 Python 1433 項通過（15 項略過）、22 項 JS 自測。[PR CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37503981020)、[分支 push CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37503960975)、[主線 CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37514560599) 各四項成功。審查：僅作者自審，沒有跨供應商或同供應商隔離審查。

### 候選（尚未合併）：PR #166，啟動器防呆與協作入口

- 基底：`88c5139c17a6095703903e7f33c3cdc97246bd03`。實作提交：`712872a8eb1edd242806ccd2892942ee77ba5c4d`、`c09a45620fa5e9c391198c6a421178a2612b88ce`，及其後的對齊與修訂紀錄提交（以 PR #166 為準）。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `go.ps1` 啟動防呆 | 已登記受管本機安裝時，`go.ps1` 只在目前資料夾等於登記的 `originalCheckout` 才轉交；從其他資料夾一般啟動會落入開發流程，`Stop-PortListeners` 關掉 18432 埠上的程序，再啟動一份未受管版本。2026-10-07 發生一次：雲端代理人沿用 2026-10-03 已退役的 `C:\Users\Sam\AI_Stock` 路徑，指示使用者在該資料夾執行 `START_TIP.cmd`。現在這種情況在關閉任何程序之前以 `ST-LAUNCHER-GUARD` 停止並說明；明確的 `-Worktree`／`-Pull`／`-UpdateOnly`／`-RebuildOnly`、登記資料夾的轉接、沒有受管安裝的行為不變。 | 靜態順序／BOM 測試，加 2 個在暫存目錄實際執行 `go.ps1` 的行為測試（PowerShell 7.4），在舊 `go.ps1` 上失敗；全套 1436 項通過。**尚未在使用者機器驗證**。行為測試原先優先選 `pwsh`，Windows CI 因此只用 PowerShell 7 跑過；`START_TIP.cmd` 實際呼叫的是 Windows PowerShell 5.1，所以已改為每個找得到的引擎（5.1 與 `pwsh`）都跑，5.1 的結果以該 PR 最新 head 的 Windows CI 為準。 |
| 停用 `scripts/apply.bat` | 舊腳本會強制 `git checkout -B` 遠端分支、`stash -u` 所有未追蹤檔並依埠 `taskkill` 18432，與受管本機安裝及「不 reset、不 force」的共用規則衝突；其預設分支檢查也拒絕 `main`（`TIP_BRANCH` 自 2026-09-07 起為 `main`），倉庫內沒有任何地方引用它。改為只印出停用說明並以 2 結束的存根（舊邏輯保留在 Git 歷史，未刪檔）。 | 靜態測試：存根不含 `taskkill`、`git checkout`、`git stash`、`git reset`、`netstat`、`server.py`、`build_v2`，且為 ASCII；未在使用者機器執行。 |
| 協作入口文件 | 新增 `AGENTS.md`、`CLAUDE.md`，更新 `.cursorrules` 的過時路徑，記錄正式開發資料夾、受管本機、正式站與退役舊路徑，並指向 `AI-Workspace` 的共用規則（本機檔案，不在 Git 內，不複製其內容）。 | 文件變更，無程式行為；內容只含從使用者機器輸出與倉庫文件驗證過的事實。 |

審查：僅作者自審，沒有跨供應商或同供應商隔離審查。

事故處置紀錄：未受管開發程序於 2026-10-07 03:33:05 啟動並佔用 18432；使用者之後改由 `%LOCALAPPDATA%\StockTerminalLocal\start_local.ps1` 啟動受管安裝，其 runtimeCommit 為 `e0b11475…`，與正式站一致；正式站（18434／18435）未受影響。使用者事後提供的證據：受管啟動收據 `createdAt` 為 2026-10-06T19:48:00Z（台北 10-07 03:48:00，即改由受管啟動器重新啟動的那次），前一份受管程序的 log 最後寫入 2026-10-05 18:41（台北），距事發約 33 小時；因此事發當時 18432 上很可能沒有受管程序在運行，很可能沒有關閉任何受管程序。這是推論，不是證明（前一份收據已被覆寫）。

---

## v5.0 修訂 — 2026-10-03 已發布與後續本機階段

產品版本仍為根目錄 `VERSION` 的 **5.0**；本輪沿用「產品版本 + 精確 Git／runtime commit」辨識修訂，沒有為整理紀錄改動版本號。以下保留各階段的原因、行為、驗證與發布狀態；歷史紀錄不覆寫。

### 已發布：PR #162，正式與受管理本機一致

- 原基底：`c8274eb4995cc07a90bb6b5414b5dc81a919f273`。
- 實作：`45eea31b832d69d4eb26bb3241f2ebb5c5386221`；覆核後修正：`97fd75996038d91fd61b37d2aab7d4fb59df7277`。
- [PR #162](https://github.com/SamHuang68/AI_Stock/pull/162) 合併／部署修訂：`2ae7256f9d898fee0df25f1787952337b37b12e2`。
- 2026-10-03 UTC 的實際 UI 收據確認正式與受管理本機皆執行此 SHA；兩份部署 `VERSION` 均為 5.0。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 型態視窗回覆歸屬 | 關閉視窗、換股或新請求後的舊回覆可能覆蓋目前畫面；現核對請求、視窗與圖表序號，取消過期批次，保留舊 modal 呼叫相容性。 | 11 個定向瀏覽器案例；正式與本機各一次真實型態視窗操作通過；已發布。 |
| 型態績效說明 | 固定星等與「最高勝率」缺乏統計依據；改為規則符合，明示不代表獲利機率。 | 沿用型態瀏覽器案例及兩份實際 UI 文字證據；技術分數公式不變；已發布。 |
| 美股日線截止日 | 單靠平日與固定收市時間無法正確處理休市、DST 及提前收市；採有限 2026–2028 官方日曆，訊號與資料品質共用截止語意，範圍外保守標示未知。 | 10 個日曆案例及 3 個直接相依案例通過；部署後固定時鐘核對聖誕休市、提前收市及未知年份；已發布。 |
| 未知日曆的歷史資料說明 | Claude 覆核指出前一日資料仍可能被描述成已收市；未知說明現同樣適用較舊資料。 | 僅重跑受影響 API 案例通過，0.008 秒；提交 97fd759；已發布。 |
| 新增測試與發布包涵蓋 | 新日曆資源、模組與型態測試需進入既有發布／CI 路徑。 | PR／主線 CI 各四項首次通過；精確 SHA stage 一次通過 1403 單元（略過 1）、25 smoke、11 dist 及既有 JS 自測。 |

[PR CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37147220378)、[主線 CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37147892630)。正式完整備份 14 個 DB、保留 269 個資料檔；本機備份 16 個 DB、331 個檔案。原排程定義及原工作區資料保留。有限 supervisor 存活觀察不代表未知外部終止原因已永久修復。

### 後續必要呈現修正：本機已提交，未發布

實作提交 `b5293a77c356e4b26aedde7c438b88a82e43996d`，分支 `codex/st-evidence-presentation`，基底為上述已發布的 `2ae7256`，產品版本仍為 5.0。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 市場成績單歸屬與快取 | 切換 TW／US 後舊回覆可能污染新卡片；快取依市場保存，讀取／重算回覆僅更新原卡片，支援收合取消與唯讀重試。 | 11 個離線 Chromium 案例及既有體檢自測通過；未發布。 |
| 指標／劇本績效文案 | KD「最高勝率」、任意組合「70～80%」及多訊號必然提高勝率沒有對應績效證據；移除宣稱，區分歷史統計與真實前瞻。 | 上述瀏覽器文案案例與 watch 語法檢查通過；分數、訊號公式不變；未發布。 |
| 官方成交量來源關係 | 同源首次建列或原始來源未知的零差異不能證明獨立核對；依當日、選定收據 ID、來源及 rawOrigin 顯示證據邊界，收據展開可追查日期與 ID。 | 29 組呈現自測通過；保留 raw／official／difference、衝突及未知單位；無 DB 修改；未發布。 |
| 測試入口與文件 | 新成績單案例需可重現，並接入既有 package／CI 路徑；記錄範圍、限制與測試。 | 本機腳本已通過；新的 CI hook 尚未執行，不把本機成功當作遠端 CI 成功；未發布。 |

Claude 於 2026-10-03 UTC 以既有 claude.ai 官方 CLI 完成本提交的首次跨供應商唯讀覆核，模型 claude-sonnet-5-5，結論 **PASS／無可證實新缺陷**。作者定向核對 rpanel 入口與既有 health/chart guard 一致；沒有因此修改產品或重跑既有成功測試。覆核綁定九個受審檔案雜湊；文件追記不改變其程式版本。

本階段沒有 push、完整 CI、合併或部署；下一次發布仍待確認。詳見 [本機修正說明](st-evidence-presentation.md)。本次修訂紀錄補登屬文件變更，不代表程式再進版或已發布。

本機稽核證據入口：`C:\Users\Sam\AI-Workspace\docs\stock-terminal\st-pattern-us-calendar\release-handoff.md`，以及同目錄 `release/verification-ledger.json`、`followup/ledger.json`、`followup/claude-review-triage.json`。這些是留存的當時證據，不以重新執行測試取代歷史紀錄。

---

## v5.0 — 總覽儀表板 + 分析轉盤（tip UX；無側欄）

**產品殼層**
- `shell_v5`：分析轉盤導航（最多三層，投資分析分類）；涵蓋原側欄全部 ROUTES；預設 `#pulse` 並 **boot 自動 openRing**；歷史庫 merge 同步。
- **移除 navrail／nr-edge／nr-backdrop**；`[`／Ctrl+B 改開轉盤。
- 品牌：`assets/st50-icon.svg` 置於**轉盤中心**（+ 頂列小 icon + favicon）；內頁隱藏重複 kicker。
- 對外導覽：`docs/TIP_UX.md`（Mermaid／SVG／概念圖）；示意 `assets/tip-ring-schematic.svg`。

**總覽與情報**
- `pulse_v5`：`GET /pulse` 一屏高密度（台指期、法人趨勢、廣度多空比、產業 TW/US、全球 SOX／日經／KOSPI、台美快訊 `/flash`、因子帳本）。
- **產業月營聚合**：自 OpenAPI `t187ap05_L`／`t187ap05_O` 快取加總產業 YoY／營收占比／家數成長；熱力 KPI／格註解 + pulse 快訊一句（月頻基本面，非盤中輪動）。
- `hub_v5`：法人／國際／訊號／自選／風險／設定分頁。
- `viz_v5`：共用 spark／bar；近 20 日趨勢圖 X/Y 軸單位。
- 廣度漲跌停浮動清單；真實資料計分（缺源「尚未納入」、不捏造 Fear&Greed）。

**體驗打磨（本 tip 續）**
- 轉盤：點選項為下一層圓心、上層透明鎖定、立體軌道質感、滾輪循環選取。
- 定時面板 soft refresh；離頁 `deactivate` 清輪詢。
- `Alt+Shift+1…0` 直達常用路由；`Esc` 先關轉盤／浮層。

**AI 中樞 + 工具列橋接**
- `ai_v5`：AI 室 — 報告／副駕／焦點入口 + `/focus` 摘要。
- `bridge_v5`：`screener3Open`→scan、`portfolioOpen`→book、`marketFlowOpen`／`instRankOpen`→institutional、AI 三鈕→ai（再開模態）。

---

## v4.1 — 體驗打磨 / 欄位標準 / 顏色管理

**新功能**
- 分析結果一鍵寄送 Telegram/Email（`src/ui/share_v3.js`）：掛到 焦點掃描 / 條件選股 / 供應鏈輪動 / 投組風險。`ShareResult.buttonHTML / wire / send`,沿用後端 `/notify`。
- ETF 增減碼徽章浮動視窗（`src/core/etf_flow_tip_v3.js`）：自選股徽章 hover/點擊列出哪幾檔 ETF 新增/移除/加減碼,每檔可點載入線型。純事件委派,讀裸 S。
- 欄位型別標準（`src/core/fields_v3.js` + `docs/FIELDS.md`）：數值/帶入/搜尋/文字四角色分離;全域滾輪防護(擋 type=number 滾輪改值);`Field.editing/renderGuarded`。
- 顏色管理單一真理來源（`src/core/colors_v3.js`）：`dir`(個股漲跌依市場)、`gain`(賺/買超/偏多=紅,永遠台股)、`quality`(體質/勝率好=紅)、`warn`(估值琥珀/中性)、`dirRU`(總體列)、`candle`、`state`、`isTW`。
- 代號庫升級成「台股清單 + 每股四大指標」（`server/universe.py` + `src/core/market_v3.js`）:universe.json 新增 `twmeta{code:{zh,en,board,pe,pb,yield,eps,gross,op,net,close,chg,vol,mktcap}}`。三組指標—量價(收盤/漲跌%/量)、估值(本益比/股價淨值比/殖利率/EPS)、獲利三率(毛/營/淨)—全抓官方 OpenAPI(TWSE STOCK_DAY_ALL·BWIBBU_ALL·t187ap06_L_ci·t187ap03_L;TPEx 對應上櫃),中英名對照(t187ap03 英文簡稱),市值=收盤×發行股數。前端「🗂 代號庫」改成可搜尋表(代號/中文/英文/四大指標,點代號載入),一鍵更新同時重抓名稱+指標+收錄新上市櫃。抽取一律中英雙語子字串比對+排除子項、配對到才填否則 null(優雅降級)。

**修正（root cause）**
- POS「進場價」輸入跳出搜尋框 / 焦點約 3 秒消失：真凶是 `wl_live_v3.js` 的 pollOnce 每數秒直接 `innerHTML=renderPosition()` 重建面板(繞過守門)。四條重繪路徑收斂到單一守門入口 `renderPositionPanel`/`renderWatchPanel`,編輯中跳過重繪。WATCH 同款修。
- 移除全域「打字即搜尋」熱鍵：會與數值欄位搶鍵;搜尋只留 `/` 與代號框。
- 欄位純資料輸入：數值欄 `type=number`→`type=text + inputmode`(消除滾輪偷改值、微調鈕、Enter→送出)。
- 頂部漲跌%顏色:改在 `polish_v3` 直接依當前個股市場上色;指數/個股一律依「標的本身市場」(`_isTwSym`/`Colors`),修「載過美股後台股顯綠」「^TWII 套美股慣例」。
- 美股盤中 X 軸收盤時間:`renderChart` 用 `America/New_York` 自動判 EDT(-4)/EST(-5),16:00 ET→台灣夏令 04:00/冬令 05:00(DST 自動)。
- LIVE 報價:台股跌顯綠(原誤紅,走 `Colors.dir`);台股指數改抓 TWSE `/twindex`,與底部總體列同源、數字一致(原 Yahoo 1m 延遲打架)。
- 底部總體列 / 自選股 chip:改「每檔依自身市場」(美股漲綠、台股漲紅);chip 用 inline `!important` 蓋過全域 market class CSS。
- ^TWII 早盤 Yahoo 日線落後一日:偵測到落後時用 TWSE 即時校正頂部現價/漲跌%/昨收(`patchTwIndexHeader`)。
- 殖利率:`server.py` 改用「每股配息÷價格」無歧義計算 + 合理上限(>40% 視為異常),修「真實<1% 殖利率被 `dy<1 就×100` 縮放成 59% 還上綠」。
- 籌碼面「無資料」修正:`_handle_chip` 原本只抓「當日」TWSE T86/融資券/借券/當沖,週末或盤前 17:30 前一律無資料 → 連上市權值股(2330)都顯示「無籌碼」。改為**往回找最近一個有 T86 資料的交易日**(最多 8 天)再抓全部。另:上櫃股 TWSE T86 查不到,新增 **TPEx 三大法人**(`tpex_3insti_daily_trading`)→ 修 3529 等上櫃股無籌碼。**根因續修(6683)**:該 OpenAPI JSON 的 key 實為英文 PascalCase(用中文 '外資'/'三大法人' 比對全 null;若為中文則 '三大法人' 唯一欄會配中→證實英文)。改成中英雙語子字串比對 + 鎖定「淨買賣超(買賣超/BuySell/Net)」欄位、排除子項(不含/自營自行/避險/外資自營商),並暫附 `_chipKeys` 供重啟後同源核對真實欄名。基本面(月營收/三率)實為暫時性 null,非缺陷。
- ETF 完整報表 email 變原始 JSON 修正:`etf_report`(需 pandas/matplotlib,打包排除/dev 未裝)為 None 時,`_etf_report_email` fallback 直接 `json.dumps(delta)` 寄原始 JSON。新增純 stdlib `server/etf_report_lite.py`(彙總邏輯同畫面、台股紅綠 HTML + 純文字);`_etf_report_email` 改「rich 可用就用,否則走 lite,絕不寄原始 JSON」;`--hidden-import etf_report_lite`。
- 資料源集中管理 + 一鍵更新:新增 `server/datasources.py`(registry:每源標 提供者/可靠度 official·vendor·local /更新類型 file·db·daily·live /最後更新/筆數)、`/datasources` GET 與 `/datasource/refresh` POST(universe 同步重抓;日線DB/ETF持股/法人籌碼 背景 spawn tracker)。前端 `src/ui/datasources_v3.js` 工具列「🗄 資料源」面板:全來源一表,可逐項或全部一鍵更新。涵蓋:代號庫、本機日線庫、主動 ETF 持股、法人籌碼、ETF 目錄、估值/月營收/名稱/產業(每日自動)、即時報價/指數/台指期(免更新)。
- 代號庫(universe lookup)+ 權威市場判定:新增 `server/universe.py`(TW 上市股+ETF+上櫃 / US NASDAQ Trader directory → `data/universe.json`)、`/universe` GET 與 `/universe/refresh` POST;前端 `src/core/market_v3.js` 的 `Market.of/name/refresh`(權威表優先、代號格式兜底,永不失敗且對未收錄新上市也正確);工具列「🗂 代號庫」可看數量/最後更新/一鍵更新。`loadSym`(base+v2)與估值彈窗一律 `Market.of`/依代號判市場,不靠 TW/US 鈕。
- 估值彈窗市場標籤:原本吃 server 回的 `v.market`(會把 00631L 標美股),改成依代號判定(`Colors.isTW`/`Market`)。
- 市場誤判根治:`loadSym` 原本直接吃 TW/US 市場鈕、不看代號 → 在 US 鈕載入台股代號(如 00631L)會被當美股,`S.mkt='US'`,用無 `.TW` 的代號抓 Yahoo **抓到錯標的**(實測 00631L 載成台積電),估值面板也標「美股」。修:`loadSym` 開頭加「數字開頭或 `^TW` → 強制 `mkt='TW'`」,`setMktUI` 同步市場鈕。
- 顏色語意全面統一台股慣例:P&L 賺=紅/賠=綠、法人買賣超 買=紅、型態多空 偏多=紅、ETF 加碼/新增/買盤=紅、體質評分/勝率 好=紅;水準型(P/E/三率/殖利率)中性琥珀,不用紅綠避免與股價打架。

---

## v4.0 — 本機資料骨幹 + 投組 + AI 副駕
- 本機時序 DB（`server/datastore.py`,SQLite,純 stdlib）:全市場約 2200 檔日線一鍵回補(限流退避 + resume)。選股/回測/投組讀同一份。
- 選股讀 DB(分鐘級→秒級);回測讀 DB(`/bars` 深度 5 年)。
- 投組風險面板（`src/portfolio`）:相關性/年化波動/1日95%VaR/Beta/投組Beta/產業曝險/供應鏈曝險鏈條圖/相關性熱力圖;可自訂成分股與權重。
- AI 副駕（`src/ai/copilot` + `server/ai_local.py`）:接本機 LM Studio(OpenAI 相容、SSE 串流);自動帶入持倉/個股/盤面 context,只用真實資料。
- 供應鏈輪動（`src/fundamental/chainmom`）:各段 5/20/60 日動能 + 近 8 週輪動軌跡 + 流向圖。

---

## 歷史摘要
- **v3.9** 多圖 / 全鍵盤 / 視覺化回測 / 畫線 / 三合一選股 / 複合警示;模組化重構(工具列分類下拉、`src/` 依功能分區、載入順序自動排序)。
- **v3.8** 四主軸(籌碼/基本面/回測/警報)+ 成交金額 Volume Profile + 後端推播 daemon。
- **v3.5–3.7** Yahoo 日線落後修正、build 根因修正 + LRU TTL、全球型 ETF 持股完整抓取。
- **v3.0** 19 種型態辨識(經典/諧波/艾略特/循環)。
- **v2.0** 倉位管理(POS)+ 多訊號觀察(WATCH)+ 共識評分 + (i) 中文說明。
