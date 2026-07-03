# Revision History（內部文件 — 不對外分享）

> 各版本「改了什麼 / 修了什麼」的詳細紀錄,內部追蹤用。
> 對外分享的功能介紹在 `README.md`;本檔由 `scripts/build_dist.bat` 排除,不進分享包。

---

## v4.1 — 體驗打磨 / 欄位標準 / 顏色管理

**指標統一 / 回測費稅（precision pass）**
- **統一指標庫（SSOT）**：新增 `src/core/indicators_v3.js`（前端）+ `server/indicators.py`（後端）,兩份演算法完全對齊（SMA/EMA/RSI/KD/MACD/BB/ATR）。所有引用端改接統一庫:指標列 Web Worker（經 `INDICATORS_LIB_SRC` 原始碼串進 blob,與主執行緒共用同一份程式）、主圖 SMA/BB overlay、`StratLib`、`window.Backtest`、`pro_v2 mockInd`、`wizard ATR`;後端 `server.py _calc_ind`、`watch_daemon`、`alert_daemon`。
- **修正（root cause）指標數學**:
  - 指標列 **KD 完全壞掉**:舊 worker 把 prevK/prevD 直接設成當根 RSV → K=D=RSV,毫無平滑。改為台股慣例 9,3,3 自序列起點逐根迭代（種子 50）。
  - **RSI 分裂**:顯示/後端用 14 根簡單平均（Cutler）,回測/StratLib 用 Wilder → 同一檔面板與回測訊號對不上。全面統一為 **Wilder 平滑**（TradingView/TA-Lib 標準）。
  - `pro_v2 mockInd` RSI bug:全漲無跌時 rs 被設 100 → RSI 算出 ≈0.99 而非 100。
  - **ATR14**:TR 簡單平均 → **Wilder 平滑**（wizard 停損自適應同步修正）。
  - **MACD**:worker EMA 無種子/無暖身、StratLib signal 以 0 充填暖身期 → EMA 改 SMA 種子,signal 只對有效 line 段計算,暖身期一律 null。
- **回測精準化（`backtest_v3.js` run/runLS）**:
  - 進場改「訊號**次一根開盤**」（原同根收盤進場 = 前視偏差,績效高估）;出場訊號亦成交於次根開盤;TP/SL/時間出場維持 EOD 收盤判斷（不模擬盤中觸價,已標注）。
  - **台股費稅模型**:手續費 0.1425%（買賣各一,可設折扣）+ 證交稅 0.3%（賣出）,`opts.market/cost` 可覆寫,美股預設零費稅。`ret`=淨報酬、`retGross`=毛報酬,summary 新增 `totalReturnGross`/`cost`;回測引擎/策略組合器/腳本 UI 皆顯示「淨 vs 毛」與成本假設。
- **對齊 selftest**:`tests/indicators_selftest.js`（node）與 `python server/indicators.py` 共用同一組 Lehmer LCG fixture + 凍結期望值（容差 1e-9）,JS/Python 任何一邊分岔立刻紅燈;已併入 server `/selftest`。另新增 `tests/backtest_selftest.js` 驗證次根開盤進場/費稅計算。
- **效能（GMKtec EVO-T1 96GB/16T,規格記憶於 .cursorrules）**:`MAX_WORKERS` ≥ CPU×4（min 64）、LRU 快取 20000→50000、`request_queue_size` 64→256、SQLite `cache_size` 256MB + `mmap_size` 1GB + `temp_store=MEMORY`。

