# Stock Terminal v3.9 設計規格書 — 「向 TradingView 看齊」

> 依 Gemini 建議的 5 大維度 + 複合警示/ETF 深化，對接現有 v3.8.2 架構撰寫的**實作規格**。
> 交付原則：先規格、後實作。經 Sam 確認後逐功能實作 → Windows 端 rebuild 驗證。
> 撰寫日期 2026-06-14。基底 commit `b886e6e` (v3.8.2)。

---

## 0. 架構前提（所有新模組都必須遵守）

這些是從現有程式碼讀出的硬規則，新功能一律沿用，避免重蹈覆轍：

1. **狀態用裸 `S`**：`stock_terminal.html` 內 `let S = {...}`（詞法全域，**非** `window.S`）。新模組存取狀態一律 `S.xxx`（必要時 `typeof S!=='undefined' && S.xxx`），**禁止** `window.S`。
2. **模組樣板**：每個功能 = 一支 `xxx_v3.js`，IIFE `(function(){ 'use strict'; ... })()`，對外只掛 `window.xxxOpen / xxxClose / xxxRefresh`。資料打 `const SRV = window.SERVER || 'http://localhost:18432'`。
3. **工具列鈕**：在 `pro_v2.js` 注入 UI 區塊新增 `<button class="probtn" id="btn-xxx" onclick="window.xxxOpen&&xxxOpen()">`，排在現有鈕之後。
4. **載入個股**：呼叫全域 `loadSym(code, mkt)`。切股事件 `window.dispatchEvent('symLoaded',{detail:{sym,mkt}})` 已存在，可監聽。
5. **圖表物件**：單一 `S.chart`（lightweight-charts），`S.chartSeries`(K線)、`S.volSeries`、`S.overlaySeries`(SMA/BB)。`renderChart()` 已被 pro_v2 hook，重繪後自動跑 `attachChartContext / drawLines / drawVolumeProfile`。
6. **時區**：圖表時間都先 `+S.tzOffset` 平移到本地時鐘；crosshair 讀回用 `getUTC*`。新疊圖資料要套同一 `tz()`。
7. **build**：純前端 script 改完 **Ctrl+F5 即生效**（script src）。動到 `stock_terminal.html` 本體或新增模組檔，要跑 `build_v2.py` 重生 `stock_terminal_v2.html`，再到 `V2_SCRIPTS` 陣列登記新檔。改 `server.py` 要重啟 server。
8. **資料源紀律**：`.tw` 來源（TWSE/TPEx OpenAPI、Yahoo TW SSR）**沙盒連不到**，一律 Windows 端實測；我這端只能審查程式碼 + 驗證走國際 Yahoo 的路徑。回報前不假裝已驗證。
9. **.bat 純 ASCII**：所有批次檔禁止中文（CP950 亂碼）。
10. **市場派視角**：研判類輸出（警示原因、AI 推導）保留 TSMC/台灣 AI 供應鏈結構偏多的背景，但短線以當下數據修正並提醒風險。

---

## 1. 多圖連動布局（Multi-Chart Layouts）★ 第一優先

**目標**：同畫面看多個圖（同股多時框 / 相關商品並排），同步十字游標與時間軸。

**設計決策**：lightweight-charts 一個 instance = 一張圖。多圖 = 在主圖區生成 grid 容器，每格各自 `createChart`。為**不破壞** `S.chart`/`renderChart`/畫線/量價等既有邏輯，採「**主圖不動，多圖為獨立 overlay 模式**」：

- 新檔 `multichart_v3.js`，工具列鈕 `▦ 多圖`。
- 開啟時在 `#chart-wrap` 上層蓋一個 `#mc-grid`（絕對定位、佔滿圖區），支援版面：`1×1`(關閉)、`2×1`、`2×2`、`1+3`。
- 每格一個輕量 chart：K線 + 量 + SMA20/60（重用 `renderChart` 的計算函式，抽成共用 helper `mcBuildPanel(container, candles, opts)`）。每格頂端有：商品輸入框（敲代號 Enter 換股，見 §5 全鍵盤）、時框下拉（1d/5d/1mo/6mo/1y/...）、interval。
- **同步十字游標**：每格 `subscribeCrosshairMove`，把 time 廣播給其他格 `chart.setCrosshairPosition(price, time, series)`（lightweight-charts v4 API；若版本無此 API 則退化為自繪垂直線 overlay）。
- **同步時間軸**：監聽每格 `timeScale().subscribeVisibleLogicalRangeChange`，設 guard flag 防回圈，套用到其他格 `setVisibleLogicalRange`。可由「🔗 連動」開關切換是否同步。
- 預設樣板：①同股多時框（2330 日/週/60分/月）②供應鏈對比（2330/TSM/SOXX/^TWII）③自選股前 4 檔。樣板存 localStorage `mc_layouts`。
- 點任一格標題 → `loadSym` 把該商品設為主商品（回單圖時承接）。

