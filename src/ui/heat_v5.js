/* ============================================================================
 * heat_v5.js  —  Stock Terminal 5.0 Stage 5：類股熱力圖
 * ----------------------------------------------------------------------------
 * 資料：GET /sectors?mkt=TW|US（官方類股／SPDR）
 * 輔區：GET /focus?mkt=TW|US 做多／做空焦點（背景載入，可點進圖表）
 * 掛載：#mount-heat；側欄「熱力」
 * 深鏈：ShellV5.go('heat', { mkt, sector, sectorKey }) — 總覽產業輪動列／熱力 →
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var state = {
    mkt: 'TW',
    sort: 'chg',
    last: null,
    focusByMkt: { TW: null, US: null },
    sector: null,
    sectorKey: null
  };

  // 台股類股名 → 代表股（點格載入 K 線）
  var TW_PROXY = [
    { key: '半導體', code: '2330' },
    { key: '電子', code: '2317' },
    { key: '電腦', code: '2382' },
    { key: '光電', code: '3008' },
    { key: '通信', code: '2345' },
    { key: '通訊', code: '2345' },
    { key: '網通', code: '2345' },
    { key: '金融', code: '2882' },
    { key: '保險', code: '2882' },
    { key: '塑膠', code: '1301' },
    { key: '化學', code: '1303' },
    { key: '鋼鐵', code: '2002' },
    { key: '航運', code: '2603' },
    { key: '汽車', code: '2207' },
    { key: '食品', code: '1216' },
    { key: '電信', code: '2412' },
    { key: '生技', code: '1707' },
    { key: '醫療', code: '1707' },
    { key: '營建', code: '2548' },
    { key: '建材', code: '2548' },
    { key: '紡織', code: '1476' },
    { key: '橡膠', code: '2105' },
    { key: '電機', code: '2308' },
    { key: '機械', code: '2308' },
    { key: '水泥', code: '1101' },
    { key: '玻璃', code: '1802' },
    { key: '造紙', code: '1904' },
    { key: '觀光', code: '2707' },
    { key: '貿易', code: '2912' },
    { key: '百貨', code: '2912' },
    { key: '油電', code: '6505' },
    { key: '燃氣', code: '6505' },
    { key: '電器', code: '2377' },
    { key: '其他電子', code: '2357' },
    { key: '資訊服務', code: '2474' },
    { key: '文化創意', code: '8446' },
    { key: '農業科技', code: '1216' },
    { key: '數位雲端', code: '2454' },
    { key: '綠能', code: '6443' },
    { key: '環保', code: '6443' }
  ];

  var SKIP_TW = /加權|櫃買|寶島|公司治理|中型100|未含金融|未含電子|報酬指數|全市場/;

  function $(id) { return document.getElementById(id); }

  function sectorKey(name) {
    return String(name || '')
      .replace(/業$/g, '')
      .replace(/[\s　]/g, '')
      .toLowerCase();
  }

  function sectorKeysMatch(a, b) {
    var ka = sectorKey(a), kb = sectorKey(b);
    if (!ka || !kb) return false;
    return ka === kb || ka.indexOf(kb) >= 0 || kb.indexOf(ka) >= 0;
  }

  function injectCSS() {
    var s = $('heat-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'heat-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-heat.on){overflow:hidden!important}' +
      '#view-heat.sv-panel.on{max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-heat,#mount-heat.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#ht-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);width:100%;max-width:none;margin:0;min-width:0;' +
        'box-sizing:border-box;flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#ht-root .ht-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#ht-root .ht-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#ht-root .ht-kicker{display:none!important}' +
      '#ht-root .ht-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#ht-root .ht-sub{font-size:11px;color:var(--tlo);margin:0}' +
      '#ht-root .ht-actions{display:flex;gap:4px;flex-wrap:nowrap;align-items:center;flex:0 0 auto}' +
      '#ht-root .ht-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;white-space:nowrap}' +
      '#ht-root .ht-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ht-root .ht-btn.on{border-color:var(--gold);color:var(--gold);background:var(--gold-s)}' +
      '#ht-root .ht-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      /* 直向堆疊：WD／KPI 置頂，主區 2 欄 — 禁止把 .ht-wd 塞進 2 欄 grid 當第 1 格 */
      '#ht-body{flex:1;min-height:0;display:flex;flex-direction:column;gap:4px;overflow:hidden}' +
      '#ht-body.ht-loading{display:flex;align-items:center;justify-content:center}' +
      '#ht-body .ht-wd{flex:0 0 auto;margin:0;padding:5px 8px;border-radius:6px;background:var(--bg2);' +
        'border:1px solid rgba(103,232,249,.28);font-size:9px;line-height:1.45;color:var(--tlo)}' +
      '#ht-body .ht-wd b{color:var(--cyan)}' +
      '#ht-body .ht-kpi{flex:0 0 auto;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}' +
      '#ht-body .ht-kpi .k{background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:4px 7px;min-width:0}' +
      '#ht-body .ht-kpi .k .l{font-size:10px;color:var(--tlo);letter-spacing:.3px}' +
      '#ht-body .ht-kpi .k .v{font-size:12px;font-weight:700;color:var(--thi);margin-top:1px;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ht-body .ht-kpi .k .s{font-size:10px;color:var(--tlo);margin-top:1px}' +
      '#ht-body .ht-kpi .k .s.us-up{color:var(--green)}#ht-body .ht-kpi .k .s.us-down{color:var(--red)}' +
      '#ht-body .ht-dash{flex:1;min-height:0;display:grid;gap:4px;overflow:hidden;' +
        'grid-template-columns:minmax(0,1.55fr) minmax(260px,1fr);grid-template-rows:minmax(0,1fr)}' +
      '#ht-body .ht-main{min-height:0;display:flex;flex-direction:column;overflow:hidden;' +
        'background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px}' +
      '#ht-body .ht-main > h4,#ht-root .ht-focus-zone > h4{margin:0 0 3px;font-size:10px;color:var(--gold);' +
        'letter-spacing:.5px;flex:0 0 auto;display:flex;align-items:baseline;justify-content:space-between;gap:6px}' +
      '#ht-body .ht-main > h4 .ht-focus-tag{font-size:9px;color:var(--cyan);font-weight:600;letter-spacing:0}' +
      '#ht-root .ht-legend{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--tlo);margin:0 0 3px;flex:0 0 auto}' +
      '#ht-root .ht-legend i{display:inline-block;width:12px;height:8px;border-radius:2px}' +
      '#ht-root .ht-grid-wrap{flex:1;min-height:0;overflow:auto}' +
      '#ht-root .ht-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:4px;margin:0;' +
        'align-content:start;grid-auto-rows:minmax(58px,auto)}' +
      '#ht-root .ht-cell{min-height:54px;padding:5px 4px;border-radius:5px;border:1px solid rgba(255,255,255,.06);' +
        'cursor:pointer;text-align:center;display:flex;flex-direction:column;justify-content:center;gap:1px;' +
        'transition:transform .1s,box-shadow .1s,opacity .12s,outline-color .12s;color:#fff;' +
        'text-shadow:0 1px 2px rgba(0,0,0,.55)}' +
      '#ht-root .ht-cell:hover{transform:scale(1.02);box-shadow:0 2px 10px rgba(0,0,0,.4);z-index:2}' +
      '#ht-root .ht-cell.hi{outline:2px solid var(--gold);box-shadow:0 0 0 1px rgba(245,197,24,.45),0 4px 14px rgba(0,0,0,.5);' +
        'z-index:3;transform:scale(1.03)}' +
      '#ht-root .ht-cell.dim{opacity:.38}' +
      '#ht-root .ht-cell .nm{font-size:10px;font-weight:700;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ht-root .ht-cell .pc{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums}' +
      '#ht-root .ht-cell .px{font-size:8px;opacity:.85;font-variant-numeric:tabular-nums}' +
      '#ht-root .ht-cell .pxcode{font-size:8px;opacity:.7;letter-spacing:.2px}' +
      '#ht-root .ht-focus-zone{min-height:0;display:flex;flex-direction:column;' +
        'background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;overflow:hidden}' +
      '#ht-root .ht-focus-zone > #ht-focus{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#ht-root .ht-two{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,1fr);gap:4px;flex:1;min-height:0;overflow:hidden}' +
      '#ht-root .ht-two > div{min-height:0;display:flex;flex-direction:column;overflow:hidden;' +
        'background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 5px}' +
      '#ht-root .ht-list{flex:1;min-height:0;overflow:auto}' +
      '#ht-root .ht-row{display:flex;align-items:center;gap:5px;padding:2px 3px;border-bottom:1px solid var(--border);' +
        'cursor:pointer;font-size:10px}' +
      '#ht-root .ht-row:hover{background:var(--bg3)}' +
      '#ht-root .ht-row .code{color:var(--gold);font-weight:700;min-width:42px;font-size:9px}' +
      '#ht-root .ht-row .name{flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px}' +
      '#ht-root .up{color:var(--red)}#ht-root .dn{color:var(--green)}' +
      '#ht-root .us-up{color:var(--green)}#ht-root .us-down{color:var(--red)}' +
      '#ht-root .ht-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:2px;flex:0 0 auto}' +
      '#ht-root .ht-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      '@media (max-width:980px){' +
        '#ht-body .ht-dash{grid-template-columns:1fr;grid-template-rows:minmax(0,1.1fr) minmax(0,.9fr)}' +
        '#ht-body .ht-kpi{grid-template-columns:repeat(2,minmax(0,1fr))}' +
      '}';
  }

  function wdStripHtml() {
    try {
      if (!window.WaveDeckBridge) return '';
      var last = window.WaveDeckBridge.lastSync && window.WaveDeckBridge.lastSync();
      var p = last && last.payload;
      var meta = (p && p.meta) || {};
      if (!p) {
        return '<div class="ht-wd">WaveDeck：尚無宏觀覆寫（可開脈動或 START_WAVEDECK）</div>';
      }
      var spill = meta.spillover_prob != null
        ? Math.round(Number(meta.spillover_prob) * 100) + '%' : '—';
      return '<div class="ht-wd">WaveDeck 覆寫 · 風格 <b>' + p.style + '</b>' +
        (p.delever ? ' · <b>降載</b>' : '') +
        ' · 外溢 <b>' + spill + '</b>' +
        (meta.rotation ? (' · 輪動 <b>' + meta.rotation + '</b>') : '') +
        (meta.hot_stage ? (' · 最強 <b>' + meta.hot_stage + '</b>') : '') +
        '</div>';
    } catch (e) {
      return '';
    }
  }

  function pctColor(pct, mkt) {
    var v = Math.min(Math.abs(pct || 0), 5) / 5;
    var a = 0.22 + v * 0.58;
    var isUp = pct >= 0;
    var upR = mkt === 'TW' ? 248 : 74, upG = mkt === 'TW' ? 113 : 222, upB = mkt === 'TW' ? 113 : 128;
    var dnR = mkt === 'TW' ? 74 : 248, dnG = mkt === 'TW' ? 222 : 113, dnB = mkt === 'TW' ? 128 : 113;
    return isUp
      ? 'rgba(' + upR + ',' + upG + ',' + upB + ',' + a.toFixed(2) + ')'
      : 'rgba(' + dnR + ',' + dnG + ',' + dnB + ',' + a.toFixed(2) + ')';
  }

  function twCls(p) {
    if (p == null || p !== p) return '';
    return p > 0 ? 'up' : p < 0 ? 'dn' : '';
  }
  /** 台股紅漲綠跌；美股綠漲紅跌，使用獨立類別避免 CSS 語意互換。 */
  function chgCls(p, mkt) {
    if (p == null || p !== p) return '';
    if (mkt === 'US') return p > 0 ? 'us-up' : p < 0 ? 'us-down' : '';
    return twCls(p);
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  }
  function fmt(v) {
    if (v == null || !isFinite(v)) return '—';
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function proxyFor(name) {
    for (var i = 0; i < TW_PROXY.length; i++) {
      if (name.indexOf(TW_PROXY[i].key) >= 0) return TW_PROXY[i].code;
    }
    return null;
  }

  function filterSectors(list, mkt) {
    var rows = (list || []).filter(function (s) {
      if (!s || s.changePct == null || !s.name) return false;
      if (mkt === 'TW' && SKIP_TW.test(s.name)) return false;
      return true;
    });
    if (state.sort === 'name') {
      rows.sort(function (a, b) { return String(a.name).localeCompare(String(b.name), 'zh-TW'); });
    } else {
      rows.sort(function (a, b) { return b.changePct - a.changePct; });
    }
    return rows;
  }

  function syncMktButtons() {
    var mount = $('mount-heat');
    if (!mount) return;
    mount.querySelectorAll('[data-mkt]').forEach(function (x) {
      x.classList.toggle('on', x.getAttribute('data-mkt') === state.mkt);
    });
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-heat');
    if (!panel) return null;
    var mount = $('mount-heat');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-heat';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('ht-root')) {
      mount.innerHTML =
        '<div id="ht-root">' +
          '<div class="ht-head"><div>' +
            '<span class="ht-title">類股熱力</span>' +
            '<span class="ht-sub" id="ht-sub">產業漲跌 · 點格載入代表股</span>' +
          '</div><div class="ht-actions">' +
            '<button type="button" class="ht-btn on" data-mkt="TW">TW</button>' +
            '<button type="button" class="ht-btn" data-mkt="US">US</button>' +
            '<button type="button" class="ht-btn on" data-sort="chg">漲跌</button>' +
            '<button type="button" class="ht-btn" data-sort="name">名稱</button>' +
            '<button type="button" class="ht-btn" id="ht-refresh">↻</button>' +
            '<button type="button" class="ht-btn primary" data-shell-back>← 儀表板</button>' +
          '</div></div>' +
          '<div id="ht-body" class="ht-loading">載入類股…</div>' +
        '</div>';
      mount.querySelectorAll('[data-mkt]').forEach(function (b) {
        b.onclick = function () {
          state.mkt = b.getAttribute('data-mkt');
          state.sector = null;
          state.sectorKey = null;
          syncMktButtons();
          /* 切市場時強制重抓對應焦點（TW/US 池不同） */
          refresh(true);
        };
      });
      mount.querySelectorAll('[data-sort]').forEach(function (b) {
        b.onclick = function () {
          state.sort = b.getAttribute('data-sort');
          mount.querySelectorAll('[data-sort]').forEach(function (x) {
            x.classList.toggle('on', x.getAttribute('data-sort') === state.sort);
          });
          if (state.last) renderHeat(state.last);
        };
      });
      var r = $('ht-refresh');
      if (r) r.onclick = function () { refresh(true); };
    }
    return $('ht-body');
  }

  function openSym(code, mkt) {
    if (!code || typeof loadSym !== 'function') return;
    loadSym(code, mkt || 'TW');
    if (window.ShellV5) window.ShellV5.go('chart');
  }

  function renderFocus(j) {
    var box = $('ht-focus');
    if (!box) return;
    var mkt = (j && j.mkt) || state.mkt || 'TW';
    var zoneTitle = $('ht-focus-title');
    if (zoneTitle) {
      zoneTitle.textContent = '焦點掃描 · ' + mkt;
    }
    if (!j || !j.ok) {
      box.innerHTML = '<div class="ht-note">焦點掃描暫不可用或仍在載入。</div>';
      return;
    }
    function col(title, rows) {
      var V = window.Viz;
      var h = '<div><h4 style="margin:0 0 4px;font-size:10px;color:var(--gold);flex:0 0 auto">' + title +
        ' · ' + rows.length + '</h4><div class="ht-list">';
      if (!rows.length) h += '<div class="ht-note">無符合</div>';
      rows.slice(0, 20).forEach(function (r) {
        var rowMkt = r.mkt || mkt;
        h += '<div class="ht-row" data-code="' + esc(r.sym) + '" data-mkt="' + esc(rowMkt) + '">' +
          '<span class="code">' + esc(r.sym) + '</span>' +
          '<span class="name">' + esc(r.name || '') + '</span>' +
          '<span class="' + chgCls(r.changePct, rowMkt) + '">' + pct(r.changePct) + '</span>' +
          '<span style="color:var(--gold);font-weight:700;min-width:48px;text-align:right">' +
          (r.score != null ? r.score : '') +
          (V && r.score != null ? V.scoreMeter(r.score) : '') +
          '</span></div>';
      });
      return h + '</div></div>';
    }
    var poolNote = mkt === 'US'
      ? '美股流動池 ' + (j.poolSize || j.scanned || '—') + ' · 掃描 ' + (j.scanned || '—') + ' 檔'
      : '掃描 ' + (j.scanned || '—') + ' 檔';
    box.innerHTML = '<div class="ht-two">' +
      col('做多焦點', j.buy || []) +
      col('做空焦點', j.short || []) +
      '</div>' +
      '<div class="ht-note">' + poolNote + ' · 點列載入 K 線</div>';
    box.querySelectorAll('.ht-row').forEach(function (el) {
      el.onclick = function () {
        openSym(el.getAttribute('data-code'), el.getAttribute('data-mkt') || mkt);
      };
    });
  }

  function kpiHtml(rows, mkt) {
    var up = 0, dn = 0;
    var best = null, worst = null;
    rows.forEach(function (s) {
      if (s.changePct > 0) up += 1;
      else if (s.changePct < 0) dn += 1;
      if (!best || s.changePct > best.changePct) best = s;
      if (!worst || s.changePct < worst.changePct) worst = s;
    });
    var flow = (state.last && state.last.sectorFlow) || {};
    var focusBit = state.sector
      ? ('<div class="k"><div class="l">深鏈聚焦</div><div class="v" style="color:var(--cyan)">' +
        esc(state.sector) + '</div><div class="s">總覽產業輪動帶入</div></div>')
      : ('<div class="k"><div class="l">資金口徑</div><div class="v" style="font-size:11px">' +
        esc(flow.label || '漲跌參與') + '</div><div class="s">' + rows.length + ' 格 · 參與 ' +
        (flow.participationPct == null ? '—' : Number(flow.participationPct).toFixed(0) + '%') + '</div></div>');
    return '<div class="ht-kpi">' +
      focusBit +
      '<div class="k"><div class="l">上漲／下跌</div><div class="v"><span class="' + chgCls(1, mkt) + '">' + up +
        '</span>　<span class="' + chgCls(-1, mkt) + '">' + dn + '</span></div><div class="s">依目前排序篩選</div></div>' +
      '<div class="k"><div class="l">最強</div><div class="v">' + esc(best ? best.name : '—') +
        '</div><div class="s ' + chgCls(best && best.changePct, mkt) + '">' +
        (best ? pct(best.changePct) : '—') + '</div></div>' +
      '<div class="k"><div class="l">最弱</div><div class="v">' + esc(worst ? worst.name : '—') +
        '</div><div class="s ' + chgCls(worst && worst.changePct, mkt) + '">' +
        (worst ? pct(worst.changePct) : '—') + '</div></div>' +
      '</div>';
  }

  function applySectorHighlight(body) {
    if (!body) return;
    var key = state.sectorKey || state.sector;
    var cells = body.querySelectorAll('.ht-cell');
    if (!key || !cells.length) {
      cells.forEach(function (el) {
        el.classList.remove('hi', 'dim');
      });
      return;
    }
    var any = false;
    cells.forEach(function (el) {
      var match = sectorKeysMatch(key, el.getAttribute('data-sector-key') || el.getAttribute('data-name'));
      el.classList.toggle('hi', match);
      if (match) any = true;
    });
    cells.forEach(function (el) {
      if (any) el.classList.toggle('dim', !el.classList.contains('hi'));
      else el.classList.remove('dim');
    });
    var hi = body.querySelector('.ht-cell.hi');
    if (hi && typeof hi.scrollIntoView === 'function') {
      try { hi.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      catch (e) { try { hi.scrollIntoView(false); } catch (e2) {} }
    }
  }

  function renderHeat(d) {
    var body = ensureMount();
    if (!body) return;
    state.last = d;
    var mkt = state.mkt;
    var rows = filterSectors(d && d.sectors, mkt);
    var sub = $('ht-sub');
    if (sub) {
      sub.textContent = (mkt === 'TW' ? '台股類股指數' : '美股 SPDR 產業') +
        ' · ' + rows.length + ' 格 · 資料日 ' + ((d && d.date) || '—') +
        ' · 更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (state.sector ? (' · 聚焦 ' + state.sector) : '');
    }

    var legend = mkt === 'TW'
      ? '<div class="ht-legend"><i style="background:rgba(248,113,113,.8)"></i>漲 ' +
        '<i style="background:rgba(74,222,128,.8)"></i>跌　（台股紅漲綠跌）</div>'
      : '<div class="ht-legend"><i style="background:rgba(74,222,128,.8)"></i>漲 ' +
        '<i style="background:rgba(248,113,113,.8)"></i>跌　（美股綠漲紅跌）</div>';

    var grid = '<div class="ht-grid">';
    if (!rows.length) {
      grid += '<div class="ht-loading">無類股資料</div>';
    } else {
      rows.forEach(function (s) {
        var code = mkt === 'US' ? (s.symbol || '') : proxyFor(s.name);
        var sk = sectorKey(s.name);
        var flowBits = [];
        if (s.marketSharePct != null) flowBits.push('占比 ' + Number(s.marketSharePct).toFixed(1) + '%');
        if (s.rs20VsBenchmarkPct != null) flowBits.push('RS20 ' + (Number(s.rs20VsBenchmarkPct) >= 0 ? '+' : '') + Number(s.rs20VsBenchmarkPct).toFixed(1));
        grid += '<div class="ht-cell" style="background:' + pctColor(s.changePct, mkt) + '" data-code="' +
          esc(code || '') + '" data-mkt="' + mkt + '" data-name="' + esc(s.name) +
          '" data-sector-key="' + esc(sk) + '" title="' + esc(s.name) + (code ? ' → ' + code : '') + '">' +
          '<div class="nm">' + esc(s.name) + '</div>' +
          '<div class="pc">' + pct(s.changePct) + '</div>' +
          (flowBits.length ? '<div class="pxcode">' + esc(flowBits.join(' · ')) + '</div>' : '') +
          (code ? '<div class="pxcode">' + esc(code) + '</div>' : '') +
          '<div class="px">' + fmt(s.close) + '</div></div>';
      });
    }
    grid += '</div>';

    var focusTag = state.sector
      ? '<span class="ht-focus-tag">← ' + esc(state.sector) + '</span>'
      : '';

    body.classList.remove('ht-loading');
    body.innerHTML =
      wdStripHtml() +
      kpiHtml(rows, mkt) +
      '<div class="ht-dash">' +
        '<div class="ht-main"><h4><span>類股熱力圖</span>' + focusTag + '</h4>' +
          legend + '<div class="ht-grid-wrap">' + grid + '</div>' +
          '<div class="ht-note">/sectors · ' + esc(((d && d.sectorFlow) || {}).label || '漲跌參與') +
          ' · 無同 scope 成交額時不顯示資金流 · 點格載入 K 線 · 非投資建議</div></div>' +
        '<div class="ht-focus-zone"><h4 id="ht-focus-title">焦點掃描 · ' + mkt + '</h4>' +
          '<div id="ht-focus" class="ht-loading">掃描中…</div></div>' +
      '</div>';

    body.querySelectorAll('.ht-cell').forEach(function (el) {
      el.onclick = function () {
        var c = el.getAttribute('data-code');
        var m = el.getAttribute('data-mkt') || 'TW';
        if (c) openSym(c, m);
      };
    });

    applySectorHighlight(body);

    var cachedFocus = state.focusByMkt[mkt];
    if (cachedFocus) renderFocus(cachedFocus);
  }

  function loadFocus(force) {
    var mkt = state.mkt || 'TW';
    var url = SRV + '/focus?mkt=' + encodeURIComponent(mkt) + (force ? '&refresh=1' : '');
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (j && !j.mkt) j.mkt = mkt;
        state.focusByMkt[mkt] = j;
        if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'heat' &&
            state.mkt === mkt) {
          renderFocus(j);
        }
      })
      .catch(function () {
        state.focusByMkt[mkt] = null;
        if (state.mkt === mkt) renderFocus(null);
      });
  }

  function refresh(forceFocus, opts) {
    opts = opts || {};
    var body = ensureMount();
    if (!body) return;
    var soft = !!opts.soft || !!state.last || !!body.querySelector('.ht-grid');
    if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-heat', soft, '更新中…');
    }
    if (!soft) body.innerHTML = '<div class="ht-loading">載入類股…</div>';
    fetch(SRV + '/sectors?mkt=' + encodeURIComponent(state.mkt), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        renderHeat(d || { sectors: [] });
        var cached = state.focusByMkt[state.mkt];
        if (forceFocus || !cached) loadFocus(!!forceFocus);
        else renderFocus(cached);
      })
      .catch(function () {
        var b = ensureMount();
        if (b && !soft) b.innerHTML = '<div class="ht-loading">載入失敗</div>';
      })
      .finally(function () {
        if (window.ShellV5 && window.ShellV5.softBadge) {
          window.ShellV5.softBadge('mount-heat', false);
        }
      });
  }

  function applyRouteOpts(opts) {
    opts = opts || {};
    var mktChanged = false;
    if (opts.mkt && (opts.mkt === 'TW' || opts.mkt === 'US') && opts.mkt !== state.mkt) {
      state.mkt = opts.mkt;
      mktChanged = true;
      syncMktButtons();
    }
    if (Object.prototype.hasOwnProperty.call(opts, 'sector') ||
        Object.prototype.hasOwnProperty.call(opts, 'sectorKey')) {
      state.sector = opts.sector || null;
      state.sectorKey = opts.sectorKey || (opts.sector ? sectorKey(opts.sector) : null);
    }
    return mktChanged;
  }

  function activate(opts) {
    opts = opts || {};
    var mktChanged = applyRouteOpts(opts);
    ensureMount();
    refresh(false, { soft: !!state.last && !mktChanged });
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'heat') {
        refresh(false, { soft: true });
      }
    }, 60000);
  }

  function deactivate() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  window.HeatV5 = {
    activate: activate,
    deactivate: deactivate,
    refresh: refresh,
    sectorKey: sectorKey,
    sectorKeysMatch: sectorKeysMatch
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'heat') {
      activate((ev.detail && ev.detail.opts) || {});
    }
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'heat') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 220); });
  else setTimeout(boot, 220);
})();
