# Stock Terminal v4.1

Bloomberg 風格的個股研究終端機。**本機跑、零雲端、零追蹤、不需 pip 安裝任何套件**（純 Python stdlib）。
架構為「瀏覽器前端 ↔ 本機 `server.py` ↔ 外部資料源（Yahoo / MoneyDJ / TWSE / TDCC / FRED）」三層；前端模組依功能分資料夾，新增功能用 `Toolbar.register({...})` 一行掛上。

> **分享版說明**：本發行包已剝除 API Key、觀察股清單、警報設定、畫線雲端記憶等私人檔。收件者需自行在右上角貼 Claude Key、在 🔔 設定 Telegram／Email，觀察股留在本機瀏覽器 `localStorage`。

---

## 功能總覽

### 核心看盤
- 即時 Yahoo K 線，11 個時間段（1 天 ～ 全部）；台股 + 美股切換
- 16 項技術指標：RSI / KD / MACD / SMA / BB / ATR / 年化波動% / MaxDD% / 量比 / 乖離 / ETF Flow…
- 自選股清單（雙列、拖曳排序）+ 本地 LRU 快取 + 多執行緒併發抓取
- **代號庫**（🗂）：全台股(含 ETF / 上櫃) + 美股 lookup；市場判定一律由代號決定
- **資料源管理**（🗄）：提供者、可靠度、最後更新、筆數；每源可一鍵重抓
- **LIVE 報價**：30 秒輪詢（含 bid/ask）；台股指數接 TWSE 即時
- **持倉 POS**：成本 / 市值 / 未實現損益 + 規則化訊號
- **觀察 WATCH**：8 策略 + 5 個預設劇本，一檔可掛多訊號算 Confluence（資料只存你本機瀏覽器）

### 圖表分析
- **量價**：成交金額 Volume Profile（POC / VAH / VAL）
- **多圖**（`Alt+M`）：2×1 / 2×2 / 1×3 分割，同步十字游標
- **價差**（`Alt+D`）：數學式合成線（如 `2330/2303`、`^TWII/^SOX`）
- **畫線**（`Alt+T`）：趨勢 / 水平 / 斐波那契 / 矩形 / 平行通道 / 文字
- **形態³**：19 種型態辨識；**vs 大盤**、**夜盤連動預警**、**Replay**

### 大盤 / 市場體質（主圖）
底部切換 **大盤** / **市場** 分頁，主圖上方有體質分數列（可展開支柱、`?` 看演算法）：

| 圖表代號 | 說明 |
|---------|------|
| `__TW_RATES__` | 台股利率／央行政策 |
| `__TW_MARGIN_MIX__` | 融資比 YoY（上櫃÷上市融資張數年增；樣本過稀會自動雙週回補） |
| `__TW_MARGIN_CYCLE__` | **融資週期**：維持率 vs 加權，風險線 166／150／140／130 |
| `__US_RATES_CREDIT__` | 美債利率＋信用利差（預設 rebase 同基） |
| `__US_CPI_FIN__` | CPI／金融股相對強弱 |
| `__HOLDERS_2330__` | **籌碼集中度**（TDCC 集保；搜尋 `集中2330`） |

- **大盤體質**／**市場風險**：利率、信用、通膨、融資週期、集中度等支柱連續分數
- 美股多軌圖可切 **絕對價**／**rebase＝100** 同基比較

### 選股 / 策略 / 回測
- **三合一選股**：技術 × 基本面 × 籌碼；全市場 Screener + 類股篩選
- **策略組合器**／**腳本**（類 Pine DSL）／**選股精靈**
- **本機時序 DB**：全市場約 2200 檔日線一鍵回補，掃描秒級

### 籌碼 / 基本面
- 本益比河流、資金流、法人榜、供應鏈／輪動、月營收／三率
- **ETF△ 主動 ETF 每日持股 delta** + 共識報表
- **TDCC 集保大股東集中度**（≥400 張層級彙總，官方 opendata）
- **計畫 PLAN**：持倉／買進計畫 + 歷史

### 投組風險
- 相關性／年化波動／VaR／Beta／產業曝險／熱力圖

