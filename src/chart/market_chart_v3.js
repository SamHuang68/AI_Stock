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

  const VER = '3.6.0';
  const LOG = (...a) => console.log('%c[MarketChart ' + VER + ']', 'color:#64748b', ...a);
  const WARN = (...a) => console.warn('[MarketChart]', ...a);
  const VIEW_MODE_LS = 'mc-view-mode';
  /** 美風險圖預設「對齊」基準 100；其他多序列預設原始 */
  function defaultViewMode(defId) {
    const id = String(defId || '').toUpperCase();
    if (id === '__US_RATES_CREDIT__' || id === '__US_CPI_FIN__') return 'rebase';
    return 'raw';
  }
  function getViewMode(defId) {
    try {
      const all = JSON.parse(localStorage.getItem(VIEW_MODE_LS) || '{}');
      const v = all[String(defId || '').toUpperCase()];
      if (v === 'rebase' || v === 'raw') return v;
    } catch (e) {}
    return defaultViewMode(defId);
  }
  function setViewMode(defId, mode) {
    try {
      const all = JSON.parse(localStorage.getItem(VIEW_MODE_LS) || '{}');
      all[String(defId || '').toUpperCase()] = mode;
      localStorage.setItem(VIEW_MODE_LS, JSON.stringify(all));
    } catch (e) {}
  }
  /** 各序列以第一筆有效值為 100 對齊（相對趨勢） */
  function rebaseSeriesList(seriesList) {
    return (seriesList || []).map(s => {
      const pts = s.points || [];
      let base = null;
      for (const p of pts) {
        if (p && p.value != null && isFinite(p.value) && Number(p.value) !== 0) {
          base = Number(p.value);
          break;
        }
      }
      if (base == null) {
        return Object.assign({}, s, { points: pts.slice(), _rebased: false, _base: null });
      }
      const next = pts.map(p => {
        if (!p || p.value == null || !isFinite(p.value)) return p;
        return { date: p.date, value: (Number(p.value) / base) * 100 };
      });
      return Object.assign({}, s, {
        points: next,
        unit: '', // 對齊後為指數 100
        _rebased: true,
        _base: base,
        _rawUnit: s.unit,
      });
    });
  }

  /**
   * 專業終端配色（低飽和、細線、無面積填色）
   * 參考 Bloomberg / TradingView 總經圖慣例：利率左軸、指數右軸。
   */
  const SERIES_STYLE = {
    '__US_RATES_CREDIT__': {
      fedfunds: { lineWidth: 1.5, lineStyle: 2, color: '#94A3B8', lastValueVisible: false },
      us10y:    { lineWidth: 2,   lineStyle: 0, color: '#D4A574', lastValueVisible: false },
      baml_ig:  { lineWidth: 1.75, lineStyle: 0, color: '#6B9BB8', lastValueVisible: false },
      baml_hy:  { lineWidth: 1.75, lineStyle: 0, color: '#B89595', lastValueVisible: false },
      _axis: { left: 'L · %', right: 'R · Index' },
      _shortNames: { fedfunds: 'Fed', us10y: '10Y', baml_ig: 'IG', baml_hy: 'HY' },
    },
    '__US_CPI_FIN__': {
      us_cpi_yoy: { lineWidth: 1.5, color: '#7A9EB8' },
      fedfunds:   { lineWidth: 1.5, lineStyle: 2, color: '#8FA88F' },
      xlf:        { lineWidth: 2, color: '#C4A35A', lastValueVisible: false },
      _axis: { left: 'L · %', right: 'R · XLF' },
      _shortNames: { us_cpi_yoy: 'CPI', fedfunds: 'Fed', xlf: 'XLF' },
    },
    '__TW_RATES__': {
      discount: { lineWidth: 2, color: '#6B9BB8', lastValueVisible: false },
      secured:  { lineWidth: 1.5, color: '#B89595' },
      short:    { lineWidth: 1.5, color: '#8FA88F' },
      _axis: { left: 'L · %', right: '' },
      _shortNames: { discount: '重貼', secured: '擔保', short: '短融' },
    },
    '__TW_MARGIN_MIX__': {
      yoy:  { lineWidth: 2, color: '#6B9BB8', lastValueVisible: false },
      twii: { lineWidth: 1.5, color: '#B89595', lastValueVisible: false },
      _axis: { left: 'L · YoY%', right: 'R · 加權' },
      _shortNames: { yoy: '融資比', twii: '加權' },
    },
    '__TW_MARGIN_CYCLE__': {
      margin_ratio: { lineWidth: 2.25, color: '#6B9BB8', lastValueVisible: false },
      twii:         { lineWidth: 1.5, color: '#D4A574', lastValueVisible: false },
      margin_yoy:   { lineWidth: 1.25, lineStyle: 2, color: '#B89595', lastValueVisible: false },
      ss_ratio:     { lineWidth: 1.25, lineStyle: 2, color: '#8FA88F', lastValueVisible: false },
      _axis: { left: 'L · 維持率%', right: 'R · 加權' },
      _shortNames: { margin_ratio: '維持率', twii: '加權', margin_yoy: '餘額YoY', ss_ratio: '券資比' },
      _defaultOff: ['margin_yoy', 'ss_ratio'],
    },
    '__HOLDERS__': {
      holders:   { lineWidth: 1, color: '#6B9BB8' },
      major_pct: { lineWidth: 2, color: '#D4A574', lastValueVisible: false },
      _axis: { left: 'L · 人數', right: 'R · 大股東%' },
      _shortNames: { holders: '人數', major_pct: '大股東' },
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

  function parseHoldersCode(sym) {
    const up = String(sym || '').trim().toUpperCase();
    let m = up.match(/^__HOLDERS_([0-9A-Z]{4,6})__$/);
    if (m) return m[1];
    m = up.match(/^HOLDERS[:\/]([0-9A-Z]{4,6})$/);
    if (m) return m[1];
    return null;
  }

  function holdersDef(code) {
    const c = String(code).toUpperCase();
    return {
      id: `__HOLDERS_${c}__`,
      name: `${c} 籌碼集中度`,
      shortName: `${c}集中`,
      market: 'TW',
      unit: '',
      defaultRange: 'max',
      multi: true,
      endpoint: `/holders/chart/${c}`,
      holdersCode: c,
      valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }) : ''),
      aliases: [`集中${c}`, `holders:${c}`],
    };
  }

  function resolve(sym) {
    if (sym == null) return null;
    const raw = String(sym).trim();
    if (!raw) return null;
    const up = raw.toUpperCase();
    const hCode = parseHoldersCode(up);
    if (hCode) return holdersDef(hCode);
    const zh = raw.match(/^集中\s*([0-9]{4,6})$/);
    if (zh) return holdersDef(zh[1]);
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
    id: '__TW_MARGIN_CYCLE__',
    name: '融資週期（槓桿臨界）',
    shortName: '融資週期',
    market: 'TW',
    unit: '%',
    defaultRange: 'max',
    multi: true,
    endpoint: '/macro/chart/__TW_MARGIN_CYCLE__',
    years: 20,
    riskLines: [
      { level: 166, label: '門檻 166', color: '#38bdf8' },
      { level: 150, label: '偏弱 150', color: '#eab308' },
      { level: 140, label: '警戒 140', color: '#f97316' },
      { level: 130, label: '危險 130', color: '#ef4444' },
    ],
    valueFormat: (v) => (v != null && isFinite(v) ? Number(v).toFixed(2) + '%' : ''),
    aliases: ['融資週期', '槓桿臨界', 'MARGIN_CYCLE', 'TW_MARGIN_CYCLE'],
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
      const wrap = document.getElementById('chart-wrap');
      if (wrap) {
        if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
        wrap.appendChild(el);
      } else {
        host.appendChild(el);
      }
    }
    // 多序列圖：不貼版本徽章（減少噪音）；單序列仍顯示精簡標籤
    if (def && def.multi) {
      el.style.display = 'none';
    } else {
      el.style.cssText = [
        'position:absolute', 'top:8px', 'right:12px', 'z-index:30',
        'padding:2px 6px', 'border-radius:2px',
        'font:9px/1.2 JetBrains Mono,ui-monospace,monospace',
        'color:#64748b', 'background:rgba(8,12,20,.75)',
        'border:1px solid rgba(51,65,85,.5)', 'pointer-events:none',
      ].join(';');
      el.textContent = def ? (def.shortName || def.name) : '';
      el.style.display = def ? 'block' : 'none';
    }
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
        'position:absolute', 'top:6px', 'right:8px', 'z-index:31',
        'display:flex', 'align-items:center', 'gap:4px',
        'pointer-events:auto', 'opacity:0.55', 'transition:opacity .15s',
      ].join(';');
      bar.onmouseenter = () => { bar.style.opacity = '1'; };
      bar.onmouseleave = () => { bar.style.opacity = '0.55'; };

      const densWrap = document.createElement('label');
      densWrap.id = 'market-chart-density-wrap';
      densWrap.style.cssText = [
        'display:flex', 'align-items:center', 'gap:3px',
        'padding:2px 5px', 'border-radius:2px',
        'font:9px/1.2 JetBrains Mono,ui-monospace,monospace',
        'color:#64748b', 'background:rgba(10,14,22,.8)',
        'border:1px solid rgba(51,65,85,.55)',
      ].join(';');
      densWrap.innerHTML = '<span style="white-space:nowrap;opacity:.8">密度</span>';
      const sel = document.createElement('select');
      sel.id = 'market-chart-density';
      sel.style.cssText = [
        'background:transparent', 'color:#94a3b8', 'border:none',
        'font:9px/1.2 JetBrains Mono,ui-monospace,monospace',
        'padding:1px 0', 'cursor:pointer', 'outline:none', 'max-width:72px',
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
        'padding:2px 7px', 'border-radius:2px',
        'font:9px/1.2 JetBrains Mono,ui-monospace,monospace',
        'color:#94a3b8', 'background:rgba(10,14,22,.8)',
        'border:1px solid rgba(51,65,85,.55)', 'cursor:pointer',
        'white-space:nowrap',
      ].join(';');
      btn.title = '重抓／回補此追蹤圖';
      btn.textContent = '更新';
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
      btn.textContent = '更新';
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
    // 角落小標，不旋轉、不擋圖
    el.style.cssText = [
      'position:absolute', 'inset:0', 'z-index:12', 'pointer-events:none',
      'font:9px/1 JetBrains Mono,ui-monospace,monospace', 'color:#475569',
    ].join(';');
    el.innerHTML =
      (axis.left
        ? `<div style="position:absolute;left:6px;top:8px;letter-spacing:.4px">${axis.left}</div>`
        : '') +
      (axis.right
        ? `<div style="position:absolute;right:6px;top:8px;letter-spacing:.4px">${axis.right}</div>`
        : '');
    el.style.display = 'block';
  }

  /**
   * 底部 chip 圖例（TradingView 風格）：點擊開關；含全開／全關
   * 不佔大塊卡片，不遮主圖。
   */
  function ensureSeriesPanel(def, apiSeries, viewMode) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap || !def || !apiSeries || !apiSeries.length) {
      hideSeriesPanel();
      return;
    }
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
    viewMode = viewMode || getViewMode(def.id);

    let panel = document.getElementById('market-chart-series-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'market-chart-series-panel';
      wrap.appendChild(panel);
    }

    const stylePack = SERIES_STYLE[def.id]
      || (def.holdersCode || String(def.id || '').startsWith('__HOLDERS_') ? SERIES_STYLE['__HOLDERS__'] : null)
      || {};
    const shorts = stylePack._shortNames || {};
    const defaultOff = new Set(stylePack._defaultOff || []);
    const saved = getSeriesVis(def.id) || {};

    apiSeries.forEach(e => {
      const k = e.meta.key;
      let on;
      if (saved[k] !== undefined) on = !!saved[k];
      else if (e.meta.defaultVisible === false || defaultOff.has(k)) on = false;
      else on = true;
      e.visible = on;
      try { e.seriesObj.applyOptions({ visible: on }); } catch (err) {}
    });

    panel.style.cssText = [
      'position:absolute', 'left:8px', 'bottom:8px', 'right:auto', 'top:auto',
      'z-index:29', 'max-width:calc(100% - 16px)',
      'display:flex', 'flex-wrap:wrap', 'align-items:center', 'gap:4px',
      'padding:0', 'background:transparent', 'border:none', 'box-shadow:none',
      'backdrop-filter:none', 'pointer-events:auto',
      'font:10px/1.2 JetBrains Mono,ui-monospace,monospace',
    ].join(';');

    function chipLastStr(e) {
      if (viewMode === 'rebase') return Number(e.last).toFixed(1);
      return e.meta.unit === '%'
        ? Number(e.last).toFixed(2)
        : Number(e.last).toLocaleString('en-US', { maximumFractionDigits: 1 });
    }

    function chipHtml(e) {
      const k = e.meta.key;
      const col = e.meta.color || '#94a3b8';
      const label = shorts[k] || e.meta.name;
      const on = e.visible;
      const lastStr = chipLastStr(e);
      return `<button type="button" class="mc-chip" data-series-key="${k}" title="${e.meta.name}（${e.meta.scale === 'right' ? '右軸' : '左軸'}）· 點擊開關"` +
        ` style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:2px;cursor:pointer;` +
        `font:inherit;border:1px solid ${on ? col + '66' : 'rgba(51,65,85,.7)'};` +
        `background:${on ? 'rgba(15,20,30,.88)' : 'rgba(10,14,20,.55)'};` +
        `color:${on ? '#cbd5e1' : '#475569'};opacity:${on ? 1 : 0.55}">` +
        `<span style="width:10px;height:2px;background:${on ? col : '#334155'};flex-shrink:0"></span>` +
        `<span>${label}</span>` +
        `<span style="color:${on ? col : '#475569'};font-weight:600;font-variant-numeric:tabular-nums">${lastStr}</span>` +
        `</button>`;
    }

    panel.innerHTML =
      apiSeries.map(chipHtml).join('') +
      `<button type="button" data-mc-vis="all" title="全部顯示" style="padding:3px 7px;border-radius:2px;cursor:pointer;font:inherit;` +
        `border:1px solid rgba(71,85,105,.6);background:rgba(15,20,30,.75);color:#64748b">全開</button>` +
      `<button type="button" data-mc-vis="none" title="全部隱藏" style="padding:3px 7px;border-radius:2px;cursor:pointer;font:inherit;` +
        `border:1px solid rgba(51,65,85,.5);background:rgba(10,14,20,.55);color:#475569">全關</button>`;

    panel.style.display = 'flex';

    function refreshChips() {
      panel.querySelectorAll('.mc-chip').forEach(btn => {
        const key = btn.getAttribute('data-series-key');
        const entry = apiSeries.find(e => e.meta.key === key);
        if (!entry) return;
        const col = entry.meta.color || '#94a3b8';
        const on = entry.visible;
        const lastStr = chipLastStr(entry);
        btn.style.borderColor = on ? col + '66' : 'rgba(51,65,85,.7)';
        btn.style.background = on ? 'rgba(15,20,30,.88)' : 'rgba(10,14,20,.55)';
        btn.style.color = on ? '#cbd5e1' : '#475569';
        btn.style.opacity = on ? '1' : '0.55';
        const sw = btn.children[0];
        const val = btn.children[2];
        if (sw) sw.style.background = on ? col : '#334155';
        if (val) { val.style.color = on ? col : '#475569'; val.textContent = lastStr; }
      });
    }

    panel.onclick = function (ev) {
      const allBtn = ev.target && ev.target.closest && ev.target.closest('[data-mc-vis]');
      if (allBtn) {
        const on = allBtn.getAttribute('data-mc-vis') === 'all';
        const map = {};
        apiSeries.forEach(e => {
          e.visible = on;
          map[e.meta.key] = on;
          try { e.seriesObj.applyOptions({ visible: on }); } catch (err) {}
        });
        setSeriesVis(def.id, map);
        refreshChips();
        syncRightScale(apiSeries);
        return;
      }
      const chip = ev.target && ev.target.closest && ev.target.closest('.mc-chip');
      if (!chip) return;
      const key = chip.getAttribute('data-series-key');
      const entry = apiSeries.find(e => e.meta.key === key);
      if (!entry) return;
      entry.visible = !entry.visible;
      try { entry.seriesObj.applyOptions({ visible: entry.visible }); } catch (err) {}
      const map = {};
      apiSeries.forEach(e => { map[e.meta.key] = !!e.visible; });
      setSeriesVis(def.id, map);
      refreshChips();
      syncRightScale(apiSeries);
    };
    panel.onchange = null;

    if (window.S) S._marketApiSeries = apiSeries;
    syncRightScale(apiSeries);
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
    if (def && def.multi) {
      el.style.cssText = [
        'position:absolute', 'top:28px', 'left:50%', 'transform:translateX(-50%)', 'z-index:28',
        'min-width:0', 'max-width:min(420px,86%)',
        'padding:6px 10px', 'border-radius:2px',
        'font:10px/1.4 JetBrains Mono,ui-monospace,monospace',
        'color:#cbd5e1', 'background:rgba(10,14,20,.92)',
        'border:1px solid rgba(51,65,85,.65)',
        'box-shadow:0 4px 16px rgba(0,0,0,.4)',
        'pointer-events:none',
      ].join(';');
      // multi：精簡標題，不要大號漲跌
      if (opts.extraHtml) {
        el.innerHTML =
          (dateStr ? `<div style="color:#64748b;margin-bottom:3px;text-align:center">${dateStr}</div>` : '') +
          opts.extraHtml;
      }
    } else {
      el.style.left = '12px';
      el.style.right = 'auto';
      el.style.top = '36px';
      el.style.transform = '';
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

  function formatSeriesValue(meta, val, viewMode) {
    if (val == null || !isFinite(val)) return '—';
    if (viewMode === 'rebase') {
      return Number(val).toFixed(1);
    }
    if (meta && meta.unit === '%') return Number(val).toFixed(2) + '%';
    return Number(val).toLocaleString('en-US', { maximumFractionDigits: 2 });
  }

  /**
   * 依目前可見時間窗裁切原始序列，供市場風險重算
   */
  function sliceSeriesForVisible(rawSeries, chart) {
    if (!chart || !rawSeries) return rawSeries || [];
    let from = null, to = null;
    try {
      const vr = chart.timeScale().getVisibleRange();
      if (vr) { from = vr.from; to = vr.to; }
    } catch (e) {}
    if (from == null || to == null) return rawSeries;
    const userTzOffset = (window.S && S.tzOffset != null)
      ? S.tzOffset
      : (-new Date().getTimezoneOffset() * 60);
    return rawSeries.map(s => {
      const pts = [];
      for (const p of s.points || []) {
        const u = dateToUnix(p.date);
        if (u == null) continue;
        const t = u + userTzOffset;
        if (t >= from && t <= to) pts.push(p);
      }
      return Object.assign({}, s, { points: pts.length ? pts : (s.points || []) });
    });
  }

  function syncRiskFromPayload(def, payload, chart, opts) {
    opts = opts || {};
    const id = def && def.id;
    if (!id) return;
    const isUs = (id === '__US_RATES_CREDIT__' || id === '__US_CPI_FIN__');
    const isCycle = (id === '__TW_MARGIN_CYCLE__');
    const isHolders = !!(def && def.holdersCode) || String(id).startsWith('__HOLDERS_');
    if (!isUs && !isCycle && !isHolders) return;
    let risk = null;
    if (isUs) {
      const raw = (payload && payload.series) || [];
      const sliced = sliceSeriesForVisible(raw, chart);
      if (window.MarketScoreBar && typeof MarketScoreBar.recomputeFromSeries === 'function') {
        risk = MarketScoreBar.recomputeFromSeries(id, sliced);
        if (payload && payload.risk && payload.risk.algo && risk) risk.algo = payload.risk.algo;
      } else if (payload && payload.risk) {
        risk = payload.risk;
      }
    } else if (payload && payload.risk) {
      risk = payload.risk;
    }
    if (!risk) return;
    if (window.S) {
      S._marketRisk = risk;
      S._marketRiskAlgo = risk.algo || (payload.risk && payload.risk.algo) || S._marketRiskAlgo;
      S._fundPanelPayload = risk;
    }
    if (window.MarketScoreBar && typeof MarketScoreBar.applyRiskUpdate === 'function') {
      MarketScoreBar.applyRiskUpdate(risk, {
        sym: id,
        viewMode: (window.S && S._marketViewMode) || getViewMode(id),
        showModeToggle: isUs,
      });
    }
    if (opts.toast && typeof window.notifyToast === 'function') {
      notifyToast('視圖已更新', '分數已依目前視圖重算', { level: 'info', skipDesktop: true });
    }
  }

  /**
   * 多序列 MacroMicro 風格渲染（左／右軸、折線／柱狀／面積）
   * @param {object} def MarketChart def
   * @param {object} payload /macro/chart 回應
   */
  function renderMulti(def, payload) {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap || typeof LightweightCharts === 'undefined') { WARN('no chart env'); return; }
    const rawSeries = (payload && payload.series) || [];
    if (!rawSeries.length) { WARN('no series in payload'); return; }

    const viewMode = getViewMode(def.id);
    const seriesList = viewMode === 'rebase' ? rebaseSeriesList(rawSeries) : rawSeries.map(s => Object.assign({}, s, { points: (s.points || []).slice() }));

    if (window.S && S.chart) {
      try { S.chart.remove(); } catch (e) {}
      S.chart = null;
    }

    const userTzOffset = -new Date().getTimezoneOffset() * 60;
    if (window.S) {
      S.tzOffset = userTzOffset;
      S._marketViewMode = viewMode;
      S._marketRawPayload = payload;
      S._marketChartId = def.id;
    }
    const tz = (t) => (t == null ? t : t + userTzOffset);
    const hasRight = seriesList.some(s => s.scale === 'right' && (s.points || []).length);
    const stylePack = SERIES_STYLE[def.id]
      || (def.holdersCode || String(def.id || '').startsWith('__HOLDERS_') ? SERIES_STYLE['__HOLDERS__'] : null)
      || {};
    const LineStyle = (LightweightCharts.LineStyle) || { Solid: 0, Dotted: 1, Dashed: 2 };
    // 對齊模式：左右軸皆為相對指數，軸標改寫
    const axisPack = Object.assign({}, stylePack);
    if (viewMode === 'rebase') {
      axisPack._axis = { left: 'L · 對齊100', right: hasRight ? 'R · 對齊100' : '' };
    }

    const chart = LightweightCharts.createChart(wrap, {
      width: wrap.clientWidth,
      height: wrap.clientHeight,
      layout: {
        background: { color: '#0A0E14' },
        textColor: '#5C6B7A',
        fontFamily: "JetBrains Mono, ui-monospace, Menlo, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,.03)' },
        horzLines: { color: 'rgba(255,255,255,.04)' },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Magnet,
        vertLine: {
          color: 'rgba(148,163,184,.28)', width: 1, style: LineStyle.Dashed,
          labelVisible: true, labelBackgroundColor: '#151b24',
        },
        horzLine: {
          color: 'rgba(148,163,184,.20)', width: 1, style: LineStyle.Dashed,
          labelVisible: true, labelBackgroundColor: '#151b24',
        },
      },
      leftPriceScale: {
        visible: true, borderVisible: false,
        scaleMargins: { top: 0.06, bottom: 0.14 },
        entireTextOnly: true,
      },
      rightPriceScale: {
        visible: hasRight, borderVisible: false,
        scaleMargins: { top: 0.06, bottom: 0.14 },
        entireTextOnly: true,
      },
      timeScale: {
        borderVisible: false, timeVisible: false, secondsVisible: false,
        rightOffset: 8, barSpacing: 2.5, minBarSpacing: 0.4,
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
      if (payload && payload.risk) {
        S._marketRisk = payload.risk;
        S._marketRiskAlgo = payload.risk.algo || null;
      }
    }

    const apiSeries = []; // {meta, seriesObj, byTime, visible, last, prev, rawByTime}
    let primaryApi = null;
    // 原始數值對照（十字游標在對齊模式可附帶原始）
    const rawByKey = {};
    for (const rs of rawSeries) {
      const m = new Map();
      for (const p of rs.points || []) {
        const u = dateToUnix(p.date);
        if (u == null || p.value == null || !isFinite(p.value)) continue;
        m.set(tz(u), p.value);
      }
      rawByKey[rs.key] = m;
    }

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
      const isHist = (s.style === 'histogram' || s.style === 'bar') && viewMode !== 'rebase';
      const useArea = false; // 專業線圖：不用面積填色
      let obj;
      const fmt = (viewMode === 'rebase')
        ? { type: 'price', precision: 1, minMove: 0.1 }
        : (s.unit === '%'
          ? { type: 'custom', formatter: v => (v != null && isFinite(v) ? v.toFixed(2) + '%' : '') }
          : (s.key === 'holders'
            ? { type: 'custom', formatter: v => (v != null && isFinite(v) ? Math.round(v).toLocaleString('en-US') : '') }
            : { type: 'price', precision: 2, minMove: 0.01 }));
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
        rawByTime: rawByKey[s.key] || new Map(),
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

    // 多序列：圖例改底部 chip，清空右側舊 legend 避免重複
    const lg = document.getElementById('chart-legend');
    if (lg) lg.innerHTML = '';

    chart.subscribeCrosshairMove(param => {
      const ohlcEl = document.getElementById('ci-ohlc');
      if (ohlcEl) ohlcEl.style.display = 'none';
      if (!param || !param.point || !param.time || !param.seriesData) {
        hideFloat();
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
        let line = `<div style="display:flex;justify-content:space-between;gap:12px;color:${e.meta.color};margin-top:2px">` +
          `<span>${e.meta.name}</span>` +
          `<span style="font-weight:700">${formatSeriesValue(e.meta, v, viewMode)}`;
        // 對齊模式：附帶原始數值
        if (viewMode === 'rebase') {
          const rv = e.rawByTime.get(param.time);
          if (rv != null) {
            const ru = e.meta._rawUnit || e.meta.unit;
            line += ` <span style="color:#64748b;font-weight:500;font-size:9px">(` +
              (ru === '%' ? Number(rv).toFixed(2) + '%' : Number(rv).toLocaleString('en-US', { maximumFractionDigits: 2 })) +
              `)</span>`;
          }
        }
        line += `</span></div>`;
        rows.push(line);
      }
      updateFloat(def, {
        value: primVal != null ? primVal : (primaryApi && primaryApi.last),
        prev: null,
        dateStr: ds,
        dual: null,
        extraHtml: rows.join(''),
      });
    });

    // 可見區間變化 → 風險分數重算（節流）
    let _riskTimer = null;
    function scheduleRiskSync(toast) {
      if (_riskTimer) clearTimeout(_riskTimer);
      _riskTimer = setTimeout(() => {
        syncRiskFromPayload(def, payload, chart, { toast: !!toast });
      }, 180);
    }
    try {
      chart.timeScale().subscribeVisibleTimeRangeChange(() => scheduleRiskSync(false));
    } catch (e) {}

    ensureBadge(def);
    ensureAxisLabels(def, axisPack);
    ensureSeriesPanel(def, apiSeries, viewMode);

    // 融資週期：在維持率序列上畫臨界虛線
    const riskLines = (def && def.riskLines) || (payload && payload.riskLines) || [];
    if (riskLines.length) {
      const mmEntry = apiSeries.find(e => e.meta && e.meta.key === 'margin_ratio') || primaryApi;
      if (mmEntry) applyRiskLines(mmEntry.seriesObj, riskLines);
    }

    if (primaryApi) {
      // 對齊模式 header 顯示指數；名稱帶模式標
      if (viewMode === 'rebase') {
        try {
          const nEl = document.getElementById('ci-name');
          if (nEl) nEl.textContent = def.name + ' · 對齊100';
          const pEl = document.getElementById('ci-price');
          if (pEl) pEl.textContent = Number(primaryApi.last).toFixed(1);
          const cEl = document.getElementById('ci-chg');
          if (cEl && primaryApi.prev != null && primaryApi.prev > 0) {
            const chg = (primaryApi.last - primaryApi.prev) / primaryApi.prev * 100;
            cEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
          }
          const info = document.getElementById('chart-info');
          if (info) info.style.display = 'block';
          const loading = document.getElementById('chart-loading');
          if (loading) loading.style.display = 'none';
        } catch (e) {}
      } else {
        setHeader(def, primaryApi.last, primaryApi.prev);
      }
      hideFloat(); // 常駐浮層太吵；數值看底部 chip，細節靠十字游標
    }

    if (window.S && primaryApi) {
      const primMeta = primaryApi.meta;
      const candles2 = (primMeta.points || []).map(p => {
        const u = dateToUnix(p.date);
        return { time: u, open: p.value, high: p.value, low: p.value, close: p.value, volume: 0 };
      }).filter(c => c.time != null);
      S.data = { candles: candles2, name: def.name };
    }

    scheduleRiskSync(false);

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
    LOG('rendered MULTI', def.id, viewMode, apiSeries.map(e => e.meta.key + ':' + e.byTime.size).join(', '));
  }

  function toggleViewMode() {
    if (!window.S || !S._marketChartId || !S._marketRawPayload) return;
    const def = resolve(S._marketChartId);
    if (!def) return;
    const cur = getViewMode(def.id);
    const next = cur === 'rebase' ? 'raw' : 'rebase';
    setViewMode(def.id, next);
    if (window.S) S._marketViewMode = next;
    renderMulti(def, S._marketRawPayload);
    // renderMulti 內已 scheduleRiskSync；再補一次 toast
    if (typeof window.notifyToast === 'function') {
      notifyToast(next === 'rebase' ? '已切換對齊' : '已切換原始', '分數已依目前視圖重算', { level: 'info', skipDesktop: true });
    } else if (typeof setStat === 'function') {
      setStat((next === 'rebase' ? '對齊' : '原始') + ' · 分數已依目前視圖重算');
    }
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
    toggleViewMode,
    getViewMode,
    setViewMode,
    refresh: function (id) {
      const btn = document.getElementById('market-chart-refresh');
      if (btn && id) btn.dataset.chartId = id;
      return onRefreshClick({ currentTarget: btn });
    },
  };

  LOG('module ready — register() more series as needed');
})();
