# 外置資料的程式發布與本機入口

此變更只提供程式契約，沒有建立正式 binding、搬資料、停服務、刪備份或切換安裝。
舊安裝未設定任何新 runtime 選項時，沿用原路徑。

PrivateWeb 安裝根的 `runtime_binding.json` 或明確的 `ST_DATA_BINDING` 引用可要求外置模式。
它們都交給 `server/data_paths.py` 核對既有資料識別、完成的切換收據、程式根與能力版本；
衝突、缺檔、不相容版本一律拒絕，不能回退到空資料目錄。正式啟動不使用 metadata-only 驗證。
host 正式啟動另要求安裝根存在該唯一名稱的 binding，使 gateway 能獨立核對；
只有環境引用而沒有安裝 sidecar 時，host 拒絕啟動。

程式發布與回復只使用共用解析器作唯讀驗證，不取得資料 writer lease。
runtime 與 recovery 必須和整個安裝根分離；發布交易記錄保存 binding 識別，
中斷後若 binding 改變即停止回復。外置模式不將程式資料種子寫入業務資料。
既有 `current/data` 私人網站認證附屬設定仍保留，不會以新空設定取代。
host 不將業務 binding 環境傳入 gateway；gateway 啟動另以 client 身分驗證同一份 binding，
只取得 access-request 設定檔及原有原子寫入附屬檔的精確授權，不取得 ST writer lease，
不能因此寫入業務根或 `current/data/market.db`。認證與路由政策保持原設定。
舊版本缺少外置能力宣告時不得在外置安裝中發布或回復。

所有模式都拒絕把 `data/runtime`、`data/recovery`（不分大小寫）及 binding／資料識別檔
納入封裝或遞迴備份；檢查在讀取保護樹內容、建立備份或改名之前執行。
分享包會先裁掉保護樹，最後封裝前再次檢查。`.gitignore` 只協助避免誤加入 Git，
封裝檢查不依賴 Git 忽略規則，已追蹤的檔案同樣會拒絕。

本機設定若明確指定 `storageMode: external`、`dataBinding` 與既有 `sourceInstallRoot`，
入口只核對該 PrivateWeb 的資料 ID、能力版本與執行中 SHA，然後開啟原認證網址；
不建立本機程序收據、不同步資料、不備份資料、不啟動第二個後端。
若 PrivateWeb 已啟用外置資料而 Local 仍是舊設定，Local 的啟動／同步也會拒絕，
不另開使用舊資料的後端。
設定啟用仍屬實際切換，必須另外完成資料差異核對與停寫時段確認。

**目前功能相容性仍阻止切換。** PrivateWeb 安全政策保持 `wavedeck: false`、
`remoteTrading: false`；原 Local 功能無法無損改用這個入口。
共用入口會明確拒絕能力降級，不自動啟用 market-only，也不放寬認證或路由允許清單。
此提交不能作為「已可無損切換」的證據。

測試入口：`test_runtime_package_policy`、`test_external_runtime_release`、
`test_shared_backend_launcher`。只使用小型暫存目錄、假健康回應與受控 PowerShell 入口；
不建立 ZIP、不啟動服務、不連網。必須整合 runtime-core 的正式依賴後，由主控驗證 gate 執行。

本工作線依賴 runtime-core 的 `bootstrap_gateway_auth`／`GatewayAuthLease`、
缺失 binding 防降級實作，以及 runtime-wavedeck 的 `wavedeck/runtime_paths.py`。
直接腳本的 `scripts/assert_standalone_runtime.ps1` 也列入必要封裝檔案。
在這些獨立工作線整合並通過主控驗證之前，外置 host／gateway 接線不能視為可用發布版本。
