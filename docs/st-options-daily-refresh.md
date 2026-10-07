# 台指選擇權結構收盤後自動更新

基底：e0b11475f40a980289553d18029b916be3d1e457。產品版本仍為 5.0。

## 原因

選擇權結構只能由畫面按鈕觸發 `/options/txo/refresh`，沒有任何排程呼叫它。2026-10-07 實測 local 快取停在 2026-08-16、正式網站停在 2026-09-09，TAIFEX 官方來源本身可正常讀取（資料日 2026-10-06）。

## 行為

- `server/options_schedule.py` 在交易日 18:30、19:30、20:30 三個時段各檢查一次，並在 21:00 後停止。
- 快取的 `observed.tradeDate` 已是當日就不再送出；否則透過統一更新中心 `submit('options', {'force': True})` 排入既有的 `options` 工作。不新增來源、欄位或第二條抓取管線。
- 預設關閉。需在該 runtime 的 `data/options_daily_schedule.json` 寫入 `{"enabled": true}`（必須是布林 true）才會對外抓取 TAIFEX，比照每日日線的擁有者同意檔。
- 時段收據寫入 `data/options_daily_attempts.json`，先寫收據再排隊；排隊被拒會記為 `rejected`，同一時段不重試，下一時段再試。
- 交易日判斷沿用 `台股交易參考.session`：週末、官方休市與無年度日曆的年份都不送出。
- 啟動掛在 `server.py` 的 `configure_updates` 之後；啟動失敗只印訊息，不阻擋服務。

## 限制

- 只在服務運行時檢查；電腦關機或 21:00 後才開機，當日不補。
- 既有 `options` 工作在現貨日期與選擇權資料日不同（品質旗標 `SPOT_CHAIN_TIMESTAMP_MISMATCH`、`STALE_OR_HYBRID_REFERENCE`）時會標為失敗並不發布市場快照。若 TAIFEX 當日資料晚於 20:30 才發布，當天不會成功，隔日 18:30 起再試。這是既有品質保護，沒有放寬。
- local 與 web 各讀自己的同意檔，不共用；啟用哪一邊需分別設定。

## 驗證

`tests/test_options_schedule.py` 6 個案例（預設關閉與非布林 true、每時段只送一次、舊資料時下一時段重試、當日資料已存在即停止、時段外與休市日不動作、排隊失敗留收據）。連同 `test_options_exposure`、`test_統一更新中心`、`test_dist_scrub` 共 55 個測試通過。尚未實際啟動服務觀察排程在 18:30 觸發。
