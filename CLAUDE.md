# Claude Code

開工前先完整閱讀 @AGENTS.md ：其中的位置、環境與操作規則優先於任何記憶中的路徑假設，並指向 `AI-Workspace` 的共用規則（先讀 `shared-ai-memory` 的 `_rules/0005` 與 `sessions/handoff-current.md`）。

- 雲端工作階段看不到使用者的電腦：本機的更新、啟動與部署指令，一律先請使用者做唯讀檢查並貼回結果。共用規則在私有 repo `SamHuang68/shared-ai-memory`，用 `add_repo` 唯讀掛上讀取，並先核對最新提交日期（遠端可能落後本機，見 `AGENTS.md`）。
- 不要在未登記的資料夾啟動 Stock Terminal，不要自行發布正式版。
- 程式進版要同步補 `docs/revision.md`（基底與合併 SHA、原因、驗證、發布狀態）。
