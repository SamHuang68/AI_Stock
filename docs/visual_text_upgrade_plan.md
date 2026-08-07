# 文字 → 視覺強化計畫（檢視稿）

> **狀態**：待檢視（尚未實作）  
> **範圍**：Stock Terminal v5.0 前端，把「已有數據、卻只剩純文字／裸數字」的區塊，統一升級成可掃讀的視覺語言。  
> **原則**：不新增大後端依賴；優先 FE-only；台股紅漲綠跌／買超紅賣超綠；缺資料不捏造。  
> **分支**：`cursor/merge-tw-pulse-intel-b5cf`

---

## 1. 目標

| 要做 | 不做 |
|------|------|
| 同一語意（漲跌、買超、分數、廣度、連續天數）全站同一視覺元件 | 重新設計整站配色／殼層 |
| 從「讀數字」變成「一眼判方向＋強度」 | 為視覺而加假數據或假分數 |
| 抽出共用 helper，避免各面板各畫一套 | 引入 chart 套件或重型 UI framework |
| 法人三欄（外資／投信／自營）視覺平行 | 美股面板套用台股紅綠慣例 |

---

## 2. 現有可複用視覺語言（單一真理）

實作時**先抽共用、再套用**，禁止再複製一份 CSS／內聯 bar。

| 模式 | 現況位置 | 用途 |
|------|----------|------|
| 顏色語意 | `src/core/colors_v3.js` → `dir` / `gain` / `quality` / `warn` | 漲跌、買超、體質、警示 |
| 折線 spark | `pulse_v5.js` → `sparkSvg()` | 指數收盤、序列趨勢 |
| 柱狀 spark（含正負） | `hub_v5.js` → `spark()` | 法人合計、廣度淨值 |
| 量能 spark＋參考線 | `marketflow_v3.js` → `sparkline()` | 成交額 vs 8000億／1.2兆 |
| 分數環／進度條 | `pulse_v5.js` → `.pl-gauge` / `.pl-comp` | 0–100 分數、可靠度 |
| 廣度分段條 | `breadth_v5.js` → `.bd-bar` | 上漲／平／下跌 |
| 廣度甜甜圈 | `pulse_v5.js` → `.pl-donut` | 市場結構 |
| 相對強弱條 | `pulse_v5.js` → `.pl-sbar` | 類股、排行幅度 |
| 熱力格 | `heat_v5.js` → `.ht-cell` | 類股漲跌 |
| 狀態 badge | `hub_v5.js` → `.badge` | ok／warn／err |
| 分數 pill | `fundamental_v3.js` → `scoreBadge()` | 體質／風險 |
| 連續天數 chip | `chip_v3.js` streak badges | 連買／連賣 N 日 |
| 機會／風險 tag | `pulse_v5.js` → `.pl-tag` | 自選標籤 |
| 估值水位計 | `valuation_v3.js` → `.val-gauge` | 百分位 |
| 相關熱力 | `book_v5.js` → `heatmap()` | 矩陣 |

### 2.1 建議抽出的共用 FE helper（新檔草案）

路徑建議：`src/ui/viz_v5.js`（或 `src/core/viz_v3.js`），由 `build_v2.py` 掛載。

| Helper | 輸入 | 輸出 |
|--------|------|------|
| `Viz.toneGain(v)` | number／null | class 或 color（包 `Colors.gain`） |
| `Viz.magBar(v, max, opts)` | 有號數值 | 水平幅度條（買超向右紅、賣超向左綠） |
| `Viz.segBar(up, flat, dn)` | 家數 | 紅／灰／綠分段條 |
| `Viz.scoreMeter(0–100)` | score | 細進度條＋quality 色 |
| `Viz.streakChip(n, who)` | 連買正／連賣負 | 與籌碼面同款 pill |
| `Viz.unitShares(n)` / `Viz.unitYi(n)` | 股／元 | 張／萬股／億（沿用既有 fmt） |
| `Viz.limitChip(chgPct)` | 漲跌% | 「漲停」「跌停」chip（約 ±9.5%） |

> 檢視重點：是否同意「先抽 `Viz.*` 再改面板」，而不是在各檔各寫一份 bar HTML。

---

## 3. 台股顯示鐵律（全案適用）

1. **價格／漲跌%**：`Colors.dir(sym)` — 台股紅漲綠跌；美股綠漲紅跌。  
2. **法人／損益／偏多空**：`Colors.gain` — 永遠台股慣例（買超／賺＝紅）。  
3. **單位**：融資融券／借券／當沖／法人榜優先 **張**；籌碼分項用既有 `fmtShares`（萬股）；大盤法人用 **億**。  
4. **法人三欄平行**：外資／投信／自營在 pulse、hub、breadth、afterhours、chip、marketflow、instrank 同一視覺骨架。  
5. **缺資料**：顯示 `—` 或「尚未納入」，不補假 spark／假分數。

