# AI_Stock 專案 Code Review 與修正計畫

> Stock Terminal v4.1 · Housekeeping（功能潮後整理）  
> 基準分支參考：`cursor/margin-mix-yoy-dense-4e66`（含大盤體質／融資週期／TDCC／融資比加密度／分享打包）  
> 產出目的：把「能跑」收斂成「可維護、可回歸、可分享」。

---

## 1. 專案概述

| 項目 | 說明 |
|------|------|
| 語言 / 框架 | 後端 **Python 3.10+ stdlib only**（`ThreadingHTTPServer`）；前端 **Vanilla JS + TradingView Lightweight Charts**；無 React／無 pip 依賴 |
| 架構 | 瀏覽器 ↔ 本機 `server/server.py:18432` ↔ Yahoo／TWSE／TPEx／TDCC／FRED／MoneyDJ |
| 建置 | `build_v2.py` 把 `src/**`（約 63 支 JS）注入 `stock_terminal.html` → `stock_terminal_v2.html` |
| 啟動 | `scripts/go.bat`／`scripts/apply.bat`（Windows 本機） |
| 規模 | `server/` ≈ **12.9k** LOC；`src/` ≈ **21.7k** LOC；單檔最大：`server.py` **~5.6k**、`market_chart_v3.js` **~1.8k** |
| 核心功能 | 台／美股看盤、技術指標、觀察／持倉、選股回測、ETFΔ、籌碼／基本面、大盤 Macro 追蹤圖、市場風險評分、融資週期、TDCC 集中度、本機 AI／Claude 報告、推播警示 |
| 鐵律（`.cursorrules`） | RSI／SMA 計算必須精準；前後端欄位必須對齊；拒絕半成品 |

---

## 2. 結構與模組分析

| 模組 | 功能說明 | 潛在結構脆弱點 |
|------|----------|----------------|
| `server/server.py` | 幾乎所有 HTTP 路由、Yahoo proxy、AI、batch 報價、靜態檔 | **God-file**；改一處易誤傷；難做針對性測試 |
| `server/macro_track.py` | `__TW_RATES__`／`__TW_MARGIN_MIX__`／美總經多序列圖 | `/yf/` 相容路徑 vs `/macro/chart` 雙軌；主序列選錯會顯示加權價 |
| `server/margin_cycle.py` + `margin_ratio.py` | 融資維持率、融資週期評分 | 與 `macro_track` 命名相近（MIX vs CYCLE vs RATIO）易混淆 |
| `server/tdcc_holders.py` | 集保分散 → `__HOLDERS_<code>__` | 大 DB 已進 git（`tdcc_holders.db`）；與 gitignore 的 `market.db` 策略不一致 |
| `server/market_risk.py` | 大盤體質／市場風險支柱分數 | 前端 score bar 契約若漂移，UI 空白或錯色 |
| `server/datastore.py` | 全市場日線 SQLite | 首次回補成本高；與即時 Yahoo 路徑並存 |
| `server/alert_daemon.py` / `watch_daemon.py` | 背景警示／觀察 | 設定檔與瀏覽器 localStorage 雙來源，易不同步 |
| `src/chart/market_chart_v3.js` | Macro／維持率／集中度主圖 | 風格包、`_defaultOff`、rebase、風險線交織；回歸成本高 |
| `src/chart/market_score_bar_v3.js` | 體質分數列 | 依賴後端 `risk`／`summary` 欄位完整 |
| `src/ui/polish_v3.js` | 大盤／市場 tab、格上報價 | 格上數值選錯 series（已見融資比→TWII） |
| `src/core/fields_v3.js` + `docs/FIELDS.md` | 欄位型別契約 | 新 STATS／macro 欄位未登記會破一致性 |
| `src/screener/strategy_script_v3.js` | 類 Pine DSL | 刻意不用 `eval`；白名單需持續守門 |
| `build_v2.py` / `build_order.py` | 模組注入順序 | `build_order._CURRENT` 與實際 `V2_SCRIPTS` **不同步** |
| `scripts/apply.bat` / `go.bat` | 本機套用／啟動 | checkout 覆寫執行中 bat（已用 `--continue` 緩解） |
| `scripts/build_dist.py` | 分享包剝密 | 需與 `.gitignore`／README 私人檔清單保持一致 |
| `data/*` | seed CSV／DB／universe | regenerable DB 有的追蹤、有的忽略；zip／clone 體積與衝突 |

---

## 3. 邏輯判斷與錯誤處理檢視

