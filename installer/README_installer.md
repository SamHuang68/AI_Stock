# Stock Terminal — 打包成 Windows 安裝檔

把 Stock Terminal 做成一個 `setup.exe`，收件人像裝一般程式一樣雙擊安裝，**完全不用另外裝 Python**（server 已用 PyInstaller 凍結、內含 Python）。個人安裝，免系統管理員權限。

---

## 一次性準備（只需做一次）

1. **Python 3.10+**（你已經有）。
2. **Inno Setup 6**（免費）—— 從 https://jrsoftware.org/isdl.php 下載安裝。這是把檔案包成 `setup.exe` 的標準工具。
3. **PyInstaller** —— 不用手動裝，`build_installer.bat` 會自動 `pip install`。

---

## 怎麼產生安裝檔

在專案根目錄跑（或直接雙擊）：

```
installer\build_installer.bat
```

它會自動三步：

1. `build_v2.py` 產生最新的 `stock_terminal_v2.html`
2. PyInstaller 把 `server\server.py` 凍結成 `installer\build\server.exe`（內含 Python）
3. Inno Setup 把 server.exe + UI + 模組 + ETF 目錄打包成安裝檔

**產出**：`installer\dist_installer\StockTerminal-Setup-v3.9.exe` —— 把這**一個檔**寄給別人就好。

---

## 收件人體驗

1. 雙擊 `StockTerminal-Setup-v3.9.exe` → 一路下一步 → 裝好（裝到個人目錄，免管理員）。
2. 開始選單 / 桌面出現「Stock Terminal」捷徑。
3. 點捷徑 → server.exe 啟動（一個小視窗）→ **自動開瀏覽器**進到看盤畫面。
4. **要關閉**：關掉那個 server 小視窗即可。
5. 移除：到「設定 → 應用程式」或開始選單的「Uninstall Stock Terminal」。

> Windows 可能跳 SmartScreen 警告（因為 exe 沒有付費的程式碼簽章）：點「**其他資訊 → 仍要執行**」即可。要消除這警告需要購買程式碼簽章憑證，非必要。

---

## v1 範圍與限制

- **完整可用**：K 線、技術指標、量價、多圖、畫線、選股、回測、策略、估值、資金流、法人榜、AI 報告等**互動功能全都在**。
- **不含背景排程**：每日 ETF 持股快照爬蟲、後端警報推播 daemon、籌碼每日快照這些「背景常駐 / Windows 排程」功能**沒有包進安裝版**（它們需要 Python 環境 + 工作排程器）。要用那些，仍用開發版（git repo + `scripts\start_terminal_v3.bat`）。
- **資料位置**：你的畫線、API Key、籌碼快照存在安裝資料夾的 `data\`（個人目錄下、可寫）。

---

## 疑難排解

- **PyInstaller 失敗**：確認 `python --version` 正常；手動 `python -m pip install --user pyinstaller` 再重跑。
- **找不到 ISCC**：裝好 Inno Setup 後，server.exe 已在 `installer\build\`，手動編譯：`iscc installer\StockTerminal.iss`。
- **點捷徑沒反應 / 瀏覽器沒開**：可能 18432 埠被占用。先關掉舊的 server 視窗，或改 `server\server.py` 的 `PORT` 後重新打包。
