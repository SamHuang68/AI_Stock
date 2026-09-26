/* ============================================================================
 * chainmom_v3.js — 供應鏈「5/20/60 日動能」檢視（畫在 🔗 供應鏈 視窗內）
 * ----------------------------------------------------------------------------
 * 用本機 DB 算台灣 AI 供應鏈每一段的 5/20/60 日動能,並抓出「資金正流入哪一段」
 * (5 日日均動能 > 20 日日均動能 = 加速/流入)。沿用 supplychain_v3 的 SC_CHAINS。
 * 原獨立「鏈動能」視窗已併入供應鏈視窗（同一組鏈段，今日漲跌／多時框動能切換）。
 * 顏色:台股紅漲綠跌(動能即漲跌,>0 紅、<0 綠、平無色)。
 * ========================================================================== */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }
  function momCol(v) { return v == null ? '#94a3b8' : (v > 0 ? '#ef4444' : v < 0 ? '#22c55e' : '#94a3b8'); }
  function fmt(v) { return v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }

  function injectStyle() {
    if (document.getElementById('cm-style')) return;
    var s = document.createElement('style'); s.id = 'cm-style';
    s.textContent =
      '.cm-view .sub{font-size:10px;color:#64748b;margin-bottom:10px}' +
      '.cm-share{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin:0 0 6px}' +
      '.cm-sum{background:#16213a;border:1px solid #28324d;border-radius:8px;padding:8px 10px;margin-bottom:12px;line-height:1.7}' +
      '.cm-view table{width:100%;border-collapse:collapse}' +
      '.cm-view th,.cm-view td{padding:5px 6px;border-bottom:1px solid #1e293b;text-align:right;font-family:monospace}' +
      '.cm-view th:first-child,.cm-view td:first-child{text-align:left;font-family:inherit}' +
      '.cm-flow{font-size:10px;padding:1px 6px;border-radius:10px}' +
      '.cm-in{background:rgba(239,68,68,.15);color:#fca5a5}.cm-out{background:rgba(34,197,94,.12);color:#86efac}' +
      '.cm-ld{font-size:10px;color:#94a3b8;margin-top:2px}' +
      '.cm-h{font-weight:700;margin:14px 0 6px;font-size:12px;color:#cbd5e1;border-left:3px solid #F5C518;padding-left:7px}' +
      '.cm-rot{display:flex;flex-wrap:wrap;align-items:center;gap:4px;background:#16213a;border:1px solid #28324d;border-radius:8px;padding:8px 10px}' +
      '.cm-rot-chip{font-size:11px;white-space:nowrap}.cm-rot-chip .wk{color:#64748b;margin-right:4px;font-size:9px}' +
      '.cm-rot-arr{color:#475569;margin:0 2px}' +
      '.cm-node{border:1px solid #1e293b;border-left:4px solid #475569;border-radius:6px;padding:7px 10px;background:#0d1526}' +
      '.cm-node.cm-empty{color:#64748b;font-size:11px}' +
      '.cm-nm{font-weight:700;font-size:12px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}' +
      '.cm-mom{display:flex;gap:14px;font-size:11px;margin-top:3px}.cm-mom b{font-family:monospace}' +
      '.cm-arrow{text-align:center;color:#475569;font-size:11px;line-height:1;margin:2px 0}';
    document.head.appendChild(s);
  }

  function stagesFromChain() {
    var ch = (typeof window !== 'undefined' && window.SC_CHAINS && window.SC_CHAINS.TW) || null;
    if (!ch) return null;
    return ch.map(function (g) { return { stage: g.stage, codes: g.stocks.map(function (s) { return s[0]; }) }; });
  }

  function flowNode(r) {
    if (!r.n) return '<div class="cm-node cm-empty">' + esc(r.stage) + ' · 無 DB 資料</div>';
    var V = window.Viz;
    var flow = r.accel == null ? '' : (r.accel > 0.05 ? '<span class="cm-flow cm-in">▲資金流入</span>' : r.accel < -0.05 ? '<span class="cm-flow cm-out">▼退潮</span>' : '');
    var ld = (r.leaders || []).map(function (l) { return esc(l.name) + ' ' + fmt(l.ret20); }).join('、');
    var spark = V ? V.sparkBars([r.mom5, r.mom20, r.mom60]) : '';
    return '<div class="cm-node" style="border-left-color:' + momCol(r.mom20) + '">' +
      '<div class="cm-nm">' + esc(r.stage) + ' ' + flow + '</div>' +
      '<div class="cm-mom"><span>5日 <b style="color:' + momCol(r.mom5) + '">' + fmt(r.mom5) + '</b></span>' +
      '<span>20日 <b style="color:' + momCol(r.mom20) + '">' + fmt(r.mom20) + '</b></span>' +
      '<span>60日 <b style="color:' + momCol(r.mom60) + '">' + fmt(r.mom60) + '</b></span></div>' +
      spark +
      (ld ? '<div class="cm-ld">領漲:' + ld + '</div>' : '') + '</div>';
  }

  function rotationPath(rot) {
    return '<div class="cm-rot">' + rot.map(function (x, i) {
      return (i ? '<span class="cm-rot-arr">→</span>' : '') +
        '<span class="cm-rot-chip"><span class="wk">' + esc(x.week) + '</span>' +
        (x.stage ? esc(x.stage) : '—') +
        (x.ret != null ? ' <b style="color:' + momCol(x.ret) + '">' + fmt(x.ret) + '</b>' : '') + '</span>';
    }).join('') + '</div>';
  }

  var _lastD = null;
  // 把供應鏈輪動結果格式化成純文字(寄送用)
  function chainText(d) {
    if (!d || !d.stages) return '';
    var rows = d.stages, lines = ['🔄 供應鏈輪動 · 台灣 AI 供應鏈', new Date().toLocaleString('zh-TW'), ''];
    var withData = rows.filter(function (r) { return r.n; });
    var strongest = withData.slice().sort(function (a, b) { return (b.mom20 || -999) - (a.mom20 || -999); })[0];
    if (strongest) lines.push('🏆 20日最強段:' + strongest.stage + ' ' + fmt(strongest.mom20));
    if (d.rotation && d.rotation.length) lines.push('近8週輪動:' + d.rotation.map(function (x) { return x.week + ' ' + (x.stage || '—'); }).join(' → '));
    lines.push(''); lines.push('各段動能(5/20/60日):');
    rows.forEach(function (r) {
      if (!r.n) { lines.push('  ' + r.stage + ' · 無DB資料'); return; }
      var ld = (r.leaders || []).map(function (l) { return l.name + ' ' + fmt(l.ret20); }).join('、');
      lines.push('  ' + r.stage + '  ' + fmt(r.mom5) + ' / ' + fmt(r.mom20) + ' / ' + fmt(r.mom60) + (ld ? '  領漲:' + ld : ''));
    });
    return lines.join('\n');
  }
  function render(d) {
    _lastD = d;
    var rows = d.stages || [];
    rows.forEach(function (r) {
      r.accel = (r.mom5 != null && r.mom20 != null) ? (r.mom5 / 5 - r.mom20 / 20) : null;
    });
    var withData = rows.filter(function (r) { return r.n; });
    var strongest = withData.slice().sort(function (a, b) { return (b.mom20 || -999) - (a.mom20 || -999); })[0];
    var inflow = withData.filter(function (r) { return r.accel != null && r.accel > 0.05; })
      .sort(function (a, b) { return b.accel - a.accel; });

    var h = '<div class="cm-sum">';
    h += '🏆 20 日最強段:<b style="color:' + momCol(strongest && strongest.mom20) + '">' + (strongest ? esc(strongest.stage) + ' ' + fmt(strongest.mom20) : '—') + '</b><br>';
    h += '💰 資金流入中(近 5 日加速):' + (inflow.length ? inflow.map(function (r) { return '<b style="color:#fca5a5">' + esc(r.stage) + '</b>'; }).join(' → ') : '無明顯加速段');
    h += '</div>';

    if (d.rotation && d.rotation.length) {
      h += '<div class="cm-h">近 8 週輪動軌跡（各週領漲段）</div>' + rotationPath(d.rotation);
    }

    h += '<div class="cm-h">供應鏈流向圖（上游→下游 · 框色＝20日動能）</div>';
    h += rows.map(flowNode).join('<div class="cm-arrow">▼</div>');

    h += '<div class="sub" style="margin-top:8px">動能＝該段成分股期間報酬平均(本機 DB 日線)。框左色與數字:台股紅漲綠跌。「資金流入」＝ 5 日日均動能 > 20 日日均動能。輪動軌跡＝每週各段平均報酬最高者(資金輪到哪一段)。</div>';
    return h;
  }

  /** 畫進供應鏈視窗的內容區（host），由 supplychain_v3 的「5/20/60 日動能」切換呼叫；
   *  isCurrent() 回 false 表示載入期間已切回「今日漲跌」→ 丟棄結果 */
  async function renderInto(host, isCurrent) {
    var stale = function () { return !host.isConnected || (typeof isCurrent === 'function' && !isCurrent()); };
    if (!host) return;
    injectStyle();
    host.innerHTML = '<div class="cm-view">計算中…</div>';
    var stages = stagesFromChain();
    if (!stages) { host.innerHTML = '<div class="cm-view">供應鏈對照尚未載入(supplychain_v3)。</div>'; return; }
    try {
      var r = await fetch('/chain-momentum', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stages: stages })
      });
      var d = await r.json();
      if (stale()) return;
      if (!d || !d.stages) { host.innerHTML = '<div class="cm-view">計算失敗:' + esc((d && d.error) || '無資料') + '</div>'; return; }
      var share = window.ShareResult ? '<div class="cm-share">' + ShareResult.buttonHTML('cm-send', '寄結果') + '</div>' : '';
      host.innerHTML = '<div class="cm-view">' + share + render(d) + '</div>';
      if (window.ShareResult) ShareResult.wire('cm-send', function () { return chainText(_lastD); }, '供應鏈輪動');
    } catch (e) {
      if (stale()) return;
      host.innerHTML = '<div class="cm-view">計算失敗:' + esc(e.message) + '</div>';
    }
  }

  window.ChainMom = { renderInto: renderInto };
  /* 舊入口（指令盤／快捷）：開供應鏈視窗並切到動能檢視 */
  window.chainMomOpen = function () {
    if (typeof window.supplyChainOpen === 'function') window.supplyChainOpen({ view: 'mom' });
  };
})();
