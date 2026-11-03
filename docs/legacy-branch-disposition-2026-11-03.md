# 舊分支處置紀錄（2026-11-03）

Sam 2026-11-03：「有價值的全部整合 其餘刪掉」。本檔記錄當時尚存的 75 個非 main 分支各自的處置、依據與復原方式。

## 依據與方法

- 分支是否已在 main：祖先關係、`git cherry`（patch-id）、PR 的 base 與狀態。逐檔比對對舊分支無效（每個檔案後來都被 main 改過），未採用。
- 內容是否仍有價值：（1）新增行是否仍出現在 main 同一檔案；（2）新增的函式、類別、測試名稱是否出現在 main；（3）`docs/可靠性補完與待證據清單.md` 已記錄的處置。三者都是間接證據，不等於功能等價，所以對有疑慮的項目逐項讀程式與實測。
- 舊整合線：PR #84～#127 的 base 是 `cursor/st-wd-tip-integrate-3497` 而非 main；該線 2026-09-03 之後就沒有再合進 main，main 光 10 月就有 442 個提交。

## 整合到 main

| 分支 | 內容 | 去向 |
| --- | --- | --- |
| `claude/heat-industry-sectors-only` | 2026-10-21 完整程式碼審查報告與修正（H-1 GET 同源檢查、H-2 代號單次解碼、鎖範圍、ETF TLS 驗證等） | PR #283 |
| `codex/preserve-local-main-b3209f3-20261001` | AI 金鑰可配對 Anthropic 工作區 ID；金鑰變更時不沿用舊模型快取；解讀失敗時顯示可行動的錯誤 | 本次整合 PR（與下一列同一個 PR） |
| 舊整合線的 `server/美股類股成員.py`（來源提交 `e5c148c`，PR #93 的 `codex/手機熱力捲動與類股明細`） | 熱力圖美股產業可查看成員：State Street 官方每日持股加 Pulse 批次報價；main 原本對美股只回 UNAVAILABLE | 本次整合 PR |

## 保留（有價值但本次無法整合，需要決定）

- `claude/runtime-unification-fixes`（`71be7fa44ad5491145dd96287ddcc13b24f92c12`，#266 已關閉）：Sam 2026-10-26 關閉 #266 時指定保留，單一資料根架構驗收未完成；需要時可重開 PR。
- `codex/wavedeck-paper-p0`（`0bec06d009c6a8a3c57587a9c678394b667522ed`，無 PR）：WaveDeck 紙上 P0（行情時效契約、委託冪等、付費預算預留，約 2.7k 行），main 沒有這些模組；與 2026-10-19～21 的 WD-07 等紙上模式修改在 broker／engine／risk／st_link／server／deck.js 七處衝突，需先決定紙上模式的權益與委託語意。
- `codex/跨專案驗證入口`（`5dac8ba0d35ac4f206705f2f9d7500bda53df79e`，無 PR）：`tools/codex` 的跨專案直接命令與 `--reuse-only` 等，與使用者共用的全域 tools/codex 內容相同，但 main 的複本較舊；整合會讓「文件計畫不可建立可發布 stage」生效，使 `tests.test_private_web_release` 的 4 個既有案例失敗（本機實測），屬發布政策取捨。
- `fix/etf-catalog-validation`（`e88f2d8da2def6d4d0506d71815ece253a590eb0`，無 PR）：Codex 的 ETF 目錄欄位型別驗證修復（e88f2d8），與 #266 的每輪重載機制綁在一起，main 沒有該機制所以未照搬；與上一條同屬架構決定。

## 舊整合線逐 PR 核對（符號＝該 PR 新增的函式、類別、測試名稱，出現在 main 的比例）

