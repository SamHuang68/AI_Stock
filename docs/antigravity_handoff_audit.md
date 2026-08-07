# Antigravity 接手稽核（2026-08-07）

## 結論
開啟總覽／Dashboard 卻看到**舊圖表介面**的根因：

`src/ui/shell_v5.js` 在 Antigravity commit `0e53f81` 被寫壞：

```js
var V  var ROUTES = [
```

瀏覽器 SyntaxError → `ShellV5` 永不建立 → `#shell-views`／`#view-pulse` 不存在 → 舊 `#body` 圖表區一直顯示。

後續 `53aec87`～`78b82f7`（預設 pulse、no-cache、go.bat `#pulse`、emitRoute retry）在 shell 無法解析時全部無效。

## Antigravity 有用部分（已保留／合併）
- 預設 route → pulse；URL hash `#pulse`
- HTML／JS no-cache；`/` 與 `stock_terminal.html` 導向 v2
- go.bat 開 `#pulse`
- TW Pulse 寬側欄 branding
- pulse 10 卡視覺改版（已清掉假資料 fallback）

## 本次接手修復
1. 還原可解析 `shell_v5.js`，合併 branding／hash／retry／隱藏 topbar
2. `pulse_v5.js` 移除灌假分數／假漲停／假全球／假自選
3. server 對 `.js`/`.css` 亦送 no-cache

## 本地驗證
```
node --check src/ui/shell_v5.js
python3 build_v2.py
# Ctrl+F5 → http://localhost:18432/#pulse
# Console 應見 [shell-v5] Stock Terminal 5.0 · route=pulse
```
