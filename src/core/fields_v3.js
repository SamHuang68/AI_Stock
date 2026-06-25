// ============================================================
// Stock Terminal — 欄位(blank)型別定義與全域安全防護  [單一真理來源]
// ------------------------------------------------------------
// 目的:把「輸入欄位」做成有明確角色、不會功能混用、不會被重繪奪走焦點、
//       不會被滾輪/熱鍵偷改的單一標準。任何模組新增欄位都應遵循這裡。
//
// ── 欄位角色(嚴格分離,絕不混用) ──────────────────────────
//   數值 NUMBER : 純數值輸入(進場價/股數/停利停損/門檻)。
//                 標準:type="text" + inputmode + autocomplete="off"。
//                 不可用 type="number"(滾輪會偷改值、上下鍵改值、微調鈕)。
//                 不可在欄位上掛搜尋/送出等其他行為。送出時才 parseFloat。
//   帶入 PREFILL : 點選後自動帶入既有資料的欄位(如 watch-sym 預填目前代號)。
//                 純文字,值由程式或使用者填入,不連後台查詢。
//   搜尋 SEARCH  : 唯一會連後台資料查詢的欄位(快搜 hk-qs / 命令盤 cmdp /
//                 公式 sp-input)。只有這類才可觸發載入/查詢。
//   文字 TEXT    : 自由文字/筆記(notes/outlook)。textarea,純輸入。
//
// ── 鐵則 ──────────────────────────────────────────────────
//   1. 數值/帶入/文字欄位「永遠不」觸發搜尋或任何全域行為。
//   2. 會被定時器/事件重繪的面板,重繪一律走「守門入口」:使用者正在某欄位
//      輸入時就跳過重繪(否則 innerHTML 重建會清空欄位、奪走焦點)。
//   3. 數值欄位一律 type="text"+inputmode,不用 type="number"。
//      (舊有 type="number" 由本檔的全域滾輪防護兜底,避免滾輪偷改值。)
// ============================================================
(function () {
  'use strict';

  const Field = {};

  // 角色常數(供文件/標註用)
  Field.ROLE = { NUMBER: 'number', PREFILL: 'prefill', SEARCH: 'search', TEXT: 'text' };

  // 新增數值欄位的安全屬性(取代 type="number")。
  //   用法:`<input id="x" ${Field.numAttrs()} placeholder="價">`
  Field.numAttrs = function (mode) {
    return `type="text" inputmode="${mode || 'decimal'}" autocomplete="off"`;
  };

  // 唯一的「使用者正在輸入中」判斷。
  //   只認「會承載鍵入文字」的元件:INPUT(文字/數值類)、TEXTAREA、contenteditable。
  //   SELECT / checkbox / radio / range / file / button 不算(它們重繪不會丟失打字),
  //   這讓 select 變更後仍可正常重繪,只有真的在打字時才擋重繪。
  Field.editing = function (scope) {
    const ae = document.activeElement;
    if (!ae) return false;
    const tag = (ae.tagName || '').toUpperCase();
    let isTextEntry = false;
    if (tag === 'TEXTAREA' || ae.isContentEditable) isTextEntry = true;
    else if (tag === 'INPUT') {
      const t = (ae.getAttribute('type') || 'text').toLowerCase();
      isTextEntry = !/^(checkbox|radio|button|submit|reset|range|file|color|image)$/.test(t);
    }
    if (!isTextEntry) return false;
    if (scope && scope.nodeType === 1 && !scope.contains(ae)) return false;
    return true;
  };

  // 守門渲染:所有「會被定時器/事件重繪」的面板都應透過它重繪。
  //   el      : 容器元素
  //   htmlFn  : () => string  產生 innerHTML
  //   attachFn: () => void    重新綁定事件(可省略)
  // 使用者正在 el 內任一輸入欄位打字時 → 完全不動 DOM(資料可在背景照常更新)。
  Field.renderGuarded = function (el, htmlFn, attachFn) {
    if (!el) return false;
    if (Field.editing(el)) return false;        // 編輯中:不重繪
    try {
      el.innerHTML = htmlFn();
      if (typeof attachFn === 'function') attachFn();
      return true;
    } catch (err) {
      console.error('[Field] renderGuarded threw:', err);
      return false;
    }
  };

  // ── 全域滾輪防護 ──────────────────────────────────────────
  // 任何聚焦中的 type="number" 欄位,滑鼠滾輪滑過不得改值(資料完整性)。
  // 一次保護全專案所有舊有 type=number 欄位,不必逐檔改。
  document.addEventListener('wheel', function (e) {
    const t = e.target;
    if (t && t.tagName === 'INPUT' &&
        (t.getAttribute('type') || '').toLowerCase() === 'number' &&
        document.activeElement === t) {
      e.preventDefault();   // 擋掉「滾輪改值」,但保留焦點與輸入內容
    }
  }, { passive: false });

  window.Field = Field;
  console.log('[fields] 欄位型別定義就緒 — 全域滾輪防護已啟用,守門渲染入口 Field.renderGuarded');
})();
