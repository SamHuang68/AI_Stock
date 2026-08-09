# 文字 → 視覺強化計畫

> **狀態**：已執行（Phase A→D，2026-08-07）  
> **共用模組**：`src/ui/viz_v5.js`（`window.Viz`）  
> **分支**：`cursor/merge-tw-pulse-intel-b5cf`

---

## 完成摘要

| Phase | 內容 | 狀態 |
|-------|------|------|
| A | `Viz.*` + 法人線（pulse／hub／chip／instrank／marketflow／breadth／afterhours） | ✅ |
| B | 廣度分段條、分數 meter、歷史 spark、盤後排行／個股期 | ✅ |
| C | scan／news／book／polish／heat／fundamental／代號庫／score_bar | ✅ |
| D | chainmom 三點 spark、datasources badge、設定列 count chip | ✅ |

### 核心 API（`window.Viz`）

`magBar` / `magBars`（對零軸左右開）· `segBar` · `scoreMeter` · `streakChip` · `limitChip` · `chip` / `badge` · `dualBars` · `ratioMeter` · `refMeter` · `zoneMark` · `heatCell` · `rowBar` · `sparkLine` · `sparkBars` · `fmtYiFromYuan`

### 台股鐵律（已落地）

- 買超／偏多＝紅、賣超／偏空＝綠（`Colors.gain`）
- 價格漲跌依標的市場（`Colors.dir`）
- 缺資料顯示 `—`，不畫假條

### 本機驗證

```bat
.\scripts\go.bat pull cursor/merge-tw-pulse-intel-b5cf
```

Ctrl+F5 → 總覽／法人／籌碼(2330)／法人榜自營商／廣度／盤後／選股。

---

## 修訂紀錄

| 日期 | 說明 |
|------|------|
| 2026-08-07 | 初稿盤點 |
| 2026-08-07 | 一次執行 Phase A→D 並重建 `stock_terminal_v2.html` |
