// ============================================================
// Stock Terminal — 顏色管理(單一真理來源)
// ------------------------------------------------------------
// 全 app 的紅綠/警示顏色一律走這裡,杜絕「每個模組各自寫一套紅綠」造成的
// 反覆 bug(漲跌紅綠分不清市場、基本面用西式綠=好跟股價打架…)。
//
// ── 顏色語意表(semantic → color) ───────────────────────────
//   方向性 DIRECTIONAL(漲跌、成長 YoY/MoM):
//       台股(數字代號 / ^TW 指數):漲/正 = 紅、跌/負 = 綠(平 = 中性)
//       美股/其他:                 漲/正 = 綠、跌/負 = 紅
//       → 依「標的本身」判市場,不受 TW/US 市場鈕影響。
//   水準型 LEVEL(三率、P/E、P/B、殖利率…):不用紅綠(會跟股價打架),
//       超出合理門檻 = 琥珀(注意/警示)、其餘 = 中性。
//   狀態 STATE:盤中=綠、盤前盤後=琥珀、休市=灰。
// ============================================================
(function () {
  'use strict';

  // 基礎色票(對應 styles.css 的 CSS 變數;canvas/K棒需 hex 故另存)
  var PALETTE = {
    red:     'var(--red)',     // 台股漲 / 美股跌 / 警示
    green:   'var(--green)',   // 台股跌 / 美股漲
    amber:   'var(--orange)',  // 水準型注意 / 盤前盤後
    neutral: 'var(--thi)',     // 中性(亮)
    dim:     'var(--tlo)',     // 中性(暗)/ 無資料 / 平盤
  };
  var HEX = { red: '#F87171', green: '#4ADE80', amber: '#FB923C', neutral: '#F1F5FA', dim: '#5A6A82' };

  function isTW(sym) {
    // 台股現貨、指數，以及本機台股特例都必須走紅漲綠跌。
    // __TXF__ 若漏判成美股，圖表／即時列會把跌幅錯畫成紅色。
    var s = String(sym || '').trim().toUpperCase();
    if (s === '^N225' || (/^\d{4}\.T$/.test(s) && !/\.TW(O)?$/.test(s))) return false;
    return /^\d/.test(s) || /^\^TW/.test(s) ||
      s === '__TXF__' || s === 'TXF' || s === 'TX' || s === 'MXF' ||
      s === '__MARGIN_RATIO__' || s === '__MARGIN__' ||
      /^__TW_/.test(s) || /^__HOLDERS_/.test(s);
  }

  function isJP(sym) {
    var s = String(sym || '').trim().toUpperCase();
    return s === '^N225' || (/^\d{4}\.T$/.test(s) && !/\.TW(O)?$/.test(s));
  }

  function isRedUp(sym) { return isTW(sym) || isJP(sym); }

  var Colors = {
    PALETTE: PALETTE,
    HEX: HEX,
    isTW: isTW,
    isJP: isJP,
    isRedUp: isRedUp,

    // 方向性顏色(漲跌/成長):v>0 漲/正,v<0 跌/負,v==0/缺 平盤中性。
    // 回傳 CSS 字串(供 style.color 用)。
    dir: function (sym, v) {
      if (v == null || !isFinite(v) || v === 0) return PALETTE.dim;
      var tw = isRedUp(sym);
      var up = v > 0;
      return up ? (tw ? PALETTE.red : PALETTE.green) : (tw ? PALETTE.green : PALETTE.red);
    },
    // 成長(基本面方向性)= 同 dir
    growth: function (sym, v) { return this.dir(sym, v); },

    // 依「紅漲市場旗標」上色(給總體列等已知各標的慣例的場合用)。
    //   redUp=true → 漲紅跌綠(台股/東亞);redUp=false → 漲綠跌紅(美股/商品)。
    dirRU: function (redUp, v) {
      if (v == null || !isFinite(v) || v === 0) return PALETTE.dim;
      var up = v > 0;
      return up ? (redUp ? PALETTE.red : PALETTE.green) : (redUp ? PALETTE.green : PALETTE.red);
    },

    // K 棒/成交量 上下色(canvas 需 hex)。回傳 {up, down}。
    candle: function (sym) {
      var tw = isRedUp(sym);
      return tw ? { up: HEX.red, down: HEX.green } : { up: HEX.green, down: HEX.red };
    },

    // 台股語意「賺/買超/偏多 = 紅」:正向 → 紅、負向 → 綠、零/缺 → 中性。
    // 與市場無關(永遠台股慣例);用於盈虧 P&L、法人買賣超、型態多空等「方向性的好壞」。
    gain: function (v) {
      if (v == null || !isFinite(v) || v === 0) return PALETTE.dim;
      return v > 0 ? PALETTE.red : PALETTE.green;
    },

    // 品質判定(體質評分/勝率等):台股「好=紅」。v>=hi → 紅(好)、v>=mid → 琥珀(中)、其餘 → 綠(差)。
    quality: function (v, hi, mid) {
      if (v == null || !isFinite(v)) return PALETTE.dim;
      if (v >= hi) return PALETTE.red;
      if (v >= mid) return PALETTE.amber;
      return PALETTE.green;
    },

    // 水準型:超出門檻 → 琥珀(注意),其餘中性。opts:{hi, lo}
    warn: function (v, opts) {
      opts = opts || {};
      if (v == null || !isFinite(v)) return PALETTE.dim;
      if ((opts.hi != null && v > opts.hi) || (opts.lo != null && v < opts.lo)) return PALETTE.amber;
      return PALETTE.neutral;
    },

    // 市場狀態色:'REGULAR'盤中綠 / 'PRE'|'POST'琥珀 / 'CLOSED'灰
    state: function (st) {
      if (st === 'REGULAR') return PALETTE.green;
      if (st === 'PRE' || st === 'POST') return PALETTE.amber;
      return PALETTE.dim;
    },
  };

  window.Colors = Colors;
  console.log('[colors] 顏色管理表就緒 — Colors.dir/growth/candle/warn/state(單一真理來源)');
})();
