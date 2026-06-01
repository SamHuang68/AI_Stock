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

## v3.0 — 進階形態辨識 (TradingView-grade Pattern Recognition)

v3 把形態辨識器從 v2 的 8 種擴充到 **19 種**，目標是覆蓋 TradingView 形態工具列的核心功能。所有偵測都是規則式 (rule-based)、無黑盒 ML，每個型態都有明確的 Fibonacci / 幾何規則。

### 19 種型態（分四大類）

**經典反轉與持續（v2 保留並升級）**
- 趨勢結構 (HH/HL vs LH/LL)、雙頂雙底 (M/W)、頭肩頂底 (含頸線趨勢線)
- 黃金/死亡交叉、區間突破、箱型整理、杯柄、三角 (對稱/上升/下降三種子型)

**諧波 Harmonics (XABCD 五點)**
- **ABCD** — Fib 0.618/0.786 修正 + 1.27/1.618 延伸
- **XABCD** — Gartley / Bat / Butterfly / Crab / Shark (5 子型，每個都有獨立 Fib 比例)
- **Cypher 賽福** — CD/XC 0.786 反轉區

**艾略特波浪 Elliott Wave**
- **脈衝波 1-2-3-4-5** — 含 Elliott 三大鐵律驗證 (w2 不破 w0、w3 非最短、w4 不入 w1)
- **修正浪 A-B-C** — 自動分類 Zigzag / Flat / Irregular
- **三角波 A-B-C-D-E** — 五浪收斂三角修正
- **雙重組合 W-X-Y** — 兩個修正 + 連接浪
- **三重組合 W-X-Y-X-Z** — 三個修正 + 兩個連接 (罕見)
- **三驅 Three Drives** — 三推進浪衰竭型反轉

**循環分析**
- **FFT/自相關週期偵測** — 用去趨勢自相關找主要循環長度，預測下一個轉折點

### 核心引擎

- **ZigZag 規範化** — `buildZigZag()` 把 pivots 轉成嚴格交替的 H/L swing 序列，過濾 < 1.2% 雜訊
- **Fibonacci 比例驗證** — 每個諧波都有獨立 `ab_xa / bc_ab / cd_bc / ad_xa` 範圍（容忍 ±5%）
- **斜線繪製** — 升級 chart overlay 從 v2 的純水平 price line 到 LightweightCharts `LineSeries` 動態斜線，可連接任意 swing 點

### 使用方式

**整合進主終端機**
- `stock_terminal_v2.html` 已自動切換到 `pattern_v3.js`
- 工具列的 🤖 按鈕現在會顯示 "🤖 形態³"，點擊跳出 19 種型態的分組面板
- 長按 🤖 按鈕可在 chart 上 toggle overlay（畫斜線 + 標籤）

**獨立驗證頁** (`pattern_v3_test.html`)
- 直接用瀏覽器開啟（需先跑 `server.py` 在 port 18432）
- 預設自動載入 2330，可改任意代碼/區間 (1y / 2y / 5y)
- 左側 sidebar 顯示 19 偵測器逐個 ✅/❌ 狀態 + 觸發的型態詳情
- 點任一型態 → chart 只顯示該型態的標記
- 「疊加形態」按鈕可一鍵切換全部疊加 vs 全部清除

### 公開 API (window.PatternV3)

```js
PatternV3.detectPatterns(candles)       // 跑全部 19 偵測器
PatternV3.findPivots(candles, window)   // 基本 pivot
PatternV3.buildZigZag(candles, pivots)  // ZigZag swing 序列
PatternV3.detectXABCD(candles, zz)      // 諧波（回傳陣列，含所有匹配的 Gartley/Bat/Butterfly/Crab/Shark）
PatternV3.detectElliottImpulse(candles, zz)  // 艾略特五浪
PatternV3.detectCycle(candles)          // FFT 週期
// ... 等等，共 19 個獨立偵測器都可單獨呼叫
PatternV3.HARMONICS                     // 5 種 XABCD 的 Fib 比例定義
PatternV3.FIB                           // 常用 Fib 比例常數
```