### 已觀察到的漏洞／漂移

1. **雙軌圖表契約**  
   主路徑 `/macro/chart/<id>`；相容 `/yf/__XXX__` 只帶「主序列」。主序列選錯（右軸指數）→ 格上出現 `43654` 類錯誤（融資比已修，其他圖仍需統一 prefer-key）。

2. **稀疏時間序列 + YoY**  
   抽樣過稀時 YoY 對齊失敗 → 線段斷裂（融資比已加密度／±45 天；同類模式若出現在他處需複用）。

3. **靜默吞錯**  
   後端大量 `except Exception` + `print`；前端大量空 `catch {}`。失敗時 UI 顯示 `--`／舊快取，使用者以為「沒資料」。

4. **文件漂移**  
   README／註解仍提 allorigins 等備援，程式路徑可能已移除 → 除錯指引失效。

5. **Daemon vs 瀏覽器狀態**  
   觀察股：`localStorage` vs `watch_rules.json`；警報：`alert_config.json`。分享包已剝除後端檔，但本機雙寫仍可能不一致。

6. **建置清單過期**  
   `build_order.py` 自測清單缺 `market_chart`／`fields`／`copilot` 等 → 假綠燈。

### 建議修正／重構策略

| 優先 | 作法 |
|------|------|
| P0 | 為每個 macro／特殊圖定義 **唯一 primaryKey**（後端＋`polish` 共用表）；禁止 fallback 到 `scale==='right'` |
| P0 | 關鍵路徑改 `logging`（檔案 + 等級），保留 UI 可讀的 `note`／`error` 欄位 |
| P1 | 抽出 `server/routes/` 或至少 `macro_api.py`／`quote_api.py`，瘦身 `server.py` |
| P1 | 單一「圖表註冊表」：id、series、primaryKey、endpoint、FE stylePack（避免三處手寫） |
| P2 | `docs/FIELDS.md` 與 macro score payload 加「契約測試」 |
| P2 | Daemon 與前端同步策略寫死：以誰為準、何時 upload |

---

## 4. 效能與資源管理

### 瓶頸

| 點 | 說明 |
|----|------|
| 同步 HTTP 回補 | 融資比／TDCC／FRED／MoneyDJ 在 request 或背景 thread 內 sleep 輪詢；長回補占鎖 |
| Yahoo batch | 自選／大盤列頻繁 `/yf/batch`；LRU 無 TTL 時易吃到過期 K |
| `market.db` 全市場掃描 | Screener／三合一選股 CPU＋磁碟；未做增量標記易重算 |
| 前端單頁巨石 | 63 支腳本全載；無 code-split（可接受於本機工具，但首屏解析重） |
| 大檔進 repo | `universe.json`、`tdcc_holders.db` 拉長 clone／PR diff |

### 優化建議

- **回補**：統一 job queue（單 worker）+ 進度 API（已有雛形 `_REFRESH_LOCK`）；避免重複 autodense。
- **快取**：Yahoo／MIS 加短 TTL；macro seed 優先、live 失敗不擋圖（FRED fail-fast 方向已有）。
- **批次**：TWSE MIS／T86 已部分 batch；檢查 chip／ETF 是否仍 N+1。
- **資料**：`tdcc_holders.db`／`margin_cycle.db` 改「seed 小檔 + 首次下載」或 LFS；與 `market.db` 策略對齊。
- **前端**：Macro 圖懶載；非首屏 toolbar 模組可延後（可選，非必須）。

---

## 5. 測試覆蓋與 CI/CD 建議

### 現況

- 僅 `tests/test_margin_ratio.py`、`tests/parse_selftest.js`（手動）、`/selftest` 端點
- **無** `.github/workflows`、無 ruff／eslint／pre-commit

### 應補的測試（依鐵律排序）

| 類型 | 項目 |
|------|------|
| 單元 | RSI／SMA／KD／MACD 黃金向量（固定 fixture，禁止「看起來像」） |
| 單元 | `margin_mix` YoY 對齊窗、primaryKey 選擇（不可回傳 TWII） |
| 單元 | `market_risk` 支柱分數邊界（缺序列 → 明確 null，非 0 假分數） |
| 契約 | `/macro/chart/__TW_*__` JSON schema：series.key／scale／unit |
| 契約 | Score bar payload vs `market_score_bar_v3.js` 欄位 |
| 整合 | `build_v2.py` 後 `stock_terminal_v2.html` 含全部 `V2_SCRIPTS` |
| 安全 | `build_dist.py` zip 不得含 `ai_key`／`watch_*`／`alert_*` |
| 煙霧 | `/health`、`/selftest`、靜態 deny list |

