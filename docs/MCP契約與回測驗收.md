# MCP 契約與回測可信度

本輪開發基線為 `2c11e873df787d6879fc889f95032ff30eb461c3`（含 #139）。#138 owner 已正式交棒，整合發布基線為 `dcc7f3d9101d39c2db43b284ffeaa912fffe18bd`。技術分數維持 0–100，體檢、事件研究及交易模擬分開。開發使用獨立 worktree，不複製原工作區資料。

## 分階段驗收

1. MCP：七項工具的輸出 schema、結構化結果、舊版協定及文字相容、來源與錯誤語意；離線 fixtures 不呼叫正式後端。
2. 回測：共用純計算引擎、下一可成交日開盤、雙邊費用／滑價、逐日估值／回撤／Sharpe；固定時序切分的樣本外驗證。
3. UI 與整合：可調成本、設定／版本／限制、缺值／錯誤／未平倉；重建 HTML、完整 Python／JavaScript 測試及隔離覆核。
4. 發布：最新基線整合、PR 與 Linux／Windows CI；核對正式 SHA、私有 gateway 與實際 UI，保護 `data/`、`logs/` 與原工作區未提交內容。

## MCP 結果契約 `st-mcp-result/1`

協定 `2025-06-18`、`2025-11-25` 的 `tools/list` 提供 `outputSchema`，`tools/call` 提供符合 schema 的 `structuredContent`。`2024-11-05`、`2025-03-26` 保持單一文字結果。stdio 連線依 initialize 協商，未知版本回傳伺服器支援的最新版。

現有 `content[0].text` 仍是原本的精簡 JSON（傳輸／參數錯誤仍是文字）。新協定在第二段文字附上完整結構化封裝，供能讀文字但不能讀結構化內容的客戶端使用。不要把第二段當成另一份分析。

| 欄位 | 語意 |
| --- | --- |
| `contractVersion` | MCP 封裝版本，並非後端計算版本 |
| `status` | `ok`、批次部分失敗／決策不足的 `partial`、後端明示無資料的 `unavailable`、呼叫失敗的 `error` |
| `data` | 舊文字 JSON 的同一份精簡結果；參數／傳輸錯誤為 null |
| `metadata.source` | 只轉送後端 `dataSource` 或 `source`，缺少為 null |
| `metadata.asOf` | 後端原始 asOf；不以目前時間或 generatedAt 替代。不同工具可能是資料日或決策建構時間，需連同原始品質／證據日期判讀 |
| `metadata.generatedAt` | 後端生成時間，與資料截止日分開 |
| `metadata.freshness` | 後端提供的 staleDays、暫定盤中旗標、dataWarning、dataQuality；不自行推算新鮮度 |
| `metadata.calculationVersion` | 只轉送後端 engine／model 識別字串；沒有就 null，不以契約版號冒充 |
| `metadata.missing` | 本封裝欠缺的中繼資料欄位；空陣列不代表底層所有資料都完整 |
| `metadata.backendMissing` | 後端原始 missing（如有），其餘缺漏仍保留在 dataQuality／原始資料 |
| `metadata.access` | 此次呼叫的傳輸、cache-only 或 backend-may-refresh 能力語意 |
| `error` | 穩定 code、message、retryable；無錯誤為 null。unavailable 也設 MCP isError；partial 保留可用資料 |

`st_stock_health`、`st_stock_evidence`、`st_watchlist_health` 沿用既有後端，預設可能補抓公開日線並更新後端快取；可傳 `cacheOnly: true` 禁止補抓。它們的 `openWorldHint` 為 true，readOnlyHint 表示沒有交易、設定或使用者狀態寫入，並非保證沒有快取更新。其餘四項只讀本機資料／定義。關鍵價位目前後端僅支援 `^TWII`、`^TWOII`、`__TXF__`，schema 與後端一致。

MCP 本身不開 HTTP 服務，不建立憑證，不新增外部來源。`ST_MCP_BASE_URL` 僅允許無憑證／路徑的 loopback HTTP 位址；停用代理及重新導向。未知市場／多餘參數／型別不符在呼叫後端前明確拒絕，不再靜默退回台股。