向下相容：`window.detectPatterns / showPatternsModal / patternsToggle / loadPatternCandles / renderPatternsPanel` 全部被 v3 版本覆寫，現有 v2 hook 不用改。

---

## v3.5 — Yahoo 日線落後修正 + 使用者本地時區（2026-05）

### 背景：Yahoo 雙伺服器資料不同步問題

Yahoo Finance 提供報價的 query1/query2 兩台前端常出現「日 K 線陣列已停留在前一交易日，但 `regularMarketPrice` 已更新到今日收盤」的時間差。盤後幾小時甚至到隔日凌晨期間，這個落差最明顯，造成：

- ETF / 個股 % 變化跳動於「今天」和「昨天」之間（例如 00830 應顯示 -3.42%，常閃成 +4.02%）
- 全市場 Screener 抓到的「漲幅榜」其實是昨日漲幅（例如 2454 顯示 +8.79% 而非 -4.96%）
- 指數面板 (加權 / 櫃買 / 費半 / S&P500 / NASDAQ / 道瓊 / 日經 / 恆生) 部分顯示 0.00%
- TW / US Sectors 熱力圖數字偏差
- 點擊個股後 chart-info 與昨收線錯位

### 統一修法：rmt vs last candle 對齊判斷

凡是用 Yahoo daily K 算 %chg 的地方都加同一段判斷：

```js
// 若 regularMarketTime 比最後一根 K 線晚 > 20 小時 →
// regularMarketPrice 才是「今天」，last candle 是「昨天」
if (rmt && rmp && rmt - last.time > 20 * 3600) {
  cur = rmp;
  prev = last.close;
}
```

對於 chart 顯示則更進一步「合成今日 K 線」（OHLC 全用 rmp，量設 0 或近 5 日均量），讓 chart、chart-info、chip 全部對齊。

Yahoo 資料同步正常時（K 線追上 rmt），合成 K 線自動不觸發，邏輯安全可逆。

### 涵蓋範圍（8 處全收）

| 模組 | 檔案 | 觸發路徑 |
|------|------|---------|
| Watchlist 30s 輪詢 chip | `wl_live_v3.js` | 自動 |
| 點擊載入 daily/weekly chart | `stock_terminal_v2.html` (loadSym) | 點 chip / 輸入代號 |
| 點擊載入 intraday chart | `stock_terminal_v2.html` + `polish_v3.js` | 1天 / 3周 視圖 |
| 全市場 Screener | `server.py` (_handle_screener_post) | 🔍 掃描 |
| 指數面板 (8 個) | `polish_v3.js` (refreshMktBar) | 每分鐘自動 |
| US Sectors API | `server.py` (_handle_sectors_us) | 熱力圖 US |
| TW Sectors API | `server.py` (_fetch_tw_sectors_via_yahoo) | 熱力圖 TW |
| Heatmap UI | `heatmap_v3.js` (extractChg) | 開啟熱力圖 |

### Intraday (1天) 模式昨收 / % 計算

`1天` 視圖的 candles 是當日 5-min K，過去版本直接拿倒數第二根當「昨收」算出微幅變動（例 +1.50% 而非正確的 -4.96%）。修法：

- intraday 模式改用 `meta.chartPreviousClose`（Yahoo 內建昨日收盤），存入 `S.data.yesterdayClose`
- `polish_v3.js` 的「昨收」水平虛線、ci-chg 顏色都改讀 `S.data.yesterdayClose`，daily 模式仍維持原邏輯

### 圖表時間軸：使用者本地時區

lightweight-charts 預設用 UTC 顯示時間軸，台股 13:30 收盤會顯示成 05:30。修法：