**新功能**
- 分析結果一鍵寄送 Telegram/Email（`src/ui/share_v3.js`）：掛到 焦點掃描 / 條件選股 / 供應鏈輪動 / 投組風險。`ShareResult.buttonHTML / wire / send`,沿用後端 `/notify`。
- ETF 增減碼徽章浮動視窗（`src/core/etf_flow_tip_v3.js`）：自選股徽章 hover/點擊列出哪幾檔 ETF 新增/移除/加減碼,每檔可點載入線型。純事件委派,讀裸 S。
- 欄位型別標準（`src/core/fields_v3.js` + `docs/FIELDS.md`）：數值/帶入/搜尋/文字四角色分離;全域滾輪防護(擋 type=number 滾輪改值);`Field.editing/renderGuarded`。
- 顏色管理單一真理來源（`src/core/colors_v3.js`）：`dir`(個股漲跌依市場)、`gain`(賺/買超/偏多=紅,永遠台股)、`quality`(體質/勝率好=紅)、`warn`(估值琥珀/中性)、`dirRU`(總體列)、`candle`、`state`、`isTW`。
- 代號庫升級成「台股清單 + 每股四大指標」（`server/universe.py` + `src/core/market_v3.js`）:universe.json 新增 `twmeta{code:{zh,en,board,pe,pb,yield,eps,gross,op,net,close,chg,vol,mktcap}}`。三組指標—量價(收盤/漲跌%/量)、估值(本益比/股價淨值比/殖利率/EPS)、獲利三率(毛/營/淨)—全抓官方 OpenAPI(TWSE STOCK_DAY_ALL·BWIBBU_ALL·t187ap06_L_ci·t187ap03_L;TPEx 對應上櫃),中英名對照(t187ap03 英文簡稱),市值=收盤×發行股數。前端「🗂 代號庫」改成可搜尋表(代號/中文/英文/四大指標,點代號載入),一鍵更新同時重抓名稱+指標+收錄新上市櫃。抽取一律中英雙語子字串比對+排除子項、配對到才填否則 null(優雅降級)。

**修正（root cause）**
- POS「進場價」輸入跳出搜尋框 / 焦點約 3 秒消失：真凶是 `wl_live_v3.js` 的 pollOnce 每數秒直接 `innerHTML=renderPosition()` 重建面板(繞過守門)。四條重繪路徑收斂到單一守門入口 `renderPositionPanel`/`renderWatchPanel`,編輯中跳過重繪。WATCH 同款修。
- 移除全域「打字即搜尋」熱鍵：會與數值欄位搶鍵;搜尋只留 `/` 與代號框。
- 欄位純資料輸入：數值欄 `type=number`→`type=text + inputmode`(消除滾輪偷改值、微調鈕、Enter→送出)。
- 頂部漲跌%顏色:改在 `polish_v3` 直接依當前個股市場上色;指數/個股一律依「標的本身市場」(`_isTwSym`/`Colors`),修「載過美股後台股顯綠」「^TWII 套美股慣例」。
- 美股盤中 X 軸收盤時間:`renderChart` 用 `America/New_York` 自動判 EDT(-4)/EST(-5),16:00 ET→台灣夏令 04:00/冬令 05:00(DST 自動)。
- LIVE 報價:台股跌顯綠(原誤紅,走 `Colors.dir`);台股指數改抓 TWSE `/twindex`,與底部總體列同源、數字一致(原 Yahoo 1m 延遲打架)。
- 底部總體列 / 自選股 chip:改「每檔依自身市場」(美股漲綠、台股漲紅);chip 用 inline `!important` 蓋過全域 market class CSS。
- ^TWII 早盤 Yahoo 日線落後一日:偵測到落後時用 TWSE 即時校正頂部現價/漲跌%/昨收(`patchTwIndexHeader`)。
- 殖利率:`server.py` 改用「每股配息÷價格」無歧義計算 + 合理上限(>40% 視為異常),修「真實<1% 殖利率被 `dy<1 就×100` 縮放成 59% 還上綠」。
- 籌碼面「無資料」修正:`_handle_chip` 原本只抓「當日」TWSE T86/融資券/借券/當沖,週末或盤前 17:30 前一律無資料 → 連上市權值股(2330)都顯示「無籌碼」。改為**往回找最近一個有 T86 資料的交易日**(最多 8 天)再抓全部。另:上櫃股 TWSE T86 查不到,新增 **TPEx 三大法人**(`tpex_3insti_daily_trading`)→ 修 3529 等上櫃股無籌碼。**根因續修(6683)**:該 OpenAPI JSON 的 key 實為英文 PascalCase(用中文 '外資'/'三大法人' 比對全 null;若為中文則 '三大法人' 唯一欄會配中→證實英文)。改成中英雙語子字串比對 + 鎖定「淨買賣超(買賣超/BuySell/Net)」欄位、排除子項(不含/自營自行/避險/外資自營商),並暫附 `_chipKeys` 供重啟後同源核對真實欄名。基本面(月營收/三率)實為暫時性 null,非缺陷。
- ETF 完整報表 email 變原始 JSON 修正:`etf_report`(需 pandas/matplotlib,打包排除/dev 未裝)為 None 時,`_etf_report_email` fallback 直接 `json.dumps(delta)` 寄原始 JSON。新增純 stdlib `server/etf_report_lite.py`(彙總邏輯同畫面、台股紅綠 HTML + 純文字);`_etf_report_email` 改「rich 可用就用,否則走 lite,絕不寄原始 JSON」;`--hidden-import etf_report_lite`。
- 資料源集中管理 + 一鍵更新:新增 `server/datasources.py`(registry:每源標 提供者/可靠度 official·vendor·local /更新類型 file·db·daily·live /最後更新/筆數)、`/datasources` GET 與 `/datasource/refresh` POST(universe 同步重抓;日線DB/ETF持股/法人籌碼 背景 spawn tracker)。前端 `src/ui/datasources_v3.js` 工具列「🗄 資料源」面板:全來源一表,可逐項或全部一鍵更新。涵蓋:代號庫、本機日線庫、主動 ETF 持股、法人籌碼、ETF 目錄、估值/月營收/名稱/產業(每日自動)、即時報價/指數/台指期(免更新)。
- 代號庫(universe lookup)+ 權威市場判定:新增 `server/universe.py`(TW 上市股+ETF+上櫃 / US NASDAQ Trader directory → `data/universe.json`)、`/universe` GET 與 `/universe/refresh` POST;前端 `src/core/market_v3.js` 的 `Market.of/name/refresh`(權威表優先、代號格式兜底,永不失敗且對未收錄新上市也正確);工具列「🗂 代號庫」可看數量/最後更新/一鍵更新。`loadSym`(base+v2)與估值彈窗一律 `Market.of`/依代號判市場,不靠 TW/US 鈕。
- 估值彈窗市場標籤:原本吃 server 回的 `v.market`(會把 00631L 標美股),改成依代號判定(`Colors.isTW`/`Market`)。
- 市場誤判根治:`loadSym` 原本直接吃 TW/US 市場鈕、不看代號 → 在 US 鈕載入台股代號(如 00631L)會被當美股,`S.mkt='US'`,用無 `.TW` 的代號抓 Yahoo **抓到錯標的**(實測 00631L 載成台積電),估值面板也標「美股」。修:`loadSym` 開頭加「數字開頭或 `^TW` → 強制 `mkt='TW'`」,`setMktUI` 同步市場鈕。
- 顏色語意全面統一台股慣例:P&L 賺=紅/賠=綠、法人買賣超 買=紅、型態多空 偏多=紅、ETF 加碼/新增/買盤=紅、體質評分/勝率 好=紅;水準型(P/E/三率/殖利率)中性琥珀,不用紅綠避免與股價打架。

