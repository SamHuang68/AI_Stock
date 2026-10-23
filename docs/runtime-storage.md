# 單一正式資料根：程式契約與切換邊界

本變更提供外置資料根的程式能力；不建立正式 binding、不遷移資料、不停止現行服務、不刪除備份，也不代表已部署或完成切換。正式切換仍須先比較現有資料、確認停寫時段與保留備份，再由獨立程序產生並核對切換收據。

## 程序與寫入所有權

- 正式業務資料只有一個 ST backend writer。Local 與 PrivateWeb 的使用入口應共用這個後端，不能各啟動一份業務資料寫入程序。
- WaveDeck 保有獨立程序，只能持有 `wavedeck` namespace 的 writer lease，資料位於正式根的 `wavedeck/`。這不是「整個 runtime 只有一個 OS 程序」。
- 兩個 namespace 各持有一個程序存活期間的 OS byte lock。PID 檔不授予或取代寫入權限；單純解析路徑、匯入模組或繼承環境變數也不授予 lease。
- WaveDeck 的 ST LLM gate 走同一 ST backend HTTP API；外置模式不能退回直接寫 ST gate JSON。POST 帶 `expectedDataRootId`，回應帶 `dataRootId`、`acquired` 或 `released`。
- 未取得 lease 的直接 CLI、額外 backend 或不符 `allowedCodeRoots` 的 worktree 必須拒絕寫入。測試使用明確 fixture binding。

## Binding 與檔案身分

`server/data_paths.py` 僅使用標準庫，讀取非秘密身分資訊，不建立目錄或開啟業務資料庫。

安裝位置的唯一 sidecar 名稱為 `runtime_binding.json`，位於 managed `current/` 的上一層。也可用 `ST_DATA_BINDING` 指定絕對路徑；環境、顯式傳入與安裝 sidecar 不得互相矛盾。`ST_RUNTIME_ROLE` 必須明列 `backend`、`wavedeck` 或 `client`。可選 `ST_DATA_ROOT` 若出現，必須與 binding 相同。沒有任何新設定且沒有外置安裝收據時，保留 legacy 路徑。

安裝 binding 欄位：`schemaVersion=1`、`storageMode=external`、絕對 `dataRoot`、UUID `dataRootId`、獨立 `recoveryRoot`、`capabilityVersion=1`、非空 `allowedCodeRoots`，以及固定 loopback origin 的 `backendUrl` 與 `publicUrl`。

正式根必須已存在，並具有：

- `.st-data-root.json`：`schemaVersion=1`、`kind=production`、相符的 `dataRootId`。
- `.st-cutover.json`：`schemaVersion=1`、`state=ready`、相符的 `dataRootId` 與 `capabilityVersion`，以及非空的 `requiredPaths`。每個項目必須是已存在的業務檔案；不允許以空根啟動後自建另一份資料庫。

外置版本的 `.private_web_release.json.storageBinding` 也須與 binding 身分相符。若該收據宣告外置模式但 binding 遺失，不能退回 legacy。發布與回退另檢查程式根的 `runtime_storage_capability.json`，不允許把已外置的安裝交給不支援此能力的舊程式。

`require_runtime_paths(relative_paths, binding=...)` 讓入口列出必要檔案，檢查既存且已列入切換收據；不擴充或產生收據。WaveDeck 的必要檔案為 `wavedeck/runtime_state.json` 與 `wavedeck/wavedeck_config.json`。

路徑檢查拒絕 traversal、相對覆寫、不同資料根覆寫、reparse／symlink／hard-link 別名與 Windows 不明確檔名。程式根、runtime 與 recovery 不得互相包含。正式 metadata 與 writer lease 檔不能由一般存取函式改寫。

## 消費者 API

- `binding_for(...)`／`resolve_binding(...)`／`validate_binding(...)`：取得與驗證 `DataBinding`；驗證回傳相同物件。
- `data_path(...)`／`log_path(...)`：解析可變資料與紀錄。`seed_path(...)` 保持程式附帶的靜態種子位置。
- `bootstrap_runtime(..., namespace='st'|'wavedeck')`：明確啟動 writer，必須在會初始化資料、queue 或 worker 的模組載入之前完成。
- `assert_write_allowed(path, namespace=..., must_exist=...)`：檢查程序、namespace 與路徑；SQLite 寫入入口使用 `must_exist=True`。中央 atomic/JSONL 工具用 `namespace=None`，依路徑核對實際 namespace。
- `public_identity(...)`：回傳 `dataRootId`、`storageMode`、`runtimeRole`、`storageCapability`／`capabilityVersion`，不增加公開完整路徑。`describe_binding(...)` 則供本機管理工具取得實際路徑與 protected roots。

Fixture 模式需既存 `.st-fixture.json`，包含 `schemaVersion=1`、`kind=fixture` 與 UUID `fixtureId`。resolver 不替測試建立 marker。Fixture 不得指向 production marker 的子樹，亦不得涵蓋已知 canonical／Local／PrivateWeb 正式目錄。測試可在新建的暫存目錄中準備這份小型 marker 與合成資料。

## 認證附屬檔與資源鎖

憑證、token 與現有認證設定不遷移。Gateway 本身沒有業務 writer lease；`bootstrap_gateway_auth(binding, writable_file=...)` 僅授權既有 access-request JSON 的精確檔名、`.bak`、既有格式的 `.corrupt-*` 與 atomic 暫存檔。該檔必須和 runtime／recovery 完全分離，其他檔案或整個目錄均不因此取得寫入權限。

既有 Fast AI 的全機資源鎖維持固定位置 `<temp>/StockTerminal/ai-runtime/fast-ai.lock`。這不是可變業務資料根的例外白名單；只有此固定 name／directory 可走資源鎖檢查，而且正式程序仍須先持有自己的 namespace lease。發布管理鎖也僅能在固定呼叫點、完成 protected-root 隔離驗證後使用內部低階鎖定入口。

## ETF／研究工作期限的限制

外置模式的 ETF 更新與研究來源更新由已持有 lease 的 ST backend 程序執行，不讓子程序繼承環境後成為第二個 writer；legacy 保持既有子程序路徑。

外置工作使用**合作式 deadline**：檢查 HTTP 重試、回應 body、工作迴圈及提交快照前的剩餘時間。ETF 仍使用 300 秒時間預算，研究工作使用 10,800 秒，但這不等同舊子程序的硬 wall-clock 終止。阻塞中的 DNS、HTTP header 或尚未返回的來源呼叫可能超過預算；研究籌碼來源目前的單次 socket timeout 為 20 秒。不能為終止一個工作而硬殺共用 backend。

若驗收要求精確秒級停止，仍須另行設計「只抓取、不寫業務資料」的隔離 worker，讓父程序驗證結果後提交。本變更不宣稱已提供此硬期限能力，也不宣稱已實際切換正式服務。

## 隔離驗證入口

新增 `tests.test_runtime_storage` 與 `tests.test_runtime_workers`；包含 binding／缺檔拒絕、跨程序租約、gateway 精確權限、namespace、fixture／alias、同程序 worker、逾時保留快照及 gate 身分反例。需連同 consumers、WaveDeck、release 與中央存取 guard 的相依提交整合後，由主控依驗證 gate 執行。此文件不是測試通過或部署成功的證據。
