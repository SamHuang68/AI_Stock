# MCP 契約與回測可信度

本輪基線為 `2c11e873df787d6879fc889f95032ff30eb461c3`（含 #139）。技術分數維持 0–100，體檢、事件研究及交易模擬分開。開發使用獨立 worktree，不複製原工作區資料。整合發布須等待 #138 owner 完成交付協調。

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
