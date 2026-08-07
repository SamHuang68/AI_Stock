# Stock Terminal v5.0

Bloomberg 風格台／美股研究終端機 — **本機跑、零雲端、純 Python stdlib（不用 pip）**。

完整說明、功能表與打包規範見 **[docs/README.md](docs/README.md)**。

## 5.0 重點

- **總覽儀表板**：側欄導覽 + 一屏高密度市場脈搏（廣度、產業輪動、法人資金趨勢、全球影響、台美快訊）
- **台指期／產業 TW·US／漲跌停清單／費半·日韓**：總覽與廣度／熱力對齊
- **歷史庫 merge 同步**：頂列「同步資料」只補新日，不重灌全庫
- **真實資料計分**：缺源進「尚未納入」，不捏造 Fear&Greed／全市場 250 日新高家數

---

## 本機執行指令

需求：Python 3.10+（純標準庫）、現代瀏覽器。Server **只聽** `127.0.0.1:18432`。

### Windows（PowerShell）

在**專案根目錄**執行（不是 `scripts` 子資料夾）：

```powershell
cd C:\Users\Sam\AI_Stock
.\scripts\go.bat
```

若目前已在 `...\AI_Stock\scripts`：

```powershell
cd ..
.\scripts\go.bat
```

| 指令 | 用途 |
|------|------|
| `.\scripts\go.bat` | rebuild + 重啟 server + 開瀏覽器 |
| `.\scripts\go.bat pull` | `git pull` 後同上 |
| `.\scripts\go.bat pull <分支>` | 切分支 + pull + 重建 + 重啟 |
| `.\scripts\go.bat rebuild` | 只重建＋重啟（不開瀏覽器） |

> PowerShell 不要貼 `REM …`（那是 cmd 註解）。路徑請用你本機實際目錄，不要用文件裡的佔位路徑。

### Linux / macOS

```bash
cd /path/to/AI_Stock
chmod +x scripts/go.sh          # 首次
./scripts/go.sh                 # rebuild + 重啟 + 嘗試開瀏覽器
```

| 指令 | 用途 |
|------|------|
| `./scripts/go.sh` | rebuild + 重啟 + 開瀏覽器 |
| `./scripts/go.sh pull` | `git pull` 後同上 |
| `./scripts/go.sh pull <分支>` | 切分支 + pull + 重建 + 重啟 |
| `./scripts/go.sh rebuild` | 只重建＋重啟（不開瀏覽器） |

### 手動（任一平台）

```bash
cd /path/to/AI_Stock
python3 build_v2.py                 # 或 Windows: python build_v2.py
python3 server/server.py            # 前景跑；Ctrl+C 結束
```

瀏覽器開啟（開頁後建議 **Ctrl+F5**）：

```
http://127.0.0.1:18432/stock_terminal_v2.html
http://127.0.0.1:18432/stock_terminal_v2.html#pulse
```

> 融資週期／TDCC 集中度／`pulse_history.db`／`market.db` 等大 DB **不隨 git／分享包**；首次使用會背景回補或按頂列「同步資料」。

---

## 打包可分享版

```bash
python3 scripts/build_dist.py
# Windows: python scripts\build_dist.py
# 或雙擊 scripts\build_dist.bat
```

產出根目錄 **`Stock_Terminal_v5.0.zip`**（已剝除 API Key、警報、觀察股、本機大 DB）。收件者解壓後：

- Windows：`scripts\go.bat`
- Linux／macOS：`./scripts/go.sh`

## 分享版注意

發行 zip **不含**：Claude API Key、Telegram／Email 警報、觀察股後端清單、畫線雲端記憶、本機大庫。請自行在 UI 設定；觀察股只存在你本機瀏覽器。

## 授權

MIT