---

## 4. 盤點範圍

已掃：`src/ui/*_v5.js`、`src/fundamental/{chip,instrank,marketflow,fundamental,valuation,stockfut,chainmom}*`、`src/core/{pro,market,etf*}*`、`src/chart/{overnight,market_score_bar}*`、`src/ai/focus_v3.js`。

下列以 **P0 → P1 → P2** 分批；勾選表示「檢視後同意納入實作」。

---

## 5. Phase A — 共用元件＋法人視覺統一（建議第一批）

> 影響面最大、數據齊全、與剛完成的「自營商買賣超」同一語意線。

| ☐ | ID | 表面 | 現況（文字） | 升級 | FE/BE |
|---|----|------|--------------|------|-------|
| ☐ | A1 | 抽出 `Viz.*` helper + 最小 CSS | 各檔複製樣式 | 單一模組 | FE |
| ☐ | A2 | `pulse_v5` 法人分歧 | 四個億元數字＋說明句 | 三條 diverging magBar；外資↔自營背離時 callout chip | FE |
| ☐ | A3 | `hub_v5` 法人卡片 | 僅 Yi 大字 | 卡下 20d spark（合計既有；分項若 hist 無 who 則先只合計） | FE（分項序列可選 BE） |
| ☐ | A4 | `hub_v5` 外資買超／賣超表 | 文字張／億 | 幅度條；有 streak 則 `streakChip` | FE |
| ☐ | A5 | `instrank_v3` 法人榜 | 張數＋「連買N」文字 | magBar + streakChip（含自營商分頁） | FE |
| ☐ | A6 | `chip_v3` 三大法人列 | 簽數字 | 外資／投信／自營並排 magBar；合計 tone chip | FE |
| ☐ | A7 | `chip_v3` 融資／融券／券資比 | 張＋% | 雙條對照；券資比分區 meter（既有 10%／30% 門檻） | FE |
| ☐ | A8 | `marketflow_v3` 三大法人卡 | 四個 Yi | 同 A2 視覺＋可選 hist spark | FE |
| ☐ | A9 | `breadth_v5` / `afterhours_v5` 盤後籌碼 | 文字億 | 同法人三欄 magBar + 合計 chip | FE |

**Phase A 完成定義**
- 任一法人數字出現處，方向靠色、強度靠條，連續天數靠 chip。  
- 自營商與外資／投信同列同規格（含法人榜）。  
- 單元／手測：2330 籌碼面、法人榜自營商、總覽法人分歧。

---

## 6. Phase B — 廣度／盤勢／分數（第二批）

| ☐ | ID | 表面 | 現況 | 升級 | FE/BE |
|---|----|------|------|------|-------|
| ☐ | B1 | `pulse` 頂列漲跌家數 | `上/平/下` 純文字 | `segBar` + 多空語氣 chip | FE |
| ☐ | B2 | `pulse` 廣度 % | 百分比＋字 | 對 50% 中線的 progress／半環 | FE |
| ☐ | B3 | `pulse` 動能／風險 mini | `xx/100` | 底下列 `scoreMeter` | FE |
| ☐ | B4 | `pulse` 體質支柱表 | score 數字格 | score 欄改 meter + pill | FE |
| ☐ | B5 | `pulse` / `hub` 脈搏歷史表 | 純數字表 | 上方雙 spark（動能／風險）+ badge；表保留 | FE |
| ☐ | B6 | `breadth` 歷史表 | up/down/flat/lsRatio | lsRatio 或淨家數 spark；列底色熱力 | FE |
| ☐ | B7 | `breadth` 大盤體質卡 | 分數＋摘要 | gauge 或 quality pill | FE |
| ☐ | B8 | `afterhours` 漲跌家數 | 淨 ±N 文字 | 迷你 `segBar` | FE |
| ☐ | B9 | `afterhours` 漲跌排行 | % 文字 | 相對幅度條；≥9.5% 漲停 chip | FE |
| ☐ | B10 | `afterhours` / `stockfut` 個股期領先 | 期%/現%/領先文字 | 領先 diverging bar +「期>現」chip | FE |

---

## 7. Phase C — 表格密集區與輔助面板（第三批）

