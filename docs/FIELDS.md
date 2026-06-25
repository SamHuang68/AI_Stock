# 欄位（blank）型別定義與安全標準

單一真理來源：`src/core/fields_v3.js`（最先載入，提供 `window.Field` 與全域防護）。
任何新增/修改輸入欄位都必須遵循本文件。核心原則：**欄位角色嚴格分離，絕不功能混用。**

## 四種欄位角色

| 角色 | 用途 | 標準寫法 | 禁止 |
|---|---|---|---|
| **數值 NUMBER** | 純數字（進場價、股數、停利停損、門檻、%、天數） | `type="text"` + `inputmode="decimal\|numeric"` + `autocomplete="off"`；送出時才 `parseFloat`。可用 `Field.numAttrs()` | 不可 `type="number"`（滾輪偷改值/上下鍵改值/微調鈕）；不可掛搜尋或送出行為 |
| **帶入 PREFILL** | 點選後自動帶入既有資料（如 `watch-sym` 預填目前代號、倉位自動帶入選到的標的） | 純文字 `type="text"`；值由程式或使用者填入 | 不連後台查詢；不可被當搜尋欄 |
| **搜尋 SEARCH** | 唯一會連後台查詢/載入的欄位 | 明確觸發（按 `/`、Ctrl+K、Enter） | 不可由「打字即觸發」全域攔截（已移除） |
| **文字 TEXT** | 自由文字/筆記 | `<textarea>` | — |

只有 **搜尋** 欄位可觸發載入/查詢：`hk-qs-in`（快搜）、`cmdp-input`（命令盤）、`sp-input`（價差公式）、`syminput`（主代號框）。其餘任何欄位都不得觸發。

## 三條全域鐵則（由 `fields_v3.js` 強制）

1. **重繪不奪焦點**：會被定時器/事件重繪的面板，一律走守門入口 `Field.renderGuarded(el, htmlFn, attachFn)`（或等效的 `renderPositionPanel` / `renderWatchPanel`）。使用者正在欄位打字時（`Field.editing()` 為真）就**完全不動 DOM**，資料仍可在背景更新，待失焦後下次才反映。`Field.editing()` 只認文字/數值輸入與 textarea/contenteditable，**不含 select**（故下拉變更仍正常重繪）。
2. **滾輪不改值**：全域攔截，任何聚焦中的 `type="number"` 滑鼠滾輪滑過不得改值。一次保護全專案所有舊有 `type=number`。
3. **不混用**：數值/帶入/文字欄位永不觸發搜尋或任何全域行為。全域「打字即搜尋」已移除，鍵盤焦點在欄位時不被任何熱鍵搶走。

## 稽核結果（全專案）

**有「焦點被定時重繪奪走」風險者 — 已修：**

| 面板 | 欄位 | 修法 |
|---|---|---|
| 倉位 POS（右panel） | `pos-entry/shares/target/stop`(數值)、`pos-notes`(文字)、`pos-unit`(select) | 四條重繪路徑（renderRpanel wrapper、symLoaded、pollSymChange、wl_live 輪詢）全收斂到守門入口 `renderPositionPanel`；數值欄改純文字；移除欄位上的 Enter→送出 |
| 自選 WATCH（右panel） | `watch-sym`(帶入)、`watch-notes`(文字)、`watch-preset-price/price2`(數值)、`watch-param-*` | 同款架構同款修：守門入口 `renderWatchPanel` + wrapper 的 origRender 路徑加 `Field.editing` 守門；數值欄改純文字 |
| `setTab`（切分頁） | — | 切頁屬明確操作：先讓 rpanel 內聚焦欄位失焦，確保切頁必定重繪 |

**無此風險者（symLoaded 只重畫圖表/數據或模態開啟時才渲染）：** `polish_v3`(總體列)、`volume_profile_v3`/`drawtools_v3`(圖層)、`chip_v3`(stats 數據)、`live_v2`/`aftermarket_v3`(報價)、`pro_v2`(通知)、`plan_v3`(只畫價位線)。

**`type=number` 欄位（模態，開啟時渲染一次，無焦點被奪風險）— 由全域滾輪防護兜底，建議逐步遷移到 `Field.numAttrs()`：** `alert_push`(ap-poll/em-port/r-price)、`screener3`(s3-*)、`wizard`(wz-*)、`plan_v3`(buyZone 等)、`plan_position`(ppc-*)、`strategy_builder`(sb-*)。

## 新增欄位檢查清單

- 數值欄？→ 用 `Field.numAttrs()`，不要 `type="number"`。
- 此面板會被定時器/symLoaded 重繪？→ 重繪改走 `Field.renderGuarded`／對應守門入口，不要自己 `el.innerHTML = render()`。
- 此欄位該觸發查詢嗎？→ 只有搜尋角色可以；其餘一律不可。
