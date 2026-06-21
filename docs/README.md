# Stock Terminal

Bloomberg 風格的個股研究終端機。本機跑、零雲端依賴、**不需 pip 安裝任何套件**（純 Python stdlib）。

---

## 系統架構（模組結構）

執行時是「瀏覽器前端 ↔ 本機 server ↔ 外部資料源」三層；前端模組依功能分資料夾，後端服務集中在 `server/`。

```
瀏覽器 UI ── src/ 前端模組（工具列：一階分類 + 二階下拉）
   │  HTTP  localhost:18432
本機 server.py（純 stdlib）── Yahoo proxy · LRU 快取 · 籌碼/ETF/估值 API · 常駐 daemon
   │  讀寫                                   │ 抓取
data/（本機資料：ETF/籌碼/設定）        外部源：Yahoo Finance / MoneyDJ / TWSE
```

### 目錄結構

```
Stock_Terminal/
├── stock_terminal.html          v1 基底 UI（build 來源）
├── stock_terminal_v2.html       實際使用的 UI（由 build_v2.py 產生）
├── build_v2.py                  打包器：把 src/ 模組注入 UI
├── build_order.py               依相依關係自動排序模組載入順序
├── modularize.py / migrate_*.py / fix_moves.py   結構搬遷工具（一次性）
│
├── src/                         ── 前端模組（依功能分類）──
│   ├── core/        報價・自選・部位・即時（pro / position / watch / live / etf …）
│   ├── chart/       量價・多圖・價差・畫線・型態・夜盤・Replay
│   ├── screener/    選股・掃描・策略・腳本・回測・精靈
│   ├── fundamental/ 估值・資金流・法人榜・供應鏈・個股期・計畫
│   ├── alert/       通知・推播・行事曆・資料源健檢・結算提醒
│   ├── ai/          AI 報告・命令面板・焦點掃描
│   └── ui/          工具列・拖拉視窗・PDF 匯入匯出・外觀
│
├── server/                      ── 後端服務（本機，純 stdlib）──
│   ├── server.py                HTTP server：YF proxy + LRU + 各功能 API
│   ├── alert_daemon.py          常駐警報（Telegram / Email / Webhook）
│   ├── watch_daemon.py          觀察清單 24h 後端偵測
│   ├── chip_history_tracker.py  每日法人籌碼快照
│   ├── etf_delta_tracker.py     每日主動 ETF 持股 delta（server 會就近 spawn）
│   └── backup_data.py · expand_etf_catalog.py
│
├── data/                        ── 使用者資料（多數 .gitignore）──
│   ├── etf_catalog.json · etf_history/ · chip_history/
│   └── alert_config.json · alert_rules.json · draw_store.json · ai_key.txt
│
├── scripts/                     ── 啟動與排程 .bat ──
│   ├── start_terminal_v3.bat    唯一啟動器（build + server + 開頁）
│   ├── rebuild_and_restart.bat · restart_server.bat
│   ├── daily_*.bat              排程觸發（籌碼 / ETF / 備份 / 報表 / 早報）
│   └── install_*.bat · fix_scheduler_paths.bat
│
└── docs/                        README 與規劃文件
```

### 設計原則

- **設定驅動的工具列**：所有功能鈕收進 4 個分類下拉（圖表 / 籌碼基本面 / 選股策略 / 快訊）＋ 常駐入口（指令 / AI 報告 / 焦點）。新增功能用 `Toolbar.register({...})` 一行掛上，分組只改 `src/ui/toolbar_v3.js` 的設定表。
- **載入順序自動化**：`build_order.py` 用相依表（取代人工「須在 X 後」）做穩定拓樸排序。
- **零雲端**：所有抓取與運算都在本機 `server.py`，資料留在 `data/`。

---

## 功能總覽（按模組分類）

### 核心看盤 — `src/core`

- 即時 Yahoo K 線，11 個時間段（1 天 ～ 全部）切換
- 16 項技術指標：RSI / KD / MACD / SMA / BB / ATR / 年化波動% / MaxDD% / 量比 / 乖離 / ETF Flow …
- 多市場：台股 + 美股（`US` 切換）
- 自選股清單（雙列、拖曳排序）+ 本地 LRU 快取 + 多執行緒併發抓取
- **POS 持倉**：成本 / 市值 / 未實現損益 + 規則化訊號（均線交叉、RSI、KD、MACD、布林、量能、倉位連動、主動 ETF 共振）
- **WATCH 多訊號觀察 + 共識評分**：8 策略（趨勢 / 動能 / 波動 / 價格）＋ 5 個預設劇本，一檔可掛多訊號自動算 Confluence
- **LIVE**：30 秒輪詢近即時報價（含 bid/ask）；指數（加權 / 櫃買 + 美股四大）也能加入自選

