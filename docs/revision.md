## 2026-10-24 單一資料根候選分支的三組缺陷修正（ST-R1、ST-R2、ST-R3）

- 基底：`442b90841ac979d0ff42facf1513baa04edf28b7`（origin/main）；分支 `claude/runtime-unification-fixes`，疊在 Codex 的 `review/runtime-unification`（`f3f7ebda5017d01c059abf5be71b4b2f0822921f`）之上。**本分支是單一資料根架構的候選，不是已驗收的版本，不可合併、不可發布。**
- 背景：Codex 交接單 `Documents\Codex\2026-10-23\task-2\ST-Claude-Handoff.md`（2026-10-24）列出該分支三組仍未修的缺陷，當時因審查限制未能套用；Sam 2026-10-24 指示「照建議執行」，由 Claude 複核並修正。Claude 獨立核對過三項描述與程式碼相符。
- **ST-R1（發布單檔被當目錄遍歷）**：
  - 問題：`runtime_release_policy.assert_safe_tree` 在名稱與祖先連結檢查後，對一般檔案仍呼叫 `os.walk(..., onerror=fail)`，Windows 拋 `NotADirectoryError [WinError 267]`。呼叫端 `private_web_release._copy_item` 是所有發布共用的複製路徑（基準 `442b908` 沒有這個呼叫），所以連**舊模式**的 stage、promote 也會被擋。
  - 修正：名稱與祖先連結檢查之後，`root.is_file()` 直接回傳。受保護名稱與 junction 的拒絕仍在前面，反向案例（單一受保護檔仍被拒）通過。
- **ST-R2（gateway／host 輸出路徑）**：
  - 問題：gateway 只取得 auth 檔的寫入權；稽核紀錄、客戶端追蹤、啟動追蹤、PID 檔，以及 host 的三個日誌與 PID 檔，路徑來自設定與環境變數，沒有確認不碰受保護的資料根／復原根、也不是硬連結別名。需要本機設定誤指或別名才會發生，沒有遠端提權。
  - 修正：非舊模式時，在任何探測、建目錄或寫入之前檢查所有輸出：與受保護根雙向不重疊，並沿用 `data_paths.assert_no_links`（符號連結、junction、硬連結、非正規拼寫）。gateway 新增 `_pid_path`、`_assert_gateway_outputs`；host 新增 `_host_output_paths`、`_assert_host_outputs`。舊模式不受影響。
- **ST-R3（ETF 清單只在匯入時載入）**：
  - 問題：外部模式下 ETF 更新在長駐後端內同程序執行，`ETFS = load_catalog()` 只在匯入時執行一次，修改 `etf_catalog.json` 後要重啟才生效；舊模式每輪是新程序，沒有此問題。
  - 修正：`run()` 每輪開頭重新讀一份清單，整輪（預期數、最低門檻、待補代號、逐檔抓取）用同一份快照。
  - 測試 fixture：`test_runtime_workers.setUp` 的 `patch.dict(os.environ, clear=True)` 清掉 Windows 家目錄變數，7 案在 `Path.home()` 出錯；只保留 `HOME`、`USERPROFILE`、`HOMEDRIVE`、`HOMEPATH` 四個，不帶入其他環境。
- **ST-R4（新發現：WaveDeck 測試隔離被破壞，交接單未列）**：
  - 問題：Codex 因 Sam 豁免而沒驗 WaveDeck。分支把 `wavedeck/server/state.py` 的 `DATA` 改成 `runtime_paths.runtime_data()`，舊模式回傳 `runtime_paths` 自己所在目錄的 `data`；但測試把 `server/` 複製到暫存目錄執行，仍匯入真實的 `runtime_paths`，狀態於是寫進**真實**的 `wavedeck/data` 並在測試之間互相汙染，WaveDeck 測試從 main 的 129 個全過變成 47 個錯誤（46 個是「委託尚未核對，請先完成核對再切換策略」）。
  - 修正：`state.py` 舊模式維持「本檔旁的 data」（與 main 完全相同），外置與 fixture 模式才走共用資料根；`config.py` 的秘密檔路徑舊模式同樣跟著 `DATA`。另一個子程序測試（`test_真實服務匯入入口先取得單例…`）的夾具補複製 `runtime_paths.py` 與 `data_paths.py`、`runtime_storage.py`、`daemon_lock.py`。
  - 結果：WaveDeck 148 個案例全過（main 為 129 個，差額是分支新增與先前合併的案例）。跑完後真實 `wavedeck/data` 仍出現狀態檔，main 的副本跑同一套測試也一樣，是原本就有的行為。
  - 這是正式使用的風險點：若有人在**正式主工作樹**跑這個分支的 WaveDeck 測試，會改寫執行中的 WaveDeck 狀態；修正前尤其如此。
- **ST-R5（新發現：Windows 暫存目錄 8.3 短檔名導致 39 個新架構測試在 CI 失敗）**：
  - 問題：手動完整驗證（run 40052323841，對 `94297a5`）在 GitHub Windows 失敗 39 個，全部在 `test_runtime_storage`、`test_runtime_consumers`、`test_runtime_workers`、`test_runtime_secrets`，錯誤是 `runtime paths must use their canonical spelling, not filesystem aliases`。runner 的暫存目錄是 8.3 短檔名（`C:\Users\RUNNER~1\…`），新架構的資料根檢查**刻意**要求正規拼寫、拒絕別名。我本機一般暫存路徑跑全過，所以第一輪完整測試沒有發現。
  - 判斷：產品拒絕檔案系統別名是對的，是測試夾具沒有把暫存路徑展開；啟動器測試本來就用 `.resolve()`。另有一個跨磁碟 `os.path.relpath`（CI 的 checkout 在 D 槽、暫存在 C 槽）。
  - 修正：6 個測試檔的暫存根改用 `resolve()` 或 `os.path.realpath`（storage、consumers、workers、secrets、WaveDeck 的 runtime_binding 與 runtime_launcher），`relpath` 加 `start=`。不改產品。
  - 重現與驗證：本機建立有 8.3 短名的目錄並把 `TEMP` 指過去重現（修正前 38 個失敗），修正後這 4 個模組 49 個案例與 WaveDeck 148 個案例在短檔名與一般暫存路徑下都全過。Windows CI 因「Unit tests」失敗，後面的 WaveDeck、JS、瀏覽器步驟被跳過、沒有結果，需重新觸發完整驗證。
- **第二意見（Codex，隔離封包、跨供應商，2026-10-24）**：範圍為相對 `f3f7ebd` 的 16 個檔案差異；結論 `significant-issues`、完整度 `insufficient`（只看到差異，看不到完整檔案），依規則不算完成審查。三項發現逐項對照程式碼：
  - **host 在安全檢查前就覆寫 PID 檔（高）：同意，是我 R2 修正的真實缺口。** `main()` 在呼叫 `run()` 之前就建立 PID 目錄並寫入，而我的檢查只放在 `run()`；PID 檔若是受保護檔案的硬連結，會先被截斷。我的測試只測了 `run()`。修正：`main()` 取得綁定後先呼叫 `_assert_host_outputs`；新增直接呼叫 `main()` 的拒絕案例，舊程式失敗。
  - **ETF 以修改時間與大小判斷目錄有沒有變不夠（中）：同意。** 等長內容加時間戳相同會漏判，且「先載入再取時間戳」之間檔案若更新會被標成新版。修正：改用 SHA-256，清單與雜湊來自同一次讀取；讀取失敗（雜湊為 None）時沿用現有清單、不退回 fallback。新增「等長內容且修改時間改回原值」與「檔案損毀或消失」兩個案例，舊程式都失敗。
  - **驗證計畫自身沒有落在任何案例的 `changes`（中）：不同意。** 計畫檢查入口（`scripts/變更驗證.py --check`）本來就把 `.github/驗證計畫.json` 排除在變更對應之外，現在與先前所有 PR 一樣通過；把它塞進案例反而會讓計畫的指紋隨自己改變。
  - 兩個未決問題：ETF 更新能否並行啟動我沒有完整驗證（`etf_api` 的 `_tracker_lock` 保護狀態更新，是否同時擋住並行啟動未確認），所以採保守設計：全域清單只在一輪開頭重新指定、整輪用同一份；若兩輪真的並行，後啟動者換清單時前一輪的後續讀取可能讀到新清單，這個風險未排除；路徑通過預檢後到實際開啟之間被換成連結（檢查時間與使用時間之差）屬已知限制，目前靠 writer lease 與目錄權限，不在本次修正範圍，記在此處。
  - 修正後未再送複審。
- **ST-R6（計畫版 CI 在 Windows 的偶發失敗：時序競爭，非新功能壞掉）**：
  - 現象：#266 計畫版 CI（`a510021`）Windows 的「主站測試模組 1/12」失敗一個案例 `test_Pulse更新佇列` 的 `test_terminal_write_failure_retries_receipt_without_rebuilding`：`'IntegrityError: 注入工作收據失敗' is not None`；同一個 SHA 的手動完整驗證與我的本機完整重跑（2149 案例）都通過，本機單案例 25 次、整個模組 6 次、main 單案例 25 次也全過。
  - 根因：`pulse_updates._finish` 在資料庫提交後工作即顯示 `succeeded`，**接著才**寫診斷紀錄（`_trace`），**之後**才把 `workerError` 清成 None；測試每 10 毫秒輪詢到 `succeeded` 就立刻斷言 `workerError` 為 None，中間沒有等待。寫檔慢的機器會落在這個空檔。這個競爭在 main 上同樣存在，不是分支引入的。
  - 驗證：本機把 `_trace` 人為拖慢 0.3 秒，舊測試重現與 CI 完全相同的失敗訊息，新測試通過。
  - 修正：只改測試。契約是「重試成功後 `workerError` 會被清掉」，改成最多等 3 秒讓它變成 None，斷言本身不變、不放寬；不改產品程式。
- **ETF 目錄欄位型別驗證（Codex 的修復，Claude 審查後整合）**：
  - 來源：Codex 在自己的隔離工作樹（`runtime-verification-c56`）基於本分支 `c56d543` 做的最小修復，提交 `e88f2d8da2def6d4d0506d71815ece253a590eb0`，交接單 `Documents\Codex\2026-10-23\task-2\ST-ETF-Catalog-Fix-Handoff.md`。我只取它的產品檔 `server/etf_delta_tracker.py` 與新測試 `tests/test_etf_catalog_validation.py`；驗證計畫由我的產生器重新產生、本段由我撰寫，維持單一寫入者。
  - 問題：目錄裡的欄位型別錯誤（例如 `code` 是整數）會在 `_catalog_from` 拋出未預期例外（原缺陷：`int` 沒有 `.strip`），而 loader 的 `except Exception` 把它吞成「退回 fallback」。
  - 修正：`load_catalog_with_digest` 在同一次讀取內先驗證結構（根物件與 `categories`、類別與 `etfs`、每個 ETF 的 `code`／`enabled`／`name`／`market` 型別），通過才產生雜湊；不合法回 `None` 雜湊，`run()` 因此沿用最後一份有效清單；例外縮為 `OSError／ValueError`，未預期的錯誤（如 `RuntimeError`）仍會傳出；診斷只記錯誤類別，不輸出目錄內容或路徑。
  - 政策變化（需要知道）：過去目錄裡不合法的列會被略過，現在**任何一列不合法就整份目錄無效**，沿用上一份有效清單，只在輸出留一行紀錄。我核對過現有 `data/etf_catalog.json` 226 筆全部符合新規則；網頁端儲存入口 `/etf-catalog` 只驗證 `categories` 是陣列，UI 送出的是抓下來後切換 `enabled` 的目錄，所以不合法列只會來自手動編輯或其他 API 用戶端。
  - 沒有改變：合法的「全部停用」仍採預設十檔；HTTP 儲存入口沒有加驗證，不能宣稱 HTTP 已拒絕非法內容。
  - 我的獨立驗證：Codex 的新測試 3 案在 `c56d543` 的產品程式上失敗（8 個失敗＋6 個錯誤觀察，同一測試的子情境），整合後通過；加上 `test_etf_delta_tracker`、`test_ETF更新防再發`、`test_runtime_workers`（含我先前「等長內容仍重載」與「損毀沿用舊清單」）、`test_etf_paths`、`test_etf_api`、`test_etf_snapshot_health` 共 64 案全過。未重跑整套 Python（變更只在一個產品檔，由計畫版 CI 的主站分塊涵蓋）。
- 驗證（Python 3.12，與 CI 相同）：
  - R1：`test_runtime_package_policy` 9 案通過，含原本紅燈的 `test_regular_file_is_checked_without_directory_traversal`。
  - R2：`test_shared_backend_launcher` 12 案通過，含原本 3 案共 28 個失敗觀察（gateway 2 案、host 1 案的 4 個子案例）。
  - R3：`test_runtime_workers` 11 案通過；新增「兩輪之間改清單，第二輪看到新清單」案例，舊程式失敗（清單停在首次載入的 10 檔）。
  - **完整套件**：`unittest discover -s tests`，2146 案例通過、8 個跳過、0 失敗（Python 3.12）。第一輪 12 個沒過，其中 6 個 ETF 追蹤器測試是 R3 初版（每輪無條件重讀）造成，已改成「目錄檔案修改時間或大小有變才重讀」；6 個發布測試是替身沒跟上產品（假 `_run` 未處理 `git ls-tree`、需複製真實 `runtime_release_policy.py`），已補。
  - 沒有重跑 JS、瀏覽器與 WaveDeck 測試：本次只改 Python，Codex 的 a47220e 矩陣中這些項目已通過（WaveDeck 專屬驗證依 Sam 豁免）。
- 沒有做：沒有搬正式資料、沒有停服務、沒有刪備份、沒有部署；WaveDeck 專屬驗證依 Sam 先前豁免未跑；沒有通讀分支其餘約 6000 行。
- 發布狀態：未合併、未發布。

---

## 2026-10-25 補記 #267 合併狀態（條件期望短期／長期指標）

- 基底：`663eadc0cfc85a25c2745679311794b7fab76cba`（origin/main）；分支 `claude/revision-267-status`。
- #267 已合併：實作提交 `2a51a60df4817efa0e83d6aff028b05721cee492`，合併提交 `663eadc0cfc85a25c2745679311794b7fab76cba`；合併前 CI 四項（ubuntu、windows、兩個 Cursor 審查）全部通過。
- 發布狀態：**未發布**。正式站與本機受管安裝仍是 `292a2d9c`；自 `292a2d9c` 之後合併的 #264、#265、#267 都尚未發布（#264、#265 無行為變更；#267 為新增欄位與卡片分段，不改既有欄位與門檻）。
- 未做：瀏覽器實機畫面確認；是否把「獨立事件數」納入樣本門檻仍待 Sam 決定。

---

## 2026-10-25 條件期望卡片獨立出短期指標與長期指標

- 基底：`442b90841ac979d0ff42facf1513baa04edf28b7`（origin/main）；分支 `claude/ce-short-long-split`。實作與合併 SHA 待 PR 合併後補記。
- 決定：Sam 2026-10-25「獨立出短期指標與長期指標(原來) 不做任何降級」。起因是時間序列洩漏對照檢查：20 日持有期的相鄰樣本高度重疊，`n >= 20` 對長期指標的獨立證據偏樂觀。
- 查證：沿用同一來源 `conditional_expectation.build_card` 的 `horizons`（1／5／20）與前端 `conditional_expectation_v5.js`；沒有另建平行管線。
- 修正（全部是新增，不刪不改既有欄位）：
  - 後端每個持有期新增 `independentEvents`（互不重疊的事件數）；卡片新增 `horizonGroups`：`short` = T+1、T+5，`long` = T+20（原有指標），各自判定 `ready`／`invalidIf`。頂層 `horizons`、`invalidIf`、`status`、`minimumSample` 與 `n >= 20` 門檻完全不變。
  - 前端同一張表分成「短期指標」「長期指標」兩段，T+1／T+5／T+20 全部保留，並新增「獨立事件」欄；任一段樣本未達門檻只標該段，不再拖累另一段的呈現。
- 沒有降級：沒有任何持有期、欄位、門檻被移除或收緊，沒有資料因此被隱藏。是否要把「獨立事件」納入門檻是另一個需要 Sam 決定的取捨，本次沒做。
- 驗證：`test_conditional_expectation`、`test_conditional_expectation_p1`、`test_shadow_multifactor` 共 35 案（含新增 3 案）通過；`conditional_expectation_v5_selftest.js`（新增短長期分組斷言）通過；`test_bundle_fresh`、`test_build_reproducibility` 通過。未做瀏覽器實機畫面確認。
- 發布狀態：未合併、未發布。

---

## 2026-10-23 整併大盤 8D 與台指期 8D（交接單第 9 節第 6 項）

- 基底：`6945c039cb275264544e9a5dc5bd25701f4c9bcb`（origin/main）；分支 `claude/consolidate-chart-8d`。實作與合併 SHA 待 PR 合併後補記。
- 決定：Sam 2026-10-23「整併」。兩份 8D（`docs/大盤當日漲跌8D報告.md`；`AI-Workspace/docs/stock-terminal/台指期重複回歸8D/台指期重複回歸8D報告.md`）是同一個共用主圖流程的兩次發作，共同根因是參考價與當前報價沒有單一契約、測試自行提供正式頁面沒有的 `window.S`，以及前一次 8D 結案範圍不足。
- 做法：新增 `docs/shared-main-chart-recurrence-8d.md`（依規則 0013 用英文檔名）作為主文件，寫共同範圍、共同根因與流出根因、各項措施的合併與發布狀態、驗證層級與未解事項。**兩份原報告不改寫**，保留當歷史與證據來源；本文件只引用，不複製其證據。
- 本文件記錄但不新增決定的事項：日線主圖結算價口徑（暫緩）、分鐘級資料來源未補、無頭瀏覽器驗收是否納入日常驗證計畫（仍待 Sam）、Issue #213 維持開啟。
- 驗證：只改文件；`tests.test_dist_scrub` 通過；文中 PR 合併 SHA 與日期逐項對照 `gh pr view` 與 `docs/revision.md`（#217 合併日以 GitHub 為準：2026-10-16）。
- 發布狀態：文件變更，不涉及發布。

---

## 2026-10-23 移除無呼叫者的 refreshTwIndexCells（交接單第 9 節第 3 項）

- 基底：`8765239f701a945c845e56b73f1ec754dce8e185`（origin/main）；分支 `claude/remove-dead-twindex-cells`。實作與合併 SHA 待 PR 合併後補記。
- 背景：Codex 台指期／大盤 8D 交接單第 9 節第 3 項「`refreshTwIndexCells` 死碼是否移除」，Sam 2026-10-22 指示由 Claude 接手、2026-10-23 指示「補完」。
- 查證：`git grep` 在 `src`、`stock_terminal.html`、`stock_terminal_v2.html`、`tests` 全部範圍（含 HTML 內聯事件與字串呼叫）都只有定義，沒有任何呼叫者；下方大盤小框的實際更新路徑是 `/market/snapshot` → `marketData` 事件 → `renderCanonicalMarketQuote`（2026-10-15 審查更正已記錄）。
- 修正：移除 `src/ui/polish_v3.js` 的 `refreshTwIndexCells`（31 行，直接讀 `/twindex` 並改寫小框）；它與正式路徑並存會讓人誤以為小框有兩個來源。`refreshTxfCell` 與其餘函式不動。自測 `tw_index_day_change_selftest.js` 的註解改為說明已移除。`stock_terminal_v2.html` 已重建。
- 沒有刪減任何畫面功能：函式從未被呼叫，行為不變。
- 驗證：`tw_index_day_change_selftest.js`（25 組）、`test_bundle_fresh`、`test_build_reproducibility` 通過。
- 同單其餘項目：第 5 項（案例 12 文件）2026-10-15 已更正，不需再做；第 4 項（無頭瀏覽器驗收是否納入日常驗證計畫）與第 6 項（Issue #213 與大盤 8D 是否合併）屬流程決定，仍待 Sam。
- 發布狀態：未合併、未發布。

---

## 2026-10-23 合併與發布狀態補記（#259～#262、292a2d9c）

- 基底：`292a2d9cee84a24e764f5ee4c3c195393d818fc8`（main）。只補記狀態，不改程式；歷史段落不覆寫。本段補充下方四個 PR 各段的「實作與合併 SHA 待 PR 合併後補記」「未合併、未發布」。

| PR | 內容 | 實作 SHA（合併前分支頭） | 合併 SHA |
| --- | --- | --- | --- |
| #259 | 台指期日盤／夜盤改由同一個場次選擇函式決定（QB-01、D-01、D-02、D-09、QB-08、QB-04） | `23c4d0a8d3843eed9638036459e07dfbfba49ca9` | `0dc6ad88112bc0656690ce2f74c32a85bcfe65b7` |
| #260 | K 線型態改讀詞法 S（TQ-01） | `1ec55e9b2704795924c65ec235093cfde7365869` | `7fa4119eb44da76ffe9ab45d9f17c98c27688df6` |
| #261 | 台指期參考價標示為結算價、大盤備援報價採官方昨收（QB-02 標示、QB-12） | `cb14d2dad21f9bfa30f6e0f71887222fdc8638ef` | `2c7ae269b69dad1b74ef13064e56dcf7cc6210c7` |
| #262 | 統計卡片依分頁掛載，切回統計分頁時重新掛上（TQ-01） | `508d41ac2f7a4e9ed6ff4d8153bf9388b82c7b34` | `292a2d9cee84a24e764f5ee4c3c195393d818fc8` |

- 發布：四者皆已隨 `292a2d9cee84a24e764f5ee4c3c195393d818fc8` 發布，正式 2026-10-23 01:36、本機 01:39。發布紀錄在 `AI-Workspace\docs\stock-terminal\release-292a2d9c\發布紀錄.md`：stage `tests=passed`，停機後完整備份 14 個 SQLite，promote 後 `data/` 83 項。
- 實測（本機 18432 與正式後端 18435 的 `runtimeCommit` 皆為目標）：
  - 兩端 `market.db` 的 `quick_check` ok；本機 `/selftest` 21／21 通過；
  - `/market/snapshot` 與 `/txf` 的台指期 `referenceType` 為 `settlement`；
  - #260：本機畫面 2330 型態偵測不帶參數回 9 個（修正前 0 個），打開開關畫出 30 條價位線與 11 條斜線（修正前 0 條）；
  - #262：本機畫面在體檢分頁換股，面板沒有混入統計卡片；切回統計分頁，三張統計卡片回來。
- 未驗證：
  - 日盤時段（08:45–13:45）的場次選擇實機行為，與盤前 MIS 無成交價時的大盤備援昨收：下一個交易日 10-27（週二）才看得到；
  - 閘道／Tailscale 端版本（需 Owner token）、正式站經閘道的實機畫面與手機尺寸畫面；
  - #260、#262 的畫面行為只在本機操作確認。
- 保留未刪：release 工作樹 `release-292a2d9c`（刪除暫緩）。

---

## 2026-10-23 統計卡片依分頁掛載，切回統計分頁時重新掛上（TQ-01、window.S 守衛第三組）

- 基底：`7fa4119eb44da76ffe9ab45d9f17c98c27688df6`（origin/main）；分支 `claude/stats-cards-tab`。實作與合併 SHA 待 PR 合併後補記。
- 背景：2026-10-22 的 K 線型態修正（#260）已說明正式頁面的 `S` 是頂層 `let S`、不是 `window.S`，並把 touxin／peak／conditional 四個模組的 16 處守衛列為「目前等於沒作用，補全域別名可能翻轉行為，另行確認」。Sam 2026-10-23 指示「補完三項」，本次確認並修正。
- 實測（本機 18432 正式頁面，內建瀏覽器，2026-10-23）：
  - 初始在統計分頁、載入 2330 後，波峰（`st-pk-sect`）、波峰 100 日（`st-pk100-sect`）、投信 5 日（`st-tx-sect`）三張卡片在面板內（條件期望的旗標在本機是關閉的）。
  - 切到「體檢」分頁再載入 2317：三張統計卡片被掛進體檢面板，面板文字混進 `st-peak-v0.1` 等內容。
  - 切回「統計」分頁：三張卡片全部消失，直到下一次換股才會回來。
- 根因：
  - 四個模組把卡片 append 到共用的 `#rpanel`（所有分頁共用同一個容器），靠 `typeof window.S !== 'undefined' && S.tab !== 'stats'` 判斷是否在統計分頁；正式頁面的 `window.S` 是 undefined，守衛永遠不成立，所以任何分頁都會掛。
  - `setTab` 與許多更新路徑（持倉變動、換股）都呼叫 `renderRpanel()`，統計分頁每次整塊 `innerHTML` 重畫，掛在裡面的卡片一起被清掉；原本沒有任何通知讓卡片回來。
- 修正後行為：
  - 四個模組新增 `pageState()`：優先用詞法 `S`，沒有時才退回 `window.S`；分頁守衛與 `sym`／`mkt` 的備援改用它。非統計分頁換股不再掛卡片，也不為看不到的卡片發請求。
  - `stock_terminal.html` 的 `renderRpanel` 在統計分頁畫完後發出 `statsPanelRendered` 事件（含目前代號與市場）；四個模組監聽它，把卡片重新掛上。同一檔股票的卡片已掛著就不重複載入，所以換股時 `renderRpanel` 加 `symLoaded` 兩次通知只會載入一次。
  - `stock_terminal_v2.html` 已重建（`?v=` 版本碼隨整體資產雜湊更新，故多行變動）。
- 有意不做：沒有全域補 `window.S = S`。其餘 `window.S` 守衛（`market_chart_v3.js` 29 處、`market_score_bar_v3.js` 16 處、`polish_v3.js` 2 處）只在 `MarketChart` 註冊標的（`__MARGIN_RATIO__` 等 6 個）才會走到，且 `MarketChart.load()` 會先建出 `window.S`，目前有效，不在本次範圍。
- 驗證：
  - 新增 `tests/stats_cards_tab_selftest.js`：Node `vm`，先宣告頂層 `let S`（斷言 `window.S` 為 undefined），載入四個**未修改**的正式模組，DOM 會在「面板重畫」時真的移除舊節點。四個模組各 7 項共 28 項；舊程式 16 項失敗（體檢分頁出現卡片、重畫後不回來、切回後缺卡片等），修正後全過。
  - 既有的 `conditional_expectation_v5_selftest.js`、`tw_index_day_change_selftest.js`、`etf_flow_v3_selftest.js`、`mobile_workspace_pager_selftest.js`、`完整審查前端_selftest.js`、`test_bundle_fresh`、`test_build_reproducibility` 通過。
  - **未在實機驗證新版**：本機尚未部署；上列三個實測步驟需在部署後重做一次。
- 發布狀態：未合併、未發布。

---

## 2026-10-23 台指期參考價標示為結算價、大盤備援報價採官方昨收（QB-02 標示部分、QB-12）

- 基底：`7fa4119eb44da76ffe9ab45d9f17c98c27688df6`（origin/main）；分支 `claude/ref-labels-quote-prev`。實作與合併 SHA 待 PR 合併後補記。
- 背景：兩項原由 Codex 的台指期／大盤 8D 承接（交接單補充二、補充三），Codex 自 2026-10-17 起沒有進展，Sam 2026-10-22 指示由 Claude 接手，並於 2026-10-23 指示「補完三項」。
- **QB-02（標示部分）**：
  - 問題：`quote_contract` 預設把 `referenceType` 標成 `previous_close`，但台指期的參考價來自 TAIFEX MIS 的 `CRefPrice`，是**結算價**（日盤＝前一日結算價，夜盤＝當日日盤結算價），不是前收盤價。
  - 修正：`/market/snapshot` 的 `__TXF__` 與 `/txf` 標 `settlement`；昨收若由 Yahoo 補入、或主報價只來自 Yahoo，仍標 `previous_close`（Yahoo 昨收不是結算價）。
  - 影響：`referenceType` 只出現在顯示標籤（行情格子的提示文字、決策證據、預警證據），全專案沒有任何程式拿它做判斷；價格、漲跌與漲跌幅的數字都沒有改。
  - **有意不做**：日線主圖的昨收口徑。日線資料來自 FinMind `TaiwanFuturesDaily` 的 `close`，沒有保存 `settlement_price`，圖上逐根 K 的漲跌是「收盤減前一根收盤」；期交所的漲跌口徑是「收盤減前一日結算價」，審查者在事故日重現差 42 點。要改成結算價口徑得擴充 `data/txf_daily.csv` 欄位、回補歷史、改所有讀者，並會改變畫面上的歷史漲跌數字，需要 Sam 明確決定，本次不做。
- **QB-12**：
  - 問題：`^TWII`、`^TWOII` 在 MIS 沒有成交價與開盤價時（盤前、或當日尚無資料），`_trusted_quote_override` 回 None，`/quote` 與 `/quote-batch` 改走 Yahoo，連昨收也取 Yahoo 的 `chartPreviousClose`。2026-10-14 該值與官方昨收差 1%（49302 對 48341.31）。但 MIS 在這種情況仍帶官方昨收 `y`。
  - 修正：新增 `_trusted_prev_close(sym)`，只對 `_BAD_YF` 的指數，取 MIS 的官方昨收（缺、為 0、非有限數或抓取失敗都回 None，並以 `log_once` 留下記錄）；兩個 Yahoo 備援分支用「Yahoo 價配官方昨收」，來源標為 `yahoo-v8-chart+twse-mis-prev`。MIS 完全失敗時行為與原本相同。
  - 未改：`_trusted_quote_override` 本身與既有「盤前 MIS 無成交價仍不回空」的測試。
- 驗證：
  - `test_taiex_quote_official_base` 新增 3 個案例（批次與單檔都採官方昨收、MIS 完全失敗維持原行為、官方昨收只用於不可信指數與無效值）；`test_txf_session_selection` 新增 2 個案例（結算價標示、Yahoo 補入或只有 Yahoo 時不標結算價）。
  - 在舊程式上，QB-12 的 3 個案例與結算價標示案例失敗；保留舊行為的案例通過。
  - 驗證計畫列的 12 個測試模組共 160 個案例通過（跳過 1 個既有案例）。
  - 未在實機驗證：台股 2026-10-23（週五）颱風休市、10-26（週一）國定假日休市（Sam 告知，未對照交易所公告），下一個交易日是 10-27（週二）；盤前無成交價的實際行為要等該日開盤前才看得到。
- 發布狀態：未合併、未發布。

---

## 2026-10-22 K 線型態在正式頁面讀不到圖表狀態（TQ-01、交接單第 9 節 1、2 項）

- 基底：`f235a664db1e7b9830fe5ed8011134e041b03d0b`（origin/main）；分支 `claude/pattern-lexical-state`。實作與合併 SHA 待 PR 合併後補記。
- 背景：交接單（`shared-ai-memory/sessions/2026-10-16-taiex-kline-repeat-8d-handoff.md`）把「`window.S` 在正式頁面的實際狀態」列為最優先、TQ-01 列為測試盲點，原由 Codex 承接；Codex 自 2026-10-17 起沒有進展，Sam 2026-10-22 指示由 Claude 接手。
- 實測（本機 18432 正式頁面，內建瀏覽器）：
  - `stock_terminal.html:241` 是頂層 `let S = {...}`（自初始提交就是），不會成為 `window.S`。載入後 `typeof window.S` 為 `undefined`，詞法 `S` 有 38 個欄位，`window.S === S` 為 false。
  - 開啟 `^TWII`、`__TXF__` 主圖後 `window.S` 仍是 undefined。這兩個標的不是 `MarketChart` 註冊的標的（`isMarketChart` 為 false），所以 `market_chart_v3.js` 那 29 處守衛不影響它們。
  - 只有開啟 `MarketChart` 註冊的標的（如 `__MARGIN_RATIO__`）時，`load()` 才會建出一個和詞法 `S` 不同的空物件當 `window.S`；之後的行為因此依使用順序而不同。
- 問題（已證實，非推測）：`pattern_v3.js` 用 `window.S && ...` 守衛。在正式頁面開 2330（126 根日 K）：
  - `detectPatterns()` 不帶參數回 0 個；帶入 K 線回 9 個型態；
  - `renderPatternsPanel()` 顯示「分析了 0 個日 K 線，無觸發任何形態規則」；帶入 K 線則是「共偵測到 9 個型態」；
  - `patternsToggle()` 開啟後 `S.patternLines` 仍為 0，疊圖沒有畫出；暫時讓 `window.S` 指向 `S` 後畫出 30 條線。
  - 既有瀏覽器測試（`pattern_modal_browser.cjs` 等）都先注入 `window.S`，所以測不到。
- 根因：腳本用 `window.S` 讀取圖表狀態，但正式頁面的狀態是詞法綁定，不在 window 上；同一份腳本的其他地方已直接用 `S`，只有這四處守衛用 `window.S`。
- 修正後行為：
  - `pattern_v3.js` 新增 `patternStateV3()`：優先用詞法 `S`，沒有時才退回 `window.S`；`detectPatternsV3`、`drawPatternsOnChartV3`、`renderPatternsPanelV3` 與 `renderChart` 掛勾四處改用它。
  - 結果：型態偵測不帶參數時讀得到目前圖表的 K 線；型態面板顯示實際偵測結果；使用者打開型態開關時才畫疊圖（開關仍由使用者控制，預設行為不變）。
  - `stock_terminal_v2.html` 已重建（`?v=` 版本碼隨整體資產雜湊更新，故多行變動）。
- 有意不做的：**沒有**全域補 `window.S = S`。touxin_5d、peak_observation、peak_observation_100d、conditional_expectation 四個模組各有 `typeof window.S !== 'undefined' && S.tab && S.tab !== 'stats'` 守衛，目前等於沒作用（切換股票時一律刷新）；全域補別名會讓它們在非統計分頁時提前 return，而我尚未確認切到統計分頁時是否會重新觸發刷新，可能讓卡片消失。這 16 處、`market_chart_v3.js` 29 處與 `market_score_bar_v3.js` 16 處維持原樣，分類見下。
- `window.S` 守衛分類（共 68 處，正式頁面現況）：
  - `pattern_v3.js` 4 處：已證實失效，本次修正。
  - `market_chart_v3.js` 29 處、`market_score_bar_v3.js` 16 處：只在 `MarketChart` 註冊的標的（`__MARGIN_RATIO__` 等 6 個）才會走到，且 `load()` 會先建出 `window.S`，目前有效但依使用順序；非 `^TWII`、`__TXF__` 主圖路徑。
  - touxin／peak／conditional 的 16 處：守衛目前無作用，補別名會翻轉行為，暫不動。
  - `polish_v3.js` 2 處、`fundamental_v3.js` 1 處：前者在 `MarketChart` 註冊標的才有意義；後者已用 `typeof S !== 'undefined'` 優先。
  - 這是人工讀碼加正式頁面抽測的分類，沒有逐處在實機驗證每一個分支。
- 驗證：
  - 新增 `tests/pattern_prod_state_selftest.js` 6 項：用 Node `vm` 先宣告頂層 `let S`（斷言 `window.S` 為 undefined），再載入未修改的 `pattern_v3.js`；在舊程式上 4 項失敗，修正後全過。
  - `pattern_breakout_day_volume_selftest.js`、`test_bundle_fresh`、`test_build_reproducibility` 通過。
  - 本機頁面尚未部署新版，部署後實機確認列在待驗證。
- 發布狀態：未合併、未發布。

---

## 2026-10-22 台指期日盤／夜盤改由同一個場次選擇函式決定（QB-01、D-01、D-02、D-09、QB-08、QB-04）

- 基底：`f235a664db1e7b9830fe5ed8011134e041b03d0b`（origin/main）；分支 `claude/txf-session-selector`。實作與合併 SHA 待 PR 合併後補記。
- 背景：這幾項原由 Codex 的台指期 8D 承接（交接單 `shared-ai-memory/sessions/2026-10-16-taiex-kline-repeat-8d-handoff.md` 補充、補充三）。Codex 自 2026-10-17 起沒有進展，Sam 2026-10-22 指示由 Claude 接手，必要時再請 Codex 做第二意見。以下六項在現行 main 讀碼確認屬實，並以新測試在舊程式上重現。
- 根因（同一類：各消費端各自選場次）：
  - **QB-01**：`_handle_market_snapshot` 以 `夜盤 or 日盤` 選擇。TAIFEX MIS 的夜盤清單在日盤時段仍回前一晚 05:00 的收盤，所以 08:45–13:45 的 `/market/snapshot`（行情列與主圖每 60 秒讀取）給的是前一晚夜盤。
  - **D-02**：`/txf` 以「Yahoo 價與夜盤價相差 ≤ 0.05%（約 22 點）」判定夜盤。日盤開盤附近價格接近夜盤收盤，會選到過期夜盤。
  - **D-01**：Pulse 頂列的期現價差與台指期趨勢一律以夜盤區塊優先，日盤時段等於「前一晚夜盤收盤 − 即時加權」。
  - **D-09**：夜盤區塊缺失時，主報價只要有 `ampRate` 就被當成夜盤區塊；日盤報價也有 `ampRate`。
  - **QB-08**：`/market/snapshot` 每次請求連線 TAIFEX MIS 兩次，沒有快取或熔斷。
  - **QB-04**：Yahoo 補欄位時連 `change`、`changePct` 一起搬進以 MIS 價格為主的報價，兩者價格不同步。
- 修正後行為：
  - 三處都改用既有的 `pulse_orchestration.txf_for_snapshot`（依已核實的時間戳取較新者）。該函式本身沒有修改，既有測試仍通過。
  - 新增 `pulse_orchestration.night_block`（夜盤區塊只接受夜盤）與 `strip_txf`（頂列用的場次選擇）。
  - `server.py` 新增 `_txf_mis_cached`：成功快取 15 秒、失敗快取 5 秒；同一場次同時未命中時以鎖合併成一次連線，其餘請求共用結果。查無資料（`None`）視為成功結果，快取 15 秒。
  - 新增 `_txf_fill_from_yahoo`：Yahoo 只補 MIS 缺的開、高、低、振幅；昨收也缺時才補昨收，並用 MIS 成交價重算漲跌與漲跌幅；MIS 已有昨收時不採用 Yahoo 的漲跌。
  - 新增 `_txf_now`（可替換的時鐘），snapshot 的兩次場次查詢失敗時改用 `log_once` 留下限頻記錄。
- 不變：`/txf` 的 `night` 區塊、20 秒整體快取、Pulse 的 `out['txf']`（夜盤區塊）、`txf_for_snapshot` 的語意都沒有改；沒有刪減任何欄位。
- 第二意見（Codex，隔離封包，只含這三個檔案的差異與契約；標示：跨供應商）：
  - 結論 `significant-issues`，完整度 `insufficient`（看不到 `_cache` 實作與完整 `/txf`），依規則不算完成審查；兩項發現已逐項對照程式碼：
  - 併發重複查詢（中）：**同意**。原本先 get、後 set，冷啟動時多個請求各自連線。已加鎖並補併發測試；拿掉鎖時六個請求各連線一次，加鎖後一次。
  - 切盤後 snapshot 與 `/txf` 快取不一致（高）：**部分同意，不同意嚴重度**。快取讓 snapshot 在 15:00 後最多 15 秒仍顯示日盤收盤，與 `/txf` 既有 20 秒快取同類，差距有上限，也不是選錯場次。沒有另做跨端點快取同步，改補切盤邊界測試把行為寫清楚。
  - 其餘為測試涵蓋建議（切盤邊界、單一場次失敗、TTL 到期、Yahoo 部分補欄位、asOf 缺失）：已補。
  - 未再送複審。
- 驗證：
  - `tests/test_txf_session_selection.py` 19 個案例（真實 Handler 與 HTTP，只替換 TAIFEX、Yahoo、證交所 MIS 與時鐘）。
  - 在舊程式上，場次選擇、Yahoo 補欄位與快取相關的 7 個案例失敗；保留舊行為的案例通過。
  - 驗證計畫列的 14 個測試模組共 174 個案例通過（跳過 1 個既有案例）。
  - 沒有在實機驗證：目前（週四傍晚）是夜盤時段，日盤時段的實際行為要隔個日盤時段才能看到。
- 限制與後續：
  - QB-02（`referenceType` 標示與日線結算價）、QB-12（`/quote-batch` 在 MIS 無成交時退回 Yahoo 昨收）、TQ-01（`window.S`）不在本 PR，另行處理。
  - 正式頁面 `window.S` 為 undefined（`let S` 不會成為 window 屬性），詳見後續修訂。
- 發布狀態：未合併、未發布。

---

## 2026-10-22 合併與發布狀態補記（#256、6caa8b96）

- 基底：`6caa8b96f4fcec5b3675eb10430ccbc846c8db53`（main）。只補記狀態，不改程式；歷史段落不覆寫。本段補充下方「類股熱力圖與 Pulse 只用 32 個單一產業類股」的「實作與合併 SHA 待 PR 合併後補記」。

| PR | 內容 | 實作 SHA（合併前分支頭） | 合併 SHA | 發布 |
| --- | --- | --- | --- | --- |
| #256 | 類股熱力圖與 Pulse 只用 32 個單一產業 | `e47be84d1c0aa4efea71779487d1c6e33656ded9` | `6caa8b96f4fcec5b3675eb10430ccbc846c8db53` | 2026-10-21 21:44（正式）、21:52（本機） |

- 發布紀錄在 `AI-Workspace\docs\stock-terminal\release-6caa8b96\發布紀錄.md`：stage `tests=passed`，停機後完整備份 14 個 SQLite，promote 後 `data/` 83 項。
- 實測：兩端 `/sectors?mkt=TW` 為 56 列，其中 32 列 `industry: true`；正式站 Pulse 產業排行 12 列全是單一產業；本機 `/selftest` 21／21 通過，熱力圖 32 格。
- 本機停機約 7 分鐘（21:44:57–21:52:11）：停掉舊程序後，重啟指令的引號寫錯而沒有執行，之後由 `START_ALL.cmd` 恢復。正式站不受影響。
- 未驗證：閘道／Tailscale 端版本（需 Owner token）、正式站經閘道的實機畫面、手機尺寸畫面。
- WaveDeck：2026-10-22 14:03 發現原 PID 59760（版本 `1a4d014b`）已不在執行，log 在 04:36 後無輸出也無錯誤，停止原因至今不明。
  - Sam 指示執行後，備份 `wavedeck/data`（213 檔），主工作樹快轉到 `61091d6dff0c0925431eaeeff647f76320192653`，重建發布收據後以 `START_WAVEDECK.cmd --no-browser` 啟動。
  - 實測（PID 77460）：`runtimeCommit` 為 `61091d6d`、`releaseVerified` 為 true；Halted、paper、急停維持、持倉 0；帳戶來源 `paper_sim`、權益 1,000,000、回撤 `measured`；`wavedeck/data/master/` 前後無變動。
- #257（WaveDeck 過大 JSON 回 400 不再重設連線）：實作 `0695da8`（合併前分支頭）、合併 `61091d6dff0c0925431eaeeff647f76320192653`，已隨上述 WaveDeck 部署。對執行中的 WaveDeck 實送超量本體與只宣告超量各 25 次，全部收到 400，0 次連線中止。

---

## 2026-10-21 WaveDeck 過大或長度無效的 JSON 回 400 時不再重設連線（`test_策略HTTP` 偶發失敗）

- 基底：`6caa8b96f4fcec5b3675eb10430ccbc846c8db53`（origin/main）；分支 `claude/wd-http-oversize-flake`。實作與合併 SHA 待 PR 合併後補記。
- 問題：`wavedeck/tests/test_策略HTTP.py` 的 `test_錯誤及過大JSON回傳400且不觸發AI` 在 Windows 偶發 `ConnectionAbortedError: [WinError 10053]`。失敗的永遠是「本體 `{}`、宣告長度 262145」的子案例，端點不固定。2026-10-21 在乾淨的 origin/main 上曾 5 次失敗 2 次；同日稍晚重跑 20 次全數通過。是否重現取決於系統負載。
- 根因（與 2026-10-14「被拒請求先讀完本體」同一類）：
  - `_read_json` 遇到宣告長度超過 256 KiB，或 `Content-Length` 無法解析時，不讀本體就拋出例外，`do_POST` 隨即回 400 並關閉連線。
  - 客戶端送出的本體仍留在伺服器未讀。Windows 對仍有未讀資料的連線關閉時會送出 RST，並丟棄客戶端尚未讀取的資料，客戶端因此可能讀不到 400。
  - 同類漏洞：`_drain_request_body` 遇到超量本體時同樣直接關閉，所以防護拒絕（403）與 webhook 密鑰錯誤（401）在本體超量時也會發生。
- 修正後行為：
  - 新增 `_UnreadBody`（`ValueError` 子類別），代表本體未讀取：宣告超量與長度無效都改拋這個例外，錯誤訊息不變。
  - 新增 `_discard_after_response`（lingering close）：回應送出後先關閉寫入端，讓客戶端讀到完整回應，再丟棄殘留本體，最多 1 MiB、1 秒；讀到 EOF、逾時或達上限就停止，之後照常關閉。由 `Handler.finish` 依 `_linger_close` 旗標執行。
  - 400（未讀本體）與 `_drain_request_body` 的超量分支都會設定這個旗標。超量本體仍不在回應前讀取，回應碼與內容不變。
  - 代價：一個超量請求最多占用處理緒 1 秒、讀 1 MiB；WaveDeck 只綁本機回環位址，並有 Host 與 Origin 防護。
- 測試：
  - `test_request_guard` 新增兩個案例，每種情形重複 25 次，任何一次連線中止都算失敗：
    - 400：宣告超量但只送少量、實際送出超量本體、長度無效；
    - 403：防護拒絕時送出超量本體。
  - 修正前兩案例 3 次全部失敗（WinError 10053／10054）；修正後連跑 10 次全部通過。
  - 修正後 `test_策略HTTP` 整檔連跑 20 次、`test_request_guard` 整檔連跑 10 次皆 0 失敗；WaveDeck 全部 129 案例通過。
  - 原本不穩定的案例本身沒有改動。
- 不變：WaveDeck 不隨私有站發布，本修正不影響正式站與本機受管安裝；要讓執行中的 WaveDeck 套用，須另行授權重新部署。
- 發布狀態：未合併、未部署。

---

## 2026-10-21 類股熱力圖與 Pulse 只用 32 個單一產業類股

- 基底：`f219007905479a2f92e3e60e2db4e90afe1a71ea`（origin/main）；分支 `claude/heat-industry-sectors-only`。實作與合併 SHA 待 PR 合併後補記。
- 原因：
  - `/sectors` 台股與 Pulse 的解析器只要名稱含「類」或「指數」就收。證交所 MI_INDEX type=IND 第一張表有 56 列，其中只有 32 個是上市產業分類的單一產業。
  - 熱力圖與 Pulse 原本各用一份名稱排除清單（`SKIP_TW`、`SECTOR_SKIP`），兩份內容不同，都漏掉主題、槓桿反向與合併類指數。熱力圖因此顯示 49 格，名次和這些指數一起排，例如臺指日報酬兩倍排第 4。
  - 2026-10-21 唯讀驗證時在本機畫面發現。
- Sam 的決定（2026-10-21）：只保留 32 個單一產業，5 個合併類也拿掉；Pulse 一併改用同一套產業定義。
- 修正後行為：
  - `sector_flow.is_twse_industry_index` 依證交所原始名稱判定：以「類指數」結尾、且不是合併類（水泥窯製、塑膠化工、機電、化學生技醫療、電子工業）才算單一產業。名稱正規化後就無法分辨，所以在解析時判定。
  - `/sectors` 台股與 `pulse_extras.parse_sector_tables` 的每一列都加上 `industry` 標記，**列本身不刪**。類股歷史以同一份資料的「發行量加權股價指數」作 RS20 基準，刪列會讓基準改走本機日線替代。
  - 使用 `industry` 標記的地方：熱力圖格子與名次、Pulse 計分與產業排行（`pulse_intel.filter_sectors`）、Pulse 產業輪動卡、決策中心產業卡、決策中心的台股科技漲跌（`decision_context._tw_tech_change`，原本以名稱含「半導／電子／電腦」挑列，連電子類反向、兩倍槓桿、未含電子都算進去）；`build_sector_flow` 的參與率、成交覆蓋與集中度也只算單一產業。
  - 沒有標記的列（Yahoo 代理籃、舊快取）照舊，仍由原本的名稱排除清單處理；美股不受影響。
- 畫面與計分的實際差異（以 2026-10-21 證交所資料重算）：
  - 熱力圖由 49 格變 32 格，移除：臺灣50、臺灣50權重上限30%、臺灣資訊科技、臺灣發達、臺灣高股息、臺灣就業99、臺灣高薪100、小型股300、水泥窯製、塑膠化工、機電、化學生技醫療、電子工業、臺指日報酬兩倍、臺指反向一倍、電子類兩倍槓桿、電子類反向。
  - 熱力圖參與率由 78.57% 變 68.75%；名次例如光電 3→2、金融保險 5→3、電子零組件 11→6。
  - Pulse 計分的類股數 48→32，上漲比例 0.750→0.688，集中度（最強減中位數）5.52→5.98；最強塑膠、最弱通信網路不變。
  - Pulse 進階卡原本就只列前 29 列；改後列出前 29 個產業，運動休閒、居家生活、其他三個仍不在卡內（改前同樣不在）。
  - 隨合併類一起消失的入口：原本點「電子工業」格子可查看 8 個電子次產業的合併成員清單（`類股成員.py` 的 `電子` 群組），由隔離審查指出。Sam 2026-10-21 選擇「在熱力圖加一個入口」：台股說明列加上「電子相關產業合併成員」按鈕，送出與原本點格子相同的 `/sector-members?market=TW&sector=電子工業`；美股不顯示。
  - 決策中心台股科技漲跌的範例：半導體 −0.6、電子零組件 −0.2、電腦及週邊設備 −0.4，加上電子工業 −0.5、電子類反向 +0.5、未含電子 +0.8；改前平均 −0.07，改後只算三個產業為 −0.40。
- 驗證：
  - 新增測試：證交所 56 個原始名稱恰好選出 32 個單一產業；槓桿、反向、主題、合併類不算產業；參與率只算產業但列全部保留；非產業成交額不進集中度；兩個解析器的標記；Pulse 計分排除標記列；熱力圖與 Pulse 產業輪動排除標記列（沒有標記的列照舊）。
  - 在未修改的 main 上，7 個新 Python 案例與 2 個新 JS 自我測試全部失敗；修改後通過。
  - 兩位隔離審查者（與作者同供應商，分「正確性」與「既有能力保全」兩個角度）：正確性沒有提出缺陷；保全提出兩項，皆經查證同意。決策中心台股科技漲跌已修正並新增測試（舊程式得 −0.07，新程式得 −0.40）；電子合併成員清單改由說明列按鈕開啟，`tests/類股成員與更新入口_selftest.js` 新增按鈕送出的網址、成員面板與美股不顯示的檢查。
  - UI 同條件對照（`tests/ui_baseline_compare.cjs`，合成資料、固定時鐘，main `f219007` 對工作樹）：熱力圖 1440×900 只有說明列不同（1232 像素，範圍 y 820–843，即新按鈕）；熱力圖 390×844、Pulse 與決策中心兩種尺寸皆相同，版本內無不穩定。合成資料沒有 `industry` 標記，所以這次對照證明的是沒有標記的資料畫面不變，以及新按鈕的位置。
  - 既有的類股歷史、產業營收、行情類股契約、決策資料品質、Pulse 抽取、類股成員與更新入口、脈動介面契約、打包產物一致等測試照常通過；其餘見驗證計畫證據。
- 未驗證：實機畫面，需部署後檢查。
- 發布狀態：未推送、未合併、未發布。

---

## 2026-10-21 發布狀態補記（dba64e3b）

- 基底：`dba64e3b3bd010481dbb17fd1230e1177e1959f2`（main）。只補記發布狀態，不改程式；歷史段落不覆寫。本段補充下方「合併紀錄補記（#245、#251）」中 #251 的「未發布」，以及 `/sectors` 台股快取段落的「未推送、未合併、未發布」。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `dba64e3b3bd010481dbb17fd1230e1177e1959f2` | #251 `/sectors` 台股快取契約（實作 `804abaad3ef1cd1700f21d6b2a28143385a81f65`、合併 `14e243ab4cce59b9c628372af05e836081c35062`）；以及 #250、#253 文件與 #252 WaveDeck 檔案 | 2026-10-21 20:30（正式）、20:32（本機） | 本機與正式後端已發布 |

- 依據：
  - 本機 18432 `/health`、正式後端 18435 `/health` 與 `/health/live` 的 `runtimeCommit` 實測皆為目標 SHA；閘道 `ok`、`isolated-host`；本機 `/selftest` 21／21 通過。
  - #251：兩端 `/sectors?mkt=TW` 都回完整契約（`date`、`prevSession`、56 列皆有 `prevChangePct` 與 `change`，並有 `sectorFlow`、`industryRevenue`，來源 `TWSE MI_INDEX IND`）。
  - 20:33:03 與 20:35:02 各查一次，結果相同。第二次已超過完整回應的 60 秒快取期限，期間兩端 Pulse 各執行 4、5 次，沒有再以精簡版覆寫。
  - #245 的類股名次升降依賴的 `prevChangePct` 已出現在兩端回應中；畫面上是否顯示未驗證。
- 流程：
  - stage 為 `tests=passed`，main push CI 對目標為 success；
  - 停止前兩端無執行中工作；停止後完整備份 14 個 SQLite，完整性 ok；
  - promote rc 0，保留 `data/`；兩端 `market.db` 的 `quick_check` ok。
- WaveDeck：不隨私有站發布，維持 `1a4d014b`、`releaseVerified` true（見上方 #252 部署狀態段落）。
- 未驗證：閘道／Tailscale 端版本（需 Owner token）、實機畫面（類股名次升降、資金流向標籤與產業營收的顯示）。

---

## 2026-10-21 合併紀錄補記（#245、#251）

- 基底：`14e243ab4cce59b9c628372af05e836081c35062`（origin/main，即 #251 的合併提交）。
  - 本段只補記下列兩段的「實作與合併 SHA 待 PR 合併後補記」，不覆寫原段落。
  - #244 的合併已記在 PR A 段落的 2026-10-21 補記。
- 合併方式：
  - #245：Sam 2026-10-21 指示「合併 #245」。合併前先把 main 兩度合併進分支（`1190f97` #243、`0207451` #246）；CI（ubuntu、windows）通過後，以 merge commit 合併。
  - #251：Sam 2026-10-21 指示「合併 #251」。合併前先把 main 合併進分支（`1a4d014` #252），衝突只在 `docs/revision.md` 與驗證計畫；驗證計畫 3 個案例重跑通過、CI 4 項通過後，以 merge commit 合併，並鎖定分支頭 `804abaa`。
  - #251 的實作提交是 `80ad1b7f07b8c5dd6eb6e834f467d54cab248191`。

| PR | 標題 | 實作 SHA（合併前分支頭） | 合併 SHA |
| --- | --- | --- | --- |
| #245 | 警報新增漲跌幅／預估量比／只提醒一次，類股熱力圖加名次升降（PR B） | `469c4d7fc281c970455e0fd5dd3739c635928d15` | `84b3aeaf912158c5c2b0d324239530cf97bf77cd` |
| #251 | `/sectors` 台股只沿用完整快取，Pulse 類股精簡列改寫自己的鍵 | `804abaad3ef1cd1700f21d6b2a28143385a81f65` | `14e243ab4cce59b9c628372af05e836081c35062` |

- 發布狀態：
  - #245 已隨 `4de979bd` 發布（見該次發布狀態補記），但類股名次升降受 #251 修正的快取問題影響，在正式站沒有作用。
  - #251 已合併、**未發布**。2026-10-21 補記時，正式後端 18435 與本機 18432 的 `runtimeCommit` 實測仍為 `a9214b8c115ad2dfe83dc42075a64ca8cdff3ed7`。
  - 發布須 Sam 另行授權，並走 stage → promote。發布後要確認兩件事：`/sectors?mkt=TW` 回應帶 `date`、`prevSession` 與 `sectorFlow`；畫面上出現類股名次升降、資金流向標籤與產業營收。

---

## 2026-10-21 WaveDeck 部署狀態補記（#252，WD-07）

- 基底：`1a4d014bf32979c725b27d0f2d7ca421fc8a9989`（main）。只補記狀態，不改程式；本段補充下方「WaveDeck 紙上模式改用模擬權益」段落的「未合併、未部署」。

| PR | 內容 | 實作 SHA（合併前分支頭） | 合併 SHA | WaveDeck 部署（本機時間） |
| --- | --- | --- | --- | --- |
| #252 | WD-07 紙上模擬權益，paper 每日回撤上限生效 | `84c5634903b9d8f54dce6dafa860283e9dba4da7` | `1a4d014bf32979c725b27d0f2d7ca421fc8a9989` | 2026-10-21 19:17 |

- 部署方式（與 #237、#238 相同）：
  1. 核對健康端點 PID、baseDir 與完整命令列後停止 WaveDeck；
  2. 停止後備份 `wavedeck/data`（213 個檔案）；
  3. 主工作樹 `git pull --ff-only`，根目錄 `data/` 既有修改未動；
  4. 逐檔核對 Git blob 後重建 `wavedeck/data/程式版本.json`（47 檔，含新的 `server/paper_account.py`）；
  5. 以 `START_WAVEDECK.cmd --no-browser` 重啟。
- 實測（PID 59760）：
  - `runtimeCommit` 為 `1a4d014…`，`releaseVerified` 為 true；Halted、paper、急停維持、持倉 0。
  - 帳戶來源由 `wave_ai_ref` 改為 `paper_sim`：權益與昨日餘額皆 1,000,000，單日回撤 0%，`daily_dd_status` 由 `unknown_reference` 變為 `measured`。
  - 交易日記為 2026-10-22（19:17 已過 15:00 換日點，屬夜盤），符合設計。
  - `wavedeck/data/master/` 的檔案在重啟前後大小與修改時間相同。
  - 帳戶面板 DOM 文字：說明列為「紙上模擬權益 · 起始 1,000,000 · 每點 200 元 · 未計費稅」，單日回撤格為「0% / 5%」；瀏覽器窗格當時隱藏，只讀文字、未截圖。
- 未在實機驗證：有部位時的成交記帳，以及模擬虧損超過 5% 觸發急停與紙上平倉。目前急停中、沒有部位，只有自動化案例涵蓋。
- 本機 ST 與正式後端不受影響（兩者沒有 WaveDeck 程式），仍為 `a9214b8c`。

---

## 2026-10-21 `/sectors` 台股快取被 Pulse 精簡版取代（類股名次、資金流向、產業營收不顯示）

- 基底：`cffe196bad2c61ea1bf0503f493b389febe97e00`（origin/main）；分支 `claude/sectors-cache-contract`。實作與合併 SHA 待 PR 合併後補記。
- 發現經過：
  - `a9214b8c` 部署後做唯讀驗證，正式後端與本機的 `/sectors?mkt=TW` 回應都只有 `ok`、`sectors`、`source` 三個欄位；
  - `date` 為空，沒有 `prevSession`，56 列都沒有 `prevChangePct`；
  - 也沒有 `sectorFlow`、`industryRevenue`；`change` 為空，並混入寶島股價、臺灣50 等非產業指數。
- 根因：
  - `pulse_orchestration.py` 在三個類股快取鍵都未命中時，把 `pulse_extras` 的精簡列以 `{ok, sectors, source}` 寫進 `sectors:{ymd}`，存 300 秒；這也是 `/sectors` 台股完整回應的鍵。
  - `/sectors` 讀到任何帶 `sectors` 的快取就直接回傳，走不到前一交易日、資金流向與產業營收的組裝。
  - `/sectors` 自己的完整回應只存 60 秒（`_cache` 預設）。Pulse 持續更新，所以完整回應過期後，多半是 Pulse 先寫回精簡版。
  - 精簡版可能是 `pulse_extras` 往前找到的較早資料日，卻存在今天的鍵下；前一交易日查詢若讀到它，會把別天的漲跌當成該日官方數字。
- 引入時間：
  - Pulse 從 `6f50baa`（2026-08-03）開始寫 `sectors:{ymd}`；`fe9dd67`（2026-09-06）搬到 `pulse_orchestration.py` 時沿用。
  - 因此資金流向標籤、產業營收與資料日從 8 月起就常常不見。
  - #245 的名次升降已隨 `4de979bd` 發布，但在正式站沒有作用。
- 修正後行為：
  - Pulse 照舊先讀 `/sectors` 的完整回應；自己的精簡列改寫到 `sectors:pulse:{ymd}`，不再寫 `/sectors` 的鍵。
  - 新增 `_tw_sectors_body_complete`。`/sectors` 讀快取和前一交易日查詢都只沿用「同資料日、官方來源、帶 `prevSession`」的完整回應，其餘一律當作未命中、重新計算。這一步防止其他寫入者再造成同類的欄位消失。
  - 沒有刪減任何欄位；畫面會恢復顯示 #245 的名次升降、資金流向標籤與產業營收。
- 驗證：
  - `tests/test_sector_rank_change.py` 新增 `SectorsHandlerCacheTest` 的兩個案例：精簡版會重新計算成完整契約；完整快取照舊不連網。
  - 同一檔新增一個案例：前一交易日查詢不採用精簡版。既有「快取沿用」案例的夾具補上 `date` 與 `prevSession`，以對應收緊後的契約。
  - `tests/test_pulse_extraction.py` 新增 `SectorsCacheKeyContractTests`：檢查 Pulse 讀寫哪些鍵；完整回應存在時不寫入。
  - 在未修改的 main 上，三個新行為案例失敗，兩個保留案例通過。
  - 修改後，`tests.test_sector_rank_change` 與 `tests.test_pulse_extraction` 共 28 個案例通過；其餘見驗證計畫證據。
- 未驗證：實機畫面，需部署後檢查。
- 後續（不在本次範圍）：Pulse 的 `pulse_extras.fetch_sectors_light` 與 `/sectors` 用不同解析器讀同一個 MI_INDEX 來源（Pulse 版本含非產業指數、沒有漲跌點），仍是兩條契約不同的管線；是否統一待 Sam 決定。
- 發布狀態：未推送、未合併、未發布。

---

## 2026-10-21 WaveDeck 紙上模式改用模擬權益，每日回撤上限在 paper 生效（WD-07）

- 基底：`cffe196bad2c61ea1bf0503f493b389febe97e00`（origin/main）；分支 `claude/wd-paper-sim-equity`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 WD-07）：paper 券商沒有自己的權益。帳戶面板一直顯示示範參考帳戶（`wave_ai_ref`，72,312／59,888）。WD-04（#237）之後，參考帳戶的回撤固定回報「未知」，所以 paper 模式下每日回撤鎖永遠不會觸發。
- 修正後行為（Sam 2026-10-21「WD-07 照建議修」，選「紙上模擬權益」、起始資金 100 萬元）：
  - 新增 `wavedeck/server/paper_account.py`。PaperBroker 以當下 `exec.price`（最近一筆訊號價格）記錄每筆模擬成交。帳本保存部位、平均成本與已實現損益：反手或歸零先平倉實現損益；減碼依平掉的口數實現；加碼則更新加權平均成本。
  - 權益＝起始資金＋已實現＋未實現損益。台指期大台每點 200 元，未計手續費與期交稅。設定在 `wavedeck_config.json` 的 `paper_account`（預設 `starting_equity` 1,000,000、`point_value` 200）。
  - 交易日以 15:00 換日（夜盤歸下一交易日），週末順延到週一，未含國定假日。每個交易日第一次算出的權益記為「昨日餘額」，作為單日回撤基準。
  - 缺成交價或帳本部位與帳戶部位不一致時，權益回報 `null`，狀態為 `unknown_price_unknown`／`unknown_ledger_mismatch`；與參考帳戶相同，不鎖定也不平倉。
  - 每次風控閘門判斷前，以及每輪回撤監控（5 秒心跳）時更新權益，兩者都在送單鎖內進行。
  - 券商只回傳成交擁有的欄位（部位、成本、損益）。交易日基準由權益更新維護，送單用的舊快照不會覆寫它。
  - 切到 `txt_master` 時撤下模擬數字、改回參考帳戶，回撤維持「未知」，直到下單大師能回報權益。
  - `risk.daily_dd_known` 改為：明確 `reference: True` 或參考來源一律未知；其餘須有權益與昨日餘額兩個數字。
  - 介面：paper 說明列顯示「紙上模擬權益 · 起始 1,000,000 · 每點 200 元 · 未計費稅」；回撤未知依原因顯示「未知（參考帳戶／帳本與部位不一致／缺價格）」；未知金額顯示「—」，不再顯示為 0。
- 限制：
  - 沒有獨立報價來源，未實現損益只在有新訊號價格時更新；
  - 缺價成交的損益不計入（部位歸零前權益為未知，歸零後恢復計算，但不含該筆）；
  - 不含費稅與國定假日。
- 部署影響：執行中 WaveDeck 的 `positions.account` 為 0，部署後 paper 權益立即以 1,000,000 起算。paper 模式的單日回撤上限從此生效：模擬虧損超過 5% 會急停並平掉紙上部位（paper 不寫任何下單大師檔，沿用 WD-05）。
- 測試：
  - `test_dd_reference_account`：
    - 示範帳戶案例改在 `txt_master` 下驗證，因為 paper 已不顯示示範帳戶；
    - 實盤案例改用真實的模擬虧損（300 點 × 部位口數），不再注入帳戶數字；
    - 加上 `del _base`，基礎類別的 12 個案例不再重複執行，它們仍在自己的模組執行。
  - `test_完整審查執行` 的送單途中回撤案例：改為送單途中寫入較高的當日基準，同時驗證舊快照不覆寫基準；斷言不變。
  - 新增 `wavedeck/tests/test_paper_sim_equity.py`（9 案例）：帳本加減碼、反手、平倉、缺價，權益與交易日換日，帳本不一致，引擎整合，以及切換券商。
  - 新檔與上述兩個改寫案例在舊程式上失敗。
- 驗證：
  - WaveDeck 10 個模組共 127 案例連續 3 次通過。數量少於先前的 130，是因為少了 12 個重複執行、多了 9 個新案例。
  - `tests/wavedeck_onepage_selftest.js` 通過，`node --check deck.js` 通過；畫面尚未實際操作確認。
  - 另見既有不穩定案例：`test_策略HTTP.test_錯誤及過大JSON回傳400且不觸發AI` 在 Windows 偶發 `ConnectionAbortedError`，乾淨的 origin/main 5 次中也有 2 次失敗，與本次修改無關。
- 部署注意：合併後須更新主工作樹、重建 `wavedeck/data/程式版本.json` 再重啟 WaveDeck，需另行授權。
- 發布狀態：未合併、未部署。

---

## 2026-10-21 發布狀態補記（a9214b8c）

- 基底：`a9214b8c115ad2dfe83dc42075a64ca8cdff3ed7`（main）。只補記發布狀態，不改程式；歷史段落不覆寫。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `a9214b8c115ad2dfe83dc42075a64ca8cdff3ed7` | #249 QB-05（以及 #248 發布狀態補記） | 2026-10-21 14:20（正式）、14:23（本機） | 本機與正式後端已發布 |

- 依據：本機 18432 `/health`、正式後端 18435 `/health` 與 `/health/live` 的 `runtimeCommit` 實測皆為目標 SHA；閘道 `ok`、`isolated-host`；本機 `/selftest` 21／21 通過，含 QB-05 新增的 4 項。
- 流程：
  - stage 為 `tests=passed`，main push CI 對目標為 success；
  - 停止前兩端無執行中工作；停止後完整備份 14 個 SQLite，完整性 ok；
  - promote rc 0，保留 `data/`；兩端 `market.db` 的 `quick_check` ok。
- WaveDeck：`wavedeck/` 無變更，維持 `474c509`、`releaseVerified` true。
- 未驗證：閘道／Tailscale 端版本（需 Owner token）、實機畫面。

---

## 2026-10-21 Yahoo 報價的異常門檻不再對海外標的套用台股漲跌停（QB-05）

- 基底：`85b1dc868b8a061f2a0fcbe8291e0497eca7168c`（origin/main）；分支 `claude/quote-anomaly-non-tw`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 QB-05）：
  - `server.py` `_anom_quote` 以 ±11%（`stock`）／±12%（`index`）判定報價可疑，那是台股漲跌停門檻；
  - 台股代號在 `_handle_quote` 開頭已轉 `/twquote`，所以 Yahoo 路徑的 `stock` 實際只有美股、加密、商品與外匯，`^` 開頭的海外指數（如 `^VIX`）套 12%；
  - 這些標的的正常大波動會被回 `suspect: true`。
- 嚴重度更正：審查補齊時寫「美股、加密在 Pulse 消失，建議升為 medium」。2026-10-21 複查不成立：前端唯一丟棄 `suspect` 報價的 `pulse_v5.js` `stockHealthQuote` 只處理 `/twquote` 的台股與台股大盤基準，美股走 `/quote-batch`、不經 `_anom_quote`。實際影響限於單檔 `/quote` 的 API 回應，畫面目前不受影響，維持 low。
- 修正後行為（Sam 2026-10-21「QB-05 照建議修」）：
  - 新增 `_anom_quote_kind(sym)`：只有台股指數（`^TWII`、`^TWOII`）用 `index` 門檻，其餘 Yahoo 標的為 `foreign`；
  - `foreign` 不套漲跌幅門檻，仍保留價格 ≤ 0 與價格／昨收比值超出 0.5～1.5 的資料合理性檢查；
  - 台股門檻與既有內建自測不變。
- 驗證：
  - 新增 `tests/test_quote_anomaly_non_tw.py`（海外 ±15～30% 不標可疑、資料合理性檢查保留、台股規則不變、依代號判定種類），在舊程式上 3 案例失敗、1 案例錯誤；
  - `server._run_selftests()` 21 項全數通過（新增 4 項）；
  - `tests.test_taiex_quote_official_base`、`test_fallback_observability`、`test_no_new_silent_exceptions` 通過。
  - 依 AGENTS.md 2026-10-14 指引，`tests/tw_index_day_change_selftest.js` 通過（`^TWII` 仍為 `index` 門檻，行為不變）。
- 發布狀態：未合併、未發布。

---

## 2026-10-21 發布狀態補記（4de979bd）

- 基底：`4de979bdaf282835e102e43353e7ea62896c235d`（main）。只補記發布狀態，不改程式；歷史段落不覆寫。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `4de979bdaf282835e102e43353e7ea62896c235d` | #240 CM-04、#241 AL-01、#242 FE-03、#243 CH-02、#244、#245、#246 CAL-02、#247 TQ-02（以及先前已部署到 WaveDeck 的 #237、#238） | 2026-10-21 13:43（正式）、13:46（本機） | 本機與正式後端已發布 |

- 依據：本機 18432 `/health`、正式後端 18435 `/health` 與 `/health/live` 的 `runtimeCommit` 實測皆為目標 SHA；閘道 `ok`、`isolated-host`。
- 流程：
  - stage 為 `tests=passed`，main push CI 對目標為 success；
  - 停止前正式後端有一筆 `pulse` 更新工作執行中，等到閒置後才停止；
  - 停止後完整備份 14 個 SQLite，完整性 ok；promote rc 0，保留 `data/`；
  - 兩端 `market.db` 的 `quick_check` ok。
- 生效核對：兩端 `/alert/status` 已出現 `pending_deliveries`（0）與 `recent_deliveries`（AL-01）。
- CAL-02：程式已發布；2027 年官方日曆要等每日日線工作在 2027 年第一次執行時寫入資料庫，在那之前 2027 日期仍為 `unknown`。
- WaveDeck：自 `474c509` 之後 `wavedeck/` 沒有變更，不需重新部署；實測仍為 `474c509`、`releaseVerified` true。
- 未驗證：閘道／Tailscale 端版本（需 Owner token）、實機畫面。

---

## 2026-10-21 兩個從未執行的契約測試檔納入 unittest 並修正過期夾具（TQ-02）

- 基底：`020745108e1ac1a0fb4cc6e2656181c33e2e8ca8`（origin/main）；分支 `claude/collect-stale-contract-tests`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 TQ-02）：
  - `tests/test_投組涵蓋契約.py`（9 例）與 `tests/test_行情類股契約.py`（10 例）以裸函式寫成且沒有 `load_tests`，unittest 收集 0 例；驗證計畫只支援 unittest，所以 CI 與 stage 從未執行它們。
  - 以 pytest 實跑時 7 例失敗，全部是測試夾具過期，不是產品缺陷：
    - 投組 6 例：`b3bdcf7`（2026-10-13）起 `portfolio.compute` 必須以資料庫核對交易日曆與價格品質；舊夾具只替換 `get_bars_bulk`、沒有日曆，結果一律為空。它驗證的持股涵蓋率、`betaCoveragePct`、`skipped`、零權重排除、代號後綴合併、常數價格相關係數未定義等契約，在其他測試中沒有對應斷言。
    - 類股 1 例，三處過期：
      - 正式程式改由 `http_client.fetch_json` 取 TWSE／TPEx，舊替身只換 `urllib`，**實際會連到真實網路**（實跑取得 1,087 筆真實個股）；
      - `_get_tw_sectors` 改為 `deadline` 參數，舊替身不收參數，呼叫即 TypeError 而被當成無分類；
      - 假 Thread 缺 `is_alive`，AST 取出的命名空間缺正式模組已有的 `time`。
- 修正（Sam 2026-10-21「TQ-02 照建議修」）：
  - 兩檔補 `load_tests`，以 `FunctionTestCase` 包裝，與 `test_pulse_intel` 等既有寫法相同；
  - 投組：`bars()` 改用合成日曆的交易日，`compute()` 改用共用夾具 `tests/已核對資料.py` 的 `價格資料`（暫存資料庫、合成日曆與還原快照），不再只替換 `get_bars_bulk`；
  - 類股：
    - 改替換 `http_client.fetch_json`，並以 socket 防線確保不連網；
    - `_get_tw_sectors` 替身改為與正式同簽名；假 Thread 補 `is_alive`；命名空間補 `time`（正式 `server.py` 頂層已 import，不補正式模組沒有的名稱）；
    - pytest 的 `tmp_path` 案例改為缺省時自建暫存目錄。
  - **斷言完全不變**：投組檔從第一個測試函式起逐字相同；類股檔 47 行 `assert` 逐行相同。
- 驗證：兩檔以 unittest 19 例通過、以 pytest 19 例通過。
- **更正先前記載**（不覆寫原段落）：
  - 「2026-10-19 台指期主力契約切換日」段寫「`tests/test_pulse_extras.py` 以 pytest 7 案例通過（該檔為裸函式，unittest 不會收集）」；
  - 「2026-10-20 個股融資融券增減」段寫「`tests/test_chip_api.py`（裸函式，unittest 不收集）以 pytest 6 案例通過」。
  - 兩檔其實都有 `load_tests`，unittest 會收集（各 7、6 例）；結果仍是通過，但「unittest 不收集」的說法錯誤。
- 發布狀態：只改測試，無產品程式變更。

---

## 2026-10-21 警報新增漲跌幅／預估量比／只提醒一次，類股熱力圖加名次升降（借鏡 EquiLens，PR B）

- 基底：`bd59a81282e8f2fa1ea4d5a5dc6e5ec424213214`（PR A 分支 `claude/ui-baseline-and-api-docs-check`）；分支 `claude/alert-conditions-and-sector-rank`。PR A 合併後須合併 `origin/main` 並更新驗證計畫基底；實作與合併 SHA 待 PR 合併後補記。
- 原因（Sam 2026-10-21「給我規劃 然後轉到 AI_Stock 專案下執行」，四項之二）：
  - 警報只有價位穿越與日線複合條件，盤中看不到「今天漲跌幅」與「今天爆量」；
  - 類股熱力圖只有當日漲跌，看不出相對前一交易日的輪動。
- 修正後行為：
  - **警報**（`server/alert_daemon.py`、`src/alert/alert_push_v3.js`）：
    - 新類型 `pct_up`／`pct_down`（相對前一日收盤的漲跌幅達門檻）與 `volume_ratio`（預估全日量 ÷ 前一交易日量；以已交易時間線性換算，開盤 15 分鐘內不判斷，畫面與推播都標示「線性估算，早盤偏高」）；門檻存在 `threshold`，`save_rules` 驗證範圍（漲跌幅 0.1–50、倍數 1–20），超出回 400；
    - 台股報價由 `server.py` 注入既有的 `_twse_mis_stock_quotes`（證交所 MIS，已過 `guard_tw_quote`），沒有可用成交才退到 Yahoo；美股用 Yahoo `currentTradingPeriod` 的正規盤起訖；昨量沿用 `load_alert_bars` 日線，取盤中日期之前最後一根；
    - 條件由不成立變成立才觸發，首次觀察只初始化，沿用 5 分鐘冷卻與 #241 待送匣；資料不足不觸發並以 `log_once` 記錄；
    - 選填 `once`（適用所有規則類型）：觸發後以狀態欄位 `_last_once_done` 停止提醒，不改使用者的 `enabled`；編輯或重新啟用規則時狀態自然清除；
    - `fetch_price` 改用共用的 `_yahoo_chart_meta`，盤前盤後價格選擇不變；失敗改為記錄，`alert_daemon.py` 靜默寬鬆例外 4 → 3（基準同步降低）；
    - 表單：輸入列與原本相同，類型選單加入三個新條件、門檻欄提示隨類型變化；「只提醒一次」與說明放在下一列；表頭「價位」改為「價位／門檻」。
  - **類股熱力圖**（`server/sector_flow.py`、`server/server.py`、`src/ui/heat_v5.js`）：
    - `/sectors` 台股回應以同一來源（TWSE MI_INDEX IND、同一解析）附前一交易日官方漲跌 `prevChangePct` 與 `prevSession`；官方回覆無資料才視為非交易日往前找，抓取或解析失敗就停止，不往前猜；結果依資料日記住，失敗或查無 10 分鐘後才重試；
    - 未採用 `sector_history.db` 推算：其回補是 4 秒預算的平行抓取，日期可能有缺口，前兩個日期不一定是相鄰交易日；
    - 前端在畫面同一組類股內各自排序算名次，於漲跌幅旁顯示精簡標記（如「#1▲6」），完整說明在 title／aria-label；無前一日資料不顯示；頁尾註明對照日期。曾把名次放在第三行，實測造成格子變高、版面下推，改為不增加行數。
- 既有能力保全（規則 0009）：
  - 以 PR A 的工具在相同合成資料下對照 PR A 與本分支：總覽、決策、圖表兩種視窗共 6 組相同；類股熱力圖 2 組有差異，人工確認只有名次標記與頁尾說明，格子尺寸、欄位與排序不變；
  - 警報視窗另以相同 fixture 截圖比對：第一版把勾選框放進輸入列，桌機文字被截、手機輸入框被擠，已改為下一列，修正後輸入列與原本一致；
  - 既有價位規則、遲滯、冷卻、複合規則、待送匣、日線來源與 Owner 寫入行為由下列既有測試覆蓋並通過。
- 驗證（本機）：
  - `tests.test_alert_conditions`（11）、`tests.test_警報日線來源`、`tests.test_完整審查警報權限`、`tests.test_alert_delivery_outbox`、`tests.test_no_new_silent_exceptions`：共 47 案例通過；
  - `tests.test_sector_rank_change`（11）、`tests.test_sector_flow`、`tests.test_sector_history`：通過；
  - `node tests/heat_rank_selftest.js`、`node tests/類股成員與更新入口_selftest.js`、`node tests/shell_v5_selftest.js`、`node tests/review_market_state_selftest.js`：通過；
  - `node tests/alert_rule_form_browser.cjs`（完整建置頁面、離線）：通過；
  - `tests.test_bundle_fresh`：通過；
  - 新增測試未在舊程式上逐一執行確認失敗（新條件類型與欄位在舊程式不存在）。
- 已知限制：預估量為線性估算，開盤後一段時間偏高；類股名次只涵蓋上市類股指數；美股 SPDR 無前一日名次。
- 順帶發現（未在本次處理）：`sector_history.return20_by_sector` 取「最近 21 個已存日期」，回補缺口時實際區間可能超過 20 個交易日。
- 2026-10-21：PR A 修正 Windows CI（`19dcc3dc8b9307808a3ede0d748220a02a062274`，UI 對照工具改用 git 暫時索引取出版本）後合併進本分支，驗證計畫 `baseCommit` 改為該提交。本分支首次 Windows CI 的 8 個案例中，其他 7 個已通過，只有 UI 對照工具自我驗證因同一原因失敗。
- 2026-10-21：#244 合併（`d3ca662271436971a4e6f30a99b9a86d5b43d494`）後合併 `origin/main`，驗證計畫 `baseCommit` 改為 `d3ca662`，並把 #245 目標改為 `main`。因先推送 `6ae5948` 才改目標，該次 CI 讀到舊基底 `19dcc3d` 而以「計畫基底與此次 PR／push 基底不同」失敗；改目標不會觸發 CI（只監聽開啟、同步、重開），重跑也沿用舊事件基底，故以本補記提交重新觸發。疊在其他 PR 上的分支，之後應先改目標再推送。
- 發布狀態：未推送、未合併、未部署。

---

## 2026-10-21 台股交易日曆跨年後改讀資料庫官方日曆（CAL-02）

- 基底：`1190f97719fdff71c6164428c440c075ecf03257`（origin/main）；分支 `claude/tw-calendar-db-fallback`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 CAL-02）：
  - `server/台股交易參考.json` 只收錄 2026 年且以人工提交更新，46 個模組依賴它；
  - 以 2027-01-05 實測：`session()` 回 `unknown`、`previous_session()` 回 None、選擇權鏈 `_date_ready` 一律 False、個股訊號時段沒有 `expectedLastDate`；
  - 但 `market.db` 的 `calendar_years` 已有 `台股日線.stored_calendar` 自動抓取的 TWSE 官方開休市日曆（當年度每 7 天重核），同一事實有兩份來源。
- 修正後行為（Sam 2026-10-21「CAL-02 照建議修」）：
  - `session()` 遇到 **JSON 年度之後**的日期時，改讀資料庫的官方日曆（含補班日），讀取結果快取一小時；資料庫未收錄或內容矛盾（年度不符、休市與補班重疊）時維持 `unknown`，並以 `log_once` 記錄；
  - `previous_session()` 改為只看日曆狀態，跨年時可由下一年度的官方日曆接續（例：2027-01-04 往前得 2026-12-31）；
  - 新增 `calendar_covers(year)`，`etf_paths.freshness_calendar` 改用它判斷未核對年度，揭露與實際計算一致；
  - **JSON 年度之前的年度維持原行為**：資料庫雖有 2021～2025，但不改變既有歷史計算（例如連續交易日切段、研究統計）；要不要延伸是另一個決定。
  - 2027 年的官方日曆會在每日日線工作於 2027 年第一次執行時寫入資料庫；在那之前仍為 `unknown`，與現況相同。
- 測試：新增 `tests/test_tw_calendar_db_fallback.py`（暫存資料庫；2027 休市、補班日、一般週六、跨年前一交易日、選擇權鏈就緒、資料庫缺年度仍未知、較早年度不變、矛盾內容拒用、ETF 新鮮度揭露），在舊程式上 4 案例失敗、2 案例錯誤。
- 驗證：
  - 新案例與既有日曆、個股訊號、條件期望、盤後報告、ETF、選擇權等 22 個模組共 327 案例通過；
  - 以本機受管安裝的真實 `market.db` 唯讀確認讀取路徑可用（2026 可讀；2027 尚未收錄，回 `unknown`）。
- 發布狀態：未合併、未發布。需在 2027-01-01 前發布才能生效。

---

## 2026-10-20 主圖型態「區間向上突破」改用當日量口徑（CH-02）

- 基底：`d42daea3e0a410d534905dbf2e6d041d7fc78f89`（origin/main）；分支 `claude/pattern-breakout-day-volume`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 CH-02）：
  - `src/chart/pattern_v3.js` 的 `detectBreakout` 以「近 5 日量均／近 20 日量均」（兩窗都含當日）判斷突破量能；
  - #233 已依 Sam 選擇把 WATCH 改為「當日量／前 20 日均量」，個股訊號本來就是這個口徑；
  - 同一天單日 3 倍量的突破，WATCH 推播「帶量突破」，主圖型態面板卻寫「量能不足，假突破風險」。
- 修正後行為（Sam 2026-10-20「CH-02 照建議修」）：
  - 量能改為當日量／前 20 日均量（不含當日），`>= 1.5` 為「量增突破」；
  - 前 20 日量有缺值、或均量為 0 時，標「量能未知」，不再以預設值 1 判定；
  - 說明改為「當日量為前 20 日均量 N.Nx」；跌破分支不變。
  - 型態歷史命中率（`patternHitRatesV3`）以型態名稱分組，「區間向上突破」的偵測條件不變（量能只影響說明與可靠度標籤），樣本數不受影響。
  - 已重建 `stock_terminal_v2.html`（只有 `?v=` 雜湊變動）。
- 驗證：
  - 新增 `tests/pattern_breakout_day_volume_selftest.js`（3 倍量為量增突破、正常量為量不足、前 20 日缺量為量能未知、跌破分支不受影響），在舊程式上失敗；
  - `tests/完整審查前端_selftest.js`、`tests.test_bundle_fresh` 通過；
  - `tests/pattern_modal_browser.cjs`（Playwright，本機借用 `nvm-hub` 專案已安裝的 playwright 模組）11 項通過、0 頁面錯誤、0 網路請求。
- 發布狀態：未合併、未發布。

---

## 2026-10-21 新增 UI 同條件對照工具與 README API 表一致性測試（借鏡 EquiLens，PR A）

- 基底：`d42daea3e0a410d534905dbf2e6d041d7fc78f89`（origin/main）；分支 `claude/ui-baseline-and-api-docs-check`。實作與合併 SHA 待 PR 合併後補記。
- 原因（Sam 2026-10-21「給我規劃 然後轉到 AI_Stock 專案下執行」；比較 `wakin61043/tw-trading-dashboard` 後選出的四項之二）：
  - 規則 0009「既有能力保全」第 4 條要求 UI 改版用相同視窗、資料與狀態做前後對照，專案原本只有個別功能的瀏覽器驗收，沒有通用工具；
  - README「主要 API」表沒有檢查機制，端點改名或移除後文件可能失真。
- 新增（不改任何產品行為）：
  - `tests/ui_baseline_compare.cjs`：兩個版本各自從 Git 取出並執行 `build_v2.py`（不改工作樹），在 `tests/fixtures/ui_baseline/synthetic.cjs` 的示意資料、固定時鐘、固定亂數、停用動畫與相同視窗下截圖；所有對外請求一律攔下；每個版本截兩次，同版不一致標為「版本內不穩定」不判讀；其餘判為相同或有差異（附差異像素與範圍），輸出並排報告與收據；
  - `tests/ui_baseline_compare_selftest.cjs`：同一版本對自己，必須全部就緒、無頁面錯誤、沒有被判為有差異的組；
  - `tests/test_readme_api_routes.py`：以 AST 讀 `do_GET`／`do_POST` 中與路徑 `p` 比較的常數，核對 README API 表的方法與路徑；
  - `package.json` 新增 `test:ui-baseline`、`test:ui-baseline-selftest`；README「開發與測試」補使用說明。
- 開發中觀察到的工具問題與處置：Chromium 預設 GPU 光柵化造成同版截圖 2–51 像素雜訊，改用固定渲染參數後同版逐位元組相同；曾考慮 0.1% 雜訊門檻，實測一行標題改字只有約 0.03% 像素會被誤放過，因此不設門檻。
- 2026-10-21 CI 修正（#244 首次 CI 的 `test (windows-latest)` 失敗）：工具原以 `git archive` + `tar` 取出版本；CI 在 PowerShell 下呼叫 Windows 內建 `tar.exe`（bsdtar），解壓時把中文檔名弄壞（`Invalid empty pathname`），`build_v2.py` 找不到 `src/core/投組資料契約_v5.js`。本機在 Git Bash 下用的是 GNU tar，Ubuntu 也通過，所以開發時沒暴露。已在本機 PowerShell 重現，改用 git 暫時索引（`GIT_INDEX_FILE` + `read-tree` + `checkout-index`）取出檔案，不再依賴外部 tar，也不動倉庫索引；修正後在 PowerShell 下自我驗證 4 組全部相同。
- 順帶發現（未在本次處理）：圖表頁右側價格軸的「今／昨」小標籤在部分載入時序下不會畫出（`renderCloseReadout` 呼叫時 `priceToCoordinate` 尚無座標，之後不重畫）；工具把該組判為版本內不穩定。
- 驗證：
  - `python -m unittest tests.test_readme_api_routes`：4 案例通過（含刻意不存在的路徑與錯誤方法會被抓出）；
  - `node tests/ui_baseline_compare_selftest.cjs`：pulse、heat 各兩種視窗 4 組全部相同（約 56 秒）；
  - 工具全路由自我對照兩次各 8 組全部相同；刻意修改產業頁標題後，該頁兩種視窗都判為有差異（434 像素），還原後無殘留；
  - `origin/main` 對工作樹：7 組相同、圖表桌機 1 組版本內不穩定（上述競態）。
- 發布狀態：未推送、未合併、未部署。
- 2026-10-21 補記：已推送並以 #244 合併到 `main`；實作提交 `bd59a81282e8f2fa1ea4d5a5dc6e5ec424213214`、`19dcc3dc8b9307808a3ede0d748220a02a062274`（Windows CI 修正），合併提交 `d3ca662271436971a4e6f30a99b9a86d5b43d494`；CI（ubuntu、windows）通過。只加工具與測試，不需部署。

---

## 2026-10-20 持倉風險面板與持倉清單共用同一份彙總，未載價不以成本當市值（FE-03）

- 基底：`d1ec70c4e79f32788bd72344b1588542dcb138d5`（origin/main）；分支 `claude/portfolio-risk-known-cost`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 FE-03）：
  - `src/core/pro_v2.js` 的 `computePortfolioMetrics` 是持倉損益的第二份實作，未載價部位以成本當市值、損益與損益% 記 0；
  - 風險面板的總市值、合計損益%、最大單股佔比、前 3 檔佔比、HHI 與圓餅都因此失真，且沒有任何標示。例：2330 已載價（+10%）、2317 未載價時，面板顯示 +5.00%。
  - #229 只修了 `position_v2.js` 的持倉清單，沒有發現這份平行計算，屬 Claude 在 PB-07 修正範圍上的遺漏。
- 修正後行為（Sam 2026-10-20「FE-03 照建議修」）：
  - `position_v2.js` 新增 `positionRefPrice`、`positionTotals`，持倉清單與風險面板共用同一份彙總：損益% 的分子分母都只用已載價部位，未載價部位的市值與損益為 null；
  - 風險面板的總市值與合計損益在有未載價時加「（N 檔未載價）」，全部未載價時顯示 `--`／「價格未載入」；
  - 集中度（最大單股、前 3 檔、HHI）只在全部部位都有市值時計算，否則顯示「--（部分未載價）」並列一條警示；
  - 圓餅只畫有市值的部位，未載價部位仍列在清單中，顯示「持有 --」「未載價」「市值 --（成本 $…）」，不刪除任何部位；
  - 圓餅中心與重設事件顯示「N 檔持股（M 檔未載價）」；
  - 已重建 `stock_terminal_v2.html`（只有 `?v=` 雜湊變動）。
- 測試：
  - 新增 `tests/portfolio_risk_known_cost_selftest.js`（兩檔一缺價時 +10%、總市值只計已載價、集中度未計算、清單標示未載價、無 NaN；全部已載價時集中度照算；全部未載價時顯示 --），在舊程式上失敗；
  - `tests/台股即時報價_selftest.js` 以名稱切片載入函式，原本先載入 `computePortfolioMetrics`、後載入持倉清單；依正式頁面的載入順序改為先載入 `position_v2.js` 的共用彙總，斷言不變。
- 驗證：
  - 新案例與 `position_total_known_cost_selftest.js`、`position_lot_rounding_selftest.js`、`完整審查前端_selftest.js`、`shell_v5_selftest.js`、`台股即時報價_selftest.js`、`review_market_state_selftest.js` 通過；`tests.test_bundle_fresh` 通過。
  - `pattern_modal_browser.cjs`、`手機行情遮蔽_browser.cjs` 需要 Playwright，只用到 `pro_v2.js` 的對話框，未執行。
- 發布狀態：未合併、未發布。

---

## 2026-10-20 推播送達失敗時保留待送並重試，記錄失敗原因（AL-01）

- 基底：`4457d52597ef4ebcf5d4ef282104696c0df57897`（origin/main）；分支 `claude/alert-delivery-outbox`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 AL-01）：
  - 價格警報、複合警報、WATCH 與個股訊號即時推播都直接呼叫 `alert_daemon.notify()` 並忽略回傳值；
  - Telegram、Email、Webhook 全部失敗時，警報仍記為已觸發（冷卻、穿越狀態與 `sent` 記號照樣更新），不重送；
  - 日誌只寫警報文字，不寫失敗原因；`recent_fired` 也看不出是否送達。
- 修正後行為（Sam 2026-10-20「AL-01 照建議修」）：
  - 新增 `alert_daemon.deliver()`，四條路徑改用它。仍先立即送出，至少一個通道成功即為 `sent`；
  - 已設定的通道全部失敗時為 `queued`，寫入 `data/alert_outbox.json`；
  - 沒有任何已設定的通道時為 `no_channel`，不排入待送。
  - `retry_outbox()` 由警報、WATCH、個股訊號三個背景迴圈每輪呼叫，共用同一把鎖：
    - 每筆間隔 60 秒、最多 5 次、最久 1 小時，逾時或用盡次數即放棄並記錄；
    - 本輪只要有一筆仍全部失敗就停止，避免網路中斷時逐筆等候逾時；
    - 待送匣上限 50 筆。
  - 每次失敗都把各通道原因寫入警報日誌，寫入前移除 Telegram 權杖、Email 密碼與 webhook 網址。
  - `recent_fired` 各筆加上 `delivery`（sent／queued／no_channel）；`/alert/status` 新增 `recent_deliveries` 與 `pending_deliveries`。前端目前沒有顯示這兩個清單，資訊在 API。
  - 待送匣檔案加入 `.gitignore` 與分享封存的 `BLOCKED_BASENAMES`；本機服務只允許下載 `src/`、`assets/`，不會外流。
  - 手動推播（`/notify`、測試推播）仍直接回報結果給呼叫者，不排入待送。
- 測試：
  - 新增 `tests/test_alert_delivery_outbox.py`（失敗排入且日誌不含權杖、60 秒後重送成功即清除、5 次後放棄、逾 1 小時不送即放棄、無通道不排入、一筆失敗即停止本輪、複合警報記錄送達狀態），在舊程式上 7 案例皆失敗；
  - `tests/test_警報日線來源.py` 的複合警報案例把 `notify` 替身改為回傳 `(True, {})`（新流程會解讀回傳值），斷言不變。
- 驗證：新案例與 `test_警報日線來源`、`test_完整審查警報權限`、`test_stock_signals`、`test_watch_breakout_day_volume`、`test_secret_migration`、`test_daemon_lock`、`test_no_new_silent_exceptions`、`test_Pulse讀寫分離`、`test_signal_narrative` 共 105 案例通過；`tests.test_dist_scrub` 12 案例通過。
- 發布狀態：未合併、未發布。

---

## 2026-10-20 個股融資融券增減改以餘額差計算，盤後融資異常門檻改為 500 張（CM-04）

- 基底：`4457d52597ef4ebcf5d4ef282104696c0df57897`（origin/main）；分支 `claude/margin-change-balance-delta`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 CM-04，主控以 TWSE 2026-10-16 MI_MARGN 真實資料實證）：
  - `chip_api` 的 `marginChange` 用「融資買進−賣出」，漏了現金償還；
  - `shortChange` 用「融券買進−賣出」，正負號相反（融券賣出是新增空單），也漏了現券償還；
  - `postmarket_report` 的 `MARGIN_CHANGE_SIGNIFICANT = 500.0` 與單位為股的 `marginChange` 比較，等於 0.5 張就算異常，標籤印出股數而沒有單位。
  - 實測 2026-10-16 全市場 1,301 檔：舊門檻會讓 1,045 檔標「融資異常」，以真實增減與 500 張計算為 77 檔；另有 11 檔「買進−賣出」與真實增減方向相反。
- 修正後行為（Sam 2026-10-20「CM-04 照建議修（門檻 500 張）」）：
  - 增減一律為「今日餘額−前日餘額」，乘 1000 與餘額同單位（股）；前日餘額缺值時回 None，不退回買進−賣出、也不補 0；
  - 融資異常門檻改為 500 張（500,000 股），標籤顯示「融資餘額增加／減少 N 張」；
  - 快取只在記憶體（`_SNAP`），沒有需要修正的已存歷史。
- 契約變更與測試：
  - `tests/test_chip_api.py` 的 `snap_margn` 斷言改為餘額差：融資 −292 張（舊式 −251），融券 −5 張（舊式 +5）；
  - 新增 `tests/test_margin_change_balance_delta.py`（以 2026-10-16 實際兩列資料核對融資含現金償還、融券正負號、前日餘額缺值回 None、門檻 500 張與標籤單位），在舊程式上 3 案例失敗。
- 驗證：
  - 新案例與 `tests.test_postmarket_report`、`test_postmarket_http`、`test_decision_context`、`test_chip_official_date_safety`、`test_三合一選股`、`test_三項限制解方`、`test_個股研究資料更新`、`test_全檢資料邊界`、`test_no_new_silent_exceptions` 共 125 案例通過（含敘事數字紅線案例）；
  - `tests/test_chip_api.py`（裸函式，unittest 不收集）以 pytest 6 案例通過。
- 影響：盤後報告的融資異常由「幾乎每檔」降為真正有 500 張以上變化的個股；圖表 `chip_v3.js` 只用餘額，不受影響。
- 發布狀態：未合併、未發布。

---

## 2026-10-20 WaveDeck 部署狀態補記（#237、#238）

- 基底：`474c509270ca6f45f2299da0f9466fa586dd6b87`（main）。只補記狀態，不改程式；本段補充下方 WD-04、WD-05、WD-06 兩段的「未合併、未部署」。

| PR | 內容 | 實作 SHA（合併前分支頭） | 合併 SHA | WaveDeck 部署（本機時間） |
| --- | --- | --- | --- | --- |
| #237 | WD-04 回撤鎖不以示範參考帳戶觸發 | `3e57fab04ac785aa9ac5fa8e11196e0cb1eace3f` | `f52b8c3ebe9b25a2fa266f225b2c5d0ed60a455c` | 2026-10-20 08:35 |
| #238 | WD-05 紙上不寫下單大師檔、WD-06 減碼不等於全平 | `b1b4f884908e7cd5f349569cae772d43efcd9ef4` | `474c509270ca6f45f2299da0f9466fa586dd6b87` | 2026-10-20 08:43 |

- 部署方式（兩次相同）：
  1. 核對健康端點 PID、baseDir 與完整命令列後停止 WaveDeck；
  2. 停止後備份 `wavedeck/data`；
  3. 主工作樹 `git pull --ff-only`，根目錄 `data/` 既有修改未動；
  4. 逐檔核對 Git blob 後重建 `wavedeck/data/程式版本.json`；
  5. 以 `START_WAVEDECK.cmd --no-browser` 重啟。
- 實測（目前 PID 68736）：`runtimeCommit` 為 `474c509…`，`releaseVerified` 為 true；Halted、paper、急停維持、持倉 0；`daily_dd_status` 為 `unknown_reference`，風控燈維持 warn。
  - #237 部署後：單日回撤格實機顯示「未知（參考帳戶）/ 5%」，08:30 之後沒有 `daily_dd_lock` 或 `panic_flatten`。
  - #238 部署後：`wavedeck/data/master/` 三個檔案在重啟前後大小與修改時間完全相同。
- 未在實機驗證：WD-06 的減碼行為。WaveDeck 處於急停且無部位，沒有可減碼的部位；只有自動化案例涵蓋。
- 本機 ST 與正式後端不受影響（兩者沒有 WaveDeck 程式），仍為 `aeaecef3`。
- 未決：WD-07——WaveDeck 沒有真實權益來源，每日回撤上限在任何模式都顯示未知、不生效；待 Sam 決定設計。

---

## 2026-10-20 WaveDeck 紙上模式不寫下單大師檔、減碼不再等於全平（WD-05、WD-06）

- 基底：`f52b8c3ebe9b25a2fa266f225b2c5d0ed60a455c`（origin/main）；分支 `claude/wd-paper-isolation-reduce`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊，主控讀碼並以執行中 WaveDeck 實證）：
  - **WD-05**：`broker.panic_flatten` 在 paper 模式也寫 `target_position.txt` 與 `order_signal.txt`。`engine.py` 與 `st_link.py` 在任何券商模式都寫 `invalidation.txt`。2026-10-20 兩次重啟各寫出一行 `TXF EXIT lots=0` 到 `wavedeck/data/master/`。
  - **WD-06**：`broker._target` 對 REDUCE 一律回 0。說明文字寫「減碼降低曝險」，實際送出的卻是全平。
- 修正後行為（Sam 2026-10-20「WD-05、WD-06 照建議修」）：
  - 新增 `broker.writes_master_files()`，只有 `txt_master` 券商回 true；paper 急停只改紙上部位，兩處 `invalidation.txt` 寫入也改為只在 txt_master 時進行；
  - 減碼依現有部位計算：策略指定口數時減該口數，否則保留一半（向下取整，所以 1 口減碼即平倉），不會翻向；部位未知或為 0 時沿用舊的平倉目標；
  - paper 與 txt_master 共用同一規則；txt_master 的 `order_signal.txt` 維持既有格式（`lots` 是目標部位的絕對值）；
  - 解除 fail-safe 時不再把風控燈蓋成 ok，參考帳戶的回撤未知時維持 warn（#237 部署後發現的燈號反覆）。
- 契約變更與測試：
  - `test_smoke.test_panic_flatten_writes_zero_target` 改寫為 `test_panic_flatten_paper_does_not_touch_master_files`；
  - 新增 `wavedeck/tests/test_reduce_and_paper_isolation.py`（減碼口數、部位未知時平倉、paper 不產生任何下單大師檔），以及 `test_成交確認.test_減碼依現有部位送出部分目標而非全平`（txt_master 送出目標 1）；
  - 新案例在舊程式上全部失敗。
- 驗證：WaveDeck 相關 10 個模組共 130 案例通過；`tests/wavedeck_onepage_selftest.js` 通過。
- 部署注意：合併後須更新主工作樹、重建 `wavedeck/data/程式版本.json` 再重啟 WaveDeck，另行授權。
- 發布狀態：未合併、未部署。

---

## 2026-10-20 WaveDeck 每日回撤鎖不再以示範參考帳戶觸發（WD-04）

- 基底：`f361ec1e7da0702c2efe64c43b35bccdf5fd66ae`（origin/main）；分支 `claude/wd-dd-reference-account`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查補齊 WD-04，主控以執行中 WaveDeck 與稽核庫實證）：
  - 預設帳戶是示範參考數值（`source: wave_ai_ref`、`reference: True`、昨日 72312、權益 59888），券商不會更新；
  - `daily_dd_ratio` 不分辨，固定算出 17.18%，高於 5% 上限；
  - 稽核庫顯示自 2026-10-09 起，每次啟動都觸發 `daily_dd_lock`，比率全部相同；
  - #225（WD-01）把 `WD_DD_FLATTEN` 預設改為開啟後，每次啟動還會自動全平（2026-10-20 兩次重啟各一次，當時紙上持倉已是 0）。
  - WD-01 實作時沒有查核回撤數字的來源，屬 Claude 的驗證遺漏。
- 修正後行為（Sam 2026-10-20「WD-04 照建議修」）：
  - 新增 `risk.daily_dd_known`：帳戶有 `reference` 旗標時以旗標為準，沒有旗標時以 `source` 是否為 `wave_ai_ref`／`reference`／`demo` 判定，與前端 `deck.js` 的判定一致；
  - 參考帳戶的 `daily_dd_ratio` 回 0，`enforce_daily_drawdown` 不鎖定、不平倉，帳戶標 `daily_dd_status: unknown_reference`、`daily_dd_pct: None`，風控燈為 warn；
  - **不解除既有急停**；
  - 閘門在新單理由中註明「單日回撤未知：帳戶為示範參考數值，回撤上限未生效」，但不據此擋單；
  - 前端單日回撤格顯示「未知（參考帳戶）」，不再以參考數字重算；
  - 明確標示為實盤（`reference: False`）的帳戶照舊計算、鎖定並全平。
- 驗證：
  - 新增 `wavedeck/tests/test_dd_reference_account.py`（參考帳戶回撤未知且不擋單、不鎖定也不全平且不解除既有急停、實盤帳戶照舊鎖定並全平），在舊程式上 3 案例皆失敗；
  - WaveDeck 相關 9 個模組共 123 案例通過，`tests/wavedeck_onepage_selftest.js` 通過，`deck.js` 語法檢查通過；
  - 前端回撤格的顯示沒有自動化案例，需部署後實機確認。
- 部署注意：WaveDeck 由主工作樹執行，合併後須更新主工作樹、重建 `wavedeck/data/程式版本.json` 再重啟，另行授權。
- 發布狀態：未合併、未部署。

---

## 2026-10-20 WaveDeck 更新到 7074b03，WD-01 生效

- 基底：`7074b03167cca8ae4f5cbd4f286e65df722d878a`（main）。只補記狀態，不改程式；本段補充上一段「WaveDeck 未生效」的後續。
- 依 Sam 指示更新主工作樹並重啟 WaveDeck：主工作樹以 `git pull --ff-only` 從 `edd44f6` 快轉到 `7074b03`，根目錄 `data/` 的既有修改保留未動；重啟前已備份 `wavedeck/data`。
- 實測（健康端點）：PID 74832，`runtimeCommit` 為 `7074b03167cca8ae4f5cbd4f286e65df722d878a`，`releaseVerified` 為 true；paper、Halted、急停維持，只監聽 127.0.0.1:18433。
- WD-01 實際行為：重啟前是 paper 帳戶 1 口、急停中，不留倉狀態自 2026-10-11 起卡在 blocked。新程式啟動後送出 1 筆紙上 EXIT，持倉歸 0、不留倉狀態變為 confirmed，急停維持。broker 為 paper，不寫委託檔。
- 發現：WaveDeck 的發布收據 `wavedeck/data/程式版本.json` 不會隨 `git pull` 更新。第一次重啟時因收據缺少新增的 `server/request_guard.py`，回報 `releaseVerified=false`；逐檔核對 Git blob 後重建收據，再重啟才通過。
- 發布狀態：本機 ST、正式後端與 WaveDeck 三者皆已在 `aeaecef3` 以後的版本執行（WaveDeck 為 `7074b03`，比 `aeaecef3` 只多文件提交）。

---

## 2026-10-20 發布狀態補記（aeaecef3）

- 基底：`aeaecef388eaa2e90763451ebdd68793050e88bc`（main）。只補記發布狀態，不改程式；歷史段落不覆寫。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `aeaecef388eaa2e90763451ebdd68793050e88bc` | 全專案審查修正 #220–#233 與合併紀錄 #234 | 2026-10-20 06:24（正式）、06:27（本機） | 本機與正式後端已發布；WaveDeck 未生效 |

- 依據：本機 18432 `/health`、正式後端 18435 `/health` 與 `/health/live` 的 `runtimeCommit` 實測皆為目標 SHA；閘道 `ok`、`isolated-host`。
- 流程：stage 為 `tests=passed`；停止正式服務後完整備份 14 個 SQLite，完整性 ok；promote rc 0，保留 `data/`；兩端 `market.db` 的 `quick_check` ok。
- 流程更正：第一次備份是在正式服務仍執行時進行，備份工具偵測到來源變動而停止。工具要求先停止寫入者，正確順序是「stage → 停止 → 備份 → promote」，而不是先備份後停止。
- **WaveDeck 未生效**：WaveDeck 由主工作樹的 `wavedeck/run.py` 執行，不在 Private Web 發布範圍內。主工作樹停在 `edd44f6`，所以 #225（WD-01）尚未在執行中的 WaveDeck 生效；需更新主工作樹並重啟 WaveDeck，另行授權。
- 未驗證：閘道／Tailscale 端版本（需 Owner token）、實機畫面。

---

## 2026-10-20 全專案審查修正 #220–#233 合併紀錄

- 基底：`63ef6492ddbfa54e1c2157946a0ea98c46a4c2cc`（origin/main，即 #233 的合併提交）。本段只補記下列 14 段「實作與合併 SHA 待 PR 合併後補記」，不覆寫原段落。
- 合併方式：Sam 2026-10-20 指示「依序合併 #220 到 #233」。
  - 每個 PR 先把當時的 origin/main 合併進分支：`docs/revision.md` 保留雙方段落，驗證計畫保留各自案例、`baseCommit` 改為新 main，改到 `src/` 的分支重建 `stock_terminal_v2.html`；
  - `scripts/變更驗證.py --check` 通過、兩個 CI 工作（ubuntu、windows）通過後，才以 merge commit 合併；
  - 除上述三個檔案外沒有程式衝突。#229 與 #222 同改 `src/core/position_v2.js`，由 Git 自動合併。

| PR | 標題 | 實作 SHA（合併前分支頭） | 合併 SHA |
| --- | --- | --- | --- |
| #220 | 條件期望卡 MaxDD Q90 改取回撤尾端 | `f1ac48d1e69abc81ce77eecd5c996cce3244f7ae` | `099453480faa2168bf2dc6433dbba65bebfa47e8` |
| #221 | 週間官方休市日改以官方日曆判定 | `10becc1fd03735b1a18342153088ce9ad73493fb` | `9cd9403802e357cf4ae5662c314c3376ba3ba9ef` |
| #222 | 持倉張數換算股數不再少 1 股 | `cdbec422930aa834282669f2e0cf7eb9376989d6` | `7689e8a970b90b77adf11e2bdefcfb3239e88311` |
| #223 | 本機 ST 後端拒絕非 loopback 的 Host 標頭 | `a54933b1bd4f5809bfe945007e5e8307bd134b88` | `a12f5c533d0008aa95a5dce6b290ad866c429662` |
| #224 | 兩份新文件改用中性路徑，恢復分享封存掃描 | `6c55846524d00a6119cd40c7b92bc619a2f00ddc` | `2c93ae001d693bb58ca2259b0458c942815c30eb` |
| #225 | WaveDeck 回撤鎖定預設自動全平，急停仍放行平倉（WD-01） | `2159a56f3b2627ecd9c5a19067702a591588ff14` | `8c80dacdf77552705233d07f39389d708dd6ebc6` |
| #226 | 條件期望的法人分箱不再使用當日籌碼（PB-02） | `ac0a3bf5a403d01738d82b0917e70fa1ad05d3e6` | `4b7c4a4ac9b00576b7ac26ba4a0a9bbf64e7b904` |
| #227 | 曝險研究的 Kelly 值照公式回報，上限保留 1x 底（PB-03） | `945cfc02c7e1bc946b2470903e81d2d56025b4fe` | `5b8ac06d6a9931a4d89fc8f0a72f8514ee27d5af` |
| #228 | 策略指標庫遇到缺值回 null，不再產生假訊號（PB-04、PB-05） | `6ba75226998da31b6f0e92e8d51f51ed70e1adce` | `38eca6c157ed93eef29421ba9b40354fb0f25414` |
| #229 | 持倉合計損益%只用已載價部位計算，未載價明示（PB-07） | `39647841971b1f29c1b73b608546d5f2f09bb5db` | `2c881f9744b1b8a6686c5dff134e852d499059f6` |
| #230 | 大盤融資維持率在收盤價不完整時不輸出（CM-01） | `49f15041ef517a0ea1a9d6125029e0bae945e47e` | `d50ed8cb04e4ddac20244f1b56dea5ec57fa29af` |
| #231 | 台指期主力契約切換日不再把轉倉算成增倉（D-03） | `571afcd8d6ec4fa8f72601f8274046746ae5a195` | `f4fee781ca1ad5d46149be6c76abb3d2993d1db4` |
| #232 | 個股期 MIS 整批抓取失效時不再讓每個請求各自重試（D-04） | `0caca235714360f514acf37184cfb85182f8b366` | `722d7bbdd9f3a82e5602de282ee7e7c889c5a955` |
| #233 | WATCH 突破新高的量能改用當日量口徑（IND-01） | `4a9bb5ce63221799b3789ab2229acb70fe93fce4` | `63ef6492ddbfa54e1c2157946a0ea98c46a4c2cc` |

- 合併後整合驗證（main `63ef649`，乾淨工作樹）：
  - 14 個 PR 驗證計畫中的全部局部案例在同一份程式上重跑：Python unittest 共 805 案例通過（1 個需網路的案例照例略過）；9 個 node 自測全數通過；
  - 同一程序內有 2 個 WaveDeck 模組因 `server` 名稱與 ST 的 `server` 模組衝突而無法載入，屬於混跑的測試隔離問題；另以獨立程序重跑 WaveDeck 7 個模組 90 案例全數通過。CI 本來就是每個案例各自一個程序。
  - 這是局部案例的聯集，不是完整測試套件。
- 發布狀態：14 個 PR 皆已合併、**皆未發布**。正式站與本機的 runtimeCommit 未變動，發布須 Sam 另行授權並走 stage → promote。

---

## 2026-10-20 WATCH 突破新高的量能改用當日量口徑（IND-01）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/watch-breakout-day-volume`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 IND-01）：
  - WATCH「突破 N 日新高」的前端（`src/core/watch_v2.js`）與背景常駐（`server/watch_daemon.py`）都用 `volRatio`（5 日均量／20 日均量）比對量能倍數。
  - 個股訊號「帶量突破 20 日高」用的是當日量／前 20 日均量，提示文字也寫「大於 20 日均量幾倍」。
  - 當日 3 倍量的突破，在 WATCH 被判「量不足（1.3x）」，同一檔在個股體檢卡卻顯示帶量突破。
- 修正後行為（Sam 2026-10-19 選擇「改用當日量口徑」）：
  - `indicators.candle_snapshot` 新增 `volVs20d`（當日量／前 20 日均量，不含當日），與 `stock_signals.build_frame` 的 `volx` 同式；
  - `watch_daemon` 與前端 WATCH 的突破判定改用此口徑，前端由 K 線直接計算，前 20 日量有缺值時不觸發；
  - 提示改為「當日量為前 20 日均量幾倍」；
  - `volRatio`（5 日／20 日）本身與其他使用者（警示、盤後報告、多因子等）不變。
  - 既有 WATCH 規則會較早觸發：單日爆量即成立。
- 契約變更與測試：
  - `tests/test_警報日線來源.py` 的突破判定案例改餵 `volVs20d`，並新增「`volRatio` 高但當日量不足仍為 partial」的斷言；
  - 新增 `tests/test_watch_breakout_day_volume.py`（3 倍量觸發、與 `volx` 同值、正常量為 partial、資料不足為 None）；
  - 新增 `tests/watch_breakout_day_volume_selftest.js`（前端同口徑、缺值不觸發、提示文字）。
  - 新案例在舊程式上失敗。
- 驗證：
  - 以上案例，加上 `tests.test_indicators`、`test_signal_indicator_parity`、`test_stock_signals`、`test_postmarket_report` 共 110 案例通過；
  - `watch_rsi_bounce_selftest.js`、`完整審查前端_selftest.js`、`tests.test_bundle_fresh` 通過；
  - 已重建 `stock_terminal_v2.html`（只有 `?v=` 雜湊變動）。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 個股期 MIS 整批抓取失效時不再讓每個請求各自重試（D-04）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/mis-futures-negative-cache`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 D-04，主控查證屬實）：
  - `server._mis_load_futures` 對日盤、夜盤各同步重試 3 次（逾時 12 秒，每次失敗後再睡 1.2 秒），全部失敗時不寫快取、也沒有鎖。
  - MIS 中斷期間，盤後頁每 45 秒的輪詢會讓每個請求重做最多 6 次連線，最壞約 79 秒，形成請求堆積，對 MIS 的失敗請求量也放大。
- 修正後行為：
  - 以 `_MIS_FUT_LOCK` 讓並行請求共用同一次抓取；
  - 整批失敗後 60 秒內直接回空（呼叫端照舊顯示未載入），之後再試；成功時清除失敗標記；
  - 每個盤別最多 2 次，只在兩次之間等待 1.2 秒，最壞約 49 秒。
  - 部分盤別成功時照舊寫入快取。
- 驗證：
  - 新增 `tests/test_mis_futures_negative_cache.py`：失敗後 60 秒內不再呼叫 MIS、5 個並行請求只抓一次、成功時清除失敗並快取。
  - 只移除鎖時，並行案例會失敗；在舊程式上 3 案例皆失敗。
  - `tests.test_no_new_silent_exceptions`、`tests.test_fallback_observability` 通過。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 台指期主力契約切換日不再把轉倉算成增倉（D-03）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/tx-oi-rollover`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 D-03，主控查證屬實）：
  - `pulse_extras.compute_tx_oi` 以當日成交量最大契約為主力，再往前找同契約。
  - 換月日次月量超過近月時，前一日次月的 OI（轉倉前、很小）成了基準，`oiChgPct` 出現 +30%～+60% 的假增倉。
  - 這個值會進 Pulse 的「多方增倉」因子，以及決策中心的 flow 特徵。
  - docstring 已宣稱「換月無法對齊時回 None」，但這個情況會對齊成功。
- 修正後行為：前一日的主力契約與當日不同時回 None（沿用既有的 pending 流程）。主力未切換的日子照舊計算。
- 驗證：
  - 新增 `tests/test_tx_oi_rollover.py`（切換日回 None、未切換時 +10% 照算、既有換月情境），切換日案例在舊程式上失敗；
  - 既有 `tests/test_pulse_extras.py` 以 pytest 7 案例通過（該檔為裸函式，unittest 不會收集）；
  - `tests.test_decision_context`、`tests.test_pulse_intel` 通過。
- 影響：每月到期週的換月日，台指期 OI 因子改顯示待更新，不再給假的增倉訊號。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 大盤融資維持率在收盤價不完整時不輸出（CM-01）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/margin-lot-coverage`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 CM-01，主控查證屬實）：
  - `compute_ratio_for_date` 與 `fetch_latest_ratio_live` 的分母是全市場融資金額，分子遇到缺收盤價的股票直接略過。
  - 收盤價回應不完整時，比率被低估且沒有任何標示；即時路徑也沒有任何覆蓋率下限。
- 實測：2026-10-19 以 TWSE OpenAPI 取得 1013 檔融資股，5 檔缺收盤價（停牌），以融資張數計的覆蓋率 99.98%。正常日的偏差約 0.02%，風險在於回應不完整的日子。
- 修正後行為：
  - 新增 `_collateral_with_coverage`，兩條路徑共用；
  - 以官方收盤價計算時，張數覆蓋率低於 `MIN_LOT_COVERAGE = 0.95` 則記錄原因並不輸出；
  - 2004-02-11 前與官方失敗時的 Yahoo 後備維持原有的檔數下限（30／50 檔），不改變歷史口徑、不移除已存的歷史點。這條路徑的覆蓋率仍未記錄，列為未決。
- 驗證：
  - 新增 `test_live_ratio_rejects_incomplete_closing_prices`（缺 2% 照常輸出、缺 10% 拒絕）與 `test_lot_coverage_counts_margin_lots_not_stock_count`，兩者在舊程式上失敗；
  - `tests.test_margin_ratio` 13 案例通過（1 個需網路的整合案例照例略過）。
  - 當下以真實網路呼叫 `fetch_latest_ratio_live`，main 與本分支都因既有的「兩端點交易日不一致」檢查回 None，未能以即時資料做端對端確認。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 持倉合計損益%只用已載價部位計算，未載價明示（PB-07）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/position-total-known-cost`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 PB-07）：
  - `renderPositionList` 的總成本累加全部部位，損益與市值只累加已載價部位，合計損益%因此被低估。例：實際 +10% 顯示 +5%。
  - 「部分價格未載入」只在全部缺價時才出現。
  - `renderPosition` 把未載價的當前個股顯示成損益 0%、市值等於成本。
- 修正後行為：
  - 合計損益%的分母改為已載價部位的成本；
  - 有部分部位未載價時，市值與合計損益後加「（N 檔未載價）」；全部缺價時顯示「價格未載入」；
  - 總成本照舊顯示全部部位，沒有刪減任何欄位；
  - 當前個股未載價時，目前市值與未實現損益顯示 `--`；
  - 已重建 `stock_terminal_v2.html`（只有 `?v=` 雜湊變動）。
- 驗證：
  - 新增 `tests/position_total_known_cost_selftest.js`，在舊程式上重現 +5.00% 而失敗，新程式通過。
  - 既有 `完整審查前端_selftest.js`、`shell_v5_selftest.js`、`台股即時報價_selftest.js` 與 `tests.test_bundle_fresh` 通過。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 策略指標庫遇到缺值回 null，不再產生假訊號（PB-04、PB-05）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/stratlib-missing-values`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 PB-04、PB-05）：`src/screener/strategy_builder_v3.js` 的 `StratLib` 在窗口含缺值（停牌、缺列）時沒有檢查。
  - `kd`、`highest`、`lowest` 的 `Math.max/min` 把 null 當 0：缺值後約 10 根 K 值出現假低檔，N 日最低變成 0。
  - `pctChange` 在缺值當根得到 −100%。
  - `bb` 在均線為 null 時仍計算上下軌，得到約 ±2 倍價格的假值，與 `Backtest.bbLower` 分歧。
- 修正後行為：
  - 依 `Backtest.sma`／`breakout` 的口徑，窗口含非有限值時該根回 null，條件判斷因此不成立；
  - `bb` 在均線為 null 處跳過，下軌與 `Backtest.bbLower` 結果一致；
  - 已重建 `stock_terminal_v2.html`（只有 `?v=` 雜湊變動）。
- 驗證：
  - 新增 `tests/stratlib_missing_values_selftest.js`，涵蓋 N 日高低、漲跌%、40 根含缺值的 KD 不出現假低檔、布林通道與 `Backtest.bbLower` 一致；在舊程式上失敗。
  - 既有 `tests/完整審查前端_selftest.js`、`tests/自訂策略樣本外_selftest.js` 與 `tests.test_bundle_fresh` 通過。
- 影響：含缺值日線的策略組合器與腳本回測，訊號會改變；新訊號才是正確的。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 曝險研究的 Kelly 值照公式回報，上限保留 1x 底（PB-03）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/exposure-kelly-raw`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 PB-03）：`_mode_ceilings` 先把 `λ*` 以 `max(1.0, ·)` 截斷，再把截斷後的值放進 `costAdjustedKellyPct`。公式值 42.5% 或 −66.8% 都會顯示成 100%，與同列 `formula` 字串不符。
- 查核結論：研究文件 `docs/ST_DYNAMIC_LEVERAGE_FIVE_POST_RESEARCH_2026-08-16.md` §6.4 明訂 `λ_research = min(cap, max(1, λ*))`，研究範圍限 1x～2x，所以上限的 1x 底是刻意設計，保留。有誤的只有 Kelly 欄位本身。審查建議的「移除 1x 底」未採用。
- 修正後行為：
  - `costAdjustedKellyPct` 回報未截斷的公式值；
  - 新增 `researchLambdaPct`，標示截斷後實際用於上限的值；
  - `researchCeilingPct` 數值不變；
  - `formula` 字串補上 `max(1,lambda*)`；
  - 前端沒有顯示 `costAdjustedKellyPct`，畫面不變。
- 驗證：
  - 新增 `test_kelly_below_one_is_reported_as_computed_while_ceiling_keeps_1x_floor`，涵蓋 (2%, 20%) 與 (−5%, 25%) 兩種情境，在舊程式上失敗；
  - `tests.test_exposure_lab`、`test_decision_context`、`test_完整審查資料`、`test_曝險壓力` 共 69 案例通過。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 條件期望的法人分箱不再使用當日籌碼（PB-02）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/ce-chip-strict-lag`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 PB-02）：
  - 舊版 `_inst3d_sign` 與 `evidenceAsOf.chips` 用 `籌碼日 <= asOf` 篩選，把交易日 T 的三大法人買賣超放進 T 的分箱。
  - 但 T86 在 T 收盤後才公布，而前瞻報酬以 T 收盤為進場價，所以歷史統計條件用到了進場時還拿不到的資訊。
  - `pitAssumptions` 宣稱已處理公布落後，程式卻沒有位移。
- 修正後行為：
  - 新增 `_chip_known_at_close`，只採用 asOf 之前交易日的籌碼；歷史觀測與線上卡片共用同一函式。
  - `pitAssumptions` 改為描述實際做法。
  - `evaluate_asof_gate` 的籌碼新鮮度門檻與模型版本字串不變。
- 驗證：
  - 新增 `test_same_session_chips_do_not_enter_the_bin`：只有當日籌碼時分箱為 unknown；前一日賣超加當日買超時，以前一日為準。
  - 該案例在舊程式上失敗（`'buy' != 'unknown'`）。
  - `tests.test_conditional_expectation`、`test_conditional_expectation_p1`、`test_完整審查資料`、`test_shadow_multifactor` 共 53 案例通過。
- 影響：研究用卡片（`actionAuthority: none`）。部分標的的法人 3 日分箱與勝率統計會改變，改變後的值才是可執行的條件。
- 發布狀態：未合併、未發布。

---

## 2026-10-19 WaveDeck 回撤鎖定自動全平、急停仍放行平倉（WD-01）

- 基底：`edd97ae53a6a4557d1b917522a3e7ea837a6b040`（origin/main）；分支 `claude/wd-drawdown-flatten`。實作與合併 SHA 待 PR 合併後補記。
- 原因（全專案審查 WD-01）：急停的目的是擋新風險，但舊版三處一起把部位鎖在場內：
  1. `WD_DD_FLATTEN` 預設關閉，當日回撤達上限只急停不平倉；
  2. `risk.evaluate_gate` 在急停或 Halted 時連 EXIT／REDUCE 都拒絕；
  3. `engine.enforce_no_overnight` 在急停時停在 blocked，不留倉截止送不出平倉，部位會過夜。
- 修正後行為（Sam 2026-10-19 選擇「兩者都做」）：
  - `st_link.DD_FLATTEN` 預設開啟，設 `WD_DD_FLATTEN=0` 可改回只急停；
  - 急停或 Halted 時閘門仍拒絕 ENTER_LONG／ENTER_SHORT，只放行 EXIT 與 REDUCE；
  - 不留倉截止在急停中照常經閘門送一次平倉，急停狀態維持不變；`handle_signal` 在急停時拒收所有訊號的行為不變。
- 契約變更與測試：
  - `test_不留倉.test_減倉仍尊重緊急停止` 改寫為 `test_緊急停止只擋新倉_平倉與減碼放行`；
  - `test_策略訊號整合.test_急停時不留倉不自動送單` 改寫為 `test_急停時不留倉仍送平倉一次且維持急停`；
  - 新增 `test_完整審查執行.test_緊急停止中仍執行截止平倉`。
  - 新案例在舊程式上確認會失敗（2 FAIL），新程式通過。
- 驗證：
  - 本機以 repo 根目錄執行 `wavedeck.tests` 的 exec_md、request_guard、smoke、不留倉、完整審查執行、策略HTTP、策略訊號整合，共 90 案例，連續兩次全數通過。
  - 第一次執行時 `test_策略HTTP` 的過大 JSON 案例出現一次 WinError 10053（連線中止）；單獨執行與後續兩次全組皆通過，修改前的 main 單獨執行也通過，判定為與本修改無關的偶發失敗，未修改該測試。
- 發布狀態：未合併、未發布。

---

## v5.0 修訂 — 2026-10-19 兩份新文件改用中性路徑，恢復分享封存掃描（候選，未發布）

基底 `edd97ae53a6a4557d1b917522a3e7ea837a6b040`（main）；分支 `claude/docs-abs-paths`，只改文件。

**問題**：PR #218、#219 新增的 `docs/當日分時修復.md`、`docs/加權行情錯誤8D.md` 各有一處絕對使用者路徑（`C:/Users/...`），被分享封存的內容掃描器擋下（`windows-user-path`、`mac-user-path`），使 main 上 `tests.test_dist_scrub.TestDistScrub` 的 `setUpClass` 整組失敗。與 PR #208 修過的是同一類問題；兩個 PR 的局部驗證計畫沒有涵蓋分享封存，所以 CI 是綠的。

**處理**：把兩處路徑改為 `<AI-Workspace>/...`，語意不變，不放寬掃描器。

**驗證（本機 targeted）**：`tests.test_dist_scrub` 12 項通過。

**防再發建議（未實作）**：倉庫內 `docs/` 新增或修改時，驗證計畫一律帶上分享封存掃描案例；或在提交前以 `scripts/build_dist.py` 的同一掃描器檢查 `docs/`。

發布狀態：只改文件，未合併、未部署。

---

## v5.0 修訂 — 2026-10-19 本機 ST 後端拒絕非 loopback 的 Host 標頭（候選，未發布）

基底 `edd97ae53a6a4557d1b917522a3e7ea837a6b040`（main）；分支 `claude/st-host-check`，`VERSION` 維持 5.0。來源：全專案審查 SEC-01。

**問題**：後端只綁 loopback，但 `server/server.py` 從不檢查 `Host` 標頭。惡意網頁以 DNS rebinding 把自己的網域解析到 127.0.0.1 後，對 `http://<惡意網域>:18432/` 的請求在瀏覽器看來是同源，可以讀到 GET 回應（例如 `/research/portfolio`、`/decision/context`、`/alert/config`）。寫入有 `Origin` 檢查而不受影響。WaveDeck 已有主機白名單，ST 後端沒有。

**處理**：`server/http_boundary.py` 新增 `is_local_host_header`，只接受 `127.0.0.1`、`localhost`、`[::1]`（可帶本服務實際綁定的埠）；`Handler.parse_request` 對所有方法套用，不符回 403。比對的是伺服器實際綁定的埠（測試伺服器使用隨機埠）。正式站閘道轉發時會把 `Host` 改寫成 `127.0.0.1:<後端埠>`（`private_web_gateway.py` `_proxy`），不受影響。沒有 `Host` 標頭的非瀏覽器 HTTP/1.0 呼叫維持放行。

**驗證（本機 targeted）**：新增 `tests/test_st_host_header.py` 4 個案例（規則單元測試，以及啟動真實 Handler：loopback 主機回 200、外部網域的 GET 與 POST 回 403）；外部網域案例在舊 `server.py` 上失敗。會實際啟動 Handler 或涉及 Host／閘道的 32 個測試模組 396 項中，只有 `tests.test_dist_scrub` 的 `setUpClass` 失敗，原因與本次無關：main 上 `docs/加權行情錯誤8D.md`、`docs/當日分時修復.md` 含絕對使用者路徑而被分享封存掃描器擋下（另開 PR 修正），因此本計畫不列該案例。**未驗證**：真實瀏覽器的 DNS rebinding；正式站經閘道的實機請求。

發布狀態：候選，未合併、未部署。

---

## v5.0 修訂 — 2026-10-19 持倉張數換算股數不再少 1 股（候選，未發布）

基底 `edd97ae53a6a4557d1b917522a3e7ea837a6b040`（main）；分支 `claude/position-lot-rounding`，`VERSION` 維持 5.0。來源：全專案審查 PB-06。

**問題**：`src/core/position_v2.js` `submitPosition` 以 `String(parseFloat(s) * 1000)` 把張數換成股數，`setPosition` 再以 `parseInt` 取整。浮點誤差使 32.3×1000＝32299.999…，存成 32,299 股；0.1 至 999.9 張（0.1 步）有 46 筆、0.01 步有 590 筆少 1 股，持倉成本與損益隨之偏差。

**處理**：新增 `lotsToShares`，以 `Math.round(lots × 1000)` 換算到整股；非數字輸入原樣交給 `setPosition` 拒絕（行為不變）。重建追蹤中的 `stock_terminal_v2.html`（差異只有各模組的快取版本雜湊）。

**驗證（本機 targeted）**：新增 `tests/position_lot_rounding_selftest.js`，以 vm 執行正式 `lotsToShares`，0.1 至 999.9 張與 0.01 至 999.99 張共 109,998 筆全部正確；舊程式碼上失敗。`tests.test_bundle_fresh` 通過。**未驗證**：瀏覽器內實際送出表單；已存入 localStorage、少 1 股的既有持倉不會自動更正（使用者需重新儲存）。

發布狀態：候選，未合併、未部署。

---

## v5.0 修訂 — 2026-10-19 週間官方休市日改以官方日曆判定（候選，未發布）

基底 `edd97ae53a6a4557d1b917522a3e7ea837a6b040`（main）；分支 `claude/tw-calendar-closed-days`，`VERSION` 維持 5.0。來源：全專案審查 CAL-01、QB-03、PB-08、EW-01 同類（`AI-Workspace/docs/stock-terminal/全專案弱點與公式審查-20261019/`）。

**問題**：多處以「只跳過週末」推算台股交易日，不查 `server/台股交易參考.json` 已收錄的官方休市日（2026 年 25 日）。
- `guard_tw_quote`（`server/market_routes.py`）把週間休市日 09:00–13:30 當成盤中，所有 `/twquote`、`/quote`、`/quote-batch` 的台股報價被清空並顯示「成交資料尚未更新」。
- 「最近收盤日」`_last_tw_close_day` 在 `conditional_expectation.py`、`touxin_5d.py`、`peak_observation.py` 各一份，休市日當天會被當成收盤日；`conditional_expectation.evaluate_asof_gate` 與 `chip_path_state.py` 的籌碼落後計數把假日算進交易日，連假後籌碼被誤判逾期。
- `postmarket_report._next_tw_session_date`（盤後報告的「明日」）與 `signal_digest._digest_due`（每日摘要）也只跳過週末。

**處理**：`台股交易參考.py` 新增 `is_closed_day`、`last_close_day`、`next_session_day`（以既有 `session()` 判定；未涵蓋年度仍只看週末，維持既有行為），上述各處改呼叫它們。三份 `_last_tw_close_day` 保留函式名稱，其他模組的匯入不變。

**既有測試的期望調整（有理由）**：`tests/test_stock_signals.py::test_digest_once_per_day_after_close` 原以 2026-09-25 為日期，那天是官方休市日（中秋節）；新行為在休市日不發摘要是本次修正的目的。該案例只驗「收盤後每日一次」，改用交易日 2026-09-24，斷言不變；另新增 `test_digest_is_not_sent_on_an_official_weekday_holiday`。

**驗證（本機 targeted）**：新增 `tests/test_tw_calendar_closed_days.py` 6 個案例（休市日判定、最近收盤日、三份複本、下一交易日與盤後「明日」、報價防線在休市日保留最後成交而交易日仍拒絕跨日價、籌碼落後不計假日），舊程式碼上全部失敗。引用相關模組的 22 個測試模組 309 項通過，靜默例外棘輪通過。**未驗證**：休市日當天的實機畫面；2027 年起需更新官方日曆 JSON 才能涵蓋。

發布狀態：候選，未合併、未部署。

---

## v5.0 修訂 — 2026-10-19 條件期望卡「MaxDD Q90」改取回撤尾端（候選，未發布）

基底 `edd97ae53a6a4557d1b917522a3e7ea837a6b040`（main）；分支 `claude/ce-maxdd-tail`，`VERSION` 維持 5.0。來源：全專案審查 PB-01（`AI-Workspace/docs/stock-terminal/全專案弱點與公式審查-20261019/`）。

**問題**：`server/conditional_expectation.py` `aggregate_horizon_stats` 以 `_quantile(drawdowns, 0.90)` 計算 `maxDrawdownQ90Pct`。回撤是帶號值（0 為無回撤、越負越糟），升冪排序後的第 90 百分位落在最溫和的一端，只要超過一成樣本沒有回撤就恆為 0。卡片「MaxDD Q90」因此一直顯示 0，與 `docs/FINDINGS_CONDITIONAL_EXPECTATION_P0.md` 範例（−3.1）所表達的「90% 樣本的最大回撤不劣於 X」不符。

**處理**：改為 `_quantile(drawdowns, 0.10)`，即帶號數列的第 10 百分位（等價於 −「絕對回撤的第 90 百分位」）。欄位名稱、前端顯示與資料契約不變。

**驗證（本機 targeted）**：新增案例 `test_max_drawdown_q90_reports_the_adverse_tail_not_the_mildest_end`（20 筆樣本，一半為 0、其餘 −1 至 −10，應得 −8.0）；同一組資料在舊程式回傳 0.0。`tests.test_conditional_expectation` 11 項通過，`tests/conditional_expectation_v5_selftest.js` 通過。**未驗證**：正式卡片在真實資料上的新數值。

發布狀態：候選，未合併、未部署。

---

## v5.0 修訂 — 2026-10-17 加權行情基準與來源優先（本機候選）

修正加權主圖與行情列將 10/16 的 47111.26 配上 10/14 收盤而顯示 -1514.57 的錯誤。當日日 K 缺值時，改依現價交易日選前收；同日正式行情可校正晚 25 秒的 Yahoo 備援。保留跨日、同品質時間排序與台指期既有行為。缺現價時價格、日期與前收一起退回最後有效日 K；metadata 未提供日期時不推定。

版本維持專案 `5.0`，資源識別更新為 `73c964edc727`；提交 SHA 與發布狀態見同版 [8D 紀錄](加權行情錯誤8D.md) 所列發布證據。局部驗證：11 組根因／邊界、原 25 組行情保全、兩順序 × 兩期間的 4 組獨立市場真值完整頁面與原三標的直橫式畫面均通過。同供應商有界審查的兩項 P2 已修正。尚未以本機候選證據代替兩站部署結果；未跑全套。

---

## v5.0 修訂 — 2026-10-16 發布狀態補記（58c36aec）

基底 `58c36aeca1b6d080891059b961e37d9abb197209`（main）；分支 `claude/st-release-status-3`，只補記發布狀態，不改程式。歷史段落不覆寫，以下為後續狀態。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `58c36aeca1b6d080891059b961e37d9abb197209` | PR #214 補齊兩條缺收據的 Yahoo 寫入路徑、舊形狀證據表偵測、修正被 #206 弄壞的 `update()` 測試；PR #215 `merge_source_bars` 寫入交易涵蓋讀取（跨程序競態）與證據層錯誤以 `SAVEPOINT` 降級 | 2026-10-16 08:24 前後 | 已發布到本機與正式後端；前一版為 `172d378f` |

**依據（實測，不是推定）**：發布後查詢本機 `127.0.0.1:18432/health` 與 `/health/live`、正式後端 `127.0.0.1:18435/health`，`runtimeCommit` 皆等於目標 SHA；閘道 `/gateway/health` 為 `ok`、`upstream` 為 true。發布前（08:21）確認兩端沒有 queued／running 的更新工作；正式站停止後以 `backup-databases.py` 備份 14 個 SQLite 並逐表核對；promote 後 `data/` 保留 82 項；正式庫日線 1,494,785 筆、本機 1,459,599 筆，`quick_check` 皆 ok。本機第一次查詢沒有回應，是啟動前的版本同步花得比等待時間久，之後正常。

**對先前「候選，未發布」與「尚未在正式庫建立」的後續狀態**：上列 PR 的修正已隨本版發布。先前記載的「日線來源收據表在正式庫尚未建立」已不成立：這些表在 2026-10-15 `172d378f` 運行期間因真實更新而建立（時間點在先前的發布狀態補記之後）。本次發布後核對（唯讀）：正式與本機庫的四張證據表（`bar_source_receipts`、`bar_first_ingest`、`bar_reinsert_ingest`、`bar_revision_ingest`）定義皆含 `WITHOUT ROWID`，各有 12 個觸發器；正式庫有 2 筆收據（2330、^TWII）與 2 筆首次寫入關聯，本機有 1 筆（^TWII），每筆原始回應約 3 KB（遠小於 5y 回補的 67 KB 估算，因為是每日 5d 更新）；沒有孤兒關聯、沒有指向不存在日線的關聯；新版寫入的 `sourceReceipt` 旗標皆為 `stored`、沒有錯誤。其餘既有 Yahoo 寫入紀錄是舊版（無旗標），屬預期。

**未驗證（不可視為已驗收）**：
- 閘道與 Tailscale 端的版本：需要 Owner token，未能確認該端的 SHA。
- 大盤標頭與小框、右軸標籤的實機畫面：只有前端自測與後端案例，沒有瀏覽器視覺驗收。
- 證據表在大量寫入下的實際增長量：目前只有 3 筆真實資料；全市場回補前須先決定壓縮或限制。
- 本版 `BEGIN IMMEDIATE` 與 `SAVEPOINT` 在真實跨程序競態下的行為：只有同程序內第二連線的案例與逐一陳述句注入，尚未在正式環境被觸發。
- `log_once` 仍在持鎖交易內輸出（審查所報的低度項目，未處理）。

證據：`<AI-Workspace>/docs/stock-terminal/指定版本發布-58c36aec/`（發布紀錄、備份證據）。

---

## v5.0 修訂 — 2026-10-16 merge_source_bars 兩個缺口：跨程序競態與證據層錯誤降級（候選，未發布）

基底 `a6fa19888f562f44468b04c097e28e336ee211c9`（main，含 PR #214）；分支 `claude/st-txn-gaps`，`VERSION` 維持 5.0。只改 `server/datastore.py` 的 `merge_source_bars` 與測試。

這是 init_db／交易區段審查留下的兩個缺口（見 PR #214 的修訂段落）。

**缺口 1：`existing` 在寫入交易之外讀取，跨程序同時更新同標的同日會整批失敗（既有行為，自 2026-09-29 的 `6e57d70` 就存在）。** `_db_write_lock` 只在行程內互斥；legacy 交易語意下 SELECT 與 DDL 不開交易，隱式 BEGIN 要到第一個 INSERT 才發出。另一個程序（`scripts/個股研究資料更新.py`、`datastore` CLI）在讀 `existing` 與第一個 INSERT 之間提交同一天，本次的 INSERT 會撞主鍵、整批以 `IntegrityError` 回復，呼叫端顯示更新失敗。處理：取得鎖並建立連線、做任何讀取或建表之前先 `BEGIN IMMEDIATE`，讀取與所有寫入在同一個寫入交易內；等待對方提交後再讀，該日自然視為未變動。兩張帳本表的建立因此也進入交易，失敗時一併回復（原本會在失敗後留下空表）。

**缺口 2：證據層的 sqlite 錯誤會讓整批日線寫入失敗，與「不得拖累既有寫入」的契約字面不符。** 這是設計取捨，本次採用契約已寫明的方向：**證據層失敗只回復證據本身，日線照舊寫入並標記**。以 `SAVEPOINT` 隔離每一個證據步驟（保存收據、首次寫入關聯、修訂關聯）；失敗時 `ROLLBACK TO` 一併撤銷該步驟建立的表、觸發器與列，標記 `sourceReceiptError`（含例外型別），並以 `log_once` 留下限頻記錄。預期的證據錯誤（`ValueError`、`TypeError`、`KeyError`、`IndexError`、`AttributeError`、`OverflowError`、`sqlite3.Error`）才降級；`KeyboardInterrupt` 等仍整個交易回復。新增旗標值 `partial`：收據已保存，但後續某一步證據失敗，部分日線沒有關聯。**語意變更（需知悉）**：以前證據層的 sqlite 錯誤是全有或全無，現在改成日線優先、證據可能缺漏並如實標示；`ROLLBACK TO` 或 `RELEASE` 本身失敗（例如磁碟錯誤）仍會讓整個交易回復。`BEGIN IMMEDIATE` 是 `SAVEPOINT` 的前提：交易已開啟時它是巢狀的，不會在釋放時提前提交。

**驗證（本機 targeted，非完整套件）**：
- 新增 3 個案例（共 21 項收據案例）：另一連線持有寫入交易並已寫入同日時，merge 等待、提交後視為未變動而不失敗（**此案例在舊程式碼上重現 `IntegrityError`**；第一版案例因測試庫是全新的、DDL 恰好需要寫入鎖而沒有重現，已改為先建立帳本表以貼近正式庫）；證據表欄位不符時日線照舊寫入並標記；失敗步驟的證據隨 SAVEPOINT 撤銷。降級案例在舊程式碼上失敗。
- 對 `merge_source_bars` 的每一個 `execute` 逐一注入 `sqlite3.OperationalError`（冷庫新增 45 個點、暖庫含衝突 35 個點，共 80 點）：例外往外傳時，資料庫與執行前逐表逐列相同（28 點）；沒有例外時，日線全數寫入、每筆證據列都指向存在的收據與日線、`integrity_check` ok，也沒有『注入失敗卻回報 stored』（52 點降級）。不變式違反 0。
- 所有引用 `fetch_yahoo_daily`／`upsert_bars`／`merge_source_bars`／`_fetch_remote`／`datastore.update`／`backfill_universe`／`ingest_receipt`／`receipt_out` 的測試模組（25 個）379 項通過；`tests.test_no_new_silent_exceptions` 通過。

**未驗證**：兩個真實 OS 程序在正式資料量下的競態（案例用同程序內的第二連線模擬跨程序的鎖語意）；`BEGIN IMMEDIATE` 對寫入等待時間的實際影響（每次 merge 的寫入鎖多涵蓋一次 `SELECT existing`，備份副本上單檔日更約 22 ms，未重新量測）；`log_once` 仍在持鎖交易內輸出（審查所報的低度項目，本次未改）。

發布狀態：候選，未合併、未部署。正式與本機仍為 `172d378f`；證據表尚未在正式庫建立。

---

## v5.0 修訂 — 2026-10-16 init_db／交易區段審查結果與收據補齊（候選，未發布）

基底 `e3a6744f6c6f24ca35a8d4430c4e862e303bb7eb`（main，已含發布的 `172d378f`）；分支 `claude/st-receipt-callers`，`VERSION` 維持 5.0。

**審查範圍與完成度（誠實記錄）**：六個面向（`init_db` 與遷移、交易邊界、併發與鎖、舊庫相容與周邊工具、證據邏輯、呼叫端）。原定以 workflow 讓六位審查者各自實驗、每個發現再由兩位獨立查證者覆核。執行中連續三次遇到使用量限額，**只有三個面向由獨立審查者完成：交易邊界、證據邏輯、呼叫端**；其發現的雙重查證沒有執行，下列「成立」是我（主控）逐條對照程式碼並實驗後的判定。另外三個面向（`init_db` 與遷移、併發與鎖、舊庫相容與周邊工具）**改由我直接審查並實驗完成**（沒有獨立審查者，也沒有反方查證，同作者自審），結果見下方。

**交易邊界面向的結論（審查者以 78 個故障注入情境、逐一陳述句注入共 84 個點、10 次 `os._exit` 真實程序中斷實測）**：`merge_source_bars` 一律整次回復或整次提交，沒有「bars 有但證據沒有」「證據有但 bars 沒有」「只寫入部分日期」；兩張帳本表（`bar_source_revisions`、`bar_ingest_runs`）的建立在交易外、失敗後可能留下空表（無害）；四張證據表與觸發器在第一個寫入之後建立，隨失敗回復；`counts` 與資料庫實況一致；持鎖期間沒有網路；備份副本上單檔日更約 22 ms、新標的 10 年回補約 57 ms。**這項結論依據審查者的實驗輸出，我只重跑了其中與本次修正有關的部分。**

**後補三個面向的結果（我直接審查與實驗，2026-10-16；在 `e3a6744` 上）**：
- **`init_db` 與遷移：沒有發現問題。** 合成 v1 舊庫（`bars` 主鍵為 `(symbol, ts)`、市場欄為空或 NULL）遷移後 `user_version`=3、主鍵為 `(market, symbol, ts)`、市場補成 TW，並產生 `.pre-market-key-v2.bak` 與 `.pre-quality-v3.bak`；遷移後可正常附收據寫入。v2 且已有品質表的庫升級時建立備份、`bars` 逐列位元不變；`init_db` 第二次執行冪等（備份數不變）；`user_version` 較新時拒絕降版；在 `DROP TABLE bars_legacy_v1` 注入失敗後整個遷移回復（`bars` 位元不變、無殘留 legacy 表），再次執行可完成。在 354 MB 真實庫備份副本上 `init_db` 0.02 至 0.2 秒，無任何結構變動。**資訊（既有行為，非本次引入）**：v1 遷移用 `INSERT OR REPLACE`，若舊庫有「同標的同日、市場為空值與 TW 各一筆」，遷移後只留一筆（實驗中保留 TW 那筆）；遷移前已建立 `.bak` 可還原。首次遷移時 `init_db` 在持有全域寫入鎖期間備份整個資料庫（大庫會較久，一次性）。
- **併發與鎖：沒有發現問題。** 寫入 `market.db` 的路徑只有 `datastore`（`merge_source_bars`、`upsert_bars`、`init_db`）、`個股還原研究.save_snapshot`、`台股日線.import_day`，皆取同一把 `_db_write_lock`；持鎖期間可達的呼叫沒有再取同一把（非可重入）鎖的路徑，無死結。`early_warning` 等模組寫的是 `market_signals.db`，不同檔案。8 執行緒同時對同標的重疊日期（半數製造衝突）寫入，重跑 3 次：無錯誤、`bars` 5、首次證據 5 且每日唯一、修訂 1、收據 2、修訂關聯 1、`integrity_check` ok。實驗中曾出現一次 `no such table: bars`，經查是我的測試腳本用 `mock.patch` 在多執行緒各自改 `DB_PATH` 造成（先結束者把它還原），不是產品問題；改為全域設定後排除。**未量測**：`台股日線.import_day` 在單一交易內寫約 1,400 檔而持鎖數秒，對 Yahoo 更新的等待影響；跨程序壓力（見下方未處理項）。
- **舊庫相容與周邊工具：沒有發現問題。** 全專案對 `sqlite_master`／`table_info` 的使用都是「某表是否存在」的成員檢查，新增表與觸發器不影響它們。對含四張證據表與 18 個觸發器（含原有 6 個官方收據觸發器）的 354 MB 庫實跑：發布前備份工具 `backup-databases.py` 的 `signature`（28 張表）與本機同步工具 `local_release.sqlite_backup`（`integrity_check` ok、備份後簽章一致、觸發器與證據列保留）皆通過，各約 19 秒。`market.db` 與其 `-wal`／`-shm` 本來就在分享封存的排除清單。舊形狀證據表由本 PR 的形狀檢查處理。

**成立並已修正（本 PR）**：
1. **中：兩條實際寫入 Yahoo 日線的路徑沒附來源收據**（`server/個股還原研究.py` 的 `append_missing`、`scripts/個股研究資料更新.py` 的 `--benchmark-range`）。我以 grep 核對全部呼叫端屬實：新增日線沒有首次來源證據，違反「事後可稽核每一筆新增日線」。`fetch_yahoo_daily` 的 `with_research` 路徑同樣會填收據。處理：兩處都傳 `receipt_out`，並以同一份收據寫入。
2. **低：舊形狀（無 `WITHOUT ROWID`）的證據表會被沿用，不可覆寫保證靜默失效**（`CREATE TABLE IF NOT EXISTS` 不升級）。處理：建表後檢查定義，不符就走既有的 `rejected` 路徑（日線照寫、標記、限頻記錄），不沿用。正式與本機庫目前都沒有這些表，這是防止開發或測試資料庫的潛在風險。
3. **低：收據核對的例外白名單漏接 `OverflowError`。** 已補。
4. **審查過程中另發現：`main` 上有一個既有測試被 PR #206 弄壞**——`tests/test_個股研究資料更新.py::test_stale_benchmark_fetches_enough_history` 以 `assert_called_once_with('^TWII','TW','6mo')` 驗證 `update()`，而 #206 讓 `update()` 多傳 `receipt_out`。局部 CI 只跑計畫內的案例，所以當時是綠的。處理：改為驗證位置參數並斷言有傳入收據字典。為排除同類問題，我把所有引用 `fetch_yahoo_daily`／`upsert_bars`／`merge_source_bars`／`_fetch_remote`／`datastore.update`／`backfill_universe`／`ingest_receipt`／`receipt_out` 的測試模組（25 個）全跑過，只有這一項失敗。

**審查者所報、未經獨立查證、本 PR 不處理（留待決定）**：
- 低：`existing` 讀取在寫入交易之外，跨程序同時更新同標的同日會讓整批以 IntegrityError 回復（審查者在 git 歷史確認自 2026-09-29 的 `6e57d70` 就存在，非收據 PR 引入；建議 `BEGIN IMMEDIATE`，觸及核心寫入路徑，需單獨評估）。
- 低：證據表的 sqlite3 錯誤不在「核對失敗仍寫入」範圍，會讓整批失敗（原子、不損毀，但與契約字面不同；需先決定要原子失敗還是降級，降級可用 `SAVEPOINT`）。
- 低：`log_once` 在持鎖且未提交的交易內輸出（stdout 失敗會使整筆回復；記錄可能先於提交）。
- 低或資訊：同值重插保存了無人引用的原始回應卻標 `stored`；`bar_first_ingest` 記錄的是「首次留有證據的寫入」；`json.dumps` 比較對 int／float 寫法敏感；修訂首次出現時無收據則之後補不上關聯；`log_once` 限頻 key 會蓋掉不同標的或原因；「不可覆寫」不涵蓋 `DROP TABLE`／`ALTER`／`writable_schema`；`observedAt` 在等鎖前取得、帳本 payload 缺 `queryCoverage`；證據表沒有故障回復的測試。

**驗證（本機 targeted，非完整套件）**：新增 3 個案例（兩條補收據路徑、舊形狀證據表不沿用），收據模組 18 項；25 個相關測試模組共 376 項全通過。變異檢查：把兩處呼叫端改回原狀、移除形狀檢查，三個新案例皆失敗。**未驗證**：真實 Yahoo 回應、這兩條路徑在正式環境的實際觸發頻率；斷電時 `synchronous=NORMAL` 的耐久性（只用程序中斷模擬）；全市場回補時證據表與 WAL 的實際增長量；後補三個面向沒有獨立審查者與反方查證。

發布狀態：候選，未合併、未部署。正式與本機仍為 `172d378f`。

---

## v5.0 修訂 — 2026-10-15 啟動器測試對齊 10/13 契約（候選，未發布）

基底 `e27eee97534bd76941782dc2d58b76cdf8ec00bf`（main）；分支 `claude/st-launcher-test`，`VERSION` 維持 5.0，**不改啟動器與任何產品程式，只改 `tests/test_launcher_cmd.py`**。

**判定（先驗證，再改測試）**：2026-10-13 的提交 `b3bdcf7` 把 `START_LOCAL_AND_WEB.cmd` 改成無條件 `call START_TIP.cmd -NoBrowser`，本機狀態改由受管的 `scripts\start_local.ps1 -CheckOnly`（核對受管版本、程序身分、綁定、埠與目錄）判定，並移除啟動器自己的「背景啟動後輪詢 40 次」。`tests.test_launcher_cmd` 仍照舊契約，3 個案例在乾淨 main 上失敗。先前懷疑新流程在冷啟動時 `START_TIP.cmd` 不返回而卡住網站；**2026-10-15 在真實終端機分頁實測：本機停止後執行 `START_LOCAL_AND_WEB.cmd --no-browser`，13 秒返回（12:17:33→12:17:46），印出「本機 ST 已就緒」、`Local : UP`、`Web : UP`，啟動器結束後服務仍在**。2026-10-14 觀察到的「不返回」是在擷取輸出的管線下發生（推測為背景程序繼承管線控制代碼，未另行重現）。結論：啟動器沒有退化，是測試過時。

**測試改動（保留原有保護，不刪斷言以求通過）**：
- 新增 `START_TIP.cmd` 替身（啟動器以 `%~dp0` 呼叫同資料夾的檔案）與 `powershell -File start_local.ps1 -CheckOnly` 分支；來源必須恰有一次 `call START_TIP.cmd -NoBrowser`、一次受管 `-CheckOnly`、恰一個閘道 JSON 查詢；外部命令清單改為 powershell 5、schtasks 1、start 1。
- 啟動器若自行查本機 `18432/health` 即為未核准請求（HTTP 邊界替身只核准閘道），以防倒退回舊流程。
- 原「本機 `runtimeCommit` 必須是完整字串 SHA」的保護，移到受管腳本真正使用的 `Test-LocalHealth`（`-FunctionsOnly` 載入，真 PS 5.1）：必須與已安裝 SHA 完全相同（大小寫、換行、長度、型別），並核對 `status`、綁定位址、埠、目錄與 Python。
- 網站輪詢仍為 20 次（保留）；本機偵測式輪詢 40 次已隨 `b3bdcf7` 移除，改由 `start_local.ps1` 內 60 次、每次 0.5 秒的就緒等待；測試明確斷言啟動器內不再有 `GEQ 40` 與 `:wait_local`，等待命令（stdin 導向仍有效）改驗單一處。
- 新增案例：本機入口失敗時網站仍被啟動並如實回報本機 DOWN；冷啟動時本機入口先於任何網站步驟；超長（>200 KB）閘道 health 不觸發重啟。原兩個超長「本機」health 案例改為閘道版本。
- 共 29 項（原 18 項加 11 項）。

**驗證（本機 targeted；非完整套件）**：`tests.test_launcher_cmd` 29 項通過；連帶的 `tests.test_dist_scrub...test_review_regressions_run_from_the_actual_single_machine_share`（從分享封存內執行這組測試）通過。變異檢查 6 項皆被抓到：移除 `call START_TIP`、本機永遠視為 UP、`Test-LocalHealth` 放寬為不分大小寫、`Test-LocalHealth` 不核對綁定位址、本機入口失敗就中止、網站輪詢改 40 次（其中「入口失敗就中止」一項第一版案例沒抓到，因網站原本就在線；已改為網站需被啟動的情境後抓到）。

**未驗證**：真實 `START_TIP.cmd`／`start_local.ps1` 與替身的差異（替身只模擬結果）；多螢幕、UAC、非 Windows Terminal 主控台下的冷啟動；啟動器的網站端排程工作在真機上的完整流程（本次真機只涵蓋「網站已在線」的分支）。

發布狀態：候選，只改測試，未合併、未部署；不影響已發布的 `172d378f` 執行行為。

---

## v5.0 修訂 — 2026-10-15 發布狀態補記（172d378f）

基底 `172d378f986e4eac1506e176e7f9572b64ed4d52`（main）；分支 `claude/st-release-status-2`，只補記發布狀態，不改程式。歷史段落不覆寫，以下為後續狀態。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `172d378f986e4eac1506e176e7f9572b64ed4d52` | PR #208 發布狀態補記與 8D 報告路徑修正、PR #209 日線來源收據證據表防覆寫（Codex 第二意見三項）、PR #210 大盤案例改經正式 `MarketData.refresh` | 2026-10-15 04:56 前後 | 已發布到本機與正式後端；前一版為 `d586f9af` |

**依據（實測，不是推定）**：發布後查詢本機 `127.0.0.1:18432/health` 與正式後端 `127.0.0.1:18435/health`，`runtimeCommit` 皆等於目標 SHA；閘道 `/gateway/health` 為 `ok`、`upstream` 為 true。發布前確認兩端沒有 queued／running 的更新工作；正式站停止後以 `backup-databases.py` 備份 14 個 SQLite 並逐表核對；promote 後 `data/` 保留 82 項，正式庫日線 1,492,443 筆、`quick_check` ok。

**對先前「候選，未發布」段落的後續狀態**：2026-10-15 的 Codex 第二意見三項修正（日線來源收據、大盤案例）已隨本版發布；先前標示「候選」者以此為準。

**未驗證（不可視為已驗收）**：
- 閘道與 Tailscale 端的版本：需要 Owner token，未能確認該端的 SHA。
- 日線來源收據的三張證據表在正式庫**尚未建立**（已查：沒有 `bar_source_receipts`、`bar_first_ingest`、`bar_revision_ingest`、`bar_reinsert_ingest`）；會在第一次真的新增日線並附收據時以 `WITHOUT ROWID` 定義建立。第一次建表在運作中的鎖等待、真實 Yahoo 回應大小與增長量皆未驗證；全市場回補前須先決定壓縮或限制。
- 大盤標頭與小框、右軸標籤的實機畫面：只有前端自測與後端案例，沒有瀏覽器視覺驗收。
- 仍未解的獨立問題：`tests.test_launcher_cmd` 與 10/13 重寫的 `START_LOCAL_AND_WEB.cmd` 契約不一致，冷啟動時 `START_TIP.cmd` 是否返回未在真實主控台驗證，待 Codex 判定；Codex 指出但未處理的 `init_db`／交易區段完整審查與舊庫相容性。

證據：`<AI-Workspace>/docs/stock-terminal/指定版本發布-172d378f/`（發布紀錄、備份證據）。

---

## v5.0 修訂 — 2026-10-15 大盤案例：Codex 第二意見三項修正（候選，未發布）

基底 `719b6dcd35519b5d99341b18b43cdd551f25125d`（main）；分支 `claude/st-index-tests`，`VERSION` 維持 5.0，不改產品程式。

Codex（`codex-cli 0.153.4`，唯讀封包審查，跨供應商）對已合併的 PR #205 提出 3 項發現；審查自評「材料不足」（封包只有差異），內容作為線索，逐條對照程式碼後全部成立：
1. **案例 12、13 從人工呼叫監聽函式開始，沒有經過正式更新入口。** 成立。處理：載入正式 `src/core/market_data_v5.js`，以 `MarketData.refresh()` 取 `/market/snapshot`，由正式 `publish` 發出 `marketData` 事件；新增案例 14（取數失敗不渲染、不覆寫標頭）。
2. **昨收線斷言檢查的是事件前（`symLoaded`）就建立的線。** 成立：`marketData` 監聽只更新標頭與小框，線由 `symLoaded` 階段畫。處理：移除案例 12 對該線的斷言，改為斷言取數入口實際被呼叫一次；虛線仍由 `symLoaded` 的既有案例涵蓋。
3. **文件案例數與證據記載不一致。** 成立。處理：8D 報告 D5 更正為前端 11→14 組、後端新增第 7、8 個；D6 標明本次沒有 `verification_gate` 執行識別，歷史執行識別只對應當時的結果。

驗證（本機直接執行，不是 `verification_gate`）：前端 14 組、後端 8 個通過。變異檢查：移除 `MarketData.refresh` 內的 `publish`、把差額改成 Yahoo 昨收、把標頭昨收改成 Yahoo 值，案例 12 皆失敗。**未驗證**：瀏覽器實機畫面。

發布狀態：候選，只改測試與文件，未合併、未部署。

---

## v5.0 修訂 — 2026-10-15 日線來源收據：Codex 第二意見三項修正（候選，未發布）

基底 `719b6dcd35519b5d99341b18b43cdd551f25125d`（main）；分支 `claude/st-receipt-hardening`，`VERSION` 維持 5.0。

Codex（`codex-cli 0.153.4`，唯讀封包審查，跨供應商）對已合併的 PR #206 提出 3 項有證據的發現；審查自評「材料不足」（封包只有差異，缺 `init_db` 與交易區段全文），所以驗證器不採納為正式結果，內容作為線索，**逐條對照程式碼並重現後**全部成立：
1. **高：指定 rowid 的 `INSERT OR REPLACE` 可繞過不可覆寫保護。** 在隔離的 SQLite 實測重現：`BEFORE INSERT` 觸發器只檢查業務主鍵，指定既有 rowid 且給新的 `receipt_id` 時，舊收據被直接取代（`A` 變成 `B`），DELETE 觸發器不會觸發。處理：四張證據表一律 `WITHOUT ROWID`，沒有隱藏 rowid 可用。這三張表在正式庫與本機庫都還不存在（已查），所以不需遷移；若其他環境曾以舊定義建過表，`IF NOT EXISTS` 不會改定義，須人工處理（目前已知無）。
2. **中：bars 被刪後以不同值重插，原首次證據仍指向舊值收據、新收據沒有任何關聯。** 成立。處理：保留原首次證據；值不同時另存不可覆寫的 `bar_reinsert_ingest`（市場、標的、時間、run、收據、寫入時間、內容），值相同則視為同一筆。
3. **中：收據結構錯誤（如 `sourceSymbol` 型別錯、雜湊正確但 JSON 結構無效）會丟出 `TypeError`／`KeyError`，中斷既有寫入。** 成立（先前只攔 `ValueError`）。處理：收據核對的預期格式錯誤（`ValueError`、`TypeError`、`KeyError`、`IndexError`、`AttributeError`）一律標記 `rejected` 並照舊寫入；資料庫錯誤仍往外拋。

新增 3 個案例（共 17 項）：重插不同值保留兩條追溯、證據表沒有 rowid 且 `INSERT OR REPLACE` 指定 rowid 被拒、兩種畸形收據仍寫入並標記。變異檢查：改回有 rowid 的表並縮小例外範圍，新案例共 7 個子案例失敗。驗證：17 項收據案例加既有 5 組直接依賴案例共 60 項通過（本機 targeted）；在發布前備份副本上重跑演練，結果與先前一致（寫入、不重複保存、既有 bars 位元不變、`quick_check` ok）。

**Codex 另外指出、尚未處理**：`init_db`／交易區段全文與舊庫相容性需完整審查（本次只以備份副本演練，未做獨立審查）。

發布狀態：候選，未合併、未部署。目前正式與本機為 `d586f9af`，上述證據表尚未在正式庫建立，故此修正不影響已發布資料。

---

## v5.0 修訂 — 2026-10-15 發布狀態補記（7aa94a38、d586f9af）

基底 `d586f9afd5600d0a13085c98f631e336ce096c6a`（main）；分支 `claude/st-release-status`，只補記發布狀態，不改程式。歷史段落不覆寫，以下為後續狀態。

| 版本 | 內容 | 發布時間（本機時間） | 狀態 |
| --- | --- | --- | --- |
| `7aa94a38c23498a6455f9ec7c81c0b5f8f3595a0` | PR #203 右軸標籤強化、PR #204 WaveDeck 測試字串 | 2026-10-14 22:42 前後 | 已發布到本機與正式後端；先前段落標示「候選，未發布」者，以此為後續狀態 |
| `d586f9afd5600d0a13085c98f631e336ce096c6a` | PR #205 大盤案例走實際路徑、PR #206 Yahoo 日線首次來源收據、PR #207 收據結果標記與遷移演練 | 2026-10-15 02:23 前後 | 已發布到本機與正式後端 |

**依據（實測，不是推定）**：兩次發布後都查詢本機 `127.0.0.1:18432/health` 與正式後端 `127.0.0.1:18435/health`，`runtimeCommit` 等於各自目標 SHA；`d586f9af` 另查閘道 `/gateway/health` 為 `ok`、`upstream` 為 true。發布前皆確認兩端沒有 queued／running 的更新工作，正式站停止後以 `backup-databases.py` 備份 14 個 SQLite 並逐表核對，promote 後 `data/` 保留 82 項，`d586f9af` 發布後日線 1,492,443 筆與備份一致。

**未驗證（不可視為已驗收）**：
- 閘道與 Tailscale 端的版本：需要 Owner token，未能確認該端的 SHA。
- 右軸標籤與大盤標頭、小框的實機畫面：只有前端自測與後端案例，沒有瀏覽器視覺驗收。
- 日線來源收據：正式庫尚未發生過會建立收據表的新增日線寫入；增長量只有合成回應的估算，全市場回補前須先決定壓縮或限制。
- 仍未解的獨立問題：`tests.test_launcher_cmd` 與 10/13 重寫的 `START_LOCAL_AND_WEB.cmd` 契約不一致，冷啟動時 `START_TIP.cmd` 是否返回未在真實主控台驗證，已交給 Codex 判定。

**同時修正（演練發布驗證時發現）**：PR #205 帶入的 `docs/大盤當日漲跌8D報告.md` 有兩處絕對使用者路徑（`C:/Users/...`），被分享封存的內容掃描器擋下（`windows-user-path`、`mac-user-path`），使 main 上 `tests.test_dist_scrub.TestDistScrub` 的 `setUpClass` 整個失敗。#205 的局部 CI 只跑兩組案例，沒有涵蓋分享封存，所以當時是綠的。已把兩處路徑改為 `<AI-Workspace>/...`，語意不變，不放寬掃描器。驗證：`test_has_core_share_files`、`test_archive_passes_same_post_compression_scanner`、`test_excludes_internal_context_and_runtime_state` 通過（本機 targeted）。這是文件字串，不影響已發布的程式行為。

證據：`C:/Users/Sam/AI-Workspace/docs/stock-terminal/指定版本發布-7aa94a38/`、`指定版本發布-d586f9af/`（發布紀錄、備份證據）。

---

## v5.0 修訂 — 2026-10-15 日線來源收據遷移演練與結果標記修正（候選，未發布）

基底 `abbe3a2164d002ff5c7d80c226b6056f0a75ad56`（main，含 PR #206 的合併）；分支 `claude/st-receipt-flag`，`VERSION` 維持 5.0。

**遷移演練（在正式庫的發布前一致性備份副本上執行，未碰運作中的正式庫）**：來源為 `StockTerminalPrivateWeb\backups\部署前完整資料庫-20261014T143756Z-7aa94a38\market.db`（354.4 MB、1,492,443 筆 bars、2,393 個標的、`user_version` 3、`quick_check` ok）。以 PR #206 合併後的程式在副本上執行真實的 `init_db` 與 `merge_source_bars`：
- `init_db` 0.02–0.19 秒，**不新增任何資料表或觸發器**，`user_version` 維持 3；三張證據表與 9 個觸發器在第一次真的需要保存收據時才建立，既有 6 個官方收據觸發器不受影響。
- 以 2330 的真實歷史列組成 5y 合成回應（66,990 位元組）：移除一個歷史日後重新寫入 → 新增 1 筆並保存收據與首次寫入關聯，耗時 0.03 秒；同一回應再寫入 → 不新增、不保存；持續衝突兩次 → 只第一次保存、第二次沒有再存，原值保留；寫入後 `quick_check` ok，既有 bars 逐列雜湊比對位元不變。
- 增長：每次「真的新增 bars」的 5y 回應約 67 KB（合成回應，真實 Yahoo 回應含較多中繼資料，可能更大）；典型每日 5d 更新約 0.5 KB（合成）。全市場 2,393 個標的首次回補 5y 約 160 MB 起，相當於日線庫目前大小的近一半。**回補全市場前應先決定是否壓縮或限制；此演練不代表可以直接批次回補。**
- **未驗證**：真實 Yahoo 回應的實際大小與欄位、運作中有並行讀取者時第一次建表的鎖等待、備份與還原所增加的時間、Windows 以外環境。

**發現並修正**：演練中發現有附收據但這次沒有新增 bars 或新修訂時，結果被標成 `absent`，與「呼叫端漏傳收據」無法區分，稽核者會誤判。新增 `not_needed`（有收據但本次無需保存），`absent` 只代表呼叫端沒附收據。`tests/test_daily_source_receipt.py` 的無變動案例新增此斷言。驗證：14 項收據案例加既有 5 組直接依賴案例共 57 項通過（本機 targeted）。

發布狀態：候選，未合併、未部署。

---

## v5.0 修訂 — 2026-10-15 Yahoo 日線首次來源保全整合（候選，未發布）

基底 `7aa94a38c23498a6455f9ec7c81c0b5f8f3595a0`（main）；分支 `claude/st-first-source-integrate`，`VERSION` 維持 5.0。整合 Codex 於 2026-10-12 完成但從未測試的候選提交 `9350de53b57ab6c752fd46f0d51ed010d2ff127b`（該候選落後 main 76 個提交，無文字衝突，以 cherry-pick 套入）。

原因：歷史日線有 15 筆 revision 缺原 bars 的首次寫入時間與來源回應，無法判斷是否為正常修訂（2026-10-08 診斷）。候選讓之後每次 Yahoo 寫入都保存原始回應，並把新增的 bars 與該次回應逐筆關聯，不可覆寫。**這只讓「之後的寫入」可稽核，不回填那 15 筆，也不證明歷史污染已修復。**

整合時發現並修正的問題（原候選使 13 個 main 上本來通過的測試失敗）：
1. 呼叫端未附收據（空字典，例如以替身取代 `fetch_yahoo_daily` 的既有測試）被當成必須驗證的收據而拒寫。改為空收據視為未附證據、照舊寫入。
2. 候選在寫入前就保存收據，即使沒有新增 bars 也累積完整原始回應。改為只有真的新增 bars 或新的修訂才保存。
3. 另更新 `tests/test_stock_signals_revision_metadata.py` 的 `_fetch_remote` 替身，使其接受新增的可選 `receipt_out`。

隔離審查（Claude `claude-sonnet-5-5`，同供應商隔離；驗證器因停止原因未採納正式結果，內容僅作線索）逐條對照程式碼後採納：
- 持續衝突時每次都另存完整原始回應且證據不可刪除（高）：成立。改為只有 `INSERT OR IGNORE` 真的新增修訂（`rowcount`=1）才保存並關聯。
- 首次證據主鍵與 bars 綁定，bars 被別處刪除後重新取得會讓該標的更新永久失敗（中）：成立（目前 server 內沒有直接刪除 bars 的路徑，但修復腳本或遷移可能出現）。改為已有首次證據時保留原證據、不建立第二筆，其餘日期照常寫入。
- 收據核對失敗會整批拒寫，違反「不拖累既有寫入」（中）：成立。改為 bars 照舊寫入，結果標記 `sourceReceipt: rejected` 與 `sourceReceiptError`，並以 `log_once` 留下限頻記錄，不靜默。
- 漏傳收據無從得知（低）：成立。Yahoo 來源的結果一律標 `sourceReceipt`（`stored`／`rejected`／`absent`），新增 bars 卻沒有收據時留下限頻記錄。
- `INSERT OR REPLACE` 可繞過 DELETE 觸發器（低）：成立。三張證據表加同主鍵的 BEFORE INSERT 觸發器；正常寫入先自行檢查，不會觸發。`DROP TABLE` 不在保護範圍。
未採納／延後：原始回應壓縮（中，需另定儲存契約與遷移，且要先估算增長量）；批次回補時未處理的原始位元組累積記憶體（低）；`_yf_symbol` 代號推導重複實作（低，信心低，現有 `.TW`／`.TWO` 規則與 `fetch_yahoo_daily` 一致，未見實際不符）。

新增 `tests/test_daily_source_receipt.py`（14 項）：原始回應與雜湊保存、逐筆關聯、無變動更新不累積、衝突值保留原值並關聯修訂、持續衝突不重複保存、bars 被刪後重新取得保留原證據、證據表拒絕更新／刪除／`INSERT OR REPLACE`、收據不符／偽造列／雜湊被竄改時仍寫入並標記、漏傳收據可見、非 Yahoo 來源、解析契約。變異檢查：移除「已存在修訂不重存」判斷，持續衝突案例失敗。

驗證：上述 14 項加既有 5 組直接依賴案例共 57 項通過（本機，targeted，未跑完整套件）。**未驗證**：真實 Yahoo 回應（案例用合成回應）、正式資料庫的實際增長量與備份大小、舊資料庫首次建立新表與觸發器的遷移（`CREATE TABLE IF NOT EXISTS`，未在正式資料庫副本上演練）。Codex 第二意見待回覆。

發布狀態：候選，未合併、未部署。

---

## v5.0 修訂 — 2026-10-14 大盤日漲跌 8D 與同快照防再發案例

調查基底 `8356ca3cfb820652b405f5e92ac723b2c767c836`；提交前整合主線 `7aa94a38c23498a6455f9ec7c81c0b5f8f3595a0`，分支 `codex/大盤漲跌8D預防`，`VERSION` 維持 5.0。完整提交、PR 與 CI 狀態由該分支及 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/大盤漲跌8D預防/交付收據.json` 對應，避免在同一提交內預填自己的 SHA。

原因：使用者要求追查主圖 −676.17、小框 +285 的根因並提交 8D。隔離重現證實 PR #198 修改前與 PR #199 的相同官方校正區塊都會漏掉「今日 K 正確、Yahoo 昨收錯誤」；Git 時間線不支持 PR #199 覆蓋之後才合併的 Claude 修正。Codex 先前驗收缺少同一快照的跨表面數值核對，此缺口列入 `docs/大盤當日漲跌8D報告.md`。

本次保留 Claude 正式程式，只補強兩份既有案例：前後端共用已確認官方昨收 48341.31 的 fixture；前端執行主圖與小框正式函式並保留所有原有邊界，後端新增從 MIS 解析器到三個實際 HTTP 路由的一致性案例。加入本專案入口指引與局部 CI 計畫，不新增行情管線。

本機驗證：8 個 Python 案例、13 組前端情境通過（2026-10-15 補強，見下方「審查更正」）；歷史來源重現通過；本機 18432 與正式後端 18435 的三端點實際 GET 都為 48625.83／48341.31／+0.5885649355%。當次 runtimeCommit 均為 `06d94771d19a03c9ece5006cf6e030fa823904b6`。沒有跑完整測試、沒有重新操作真瀏覽器。所有計畫與輸出保存於上述外部證據目錄。

發布狀態：本輪不修改產品來源、不部署、不更動使用者資料。交付的是 8D 與預防案例；本機提交、遠端 CI、PR 狀態以交付收據為準。官方不可用時仍有既有 Yahoo 備援，`/quote` 與 `/quote-batch` 未含市場日期；沒有擴張成新契約。

審查更正（2026-10-15，Claude 接手）：Cursor Bugbot 指出前端案例 12 驗收的 `refreshTwIndexCells` 在產品中沒有任何呼叫者，下方小框實際由 `MarketData.refresh`（`/market/snapshot`）→ `marketData` 事件 → `renderCanonicalMarketQuote` 填入，並讀 `displayChange`／`displayChangePct`。逐條對照程式碼屬實（`grep` 僅有定義處）。處理：前端案例 12 改為經 `marketData` 事件執行正式監聽與 `renderCanonicalMarketQuote`，新增案例 13（帶 Yahoo 昨收，確認同一路徑重現事故畫面）；後端新增第 8 個案例，經 `/market/snapshot` 路由驗證 `market` 欄位與 fixture 的 `snapshotMarket` 一致；fixture 新增 `expected.snapshotMarket` 供前後端共用。變異檢查：把 `renderCanonicalMarketQuote` 的差額或標頭昨收改成 Yahoo 值，案例 12 皆失敗。未修改產品來源；`refreshTwIndexCells` 死碼保留，是否移除另行決定。尚未做瀏覽器視覺驗收，也未部署。

---

## v5.0 修訂 — 2026-10-14 WaveDeck 測試字串不再被分享封存的郵件掃描器封鎖（候選，未發布）

基底 `06d94771d19a03c9ece5006cf6e030fa823904b6`（main，PR #202 的合併 SHA），分支 `claude/dist-scrub-wd-email`，提交 SHA 見該分支與 PR。`VERSION` 維持 5.0。

**問題**：`tests.test_dist_scrub` 在主線上整個失敗（`setUpClass`）。分享封存建置時，`scripts/build_dist.py` 的內容掃描器把 `wavedeck/tests/test_request_guard.py` 第 37 行的 `127.0.0.1` 後接 at 符號再接 `evil.example:18433` 判為郵件地址（規則 `email-address`，只有 `@example.com` 結尾才放行）並封鎖。該字串是 PR #200 為驗證 userinfo 攻擊刻意寫的測試資料，不是真實信箱。

**為什麼主線 CI 沒有發現**：驗證計畫只跑受影響的案例，#200 與其後的 PR 都沒有案例涵蓋 `test_dist_scrub`。這是「局部驗證」的盲點：一個測試檔的內容會被另一個流程（分享封存）掃描，但兩者之間沒有對應關係。

**修正後行為**：測試改以拼接組出同一個字串（`"127.0.0.1" + "@" + "evil.example:18433"`），語意不變，單元測試仍斷言該主機被拒絕；**不放寬掃描器**（它是安全防線）。註解中也不再寫出完整字串（第一次修正時我自己又把完整字串寫進註解，被同一個掃描器抓到）。

**防再發**：驗證計畫新增案例「WD測試字串不被分享封存掃描器封鎖」，改動 `wavedeck/tests/test_request_guard.py` 時會跑 `test_dist_scrub` 中與歸檔掃描相關的 11 個方法加上 WaveDeck 自身的測試。已證明：把原本的寫法放回去，這些方法的 `setUpClass` 立刻失敗並印出 `[BLOCK] wavedeck/tests/test_request_guard.py (email-address)`。

**驗證（本機）**：`wavedeck.tests.test_request_guard`（15 個）與歸檔掃描相關的 5 個方法實際執行通過；計畫閘門見 PR。**未執行**：CI、完整測試。

**已知限制（與本次無關、未處理）**：`tests.test_dist_scrub.TestDistScrub.test_review_regressions_run_from_the_actual_single_machine_share` 在修正後仍失敗，因為它會從分享封存內執行 `tests.test_launcher_cmd`，而該測試在乾淨的 main 上本來就失敗：`LauncherCmdOfflineBehaviorTests`、`LauncherJsonHealthOfflineTests` 的 `setUpClass` 斷言「健康查詢必須只有兩個明列的 JSON 邊界」，但 2026-10-13 重寫後的 `START_LOCAL_AND_WEB.cmd` 只有一個 `Invoke-RestMethod`（local 改用 `start_local.ps1 -CheckOnly`），另有 `LauncherNativeWaitTests` 一項失敗。這是啟動器與其測試不同步，屬 10/13 該批變更的範圍，應由其作者決定改測試或改啟動器。狀態：本機候選，未發布。

---

## v5.0 修訂 — 2026-10-14 右軸標籤避讓的防護補強與測試補齊（候選，未發布）

基底 `06d94771d19a03c9ece5006cf6e030fa823904b6`（main，PR #202 的合併 SHA，也是 2026-10-14 晚間發布到正式站與本機受管安裝的版本），分支 `claude/axis-tag-hardening`，提交 SHA 見該分支與 PR。`VERSION` 維持 5.0。

**起因**：PR #202 發布後，依 Sam 的要求派一個獨立的唯讀審查者（Claude 子代理，同供應商、上下文隔離，非跨供應商審查）審查 #202 的最終差異；審查者只拿到差異、契約與邊界，沒有拿到作者的結論。以下逐條對照程式碼查證後的處置。

| 審查發現 | 查證 | 處置 |
| --- | --- | --- |
| A：`priceToCoordinate` 回傳 NaN 時，`y == null` 擋不住，`top` 變成 `NaNpx`、排序不穩 | 屬實（`polish_v3.js` 行 1239）；舊版就存在，不是 #202 新增 | 改為 `!Number.isFinite(y)` 時不畫該標籤 |
| B：「畫面外看不見」只在 `st-vs5` 主題下證實（該主題的 `#chartarea` 有 `overflow:hidden`） | 無法判斷：沒有在非 `st-vs5` 主題實測；與舊版行為相同 | 不改程式；前一段「看不見」的說法只在 `st-vs5` 下成立，此處補記 |
| C：避讓下限用 `wrap.clientHeight`，比價格窗格高 | 屬實：已部署的 local 上容器 444、窗格 `paneSize().height` 436，差 8px | 優先用 `S.chart.paneSize().height`，讀不到才退回容器高度 |
| D：圖極矮時上移會把上方標籤推出圖頂 | 屬實（理論情境）：圖高 20、兩標籤 y=5／8 時，上方標籤會被推到負座標 | 上移量以「最上面標籤到圖頂的空間」為上限，放不下時寧可讓下方標籤超出圖底 |
| E：版面變動（平移、縮放、視窗縮放）後標籤不重算 | 屬實，但是舊有設計（全倉庫只有三個呼叫點） | 不處理，不在本次範圍 |
| 測試不足：契約第 4 條（讀不到高度、圖高未知、NaN／null）完全沒測；缺相同價位、兩標籤都在畫面外、貼邊、窗格高度優先、極矮圖等情境 | 屬實 | 自測由 8 個案例擴為 15 個，涵蓋上述全部；案例 7 的多餘程式碼已整理 |
| 文件不一致：前一段寫「6 個案例」，實際為 8 個 | 屬實 | 以本段更正：#202 發布時自測為 8 個案例，現為 15 個；前一段歷史不覆寫 |

**驗證（本機）**：自測 15 個案例通過；既有 `tw_index_day_change_selftest.js`、`test_bundle_fresh`、`test_build_reproducibility` 通過。另逐一還原 5 項防護（NaN 檢查、窗格高度、上移不推出圖頂、只抵銷被推出的一段、畫面外過濾），每一項都使自測失敗，證明新增的案例各自抓得到對應的缺口。`stock_terminal_v2.html` 已重建。**未執行**：CI、完整測試、實機量測（本次只改極端情形與防護，不改常見情形的位置）。

**已知限制**：上方「E」與「B」未處理；避讓只處理 `今`／`昨` 兩個標籤彼此的距離，不處理它們與成交量分布標籤或刻度數字的相鄰關係。狀態：本機候選，未發布。

---

## v5.0 修訂 — 2026-10-14 右軸「今」「昨」標籤價位接近時不再互相蓋住（候選，未發布）

基底 `404eb58ab8768a8f5f6ccd426addbaf598148a07`（main，PR #201 的合併 SHA，也是 2026-10-14 發布到正式站與本機受管安裝的版本），分支 `claude/axis-tag-collision`，提交 SHA 見該分支與 PR。`VERSION` 維持 5.0。

**問題**：發布 `404eb58a…` 前的版面驗證發現，大盤今收 48625.83 與官方昨收 48341.31 只差 0.59% 時，圖表右軸的「今」「昨」兩個標籤垂直重疊（桌機 8px、844×390 為 9px、390×844 為 8px），昨的標籤蓋住今的下半部。這不是該次發布引入：`renderCloseReadout` 把兩個標籤各放在自己價位的高度（`priceToCoordinate`、`translateY(-50%)`），一直沒有避讓邏輯，`17bad12…` 到 `404eb58a…` 之間這段程式只有縮排變動。舊版用 Yahoo 的錯誤昨收 49302（離現價 677 點）所以標籤離得很遠；改用正確的官方昨收後兩者相距只有約 9px，才顯現出來。凡是昨收接近現價的日子都會發生。

**修正後行為**：新增 `separateAxisTags`。價位在畫面上較下方的標籤往下讓開，與上方標籤保留 2px 空隙（`offsetHeight` 為整數、實際高度有小數，只留 1px 會刪成貼齊）；讓開後超出圖高時整組上移以保持間距；讀不到高度時以 14px 估計。昨收虛線的價位、標籤文字（精確價位）、顏色、上框與下框的日漲跌都不變；只有一個標籤（沒有昨收）時不移動。

**能力保全對帳（規則 0009 既有能力保全）**：沒有移除或隱藏任何資訊。

| 能力 | 舊版基準 | 新版結果 | 判定 |
| --- | --- | --- | --- |
| 昨收虛線價位 | 48341.31（官方昨收） | 48341.31 | 原樣保留 |
| 今、昨標籤文字 | `今48625.83`、`昨48341.31` | 相同 | 原樣保留 |
| 上框日漲跌 | `+284.52 (+0.59%) 日` | 相同 | 原樣保留 |
| 兩標籤可讀性 | 垂直重疊 8～9px | 間隙 1.6～1.7px（844×390、667×375、390×844，以最終的 2px 版實測）；桌機只量過 1px 版（間隙 1px），最終的 2px 版沒有重量 | 改善；桌機最終版未實測 |
| 水平溢出 | 無 | 無 | 原樣保留 |
| 價位在畫面外的標籤（跳空、漲跌停） | 各自貼自己的（畫面外）座標，今收標籤留在自己的價位 | 同左：畫面外的標籤不參與避讓，也不拖動畫面內的標籤 | 原樣保留（審查修正，見下） |

**審查修正（Cursor Bugbot，PR #202 的 `polish_v3.js` 行 1274）**：第一版「讓開後超出圖高就整組上移」沒有區分標籤是被我推出去，還是價位本身就在畫面外。昨收跳空或漲跌停時 `priceToCoordinate` 仍回傳畫面外的座標，會把畫面內的今收標籤一起拉離自己的價位（重現：今收 y=330、昨收在畫面外，今收被拖到 4.3）。已核實成立並修正：只讓兩個都在畫面內的標籤參與避讓；整組上移只抵銷「被讓開而推出去」的那一段，標籤原本的下緣若已壓在圖底邊則不因此拉走另一個標籤。新增 2 個案例（昨收在畫面外、今收在畫面外），並把原案例 5 改為「原本完全在圖內、讓開後才超出」；自測共 8 個案例，舊程式碼下失敗、修正後通過。實機尺寸量測是修正前版本的結果，這次修正只改變畫面外與貼邊的情形，沒有重量。

**驗證（本機）**：新增 `tests/axis_tag_collision_selftest.js`（6 個案例，執行正式的 `renderCloseReadout`）：舊程式碼下失敗（今標籤 y=330、昨標籤 y=339、高度 17／13 的重現）、修正後通過；既有 `tests/tw_index_day_change_selftest.js` 仍通過；`tests.test_bundle_fresh`、`tests.test_build_reproducibility` 通過（`stock_terminal_v2.html` 已重建，差異只有 `?v=` 修訂值與這次的 `polish_v3.js`）。實機：在隔離埠（目標程式碼、資料庫只含 `^TWII`）以內建瀏覽器量測四種尺寸的兩個標籤實際位置，修正前重疊，修正後皆有空隙，昨收虛線與日漲跌不變。**未執行**：CI、完整測試。工程測試與版面量測不代表策略有效，也不是真機（iPhone／Android）驗收。

**已知限制**：避讓只處理這兩個標籤彼此的距離，沒有處理它們與 VAH／POC／VAL 等成交量分布標籤、右軸刻度數字的相鄰關係；那些是既有的畫法，本次未動。狀態：本機候選，未提交以外的任何階段。

---

## v5.0 修訂 — 2026-10-14 WaveDeck 被拒請求先讀完本體，消除 Windows 上的偶發連線重設（候選，未發布）

基底 `d5871f5fdfafb03f13a129f767c92c46933437cb`（main，PR #200 的合併 SHA），分支 `claude/wavedeck-guard-drain-body`，提交 SHA 見該分支與 PR。`VERSION` 維持 5.0。

**問題**：PR #200 新增的 `wavedeck/tests/test_request_guard.py` 在 Windows 上偶發失敗（`ConnectionAbortedError: [WinError 10053]`），2026-10-14 發布 `d5871f5f…` 時使 `private_web_release.py stage` 的局部驗證失敗，發布工具並依設計拒絕「前次驗證失敗後原樣重跑」。單檔連跑實測：修正前約 6 次中 1 次、7 次中 2 次、20 次中 1 次失敗，每次失敗的案例不同。

**根因**：`wavedeck/server/server.py` 的 `do_POST` 在讀取請求本體之前就回應並結束，共兩處：`_guard` 拒絕（403）與 `/webhook` 密鑰錯誤（401）。伺服器在本體尚未讀完時關閉連線，Windows 會對仍有未讀資料的連線送出 RST，客戶端可能還沒讀到回應就收到 WinError 10053／10054。Linux 上通常不會撞上，所以 CI 的 Ubuntu 一直通過。

**修正後行為**：新增 `_drain_request_body`，這兩處回應前先讀完 `Content-Length` 指定的本體。讀取上限與 `_read_json` 相同（256 KiB），讀取期間設 2 秒逾時，避免惡意請求拖住處理緒；超過上限的請求不讀取、直接關閉連線；讀取失敗也關閉連線。被拒絕的請求仍回原本的 403／401，錯誤內容不變，也不新增可被利用的資料路徑。

**驗證（只含本機定向測試，沒有 CI 與完整測試結果）**：新增兩個案例（防護拒絕、webhook 密鑰錯誤，各以約 200 KB 本體重複 25 次）；兩者在舊程式碼下各 3/3 失敗、修正後各 3/3 通過；修正後 `wavedeck.tests.test_request_guard` 整檔連跑 30 次，0 次失敗。這證明該案例檔在本機的偶發失敗已消失，不代表 WaveDeck 其他部分已驗證。

**不變**：WaveDeck 不隨私有站發布，本修正不影響正式站與本機受管安裝的執行行為；發布狀態：本機候選，未提交以外的任何階段。

---

## v5.0 修訂 — 2026-10-14 加權指數 /quote 與 /quote-batch 改用官方昨收（候選，未發布）

基底 `aa2be1bdd5d7966fe0008d68ae046adc71e3ef0b`（main，PR #197 的合併 SHA；補記下方「大盤當日漲跌基準改用官方昨收」與「補完 main 上既有測試的紅燈」兩則的合併 SHA，兩則原文保留）。實作提交由 Draft PR 指向，合併 SHA 尚未產生。`VERSION` 維持 5.0。這是 Sam 2026-10-14 「先修完待處理」對上一則「未解」第三項的處置。

**Sam 貼回的唯讀檢查（本機與雲端無法互通，以貼回為準）**：本機與正式站的 `runtimeCommit` 都是 `17bad12031b26a3a09ba4cd413cfa5b4244b2971`（不含 PR #197，所以畫面仍是舊行為）。`/twindex` 的 `t00`：現價 48625.83、`prevClose` 48341.31、`tradeDate` 2026-10-14、`asOf` 2026-10-14T13:33:00+08:00。Yahoo 的 `meta`：現價 48625.83、`chartPreviousClose` = `previousClose` = 49302.0、`regularMarketPreviousClose` 為空，最後一根 K 棒 2026-10-14 13:30（台北）。根因因此有資料佐證：Yahoo 昨收 49302.0 讓日漲跌成為 48625.83 − 49302.0 = −676.17（−1.37%），官方昨收 48341.31 的口徑是 +284.52（+0.59%），底部列四捨五入顯示 +285。前一則寫的「請確認官方昨收是否為 48340.83」已有答案：是 48341.31（48340.83 來自當時畫面推算）。

**問題**：PR #197 只修了圖表標頭（前端 `patchTwIndexHeader`）。伺服器的 `/quote/^TWII` 與 `/quote-batch` 仍以 Yahoo 昨收計算，`_BAD_YF` 只列 `^TWOII`。凡是走這兩條路徑的大盤日漲跌（日線載入時的昨收補值、分 K 空白時以即時報價合成今日 K 棒、自選清單與 Pulse 以 `/quote-batch` 取報價）會與 `/twindex` 的官方昨收不同源。

**修正後行為**：`^TWII` 加入 `_BAD_YF`，與 `^TWOII` 相同：只信 TWSE MIS（`t00`），`price`、`prevClose`、`changePct` 與 `/twindex` 同一個官方來源，不再請求 Yahoo。`/quote/^TWII` 回應多帶 MIS 的 `open`／`high`／`low`。盤前 MIS 沒有成交價也沒有開盤價、或 MIS 請求失敗時，維持原本行為退回 Yahoo，不回空。其他標的不受影響（`^GSPC`、`^N225` 等不呼叫 MIS）。

**可見的縮減（規則 0009 第 1 條）**：沒有功能被移除。`/quote/^TWII` 在 MIS 有成交價時的回應形狀與 `^TWOII` 現有的相同，不再含 Yahoo 才有的 `volume`、`marketState`、`lastBarTime`、`bid`／`ask`。即時報價面板的備援路徑（`/twindex` 失敗後才會走 `/quote/^TWII`）因此可能顯示「成交時間未知」並用本地時間推算盤別；`/twindex` 正常時面板本來就不走這條路徑。

**驗證**：新增 `tests/test_taiex_quote_official_base.py`，6 個案例，以正式 `Handler` 與 `urllib` 載入真的 `server/server.py`：`/quote/%5ETWII` 與 `/quote/^TWII` 回官方昨收 48341.31、`change` 284.52、`changePct` 約 0.5885 且不呼叫 Yahoo；`/quote-batch` 與 `/twindex` 同一個昨收；Yahoo 回 49302.0 時批次結果仍為正漲幅；MIS 無成交價或請求失敗時 `_trusted_quote_override` 回 `None`（退回 Yahoo）；其他標的不呼叫 MIS。把 `server/server.py` 暫時還原成修正前，4 個案例失敗（3 個錯誤、1 個斷言），證明測試抓得到這個錯誤。相關測試共 84 個（含新增的 6 個，另含 `test_台股即時報價`、`test_server_http_security`、`test_no_undefined_names`、`test_no_new_silent_exceptions`、`test_bundle_fresh`）與 `tests/tw_index_day_change_selftest.js` 通過。列入 `.github/驗證計畫.json` 的案例「加權指數報價官方昨收」。

**未解／限制**：
- 沒有在真實 TWSE／Yahoo 即時回應與真瀏覽器上驗證；上面的資料是 Sam 貼回的單一時間點，不是自動化驗證。
- Windows 專用的 `tests/test_launcher_cmd.py` 仍紅（見下方「補完 main 上既有測試的紅燈」的「未解」），需要在 Windows 上由 Codex 或 Sam 依新的啟動流程更新；雲端無法執行，未處理。
- `shell_v5_selftest` 的失敗已於 PR #197 修正，不在此列。
- 未發布。發布須 Sam 指定完整 SHA 的明確授權。

## v5.0 修訂 — 2026-10-14 WaveDeck 控制面加上請求防護（候選，未發布）

基底 `aa2be1bdd5d7966fe0008d68ae046adc71e3ef0b`（main，PR #197 之後）；實作提交由 Draft PR 指向，合併 SHA 尚未產生。`VERSION` 維持 5.0。這是 Sam 2026-10-14 「照建議執行」對完整審查最高風險發現的處置。

**問題（在隔離複本上以 curl 實測重現，未用真瀏覽器）**：WaveDeck 控制介面沒有驗證，任何網頁都能跨來源下指令。已設定 `WAVEDECK_SECRET` 的情況下：不帶密鑰、`Origin` 為別的網站的 `text/plain` 簡單請求 `POST /api/mode {"mode":"live"}` 回 200，券商切成 `txt_master` 並寫入設定檔（重啟仍在）；緊急停止開啟後，別的來源能用 `POST /api/kill {"on":false}` 解除；`/api/signal` 不需密鑰就被接受。根源：密鑰只擋 `/webhook*`、所有回應帶 `Access-Control-Allow-Origin: *`、預檢一律放行、不檢查 `Host`、只有 4 個策略設定端點有來源檢查，而且那個檢查拿 `Host` 當信任基準，DNS 重綁定時 `Origin` 與 `Host` 同為攻擊者網域，擋不住。

**修正後行為**（新增 `wavedeck/server/request_guard.py`，`server.py` 在 GET／POST／OPTIONS 一律先過這個防護）：
- `Host` 必須是 `127.0.0.1`／`localhost`／`[::1]`（埠為服務實際的埠）。區網或自訂名稱用 `WAVEDECK_ALLOWED_HOSTS` 明示加入。
- 寫入沒有 `Origin` 放行（命令列、PowerShell、伺服器對伺服器）；有 `Origin` 必須是 WaveDeck 自己的控制臺；`Sec-Fetch-Site: cross-site`、只有外站 `Referer` 一律 403。GET／OPTIONS 不看 `Referer`，從別的網頁或 ST 按鈕開啟 WaveDeck 畫面不受影響。
- Stock Terminal 畫面是合法的跨來源呼叫者（來源由 `ST_URL` 的埠推得）：只開放讀取 `/health`、`/api/state` 與推送 `POST /bridge/st`；其他端點 403。
- CORS 只對該 ST 來源回應其確切來源，移除 `*`；預檢只對上述呼叫放行。
- `/webhook*` 仍只靠共享密鑰（改為常數時間比對），可走隧道主機；隧道主機打不到控制端點。
- 舊的「4 個策略端點」來源檢查併入同一套防護。

**可見的縮減（規則 0009 第 1 條）**：不再接受任何來源的跨站控制請求，也不再回萬用 CORS。合法呼叫者（WD 自己的控制臺、ST 畫面的狀態讀取與 `/bridge/st` 推送、命令列與啟動腳本的 `/health`、電視 webhook）都保留並有測試。若你有其他自製工具從瀏覽器跨來源呼叫 WD 的控制端點，會被拒絕，需改為伺服器端呼叫或加入 `WAVEDECK_ALLOWED_HOSTS` 的同主機控制臺。

**驗證**：新增 `wavedeck/tests/test_request_guard.py` 13 項（4 項純判定、9 項以正式 Handler 與動態本機埠做 HTTP 驗證，含重現原本的攻擊：15 個控制端點在外站 `Origin` 下一律 403 且狀態不變）。這些 HTTP 測試在舊的 `server.py` 上失敗、在新的通過。既有 WD 測試（策略 HTTP、smoke、不留倉、完整審查執行、成交確認、策略訊號整合、exec_md）與 ST 端的 `test_bridge_http`、`test_start_all`、`test_wavedeck_bus`、`test_wavedeck_launcher` 通過。

**未解／限制**：
- 沒有用真瀏覽器驗證；測試用 HTTP 用戶端模擬瀏覽器送出的標頭。瀏覽器對「公開網頁連本機」另有保護，本修正不依賴它。
- 本機上的其他程式（不經瀏覽器）仍可呼叫 WD；沒有帳密。這需要另外的設計（例如啟動時產生的權杖）。
- `/webhook` 在未設定 `WAVEDECK_SECRET` 時仍不驗證。
- WD 預設帳戶是樣本數字、單日回撤風控未接真實權益，是另一個發現，未處理。
- 未發布。發布須 Sam 指定完整 SHA 的明確授權。

## v5.0 修訂 — 2026-10-14 補完 main 上既有測試的紅燈（候選，未發布）

基底 `17bad12031b26a3a09ba4cd413cfa5b4244b2971`；與同一個 Draft PR 的大盤昨收修正、選擇權新鮮度修正分開記錄。實作提交由 PR 指向，合併 SHA 尚未產生。`VERSION` 維持 5.0。Sam 2026-10-14 同意在雲端沙盒執行完整 Python 套件與全部 Node 自測（規則 0008 第 13 條）。

**原因**：PR #198／#199 的 CI 只跑各 PR 計畫列出的案例，被改動函式的既有測試不在其中，`main` 上累積了既有測試的紅燈。本次逐項判斷，**只更新過時的測試與基準，沒有改產品程式、沒有放寬任何斷言、沒有跳過或停用測試**。

| 測試 | 判斷 | 處置 |
|---|---|---|
| `tests/indicator_cache_selftest.js` | 測試過時。PR #198 把 EMA 抽成 `window.stEmaSeries` 並內嵌進 worker 模板，自測只擷取模板，在沒有 `window` 的環境失敗 | 先執行 `stock_terminal.html` 內同一份 EMA 定義，再取 worker 模板 |
| `tests/shell_v5_selftest.js`（決策頁溫度燈說明） | 測試過時。`cc5e9bd` 刻意把說明由 6.5px 置中不換行改為 10px 可換行，斷言仍是舊樣式 | 改斷言目前的整列寬且可換行樣式 |
| `tests/test_no_new_silent_exceptions.py`（`silent_except_baseline.json`） | 基準未下修。PR #198 讓 `trend_quant` 由 2 降為 1、`turnover_quant` 降為 0；規則 0014 要求減少時一併降基準 | `trend_quant` 2→1，移除 `turnover_quant` |
| `tests/test_三項限制解方.py`、`tests/test_全檢資料邊界.py` 各一項日資料重試測試 | 測試過時。PR #199 在每日來源流程加入「官方研究續補」與「還原快照」兩步；測試沒有模擬新步驟，第二次執行因還原快照為 partial 而不是 completed | 模擬還原快照步驟；新增斷言：還原快照兩次執行都重新核對（`call_count == 2`），證明沒有沿用「先前已完成」 |
| `tests.test_bundle_fresh` | 追蹤中的 `stock_terminal_v2.html` 與原始碼不一致 | 已於同一 PR 重建（見上一則） |

**驗證**：上列各案例單獨執行通過，並列入 `.github/驗證計畫.json`。

**未解（Windows 專用，未修正，也沒有被隱藏）**：Windows CI 對本 PR 的「分享封存」案例失敗，原因是封存內的 `test_review_regressions_run_from_the_actual_single_machine_share` 在 Windows 上執行 `tests.test_launcher_cmd`，它在 `setUpClass` 就失敗：`健康查詢必須只有兩個明列的 JSON 邊界`。PR #198 把 `START_LOCAL_AND_WEB.cmd` 的本機啟動與健康檢查改成 `call START_TIP.cmd` 與 `start_local.ps1 -CheckOnly`，檔內只剩一個 `Invoke-RestMethod`（閘道），但這組 Windows 專用的真實 CMD 測試仍斷言兩個、並模擬已刪除的 40 次輪詢。這是 `main` 上本來就紅的 Windows 啟動器測試，與本 PR 無關（本 PR 只改封存內的文件路徑與測試信箱）。它需要在 Windows 上實際執行才能更新，雲端沙盒做不到，所以本 PR 的驗證計畫把該方法排除並在案例理由寫明；其餘 11 個封存測試方法與 `tests.test_變更驗證` 在兩個平台都跑。請 Codex 在 Windows 上依新的啟動流程更新 `tests/test_launcher_cmd.py`（同批可能還有其他 Windows 啟動器案例）。

**限制**：沒有在真實資料上驗證；以上都是測試層級的修正。未發布。

## v5.0 修訂 — 2026-10-14 大盤當日漲跌基準改用官方昨收（候選，未發布）

基底 `17bad12031b26a3a09ba4cd413cfa5b4244b2971`（main，PR #199 之後）；實作提交由 Draft PR 指向，合併 SHA 尚未產生。`VERSION` 維持 5.0。

**症狀**：同一張畫面，圖表標頭顯示加權 48625.83「-676.17 (-1.37%)」，底部加權條顯示「+285 (+0.59%)」。兩個數字各自自洽，但昨收基準不同：標頭基準 49302.00，底部 48340.83。

**根因（由程式碼與畫面推得，未在真實 Yahoo／TWSE 回應上重現）**：標頭的日漲跌基準 `S.data.yesterdayClose` 來自 Yahoo `meta.chartPreviousClose`（盤中分 K）或 `/quote` 的 Yahoo 昨收。伺服器端 `server/server.py` 已有註解記載 Yahoo 在雙伺服器不同步時會把上上日收盤當昨收。`polish_v3.js` 的 `patchTwIndexHeader` 只在「Yahoo 日線落後一日（最後一根收盤≈官方昨收）」時才用 `/twindex`（TWSE MIS）校正，其餘情況註解寫「主圖已是今天，Yahoo 已正確，不介入」。這個假設不成立：主圖已是今天時，Yahoo 的昨收仍可能錯。底部加權條一直用 `/twindex`，所以兩者分歧。

**修正後行為**：`^TWII`／`^TWOII` 在主圖最新一根與 MIS 同一交易日（`tradeDate`）、且 Yahoo 昨收與官方昨收不同時，日漲跌基準改為 `/twindex` 的官方昨收；現價維持主圖值，昨收虛線與右軸讀數重畫，統計分頁開著時一併重繪。原有「早盤落後」整組校正不變。以下情況不介入、保留 Yahoo 值：昨收已一致（容許 0.005 點浮點誤差）、主圖仍是上一個交易日、`/twindex` 沒有 `tradeDate`／成交價／昨收、非大盤指數、取不到 `/twindex`。重畫昨收虛線的程式抽成 `applyPrevCloseMarks`，`renderChart` 之後與校正共用。

**可見的縮減（規則 0009 第 1 條）**：無功能被移除。唯一可見變化是大盤標頭的日漲跌數字與昨收虛線位置，在 Yahoo 昨收錯誤時改為官方值。

**驗證**：新增 `tests/tw_index_day_change_selftest.js`，在 VM 內執行 `polish_v3.js` 與 `stock_terminal.html` 的正式程式碼，11 個情境通過，含畫面重現（49302.00 → 48340.83，標頭 +285.00 (+0.59%)）。把閘門暫時還原成「只在落後時校正」，畫面重現情境失敗，證明測試抓得到這個錯誤。相關前端自測 `range_chg`、`台股即時報價`、`js_syntax`、`chart_visual_v5`、`layout_visual_v5`、`完整審查前端`、`圖表生命週期`、`LIVE報價一致性` 通過。

**重建 `stock_terminal_v2.html`**：追蹤中的 v2 在 `main` 上就與原始碼不一致（`tests.test_bundle_fresh` 在乾淨的 `17bad12` 失敗；差異是 PR #198／#199 已合併的前端來源，如共用 EMA 與 mobile_v2.css 版本戳）。本次重建把這些一併帶入，`tests.test_bundle_fresh` 通過。

**未解／限制**：
- 沒有在真實資料上驗證。請確認當時 TWSE 官方昨收是否為 48340.83。
- `tests/shell_v5_selftest.js` 在乾淨的 `17bad12` 就有 1 項失敗（`decision uses visual divergence overlays…`，第一個條件 `dc-temp-light` 樣式找不到），與本次無關，未處理。
- 伺服器 `/quote/^TWII`、`/quote-batch` 仍使用 Yahoo 昨收（`_BAD_YF` 只列 `^TWOII`）。目前沒有找到會顯示 `^TWII` 日漲跌的其他畫面使用這條路徑；若要同源，需另行決定。
- 未發布。發布須 Sam 指定完整 SHA 的明確授權。

## 2026-10-13 — PR199 完整歷史根因補完候選

版本維持 **5.0**；本輪起點 `bd573cb9997a2d25103c226c90864211fc00c04d`。Sam 明確要求解決剩餘實際問題，並追加「可直接部署」，取代下方較早的 HOLD 授權狀態。新增完整官方比較讀取：所有交易日原件、四類公司行動與全期日曆到齊才可使用；不截短、不混合還原快照，不修改首次行情。2330 的 24 天原價差異須雙官方報表逐欄一致；0050 舊分割基準、官方停牌日期與公司行動非經濟修訂皆有可追溯判定。月末日曆邊界修正及有界每日續補防止相同缺口重現，UI 揭露實際期間與價格基準。

兩套真實副本的 2330／0050 各 50% 情境均恢復可用風險，1,256 筆共同有效報酬；原始 bars 保留。36 項新增／直接相關案例與前端來源期間呈現通過，只驗本次影響範圍。追加 42 項複審修正案例與兩套真實副本的部位／警報情境均通過；此筆建立時仍為候選，Claude Opus 5.5 最終複審、CI、合併與部署尚待完成；後續結果另增補，不以副本成功代替正式發布。完整分類與限制見 `docs/PR198後續分類.md`；最終提交與發布證據將由 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/審查後續回歸修正/完整歷史交付收據.json` 追溯。

## 2026-10-13 — PR199 收尾決定：保留完整歷史，暫不部署

Sam 明確選擇「保留完整歷史嚴格契約：完成 commit、push，維持 HOLD 暫不部署」。Stock Terminal 5.0 程式提交 `f83fd18dc89de596138bca325fa37f1b25ba37bc` 已推送至 PR #199；CI `38411780663` 雙平台通過 253 案的明列計畫，包含有效證據沿用。實際副本的四組警報價格／量能指標已恢復，投組與部位區間仍因不可比還原資料維持 HOLD。未合併、未建立 stage、未 promote、未部署，正式資料未改。

此筆只記錄最後決定，產品程式及測試不變，沿用原成功證據。最終文件提交 SHA 與遠端核對見外部 `審查後續回歸修正/資料補完交付收據.json`。

## 2026-10-13 — PR199 實際資料 HOLD 根因修正候選

版本維持 **5.0**；本輪基準 `50c38b2e8fd779a29c26016fc366f5f100b7eb70`。Sam 追加「補完 然後git commit push deploy」，已授權完成後提交、推送與部署；原有不得放寬 fail-closed 及退化阻擋發布要求仍適用。

修正每日資料已完成時仍重新核對還原依賴，以同一來源完整快照更新、共用期限與最多四個工作執行緒保留待辦；不覆寫首次原價、不拼接不同還原版本、壞候選不能覆蓋有效快照。官方公司行動日期新增民國／西元中文年月日解析，非法日期、混合分隔符、附加文字及超出要求期間仍原子拒絕。警報與 WATCH 沿用既有 DB，按日期及欄位處理品質衝突，來源未知保留既有狀態；遠端備援整份核對價格基準，禁止逐根拼接。投組保留完整交易日軸，單一快照內部缺日不產生跨日報酬；最新日缺漏或價格衝突仍拒絕。

只做局部案例及兩套隔離資料副本、2330／0050 的真實來源驗證，沒有執行全套測試。價格指標在兩庫兩股均恢復非空，日期為 2026-10-13；成交量沿用既有完整收據選定的官方股數，四組量比亦非空；不可核對的值仍未知。投組代表性情境各 50% 仍 HOLD：5 筆 2022／2024 年 Yahoo 價格與官方及保存原價不符，query1／query2 與縮短期間皆重現，不能冒稱資料補齊即解除。正式使用者資料未修改，沒有拿隔離副本覆蓋執行期 DB。

Claude Opus 5.5 完整複審確認首輪八項已處理；其餘兩項低風險意見已修正並局部補驗，未追加第三輪。受審提交 `6a8f4072f6eff9de70e7e4f939fe9aaec6c508cb` 的雙平台 CI 通過，最後微調的提交與 CI 另由交付收據追溯。這筆建立時為未部署候選。最新分類、局部結果與 Claude Opus 5.5 覆核處置見 `docs/PR198後續分類.md`；完整提交 SHA、CI、推送及是否部署由 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/審查後續回歸修正/資料補完交付收據.json` 追溯。發布授權存在，但實際驗收未過不能標成已發布。

## 2026-10-13 — 完整審查修正局部驗證與發布準備

PR #198 的首輪 Ubuntu 通過，Windows 前端案例因 checkout 使用 CRLF，固定 LF 的原始碼區段邊界無法匹配。僅將測試讀入字串的 CRLF 正規化為 LF，不改產品來源或行為斷言；保留失敗收據，後續只補驗受影響案例並沿用其他有效證據。

產品版本維持 **5.0**。Sam 明確確認 F01–F24 的最小局部驗證及通過後直接部署。候選 `d11b82b27f2fde7e85fcd2525453013879f5fb32` 的 Git archive 已通過前端 8 組情境及 Python 40 個案例，涵蓋資料日期與品質、警報權限與競態、WaveDeck 風控與程序單例、Windows 冷暖啟動身分。每組明列輸入與受影響契約；相同有效證據沿用，未執行整套測試。

一位同供應商隔離 reviewer 的四類案例缺口已補齊；fixture 埠、訊號格式、Windows 鎖檔與 PowerShell 作用域修正未弱化原斷言，最後複核無阻擋發現。此筆建立時為已通過局部驗證及 stage 的候選；最終 PR／main 完整 SHA、雙平台 CI、正式與本機及 WaveDeck 的發布狀態與資料保留證據，見 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/完整審查修正/接續交付收據.json`。保留先前未測候選歷史；不將模擬券商、隔離 HTTP 或來源測試當成真實交易與手機實機驗收。

## 2026-10-13 — 完整程式碼審查 F01–F24 修正候選

產品版本維持 **5.0**；原審查基底 `ae8159d1359c459121ecdf100cbbeb5d1d6a4b6f`，提交基底已納入主線 `3b67d2d3d069e08c60e8b1285730f6874358894f` 的文件與驗證計畫。依完整審查修正執行停止／急停序列化、券商模式與程序單例、持倉和警報資料保全、異步回覆身分、指標公式、資料日期／品質／公司行動、條件研究期限與分組、Reader 唯讀邊界，以及 Local 暖啟動同步。

保留既有資料與功能入口；總經更新／回補改為受控 POST，舊的有副作用 GET 回傳 405；主圖與策略共用 EMA，無法核對品質的統計明示不可用，不產生偽有效數值。逐項原因、能力對帳及最小待驗情境見 [完整審查修正](完整審查修正.md)。

Sam 要求本輪不跑測試，因此只做來源與差異審查，未執行建置、動態重現、CI 或部署。此筆為修正候選紀錄，不宣稱測試通過或正式發布；保留發布安全門檻與當前使用版本。實作完整 SHA、隔離覆核結果、Git 清單與交付狀態由 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/完整審查修正/交付收據.json` 追溯。

## 2026-10-13 — 修正 START_ALL 冷啟動重複開頁與 Tailscale 開頁缺漏

產品版本維持 **5.0**；基準 `7cd52f739b4babc3526748d16e15e9b30a824756`。冷啟動時，受管 Local 啟動器與外層協調器各開一次同一個 Local 頁面；Web 分支原本只有服務就緒與閘道摘要，沒有 Tailscale 開頁動作。

修正由 `START_LOCAL_AND_WEB.cmd` 統一開啟 Local 與 Tailscale 各一個頁面。冷啟動傳入 `-NoBrowser`，`go.ps1` 將選項傳到既有受管啟動器，開發分支也遵守此選項；單獨 `START_TIP.cmd` 預設仍開頁。沿用 Tailscale 的 Serve 設定查詢，只接受唯一以 HTTPS 代理至 ST 閘道 18434 的根路由；解析失敗不猜網址，以 Web 位元 2 回報。WaveDeck 入口、呼叫順序、既有退出碼與 `--no-browser` 能力保留。

局部驗證：13 個選定案例通過，包含冷暖啟動、子層參數傳遞、各端失敗碼、Web 路由開頁／拒絕與既有受管防呆；不執行完整測試。同供應商隔離唯讀覆核沒有阻擋發現。既有 CMD harness 原先略過子層開頁，因此新增子層與受管轉接證據防止漏報。

發布範圍為 canonical checkout 的啟動腳本；這次不變更受管服務程式、資料、版本或 Tailscale 設定。提交、CI、實際開頁及來源更新狀態以 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/啟動分頁分流修正/交付收據.json` 的當次證據追溯。此段建立時為已局部驗證的候選，沒有聲稱已完成實機冷啟動驗收。

## v5.0 修訂 — 2026-10-12 圖表取圖時序補正

## 2026-10-13：曝險壓力品質、保守約束與資料期間

產品版本維持 **5.0**；基準 `65856dd7759e2f44b77178847357d184cf1ceac6`。既有最高分項×85%下限使短樣本融資新高長期顯示85。新增資料品質與區間契約：52週融資覆蓋至少200筆且330個日曆日才可作完整窗口評估，否則保留現有樣本百分位並明示限制；沿用來源過期標記，不因樣本筆數多而忽略過期。波動期間按實際有效報酬筆數、模型日期與複查期限呈現。

綜合評估與保守約束分開：資料不足／模型待複查時不輸出可靠綜合分數，仍保留原score／tone／state及風險警告，新增可讀下限公式與觸發分項。卡片顯示日資料、月度模型、各自區間及計算快照；不冒充盤中即時。既有資料、觀察股、風險設定及配置權限不變。過期模型假設未擅自更新，未以較低分數取代風險約束。

驗證：全域防呆計畫下16個局部計算案例與三種資料狀態×兩種尺寸共6個離線畫面情境通過；一位同供應商唯讀reviewer的來源過期與期間誤標兩項發現均修正並覆核關閉。CI／stage僅執行明列計算與畫面案例並沿用有效證據，未啟動全套。發布狀態：此條建立時為本機候選；最終完整SHA、CI與受管發布實際結果記於 `AI-Workspace/docs/stock-terminal/曝險壓力修正/交付收據.json`，不能僅據本條宣稱已發布。


封存版面案例在讀取體檢後的畫布取圖逾時，保留原失敗紀錄。將既有圖表量測留在圖表載入完成時、體檢切頁之前，避免取圖與切頁／版面重算交錯；體檢真點擊、文字與原圖表斷言全數保留。此補正只調整局部驗收器的順序，不變更產品來源，後續成功證據依同任務交付收據追溯。

## v5.0 修訂 — 2026-10-12 手機行情與體檢緊湊版面

產品版本維持 **5.0**；基準 `b0461db128493eb8228682cb8826e91a7e36ca89`。依手機實際回饋，行情指數從 12.5px 改為 10.5px、最小格寬 148px 改為 110px、左右內距 10px 改為 5px，保留依完整內容撐開的欄寬。直向行情列 88px 改為 72px，短橫向 44px 改為 36px。體檢五燈號標籤 10px 改為 9px，狀態 13px 改為 11px；長文字換行，右側容器不超過 290px 時排三欄。

同範圍實際點擊另查出舊手機抽屜把手在 667px 橫向攔截頁籤頂部 16px 的點擊；事件堆疊指向 `pro_v2.js` 的 capture listener。排除橫向與按鈕事件，保留直向空白把手行為。原失敗的體檢頁籤點擊已通過，未修改行情或體檢資料契約。

能力對帳：行情 7＋12 項的名稱、完整指數、漲跌值及百分比、滑動與末端點擊均保留；五個體檢燈號、狀態圖示、證據識別及進階說明完整。局部 Chromium 同資料前後對照與 9 個候選尺寸通過（320／375／390 直向，667／844／932 短橫向，1440 桌面）；範例行情格 148px → 123px，375×812 圖高 446px → 462px，844×300 圖高 113px → 121px。既有圖表、工具、分析收合、旋轉與轉盤入口斷言保留。未跑整套測試，未驗 iOS Safari 實機或即時行情正確性。

單一同供應商唯讀 reviewer 檢查本次來源差異與畫面。此為待提交候選紀錄；實作與合併完整 SHA、CI、正式及本機發布終態由 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/手機行情體檢緊湊修正/交付收據.json` 追溯。CI 與 stage 只明列同一版面案例，保留必要產物完整性、資料保護、程序歸屬與部署身分檢查。

## v5.0 修訂 — 2026-10-12 橫向入口量測的跨平台邊界

PR #192 的 Ubuntu 局部案例在通知按鈕捲動後的邊界檢查失敗。補上矩形與實際命中元素診斷，並與既有文字裁切量測一致，容許半像素捲動捨入誤差；中心點仍必須命中原按鈕，不忽略真實遮蔽。此補正僅修改局部驗收器，後續成功結果以同任務交付收據追溯。

## v5.0 修訂 — 2026-10-12 手機短橫向 K 線空間恢復

產品版本維持 **5.0**；基準 `4e2ef2c0090be3f299f3ebbb95f8aa8399efbc3c`。實際照片及同資料對照確認：頂列、工具列換行，加上雙列行情占高，使 844×300 的 K 線高度為 0；原視窗同步另強制至少 320px，把短畫面的行情推出可視範圍。前次只驗行情文字且未載入圖表引擎，無法證明 K 線可用。

圖表路由在寬度不超過 1100px、高度不超過 500px 的橫向畫面，改採單列可捲動頂列與工具列、緊湊雙列自選股、單列可捲動行情；使用真正 visualViewport 高度。工具選單依上下剩餘空間限制高度並保留捲動；橫向分析展開樣式不再干擾既有收合。

能力對帳：行情 7＋12 項及完整數值、末端代號點擊、自選股雙列、工具與量價入口、轉盤、右側分析與收合均保留；直向與桌面排列保留，Pulse 雙欄未修改。固定 OHLCV 及正式同版 Lightweight Charts 4.2.0 的局部 Chromium 驗收通過：667／844／932×300 圖表均為 113px；844×390 從 68px 提升至 203px；844×300 收合後圖表寬 842px，旋轉直向再轉回橫向仍保留。另核對 320／375／390 直向及 1440×900 桌面。未跑整套測試，未驗 iOS Safari 實機或真實行情正確性。

一位同供應商唯讀 reviewer 複核差異與畫面，無阻擋發現；932px 控制入口缺口已修正並有成功證據。CI 與 stage 僅明列此版面案例，保留產物完整性、資料備份／保留、程序歸屬及當次部署身分查核。此紀錄為待提交候選；實作／合併完整 SHA、CI、正式與本機部署終態由 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/手機橫向圖表修正/交付收據.json` 追溯。

## v5.0 修訂 — 2026-10-12 手機行情與控制列遮蔽修正

產品版本維持 **5.0**；基準 `1f8c909fb72c856346002e4b4c3b2542c1066f2b`。照片及相同資料的修改前畫面重現：市場 12 項固定六欄，禁止換行與裁切讓完整指數及漲跌資訊消失；固定右下轉盤蓋住行情。窄螢幕改採內容欄寬、兩列橫向捲動；手機直式頁尾預留轉盤空間。同畫面另查出 API KEY／通知被頂列擠出，改為保留入口的自動換行。

能力對帳：大盤 7 項、市場 12 項、名稱／完整指數／漲跌值／百分比、原代號點擊委派、頁籤與轉盤均保留；橫向滑動可達末端白銀與原油；Pulse 雙欄樣式未改動。桌面保留既有排列。

局部 Chromium 案例使用正式 HTML 與載入的產品模組，攔截 API／外部字型／CDN，採固定行情並記錄點擊代號：320、375、390 直式及 667×375、844×390 橫式的行情裁切、相鄰控制遮蔽、轉盤重疊與整頁溢位均為零，橫滑、末端點擊及轉盤開啟通過；375 修改前畫面重現原問題，1440×900 保存桌面對照。未執行整套測試。此證據不代表即時行情、圖表載入或 iOS Safari 實機驗收。

一位同供應商唯讀 reviewer 對照來源、量測及五張畫面，無阻擋發現。CI 計畫只含此局部案例，保留安全及部署檢查。當前為待提交候選；後續完整 SHA、CI、合併、部署與實際 runtime 終態以 `AI-Workspace/docs/stock-terminal/手機行情遮蔽修正/` 的交付收據追溯，不把本機排版通過視為已發布。

# Revision History（內部文件 — 不對外分享）

## v5.0 修訂 — 2026-10-12 Yahoo 日線首次來源保全候選

基準提交為 `1f8c909fb72c856346002e4b4c3b2542c1066f2b`，產品版本維持 **5.0**。原因：Yahoo 擷取僅保留解析後日線，取得作業只保存彙總，缺少原始回應與逐筆首次寫入的關聯。本次在既有擷取函式增加可選收據輸出，原本日線清單與研究模式回傳不變；單檔、批次回補、更新及日線快取工作傳遞原始位元組、SHA-256、取得識別與時間。

一般來源收據採獨立資料表及不可覆寫觸發器，不冒充官方品質收據。在相同資料庫交易內，僅對本次新增 bars 保存完整主鍵、原值、寫入時間、runId 與收據關聯；日線快取工作另將 jobId 存入既有 bar_ingest_runs payload。後續修訂另存來源關聯，保留既有修訂內容雜湊與去重行為。若 bars 曾被別處刪除，但首次證據仍存在，重插主鍵會拒絕並回復該次交易，不覆寫既有首次證據。既有 rows、bars schema、盤中排除與讀取快取策略不變。歷史十五筆首次來源仍未知，沒有回填、重抓、覆寫或資料修復。

本輪 Sam 明確要求「補完，不跑測試」：未執行測試、lint、compile、build 或啟動服務，只做變更閱讀及提交完整性核對。這是未驗證的本機候選，未推送、未部署，不能宣稱歷史污染已修復或執行期已生效。完整提交識別由同目錄外的交付收據對應。官方批次與其他行情擷取器尚未接入此一般來源收據；沒有證據的舊資料維持未知。

## v5.0 修訂 — 2026-10-11 全域驗證範圍與有效證據沿用

後續局部補正：PR 的 Ubuntu 流程通過；Windows 唯一失敗為暫存目錄長路徑與 8.3 短路徑的字串比較，改用既有的 `os.path.samefile` 檔案系統身分契約。CI 證據改以案例為成功單位，已完成但部分失敗的工作流仍可提供其他已通過案例；失敗、取消與來源不符的證據不會冒充成功。只補驗受影響的流程案例，沒有增加產品全套測試。

收據回復同步保留失敗、損壞與進行中紀錄，由命中案例的嚴格檢查拒絕原樣重跑；不以丟棄失敗檔案製造「沒有證據」。最終流程案例維持 53 項，所有本機補驗仍限本次三組流程。

基準提交為 `3a2356134a4fdc4b4e6a9232779594097a9f1b1d`，產品版本維持 **5.0**。Sam 明確要求修正全域執行方式、CI 與發布 stage，只驗修改處並沿用有效證據；本次禁止 ST／WD 全套驗證。通用工具由 `tools/codex/` 版本控管，安裝至 `C:/Users/Sam/AI-Workspace/tools/codex/`，適用所有專案；ST 為本次同步接入者，其他專案既有 CI 不宣稱已自動更新。

日常 CI 使用明列變更計畫，未知範圍或無關案例拒絕執行，不自動擴成全套；原跨平臺完整 CI 保留於僅接受明確授權的手動 workflow。每項靜態案例以真實輸入、驗證器及環境為識別，相同內容跨提交可沿用，提交 SHA 僅保留來源追溯。全域防呆要求變更、契約、案例與依賴對應，拒絕已知全套命令偽標局部，保留失敗、漂移、逾時及當次觀測不得沿用的保護。

stage 使用指定 Git 封存的驗證器與計畫，驗證後重建並確認內容一致；manifest 綁定完整案例收據。必要的逐檔完整性、資料保留、鎖定、程序歸屬與部署身分契約保留，略過驗證仍不能 promote。舊版同 SHA 的已通過 stage 可沿用。本機首次局部驗收 51 個流程案例通過，約 15 秒，使用非 ST 小型 Git fixture、假 runner 與隔離安裝根；沒有完整 ST／WD、真實 stage 或正式服務切換。後續修改只補驗受影響流程，未變部分沿用證據。實作 SHA、全域安裝、CI、合併及限制記於 `AI-Workspace/docs/stock-terminal/驗證範圍修正/` 的交付收據。

## v5.0 修訂 — 2026-10-11 WaveDeck 市場唯讀跨來源修正

產品版本維持 **5.0**；基準為 `d4bad079d14de1493224d2528fe1717d2a1925c9`。WD 原有宏觀面板呼叫 `/twindex`、`/breadth`、`/fundamental/^TWII`，ST 僅替橋接路徑回傳跨來源標頭，導致三個請求在瀏覽器被拒絕。沿用三支 API、原始欄位及既有 WD 埠清單，新增獨立的 GET 授權；來源只接受精確的 HTTP loopback 位址，預檢僅允許 GET。POST 的來源檢查與原橋接白名單保持原狀，其他代號、路徑、外部來源及 Private Web 保留埠不開放。

能力對帳：原 WD 三項宏觀資料由跨來源拒絕恢復為可讀；市場資料組建與畫面程式原樣保留；原橋接、同源寫入與拒絕邊界經局部整合案例驗證保留。修正前瀏覽器重現三項 CORS 錯誤；候選用同一真實 WD 頁面、實際 API 回應快照與待交付 HTTP 處理器，三項請求皆成功，CORS 錯誤為零，指數、廣度與體質評分顯示符合 payload。此項為隔離候選驗證，不代表正式服務已更新。

本機 27 項局部測試通過，涵蓋 HTTP 安全、WD 橋接、HTTP 邊界及新增靜默例外棘輪；新增正向案例先確認舊版失敗。一次同供應商隔離差異覆核無具體缺陷。未受影響的策略、券商、不留倉及版面沿用基準版本既有證據，不重跑。當前為可審查候選，尚未 push、CI、合併或部署；新 SHA 的既定完整 stage 尚待明確驗證授權。完整 SHA、檔案雜湊、局部驗證及後續發布終態由 `AI-Workspace/docs/stock-terminal/WD唯讀跨來源/` 的交付收據追溯。

## v5.0／WaveDeck 0.1.21 修訂 — 2026-10-11 PowerShell UTF-8 測試輸出

完整 stage 在本機 Windows 的 CP950 環境下，兩個 PowerShell 引擎的 Python pin Unicode 測試都因巢狀子程序輸出依主控台編碼、而測試固定以 UTF-8 解碼，將「驗收」讀成替代字元。檔案讀寫本身正常；僅調整測試 driver，明確設定 UTF-8 輸出，保留原路徑與 pin 內容斷言。原 WaveDeck pin 子案例已有相同設定。修正後針對兩引擎的單案例及巢狀捕捉輸出重現均通過；產品程式未改。最終完整 stage、正式服務與本機服務狀態由本次交付收據記錄。

## v5.0／WaveDeck 0.1.21 修訂 — 2026-10-10 瀏覽器控制回應同步

合併提交 `a53adbe3a87ee80f226f578328230fa69d458e45` 的主分支 Ubuntu CI，在 WD 瀏覽器測試的四指令斷言只讀到前三筆。隔離的正式 HTML／JS／CSS 重現：點擊 refresh 返回時，非同步路由尚未完成呼叫紀錄；受控 Promise 釋放並等到該筆回應後，原四指令完整斷言通過。測試改為在點擊前等待精確 POST 路徑與指令回應，同類模擬按鈕也同步處理；保留原順序、次數與全部介面斷言，不增加固定延遲、不放寬逾時或略過失敗。產品程式未改，完整 stage 與服務切換尚未執行；實際 CI、驗證及發布終態由本次外部交付收據追溯。

## v5.0／WaveDeck 0.1.21 修訂 — 2026-10-10 交付封裝補正

PR #186 的首次 Ubuntu CI 在完整單元階段指出兩項交付缺漏：追蹤 HTML 尚未同步新增的策略版本模組引用，分享契約文件含個人工作區絕對路徑。依既有建置器重建追蹤 HTML，並將分享文件的證據位置改為工作區相對位置；不變更內容掃描規則、不放寬斷言。後續 CI 的 JavaScript 階段指出 WD 舊介面自測仍要求 0.1.20，已依本次進版同步為精確 0.1.21，所有介面能力斷言保留。只定向核對原失敗條件，後續精確提交的 CI 與首次完整 stage 仍為發布門檻。產品策略與執行程式未改，既有局部行為證據沿用；失敗日誌與補正收據保存於本次外部證據目錄。

## v5.0／WaveDeck 0.1.21 修訂 — 2026-10-10 固定策略驗證與執行確認

Stock Terminal 產品版本依既有規則維持 **5.0**，WaveDeck 更新為 **0.1.21**。基準 `f2db8085851c44e76f21d519b601ca820d4f733a`，包含前一筆已提交的決策 AI 近端回饋修正。組合器原本只將內建八策略接到訓練／測試切分，本次新增固定自訂條件的樣本外路徑，保留原一般回測與八策略入口；新增不可覆寫的條件／執行／商品版本及報告 JSON。仍限既有股票、ETF 日線與下一可成交開盤模型。

WaveDeck 沿用稽核資料庫保存版本與訊號收據，區分 AI 裁量及依固定規則執行；錯誤版本、商品、週期、過期、逆序與變造重播會拒絕。原始訊號與風控結果分開保存。TXT 不再因缺檔造出示範持倉，新增委託追蹤、可選成交回報與部位讀回，送出不直接宣稱成交。不留倉從顯示設定補齊為提前禁新單及獨立每秒截止平倉，保留急停與未完成狀態。桌面舊操作入口保留，手機內容裁切與敘事重疊一併修復。

本機定向證據：ST 自訂樣本外與原成交核心、版本／下載及同尺寸瀏覽器互動通過；WD 不留倉 19 項、券商確認 18 項、分次整合 12 項、實際隔離 HTTP／並行急停／敘事與版本身分 7 項通過。既有 WD smoke 與敘事 29 項、發布 runner 選取案例 1 項，以及 HTML 建置與載入順序檢查通過。各項為對應版本及受影響範圍的分次證據，未宣稱已執行本機完整套件。ST 與 WD 皆有桌面／窄螢幕離線互動驗證；ST 窄螢幕前後截圖的同名覆蓋缺口已在能力對帳文件揭露。

一位同供應商隔離 reviewer 提出三項 P1：急停與一般送單並行、成交回報已到但帳戶未核對時可反向、缺帳戶檔時以舊快照入場。均已修正並加入原觸發條件測試；缺帳戶整合另攔截 FSM 誤宣告持倉，修正後原失敗案例通過。AI 敘事移出送單鎖，新增並行案例確認敘事阻塞時截止平倉仍可完成，舊敘事不會覆寫較新的部位。未對實盤下單、未改研究升格閘門，外部規則計算、期貨回測與每日截止的行事曆限制見 [策略版本與執行契約](策略版本與執行契約.md)。

此條目前為本機候選；完整 SHA、allowlist、檔案雜湊、測試證據及後續發布狀態存於 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/st-wd-strategy-20261010/交付收據.json`。完整 CI 與 stage 尚未執行；ST 及 WD 正式服務尚未更新。既有修訂歷史保留，後續以發布收據補記實際狀態。

## v5.0 修訂 — 2026-10-10 決策 AI 解釋就近顯示

產品版本維持 **5.0**；基準為 `ca63bdfe79d01d8cabe795fac53a2bf176353cd2`。原 AI 按鈕位於頁首，但載入訊息、結果及錯誤卡片在長頁面的右欄最底部，窄螢幕還會排在全部左欄內容之後，容易誤判沒有反應。Chromium 固定資料重現：1440×900 畫面中，等待卡片從 y=923.52 開始，超出畫面。

沿用既有 AI 狀態、權限及請求契約，將唯一解釋卡移到操作列下方的持續節點；等待、完成及錯誤都在同區顯示，正文調整為 14px 並支援長文字換行。按鈕關聯結果區，主動點擊帶到解釋標題並提供簡短即時狀態；完成與市場資料背景重繪不主動捲動。首次權限查核也立即顯示等待並防止重複送出。市場資料、AI 提示、模型端點及投資判斷契約維持原狀。

本機局部驗證：桌面 1440×900、窄螢幕 390×844 的 Chromium 案例通過，修正後等待卡片分別從 y=77.73、y=122.73 開始；鍵盤觸發與焦點、等待、成功、失敗重試、長文、兩倍 CSS 縮放，以及背景重繪與完成時的閱讀位置均已驗證。既有 AI 自測、新增首次權限確認三種結果，以及權限通過但缺少決策資料的分支均通過；新增瀏覽器案例接入既有 CI，防止回復到底部。既有 HTML 建置入口通過。沒有執行完整測試套件、真實模型運算或正式站驗收。

同供應商唯讀差異審查發現「首次權限確認完成但缺少市場資料」可能殘留等待正文並誤標完成，已在缺資料分支同步近端錯誤及更新指引，並用新增回歸確認模型呼叫為零、按鈕恢復、狀態明確未完成。Reader 狀態另標示「此帳號僅可閱讀」，避免顯示無法使用的重試指引。

本條為本機交付候選；提交完整 SHA、來源雜湊與驗證收據見 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/decision-ai-visible-20261010/交付收據.json`。尚未推送、合併或部署，CI 未執行；正式及本機受管服務不受本輪工作樹修改影響。舊修訂歷史保留。

---

## v5.0 修訂 — 2026-10-13 選擇權結構的新鮮度改為讀取時重算

產品版本維持 **5.0**；基準為 `3b67d2d3d069e08c60e8b1285730f6874358894f`。**候選，未發布**：本條建立時是未提交的候選；合併 SHA、精確提交的 CI 與發布狀態以新段落或發布收據補記，不在這裡預先寫入。

**問題**：2026-10-07 兩份截圖顯示，本機 ST 的「台指選擇權結構」標示「資料完成」，但資料日是 2026-08-14，而正式站同一區塊標示「資料過期」。原因在程式：`options_exposure.build_options_structure` 在建立快取的當下依資料日算出 `status` 與 `modeled.eligible`，快取檔照存；之後 `GET /options/txo/structure` 與 Pulse／決策組裝都直接取快取（`latest_cached()`），不再重算。所以幾週前建立、當時是 ready 的結構，之後一直顯示 ready。

**修正後行為**：新增 `with_current_freshness` 與 `latest_current`。讀取時用現在日期，以建立快取時同一個判斷（`_date_ready`：資料日必須是最近一個已完成交易日，且不是當日、日曆須涵蓋）再核對一次；原本 ready 但現在不符的，改為 `stale`、`modeled.eligible=false`、`quality.ageCalendarDays` 更新為現在的天數，並加上 `STALE_OR_HYBRID_REFERENCE`。只降級、不升級；`stale`、`insufficient` 與沒有資料日的值不受影響（沒有資料日的 ready 會被視為過期）。傳入的快取物件不被改動，快取檔也不被改寫。`GET /options/txo/structure` 與 Pulse 組裝改讀 `latest_current`；更新排程與 TTL 判斷仍用 `latest_cached`。

**使用者可見資訊的減少（規則 0009 第 1 項）**：資料日已落後的選擇權結構，原本可能仍顯示「資料完成」與情境式 Gamma／Vega 表；現在會顯示「資料過期」，情境表以既有的「模型已停用」說明取代，仍可閱讀上方官方 OI 事實。這是預期結果，不是新增的隱藏。

**驗證**：`tests.test_options_exposure` 新增 7 項（舊程式上全部失敗，已驗證），含舊快取數週後轉為過期、下一交易日早上仍為 ready 且原物件回傳、新交易日收盤後轉為過期、不升級、`latest_current` 不改寫快取、GET 路由與 Pulse 組裝都讀現在的版本；既有的日曆新鮮度、hybrid、分層案例保留。另跑選擇權更新排程、決策脈絡、關鍵價位守門、決策資料品質、決策 HTTP、統一更新中心、審查回歸共約 175 項，皆通過。依 `.github/驗證計畫.json` 的兩個案例由 CI 執行。

**限制與沒做的事**：沒有用即時 TAIFEX 資料驗證；沒有改畫面（徽章會自動改成「資料過期」，但沒有新增「N 天前」字樣）；沒有改變選擇權的更新時機。程式裡確有每日自動更新（`server/options_schedule.py`，交易日台北時間 07:00–08:30 的四個時段），但必須在 `data/options_daily_schedule.json` 設 `enabled: true` 才會送出，且只在 ST 正在運行時執行；兩個執行環境是否啟用、是否成功，需要查看各自的 `data/options_daily_schedule.json` 與 `data/options_daily_attempts.json`，這次沒有證據。本機與正式站不共用 DB（`docs/本機與正式版本同步.md`），兩邊資料不一致的架構問題不在這次範圍。審查：僅作者自審，沒有隔離審查。

---

## v5.0 修訂 — 2026-10-09 發布驗證去重與 Chromium 快取

依發布耗時 8D 改善 CI 與 stage 的重疊工作：分支 push 不再與 PR 重複觸發完整 CI，保留 PR 及 main push 的四項必要工作；同一 PR 的舊回合可取消，main 驗證不取消。CI 及私有發布 stage 移除獨立的 dist 測試命令，由原完整 tests discovery 執行同一批案例一次；WaveDeck 隔離測試、JavaScript、自測後重新封存與所有完整性保護保持。

Chromium 使用 runner OS／架構與 package-lock 雜湊隔離的快取；命中快取仍執行既有安裝命令，保留 Linux 系統依賴檢查及全部瀏覽器驗收。首輪可能未命中，未取得命中收據前不宣稱節省秒數。

後續修正：Actions 快取不接受 `..` 路徑段，改用工作目錄名稱加尾碼的同層絕對目錄，避免測試通過卻未保存快取；以實際保存收據確認功能。

本次只修改發布工具、CI 與對應測試，VERSION 維持 5.0，沒有產品 runtime 行為變更。局部驗證與提交／CI 終態以 `AI-Workspace/docs/stock-terminal/release-workflow-efficiency/` 的同版本收據追溯；未取得的結果不視為通過。共用記憶同步另受環境限制，既有修訂歷史完整保留。

---

> 各版本「改了什麼 / 修了什麼」的詳細紀錄,內部追蹤用。
> 對外分享的功能介紹在 `README.md`;本檔由 `scripts/build_dist.bat` 排除,不進分享包。

---

## v5.0 修訂 — 2026-10-09 Git 封存的批次檔保留 CRLF

產品版本維持 **5.0**；基準為 `5d00b2db09f897669a8570b6560815a8683521e2`。該版四項精確 main CI 通過，但完整 stage 執行 1,669 案後唯一失敗為 `START_ALL.cmd` 的 CRLF 檢查（513.150 秒；略過 5 案），原始失敗日誌保留，正式與本機受管服務尚未切換。根因為新根目錄 `START_ALL.cmd`、`START_WAVEDECK.cmd` 漏列既有 `.gitattributes` 的原始位元組保護；`git add` 把來源 CRLF 正規化成 LF，Windows checkout 又轉回 CRLF，掩蓋正式發布器使用 `core.autocrlf=false` 封存時的差異。

僅為這兩個根目錄 CMD 加入與既有批次檔相同的 `-text` 及換行空白規則，並將現有 ASCII／CRLF 位元組重新明列暫存，不改啟動邏輯、發布器或原 CRLF 斷言。新增真正 Git 暫存儲存庫的封存回歸：在 `core.autocrlf=true` 下提交四個啟動入口，再以正式發布器的封存命令取得原始位元組，逐份核對 ASCII、CRLF 及與原件完全相等；舊規則只在兩個新根入口失敗。回歸放在分享包原本排除的 Private Web 測試模組，沒有新增分享包依賴。

新封存回歸一案通過（0.568 秒）；原規則的負向回歸僅兩個新根入口失敗（0.573 秒），原日誌與方法搬移資訊完整保留。本條為封存失敗後的本機補正候選；只驗證本次封存與啟動器修改範圍，不額外執行完整本機測試套件。固定 Git blob／tree、提交與推送，以及新精確 main 的 CI、完整 stage 與雙端發布結果，以 `AI-Workspace/docs/stock-terminal/launcher-all-20261009` 的同版本收據追溯。既有 WaveDeck 原生隔離啟動與前端結果僅在來源位元組未改變時重用，不能冒稱新的完整 tree 已經驗收。所有舊修訂歷史保留。

---

## v5.0 修訂 — 2026-10-09 整合 Stock Terminal 與 WaveDeck 啟動入口

產品版本維持 **5.0**；基準為 `4deea9f617a0d35e2f5b60faddf01695ad979c5e`。原 `START_LOCAL_AND_WEB.cmd` 只啟動服務與列出網址；新增就緒後開啟 Pulse，以及 `--no-browser` 選項。新增 `START_ALL.cmd` 串接既有 local／Private Web 與 WaveDeck 入口，保留 local／web 的退出碼，另以位元 4 表示 WaveDeck 未就緒。

WaveDeck 仍沿用 `run.py`、釘選 Python 與原有埠 fallback；將無條件刪除埠收據／重複啟動改為先核對健康回應的服務、目錄、實際埠與布林就緒欄位。健康端點新增目錄、Python、PID 與實際埠身分；不改 provider、執行模式或券商設定。啟動在背景執行並保留 stdout／stderr 日誌，等待有三十秒期限；不停止任何未知程序。缺少身分的舊 WaveDeck 會明確拒絕重複啟動。移除健康處理函式內與既有全域名稱重疊的 `sys` 匯入，避免新身分欄位發生區域變數未綁定。

定向驗證：真實 CMD 串接、開頁邊界與原有 local／web 健康契約共 **26 案通過**；真實 PowerShell 5.1 的 WaveDeck 離線邊界共 **7 案通過**，涵蓋已在線重用、保留埠、身分型別、Python pin、fallback、逾時與啟動失敗；探測或 Python 解析耗盡期限後不再啟動程序，新期限保護的成功路徑另通過一案。健康端點由動態 loopback HTTP 回應證明實際埠與來源目錄一致。分享包必要檔案及同一內容保護掃描共 **2 案通過**；CMD 保持 ASCII／CRLF，PowerShell 保持 UTF-8 BOM。不同定向案例合計 **35 案**，沒有執行完整測試、完整 stage 或模型第二意見，也沒有啟動或更動受管 runtime。

本條建立時為未提交的本機候選；來源工作樹與定向日誌在 `AI-Workspace/worktrees/stock-terminal/launcher-all-20261009`、`AI-Workspace/docs/stock-terminal/launcher-all-20261009`。沒有 commit、push、部署；既有正式與本機 runtime 版本維持各自現況，所有舊修訂歷史保留。

Sam 隨後授權 commit、push、deploy；初始啟動器候選已提交為 `ce4021e831dccf95a17c915ad43b30a9355ecd94`。發布前沿用 Private Web 原有排除 WaveDeck 的契約，同步排除呼叫 WaveDeck 的 `START_ALL.cmd`，避免受管發布產物留下依賴缺失的入口；主專案與單機分享包保留完整整合入口。負向回歸證明原排除清單會留下該入口；補正後只重驗兩個發布邊界案例，實際發布及最終 SHA 以本輪同版本收據追溯。完整 stage 仍按既有發布門檻執行，不放寬測試或資料保存保護。

Windows CI 補正：提交 `56ca00e0fc8d6a8ff6bc183d14e9c2aa79bf094a` 的自動 push／PR CI（`37856060050`／`37856073708`）在 Windows 單元測試失敗，Ubuntu 與兩項離線研究通過，原始日誌保留。已用 Windows 原生 8.3 別名重現 WaveDeck 同目錄被誤認的行為；啟動目錄與健康身分統一展開為完整長路徑，雙向短／長別名均不得新增程序，八個受影響案例通過（6.999 秒）。舊 Python pin 測試改為 dot-source 正式 helper 並呼叫真正的讀取函式，PS5／PS7、UTF-8 有／無 BOM、Unicode／空白路徑的單一案例通過（2.500 秒），保留原八秒子程序期限。

持久提交測試先同步完成真實 SQLite revision 2 與通知 claim，再以受控通知 worker 檢驗讀者不受發布鎖阻塞；保留原 0.5 秒讀取期限、worker 錯誤傳遞、通知仍等待的斷言及 finally 釋放／回收，不改產品持久化程式。舊讀者搶發布鎖的負向變體實際逾時，真實行為的單一案例通過（0.282 秒）；通知 worker 注入錯誤時能顯示真正的例外。原 hosted 失敗究竟是 SQLite 準備耗時或 worker 錯誤，舊日誌不足以判斷，沒有宣稱已證明該歷史根因。只執行修改部分的定向驗證；新版精確 CI、一次完整 stage 與雙端實際發布結果另以同版本交付收據追溯。

---

## v5.0 修訂 — 2026-10-08 分享包啟動器驗證的個別期限與日誌

產品版本維持 **5.0**；基準為 `c295e34c6519d38b64073edde5f017fcfd2fe564`。該版四項精確 CI 成功，但完整 stage 在真正分享 ZIP 的啟動器驗證失敗：兩個類別共用九十秒，與原有每次 CMD 三十秒／PowerShell 十五秒及多情境累積預算不相容。原始失敗收據保留；另一次相同分享包診斷於 78.641 秒成功，不能據此認定舊失敗為偶發或已找出當時最後阻塞方法。

將四種退出碼及數值排程狀態／語言顯示拆為各自具名案例，保留全部原斷言及 CMD／PowerShell 期限。真正封裝後以個別九十秒期限執行完整啟動器模組，包括大型合法 JSON、嚴格型別與原生等待；不再讓整批案例共用單次請求的期限。每案從程序啟動即寫 stdout／stderr 日誌，避免 Windows 的 PIPE 逾時例外沒有部分輸出。若尚未確認程序終態，保留自有 handle、fixture 與既有日誌，不猜測子樹已停止或刪除仍可能使用的目錄。

定向驗證以真分享 ZIP 執行：發布保護與分享包回歸 **12 案／96.367 秒、退出 0**，ZIP 內 **20 個具名啟動器案例全部退出 0**，Windows 無略過；最慢一案 20.062 秒。來源前後雜湊與基準 HEAD 一致。本條建立時為未提交候選；新精確 main 的 CI、完整 stage、正式／本機更新及最後實機驗收另以同版本交付收據追溯。此測試與文件補正沒有自動追加 Claude 呼叫，也不將已驗收的舊模型來源說成新版完整 tree 的覆核。所有舊修訂歷史保留。

---

## v5.0 修訂 — 2026-10-08 大型健康回應的啟動器判讀

產品版本維持 **5.0**；基準為 `a6120534166d551193c6c6b89959aed2837d7c94`。該版已完成四項精確 CI、完整 stage 與正式／本機受管更新，但最後的雙端啟動器實機驗收發現 local 誤報離線：健康端點回傳 HTTP 200、合法 JSON 及正確 runtime SHA，單行約 145 KB，原 `findstr` 仍回傳失敗並顯示行過長。原始失敗、服務身分與資料保存證據均保留，不把前面的部署成功當作啟動器驗收成功。

離線重現顯示長度不是充分條件：合法大型 JSON 的 runtimeCommit 欄位在前、後續診斷欄位很長時，文本匹配會遺失先前結果；較短或欄位置末的案例可以通過。修正沿用既有 `/health` 及 `/gateway/health`，以 Windows PowerShell 5.1 的 JSON 解析器讀取完整回應，每次請求仍有三秒逾時。local 要求 runtimeCommit 為完整 SHA 字串；web 要求 upstream 為布林 true，字串等其他型別不能顯示就緒。保留分離啟動、排程 Running 防重啟、標籤、40／20 次有限輪詢、四種退出碼及 ASCII／CRLF；等待文字改為檢查次數，不把輪詢間隔當成整體牆鐘上限。

有效負向案例使用合法約 200 KB 的固定健康 JSON，所有外部啟動與來源均隔離。健康解析語意另以真實 PowerShell 執行原命令，只替換 HTTP 函式的取得資料邊界。修正來源在同一個實機環境回傳 0、兩端 UP，三個 listener 的 PID 與建立時間完全不變；此結果仍是補正來源搭配前版 runtime 的回歸，新精確提交的 CI、stage、部署與最後驗收另由同版本收據證明。

本條為最後實機驗收新增的 Codex 修正，沒有自動追加 Claude 呼叫；既有有效 Claude 結果保留各自來源版本，不能宣稱已覆核此新程式差異。完整原始歷史保留，相關證據置於 `AI-Workspace/docs/stock-terminal/review-fixes-20261008`。

---

## v5.0 修訂 — 2026-10-08 工作清理測試的一致快照

產品版本維持 **5.0**；基準為 `e622049a6c7cbe4a7cfcdafbad3962bba6d77d79`。精確 CI `37753208119` 的 Ubuntu 測試及兩個離線研究工作成功，Windows 單元測試唯一失敗為註冊清理觀測。完整失敗日誌保留，不將這次失敗稱為 flaky，也不沿用前次失敗根因。

產品在持久終態提交後，以同一把 RLock 清理 callback、查詢同種類的活動工作，再決定是否清理 handler。測試先前只觀測 callback 消失，可能看到 handler 尚在的中途快照。終態等待改用同一把鎖取得一致快照，取得鎖仍受原四秒總期限約束；同種類還有第二個排隊工作時，handler 保留的原斷言不變。新增以事件刻意停在 callback／handler 清理之間的真 SQLite 案例：舊等待方式失敗，修正後等到完整清理才返回；產品程式及清理順序沒有變更。

佇列期限、每日工作、註冊生命週期及既有審查回歸 **96 案／6.325 秒、退出 0**。新精確 main 的四項 CI、完整 stage 及雙端部署仍由各自實際收據追溯；不增加測試等待期限、不刪除失敗斷言、不改品質保護。

---

## v5.0 修訂 — 2026-10-08 精確 main CI 的測試假造點補正

產品版本維持 **5.0**；本條基準為 `c45ae11780995cd2a84132db860ba31a3c90bfe0`。該提交的 CI `37750774977` 在 Ubuntu 與 Windows 單元測試皆失敗，兩個離線研究工作成功。完整原始日誌保留，本次只修正兩個已證實的測試缺陷，不放寬產品品質、發布隱私檢查或等待期限。

SQLite URI 守衛測試的合成 Windows 路徑改用通用 `C:/fixture`，仍核對磁碟代號、絕對根與百分比編碼只解碼一次，避免個人目錄字串觸發既有發布保護。movers 的舊觀測測試改為假造實際使用的 `http_client.fetch_json` 與固定產業分類，額外拒絕並核對 urllib、HTTP 連線池及 socket 都未呼叫；健康案例須讀到兩筆預期榜單，原先移除及還原正式模組既有 math 的 NameError 觀測保留。

修正前兩項離線重現均失敗；修正後 URI、fallback、未定義名稱與實際分享 ZIP 的相關 **28 案／35.985 秒、退出 0**。Claude 已驗收的覆核仍綁各自固定候選，這次僅有測試與文件的後續補正由 Codex 驗證；新精確 main 的四項 CI 與完整 stage／部署結果另以交付收據記錄，不將舊候選或失敗 CI 當作新版通過證據。

---

## v5.0 修訂 — 2026-10-08 跨平台測試路徑與覆核限制

產品版本維持 **5.0**；提交基準為 `3bdd02da77bf0bd9fc62665387236e9bf5ea1164`。Claude 已實際覆核候選 `6e68b9bf977227093c693d64345f3251724394b9` 的來源期限、日線、工作終態與啟動器補正，取得有效材料與來源指紋收據，並指出新增 SQLite 測試的 POSIX URI 守衛問題。本條為該意見的修正紀錄；最終候選、Pulse 覆核、精確提交的 CI 與發布狀態，依 `AI-Workspace/docs/stock-terminal/review-fixes-20261008` 的同版本交付收據追溯。

測試守衛沿用標準函式庫的本機 URI 路徑轉換，保留 POSIX 的絕對路徑根及 Windows 磁碟代號，百分比編碼只解碼一次。新增兩個離線案例，分別核對兩種平台的真轉換器與一般路徑不解碼；原八個真 SQLite 儲存、修訂中繼資料故障與恢復案例保留。修正前的 POSIX 絕對路徑重現失敗，修正後十個相關案例於 Python 3.12 通過（0.553 秒、退出 0）。前條 1,632 案及 Python 3.14 結果對應本次 URI 守衛補正前的固定候選；後續精確提交的整套 CI 與 stage 結果另記錄。

本次 cp950 負向變體驗證的對象是 PR #170 的兩處發布清單讀取；不將其說成所有程式文字檔的編碼驗證。來源耗盡本次呼叫端整體期限時，不設定共用六十秒冷卻；來源持續緩慢可能在三十秒部分結果快取期滿後再使用一次呼叫預算，這是保留其他共用者可用性的取捨。每日工作的持久終態仍保留完整快照及日期明細，來源受既有五標的／五年限制，佇列保留最近一百筆；更新清單的序列化成本尚未量測，不宣稱已觀測到效能事故。

既有 `_get_tw_universe` 的官方宇集抓取仍使用 `urlopen`，部分來源失敗後可能沿用當日部分結果。原 PR #174 第一親代完整差異與三個呼叫端證據顯示該函式未被修改；目前保留為原契約範圍外的已知限制。舊 hosted Windows CI 的首次工作者堆疊及 ICU 起訖仍無法取得，唯一歷史根因維持無法判斷；正式日線疑點繼續只作唯讀診斷，不覆寫正式資料或原始證據。

---

## v5.0 修訂 — 2026-10-08 來源期限、日線中繼資料與工作終態補正

產品版本維持 **5.0**；基準為 `3bdd02da77bf0bd9fc62665387236e9bf5ea1164`，接續候選 `28a756efa777381f8f40ce0bb4a1ef37ec92d26b` 的實際 Claude 唯讀意見。本條建立時為未提交本機候選；最終完整 SHA、提交、推送、整合、覆核與正式／本機發布狀態，由 `AI-Workspace/docs/stock-terminal/review-fixes-20261008` 的同版本交付收據追溯。

共用 HTTP client 以相容的 TimeoutError 子型別分開表示整體請求期限；分類查詢因本次期限耗盡時，保留來源錯誤鏈及計數，並將部分結果交回呼叫端，避免設定共用來源的六十秒負快取。真正的 HTTP 503 與來源自身逾時仍依原契約冷卻。發布清單的測試 fixture 使用實際 UTF-8 非 ASCII 內容，強制模擬 cp950 預設讀取；移除任一明列 encoding 的負向變體均失敗。

每日日線來源預算仍為六百秒，持久佇列只為終態保存與收尾提供六百六十秒；其他舊 callback 的預設仍為三百秒。每日工作的終態快照在本身鎖內取得，來源失敗會反映到持久工作失敗，避免新工作覆蓋上一個結果。legacy callback 與註冊函式在終態成功提交且同種類沒有活動工作後回收；拒收、合併、第二個排隊工作及重啟中斷均保留正確收據。

日線儲存、讀回與來源修訂中繼資料分層處理。寫入與讀回成功後，即使修訂狀態故障，也保留已讀的新日線、明示品質待確認及六十秒重試。期滿可只讀既有資料庫確認中繼資料，資料已完整或禁止連網時仍能恢復；真正的歷史修訂與未知年度警示保留，盤中額外資料不因中繼資料未知而混入歷史。真 SQLite 回歸同時核對首次原價格、修訂證據雜湊及無額外來源抓取。

開發啟動器在執行期拒絕空白或省略的釘選 Python、基礎 Python 與 CMD 身分；即使間接呼叫，也不會寫入自動停止收據。真強身分鏈、舊收據的自有程序、未知 listener 與 CIM 失敗均有明確測試。雙端啟動器補上孤兒 gateway 的受管停止與重試提示，維持 ASCII／CRLF 與有界等待。選擇權文件補明年度未知時手動與自動更新的限制，以及日期、ready 與來源品質共同完成條件。

shell 在缺少效期模組且已有報價時顯示待確認；恢復效期模組後回復正確燈號。Pulse 測試在 HTTP 停止失敗、執行緒未退出或拋例外時，仍嘗試停止佇列，保留全部隔離與目錄並中止後續案例。

實際驗證：完整 Python 3.12 為 **1,632 案／375.193 秒、退出 0、skip 1**；唯一 skip 為未啟用 `MARGIN_LIVE_TEST` 的官方網路探測。Python 3.14 相關案例 **150 案／146.168 秒、退出 0**；真正分享 ZIP 與修訂故障回歸 **2 案／22.849 秒、退出 0**。第一輪完整測試的兩個失敗日誌保留：同一舊 fixture 在原始碼與分享包假造未寫入後仍要求舊資料，已改用真 SQLite 寫入並分層斷言，原短快取與恢復驗證保留。

本輪較舊四包有效 Claude 結果只綁原候選，Pulse 包必要材料不足的回答保留為未驗收；新版固定來源的最後覆核結果另記錄。舊 hosted Windows CI 首次工作者堆疊與 ICU 起訖仍未取得，唯一歷史根因維持無法判斷。正式歷史日線仍僅作唯讀診斷與修復方案，保留全部既有修訂歷史及原始證據。

---

## v5.0 修訂 — 2026-10-08 覆核補正與共同邊界驗證

產品版本維持 **5.0**；本次以 `3bdd02da77bf0bd9fc62665387236e9bf5ea1164` 為基準，補正已固定候選 `039347c2adda63c7e0d9a0b562e94200f793953c` 的覆核意見。提交、Claude 材料驗收、CI 與發布結果分別保留交付證據。

選擇權結構與早晨排程共用既有官方年度日曆的前交易日判定，長假不再用四個日曆日誤判過期。未知年度、同日未完成資料及現貨日錯配仍不得發布；保留實際日曆年齡。快取須同時滿足資料日及既有 ready／來源品質條件才算完成；過期、錯配或來源失敗只在下一時段重試，同時段收據與預設關閉保護保留。新增真模型、真 refresh 與既有市場協調器的離線長假案例。

HTTP 沒有 CL／TE 的拒絕請求不再空等排空期限。標準函式庫的 501、靜態檔案 404 及 parser 尚未建立標頭的錯誤亦走安全共同邊界；原回應狀態與格式保留。成功 OPTIONS 若宣告本文則在有界排空後關閉連線，無本文仍保留 204 與連線重用。暫態來源重試用盡退避預算時，保留原錯誤因果鏈、最後 HTTP 狀態與一次終態錯誤計數；實際等待因排程延遲超過期限時，也在下一次請求前保留同一原因與計數。movers 與類股成員的部分結果縮為 30 秒快取，完整結果維持 300 秒；保守分類及來源品質條件不放寬。

新舊日線 HTTP 入口共用拒收契約：佇列拒收回 503、忙碌回 409、空標的回 400。未知年度不得冒充休市；仍沿用既有失敗邊界與來源狀態。補抓儲存或讀回失敗時保留本次已讀資料與原原因，結果及防重抓快取採 60 秒，期滿可再次更新。補上同庫日曆滿七日、過期、未來時間與來源白名單案例，未新增日曆來源或背景刷新服務。

行情刷新收到缺漏或空報價時保留最後有效報價與失敗訊息，shell 在效期模組缺少時亦不得顯示成功。假時鐘驗證正式 shell 的 fresh／失敗／delayed／stale／恢復路徑。Pulse 同步補上來源阻塞時的真正 SQLite 寫入及短交易合併驗證，SQL 明列欄位。Decision 與共用其 fixture 的情境投組 HTTP 測試，在所有工作者確認停止前保留主類與子類的全部隔離設定、不刪除目錄；任一停止失敗或拋例外即停止測試批次，停止期限不放寬。

雙端啟動器改用不依 stdin 的原生等待，移除無呼叫的 gateway-only 判定。孤兒 gateway 與後端失效時仍明示 DOWN，不按埠停止或新增第三套服務。啟動器 AST 驗證要求所有正式收據寫入呼叫明列三個既有強身分引數；不改收據介面、不合併 PR #168。補原生 stdin 導向等待、真 host 拒絕既有 gateway 與明列引數防退化案例。

檔尾「A–M 審查修正（未提交本機候選）」及「審查缺口與發布候選」保留其當時狀態；後續修正應依上方較新的條目與交付證據判讀。舊 hosted Windows 首次阻塞的工作者堆疊與 ICU 起訖證據已無法取得，唯一歷史根因仍為無法判斷；目前通過的測試不能替代該證據。正式歷史資料仍僅有可稽核的唯讀診斷與修復方案，沒有依最後一筆 revision 覆寫原始日線。

---

## v5.0 修訂 — 2026-10-08 拒絕請求的有界連線收尾

產品版本維持 **5.0**；基準 `3bdd02da77bf0bd9fc62665387236e9bf5ea1164`。完整 stage 測試中，帶負數 `Content-Length` 及實際本文的拒絕案例曾在讀取回應時發生 Windows `10053`。讀碼及失敗單元確認：舊收尾對無效長度直接返回，留下未讀位元組；這與該次連線中止相符，但不宣稱已取得作業系統層的唯一原因。

共同拒絕邊界先停止連線重用，合法小本文仍只排空尚未讀取的指定長度；無效、重複、過大長度或 transfer framing 則只丟棄原始位元組，最多 64 KiB、共用 0.1 秒期限，每次最多 8 KiB，不解析殘留請求，也不無限等待。已完整讀取的合法本文不重讀。原本內容解析的大小保護、400／413／415／403 回應與關閉連線斷言保留；慢送或超過收尾上限仍可能由傳輸層中止，不保證非法客戶端必定收到完整 JSON。

新增失敗先驗、總量／總時間／timeout 還原案例，並重驗原 Windows HTTP 情境；最終完整測試、Claude 覆核、提交與發布結果另以交付證據記錄。保留全部先前修訂歷史。

---

## v5.0 修訂 — 2026-10-08 正式版本第二意見的補正

產品版本維持 **5.0**；本次基準為已發布的 `776099b0d99d3b25831eeddd67c362fa84d7182c`。以下追加紀錄，保留全部先前歷史；最終提交、覆核及發布結果以各自的交付證據辨識。

HTTP client 對已連線回應的標頭及本文共用截止時間，超時中止 socket，並在歸還連線池前停止計時器，避免緩慢標頭與計時器競爭。官方分類查詢以同一 client、同一期限處理有限的同來源重新導向；缺少位置、跨來源與迴圈均明示失敗。

共同日線寫入入口優先沿用同一資料庫已取得、七日內更新且結構有效的官方年度日曆，避免靜態交易日蓋過已核對的休市或臨時開市；舊或缺少同庫收據時，只回退已涵蓋的靜態年度，未涵蓋年度不認定當日完成。盤中及所用日曆的休市日仍拒絕未完成資料；結構無效的同庫日曆明示失敗。補上合成跨年、同年度日曆衝突、臨時開市、直接寫入與匯入案例，沒有新增來源或推定尚未公告的年度日曆。正式歷史資料仍僅作唯讀診斷與修復提案。

每日留存佇列在拒收、SQLite 錯誤與收據後例外時轉明確失敗並取消工作預算；失敗後可再次提交，遲到工作不得執行。Owner 警報規則只在伺服器接受後更新確認狀態，失敗的新增、刪除或複合條件不得隨下一次操作靜默寫入；重複寫入有明確等待提示。日線選擇被拒收的訊息在狀態輪詢期間持續保留，新的接受結果才清除。

分享包納入既有 `START_LOCAL_AND_WEB.cmd`，並實際從 ZIP 執行 Windows 啟動器的兩組離線案例；保留發布隱私檢查。另以本次 `go.ps1` 原件雜湊重做 PowerShell 5.1／7 的完整 caller 與真實 venv 身分案例。先前 hosted Windows 阻塞根因仍未知，既有成功 CI 與本次定向驗證分別留存；Claude 完整材料與結果是否獲驗收另據實記錄，不以退出碼代替通過。

本次完整測試另觀測到 Origin 拒絕案例接收回應時的 Windows 10053；未證實該次連線中止的唯一原因。第二意見後的離線探測確實重現 HTTP/1.1 拒絕 POST 後，未讀本文污染下一個請求。共同拒絕邊界現在宣告關閉連線，只以大小及總時間上限排空合法小本文；空本文及真正 JSON 本文都必須收到 403，另驗內容型別、長度、慢送與已讀本文不重讀。沒有把連線錯誤當成通過。

明示官方研究回補沿用同一 HTTP client 的 gzip、大小限制與整次來源請求期限，仍保留解壓後原始 JSON 收據及雜湊；取消提示不再保證未知 DNS 阻塞的結束秒數。日曆 SQLite 核對錯誤明示失敗且不得回退成缺收據，GET 補抓寫回失敗則保留已讀本機資料，沿用 `dataWarning` 揭露未完成。年度維護限制見 `K線事件研究.md`：背景程式與 Pulse 不自動刷新年度日曆，新年度未涵蓋時繼續停止排程。Claude 最後一輪因必要材料不足未獲驗收；其可證實發現另經 Codex 修正、定向測試與發布驗證，結果以實際交付證據記錄，不宣稱已取得該輪通過結論。

---

## v5.0 修訂 — 2026-10-08 A–M 修正與 Claude 覆核補正

產品版本維持 **5.0**；基準 `d3fed73553034e7680a526f0203e2b93890d0bf8`，分支 `codex/review-fixes-20261008`。提交識別與正式發布證據依 Git 及發布清單記錄。

補正選擇權長假排程、movers 共用期限與重用 socket timeout、未要求 gzip 的相容性、日線完成日界線、Reader 私人警報權限、受管程序收據、佇列拒收終態、歷史同步鎖、行情效期及日線更新契約；保留原修訂歷史與資料品質保護。

Claude 的第一輪材料驗收未通過，後續補正包括：既有 `__MARGIN_RATIO__` 衍生序列不套用個股盤中 K 棒界線；分享包可離線執行修正回歸、Private Web 專屬案例明示略過；產業分類沿用既有 HTTP client 並納入 movers 共用期限；無 deadline 的 `timeout=None`／`0` 保留原傳遞語意；Reader 警報介面顯示僅擁有者可見且清除舊表單；排程以數值狀態判斷，未知狀態不啟動；更新器拒絕舊按埠停止邏輯；Pulse 測試改用公開結果與明確暫存清理，工作者未停止時保留隔離設定與證據。

最終 Claude 材料與結果驗收完成後，逐項補正：deadline 讀取固定長度短回應時回報 `IncompleteRead` 並沿用既有重試；Owner 警報寫入的 HTTP／連線失敗明示提示；分類來源部分失敗仍保留已取得與舊快取，並揭露未完成；研究回補以實際接受筆數計算、明列 `excludedIncomplete`；官方日線的直接寫入與全市場匯入也共用完成日界線，未完成日不得登記完成。這批補正由 Codex 查證與驗證，沒有自動追加 Claude 輪次；原 hosted 阻塞根因仍未證實。最終提交與覆核受審版本的差異另列交付證據。

驗證包含 Windows 真實 CMD、PowerShell 5.1／7、venv 程序鏈、實際分享 ZIP 與 Reader／Owner 前端離線案例。原 hosted Windows CI 的 Pulse 終態逾時與 Node VM 3000ms 錯誤根因仍未證實；本次保留失敗診斷與延後 ICU 初始化，不宣稱原 CI 根因已修復。既有疑似污染資料另有唯讀診斷及修復提案，未直接覆寫正式 DB。最新套件、覆核及發布結果另見外部交付證據。

---

## v5.0 修訂 — 2026-10-08 TWSE／TPEx 批次抓取改用既有 http_client（候選，未發布）

產品版本仍為 **5.0**；基底 `6f3cf19214f64192c60db7dabe77ebc5956078b2`，分支 `claude/st-tpex-fetch-retry`，提交 SHA 見該分支與 PR。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 每日來源更新（`個股每日資料.py`）與 movers（`server.py` `_get_json`） | 兩處各自以裸 `urlopen`、無重試抓同一個約 5 MB 的 TPEx 批次檔（TWSE 也同樣）。web 後端日誌累計 `[movers] TPEx` 連線重設 371 次、IncompleteRead 286 次、逾時 54 次；每日更新一次連線被重設整個 TPEx 來源即判 `failed`。直接重現：只帶 User-Agent 的請求 26 次中約 2 次失敗，加 `Accept-Encoding: gzip` 的 26 次全成功且較快。改用既有 `http_client.fetch_json`（連線池、對 ConnectionReset／IncompleteRead／逾時／WinError 10054 的暫態重試），並要求 gzip；每日更新 timeout 30 秒、重試 2 次，movers 因呼叫端 join 上限 9 秒只重試 1 次。 | 真實站台實測：TPEx 20/20 成功（其中 2 次由重試吸收）、TWSE 5/5；新增 `http_client` 4 個案例（gzip 解壓、未要求壓縮時不變、連線被中斷後重試成功、無重試時失敗）；3 個既有測試的假造點由 `urlopen` 改為 `http_client.fetch_json`（其中 movers 測試原本會實際連到官方站台，已改為離線）；未發布。 |
| `http_client` | 回應帶 `Content-Encoding: gzip` 時自動解壓並移除該標頭；未要求壓縮的既有呼叫者行為不變。 | 同上測試；未發布。 |

釐清：local 的每日更新 `partial` **不是連線問題**。兩個來源都已抓到（TWSE 1348 檔、TPEx 988 檔），差的是追蹤清單中兩來源都沒有的 10 檔代號（2026-10-07：`00847B`、`1522A`、`2067`、`2323`、`3085`、`3632`、`4155`、`6167`、`6173`、`8183`），多半是已下市或停牌的舊代號，仍留在追蹤清單；這會使 `partial` 持續，屬資料清理而非抓取問題，本次未處理。

已知限制：全專案仍有數十處裸 `urlopen`（含其他抓 TWSE／TPEx 的模組），本次只處理失敗量集中的兩處；未來若其他模組出現同類錯誤，應優先改用 `http_client`。

---

## v5.0 修訂 — 2026-10-08 一鍵啟動 local 與 web（候選，未發布）

產品版本仍為 **5.0**；基底 `ad2dd0f773216742ac641f30251fff02a72a7eed`，分支 `claude/st-launcher-all`，提交 SHA 見該分支與 PR。僅新增根目錄啟動檔，不改產品程式。

| 改動 | 原因與行為 | 驗證／狀態 |
| --- | --- | --- |
| 新增 `START_LOCAL_AND_WEB.cmd` | local 沒有開機自啟，重開機後需手動啟動兩邊。檔案依序啟動 local（`START_TIP.cmd`）與 web（排程 `StockTerminal_PrivateWeb_Host`），已在線者不重複啟動，並以 `/health` 與 gateway `upstream:true` 判斷就緒；結束碼 0＝兩邊正常、1＝local 掛、2＝web 掛、3＝都掛。`START_TIP.cmd` 在 local 由停止狀態啟動時不會返回，因此改為分離啟動並輪詢 `/health`（上限 120 秒）。web 不使用 `START_PRIVATE_WEB_HOST.cmd`（它讀原始碼目錄的資料，會形成第三套資料）。 | 已實測「兩邊都在線」路徑：兩邊 UP、結束碼 0。**未實測**：local 或 web 停止時的啟動路徑、逾時與非零結束碼。未發布。 |

已知限制：只能在 local 與 web 都已安裝受管理版本時使用；web 啟動依賴既有排程，未改動排程。

---

## v5.0 修訂 — 2026-10-07 選擇權排程改為開盤前、ETF 探測不再截斷回應（候選，未發布）

產品版本仍為 **5.0**；基底 `6eb2769ce18aec2c086c55ff21a8bb922598187b`，分支 `claude/st-options-morning-etf-probe`，提交 SHA 見該分支與 PR。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 選擇權每日更新時段 | PR #169 設在收盤後 18:30–20:30，但 TAIFEX 官方檔的 `Last-Modified` 為台北 2026-10-07 06:36：D 日資料在 D+1 約 06:36 才發布，收盤後抓不到當日資料，每天只會得到前一日資料並被品質保護標為失敗。改為交易日 07:00、07:30、08:00、08:30（09:00 開盤前），並以「前一個表定交易日」作為完成條件（週一對應週五）。 | 8 個案例通過（含週一跨週末、日曆未涵蓋）；單次觀察 06:36 不是來源保證；未發布。 |
| ETF 快照探測 | `etf_snapshot_health.probe_api` 只讀回應前 1 MiB，`/etf-delta` 已約 2.1 MB，JSON 被截斷而 `JSONDecodeError`，排程 `ETF_Daily_Snapshot` 結束碼 2（ETF 資料本身健康）。改為讀取至 16 MiB 上限，超過時回報 `response_too_large` 而不是截斷；測試用的假回應原本忽略讀取上限，現與真實行為一致。 | 新增 2 案例；舊程式碼下失敗、修正後通過；該排程自主工作樹執行腳本，需更新該工作樹才生效；未發布。 |

已知限制：每日來源更新（TWSE／TPEx）今日仍為 partial，因連線被重設（WinError 10054），本次未處理。

---

## v5.0 修訂 — 2026-10-07 修正交易時段重啟會啟動失敗（候選，未發布）

產品版本仍為 **5.0**；基底 `215e7ae47e51f4d1f9cf11dac90c5f75a7d9ecbe`，分支 `claude/st-startup-order`，提交 SHA 見該分支與 PR。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 每日個股留存啟動順序 | `server.py` 先啟動每日個股留存，之後才呼叫 `configure_updates`。交易日 14:00–21:00 且每日排程已開時，留存程式一啟動就把工作排進舊佇列，`use_durable_queue` 隨即拒絕（「舊背景佇列仍有工作」）、後端以代碼 1 結束，host 重試 5 次後放棄。2026-10-07 18:59 升版重啟 web 時實際發生；e0b1147 同樣順序，屬既有問題，先前只因重啟落在週末或時段外而未觸發。修正：改為在 `configure_updates` 之後啟動。 | 新增 `tests/test_server_startup_order.py`（2 案例）；舊順序下失敗、修正後通過；相關測試與 CI 待結果；未發布。 |
| 發布白名單 | 新測試加入 `scripts/build_dist.py` 與 dist 測試清單。 | `test_dist_scrub` 待結果。 |

已知限制：靜態順序測試只鎖定呼叫順序，不模擬實際啟動；實際啟動需於部署後觀察。

---

## v5.0 修訂 — 2026-10-07 發布測試的編碼修正（候選，未發布）

產品版本仍為 **5.0**；基底 `debb9af8b37c7eb3e559c47d7fa21dca14c5bcbc`，分支 `claude/st-release-test-utf8`，提交 SHA 見該分支與 PR。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `tests/test_private_web_release.py` 讀取發布清單 | 清單以 UTF-8 寫入（`ensure_ascii=False`），測試用 `read_text()` 依系統預設編碼讀取；在繁中 Windows（cp950）的 `stage` 回歸測試因 `UnicodeDecodeError` 失敗（1474 個中 1 個），Linux CI 因預設 UTF-8 沒有發現。兩處改為明確 `encoding="utf-8"`。僅測試變更，產品程式不變。 | 在原失敗環境（cp950）重跑 `test_private_web_release` 12 個通過；完整 `stage` 重跑與 CI 待結果；未發布。 |

---

## v5.0 修訂 — 2026-10-07 選擇權結構收盤後自動更新（本機候選，已提交，未發布）

產品版本仍為 **5.0**；基底 `e0b11475f40a980289553d18029b916be3d1e457`，分支 `claude/st-options-daily-refresh`。可追溯提交 SHA 見該分支提交與 PR；本節不在檔內預寫自身 SHA。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 選擇權每日更新排程 | 選擇權結構只能手動更新，兩個 runtime 快取分別停在 2026-08-16 與 2026-09-09；新增交易日 18:30／19:30／20:30 檢查，當日資料已入快取即停止，沿用既有 `options` 更新工作，預設關閉，需擁有者同意檔 `data/options_daily_schedule.json`。 | 6 個新單元案例，加上 options、統一更新中心、dist 相關共 55 個測試通過；未實際啟動服務觀察 18:30 觸發。 |
| 發布白名單 | 新模組與測試加入 `scripts/build_dist.py` 必要檔案與 dist 測試清單，避免發布包漏檔。 | `test_dist_scrub` 通過。 |

已知限制：只在服務運行時檢查；既有品質保護在現貨日與資料日不同時仍會把工作標為失敗，TAIFEX 當日資料晚於 20:30 發布時當天落空。詳見 [說明](st-options-daily-refresh.md)。狀態：本機候選／已提交；未發布，部署與啟用同意檔仍待確認。

---

## v5.0 修訂 — 2026-10-07 備援路徑可觀測性與靜默例外棘輪（候選，未發布）

產品版本仍為根目錄 `VERSION` 的 **5.0**。補記：PR #166 已於 2026-10-07 合併，合併（squash）修訂 `fd6efb77e08e7aae718d0ed085cbd013e66779a5`；先前「候選（尚未合併）」是當時快照，不覆寫。**發布狀態**：#164、#165、#166 與本段都未發布，正式站與受管理本機的 runtimeCommit 仍為 `e0b11475f40a980289553d18029b916be3d1e457`（2026-10-07 確認）。

### 候選（本 PR）：備援路徑可觀測性、靜默例外棘輪、接線檢查

- 基底：`fd6efb77e08e7aae718d0ed085cbd013e66779a5`。實作提交以本 PR 的分支歷史為準（避免在自身檔案內預先寫入自己的 SHA）。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `server/log_once.py` 與備援路徑記錄 | #165 的 `import math` 之所以悄悄失效五天，是因為 `except Exception: return None` 吞掉 NameError。新增限頻記錄函式（同 key＋例外型別 10 分鐘一行；新的例外型別一定立刻記錄），並接到四個備援路徑：`_db_screener_arrays`（DB 失敗仍回 None，由呼叫端退回 Yahoo）、`_handle_quote_batch` 的單檔候選與 worker 例外。行為不變，只多一行記錄。 | `tests/test_log_once.py` 6 項；`tests/test_fallback_observability.py` 4 項，其中 3 項在舊 `server.py` 上失敗。 |
| 數字解析只吞解析失敗 | `_fetch_day_movers`、`_handle_twquote` 內的 `fnum` 原本 `except Exception: return None`，會連 NameError 一起吞。改為只抓 `TypeError`、`ValueError`、`OverflowError`。**行為差異**：解析以外的程式錯誤現在會往外傳，由外層既有的處理印出（例如 `[movers] TWSE ingest …`），不再悄悄回「無資料」。 | 缺全域名稱時會印出 `[movers] TWSE ingest … name 'math' is not defined` 的測試；健康模組下排行照常有資料。 |
| 靜默例外棘輪 | 共用規則 0014：寬鬆且靜默的例外處理（`except Exception` 等，只有 `pass`／`continue`／`break`／`return` 常數）數量只能下降。`server/` 目前 207 個（39 個檔案；`server.py` 69 個），新增或減少都使測試失敗，減少時要同步降低 `tests/silent_except_baseline.json`。本 PR 讓總數從 212 降到 207。 | `tests/test_no_new_silent_exceptions.py` 2 項；人為新增一個靜默處理時測試失敗（已驗證）。尚未清理其餘 207 個，屬後續工作。 |
| 接線檢查 | `server.py` 內 150 個不同的 `self._xxx()` 呼叫都要在 `server/` 內有同名定義，抓拼錯的方法名稱（pyflakes 抓不到）。名稱層級，不啟動伺服器、不碰 `data/`。 | `tests/test_server_handler_wiring.py` 2 項；目前沒有缺少的定義。 |
| 協作入口文件 | `AGENTS.md`、`CLAUDE.md` 記入：共用記憶的 GitHub 遠端與雲端唯讀讀取方式、遠端可能落後本機、8D 與「8D 後新增規則不需授權」的範圍、規則 0014 的做法。 | 文件變更；事實來自使用者回覆（遠端 repo 名稱）與雲端對遠端的唯讀核對。 |

驗證：只跑了本次相關的測試與 `test_bundle_fresh`；完整 Python 套件由 CI 執行，沒有在雲端另外跑（規則 0008 第 13 條）。限制：未用即時供應商資料驗證；路由煙霧測試（啟動真實伺服器）**沒有做**——它會寫入 `data/`、啟動背景執行緒並對外連線，與規則 0007 的執行期資料保護衝突，改以上列的接線檢查代替，煙霧測試待 Sam 決定隔離方式。審查：僅作者自審，沒有跨供應商或同供應商隔離審查。使用者可見資訊：沒有減少。

---

## v5.0 修訂 — 2026-10-06／07 決策中心時效、台指期時間與啟動器防呆（已推送並合併；未發布）

產品版本仍為根目錄 `VERSION` 的 **5.0**；沿用「產品版本 + 精確 Git／runtime commit」辨識修訂，沒有改動版本號。以下 PR #164、#165 已合併到 `main`，PR #166 為候選；**2026-10-07 實測正式站與受管理本機的 runtimeCommit 仍為 `e0b11475f40a980289553d18029b916be3d1e457`**（正式 `.private_web_release.json` 與本機 `/health` 一致），所以全部屬「未發布」。發布須依既有 stage／promote 流程由本機發布者執行；此處不宣稱已部署。

### 已推送並合併、未發布：PR #164，決策中心時效與台指期夜盤時間

- 基底：`e0b11475f40a980289553d18029b916be3d1e457`。
- 分支提交（由舊到新）：`e8125daaf2da194af7614e533101b74679632ebd`、`44e6de5704b39f294ba81fc5b4340ff54feb6fa8`、`e3ecead7e739784238580147cc33acba9c4a391f`、`0e701f1852e8a7b703225d6863074b2ac748f417`、`2c0efcc874907b7fe75b86194c9df1e88b9864a8`、`af0c8c87bebab3078c384649259acda85e45050a`。
- [PR #164](https://github.com/SamHuang68/AI_Stock/pull/164) 合併（squash）修訂：`a525885a24dc53b36441e81d161bbe0c37097b1e`。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 台指期夜盤午夜後的日期 | TAIFEX MIS 在 00:00–05:59 的夜盤報價，`CDate` 仍是場次開始日（2026-10-06 01:50 回 `20261005`；2026-10-07 02:56 回 `20261006`）。直接組合 CDate＋CTime 會使 asOf 早 24 小時，證據列顯示「1 日前」，決策中心也把新鮮報價當過期。現在夜盤且時間早於 06:00 時日期加一天；日盤與午夜前不調整；調整後若超前本機時鐘超過 120 秒，仍標「時間未核實」，不悄悄移位。 | 上述兩份使用者機器上的真實樣本進入測試，另有跨月、跨年、週末與 06:00 邊界案例。使用者以 `88c5139` 程式在舊開發資料夾（非受管安裝）實測 `/txf`：asOf 為當日、`timeUnverified` 為 false、`timeCheck.verified` 為 true；該次輸出沒有存入證據資料夾。**午夜前（15:00–23:59）的 CDate 語意尚未用真實樣本確認**：若為下一個交易日，該時段報價會顯示為時間未核實。 |
| 時間驗證失敗時保留報價 | 過去 CDate／CTime 驗證失敗會整筆丟棄，Pulse 與決策中心看不到夜盤，且沒有紀錄。現保留價格，asOf 明確為未知並標 `timeUnverified`，原始 CDate／CTime 與原因寫入 `timeCheck`，同一場次與原因每 10 分鐘最多記一行；決策中心不採用時間未知的報價，Pulse 評分排除。 | 原「缺 CDate 回 None」的斷言依新契約改為保留價格、時間未知；其餘既有測試不變。 |
| 台指期時效 | 場次結束後、下一場次開始前（夜盤 05:00–08:45、日盤 13:45–15:00、週末與休市到下個開盤前，依交易所日曆），最後一筆視為 `completed_session` 而非過期；過去 05:30–08:45 完全不採用夜盤收盤。 | 完整時間軸測試，含週末、休市與「非場次最後一筆不得被救回」。 |
| Pulse 快照的台指期選擇 | 快照過去一律取夜盤區塊，日盤時段會顯示昨夜報價。現取夜盤區塊與日盤報價中時間較新且已核實者；快取為空的日盤時段直接取日盤報價。 | 選擇邏輯單元測試。 |
| Key Levels 時效與偏離 | 參考日須為最近完成交易日（18:00 截止、依交易所日曆），否則 `stale`；現價（指數與期貨中較新且可用者）偏離參考收盤達 `max(2%, 2×ATR%)` 時標 `offReference`，保留價位但不再產生「守穩 R1／收破 S1」確認與失效條件，並加 `key_levels_off_reference` 限制。`calculate_key_levels` 回傳 `referenceBar`。 | 19 個定向測試（含已回報的 45–48k 數值對 50k 現價）。2%／3% 門檻是經驗值，未用資料校準；期現貨基差未扣除。 |
| 選擇權結構 | 現價偏離選擇權參考現貨 3% 以上時停用情境模型（Flip Band、GEX），保留官方 OI 事實與方向中立的密度，原因為 `LIVE_PRICE_FAR_FROM_CHAIN_SPOT`。 | 併入上列測試。 |
| 決策頁呈現 | Key Levels 上方顯示參考日、現價與偏離（偏離為琥珀色、過期為紅色）；選擇權格顯示現價，模型停用時說明兩個價格。 | 以真實後端輸出對決策頁做 Playwright 檢查（已回報情境、過期參考、正常情境），無 pageerror。 |

驗證：全套 Python 1431 項通過（15 項略過，為 Windows 專用或選用套件）、22 項 JS 自測、`compileall`、`build_order`、bundle 新鮮度測試。[PR CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37352435070)、[分支 push CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37352430089)、[主線 CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37353820420) 各四項成功。限制：TAIFEX、TWSE、Yahoo 無法從開發沙箱連線，沒有以即時供應商資料驗證；未部署。審查：僅作者自審，沒有跨供應商或同供應商隔離審查。

使用者可見資訊的減少（共用規則 0009 第 1 條）：本 PR 在下列情況會減少決策中心顯示的內容，都不是悄悄進行，畫面會寫出原因。(1) Key Levels 為 off-reference 或 stale 時，不再輸出「守穩 R1／收破 S1」確認與失效條件文字；價位與波動度統計照常顯示，上方多一行參考日、現價與偏離。(2) 選擇權現價偏離 3% 以上時停用情境模型（Flip Band、GEX 情境與壓力測試數字），改顯示原因；官方 OI 與方向中立的密度仍顯示。(3) 時間未核實的台指期報價不再供決策中心與 Pulse 評分使用；價格與原始 CDate／CTime 仍由 `/txf` 提供。PR 說明已列出這些項目，Sam 以「合併」核准該 PR。

### 已推送並合併、未發布：PR #165，補 `import math`

- 基底：`a525885a24dc53b36441e81d161bbe0c37097b1e`；實作：`1f5319ba011ece91cfec9b04743e1400a54f7959`。
- [PR #165](https://github.com/SamHuang68/AI_Stock/pull/165) 合併（squash）修訂：`88c5139c17a6095703903e7f33c3cdc97246bd03`。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `server.py` 缺 `import math` | `_fetch_day_movers`、`_handle_twquote`、`_handle_quote_batch`、`_db_screener_arrays`、`_tag_industry` 使用 `math.isfinite`，且都包在 `except Exception` 內，NameError 被吞掉：總覽漲跌幅排行永遠「無資料」、個股即時報價的 Yahoo 備援取不到數字等，沒有任何錯誤訊息。由 `a02436a`（2026-10-02）與 `bd6b75f`（2026-10-03）引入，**已包含在目前部署的 `e0b1147`**。既有測試用 AST 取出單一函式並手動注入 `math`，因此沒有發現。 | 以真實模組與假 TWSE 資料重現：修正前 `ok=False`、無排行，補 import 後 `ok=True`。新增 pyflakes 全專案 undefined-name 掃描（修正前 5 處、修正後 0 處）與不注入全域的行為測試，兩者在舊程式上失敗；pyflakes 釘版於 `requirements-ci.txt`。另四處只以靜態掃描涵蓋，未逐一用即時資料執行。 |

驗證：全套 Python 1433 項通過（15 項略過）、22 項 JS 自測。[PR CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37503981020)、[分支 push CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37503960975)、[主線 CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37514560599) 各四項成功。審查：僅作者自審，沒有跨供應商或同供應商隔離審查。

### 候選（尚未合併）：PR #166，啟動器防呆與協作入口

- 基底：`88c5139c17a6095703903e7f33c3cdc97246bd03`。實作提交：`712872a8eb1edd242806ccd2892942ee77ba5c4d`、`c09a45620fa5e9c391198c6a421178a2612b88ce`，及其後的對齊與修訂紀錄提交（以 PR #166 為準）。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| `go.ps1` 啟動防呆 | 已登記受管本機安裝時，`go.ps1` 只在目前資料夾等於登記的 `originalCheckout` 才轉交；從其他資料夾一般啟動會落入開發流程，`Stop-PortListeners` 關掉 18432 埠上的程序，再啟動一份未受管版本。2026-10-07 發生一次：雲端代理人沿用 2026-10-03 已退役的 `C:\Users\Sam\AI_Stock` 路徑，指示使用者在該資料夾執行 `START_TIP.cmd`。現在這種情況在關閉任何程序之前以 `ST-LAUNCHER-GUARD` 停止並說明；明確的 `-Worktree`／`-Pull`／`-UpdateOnly`／`-RebuildOnly`、登記資料夾的轉接、沒有受管安裝的行為不變。 | 靜態順序／BOM 測試，加 2 個在暫存目錄實際執行 `go.ps1` 的行為測試（PowerShell 7.4），在舊 `go.ps1` 上失敗；全套 1436 項通過。**尚未在使用者機器驗證**。行為測試原先優先選 `pwsh`，Windows CI 因此只用 PowerShell 7 跑過；`START_TIP.cmd` 實際呼叫的是 Windows PowerShell 5.1，所以已改為每個找得到的引擎（5.1 與 `pwsh`）都跑，5.1 的結果以該 PR 最新 head 的 Windows CI 為準。 |
| 停用 `scripts/apply.bat` | 舊腳本會強制 `git checkout -B` 遠端分支、`stash -u` 所有未追蹤檔並依埠 `taskkill` 18432，與受管本機安裝及「不 reset、不 force」的共用規則衝突；其預設分支檢查也拒絕 `main`（`TIP_BRANCH` 自 2026-09-07 起為 `main`），倉庫內沒有任何地方引用它。改為只印出停用說明並以 2 結束的存根（舊邏輯保留在 Git 歷史，未刪檔）。 | 靜態測試：存根不含 `taskkill`、`git checkout`、`git stash`、`git reset`、`netstat`、`server.py`、`build_v2`，且為 ASCII；未在使用者機器執行。 |
| 協作入口文件 | 新增 `AGENTS.md`、`CLAUDE.md`，更新 `.cursorrules` 的過時路徑，記錄正式開發資料夾、受管本機、正式站與退役舊路徑，並指向 `AI-Workspace` 的共用規則（本機檔案，不在 Git 內，不複製其內容）。 | 文件變更，無程式行為；內容只含從使用者機器輸出與倉庫文件驗證過的事實。 |

審查：僅作者自審，沒有跨供應商或同供應商隔離審查。

事故處置紀錄：未受管開發程序於 2026-10-07 03:33:05 啟動並佔用 18432；使用者之後改由 `%LOCALAPPDATA%\StockTerminalLocal\start_local.ps1` 啟動受管安裝，其 runtimeCommit 為 `e0b11475…`，與正式站一致；正式站（18434／18435）未受影響。使用者事後提供的證據：受管啟動收據 `createdAt` 為 2026-10-06T19:48:00Z（台北 10-07 03:48:00，即改由受管啟動器重新啟動的那次），前一份受管程序的 log 最後寫入 2026-10-05 18:41（台北），距事發約 33 小時；因此事發當時 18432 上很可能沒有受管程序在運行，很可能沒有關閉任何受管程序。這是推論，不是證明（前一份收據已被覆寫）。

---

## v5.0 修訂 — 2026-10-03 已發布與後續本機階段

產品版本仍為根目錄 `VERSION` 的 **5.0**；本輪沿用「產品版本 + 精確 Git／runtime commit」辨識修訂，沒有為整理紀錄改動版本號。以下保留各階段的原因、行為、驗證與發布狀態；歷史紀錄不覆寫。

### 已發布：PR #162，正式與受管理本機一致

- 原基底：`c8274eb4995cc07a90bb6b5414b5dc81a919f273`。
- 實作：`45eea31b832d69d4eb26bb3241f2ebb5c5386221`；覆核後修正：`97fd75996038d91fd61b37d2aab7d4fb59df7277`。
- [PR #162](https://github.com/SamHuang68/AI_Stock/pull/162) 合併／部署修訂：`2ae7256f9d898fee0df25f1787952337b37b12e2`。
- 2026-10-03 UTC 的實際 UI 收據確認正式與受管理本機皆執行此 SHA；兩份部署 `VERSION` 均為 5.0。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 型態視窗回覆歸屬 | 關閉視窗、換股或新請求後的舊回覆可能覆蓋目前畫面；現核對請求、視窗與圖表序號，取消過期批次，保留舊 modal 呼叫相容性。 | 11 個定向瀏覽器案例；正式與本機各一次真實型態視窗操作通過；已發布。 |
| 型態績效說明 | 固定星等與「最高勝率」缺乏統計依據；改為規則符合，明示不代表獲利機率。 | 沿用型態瀏覽器案例及兩份實際 UI 文字證據；技術分數公式不變；已發布。 |
| 美股日線截止日 | 單靠平日與固定收市時間無法正確處理休市、DST 及提前收市；採有限 2026–2028 官方日曆，訊號與資料品質共用截止語意，範圍外保守標示未知。 | 10 個日曆案例及 3 個直接相依案例通過；部署後固定時鐘核對聖誕休市、提前收市及未知年份；已發布。 |
| 未知日曆的歷史資料說明 | Claude 覆核指出前一日資料仍可能被描述成已收市；未知說明現同樣適用較舊資料。 | 僅重跑受影響 API 案例通過，0.008 秒；提交 97fd759；已發布。 |
| 新增測試與發布包涵蓋 | 新日曆資源、模組與型態測試需進入既有發布／CI 路徑。 | PR／主線 CI 各四項首次通過；精確 SHA stage 一次通過 1403 單元（略過 1）、25 smoke、11 dist 及既有 JS 自測。 |

[PR CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37147220378)、[主線 CI](https://github.com/SamHuang68/AI_Stock/actions/runs/37147892630)。正式完整備份 14 個 DB、保留 269 個資料檔；本機備份 16 個 DB、331 個檔案。原排程定義及原工作區資料保留。有限 supervisor 存活觀察不代表未知外部終止原因已永久修復。

### 後續必要呈現修正：本機已提交，未發布

實作提交 `b5293a77c356e4b26aedde7c438b88a82e43996d`，分支 `codex/st-evidence-presentation`，基底為上述已發布的 `2ae7256`，產品版本仍為 5.0。

| 改動 | 原因與修正後行為 | 驗證／狀態 |
| --- | --- | --- |
| 市場成績單歸屬與快取 | 切換 TW／US 後舊回覆可能污染新卡片；快取依市場保存，讀取／重算回覆僅更新原卡片，支援收合取消與唯讀重試。 | 11 個離線 Chromium 案例及既有體檢自測通過；未發布。 |
| 指標／劇本績效文案 | KD「最高勝率」、任意組合「70～80%」及多訊號必然提高勝率沒有對應績效證據；移除宣稱，區分歷史統計與真實前瞻。 | 上述瀏覽器文案案例與 watch 語法檢查通過；分數、訊號公式不變；未發布。 |
| 官方成交量來源關係 | 同源首次建列或原始來源未知的零差異不能證明獨立核對；依當日、選定收據 ID、來源及 rawOrigin 顯示證據邊界，收據展開可追查日期與 ID。 | 29 組呈現自測通過；保留 raw／official／difference、衝突及未知單位；無 DB 修改；未發布。 |
| 測試入口與文件 | 新成績單案例需可重現，並接入既有 package／CI 路徑；記錄範圍、限制與測試。 | 本機腳本已通過；新的 CI hook 尚未執行，不把本機成功當作遠端 CI 成功；未發布。 |

Claude 於 2026-10-03 UTC 以既有 claude.ai 官方 CLI 完成本提交的首次跨供應商唯讀覆核，模型 claude-sonnet-5-5，結論 **PASS／無可證實新缺陷**。作者定向核對 rpanel 入口與既有 health/chart guard 一致；沒有因此修改產品或重跑既有成功測試。覆核綁定九個受審檔案雜湊；文件追記不改變其程式版本。

本階段沒有 push、完整 CI、合併或部署；下一次發布仍待確認。詳見 [本機修正說明](st-evidence-presentation.md)。本次修訂紀錄補登屬文件變更，不代表程式再進版或已發布。

本機稽核證據入口：`C:\Users\Sam\AI-Workspace\docs\stock-terminal\st-pattern-us-calendar\release-handoff.md`，以及同目錄 `release/verification-ledger.json`、`followup/ledger.json`、`followup/claude-review-triage.json`。這些是留存的當時證據，不以重新執行測試取代歷史紀錄。

---

## v5.0 — 總覽儀表板 + 分析轉盤（tip UX；無側欄）

**產品殼層**
- `shell_v5`：分析轉盤導航（最多三層，投資分析分類）；涵蓋原側欄全部 ROUTES；預設 `#pulse` 並 **boot 自動 openRing**；歷史庫 merge 同步。
- **移除 navrail／nr-edge／nr-backdrop**；`[`／Ctrl+B 改開轉盤。
- 品牌：`assets/st50-icon.svg` 置於**轉盤中心**（+ 頂列小 icon + favicon）；內頁隱藏重複 kicker。
- 對外導覽：`docs/TIP_UX.md`（Mermaid／SVG／概念圖）；示意 `assets/tip-ring-schematic.svg`。

**總覽與情報**
- `pulse_v5`：`GET /pulse` 一屏高密度（台指期、法人趨勢、廣度多空比、產業 TW/US、全球 SOX／日經／KOSPI、台美快訊 `/flash`、因子帳本）。
- **產業月營聚合**：自 OpenAPI `t187ap05_L`／`t187ap05_O` 快取加總產業 YoY／營收占比／家數成長；熱力 KPI／格註解 + pulse 快訊一句（月頻基本面，非盤中輪動）。
- `hub_v5`：法人／國際／訊號／自選／風險／設定分頁。
- `viz_v5`：共用 spark／bar；近 20 日趨勢圖 X/Y 軸單位。
- 廣度漲跌停浮動清單；真實資料計分（缺源「尚未納入」、不捏造 Fear&Greed）。

**體驗打磨（本 tip 續）**
- 轉盤：點選項為下一層圓心、上層透明鎖定、立體軌道質感、滾輪循環選取。
- 定時面板 soft refresh；離頁 `deactivate` 清輪詢。
- `Alt+Shift+1…0` 直達常用路由；`Esc` 先關轉盤／浮層。

**AI 中樞 + 工具列橋接**
- `ai_v5`：AI 室 — 報告／副駕／焦點入口 + `/focus` 摘要。
- `bridge_v5`：`screener3Open`→scan、`portfolioOpen`→book、`marketFlowOpen`／`instRankOpen`→institutional、AI 三鈕→ai（再開模態）。

---

## v4.1 — 體驗打磨 / 欄位標準 / 顏色管理

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


## v5.0 修訂 — 2026-10-08 A–M 審查修正（未提交本機候選）

產品版本維持 **5.0**；基準 `d3fed73553034e7680a526f0203e2b93890d0bf8`。尚未 commit、push、合併或發布；修正版本由 repository 外完整 patch 與逐檔 SHA-256 固定，不以基準 SHA 冒充候選。

- A：前交易日依已涵蓋日曆回溯，不再受十天限制；遇未知年度停止。新增長假、週末、跨年與重啟收據案例。
- B、D、K：http_client 共用 monotonic 期限及剩餘請求／退避預算，首試不強制切半；movers 使用 8.5 秒來源預算並明示超時。重用連線更新 socket timeout；只有選用 gzip 的呼叫解壓，回傳長度與 body 一致。離線首試逾時、晚到重試、長短 timeout 與 gzip 相容案例通過。DNS 等底層不合作工作以呼叫端有界等待隔離，未測真實官方來源。
- C：movers 測試固定產業 fixture，拒絕額外 urlopen；仍載入真正模組，不注入正式 globals。
- E：upsert 與來源合併共同排除未完成日線，涵蓋首次 backfill、update fallback 及投組呼叫；共用既有台股 14:00 完成界線，美股依既有日曆（含提早收盤）加 30 分鐘確認期。首次盤中未寫入、盤後可寫入案例通過。既有疑似污染資料未修改，另交唯讀診斷與待核准修復方案。
- F：alert／watch status 改為 Owner-only，額外 Reader 路由不能覆寫私人邊界；路由與本機假上游 HTTP 案例通過。
- G、M：重用 PR #168（head `9556cd0b4ba1465adc3ec24064f318844ee3ea41`）的程序收據保護，補上啟動父程序與命令列核對；Pull 使用 AST 檢查實際行為。PowerShell 5.1 與 pwsh 的未知 listener、錯誤收據、命令列不符及 Pull 註解／redirect 案例通過。未合併 PR #168。
- H：QueueFull 拒收轉 failed 並回 HTTP 503，下一次可提交；狀態與 HTTP 案例通過。
- I：網路與 sleep 不持寫鎖，逐批短交易合併；status／history 用唯讀連線，不反覆建表。阻塞 fetch 時查詢及同步單例案例通過。
- J：MarketData.get 按現在時間重算效期，刷新失敗保留訊息，shell 不再沿用舊綠燈。假時鐘失效與恢復案例通過。
- L：日線資料源更新接回既有標的選擇介面及 daily-cache 工作；缺少標的時明確拒絕，不啟動缺參數 CLI，不改為 update-universe。
- Windows CI：Pulse teardown 必須確認 worker 停止才清理目錄，未停止時保留證據，逾時輸出工作收據與執行緒堆疊。回測核心延後建立 ICU formatter，VM 載入階段不初始化時區物件，保留 3000ms 門檻。原失敗測試在本機定向驗證通過；hosted Windows CI 未重跑。Pulse 原始阻塞點仍無法確定；ICU 成本已移出 VM 載入段，但不能證實它是該次 CI 唯一原因。

驗證：最終 188 個選定整合案例通過（77.603 秒）；另有研究核心單一案例及五個 JavaScript 自測入口通過。中間修正另有 48 個定向案例通過，五個 JavaScript 自測入口通過。未執行整套測試或全倉庫掃描。靜默例外棘輪降低 http_client 5→4、pulse_history 6→4，其餘修改檔未增加。最終測試結果、patch 與候選雜湊見 `AI-Workspace/docs/stock-terminal/review-fixes-20261008`。

範圍外發現：PR #173 在 gateway 存活、backend 已死時跳過 host 啟動，另列審查待辦。本候選只修 A–M。Claude 首輪因缺少必要依賴未獲封包驗收；依其意見修正 URI 編碼、無效標的 HTTP 400、慢速 gzip 預算、晚到 worker 快照、收據讀取失敗與跨平台測試邊界，補齊依賴後交同一位 Claude 複審。複審回傳指出完成時間不一致，已依既有契約修正並補測；其位置引用被封包驗收拒絕，不算通過。最新修正尚無有效的最終 Claude 覆核。實際結果見外部證據。

額度恢復後最後一輪（2026-10-08）：04:41 後以既有 Claude CLI 執行，回傳五項意見，但仍有四項必要材料缺口，驗收為 not-accepted，不能稱為覆核通過。依已證實意見修正 movers 的實際採用來源／partial，遭拒用來源回滾；受管 history 工作改用共用 completed_daily_cutoff，TW 未知年度在體檢中也保持暫定；Reader 的 WATCH 狀態按鈕明示僅擁有者可用。新增測試已進入發行必要清單。Pulse 測試若工作者不能停止，保留目錄與替身並停止該批測試，不先恢復全域設定。

後續定向驗證：193 個選定整合案例通過（82.942 秒），研究核心單一案例與五個 JavaScript 入口的既有成功證據保留，其中新增 Reader 降級的 JavaScript 入口已重驗。發行檢查在 repository 外的暫存 Git 索引納入兩份新增測試後通過，原 Git 索引完全未變；尚未提交的新檔在一般發行預檢下仍會被正確拒絕。最後一輪後不再追加 Claude 呼叫，排程已停用；本次後續修正沒有有效的最終 Claude 覆核。原 hosted CI 根因及正式資料疑似污染仍未判定或修復。

## v5.0 修訂 — 2026-10-08 審查缺口與發布候選

Sam 追加授權修正審查未通過部分，完成必要驗證後提交、推送及部署；產品版本維持 **5.0**。以下接續前一階段紀錄，既有歷史與正式資料保留。

- 雙啟動器以 gateway 的 `upstream:true` 判斷完整 Web 就緒；gateway 存活而後端停止時，仍會啟動未執行的 host 排程。保留 Running 防重啟、有限輪詢及四種退出碼，ASCII／CRLF 以 Git 原始位元組保存。離線 CMD 使用外部命令替身，保留真實標籤、管線與退出碼解析。
- 開發收據支援一層 Windows venv Python 轉接器，核對釘選／基礎執行檔、絕對工作樹命令、CMD 路徑及啟動時已捕獲的父程序建立時間。超深、未知、身分不符的程序鏈仍拒絕登記與自動停止。實際隔離 venv 與動態 loopback 埠可重現舊拒寫情境。
- `-Pull` 快轉完成後重新載入磁碟上的新版腳本，保留開發與 RebuildOnly 語意，省略 Pull 避免重複更新；UpdateOnly 維持更新後退出。
- 發行必要清單包含新增 CMD 回歸測試；完整版 Python、JavaScript、瀏覽器與研究驗證及 Claude 覆核結果由版本固定的外部證據回報。先前 Claude 材料未獲驗收的結果仍不算通過；原 hosted CI 的阻塞根因沒有因本機通過而改判。

## 2026-10-09 — PR #168 本機候選的啟動器安全補正與覆核收尾

- 基底：`3f24218539634168c3189f07aada2568344b9190`。參考尚未推送的本機候選 `5d140b5f108bd2fed66f60f353c8b272c4133f2b`，在目前 main 最小整合，未合併衝突的舊 draft #168，也未帶回舊版 `-Pull` 自我誤判或較弱收據。
- 開發流程沿用 `ST_PORT` 並在建置／程序動作前驗證範圍；Python pin 使用 UTF-8，ASCII CMD 透過環境傳入 Unicode 路徑。健康檢查核對既有 `baseDir`、`pythonExe`、`port`；完成 HTML／JS 檢查後才寫強來源收據，無法證明來源時拒絕成功回報。
- 停止目標保留核對時的 Windows Process handle，以程序物件停止；未知程序、身分漂移及 PID 重用一律拒絕，已退出程序安全返回。保留原有 CMD、釘選 Python、父鏈時間及命令列防護。
- 實機隔離驗收發現 Windows venv 會改寫子程序命令列的 Python 路徑；改為分別核對釘選／基礎執行檔與相同的精確伺服器引數，不以父子命令列全文相同判斷，也不接受額外引數。
- 承接四個 Windows 隔離啟動案例及 loopback-only fixture；分享包必要清單與清單測試包含新檔。使用空白資料、隔離 AppData 與動態埠，背景來源不得連外；不修改受管安裝、正式資料庫或執行中受管程序。
- 依 Sam 本輪要求只驗證修改部分，沒有再次執行完整套件或完整 stage。逐次失敗、修正及定向收據保存在 `AI-Workspace/docs/stock-terminal/review-fixes-20261008/closeout-20261009`；Claude 唯讀第二意見與發布終態另以該處固定版本的收據記錄，不能由本文推定通過。
- 歷史日線僅針對既有 15 個疑點在原一致備份做主鍵追查；缺少首次原始回應、首次寫入時間與逐日工作對照，仍無安全修復個案。保留原值及證據，零筆確證不代表零污染。
- VERSION 維持 5.0；本條為來源工具補正，正式站及本機受管正常執行鏈沒有改動，受管 runtime 維持已完整驗收的 `3f24218539634168c3189f07aada2568344b9190`。本條不表示新來源已部署，不使用跳過完整測試的 stage 繞過發布器。
### 2026-10-09 — Claude 收尾覆核後的最小補正

- Windows 開發伺服器使用隱藏背景 CMD，標準輸出與錯誤追加至 `logs/server_go_ps.out.log`、`logs/server_go_ps.err.log`。移除失敗後的無限 `pause`，CMD 保留 Python 退出碼並結束；就緒逾時明列可查看的日誌，不再指向不可見視窗。受管正常啟動入口仍先委派既有安裝。
- 雙端啟動器嚴格接受小寫完整 `runtimeCommit`；離線測試副本將原始 40／20 次輪詢縮短為各兩次，並核對來源仍保留原始有限次數。健康 JSON 解析仍使用真 Windows PowerShell 5.1，每案最多八次啟動，維持既有 30 秒外層期限。
- 直接執行安全測試時，入口放在全部類別定義之後，避免漏掉埠與健康身分案例。只新增／驗證受影響案例，逐項結果與 Claude 意見處置見同版本外部交付紀錄；不把過去完整測試誤記為本次執行。
- 本條為未提交補正；最終提交、推送、整合及覆核狀態由固定版本的外部收據相互引用。產品 VERSION 維持 5.0；受管 runtime 仍為上述已發布版本，不由來源補正推定新發布。

### 2026-10-09 — 背景開發伺服器操作補註與釘選讀者查證

- 背景開發伺服器重啟：在該工作樹再次執行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\go.ps1 -Worktree`，由強收據核對自己的程序後結束並重啟。收據不符時會拒絕重啟，須先人工核對佔用者，不能依埠停止。一般 `START_TIP.cmd` 可能委派受管安裝，不用它代替指定開發工作樹的重啟。
- 單純停止：先讀本工作樹 `logs/dev_server.receipt.json`，用 PowerShell 的 `Get-Process`／`Get-CimInstance` 比對收據 PID、UTC 建立時間、完整命令與絕對路徑；`startTicksUtc` 為 .NET 的 UTC ticks，可用 `[datetime]::new([long]$receipt.startTicksUtc, [DateTimeKind]::Utc)` 換算。確認工作管理員詳細資料是同一個 Python 程序後才結束。無法核對時保留程序，不依埠停止。此為使用者手動操作說明，不新增自動停止入口。
- `server_go_ps.out.log`／`server_go_ps.err.log` 以追加方式保留，沒有自動輪替或截斷；長期開發時由使用者在已停止自有伺服器後封存。這保留原始錯誤證據，也明示日誌會成長的維運限制。
- 原生 Windows CMD 的 `chcp 65001`／`set /p`／`if exist` 讀取邊界，在含 BOM 與無 BOM 的合成 Unicode 路徑都成功且未 fallback；不能把 BOM 存在當成 WaveDeck 啟動事故。保留現行 UTF-8 writer，釘選回歸案例補上真實 WaveDeck CMD 讀取邊界。各實際讀者與版本限制見外部查證收據，不宣稱未來 Python 版本相容。
- 基底為 `3f24218539634168c3189f07aada2568344b9190`，VERSION 維持 5.0；本節撰寫時為未提交來源補正。單一 pin 方法與原生 CMD 讀取邊界均成功，沒有重跑完整套件或 stage；最後文件與 DONE 訊息補正以差異及執行區段位元組核對驗證。最終提交、推送與受管安裝的實際狀態，互相引用 `AI-Workspace/docs/stock-terminal/review-fixes-20261008/closeout-20261009/final-closeout-report.md`；不能由本節推定新來源已部署。

### 2026-10-09 — 啟動器測試 fixture 移除 Windows 暫存環境假設

- 基底為 `2524752484203703ce7db99f45467dc0c5c5621b`，VERSION 維持 5.0。該提交自動 CI 的 Ubuntu 主測試因 `TEMP` 未設定，新增健康身分 fixture 在進入被測函式前的 `Join-Path` 就失敗，五個子案例均未測到預期行為；原失敗日誌保留，不視為偶發。
- 同類範圍掃描找到 configuration 共用 helper 的兩個方法使用此環境假設。改由 Python 已建立的隔離暫存目錄透過 `ST_TEST_FIXTURE_ROOT` 明確傳入；仍擷取正式函式，沒有注入缺少的正式 globals、跳過 Linux 案例或放寬健康身分判斷。
- 移除 `TEMP`／`TMP` 後以 Windows 原生 PS5.1 與 pwsh 精準重現原健康方法失敗，再只驗證同 helper 的兩個方法。Linux 真實終態由補正提交的自動 CI 記錄；本條撰寫時為未提交候選，實際提交、推送、CI 及受管發布狀態引用同版本外部 `final-closeout-report.md`。沒有重跑完整本機套件或 stage，也沒有修改產品執行程式。


## 2026-10-13 — PR198 後續：既有案例補齊與投組品質誤擋修正（5.0）

基底／已部署 main：`edd44f6c719e1e844d2ae8853a68c575b2f65ee3`。本輪後續分支 `codex/pr198-regression-followup`；本機候選，後續提交 SHA 由 PR 指向，不改寫舊發布歷史。

重現 Sam 指定 13 模組共 168 案的 15 失敗、10 錯誤，逐案分類、契約與發布阻擋見 [PR198後續分類](PR198後續分類.md)。修正日期／日曆／單一還原快照 fixtures，保留原數值與 fail-closed 斷言；產品修正投組純量差誤擋、單日缺收盤抹除整段、舊年未知日曆抹除已核對尾段。Sam 已決定恢復網頁 owner POST `/macro/refresh/<id>`；同源、reader 與 GET 保護保留。

局部結果：169 個指定模組／權限案例通過，新增投組六案通過，先前相鄰 22 契約逐項通過；不跑完整測試。驗證計畫納入全部指定模組及其直接依賴，遠端 CI 結果另記。

**發布狀態：HOLD，未 stage／promote／部署後續修正。** 兩站代表性實際投組與部位區間仍因還原快照／公司行動涵蓋不足而空；2330 供應商 10-12 全欄缺值造成警報暖機不足，0050 真實指標可用。不得以測試全綠宣稱實際非空驗收通過。完成 Claude Opus 5.5 第二意見後由 Sam 決定是否合併；本代理人不合併。


### PR198 後續覆核修訂

初版候選 `f6ec2bd7bef23c0d0fbc7ef2d72e9e4718f2c28f` 已推送至 Draft PR #199；CI 38392880941 的 Ubuntu／Windows 局部四群皆通過。Claude Opus 5.5 第一輪因必要材料不足未被採納為完整審查；已核實並修正跨執行緒 fixture、HTTP 正面斷言、owner 單一 id 限制與日曆樣本期間揭露，補上足量資料但缺來源涵蓋收據的拒絕案例。覆核修正的本機 169 項中 167 項先通過，兩個新增 HTTP fixture 錯誤修正後獨立補驗通過；日期合併兩模組未變沿用既有證據。最終 200 案計畫之遠端環境結果另記。

HOLD 不變：真實投組與 2330 警報的資料條件尚未補齊，不合併、不 stage、不 promote、不部署；不把 Draft／文字紀錄宣稱為自動發布門禁。

### PR198 複審收尾與歷史回補決定（2026-10-13）

Claude Opus 5.5 已對候選 d9803ec6383c1b9a3b8d35bdc618a4f7af215b95 完成材料完整的複審，提出兩項中等與一項低等意見。最後修正沿用圖表登錄表拒絕全部更新別名及未知 id；Sam 明確核准「保留單一圖表的既有歷史回補能力」，因此 body／query 的 dense／density／step／years 保留，同源、授權、reader 與 GET 保護維持。補回兩項受影響 F09 既有契約，固定 benchmark 測試日期避免 fixture 過期。

局部補驗 38 項全過（30.351 秒），未重跑未變案例或全套。CI 計畫共 203 項；d980 的前次 Ubuntu／Windows CI 38394278642 已通過，最後提交及遠端結果與 PR #199／外部交付紀錄相互引用。完整 25 項分類、覆核處置、能力對帳與證據位置見 [PR198後續分類](PR198後續分類.md)。最後意見修正由作者自審及測試，沒有第三輪 Claude 覆核。

狀態：Stock Terminal 5.0 後續修正候選，準備推送 Draft PR #199；本輪未 stage／promote／部署。兩站真實投組、部位區間與 2330 警報資料不足的 HOLD 仍未解除；不以靜態或 CI 成功代替實際驗收，由 Sam 決定合併。

### 2026-10-14 — CI 與交付封存的來源位元組一致

候選 `a474223410c68e4bffb21f438b5c225ad0d858b4` 的雙平台局部 CI 已通過，但 Windows checkout 自動轉成 CRLF，無法把成功證據沿用到保留 Git 原始 LF 的發布封存。CI 在 checkout 前停用自動換行轉換，保留儲存庫既有 CMD 位元組規則；未改本機 Git 全域設定。既有 CI 接線單一案例補上順序與唯一性斷言，經全域驗證入口通過。Windows 首次取得原始位元組的受影響案例須重新取得真實證據；後續 PR、main 與 stage 依相同輸入、驗證器與環境核對沿用，未把 CRLF 收據改寫成 LF，未擴成全套。

本段建立時為 CI 修正候選，程式版本維持 5.0，沒有新增產品功能。最終完整 SHA、Claude 複審、CI 與兩站部署身分沿用本頁指定的「完整歷史交付收據.json」追溯。

### 2026-10-14 — 完整歷史最終複審與收據邊界收尾

Claude Opus 5.5 對完整產品封包完成材料完整的跨供應商複審，結論為無阻擋缺陷，僅有一項低風險收據結構缺口。已在解析邊界加入精確型別檢查：雜湊與身分自洽、但 JSON 根或表格格式錯誤時，一致回傳單股資料拒絕，不使整個投組請求拋錯。五個新增反例及兩個正常官方來源保全案例經全域入口通過；最後小修由作者自審及七個局部案例驗證，沒有再追加 Claude 審查輪。

0050 官方停牌期間的舊平價觀測仍保留於原資料，供應商還原快照仍可能因已知無效交易日被拒絕；本輪不將其改成有效資料，完整官方比較來源獨立揭露此限制。每日有界官方續補已在 Sam 本輪授權範圍內，未啟用先前停用的排程。部署工具另以同一資料庫的完整已核對交易日決定首日，避免週末起日誤拒，仍核對精確截止日及錨定日。

CI 換行修正提交 `207a0fb442a367f626639b6457645218e0f7cca9` 的 Ubuntu／Windows 局部 CI `38447146359` 皆成功。最後產品小修、合併及部署身分仍由本頁指定完整歷史交付收據追溯，不以此候選紀錄代替發布證據。
## v5.0 修訂 — 2026-10-16 三標的行情標頭對齊與回歸補漏

基底 `3ab69f2a20c9488f4018b6e910c605daf6407936`；分支 `codex/台指期重複回歸8D`；沿用 v5.0 的提交識別策略。此條記錄送審候選，提交與發布的完整 SHA 及實際端點結果另見本次發布紀錄，不以測試通過代替部署完成。

**原因與處理**：主圖狀態是頂層 `let S`，正式冷啟動沒有 `window.S`；切入市場圖後建立的空物件也不是同一份狀態。先前標頭事件依賴此守衛，而且只改漲跌，導致現價、比較基準與統計可分屬不同來源。本次讓加權、櫃買、台指期的主圖與右側統計直接承接既有 `MarketData` 完整報價；現價、參考價、盤別、來源時間與同盤最高一起更新。沿用原行情列的差額與百分比公式。盤前官方報價未成交時，沿用原行情列 `/yf/batch` 最近完成日線的現價與前一根收盤，保留原資料時間；不取分時 metadata 的過期昨收來混算。

**防止再發**：完整報價不被較舊 Pulse、空成交或同日較弱的圖表備援覆寫。晚到的 `/twindex` 回應要重新核對載入序號、標的與資料物件，再優先採用已到的正式報價。主圖重繪與 `symLoaded` 也承接同一組資料。夜盤價格不覆寫歷史 K 棒；沒有可信分時資料時明示「分時未提供，顯示日線歷史」，日盤／夜盤最高不再拿整年區間最高代替。右側原 OHLCV 保留，另標明 K 線資料時間。

**歷史查核**：10 月 14 日 `d651b57783a64d9b851e905730ffcf39cc41dd3c` 的同日昨收校正與 `ca35ebc21926ae2b17505e1f64388c2dd903c8c9` 的官方報價 override 仍在。從該次合併到本次基底，沒有發現相關公式或來源被移除；已證實的是原修正未涵蓋盤前缺成交及實際頁面狀態。9 月的夜盤 overlay 修正在未合入 main 的分支，不能將整支舊分支當作正式正常版回退。

**驗證**：25 組局部契約案例通過（真實 lexical `S`、無測試注入 `window.S`，涵蓋空值、舊資料、失敗重發、跨日、切股競態及第二筆報價統計更新）。完整建置頁面使用網路邊界固定行情通過三標的 1 天／6 月與 390×844、844×390、667×375 版面檢查。候選頁面搭配受管 API 的真實行情也通過三標的、冷暖切換與統計對齊；當時受管後端為 `58c36aeca1b6d080891059b961e37d9abb197209`，不冒充候選已部署。單一同供應商隔離審查提出的兩項 Required 已修正並複審消除。沒有執行完整套件。

**限制與證據**：未新增台指期／櫃買的主圖分鐘來源，無可信分時時仍保留既有日線歷史並標示；一般個股與其他市場圖狀態守衛不在本次修正範圍。外部證據根目錄為 `<AI-Workspace>/docs/stock-terminal/台指期重複回歸8D/`；發布狀態見同目錄 `行情對齊發布紀錄.md`。本次 8D 更正另見 `docs/大盤當日漲跌8D報告.md`。

---

## v5.0 修訂 — 2026-10-16 台指期與櫃買「1天」真正分鐘行情

基底 `47ace700e9890a658834b7a58e4654bb38feb6ed`，分支 `codex/當日分時修復`，VERSION 維持 5.0。移除兩標的一日強制改一年日線的前後端路徑，沿用現有分鐘解析器接入兩個具名來源，修正台指期 05:00 收盤分鐘拒收；保留較長期間官方／FinMind 日線、原始 OHLCV、未知量、日夜盤、獨立分時工具與同組行情標頭。兩指數分時每 90 秒更新，來源失敗可重試，不補造單點或轉日線。

已取得：21 項來源與路由單元、25 組標頭契約、完整頁面分鐘操作與三尺寸檢查；候選真實來源取得兩標的當日分鐘，27 個資料檔保全。經一位同供應商隔離唯讀審查，無 Required 發現；固定案例盤別終點已校正。失敗來源仍沿用既有 60 秒快取，分鐘不保證即時，未供日線回測使用。

此段建立時為本機候選，尚未提交／發布。詳細根因、能力對帳與局部證據見 `docs/當日分時修復.md`；後續完整實作／合併 SHA、CI 與實際兩站發布證據見 `C:/Users/Sam/AI-Workspace/docs/stock-terminal/當日分時修復/發布紀錄.md`。未以本機案例替代部署驗收。
