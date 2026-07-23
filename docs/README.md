# Stock Terminal

Bloomberg 風格的個股研究終端機。**本機跑、零雲端、零追蹤、不需 pip 安裝任何套件**（純 Python stdlib）。
架構為「瀏覽器前端 ↔ 本機 `server.py` ↔ 外部資料源（Yahoo / MoneyDJ / TWSE）」三層；前端模組依功能分資料夾，新增功能用 `Toolbar.register({...})` 一行掛上。

---

## 功能總覽

### 核心看盤
- 即時 Yahoo K 線，11 個時間段（1 天 ～ 全部）；台股 + 美股切換
- 16 項技術指標：RSI / KD / MACD / SMA / BB / ATR / 年化波動% / MaxDD% / 量比 / 乖離 / ETF Flow…
- 自選股清單（雙列、拖曳排序）+ 本地 LRU 快取 + 多執行緒併發抓取
- **代號庫**（🗂）：全台股(含 ETF / 上櫃) + 美股 lookup;市場判定一律由代號決定、永不抓錯,可一鍵更新收錄新上市股 / ETF
- **資料源管理**（🗄）：所有資料源一表 — 提供者、可靠度（官方 / 第三方 / 本地）、最後更新、筆數;每源可一鍵從可靠來源重抓更新
- **LIVE 報價**：30 秒輪詢近即時（含 bid/ask）；台股指數接 TWSE 即時；指數（加權 / 櫃買 + 美股四大）也能加入自選
- **持倉 POS**：成本 / 市值 / 未實現損益 + 規則化訊號（均線交叉、RSI、KD、MACD、布林、量能、倉位連動、主動 ETF 共振）
- **觀察 WATCH**：8 策略（趨勢 / 動能 / 波動 / 價格）+ 5 個預設劇本，一檔可掛多訊號自動算 Confluence 共識分

### 圖表分析
- **量價**：成交金額 Volume Profile（POC / VAH / VAL 主力成本區，可切金額 / 成交量）
- **多圖**（`Alt+M`）：2×1 / 2×2 / 1×3 分割，每格獨立換商品時框，同步十字游標與時間軸，版面記憶
- **價差**（`Alt+D`）：數學式合成線看相對強弱 / 溢價差（如 `2330/2303`、`^TWII/^SOX`）
- **畫線**（`Alt+T`）：趨勢 / 水平 / 垂直 / 斐波那契 / 矩形 / 平行通道 / 文字，錨點以時間+價格記錄
- **形態³**：19 種型態辨識（經典 + 諧波 XABCD/Cypher + 艾略特五浪/修正 + 循環分析）
- **vs 大盤**、**夜盤連動預警**（美股期貨 → 台股隔日預估）、**Replay** K 線重播

### 選股 / 策略 / 回測
- **三合一選股**：技術 × 基本面 × 籌碼 全台股篩選，一鍵載入或加自選
- **全市場 Screener** + 類股篩選
- **策略組合器**：樂高式條件組合 → 回測，輸出最大回撤 / 勝率 / 獲利因子 / 年化夏普 / 逐筆明細 + 權益曲線
- **腳本**：類 Pine 安全 DSL（自寫直譯器、函式白名單、不用 eval），`buy/sell` 回測、`plot` 疊主圖
- **選股精靈**：回答 4 題（用途 / 週期 / 風險 / 資金）自動體檢個股，一鍵套用 觀察訊號 + 警報 + 持倉/買進計畫 + 支撐壓力畫線 + 研判結論
- **本機時序 DB**：全市場約 2200 檔日線一鍵回補，選股 / 回測 / 投組讀同一份乾淨資料，掃描由分鐘級變**秒級**

### 籌碼 / 基本面
- **估值**：本益比河流（台股 + 美股），判斷現在貴不貴
- **資金流**：大盤量能趨勢 + 三大法人；**法人榜**：外資 / 投信買賣超排行 + 連續買賣超天數
- **供應鏈**：台灣 AI 供應鏈族群連動（晶圓 → 封裝 → CPO → 伺服器 → 散熱）
- **供應鏈輪動**：各段 5/20/60 日動能 + 近 8 週輪動軌跡 + 資金流向圖
- **基本面**：月營收 / 三率 / 評分卡
- **個股期**：市值前十大個股期夜盤領先
- **ETF△ 主動 ETF 每日持股 delta** + 共識報表（投信潛在買盤估算 + AI 原因解讀）
  - **增減碼徽章浮動視窗**：自選股徽章 hover / 點擊即列出是「哪幾檔 ETF」新增 / 移除 / 加減碼，每檔可點直接載入線型
- **計畫 PLAN**：持倉 / 買進計畫 + 歷史