**資料源**：沿用 `/yf/batch`（一次抓多商品）+ `/yf` 單檔多 interval。無新後端。

**驗證**：我端可用美股(TSM/NVDA/SOXX)驗證 grid 渲染與游標/時間同步；台股代號 Windows 實測。

---

## 2. 進階畫線工具 + 雲端記憶（Drawing Tools）

**現況**：目前只有**水平價格線**（右鍵 → `createPriceLine`，存 `S.lines[sym]` → localStorage）。無斜線、趨勢線、斐波那契、型態標記。

**設計決策**：lightweight-charts 原生不支援任意斜線，需在圖上疊一層 `<canvas>` 自繪（用 `timeScale().timeToCoordinate` + `series.priceToCoordinate` 換算）。新檔 `drawtools_v3.js`，工具列鈕 `✏ 畫線`，開啟一個浮動工具盤：

- **工具**：趨勢線(2點)、水平線(沿用既有)、垂直線、平行通道(3點)、斐波那契回撤(2點，畫 0/23.6/38.2/50/61.8/78.6/100%)、矩形/區間標記、文字標籤、型態標註(頭肩頂/雙頂等預設文字標)。
- **互動**：選工具 → 在圖上點擊定錨 → 拖曳調整端點。每個物件有顏色/線寬/刪除。
- **重繪**：監聽 `timeScale().subscribeVisibleTimeRangeChange` + resize，canvas 全量重畫（座標換算）。掛進 pro_v2 既有的 `renderChart` hook，切股/切區間後重畫。
- **記憶**：物件存 `S.draw[sym]`（含 time 座標而非像素，跨區間/裝置可還原）→ localStorage `draw_v3`。**雲端記憶**：新增後端 `GET/POST /draw/<sym>`（存 server 端 `draw_store.json`，gitignore），前端開檔時 merge 本地 + 雲端，換裝置畫線不消失。
- 與既有 `S.lines` 並存：水平線維持舊路徑，新斜線/Fib 走 `S.draw`，避免回歸。

**驗證**：純前端座標換算 + canvas，我端可用任意美股驗證畫線/Fib/還原；雲端端點走 localhost，Windows 測同步。

---

## 3. 視覺化 + 程式化策略回測（核心護城河）★ 第二優先

**現況**：`backtest_v3.js`(核心) + `backtest_ui_v3.js`(UI)，已有 8 策略勝率/型態命中率/權益曲線。Gemini 要求：①樂高式條件組合器 ②類 Pine 腳本編輯 ③績效深化(MDD/勝率/獲利因子/夏普/逐筆明細)。

**設計決策**：在現有回測核心上**擴充**，不另起爐灶。

### 3a. 樂高式條件組合器 `strategy_builder_v3.js`（工具列 `🧱 策略`）
- UI：兩區塊「進場條件」「出場條件」，每條 = `[指標A] [比較] [指標B/數值]`，多條以 AND/OR 串。
- 指標池：收盤/開/高/低、SMA(n)、EMA(n)、RSI(n)、KD 的 K/D、MACD/Signal/Hist、BB 上/中/下軌、成交量、量均(n)、漲跌%。比較：`> < 交叉向上 交叉向下 介於`。
- 編譯成一個 `evalBar(i, ctx)` predicate 陣列 → 餵進回測引擎跑訊號。
- 條件組存 localStorage `strat_builder`，可命名、另存、套用到目前個股或一籃子。

### 3b. 迷你腳本引擎 `strategy_script_v3.js`（進階分頁）
- 一個 textarea + 「執行」，**安全的 DSL**（不是 eval 任意 JS）：類 Pine 的逐行語法，例如：
  ```
  fast = sma(close, 20)
  slow = sma(close, 60)
  buy  = crossover(fast, slow) and rsi(14) > 50
  sell = crossunder(fast, slow)
  plot fast, slow
  ```
- 自寫 tokenizer + 小型表達式直譯器（函式白名單：sma/ema/rsi/kd/macd/bb/crossover/crossunder/highest/lowest/and/or/not/比較/算術）。**禁用** `eval`/`Function`。
- 在主圖渲染 buy/sell marker（`series.setMarkers`）+ plot 指標線。
- 範例腳本內建數個（均線黃金交叉、RSI 背離、布林通道突破）。

