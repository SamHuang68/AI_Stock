# Private Web ST 註冊、邀請與登入指南

Private Web ST 是經由 Tailscale 分享的私人服務，不是公開網站，因此沒有「任何人都能自行註冊」的帳號系統。使用者必須同時取得：

1. 管理者授予的 Tailscale 機器存取權；
2. Stock Terminal 的 `Reader` 存取密碼。

兩項缺一不可。請勿使用 Tailscale Funnel，也不要在路由器上開放 ST 的 `18432`、`18434` 或 `18435` 連接埠。

## 一般使用者：第一次從 iPhone 登入

### 1. 接受 Tailscale 邀請

管理者會用 Tailscale 分享 ST 主機。請用收到邀請的同一個電子郵件帳號接受邀請；邀請只代表可連到該主機，不會取得管理者的整個網路。

### 2. 確認 VPN 已連線

1. 從 App Store 安裝 Tailscale。
2. 登入收到邀請的帳號。
3. 在 Tailscale App 確認 VPN 為已連線，且能看到管理者分享的 ST 主機。
4. 若剛從 Wi-Fi 切換到行動網路，先關閉再重新開啟 Tailscale VPN。

### 3. 開啟正確網址

在 iPhone 的 Chrome 開啟管理者提供的完整 HTTPS 網址：

```text
https://<管理者提供的主機名稱>.ts.net/
```

不要把 `18432`、`18434` 或 `18435` 加到網址，也不要使用 `http://`。

### 4. 選擇登入身分

- 一般受邀者選 `Reader（唯讀）`。
- `Owner` 僅供主機管理者使用，不應分享給其他人。

輸入管理者透過另一個安全管道提供的 Reader 密碼後，按「安全登入」。

### 5. 是否勾選「記住我的登入」

- 私人 iPhone：可以勾選，最長保留 30 天。
- 共用或借用裝置：不要勾選。
- 未勾選：工作階段最長 12 小時；瀏覽器關閉或系統清理 Cookie 後可能提早失效。

ST 不把原始密碼寫入 `localStorage` 或可由頁面 JavaScript 讀取的 Cookie。瀏覽器保存的是有期限、簽章且 `HttpOnly` 的工作階段 Cookie；管理者輪替存取密碼並重啟 Gateway 後，既有工作階段會失效。

## 管理者：邀請一位 Reader

### 1. 只分享 ST 主機

在 Tailscale 管理介面找到運行 ST 的主機，使用機器分享功能將該機器分享給指定使用者。優先使用指定電子郵件或一次性邀請，不要為了 ST 將整個 tailnet 開放給對方。

### 2. 另外交付 Reader 密碼

Reader 密碼保存在主機本機：

```powershell
$repo = 'C:\path\to\AI_Stock'
Set-Location $repo
$reader = (Get-Content data\private_web_read.token -Raw).Trim()
```

請用與 Tailscale 邀請不同的安全管道交付，且不要在對話截圖、Git、README 或公開分享包中放入密碼。絕對不要把 `private_web_owner.token` 提供給受邀者。

### 3. 提供三項資訊

只需告知受邀者：

1. Tailscale 機器邀請；
2. `https://…ts.net/` 完整網址；
3. Reader 密碼。

### 4. 撤銷存取

- 只撤銷某位使用者：在 Tailscale 移除該主機分享。
- Reader 密碼疑似外洩：輪替兩組 ST 存取密碼並重啟 Private Web ST：

```powershell
$repo = 'C:\path\to\AI_Stock'
Set-Location $repo
py -3 scripts\setup_private_web.py --rotate
.\STOP_PRIVATE_WEB.cmd
.\START_PRIVATE_WEB_HOST.cmd
```

輪替會讓所有舊的瀏覽器工作階段與 API Token 失效，因此應重新透過安全管道交付新的 Reader 密碼。

## iPhone 黑畫面排除

新版 Gateway 會記錄不含密碼的啟動階段，並在完整介面 5 秒內未完成啟動時，自動嘗試進入總覽；仍失敗則顯示相容圖表與重試按鈕。

依序檢查：

1. 等候 5 秒，確認是否出現總覽或「已切換手機相容圖表」。
2. 關閉該 Chrome 分頁，再從完整 `https://…ts.net/` 網址重新開啟。
3. 確認 Tailscale VPN 仍顯示已連線，且帳號正確。
4. Chrome 若保留舊的原生 Basic-auth 狀態，先關閉所有 ST 分頁並完全結束 Chrome 後重開；仍無效時，在 Chrome 的「清除瀏覽資料」中清除 Cookie／網站資料後再登入。這可能同時登出其他網站。
5. 開啟以下健康檢查網址；應看到 `"ok":true`：

```text
https://<管理者提供的主機名稱>.ts.net/gateway/health
```

6. 仍無法顯示時，把發生時間、iPhone 型號、iOS 版本與畫面交給管理者。

管理者可檢查：

```powershell
$repo = 'C:\path\to\AI_Stock'
Set-Location $repo
Invoke-RestMethod http://127.0.0.1:18434/gateway/health
tailscale serve status
Get-Content logs\private_web_audit.jsonl -Tail 50
Get-Content logs\private_web_client.jsonl -Tail 50
```

`private_web_audit.jsonl` 記錄登入成功／失敗與被拒絕的請求；`private_web_client.jsonl` 記錄 UI 啟動階段、視窗尺寸與錯誤類型。兩者都不記錄登入密碼、Authorization Header 或請求本文。

## 常見狀況

| 狀況 | 判斷與處理 |
| --- | --- |
| Tailscale 已連線但網站打不開 | 確認已接受正確主機分享，並使用 `https://…ts.net/`，不是本機 IP 或連接埠。 |
| 顯示密碼錯誤 | 檢查是否把 Reader 密碼配成 Owner 身分，或管理者是否已輪替密碼。 |
| 登入後又回登入頁 | Chrome 可能處於無痕模式或 Cookie 已被清除；改用一般分頁並暫停可能攔截本站的內容阻擋器。 |
| 換網路後停止更新 | 重新連接 Tailscale VPN，再重新整理 ST。 |
| 共用裝置曾勾選記住登入 | 清除該 `.ts.net` 網站資料，並通知管理者評估是否撤銷分享。 |

## 安全邊界

Reader 只能讀取市場、報價、基本面、廣度、總經、Pulse 與 DecisionContext 等核准資料。通知設定、密碼管理、遠端回補、WaveDeck、交易與券商操作不會經由 Private Web ST 開放。
