# WaveDeck 紙上 P0 契約

僅離線／paper；基線 7fff194a7cac4e78d1d90291c8e833c776542367；分支 codex/wavedeck-paper-p0。沒有發布、真實交易或模型呼叫。

## 行情與未知值

行情包含 symbol、price、as_of、source、demo。as_of 必須含時區，價格須有限且為正，商品須吻合；預設 90 秒有效，每次入場與模擬成交重新核對。缺漏、過時、無效、未來日期阻擋新風險；demo 僅能用於 paper。未知權益與信心度為 null，已知平倉部位為 0。

ST decision_as_of 是來源時間，overlay_at 是接收時間，心跳不刷新來源日期；缺少日期不補造 fresh。畫面標示「核對時」，不宣稱靜態畫面持續新鮮。heuristic 是確定性示範規則，rule_score 不是機率或勝率。

## 委託與成交

signal_id 重送已接受意圖會回原紀錄並跳過模型；每個不同意圖須用不同識別碼，省略則產生新 ID。pending 不更動已確認帳戶／策略部位；confirmation 才改部位。部分成交、部分減碼與 EXIT 分開處理。receipt_id 冪等；錯商品、錯單、超額及非有限價格拒絕。

PaperBroker sync 用通過契約的 quote 產生明確 source=paper 的模擬成交，保存 quote_source/as_of。這不是券商成交、真實撮合、流動性或滑價模型。paper_order／execution 隨 Runtime 保存，重啟仍保留委託、回報及冪等識別。signal/sync/panic 經單程序鎖排序，不宣稱多服務程序共用 JSON 可安全交易。

急停阻止新風險、取消未成交入場，再建立平倉意圖，不把送出等同已平倉。paper 不寫真實 TXT。既有不留倉時限只阻止新單；自動強制平倉尚未實作。

## 費用與輸入顯示

SQLite BEGIN IMMEDIATE 在付費前原子預留，持久化且跨程序共用。固定 UTC+08:00 准入日計算每日配置上限，同日只能收緊。預設 USD 5、精確模型費率預設空白，所以付費阻擋。

openai.pricing 精確模型鍵須含 input_usd_per_million、output_usd_per_million、context_window_tokens、max_output_tokens、output_limit_parameter=max_completion_tokens、limits_source。以完整 context window 加最大輸出費保守預留；不得猜測費率或來源。上限以配置及供應者遵守 token 限制為前提，不是供應者帳務保證。

逾時／缺 usage 保留預留，cost_usd=null；未知費用不能加成 0。畫面分列已用及預留、預留、配置上限；不因 fallback 到規則引擎而宣稱當日免費。session/month 是執行期累計，未知保持未知，不代表經供應者核帳。

訊號驗證 JSON 物件、16 KiB、有限數值與 symbol/provider/ID 型別；bridge 驗證形狀。模型／資料文字用 textContent 或 HTML escape。auth、CORS、網路與服務權限未更動。

## 驗證與限制

新增 Python fixtures 74 例通過（資料26、委託18、費用22、整合8），並通過直接相依既有案例。費用含三個獨立程序競爭與重啟；fake DOM 123 項斷言通過。沒有全套測試、真實瀏覽器、券商驗收、CI、push、merge、部署。

控制 API auth、CORS/allowed origins、對外網路與服務權限須另案授權；付費配置須有可驗證來源，保持停用即可完成本輪離線範圍。
