# Stock Terminal v4.1

Bloomberg 風格台／美股研究終端機 — **本機跑、零雲端、純 Python stdlib（不用 pip）**。

完整說明、功能表與打包規範見 **[docs/README.md](docs/README.md)**。

## 30 秒啟動

1. 解壓（或 clone）到任意資料夾  
2. Windows：雙擊 `scripts\go.bat` → 瀏覽器開 `http://127.0.0.1:18432`（server **只聽 loopback**）  
3. 輸入代號（例 `2330`）按 **GO**

> 融資週期／TDCC 集中度等大 DB **不隨 git／分享包**；首次開圖會背景回補。

## 連動子專案：WaveDeck（浪潮執行台）

微觀下單／AI 判斷／風控艦橋，與本終端分工：

- 專案目錄：[`wavedeck/`](wavedeck/)
- 啟動：`cd wavedeck && python3 server/server.py` → `http://127.0.0.1:18433/`
- 架構：[`wavedeck/docs/ARCHITECTURE.md`](wavedeck/docs/ARCHITECTURE.md)

## 分享版注意

發行 zip（`scripts/build_dist.py`）**不含**：

- Claude API Key（`data/ai_key.txt`）
- Telegram／Email 警報設定
- 觀察股後端清單（`watch_rules.json` / `watch_state.json`）
- 畫線雲端記憶、個人籌碼快照

請自行在 UI 設定 Key 與通知；觀察股只存在你本機瀏覽器。

## 授權

MIT
