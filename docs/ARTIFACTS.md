# 大型資料與靜態文件管理

Stock Terminal 刻意把「可重建資料」與「研究文件快照」分開，避免熱路徑（`/pulse`、`/market/snapshot`、啟動腳本）被不必要的大檔拖慢。

## 現況（約 2026-09）

| 路徑 | 約略大小 | 用途 | 建議 |
|------|----------|------|------|
| `data/universe.json` | ~3.1 MB | 全市場代號／名稱對照 | 保留於 repo；**不要**在每次 HTTP 請求讀入記憶體。需要時由 `/universe` 端點或啟動快取載入。 |
| `assets/docs/archify/*.html` | ~4.2 MB（目錄合計） | 互動架構說明（凍結快照） | 按需開啟；不嵌入 `#pulse` 或啟動流程。manifest 見 `docs/architecture/archify-manifest.json`。 |
| `data/*.db` | 視本機回補而定 | 可重建歷史庫 | 多數已在 `.gitignore`；分享包剝除。 |

## Git LFS（可選）

若 `universe.json` 或 Archify HTML 在協作中造成 clone 過慢，可改用 Git LFS 追蹤：

```bash
git lfs track "data/universe.json"
git lfs track "assets/docs/archify/*.html"
```

**注意**：CI 與 Cloud Agent 環境需安裝 `git-lfs` 並在 checkout 後執行 `git lfs pull`。在未啟用 LFS 前，請維持現狀並避免把更多大型 JSON 塞進熱路徑。

## 本機覆寫（不進版控）

| 檔案 | 用途 |
|------|------|
| `data/feature_flags.local.json` | 啟用 Shadow／實驗研究功能（預設關閉） |

範例：

```json
{
  "shadowOvernightIntraday": true,
  "shadowEarlyWarning": true,
  "shadowConsensusAttention": true
}
```

等價環境變數：`ST_ENABLE_SHADOW_RESEARCH=1` 或個別 `ST_SHADOW_*`（見 `/features` 端點）。

## 生成與更新

- **universe**：由 `server/universe.py` 與相關腳本維護；更新後請跑 `unittest` 與 `build_v2.py`，確認 `/universe` 契約未漂移。
- **Archify**：規格變更時同步更新 `docs/architecture/*.json` 與 manifest 雜湊測試（`tests/test_archify_artifacts.py`）。
