# Stock Terminal v5.0

Bloomberg 風格台／美股研究終端機 — **本機跑、零雲端、純 Python stdlib（不用 pip）**。

完整說明、功能表與打包規範見 **[docs/README.md](docs/README.md)**。

## 5.0 重點

- **總覽儀表板**：側欄導覽 + 一屏高密度市場脈搏（廣度、產業輪動、法人分歧、全球影響）
- **歷史庫 merge 同步**：頂列「同步資料」只補新日，不重灌全庫
- **真實資料計分**：缺源進「尚未納入」，不捏造 Fear&Greed／全市場 250 日新高家數

## 30 秒啟動

1. 解壓（或 clone）到任意資料夾  
2. Windows：雙擊 `scripts\go.bat` → 瀏覽器開 `http://127.0.0.1:18432`（server **只聽 loopback**）  
3. 左側點 **總覽** 看脈動；或輸入代號（例 `2330`）按 **GO** 進圖表

> 融資週期／TDCC 集中度／`pulse_history.db`／`market.db` 等大 DB **不隨 git／分享包**；首次使用會背景回補或按「同步資料」。

## 分享版注意

發行 zip（`scripts/build_dist.py` → `Stock_Terminal_v5.0.zip`）**不含**：

- Claude API Key（`data/ai_key.txt`）
- Telegram／Email 警報設定
- 觀察股後端清單（`watch_rules.json` / `watch_state.json`）
- 畫線雲端記憶、個人籌碼快照
- 本機大庫（`market.db`、`pulse_history.db`、`tdcc_holders.db`、`margin_cycle.db`）

請自行在 UI 設定 Key 與通知；觀察股只存在你本機瀏覽器。

## 授權

MIT