| PR | 標題 | 分支 | 符號在 main |
| --- | --- | --- | --- |
| #84 | feat(tip): 把 T3/T4/T5 區間高點與投信觀察接到 tip UX | `cursor/st-t345-on-tip-3497` | 100%（163/163） |
| #85 | feat(pulse): 來源長框收入標題列 · Codex freshness on tip | `cursor/st-pulse-head-meta-3497` | 96%（22/23） |
| #86 | fix(go.ps1): 略過行情 data dirty，讓 tip 快轉不再誤擋 | `cursor/st-go-data-dirty-3497` | 無符號 |
| #87 | fix(pulse): 金框改填「新手」左側空白，不再另開一列 | `cursor/st-meta-novice-gap-3497` | 0%（0/1） |
| #88 | chore: ST 一體兩面，本機與 Private Web 須同步後才能 release | `cursor/st-two-faces-sync-3497` | 0%（0/1） |
| #89 | fix(private-web): stage 不因 :18434 測試 stderr 被掐掉 | `cursor/st-sync-stage-stderr-3497` | 100%（1/1） |
| #90 | fix(afterhours): 手機直式單欄堆疊，橫式籌碼線圖不再蓋字 | `cursor/st-ah-mobile-stack-3497` | 無符號 |
| #91 | 新增估值承接研究與分批成本觀察 | `codex/估值趨勢承接` | 48%（41/85） |
| #92 | 修正私有網站發布成功後的參數型別錯誤 | `codex/修正私有網站發布回報` | 無符號 |
| #93 | 修復手機熱力捲動並新增類股個股清單 | `codex/手機熱力捲動與類股明細` | 31%（21/67） |
| #94 | 修正私有網站發布流程並驗證兩端啟動版本 | `codex/修正私有網站發布完成驗證` | 41%（7/17） |
| #95 | 修正私有網站背景程序讓發布命令正常返回 | `codex/修正私有網站背景程序管線` | 0%（0/1） |
| #96 | 改善 AI 中樞更新可靠性與鍵盤手機操作 | `codex/AI中樞可靠性優化` | 20%（22/109） |
| #97 | 共用焦點掃描並顯示實際完成時間 | `codex/焦點掃描協調` | 100%（26/26） |
| #98 | 新增官方日線更新與 K 線事件研究 | `codex/台股事件日線整合` | 95%（53/56） |
| #99 | 同步 K 線事件首頁建置產物 | `codex/首頁建置產物同步` | 無符號 |
| #100 | 修正三合一選股基本面與法人欄位空白 | `codex/三合一選股欄位修正` | 77%（24/31） |
| #101 | 補齊選股查詢結果排序與還原操作 | `codex/選股查詢排序` | 50%（4/8） |
| #102 | 修正台股金融業基本面來源與最近期營收回補 | `codex/台股基本面源頭修正` | 100%（25/25） |
| #103 | 新增 K 線事件完整歷史期間與時間軸瀏覽 | `codex/K線事件歷史時間軸` | 100%（13/13） |
| #104 | 修復 AI 報告與副駕的等待狀態及串流完成判定 | `codex/修復AI報告與副駕` | 57%（16/28） |
| #105 | 修正台股共用成交解析與報價時效判定 | `codex/修正台股即時成交來源` | 100%（19/19） |
| #106 | 同步主圖與右側統計的成交漲跌 | `codex/同步個股報價統計` | 100%（2/2） |
| #107 | 修正台指期時段與統計資料完整性契約 | `codex/體檢資料契約修正` | 14%（3/21） |
| #108 | 禁止以夜盤補成台指期日線 | `codex/台指期日盤匯入補正` | 0%（0/1） |
| #109 | 修正決策資料品質、非同步狀態與可回復發布 | `修復/架構功能審查-20260919` | 86%（95/111） |
| #110 | 修正私人網站完整測試與套件排除順序 | `修復/發布暫存驗證-20260919` | 無符號 |
| #111 | 改善 PDF 匯入解析、同源資產與相容性驗證 | `改善/PDF匯入升級-20260920` | 13%（2/15） |
| #112 | 修正決策快照持久提交與重啟恢復 | `改善/決策快照一致性-20260920` | 97%（62/64） |
| #113 | 修正手機總覽快照資訊列寬度 | `改善/手機快照資訊列-20260920` | 無符號 |
| #114 | 改善 Pulse 讀寫分離與更新工作恢復 | `改善/Pulse讀寫分離-20260920` | 92%（88/96） |
| #115 | 修正 PDF 匯出完整分頁與依賴可靠性 | `改善/PDF匯出可靠性-20260920` | 20%（8/41） |
| #116 | 修復官方行情來源、上櫃代號與分類涵蓋 | `修復/行情來源-20260920` | 17%（9/54） |
| #117 | 修正上市分類母體標示並保留存託憑證資料 | `修復/分類範圍標示-20260920` | 80%（4/5） |
| #118 | 修復決策更新按鈕卡住與等待收尾 | `修復/決策更新等待-20260920` | 29%（5/17） |
| #119 | 修復個股健診休市與歷史資料分析 | `修復/個股健診歷史分析-20260920` | 80%（16/20） |
| #120 | 恢復手機橫向五欄並避免卡片文字裁切 | `修復/手機橫向五欄-20260922` | 100%（2/2） |
| #121 | 修正 Windows 與手機直立橫向的欄位及文字排版 | `修復/全頁跨裝置版面-20260922` | 無符號 |
| #122 | 新增長期突破觀察、影子紀錄與隔日開盤對照研究 | `codex/突破觀察研究-20260922` | 52%（55/105） |
| #123 | 新增第三階段官方參考價研究與歷史資料核對 | `codex/研究資料第三階段-20260922` | 44%（44/101） |
| #124 | 補齊歷史升級缺口與可追溯研究工作流 | `codex/全面補完-20260923` | 78%（291/375） |
| #126 | 新手面板顯示既有短訊號與指標 | `cursor/beginner-panel-signals-de61` | 25%（4/16） |
| #127 | 新手面板顯示既有短訊號 | `cursor/beginner-panel-signals-7370` | 77%（17/22） |

