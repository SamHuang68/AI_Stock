# 研究 AI 路由契約

研究 Runner 沿用 `/ai/local/status`、`/ai/local` 與 `/ai/deep`，不新增供應商、憑證或權限。一般副駕省略 `expectedRoute` 時維持既有呼叫方式。

每個 status mode 提供 `destinationVerified`、`destination`、`destinationId`、`destinationReason` 與 `expectedRoute`。`available` 表示既有模型／CLI 可用性；`destinationVerified` 只表示後端能固定這次直接傳輸的端點與模型參數，**不表示已呼叫模型、供應商身分鑑別或供應商內部轉送路徑已獲證明**。

直接 HTTP adapter 的公開 `destination` 只包含 origin；`destinationId` 是 adapter 與完整端點的版本化 SHA-256 識別碼，不公布端點路徑、帳密或查詢內容。含 userinfo、query、fragment、無效埠或非 HTTP(S) 的設定不能標為已驗證。資料邊界依實際端點判定：loopback／localhost 才是 `local-only`，其他主機是 `external`，無法解析則 `unverified`。這不是新的網路存取授權。

已確認路由的 `expectedRoute` 固定包含六個非空字串：

```json
{
  "mode": "fast",
  "host": "EVO-T1",
  "provider": "LM Studio",
  "model": "後端設定的模型",
  "dataBoundary": "local-only",
  "destinationId": "st-ai-direct-v1:端點識別碼"
}
```

Runner 將 status 提供的物件交給 `STAI.request({expectedRoute, prompt, context, ...})`。共用 client 建立副本並帶入 HTTP body；這個物件只能限制可接受路由，不能選擇供應商、模型或目的地。

HTTP handler 在啟動推理前核對六欄，不完整、不相符或未驗證時回 `409`，不傳送研究內容。工作執行緒在取得模型占用鎖後再次核對，並將核對完成的 URL／model 快照直接交給 adapter，避免傳輸時重新讀取不同設定。HTTP headers 已送出後才發現變動時回 SSE `error`，沒有 `done`。若目前設定會經環境代理，status 標為未驗證，研究請求停止，不會繞過既有代理。已確認的直接 HTTP 傳輸固定不使用代理，也不接受重新導向；兩者都不能在核對後靜默改變目的地。

回應增加 `X-ST-AI-Destination-ID`。client 的 `meta.serverRequestId` **只取實際 `X-ST-AI-Request-ID` header**，缺少時保留空字串；原 `meta.requestId` 仍可使用前端 correlation id 供舊畫面追蹤，不能當研究收據。研究 client 在採用正文前比對實際 mode、host、provider、model、dataBoundary、destinationId，並要求真正收到伺服器 request header；失敗即拒絕結果。

Hermes 目前只向 ST 暴露 CLI 的供應商／模型參數，尚無可核對的最終端點契約，因此 `destinationVerified=false`、`expectedRoute=null`。既有一般深度分析保留；研究 Runner 必須將此路由標為不可用，不能以供應商名稱猜出目的地，也不能自動切換到其他模型。

驗證僅使用 mock 模型與傳輸：`tests/test_ai_research_route.py`、`tests/ai_research_route_selftest.js`。原串流取消、總期限、完成收據、占用鎖與資料快照限制仍沿用既有測試。