### 圖表分析 — `src/chart`

- **量價**：成交金額 Volume Profile（POC / VAH / VAL 主力成本區，可切金額 / 成交量）
- **多圖**（`Alt+M`）：2×1 / 2×2 / 1×3 分割，每格獨立換商品時框，**同步十字游標與時間軸**，版面記憶
- **價差**（`Alt+D`）：數學式合成線看相對強弱 / 溢價差（如 `2330/2303`、`^TWII/^SOX`；自寫解析器，純分析不可下單）
- **畫線**（`Alt+T`）：趨勢 / 水平 / 垂直 / 斐波那契 / 矩形 / 平行通道 / 文字，錨點以時間+價格記錄，換區間換裝置不消失
- **形態³**：19 種型態辨識（經典 + 諧波 XABCD/Cypher + 艾略特五浪/修正 + 循環分析）
- **vs 大盤**、**夜盤連動預警**（美股期貨 → 台股隔日）、**Replay** K 線重播

### 選股 / 策略 / 回測 — `src/screener`

- **選股**：技術 × 基本面 × 籌碼 三合一全台股篩選，一鍵載入或加自選
- **掃描**：全市場 Screener + 類股篩選
- **策略**：樂高式條件組合器 → 回測，輸出最大回撤 / 勝率 / 獲利因子 / 年化夏普 / 逐筆明細 + 權益曲線
- **腳本**：類 Pine 安全 DSL（自寫直譯器、函式白名單、不用 eval），`buy/sell` 回測、`plot` 疊主圖
- **回測引擎**：8 策略勝率 + 型態命中率 + 投組
- **精靈**：回答 4 題（用途 / 週期 / 風險 / 資金）自動體檢個股，一鍵套用 觀察訊號 + 警報 + 持倉/買進計畫 + 支撐壓力畫線 + 研判結論

### 籌碼 / 基本面 — `src/fundamental`

- **估值**：本益比河流（台股 + 美股），判斷現在貴不貴
- **資金流**：大盤量能趨勢（8000 億 → 1.2 兆）+ 三大法人
- **法人榜**：外資 / 投信買賣超排行 + 連續買賣超天數
- **供應鏈**：台灣 AI 供應鏈族群連動（晶圓 → 封裝 → CPO → 伺服器 → 散熱 RS 輪動）
- **個股期**：市值前十大個股期夜盤領先（期% − 現%）
- **基本面**：月營收 / 三率 / 評分卡
- **計畫（PLAN）**：持倉 / 買進計畫 + 歷史
- **ETF△**：主動 ETF 每日持股 delta + 共識報表（投信潛在買盤估算 + AI 原因解讀）

### 快訊 / 通知 — `src/alert`

- **通知**：桌面 / 頁內 toast
- **推播**：後端 daemon 走 Telegram / Email / Webhook（Discord/Slack/自架），**瀏覽器關著也偵測**
- **複合警示**：多條件 AND/OR（如「RSI < 30 且 收盤 ≤ 布林下軌」）
- **行事曆**：月營收 / 除權息提醒；**資料源健檢**燈、**結算日**提醒

### AI / 工具 — `src/ai`、`src/ui`

- **AI 報告**：Claude 八章節個股研究報告（需設 API Key，只存瀏覽器 localStorage）
- **焦點**：全台股多訊號掃描，自動找做多 / 做空焦點股
- **指令**：命令面板（`Ctrl+K`）搜尋股票與功能
- **工具列**（本次重構）：一階分類 + 二階摺疊下拉；拖拉視窗、PDF 匯入 / 匯出

### 後端服務 — `server/`

- **server.py**：本機 HTTP server，Yahoo proxy + LRU 快取 + 籌碼/ETF/估值/畫線等 API，純 stdlib
- **常駐 daemon**：警報（alert）、觀察（watch）後端偵測；籌碼（chip）、ETF（delta）每日快照
- 全本機運算、零雲端、零追蹤

---

## 快速開始（3 步）

> 需求：Windows 10/11 + Python 3.10+（純 stdlib，**不用 pip**）+ 現代瀏覽器。確認：cmd 打 `python --version`。