符號比例低的 PR，逐項確認為：PDF 匯入匯出（#111、#115）與舊 AI 報告入口（#96、#104）已於 2026-09-26 退役，見 `docs/可靠性補完與待證據清單.md`；私有網站發布流程（#88、#89、#92、#94、#95）由 #143～#151 的 exact-SHA stage／promote 取代；研究類（#91、#101、#122、#123、#124）依同一份文件以新契約重做，main 已有 `估值趨勢.py`、`突破觀察.py`、`突破成交研究.py`、`突破影子紀錄.py`、`公司行動比較.py`、`研究工作流.py`；版面類（#87、#90、#93、#113、#118、#120、#121、#126）因 main 的 UI 已重整，行層級無法對應；台指期時段（#107、#108）main 於 2026-10 重做（見修訂紀錄 2026-10-14、2026-10-16）；官方行情來源與上櫃代號（#116、#117）main 以 `market_contract.py` 等重做。

### 檢視後未移植的項目

- Email 聯絡人通知（`server/notify_contacts.py`）與 AI 分析全文朗讀：附屬於已退役的 AI 報告入口，移植需要重新設計入口與聯絡人儲存。
- TDCC 持股分散的 HHI／熵（`tdcc_holders._hhi_entropy`）：需要對 `holders_week` 加欄位，且來源註明「不進入總分」，價值有限。
- 私有網站同步包裝（#88）：由 exact-SHA 發布流程取代，文件明確寫「不得恢復自動同步未提交工作區」。

## 分支一覽（處置前的分支頭 SHA）

