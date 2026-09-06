# 自選股盤後敘事日報（postmarket-daily）v1

收盤後（手動觸發）對自選／觀察清單產出可稽核的敘事日報：**數字與狀態全由 ST 既有
資料管線算好（EvidencePack），Claude 只負責整理敘事、假說、明日觀察**。

## 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| `POST` | `/api/ai/postmarket-daily` | 產生日報（批次 concurrency=1；回應帶 `X-ST-AI-Request-ID`） |
| `POST` | `/api/ai/postmarket-daily/abort` | `{abortSignalClientId}` 中止進行中的批次 |
| `GET`  | `/api/ai/postmarket-daily/latest` | 讀最近一次本機存檔（`data/reports/postmarket/YYYY-MM-DD.json`，gitignored） |

Request（欄位齊 `server/postmarket_report.py::generate_report`）：

```json
{
  "asOf": "2026-09-06T15:05:00+08:00",
  "symbols": ["2330", "2454"],
  "locale": "zh-Hant-TW",
  "modelHint": "sonnet",
  "include": {"quotes": true, "chips": true, "news": true, "decisionSummary": true, "macro": false, "validationPoints": true},
  "maxNewsPerSymbol": 5,
  "abortSignalClientId": "optional-request-id"
}
```

Response 200：`{reportId, generatedAt, model, usage{inputTokens,outputTokens,estUsd},
symbols[{symbol, evidenceAsOf, stale, anomalies[]?, validationPoints[]?,
narrative{conclusion,drivers,hypotheses,risks,watchTomorrow},
citations[], guardrail?}], marketBlurb?, usageToday{estUsd,runs}, partial?, aborted?}`。

錯誤碼：`400`（無 key／參數，與 `/ai-proxy` 同拒絕行為）、`413`（>20 檔或 EvidencePack 過大）、
`429`（上游限流透傳）、`502`（Anthropic 失敗）、`503 + Retry-After`（WaveDeck 持有 llm_gate）。

## 紅線（v1，違反即退件）

1. **LLM 不算決策數字**：regime、支撐壓力、信心分數、曝險區間一律 DecisionContext／
   規則層既有值；日報只以 `decisionSummary`（`decision_context.latest_context()` 唯讀快照）當證據。
2. **不 mutate ST 狀態**：不動 positions、feature flags、DecisionContext 公式；唯一寫入
   為 `data/reports/postmarket/`（gitignored）與 wavedeck_bus 成本計數。
3. **雲端 Claude only**：走 `ai_api.anthropic_messages`（既有 proxy stack）；gate 忙碌時
   **絕不**自動 fallback 本機 `deep`（避免 ST + WaveDeck stampede）。
4. **llm_gate**：取得時標記 `purpose=postmarket-daily`；WD 持有 → `503 + Retry-After`；
   中途被 WD preempt → 剩餘檔標 `gate_preempted_by_wavedeck`、回 `partial:true`。
5. **證據落地**：每個數字主張須對得上 server 組的 EvidencePack；quote asOf 逾期
   （盤後 >6h、盤中 >1h）→ `narrative.risks` 首條由 server 決定性補「資料可能過期」。
6. **預設禁止喊單**：system prompt 明文禁止買賣建議／目標價／保證獲利；模型違規輸出
   由 `scrub_advice` guardrail 直接移除並回報 `guardrail` 欄位。
7. **明日驗證點紅線**：`anomalies[]`／`validationPoints[]` 僅由 `build_evidence_pack` 規則產出；
   LLM 可在 `watchTomorrow`／`hypotheses` **改寫語意**，禁止自創閾值或分數；`audit_narrative_numerics`
   會將 EvidencePack 未出現的數字標入 `guardrail`。
8. Reader／無 key 拒絕行為與既有 AI 端點一致（gateway：reader POST 一律 403；
   本機：無 key → 400 `AI key not set on server`）。

## 資料來源（全部沿用既有管線，缺料回空＋notes「資料不足」）

| Evidence | 來源 |
|----------|------|
| quote / techSummary | `datastore.get_bars`（日K）＋ `indicators.sma / rsi_wilders`（精準 Wilder RSI） |
| chips | `chip_api.build_chip`（三大法人／融資券／借券／當沖／TDCC） |
| news | `market_flash.build_flash` 依代號過濾（TWSE/TPEx 重大訊息；**無個股新聞爬蟲**，缺料屬預期） |
| decisionSummary | `decision_context.latest_context()` 唯讀快照（市場層級） |
| universeMeta | `universe.load()` ＋ TWSE OpenAPI 產業別（`_get_tw_sectors` 注入） |
| anomalies[] | `build_evidence_pack` 規則層（量能、RSI、SMA 偏離、法人、融資）— **FACT**，無 LLM |
| validationPoints[] | 由 anomalies 衍生的明日驗證點（≤3），含 `resolveSession`／`thresholdRef` — **FACT** |

`include.validationPoints`（預設 `true`）關閉時不產出 anomalies／validationPoints（避免不需要的 payload）。

## UI

AI 中樞（`#ai`）工具列「盤後日報」→ `src/ui/postmarket_v5.js` report drawer：
每檔結論可展開 drivers／hypotheses／risks／watchTomorrow、各區塊 evidence asOf、
**明日驗證點**（FACT 可勾選 checkbox，localStorage 記錄）與規則異常摘要、
`usage.estUsd`＋當日累計、複製 Markdown、中止鍵。Conditional Expectation 卡仍受
`shadowConditionalExpectation` 旗標控制。**不新開 Shadow 訊號面板。**

## v1 範圍外（後續）

- 交易日 15:05 排程（v1.1）、法說／年報 PDF 摘要、新聞批次標註、RAG over `data/reports/`。

測試：`tests/test_postmarket_report.py`、`tests/test_postmarket_http.py`（對齊規格驗收 §9）。