### 3c. 績效報告深化（改 `backtest_v3.js` 統計層）
補：最大回撤 MDD(%)與回撤期間、勝率、獲利因子(總獲利/總虧損)、夏普值(年化，無風險利率參數)、平均持有K數、最大連勝/連敗、期望值、**逐筆交易明細表**(進出日期/價/報酬%/持有天)。UI 加分頁「績效/權益曲線/交易明細」。

**驗證**：純前端 + 既有 candles，我端可完整驗證（含 DSL 直譯器單元測試：餵已知序列驗 sma/rsi/crossover）。

---

## 4. 三合一進階選股器 + 總經數據（Top-Down）

**現況**：`screener_v3.js` + 後端全市場 universe（`_get_tw_universe` ~2000 檔、`_get_tw_sectors`）。Gemini 要求技術+基本+籌碼三合一 + FRED 總經疊圖。

### 4a. 三合一 Screener（擴 `screener_v3.js` + 後端）
- 條件分三類可任意組合：
  - **技術面**：站上/跌破 SMA20/60/200、RSI 區間、創 N 日新高/低、量增 X 倍、KD 黃金交叉。
  - **基本面**：月營收 YoY/MoM > X%、近4季 EPS 成長、毛利率/營益率趨勢向上、PER/PBR/殖利率區間。（沿用 `fundamental_v3` / `/keystats` / OpenAPI t187ap05/06 快取）
  - **籌碼面**：投信/外資連買 N 天、主力買超、融資減/增、當沖比。（沿用 T86 / `_chip_streak`）
- 後端新端點 `GET /screen3?tech=...&fund=...&chip=...`：對 universe 批次套條件（線程池並發，吃滿 CPU—符合硬體偏好）。當日結果快取。
- 結果一鍵「存成自選股清單(Watchlist)」：寫進 `S.wl` + 既有 watch 儲存。結果列點擊 `loadSym`。
- **UI 防呆**：結果區用獨立可捲動容器、限高，避免像之前 screener 被卡片擠出視窗。

### 4b. 總經疊圖 `macro_v3.js`（工具列 `📉 總經`）
- 後端新端點 `GET /macro/<series>`：
  - **美國**走 **FRED API**（需 user 申請免費 API key，存 alert_config.json）：US10Y(DGS10)、10Y-2Y 利差(T10Y2Y，看倒掛)、CPI、Fed Funds、失業率、PMI 代理。
  - **台灣**：景氣對策燈號分數、CPI、出口 YoY → 走 OpenAPI/主計總處或國發會（Windows 實測來源可達性，取不到標「待查」不編造）。
- 前端：在主圖副圖區（或獨立 modal 雙軸圖）把總經序列與個股/大盤疊圖，算**相關係數**（rolling correlation），標示「殖利率倒掛區間」陰影。
- 呼應市場派：量能 8000億→1.2兆、四大 CSP capex 等可作為台股結構偏多註解。

**驗證**：FRED 走國際網路，我端可驗證端點與疊圖；台灣總經來源 Windows 實測。

---

## 5. UI/UX：全鍵盤 + 價差/比值圖 ★ 第一優先（與多圖並列）

### 5a. 全站快捷鍵 `hotkeys_v3.js`
- **打字即搜尋**：非輸入框聚焦時，鍵入數字/字母 → 浮出 quick-search（敲 `2330` Enter 直接 `loadSym`，美股敲 `NVDA`）。沿用既有搜尋/`loadSym`。
- 快捷：`Space` 下一檔自選股、`Shift+Space` 上一檔、`1~9` 切時框、`Alt+T` 趨勢線、`Alt+F` 斐波那契、`Alt+H` 水平線、`Alt+M` 多圖、`/` 開搜尋、`Esc` 關 modal。
- 防呆：在 input/textarea 內不攔截。快捷表 `?` 顯示 cheatsheet。

### 5b. 價差/比值圖 `spread_v3.js`（搜尋框支援公式）
- 搜尋框輸入數學式 → 繪合成序列：`2330/2303`(比值/相對強弱)、`2330-TSM*匯率`(溢價差)、`^TWII/^SOX` 等。
- 解析器：token 化 `代號 + - * / ( ) 數值`，向後端 `/yf/batch` 抓各代號對齊時間軸後逐點運算，產合成 candle/line 餵 `renderChart`（或多圖一格）。
- 標示為合成商品（不可下單，僅分析），標題顯示原式。匯率走 `TWD=X` 等 Yahoo FX。