---

## v4.0 — 本機資料骨幹 + 投組 + AI 副駕
- 本機時序 DB（`server/datastore.py`,SQLite,純 stdlib）:全市場約 2200 檔日線一鍵回補(限流退避 + resume)。選股/回測/投組讀同一份。
- 選股讀 DB(分鐘級→秒級);回測讀 DB(`/bars` 深度 5 年)。
- 投組風險面板（`src/portfolio`）:相關性/年化波動/1日95%VaR/Beta/投組Beta/產業曝險/供應鏈曝險鏈條圖/相關性熱力圖;可自訂成分股與權重。
- AI 副駕（`src/ai/copilot` + `server/ai_local.py`）:接本機 LM Studio(OpenAI 相容、SSE 串流);自動帶入持倉/個股/盤面 context,只用真實資料。
- 供應鏈輪動（`src/fundamental/chainmom`）:各段 5/20/60 日動能 + 近 8 週輪動軌跡 + 流向圖。

---

## 歷史摘要
- **v3.9** 多圖 / 全鍵盤 / 視覺化回測 / 畫線 / 三合一選股 / 複合警示;模組化重構(工具列分類下拉、`src/` 依功能分區、載入順序自動排序)。
- **v3.8** 四主軸(籌碼/基本面/回測/警報)+ 成交金額 Volume Profile + 後端推播 daemon。
- **v3.5–3.7** Yahoo 日線落後修正、build 根因修正 + LRU TTL、全球型 ETF 持股完整抓取。
- **v3.0** 19 種型態辨識(經典/諧波/艾略特/循環)。
- **v2.0** 倉位管理(POS)+ 多訊號觀察(WATCH)+ 共識評分 + (i) 中文說明。
