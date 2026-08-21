/* ============================================================================
 * shell_v5.js  —  Stock Terminal 5.0：轉盤殼層 + 視圖路由（tip UX only）
 * ----------------------------------------------------------------------------
 * tip UX 唯一執行線：開啟一律 #pulse（總覽）並自動彈出分析轉盤。
 * 導航改由分析轉盤（中鍵／\\／FAB）；側欄已移除，ROUTES 全數掛入轉盤樹。
 * 啟動前隱藏 #body／#wlbar，避免 shell 尚未掛上時閃出舊 UI。
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
  var VERSION = '5.0';
  var TIP_UX = true;
  var PRIVATE_WEB = !!(window.ST_PRIVATE_WEB_PROFILE &&
    window.ST_PRIVATE_WEB_PROFILE.profile === 'personal-market');
  var RING_LOGO = 'assets/st50-icon.svg';

  /* 舊 route → 更完整的目的地（圖表／熱力等） */
  var ROUTE_ALIASES = {
    trends: { to: 'chart', sym: '^TWII', mkt: 'TW' },   // 指數頁 → 圖表加權
    index:  { to: 'chart', sym: '^TWII', mkt: 'TW' }
  };

  var ROUTES = [
    { id: 'pulse',         label: '總覽', hint: '市場總覽儀表板（一屏高密度）', icon: '◎' },
    { id: 'decision',      label: '決策', hint: '情境矩陣／行動範圍／證據鏈',                 icon: '◆' },
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
    { id: 'factors',       label: '因子', hint: '脈動因子帳本（正面／風險／未納入）',         icon: '☰' },
    { id: 'news',          label: '快訊', hint: '事件／結算／警報中樞',                     icon: '◉' },
    { id: 'scan',          label: '選股', hint: '三合一選股（技術×基本面×籌碼）',           icon: '▷' },
    { id: 'book',          label: '投組', hint: '投組風險（波動／VaR／曝險）',               icon: '▣' },
    { id: 'settings',      label: '設定', hint: '同步狀態與資料來源',                       icon: '⚙' },
    { id: 'wavedeck',      label: '執行', hint: '開啟 WaveDeck 浪潮執行台（微觀下單艦橋）', icon: '⚡', action: 'wavedeck' },
    { id: 'workspace',     label: '工具', hint: '回到圖表並開啟指令盤',                     icon: '⌘', action: 'cmd' }
  ];
  if (PRIVATE_WEB) {
    ROUTES = ROUTES.filter(function (route) { return route.id !== 'wavedeck'; });
  }

  var state = { route: 'pulse', built: false, syncing: false, prevRoute: null };

  /* Alt+Shift+1…0 → 常用路由（避開 Alt+數字 時框） */
  var HOTKEY_ROUTES = [
    'pulse', 'chart', 'breadth', 'heat', 'institutional',
    'international', 'afterhours', 'ai', 'news', 'scan'
  ];

  /* 功能轉盤：最多 3 層；依投資分析邏輯分類；上層保留半透明鎖定 */
  var RING_MAX_DEPTH = 3;
  var RING_R = 112; /* 各層轉盤半徑（下一層以點選項為圓心） */
  var RING_SPIN_IN_MS = 520;
  var RING_SPIN_OUT_MS = 420;
  var RING_ROUTES = [
    'market', 'price', 'flow', 'screen',
    'breadth', 'global', 'ai', 'desk'
  ];
  var ringState = {
    open: false,
    wx: 0, wy: 0,   /* wheel 原點（螢幕座標） */
    cx: 0, cy: 0,   /* 作用層圓心（螢幕座標，供命中／游標） */
    hi: -1,
    wheelAcc: 0,    /* 滾輪累積，過閾值才換選 */
    layers: [],     /* [{ title, items, pickedId, ox, oy }] 最多 3；ox/oy 相對 wheel */
    items: [],      /* = 作用層 items */
    animating: false
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
    decision: 'DecisionV5',
    breadth: 'BreadthV5',
    heat: 'HeatV5',
    institutional: 'InstitutionalV5',
    international: 'InternationalV5',
    afterhours: 'AfterhoursV5',
    signals: 'SignalsV5',
    ai: 'AiV5',
    watchlist: 'WatchlistV5',
    risk: 'RiskV5',
    factors: 'FactorsV5',
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
      /* 主區全寬；導航改由轉盤（無側欄） */
      '#shell-row{display:flex;flex:1 1 0;min-height:0;min-width:0;height:100%;position:relative}' +
      '#shell-main{display:flex;flex-direction:column;flex:1 1 0;min-width:0;min-height:0;height:100%;position:relative;width:100%}' +
      /* 熱更新殘留側欄強制隱藏 */
      '#navrail,#nr-edge,#nr-backdrop{display:none!important;pointer-events:none!important}' +
      /* 品牌集中轉盤中心：內頁不再重複 STOCK TERMINAL kicker */
      '.pl-kicker,.hub-kicker,.bd-kicker,.ht-kicker,.ah-kicker,.nw-kicker,.sc-kicker,.bk-kicker,.sv-kicker,.ai5-kicker{' +
        'display:none!important}' +
      '.sv-soft-badge{position:sticky;top:0;z-index:3;display:none;align-items:center;gap:6px;' +
        'padding:3px 8px;margin:0 0 6px;font-family:\'JetBrains Mono\',monospace;font-size:9px;' +
        'color:var(--gold);background:rgba(245,197,24,.08);border:1px solid var(--gold-m);border-radius:5px;align-self:flex-start}' +
      '.sv-soft-badge.on{display:inline-flex}' +
      '#topbar .logo .shell-logo-ico{width:18px;height:18px;border-radius:4px;margin-right:6px;' +
        'vertical-align:middle;border:1px solid rgba(245,197,24,.35);object-fit:cover}' +
      '#shell-views{display:none!important;flex:1 1 0;min-height:0;min-width:0;height:100%;background:#060C16;overflow:auto}' +
      '#shell-views.show{display:flex!important;flex-direction:column;flex:1 1 0;min-height:0;height:100%}' +
      /* 高密度一頁視圖：鎖定捲動（各模組亦會覆寫） */
      '#shell-views.show:has(.sv-panel.on){overflow:hidden;flex:1 1 0;min-height:0}' +
      '#view-decision.sv-panel.on,#view-breadth.sv-panel.on,#view-heat.sv-panel.on,#view-afterhours.sv-panel.on,' +
      '#view-institutional.sv-panel.on,#view-international.sv-panel.on,#view-signals.sv-panel.on,' +
      '#view-ai.sv-panel.on,#view-watchlist.sv-panel.on,#view-risk.sv-panel.on,#view-factors.sv-panel.on,#view-news.sv-panel.on,' +
      '#view-scan.sv-panel.on,#view-book.sv-panel.on,#view-settings.sv-panel.on,' +
      '#view-pulse.sv-panel.on{max-width:none!important}' +
      '#topbar.shell-hidden{display:none !important}' +
      '#body.shell-hidden{display:none !important}' +
      '#rpanel-pager.shell-hidden{display:none !important}' +
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
      '#topbar .shell-sync{display:inline-flex;align-items:center;gap:5px;margin-left:4px;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px;' +
        'max-width:min(22vw,160px);min-width:0;overflow:hidden;white-space:nowrap;flex:0 1 auto;' +
        'vertical-align:middle;line-height:1.2}' +
      '#topbar .shell-sync .ss-dot{width:6px;height:6px;border-radius:50%;background:var(--green);' +
        'box-shadow:0 0 6px var(--green);flex-shrink:0}' +
      '#topbar .shell-sync.warn .ss-dot{background:var(--orange);box-shadow:0 0 6px var(--orange)}' +
      '#topbar .shell-sync.err .ss-dot{background:var(--red);box-shadow:0 0 6px var(--red)}' +
      '#topbar #shell-sync-txt,#topbar #shell-wd-sync-txt{overflow:hidden;text-overflow:ellipsis;' +
        'white-space:nowrap;min-width:0;max-width:100%}' +
      '#topbar #shell-wd-sync{max-width:min(28vw,200px)}' +
      '#topbar .shell-sync-btn{display:inline-flex;align-items:center;gap:5px;margin-left:6px;' +
        'padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--thi);font-family:\'JetBrains Mono\',monospace;font-size:10px;cursor:pointer;' +
        'letter-spacing:.3px;flex:0 0 auto;white-space:nowrap;line-height:1.2;' +
        'writing-mode:horizontal-tb;max-width:none}' +
      '#topbar .shell-sync-btn:hover{border-color:var(--gold-m);color:var(--gold)}' +
      '#topbar .shell-sync-btn:disabled{opacity:.55;cursor:wait}' +
      '#topbar .logo .shell-ver{margin-left:6px;font-size:9px;color:var(--gold);letter-spacing:1px;font-weight:700}' +
      '#topbar .logo [data-v2-banner] span,' +
      '#topbar .logo>span[style*="FBBF24"]{display:none !important}' +
      '@media (max-width:1024px){' +
        '.sv-panel{padding:8px 8px 10px}' +
        '#topbar .shell-sync-btn span.lbl{display:none}' +
      '}' +
      /* ── 功能轉盤：立體軌道／鈕；上層鎖定；滾輪循環選取 ── */
      '#st-ring{position:fixed;inset:0;z-index:240;display:none;pointer-events:none}' +
      '#st-ring.on{display:block;pointer-events:auto}' +
      '#st-ring .sr-backdrop{position:absolute;inset:0;' +
        'background:radial-gradient(ellipse at center,rgba(8,16,28,.42) 0%,rgba(2,8,18,.72) 70%);' +
        'backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);border:0;padding:0;cursor:default}' +
      '#st-ring .sr-wheel{position:absolute;width:0;height:0;transform:translate(-50%,-50%);' +
        'pointer-events:none}' +
      '#st-ring.on .sr-wheel{animation:sr-pop .2s cubic-bezier(.2,1.2,.4,1) both}' +
      '@keyframes sr-pop{from{opacity:0;transform:translate(-50%,-50%) scale(.55)}' +
        'to{opacity:1;transform:translate(-50%,-50%) scale(1)}}' +
      '#st-ring .sr-layers{position:absolute;left:0;top:0;width:0;height:0}' +
      '#st-ring .sr-layer{position:absolute;left:0;top:0;width:0;height:0;pointer-events:none;' +
        'transition:opacity .22s ease,filter .22s ease;will-change:transform,opacity}' +
      /* 下鑽：下一層以圓心為軸滾輪式轉入 */
      '#st-ring .sr-layer.spin-in{animation:sr-spin-in .52s cubic-bezier(.18,.9,.22,1) both;' +
        'transition:none;z-index:3;pointer-events:none}' +
      '#st-ring .sr-layer.spin-out{animation:sr-spin-out .42s cubic-bezier(.4,0,.55,1) both;' +
        'transition:none;z-index:4;pointer-events:none!important}' +
      '#st-ring .sr-layer.spin-in .sr-item,#st-ring .sr-layer.spin-out .sr-item{pointer-events:none!important}' +
      '#st-ring .sr-layer.reveal{animation:sr-reveal .36s cubic-bezier(.2,.85,.3,1) both}' +
      '@keyframes sr-spin-in{' +
        '0%{opacity:0;transform:rotate(-155deg) scale(.22);filter:blur(3px) brightness(.7)}' +
        '55%{opacity:1;filter:blur(0) brightness(1.05)}' +
        '100%{opacity:1;transform:rotate(0deg) scale(1);filter:none}}' +
      '@keyframes sr-spin-out{' +
        '0%{opacity:1;transform:rotate(0deg) scale(1);filter:none}' +
        '100%{opacity:0;transform:rotate(150deg) scale(.2);filter:blur(3px) brightness(.65)}}' +
      '@keyframes sr-reveal{' +
        '0%{opacity:.28;filter:saturate(.4) brightness(.82)}' +
        '100%{opacity:1;filter:none}}' +
      '#st-ring .sr-layer.spin-in .sr-orbit{animation:sr-orbit-glow .52s ease-out both}' +
      '#st-ring .sr-layer.spin-out .sr-orbit{animation:sr-orbit-fade .42s ease-in both}' +
      '@keyframes sr-orbit-glow{0%{opacity:0;filter:blur(4px)}100%{opacity:1;filter:none}}' +
      '@keyframes sr-orbit-fade{0%{opacity:1}100%{opacity:0;filter:blur(4px)}}' +
      '#st-ring .sr-layer.spin-in .sr-item{animation:sr-item-in .4s cubic-bezier(.2,1.15,.3,1) both;' +
        'animation-delay:calc(var(--sr-i, 0) * 26ms)}' +
      '@keyframes sr-item-in{' +
        '0%{opacity:0;filter:brightness(.6)}' +
        '100%{opacity:1;filter:none}}' +
      '@media (prefers-reduced-motion:reduce){' +
        '#st-ring .sr-layer.spin-in,#st-ring .sr-layer.spin-out,#st-ring .sr-layer.reveal,' +
        '#st-ring .sr-layer.spin-in .sr-orbit,#st-ring .sr-layer.spin-out .sr-orbit,' +
        '#st-ring .sr-layer.spin-in .sr-item{animation-duration:.01ms!important;animation-delay:0s!important}}' +
      /* 軌道圓：雙框＋內外陰影＋斜光漸層 */
      '#st-ring .sr-orbit{position:absolute;left:0;top:0;border-radius:50%;pointer-events:none;' +
        'box-sizing:border-box;z-index:0;' +
        'background:radial-gradient(circle,' +
          'transparent calc(50% - 3.5px),' +
          'rgba(245,197,24,.14) calc(50% - 2.5px),' +
          'rgba(56,189,248,.22) calc(50% - 1px),' +
          'rgba(15,23,42,.95) 50%,' +
          'transparent calc(50% + 1px));' +
        'box-shadow:' +
          '0 0 0 1px rgba(30,41,59,.75),' +
          '0 10px 28px rgba(0,0,0,.42),' +
          '0 0 24px rgba(56,189,248,.08),' +
          'inset 0 2px 4px rgba(255,255,255,.07),' +
          'inset 0 -3px 8px rgba(0,0,0,.45)}' +
      '#st-ring .sr-orbit::before{content:"";position:absolute;inset:8%;border-radius:50%;' +
        'background:conic-gradient(from 200deg,' +
          'rgba(245,197,24,.28),rgba(148,163,184,.08),rgba(56,189,248,.22),' +
          'rgba(148,163,184,.06),rgba(245,197,24,.28));' +
        '-webkit-mask:radial-gradient(circle,transparent 66%,#000 67%,#000 71%,transparent 72%);' +
        'mask:radial-gradient(circle,transparent 66%,#000 67%,#000 71%,transparent 72%);' +
        'opacity:.85;pointer-events:none}' +
      '#st-ring .sr-orbit::after{content:"";position:absolute;inset:18%;border-radius:50%;' +
        'box-shadow:inset 0 0 28px rgba(0,0,0,.35);pointer-events:none}' +
      '#st-ring .sr-layer.locked{opacity:.28;filter:saturate(.4) brightness(.82)}' +
      '#st-ring .sr-layer.locked .sr-item{pointer-events:none!important;cursor:default;' +
        'box-shadow:0 2px 8px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.04)!important;' +
        'border-color:rgba(51,65,85,.65)!important}' +
      '#st-ring .sr-layer.locked .sr-orbit{opacity:.55;filter:grayscale(.2)}' +
      '#st-ring .sr-layer.locked .sr-item.picked{opacity:1;filter:none;' +
        'border-color:rgba(245,197,24,.5)!important;color:rgba(245,197,24,.8);' +
        'box-shadow:0 0 0 1px rgba(245,197,24,.18),0 4px 12px rgba(0,0,0,.35)!important}' +
      '#st-ring .sr-layer.active{opacity:1;filter:none;z-index:2}' +
      '#st-ring .sr-layer.active .sr-item{pointer-events:auto}' +
      /* 中心：Stock Terminal 5.0 logo（立體金屬框）；子層顯示返回徽記 */
      '#st-ring .sr-hub{position:absolute;left:0;top:0;width:62px;height:62px;margin:-31px 0 0 -31px;' +
        'border-radius:50%;z-index:5;padding:0;cursor:pointer;pointer-events:auto;' +
        'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;' +
        'border:1px solid rgba(245,197,24,.55);' +
        'background:' +
          'radial-gradient(circle at 32% 26%,rgba(253,224,71,.18) 0%,transparent 40%),' +
          'radial-gradient(circle at 70% 80%,rgba(0,0,0,.55) 0%,transparent 48%),' +
          'linear-gradient(155deg,#1a2740 0%,#0c1626 52%,#070e18 100%);' +
        'box-shadow:' +
          '0 0 0 3px rgba(245,197,24,.16),' +
          '0 1px 0 rgba(255,255,255,.18) inset,' +
          '0 -3px 8px rgba(0,0,0,.5) inset,' +
          '0 12px 28px rgba(0,0,0,.55),' +
          '0 0 22px rgba(245,197,24,.14);' +
        'transition:transform .12s ease,box-shadow .12s ease,filter .12s,border-color .12s}' +
      '#st-ring .sr-hub::before{content:"";position:absolute;inset:3px;border-radius:50%;' +
        'background:linear-gradient(150deg,rgba(255,255,255,.14) 0%,rgba(255,255,255,.02) 42%,transparent 60%);' +
        'pointer-events:none}' +
      '#st-ring .sr-hub .sr-logo{width:34px;height:34px;border-radius:9px;display:block;position:relative;z-index:1;' +
        'border:1px solid rgba(245,197,24,.4);box-shadow:0 2px 8px rgba(0,0,0,.45);object-fit:cover;' +
        'background:#070E18}' +
      '#st-ring .sr-hub .sr-hub-ver{position:relative;z-index:1;font:800 8px/1 "JetBrains Mono",monospace;' +
        'color:var(--gold);letter-spacing:.7px;text-shadow:0 1px 3px rgba(0,0,0,.7)}' +
      '#st-ring .sr-hub .sr-hub-badge{position:absolute;right:-2px;top:-2px;z-index:2;' +
        'min-width:18px;height:18px;padding:0 4px;border-radius:999px;' +
        'display:flex;align-items:center;justify-content:center;' +
        'font:800 11px/1 "JetBrains Mono",monospace;color:#fff;' +
        'border:1px solid rgba(254,202,202,.55);' +
        'background:linear-gradient(160deg,#fb7185,#9f1239);' +
        'box-shadow:0 2px 8px rgba(0,0,0,.45),0 0 0 2px rgba(8,15,28,.65)}' +
      '#st-ring .sr-hub:hover,#st-ring .sr-hub.hi{transform:scale(1.06);filter:brightness(1.06);' +
        'border-color:rgba(250,204,21,.8);' +
        'box-shadow:' +
          '0 0 0 4px rgba(245,197,24,.24),' +
          '0 1px 0 rgba(255,255,255,.22) inset,' +
          '0 -3px 8px rgba(0,0,0,.5) inset,' +
          '0 14px 32px rgba(0,0,0,.6),' +
          '0 0 28px rgba(245,197,24,.22)}' +
      '#st-ring .sr-hub.back{border-color:rgba(56,189,248,.55);' +
        'box-shadow:' +
          '0 0 0 3px rgba(56,189,248,.2),' +
          '0 1px 0 rgba(255,255,255,.18) inset,' +
          '0 -3px 8px rgba(0,0,0,.5) inset,' +
          '0 12px 28px rgba(0,0,0,.55),' +
          '0 0 22px rgba(56,189,248,.16)}' +
      '#st-ring .sr-hub.back .sr-hub-badge{border-color:rgba(186,230,253,.55);' +
        'background:linear-gradient(160deg,#38bdf8,#075985)}' +
      '#st-ring .sr-hub.back:hover,#st-ring .sr-hub.back.hi{border-color:rgba(125,211,252,.85);' +
        'box-shadow:' +
          '0 0 0 4px rgba(56,189,248,.28),' +
          '0 1px 0 rgba(255,255,255,.22) inset,' +
          '0 -3px 8px rgba(0,0,0,.5) inset,' +
          '0 14px 32px rgba(0,0,0,.6),' +
          '0 0 28px rgba(56,189,248,.24)}' +
      /* 功能鈕：斜光＋內外陰影＋邊框漸層感（位置用 --sr-x/--sr-y） */
      '#st-ring .sr-item{position:absolute;left:0;top:0;width:56px;height:56px;margin:-28px 0 0 -28px;' +
        'border-radius:50%;z-index:1;' +
        'border:1px solid rgba(100,116,139,.55);' +
        'background:' +
          'radial-gradient(circle at 30% 24%,rgba(226,232,240,.22) 0%,transparent 38%),' +
          'radial-gradient(circle at 70% 80%,rgba(0,0,0,.55) 0%,transparent 48%),' +
          'linear-gradient(155deg,#243548 0%,#152337 48%,#0a1422 100%);' +
        'color:#e2e8f0;cursor:pointer;' +
        'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;' +
        'transform:translate(var(--sr-x,0px),var(--sr-y,0px));' +
        'box-shadow:' +
          '0 1px 0 rgba(255,255,255,.14) inset,' +
          '0 -2px 5px rgba(0,0,0,.45) inset,' +
          '0 0 0 1px rgba(15,23,42,.85),' +
          '0 8px 18px rgba(0,0,0,.48),' +
          '0 2px 4px rgba(0,0,0,.35);' +
        'transition:transform .13s cubic-bezier(.2,1.1,.4,1),border-color .12s,color .12s,' +
          'box-shadow .13s,filter .12s,opacity .16s}' +
      '#st-ring .sr-item::before{content:"";position:absolute;inset:3px;border-radius:50%;' +
        'background:linear-gradient(150deg,rgba(255,255,255,.16) 0%,rgba(255,255,255,.03) 40%,transparent 58%);' +
        'pointer-events:none;z-index:0}' +
      '#st-ring .sr-item .sr-ico,#st-ring .sr-item .sr-lbl{position:relative;z-index:1}' +
      '#st-ring .sr-item .sr-ico{font-size:14px;line-height:1;opacity:.95;' +
        'text-shadow:0 1px 2px rgba(0,0,0,.55)}' +
      '#st-ring .sr-item .sr-lbl{font:700 9px/1 "JetBrains Mono",monospace;letter-spacing:.15px;opacity:.92;' +
        'text-shadow:0 1px 2px rgba(0,0,0,.5)}' +
      '#st-ring .sr-layer.active .sr-item:hover,#st-ring .sr-layer.active .sr-item.hi{' +
        'transform:translate(var(--sr-x,0px),var(--sr-y,0px)) scale(1.12);' +
        'border-color:rgba(250,204,21,.75);color:var(--gold);' +
        'background:' +
          'radial-gradient(circle at 30% 24%,rgba(253,224,71,.28) 0%,transparent 40%),' +
          'radial-gradient(circle at 70% 80%,rgba(0,0,0,.4) 0%,transparent 48%),' +
          'linear-gradient(155deg,#2f4560 0%,#1a2c44 50%,#101c30 100%);' +
        'box-shadow:' +
          '0 1px 0 rgba(255,255,255,.22) inset,' +
          '0 -2px 5px rgba(0,0,0,.4) inset,' +
          '0 0 0 2px rgba(245,197,24,.28),' +
          '0 0 18px rgba(245,197,24,.18),' +
          '0 10px 24px rgba(0,0,0,.55)}' +
      '#st-ring .sr-item.on{border-color:rgba(56,189,248,.7);color:#7dd3fc;' +
        'box-shadow:' +
          '0 1px 0 rgba(255,255,255,.16) inset,' +
          '0 -2px 5px rgba(0,0,0,.4) inset,' +
          '0 0 0 2px rgba(56,189,248,.22),' +
          '0 0 14px rgba(56,189,248,.16),' +
          '0 8px 18px rgba(0,0,0,.48)}' +
      '#st-ring .sr-item.has-kids::after{content:"›";position:absolute;right:5px;top:50%;' +
        'transform:translateY(-50%);font-size:10px;color:var(--gold);opacity:.95;z-index:1;' +
        'text-shadow:0 0 6px rgba(245,197,24,.45)}' +
      '#st-ring .sr-tip{position:absolute;left:50%;top:86px;transform:translateX(-50%);z-index:5;' +
        'font:600 10px/1.3 "JetBrains Mono",monospace;color:#94a3b8;white-space:nowrap;' +
        'pointer-events:none;text-shadow:0 1px 8px rgba(0,0,0,.8);max-width:320px;' +
        'overflow:hidden;text-overflow:ellipsis;' +
        'padding:3px 8px;border-radius:999px;background:rgba(8,15,28,.55);' +
        'border:1px solid rgba(51,65,85,.45);backdrop-filter:blur(2px)}' +
      '#st-ring .sr-level{position:absolute;left:50%;top:-108px;transform:translateX(-50%);z-index:5;' +
        'font:700 9px/1.35 "JetBrains Mono",monospace;color:var(--gold);letter-spacing:.3px;' +
        'white-space:nowrap;pointer-events:auto;text-shadow:0 1px 8px rgba(0,0,0,.8);text-align:center;' +
        'padding:3px 8px;border-radius:999px;background:rgba(8,15,28,.5);' +
        'border:1px solid rgba(245,197,24,.22);display:flex;flex-wrap:wrap;align-items:center;' +
        'justify-content:center;gap:2px;max-width:min(72vw,420px)}' +
      '#st-ring .sr-level .sr-crumb{appearance:none;border:0;background:transparent;padding:1px 4px;' +
        'margin:0;border-radius:6px;cursor:pointer;color:#94a3b8;font:inherit;letter-spacing:inherit;' +
        'text-decoration:underline;text-underline-offset:2px;text-decoration-color:rgba(148,163,184,.35)}' +
      '#st-ring .sr-level .sr-crumb:hover{color:#e2e8f0;background:rgba(255,255,255,.06);' +
        'text-decoration-color:rgba(245,197,24,.55)}' +
      '#st-ring .sr-level .sr-crumb:focus-visible{outline:2px solid rgba(245,197,24,.55);outline-offset:1px}' +
      '#st-ring .sr-level .sr-sep{opacity:.55;pointer-events:none;user-select:none;color:var(--gold)}' +
      '#st-ring-fab{position:fixed;right:14px;bottom:14px;z-index:90;width:42px;height:42px;' +
        'border-radius:50%;border:1px solid rgba(245,197,24,.45);' +
        'background:' +
          'radial-gradient(circle at 32% 28%,rgba(253,224,71,.2) 0%,transparent 40%),' +
          'linear-gradient(155deg,#1e2d48 0%,#0c1626 100%);' +
        'color:var(--gold);font:800 15px/1 "JetBrains Mono",monospace;cursor:pointer;' +
        'box-shadow:' +
          '0 1px 0 rgba(255,255,255,.12) inset,' +
          '0 -2px 5px rgba(0,0,0,.4) inset,' +
          '0 8px 22px rgba(0,0,0,.5),' +
          '0 0 12px rgba(245,197,24,.12);' +
        'display:flex;align-items:center;justify-content:center;' +
        'transition:transform .14s ease,border-color .14s,box-shadow .14s}' +
      '#st-ring-fab:hover{transform:scale(1.06);border-color:var(--gold);' +
        'box-shadow:' +
          '0 1px 0 rgba(255,255,255,.18) inset,' +
          '0 -2px 5px rgba(0,0,0,.4) inset,' +
          '0 0 0 3px rgba(245,197,24,.16),' +
          '0 10px 26px rgba(0,0,0,.55)}' +
      '#st-ring-fab[hidden]{display:none!important}' +
      /* 圖表頂欄 Logo／快捷鈕 → 儀表板 */
      '#topbar .logo{cursor:pointer}' +
      '#topbar .logo:hover{filter:brightness(1.08)}' +
      '#topbar{position:relative;flex-wrap:nowrap;min-height:42px;max-height:42px;overflow:hidden;isolation:isolate}' +
      '#wlbar{position:relative;z-index:1;isolation:isolate}' +
      '#topbar #keybtn{order:90;margin-left:auto!important;flex:0 0 auto}' +
      '#topbar .shell-dash-btn{position:relative;display:inline-flex;align-items:center;gap:6px;margin-left:6px;' +
        'order:100;flex:0 0 auto;height:28px;padding:3px 10px 3px 4px;overflow:hidden;' +
        'border-radius:8px;border:1px solid rgba(255,215,78,.82);' +
        'background:linear-gradient(135deg,#ffe36a 0%,#f5c518 48%,#d99a08 100%);' +
        'color:#07111d;font:900 10px/1.2 "JetBrains Mono",monospace;cursor:pointer;white-space:nowrap;' +
        'box-shadow:0 0 0 1px rgba(245,197,24,.16),0 6px 18px rgba(226,169,11,.28),' +
        'inset 0 1px 0 rgba(255,255,255,.5);text-shadow:0 1px 0 rgba(255,255,255,.24);' +
        'transition:transform .16s ease,filter .16s ease,box-shadow .16s ease}' +
      '#topbar .shell-dash-btn:before{content:"";position:absolute;inset:-8px auto -8px -40%;width:34%;' +
        'transform:skewX(-18deg);background:linear-gradient(90deg,transparent,rgba(255,255,255,.66),transparent);' +
        'animation:shellDashSheen 3.2s ease-in-out infinite;pointer-events:none}' +
      '#topbar .shell-dash-btn>*{position:relative;z-index:1}' +
      '#topbar .shell-dash-glyph{width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;' +
        'justify-content:center;background:linear-gradient(145deg,#14243a,#07111d);' +
        'border:1px solid rgba(255,255,255,.22);box-shadow:0 2px 7px rgba(0,0,0,.36),0 0 10px rgba(255,221,74,.22)}' +
      '#topbar .shell-dash-glyph img{width:14px;height:14px;display:block;border-radius:3px}' +
      '#topbar .shell-dash-btn:hover{filter:brightness(1.08) saturate(1.08);transform:translateY(-1px);' +
        'box-shadow:0 0 0 2px rgba(245,197,24,.18),0 8px 22px rgba(226,169,11,.36),' +
        'inset 0 1px 0 rgba(255,255,255,.58)}' +
      '@keyframes shellDashSheen{0%,62%{left:-40%}82%,100%{left:125%}}' +
      '@media(prefers-reduced-motion:reduce){#topbar .shell-dash-btn:before{animation:none}}' +
      /* 手機直式統一由 shell-views 擔任唯一捲動容器；內容底部避開浮動轉盤與 iOS safe area。 */
      '@media(max-width:900px) and (orientation:portrait){' +
        '#shell-main #shell-views.show{display:block!important;overflow-x:hidden!important;overflow-y:auto!important;' +
          'height:100%!important;min-height:0!important;overscroll-behavior-y:contain;scroll-padding-bottom:calc(80px + env(safe-area-inset-bottom,0px))}' +
        '#shell-main #shell-views.show>.sv-panel.on{display:block!important;flex:none!important;height:auto!important;min-height:100%!important;' +
          'overflow:visible!important;padding-bottom:calc(80px + env(safe-area-inset-bottom,0px))!important}' +
        '#shell-main #shell-views.show>.sv-panel.on>.sv-mount{display:block!important;height:auto!important;min-height:0!important;overflow:visible!important}' +
        '#st-ring-fab{bottom:calc(14px + env(safe-area-inset-bottom,0px))}' +
      '}';
  }

  function stubHTML(route) {
    return '' +
      '<div class="sv-kicker">STOCK TERMINAL · ' + VERSION + '</div>' +
      '<div class="sv-title">' + route.label + '</div>' +
      '<p class="sv-desc">' + route.hint +
        '。面板載入中或尚未掛接資料模組。</p>' +
      '<div class="sv-meta">route = ' + route.id + '</div>' +
      '<button type="button" class="sv-cta" data-shell-back>← 返回儀表板</button>';
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
        ringRoute('decision', '策略決策', '◆', '情境矩陣／行動範圍／證據鏈'),
        ringRoute('news', '快訊', '◉', '事件／結算／警報'),
        ringRoute('risk', '風險', '◇', '風險事件與脈動'),
        ringRoute('factors', '因子帳本', '☰', '正面／風險／未納入')
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
      ringFolder('desk', '工作台', '★', '自選、投組、系統（含原側欄「工具」指令盤）', [
        ringRoute('watchlist', '自選', '★', '自選股中心'),
        ringRoute('book', '投組', '▣', '投組風險'),
        PRIVATE_WEB ? null : ringRoute('wavedeck', 'WaveDeck', '⚡', '開啟浪潮執行台'),
        ringFolder('sys', '系統', '⚙', '指令盤／資料／快捷（原側欄工具＋設定工具）', [
          ringClick('btn-cmdp'), /* workspace／工具 */
          ringClick('btn-universe'), ringClick('btn-datasources'),
          ringClick('btn-datahealth'), ringClick('btn-hotkeys'), ringClick('btn-alertpush'),
          ringClick('btn-toast'), ringClick('btn-live')
        ]),
        ringRoute('settings', '設定', '⚙', '同步與資料來源')
      ].filter(Boolean))
    ];
  }

  /** 轉盤是否涵蓋某一 sidebar route（含 workspace→指令盤） */
  function ringCoversRoute(routeId) {
    if (!routeId) return false;
    if (routeId === 'workspace') return true; /* → btn-cmdp */
    function walk(nodes) {
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (n.route === routeId) return true;
        if (n.children && n.children.length && walk(n.children)) return true;
      }
      return false;
    }
    return walk(ringAnalysisTree());
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
      '<div class="sr-wheel" id="st-ring-wheel" role="menu" aria-label="Stock Terminal 分析轉盤">' +
        '<div class="sr-level" id="st-ring-level">L1 · 分析主選單</div>' +
        '<div class="sr-layers" id="st-ring-layers"></div>' +
        '<button type="button" class="sr-hub" id="st-ring-hub" title="Stock Terminal 5.0" aria-label="Stock Terminal 5.0">' +
          '<img class="sr-logo" src="' + RING_LOGO + '" alt="Stock Terminal" width="34" height="34">' +
          '<span class="sr-hub-ver">' + VERSION + '</span>' +
          '<span class="sr-hub-badge" aria-hidden="true">◎</span>' +
        '</button>' +
        '<div class="sr-tip" id="st-ring-tip">滾輪循環選 · 點 › 從該點開下一層</div>' +
      '</div>';
    document.body.appendChild(root);
    root.addEventListener('click', onRingClick);
    root.addEventListener('pointermove', onRingPointer);
    root.addEventListener('wheel', onRingWheel, { passive: false });
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

  function goDashboard() {
    closeRing();
    go('pulse');
  }

  function paintRingHub() {
    var hub = $('st-ring-hub');
    if (!hub) return;
    if (!hub.querySelector('.sr-logo')) {
      hub.innerHTML =
        '<img class="sr-logo" src="' + RING_LOGO + '" alt="Stock Terminal" width="34" height="34">' +
        '<span class="sr-hub-ver">' + VERSION + '</span>' +
        '<span class="sr-hub-badge" aria-hidden="true">◎</span>';
    }
    var badge = hub.querySelector('.sr-hub-badge');
    if (badge) badge.textContent = '◎';
    hub.title = '返回儀表板 · Stock Terminal ' + VERSION;
    hub.setAttribute('aria-label', hub.title);
    /* 中心 Logo 固定為儀表板快捷；子層返回改走 Esc／麵包屑／滾輪上一層 */
    hub.classList.remove('back');
  }

  function paintRingCrumbs() {
    var level = $('st-ring-level');
    if (!level) return;
    var parts = [];
    for (var i = 0; i < ringState.layers.length; i++) {
      var t = ringState.layers[i].title || ('L' + (i + 1));
      if (i === ringState.layers.length - 1) {
        parts.push('L' + (i + 1) + ' · ' + t);
      } else {
        /* 上層麵包屑可點：一次回到該層（等同多次返回） */
        parts.push('<button type="button" class="sr-crumb" data-ring-pop-to="' + i + '" title="回到：' +
          t.replace(/"/g, '&quot;') + '">' + t + '</button>');
      }
    }
    level.innerHTML = parts.join('<span class="sr-sep" aria-hidden="true"> › </span>') || 'L1 · 分析主選單';
  }

  /** 回到指定層（保留 0..toIdx）；toIdx 缺省＝上一層 */
  function ringPopTo(toIdx) {
    if (ringDepth() <= 1) {
      closeRing();
      return;
    }
    if (ringState.animating) return;
    if (toIdx == null || toIdx < 0) {
      ringPop();
      return;
    }
    toIdx = Math.min(toIdx, ringDepth() - 1);
    if (toIdx >= ringDepth() - 1) return;
    animateLayerOut(function () {
      while (ringDepth() - 1 > toIdx) {
        ringState.layers.pop();
      }
      var cur = ringState.layers[ringDepth() - 1];
      if (cur) cur.pickedId = null;
      clampWheelForActive();
      renderRingLayers({ reveal: true });
    });
  }

  function prefersReducedMotion() {
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) {
      return false;
    }
  }

  /** 作用層滾輪轉出；完成後呼叫 done */
  function animateLayerOut(done) {
    var host = $('st-ring-layers');
    var active = host && host.querySelector('.sr-layer.active');
    if (!active || prefersReducedMotion()) {
      if (done) done();
      return;
    }
    ringState.animating = true;
    active.classList.remove('spin-in', 'reveal');
    active.classList.add('spin-out');
    var finished = false;
    function finish() {
      if (finished) return;
      finished = true;
      active.removeEventListener('animationend', onEnd);
      clearTimeout(tid);
      ringState.animating = false;
      if (done) done();
    }
    function onEnd(ev) {
      if (ev.target !== active) return;
      finish();
    }
    active.addEventListener('animationend', onEnd);
    var tid = setTimeout(finish, RING_SPIN_OUT_MS + 90);
  }

  function playLayerEnter(layerEl, mode) {
    if (!layerEl || prefersReducedMotion()) return;
    layerEl.classList.remove('spin-in', 'spin-out', 'reveal');
    /* reflow 以重播同名 animation */
    void layerEl.offsetWidth;
    layerEl.classList.add(mode === 'reveal' ? 'reveal' : 'spin-in');
    ringState.animating = true;
    var finished = false;
    function finish() {
      if (finished) return;
      finished = true;
      layerEl.removeEventListener('animationend', onEnd);
      clearTimeout(tid);
      layerEl.classList.remove('spin-in', 'reveal');
      ringState.animating = false;
    }
    function onEnd(ev) {
      if (ev.target !== layerEl) return;
      finish();
    }
    layerEl.addEventListener('animationend', onEnd);
    var ms = mode === 'reveal' ? 360 : RING_SPIN_IN_MS;
    var tid = setTimeout(finish, ms + 90);
  }

  function renderRingLayers(opts) {
    opts = opts || {};
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
      /* 旋轉軸心＝該層圓心（滾輪轉動視覺） */
      layerEl.style.transformOrigin = ox.toFixed(1) + 'px ' + oy.toFixed(1) + 'px';
      /* 立體軌道圓（以該層圓心繪製） */
      var orbit = document.createElement('div');
      orbit.className = 'sr-orbit';
      orbit.setAttribute('aria-hidden', 'true');
      var diam = RING_R * 2;
      orbit.style.width = diam + 'px';
      orbit.style.height = diam + 'px';
      orbit.style.transform = 'translate(' + (ox - RING_R) + 'px,' + (oy - RING_R) + 'px)';
      layerEl.appendChild(orbit);
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
        btn.style.setProperty('--sr-x', x.toFixed(1) + 'px');
        btn.style.setProperty('--sr-y', y.toFixed(1) + 'px');
        btn.style.setProperty('--sr-i', String(idx));
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
    if (opts.spinIn || opts.reveal) {
      var activeEl = host.querySelector('.sr-layer.active');
      playLayerEnter(activeEl, opts.reveal ? 'reveal' : 'spin');
    }
  }

  function ensureRingFab() {
    if ($('st-ring-fab')) return;
    var fab = document.createElement('button');
    fab.type = 'button';
    fab.id = 'st-ring-fab';
    fab.title = '分析轉盤（點一下）· 雙擊返回儀表板 · 中鍵或 \\';
    fab.setAttribute('aria-label', '開啟功能轉盤；雙擊返回儀表板');
    fab.textContent = '◎';
    var fabTimer = null;
    fab.addEventListener('click', function (e) {
      e.preventDefault();
      if (fabTimer) clearTimeout(fabTimer);
      fabTimer = setTimeout(function () {
        fabTimer = null;
        openRing(window.innerWidth - 80, window.innerHeight - 80);
      }, 220);
    });
    fab.addEventListener('dblclick', function (e) {
      e.preventDefault();
      if (fabTimer) { clearTimeout(fabTimer); fabTimer = null; }
      goDashboard();
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
      tip.textContent = '返回儀表板（中心 Logo）';
      return;
    }
    if (idx < 0) {
      tip.textContent = 'L' + ringDepth() + '/' + RING_MAX_DEPTH +
        ' · 滾輪循環' +
        (deep ? ' · Esc 上一層 · 中心◎儀表板' : ' · 中心◎儀表板 · 點 › 下鑽');
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
    if (dist < 34) return -2; /* logo 中心鈕 */
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

  /** 滾輪可選槽：作用層項目 + 中心儀表板（hi=-2） */
  function ringWheelSlots() {
    var n = ringState.items.length || 0;
    var slots = [];
    for (var i = 0; i < n; i++) slots.push(i);
    slots.push(-2);
    return slots;
  }

  /** 滾輪循環選取作用層功能（含子層時可滾到中心返回；觸控板小步長累積） */
  function onRingWheel(e) {
    if (!ringState.open) return;
    e.preventDefault();
    e.stopPropagation();
    var slots = ringWheelSlots();
    if (!slots.length) return;
    var delta = e.deltaY;
    if (!delta && e.deltaX) delta = e.deltaX;
    if (!delta) return;
    /* deltaMode: 0=pixel, 1=line, 2=page */
    if (e.deltaMode === 1) delta *= 16;
    if (e.deltaMode === 2) delta *= 48;
    ringState.wheelAcc += delta;
    var step = 36;
    if (Math.abs(ringState.wheelAcc) < step) return;
    var dir = ringState.wheelAcc > 0 ? 1 : -1;
    ringState.wheelAcc = 0;
    var curSlot = slots.indexOf(ringState.hi);
    if (curSlot < 0) curSlot = dir > 0 ? -1 : 0;
    var next = slots[(curSlot + dir + slots.length * 8) % slots.length];
    setRingHighlight(next);
  }

  function ringPushChildren(item, idx) {
    var kids = item.children || [];
    if (!kids.length) return;
    if (ringState.animating) return;
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
    renderRingLayers({ spinIn: true });
  }

  function ringPop() {
    if (ringDepth() <= 1) {
      closeRing();
      return;
    }
    if (ringState.animating) return;
    animateLayerOut(function () {
      ringState.layers.pop();
      var cur = ringState.layers[ringDepth() - 1];
      if (cur) cur.pickedId = null;
      clampWheelForActive();
      renderRingLayers({ reveal: true });
    });
  }

  function activateRingItem(item, idx) {
    if (!item || ringState.animating) return;
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
    if (ringState.animating) {
      e.preventDefault();
      return;
    }
    if (e.target.closest('#st-ring-bd')) {
      e.preventDefault();
      closeRing();
      return;
    }
    var crumb = e.target.closest('[data-ring-pop-to]');
    if (crumb) {
      e.preventDefault();
      var to = parseInt(crumb.getAttribute('data-ring-pop-to'), 10);
      if (isFinite(to)) ringPopTo(to);
      return;
    }
    if (e.target.closest('#st-ring-hub')) {
      e.preventDefault();
      goDashboard();
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
    ringState.hi = -1;
    ringState.wheelAcc = 0;
    ringState.animating = false;
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
    renderRingLayers({ spinIn: true });
  }

  function closeRing() {
    if (!ringState.open && !$('st-ring')) return;
    ringState.open = false;
    ringState.hi = -1;
    ringState.wheelAcc = 0;
    ringState.animating = false;
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

  /** 移除熱更新殘留的側欄 DOM（轉盤已涵蓋全部 ROUTES） */
  function stripLegacyNav() {
    ['navrail', 'nr-edge', 'nr-backdrop'].forEach(function (id) {
      var el = $(id);
      if (el && el.parentNode) el.parentNode.removeChild(el);
    });
    var row = $('shell-row');
    if (row) {
      row.classList.remove('nr-open', 'nr-collapsed');
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
        ico.src = RING_LOGO;
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
    /* favicon：與轉盤中心 ST icon 同一資產 */
    if (!document.querySelector('link[data-st50-favicon]')) {
      var fav = document.createElement('link');
      fav.rel = 'icon';
      fav.type = 'image/svg+xml';
      fav.href = RING_LOGO;
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
    if (topbar && !PRIVATE_WEB && !$('shell-wd-sync')) {
      var wds = document.createElement('div');
      wds.id = 'shell-wd-sync';
      wds.className = 'shell-sync warn';
      wds.title = 'WaveDeck 連線／最近宏觀覆寫（點擊開啟）';
      wds.style.cursor = 'pointer';
      wds.innerHTML = '<span class="ss-dot" aria-hidden="true"></span><span id="shell-wd-sync-txt">WD …</span>';
      wds.onclick = function () {
        if (window.WaveDeckBridge && typeof window.WaveDeckBridge.open === 'function') {
          window.WaveDeckBridge.open();
        } else {
          window.open(window.WAVEDECK_URL || 'http://127.0.0.1:18433/', '_blank', 'noopener');
        }
      };
      var stSync = $('shell-sync-btn') || $('shell-sync');
      if (stSync && stSync.parentElement === topbar) {
        if (stSync.nextSibling) topbar.insertBefore(wds, stSync.nextSibling);
        else topbar.appendChild(wds);
      } else {
        topbar.appendChild(wds);
      }
    }

    if (!$('shell-row')) {
      var row = document.createElement('div');
      row.id = 'shell-row';

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
      row.appendChild(main);
      /* topbar／wlbar 移入 shell-main，僅圖表路由顯示，避免壓在其他 tab 上方 */
      var topbarEl = $('topbar');
      var wlEl = $('wlbar');
      var pagerEl = $('rpanel-pager');
      if (topbarEl) main.appendChild(topbarEl);
      if (wlEl) main.appendChild(wlEl);
      main.appendChild(body);
      if (pagerEl) main.appendChild(pagerEl);
      main.appendChild(views);

      ensureRingFab();
      views.addEventListener('click', function (e) {
        if (e.target.closest('[data-shell-back]')) goDashboard();
      });
    } else {
      stripLegacyNav();
      ensureRingFab();
      ROUTES.forEach(ensurePanel);
      var existingMain = $('shell-main');
      var existingPager = $('rpanel-pager');
      var existingViews = $('shell-views');
      if (existingMain && existingPager && existingPager.parentElement !== existingMain) {
        existingMain.insertBefore(existingPager, existingViews || null);
      }
    }

    stripLegacyNav();
    ensureDashChrome();
    state.built = true;
    return true;
  }

  /** 圖表頂欄：Logo 與「儀表板」鈕快捷回總覽 */
  function ensureDashChrome() {
    var logo = document.querySelector('#topbar .logo');
    if (logo && !logo.getAttribute('data-dash-bound')) {
      logo.setAttribute('data-dash-bound', '1');
      logo.title = '返回儀表板';
      logo.addEventListener('click', function (e) {
        e.preventDefault();
        goDashboard();
      });
    }
    var topbar = $('topbar');
    var btn = $('shell-dash-btn');
    if (topbar && !btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'shell-dash-btn';
      btn.className = 'shell-dash-btn';
      btn.innerHTML = '<span class="shell-dash-glyph" aria-hidden="true"><img src="' + RING_LOGO +
        '" alt="" width="14" height="14"></span><span class="shell-dash-label">儀表板</span>';
      btn.title = '返回市場總覽儀表板';
      btn.setAttribute('aria-label', '返回儀表板');
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        goDashboard();
      });
    }
    if (topbar && btn) {
      var keybtn = $('keybtn');
      if (keybtn && keybtn.parentNode === topbar) {
        if (keybtn.nextSibling) topbar.insertBefore(btn, keybtn.nextSibling);
        else topbar.appendChild(btn);
      } else topbar.appendChild(btn);
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

  /** 頂列僅顯示純文字；誤傳 HTML 時剝成可讀短句，避免遮蔽自選列 */
  function plainWdStatus(text) {
    var s = text == null ? '' : String(text);
    if (!s) return 'WD';
    if (s.indexOf('<') >= 0) {
      s = s.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    }
    if (s.length > 36) s = s.slice(0, 34) + '…';
    return s || 'WD';
  }

  function setWdSync(mode, text) {
    var el = $('shell-wd-sync');
    var txt = $('shell-wd-sync-txt');
    if (!el || !txt) return;
    el.classList.remove('warn', 'err');
    if (mode === 'warn') el.classList.add('warn');
    if (mode === 'err') el.classList.add('err');
    var plain = plainWdStatus(text);
    txt.textContent = plain;
    /* 完整原文進 title（若無成本 tip 覆蓋）；HTML 則不塞進 title */
    if (text && String(text).indexOf('<') < 0) {
      el.setAttribute('data-wd-status', String(text));
    }
  }

  function paintWdCostTip(meter) {
    var el = $('shell-wd-sync');
    if (!el) return;
    var tip = 'WaveDeck 連線／最近宏觀覆寫（點擊開啟）';
    if (meter && meter.age_sec != null) {
      tip += ' · 回報年齡 ' + meter.age_sec + 's' + (meter.fresh ? '（新鮮）' : '（偏舊）');
    }
    if (meter && meter.costs) {
      var c = meter.costs;
      tip += ' · 成本合計≈$' + (c.combined_usd_est != null ? c.combined_usd_est : '—') +
        '（ST 本機 ' + (c.st_local_calls || 0) + ' 次／雲端≈$' + (c.st_cloud_usd_est || 0) +
        ' · WD 今日 $' + (c.wd_day_usd || 0) +
        (c.wd_provider ? ' · ' + c.wd_provider : '') + '）';
    }
    if (meter && meter.report) {
      var r = meter.report;
      tip += ' · WD 回報 ' + (r.fsm || '—') + '/' + (r.mode || '—') +
        (r.ai && r.ai.action_label ? ' · ' + r.ai.action_label : '');
    }
    el.title = tip;
    if (meter && meter.report && meter.age_sec != null && Number(meter.age_sec) > 45) {
      el.classList.remove('err');
      el.classList.add('warn');
    }
  }

  function shortWdAction(report) {
    if (!report || !report.ai) return '';
    var map = {
      HOLD: '抱', ENTER_LONG: '多', ENTER_SHORT: '空',
      REDUCE: '減', EXIT: '平'
    };
    var act = report.ai.action;
    if (act && map[act]) return map[act];
    var lab = report.ai.action_label ? String(report.ai.action_label) : '';
    return lab ? lab.slice(0, 2) : '';
  }

  function probeWaveDeck() {
    if (PRIVATE_WEB) return;
    if (!window.WaveDeckBridge || typeof window.WaveDeckBridge.ping !== 'function') {
      setWdSync('warn', 'WD —');
      return;
    }
    window.WaveDeckBridge.ping().then(function (ok) {
      if (!ok) {
        setWdSync('warn', 'WD OFF');
        return;
      }
      var last = window.WaveDeckBridge.lastSync && window.WaveDeckBridge.lastSync();
      var baseTxt = (last && last.payload)
        ? ('WD ' + last.payload.style + (last.payload.delever ? '↓' : ''))
        : 'WD OK';
      setWdSync('ok', baseTxt);
      if (typeof window.WaveDeckBridge.fetchCostMeter === 'function') {
        window.WaveDeckBridge.fetchCostMeter(false).then(function (meter) {
          paintWdCostTip(meter);
          var act = shortWdAction(meter && meter.report);
          if (act) setWdSync('ok', baseTxt + ' · ' + act);
        }).catch(function () {});
      }
    }).catch(function () { setWdSync('warn', 'WD OFF'); });
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
    fetch('/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: 40 }),
      cache: 'no-store'
    })
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
    if (!PRIVATE_WEB) probeWaveDeck();
  }

  function panelApi(id) {
    var key = PANEL_MAP[id];
    var api = key && window[key] ? window[key] : null;
    if (api && window.AppKernel && !api.__stKernelRegistered) {
      window.AppKernel.panels.register(id, api);
      try { Object.defineProperty(api, '__stKernelRegistered', { value: true }); }
      catch (e) { api.__stKernelRegistered = true; }
    }
    return api;
  }

  function deactivateRoute(id) {
    if (!id || id === 'chart') return;
    var api = panelApi(id);
    if (api && typeof api.deactivate === 'function') {
      try { api.deactivate(); }
      catch (err) { console.warn('[shell-v5] deactivate ' + id, err); }
    }
  }

  function emitRoute(id, opts, retries) {
    /* 相容舊呼叫 emitRoute(id, retriesNumber) */
    if (typeof opts === 'number') {
      retries = opts;
      opts = {};
    }
    opts = opts || {};
    retries = retries || 0;
    try {
      window.dispatchEvent(new CustomEvent('shell:route', {
        detail: { route: id, opts: opts }
      }));
    } catch (e) {}
    var key = PANEL_MAP[id];
    if (!key) return;
    if (window[key] && typeof window[key].activate === 'function') {
      try {
        var api = panelApi(id);
        if (window.AppKernel && api) window.AppKernel.panels.activate(id, opts);
        else window[key].activate(opts);
      }
      catch (err) { console.warn('[shell-v5] ' + key + ' activate', err); }
      return;
    }
    /* 模組尚未載入：短重試，避免開成空白舊介面 */
    if (retries < 20) {
      setTimeout(function () { emitRoute(id, opts, retries + 1); }, 50);
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
    var merged = {};
    for (var k in opts) {
      if (Object.prototype.hasOwnProperty.call(opts, k)) merged[k] = opts[k];
    }
    if (a.sym && !merged.sym) merged.sym = a.sym;
    if (a.mkt && !merged.mkt) merged.mkt = a.mkt;
    return { id: a.to, opts: merged };
  }

  function traceMobilePanelLayout(routeId) {
    try {
      if (!window.matchMedia || !window.matchMedia('(max-width:900px)').matches) return;
      var views = $('shell-views');
      var panel = $('view-' + routeId);
      var mount = $('mount-' + routeId);
      if (!views || !panel) return;
      var vr = views.getBoundingClientRect();
      var pr = panel.getBoundingClientRect();
      fetch('/diagnostics/ui-route', {
        method: 'POST', headers: {'Content-Type':'application/json'}, keepalive: true,
        body: JSON.stringify({
          ts: new Date().toISOString(), event: 'mobile_shell_panel_layout',
          correlationId: 'mobile-shell-' + Date.now(), from: 'shell-views', to: routeId,
          state: (window.matchMedia('(orientation:portrait)').matches ? 'portrait' : 'landscape') +
            '-scroll-' + getComputedStyle(views).overflowY,
          label: window.innerWidth + 'x' + window.innerHeight + '|views=' + Math.round(vr.height) +
            '/' + views.scrollHeight + '|panel=' + Math.round(pr.height) +
            (mount ? '/' + mount.scrollHeight : '')
        })
      }).catch(function () {});
    } catch (e) {}
  }

  function applyRoute(id, opts) {
    opts = opts || {};
    var resolved = resolveAlias(id, opts);
    id = resolved.id;
    opts = resolved.opts;

    var route = findRoute(id) || findRoute('chart') || ROUTES[0];

    if (route.action === 'wavedeck') {
      var url = (window.WAVEDECK_URL || 'http://127.0.0.1:18433/');
      if (window.WaveDeckBridge && typeof window.WaveDeckBridge.open === 'function') {
        window.WaveDeckBridge.open(url);
      } else {
        window.open(url, '_blank', 'noopener');
      }
      return;
    }

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
    var pager = $('rpanel-pager');
    var views = $('shell-views');
    var isChart = id === 'chart';

    if (topbar) topbar.classList.toggle('shell-hidden', !isChart);
    if (body) body.classList.toggle('shell-hidden', !isChart);
    if (wl) wl.classList.toggle('shell-hidden', !isChart);
    if (pager) pager.classList.toggle('shell-hidden', !isChart);
    if (views) views.classList.toggle('show', !isChart);
    try { document.documentElement.setAttribute('data-st5-route', id); } catch (eRouteAttr) {}
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

    emitRoute(id, opts);
    setTimeout(function () { traceMobilePanelLayout(id); }, 180);
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
     * tip UX only：開啟預設總覽 + 彈出轉盤
     * - 一律 #pulse（絕不吃 localStorage／舊 hash 的 chart）
     * - boot 後自動 openRing（中心）；之後仍可由 hashchange 切頁
     */
    try {
      if (window.history && window.history.replaceState) {
        var base = window.location.pathname + (window.location.search || '');
        window.history.replaceState(null, '', base + '#pulse');
      } else {
        window.location.hash = 'pulse';
      }
    } catch (eHash) {}
    applyRoute('pulse');
    try {
      document.documentElement.classList.add('st5-booted');
      document.documentElement.setAttribute('data-st5-ux', 'tip');
      document.documentElement.setAttribute('data-st5-route', state.route);
    } catch (eBootCls) {}
    probeHealth();
    setInterval(probeHealth, 60000);
    try {
      window.addEventListener('wavedeck:overlay', function (ev) {
        var p = ev && ev.detail;
        if (p && p.style != null) setWdSync('ok', 'WD ' + p.style + (p.delever ? '↓' : ''));
        else probeWaveDeck();
      });
      window.addEventListener('wavedeck:chip', function (ev) {
        var d = ev && ev.detail;
        if (d && d.symbol) {
          var lab = (window.WaveDeckBridge && typeof WaveDeckBridge.chipLabel === 'function')
            ? WaveDeckBridge.chipLabel(d.symbol) : '';
          setWdSync('ok', 'WD ' + d.symbol + (lab ? ' · ' + lab : ''));
        } else probeWaveDeck();
      });
      window.addEventListener('wavedeck:stream', function (ev) {
        var d = ev && ev.detail;
        if (d && d.style != null) setWdSync('ok', 'WD ' + d.style + (d.delever ? '↓' : ''));
        else if (d && d.ok) probeWaveDeck();
      });
    } catch (eWd) {}
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
    /* 開啟即彈出分析轉盤（畫面中央） */
    setTimeout(function () {
      if (!ringState.open) {
        openRing(window.innerWidth / 2, window.innerHeight / 2);
      }
    }, 180);
    console.log('[shell-v5] Stock Terminal ' + VERSION + ' · tip UX · route=pulse · ring=auto');
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
    /* Esc／Backspace／BrowserBack／Alt+←：有子層先返回上一層，否則關轉盤 */
    if (e.key === 'Escape' || e.key === 'Backspace' || e.key === 'BrowserBack' ||
        (e.altKey && e.key === 'ArrowLeft' && ringState.open)) {
      if (ringState.open) {
        e.preventDefault();
        e.stopPropagation();
        if (e.key === 'Escape' && ringState.animating) {
          closeRing();
          return;
        }
        if (ringState.animating) return;
        ringPop();
        return;
      }
    }
    /* \\：功能轉盤（MX Master 風格） */
    if (e.key === '\\' && !e.altKey && !meta) {
      e.preventDefault();
      toggleRing(window.innerWidth / 2, window.innerHeight / 2);
      return;
    }
    /* 轉盤開啟時：方向鍵環選（含子層返回槽）；Enter／Space 確認／下鑽／返回 */
    if (ringState.open) {
      var slots = ringWheelSlots();
      var sn = slots.length || 1;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        var cR = slots.indexOf(ringState.hi);
        if (cR < 0) cR = -1;
        setRingHighlight(slots[(cR + 1 + sn * 8) % sn]);
        return;
      }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        var cL = slots.indexOf(ringState.hi);
        if (cL < 0) cL = 0;
        setRingHighlight(slots[(cL - 1 + sn * 8) % sn]);
        return;
      }
      if ((e.key === 'Enter' || e.key === ' ') && ringState.hi === -2) {
        e.preventDefault();
        goDashboard();
        return;
      }
      if ((e.key === 'Enter' || e.key === ' ') && ringState.hi >= 0) {
        e.preventDefault();
        activateRingItem(ringState.items[ringState.hi], ringState.hi);
        return;
      }
    }
    /* [ 或 Ctrl/⌘B：開／關分析轉盤（側欄已移除） */
    if (e.key === '[' || (meta && (e.key === 'b' || e.key === 'B'))) {
      e.preventDefault();
      toggleRing(window.innerWidth / 2, window.innerHeight / 2);
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
      return;
    }
    /* 滑鼠側鍵「返回」(button 3)：轉盤子層回上一層 */
    if (e.button === 3 && ringState.open) {
      e.preventDefault();
      ringPop();
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
    goDashboard: goDashboard,
    route: function () { return state.route; },
    /* 側欄已移除：保留 no-op 以免舊 hotkeys 呼叫炸裂 */
    toggleNav: function () { toggleRing(window.innerWidth / 2, window.innerHeight / 2); },
    setNavOpen: function () {},
    isNavOpen: function () { return false; },
    openRing: openRing,
    closeRing: closeRing,
    toggleRing: toggleRing,
    ringPop: ringPop,
    ringPopTo: ringPopTo,
    isRingOpen: function () { return !!ringState.open; },
    ringDepth: function () { return ringDepth(); },
    ringAnalysisTree: ringAnalysisTree,
    ringCoversRoute: ringCoversRoute,
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
    },
    probeWaveDeck: probeWaveDeck
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