| ☐ | ID | 表面 | 升級摘要 | FE/BE |
|---|----|------|----------|-------|
| ☐ | C1 | `scan_v5` 結果表 | RSI 熱格（30/70）；連買 chip；YoY 用 `Colors.growth` | FE |
| ☐ | C2 | `hub` 策略訊號／風險監控 | 多空 tag + score meter；事件 severity 色條 | FE |
| ☐ | C3 | `hub` 自選／指數表 | 列上 spark；漲跌格底色 | FE |
| ☐ | C4 | `pulse` 成交額 strip | vs 8000億／1.2兆 參考刻度 | FE |
| ☐ | C5 | `pulse` 漲停／跌幅列表 | 朝漲跌停進度條；熱力底 | FE |
| ☐ | C6 | `pulse` 自選風險表 | 列 spark（有 hist 才畫） | FE |
| ☐ | C7 | `news_v5` 結算／除權息 | 倒數 badge／類型 chip | FE |
| ☐ | C8 | `book_v5` 風險 KPI | VaR／corr／beta 分區 meter | FE |
| ☐ | C9 | `polish_v3` 融資維持率 keystats | 130/140/150/166 水位計 | FE |
| ☐ | C10 | `fundamental_v3` 三率／月營收 | 水準條；有序列才 spark | FE／可選 BE `revenueSeries` |
| ☐ | C11 | `market_v3` 代號庫表 | 漲跌熱格；量相對 bar | FE |
| ☐ | C12 | `market_score_bar_v3` 展開支柱 | 每柱 scoreMeter | FE |

---

## 8. Phase D — 拋光／低流量（可選）

| ☐ | ID | 項目 |
|---|----|------|
| ☐ | D1 | 設定頁歷史庫列數 → 各 dataset count chip |
| ☐ | D2 | 資料源狀態 → 統一 `.badge`／新鮮度點 |
| ☐ | D3 | 供應鏈／鏈動量：stage 熱條、mom 三點 spark |
| ☐ | D4 | 總經／全球卡：有序列才 spark；VIX 過高 warn chip |
| ☐ | D5 | 掃描漏斗文案 → 階梯 chip |

---

## 9. 可能的後端補強（非第一批必要）

僅在 FE 做滿仍不夠時再開：

| 需求 | 用途 | 優先 |
|------|------|------|
| `/pulse/history?kind=institutional` 分 who（foreign/trust/dealer）序列 | hub／marketflow 分卡 spark | 中 |
| 類股成交量進 `/sectors` | heat 格透明度＝熱度 | 低 |
| 月營收歷史序列 | fundamental YoY/MoM spark | 低 |

---

## 10. 明確不做（本計畫）

- 不改 TradingView／主圖 K 線視覺語言（已有 VP／型態／畫線）。  
- 不為「看起來忙」而在首屏堆 stats／pill 叢集（總覽仍守 one-job-per-section）。  
- 不引入 Inter／紫系發光／預設 AI 儀表板皮。  
- 不把文字報告（AI SECTION）強行圖表化——本計畫聚焦**數據面板**。

---

## 11. 實作與驗證節奏（核准後）

1. **A1** 落地 `Viz` + 1～2 個示範面板（建議 A2 + A6）→ 你檢視手感。  
2. 一次做完 **Phase A** 法人線 → commit／push／本機 `go.bat pull`。  
3. **Phase B** 廣度分數線。  
4. **Phase C** 依你勾選的表密集區。  
5. 每批手測：2330 籌碼、法人榜三 who、總覽 pulse、盤後、廣度；桌機＋窄寬。

### 驗收清單（每批）

- [ ] TW 標的漲跌／買超顏色正確（紅漲／紅買）  
- [ ] US 區塊不污染台股色意  
- [ ] null／缺源顯示 `—`，無假條  
- [ ] 自營商與外資／投信同規格  
- [ ] 無障礙：色以外仍有符號／文字（＋/−、連買 N）  
- [ ] `build_v2.py` 後 Ctrl+F5 可見  

---

## 12. 請你檢視時回覆的重點

請直接標註即可（可回覆編號）：

1. **Phase 範圍**：只做 A？A+B？全做？  
2. **共用檔名**：接受 `src/ui/viz_v5.js`？或想併進 `colors_v3.js`？  
3. **法人幅度條**：要「對零軸左右開」還是「一律向右、賣超改綠色」？  
4. **歷史 spark**：第一批要不要上（A3／B5），還是先條／chip？  
5. **表格類（scan／代號庫）**：要進第一波還是留 C？  
6. 上表 ☐ 有要**剔除**或**升成 P0** 的 ID？

---

## 13. 修訂紀錄

| 日期 | 說明 |
|------|------|
| 2026-08-07 | 初稿：全面盤點 + Phase A/B/C/D，待檢視後再實作 |