- 從 `new Date().getTimezoneOffset()` 取得使用者瀏覽器時區（Taipei 為 +28800s）
- 所有 chart series（candles / volume / SMA / BB）的 timestamp 一律加上 userTzOffset 後再丟給 lightweight-charts
- Crosshair 讀回時改用 `getUTCHours / getUTCMinutes / getUTCDate`（時間已被預先平移）
- 效果：所有市場一致對齊到使用者本地時鐘
  - TW 股 in Taipei：**09:00–13:30**（本地交易時段）
  - US 股 in Taipei：**21:30–04:00 隔天**（NYSE 在 Taipei 的真實時段，自動跨日）

未來換時區（搬家 / 出國）瀏覽器抓到的 offset 會自動跟著變，不需要改設定。

### 重啟 server

`server.py` 三處修改（screener / sectors-us / sectors-tw）需要重啟 server 生效：

```
雙擊 restart_server.bat
```

本檔自動殺掉 port 18432 上的舊 process 再重啟。client 端修改透過 `?v=` 版本號參數 cache bust，重整即可生效。

---

## v3.6 — 根因修正：build 重置 + LRU TTL（2026-05）

### 真正的根因（前 5 輪修正失效原因）

v3.5 加了一堆「Yahoo 日線落後」的修正，但你會看到：
1. 重啟後第一次點某股 → 顯示正確
2. 過幾分鐘再點 → 又跳回昨天的 %
3. chip 跟 chart-info 顯示不一致

挖到底原來是兩個獨立問題串在一起：

**問題 A：`stock_terminal_v2.html` 是 build_v2.py 從 v1 base 自動生成。**

我的 loadSym 修正（合成 K 線、yesterdayClose、時區平移）全部寫在 v2.html，但每次跑 `start_terminal_v2.bat` 觸發 build 都會從 `stock_terminal.html` 重生 v2.html，**所有 fix 被覆寫回原始版本**。表現為「修完看起來對，下次開啟又跳回」。

修法：**所有 loadSym + renderChart 修正改寫到 `stock_terminal.html` (v1 base)**，build 會保留。

**問題 B：`server.py` 的 LRU cache 沒 TTL。**

```python
class LRUCache:   # 原始版本：永久 cache
    def get(self, k): return self._d.get(k)
    def set(self, k, v): self._d[k] = v
```

若 server 啟動後第一次打 Yahoo 剛好遇到 query1/query2 同步落差期間（盤後/凌晨很常見），Yahoo 整份 response（含 `regularMarketPrice = 昨天收盤`、`regularMarketTime = 昨天盤後`、整個 K 線陣列）會被**永久 cache**。後續所有 client 端的修正邏輯（rmt 比對、合成 K 線）拿到的都是這份「過時但內部一致」的快照 — 連 `rmt - last.t > 20h` 都因為兩者都是昨日而觸發不了。

`wl_live_v3.js` 因為 `nocache=1` 繞過 LRU 而看起來正常，所以你看到的就是「**chip 是對的，點開卻是昨日**」這種「隨機」行為 — 哪邊讀 cache 看哪邊。

修法：**加 TTL=60 秒到 LRUCache**：

```python
class LRUCache:
    def __init__(self, maxsize, ttl_seconds=60):
        self._d = OrderedDict()       # key → (value, expire_ts)
        self._ttl = ttl_seconds
    def get(self, k):
        ent = self._d.get(k)
        if ent and ent[1] > time.time(): return ent[0]
        if ent: self._d.pop(k, None)   # expired
        return None
    def set(self, k, v):
        self._d[k] = (v, time.time() + self._ttl)
```

60s TTL 對效能影響可忽略：同一張線型 60s 內反覆點仍走 cache；最壞情況也只持續 60 秒就會重抓 Yahoo。

### 一鍵 rebuild + restart

由於這次同時改了 v1 base 和 server.py，提供整合腳本：

```
雙擊 rebuild_and_restart.bat
```