### AI / 工具
- **AI 報告**：Claude 八章節（Key 只存瀏覽器 localStorage，**不會進分享包**）
- **AI 副駕**：本機 [LM Studio](https://lmstudio.ai)
- 焦點掃描、指令面板（`Ctrl+K`）、結果一鍵寄 Telegram／Email

### 快訊 / 通知
- 桌面 toast；後端 daemon 走 Telegram／Email／Webhook（**設定檔不進分享包**）
- 複合警示、行事曆、資料源健檢

### 一致性系統
- `fields_v3` 欄位型別標準；`colors_v3` 台股紅漲／美股綠漲語意統一

---

## 快速開始（3 步）

> 需求：Windows 10/11 + Python 3.10+（純 stdlib，**不用 pip**）+ 現代瀏覽器。確認：`python --version`。

1. **解壓縮**到任一資料夾（例 `C:\Tools\Stock_Terminal\`）。
2. **雙擊 `scripts\go.bat`** — 自動 rebuild、重啟 server（**只聽 127.0.0.1:18432**）、開瀏覽器。
3. 上方輸入框打代號按 **GO**（台股 `2330`；美股先點 `US` 再打 `AAPL`）。

> **首次開啟**「融資週期」「籌碼集中度」等圖時，會背景回補歷史（不再隨 git 附大 DB）。可在資料源面板看進度。

### 每次 Git 更新後

```powershell
cd C:\Tools\Stock_Terminal
scripts\go.bat pull
```

這會：`git pull`（若本機改過 `stock_terminal_v2.html` 會自動 stash）→ `build_v2.py` → 殺掉舊 :18432 → 重啟 → 開瀏覽器。開頁後 **Ctrl+F5**。

| 指令 | 用途 |
|------|------|
| `scripts\go.bat` | 日常啟動（不 pull） |
| `scripts\go.bat pull` | 更新後用（維持目前分支） |
| `scripts\go.bat pull cursor/某分支` | 切分支 + pull + 重建 + 重啟 |
| `scripts\go.bat rebuild` | 只重建＋重啟（不開瀏覽器） |
| `scripts\apply.bat <分支名>` | 一鍵套用指定功能分支 |

舊捷徑 `start_terminal_v3.bat` / `rebuild_and_restart.bat` 仍可用。

### 首次設定（私人資訊自行填）

1. **通知 🔔**：自行填 Telegram Bot Token／Chat ID 或 Email（寫入本機 `data/alert_config.json`，勿分享）。
2. **AI 報告**：右上 `API KEY` 貼上 `sk-ant-…`（只存瀏覽器；後端亦可放 `data/ai_key.txt`，**勿提交／勿打包**）。
3. **AI 副駕**：另裝 LM Studio 並載入模型。
4. **資料骨幹**（可選）：`python server\datastore.py backfill-universe` 回補全市場日線。

**可選排程**（系統管理員跑一次）：`scripts\install_scheduler.bat`（ETF）、`scripts\install_chip_scheduler.bat`（法人籌碼）。

---

## 打包可分享版（維護者）

剝除觀察股、API Key、警報設定等私人檔後產出 zip：

```powershell
python scripts\build_dist.py
REM 或雙擊 scripts\build_dist.bat（Windows）
```

產出根目錄 **`Stock_Terminal_v4.1.zip`**。收件者解壓後雙擊 `scripts\go.bat` 即可。

**發行包刻意排除：**

| 類型 | 檔案／目錄 |
|------|------------|
| API Key | `data/ai_key.txt`、`.env*` |
| 警報／推播 | `data/alert_config.json`、`alert_rules.json` |
| 觀察股（後端） | `data/watch_rules.json`、`watch_state.json` |
| 畫線記憶 | `data/draw_store.json` |
| 個人籌碼快照 | `data/chip_history/*.json` |
| 內部修訂筆記 | `docs/revision.md` |
| 建置殘渣 | `__pycache__`、`.git`、既有 zip |

觀察股若曾存在於**瀏覽器** `localStorage`（`stock_terminal_watches_v2`），與 zip 無關；換電腦／無痕視窗即為空清單。

---

## 資料來源

| 用途 | 來源 | 備註 |
|------|------|------|
| K 線／報價 | Yahoo Finance v8 chart API | query1／query2 備援；台股指數另走 TWSE／FinMind |
| 台股指數即時 | TWSE MIS | 加權／櫃買 |
| 主動 ETF 持股 | MoneyDJ Basic0007B | 全部持股頁 |
| 法人籌碼 | TWSE 三大法人 | 每日快照 |
| 融資維持率／餘額 | TWSE／TPEx 公開資訊 | 融資週期圖 |
| 集保持股分級 | TDCC opendata | 籌碼集中度 |
| 美債／信用／CPI | FRED 等公開序列 | 市場風險圖 |

**所有資料抓取與運算都在你本機跑，零雲端、零追蹤。**

---

## License / 致謝

MIT — 自由分享、修改、商用皆可，原作者保留歸功（不強制）。

- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) — 圖表引擎
- [MoneyDJ ETF 基智網](https://www.moneydj.com/etf/) — ETF 持股資料源
- [Yahoo Finance](https://finance.yahoo.com/) — 報價資料源
- [臺灣集中保管結算所 TDCC](https://www.tdcc.com.tw/) — 集保持股分級
- [FRED](https://fred.stlouisfed.org/) — 美國總經序列
