/* ============================================================================
 * afterhours_v5.js  —  Stock Terminal 5.0 Stage 3：台股盤後整理
 * ----------------------------------------------------------------------------
 * 資料（皆既有端點，不新增 scraper）：
 *   GET /txf        — 台指期夜盤（主訊號）
 *   GET /stockfut   — 市值前十大個股期領先
 *   GET /marketflow — 量能／三大法人（盤後籌碼）
 *   GET /breadth    — 漲跌家數摘要（S2）
 * 掛載：#mount-afterhours；路由 shell:route=afterhours
 * 大螢幕一頁高密度（pulse 2-zone 風格）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var LIST = [
    { code: '2330', name: '台積電', cid: 'CDF' },
    { code: '2317', name: '鴻海', cid: 'DHF' },
    { code: '2454', name: '聯發科', cid: 'DVF' },
    { code: '2308', name: '台達電', cid: 'FRF' },
    { code: '2382', name: '廣達', cid: 'DKF' },
    { code: '2891', name: '中信金', cid: 'CNF' },
    { code: '2882', name: '國泰金', cid: 'CKF' },
    { code: '2881', name: '富邦金', cid: 'CEF' },
    { code: '2412', name: '中華電', cid: 'DLF' },
    { code: '3711', name: '日月光投控', cid: 'OZF' }
  ];

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('afterhours-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'afterhours-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-afterhours.on){overflow:hidden!important}' +
      '#view-afterhours.sv-panel.on{' +
        'max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-afterhours,#mount-afterhours.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#ah-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#ah-root .ah-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#ah-root .ah-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#ah-root .ah-kicker{display:none!important}' +
      '#ah-root .ah-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#ah-root .ah-sub{font-size:11px;color:var(--tlo);margin:0}' +
      '#ah-root .ah-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '#ah-root .ah-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:10px;cursor:pointer;flex:0 0 auto;white-space:nowrap}' +
      '#ah-root .ah-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ah-root .ah-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#ah-root .ah-btn.primary:hover{background:#FBBF24}' +
      '#ah-root .up{color:var(--red)}#ah-root .dn{color:var(--green)}#ah-root .flat{color:var(--tlo)}' +
      '#ah-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#ah-root .ah-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;margin:0 0 4px;min-width:0;flex:0 0 auto}' +
      '#ah-root .ah-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#ah-root .ah-strip .k{font-size:10px;color:var(--tlo);letter-spacing:.4px;margin-bottom:0;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-strip .v{font-size:15px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-strip .s{font-size:10px;margin-top:0;font-weight:700;line-height:1.2;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-strip .viz-hide,#ah-root .ah-strip .viz-meter,#ah-root .ah-strip .viz-seg,' +
        '#ah-root .ah-strip .viz-chip{display:none!important}' +
      '#ah-root .ah-dash{flex:1;min-height:0;display:grid;gap:4px;' +
        'grid-template-rows:minmax(0,1fr);' +
        'grid-template-columns:minmax(0,1fr) minmax(0,1.25fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)}' +
      '#ah-root .ah-zone,#ah-root .ah-zone-up,#ah-root .ah-zone-lo{display:contents}' +
      '#ah-root .ah-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#ah-root .ah-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px;font-weight:700}' +
      '#ah-root .ah-sec > .ah-fill{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column}' +
      '#ah-root .ah-sec.ah-ovn{padding:5px 6px}' +
      '#ah-root .ah-ovn-head{min-width:0;white-space:nowrap}' +
      '#ah-root .ah-ovn-head > span:first-child{overflow:hidden;text-overflow:ellipsis}' +
      '#ah-root .ah-ovn-sub{flex:0 0 auto;font-size:9px;color:var(--tlo);font-weight:600;letter-spacing:0}' +
      '#ah-root .ah-sec.ah-ovn > .ah-fill{padding-right:2px}' +
      '#ah-root #ah-ovn-host.ovn-embed{flex:1;min-height:0}' +
      '#ah-root table.ah-tbl{width:100%;border-collapse:collapse;font-size:10px}' +
      '#ah-root table.ah-tbl th,#ah-root table.ah-tbl td{padding:3px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#ah-root table.ah-tbl th:first-child,#ah-root table.ah-tbl td:first-child,' +
      '#ah-root table.ah-tbl th:nth-child(2),#ah-root table.ah-tbl td:nth-child(2){text-align:left}' +
      '#ah-root table.ah-tbl th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '#ah-root tr.ah-row{cursor:pointer}#ah-root tr.ah-row:hover{background:var(--bg3)}' +
      '#ah-root .ah-inst4{display:grid;grid-template-columns:1fr 1fr;gap:4px;flex:0 0 auto;' +
        'min-height:0;margin-bottom:4px}' +
      '#ah-root .ah-inst4 .c{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:6px 5px;' +
        'text-align:center;display:flex;flex-direction:column;justify-content:center}' +
      '#ah-root .ah-inst4 .c .k{font-size:11px;color:var(--tlo)}' +
      '#ah-root .ah-inst4 .c .v{font-size:13px;font-weight:800;margin-top:1px;color:var(--thi)}' +
      '#ah-root .ah-inst-trend{flex:0 0 auto;min-height:72px;margin:0 0 6px;background:var(--bg);border:1px solid var(--border);' +
        'border-radius:5px;padding:4px 6px;display:flex;flex-direction:column;min-width:0;overflow:hidden;isolation:isolate}' +
      '#ah-root .ah-inst-trend .lab{font-size:10px;color:var(--tlo);flex:0 0 auto;margin-bottom:2px;' +
        'display:flex;justify-content:space-between;gap:6px;align-items:baseline;min-width:0}' +
      '#ah-root .ah-inst-trend .lab>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-inst-trend .chart{flex:0 0 72px;height:72px;min-height:72px;max-height:88px;overflow:hidden;position:relative}' +
      '#ah-root .ah-inst-trend .chart .vz-spark-ax{height:100%;min-height:0;max-height:100%;overflow:hidden}' +
      '#ah-root .ah-inst-trend .chart .vz-plot,#ah-root .ah-inst-trend .chart .vz-spark-wrap{overflow:hidden;max-width:100%;max-height:100%}' +
      '#ah-root .ah-inst-trend .chart .vz-pt{font-size:8px;z-index:4;max-width:calc(100% - 4px)}' +
      '#ah-root .ah-inst-trend .chart .vz-spark,#ah-root .ah-inst-trend .chart svg{width:100%!important;height:100%!important;min-height:0;max-height:100%;overflow:hidden}' +
      '#ah-root .ah-inst-cmt{font-size:11px;line-height:1.45;color:var(--text);margin-top:2px;flex:0 0 auto;' +
        'position:relative;z-index:2;white-space:normal;overflow:visible;word-break:break-word}' +
      '#ah-root .ah-inst-cmt b{color:var(--gold);font-weight:700}' +
      '#ah-root .ah-inst-cmt .up{color:var(--red)}#ah-root .ah-inst-cmt .dn{color:var(--green)}' +
      '#ah-root .ah-inst-mkt{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:3px;flex:0 0 auto;' +
        'padding-top:3px;border-top:1px solid var(--border);white-space:normal;overflow:visible;word-break:break-word}' +
      '#ah-root .ah-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:2px;flex:0 0 auto;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-loading,#ah-root .ah-err{font-size:10px;color:var(--tlo);padding:10px 0}' +
      '#ah-root .ah-err{color:var(--orange)}' +
      '#ah-root table.ah-tbl{table-layout:fixed}' +
      '#ah-root table.ah-tbl th,#ah-root table.ah-tbl td{min-width:0;overflow:hidden;text-overflow:ellipsis}' +
      '#ah-root table.ah-mv col.c-i{width:1.6em}#ah-root table.ah-mv col.c-cd{width:3.2em}' +
      '#ah-root table.ah-mv col.c-nm{width:auto}#ah-root table.ah-mv col.c-pct{width:9em}' +
      '#ah-root table.ah-mv td:nth-child(4),#ah-root table.ah-mv th:nth-child(4){white-space:nowrap;overflow:visible;text-overflow:unset}' +
      '#ah-root table.ah-mv .vz-rowbar{display:none!important}' +
      '#ah-body.ah-loading{display:flex;align-items:center}' +
      /* 手機直式：一行一個 frame 往下排，允許整頁垂直捲動 */
      '@media(max-width:900px) and (orientation:portrait){' +
        '#shell-views:has(#view-afterhours.on){overflow-x:hidden!important;overflow-y:auto!important;display:block!important;' +
          'overscroll-behavior:contain;-webkit-overflow-scrolling:touch}' +
        '#view-afterhours.sv-panel.on{height:auto!important;min-height:100%;overflow:visible!important;' +
          'display:block!important;flex:none!important;padding:6px 8px 18px}' +
        '#mount-afterhours,#mount-afterhours.sv-mount,#ah-root,#ah-body{height:auto;min-height:0;overflow:visible;display:block;flex:none}' +
        '#ah-root .ah-head{flex-wrap:wrap;align-items:flex-start}' +
        '#ah-root .ah-actions{flex-wrap:wrap;justify-content:flex-start}' +
        '#ah-root .ah-ovn-head{white-space:normal;flex-wrap:wrap}' +
        '#ah-root .ah-strip{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin:0 0 8px}' +
        '#ah-root .ah-strip .cell{overflow:visible;padding:7px 9px}' +
        '#ah-root .ah-strip .k,#ah-root .ah-strip .v{overflow:visible;text-overflow:unset;white-space:nowrap}' +
        '#ah-root .ah-strip .s{white-space:normal;overflow:visible;text-overflow:unset;line-height:1.35}' +
        '#ah-root .ah-dash{display:grid;grid-template-columns:1fr;grid-template-rows:none;height:auto;min-height:0;gap:8px;align-items:stretch}' +
        '#ah-root .ah-sec{height:auto;min-height:0;overflow:visible;padding:9px 10px}' +
        '#ah-root .ah-sec > .ah-fill{flex:0 0 auto;overflow:visible;min-height:0}' +
        '#ah-root #ah-ovn-host.ovn-embed{flex:0 0 auto;height:auto}' +
        '#ah-root .ovn-embed .ovn-signal-name,#ah-root .ovn-embed .ovn-signal-meta,' +
          '#ah-root .ovn-embed th,#ah-root .ovn-embed td{white-space:normal;overflow:visible;text-overflow:unset}' +
        '#ah-root table.ah-tbl th,#ah-root table.ah-tbl td{overflow:visible;text-overflow:unset;white-space:nowrap}' +
        '#ah-root table.ah-mv td:nth-child(3),#ah-root table.ah-fut td:nth-child(2){white-space:normal}' +
        '#ah-root table.ah-tbl .vz-rowbar{display:none!important}' +
        '#ah-root .ah-note{white-space:normal;overflow:visible;text-overflow:unset}' +
        '#ah-root .ah-inst-trend .lab>span{white-space:normal;overflow:visible;text-overflow:unset}' +
      '}' +
      /* 手機橫式：維持五欄，但框隨內容長高、禁止線圖蓋字／欄位截斷 */
      '@media(max-width:900px) and (orientation:landscape){' +
        '#shell-views:has(#view-afterhours.on){overflow-x:hidden!important;overflow-y:auto!important;display:block!important;' +
          'overscroll-behavior:contain;-webkit-overflow-scrolling:touch}' +
        '#view-afterhours.sv-panel.on{height:auto!important;min-height:100%;overflow:visible!important;' +
          'display:flex!important;flex-direction:column;padding:4px 6px 14px}' +
        '#mount-afterhours,#mount-afterhours.sv-mount,#ah-root{height:auto;min-height:0;overflow:visible}' +
        '#ah-body{height:auto;min-height:0;overflow:visible;flex:1 0 auto}' +
        '#ah-root .ah-head{flex-wrap:wrap;gap:4px}' +
        '#ah-root .ah-actions{flex-wrap:wrap}' +
        '#ah-root .ah-strip{grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}' +
        '#ah-root .ah-strip .cell{overflow:visible;padding:4px 6px}' +
        '#ah-root .ah-strip .k,#ah-root .ah-strip .v{overflow:visible;text-overflow:unset;white-space:nowrap}' +
        '#ah-root .ah-strip .s{white-space:normal;overflow:visible;text-overflow:unset;line-height:1.3;font-size:9px}' +
        '#ah-root .ah-dash{height:auto;min-height:0;grid-template-rows:auto;align-items:start;gap:5px}' +
        '#ah-root .ah-sec{height:auto;max-height:none;overflow:visible;min-height:0}' +
        '#ah-root .ah-sec > .ah-fill{overflow:visible;flex:0 0 auto}' +
        '#ah-root #ah-ovn-host.ovn-embed{flex:0 0 auto;height:auto}' +
        '#ah-root .ovn-embed .ovn-signal-name,#ah-root .ovn-embed .ovn-signal-meta{white-space:normal;overflow:visible;text-overflow:unset}' +
        '#ah-root .ovn-embed th,#ah-root .ovn-embed td{white-space:normal;overflow:visible;text-overflow:unset}' +
        '#ah-root .ah-inst-trend .chart .vz-pt,#ah-root .ah-inst-trend .chart .vz-yunit,' +
          '#ah-root .ah-inst-trend .chart .vz-ylabs,#ah-root .ah-inst-trend .chart .vz-xlabs,' +
          '#ah-root .ah-inst-trend .chart .vz-xunit{display:none!important}' +
        '#ah-root .ah-inst-trend .chart .vz-spark-ax{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr);gap:0;padding:0;overflow:hidden}' +
        '#ah-root .ah-inst-trend .chart .vz-plot{grid-column:1;grid-row:1;border-left:0}' +
        '#ah-root table.ah-tbl .vz-chip,#ah-root table.ah-tbl .vz-rowbar{display:none!important}' +
        '#ah-root table.ah-tbl th,#ah-root table.ah-tbl td{overflow:visible;text-overflow:unset;font-size:9px;padding:2px 3px}' +
        '#ah-root table.ah-mv col.c-pct{width:4.8em}' +
        '#ah-root table.ah-mv td:nth-child(4){font-size:10px;letter-spacing:-0.2px}' +
        '#ah-root .ah-note{white-space:normal;overflow:visible;text-overflow:unset}' +
        '#ah-root .ah-inst4 .c .v{white-space:nowrap;overflow:visible;font-size:12px}' +
        '#ah-root .ah-inst-cmt{font-size:10px;line-height:1.4}' +
      '}';
  }

  function twCls(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  }
  function fmtN(v, dig) {
    if (v == null || !isFinite(v)) return '—';
    dig = dig == null ? 0 : dig;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: dig, minimumFractionDigits: dig });
  }
  function yi(v) { return v == null ? '—' : (v / 1e8).toFixed(0) + ' 億'; }
  function fyi(v) {
    if (v == null) return '—';
    return (v >= 0 ? '+' : '') + (v / 1e8).toFixed(0) + ' 億';
  }
  function fmtTime(t) {
    if (!t || String(t).length < 4) return '';
    var s = String(t).padStart(6, '0');
    return s.slice(0, 2) + ':' + s.slice(2, 4) + ':' + s.slice(4, 6);
  }
  function toneTxf(p, amp) {
    var parts = [];
    if (p == null) parts.push('夜盤%不足');
    else if (p <= -1.5) parts.push('強烈開低風險');
    else if (p <= -0.5) parts.push('偏弱・開低機率高');
    else if (p >= 1.5) parts.push('強烈開高・留意追高');
    else if (p >= 0.5) parts.push('偏強・開高機率高');
    else parts.push('中性・開盤波動有限');
    if (amp != null) {
      if (amp >= 3.5) parts.push('高振幅');
      else if (amp >= 2.0) parts.push('波動偏大');
    }
    return parts.join(' · ');
  }

  /** 元 → 億（與 pulse/history totalYi 對齊） */
  function yiNum(v) {
    if (v == null || !isFinite(v)) return null;
    return Number(v) / 1e8;
  }
  function fmtYiSigned(y) {
    if (y == null || !isFinite(y)) return '—';
    return (y >= 0 ? '+' : '') + y.toFixed(1) + ' 億';
  }

  /** 依當日法人＋歷史序列產生趨勢評論（不重複上方數字本身） */
  function buildInstComment(inst, histNewestFirst) {
    var parts = [];
    var f = yiNum(inst && inst.foreign);
    var t = yiNum(inst && inst.trust);
    var d = yiNum(inst && inst.dealer);
    var tot = (f != null || t != null || d != null) ? ((f || 0) + (t || 0) + (d || 0)) : null;
    var rows = (histNewestFirst || []).filter(function (r) {
      return r && r.totalYi != null && isFinite(r.totalYi);
    });
    var chrono = rows.slice().reverse();
    var streak = 0;
    if (tot != null && tot !== 0 && chrono.length) {
      var sign = tot > 0 ? 1 : -1;
      for (var k = chrono.length - 1; k >= 0; k--) {
        var v = chrono[k].totalYi;
        if (v == null || v === 0 || (v > 0 ? 1 : -1) !== sign) break;
        streak += 1;
      }
    }
    if (streak >= 3) {
      parts.push(tot > 0
        ? '合計已連 <b class="up">' + streak + '</b> 日買超，資金偏進攻節奏。'
        : '合計已連 <b class="dn">' + streak + '</b> 日賣超，資金偏防衛／調節。');
    } else if (tot != null) {
      parts.push(tot > 20
        ? '當日合計明顯買超，短線籌碼偏多。'
        : tot < -20
          ? '當日合計明顯賣超，留意權值與指數壓力。'
          : '當日合計接近平衡，方向性訊號有限。');
    }
    if (chrono.length >= 2 && tot != null) {
      var prev = chrono[chrono.length - 2].totalYi;
      if (prev != null && isFinite(prev)) {
        var delta = tot - prev;
        if (Math.abs(delta) >= 50) {
          parts.push(delta > 0
            ? '較前日轉強約 <span class="up">' + fmtYiSigned(delta) + '</span>。'
            : '較前日轉弱約 <span class="dn">' + fmtYiSigned(delta) + '</span>。');
        } else if (prev > 0 && tot < 0) {
          parts.push('合計由買轉賣，資金氛圍轉向謹慎。');
        } else if (prev < 0 && tot > 0) {
          parts.push('合計由賣轉買，資金回補跡象。');
        }
      }
    }
    if (f != null && d != null) {
      if (f > 30 && d < -30) parts.push('外資偏買、自營偏賣 — 常見結構／避險分歧。');
      else if (f < -30 && d > 30) parts.push('外資偏賣、自營偏買 — 留意承接能否延續。');
    }
    if (t != null && Math.abs(t) >= 20) {
      parts.push(t > 0 ? '投信偏買，中長線資金仍有佈局。' : '投信偏賣，主動資金偏調節。');
    }
    if (!parts.length) parts.push('法人序列載入中或資料不足，暫無趨勢評論。');
    return parts.slice(0, 3).join(' ');
  }

  function buildMktLine(bd, txf) {
    var st = (bd && bd.stocks) || {};
    var bits = [];
    if (bd && bd.summary) bits.push(bd.summary);
    else if (bd && bd.score != null) bits.push('大盤體質 ' + bd.score);
    if (st.up != null && st.down != null) {
      var net = st.net != null ? st.net : (st.up - st.down);
      bits.push('漲跌淨 ' + (net >= 0 ? '+' : '') + net);
    }
    if (txf && txf.changePct != null) {
      bits.push('夜盤 ' + pct(txf.changePct) + ' · ' + toneTxf(txf.changePct, txf.ampRate).split(' · ')[0]);
    }
    return bits.length ? bits.join(' · ') : '市場廣度／夜盤訊號載入中';
  }

  function fillAhInstTrend(inst) {
    jget('/pulse/history?kind=institutional&n=20').then(function (h) {
      var V = window.Viz;
      var chart = $('ah-inst-chart');
      var meta = $('ah-inst-trend-meta');
      var cmt = $('ah-inst-cmt');
      if (!chart && !meta && !cmt) return;
      var rows = (h && h.rows) || [];
      var chrono = rows.slice().reverse();
      var totals = chrono.map(function (r) { return r.totalYi; });
      if (chart) {
        if (V && totals.filter(function (v) { return v != null && isFinite(v); }).length >= 2) {
          var last = totals[totals.length - 1];
          var col = last >= 0 ? 'var(--red)' : 'var(--green)';
          chart.innerHTML = V.sparkLine(totals, {
            color: col, h: 64, w: 280,
            xUnit: '日', yUnit: '億', yDigits: 1,
            compact: true
          });
        } else if (totals.length && V && V.sparkBars) {
          chart.innerHTML = V.sparkBars(totals);
        } else if (totals.length) {
          chart.innerHTML = '<div class="ah-err" style="padding:6px 0">序列不足</div>';
        } else {
          chart.innerHTML = '<div class="ah-err" style="padding:6px 0">尚無本機法人歷史 — 可按同步資料預抓</div>';
        }
      }
      if (meta) {
        meta.textContent = (rows.length ? ('近 ' + rows.length + ' 日 · Y：億') : '無序列') +
          (inst && inst.date ? ' · ' + inst.date : '');
      }
      if (cmt) cmt.innerHTML = buildInstComment(inst || {}, rows);
    });
  }

  function normalizeNight(d) {
    if (!d || !d.ok) return null;
    var n = d.night;
    if (!n || n.price == null) {
      if (d.session === 'night' && d.price != null) n = d;
      else if (d.ampRate != null && d.high != null && d.low != null) n = d;
      else return null;
    }
    var changePct = n.changePct;
    if (changePct == null && n.prevClose > 0) changePct = (n.price - n.prevClose) / n.prevClose * 100;
    var amp = n.ampRate;
    if (amp == null && n.high != null && n.low != null && n.prevClose > 0) {
      amp = (n.high - n.low) / n.prevClose * 100;
    }
    return {
      price: n.price, prevClose: n.prevClose, change: n.change, changePct: changePct,
      open: n.open, high: n.high, low: n.low, ampRate: amp, volume: n.volume,
      time: n.time || '', source: n.source || d.source || '', sessionLabel: n.sessionLabel || '夜盤'
    };
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-afterhours');
    if (!panel) return null;
    var mount = $('mount-afterhours');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-afterhours';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('ah-root')) {
      mount.innerHTML =
        '<div id="ah-root">' +
          '<div class="ah-head">' +
            '<div>' +
              '<span class="ah-title">盤後數據</span>' +
              '<span class="ah-sub" id="ah-sub">漲跌排行 · 夜盤 · 籌碼摘要</span>' +
            '</div>' +
            '<div class="ah-actions">' +
              '<button type="button" class="ah-btn" id="ah-refresh">↻ 重新整理</button>' +
              '<button type="button" class="ah-btn" id="ah-open-ovn">夜盤詳情</button>' +
              '<button type="button" class="ah-btn primary" data-shell-back>← 儀表板</button>' +
            '</div>' +
          '</div>' +
          '<div id="ah-body" class="ah-loading">載入盤後資料…</div>' +
        '</div>';
      var r = $('ah-refresh');
      if (r) r.onclick = function () { refresh(); };
      var o = $('ah-open-ovn');
      if (o) o.onclick = function () {
        if (window.overnightOpen) window.overnightOpen();
      };
    }
    return $('ah-body');
  }

  function stripCell(k, v, s, cls) {
    return '<div class="cell"><div class="k">' + k + '</div>' +
      '<div class="v' + (cls ? ' ' + cls : '') + '">' + v + '</div>' +
      (s ? '<div class="s' + (cls ? ' ' + cls : '') + '">' + s + '</div>' : '') + '</div>';
  }

  function render(pack) {
    var V = window.Viz;
    var body = ensureMount();
    if (!body) return;
    var txf = pack.txf, fut = pack.fut || [], mf = pack.mf || {}, bd = pack.bd || {};
    var sub = $('ah-sub');
    var st = (bd.stocks || {});
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (txf && txf.time ? ' · 夜盤 ' + fmtTime(txf.time) : '') +
        (bd.date ? ' · 廣度日 ' + bd.date : '');
    }

    var inst = mf.inst;
    var to = (mf.turnover || []).filter(function (x) { return x.amount != null; });
    var latestAmt = to.length ? to[to.length - 1].amount : null;
    var total = inst ? ((inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0)) : null;

    var strip =
      stripCell('台指期夜盤', txf ? fmtN(txf.price) : '—',
        (pct(txf && txf.changePct) + (txf && txf.sessionLabel ? ' · ' + txf.sessionLabel : '')),
        twCls(txf && txf.changePct)) +
      stripCell('夜盤振幅', txf && txf.ampRate != null ? txf.ampRate.toFixed(2) + '%' : '—',
        txf ? fmtN(txf.volume) + ' 口' : '—') +
      stripCell('漲跌家數', '<span class="up">' + fmtN(st.up) + '</span> / <span class="dn">' + fmtN(st.down) + '</span>',
        '淨 ' + (st.net != null ? ((st.net >= 0 ? '+' : '') + st.net) : '—')) +
      stripCell('大盤體質', bd.score != null ? bd.score : '—', bd.summary || '量能／法人／融資') +
      stripCell('成交金額', yi(latestAmt), (function () {
        var tq = mf.turnoverQuant || {};
        var bits = [];
        if (tq.chgPct != null) bits.push((tq.chgPct >= 0 ? '+' : '') + Number(tq.chgPct).toFixed(1) + '%日');
        if (tq.vsMa5Pct != null) bits.push((tq.vsMa5Pct >= 0 ? '+' : '') + Number(tq.vsMa5Pct).toFixed(1) + '%vs5');
        if (tq.volumeScore != null) bits.push('體制分' + Number(tq.volumeScore).toFixed(0));
        if (tq.z20 != null) bits.push('Z' + Number(tq.z20).toFixed(1));
        if (tq.volumeRelative) bits.push(tq.volumeRelative);
        if (tq.volumeRelativeScore != null) bits.push('相對分' + Number(tq.volumeRelativeScore).toFixed(0));
        if (tq.trend) bits.push(tq.trend);
        return bits.length ? bits.join(' · ') : (mf.date || '量能');
      })()) +
      stripCell('法人合計', fyi(total),
        '外 ' + fyi(inst && inst.foreign) + ' · 投 ' + fyi(inst && inst.trust));

    /* 左欄改掛載 overnight_v3 現有夜盤面板（雙 gauge／TXF OHLC／美股連動／TSMC／停損） */
    var txfBlock =
      '<div class="ah-sec ah-ovn">' +
        '<h4 class="ah-ovn-head"><span>夜盤連動預警</span><span class="ah-ovn-sub">台指期 · 美股連動</span></h4>' +
        '<div class="ah-fill" id="ah-ovn-host">' +
          '<div class="ah-loading">載入夜盤面板…</div>' +
        '</div>' +
      '</div>';

    var leadMax = 0;
    fut.forEach(function (r) {
      if (r.lead != null && isFinite(r.lead)) leadMax = Math.max(leadMax, Math.abs(r.lead));
    });
    var rows = fut.map(function (r) {
      var lead = r.lead == null ? '—' : ((r.lead >= 0 ? '+' : '') + r.lead.toFixed(2));
      var leadExtra = '';
      if (V && r.lead != null && isFinite(r.lead)) {
        leadExtra = V.rowBar(r.lead, leadMax || 1) +
          V.chip(r.lead >= 0 ? '期>現' : '期<現', r.lead >= 0 ? 'buy' : 'sell');
      }
      return '<tr class="ah-row" data-code="' + r.code + '">' +
        '<td style="color:var(--gold);font-weight:700">' + r.code + '</td>' +
        '<td>' + r.name + '</td>' +
        '<td>' + (r.price != null ? r.price : '—') + '</td>' +
        '<td class="' + twCls(r.changePct) + '">' + pct(r.changePct) + '</td>' +
        '<td class="' + twCls(r.spotChangePct) + '">' + pct(r.spotChangePct) + '</td>' +
        '<td class="' + twCls(r.lead) + '">' + lead + leadExtra + '</td></tr>';
    }).join('');
    var sess = fut.some(function (r) { return r.session === 'night'; }) ? '夜盤'
      : fut.some(function (r) { return r.session === 'day'; }) ? '日盤' : '—';
    var futBlock =
      '<div class="ah-sec"><h4>個股期領先 · ' + sess + '</h4>' +
      '<div class="ah-fill">' +
      (rows
        ? '<table class="ah-tbl ah-fut"><tr><th>代號</th><th>名稱</th><th>期價</th><th>期%</th><th>現%</th><th>領先</th></tr>' +
          rows + '</table>'
        : '<div class="ah-err">個股期資料暫缺</div>') +
      '</div>' +
      '<div class="ah-note">領先 = 期% − 現% · 點列載入線型</div></div>';

    var instBlock = '<div class="ah-sec"><h4>盤後籌碼</h4>';
    if (!inst && latestAmt == null) {
      instBlock += '<div class="ah-err">資金流尚未更新</div></div>';
    } else {
      var mktLine = buildMktLine(bd, txf);
      instBlock += '<div class="ah-fill">' +
        '<div class="ah-inst4">' +
          '<div class="c"><div class="k">外資</div><div class="v ' + twCls(inst && inst.foreign) + '">' + fyi(inst && inst.foreign) + '</div></div>' +
          '<div class="c"><div class="k">投信</div><div class="v ' + twCls(inst && inst.trust) + '">' + fyi(inst && inst.trust) + '</div></div>' +
          '<div class="c"><div class="k">自營</div><div class="v ' + twCls(inst && inst.dealer) + '">' + fyi(inst && inst.dealer) + '</div></div>' +
          '<div class="c"><div class="k">合計</div><div class="v ' + twCls(total) + '">' + fyi(total) + '</div></div>' +
        '</div>' +
        '<div class="ah-inst-trend" id="ah-inst-trend">' +
          '<div class="lab"><span>合計買賣超趨勢</span><span id="ah-inst-trend-meta">' +
            ((inst && inst.date) ? ('法人日 ' + inst.date) : '載入…') +
          '</span></div>' +
          '<div class="chart" id="ah-inst-chart"><div class="ah-err" style="padding:6px 0">載入資金序列…</div></div>' +
        '</div>' +
        '<div class="ah-inst-cmt" id="ah-inst-cmt">分析資金變化中…</div>' +
        '<div class="ah-inst-mkt">' + mktLine + '</div>' +
        '</div>' +
        '<div class="ah-note">法人日 ' + ((inst && inst.date) || mf.date || '—') +
          ' · 趨勢不重複上方數字</div></div>';
    }

    var movers = pack.movers || {};
    var gain = movers.gainers || movers.up || [];
    var lose = movers.losers || movers.down || [];
    function mvTbl(list, title, cls) {
      var h = '<div class="ah-sec"><h4>' + title + '</h4><div class="ah-fill">';
      if (!list.length) return h + '<div class="ah-err">尚無排行</div></div></div>';
      var slice = list.slice(0, 22);
      var maxAbs = 0;
      slice.forEach(function (r) {
        if (r.changePct != null && isFinite(r.changePct)) maxAbs = Math.max(maxAbs, Math.abs(r.changePct));
      });
      h += '<table class="ah-tbl ah-mv"><colgroup><col class="c-i"><col class="c-cd"><col class="c-nm"><col class="c-pct"></colgroup>' +
        '<tr><th>#</th><th>代號</th><th>名稱</th><th>漲跌幅</th></tr>';
      slice.forEach(function (r, i) {
        var lim = V ? V.limitChip(r.changePct) : '';
        var bar = V ? V.rowBar(r.changePct, maxAbs) : '';
        h += '<tr class="ah-row" data-code="' + (r.code || '') + '"><td>' + (i + 1) +
          '</td><td style="color:var(--gold);font-weight:700">' + (r.code || '') +
          '</td><td>' + (r.name || '') + '</td><td class="' + (cls || twCls(r.changePct)) + '">' +
          pct(r.changePct) + lim + bar + '</td></tr>';
      });
      return h + '</table></div></div>';
    }

    body.classList.remove('ah-loading');
    body.innerHTML =
      '<div class="ah-strip">' + strip + '</div>' +
      '<div class="ah-dash">' +
        '<div class="ah-zone ah-zone-up">' + txfBlock + futBlock + '</div>' +
        '<div class="ah-zone ah-zone-lo">' + instBlock + mvTbl(gain, '漲幅排行', 'up') + mvTbl(lose, '跌幅排行', 'dn') + '</div>' +
      '</div>' +
      '<div class="ah-note">僅供參考 · TAIFEX MIS / TWSE OpenData</div>';

    body.querySelectorAll('tr.ah-row').forEach(function (el) {
      el.onclick = function () {
        var c = el.getAttribute('data-code');
        if (c && typeof loadSym === 'function') {
          loadSym(c, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
    if (inst || latestAmt != null) fillAhInstTrend(inst || {});
    mountOvernightPanel();
  }

  function mountOvernightPanel() {
    var host = $('ah-ovn-host');
    if (!host) return;
    if (typeof window.overnightRenderInto === 'function') {
      window.overnightRenderInto(host, { embedded: true });
      return;
    }
    /* overnight 模組尚未就緒時退回精簡 OHLC（與頂列同源 /txf） */
    host.innerHTML = '<div class="ah-err">夜盤模組載入中…請按「夜盤詳情」或重新整理</div>';
  }

  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function refresh(opts) {
    opts = opts || {};
    var body = ensureMount();
    if (!body) return;
    var soft = !!opts.soft || !!body.querySelector('.ah-strip, .ah-dash, .ah-sec');
    if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-afterhours', soft, '更新中…');
    }
    if (!soft) body.innerHTML = '<div class="ah-loading">載入盤後資料…</div>';
    var cids = LIST.map(function (x) { return x.cid; }).join(',');
    Promise.all([
      jget('/txf'),
      jget('/stockfut?cids=' + encodeURIComponent(cids)),
      jget('/marketflow'),
      jget('/breadth'),
      jget('/movers?n=22')
    ]).then(function (arr) {
      var txfRaw = arr[0], sf = arr[1], mf = arr[2], bd = arr[3], mv = arr[4];
      var byCid = {};
      ((sf && sf.results) || []).forEach(function (r) { byCid[r.cid] = r; });
      var fut = LIST.map(function (s) {
        return Object.assign({}, s, byCid[s.cid] || { ok: false });
      }).sort(function (a, b) {
        return (b.changePct == null ? -999 : b.changePct) - (a.changePct == null ? -999 : a.changePct);
      });
      render({ txf: normalizeNight(txfRaw), fut: fut, mf: mf || {}, bd: bd || {}, movers: mv || {} });
    }).finally(function () {
      if (window.ShellV5 && window.ShellV5.softBadge) {
        window.ShellV5.softBadge('mount-afterhours', false);
      }
    });
  }

  function activate() {
    ensureMount();
    refresh({ soft: !!$('ah-body') && !$('ah-body').querySelector('.ah-loading') });
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'afterhours') {
        refresh({ soft: true });
      }
    }, 45000);
  }

  function deactivate() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  window.AfterhoursV5 = { activate: activate, deactivate: deactivate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'afterhours') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'afterhours') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 220); });
  else setTimeout(boot, 220);
})();