### 投組風險
- 相關性 / 年化波動 / 1日95%VaR / Beta / 投組Beta / 產業曝險 / 供應鏈曝險鏈條圖 / 相關性熱力圖
- 可自訂成分股與權重（持倉市值 / 自選等權 / 手動）

### AI / 工具
- **AI 報告**：Claude 八章節個股研究報告（需設 API Key，只存瀏覽器 localStorage）
- **AI 副駕**：接**本機 LM Studio**（OpenAI 相容、串流），自然語言問盤，自動帶入你的持倉 / 當前個股 / 盤面當 context，只用真實資料不編造
- **焦點掃描**：全台股多訊號掃描，自動找做多 / 做空焦點股
- **指令**：命令面板（`Ctrl+K`）搜尋股票與功能
- **分析結果一鍵寄送**：焦點掃描 / 選股 / 供應鏈輪動 / 投組風險 的結果都可寄到 Telegram / Email 留存
- 工具列一階分類 + 二階下拉、拖拉視窗、PDF 匯入 / 匯出

### 快訊 / 通知
- 桌面 / 頁內 toast；後端 daemon 走 Telegram / Email / Webhook（Discord/Slack/自架），**瀏覽器關著也偵測**
- **複合警示**：多條件 AND/OR（如「RSI < 30 且 收盤 ≤ 布林下軌」）
- **行事曆**：月營收 / 除權息提醒；資料源健檢燈、結算日提醒

### 一致性系統（內建）
- **欄位型別標準**（`fields_v3`）：數值 / 帶入 / 搜尋 / 文字四種角色嚴格分離，全域滾輪防護，數值欄純文字輸入
- **顏色管理單一真理來源**（`colors_v3`）：全 app 紅綠語意統一 — 台股 漲 / 賺 / 買超 / 體質佳 = 紅，美股 漲 = 綠，估值 / 水準型 = 中性琥珀

---

## 快速開始（3 步）

> 需求：Windows 10/11 + Python 3.10+（純 stdlib，**不用 pip**）+ 現代瀏覽器。確認：cmd 打 `python --version`。

1. **解壓縮／clone**到任一資料夾（例 `C:\Users\Sam\AI_Stock\`）。
2. **雙擊 `scripts\go.bat`** — 自動 rebuild、重啟 server、開瀏覽器（port 18432）。
3. 上方輸入框打代號按 **GO**（台股 `2330`；美股先點 `US` 再打 `AAPL`）。

### 每次 AI／Git 更新後（建議固定流程）

```powershell
cd C:\Users\Sam\AI_Stock
scripts\go.bat pull
```

這會：`git pull`（若本機改過 `stock_terminal_v2.html` 會自動 stash）→ `build_v2.py` → 殺掉舊 :18432 → 重啟 server → 開瀏覽器。  
開頁後 **Ctrl+F5**；雙軸卡技術面 tag 應出現 `tech·385`。

| 指令 | 用途 |
|------|------|
| `scripts\go.bat` | 日常啟動（不 pull） |
| `scripts\go.bat pull` | **更新後用這個**（維持目前分支） |
| `scripts\go.bat pull cursor/某分支` | 切分支 + pull + 重建 + 重啟 |
| `scripts\go.bat rebuild` | 只重建＋重啟（不開瀏覽器） |

舊捷徑 `start_terminal_v3.bat` / `rebuild_and_restart.bat` 仍可用，內部已轉呼叫 `go.bat`。

**首次使用**：通知（🔔）需自行填入 Telegram / Email；AI 報告需在右上 `API KEY` 貼上 `sk-ant-…`；AI 副駕需另裝 [LM Studio](https://lmstudio.ai) 並載入模型；資料骨幹首次跑一次 `python server\datastore.py backfill-universe` 回補全市場。

**可選排程**（系統管理員身分跑一次）：`scripts\install_scheduler.bat`（每交易日更新 ETF 持股）、`scripts\install_chip_scheduler.bat`（更新法人籌碼）。

---

## 資料來源

| 用途 | 來源 | 備註 |
|------|------|------|
| K 線 / 報價 | Yahoo Finance v8 chart API | 失敗時 fallback 經 allorigins.win |
| 台股指數即時 | TWSE MIS | 加權 / 櫃買 |
| 主動 ETF 持股 | MoneyDJ Basic0007B | 全部持股頁面 |
| 法人籌碼 | TWSE 三大法人 | 每日快照累積連買賣天數 |

**所有資料抓取與運算都在你本機跑，零雲端、零追蹤。**

---

## License / 致謝

MIT — 自由分享、修改、商用皆可，原作者保留歸功（不強制）。

- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) — 圖表引擎
- [MoneyDJ ETF 基智網](https://www.moneydj.com/etf/) — ETF 持股資料源
- [Yahoo Finance](https://finance.yahoo.com/) — 報價資料源
