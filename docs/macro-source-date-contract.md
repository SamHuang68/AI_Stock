# 總經 Seed 的來源與日期契約

本次以 main `3d1c38d69851a288b15798dd8dc8630f02fda280` 為基線，移植 PR65 的總經契約意圖。2026-10-01 唯讀核對：遠端 main、本機 main、`StockTerminalPrivateWeb/current/.private_web_release.json` 的已發布 commit 相同；該 main 的 GitHub CI 成功。這是防止跨量尺混檔的修正，並非證實生產已出現污染。

每個有 seed 的 API 序列與美國總經圖指定唯一 provider。固定來源不可用時沿用已存在的 seed 或回傳 unavailable，不再退回不同量尺資料。`us2y` 保留 FRED DGS2，不再用三個月利率冒充；公司債序列清楚標示 LQD/HYG 還原收盤代理。

CSV 必須使用 `date,value` 標頭、完整 ISO 日期、嚴格遞增且不重複的日期，以及有限數值；未來日依台北日曆日拒收。整檔讀取失敗回空資料，線上點驗證失敗不覆寫既有檔案。寫入經暫存、fsync、原子 replace；同程序解析共用 seed 時序列化。

既有 CSV 沒有可核實來源。第一次固定來源刷新成功時，先保存原檔至 `<seed>.unverified.<sha256>.bak`，以此次 provider 的有效資料重建 CSV，寫入 `<seed>.source.json`（provider、symbol、FRED ID 與 CSV SHA-256）。後续更新只有來源及雜湊均匹配才保留舊日期並合併；不匹配重新備份與重建。首次重建的歷史範圍由實際取得的指定來源資料決定，舊歷史保留在備份，不直接混入。刷新失敗時保持原檔可讀，標示 unverified；未驗證檔不視為可發布快照。

日資料時效用平日數估算，月資料用日曆日；這不是完整交易所假日模型。日期與來源狀態在 API/chart/status 回傳，未來、未知、過期資料不視為可發布美國總經圖／經濟快照。來源雜湊可以偵測外部改寫，並非檔案簽章或跨程序資料庫交易。

本 PR 不變更任何 seed、DB、正式 HTML 或正在執行的服務，不合併 TIP 分支，不處理 PR65 的法人、TXF、marketflow 或其他台股日期移植。PR65 保持開啟；本 PR 僅取代其中總經部分。

回歸覆蓋固定来源失敗、未知 provider、API 二次 fallback、共用 seed identity、舊檔重建與備份、驗證後合併、外部改寫／provider 切換、非法日期與數值、原子 replace 失敗，以及 stale/unverified API 狀態。本機自查不等同獨立第二意見；遵守本次禁止聯絡外部代理的限制，未呼叫外部 reviewer。
