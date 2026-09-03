# Stock Terminal 文件索引

完整的產品說明、系統架構、資料流、頁面邏輯地圖、啟動方式、安全邊界、測試與分享打包流程，統一維護在根目錄 [README.md](../README.md)。

## 文件導覽

| 文件 | 內容 |
|---|---|
| [README.md](../README.md) | 主要說明、架構、資料契約、流程圖、測試與分享 |
| [TIP_UX.md](TIP_UX.md) | 分析轉盤、快捷鍵與總覽操作 |
| [FIELDS.md](FIELDS.md) | 欄位型別與前後端一致性契約 |
| [STRATEGIC_COMMAND_CENTER_PLAN.md](STRATEGIC_COMMAND_CENTER_PLAN.md) | 戰略指揮中心、DecisionContext 與實作計畫 |
| [HOUSEKEEPING.md](HOUSEKEEPING.md) | 專案維護與清理原則 |
| [WaveDeck ARCHITECTURE](../wavedeck/docs/ARCHITECTURE.md) | 可選執行台架構 |

## 快速啟動

Windows：

```powershell
cd C:\Stock_Terminal
.\START_TIP.cmd
```

Linux／macOS：

```bash
cd /path/to/Stock_Terminal
./scripts/go.sh
```

瀏覽器：<http://127.0.0.1:18432/#pulse>

## 文件維護原則

- 根目錄 README 是架構與操作的單一主要文件。
- 欄位、來源、盤別或比較基準變更時，同步更新資料契約章節與測試。
- 不在文件中放真實 API Key、Email、Telegram ID、個人絕對路徑或私人 Git remote。
- 內部交接、稽核與修訂筆記不進公開分享包。
- 對外分享前執行 `python scripts/build_dist.py` 與 `python -m unittest tests.test_dist_scrub -v`。
