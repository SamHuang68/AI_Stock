# Stock Terminal v3.8 規劃

四大主軸：**籌碼面深化 / 基本面深化 / 回測引擎強化 / 警報推播擴充**。
規劃日期 2026-06-01。每項標出貼合現有架構的改動點，避免重造輪子。

> 現況基準：程式碼實際已到 v3.4~v3.7 級（PLAN 卡、plan↔倉位、plan 歷史、alert、peg、screener、chip、ai_report、pdf 匯出入皆存在）。README 只記到 v3.7，v3.8 完成後一併補 README。

---

## A. 籌碼面深化（擴充 `chip_v3.js` + `server.py` `_handle_chip`）

現況：`_handle_chip` 只抓 TWSE **T86**（三大法人買賣超）+ **MI_MARGN**（融資融券）。

### A1. 分點/券商買賣超（主力進出）
- 新端點 `_handle_broker(sym)` — 抓 TWSE 分點資料（券商分點買賣超前 15 名）
- 資料源候選：TWSE 個股分點需付費，免費替代用 **MoneyDJ 主力進出** 或 **富邦/凱基分點** 公開頁
- UI：STATS 分頁籌碼 section 加「主力進出」子表（買超前 5 / 賣超前 5 分點 + 主力買賣超合計）

### A2. 借券賣出餘額
- T86 同源延伸：TWSE **TWT72U**（借券賣出）日報
- 顯示借券賣出餘額 + 日增減，與融券並列看空方力道

### A3. 當沖比
- TWSE **TWTB4U**（當日沖銷交易標的）→ 當沖成交量 / 總成交量
- 高當沖比 (>30%) 標紅旗，提示投機盤

### A4. 法人連續買賣超天數
- 在 `etf_history/` 模式上加 `chip_history/` 每日快照
- chip_v3 計算「外資連 N 買 / 投信連 N 賣」並在卡片顯示徽章
- **依賴每日盤後排程**（沿用 `install_scheduler.bat` 機制，新增 chip 抓取任務）

**新增檔**：`chip_history_tracker.py`（盤後抓 T86/TWT72U/TWTB4U 存快照）
**改動**：`chip_v3.js`（4 個新 section）、`server.py`（`_handle_broker` / `_handle_chip` 擴充欄位）

---

## B. 基本面深化（擴充 `peg_v3.js` + `_handle_keystats`）

現況：`_handle_keystats` 已有 trailingPE、eps、revenueGrowth、earningsQuarterlyGrowth。peg_v3 只做 PE/EPS/PEG 比較表。

### B1. 月營收 YoY / MoM
- 新端點 `_handle_revenue(sym)` — 抓台股月營收
- 資料源：**公開資訊觀測站 (mops.twse.com.tw)** 月營收彙總，或 MoneyDJ 月營收頁
- UI：新增「月營收」分頁，近 12 個月柱狀圖 + YoY/MoM 表，連續成長月數徽章

### B2. 毛利率 / 營益率 / 淨利率趨勢
- 抓近 8 季財報（mops 綜合損益表）
- 三率折線圖，判斷趨勢向上/向下

### B3. 財報三表 + 現金流
- 損益表 / 資產負債表 / 現金流量表近 4 季精簡版
- 重點指標：自由現金流、負債比、ROE、流動比

### B4. 基本面評分卡
- 綜合 B1~B3 算 0~100 基本面分數（成長性/獲利性/財務體質三維）
- 與 WATCH 共識評分（技術面）並列，形成「技術 × 基本面」雙軸

**新增檔**：`fundamental_v3.js`（月營收/三率/三表/評分卡 UI）
**改動**：`server.py`（`_handle_revenue` / `_handle_financials` 新端點 + mops 解析）、`peg_v3.js`（併入評分卡或保留獨立）

---

## C. 回測引擎強化（升級 `pro_v2.js` Backtest + `watch_v2.js` 8 策略 + `pattern_v3.js` 19 型態）

現況：pro_v2 有基礎 Backtest，plan_history_v3 有 mini 回測。缺統一的勝率/權益曲線引擎。

### C1. 統一回測核心 `backtest_v3.js`
- 輸入：股票 + 策略（WATCH 8 策略任一 / pattern_v3 19 型態任一）+ 區間
- 進出場規則：訊號觸發進場 → 停利/停損/N 日出場
- 輸出：勝率、賠率、期望值、最大回撤、夏普、權益曲線

### C2. 策略勝率統計
- 對 WATCH 8 策略各跑歷史回測 → 每策略歷史勝率表
- 共識評分 (+3/+1/...) 對應實際勝率校準，讓「強多 +3」有數據支撐