| 處置 | 分支 | 分支頭 | PR | 理由 |
| --- | --- | --- | --- | --- |
| 整合 | `claude/heat-industry-sectors-only` | `d0f641089a3dcaa77ad5c0e5837d0b61280d93ce` | #256 已合併 | 整合：審查報告與修正，PR #283。 |
| 保留 | `claude/runtime-unification-fixes` | `71be7fa44ad5491145dd96287ddcc13b24f92c12` | #266 已關閉 | 保留：Sam 2026-10-26 關閉 #266 時指定保留，單一資料根架構驗收未完成；需要時可重開 PR。 |
| 刪除 | `codex/AI中樞可靠性優化` | `66393951361ed212e8c38ce1c73bb4a5115534d6` | #96 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/K線事件歷史時間軸` | `4a074ef1532661566a1db4773a501d44adf1458a` | #103 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/K線時間軸合併紀錄備份` | `3a7a42e4f8de8f6260bc75fe84a7eb1778ff9e7b` | 無 PR | tip 線 K 線事件時間軸的備份；main 已有 K 線事件（`server/K線事件.py`、`src/ui/K線事件研究.js`）。 |
| 刪除 | `codex/backup-before-runtime-split-20260903` | `180bc3938e277df86f8c3964f051598f0e4413bd` | 無 PR | 2026-09-03 的備份分支，內容為 PR #30 之前的狀態；main 已遠超過。 |
| 刪除 | `codex/backup-market-data-pre-pr30-20260903` | `33c3c6d9623b38ffbf9cf38a7203f4eb1d2d61e4` | 無 PR | 2026-09-03 的備份分支，內容為 PR #30 之前的狀態；main 已遠超過。 |
| 刪除 | `codex/market-data-followup-20260903` | `b31dd3c247a45cc1f19f0bcb68fda5b75a63d577` | 無 PR | 熱力圖手機可視區與台指期／法人日期來源契約；main 以 `market_contract.py` 與後續熱力圖修改重做。 |
| 刪除 | `codex/pr168-launcher-acceptance` | `5d140b5f108bd2fed66f60f353c8b272c4133f2b` | 無 PR | PR #168 的啟動器驗收後續；其測試檔 `test_launcher_startup_windows.py` 的新增行 99% 已在 main，修訂紀錄亦已收錄，之後 #276、#281 又改過啟動器。 |
| 刪除 | `codex/pr30-wavedeck-hotfix` | `a6fa0a976396bdfa7f14d01b2d0b8a47137b8740` | #61 已關閉 | PR #61 已關閉；WaveDeck 測試隔離修正，新增行 61% 已在 main，WaveDeck 之後又有 2026-10 的多次修改。 |
| 整合 | `codex/preserve-local-main-b3209f3-20261001` | `b3209f370fe28bcf7409b66b232305ecec6c66aa` | 無 PR | 整合：AI 金鑰工作區 ID 與解讀錯誤提示，見修訂紀錄「整合舊分支的未合併功能」。 |
| 保留 | `codex/wavedeck-paper-p0` | `0bec06d009c6a8a3c57587a9c678394b667522ed` | 無 PR | 保留：WaveDeck 紙上 P0（行情時效契約、委託冪等、付費預算預留，約 2.7k 行），main 沒有這些模組；與 2026-10-19～21 的 WD-07 等紙上模式修改在 broker／engine／risk／st_link／server／deck.js 七處衝突，需先決定紙上模式的權益與委託語意。 |
| 刪除 | `codex/三合一選股欄位修正` | `71b2847390cf63577f09a3029ce9333159172813` | #100 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/估值趨勢承接` | `fb59ed1f04aad774b7a58b22285ab77d54bec7a5` | #91 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/修復AI報告與副駕` | `50451f3da9ec087b498efe03bd2414a400e74c2b` | #104 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/修正台股即時成交來源` | `7bcb38ecd6e80654b90b06a5c14bcd90aa8988ea` | #105 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/修正私有網站發布回報` | `3a4949ee9bf09ab13af54a44c4196ae29f2ebeea` | #92 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/修正私有網站發布完成驗證` | `2054447a6659246b1fd4d177afd6cc08c469dbee` | #94 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/修正私有網站背景程序管線` | `3983bd1305a5d2a1512f43c1c0e55ab6599c0b23` | #95 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/全面補完-20260923` | `74e92166aa438145190b8a8bf4da6086f6002b66` | #124 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/台指期日盤匯入補正` | `a447f31e56f8631ec1bf1177c6ba9e8b1128eecd` | #108 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/台股事件日線整合` | `87cb552145520238c037ed5fae32231f150ca161` | #98 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/台股基本面源頭修正` | `64419289c3e767a36fc745e08c5e562ab6940c83` | #102 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/同步個股報價統計` | `62bbc35d65004af77c6103ddd2ea0ee65ffa7145` | #106 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/手機熱力捲動與類股明細` | `45ee3d5de63bb069087a8a53a18c170b05c6680c` | #93 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/焦點掃描協調` | `f53713def080d560f2dccde9cfbeb86e64b354bc` | #97 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/研究資料第三階段-20260922` | `83ae7ed14e3442bfa7f84be89066a4e4911c518c` | #123 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/突破觀察研究-20260922` | `841c09e2ecb67d4005d2483a8bcbc36fdd270c86` | #122 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 保留 | `codex/跨專案驗證入口` | `5dac8ba0d35ac4f206705f2f9d7500bda53df79e` | 無 PR | 保留：`tools/codex` 的跨專案直接命令與 `--reuse-only` 等，與使用者共用的全域 tools/codex 內容相同，但 main 的複本較舊；整合會讓「文件計畫不可建立可發布 stage」生效，使 `tests.test_private_web_release` 的 4 個既有案例失敗（本機實測），屬發布政策取捨。 |
| 刪除 | `codex/選股查詢排序` | `a49ee8a7390db14726b9bffd845235b32795417b` | #101 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/首頁建置產物同步` | `1c21bdc15fa60179fdd778d459dcd286cb61615c` | #99 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `codex/體檢資料契約修正` | `6dd7aabb7cec97a46b5b238bc59d1772300ca8a2` | #107 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/beginner-panel-signals-7370` | `2203183152020f02e50d32e27d778538fcfae964` | #127 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/beginner-panel-signals-de61` | `d585ec52ca82bb952f77ff20bd8971ae35d841e1` | #126 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/http-client-pool-3497` | `350fc187d27b951e265f6d7aa9227a3579d196fe` | #27 已關閉 | PR #27 已關閉；新增行 89% 已在 main（`server/http_client.py`）。 |
| 刪除 | `cursor/ind-prefetch-incremental-4e66` | `f441b51e41e57d147b73cd2a980221ad5a57e2c3` | #5 已關閉 | 2026-07 的指標預取；main 已重構（`indicator_cache_v3.js` 等）。 |
| 刪除 | `cursor/market-date-source-contract-6c55` | `4d0c28babcb86a15cc4417e7992e57b71d9f32b6` | #65 已關閉 | 同上（台指期與法人日期來源契約）；main 以 `market_contract.py` 重做。 |
| 刪除 | `cursor/no-other-models-default-4e66` | `aca5347129d917f54330aa99bb89ff56c4e77f59` | #83 已關閉 | PR #83 已關閉；新增行 78% 已在 main。 |
| 刪除 | `cursor/postmarket-canonical-prompt-a1d0` | `3897726cb7df5f35f1b6b737de1618edf0168660` | #64 已關閉 | PR #64 已關閉；新增行 93% 已在 main。 |
| 刪除 | `cursor/setup-dev-environment-d973` | `51be724c101161196f93af2f28ca79e7872ca783` | #2 已關閉 | Cursor Cloud 開發環境說明；`AGENTS.md` 已取代。 |
| 刪除 | `cursor/st-ah-mobile-stack-3497` | `74851832c92d7e5b2b47db679503cae1aabcc302` | #90 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-ai-speak-mail-3497` | `dc99e823212209df9d223972f5a9aa399b1a0ce9` | 無 PR | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-audit-hardening-3497` | `8e5c87883dc0f68878aa843d92cea327fb8cde54` | 無 PR | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-go-data-dirty-3497` | `0035269e38867bfb4768bf27b8687f402f956973` | #86 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-meta-left-novice-3497` | `53aa7b3eb6803935dc7f0db6a14a14bf2b414ebe` | 無 PR | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-meta-novice-gap-3497` | `b0dcda241f934e0aeac1a25e1f6c373e5a4afde2` | #87 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-no-other-models-3497` | `4331697744cf76b28167c390d669293302b78dff` | 無 PR | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-pulse-head-meta-3497` | `a7488f4b7f7ff59cd65ed5c4ba4474c9a0a2d36d` | #85 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-pulse-row-balance-3497` | `df12d1da4a69492f73e679a567d82de1788dc07d` | #44 已關閉 | 2026-08 的 Pulse 三排版面；Pulse 之後整個改版。 |
| 刪除 | `cursor/st-pulse-strip-spark-3497` | `b3bc30f5a4e50a7508affd9af0bccce4b6fd5023` | #43 已關閉 | 2026-08 的 Pulse 底排壓縮；Pulse 之後整個改版。 |
| 刪除 | `cursor/st-sync-stage-stderr-3497` | `4ba328517a17ed8987fc0102da0e8e4c3d8997b3` | #89 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-t345-on-tip-3497` | `30d9f23e072f66567f99ffb005b9ad1cd628a3fa` | #84 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-two-faces-sync-3497` | `d9c297b505a7ac66d6f929a59ec434ea70a6827e` | #88 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-txf-1d-intraday-3497` | `87d296d4602dfd6603c4d7a4e7225879a426710a` | 無 PR | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-txf-overlay-canon-3497` | `8f9310c9c56587dd72c31a2c2b1b7b0f3846c5bf` | 無 PR | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st-txf-ovn-k-3497` | `b5f861544d98a8b6977b898108a9cf755e435bf3` | #79 已關閉 | PR #79 已關閉；台指期「1天」顯示當日 1 分 K，main 於 2026-10-16 以「台指期與櫃買 1 天真正分鐘行情」重做。 |
| 刪除 | `cursor/st-wd-tip-integrate-3497` | `c7b4f1f883f457f64cecc63a25942c2055399a60` | #30 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `cursor/st50-docs-ux-next-arc-3497` | `606012f8effe7c5ef9576404b8e8ad10c258b626` | #25 已關閉 | 遠端分支與 main 的 606012f 相同；本機另有 2286ccb（2026-08-08「ST5.1 側欄打磨 + 籌碼室 + AI 中樞」），只存在本機，已保存在復原封包；AI 中樞入口後來已退役。 |
| 刪除 | `cursor/unified-indicators-fe49` | `9897fdf990facbbcb26b6b995af5ecb31f116ac3` | #1 已關閉 | 2026-07 的指標統一與資料源修正；main 之後重構過。 |
| 刪除 | `cursor/wavedeck-init-3497` | `adcc59ecc8f7b8b304d86e414487271d763c264c` | #28 已關閉 | PR #28 已關閉；新增行 78% 已在 main。 |
| 保留 | `fix/etf-catalog-validation` | `e88f2d8da2def6d4d0506d71815ece253a590eb0` | 無 PR | 保留：Codex 的 ETF 目錄欄位型別驗證修復（e88f2d8），與 #266 的每輪重載機制綁在一起，main 沒有該機制所以未照搬；與上一條同屬架構決定。 |
| 刪除 | `review/runtime-unification` | `f3f7ebda5017d01c059abf5be71b4b2f0822921f` | 無 PR | 其所有提交（SHA）都包含在保留的 `claude/runtime-unification-fixes`，刪除不損失任何提交。 |
| 刪除 | `修復/個股健診歷史分析-20260920` | `1f2185b35b8e68070822ae997f7b679742f1d651` | #119 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/全頁跨裝置版面-20260922` | `829fcad8de43b3a07065d0249c8e147003ec6ef3` | #121 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/分類範圍標示-20260920` | `ee9368d2f9b69bc51220f3758a57fa5f7cf1e13c` | #117 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/手機橫向五欄-20260922` | `42c444bc793ff2e78832e5c81676108b85bd5076` | #120 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/架構功能審查-20260919` | `9a8d6e70c6ce7d69eb28c1964e5c6759ab011864` | #109 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/決策更新等待-20260920` | `4f017531f1539f834b15dd9a29443af1a9cf354e` | #118 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/發布暫存驗證-20260919` | `46b37798ac9a6dd8a953b806976ad9d324966914` | #110 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `修復/行情來源-20260920` | `c0b49ee2746b723d64fc243ef65c01bfdc4b1e24` | #116 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `改善/PDF匯入升級-20260920` | `6c36558f73d479631d102af08af3d9901055f6c5` | #111 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `改善/PDF匯出可靠性-20260920` | `c2d51dd2f6661d7836139d491a970b7ab80e5dc0` | #115 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `改善/Pulse讀寫分離-20260920` | `727e207ba34fef8084505a9ecfc174784b0a31bc` | #114 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `改善/手機快照資訊列-20260920` | `ca7651c49bf4ae233bc1037fed1279b3bbd0578b` | #113 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |
| 刪除 | `改善/決策快照一致性-20260920` | `629c6ba7cd477bfb1487f5408c676a734e8291c3` | #112 已合併 | 舊整合線（PR #84～#127 合併進 `cursor/st-wd-tip-integrate-3497`，不在 main）。main 於 2026-10 以新契約重做或退役，逐項核對見下表。 |

## 復原

- 刪除前建立並驗證過的封包 `remaining-75-branches-before-delete.bundle`（約 16 MB，含所有本機與遠端分支頭），放在工作區的 `docs/stock-terminal/branch-cleanup-20261103/`（不在 Git 內）。取回單一分支：`git fetch <封包路徑> refs/remotes/origin/<分支>:refs/heads/<分支>`；封包內的本機分支頭在 `refs/heads/`。
- 有 PR 的分支，GitHub 仍保留 `refs/pull/<編號>/head`。
- 先前清掉的 133 個（完整在 main、squash 合併、補丁等價）的分支頭 SHA 在同目錄的 `deleted-branches.tsv`。
