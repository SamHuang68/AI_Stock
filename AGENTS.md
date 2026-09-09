# Agent 規則

## 模型／計費（優先於預設 Auto）

除非使用者在**本則訊息**明確點名第三方模型，否則**禁用 Other Models**。

- **預設**：Cursor Models only — Composer、Grok；子 agent 一律 `inherit`。
- **禁用（未點名時）**：Claude、GPT、Gemini、Opus、Sonnet，以及任何會打進 Other Models／on-demand 的路由。
- **允許例外**：使用者寫出模型名（例如「用 Claude」「用 GPT-5」）。未指定、Auto、Router 都不算授權。
- Cloud Agent／背景 agent／子 agent／審查員同樣適用；不要為了「比較強」自行升級到第三方。

## ST 一體兩面（本機 ＋ Private Web）

本機 `http://localhost:18432/#pulse` 與 Tailscale `https://evo-t1-st.tailbc3519.ts.net/#pulse` 是同一套 Stock Terminal。

- 有更新必須兩邊 sync 到同一 tip commit。
- 兩邊都確認版面呈現沒問題，才能 `sync_private_web.ps1 -Promote -LayoutVerified`。
- 只修本機、Tailscale 仍舊版＝工作未完成。

## 交付 routine（自己做完再回報）

`git commit`／`push`／合進 tip 是 agent 的工作，不是留給使用者的清單。

- 改完碼：自己 staging（禁止 `data/*.csv`）、commit、push 功能分支、更新 PR，然後才回報。
- 驗證通過或使用者說 deploy：自己把功能分支合進 `TIP_BRANCH` 並 push tip。
- 回報只寫結果（分支、tip HEAD、CI、還缺什麼）。禁止用「請自己 fetch／merge／push」當收尾。
- Private Web：雲端 VM 無法寫入本機 `%LOCALAPPDATA%\StockTerminalPrivateWeb`。git 側仍須合 tip；僅在無法代跑 promote 時，回報「Tailscale 尚未 promote」。
