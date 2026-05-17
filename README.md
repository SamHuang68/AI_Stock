# Stock Terminal

Bloomberg-style 個股研究終端機，本機跑、零雲端依賴、無外部 Python 套件需求。

- 即時 Yahoo Finance K 線（含 1天 ~ 全部 共 11 個時間段切換）
- 16 項技術指標（RSI / KD / MACD / SMA / BB / ATR / Ann Vol% / MaxDD% / Vol Ratio / D2-SMA20% / ETF Flow）
- 台股 10 檔主動式 ETF 持股每日 delta（資料源：MoneyDJ）
- 自選股清單、本地 LRU 快取、多執行緒併發抓取
- 可選：Claude API 串接的個股 AI 研究報告

---

## 系統需求

- Windows 10 / 11（macOS / Linux 也能跑 server.py 但 .bat 啟動器要自己改寫）
- Python 3.10+（用 `python --version` 確認）
  - 純 stdlib，**完全不需要 pip install 任何套件**
- 現代瀏覽器（Chrome / Edge / Firefox 都行）
- 網路連線（要打 Yahoo Finance / MoneyDJ）

---

## 快速開始（3 步）

**1. 解壓縮**到任何資料夾（例：`C:\Tools\Stock_Terminal\`）

**2. 雙擊 `start_terminal.bat`（v1）或 `start_terminal_v2.bat`（v2 含倉位與訊號）**
- 自動啟動本機 server（port 18432）
- 自動開瀏覽器到 `stock_terminal.html` 或 `stock_terminal_v2.html`
- 輸入股票代號（台股填 2330 / 美股切到 US 填 AAPL）按 GO

**3.（可選）建立每日 ETF 排程**
- 系統管理員身分跑 `install_scheduler.bat`
- 之後每個交易日 19:00 自動更新 ETF 持股快照
- 累積 2 天以上資料後，ETF△ 分頁會顯示主動 ETF 的進出 / 加減碼變化

---

## v2.0 — 倉位管理 + 多訊號觀察 + 共識評分 + 中文說明

v2 在 v1 之上加了兩個分頁：**POS**（已持有部位）+ **WATCH**（觀察名單），並在所有指標/策略旁加 **(i) 圖示**點擊看中文說明。

### POS 分頁 — 倉位管理 + 即時訊號

**倉位記錄**（存瀏覽器 localStorage，每檔股票獨立）
- 進場價、股數（支援「張」單位自動 ×1000）、停利價、停損價、進場筆記
- 即時顯示成本、市值、未實現損益（%、金額）
- **持倉清單**：所有持倉一覽（總成本/市值/合計損益），點任一檔跳轉

**規則化訊號**（每次切換股票自動算）
- A. 均線交叉：破/站上 SMA20、SMA60；黃金/空頭排列
- B. RSI：> 75 過熱建議停利、< 25 超賣建議承接
- C. KD：低檔黃金交叉加碼、高檔死亡交叉減碼
- D. MACD：動能由空轉多 / 由多轉空
- E. 布林通道：觸上軌+RSI 過熱 / 觸下軌+RSI 超賣
- F. 量能：> 20 日均量 2 倍以上 + 價方向判斷
- G. 倉位連動：達停利/停損、距停損 < 3%、浮盈 ≥ 20%、浮虧 ≤ -10%
- H. 主動 ETF 共振：≥ 3 檔同步買進 / 賣出該股

### WATCH 分頁 — 多訊號觀察 + 共識評分（v2 核心功能）

**一檔股票可掛多個訊號 + 自動算共識（Confluence）**

8 個策略（4 大類）：

| 類別 | 策略 | 方向 |
|------|------|------|
| 📈 趨勢 | 回測 60 日均線、回測 20 日均線 | 多 |
| ⚡ 動能 | 突破 N 日新高、RSI 超賣反彈、🔥 RSI 過熱 | 多/多/空 |
| 📊 波動 | 布林下軌承接 | 多 |
| 🎯 價格 | 自訂買進、自訂賣出 | 多/空 |

**5 個專業預設劇本（一鍵套用 2~3 個搭配好的訊號）**

| 劇本 | 包含 | 適用 |
|------|------|------|
| 📉 經典回檔買進 | SMA60 + SMA20 + RSI 反彈 | 多頭中等回檔 |
| 🚀 強勢突破追勢 | 20 日突破 + 60 日突破 + SMA20 | 盤整後抓突破 |
| 🔄 超賣反彈短線 | RSI 超賣 + BB 下軌 | 急殺後抓反彈 |
| 💰 波段停利 | 自訂目標 + RSI 過熱 | 已建倉的停利 |
| 🎯 雙價位警示 | 自訂買 + 自訂賣 | 純價格區間 |

**共識評分**：每檔股票卡片頂端顯示 🟢 強多 +3 / 🟢 偏多 +1 / ⚖️ 中性 / ⚠️ 多空分歧 / 🔴 偏空 / 👀 觀察中。多訊號共振統計上把勝率從單一指標的 50% 推到 70~80%。

### (i) 圖示中文說明系統

**任何指標、策略、劇本旁邊都有 (i) 小圖示**，點擊跳出浮動視窗：

- **指標說明**（16 個）：是什麼 / 怎麼看 / 實戰用法
- **策略說明**（8 個）：原理 / 適用場景 / 觸發後行動
- **劇本說明**（5 個）：適用情境 / 包含訊號 / 為何組合

點視窗外、按 Esc、或點 × 關閉。設計給股市小白：白話、不講廢話、有實戰建議。

### 自選股雙列佈局 + 拖曳排序

頂端自選股列從單列改 **2 列 grid**，密度直接翻倍。每個 chip 左側有 `⋮⋮` 抓握圖示，**拖曳即可重新排序**，順序自動存 localStorage。

> ⚠ 所有訊號僅供參考，不涵蓋基本面與總體環境。多訊號共振只提升勝率，不保證獲利。資金管理 > 選股。

**初次使用**：跑 `start_terminal_v2.bat` 會自動 build v2 + 開啟。之後每次啟動都會自動同步 v1 的更新。

---

## 檔案結構

```
Stock_Terminal/
├── server.py                  本機 HTTP server（YF proxy + LRU + ETF Delta + Catalog + Tracker run）
├── stock_terminal.html        v1 UI（單檔 HTML，含雙列拖曳自選股）
├── stock_terminal_v2.html     v2 UI（build_v2.py 產生：POS + WATCH + ETF△ 分類）
├── position_v2.js             倉位管理 + 訊號引擎
├── watch_v2.js                多訊號觀察清單 + 8 策略 + 5 預設劇本 + 共識評分
├── info_v2.js                 (i) 圖示浮動中文說明（16 指標 + 8 策略 + 5 劇本）
├── pro_v2.js                  專業工具（通知中心/大盤/繪線/風險/熱力圖/POC/Replay/Backtest）
├── pattern_v2.js              AI 形態辨識（8 種經典 K 線形態）
├── live_v2.js                 近即時報價輪詢（30 秒 / Yahoo v8 chart 1m）
├── etf_v2.js                  ETF △分類 tabs + ⚙ 管理 modal + 立即更新
├── mobile_v2.css              響應式 RWD（手機/平板/桌機）
├── etf_catalog.json           60+ ETF / 7 分類 + 自訂類觀測池配置
├── build_v2.py                v1 → v2 的生成腳本（v1 更新後重跑即同步）
├── etf_delta_tracker.py       主動 ETF 持股爬蟲（MoneyDJ）
├── start_terminal.bat         v1 啟動
├── start_terminal_v2.bat      v2 啟動（每次自動重 build）
├── run_tracker.bat            手動跑 ETF tracker（互動式）
├── daily_etf.bat              排程觸發用的 ETF tracker（無互動）
├── install_scheduler.bat      註冊 Windows 工作排程器
├── uninstall_scheduler.bat    移除工作排程器
├── build_dist.bat             打包成 Stock_Terminal_v2.0.zip 的腳本
└── etf_history/               ETF 歷史快照存放處（執行後自動產生）
```

---

## 進階設定

### 改 server port

`server.py` 第 14 行：
```python
PORT = 18432
```

### 改線型預設範圍

啟動前設環境變數：
```cmd
set YF_RANGE=10y
set YF_INTERVAL=1d
python server.py
```
（前端時間段按鈕仍可即時切換，這只是初次預設）

### 改 ETF 觀測池

`etf_delta_tracker.py` 第 26 行 `ETFS = {...}` 改成你想追的代號。
`server.py` 第 24 行 `ETF_NAME_MAP` 也順手改名稱對照。

### 上傳 Claude API Key

開終端機後右上角按 `API KEY` → 貼上 `sk-ant-...` → 個股頁面右側 RESEARCH 分頁就能跑 AI 八章節研究報告。Key 只存瀏覽器 localStorage，不會外傳。

---

## 資料來源

| 用途 | 來源 | 備註 |
|------|------|------|
| K 線 / 報價 | Yahoo Finance v8 chart API | 失敗時 fallback 經 allorigins.win |
| 主動 ETF 持股 | MoneyDJ Basic0007B | 全部持股頁面 |
| Fallback ETF | MoneyDJ Basic0007 / TWSE | 只有被動 ETF |

**所有資料抓取都在你本機跑，零雲端、零追蹤。**

---

## 疑難排解

**❌ start_terminal.bat 開了但瀏覽器顯示無法連線**
→ Port 18432 被占用。改 `server.py` PORT 變數或關掉佔用程式（`netstat -ano | findstr 18432`）

**❌ ETF△ 分頁顯示「尚無足夠歷史檔」**
→ 跑 `python etf_delta_tracker.py --backfill 5` 一次（會抓 MoneyDJ 最新快照寫到 5 個日期檔案；但因為是同一份快照，summary 會是 0/0/0）
→ 設好 `install_scheduler.bat` 排程後，明後天就會累積真實的 day-over-day delta

**❌ 中文亂碼**
→ Windows console 預設 CP950。`.bat` 已加 `chcp 65001` 切 UTF-8，Python 輸出也是 UTF-8。看 log 用 `Get-Content -Encoding UTF8 logs\etf_xxx.log`

**❌ Yahoo Finance 抓不到**
→ Yahoo 偶爾 rate-limit，server 已內建 LRU cache + query1/query2 雙端點重試。若仍失敗，前端會自動經 allorigins.win 繞道

---

## License

MIT — 自由分享、修改、商用都可以。原作者保留歸功（不強制）。

---

## 致謝

- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) — 圖表引擎
- [MoneyDJ ETF 基智網](https://www.moneydj.com/etf/) — ETF 持股資料源
- [Yahoo Finance](https://finance.yahoo.com/) — 報價資料源