**驗證**：純前端 + /yf/batch，我端可用美股比值(NVDA/AMD)驗證；台股 Windows 測。

---

## 6. 複合式警示 + ETF 深化（本次一併納入）

**現況**：警示前端 `alert_v3.js`/`alert_push_v3.js` + 後端 `alert_daemon.py`/`watch_daemon.py`（8 策略、每5分鐘、Telegram/Email）。ETF `etf_v3.js` 已有持股變動明細(+1/-1/加減碼)、`etf_report.py` 共識報表。

### 6a. 複合式警示（擴 `alert_v3.js` + `watch_daemon.py`）
- 警示條件升級為**多條件複合**（重用 §3a 的條件組合器引擎）：例：`RSI<30 且 觸及 BB 下軌`、`價格交叉趨勢線`（讀 §2 的 `S.draw` 趨勢線，daemon 端用線性外推算當日對應價）。
- 推播管道加 **Webhook**（POST 任意 URL，給 user 自接 Line Notify 替代品/Discord/自架）。Telegram/Email 已有；LINE Notify 已停服不做。
- 設定存 `watch_rules.json`/`alert_rules.json`（已 gitignore）。daemon 解析複合條件。

### 6b. ETF 異動深化（擴 `etf_v3.js` + `etf_delta_tracker.py`）
- **投信潛在買盤佔比**：當多檔主動 ETF 同時加碼某檔 → 估「本週新增持股張數 ÷ 個股近 N 日均量」%，標示買盤壓力強度。資料：ETF 持股變動張數(已追蹤) + 個股均量(/yf)。
- **AI 原因推導**：點某筆異動 → 呼叫既有 AI 報告鏈，餵「ETF 名 + 個股 + 近期財報重點(月營收/三率/EPS) + 加減碼幅度」→ 一句話解讀。沿用 `ai_report_v3` 的後端 chat 端點與「以代號為準、不臆測公司名」紀律。
- UI：ETF△ 報表內每筆異動加「佔量%」欄 + 「🤖 原因」鈕。

**驗證**：佔比計算我端可用合成資料驗算法；ETF .tw 持股資料 + AI 推導 Windows 實測。

---

## 7. 分期實作計畫（建議順序）

| 階段 | 內容 | 產出檔 | 我端可驗證度 |
|---|---|---|---|
| **P1**（先做，立即有感）| §1 多圖連動、§5a 全鍵盤、§5b 價差圖 | `multichart_v3.js`、`hotkeys_v3.js`、`spread_v3.js` | 高（美股驗證） |
| **P2**（護城河）| §3 視覺化+腳本回測、績效深化 | `strategy_builder_v3.js`、`strategy_script_v3.js`、改 `backtest_v3.js` | 高（含單元測試） |
| **P3** | §2 進階畫線+雲端記憶 | `drawtools_v3.js`、server `/draw` | 中（端點走 localhost） |
| **P4** | §4 三合一選股+總經 | 擴 `screener_v3.js`、`macro_v3.js`、server `/screen3`、`/macro` | 中（FRED 可驗、台源 Win 測） |
| **P5** | §6 複合警示+ETF 深化 | 擴 `alert_v3/watch_daemon/etf_v3/etf_delta_tracker` | 低（.tw + daemon，Win 測為主） |

每階段交付後請你 Windows rebuild + 實測回貼結果，確認 OK 再進下一階段。

## 8. 動到的共用檔（每階段對應）
- `build_v2.py`：`V2_SCRIPTS` 依序登記每支新 `*_v3.js`（畫線/腳本等有相依順序的排在依賴之後）。
- `pro_v2.js`：UI 注入區塊加各工具列鈕。
- `server.py`：P3 `/draw`、P4 `/screen3` `/macro`、P5 webhook 與佔比。改完重啟。
- `README.md` / `build_dist.bat`：版本升 v3.9、打包清單納新檔（最後一步）。
- `commit_v3_9.bat`（純 ASCII，含 `git push origin main`）。

## 9. 待你確認的決策點
1. **分期順序**：是否照 P1→P5？或想先抽某一項（如先做 §3 回測）。
2. **FRED**：你要不要用美國總經（需免費 API key）；台灣總經來源若取不到，是否接受「先標待查」。
3. **雲端畫線**：存在本機 server `draw_store.json` 即可，還是要同步到某處（目前無雲端帳號系統，建議先本機 server 檔）。
4. **價差圖**：合成商品要不要也能存進自選股 / 套警示，還是純看圖。