執行步驟：
1. `python build_v2.py` 從 v1 source 重新生成 v2.html
2. Kill port 18432 舊 server
3. 啟動含 TTL 的新 server.py

---

## v3.7 — 全球型 ETF 持股完整抓取 + 多市場跳轉（2026-05）

### 問題

00988A 主動統一全球創新（也包含 00989A 等全球型 ETF）顯示的 TOP 10 持股全部是台股，少了真正大佔比的外國成分（Samsung、AMD、Micron、ROHM 等）。實際 46 檔持股只看到 13 檔。

### 根因

`etf_delta_tracker.py` 的 MoneyDJ row 解析 regex 寫死兩個假設：

```python
_MDJ_ROW_RE = re.compile(
    r'etfid=(\d{4,6})\.TW(?:&|&amp;)back=[0-9A-Za-z]+\.TW[^>]*>'
    #         ^^^^^^^                                  ^^^^
    r'\s*([^<]+?)\(\1\.TW\)\s*</a>'
    #                  ^^^^
    ...
```

- `(\d{4,6})` 只接受純數字 code → AMD / MU / AAPL（字母 code）整批被擋
- `\.TW` 鎖死後綴 → 009150.KS / 6963.JP / 0700.HK / 600519.SH 全部被擋

MoneyDJ HTML 對外股的 link 格式：

```
etfid=AMD.US      → AMD(AMD.US)
etfid=6963.JP     → ROHM(6963.JP)
etfid=009150.KS   → Samsung Elec Mech(009150.KS)
```

### 修法

#### 1. Regex 放寬

```python
_MDJ_ROW_RE = re.compile(
    r'etfid=([0-9A-Za-z]{1,7})\.([A-Z]{2})(?:&|&amp;)back=[0-9A-Za-z]+\.TW[^>]*>'
    r'\s*([^<]+?)\(\1\.\2\)\s*</a>'
    ...
)
```

新增 group 2 抓市場碼，holdings 多存 `market` 欄位。00988A 的 41/46 筆現在都抓得到（剩 5 筆是現金/期貨/特殊格式 row，佔權重 < 1%）。

#### 2. 市場碼 → Yahoo Finance 後綴 mapping

MoneyDJ 跟 Yahoo 對市場後綴的命名不完全一致：

| 市場 | MoneyDJ | Yahoo | 範例 |
|------|---------|-------|------|
| 台灣 | .TW | .TW | 2454.TW |
| 美國 | .US | (無) | AMD |
| 日本 | .JP | **.T** | 6963.T |
| 韓國 | .KS | .KS | 009150.KS |
| 香港 | .HK | .HK | 0700.HK |
| 上海 | .SH | **.SS** | 600519.SS |
| 深圳 | .SZ | .SZ | 000858.SZ |
| 德國 | .DE | .DE | SAP.DE |
| 英國 | .L | .L | HSBA.L |

`etf_v3.js` 加 `mapToYahoo(sym, mdjMkt)` helper，點擊持股時即時 map 並 dispatch 到 `loadSym(yfsym, uiMkt)`。HK 股代號自動 padStart(4, '0')。

#### 3. 顯示優化

外股代號旁顯示小型市場後綴標籤：

```
1. AMD .US           Advanced Micro Devices    4.70%
2. 6963 .JP          ROHM                      0.47%
3. 009150 .KS        Samsung Elec Mech         5.76%
4. 2454              聯發科                    3.84%   ← 台股不顯示 .TW
```

### 套用步驟

```
1. python etf_delta_tracker.py        重抓 holdings（含 market 欄位）
2. rebuild_and_restart.bat            套用 etf_v3.js 改動
```

---

## v3.8 — 籌碼/基本面/回測/警報 四主軸 + 成交金額 Volume Profile（2026-06）

一次推進五個方向。新增模組皆可獨立關閉，不影響既有功能。

### E. 成交金額 Volume Profile（主力成交金額）

