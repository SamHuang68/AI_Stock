# 官方研究成交量
估值研究版本 valuation-research-4；分欄版本 official-research-volume-1。

研究量優先採完整且一致的 TWSE STOCK_DAY 收據股數。核對股票、交易日、來源 URL、原始回應雜湊、取得時間、解析版本及每份觀測的收據連結；價格仍須通過既有核對。任何來源／日期歧義、壞收據、缺收據、官方修訂量不一致、空值或非整股均不選取。零股數 0 與缺值 null 分開。未選定時，只有原有有效品質紀錄且無衝突的量可沿用，回應以 volumeBasis 明示；缺值不補零。

officialResearchVolume 保留官方 value/source/asOf/unit/receiptIds，原始 rawValue/rawSource/rawUnit，以及 numericDifference（官方股數減原始數值）。原始來源／單位沒有證據即為 null；數值差不代表交易類別差或可換算股數。來源 notes 保留 TWSE 的涵蓋與排除範圍。

不改寫 bars、不改 schema、不追補原始來源；volumeVerified、volumeConflict 及原品質摘要仍依原值核對，不因研究量可用而洗掉衝突。估值量比改以研究量計算，版本同步更新。ETF 仍不適用普通股估值；0050 只用於資料品質欄位驗證。既有技術 0–100 分、獨立體檢與前瞻事件研究不改算法。

七筆既有差異以固定期望值測試；正式驗收唯讀核對相同日期及 UI。完整原始來源回應保留於既有收據庫，不重抓或另建管線。此為事後研究資料，不能宣稱具備當時可得財報、還原價格、全下市樣本或已消除存活者偏差。
