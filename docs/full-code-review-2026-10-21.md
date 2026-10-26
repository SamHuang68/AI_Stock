# Stock Terminal 完整程式碼審查報告（2026-10-21）

- 審查類型：作者外的同供應商單執行緒審查（Claude；無子代理、無並行工作流）。只讀，不改程式、不提交、不推送。
- 受審工作樹：`C:\Users\Sam\AI-Workspace\worktrees\stock-terminal\equilens-learnings`，分支 `claude/heat-industry-sectors-only`，HEAD `e47be84`（工作樹乾淨）。主工作階段告知 `origin/main` 與正式站、本機皆為 `6caa8b96`（#256）；本報告的行號以 `e47be84` 為準，核對時請對照該 SHA。
- 倉庫規模：861 個追蹤檔；Python 約 48,000 行（`server/` 289 檔）、JavaScript 約 42,800 行（`src/` 130 檔）、測試 291 檔。
- 已執行的驗證：`python -m unittest tests.test_no_new_silent_exceptions`（2 個測試通過，基準與現狀相符）；以 Python 片段實測 `_safe_sym` 二次解碼繞過（見 H-2）。其餘發現為程式閱讀推論，未做瀏覽器或整合實測。

## 1. 範圍與方法

逐行閱讀的檔案（完整）：
`server/server.py`（6,830 行）、`server/private_web_gateway.py`、`server/http_boundary.py`、`server/http_client.py`、`server/atomic_store.py`、`server/lru_cache.py`、`server/datastore.py`、`server/job_queue.py`、`server/pulse_updates.py`、`server/pulse_orchestration.py`、`server/alert_daemon.py`、`server/ai_api.py`、`server/ai_routes.py`、`server/wavedeck_bus.py`、`server/secret_store.py`、`server/llm_gate.py`、`server/daemon_lock.py`、`server/market_routes.py`、`server/source_health.py`、`server/deadline.py`、`server/quote_api.py`（fetch_one）、`server/decision_context.py`（持久化與發布段 1571–1780）、`build_v2.py`、`scripts/go.ps1`、`src/core/app_kernel_v5.js`、`.github/workflows/*.yml`、`tests/test_no_new_silent_exceptions.py`。

以模式掃描覆蓋的範圍：全部 `server/`、`scripts/`、根目錄 Python（裸 except、eval/exec/pickle、shell=True、SQL 字串拼接、TLS 驗證關閉、硬編碼密鑰）；全部 `src/` JavaScript（innerHTML／insertAdjacentHTML 未逸出、eval／new Function、計時器配對、fetch 與 AbortController、localStorage 鍵）。

未逐行閱讀（見第 6 節）：`decision_context.py` 的規則本體、`macro_track.py`、`early_warning.py`、`exposure_lab.py`、`options_exposure.py`、`margin_ratio.py`、`stock_signals*.py`、`tdcc_holders.py` 大部分、`postmarket_report.py`、`etf_*` 其餘、`pulse_v5.js`／`shell_v5.js` 等大型前端檔、`wavedeck/` 子專案、`installer/`、其他 scripts。

嚴重度定義：
- **高**：可被本機其他程式或私有網站 reader 角色觸發的未授權副作用、資料被竄改、或會讓功能持續錯誤的缺陷。
- **中**：可用性／效能明顯退化、資料契約分歧、或需特定條件才成立的安全弱點。
- **低**：邊界情況、資訊揭露、維護性問題。
- **Nit**：風格與小修。

每項標示「驗證狀態」：**已驗證**（實際執行或可直接從程式碼確定）／**推論**（需實測確認）。

## 2. 高嚴重度