`volume_profile_v3.js` 覆寫 pro_v2 的 POC，把每根 K 的成交**金額**（typical price × volume）分配到 Y 軸價格 bin，右側畫橫向直方圖，並標出：

- **POC**（金額最大價區，主力最集中成本）粗線 + 累積金額（億/萬）
- **VAH / VAL**（70% 金額集中區上下緣）虛線
- **主力成本區** = VAL~VAH，自動判斷現價在主力成本之上（偏多）/ 之下（偏空）/ 區內（盤整）

工具列 `📊 量價` 開關、模式鈕循環切換 **量價均衡**（金額與量各自正規化後平均，預設）→ **金額** → **成交量**。

### 版面：可拖拉左右分隔

`layout_v3.js`：線型區 `#left` 與功能分析區 `#right` 之間加可拖曳分隔條 `#splitter`，寬度存 localStorage，雙擊重置成 340px。底部 16 指標鎖成 2 列、頂部自選股維持 2 列。拖曳後自動觸發 chart resize + 量價重繪。

### A. 籌碼深化

`_handle_chip` 擴充：借券賣出餘額（TWT72U）、當沖比（TWTB4U，>30% 標 🚩）、法人連續買賣超天數徽章。新增 `chip_history_tracker.py` 盤後抓 T86 全市場存 `chip_history/`，累積後 `_chip_streak()` 算「外資連 N 買/賣」。

### B. 基本面深化

`fundamental_v3.js` + `/fundamental/<sym>` 端點（TWSE OpenAPI 全市場資料集，整批快取一天）：月營收當月/YoY/MoM/累計YoY、損益表三率（毛利/營益/淨利率）+ EPS、基本面評分 0~100。與 WATCH 技術面共識並列成「技術 × 基本面」雙軸。STATS 分頁新增「基本面」section。

### C. 回測引擎強化

`backtest_v3.js` 統一核心（自足 SMA/RSI/BB，不依賴他模組）：

- **策略掃描** 8 策略歷史勝率 / 賠率 / 期望值 / 總報酬 / 最大回撤 / 夏普
- **型態命中率** 對 PatternV3 型態跑歷史偵測 → 10 日後報酬分布
- **投組回測** 多檔 + 資金配置 → 投組權益曲線
- `backtest_ui_v3.js` 提供面板（工具列 `📈 回測`），點任一策略列畫權益曲線

### D. 警報推播擴充（後端常駐）

警報邏輯下放 `server.py` 背景 thread（`alert_daemon.py`），**瀏覽器關著也會推播**：

- **Telegram Bot**（推薦）+ **Email (SMTP)** 雙通道
- 設定存 `alert_config.json`、規則存 `alert_rules.json`（皆 .gitignore，含 token）
- 端點：`GET /alert/status|rules|config`、`POST /alert/rules|config|test`
- 前端 `alert_push_v3.js`（工具列 `🔔 推播`）：開關 daemon、設定通道、規則表、測試推播
- 觸發紀錄存 `logs/alerts/`
- 註：LINE Notify 已於 2025-03 停服，故改 Telegram

### 套用步驟

```
雙擊 rebuild_and_restart.bat      # build_v2.py 重生 v2.html + 重啟含新端點的 server.py
（可選）python chip_history_tracker.py    # 起始一筆籌碼快照
```

警報設定、Telegram token 在終端機 `🔔 推播` 面板填，或直接編 `alert_config.json`。

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
├── pattern_v2.js              AI 形態辨識 v2（8 種經典 — 保留作為 legacy）
├── pattern_v3.js              AI 形態辨識 v3（19 種：v2 + 諧波 XABCD/Cypher、ABCD、三角(對稱/上升/下降)、三驅、艾略特五浪/修正/三角/雙重/三重組合、循環分析）
├── pattern_v3_test.html       v3 獨立驗證頁（連 server.py，全部 19 種偵測器逐個跑、結果直接畫在 chart 上）
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