### C3. 形態歷史命中率
- pattern_v3 每個型態在歷史上偵測 → 偵測後 N 日報酬分布
- 給每個型態貼「歷史命中率 X%、平均報酬 Y%」標籤

### C4. 投組層級回測
- 多檔 + 資金配置（沿用 plan_position_v3 的倉位比例）→ 投組權益曲線、相關性、整體回撤

**新增檔**：`backtest_v3.js`（核心引擎 + UI 面板）
**改動**：`watch_v2.js`（勝率徽章）、`pattern_v3.js`（命中率標籤）、`pro_v2.js`（舊 Backtest 改呼叫新核心）

---

## D. 警報推播擴充（擴充 `alert_v3.js` + `server.py`）

現況：`alert_v3.js` 只有 Browser Notification（瀏覽器要開著才收得到）。

### D1. 後端常駐警報輪詢
- 警報邏輯下放到 `server.py`（不依賴前端開著）
- 新增 `alert_daemon`：server 啟動時背景 thread 每 60s 輪詢 plans/wl 價位

### D2. 推播通道
- **Telegram Bot**（推薦：免費、API 簡單、跨平台）— 設 bot token + chat id
- **Email**（SMTP，沿用 Gmail）
- ~~LINE Notify~~ 註：LINE Notify 已於 2025-03 停止服務，改用 **LINE Messaging API** 或直接走 Telegram
- 設定存後端 `alert_config.json`（token 等敏感資料不進 git，加 .gitignore）

### D3. 警報類型擴充
- 現有：過壓力 / 破支撐
- 新增：技術訊號觸發（KD 黃金交叉等）、籌碼異常（外資連買轉賣）、月營收公布、達停利/停損

### D4. 警報歷史 log
- 觸發紀錄存 `logs/alerts/`，UI 加警報歷史檢視

**新增檔**：`alert_daemon`（server.py 內模組或獨立）、`alert_config.json`（gitignore）
**改動**：`server.py`（背景 thread + Telegram/SMTP push）、`alert_v3.js`（設定 UI + 歷史檢視）

---

## E. 成交金額 Volume Profile（成交量對應成交價 → 主力成交金額）

現況：`pro_v2.js` 已有 POC（Point of Control，量價分布）。但目前是「成交量」基礎；使用者要的是**成交金額**（turnover = 價 × 量）對應到 Y 軸價位，用來判斷主力真正砸了多少錢、集中在哪個價區。

### E1. 金額基礎的量價分布
- 把每根 K 線的成交額 `turnover ≈ (H+L+C)/3 × volume` 分配到對應價格 bin
- Y 軸切 N 個價格 bin（預設 50~100 格），橫向 bar 長度 = 該價區累積**成交金額**（非張數）
- 與現有「量」profile 可切換（量 / 金額 兩種模式）

### E2. 主力成交金額辨識
- POC（金額最大價區）標粗線 + 顯示該價位累積金額（億/萬元）
- Value Area（70% 金額集中區）上下緣 VAH/VAL 標示
- 「主力成本區」= 金額 POC ± Value Area，判斷當前價在主力成本之上/之下

### E3. 區間可調
- 計算區間跟隨 chart 可視範圍（或可鎖定近 N 日 / 全部）
- 切換時間段（1天~全部）即時重算

**改動**：`pro_v2.js`（POC 模組擴成量/金額雙模式 + VAH/VAL/主力成本區）、`stock_terminal.html` v1 base（chart overlay Y 軸 profile 渲染，注意 build_v2.py 會覆寫故寫 v1 base，見 v3.6 教訓）

> 注意：截圖右側已有橫向量價 bar，E 是把它從「量」升級成「金額」並加 POC/VA/主力成本區標示。

---

## 建議落地順序

考量相依性與快速見效：

1. **D（警報後端化）** — 獨立性高、痛點明顯（瀏覽器要開著才收），先做有感
2. **A（籌碼深化）** — 資料源熟（已會打 TWSE），擴充 `_handle_chip` 增量小
3. **B（基本面）** — 需新解析 mops，工程量中等
4. **C（回測引擎）** — 最大工程，依賴前面資料齊全後做最有價值

每個主軸可獨立發 minor（v3.8.1 / .2 ...），不必綁成一個大版本一次出。

## 待確認決策

- **D2 推播通道**：先做 Telegram 還是 Email？（建議 Telegram 先，最省事）
- **A1 分點資料源**：免費源（MoneyDJ/分點頁）品質不一，可接受還是要找穩定源？
- **排程**：A4 連續買賣超、B 月營收都需盤後排程，沿用 Windows 工作排程器還是改 server 內建 cron thread？
- **發版策略**：四主軸綁成單一 v3.8，還是拆成 v3.8.x 漸進出？
