# 上游來源

- 來源：`https://github.com/pbakaus/impeccable`，commit `ffeda44b00b1e39bd901621dcd3a7e44ba184ce1`（2026-10-07），技能 4.5.0，引擎 0.1.11。取得日期 2026-10-08。
- 授權：Apache-2.0（同目錄 `LICENSE`、`NOTICE.md`）。
- 安裝範圍：只裝在 NVM Hub、Stock Terminal 與 Arcade 專案（後兩者於 2026-10-08 補裝），沒有全域安裝。內容包含 `.claude/skills/impeccable` 和 `.claude/agents/impeccable-*.md`（4 個子代理人）。
- 依 Sam 2026-10-08 的決定：允許下載引擎執行檔，快取在 `~/.impeccable/bin/0.1.11/impeccable.exe`；不開自動檢查 hooks（沒有加 `.claude/settings.json`），需要時再用 `/impeccable hooks on`。
- 本地修改：無。三個專案於 2026-10-08 本機提交（未推送），是否提交另外決定。
- 移除方式：刪掉上述兩處專案內的檔案，以及 `~/.impeccable`。