1. **解壓縮**到任一資料夾（例 `C:\Tools\Stock_Terminal\`）。
2. **雙擊 `scripts\start_terminal_v3.bat`** — 自動 build、開瀏覽器、啟動本機 server（port 18432）。
3. 上方輸入框打代號按 **GO**（台股 `2330`；美股先點 `US` 再打 `AAPL`）。

**更新後沒看到變化？** 關掉舊 server 黑視窗 → 雙擊 `scripts\rebuild_and_restart.bat` → 瀏覽器 **Ctrl+F5**。

**可選排程**（系統管理員身分跑一次）：`scripts\install_scheduler.bat`（每交易日 19:00 更新 ETF 持股）、`scripts\install_chip_scheduler.bat`（17:40 更新法人籌碼）。搬動資料夾後若排程失效，跑 `scripts\fix_scheduler_paths.bat` 重新指向。

---

## 系統需求

- Windows 10 / 11（macOS / Linux 也能跑 `server/server.py`，但 `.bat` 啟動器要自己改寫）
- Python 3.10+（純 stdlib，**完全不需要 pip install**）
- 現代瀏覽器（Chrome / Edge / Firefox）
- 網路連線（要打 Yahoo Finance / MoneyDJ / TWSE）

---

## 進階設定

### 改 server port

`server/server.py` 的 `PORT = 18432`。

### 改線型預設範圍

啟動前設環境變數（前端時間段按鈕仍可即時切換，這只是初次預設）：
```cmd
set YF_RANGE=10y
set YF_INTERVAL=1d
python server\server.py
```

### 改 ETF 觀測池

`server\etf_delta_tracker.py` 的 `ETFS = {...}` 改成你想追的代號；`server\server.py` 的 `ETF_NAME_MAP` 順手改名稱對照。

### 上傳 Claude API Key

終端機右上角按 `API KEY` → 貼上 `sk-ant-...` → 個股頁右側 RESEARCH 分頁即可跑 AI 研究報告。Key 只存瀏覽器 localStorage，不外傳。

---

## 資料來源

| 用途 | 來源 | 備註 |
|------|------|------|
| K 線 / 報價 | Yahoo Finance v8 chart API | 失敗時 fallback 經 allorigins.win |
| 主動 ETF 持股 | MoneyDJ Basic0007B | 全部持股頁面 |
| 法人籌碼 | TWSE 三大法人 | 每日快照累積連買賣天數 |

**所有資料抓取都在你本機跑，零雲端、零追蹤。**

---

## 疑難排解

**❌ 啟動了但瀏覽器顯示無法連線** → Port 18432 被占用。改 `server/server.py` 的 `PORT`，或關掉佔用程式（`netstat -ano | findstr 18432`）。

**❌ ETF△ 顯示「尚無足夠歷史檔」** → 跑 `python server\etf_delta_tracker.py --backfill 5` 一次；設好排程後明後天會累積真實的 day-over-day delta。

**❌ 中文亂碼** → Windows console 預設 CP950。`.bat` 已加 `chcp 65001` 切 UTF-8。看 log 用 `Get-Content -Encoding UTF8 logs\etf_xxx.log`。

**❌ Yahoo Finance 抓不到** → 偶爾 rate-limit，server 已內建 LRU cache + query1/query2 雙端點重試，仍失敗會自動經 allorigins.win 繞道。

---

## 版本沿革（精簡）

> 詳細功能見上方「功能總覽」；此處僅留各階段重點。

- **v2.0** 倉位管理（POS）+ 多訊號觀察（WATCH）+ 共識評分 + (i) 中文說明
- **v3.0** 19 種型態辨識（經典 / 諧波 / 艾略特 / 循環）
- **v3.5–3.7** Yahoo 日線落後修正、build 根因修正 + LRU TTL、全球型 ETF 持股完整抓取
- **v3.8** 四主軸（籌碼 / 基本面 / 回測 / 警報）+ 成交金額 Volume Profile + 後端推播 daemon
- **v3.9** 多圖 / 全鍵盤 / 視覺化回測 / 畫線 / 三合一選股 / 複合警示；**模組化重構**（工具列分類下拉、`src/` 依功能分區、`server/` `data/` `scripts/` 分區、載入順序自動排序）

---

## License / 致謝

MIT — 自由分享、修改、商用皆可，原作者保留歸功（不強制）。

- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) — 圖表引擎
- [MoneyDJ ETF 基智網](https://www.moneydj.com/etf/) — ETF 持股資料源
- [Yahoo Finance](https://finance.yahoo.com/) — 報價資料源