### H-1 帶副作用的 GET 端點沒有 CSRF 與角色保護
- 位置：[server.py:4306](../server/server.py#L4306)（`/holders/backfill?weeks=N`）、[server.py:4286](../server/server.py#L4286)（`/holders/refresh`）、[server.py:5477](../server/server.py#L5477)（`/focus?refresh=1` 全台股 Yahoo 掃描）、`/movers?refresh=1`、`/sectors?nocache=1`、`/macro/<key>?refresh=1`、`/flash?refresh=1`。
- 問題：`_origin_ok` 只在 `do_POST` 檢查（[server.py:2976](../server/server.py#L2976)）。本機任何網頁放一個 `<img src="http://127.0.0.1:18432/holders/backfill?weeks=5200">` 即可觸發 104 週以上的 TDCC 背景回補；Host 檢查擋的是 DNS rebinding，擋不住這種 GET 型 CSRF。
- 閘道面：`route_permission` 把 `/holders/` 列為唯讀前綴（[private_web_gateway.py:418](../server/private_web_gateway.py#L418)），`/focus` 列為唯讀路徑（[private_web_gateway.py:404](../server/private_web_gateway.py#L404)）。reader 角色因此能啟動背景抓取與整個宇集的 Yahoo 掃描，和閘道「唯讀」的宣稱不符。
- 另 `weeks` 直接 `int()` 無上下限、無 try：非數字會讓 handler 丟出未攔截例外（連線中斷，無 JSON 錯誤）。
- 驗證狀態：已驗證（程式碼路徑直接可確定；未實際對正式站發送）。
- 建議：把 refresh／backfill 類動作改為 POST 並走 `_origin_ok`；或至少在 `do_GET` 對帶 `refresh`／`nocache`／`backfill` 的請求套用同一來源檢查。閘道側把 `/holders/refresh`、`/holders/backfill` 移到 owner 控制清單並限制 `weeks` 範圍。`tests/test_private_web_gateway.py` 目前沒有針對這些路徑的 reader 案例，建議補上。

### H-2 `/quote/<sym>` 二次解碼繞過代號白名單
- 位置：[server.py:2661](../server/server.py#L2661) 先 `unquote` 再 `_safe_sym`；[server.py:3660](../server/server.py#L3660) 在 handler 內再次 `unquote`。
- 問題：`_safe_sym` 允許 `%`，所以 `%252Fx%253Fa` 第一次解碼成 `%2Fx%3Fa` 通過白名單，第二次解碼成 `/x?a`，直接拼進 Yahoo URL 路徑（[server.py:3685](../server/server.py#L3685) 附近）。實測結果：

  ```
  %255ETWII    -> %5ETWII  safe=True -> ^TWII
  %252Fx%253Fa -> %2Fx%3Fa safe=True -> /x?a
  ```
- 影響：無法換主機（不是跨主機 SSRF），但白名單形同失效，可改寫 Yahoo 端的路徑與查詢字串；`tests/test_server_http_security.py:178` 只測了 `/fundamental/%255ETWII`，沒有涵蓋 `/quote/`。
- 驗證狀態：已驗證（本機 Python 重現解碼鏈）。
- 建議：只在路由層解碼一次，handler 不再 `unquote`；或 `_safe_sym` 在解碼後再驗一次。同類寫法也出現在 `_handle_draw_get/_handle_draw_post`（[server.py:6649](../server/server.py#L6649)，但那裡 sym 只當 JSON 鍵，風險低）。

## 3. 中嚴重度

### M-1 持鎖做網路：單一慢來源會讓同類請求全部排隊
- `_mops_monthly_revenue` 在 `with _mops_rev_lock:` 內對 MOPS 做最多 2 主機 × 20 秒逾時的請求，外層又是 4 個月 × 2 類別的迴圈（[server.py:1263](../server/server.py#L1263)）。全站所有台股基本面／選股／ETF 原因查詢共用這把 RLock，一檔卡住，其餘全部等待。
- `_yahoo_crumb_opener` 在 `_yf_crumb_lock` 內做 3 次 Yahoo 請求（[server.py:1737](../server/server.py#L1737)）；crumb 失效時每個 keystats 請求各自排隊重取。
- `retry_outbox` 在 `_outbox_lock` 內逐筆送 Telegram／SMTP／Webhook（[alert_daemon.py:511](../server/alert_daemon.py#L511)），每筆最長約 35 秒，期間 `deliver()`（[alert_daemon.py:494](../server/alert_daemon.py#L494)）與 `/notify`、`/alert/test` 都被擋住。
- 驗證狀態：推論（鎖範圍可從程式碼確定；實際等待時間需實測）。
- 建議：鎖只保護快取讀寫，網路呼叫放在鎖外；或改為每個快取鍵一把鎖。

### M-2 `datastore.fetch_tw_universe` 與 `server._extract_tw_stock_codes` 契約分歧
- [datastore.py:522](../server/datastore.py#L522) 仍保留「掃描列內所有值找 4 位數」的啟發式；[server.py:830](../server/server.py#L830) 的同功能函式已明文「不從成交價、筆數或日期猜股票代號」。
- 影響：`backfill-universe`／`update-universe` CLI 可能把成交筆數、價格等 4 位數值誤當代號去抓 Yahoo，寫入 `market.db`。這是規則 0009 第 12 條禁止的平行管線。
- 驗證狀態：已驗證（兩段程式碼直接比對）。
- 建議：`datastore.fetch_tw_universe` 改呼叫 server 端同一個解析函式，或把解析函式搬到共用模組。

### M-3 ETF 更新完全關閉 TLS 驗證
- [etf_delta_tracker.py:48](../server/etf_delta_tracker.py#L48)–50 建立 `CERT_NONE` 且 `check_hostname=False` 的全域 context，[etf_delta_tracker.py:126](../server/etf_delta_tracker.py#L126) 所有 ETF 來源都用它。
- 影響：同網段中間人可替換 ETF 持股資料；註解稱「Windows 憑證問題統一關閉」，但其他模組（`http_client`）都用預設驗證且正常運作。
- 驗證狀態：已驗證。
- 建議：改走 `http_client`；若特定來源憑證確有問題，只對該主機降級並記錄。

### M-4 私有網站閘道的信任邊界
- `_client_identity` 在 peer 為 loopback 時信任 `X-Forwarded-For`／`Tailscale-User-Login`（[private_web_gateway.py:1213](../server/private_web_gateway.py#L1213)）。Tailscale Serve 之後所有請求的 peer 都是 loopback，本機程序可偽造這兩個標頭以繞過每客戶端速率限制，審計紀錄的 `client` 欄位也隨之不可信。
- `ST_WEB_DEV_BYPASS=1` 時所有 loopback 請求直接取得 owner（[private_web_gateway.py:1334](../server/private_web_gateway.py#L1334)）；在 Tailscale Serve 之後等於對整個 tailnet 開放 owner。這是設定風險，建議啟動時若偵測到 `allowed_host_suffixes` 含 `.ts.net` 就拒絕 dev_bypass。
- reader 角色可讀 `/health`（[private_web_gateway.py:357](../server/private_web_gateway.py#L357)），而 `/health` 回傳 `baseDir`、`pythonExe`、快取與各來源健康細節；`/selftest` 也對 reader 開放。屬資訊揭露。
- 審計檔與 client trace 檔只追加、無上限、無輪替；每個未認證請求都寫一筆 `authentication_failed`（[private_web_gateway.py:1631](../server/private_web_gateway.py#L1631)），掃描器可持續灌大 `logs/private_web_audit.jsonl`。
- 驗證狀態：已驗證（程式碼）。

### M-5 冷啟動同步請求可長達數十秒以上
- `_handle_inst_rank` 快取未命中時最多往前 7 天、每次 15 秒逾時（[server.py:4811](../server/server.py#L4811)），最壞 105 秒才回應。
- `_handle_market_snapshot` 完全沒有快取，每次都打 TWSE MIS 一次、TAIFEX MIS 最多兩次（[server.py:6354](../server/server.py#L6354)）；前端若以此為頂列來源會放大上游請求。
- `_fetch_tw_light` 不管主來源是否可用，每次先打 data.gov.tw 中繼資料 API（12 秒逾時）（[server.py:758](../server/server.py#L758)）。
- 驗證狀態：推論。
- 建議：inst-rank 以單一「最近交易日」查詢取代逐日試探；market snapshot 加 10–15 秒快取；tw_light 先試主來源，失敗才查中繼資料。

### M-6 前端 innerHTML 未逸出（19 處）
- 掃描到 19 處以字串串接把變數直接塞進 `innerHTML` 且同行沒有 `esc()`，例如 [strategy_builder_v3.js:449](../src/screener/strategy_builder_v3.js#L449)（localStorage 中使用者自訂條件組名稱直接成為 `<option>`）、[wizard_v3.js:469](../src/screener/wizard_v3.js#L469)（`e.message`）、[multichart_v3.js:189](../src/chart/multichart_v3.js#L189)（`p.sym`）。模板字串版本（`${}`）則全部有逸出。
- 影響：資料多來自本機伺服器或使用者自己輸入，屬 self-XSS；但私有網站有 reader 角色且 `/search` 名稱來自官方資料集，若上游名稱含 `<`，會原樣注入。
- 驗證狀態：已驗證（掃描結果）；是否能實際觸發屬推論。
- 建議：把各檔重複定義的 `esc()`（至少 20 個檔各自一份）集中到 `colors_v3`／`viz_v5` 層級共用，並把這 19 處改用逸出。

## 4. 低嚴重度

- L-1 `_macro_economy_snapshot` 前值為 0 時不算變化：`prev.get('value') not in (None, 0)`（[server.py:543](../server/server.py#L543)）。殖利率利差（`spread10y2y`）恰為 0 時 `change` 會是 `None`。已驗證。
- L-2 `_fetch_day_movers` 的 TPEx 去重用 `any(x['code'] == code for x in rows)`（[server.py:2090](../server/server.py#L2090)），約 1,000 × 800 次比較，每次呼叫重算。建議改成 set。已驗證。
- L-3 `_get_tw_universe`／`_get_tw_names`／`_get_tw_sectors`／多個 handler 用 `date.today()`（主機本地日）當快取鍵，而 `_build_tw_market_fundamental` 已改用 `taipei_today()` 並註明主機非 UTC+8 時會錯。本機在台灣不影響，但雲端或 CI 不一致。已驗證。
- L-4 `wavedeck_bus._save` 多執行緒同時寫同一個 `.tmp` 再 `replace`（[wavedeck_bus.py:85](../server/wavedeck_bus.py#L85)），競爭時 `replace` 失敗被 `except: pass` 吞掉，狀態可能沒有落盤。推論。建議改用 `atomic_store.atomic_write_json`（已有且加鎖）。
- L-5 `_etf_report_email` 對 `http://localhost:{PORT}/etf-delta` 自我發 HTTP（[server.py:5971](../server/server.py#L5971)），30 秒逾時，佔用兩條伺服器執行緒；直接呼叫 `_handle_etf_delta` 背後的函式即可。已驗證。
- L-6 `_fetch_keystats_html` 仍有唯一一處裸 `except: pass`（[server.py:4275](../server/server.py#L4275)）；`_handle_portfolio` 的回補迴圈 `except Exception: pass`（[server.py:5751](../server/server.py#L5751) 區段）。棘輪基準目前 `server/server.py` 69 處，測試通過；屬既有技術債，數字只能往下。已驗證。
- L-7 前端 `setInterval` 26 處、`clearInterval` 22 處；至少 4 個計時器可能沒有對應的清除（未逐一核對哪些是刻意長駐）。推論。
- L-8 `http_client.request` 對 POST 也套用暫態重試（[http_client.py:396](../server/http_client.py#L396)）。目前的 POST 呼叫端（TAIFEX MIS 查詢）是冪等查詢，無實害，但新呼叫端若用來送出非冪等請求會重送。已驗證。
- L-9 閘道 `/gateway/logout` POST 沒有 CSRF／來源檢查（[private_web_gateway.py:1626](../server/private_web_gateway.py#L1626)）；跨站可讓使用者登出。已驗證。
- L-10 `_openapi_lookup_list` 的 `except` 分支引用 `_hc`（[server.py:1152](../server/server.py#L1152)）；若 `import http_client` 失敗，`_hc` 未定義會在 except 內再丟 NameError。目前 `http_client` 在倉庫內，實際不會發生。已驗證。
- L-11 `_handle_quote_batch` 內 `cls = ...` 未使用（[server.py:3628](../server/server.py#L3628)）。Nit。
- L-12 `_fetch_fred_csv` 直接改寫 `macro_track._FRED_CIRCUIT_OPEN` 私有狀態（[server.py:368](../server/server.py#L368)），跨模組耦合；建議提供 `macro_track.open_fred_circuit(reason)`。Nit。

## 5. 各區塊觀察（含正面）

**HTTP 邊界與伺服器骨架（server.py、http_boundary.py）**：請求本文有長度與型別上限、拒絕時正確排空並關閉連線；Host 標頭檢查擋 DNS rebinding；靜態檔案只允許 `src/`、`assets/`；`X-ST-Trace-ID` 貫穿；HTML／JS 回應禁快取。主要缺口是第 2 節的 GET 副作用與二次解碼。`do_GET` 是 100 多個 `elif` 的線性比對，可讀性尚可但新增路由容易漏掉安全檢查，建議改成表驅動並在表上標示「需同源」。

**私有網站閘道（private_web_gateway.py）**：路由策略白名單、HMAC 簽章工作階段、登入／表單 CSRF、速率分桶、hop-by-hop 與 cookie 剝除、Archify 文件 CSP 都做得完整；測試 `test_private_web_gateway.py` 有 reader 不可寫的案例。缺口見 H-1、M-4、L-9。

**外呼與資料來源（http_client.py、source_health.py、deadline.py）**：連線池、期限、gzip、熔斷、節流都有實作且執行緒安全；`collect_named` 逾時後取消未啟動的工作。`_response_deadline` 用 Timer 強制 shutdown socket 的做法正確。

**持久化（atomic_store.py、datastore.py、job_queue.py、pulse_updates.py、decision_context.py）**：原子寫入＋備份＋損毀隔離；SQLite 全部參數化（f-string 只用於表名常數與 PRAGMA）；`merge_source_bars` 以 `BEGIN IMMEDIATE` 包住讀寫並用 SAVEPOINT 隔離證據層；兩個持久佇列都有跨程序 daemon lock、啟動時恢復中斷工作、單一工作者。decision_context 的「先記錄意圖、再提交、再通知」協定與 `superseded` 判定邏輯一致。未發現競態或 SQL 注入。

**憑證（secret_store.py、ai_api.py、alert_daemon.py）**：DPAPI 保護、明文自動遷移、設定回應遮罩 `***set***`、日誌寫入前 `_redact`。`push_telegram` 失敗訊息原樣回給 `/alert/test`／`/notify` 呼叫端（未經 `_redact`），若 urllib 例外文字含 URL 會帶出 bot token；屬低風險（owner 才能呼叫），列入 L 類補充。

**警報常駐（alert_daemon.py）**：遲滯帶、冷卻、待送匣重試、三值邏輯都有；見 M-1 的鎖範圍問題。

**Pulse 編排（pulse_orchestration.py）**：所有外呼都走有界 pool 與快取優先；`txf_for_snapshot` 的時間戳比較邏輯正確處理 05:00–08:45 的舊日盤問題。`_ohlc_job` 用裸 Thread 搭 `join(3.0)`，逾時後執行緒繼續跑，建議改走 `pulse_side_pool`。

**啟動腳本（go.ps1）**：收據（PID＋啟動時間＋命令列＋工作樹）核對、AST 自我檢查、不依埠 taskkill、更新只 ff-only 且不 stash——與 AGENTS.md 第 2 節事故對策一致。

**建置（build_v2.py）**：以字串替換修改 v1 HTML，多處「找不到就靜默跳過」；最後有 tip UX 契約硬檢查，可接受。

**CI（ci.yml、完整驗證.yml）**：局部驗證計畫與明確授權的完整驗證分開，符合規則 0008 第 13 條；`requirements-ci.txt` 安裝與證據沿用正常。

**前端核心（app_kernel_v5.js）**：GET 去重、15 秒預設期限、呼叫端 signal 與內部 controller 合併（含無 `AbortSignal.any` 的回退），實作正確。136 處 `fetch(` 中僅 54 處用 AbortController，未經 `AppKernel.api` 的直接 fetch 沒有期限（例如 `shell_v5.js:1523`、`1542`、`1575`、`1880`），建議逐步收斂到 kernel。

## 6. 未涵蓋與限制

- 約 48,000 行 Python 中逐行讀過的約 16,000 行；其餘以模式掃描覆蓋。決策引擎規則本體、預警狀態機、選擇權曝險、融資維持率、個股訊號等分析邏輯的數值正確性未審。
- 前端大型檔（`pulse_v5.js` 5,064 行、`shell_v5.js` 2,054 行、`decision_v5.js` 2,375 行）只讀結構與掃描，未審渲染邏輯與狀態競態（例如快速切換標的時舊回應覆寫新圖，這是 handoff 曾列的待修風險，本次未驗證）。
- `wavedeck/` 子專案、`installer/`、其他 `scripts/*.py`、`research/` 未審。
- 未執行完整測試套件（依規則 0008 第 13 條需另行同意）；只跑了棘輪測試。未做瀏覽器實測。
- 行號以 `e47be84` 為準；主工作階段若已合併到 `6caa8b96`，`server.py` 行號可能偏移，請以函式名定位。

## 7. 建議處理順序

1. H-1：把 backfill／refresh 類 GET 改 POST 或加同源檢查；閘道把 `/holders/refresh`、`/holders/backfill` 移出唯讀前綴；`weeks` 加範圍。補 reader 測試案例。
2. H-2：移除 `_handle_quote` 內的第二次 `unquote`，並在 `tests/test_server_http_security.py` 加 `/quote/%252F...` 案例。
3. M-3：`etf_delta_tracker` 改回 TLS 驗證（或只對確有問題的主機降級並記錄）。
4. M-2：`datastore.fetch_tw_universe` 沿用 server 的代號解析函式。
5. M-1：把 MOPS、crumb、outbox 的網路呼叫移出鎖。
6. M-4／M-5／L 類依序處理；M-6 可與下一次前端改版一起做。

本報告只列發現與建議，未修改任何程式；修正依主工作階段的協調通知由該階段依序處理。

## 8. 修正狀態（2026-10-22，工作樹未提交）

已修正並通過 159 個相關測試：H-1（同源檢查加在會觸發副作用的 GET、閘道限 owner、weeks 範圍）、H-2（移除第二次解碼）、M-1（MOPS 改逐月份鎖、待送匣送出不持鎖）、M-2、M-3（預設驗證憑證，`ST_ETF_INSECURE_HOSTS` 明列才關閉）、M-4（dev bypass 限 localhost、登出來源檢查、審計檔 32 MB 換檔）、M-5（快照 10 秒快取、tw_light 先試主來源、inst-rank 總預算）、M-6 三處確認的未逸出點、L-1、L-2、L-4、L-6、L-9、L-10、L-11。

未改：Yahoo crumb 鎖（單飛取得是刻意去重，影響小）、`X-Forwarded-For` 信任、`/health` 對 reader 的資訊揭露、L-3、L-5、L-7、L-8、L-12；M-6 其餘 16 處經核對多為數字或常數串接。尚未做瀏覽器實測，也未跑完整測試套件。
