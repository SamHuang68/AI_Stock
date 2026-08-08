/* ============================================================================
 * shell_v5.js  —  Stock Terminal 5.0：側欄殼層 + 視圖路由（tip UX only）
 * ----------------------------------------------------------------------------
 * tip UX 唯一執行線：預設 #pulse；無 hash 絕不還原舊圖表殼。
 * 啟動前隱藏 #body／#wlbar，避免 shell 尚未掛上時閃出舊 UI。
 * 路由：總覽／圖表／廣度／熱力／法人／國際／盤後／訊號／AI／自選／風險／快訊／選股／投組／設定。
 * 鐵律：不破壞 #left / #pro-tools / symLoaded / Toolbar 既有行為。
 * ========================================================================== */
(function () {
  'use strict';

  /* 立刻隱藏舊圖表殼，避免 JS 尚未 boot 時露出 ST4 版面 */
  try {
    if (!document.getElementById('st5-tip-boot')) {
      var bootCss = document.createElement('style');
      bootCss.id = 'st5-tip-boot';
      bootCss.textContent =
        'html:not(.st5-booted) #body,' +
        'html:not(.st5-booted) #wlbar,' +
        'html:not(.st5-booted) #mkt-bar{display:none!important}' +
        'html:not(.st5-booted) body::before{' +
          'content:"Stock Terminal tip UX · loading…";display:block;padding:18px 20px;' +
          'font:700 12px/1.4 "JetBrains Mono",monospace;color:#F5C518;letter-spacing:.4px}';
      (document.head || document.documentElement).appendChild(bootCss);
    }
  } catch (eBoot) {}

  var STORAGE_KEY = 'st5.shell.route';
  var NAV_KEY = 'st5.shell.navOpen';
  var VERSION = '5.0';
  var TIP_UX = true;

  /* 舊 route → 更完整的目的地（圖表／熱力等） */
  var ROUTE_ALIASES = {
    trends: { to: 'chart', sym: '^TWII', mkt: 'TW' },   // 指數頁 → 圖表加權
    index:  { to: 'chart', sym: '^TWII', mkt: 'TW' }
  };

  var ROUTES = [
    { id: 'pulse',         label: '總覽', hint: '市場總覽儀表板（一屏高密度）', icon: '◎' },
    { id: 'chart',         label: '圖表', hint: 'K 線工作區（含加權／櫃買指數與總體列）',   icon: '◈' },
    { id: 'breadth',       label: '廣度', hint: '大盤廣度（漲跌家數）',                     icon: '▤' },
    { id: 'heat',          label: '熱力', hint: '類股熱力圖＋焦點掃描',                     icon: '▦' },
    { id: 'institutional', label: '法人', hint: '三大法人動向與買賣超',                     icon: '₴' },
    { id: 'international', label: '國際', hint: '美股／美元／黃金避險／銅景氣與總經',         icon: '◎' },
    { id: 'afterhours',    label: '盤後', hint: '漲跌排行／籌碼／期貨盤後',                 icon: '◐' },
    { id: 'signals',       label: '訊號', hint: '策略訊號／焦點掃描結果',                   icon: '✦' },
    { id: 'ai',            label: 'AI',   hint: 'AI 報告／副駕／焦點掃描中樞',               icon: '✧' },
    { id: 'watchlist',     label: '自選', hint: '自選股中心（表格式；完整操作在圖表列）',   icon: '★' },
    { id: 'risk',          label: '風險', hint: '風險事件與脈動風險度',                     icon: '◇' },
    { id: 'news',          label: '快訊', hint: '事件／結算／警報中樞',                     icon: '◉' },
    { id: 'scan',          label: '選股', hint: '三合一選股（技術×基本面×籌碼）',           icon: '▷' },
    { id: 'book',          label: '投組', hint: '投組風險（波動／VaR／曝險）',               icon: '▣' },
    { id: 'settings',      label: '設定', hint: '同步狀態與資料來源',                       icon: '⚙' },
    { id: 'workspace',     label: '工具', hint: '回到圖表並開啟指令盤',                     icon: '⌘', action: 'cmd' }
  ];

  var state = { route: 'pulse', built: false, syncing: false, prevRoute: null, navOpen: false };

  /* Alt+Shift+1…0 → 側欄（避開 Alt+數字 時框） */
  var HOTKEY_ROUTES = [
    'pulse', 'chart', 'breadth', 'heat', 'institutional',
    'international', 'afterhours', 'ai', 'news', 'scan'
  ];

  /* 功能轉盤：最多 3 層；依投資分析邏輯分類；上層保留半透明鎖定 */
  var RING_MAX_DEPTH = 3;
  var RING_R = 112; /* 各層轉盤半徑（下一層以點選項為圓心） */
  var RING_ROUTES = [
    'market', 'price', 'flow', 'screen',
    'breadth', 'global', 'ai', 'desk'
  ];
  var ringState = {
    open: false,
    wx: 0, wy: 0,   /* wheel 原點（螢幕座標） */
    cx: 0, cy: 0,   /* 作用層圓心（螢幕座標，供命中／游標） */
    hi: -1,
    layers: [],     /* [{ title, items, pickedId, ox, oy }] 最多 3；ox/oy 相對 wheel */
    items: []       /* = 作用層 items */
  };
  /* Toolbar 按鈕短標（DOM 未掛時備援） */
  var RING_BTN_META = {
    'btn-valuation': { label: '估值', icon: '⚓' },
    'btn-marketflow': { label: '資金', icon: '💰' },
    'btn-instrank': { label: '法人榜', icon: '🏆' },
    'btn-supplychain': { label: '供應鏈', icon: '🔗' },
    'btn-stockfut': { label: '個股期', icon: '🔭' },
    'btn-portfolio': { label: '投組', icon: '▣' },
    'btn-chainmom': { label: '鏈動能', icon: '⛓' },
    'btn-screener3': { label: '三合一', icon: '🔬' },
    'btn-screener': { label: '篩選', icon: '🔍' },
    'btn-patterns': { label: '型態', icon: '〰' },
    'btn-stratbuilder': { label: '策略', icon: '🧱' },
    'btn-bt3': { label: '回測', icon: '📈' },
    'btn-wizard': { label: '精靈', icon: '🧙' },
    'btn-stratscript': { label: '腳本', icon: '📝' },
    'btn-ai-report': { label: '報告', icon: '🤖' },
    'btn-copilot': { label: '副駕', icon: '✦' },
    'btn-focus': { label: '焦點', icon: '◎' },
    'btn-vp': { label: '量價', icon: '📊' },
    'btn-multichart': { label: '多圖', icon: '▦' },
    'btn-spread': { label: '價差', icon: '⇄' },
    'btn-compare': { label: '比較', icon: '⧉' },
    'btn-overnight': { label: '夜盤', icon: '☾' },
    'btn-drawtools': { label: '畫線', icon: '✎' },
    'btn-replay': { label: '重播', icon: '▷' },
    'btn-universe': { label: '代號庫', icon: '📚' },
    'btn-datasources': { label: '資料源', icon: '🗄' },
    'btn-calendar': { label: '行事曆', icon: '📅' },
    'btn-alertpush': { label: '推播', icon: '🔔' },
    'btn-toast': { label: '提示', icon: '💬' },
    'btn-live': { label: '即時', icon: '●' },
    'btn-datahealth': { label: '健檢', icon: '❤' },
    'btn-hotkeys': { label: '快捷', icon: '⌨' },
    'btn-cmdp': { label: '指令', icon: '⌘' }
  };

  var PANEL_MAP = {
    pulse: 'PulseV5',
    breadth: 'BreadthV5',
    heat: 'HeatV5',
    institutional: 'InstitutionalV5',
    international: 'InternationalV5',
    afterhours: 'AfterhoursV5',
    signals: 'SignalsV5',
    ai: 'AiV5',
    watchlist: 'WatchlistV5',
    risk: 'RiskV5',
    news: 'NewsV5',
    scan: 'ScanV5',
    book: 'BookV5',
    settings: 'SettingsV5'
  };

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('shell-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'shell-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      /* 主區全寬；側欄浮動疊加，隱藏時釋出 ~150px 可視區 */
      '#shell-row{display:flex;flex:1 1 0;min-height:0;min-width:0;height:100%;position:relative}' +
      '#shell-main{display:flex;flex-direction:column;flex:1 1 0;min-width:0;min-height:0;height:100%;position:relative;width:100%}' +
      '#navrail{position:absolute;left:0;top:0;bottom:0;width:156px;' +
        'background:linear-gradient(180deg,#0A1220 0%,#070E18 100%);' +
        'border-right:1px solid #132238;display:flex;flex-direction:column;align-items:stretch;' +
        'padding:8px 6px;gap:1px;z-index:80;overflow-y:auto;overflow-x:hidden;box-sizing:border-box;' +
        'transform:translateX(0);transition:transform .2s ease,box-shadow .2s ease;' +
        'box-shadow:8px 0 28px rgba(0,0,0,.45)}' +
      '#shell-row.nr-collapsed #navrail{transform:translateX(-100%);pointer-events:none;box-shadow:none}' +
      '#nr-backdrop{display:none;position:absolute;inset:0;z-index:70;background:rgba(2,6,14,.35);border:none;padding:0;cursor:pointer}' +
      '#shell-row.nr-open #nr-backdrop{display:block}' +
      '#nr-edge{position:absolute;left:0;top:50%;transform:translateY(-50%);z-index:85;' +
        'display:none;flex-direction:column;align-items:center;justify-content:center;gap:4px;' +
        'width:22px;min-height:72px;padding:8px 0;border:1px solid #1e334d;border-left:none;' +
        'border-radius:0 8px 8px 0;background:linear-gradient(180deg,#0E1A2C,#0A1220);' +
        'color:var(--gold);cursor:pointer;font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:800;' +
        'letter-spacing:.5px;box-shadow:4px 0 16px rgba(0,0,0,.35)}' +
      '#nr-edge:hover{background:#132238;color:#FBBF24}' +
      '#shell-row.nr-collapsed #nr-edge{display:flex}' +
      '#nr-edge .nr-edge-ico{font-size:12px;line-height:1}' +
      '#nr-edge .nr-edge-lbl{writing-mode:vertical-rl;text-orientation:mixed;font-size:9px;letter-spacing:1px}' +
      '#navrail .nr-brand-st{display:flex;align-items:center;gap:8px;padding:6px 6px 12px;' +
        'border-bottom:1px solid #132238;margin-bottom:6px;user-select:none;flex-shrink:0}' +
      '#navrail .nr-brand-st .logo-box{width:34px;height:34px;border-radius:9px;padding:0;overflow:hidden;' +
        'flex-shrink:0;border:1px solid rgba(245,197,24,.35);background:#070E18;' +
        'box-shadow:0 0 0 1px rgba(56,189,248,.12)}' +
      '#navrail .nr-brand-st .logo-box img{width:100%;height:100%;display:block;object-fit:cover}' +
      '#navrail .nr-brand-st .logo-text{flex:1;min-width:0}' +
      '#navrail .nr-brand-st .brand-title{font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:800;' +
        'color:#F1F5F9;line-height:1.1;letter-spacing:.2px}' +
      '#navrail .nr-brand-st .brand-sub{font-family:\'JetBrains Mono\',monospace;font-size:8px;font-weight:700;' +
        'color:var(--gold);letter-spacing:.8px;margin-top:2px}' +
      '#navrail .nr-hide{flex:0 0 auto;width:26px;height:26px;border:1px solid #1e334d;border-radius:6px;' +
        'background:transparent;color:#94A3B8;cursor:pointer;font-size:14px;line-height:1;padding:0}' +
      '#navrail .nr-hide:hover{color:var(--gold);border-color:var(--gold-m)}' +
      /* 品牌集中左上：內頁不再重複 STOCK TERMINAL kicker */
      '.pl-kicker,.hub-kicker,.bd-kicker,.ht-kicker,.ah-kicker,.nw-kicker,.sc-kicker,.bk-kicker,.sv-kicker,.ai5-kicker{' +
        'display:none!important}' +
      '.nr-btn{display:flex;align-items:center;gap:8px;' +
        'min-height:30px;margin:1px 0;padding:4px 8px;border:1px solid transparent;border-radius:7px;' +
        'background:transparent;color:#94A3B8;cursor:pointer;font-family:\'JetBrains Mono\',monospace;' +
        'font-size:11px;font-weight:600;letter-spacing:.2px;transition:color .14s ease,background .14s ease,border-color .14s ease;flex-shrink:0;text-align:left}' +
      '.nr-btn .nr-ico{font-size:13px;line-height:1;opacity:.85;width:16px;text-align:center;flex-shrink:0}' +
      '.nr-btn:hover{color:#F8FAFC;background:rgba(255,255,255,0.04);border-color:rgba(255,255,255,0.06)}' +
      '.nr-btn.on{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}' +
      '.nr-btn.on .nr-ico{opacity:1}' +
      '.nr-btn:focus-visible{outline:2px solid var(--gold);outline-offset:1px}' +
      '.nr-spacer{flex:1;min-height:10px}' +
      '.sv-soft-badge{position:sticky;top:0;z-index:3;display:none;align-items:center;gap:6px;' +
        'padding:3px 8px;margin:0 0 6px;font-family:\'JetBrains Mono\',monospace;font-size:9px;' +
        'color:var(--gold);background:rgba(245,197,24,.08);border:1px solid var(--gold-m);border-radius:5px;align-self:flex-start}' +
      '.sv-soft-badge.on{display:inline-flex}' +
      '#topbar .logo .shell-logo-ico{width:18px;height:18px;border-radius:4px;margin-right:6px;' +
        'vertical-align:middle;border:1px solid rgba(245,197,24,.35);object-fit:cover}' +
      '.nr-foot-st{padding:8px 6px 4px;font-family:\'JetBrains Mono\',monospace;' +
        'font-size:9px;color:#64748B;border-top:1px solid #132238;margin-top:4px;flex-shrink:0;' +
        'display:flex;flex-direction:column;gap:2px}' +
      '.nr-foot-st .mode-dot{color:var(--cyan);font-weight:600}' +
      '.nr-foot-st .mode-sub{font-size:8px;color:#475569;line-height:1.2}' +
      '#shell-views{display:none!important;flex:1 1 0;min-height:0;min-width:0;height:100%;background:#060C16;overflow:auto}' +
      '#shell-views.show{display:flex!important;flex-direction:column;flex:1 1 0;min-height:0;height:100%}' +
      /* 高密度一頁視圖：鎖定捲動（各模組亦會覆寫） */
      '#shell-views.show:has(.sv-panel.on){overflow:hidden;flex:1 1 0;min-height:0}' +
      '#view-breadth.sv-panel.on,#view-heat.sv-panel.on,#view-afterhours.sv-panel.on,' +
      '#view-institutional.sv-panel.on,#view-international.sv-panel.on,#view-signals.sv-panel.on,' +
      '#view-ai.sv-panel.on,#view-watchlist.sv-panel.on,#view-risk.sv-panel.on,#view-news.sv-panel.on,' +
      '#view-scan.sv-panel.on,#view-book.sv-panel.on,#view-settings.sv-panel.on,' +
      '#view-pulse.sv-panel.on{max-width:none!important}' +
      '#topbar.shell-hidden{display:none !important}' +
      '#body.shell-hidden{display:none !important}' +
      '#wlbar.shell-hidden{display:none !important}' +
      /* 非作用中面板強制隱藏，避免「市場總覽」殘留在其他 tab 上方 */
      '.sv-panel{display:none!important;flex:1 1 0;padding:8px 10px 10px;max-width:none;min-width:0;' +
        'box-sizing:border-box;min-height:0;height:100%;visibility:hidden;pointer-events:none}' +
      '.sv-panel.on{display:flex!important;flex-direction:column;visibility:visible;pointer-events:auto;' +
        'flex:1 1 0;min-height:0;height:100%}' +
      '#shell-views > .sv-panel{min-width:0}' +
      '#mkt-bar.shell-hidden{display:none!important}' +
      '.sv-mount{flex:1 1 0;min-height:0;height:100%;min-width:0;max-width:100%;box-sizing:border-box;display:flex;flex-direction:column}' +
      '.sv-kicker{font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--gold);' +
        'letter-spacing:1.5px;margin-bottom:2px}' +
      '.sv-title{font-family:\'Noto Serif TC\',serif;font-size:20px;font-weight:700;color:var(--thi);' +
        'letter-spacing:.5px;margin-bottom:4px;line-height:1.15}' +
      '.sv-desc{font-size:11px;line-height:1.5;color:var(--text);max-width:42em;margin-bottom:8px}' +
      '.sv-meta{font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px}' +
      '.sv-cta{display:inline-flex;align-items:center;gap:5px;margin-top:8px;padding:5px 10px;' +
        'background:var(--gold);color:#060A12;border:none;border-radius:5px;cursor:pointer;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;letter-spacing:.5px}' +
      '.sv-cta:hover{background:#FBBF24}' +
      '#topbar .shell-sync{display:inline-flex;align-items:center;gap:6px;margin-left:4px;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px}' +
      '#topbar .shell-sync .ss-dot{width:6px;height:6px;border-radius:50%;background:var(--green);' +
        'box-shadow:0 0 6px var(--green);flex-shrink:0}' +
      '#topbar .shell-sync.warn .ss-dot{background:var(--orange);box-shadow:0 0 6px var(--orange)}' +
      '#topbar .shell-sync.err .ss-dot{background:var(--red);box-shadow:0 0 6px var(--red)}' +
      '#topbar .shell-sync-btn{display:inline-flex;align-items:center;gap:5px;margin-left:8px;' +
        'padding:4px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--thi);font-family:\'JetBrains Mono\',monospace;font-size:10px;cursor:pointer;' +
        'letter-spacing:.3px}' +
      '#topbar .shell-sync-btn:hover{border-color:var(--gold-m);color:var(--gold)}' +
      '#topbar .shell-sync-btn:disabled{opacity:.55;cursor:wait}' +
      '#topbar .logo .shell-ver{margin-left:6px;font-size:9px;color:var(--gold);letter-spacing:1px;font-weight:700}' +
      '#topbar .logo [data-v2-banner] span,' +
      '#topbar .logo>span[style*="FBBF24"]{display:none !important}' +
      '@media (max-width:1024px){' +
        '#navrail{width:148px}' +
        '.sv-panel{padding:8px 8px 10px}' +
        '#topbar .shell-sync-btn span.lbl{display:none}' +
      '}' +
      /* ── 功能轉盤：最多 3 層同心圓；上層透明鎖定、作用層可點 ── */
      '#st-ring{position:fixed;inset:0;z-index:240;display:none;pointer-events:none}' +
      '#st-ring.on{display:block;pointer-events:auto}' +
      '#st-ring .sr-backdrop{position:absolute;inset:0;background:rgba(2,8,18,.58);' +
        'backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);border:0;padding:0;cursor:default}' +
      '#st-ring .sr-wheel{position:absolute;width:0;height:0;transform:translate(-50%,-50%);' +
        'pointer-events:none}' +
      '#st-ring.on .sr-wheel{animation:sr-pop .18s cubic-bezier(.2,1.2,.4,1) both}' +
      '@keyframes sr-pop{from{opacity:0;transform:translate(-50%,-50%) scale(.55)}' +
        'to{opacity:1;transform:translate(-50%,-50%) scale(1)}}' +
      '#st-ring .sr-layers{position:absolute;left:0;top:0;width:0;height:0}' +
      '#st-ring .sr-layer{position:absolute;left:0;top:0;width:0;height:0;pointer-events:none;' +
        'transition:opacity .16s ease}' +
      '#st-ring .sr-layer.locked{opacity:.26;filter:saturate(.35) brightness(.85)}' +
      '#st-ring .sr-layer.locked .sr-item{pointer-events:none!important;cursor:default;' +
        'box-shadow:none;border-color:rgba(30,51,77,.55)}' +
      '#st-ring .sr-layer.locked .sr-item.picked{opacity:1;filter:none;border-color:rgba(245,197,24,.45);' +
        'color:rgba(245,197,24,.75);box-shadow:0 0 0 1px rgba(245,197,24,.12)}' +
      '#st-ring .sr-layer.active{opacity:1;filter:none;z-index:2}' +
      '#st-ring .sr-layer.active .sr-item{pointer-events:auto}' +
      '#st-ring .sr-hub{position:absolute;left:0;top:0;width:44px;height:44px;margin:-22px 0 0 -22px;' +
        'border-radius:50%;border:1px solid rgba(248,113,113,.55);z-index:5;' +
        'background:radial-gradient(circle at 40% 35%,#fb7185,#b91c1c 70%);' +
        'color:#fff;font:800 16px/44px "JetBrains Mono",monospace;text-align:center;' +
        'cursor:pointer;pointer-events:auto;box-shadow:0 0 0 4px rgba(185,28,28,.18),0 8px 28px rgba(0,0,0,.45);' +
        'transition:transform .12s ease,box-shadow .12s ease}' +
      '#st-ring .sr-hub:hover,#st-ring .sr-hub.hi{transform:scale(1.08);' +
        'box-shadow:0 0 0 5px rgba(251,113,133,.28),0 10px 32px rgba(0,0,0,.5)}' +
      '#st-ring .sr-hub.back{border-color:rgba(56,189,248,.55);' +
        'background:radial-gradient(circle at 40% 35%,#38bdf8,#0369a1 70%)}' +
      '#st-ring .sr-item{position:absolute;left:0;top:0;width:54px;height:54px;margin:-27px 0 0 -27px;' +
        'border-radius:50%;border:1px solid rgba(30,51,77,.95);' +
        'background:radial-gradient(circle at 35% 30%,#1a2740,#0b1524 72%);' +
        'color:#cbd5e1;cursor:pointer;' +
        'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;' +
        'box-shadow:0 6px 18px rgba(0,0,0,.4);transition:transform .12s ease,border-color .12s,color .12s,opacity .16s}' +
      '#st-ring .sr-item .sr-ico{font-size:14px;line-height:1;opacity:.92}' +
      '#st-ring .sr-item .sr-lbl{font:700 9px/1 "JetBrains Mono",monospace;letter-spacing:.15px;opacity:.9}' +
      '#st-ring .sr-layer.active .sr-item:hover,#st-ring .sr-layer.active .sr-item.hi{transform:scale(1.12);' +
        'border-color:rgba(245,197,24,.65);color:var(--gold);' +
        'background:radial-gradient(circle at 35% 30%,#243552,#101c30 72%);' +
        'box-shadow:0 0 0 2px rgba(245,197,24,.18),0 8px 22px rgba(0,0,0,.5)}' +
      '#st-ring .sr-item.on{border-color:rgba(56,189,248,.55);color:#7dd3fc}' +
      '#st-ring .sr-item.has-kids::after{content:"›";position:absolute;right:5px;top:50%;' +
        'transform:translateY(-50%);font-size:10px;color:var(--gold);opacity:.9}' +
      '#st-ring .sr-tip{position:absolute;left:50%;top:86px;transform:translateX(-50%);z-index:5;' +
        'font:600 10px/1.3 "JetBrains Mono",monospace;color:#94a3b8;white-space:nowrap;' +
        'pointer-events:none;text-shadow:0 1px 8px rgba(0,0,0,.8);max-width:300px;' +
        'overflow:hidden;text-overflow:ellipsis}' +
      '#st-ring .sr-level{position:absolute;left:50%;top:-100px;transform:translateX(-50%);z-index:5;' +
        'font:700 9px/1.35 "JetBrains Mono",monospace;color:var(--gold);letter-spacing:.3px;' +
        'white-space:nowrap;pointer-events:none;text-shadow:0 1px 8px rgba(0,0,0,.8);text-align:center}' +
      '#st-ring .sr-level .sr-crumb{color:#64748b;font-weight:600}' +
      '#nr-edge .nr-edge-ring{font-size:11px;opacity:.85;margin-top:2px}' +
      '#st-ring-fab{position:fixed;right:14px;bottom:14px;z-index:90;width:40px;height:40px;' +
        'border-radius:50%;border:1px solid rgba(245,197,24,.4);' +
        'background:radial-gradient(circle at 35% 30%,#1e2d48,#0c1626);color:var(--gold);' +
        'font:800 15px/1 "JetBrains Mono",monospace;cursor:pointer;' +
        'box-shadow:0 6px 20px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;' +
        'transition:transform .14s ease,border-color .14s,box-shadow .14s}' +
      '#st-ring-fab:hover{transform:scale(1.06);border-color:var(--gold);' +
        'box-shadow:0 0 0 3px rgba(245,197,24,.15),0 8px 24px rgba(0,0,0,.5)}' +
      '#st-ring-fab[hidden]{display:none!important}';
  }

  function readNavOpen() {
    try {
      var v = localStorage.getItem(NAV_KEY);
      if (v === null || v === undefined) return false; /* 預設隱藏，放大總覽可視區 */
      return v === '1' || v === 'true';
    } catch (e) { return false; }
  }

  function applyNavOpen(open) {
    state.navOpen = !!open;
    var row = $('shell-row');
    if (!row) return;
    row.classList.toggle('nr-open', state.navOpen);
    row.classList.toggle('nr-collapsed', !state.navOpen);
    var rail = $('navrail');
    if (rail) {
      rail.setAttribute('aria-hidden', state.navOpen ? 'false' : 'true');
      if (state.navOpen) rail.removeAttribute('inert');
      else rail.setAttribute('inert', '');
    }
    var edge = $('nr-edge');
    if (edge) edge.setAttribute('aria-expanded', state.navOpen ? 'true' : 'false');
    try { localStorage.setItem(NAV_KEY, state.navOpen ? '1' : '0'); } catch (e) {}
  }

  function setNavOpen(open) { applyNavOpen(open); }

  function toggleNav() { applyNavOpen(!state.navOpen); }

  function stubHTML(route) {
    return '' +
      '<div class="sv-kicker">STOCK TERMINAL · ' + VERSION + '</div>' +
      '<div class="sv-title">' + route.label + '</div>' +
      '<p class="sv-desc">' + route.hint +
        '。面板載入中或尚未掛接資料模組。</p>' +
      '<div class="sv-meta">route = ' + route.id + '</div>' +
      '<button type="button" class="sv-cta" data-shell-back>← 回到圖表工作區</button>';
  }

  function railHTML() {
    return '<div class="nr-brand-st" title="Stock Terminal ' + VERSION + '">' +
      '<div class="logo-box"><img src="assets/st50-icon.svg" alt="Stock Terminal" width="34" height="34"></div>' +
      '<div class="logo-text">' +
        '<div class="brand-title">Stock Terminal</div>' +
        '<div class="brand-sub">v' + VERSION + '</div>' +
      '</div>' +
      '<button type="button" class="nr-hide" id="nr-hide" title="隱藏側欄（[ 或 Ctrl/⌘B）" aria-label="隱藏側欄">‹</button>' +
      '</div>' +
      ROUTES.map(function (r) {
        return '<button type="button" class="nr-btn" data-route="' + r.id + '" title="' +
          r.hint.replace(/"/g, '') + ' (Alt+Shift)" aria-label="' + r.label + '">' +
          '<span class="nr-ico" aria-hidden="true">' + r.icon + '</span>' +
          '<span>' + r.label + '</span></button>';
      }).join('') +
      '<div class="nr-spacer"></div>' +
      '<div class="nr-foot-st">' +
        '<div class="mode-dot">● LOCAL · v' + VERSION + '</div>' +
        '<div class="mode-sub">[ 側欄 · \\／中鍵轉盤 · Esc 關閉</div>' +
      '</div>';
  }

  function edgeHTML() {
    return '<button type="button" class="nr-edge" id="nr-edge" title="展開側欄（[／Ctrl⌘B）· 轉盤（中鍵或 \\）" ' +
      'aria-label="展開功能選單" aria-expanded="false">' +
      '<span class="nr-edge-ico" aria-hidden="true">›</span>' +
      '<span class="nr-edge-lbl">選單</span>' +
      '<span class="nr-edge-ring" aria-hidden="true">◎</span>' +
      '</button>';
  }

  function btnMeta(id) {
    var m = RING_BTN_META[id] || {};
    var el = document.getElementById(id);
    var raw = '';
    if (el) {
      raw = String(el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!raw && el.title) raw = String(el.title).split(/[：:(]/)[0];
    }
    raw = raw.replace(/^[^\u4e00-\u9fffA-Za-z0-9]+/, '').trim();
    var label = m.label || (raw ? raw.slice(0, 3) : id.replace(/^btn-/, '').slice(0, 4));
    var hint = (el && el.title) || m.label || id;
    return { label: label, icon: m.icon || '·', hint: hint };
  }

  function ringClick(id) {
    var m = btnMeta(id);
    return { id: 'click:' + id, label: m.label, icon: m.icon, hint: m.hint, clickId: id };
  }

  function ringRoute(id, label, icon, hint) {
    var r = findRoute(id) || {};
    return {
      id: id,
      label: label || r.label || id,
      icon: icon || r.icon || '·',
      hint: hint || r.hint || '',
      route: id
    };
  }

  function ringFolder(id, label, icon, hint, children) {
    return {
      id: id,
      label: label,
      icon: icon,
      hint: hint,
      children: children || []
    };
  }

  /**
   * 投資分析邏輯樹（最多 3 層）
   * L1 分析域 → L2 子域／頁面 → L3 工具按鈕
   */
  function ringAnalysisTree() {
    return [
      ringFolder('market', '總覽', '◎', '市場儀表板／快訊／風險', [
        ringRoute('pulse', '儀表板', '◎', '一屏高密度總覽'),
        ringRoute('news', '快訊', '◉', '事件／結算／警報'),
        ringRoute('risk', '風險', '◇', '風險事件與脈動')
      ]),
      ringFolder('price', '行情', '◈', '價格、技術、盤後', [
        ringRoute('chart', 'K線', '◈', '圖表工作區'),
        ringFolder('tech', '技術', '▦', '量價／多圖／畫線', [
          ringClick('btn-vp'), ringClick('btn-multichart'), ringClick('btn-compare'),
          ringClick('btn-spread'), ringClick('btn-drawtools'), ringClick('btn-replay'),
          ringClick('btn-overnight')
        ]),
        ringRoute('afterhours', '盤後', '◐', '排行／夜盤／籌碼摘要')
      ]),
      ringFolder('flow', '籌碼', '₴', '法人、資金流、基本面', [
        ringRoute('institutional', '法人頁', '₴', '三大法人動向'),
        ringFolder('flow-tools', '資金流', '💰', '資金與排行工具', [
          ringClick('btn-marketflow'), ringClick('btn-instrank'),
          ringClick('btn-stockfut'), ringClick('btn-chainmom')
        ]),
        ringFolder('fundamentals', '基本面', '⚓', '估值／供應鏈／投組', [
          ringClick('btn-valuation'), ringClick('btn-supplychain'),
          ringClick('btn-portfolio')
        ])
      ]),
      ringFolder('screen', '選股', '▷', '篩選、策略、回測', [
        ringRoute('scan', '選股室', '▷', '三合一選股頁'),
        ringFolder('screen-tools', '策略庫', '🔬', '選股／型態／回測', [
          ringClick('btn-screener3'), ringClick('btn-screener'), ringClick('btn-patterns'),
          ringClick('btn-stratbuilder'), ringClick('btn-bt3'), ringClick('btn-wizard'),
          ringClick('btn-stratscript')
        ]),
        ringRoute('signals', '訊號', '✦', '策略訊號／焦點結果')
      ]),
      ringFolder('breadth', '廣度', '▤', '市場廣度與類股', [
        ringRoute('breadth', '漲跌家數', '▤', '大盤廣度'),
        ringRoute('heat', '熱力', '▦', '類股熱力圖'),
        ringRoute('afterhours', '排行', '◐', '漲跌排行（盤後）')
      ]),
      ringFolder('global', '國際', '◎', '海外與總經', [
        ringRoute('international', '國際頁', '◎', '美股／美元／黃金／銅'),
        ringClick('btn-calendar')
      ]),
      ringFolder('ai', 'AI', '✧', '報告、副駕、焦點', [
        ringRoute('ai', 'AI中樞', '✧', 'AI 報告／副駕頁'),
        ringFolder('ai-tools', 'AI工具', '🤖', '報告／副駕／焦點掃描', [
          ringClick('btn-ai-report'), ringClick('btn-copilot'), ringClick('btn-focus')
        ])
      ]),
      ringFolder('desk', '工作台', '★', '自選、投組、系統', [
        ringRoute('watchlist', '自選', '★', '自選股中心'),
        ringRoute('book', '投組', '▣', '投組風險'),
        ringFolder('sys', '系統', '⚙', '資料與快捷', [
          ringClick('btn-cmdp'), ringClick('btn-universe'), ringClick('btn-datasources'),
          ringClick('btn-datahealth'), ringClick('btn-hotkeys'), ringClick('btn-alertpush'),
          ringClick('btn-live')
        ]),
        ringRoute('settings', '設定', '⚙', '同步與資料來源')
      ])
    ];
  }

  function ringNeedsChart(item) {
    if (!item) return false;
    if (item.clickId) return true;
    if (item.children && item.children.length) {
      for (var i = 0; i < item.children.length; i++) {
        if (ringNeedsChart(item.children[i])) return true;
      }
    }
    return false;
  }

  function ensureRing() {
    if ($('st-ring')) return $('st-ring');
    var root = document.createElement('div');
    root.id = 'st-ring';
    root.setAttribute('aria-hidden', 'true');
    root.innerHTML =
      '<button type="button" class="sr-backdrop" id="st-ring-bd" aria-label="關閉功能轉盤"></button>' +
      '<div class="sr-wheel" id="st-ring-wheel" role="menu" aria-label="分析功能轉盤">' +
        '<div class="sr-level" id="st-ring-level">L1 · 分析主選單</div>' +
        '<div class="sr-layers" id="st-ring-layers"></div>' +
        '<button type="button" class="sr-hub" id="st-ring-hub" title="關閉" aria-label="關閉轉盤">✕</button>' +
        '<div class="sr-tip" id="st-ring-tip">中鍵／\\ · 點 › 從該點開下一層</div>' +
      '</div>';
    document.body.appendChild(root);
    root.addEventListener('click', onRingClick);
    root.addEventListener('pointermove', onRingPointer);
    return root;
  }

  function ringDepth() { return ringState.layers.length; }

  function activeLayer() {
    var d = ringDepth();
    return d ? ringState.layers[d - 1] : null;
  }

  function itemOffsetOnLayer(layer, idx) {
    var items = (layer && layer.items) || [];
    var n = items.length || 1;
    var ang = -Math.PI / 2 + idx * (Math.PI * 2 / n);
    return {
      ox: (layer.ox || 0) + Math.cos(ang) * RING_R,
      oy: (layer.oy || 0) + Math.sin(ang) * RING_R
    };
  }

  function syncActiveCenter() {
    var a = activeLayer();
    if (!a) return;
    ringState.cx = ringState.wx + (a.ox || 0);
    ringState.cy = ringState.wy + (a.oy || 0);
  }

  /* 作用層圓心貼近螢幕邊緣時平移 wheel，避免下一層轉盤被裁切 */
  function clampWheelForActive() {
    var a = activeLayer();
    if (!a) return;
    var ax = ringState.wx + (a.ox || 0);
    var ay = ringState.wy + (a.oy || 0);
    var pad = RING_R + 48;
    var nx = Math.max(pad, Math.min(window.innerWidth - pad, ax));
    var ny = Math.max(pad, Math.min(window.innerHeight - pad, ay));
    ringState.wx += nx - ax;
    ringState.wy += ny - ay;
    var wheel = $('st-ring-wheel');
    if (wheel) {
      wheel.style.left = ringState.wx + 'px';
      wheel.style.top = ringState.wy + 'px';
    }
    syncActiveCenter();
  }

  function paintRingAnchor() {
    var a = activeLayer();
    var ox = a ? (a.ox || 0) : 0;
    var oy = a ? (a.oy || 0) : 0;
    var hub = $('st-ring-hub');
    if (hub) {
      hub.style.left = ox + 'px';
      hub.style.top = oy + 'px';
    }
    var tip = $('st-ring-tip');
    if (tip) {
      tip.style.left = ox + 'px';
      tip.style.top = (oy + 86) + 'px';
    }
    var level = $('st-ring-level');
    if (level) {
      level.style.left = ox + 'px';
      level.style.top = (oy - 100) + 'px';
    }
  }

  function paintRingHub() {
    var hub = $('st-ring-hub');
    if (!hub) return;
    var deep = ringDepth() > 1;
    hub.textContent = deep ? '‹' : '✕';
    hub.title = deep ? '返回上一層' : '關閉';
    hub.setAttribute('aria-label', hub.title);
    hub.classList.toggle('back', deep);
  }

  function paintRingCrumbs() {
    var level = $('st-ring-level');
    if (!level) return;
    var parts = [];
    for (var i = 0; i < ringState.layers.length; i++) {
      var t = ringState.layers[i].title || ('L' + (i + 1));
      if (i === ringState.layers.length - 1) parts.push('L' + (i + 1) + ' · ' + t);
      else parts.push('<span class="sr-crumb">' + t + '</span>');
    }
    level.innerHTML = parts.join(' › ') || 'L1 · 分析主選單';
  }

  function renderRingLayers() {
    var host = $('st-ring-layers');
    if (!host) return;
    host.innerHTML = '';
    var depth = ringDepth();
    if (!depth) return;
    var activeIdx = depth - 1;
    syncActiveCenter();
    paintRingAnchor();
    ringState.layers.forEach(function (layer, li) {
      var locked = li < activeIdx;
      var ox = layer.ox || 0;
      var oy = layer.oy || 0;
      var layerEl = document.createElement('div');
      layerEl.className = 'sr-layer ' + (locked ? 'locked' : 'active');
      layerEl.setAttribute('data-layer', String(li));
      var items = layer.items || [];
      var n = items.length || 1;
      items.forEach(function (r, idx) {
        var ang = -Math.PI / 2 + idx * (Math.PI * 2 / n);
        var x = ox + Math.cos(ang) * RING_R;
        var y = oy + Math.sin(ang) * RING_R;
        var btn = document.createElement('button');
        btn.type = 'button';
        var cls = 'sr-item';
        if (r.children && r.children.length) cls += ' has-kids';
        if (layer.pickedId && layer.pickedId === r.id) cls += ' picked';
        btn.className = cls;
        btn.setAttribute('role', 'menuitem');
        btn.setAttribute('data-layer', String(li));
        btn.setAttribute('data-idx', String(idx));
        btn.setAttribute('data-id', r.id);
        if (r.route) btn.setAttribute('data-route', r.route);
        btn.title = (r.hint || r.label) + (r.children && r.children.length ? ' · 由此展開下一層' : '');
        btn.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px)';
        /* 已展開的父項落在下一層圓心（中心鈕），鎖定層隱藏避免疊在 hub 上 */
        if (locked && layer.pickedId && layer.pickedId === r.id) {
          btn.style.visibility = 'hidden';
          btn.setAttribute('aria-hidden', 'true');
        }
        btn.innerHTML = '<span class="sr-ico" aria-hidden="true">' + (r.icon || '·') + '</span>' +
          '<span class="sr-lbl">' + r.label + '</span>';
        layerEl.appendChild(btn);
      });
      host.appendChild(layerEl);
    });
    ringState.items = ringState.layers[activeIdx].items || [];
    paintRingHub();
    paintRingCrumbs();
    paintRingActive();
    setRingHighlight(-1);
  }

  function ensureRingFab() {
    if ($('st-ring-fab')) return;
    var fab = document.createElement('button');
    fab.type = 'button';
    fab.id = 'st-ring-fab';
    fab.title = '分析轉盤（中鍵或 \\）· 最多三層';
    fab.setAttribute('aria-label', '開啟功能轉盤');
    fab.textContent = '◎';
    fab.addEventListener('click', function (e) {
      e.preventDefault();
      openRing(window.innerWidth - 80, window.innerHeight - 80);
    });
    document.body.appendChild(fab);
  }

  function paintRingActive() {
    var nodes = document.querySelectorAll('#st-ring .sr-layer.active .sr-item');
    for (var i = 0; i < nodes.length; i++) {
      var route = nodes[i].getAttribute('data-route');
      var on = !!route && route === state.route;
      var item = ringState.items[i];
      if (item && item.clickId) {
        var el = document.getElementById(item.clickId);
        if (el && el.classList.contains('on')) on = true;
      }
      nodes[i].classList.toggle('on', on);
    }
  }

  function setRingHighlight(idx) {
    ringState.hi = idx;
    var nodes = document.querySelectorAll('#st-ring .sr-layer.active .sr-item');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].classList.toggle('hi', i === idx);
    }
    var hub = $('st-ring-hub');
    if (hub) hub.classList.toggle('hi', idx === -2);
    var tip = $('st-ring-tip');
    if (!tip) return;
    var deep = ringDepth() > 1;
    if (idx === -2) {
      tip.textContent = deep ? '返回上一層（上層保持鎖定顯示）' : '關閉轉盤';
      return;
    }
    if (idx < 0) {
      tip.textContent = 'L' + ringDepth() + '/' + RING_MAX_DEPTH +
        (deep ? ' · 上層鎖定 · ‹ 返回' : ' · 點 › 從該點開下一層');
      return;
    }
    var r = ringState.items[idx];
    if (!r) { tip.textContent = ''; return; }
    tip.textContent = r.label +
      (r.children && r.children.length ? ' ›' : '') +
      ' — ' + (r.hint || '');
  }

  function ringIndexFromPoint(clientX, clientY) {
    var dx = clientX - ringState.cx;
    var dy = clientY - ringState.cy;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 28) return -2;
    var n = ringState.items.length || 1;
    var radius = RING_R;
    if (dist < 48 || dist > radius + 40) return -1;
    var ang = Math.atan2(dy, dx);
    var step = (Math.PI * 2) / n;
    var norm = ang + Math.PI / 2;
    if (norm < 0) norm += Math.PI * 2;
    var idx = Math.round(norm / step) % n;
    if (idx < 0) idx += n;
    return idx;
  }

  function onRingPointer(e) {
    if (!ringState.open) return;
    setRingHighlight(ringIndexFromPoint(e.clientX, e.clientY));
  }

  function ringPushChildren(item, idx) {
    var kids = item.children || [];
    if (!kids.length) return;
    if (ringDepth() >= RING_MAX_DEPTH) {
      if (window.UI && window.UI.toast) window.UI.toast('已達第三層上限', 1400);
      return;
    }
    if (ringNeedsChart(item) && state.route !== 'chart') go('chart');
    var cur = ringState.layers[ringDepth() - 1];
    if (!cur) return;
    cur.pickedId = item.id;
    var off = itemOffsetOnLayer(cur, idx | 0);
    /* 下一層以點選功能為圓心（非原轉盤置中） */
    ringState.layers.push({
      title: item.label,
      items: kids,
      pickedId: null,
      ox: off.ox,
      oy: off.oy
    });
    clampWheelForActive();
    renderRingLayers();
  }

  function ringPop() {
    if (ringDepth() <= 1) {
      closeRing();
      return;
    }
    ringState.layers.pop();
    var cur = ringState.layers[ringDepth() - 1];
    if (cur) cur.pickedId = null;
    clampWheelForActive();
    renderRingLayers();
  }

  function activateRingItem(item, idx) {
    if (!item) return;
    if (item.children && item.children.length) {
      ringPushChildren(item, idx);
      return;
    }
    if (item.clickId) {
      closeRing();
      if (state.route !== 'chart') go('chart');
      setTimeout(function () {
        var el = document.getElementById(item.clickId);
        if (el) {
          try { el.click(); } catch (err) { console.warn('[st-ring] click', item.clickId, err); }
        } else if (window.UI && window.UI.toast) {
          window.UI.toast('找不到工具：' + item.label, 1800);
        }
      }, 80);
      return;
    }
    if (item.route) {
      closeRing();
      go(item.route);
    }
  }

  function onRingClick(e) {
    if (!ringState.open) return;
    if (e.target.closest('#st-ring-bd')) {
      e.preventDefault();
      closeRing();
      return;
    }
    if (e.target.closest('#st-ring-hub')) {
      e.preventDefault();
      ringPop();
      return;
    }
    /* 僅作用層可點；鎖定層忽略 */
    var node = e.target.closest('.sr-layer.active .sr-item');
    if (!node) return;
    e.preventDefault();
    var idx = parseInt(node.getAttribute('data-idx'), 10);
    activateRingItem(ringState.items[idx], idx);
  }

  function openRing(clientX, clientY) {
    ensureRing();
    ensureRingFab();
    var pad = RING_R + 48;
    var x = Math.max(pad, Math.min(window.innerWidth - pad, clientX || window.innerWidth / 2));
    var y = Math.max(pad, Math.min(window.innerHeight - pad, clientY || window.innerHeight / 2));
    ringState.open = true;
    ringState.wx = x;
    ringState.wy = y;
    ringState.cx = x;
    ringState.cy = y;
    ringState.layers = [{
      title: '分析主選單',
      items: ringAnalysisTree(),
      pickedId: null,
      ox: 0,
      oy: 0
    }];
    var root = $('st-ring');
    var wheel = $('st-ring-wheel');
    if (!root || !wheel) return;
    wheel.style.left = x + 'px';
    wheel.style.top = y + 'px';
    root.classList.add('on');
    root.setAttribute('aria-hidden', 'false');
    renderRingLayers();
    setNavOpen(false);
  }

  function closeRing() {
    if (!ringState.open && !$('st-ring')) return;
    ringState.open = false;
    ringState.hi = -1;
    ringState.wx = 0;
    ringState.wy = 0;
    ringState.cx = 0;
    ringState.cy = 0;
    ringState.layers = [];
    ringState.items = [];
    var root = $('st-ring');
    if (root) {
      root.classList.remove('on');
      root.setAttribute('aria-hidden', 'true');
    }
    var host = $('st-ring-layers');
    if (host) host.innerHTML = '';
  }

  function toggleRing(clientX, clientY) {
    if (ringState.open) closeRing();
    else openRing(clientX, clientY);
  }

  function ensureNavChrome(row) {
    if (!row) return;
    if (!$('nr-edge')) {
      row.insertAdjacentHTML('beforeend', edgeHTML());
    }
    if (!$('nr-backdrop')) {
      var bd = document.createElement('button');
      bd.type = 'button';
      bd.id = 'nr-backdrop';
      bd.className = 'nr-backdrop';
      bd.setAttribute('aria-label', '關閉側欄');
      bd.setAttribute('tabindex', '-1');
      row.appendChild(bd);
    }
    var edge = $('nr-edge');
    var backdrop = $('nr-backdrop');
    if (edge && !edge._nrBound) {
      edge._nrBound = true;
      edge.addEventListener('click', function (e) {
        e.preventDefault();
        /* 點轉盤圖示 → 開功能轉盤；其餘 → 展開側欄 */
        if (e.target.closest('.nr-edge-ring')) {
          var rect = edge.getBoundingClientRect();
          openRing(rect.right + 120, rect.top + rect.height / 2);
          return;
        }
        setNavOpen(true);
      });
    }
    if (backdrop && !backdrop._nrBound) {
      backdrop._nrBound = true;
      backdrop.addEventListener('click', function (e) {
        e.preventDefault();
        setNavOpen(false);
      });
    }
  }

  function ensurePanel(r) {
    if (r.id === 'chart' || r.action) return;
    if ($('view-' + r.id)) return;
    var views = $('shell-views');
    if (!views) return;
    var p = document.createElement('section');
    p.className = 'sv-panel';
    p.id = 'view-' + r.id;
    p.dataset.route = r.id;
    p.setAttribute('hidden', '');
    p.setAttribute('aria-hidden', 'true');
    p.innerHTML = r.stub ? stubHTML(r) : '<div class="sv-mount" id="mount-' + r.id + '"></div>';
    views.appendChild(p);
  }

  function ensureStructure() {
    if (state.built) return true;
    var app = $('app');
    var body = $('body');
    if (!app || !body) return false;

    injectCSS();

    var logo = app.querySelector('#topbar .logo');
    if (logo) {
      if (!logo.querySelector('.shell-logo-ico')) {
        var ico = document.createElement('img');
        ico.className = 'shell-logo-ico';
        ico.src = 'assets/st50-icon.svg';
        ico.alt = '';
        ico.width = 18;
        ico.height = 18;
        logo.insertBefore(ico, logo.firstChild);
      }
      if (!logo.querySelector('.shell-ver')) {
        var ver = document.createElement('span');
        ver.className = 'shell-ver';
        ver.textContent = 'v' + VERSION;
        logo.appendChild(ver);
      } else {
        logo.querySelector('.shell-ver').textContent = 'v' + VERSION;
      }
    }
    /* favicon：與側欄 ST icon 同一資產 */
    if (!document.querySelector('link[data-st50-favicon]')) {
      var fav = document.createElement('link');
      fav.rel = 'icon';
      fav.type = 'image/svg+xml';
      fav.href = 'assets/st50-icon.svg';
      fav.setAttribute('data-st50-favicon', '1');
      document.head.appendChild(fav);
    }

    var topbar = $('topbar');
    if (topbar && !$('shell-sync')) {
      var sync = document.createElement('div');
      sync.id = 'shell-sync';
      sync.className = 'shell-sync';
      sync.innerHTML = '<span class="ss-dot" aria-hidden="true"></span><span id="shell-sync-txt">LOCAL</span>';
      var status = $('statusbar');
      if (status && status.parentElement === topbar) topbar.insertBefore(sync, status);
      else {
        var keybtn = $('keybtn');
        if (keybtn) topbar.insertBefore(sync, keybtn);
        else topbar.appendChild(sync);
      }
    }
    if (topbar && !$('shell-sync-btn')) {
      var sbtn = document.createElement('button');
      sbtn.type = 'button';
      sbtn.id = 'shell-sync-btn';
      sbtn.className = 'shell-sync-btn';
      sbtn.title = '預抓歷史庫並合併最近資料';
      sbtn.innerHTML = '⟳ <span class="lbl">同步資料</span>';
      sbtn.addEventListener('click', function () { runSync(true); });
      var syncEl = $('shell-sync');
      if (syncEl && syncEl.parentElement === topbar) {
        if (syncEl.nextSibling) topbar.insertBefore(sbtn, syncEl.nextSibling);
        else topbar.appendChild(sbtn);
      } else {
        topbar.appendChild(sbtn);
      }
    }

    if (!$('shell-row')) {
      var row = document.createElement('div');
      row.id = 'shell-row';

      var rail = document.createElement('nav');
      rail.id = 'navrail';
      rail.setAttribute('aria-label', '主選單');
      rail.innerHTML = railHTML();

      var main = document.createElement('div');
      main.id = 'shell-main';

      var views = document.createElement('div');
      views.id = 'shell-views';
      ROUTES.forEach(function (r) {
        if (r.id === 'chart' || r.action) return;
        var p = document.createElement('section');
        p.className = 'sv-panel';
        p.id = 'view-' + r.id;
        p.dataset.route = r.id;
        p.setAttribute('hidden', '');
        p.setAttribute('aria-hidden', 'true');
        p.innerHTML = '<div class="sv-mount" id="mount-' + r.id + '"></div>';
        views.appendChild(p);
      });

      body.parentElement.insertBefore(row, body);
      row.appendChild(rail);
      row.appendChild(main);
      /* topbar／wlbar 移入 shell-main，僅圖表路由顯示，避免壓在其他 tab 上方 */
      var topbarEl = $('topbar');
      var wlEl = $('wlbar');
      if (topbarEl) main.appendChild(topbarEl);
      if (wlEl) main.appendChild(wlEl);
      main.appendChild(body);
      main.appendChild(views);

      ensureNavChrome(row);
      ensureRingFab();
      rail.addEventListener('click', onNavrailClick);
      views.addEventListener('click', function (e) {
        if (e.target.closest('[data-shell-back]')) go('chart');
      });
    } else {
      var row2 = $('shell-row');
      var rail2 = $('navrail');
      if (rail2) {
        rail2.innerHTML = railHTML();
        if (!rail2._nrClickBound) {
          rail2._nrClickBound = true;
          rail2.addEventListener('click', onNavrailClick);
        }
      }
      ensureNavChrome(row2);
      ensureRingFab();
      ROUTES.forEach(ensurePanel);
    }

    applyNavOpen(readNavOpen());
    state.built = true;
    return true;
  }

  function onNavrailClick(e) {
    var hide = e.target.closest('#nr-hide');
    if (hide) {
      e.preventDefault();
      setNavOpen(false);
      return;
    }
    var btn = e.target.closest('.nr-btn');
    if (!btn) return;
    go(btn.getAttribute('data-route'));
    /* 窄螢幕導航後收合，把可視區留給內容 */
    if (window.matchMedia && window.matchMedia('(max-width: 1100px)').matches) {
      setNavOpen(false);
    }
  }

  function setSync(mode, text) {
    var el = $('shell-sync');
    var txt = $('shell-sync-txt');
    if (!el || !txt) return;
    el.classList.remove('warn', 'err');
    if (mode === 'warn') el.classList.add('warn');
    if (mode === 'err') el.classList.add('err');
    txt.textContent = text || 'LOCAL';
  }

  function toast(msg, ms) {
    if (window.UI && window.UI.toast) window.UI.toast(msg, ms || 2800);
    else if (typeof window.notifyToast === 'function') window.notifyToast(msg);
    else console.log('[ST5]', msg);
  }

  function pollSyncDone(tries) {
    tries = tries || 0;
    return fetch('/sync/status', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.running && tries < 90) {
          return new Promise(function (res) {
            setTimeout(function () { res(pollSyncDone(tries + 1)); }, 1000);
          });
        }
        return j;
      });
  }

  function runSync(manual) {
    if (state.syncing) return;
    state.syncing = true;
    var btn = $('shell-sync-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '⟳ <span class="lbl">同步中…</span>'; }
    setSync('warn', 'SYNCING');
    if (manual) toast('歷史庫合併同步中（僅抓最近缺漏日）…', 3500);
    fetch('/sync?days=40', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function () { return pollSyncDone(0); })
      .then(function (st) {
        if (!st || !st.ok) throw new Error((st && st.lastError) || 'sync failed');
        var c = st.counts || {};
        var msg = '同步完成 · 指數 ' + (c.index || 0) + ' · 廣度 ' + (c.breadth || 0) +
          ' · 法人 ' + (c.institutional || 0);
        setSync('ok', 'SYNC OK');
        toast(msg, 4200);
        emitRoute(state.route);
      })
      .catch(function (e) {
        setSync('err', 'SYNC ERR');
        toast('同步失敗：' + (e && e.message ? e.message : e), 4000);
      })
      .finally(function () {
        state.syncing = false;
        if (btn) { btn.disabled = false; btn.innerHTML = '⟳ <span class="lbl">同步資料</span>'; }
      });
  }

  function probeHealth() {
    if (typeof fetch !== 'function') return;
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, 2500);
    Promise.all([
      fetch('/health', { signal: ctrl && ctrl.signal }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch('/sync/status', { cache: 'no-store' }).then(function (r) { return r.json(); }).catch(function () { return null; })
    ]).then(function (arr) {
      var h = arr[0];
      var s = arr[1];
      if (!h) { setSync('warn', 'LOCAL'); return; }
      if (s && s.running) { setSync('warn', 'SYNCING'); return; }
      var n = s && s.counts ? (s.counts.index || 0) : 0;
      setSync('ok', n ? ('DB ' + n) : 'SYNC OK');
    }).finally(function () { clearTimeout(t); });
  }

  function panelApi(id) {
    var key = PANEL_MAP[id];
    return key && window[key] ? window[key] : null;
  }

  function deactivateRoute(id) {
    if (!id || id === 'chart') return;
    var api = panelApi(id);
    if (api && typeof api.deactivate === 'function') {
      try { api.deactivate(); }
      catch (err) { console.warn('[shell-v5] deactivate ' + id, err); }
    }
  }

  function emitRoute(id, retries) {
    retries = retries || 0;
    try {
      window.dispatchEvent(new CustomEvent('shell:route', { detail: { route: id } }));
    } catch (e) {}
    var key = PANEL_MAP[id];
    if (!key) return;
    if (window[key] && typeof window[key].activate === 'function') {
      try { window[key].activate(); }
      catch (err) { console.warn('[shell-v5] ' + key + ' activate', err); }
      return;
    }
    /* 模組尚未載入：短重試，避免開成空白舊介面 */
    if (retries < 20) {
      setTimeout(function () { emitRoute(id, retries + 1); }, 50);
    } else {
      console.warn('[shell-v5] module not ready: ' + key + ' (route=' + id + ')');
    }
  }

  function findRoute(id) {
    for (var i = 0; i < ROUTES.length; i++) if (ROUTES[i].id === id) return ROUTES[i];
    return null;
  }

  function resolveAlias(id, opts) {
    opts = opts || {};
    var a = ROUTE_ALIASES[id];
    if (!a) return { id: id, opts: opts };
    return {
      id: a.to,
      opts: {
        sym: opts.sym || a.sym,
        mkt: opts.mkt || a.mkt
      }
    };
  }

  function applyRoute(id, opts) {
    opts = opts || {};
    var resolved = resolveAlias(id, opts);
    id = resolved.id;
    opts = resolved.opts;

    var route = findRoute(id) || findRoute('chart') || ROUTES[0];

    if (route.action === 'cmd') {
      id = 'chart';
      route = findRoute('chart') || ROUTES[0];
      setTimeout(function () {
        var b = $('btn-cmdp');
        if (b) b.click();
        else if (window.cmdPaletteOpen) window.cmdPaletteOpen();
      }, 0);
    } else {
      id = route.id;
    }

    if (state.prevRoute && state.prevRoute !== id) {
      deactivateRoute(state.prevRoute);
    }
    state.route = id;
    state.prevRoute = id;
    try { localStorage.setItem(STORAGE_KEY, id); } catch (e) {}
    try {
      if (window.history && window.history.replaceState) {
        var base = window.location.pathname + (window.location.search || '');
        window.history.replaceState(null, '', base + '#' + id);
      } else {
        window.location.hash = id;
      }
    } catch (e2) {}

    var topbar = $('topbar');
    var body = $('body');
    var wl = $('wlbar');
    var views = $('shell-views');
    var isChart = id === 'chart';

    if (topbar) topbar.classList.toggle('shell-hidden', !isChart);
    if (body) body.classList.toggle('shell-hidden', !isChart);
    if (wl) wl.classList.toggle('shell-hidden', !isChart);
    if (views) views.classList.toggle('show', !isChart);
    /* 圖表底列大盤／市場條僅圖表頁顯示，勿蓋到其他 shell tab */
    var mktBar = $('mkt-bar');
    if (mktBar) mktBar.classList.toggle('shell-hidden', !isChart);

    var panels = document.querySelectorAll('.sv-panel');
    for (var p = 0; p < panels.length; p++) {
      var active = panels[p].dataset.route === id;
      panels[p].classList.toggle('on', active);
      if (active) {
        panels[p].removeAttribute('hidden');
        panels[p].setAttribute('aria-hidden', 'false');
      } else {
        panels[p].setAttribute('hidden', '');
        panels[p].setAttribute('aria-hidden', 'true');
      }
    }

    var btns = document.querySelectorAll('#navrail .nr-btn');
    for (var b = 0; b < btns.length; b++) {
      var rid = btns[b].getAttribute('data-route');
      var on = rid === id && rid !== 'workspace';
      btns[b].classList.toggle('on', on);
      if (on) btns[b].setAttribute('aria-current', 'page');
      else btns[b].removeAttribute('aria-current');
    }
    if (ringState.open) paintRingActive();

    if (isChart) {
      setTimeout(function () {
        try { window.dispatchEvent(new Event('resize')); } catch (e) {}
      }, 30);
    }

    if (opts.sym && typeof loadSym === 'function') {
      var sym = opts.sym, mkt = opts.mkt || 'TW';
      setTimeout(function () {
        try { loadSym(sym, mkt); } catch (e) { console.warn('[shell-v5] loadSym', e); }
      }, isChart ? 40 : 0);
    }

    emitRoute(id);
  }

  function go(id, opts) {
    if (!ensureStructure()) return;
    applyRoute(id || 'pulse', opts || {});
  }

  function boot() {
    if (!ensureStructure()) return setTimeout(boot, 120);
    /* 移除舊「指數」面板 DOM（若熱更新殘留） */
    ['trends', 'index'].forEach(function (rid) {
      var orphan = $('view-' + rid);
      if (orphan && orphan.parentNode) orphan.parentNode.removeChild(orphan);
    });
    /*
     * tip UX only：
     * - 有合法 hash → 跟 hash（含使用者主動開 #chart）
     * - 無 hash → 一律 #pulse（絕不吃 localStorage 的 chart，避免合完／重開閃回舊圖表殼）
     */
    var saved = 'pulse';
    var hash = (window.location.hash || '').replace(/^#/, '').trim();
    if (hash && findRoute(hash)) {
      saved = hash;
    } else {
      saved = 'pulse';
      try {
        if (window.history && window.history.replaceState) {
          var base = window.location.pathname + (window.location.search || '');
          window.history.replaceState(null, '', base + '#pulse');
        } else {
          window.location.hash = 'pulse';
        }
      } catch (eHash) {}
    }
    /* 舊「指數」分頁 → 圖表加權；非法 route → 總覽 */
    if (saved === 'trends' || saved === 'index') {
      applyRoute('chart', { sym: '^TWII', mkt: 'TW' });
    } else {
      if (!saved || !findRoute(saved)) saved = 'pulse';
      applyRoute(saved);
    }
    try {
      document.documentElement.classList.add('st5-booted');
      document.documentElement.setAttribute('data-st5-ux', 'tip');
      document.documentElement.setAttribute('data-st5-route', state.route);
    } catch (eBootCls) {}
    probeHealth();
    setInterval(probeHealth, 60000);
    window.addEventListener('hashchange', function () {
      var h = (window.location.hash || '').replace(/^#/, '').trim();
      if (h && findRoute(h) && h !== state.route) go(h);
    });
    /* 歷史庫過薄時自動背景 merge（不打擾） */
    setTimeout(function () {
      fetch('/sync/status', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j || !j.ok || j.running) return;
          if (((j.counts && j.counts.index) || 0) < 5) runSync(false);
        })
        .catch(function () {});
    }, 2800);
    document.addEventListener('keydown', onShellKey, true);
    document.addEventListener('auxclick', onShellAuxClick, true);
    document.addEventListener('mousedown', onShellMiddleDown, true);
    console.log('[shell-v5] Stock Terminal ' + VERSION + ' · tip UX · route=' + state.route +
      ' · ring=中鍵/\\\\');
  }

  function inEditable(el) {
    if (!el) return false;
    var tag = (el.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    return !!el.isContentEditable;
  }

  function onShellKey(e) {
    if (inEditable(e.target)) return;
    var meta = e.metaKey || e.ctrlKey;
    /* Esc：轉盤有子層先返回，否則關轉盤；再關側欄 */
    if (e.key === 'Escape') {
      if (ringState.open) {
        e.preventDefault();
        e.stopPropagation();
        /* 有上層鎖定層 → 返回；否則關閉 */
        ringPop();
        return;
      }
      if (state.navOpen) {
        e.preventDefault();
        e.stopPropagation();
        setNavOpen(false);
        return;
      }
    }
    /* Backspace：轉盤子層返回 */
    if (ringState.open && e.key === 'Backspace') {
      e.preventDefault();
      ringPop();
      return;
    }
    /* \\：功能轉盤（MX Master 風格） */
    if (e.key === '\\' && !e.altKey && !meta) {
      e.preventDefault();
      toggleRing(window.innerWidth / 2, window.innerHeight / 2);
      return;
    }
    /* 轉盤開啟時：方向鍵環選；Enter 確認／下鑽 */
    if (ringState.open) {
      var n = ringState.items.length || 1;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        setRingHighlight(((ringState.hi < 0 ? -1 : ringState.hi) + 1 + n) % n);
        return;
      }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        setRingHighlight(((ringState.hi < 0 ? 0 : ringState.hi) - 1 + n) % n);
        return;
      }
      if (e.key === 'Enter' && ringState.hi >= 0) {
        e.preventDefault();
        activateRingItem(ringState.items[ringState.hi], ringState.hi);
        return;
      }
    }
    /* [ 或 Ctrl/⌘B：切換浮動側欄 */
    if (e.key === '[' || (meta && (e.key === 'b' || e.key === 'B'))) {
      e.preventDefault();
      closeRing();
      toggleNav();
      return;
    }
    if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && /^[0-9]$/.test(e.key)) {
      var idx = e.key === '0' ? 9 : (parseInt(e.key, 10) - 1);
      var rid = HOTKEY_ROUTES[idx];
      if (rid) {
        e.preventDefault();
        closeRing();
        go(rid);
      }
    }
  }

  function onShellAuxClick(e) {
    if (inEditable(e.target)) return;
    /* 滑鼠中鍵：在游標處開／關功能轉盤（類 MX Master Gesture Button） */
    if (e.button === 1) {
      e.preventDefault();
      toggleRing(e.clientX, e.clientY);
    }
  }

  function onShellMiddleDown(e) {
    if (e.button === 1 && !inEditable(e.target)) {
      e.preventDefault(); /* 避免中鍵自動捲動 */
    }
  }

  window.ShellV5 = {
    VERSION: VERSION,
    TIP_UX: TIP_UX,
    ROUTES: ROUTES,
    HOTKEY_ROUTES: HOTKEY_ROUTES,
    RING_ROUTES: RING_ROUTES,
    RING_MAX_DEPTH: RING_MAX_DEPTH,
    ALIASES: ROUTE_ALIASES,
    go: go,
    navigate: go,
    route: function () { return state.route; },
    toggleNav: toggleNav,
    setNavOpen: setNavOpen,
    isNavOpen: function () { return !!state.navOpen; },
    openRing: openRing,
    closeRing: closeRing,
    toggleRing: toggleRing,
    isRingOpen: function () { return !!ringState.open; },
    ringDepth: function () { return ringDepth(); },
    ringAnalysisTree: ringAnalysisTree,
    setSync: setSync,
    sync: function () { runSync(true); },
    softBadge: function (mountId, on, text) {
      var mount = $(mountId);
      if (!mount) return;
      var b = mount.querySelector('.sv-soft-badge');
      if (!b) {
        b = document.createElement('div');
        b.className = 'sv-soft-badge';
        mount.insertBefore(b, mount.firstChild);
      }
      b.textContent = text || '更新中…';
      b.classList.toggle('on', !!on);
    },
    /** 開圖表並載入代號（指數預設 ^TWII） */
    openChart: function (sym, mkt) {
      go('chart', { sym: sym || '^TWII', mkt: mkt || 'TW' });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