### CI 工作流範例（GitHub Actions）

```yaml
# .github/workflows/ci.yml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: Unit tests
        run: python -m unittest discover -s tests -v
      - name: Build v2
        run: python build_v2.py
      - name: Dist scrub check
        run: |
          python scripts/build_dist.py --out /tmp/st.zip
          python -c "import zipfile; z=zipfile.ZipFile('/tmp/st.zip');
          bad=[n for n in z.namelist() if any(x in n.lower() for x in
          ['ai_key','watch_rules','alert_config','draw_store','revision.md'])];
          assert not bad, bad"
```

（可再加：Ruff 只對 `server/` 新檔；不強制前端 eslint 以免一次爆炸。）

---

## 6. 安全性檢查

| 風險 | 現況 | 建議 |
|------|------|------|
| API Key | 已遷 `data/ai_key.txt` + `/ai-key`；分享包剝除 | 維持；禁止再寫回 localStorage |
| Telegram／SMTP | `alert_config.json` gitignore | UI 遮罩已設；log 禁止印 token |
| CORS `*` | 本機工具假設 | 文件標明「勿把 18432 暴露公網」；可選綁 `127.0.0.1` only |
| CSRF／Origin | POST 有 `_origin_ok`；OPTIONS 較寬 | 對寫入 API 一律校 Origin |
| 靜態外洩 | 已 deny `.py`／`ai_key`／`alert_config` | 定期對照 deny list vs 新敏感檔名 |
| DSL | 策略腳本無 `eval` | 保持白名單；新增函式要審 |
| 供應鏈 | 無 npm；CDN Lightweight Charts | 鎖定版本／SRI（可選） |

---

## 7. 修正計畫（技術階段 · 不依日曆週）

> 依依賴與風險排序；每一階段應有可合併的 PR，避免再堆「超大功能分支」。

| 階段 | 工作項目 | 預期產出 |
|------|----------|----------|
| **H0 · 止血** | primaryKey 表統一；macro 格上報價回歸測試；文件去掉過時備援敘述 | 不再出現「指數價當 YoY」類 bug |
| **H1 · 可回歸** | RSI／SMA fixture 測試；`build_v2`／`build_dist` scrub CI；修 `build_order._CURRENT` | PR 必跑綠燈 |
| **H2 · 結構** | 從 `server.py` 拆 `macro_api`／`quote_api`（或同目錄模組 + 薄路由）；圖表註冊表單源 | `server.py` 行數明顯下降、改 macro 不碰 AI 路由 |
| **H3 · 資料治理** | regenerable DB／大 JSON 的 git 策略統一；seed vs runtime 文件化 | clone／分享包體積可控、少衝突 |
| **H4 · 觀測性** | `logging` + 前端可顯示的 `source`／`note`；回補進度單一 API | 資料不齊時「知道為什麼」 |
| **H5 · 效能** | 回補 queue、Yahoo TTL、screener 增量 | 長回補不卡 UI；掃描可預期 |

建議 **一次只推進一個階段的 1～2 個 PR**；新功能分支必須能快轉合併進「已 housekeeping 的 tip」，避免再分叉 10 條平行 feature。

---

## 8. 待確認事項 — **已拍板（2026-07-28）**

| 問題 | 決定 |
|------|------|
| 優先 H0→H1→H2？ | **是**（本分支實作中） |
| 大 DB 進 git？ | **否** — 改首次開啟回補；`tdcc_holders.db`／`margin_cycle.db` gitignore |
| server 只聽 127.0.0.1？ | **是** |
| housekeeping 暫緩新指標？ | **是** |

---

## 9. 本輪實作勾選

- [x] H0 chart_registry 單源 + 回歸測試（禁右軸 fallback）
- [x] H0 bind `127.0.0.1`
- [x] H0/H3 大 DB 移出 git／分享包
- [x] H1 indicators.py + RSI/SMA fixture 測試
- [x] H1 build_order 對齊 V2_SCRIPTS；GitHub Actions CI
- [x] H1 build_dist scrub 測試
- [x] H2 抽出 `macro_api.py`／`indicators.py`（server.py 仍厚，後續可續拆）
- [ ] H2 續：quote_api／更薄路由（下一 PR）
- [ ] H4/H5 觀測性與效能（下一波）

---

*本文件為 housekeeping 活文件；完成一階段就在此勾選並開下一 PR。*
