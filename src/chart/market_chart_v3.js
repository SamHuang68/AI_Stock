// ============================================================
// Market Chart Module v3 — 總經 / 大盤折線圖（與個股 K 線完全隔離）
// ------------------------------------------------------------
// 設計目標：
//   1. 融資維持率、未來利率／利差／CPI 等「非 OHLC」序列，不走 candlestick
//      + SMA + 布林 + 量柱 pipeline。
//   2. 新增圖表只需 MarketChart.register({...})，不必改 stock_terminal.html。
//   3. 以最外層 hook 攔截 loadSym / renderChart / setRange / go，
//      即使其他模組後掛 K 線 patch，也會被定期重掛蓋過。
// ============================================================
(function MarketChartV3() {
  'use strict';

  const VER = '3.3.0';
  const LOG = (...a) => console.log('%c[MarketChart ' + VER + ']', 'color:#38BDF8;font-weight:700', ...a);
  const WARN = (...a) => console.warn('[MarketChart]', ...a);

  /** 美利率債等圖：序列視覺覆寫（線寬／虛線／面積） */
  const SERIES_STYLE = {
    '__US_RATES_CREDIT__': {
      fedfunds: { lineWidth: 2, lineStyle: 2, color: '#CBD5E1', lastValueVisible: true },
      us10y:    { lineWidth: 2.5, lineStyle: 0, color: '#FBBF24', lastValueVisible: true },
      baml_ig:  { lineWidth: 2, lineStyle: 0, color: '#38BDF8', lastValueVisible: true, area: true,
                  topColor: 'rgba(56,189,248,0.18)', bottomColor: 'rgba(56,189,248,0.01)' },
      baml_hy:  { lineWidth: 2, lineStyle: 0, color: '#FB7185', lastValueVisible: true, area: true,
                  topColor: 'rgba(251,113,133,0.16)', bottomColor: 'rgba(251,113,133,0.01)' },
      _axis: { left: '利率 %', right: '總報酬指數' },
      _subtitle: 'Fed／10Y（左） vs 美林 IG／HY 總報酬（右）',
    },
    '__US_CPI_FIN__': {
      us_cpi_yoy: { lineWidth: 1, color: '#7DD3FC' },
      fedfunds:   { lineWidth: 1, color: '#4ADE80' },
      xlf:        { lineWidth: 2.5, color: '#F59E0B', lastValueVisible: true },
      _axis: { left: '%', right: 'XLF' },
    },
    '__TW_RATES__': {
      discount: { lineWidth: 2.5, color: '#38BDF8', lastValueVisible: true },
      secured:  { lineWidth: 2, color: '#F87171' },
      short:    { lineWidth: 2, color: '#4ADE80' },
      _axis: { left: '利率 %', right: '' },
    },
    '__TW_MARGIN_MIX__': {
      yoy:  { lineWidth: 2.5, color: '#38BDF8', lastValueVisible: true },
      twii: { lineWidth: 1.5, color: '#F87171', lastValueVisible: true },
      _axis: { left: 'YoY %', right: '加權' },
    },
  };

  function hexToRgba(hex, a) {
    const h = String(hex || '').replace('#', '');
    if (h.length !== 6) return `rgba(56,189,248,${a})`;
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  const DENSITY_PRESETS = [
    { key: 'today',  label: '僅今日', tip: '只重抓最新一筆，不回補歷史' },
    { key: 'month',  label: '月抽樣', tip: '每 30 日一筆 · 約 8 年（預設）' },
    { key: 'biweek', label: '雙週',   tip: '每 14 日一筆 · 約 10 年' },
    { key: 'week',   label: '週抽樣', tip: '每 7 日一筆 · 約 12 年' },
    { key: 'day',    label: '日(最密)', tip: '每個交易日 · 約 5 年（較久）' },
  ];
  const DENSITY_LS = 'mc-track-density';

  function getDensity() {
    try {
      const v = localStorage.getItem(DENSITY_LS);
      if (v && DENSITY_PRESETS.some(p => p.key === v)) return v;
    } catch (e) {}
    return 'month';
  }
  function setDensity(key) {
    try { localStorage.setItem(DENSITY_LS, key); } catch (e) {}
  }

  function serverBase() {
    if (window.SERVER) return window.SERVER;
    if (typeof location !== 'undefined' && location.origin && location.origin !== 'null') return location.origin;
    return 'http://localhost:18432';
  }

  /**
   * @typedef {Object} MarketChartDef
   * @property {string} id
   * @property {string} name
   * @property {string} [shortName]
   * @property {'TW'|'US'} [market]
   * @property {string} [unit]
   * @property {string} [defaultRange]  e.g. 'max'
   * @property {string} [interval]      e.g. '1d'
   * @property {'area'|'line'} [style]
   * @property {string} [color]
   * @property {string} [topColor]
   * @property {string} [bottomColor]
   * @property {{symbol:string,name:string,color:string,priceScaleId?:string}|null} [dualAxis]
   * @property {{level:number,label:string,color:string}[]} [riskLines]
   * @property {(v:number)=>string} [valueFormat]
   * @property {string[]} [aliases]
   * @property {string} [yfPath]  override fetch path segment (default = id)
   */

  /** @type {Record<string, MarketChartDef>} */
  const REGISTRY = Object.create(null);

  /** @type {Record<string, string>} alias → id */
  const ALIAS = Object.create(null);

  function register(def) {
    if (!def || !def.id) throw new Error('MarketChart.register: id required');
    const id = String(def.id).toUpperCase();
    const copy = Object.assign({
      market: 'TW',
      unit: '',
      defaultRange: 'max',
      interval: '1d',
      style: 'area',
      color: '#38BDF8',
      topColor: 'rgba(56,189,248,0.22)',
      bottomColor: 'rgba(56,189,248,0.02)',
      dualAxis: null,
      riskLines: [],
      aliases: [],
      valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(2) : ''),
    }, def, { id });
    REGISTRY[id] = copy;
    ALIAS[id] = id;
    for (const a of (copy.aliases || [])) {
      ALIAS[String(a).toUpperCase().trim()] = id;
    }
    LOG('registered', id, copy.name);
    return copy;
  }

  function resolve(sym) {
    if (sym == null) return null;
    const raw = String(sym).trim();
    if (!raw) return null;
    const up = raw.toUpperCase();
    // 完整命中
    if (ALIAS[up]) return REGISTRY[ALIAS[up]];
    // 允許使用者打 __MARGIN_ / MARGIN_RATIO / 融資維持 等前綴
    for (const id of Object.keys(REGISTRY)) {
      if (up === id || id.startsWith(up) || up.startsWith(id.replace(/_+$/, ''))) {
        return REGISTRY[id];
      }
      const d = REGISTRY[id];
      if (d.shortName && up === String(d.shortName).toUpperCase()) return d;
      if (d.name && up === String(d.name).toUpperCase()) return d;
    }
    // 中文別名（不分大小寫無意義，直接比）
    for (const id of Object.keys(REGISTRY)) {
      const d = REGISTRY[id];
      for (const a of (d.aliases || [])) {
        if (raw === a || up === String(a).toUpperCase()) return d;
      }
    }
    return null;
  }

  function isMarketChart(sym) {
    return !!resolve(sym) || !!(window.S && resolve(S.sym));
  }

  // ── 內建：大盤融資維持率（MacroMicro 雙軸）─────────────────────
  register({
    id: '__MARGIN_RATIO__',
    name: '大盤融資維持率',
    shortName: '融資維持',
    market: 'TW',
    unit: '%',
    defaultRange: 'max',
    interval: '1d',
    style: 'area',
    color: '#38BDF8',
    topColor: 'rgba(56,189,248,0.22)',
    bottomColor: 'rgba(56,189,248,0.02)',
    dualAxis: {
      symbol: '^TWII',
      name: '加權指數',
      color: '#F59E0B',
      priceScaleId: 'right',
    },
    riskLines: [
      { level: 166, label: '門檻 166', color: '#38bdf8' },
      { level: 150, label: '偏弱 150', color: '#eab308' },
      { level: 140, label: '警戒 140', color: '#f97316' },
      { level: 130, label: '危險 130', color: '#ef4444' },
    ],
    valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(2) + '%' : ''),
    aliases: [
      '融資維持率', '大盤融資維持率', '融資維持',
      '__MARGIN__', '__MARGIN_RATIO', 'MARGIN_RATIO', 'MARGIN',
    ],
  });

  // ── MacroMicro 四組追蹤圖（多序列；資料走 /macro/chart/<id>）────
  register({
    id: '__TW_RATES__',
    name: '台灣指標利率',
    shortName: '台利率',
    market: 'TW',
    unit: '%',
    defaultRange: 'max',
    multi: true,
    endpoint: '/macro/chart/__TW_RATES__',
    years: 25,
    valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(3) + '%' : ''),
    aliases: ['台利率', '台灣指標利率', '重貼現率', 'TW_RATES'],
  });
  register({
    id: '__TW_MARGIN_MIX__',
    name: '上櫃／上市融資張數比年增',
    shortName: '融資比YoY',
    market: 'TW',
    unit: '%',
    defaultRange: 'max',
    multi: true,
    endpoint: '/macro/chart/__TW_MARGIN_MIX__',
    years: 20,
    valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(2) + '%' : ''),
    aliases: ['融資比', '融資比YoY', '上櫃上市融資', 'TW_MARGIN_MIX'],
  });
  register({
    id: '__US_RATES_CREDIT__',
    name: '美國利率 vs 公司債總報酬',
    shortName: '美利率債',
    market: 'US',
    unit: '%',
    defaultRange: 'max',
    multi: true,
    endpoint: '/macro/chart/__US_RATES_CREDIT__',
    years: 25,
    valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(2) : ''),
    aliases: ['美利率債', '公司債', 'BAML', 'US_RATES_CREDIT'],
  });
  register({
    id: '__US_CPI_FIN__',
    name: '美國CPI＆基準利率 vs 金融股',
    shortName: 'CPI金融',
    market: 'US',
    unit: '%',
    defaultRange: 'max',
    multi: true,
    endpoint: '/macro/chart/__US_CPI_FIN__',
    years: 20,
    valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(2) : ''),
    aliases: ['CPI金融', '金融股', 'US_CPI_FIN'],
  });

  // ── UI badge + 更新按鈕 + 浮動資訊窗（不畫在軸上）──────────
  function ensureBadge(def) {
    let el = document.getElementById('market-chart-badge');
    if (!el) {
      const host = document.getElementById('chart-wrap') || document.getElementById('left');
      if (!host) return;
      el = document.createElement('div');
      el.id = 'market-chart-badge';
      el.style.cssText = [
        'position:absolute', 'top:8px', 'right:12px', 'z-index:30',
        'padding:3px 8px', 'border-radius:3px',
        'font:10px/1.3 JetBrains Mono,ui-monospace,monospace',
        'color:#7dd3fc', 'background:rgba(8,15,30,.85)',
        'border:1px solid rgba(56,189,248,.45)', 'pointer-events:none',
      ].join(';');
      const wrap = document.getElementById('chart-wrap');
      if (wrap) {
        if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
        wrap.appendChild(el);
      } else {
        host.appendChild(el);
      }
    }
    el.textContent = 'MarketChart ' + VER + ' · 折線 · ' + (def ? def.shortName || def.name : '');
    el.style.display = def ? 'block' : 'none';
    ensureRefreshBtn(def);
  }

  /** 圖表右上角：密度選項 +「↻ 更新」— 免 CLI / curl */
  function ensureRefreshBtn(def) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap) return;
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';

    let bar = document.getElementById('market-chart-refresh-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'market-chart-refresh-bar';
      bar.style.cssText = [
        'position:absolute', 'top:8px', 'right:12px', 'z-index:31',
        'margin-top:22px', 'display:flex', 'align-items:center', 'gap:6px',
        'pointer-events:auto',
      ].join(';');

      const densWrap = document.createElement('label');
      densWrap.id = 'market-chart-density-wrap';
      densWrap.style.cssText = [
        'display:flex', 'align-items:center', 'gap:4px',
        'padding:3px 6px', 'border-radius:4px',
        'font:10px/1.2 JetBrains Mono,ui-monospace,monospace',
        'color:#94a3b8', 'background:rgba(14,30,55,.95)',
        'border:1px solid rgba(56,189,248,.35)',
      ].join(';');
      densWrap.innerHTML = '<span style="white-space:nowrap">密度</span>';
      const sel = document.createElement('select');
      sel.id = 'market-chart-density';
      sel.style.cssText = [
        'background:#0b1220', 'color:#e0f2fe', 'border:none',
        'font:10px/1.2 JetBrains Mono,ui-monospace,monospace',
        'padding:2px 2px', 'cursor:pointer', 'outline:none', 'max-width:88px',
      ].join(';');
      for (const p of DENSITY_PRESETS) {
        const opt = document.createElement('option');
        opt.value = p.key;
        opt.textContent = p.label;
        opt.title = p.tip;
        sel.appendChild(opt);
      }
      sel.value = getDensity();
      sel.addEventListener('change', () => {
        setDensity(sel.value);
        const tip = DENSITY_PRESETS.find(p => p.key === sel.value);
        sel.title = tip ? tip.tip : '';
        if (typeof setStat === 'function' && tip) setStat('密度：' + tip.label + ' · ' + tip.tip);
      });
      densWrap.appendChild(sel);
      bar.appendChild(densWrap);

      const btn = document.createElement('button');
      btn.id = 'market-chart-refresh';
      btn.type = 'button';
      btn.style.cssText = [
        'padding:4px 10px', 'border-radius:4px',
        'font:11px/1.2 JetBrains Mono,ui-monospace,monospace',
        'color:#e0f2fe', 'background:rgba(14,30,55,.95)',
        'border:1px solid rgba(56,189,248,.55)', 'cursor:pointer',
        'box-shadow:0 4px 14px rgba(0,0,0,.35)', 'white-space:nowrap',
      ].join(';');
      btn.title = '依左側密度重抓／回補此追蹤圖（免指令）';
      btn.textContent = '↻ 更新資料';
      btn.addEventListener('click', onRefreshClick);
      bar.appendChild(btn);

      wrap.appendChild(bar);
    }

    const btn = document.getElementById('market-chart-refresh');
    const densWrap = document.getElementById('market-chart-density-wrap');
    const sel = document.getElementById('market-chart-density');
    const show = !!(def && (def.multi || def.id === '__MARGIN_RATIO__'));
    bar.style.display = show ? 'flex' : 'none';
    if (!show) return;

    if (btn) {
      btn.disabled = false;
      btn.textContent = '↻ 更新資料';
      btn.dataset.chartId = def.id;
    }
    // 密度選項對融資比／全部追蹤有意義；其他圖仍顯示但僅今日有效
    if (densWrap) {
      const needsDensity = def.id === '__TW_MARGIN_MIX__' || def.id === '__MARGIN_RATIO__';
      densWrap.style.opacity = needsDensity ? '1' : '0.55';
      densWrap.title = needsDensity
        ? '融資比歷史回補抽樣密度'
        : '此圖主要重抓最新；密度選項在「融資比YoY」最有用';
    }
    if (sel) {
      sel.value = getDensity();
      const tip = DENSITY_PRESETS.find(p => p.key === sel.value);
      sel.title = tip ? tip.tip : '';
    }
  }

  function hideRefreshBtn() {
    const bar = document.getElementById('market-chart-refresh-bar');
    if (bar) bar.style.display = 'none';
    const btn = document.getElementById('market-chart-refresh');
    if (btn && !bar) btn.style.display = 'none';
  }

  async function onRefreshClick(ev) {
    const btn = (ev && ev.currentTarget) || document.getElementById('market-chart-refresh');
    if (!btn || btn.disabled) return;
    const id = btn.dataset.chartId || (window.S && S.sym) || '';
    const def = resolve(id);
    if (!def) return;
    const density = (document.getElementById('market-chart-density') || {}).value || getDensity();
    setDensity(density);
    const densMeta = DENSITY_PRESETS.find(p => p.key === density) || DENSITY_PRESETS[1];

    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = '更新中…';
    try {
      if (typeof setStat === 'function') {
        setStat('更新 ' + def.name + '…（密度：' + densMeta.label + '）');
      }
      if (def.id === '__MARGIN_RATIO__') {
        await fetch(serverBase() + '/margin_ratio?action=backfill&full=1', { cache: 'no-store' });
        btn.textContent = '已啟動回補';
      } else {
        const r = await fetch(serverBase() + '/macro/refresh/' + encodeURIComponent(def.id), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: def.id,
            density: density,
            dense: density !== 'today',
          }),
          cache: 'no-store',
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || (j && j.ok === false)) {
          throw new Error((j && j.error) || ('HTTP ' + r.status));
        }
        btn.textContent = j.started ? '背景回補中' : '✓ 已更新';
        if (typeof setStat === 'function') {
          const densNote = (j.density && j.density.label)
            ? (' · ' + j.density.label + (j.density.step ? '/每' + j.density.step + '日' : ''))
            : (' · ' + densMeta.label);
          setStat(j.started
            ? ('✓ ' + def.name + ' 已更新，歷史回補背景進行中' + densNote)
            : ('✓ ' + def.name + ' 已更新' + (j.count != null ? ' · ' + j.count + ' 筆' : '') + densNote));
        }
      }
      setTimeout(() => {
        load(def.id, { silent: true }).finally(() => {
          const b = document.getElementById('market-chart-refresh');
          if (b) {
            b.disabled = false;
            b.textContent = '↻ 更新資料';
          }
        });
      }, 600);
    } catch (e) {
      WARN('refresh failed', e);
      btn.textContent = '失敗';
      btn.disabled = false;
      if (typeof setStat === 'function') setStat('更新失敗 · ' + (e && e.message ? e.message : e));
      setTimeout(() => { if (btn) btn.textContent = prev || '↻ 更新資料'; }, 2500);
    }
  }

  function hideBadge() {
    const el = document.getElementById('market-chart-badge');
    if (el) el.style.display = 'none';
    hideRefreshBtn();
    hideFloat();
    hideSeriesPanel();
    hideAxisLabels();
  }

  function getSeriesVis(chartId) {
    try {
      const raw = localStorage.getItem(SERIES_VIS_LS + chartId);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return null;
  }
  function setSeriesVis(chartId, map) {
    try { localStorage.setItem(SERIES_VIS_LS + chartId, JSON.stringify(map)); } catch (e) {}
  }

  function hideSeriesPanel() {
    const el = document.getElementById('market-chart-series-panel');
    if (el) el.style.display = 'none';
  }

  function hideAxisLabels() {
    const el = document.getElementById('market-chart-axis-labels');
    if (el) el.style.display = 'none';
  }

  function ensureAxisLabels(def, stylePack) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap) return;
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
    let el = document.getElementById('market-chart-axis-labels');
    if (!el) {
      el = document.createElement('div');
      el.id = 'market-chart-axis-labels';
      wrap.appendChild(el);
    }
    const axis = (stylePack && stylePack._axis) || {};
    if (!axis.left && !axis.right) {
      el.style.display = 'none';
      return;
    }
    el.style.cssText = [
      'position:absolute', 'inset:0', 'z-index:12', 'pointer-events:none',
      'font:9px/1.2 JetBrains Mono,ui-monospace,monospace', 'color:#64748b',
    ].join(';');
    el.innerHTML =
      (axis.left
        ? `<div style="position:absolute;left:8px;top:48%;transform:translateY(-50%) rotate(-90deg);transform-origin:left center;letter-spacing:1px;white-space:nowrap">${axis.left}</div>`
        : '') +
      (axis.right
        ? `<div style="position:absolute;right:8px;top:48%;transform:translateY(-50%) rotate(90deg);transform-origin:right center;letter-spacing:1px;white-space:nowrap">${axis.right}</div>`
        : '');
    el.style.display = 'block';
  }

  /**
   * 多序列浮動面板：各指標獨立開關 + 全開／全關
   */
  function ensureSeriesPanel(def, apiSeries) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap || !def || !apiSeries || !apiSeries.length) {
      hideSeriesPanel();
      return;
    }
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';

    let panel = document.getElementById('market-chart-series-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'market-chart-series-panel';
      wrap.appendChild(panel);
    }
    panel.style.cssText = [
      'position:absolute', 'left:12px', 'bottom:14px', 'z-index:29',
      'min-width:210px', 'max-width:min(320px,78%)',
      'padding:8px 10px 10px', 'border-radius:8px',
      'font:11px/1.4 JetBrains Mono,ui-monospace,monospace',
      'color:#e2e8f0', 'background:rgba(6,12,22,.94)',
      'border:1px solid rgba(100,116,139,.45)',
      'box-shadow:0 10px 28px rgba(0,0,0,.5)',
      'backdrop-filter:blur(6px)', 'pointer-events:auto',
    ].join(';');

    const saved = getSeriesVis(def.id) || {};
    // 預設全開；若 localStorage 有值則沿用
    apiSeries.forEach(e => {
      const k = e.meta.key;
      const on = (saved[k] === undefined) ? true : !!saved[k];
      e.visible = on;
      try { e.seriesObj.applyOptions({ visible: on }); } catch (err) {}
    });

    const stylePack = SERIES_STYLE[def.id] || {};
    const subtitle = stylePack._subtitle
      ? `<div style="color:#64748b;font-size:9px;margin:2px 0 6px;line-height:1.35">${stylePack._subtitle}</div>`
      : '';

    let rows = '';
    for (const e of apiSeries) {
      const k = e.meta.key;
      const col = e.meta.color || '#94a3b8';
      const scale = e.meta.scale === 'right' ? 'R' : 'L';
      const checked = e.visible ? 'checked' : '';
      const lastStr = e.meta.unit === '%'
        ? Number(e.last).toFixed(2) + '%'
        : Number(e.last).toLocaleString('en-US', { maximumFractionDigits: 2 });
      rows +=
        `<label class="mc-series-row" data-key="${k}" style="display:flex;align-items:center;gap:7px;padding:3px 0;cursor:pointer;user-select:none;opacity:${e.visible ? 1 : 0.45}">` +
          `<input type="checkbox" data-series-key="${k}" ${checked} style="accent-color:${col};width:13px;height:13px;cursor:pointer;flex-shrink:0">` +
          `<span style="width:8px;height:8px;border-radius:2px;background:${col};flex-shrink:0;box-shadow:0 0 0 1px rgba(255,255,255,.12)"></span>` +
          `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:${e.visible ? '#e2e8f0' : '#64748b'}">${e.meta.name}</span>` +
          `<span style="color:#64748b;font-size:9px">${scale}</span>` +
          `<span class="mc-series-last" style="color:${col};font-size:10px;font-weight:700;min-width:52px;text-align:right">${lastStr}</span>` +
        `</label>`;
    }

    panel.innerHTML =
      `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:2px">` +
        `<div style="color:#94a3b8;font-size:10px;letter-spacing:.6px;font-weight:700">序列顯示</div>` +
        `<div style="display:flex;gap:4px">` +
          `<button type="button" data-mc-vis="all" style="padding:2px 7px;border-radius:4px;border:1px solid rgba(56,189,248,.45);background:rgba(14,30,55,.9);color:#7dd3fc;font:10px JetBrains Mono,monospace;cursor:pointer">全開</button>` +
          `<button type="button" data-mc-vis="none" style="padding:2px 7px;border-radius:4px;border:1px solid rgba(148,163,184,.35);background:rgba(14,20,35,.9);color:#94a3b8;font:10px JetBrains Mono,monospace;cursor:pointer">全關</button>` +
        `</div>` +
      `</div>` +
      subtitle +
      `<div style="border-top:1px solid rgba(148,163,184,.2);padding-top:4px">${rows}</div>`;

    panel.style.display = 'block';

    panel.onclick = function (ev) {
      const btn = ev.target && ev.target.closest && ev.target.closest('[data-mc-vis]');
      if (!btn) return;
      const mode = btn.getAttribute('data-mc-vis');
      const on = mode === 'all';
      const map = {};
      apiSeries.forEach(e => {
        e.visible = on;
        map[e.meta.key] = on;
        try { e.seriesObj.applyOptions({ visible: on }); } catch (err) {}
      });
      setSeriesVis(def.id, map);
      panel.querySelectorAll('input[data-series-key]').forEach(inp => {
        inp.checked = on;
        const row = inp.closest('.mc-series-row');
        if (row) {
          row.style.opacity = on ? '1' : '0.45';
          const nameEl = row.children[2];
          if (nameEl) nameEl.style.color = on ? '#e2e8f0' : '#64748b';
        }
      });
      syncRightScale(apiSeries);
    };

    panel.onchange = function (ev) {
      const t = ev.target;
      if (!t || !t.matches || !t.matches('input[data-series-key]')) return;
      const key = t.getAttribute('data-series-key');
      const entry = apiSeries.find(e => e.meta.key === key);
      if (!entry) return;
      entry.visible = !!t.checked;
      try { entry.seriesObj.applyOptions({ visible: entry.visible }); } catch (err) {}
      const map = {};
      apiSeries.forEach(e => { map[e.meta.key] = !!e.visible; });
      setSeriesVis(def.id, map);
      const row = t.closest('.mc-series-row');
      if (row) {
        row.style.opacity = entry.visible ? '1' : '0.45';
        const nameEl = row.children[2];
        if (nameEl) nameEl.style.color = entry.visible ? '#e2e8f0' : '#64748b';
      }
      syncRightScale(apiSeries);
    };

    if (window.S) S._marketApiSeries = apiSeries;
  }

  function syncRightScale(apiSeries) {
    if (!window.S || !S.chart) return;
    const anyRight = apiSeries.some(e => e.visible && e.meta.scale === 'right');
    const anyLeft = apiSeries.some(e => e.visible && e.meta.scale !== 'right');
    try {
      S.chart.applyOptions({
        rightPriceScale: { visible: anyRight },
        leftPriceScale: { visible: anyLeft || !anyRight },
      });
    } catch (e) {}
  }

  /** 圖內浮動資訊卡：十字游標／最新值／風險區 — 絕不使用軸上 label */
  function ensureFloat() {
    let el = document.getElementById('market-chart-float');
    if (el) return el;
    const wrap = document.getElementById('chart-wrap');
    if (!wrap) return null;
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
    el = document.createElement('div');
    el.id = 'market-chart-float';
    el.style.cssText = [
      'position:absolute', 'top:36px', 'left:12px', 'z-index:28',
      'min-width:200px', 'max-width:min(360px,70%)',
      'padding:8px 10px', 'border-radius:6px',
      'font:11px/1.45 JetBrains Mono,ui-monospace,monospace',
      'color:#e2e8f0', 'background:rgba(6,10,18,.92)',
      'border:1px solid rgba(56,189,248,.35)',
      'box-shadow:0 8px 24px rgba(0,0,0,.45)',
      'pointer-events:none', 'display:none',
    ].join(';');
    wrap.appendChild(el);
    return el;
  }

  function hideFloat() {
    const el = document.getElementById('market-chart-float');
    if (el) el.style.display = 'none';
  }

  function riskZoneFor(def, value) {
    const lines = (def && def.riskLines) ? def.riskLines.slice().sort((a, b) => b.level - a.level) : [];
    // 由高到低：高於最高門檻 = 正常；否則落在第一個 level >= value 的區間之下
    if (value == null || !isFinite(value) || !lines.length) return null;
    const sortedAsc = lines.slice().sort((a, b) => a.level - b.level);
    for (const z of sortedAsc) {
      if (value <= z.level) return z;
    }
    return { level: sortedAsc[sortedAsc.length - 1].level, label: '正常區', color: '#4ade80' };
  }

  function updateFloat(def, opts) {
    const el = ensureFloat();
    if (!el || !def) return;
    opts = opts || {};
    const value = opts.value;
    const prev = opts.prev;
    const dateStr = opts.dateStr;
    const dual = opts.dual;
    const zone = riskZoneFor(def, value);
    const delta = (prev != null && value != null) ? (value - prev) : null;
    const chgPct = (delta != null && prev > 0) ? (delta / prev * 100) : null;
    const up = delta != null && delta > 0;
    const dn = delta != null && delta < 0;
    const col = up ? '#f87171' : (dn ? '#4ade80' : '#94a3b8');

    let zonesHtml = '';
    for (const z of (def.riskLines || [])) {
      zonesHtml += `<span style="color:${z.color};margin-right:8px">― ${z.label}</span>`;
    }

    el.innerHTML =
      `<div style="color:#7dd3fc;font-weight:700;margin-bottom:4px">${def.name}</div>` +
      (dateStr ? `<div style="color:#94a3b8;margin-bottom:2px">${dateStr}</div>` : '') +
      `<div style="font-size:15px;font-weight:700;color:${col}">` +
        (value != null ? def.valueFormat(value) : '—') +
        (delta != null
          ? ` <span style="font-size:11px;font-weight:600">${up ? '+' : ''}${delta.toFixed(2)}${def.unit === '%' ? 'pp' : ''}` +
            (chgPct != null ? ` (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)` : '') + `</span>`
          : '') +
      `</div>` +
      (def.dualAxis && dual != null
        ? `<div style="margin-top:4px;color:${def.dualAxis.color}">${def.dualAxis.name}(R) ${Number(dual).toLocaleString('en-US', { maximumFractionDigits: 2 })}</div>`
        : '') +
      (zone
        ? `<div style="margin-top:6px;color:${zone.color};font-weight:700">◎ ${zone.label}${zone.level != null && zone.label !== '正常區' ? '' : (value != null && value > 166 ? '（>166%）' : '')}</div>`
        : '') +
      (zonesHtml
        ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(148,163,184,.25);font-size:10px;color:#94a3b8">風險線（僅圖內虛線，不佔軸）<br>${zonesHtml}</div>`
        : '') +
      (opts.extraHtml ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(148,163,184,.2)">${opts.extraHtml}</div>` : '');
    // 多序列圖：資訊卡靠右上，避開左下序列開關面板
    if (def && def.multi) {
      el.style.left = 'auto';
      el.style.right = '12px';
      el.style.top = '56px';
    } else {
      el.style.left = '12px';
      el.style.right = 'auto';
      el.style.top = '36px';
    }
    el.style.display = 'block';
  }

  function setHeader(def, last, prev) {
    try {
      const nEl = document.getElementById('ci-name');
      if (nEl) nEl.textContent = def.name;
      const pEl = document.getElementById('ci-price');
      if (pEl && last != null) pEl.textContent = def.valueFormat(last);
      const cEl = document.getElementById('ci-chg');
      if (cEl && last != null && prev != null && prev > 0) {
        const chg = (last - prev) / prev * 100;
        cEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
        const tw = def.market === 'TW';
        cEl.style.color = chg > 0 ? (tw ? 'var(--red)' : 'var(--green)')
                        : chg < 0 ? (tw ? 'var(--green)' : 'var(--red)')
                        : 'var(--thi)';
      }
      const inp = document.getElementById('syminput');
      if (inp) inp.value = def.id;
      const info = document.getElementById('chart-info');
      if (info) info.style.display = 'block';
      const loading = document.getElementById('chart-loading');
      if (loading) loading.style.display = 'none';
      // 隱藏舊的軸旁 OHLC 列，改走浮動窗
      const ohlcEl = document.getElementById('ci-ohlc');
      if (ohlcEl) ohlcEl.style.display = 'none';
    } catch (e) {}
  }

  function applyRiskLines(series, lines) {
    if (!series || typeof series.createPriceLine !== 'function' || !lines || !lines.length) return;
    const LS = (window.LightweightCharts && LightweightCharts.LineStyle)
      ? LightweightCharts.LineStyle.Dashed : 2;
    for (const z of lines) {
      try {
        // 只畫虛線，不在 Y 軸生成標籤／標題（避免蓋軸）
        series.createPriceLine({
          price: z.level,
          color: z.color || '#64748b',
          lineWidth: 1,
          lineStyle: LS,
          axisLabelVisible: false,
          title: '',
        });
      } catch (e) {}
    }
  }

  function renderLegend(def) {
    try {
      if (typeof renderChartLegend === 'function') renderChartLegend();
    } catch (e) {}
    // 若尚無 legend，補一個簡易列
    const lg = document.getElementById('chart-legend');
    if (!lg || !def) return;
    let h = `<div class="lg-row" style="color:${def.color}"><span class="lg-swatch" style="background:${def.color}"></span>${def.name} (L)</div>`;
    if (def.dualAxis) {
      h += `<div class="lg-row" style="color:${def.dualAxis.color}"><span class="lg-swatch" style="background:${def.dualAxis.color}"></span>${def.dualAxis.name} (R)</div>`;
    }
    for (const z of (def.riskLines || [])) {
      h += `<div class="lg-row" style="color:${z.color}"><span class="lg-dash" style="width:9px;border-color:${z.color}"></span>${z.label}</div>`;
    }
    lg.innerHTML = h;
  }

  /**
   * 純折線／面積渲染 — 絕不建立 CandlestickSeries
   */
  function render(def, points) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap) { WARN('no #chart-wrap'); return; }
    if (typeof LightweightCharts === 'undefined') { WARN('LightweightCharts missing'); return; }
    if (!points || !points.length) { WARN('no points'); return; }

    if (window.S && S.chart) {
      try { S.chart.remove(); } catch (e) {}
      S.chart = null;
    }

    const userTzOffset = -new Date().getTimezoneOffset() * 60;
    if (window.S) S.tzOffset = userTzOffset;
    const tz = (t) => (t == null ? t : t + userTzOffset);
    const loadId = window.__loadSeq;
    const hasDual = !!(def.dualAxis && def.dualAxis.symbol);

    const chart = LightweightCharts.createChart(wrap, {
      width: wrap.clientWidth,
      height: wrap.clientHeight,
      layout: { background: { color: '#060A12' }, textColor: '#5A6A82' },
      grid: { vertLines: { color: '#0F1A2B' }, horzLines: { color: '#0F1A2B' } },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Magnet,
        // 軸上不顯示十字游標數值泡泡（改走左上浮動窗）
        vertLine: { color: 'rgba(245,197,24,.45)', width: 1, style: 2, labelVisible: false },
        horzLine: { color: 'rgba(245,197,24,.45)', width: 1, style: 2, labelVisible: false },
      },
      leftPriceScale: {
        visible: true,
        borderColor: '#1A2740',
        scaleMargins: { top: 0.10, bottom: 0.12 },
      },
      rightPriceScale: {
        visible: hasDual,
        borderColor: '#1A2740',
        scaleMargins: { top: 0.10, bottom: 0.12 },
      },
      timeScale: {
        borderColor: '#1A2740',
        timeVisible: false,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 2,
        minBarSpacing: 0.5,
        fixLeftEdge: true,
        fixRightEdge: true,
        lockVisibleTimeRangeOnResize: true,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
    });

    if (window.S) {
      S.chart = chart;
      S.volSeries = null;
      S.overlaySeries = {};
      S.wsSeries = null;
      S.wsLeftSeries = null;
      S.twiiSeries = null;
      S._prevLine = null;
      S._marketChartId = def.id;
      S._marginMacroChart = (def.id === '__MARGIN_RATIO__');
    }

    const lineData = points.map(p => ({ time: tz(p.time), value: p.value }));
    let primary;
    if (def.style === 'line') {
      primary = chart.addLineSeries({
        priceScaleId: 'left',
        color: def.color,
        lineWidth: 2,
        lastValueVisible: false,   // 不在軸上貼現價標籤
        priceLineVisible: false,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 5,
        priceFormat: { type: 'custom', formatter: def.valueFormat },
      });
    } else {
      primary = chart.addAreaSeries({
        priceScaleId: 'left',
        lineColor: def.color,
        topColor: def.topColor,
        bottomColor: def.bottomColor,
        lineWidth: 2,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 5,
        crosshairMarkerBorderColor: '#7DD3FC',
        crosshairMarkerBackgroundColor: def.color,
        priceFormat: { type: 'custom', formatter: def.valueFormat },
      });
    }
    primary.setData(lineData);
    if (window.S) {
      S.chartSeries = primary;
      S.dotSeries = primary;
    }
    applyRiskLines(primary, def.riskLines);

    const prevByTime = new Map();
    for (let i = 0; i < points.length; i++) {
      prevByTime.set(tz(points[i].time), i > 0 ? points[i - 1].value : null);
    }
    const dualByTime = new Map();

    chart.subscribeCrosshairMove(param => {
      // 軸上 OHLC 列關閉；資訊只進浮動窗
      const ohlcEl = document.getElementById('ci-ohlc');
      if (ohlcEl) ohlcEl.style.display = 'none';

      if (!param || !param.point || !param.time || !param.seriesData) {
        // 游標離開：回到最新值
        const last = points[points.length - 1];
        const prev = points.length >= 2 ? points[points.length - 2].value : null;
        updateFloat(def, {
          value: last.value,
          prev,
          dateStr: null,
          dual: dualByTime.get(tz(last.time)),
        });
        return;
      }
      const pt = param.seriesData.get(primary);
      if (!pt || pt.value == null) return;
      const d = new Date(typeof param.time === 'number' ? param.time * 1000 : Date.parse(param.time));
      const ds = `${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`;
      updateFloat(def, {
        value: pt.value,
        prev: prevByTime.get(param.time),
        dateStr: ds,
        dual: dualByTime.get(param.time),
      });
    });

    // 右軸對照序列（如加權）
    if (hasDual) {
      (async () => {
        try {
          const range = (window.S && S.range) || def.defaultRange || 'max';
          const url = `${serverBase()}/yf/${encodeURIComponent(def.dualAxis.symbol)}?range=${encodeURIComponent(range)}&interval=1d`;
          const r = await fetch(url, { cache: 'no-store' });
          if (!r.ok) return;
          const raw = await r.json();
          if (loadId !== window.__loadSeq || !window.S || S.sym !== def.id || S.chart !== chart) return;
          const res = raw && raw.chart && raw.chart.result && raw.chart.result[0];
          if (!res) return;
          const q = (res.indicators && res.indicators.quote && res.indicators.quote[0]) || {};
          const ts = res.timestamp || [];
          const dualData = [];
          for (let i = 0; i < ts.length; i++) {
            const c = q.close && q.close[i];
            if (c != null && isFinite(c) && c > 0) {
              const t = tz(ts[i]);
              dualData.push({ time: t, value: c });
              dualByTime.set(t, c);
            }
          }
          if (!dualData.length) return;
          const dualLine = chart.addLineSeries({
            priceScaleId: def.dualAxis.priceScaleId || 'right',
            color: def.dualAxis.color,
            lineWidth: 1.5,
            lastValueVisible: false,  // 不在右軸貼現價標籤
            priceLineVisible: false,
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 4,
            priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
          });
          dualLine.setData(dualData);
          if (window.S) {
            S.twiiSeries = dualLine;
            S.overlaySeries = Object.assign({}, S.overlaySeries, { dual: dualLine });
          }
          renderLegend(def);
        } catch (e) {
          WARN('dual axis failed', e);
        }
      })();
    }

    ensureBadge(def);
    renderLegend(def);
    const lastPt = points[points.length - 1];
    const prevPt = points.length >= 2 ? points[points.length - 2].value : null;
    setHeader(def, lastPt.value, prevPt);
    updateFloat(def, { value: lastPt.value, prev: prevPt, dateStr: null, dual: null });

    requestAnimationFrame(() => {
      try { chart.timeScale().fitContent(); } catch (e) {}
    });
    if (!wrap._mcRo) {
      wrap._mcRo = new ResizeObserver(() => {
        if (!window.S || !S.chart || !S._marketChartId) return;
        try {
          S.chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
          S.chart.timeScale().fitContent();
        } catch (e) {}
      });
      wrap._mcRo.observe(wrap);
    }

    LOG('rendered', def.id, points.length, 'pts · float panel · NO axis labels');
  }

  function dateToUnix(dstr) {
    try {
      const d = new Date(dstr + 'T00:00:00Z');
      return Math.floor(d.getTime() / 1000);
    } catch (e) { return null; }
  }

  /**
   * 多序列 MacroMicro 風格渲染（左／右軸、折線／柱狀／面積）
   * @param {object} def MarketChart def
   * @param {object} payload /macro/chart 回應
   */
  function renderMulti(def, payload) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap || typeof LightweightCharts === 'undefined') { WARN('no chart env'); return; }
    const seriesList = (payload && payload.series) || [];
    if (!seriesList.length) { WARN('no series in payload'); return; }

    if (window.S && S.chart) {
      try { S.chart.remove(); } catch (e) {}
      S.chart = null;
    }

    const userTzOffset = -new Date().getTimezoneOffset() * 60;
    if (window.S) S.tzOffset = userTzOffset;
    const tz = (t) => (t == null ? t : t + userTzOffset);
    const hasRight = seriesList.some(s => s.scale === 'right' && (s.points || []).length);
    const stylePack = SERIES_STYLE[def.id] || {};
    const LineStyle = (LightweightCharts.LineStyle) || { Solid: 0, Dotted: 1, Dashed: 2 };

    const chart = LightweightCharts.createChart(wrap, {
      width: wrap.clientWidth,
      height: wrap.clientHeight,
      layout: {
        background: { color: '#070B14' },
        textColor: '#64748b',
        fontFamily: "JetBrains Mono, ui-monospace, Menlo, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(30,41,59,.55)', style: LineStyle.Dotted },
        horzLines: { color: 'rgba(30,41,59,.55)', style: LineStyle.Dotted },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Magnet,
        vertLine: {
          color: 'rgba(148,163,184,.45)', width: 1, style: LineStyle.Dashed,
          labelVisible: true, labelBackgroundColor: '#1e293b',
        },
        horzLine: {
          color: 'rgba(148,163,184,.35)', width: 1, style: LineStyle.Dashed,
          labelVisible: true, labelBackgroundColor: '#1e293b',
        },
      },
      leftPriceScale: {
        visible: true, borderColor: 'rgba(51,65,85,.8)',
        scaleMargins: { top: 0.08, bottom: 0.10 },
        entireTextOnly: true,
      },
      rightPriceScale: {
        visible: hasRight, borderColor: 'rgba(51,65,85,.8)',
        scaleMargins: { top: 0.08, bottom: 0.10 },
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: 'rgba(51,65,85,.8)', timeVisible: false, secondsVisible: false,
        rightOffset: 10, barSpacing: 3, minBarSpacing: 0.5,
        fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
    });

    if (window.S) {
      S.chart = chart;
      S.volSeries = null;
      S.overlaySeries = {};
      S._marketChartId = def.id;
      S._marginMacroChart = false;
      S._marketMulti = true;
    }

    const apiSeries = []; // {meta, seriesObj, byTime, visible, last, prev}
    let primaryApi = null;

    for (const s of seriesList) {
      const pts = s.points || [];
      if (!pts.length) continue;
      const lineData = [];
      const byTime = new Map();
      for (const p of pts) {
        const u = dateToUnix(p.date);
        if (u == null || p.value == null || !isFinite(p.value)) continue;
        const t = tz(u);
        lineData.push({ time: t, value: p.value });
        byTime.set(t, p.value);
      }
      if (!lineData.length) continue;

      const scaleId = s.scale === 'right' ? 'right' : 'left';
      const ov = stylePack[s.key] || {};
      const color = ov.color || s.color || '#38BDF8';
      const isHist = s.style === 'histogram' || s.style === 'bar';
      const useArea = !!(ov.area) && !isHist;
      let obj;
      const fmt = s.unit === '%'
        ? { type: 'custom', formatter: v => (v != null && isFinite(v) ? v.toFixed(2) + '%' : '') }
        : { type: 'price', precision: 2, minMove: 0.01 };
      const showLast = ov.lastValueVisible !== false;

      if (isHist) {
        obj = chart.addHistogramSeries({
          priceScaleId: scaleId,
          color: color,
          base: 0,
          lastValueVisible: !!ov.lastValueVisible,
          priceLineVisible: false,
          priceFormat: fmt,
        });
      } else if (useArea && typeof chart.addAreaSeries === 'function') {
        obj = chart.addAreaSeries({
          priceScaleId: scaleId,
          lineColor: color,
          topColor: ov.topColor || hexToRgba(color, 0.18),
          bottomColor: ov.bottomColor || hexToRgba(color, 0.01),
          lineWidth: ov.lineWidth != null ? ov.lineWidth : 2,
          lastValueVisible: showLast,
          priceLineVisible: false,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
          priceFormat: fmt,
        });
      } else {
        const ls = {
          priceScaleId: scaleId,
          color: color,
          lineWidth: ov.lineWidth != null ? ov.lineWidth : (scaleId === 'right' ? 1.75 : 2.25),
          lastValueVisible: showLast,
          priceLineVisible: false,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
          priceFormat: fmt,
        };
        if (ov.lineStyle != null && LineStyle) {
          ls.lineStyle = ov.lineStyle;
        }
        obj = chart.addLineSeries(ls);
      }
      // 覆寫 meta 色（面板／圖例一致）
      s.color = color;
      obj.setData(lineData);
      const entry = {
        meta: s, seriesObj: obj, byTime, visible: true,
        last: lineData[lineData.length - 1].value,
        prev: lineData.length >= 2 ? lineData[lineData.length - 2].value : null,
      };
      apiSeries.push(entry);
      if (!primaryApi && scaleId === 'left') primaryApi = entry;
      if (window.S) S.overlaySeries[s.key] = obj;
    }

    if (!primaryApi && apiSeries.length) primaryApi = apiSeries[0];
    if (window.S && primaryApi) {
      S.chartSeries = primaryApi.seriesObj;
      S.dotSeries = primaryApi.seriesObj;
    }

    // legend（右側簡列，詳細操作改走浮動面板）
    const lg = document.getElementById('chart-legend');
    if (lg) {
      lg.innerHTML = apiSeries.map(e =>
        `<div class="lg-row" style="color:${e.meta.color}"><span class="lg-swatch" style="background:${e.meta.color}"></span>${e.meta.name} (${e.meta.scale === 'right' ? 'R' : 'L'})</div>`
      ).join('');
    }

    function visibleRowsHtml(atTime) {
      const rows = [];
      for (const e of apiSeries) {
        if (!e.visible) continue;
        const val = (atTime != null && e.byTime.has(atTime)) ? e.byTime.get(atTime) : e.last;
        if (val == null) continue;
        rows.push(`<div style="display:flex;justify-content:space-between;gap:12px;color:${e.meta.color};margin-top:2px">` +
          `<span>${e.meta.name}</span>` +
          `<span style="font-weight:700">${e.meta.unit === '%' ? Number(val).toFixed(2) + '%' : Number(val).toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>` +
          `</div>`);
      }
      return rows.join('');
    }

    chart.subscribeCrosshairMove(param => {
      const ohlcEl = document.getElementById('ci-ohlc');
      if (ohlcEl) ohlcEl.style.display = 'none';
      if (!param || !param.point || !param.time || !param.seriesData) {
        if (primaryApi) {
          updateFloat(def, {
            value: primaryApi.last,
            prev: primaryApi.prev,
            dateStr: null,
            dual: null,
            extraHtml: visibleRowsHtml(null),
          });
        }
        return;
      }
      const d = new Date(typeof param.time === 'number' ? param.time * 1000 : Date.parse(param.time));
      const ds = `${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`;
      let primVal = null;
      const rows = [];
      for (const e of apiSeries) {
        if (!e.visible) continue;
        const pt = param.seriesData.get(e.seriesObj);
        const v = pt && pt.value != null ? pt.value : e.byTime.get(param.time);
        if (v == null) continue;
        if (e === primaryApi) primVal = v;
        rows.push(`<div style="display:flex;justify-content:space-between;gap:12px;color:${e.meta.color};margin-top:2px">` +
          `<span>${e.meta.name}</span>` +
          `<span style="font-weight:700">${e.meta.unit === '%' ? Number(v).toFixed(2) + '%' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>` +
          `</div>`);
      }
      updateFloat(def, {
        value: primVal != null ? primVal : (primaryApi && primaryApi.last),
        prev: null,
        dateStr: ds,
        dual: null,
        extraHtml: rows.join(''),
      });
    });

    ensureBadge(def);
    ensureAxisLabels(def, stylePack);
    ensureSeriesPanel(def, apiSeries);

    if (primaryApi) {
      setHeader(def, primaryApi.last, primaryApi.prev);
      updateFloat(def, {
        value: primaryApi.last,
        prev: primaryApi.prev,
        extraHtml: (stylePack._subtitle
          ? `<div style="color:#64748b;font-size:9px;margin-bottom:4px">${stylePack._subtitle}</div>`
          : '') + visibleRowsHtml(null),
      });
    }

    if (window.S && primaryApi) {
      const primMeta = primaryApi.meta;
      const candles2 = (primMeta.points || []).map(p => {
        const u = dateToUnix(p.date);
        return { time: u, open: p.value, high: p.value, low: p.value, close: p.value, volume: 0 };
      }).filter(c => c.time != null);
      S.data = { candles: candles2, name: def.name };
    }

    requestAnimationFrame(() => { try { chart.timeScale().fitContent(); } catch (e) {} });
    if (!wrap._mcRo) {
      wrap._mcRo = new ResizeObserver(() => {
        if (!window.S || !S.chart || !S._marketChartId) return;
        try {
          S.chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
          S.chart.timeScale().fitContent();
        } catch (e) {}
      });
      wrap._mcRo.observe(wrap);
    }
    LOG('rendered MULTI', def.id, apiSeries.map(e => e.meta.key + ':' + e.byTime.size).join(', '));
  }

  function pointsFromYF(raw) {
    try {
      const res = raw && raw.chart && raw.chart.result && raw.chart.result[0];
      if (!res) return [];
      const q = (res.indicators && res.indicators.quote && res.indicators.quote[0]) || {};
      const ts = res.timestamp || [];
      const out = [];
      for (let i = 0; i < ts.length; i++) {
        const c = q.close && q.close[i];
        if (c != null && isFinite(c) && c > 0) out.push({ time: ts[i], value: c });
      }
      return out;
    } catch (e) {
      return [];
    }
  }

  /**
   * 完整載入流程 — 不呼叫個股 loadSym 內的 K 線／指標路徑
   */
  async function load(symOrId, opts) {
    opts = opts || {};
    const def = resolve(symOrId);
    if (!def) return false;

    window.__loadSeq = (window.__loadSeq || 0) + 1;
    const myLoad = window.__loadSeq;

    if (!window.S) window.S = {};
    S.sym = def.id;
    S.mkt = def.market || 'TW';
    S.range = opts.range || def.defaultRange || 'max';
    S.ind = null;
    S._marketChartId = def.id;

    try {
      if (typeof setMktUI === 'function') setMktUI(S.mkt);
      if (typeof renderRangeBar === 'function') renderRangeBar();
      if (typeof clearInd === 'function') clearInd();
    } catch (e) {}

    if (!opts.silent) {
      try {
        if (typeof setStat === 'function') setStat('載入 ' + def.name + '…');
        const loading = document.getElementById('chart-loading');
        if (loading) {
          loading.style.display = 'flex';
          loading.textContent = '載入 ' + def.name + '（MarketChart 折線）…';
        }
        const info = document.getElementById('chart-info');
        if (info) info.style.display = 'none';
      } catch (e) {}
    }

    // 多序列追蹤圖：走 /macro/chart/<id>
    if (def.multi && def.endpoint) {
      const years = def.years || 20;
      const url = `${serverBase()}${def.endpoint}?years=${years}`;
      try {
        const r = await fetch(url, { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const payload = await r.json();
        if (myLoad !== window.__loadSeq) return false;
        renderMulti(def, payload);
        try {
          if (typeof renderRpanel === 'function') renderRpanel();
        } catch (e) {}
        try {
          window.dispatchEvent(new CustomEvent('symLoaded', { detail: { sym: def.id, mkt: S.mkt, marketChart: true, multi: true } }));
        } catch (e) {}
        try {
          if (typeof setStat === 'function') setStat('OK · MarketChart · ' + def.id);
        } catch (e) {}
        return true;
      } catch (e) {
        WARN('multi fetch failed', url, e);
        try {
          const loading = document.getElementById('chart-loading');
          if (loading) { loading.style.display = 'flex'; loading.textContent = '載入失敗'; }
          if (typeof setStat === 'function') setStat('載入失敗 · ' + def.id);
        } catch (e2) {}
        return false;
      }
    }

    const path = def.yfPath || def.id;
    const url = `${serverBase()}/yf/${encodeURIComponent(path)}?range=${encodeURIComponent(S.range)}&interval=${encodeURIComponent(def.interval || '1d')}`;
    let raw = null;
    try {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      raw = await r.json();
    } catch (e) {
      WARN('fetch failed', url, e);
      try {
        const loading = document.getElementById('chart-loading');
        if (loading) { loading.style.display = 'flex'; loading.textContent = '載入失敗'; }
        if (typeof setStat === 'function') setStat('載入失敗 · ' + def.id);
      } catch (e2) {}
      return false;
    }
    if (myLoad !== window.__loadSeq) return false;

    const points = pointsFromYF(raw);
    if (!points.length) {
      try {
        const loading = document.getElementById('chart-loading');
        if (loading) { loading.style.display = 'flex'; loading.textContent = '無資料'; }
        if (typeof setStat === 'function') setStat('無資料 · ' + def.id);
      } catch (e) {}
      return false;
    }

    // 轉成舊 pipeline 相容的 candles（僅 close；供其他面板讀 S.data）
    const candles = points.map(p => ({
      time: p.time, open: p.value, high: p.value, low: p.value, close: p.value, volume: 0,
    }));
    S.data = { candles, name: def.name, meta: (raw.chart && raw.chart.result && raw.chart.result[0] && raw.chart.result[0].meta) || {} };

    render(def, points);

    try {
      if (typeof renderRpanel === 'function') renderRpanel();
    } catch (e) {}
    try {
      window.dispatchEvent(new CustomEvent('symLoaded', { detail: { sym: def.id, mkt: S.mkt, marketChart: true } }));
    } catch (e) {}
    try {
      if (typeof setStat === 'function') setStat('OK · MarketChart · ' + def.id);
    } catch (e) {}
    return true;
  }

  // ── Hooks：攔截個股 K 線入口 ───────────────────────────────────
  let _hookInstalled = false;
  let _innerLoadSym = null;
  let _innerRenderChart = null;
  let _innerSetRange = null;
  let _innerGo = null;

  function wrapLoadSym() {
    if (typeof window.loadSym !== 'function') return false;
    if (window.loadSym._marketChartWrapped) return true;
    _innerLoadSym = window.loadSym;
    async function mcLoadSym(sym, mkt, silent) {
      const def = resolve(sym);
      if (def) {
        LOG('intercept loadSym → MarketChart', def.id);
        return load(def.id, { silent: !!silent });
      }
      if (window.S) S._marketChartId = null;
      hideBadge();
      return _innerLoadSym.apply(this, arguments);
    }
    mcLoadSym._marketChartWrapped = true;
    window.loadSym = mcLoadSym;
    return true;
  }

  function wrapRenderChart() {
    if (typeof window.renderChart !== 'function') return false;
    // 永遠重掛成最外層
    const current = window.renderChart;
    if (current._marketChartOuter) return true;
    _innerRenderChart = current;
    function mcRenderChart(candles) {
      const def = (window.S && resolve(S.sym)) || null;
      if (def) {
        LOG('intercept renderChart → MarketChart', def.id);
        const pts = (candles && candles.length)
          ? candles.map(c => ({ time: c.time, value: c.close }))
          : ((S.data && S.data.candles) || []).map(c => ({ time: c.time, value: c.close }));
        render(def, pts);
        return;
      }
      if (window.S) S._marketChartId = null;
      hideBadge();
      return _innerRenderChart.apply(this, arguments);
    }
    mcRenderChart._marketChartOuter = true;
    window.renderChart = mcRenderChart;
    return true;
  }

  function wrapSetRange() {
    if (typeof window.setRange !== 'function') return false;
    if (window.setRange._marketChartWrapped) return true;
    _innerSetRange = window.setRange;
    function mcSetRange(key) {
      if (window.S && resolve(S.sym)) {
        if (S.range === key) return;
        S.range = key;
        try { if (typeof renderRangeBar === 'function') renderRangeBar(); } catch (e) {}
        return load(S.sym, { range: key });
      }
      return _innerSetRange.apply(this, arguments);
    }
    mcSetRange._marketChartWrapped = true;
    window.setRange = mcSetRange;
    return true;
  }

  function wrapGo() {
    if (typeof window.go !== 'function') return false;
    if (window.go._marketChartWrapped) return true;
    _innerGo = window.go;
    function mcGo() {
      const sym = (document.getElementById('syminput')?.value || '').trim();
      const def = resolve(sym);
      if (def) {
        if (document.getElementById('syminput')) document.getElementById('syminput').value = def.id;
        return load(def.id);
      }
      return _innerGo.apply(this, arguments);
    }
    mcGo._marketChartWrapped = true;
    window.go = mcGo;
    return true;
  }

  function installHooks() {
    const a = wrapLoadSym();
    const b = wrapRenderChart();
    const c = wrapSetRange();
    const d = wrapGo();
    // renderChart 可能被其他模組再次 wrap → 每次強制搶回最外層
    if (typeof window.renderChart === 'function' && !window.renderChart._marketChartOuter) {
      wrapRenderChart();
    }
    if (a || b || c || d) {
      if (!_hookInstalled) {
        _hookInstalled = true;
        LOG('hooks installed');
      }
    }
    return a && b;
  }

  // 啟動：等核心函式出現後掛鉤，並定期維持最外層
  (function boot() {
    let tries = 0;
    function tick() {
      tries++;
      installHooks();
      if (tries < 40) setTimeout(tick, 150);
    }
    tick();
    setInterval(installHooks, 1500);
  })();

  window.MarketChart = {
    version: VER,
    registry: REGISTRY,
    register,
    resolve,
    isMarketChart,
    load,
    render,
    renderMulti,
    ensureBadge,
    refresh: function (id) {
      const btn = document.getElementById('market-chart-refresh');
      if (btn && id) btn.dataset.chartId = id;
      return onRefreshClick({ currentTarget: btn });
    },
  };

  LOG('module ready — register() more series as needed');
})();
