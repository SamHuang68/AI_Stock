# 總經 Seed 的來源與日期契約

本次以 main `3d1c38d69851a288b15798dd8dc8630f02fda280` 為基線，移植 PR65 的總經契約意圖。2026-10-01 唯讀核對：遠端 main、本機 main、`StockTerminalPrivateWeb/current/.private_web_release.json` 的已發布 commit 相同；該 main 的 GitHub CI 成功。這是防止跨量尺混檔的修正，並非證實生產已出現污染。

每個有 seed 的 API 序列與美國總經圖指定唯一 provider。固定來源不可用時沿用已存在的 seed 或回傳 unavailable，不再退回不同量尺資料。`us2y` 保留 FRED DGS2，不再用三個月利率冒充；公司債序列清楚標示 LQD/HYG 還原收盤代理。

CSV 必須使用 `date,value` 標頭、完整 ISO 日期、嚴格遞增且不重複的日期，以及有限數值；未來日依台北日曆日拒收。整檔讀取失敗回空資料，線上點驗證失敗不覆寫既有檔案。寫入經暫存、fsync、原子 replace；同程序以每個 seed 的鎖保護提交，網路抓取在鎖外，提交前重新讀取 seed。讀取與來源證明共用同一份 CSV 位元組快照。

既有 CSV 沒有可核實來源。第一次固定來源刷新成功時，先保存原檔至 `<seed>.unverified.<sha256>.bak`，以此次 provider 的有效資料重建 CSV，寫入 `<seed>.source.json`（provider、symbol、FRED ID 與 CSV SHA-256）。後续更新只有來源及雜湊均匹配才保留舊日期並合併；不匹配重新備份與重建。首次重建以指定來源整檔重建，不混入舊歷史；抓取區間至少涵蓋現有種子的起點（呼叫端的 `years` 只決定圖表視窗，不決定種子保留多少歷史），舊檔完整保留在備份。刷新失敗時保持原檔可讀，標示 unverified；未驗證檔不視為可發布快照。

日資料時效用平日數估算，月資料用日曆日；這不是完整交易所假日模型。日期與來源狀態在 API/chart/status 回傳，未來、未知、過期資料不視為可發布美國總經圖／經濟快照。來源雜湊可以偵測外部改寫，並非檔案簽章或跨程序資料庫交易。

本 PR 不變更任何 seed、DB、正式 HTML 或正在執行的服務，不合併 TIP 分支，不處理 PR65 的法人、TXF、marketflow 或其他台股日期移植。PR65 保持開啟；本 PR 僅取代其中總經部分。

回歸覆蓋固定来源失敗、未知 provider、API 二次 fallback、共用 seed identity、舊檔重建與備份、驗證後合併、外部改寫／provider 切換、非法日期與數值、原子 replace 失敗，以及 stale/unverified API 狀態。另驗證失敗備份不得發布、不完整既有備份修復、CSV／來源快照競態、慢速刷新不得阻擋其他 seed，以及 adjusted provider 缺少 adjclose 時不得使用原始收盤（指數、期貨、匯率、殖利率、BTC 這十個沒有「還原」概念的序列標記 `adjOptional`，缺 adjclose 時才退回原始收盤；LQD／HYG／XLF 維持嚴格）。

依後續明確授權，安排隔離 Codex 唯讀第二意見。第一輪以 diff 為材料，發現備份、快照競態與全域鎖問題，但因缺少 adapter 原文判定材料不足；修正後使用完整原文重審。本機自查與 reviewer 建議均須逐項核實，不以測試全綠代替資料來源保證。

完整原文覆核另指出還原價局部刷新可能混用配息前後調整基準、提交失敗回報及台北跨日快取問題。已驗證並修正：`yahoo_adj` 刷新擴及既有歷史且要求涵蓋舊日期（起點差距 ≤ 10 天、缺值日 ≤ max(5, 1%)，容許 Yahoo 偶爾某天回 null），通過時整段以新抓到的資料取代以維持單一還原基準，不完整則保留原檔與明示錯誤；備份／CSV／來源證明提交失敗透過 `refreshError` 與刷新結果回報；macro handler/latest 快取鍵採台北日期。審查材料最終補齊完整原文與 main diff，以區分既有問題與本次修正。

完整原文＋main diff 的隔離 Codex 覆核完成，最後指出 economy snapshot 遺漏 refreshError；已保留每項錯誤及總體 refreshErrors，強制刷新任一失敗不得回報成功，加入回歸測試。最終本機完整套件 699 項、略過 1 項 live margin；22 組 JS 自測、compileall 與建置通過。覆核是靜態第二意見，並非對正式資料來源的保證。

## 審查後修正與刻意延後的項目

後續兩份靜態審查（PR #134、#135 合併後）指出的問題，已修正：未驗證種子重建只抓呼叫端 `years` 造成歷史被截短；讀圖（GET）遇到壞種子就備份並重寫；FRED 熔斷永不恢復（現為冷卻 600 秒後半開，`MACRO_FRED_COOLDOWN` 可調，`MACRO_SKIP_FRED=1` 仍為永久關閉）；`_macro_cache` 在更新後未失效、失敗的強制更新被快取；央行政策利率與景氣燈號的新鮮度窗口過短（改為約 100 天）；`/datasources` 每次約 2 秒（種子解析快取後約 0.1 秒）；`_macro_latest` 不帶新鮮度（現附 `freshness`／`age`／`ageUnit`／`maxAge`，美10年債在 Pulse 與國際總覽標示過期／未驗證）；來源標示仍寫 FRED／BAML。

刻意延後、需要你決定或另案處理：

- **`<seed>.source.json` 被 `.gitignore` 忽略，不隨 clone／發佈出貨。** 新環境的所有種子起始皆為 unverified：經濟指標顯示未就緒、美國總經圖不可發布，直到在該環境按一次「更新指標」（會備份原檔再以指定來源重建，歷史範圍已不再被縮短）。是否隨附初始 sidecar，等於替既有歷史做來源認證，不由程式自動認定。
- 狀態仍以 `note` 字串的子字串判斷（`'unverified' in note`、`startswith('refresh-', 'seed:', 'canonical:')`），散在 `macro_track.py` 與 `server.py` 三處；建議改為結構化結果（verified／error／kind）。
- `_resolve_series_points` 只轉呼叫 `_resolve_series_points_locked`（名稱誤導：鎖只包住快照與提交），`_seed_verified` 只有測試使用。
- `_macro_latest` 已附新鮮度，但畫面只標示美10年債；失業率、CPI 等其他列尚未標示。
- Yahoo 是否對指數類代號提供 `adjclose` 無法在這個環境驗證（網路政策擋掉 Yahoo），所以 `adjOptional` 的設計不依賴 Yahoo 的實際回應。
