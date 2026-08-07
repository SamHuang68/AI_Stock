// ============================================================
// Stock Terminal v5.0 — Viz 共用視覺元件（文字→視覺單一來源）
// ------------------------------------------------------------
// 須在 colors_v3.js 之後載入。台股：漲/買超=紅、跌/賣超=綠。
// window.Viz = { magBar, segBar, scoreMeter, streakChip, limitChip,
//                dualBars, refMeter, heatCell, sparkLine, sparkBars,
//                toneClass, unitYi, unitLots, badge, ensureStyle }
// ============================================================
(function () {
  'use strict';

  function gainColor(v) {
    if (window.Colors && Colors.gain) return Colors.gain(v);
    if (v == null || !isFinite(v) || v === 0) return 'var(--tlo)';
    return v > 0 ? 'var(--red)' : 'var(--green)';
  }
  function qualityColor(v, hi, mid) {
    if (window.Colors && Colors.quality) return Colors.quality(v, hi || 70, mid || 45);
    if (v == null || !isFinite(v)) return 'var(--tlo)';
    if (v >= (hi || 70)) return 'var(--red)';
    if (v >= (mid || 45)) return 'var(--orange)';
    return 'var(--green)';
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function finite(v) { return v != null && isFinite(v); }

  function ensureStyle() {
    if (document.getElementById('vz-style')) return;
    var s = document.createElement('style');
    s.id = 'vz-style';
    s.textContent =
      '.vz-mag{display:flex;align-items:center;gap:4px;min-width:0}' +
      '.vz-mag .vz-lbl{font-size:8px;color:var(--tlo);min-width:24px;flex-shrink:0}' +
      '.vz-mag .vz-track{position:relative;flex:1;height:5px;background:var(--bg3,#1e293b);border-radius:3px;overflow:hidden}' +
      '.vz-mag .vz-zero{position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(148,163,184,.45);z-index:1}' +
      '.vz-mag .vz-fill{position:absolute;top:0;bottom:0;border-radius:2px}' +
      '.vz-mag .vz-val{font-size:9px;font-weight:700;font-variant-numeric:tabular-nums;min-width:44px;text-align:right;flex-shrink:0}' +
      '.vz-mags{display:flex;flex-direction:column;gap:2px;margin-top:3px}' +
      '.vz-seg{display:flex;height:5px;border-radius:3px;overflow:hidden;background:var(--bg3,#1e293b);margin-top:3px}' +
      '.vz-seg > i{display:block;height:100%;min-width:0}' +
      '.vz-seg > i.up{background:var(--red)}' +
      '.vz-seg > i.flat{background:#475569}' +
      '.vz-seg > i.dn{background:var(--green)}' +
      '.vz-meter{height:4px;border-radius:2px;background:var(--bg3,#1e293b);overflow:hidden;margin-top:2px}' +
      '.vz-meter > i{display:block;height:100%;border-radius:2px}' +
      '.vz-dual{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:2px}' +
      '.vz-dual .vz-d{font-size:8px;color:var(--tlo)}' +
      '.vz-dual .vz-d b{display:block;color:var(--thi);font-size:10px;margin:1px 0}' +
      '.vz-chip{display:inline-block;margin:0 3px 0 0;padding:0 5px;border-radius:6px;font-size:8px;font-weight:700;line-height:1.55}' +
      '.vz-chip.buy{background:rgba(239,68,68,.18);color:var(--red)}' +
      '.vz-chip.sell{background:rgba(34,197,94,.18);color:var(--green)}' +
      '.vz-chip.ok{background:rgba(34,197,94,.15);color:var(--green)}' +
      '.vz-chip.warn{background:rgba(251,146,60,.18);color:var(--orange)}' +
      '.vz-chip.err{background:rgba(239,68,68,.18);color:var(--red)}' +
      '.vz-chip.mid{background:rgba(148,163,184,.15);color:var(--tlo)}' +
      '.vz-chip.hot{background:rgba(239,68,68,.2);color:var(--red)}' +
      '.vz-chip.cold{background:rgba(34,197,94,.2);color:var(--green)}' +
      '.vz-chip.lim{background:rgba(251,191,36,.2);color:var(--gold,#fbbf24)}' +
      '.vz-badge{display:inline-flex;align-items:center;gap:3px;padding:0 5px;border-radius:6px;font-size:8px;font-weight:700}' +
      '.vz-badge.ok{background:rgba(34,197,94,.15);color:var(--green)}' +
      '.vz-badge.warn{background:rgba(251,146,60,.18);color:var(--orange)}' +
      '.vz-badge.err{background:rgba(239,68,68,.18);color:var(--red)}' +
      '.vz-badge.mid{background:rgba(148,163,184,.12);color:var(--tlo)}' +
      '.vz-heat{display:inline-block;padding:0 4px;border-radius:2px;font-weight:700;font-variant-numeric:tabular-nums}' +
      '.vz-ref{position:relative;height:5px;border-radius:3px;background:var(--bg3,#1e293b);margin-top:3px;margin-bottom:10px;overflow:visible}' +
      '.vz-ref > i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--cyan),var(--gold))}' +
      '.vz-ref .vz-tick{position:absolute;top:-1px;bottom:-1px;width:1px;background:rgba(248,250,252,.35)}' +
      '.vz-ref .vz-tick-lbl{position:absolute;top:7px;font-size:7px;color:var(--tf,#64748b);transform:translateX(-50%);white-space:nowrap}' +
      '.vz-spark{display:block;width:100%;height:28px;margin-top:2px}' +
      '.vz-sparkbars{display:flex;align-items:flex-end;gap:1px;height:18px;margin-top:2px}' +
      '.vz-sparkbars i{flex:1;min-width:2px;border-radius:1px 1px 0 0;opacity:.9}' +
      '.vz-zone{position:relative;height:7px;border-radius:4px;background:linear-gradient(90deg,#4ade80 0%,#fbbf24 40%,#fb923c 70%,#f87171 100%);margin:3px 0 1px}' +
      '.vz-zone .vz-mark{position:absolute;top:-2px;width:2px;height:11px;background:#fff;border-radius:1px;box-shadow:0 0 0 1px rgba(0,0,0,.4)}' +
      '.vz-rowbar{display:inline-block;height:4px;border-radius:2px;vertical-align:middle;margin-left:4px;max-width:56px}';
    document.head.appendChild(s);
  }

  /** 對零軸左右開的幅度條（買超右紅／賣超左綠） */
  function magBar(v, maxAbs, opts) {
    ensureStyle();
    opts = opts || {};
    if (!finite(v)) {
      return '<div class="vz-mag">' +
        (opts.label ? '<span class="vz-lbl">' + esc(opts.label) + '</span>' : '') +
        '<div class="vz-track"><span class="vz-zero"></span></div>' +
        '<span class="vz-val" style="color:var(--tlo)">—</span></div>';
    }
    var m = Math.max(Math.abs(maxAbs || 0), Math.abs(v), 1e-9);
    var pct = Math.min(50, (Math.abs(v) / m) * 50);
    var col = gainColor(v);
    var fill = v >= 0
      ? '<i class="vz-fill" style="left:50%;width:' + pct.toFixed(1) + '%;background:' + col + '"></i>'
      : '<i class="vz-fill" style="right:50%;width:' + pct.toFixed(1) + '%;background:' + col + '"></i>';
    var txt = opts.fmt ? opts.fmt(v) : (v >= 0 ? '+' : '') + (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : v.toFixed(1));
    return '<div class="vz-mag">' +
      (opts.label ? '<span class="vz-lbl">' + esc(opts.label) + '</span>' : '') +
      '<div class="vz-track"><span class="vz-zero"></span>' + fill + '</div>' +
      '<span class="vz-val" style="color:' + col + '">' + txt + '</span></div>';
  }

  /** 多列法人幅度條 */
  function magBars(items) {
    ensureStyle();
    items = items || [];
    var maxAbs = 0;
    items.forEach(function (it) {
      if (finite(it.v)) maxAbs = Math.max(maxAbs, Math.abs(it.v));
    });
    if (!maxAbs) maxAbs = 1;
    return '<div class="vz-mags">' + items.map(function (it) {
      return magBar(it.v, maxAbs, { label: it.label, fmt: it.fmt });
    }).join('') + '</div>';
  }

  /** 上漲／平／下跌分段條 */
  function segBar(up, flat, dn) {
    ensureStyle();
    up = +up || 0; flat = +flat || 0; dn = +dn || 0;
    var sum = up + flat + dn;
    if (!sum) return '<div class="vz-seg"><i class="flat" style="width:100%;opacity:.35"></i></div>';
    return '<div class="vz-seg">' +
      '<i class="up" style="width:' + (100 * up / sum).toFixed(2) + '%"></i>' +
      '<i class="flat" style="width:' + (100 * flat / sum).toFixed(2) + '%"></i>' +
      '<i class="dn" style="width:' + (100 * dn / sum).toFixed(2) + '%"></i></div>';
  }

  /** 0–100 分數細條 */
  function scoreMeter(score, opts) {
    ensureStyle();
    opts = opts || {};
    if (!finite(score)) return '<div class="vz-meter"><i style="width:0"></i></div>';
    var w = Math.max(0, Math.min(100, score));
    var col = opts.color || qualityColor(score, opts.hi, opts.mid);
    return '<div class="vz-meter"><i style="width:' + w.toFixed(1) + '%;background:' + col + '"></i></div>';
  }

  /** 連續買賣超 pill */
  function streakChip(n, who) {
    ensureStyle();
    if (!n) return '';
    var buy = n > 0;
    return '<span class="vz-chip ' + (buy ? 'buy' : 'sell') + '">' +
      esc(who || '') + '連' + (buy ? '買' : '賣') + Math.abs(n) + '日</span>';
  }

  /** 漲停／跌停 chip */
  function limitChip(chgPct) {
    ensureStyle();
    if (!finite(chgPct)) return '';
    if (chgPct >= 9.5) return '<span class="vz-chip lim">漲停</span>';
    if (chgPct <= -9.5) return '<span class="vz-chip lim">跌停</span>';
    return '';
  }

  /** 通用狀態 chip */
  function chip(text, kind) {
    ensureStyle();
    if (!text) return '';
    return '<span class="vz-chip ' + esc(kind || 'mid') + '">' + esc(text) + '</span>';
  }

  function badge(text, kind) {
    ensureStyle();
    return '<span class="vz-badge ' + esc(kind || 'mid') + '">' + esc(text) + '</span>';
  }

  /** 融資 vs 融券雙條（單位張） */
  function dualBars(aLabel, aVal, bLabel, bVal, unit) {
    ensureStyle();
    unit = unit || '張';
    var max = Math.max(finite(aVal) ? aVal : 0, finite(bVal) ? bVal : 0, 1);
    function cell(lab, v, col) {
      var w = finite(v) ? Math.round(100 * v / max) : 0;
      var t = finite(v) ? Math.round(v).toLocaleString() + ' ' + unit : '—';
      return '<div class="vz-d">' + esc(lab) + '<b style="color:' + (col || 'var(--thi)') + '">' + t + '</b>' +
        '<div class="vz-meter"><i style="width:' + w + '%;background:' + (col || 'var(--cyan)') + '"></i></div></div>';
    }
    return '<div class="vz-dual">' + cell(aLabel, aVal, 'var(--gold)') + cell(bLabel, bVal, 'var(--cyan)') + '</div>';
  }

  /** 券資比／當沖比分區 meter */
  function ratioMeter(pct, warnAt, dangerAt) {
    ensureStyle();
    if (!finite(pct)) return '';
    warnAt = warnAt != null ? warnAt : 10;
    dangerAt = dangerAt != null ? dangerAt : 30;
    var col = pct > dangerAt ? 'var(--red)' : pct > warnAt ? 'var(--orange)' : 'var(--green)';
    var w = Math.min(100, pct);
    return '<div class="vz-meter"><i style="width:' + w.toFixed(1) + '%;background:' + col + '"></i></div>';
  }

  /** 成交額對參考刻度（億） */
  function refMeter(valueYi, ticks) {
    ensureStyle();
    ticks = ticks || [8000, 12000];
    if (!finite(valueYi)) return '';
    var max = Math.max.apply(null, ticks.concat([valueYi, 1]));
    var w = Math.min(100, 100 * valueYi / max);
    var marks = ticks.map(function (t) {
      var left = (100 * t / max).toFixed(1);
      return '<span class="vz-tick" style="left:' + left + '%"></span>' +
        '<span class="vz-tick-lbl" style="left:' + left + '%">' + (t >= 10000 ? (t / 10000).toFixed(1) + '兆' : t + '億') + '</span>';
    }).join('');
    return '<div class="vz-ref"><i style="width:' + w.toFixed(1) + '%"></i>' + marks + '</div>';
  }

  /** 融資維持率水位（zones 由高到低或低到高皆可；value 越高越安全時用綠→紅反轉） */
  function zoneMark(value, min, max) {
    ensureStyle();
    if (!finite(value)) return '';
    min = min != null ? min : 120;
    max = max != null ? max : 200;
    var p = Math.max(0, Math.min(100, 100 * (value - min) / (max - min || 1)));
    return '<div class="vz-zone"><span class="vz-mark" style="left:' + p.toFixed(1) + '%"></span></div>';
  }

  /** 漲跌熱格 */
  function heatCell(text, v, sym) {
    ensureStyle();
    var col = 'var(--tlo)';
    if (window.Colors && Colors.dir) col = Colors.dir(sym || '2330', v);
    else col = gainColor(v);
    var bg = 'transparent';
    if (finite(v)) {
      var a = Math.min(0.35, Math.abs(v) / 10 * 0.35);
      bg = v > 0 ? 'rgba(239,68,68,' + a.toFixed(2) + ')' : 'rgba(34,197,94,' + a.toFixed(2) + ')';
      if (sym && window.Colors && !Colors.isTW(sym)) {
        bg = v > 0 ? 'rgba(34,197,94,' + a.toFixed(2) + ')' : 'rgba(239,68,68,' + a.toFixed(2) + ')';
      }
    }
    return '<span class="vz-heat" style="color:' + col + ';background:' + bg + '">' + esc(text) + '</span>';
  }

  /** 列內相對幅度小條（一律向右，顏色表方向） */
  function rowBar(v, maxAbs) {
    ensureStyle();
    if (!finite(v) || !maxAbs) return '';
    var w = Math.max(4, Math.round(100 * Math.abs(v) / maxAbs));
    return '<span class="vz-rowbar" style="width:' + w + '%;background:' + gainColor(v) + '"></span>';
  }

  /** SVG 折線 spark */
  function sparkLine(vals, opts) {
    ensureStyle();
    opts = opts || {};
    var arr = (vals || []).filter(finite);
    if (arr.length < 2) {
      return opts.empty || '<div style="font-size:9px;color:var(--tlo);padding:4px 0">序列不足</div>';
    }
    var lo = Math.min.apply(null, arr), hi = Math.max.apply(null, arr);
    var span = (hi - lo) || 1;
    var w = opts.w || 240, h = opts.h || 36, pad = 2;
    var pts = arr.map(function (c, i) {
      var x = pad + (i / (arr.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (c - lo) / span) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    var up = arr[arr.length - 1] >= arr[0];
    var stroke = opts.color || (up ? 'var(--red)' : 'var(--green)');
    return '<svg class="vz-spark" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polyline fill="none" stroke="' + stroke + '" stroke-width="2" points="' + pts + '"/></svg>';
  }

  /** 正負柱狀 spark */
  function sparkBars(vals) {
    ensureStyle();
    var arr = vals || [];
    if (!arr.length) return '';
    var maxAbs = 0;
    arr.forEach(function (v) { if (finite(v)) maxAbs = Math.max(maxAbs, Math.abs(v)); });
    if (!maxAbs) maxAbs = 1;
    return '<div class="vz-sparkbars">' + arr.map(function (v) {
      if (!finite(v)) return '<i style="height:2px;background:#334155"></i>';
      var h = Math.max(2, Math.round(100 * Math.abs(v) / maxAbs));
      return '<i style="height:' + h + '%;background:' + gainColor(v) + '"></i>';
    }).join('') + '</div>';
  }

  function toneClass(v) {
    if (!finite(v) || v === 0) return '';
    return v > 0 ? 'up' : 'dn';
  }

  function unitYi(v) {
    if (!finite(v)) return '—';
    var yi = Math.abs(v) >= 1e6 ? v / 1e8 : v; // 若已是億則原樣
    // 呼叫端通常已是億；此 helper 假設輸入為元時 /1e8，否則用 fmtYi
    return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + ' 億';
  }

  function unitLots(shares) {
    if (!finite(shares)) return '—';
    return Math.round(shares / 1000).toLocaleString() + ' 張';
  }

  function fmtYiFromYuan(yuan) {
    if (!finite(yuan)) return '—';
    // |v|>1e5 視為元 → 億；否則已是億
    var yi = Math.abs(yuan) > 1e5 ? yuan / 1e8 : yuan;
    return (yi >= 0 ? '+' : '') + yi.toFixed(1) + ' 億';
  }

  window.Viz = {
    ensureStyle: ensureStyle,
    magBar: magBar,
    magBars: magBars,
    segBar: segBar,
    scoreMeter: scoreMeter,
    streakChip: streakChip,
    limitChip: limitChip,
    chip: chip,
    badge: badge,
    dualBars: dualBars,
    ratioMeter: ratioMeter,
    refMeter: refMeter,
    zoneMark: zoneMark,
    heatCell: heatCell,
    rowBar: rowBar,
    sparkLine: sparkLine,
    sparkBars: sparkBars,
    toneClass: toneClass,
    unitYi: unitYi,
    unitLots: unitLots,
    fmtYiFromYuan: fmtYiFromYuan,
    gainColor: gainColor,
    qualityColor: qualityColor
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureStyle);
  } else {
    ensureStyle();
  }
})();