來源參考：[MCP 工具規格](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)、[Maverick 服務組裝](https://github.com/wshobson/maverick-mcp/blob/main/maverick/server/assembly.py)、[Maverick 回測計算](https://github.com/wshobson/maverick-mcp/blob/main/maverick/backtesting/engine.py)。本輪僅參考邊界分工概念，未複製其程式碼或安裝套件。

## 回測模型 `st-backtest/4.0`

`Backtest.run`、`runLS`、`scanStrategies`、`evaluateStrategies` 共用一個純計算成交核心；不抓取資料、不寫交易。原 `server/signal_stats_pool.py` 的事件研究、同市場基準率與樣本門檻完全獨立，不以交易模擬結果替換。

- 進場與出場訊號在該日收盤才成立，最早下一個具有效開盤、正成交量且非停牌的日線開盤成交。缺開盤／量或停牌保留待執行指令；缺最後成交日不虛構平倉。
- 停利／停損是**收盤報酬門檻**，不是盤中 stop／limit 委託。當日 high/low 同時碰到兩個門檻時不猜先後。收盤檢查順序為停損、停利、持有期滿、出場訊號，下一可成交開盤再加不利滑價。`maxBars=1` 代表進場日收盤判斷期滿，次日開盤離場。
- 每筆使用當時淨權益的一倍名目資金，允許小數股數。進場數量為 `權益 / [成交價 × (1 + 進場費率)]`；買進滑價上加、賣出下減；雙邊費用依各次實際成交金額扣除。放空使用同一套現金／負股數帳本，不含借券供給或費率。權益耗盡後安排下一可成交開盤退出，不再開新倉；不把負權益壓成零掩蓋損失。
- 預設進場費 10 bp、出場費 10 bp、每邊滑價 5 bp（1 bp = 0.01%），是可調情境值，非台美股／ETF 法定費率。應把適用費用納入情境，未另外模擬交易稅、股息、融資與借券。
- 每個已提供日線都產生收盤估值曲線，包括空手日；缺收盤時沿用最近估值並標示 `carried`。缺列不自行補日曆，缺價／量不轉為零。期末保留 `openPosition`，未實現損益計入總報酬與回撤，但不列入已平倉筆數／勝率。未平倉不預扣未發生的出場費。
- MDD 從初始權益 1 與每日收盤權益計算；不是盤中最差回撤。Sharpe 與 sharpeAnn 統一使用每日簡單報酬減每日無風險利率、樣本標準差與 `sqrt(periodsPerYear)`；預設 252 日、年化無風險率 0。無交易／零波動／不足兩個每日報酬時為 null。空手日納入樣本，不用每筆交易數年化。
- 日期在單一 `dateKey` 轉換：秒級 timestamp 依 TW／US 時區轉交易日；ISO 日期視為交易所日期。拒絕亂序、重複日與同日多根，UI 也拒絕已知非日線區間。不沿用 NYSE-only 日曆。

條件組合器與腳本介面可調三種成本，顯示版本、截止日、成交口徑、每日估值、未平倉與資料限制。勝率與 Sharpe 不可定義時顯示「—」。舊儲存條件組缺成本欄位時明示載入預設情境；重新回測才產生新版績效，不混合舊結果。

### 固定樣本外切分

`evaluateStrategies` 必須由呼叫者事先固定 `trainEnd` 與 `testEnd`。只在訓練截止日前的資料上比較八種既有策略、以扣成本後每筆期望值選出有已平倉交易的一個策略，再於測試期使用同一設定與成本。測試期從空手開始，指標可用訓練期暖機，但訓練期訊號／持倉不跨界；截止日後資料不進入評估。訓練期沒有已平倉交易則不選策略。

這是固定 holdout，不是已完成的外部前瞻驗證。人工反覆查看測試結果後改設定仍會污染測試集；沒有多重比較校正、點時財報、已驗證還原價格或完整下市標的，因此不宣稱已消除存活者偏差。條件組合器的「八種既有策略的固定樣本外比較」顯示所選策略與兩個截止日；不把自訂條件誤標為該次比較的候選。

### 可重現測試

`tests/fixtures/backtest_execution.json` 包含台股、台灣 ETF、美股、美國 ETF 的手工日線。`tests/backtest_execution_selftest.js` 用獨立現金／股數預期值驗證跳空、雙邊成本、放空、每日回撤／Sharpe、停牌、缺價／缺量、沒有下一根、收盤停利停損、未平倉、零交易、日期／參數拒絕、指標缺值及測試集不參與選擇。現有 CI 的 JavaScript 自我測試迴圈會自動納入此檔。
