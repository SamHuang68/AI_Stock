# v4.0 整合技術設計 — 三件一起做（一個系統，不是三個）

關鍵洞察：**① 資料骨幹、② AI 副駕、③ 投組/結構分析 共用同一條資料脊椎**。
所以不是平行做三個專案，而是「先立脊椎，兩個層長在它上面」。

```
                    ┌──────────────────────────────┐
                    │   本機時序 DB  (data/market.db) │  ← ① 脊椎 (datastore.py, SQLite)
                    │   bars / fundamentals / chips /│
                    │   etf_holdings / news / docs   │
                    └───────────┬──────────┬─────────┘
            讀同一份乾淨資料 ↙              ↘ 讀同一份乾淨資料
        ┌─────────────────────┐     ┌──────────────────────────┐
        │ ③ 投組 / 市場結構層   │     │ ② 本機 AI 副駕            │
        │ 報酬矩陣→相關性/VaR/  │     │ Ollama LLM + RAG(向量庫) │
        │ 產業·供應鏈曝險       │     │ 自然語言問盤 / 主動洞察    │
        └─────────────────────┘     └──────────────────────────┘
                    既有即時抓取(Yahoo) 仍負責「最新報價/盤中」,DB 負責「歷史/分析」
```

---

## ① 脊椎：本機時序 DB（已開工 → `server/datastore.py`）

- **SQLite（純 stdlib、零 pip）** 當預設，符合本專案「不裝套件」哲學;DuckDB 留作之後「全市場欄式分析」的選配加速器。
- 已實作:`bars`（OHLCV）+ `meta`，含 Yahoo 雙端點回補、upsert、查詢、CLI。
- **之後擴充表**（各層需要時再加，不先空建）：
  - `fundamentals`(symbol, period, revenue, eps, margins…) — 投組估值/基本面
  - `chips`(symbol, date, foreign, trust, dealer) — 沿用現有 chip_history,改寫進 DB
  - `news`(id, symbol, ts, source, title, url, text) + `embeddings`(doc_id, vec BLOB) — AI RAG
- **整合點**：`backtest_v3` / `screener3` / `screener` 改成「先讀 DB,缺再抓並寫回」。圖表/LIVE 維持即時抓取。

驗證(現在就能跑)：
```
python server\datastore.py backfill 2330 TW
python server\datastore.py query 2330 5
python server\datastore.py stats
```

---

## ③ 投組 / 市場結構層（脊椎之上，最貼市場派）

- **資料來源**：`get_bars()` 取多檔 → 對齊日期 → 報酬矩陣。
- **產出**：相關性矩陣、Beta(對 ^TWII)、年化波動/VaR、最大回撤、產業與**供應鏈節點曝險**。
- **供應鏈映射**：一張 `supplychain_map`（symbol → 節點:晶圓/封裝/CPO/伺服器/散熱），把持倉/自選投影到你的核心論點上,TSMC/費半變動即看傳導。
- **市場內部結構**：漲跌家數、新高新低、量能結構(8000億→1.2兆)、產業輪動 → 每日結構面板。
- **前端**：新 `src/portfolio/` 模組群 + 工具列新增「投組」分類(用既有 `Toolbar.register`)。

---

## ② 本機 AI 副駕（脊椎之上，最吃 RTX 5080）

- **執行器**：**Ollama**（本機跑開源 LLM,簡單 REST API;非 pip,獨立安裝)。RTX 5080 16GB 跑 7B~14B 量化模型流暢。
- **RAG**：把 `news`/`fundamentals` 文字用本機 embedding 模型向量化存 `embeddings` 表,查詢時檢索最相關片段餵給 LLM → **有出處、可追溯**。
- **介面**：右側新分頁「副駕」+ 命令面板問句。server 新增 `/ai/local` 端點代理 Ollama。
- **兩種模式並存**：本機(即時/免費/隱私) + Claude API(深度)。
- **整合點**：副駕讀 DB(你的持倉/籌碼/量能) + 向量庫,所以它「懂你的部位、講得出理由」。

---

## 技術決策（預設，可改）

| 項目 | 選擇 | 理由 |
|---|---|---|
| 時序 DB | SQLite (stdlib) | 零 pip、符合本專案哲學;DuckDB 選配加速 |
| 本機 LLM | Ollama | 安裝簡單、REST API、社群廣;模型可換 |
| 向量庫 | SQLite + 自存 embedding | 不另起服務,一致用 SQLite |
| 即時 | 之後上 WebSocket | 取代輪詢(列在 4.0-D) |

---

## 落地順序（脊椎先行，兩層並進）

1. **脊椎**(進行中)：`datastore.py` bars 完成 → 擴 `chips`/`fundamentals` 表，改寫 trackers 寫入 DB。
2. **接消費端**：`backtest`/`screener` 改讀 DB(秒級全市場)。← 立刻有感
3. **③ 投組層**：報酬矩陣 → 風險/曝險面板 + 供應鏈映射。
4. **② AI 副駕**：Ollama 接入 → `/ai/local` → RAG 向量庫 → 副駕分頁。
5. **收尾**：WebSocket 即時、Workspace、測試/CI。

每步都可獨立跑、獨立驗證、獨立 commit。我會一塊一塊交付,不會一次丟一坨無法驗的東西。
