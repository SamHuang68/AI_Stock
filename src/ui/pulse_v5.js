/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0：市場總覽儀表板
 * ----------------------------------------------------------------------------
 * 大螢幕一頁高密度（一行五框 × 上下兩區）：
 *   頂列 KPI（加權／櫃買／台指期／量能／家數廣度／漲跌停）— 去重後 6 格
 *   上區 5 窗：脈動(綜合|體質|風險三燈)｜加權盤勢(四格＋線圖對齊法人)｜法人｜廣度｜產業
 *   下區 5 窗：漲停(產業標籤)｜跌幅｜全球｜快訊(TW/US)｜自選(TW/US·內滾)
 *   產業輪動 hover ↔ 近漲跌停同產業高亮；法人合計 Z／分位／排名
 *   因子／歷史預設收合（按鈕展開）
 * 產品名 Stock Terminal 5.0；資料：GET /pulse — 真實欄位，禁止 mock。
 * 版面錨點（勿改字串；go.ps1／selftest 依此核對本機是否跑到舊樹）：
 *   PULSE_LAYOUT_ANCHOR_3cab212
 * ========================================================================== */
(function () {
  'use strict';

  /* 本機若看不到標題旁「實測 5+5」，代表瀏覽器／server 仍在跑舊 pulse_v5.js */
  var LAYOUT_ANCHOR = 'PULSE_LAYOUT_ANCHOR_3cab212';
  var LAYOUT_CONTRACT = '5col-2zone';
  var MOBILE_LAYOUT_CONTRACT = '2col-scroll';

  var SRV = window.SERVER || '';
  var timer = null;
  var layoutResizeTimer = null;
  var lastPack = null;
  var showFactors = false;
  var sectorMkt = 'TW';
  var sectorCache = { TW: null, US: null };
  var flashMkt = 'ALL'; /* ALL | TW | US */
  var flashQ = '';      /* 快訊關鍵字（代號／標題） */
  var watchMkt = 'ALL'; /* ALL | TW | US */
  var _lastMacro = null;
  var _prevBand = null;
  var beginnerAdvanced = false;
  var aiSummaryStarted = false;
  var aiSummaryVisible = false;
  var aiSpeechActive = false;
  var aiSummaryMode = 'fast';
  var aiSummaryInFlight = false;
  var aiSummaryWaitTimer = null;
  var aiRuntimeStatus = null;
  var lastBoundaryTraceSignature = null;
  var marketColorTraceSeen = {};
  var pulseMode = (function () {
    try {
      return localStorage.getItem('st_pulse_view_mode_v1') === 'expert' ? 'expert' : 'beginner';
    } catch (e) { return 'beginner'; }
  }());

  function $(id) { return document.getElementById(id); }

  /** 實測 DOM 欄數；桌面與手機橫式維持 5+5，僅手機直式採兩欄捲動。 */
  function probeLayoutCols() {
    if (pulseMode === 'beginner') {
      var beginnerProbe = $('pl-layout-probe');
      if (beginnerProbe) {
        beginnerProbe.textContent = '新手模式 · 白話導覽';
        beginnerProbe.style.borderColor = 'rgba(56,189,248,.45)';
        beginnerProbe.style.color = '#7dd3fc';
        beginnerProbe.style.background = 'rgba(56,189,248,.12)';
        beginnerProbe.title = '預設顯示市場狀態、行動提示與三個白話訊號';
      }
      return true;
    }
    var zones = document.querySelectorAll('#pl-root .pl-zone');
    var parts = [];
    var ok = zones.length === 2;
    var mobile = !!(window.matchMedia &&
      window.matchMedia('(max-width: 900px) and (orientation: portrait)').matches);
    var expectedCols = mobile ? 2 : 5;
    for (var i = 0; i < zones.length; i++) {
      var z = zones[i];
      var gtc = window.getComputedStyle(z).gridTemplateColumns || '';
      var cols = (gtc && gtc !== 'none') ? gtc.trim().split(/\s+/).length : 0;
      var kids = z.children ? z.children.length : 0;
      parts.push(cols + '/' + kids);
      if (cols !== expectedCols || kids !== 5) ok = false;
    }
    var probe = $('pl-layout-probe');
    if (probe) {
      probe.textContent = ok
        ? (mobile ? ('手機兩欄 · ' + MOBILE_LAYOUT_CONTRACT) : ('實測 5+5 · ' + LAYOUT_CONTRACT))
        : ('⚠實測 ' + (parts.join(' + ') || '0') + ' · 預期每列 ' + expectedCols + ' 欄');
      probe.style.borderColor = ok ? 'rgba(34,211,238,.45)' : 'rgba(248,113,113,.65)';
      probe.style.color = ok ? '#67e8f9' : '#fecaca';
      probe.style.background = ok ? 'rgba(34,211,238,.12)' : 'rgba(248,113,113,.15)';
      probe.title = LAYOUT_ANCHOR;
    }
    try {
      console.log('[pulse-v5] ' + LAYOUT_ANCHOR + ' contract=' + LAYOUT_CONTRACT +
        ' mobile=' + mobile + ' probe=' + (parts.join('+') || 'none') + ' ok=' + ok);
    } catch (e) {}
    return ok;
  }

  function injectCSS() {
    var s = $('pulse-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'pulse-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      /* 一屏鎖定：上下兩區各 5 窗，大螢幕塞滿資訊 */
      '#shell-views:has(#view-pulse.on){overflow:hidden!important}' +
      '#view-pulse.sv-panel.on{' +
        'max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-pulse,#mount-pulse.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#pl-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1;min-height:0;display:flex;flex-direction:column}' +
      /* 單列微標題 */
      '#pl-root .pl-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#pl-root .pl-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#pl-root .pl-kicker{font-size:9px;color:var(--gold);letter-spacing:1.2px;margin:0;font-weight:700}' +
      '#pl-root .pl-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#pl-root .pl-sub{font-size:9px;color:var(--tlo);margin:0}' +
      '#pl-root .pl-wd{display:none}' +
      '#pl-root .pl-wd b{color:var(--cyan)}' +
      '#pl-root .pl-btn.wd{border-color:rgba(103,232,249,.35);color:var(--cyan)}' +
      '#pl-root .pl-ai{margin:4px 0 0;padding:6px 8px;background:var(--bg2);border:1px solid var(--border);border-radius:6px;flex:0 0 auto}' +
      '#pl-root .pl-ai h4{margin:0 0 4px;font-size:9px;color:var(--gold);letter-spacing:1px;display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap}' +
      '#pl-root .pl-ai .pl-ai-body{font-size:10px;line-height:1.55;color:var(--text);min-height:2em;white-space:pre-wrap}' +
      '#pl-root .pl-ai .pl-ai-meta{margin-top:4px;font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-ai-modebar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:3px 0 8px}' +
      '#pl-root .pl-ai-mode{appearance:none;border:1px solid #344965;border-radius:999px;background:#091525;color:#9fb0c5;' +
        'padding:4px 9px;font:800 9px/1.25 "Noto Sans TC",sans-serif;cursor:pointer}' +
      '#pl-root .pl-ai-mode.on{border-color:rgba(103,232,249,.65);background:rgba(14,165,233,.14);color:#cffafe;' +
        'box-shadow:0 0 16px rgba(14,165,233,.09)}' +
      '#pl-root .pl-ai-mode.deep.on{border-color:rgba(250,204,21,.62);background:rgba(234,179,8,.12);color:#fde68a}' +
      '#pl-root .pl-ai-mode:disabled{opacity:.48;cursor:wait}' +
      '#pl-root .pl-ai-runtime-note{font:700 8px/1.4 "Noto Sans TC",sans-serif;color:#8296ae}' +
      '#pl-root.beginner-mode .pl-ai{position:fixed;z-index:10020;top:34px;right:8px;bottom:8px;width:min(430px,calc(100vw - 16px));' +
        'box-sizing:border-box;margin:0;padding:14px;border:1px solid rgba(125,211,252,.32);border-radius:14px;' +
        'background:rgba(7,16,29,.88);backdrop-filter:blur(18px) saturate(135%);box-shadow:-18px 0 52px rgba(0,0,0,.48);' +
        'overflow:auto;animation:plAiDrawerIn .2s ease-out}' +
      '#pl-root.beginner-mode .pl-ai h4{position:sticky;top:-14px;z-index:2;margin:-14px -14px 10px;padding:12px 14px 9px;' +
        'background:linear-gradient(180deg,rgba(7,16,29,.98),rgba(7,16,29,.88));border-bottom:1px solid rgba(125,211,252,.16)}' +
      '#pl-root.beginner-mode .pl-ai .pl-ai-body{font:600 12px/1.85 "Noto Sans TC",sans-serif;color:#dbeafe}' +
      '@keyframes plAiDrawerIn{from{opacity:0;transform:translateX(24px)}to{opacity:1;transform:none}}' +
      '#pl-root .pl-ai-tools{display:flex;align-items:center;gap:6px;margin-left:auto}' +
      '#pl-root .pl-ai-speak{appearance:none;border:1px solid rgba(125,211,252,.38);border-radius:999px;background:rgba(14,165,233,.1);' +
        'color:#bae6fd;padding:2px 8px;font:700 9px/1.35 "Noto Sans TC",sans-serif;cursor:pointer}' +
      '#pl-root .pl-ai-speak:hover,#pl-root .pl-ai-speak:focus-visible{border-color:#7dd3fc;color:#fff;outline:none}' +
      '#pl-root .pl-ai-close{appearance:none;border:1px solid #43536a;border-radius:999px;background:#0a1423;color:#9fb0c5;' +
        'padding:2px 8px;font:700 9px/1.35 "Noto Sans TC",sans-serif;letter-spacing:0;cursor:pointer}' +
      '#pl-root .pl-ai-close:hover,#pl-root .pl-ai-close:focus-visible{color:#f8fafc;border-color:#7dd3fc;outline:none}' +
      '#pl-root .pl-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '#pl-root .pl-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;flex:0 0 auto;white-space:nowrap}' +
      '#pl-root .pl-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .pl-btn.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .pl-mode-toggle{display:inline-flex;border:1px solid #31445f;border-radius:5px;overflow:hidden;flex:0 0 auto}' +
      '#pl-root .pl-mode-toggle button{border:0;border-right:1px solid #31445f;border-radius:0;background:#0b1423;' +
        'color:#91a4bc;padding:3px 7px;font:700 9px "JetBrains Mono",monospace;cursor:pointer}' +
      '#pl-root .pl-mode-toggle button:last-child{border-right:0}' +
      '#pl-root .pl-mode-toggle button.on{background:#16304a;color:#bae6fd;box-shadow:inset 0 -2px #38bdf8}' +
      '#pl-root.beginner-mode #pl-push-wd,#pl-root.beginner-mode #pl-ai-sum{display:none!important}' +
      '#pl-root .up{color:var(--red)}#pl-root .dn{color:var(--green)}#pl-root .flat{color:var(--tlo)}' +
      '#pl-root .us-up{color:var(--green)}#pl-root .us-down{color:var(--red)}' +
      /* 盤面多空／偏強弱：台股慣例紅漲綠跌（與 .up/.dn 對齊） */
      '#pl-root .pl-bias-bull{color:var(--red)}#pl-root .pl-bias-bear{color:var(--green)}' +
      '#pl-root .pl-bias-mid{color:#94a3b8}' +
      /* 體質／風險分數：金／青，勿當漲跌色 */
      '#pl-root .pl-st-pos{color:var(--gold)}#pl-root .pl-st-risk{color:var(--cyan)}' +
      '#pl-root .pl-st-mid{color:#94a3b8}' +
      '#pl-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#pl-body.pl-mode-beginner,#pl-body.pl-mode-expert{animation:plModeIn .16s ease-out}' +
      '@keyframes plModeIn{from{opacity:.25;transform:translateY(3px)}to{opacity:1;transform:none}}' +
      '@media(prefers-reduced-motion:reduce){#pl-body.pl-mode-beginner,#pl-body.pl-mode-expert{animation:none}}' +
      '#pl-body.pl-mode-beginner{display:block;overflow:auto;padding:3px 0 14px;overscroll-behavior:contain}' +
      '#pl-root .pl-beginner{width:100%;max-width:1420px;min-width:0;margin:0 auto;padding:2px 2px 16px;box-sizing:border-box}' +
      '#pl-root .pl-beginner-hero{position:relative;isolation:isolate;overflow:hidden;display:grid;grid-template-columns:220px minmax(0,1fr);gap:18px;align-items:center;' +
        'width:100%;max-width:100%;min-width:0;box-sizing:border-box;background:linear-gradient(135deg,#101c30,#0b1423 62%,#0e2430);border:1px solid #2c4762;' +
        'border-radius:14px;padding:20px 24px;box-shadow:inset 0 1px rgba(255,255,255,.05),0 12px 35px rgba(0,0,0,.2)}' +
      '#pl-root .pl-beginner-hero>*{min-width:0}' +
      '#pl-root .pl-beginner-hero:after{content:"";position:absolute;z-index:-1;width:360px;height:220px;left:-60px;top:-75px;' +
        'border-radius:50%;filter:blur(18px);opacity:.22;pointer-events:none}' +
      '#pl-root .pl-beginner-hero.weather-calm:after{background:radial-gradient(circle,#38bdf8,transparent 68%)}' +
      '#pl-root .pl-beginner-hero.weather-watch:after{background:radial-gradient(circle,#facc15,transparent 68%)}' +
      '#pl-root .pl-beginner-hero.weather-alert:after{background:radial-gradient(circle,#fb923c,transparent 68%)}' +
      '#pl-root .pl-beginner-hero.weather-unknown:after{background:radial-gradient(circle,#64748b,transparent 68%)}' +
      '#pl-root .pl-beginner-gauge{position:relative;width:210px;height:124px;display:flex;align-items:flex-end;justify-content:center}' +
      '#pl-root .pl-beginner-gauge svg{position:absolute;inset:0;width:210px;height:118px;overflow:visible}' +
      '#pl-root .pl-beginner-gauge .track{fill:none;stroke:#22324a;stroke-width:15;stroke-linecap:round}' +
      '#pl-root .pl-beginner-gauge .value{fill:none;stroke:url(#plBeginnerGauge);stroke-width:15;stroke-linecap:round;' +
        'transition:stroke-dasharray .4s ease}' +
      '#pl-root .pl-beginner-gauge .marker-halo{fill:rgba(255,255,255,.22)}' +
      '#pl-root .pl-beginner-gauge .marker{fill:#f8fafc;stroke:#0b1423;stroke-width:3;filter:drop-shadow(0 0 5px rgba(255,255,255,.85))}' +
      '#pl-root .pl-beginner-gauge .score{text-align:center;font-size:34px;font-weight:900;color:#eef6ff;line-height:1}' +
      '#pl-root .pl-beginner-gauge .score small{display:block;font-size:12px;color:#91a4bc;margin-top:5px;font-weight:700}' +
      '#pl-root .pl-weather{display:inline-flex;align-items:center;gap:7px;padding:4px 10px;border-radius:999px;' +
        'font:800 12px "Noto Sans TC",sans-serif;border:1px solid #38506c;margin-bottom:8px}' +
      '#pl-root .pl-weather.calm{color:#bae6fd;background:rgba(14,165,233,.13);border-color:rgba(56,189,248,.45)}' +
      '#pl-root .pl-weather.watch{color:#fde68a;background:rgba(234,179,8,.12);border-color:rgba(250,204,21,.42)}' +
      '#pl-root .pl-weather.alert{color:#fed7aa;background:rgba(249,115,22,.12);border-color:rgba(251,146,60,.48)}' +
      '#pl-root .pl-weather.unknown{color:#cbd5e1;background:rgba(100,116,139,.12);border-color:#475569}' +
      '#pl-root .pl-beginner-copy{min-width:0;max-width:100%;overflow-wrap:anywhere}' +
      '#pl-root .pl-beginner-copy h2{font:900 26px/1.35 "Noto Sans TC",sans-serif;color:#f4f8fc;margin:0 0 8px}' +
      '#pl-root .pl-divergence-warning{display:flex;align-items:center;gap:8px;width:max-content;max-width:100%;margin:0 0 6px;' +
        'padding:4px 9px;border:1px solid rgba(251,146,60,.52);border-radius:7px;background:rgba(124,45,18,.18);' +
        'font:700 11px/1.35 "Noto Sans TC",sans-serif;color:#fed7aa;box-shadow:0 0 13px rgba(251,146,60,.08)}' +
      '#pl-root .pl-divergence-warning b{color:#fdba74;white-space:nowrap}#pl-root .pl-divergence-warning span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-beginner-copy .advice{font:800 17px/1.5 "Noto Sans TC",sans-serif;color:#fcd34d;margin:0 0 7px}' +
      '#pl-root .pl-beginner-copy .why{font:500 14px/1.6 "Noto Sans TC",sans-serif;color:#b8c7d9;margin:0}' +
      '#pl-root .pl-hero-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:7px}' +
      '#pl-root .pl-beginner-copy .quality{font-size:12px;color:#8296ae;min-width:0}' +
      '#pl-root .pl-stock-check{display:flex;align-items:center;gap:4px;flex:0 0 auto}' +
      '#pl-root .pl-stock-check input{width:164px;box-sizing:border-box;border:1px solid #31465f;border-radius:6px;background:#081220;' +
        'color:#e5eef9;padding:6px 8px;font:700 12px "JetBrains Mono",monospace;outline:none}' +
      '#pl-root .pl-stock-check input:focus{border-color:#7dd3fc;box-shadow:0 0 0 2px rgba(56,189,248,.1)}' +
      '#pl-root .pl-stock-check button{border:1px solid rgba(125,211,252,.4);border-radius:6px;background:rgba(14,165,233,.1);' +
        'color:#bae6fd;padding:6px 9px;font:800 12px "Noto Sans TC",sans-serif;cursor:pointer}' +
      '#pl-root .pl-stock-result{display:none;position:fixed;z-index:10015;top:38px;left:50%;transform:translateX(-50%);' +
        'width:min(560px,calc(100vw - 24px));box-sizing:border-box;padding:11px 12px;border:1px solid rgba(125,211,252,.36);' +
        'border-radius:12px;background:rgba(7,16,29,.94);backdrop-filter:blur(16px);box-shadow:0 16px 48px rgba(0,0,0,.48);' +
        'grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center}' +
      '#pl-root .pl-stock-result.on{display:grid}' +
      '#pl-root .pl-stock-result b{display:block;font:900 13px "Noto Sans TC",sans-serif;color:#eaf3ff}' +
      '#pl-root .pl-stock-result span{display:block;margin-top:3px;font:600 10px/1.45 "Noto Sans TC",sans-serif;color:#b8c7d9}' +
      '#pl-root .pl-stock-result small{display:block;margin-top:3px;font-size:11px;color:#8296ae}' +
      '#pl-root .pl-stock-result.strong b{color:var(--red)}#pl-root .pl-stock-result.weak b{color:var(--green)}' +
      '#pl-root .pl-stock-result button{border:1px solid #3b526d;border-radius:6px;background:#0c1929;color:#bcd0e6;padding:5px 8px;' +
        'font:700 11px "Noto Sans TC",sans-serif;cursor:pointer}' +
      '#pl-root .pl-simple-signals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}' +
      '#pl-root .pl-simple-card{position:relative;background:#0d1727;border:1px solid #293b54;border-radius:10px;padding:13px 14px;min-width:0;cursor:pointer}' +
      '#pl-root .pl-simple-card:hover{border-color:#49627f}' +
      '#pl-root .pl-simple-card .head{display:flex;align-items:center;gap:7px;color:#b6c6d8;font:700 13px "Noto Sans TC",sans-serif}' +
      '#pl-root .pl-simple-card .icon{font-size:22px;line-height:1}' +
      '#pl-root .pl-simple-card .method-hint{margin-left:auto;color:#7dd3fc;font-size:11px;white-space:nowrap}' +
      '#pl-root .pl-simple-card .main{font:900 20px/1.25 "Noto Sans TC",sans-serif;color:#edf5ff;margin:8px 0 5px}' +
      '#pl-root .pl-simple-card .plain{font:500 13px/1.55 "Noto Sans TC",sans-serif;color:#aebed0;min-height:40px}' +
      '#pl-root .pl-simple-card .bar{height:7px;border-radius:999px;background:#1d2a40;margin-top:9px;overflow:hidden}' +
      '#pl-root .pl-simple-card .bar i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#38bdf8,#facc15)}' +
      '#pl-root .pl-simple-card.breadth .bar{position:relative;background:linear-gradient(90deg,var(--red) 0 var(--bar),var(--green) var(--bar) 100%)}' +
      '#pl-root .pl-simple-card.breadth .bar i{position:absolute;width:2px!important;margin-left:calc(var(--bar) - 1px);background:#fff;box-shadow:0 0 5px #fff}' +
      '#pl-root .pl-simple-card.volume .bar{outline:1px solid rgba(125,211,252,.28);outline-offset:1px;' +
        'background:repeating-linear-gradient(90deg,#152338 0 13%,#0d1727 13% 15%)}' +
      '#pl-root .pl-simple-card.volume .bar i{background:linear-gradient(90deg,#38bdf8,#facc15);box-shadow:0 0 7px rgba(56,189,248,.38)}' +
      '#pl-root .pl-simple-card .bar-meta{display:flex;justify-content:space-between;gap:8px;margin-top:6px;font-size:11px;color:#8296ae}' +
      '#pl-root .pl-money-split{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-top:6px}' +
      '#pl-root .pl-money-split span{display:grid;grid-template-columns:auto 1fr;gap:2px 4px;align-items:center;min-width:0}' +
      '#pl-root .pl-money-split em{font-style:normal;font-size:11px;color:#8296ae}' +
      '#pl-root .pl-money-split b{font-size:12px;text-align:right;white-space:nowrap}' +
      '#pl-root .pl-money-split b.pos{color:var(--red)}#pl-root .pl-money-split b.neg{color:var(--green)}' +
      '#pl-root .pl-money-split b.flat{color:#94a3b8}' +
      '#pl-root .pl-money-split i{grid-column:1/-1;height:3px;border-radius:999px;background:#1d2a40;overflow:hidden}' +
      '#pl-root .pl-money-split i u{display:block;height:100%;border-radius:999px;background:#f6c84c;text-decoration:none}' +
      '#pl-root .pl-method-pop{position:absolute;z-index:8;left:8px;right:8px;top:31px;padding:8px 10px;border:1px solid #4a6686;' +
        'border-radius:8px;background:rgba(7,16,29,.98);box-shadow:0 10px 24px rgba(0,0,0,.4);font:600 12px/1.5 "Noto Sans TC",sans-serif;color:#c7d6e8}' +
      '#pl-root .pl-method-pop[hidden]{display:none!important}' +
      '#pl-root .pl-method-pop a{display:inline-block;margin-left:6px;color:#7dd3fc;text-decoration:none;white-space:nowrap}' +
      '#pl-root .pl-market-radar{margin-top:10px;background:#0a1423;border:1px solid #2a3e58;border-radius:10px;padding:12px 13px}' +
      '#pl-root .pl-market-radar-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:9px}' +
      '#pl-root .pl-market-radar-head h3{font:900 16px "Noto Sans TC",sans-serif;color:#edf5ff;margin:0}' +
      '#pl-root .pl-market-radar-head span{font:500 11px "Noto Sans TC",sans-serif;color:#879bb2}' +
      '#pl-root .pl-market-radar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}' +
      '#pl-root .pl-radar-card{background:linear-gradient(180deg,#101c2e,#0c1625);border:1px solid #2a3c54;' +
        'border-radius:9px;padding:11px 12px;min-width:0;cursor:pointer;transition:border-color .15s,transform .15s}' +
      '#pl-root .pl-radar-card:hover{border-color:#4c6684;transform:translateY(-1px)}' +
      '#pl-root .pl-radar-top{display:flex;align-items:center;justify-content:space-between;gap:7px}' +
      '#pl-root .pl-radar-name{display:flex;align-items:center;gap:6px;font:800 13px "Noto Sans TC",sans-serif;color:#c2d0df}' +
      '#pl-root .pl-radar-name .icon{font-size:19px}' +
      '#pl-root .pl-risk-pill{padding:3px 8px;border-radius:999px;font:800 11px "Noto Sans TC",sans-serif;border:1px solid}' +
      '#pl-root .pl-risk-pill.low{color:#bae6fd;border-color:rgba(56,189,248,.45);background:rgba(14,165,233,.11)}' +
      '#pl-root .pl-risk-pill.mid{color:#fde68a;border-color:rgba(250,204,21,.45);background:rgba(234,179,8,.11)}' +
      '#pl-root .pl-risk-pill.high{color:#fed7aa;border-color:rgba(251,146,60,.5);background:rgba(249,115,22,.12)}' +
      '#pl-root .pl-radar-dir{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-top:8px}' +
      '#pl-root .pl-radar-dir .trend{font:900 19px "Noto Sans TC",sans-serif;color:#edf5ff}' +
      '#pl-root .pl-radar-dir .change{font-size:18px;font-weight:900;white-space:nowrap;letter-spacing:.01em}' +
      '#pl-root .pl-radar-card.tw .change.radar-pos,#pl-root .pl-radar-card.fut .change.radar-pos{color:var(--red)}' +
      '#pl-root .pl-radar-card.tw .change.radar-neg,#pl-root .pl-radar-card.fut .change.radar-neg{color:var(--green)}' +
      '#pl-root .pl-radar-card.us .change.radar-pos{color:var(--green)}#pl-root .pl-radar-card.us .change.radar-neg{color:var(--red)}' +
      '#pl-root .pl-radar-card .change.radar-flat{color:#94a3b8}' +
      '#pl-root .pl-radar-heat{display:grid;grid-template-columns:auto 1fr;gap:7px;align-items:center;margin-top:8px}' +
      '#pl-root .pl-radar-heat span{font-size:11px;color:#a2b3c7;white-space:nowrap}' +
      '#pl-root .pl-radar-heat .track{height:6px;border-radius:999px;background:#1e2c40;overflow:hidden}' +
      '#pl-root .pl-radar-heat .track i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#38bdf8,#facc15,#fb923c)}' +
      '#pl-root .pl-radar-note{font:500 13px/1.55 "Noto Sans TC",sans-serif;color:#aebed0;margin-top:8px;min-height:40px}' +
      '#pl-root .pl-radar-meta{font-size:11px;color:#8296ae;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#pl-root .pl-safe-box{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;gap:9px;align-items:stretch;' +
        'margin-top:10px;background:transparent;border:0;padding:0}' +
      '#pl-root .pl-safe-level{border:1px solid #2b3e58;border-radius:10px;padding:10px 13px;background:#0b1524}' +
      '#pl-root .pl-safe-level.ceiling{border-color:rgba(248,113,113,.42);background:linear-gradient(135deg,rgba(127,29,29,.14),#0b1524 64%)}' +
      '#pl-root .pl-safe-level.floor{border-color:rgba(74,222,128,.36);background:linear-gradient(135deg,rgba(20,83,45,.14),#0b1524 64%)}' +
      '#pl-root .pl-safe-level.ceiling .v{color:var(--red)}#pl-root .pl-safe-level.floor .v{color:var(--green)}' +
      '#pl-root .pl-safe-level.stale{border-color:rgba(250,204,21,.34);background:linear-gradient(135deg,rgba(113,63,18,.14),#0b1524 64%)}' +
      '#pl-root .pl-safe-level.stale .v{color:#cbd5e1}#pl-root .pl-safe-level.stale .distance{color:#fde68a}' +
      '#pl-root .pl-safe-level .k{font:700 12px "Noto Sans TC",sans-serif;color:#a3b4c7}' +
      '#pl-root .pl-safe-level .v{font-size:24px;font-weight:900;color:#edf5ff;margin-top:3px}' +
      '#pl-root .pl-safe-level .s{font:500 12px "Noto Sans TC",sans-serif;color:#91a4bb;margin-top:2px}' +
      '#pl-root .pl-safe-level .distance{font:800 12px "Noto Sans TC",sans-serif;color:#cbd5e1;margin-top:3px}' +
      '#pl-root .pl-safe-sep{display:none}' +
      '#pl-root .pl-beginner-actions{display:flex;align-self:center;gap:6px;flex-wrap:wrap;justify-content:flex-end}' +
      '#pl-root .pl-beginner-actions .pl-btn{font-size:12px;padding:7px 11px}' +
      '#pl-root .pl-vol-envelope{flex:1 0 100%;text-align:right;font:700 11px "Noto Sans TC",sans-serif;color:#bae6fd}' +
      '#pl-root .pl-beginner-advanced{margin-top:10px;border:1px solid #2a3d56;border-radius:10px;padding:12px;' +
        'background:#091321}' +
      '#pl-root .pl-beginner-advanced[hidden]{display:none!important}' +
      '#pl-root .pl-advanced-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}' +
      '#pl-root .pl-advanced-card{background:#0d192a;border:1px solid #263a52;border-radius:8px;padding:10px;min-width:0}' +
      '#pl-root .pl-advanced-card h3{display:flex;justify-content:space-between;gap:6px;font:800 13px "Noto Sans TC",sans-serif;color:#f1d56b;margin:0 0 7px}' +
      '#pl-root .pl-advanced-card h3 a{color:#7dd3fc;font-size:11px;text-decoration:none;cursor:pointer}' +
      '#pl-root .pl-advanced-card .row{display:flex;justify-content:space-between;gap:8px;padding:4px 0;' +
        'border-bottom:1px solid #1b2a3e;font-size:12px;color:#b6c5d6;min-width:0}' +
      '#pl-root .pl-advanced-card .row:last-child{border-bottom:0}' +
      '#pl-root .pl-advanced-card .row span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-advanced-card .row b{color:#e7eef8;white-space:nowrap}' +
      '#pl-root .pl-tip{border-bottom:1px dotted #7890aa;cursor:help}' +
      /* 新手中型桌面短視窗：只壓縮留白，絕不再以 7–10px 小字換取單頁。寬桌面使用基準字級並允許捲動。 */
      '@media(min-width:901px) and (max-width:1199px) and (max-height:740px){' +
        '#pl-body.pl-mode-beginner{overflow-x:hidden;overflow-y:auto;padding:2px 0 8px;scrollbar-gutter:stable}' +
        '#pl-body.pl-mode-beginner:has(.pl-beginner-advanced:not([hidden])){overflow:auto}' +
        '#pl-root .pl-beginner{padding:0 2px 8px}' +
        '#pl-root .pl-beginner-hero{grid-template-columns:185px minmax(0,1fr);gap:13px;padding:11px 18px;border-radius:11px}' +
        '#pl-root .pl-beginner-gauge{width:180px;height:104px}' +
        '#pl-root .pl-beginner-gauge svg{width:180px;height:101px}' +
        '#pl-root .pl-beginner-gauge .score{font-size:32px}' +
        '#pl-root .pl-beginner-gauge .score small{margin-top:3px}' +
        '#pl-root .pl-weather{padding:3px 8px;margin-bottom:4px}' +
        '#pl-root .pl-beginner-copy h2{line-height:1.25;margin-bottom:4px}' +
        '#pl-root .pl-divergence-warning{margin-bottom:3px;padding:2px 7px}' +
        '#pl-root .pl-beginner-copy .advice{line-height:1.35;margin-bottom:3px}' +
        '#pl-root .pl-beginner-copy .why{line-height:1.45}' +
        '#pl-root .pl-beginner-copy .quality{margin-top:4px}' +
        '#pl-root .pl-hero-foot{margin-top:4px}' +
        '#pl-root .pl-stock-check input{width:145px;padding:3px 6px}' +
        '#pl-root .pl-stock-check button{padding:3px 7px}' +
        '#pl-root .pl-simple-signals{gap:7px;margin-top:7px}' +
        '#pl-root .pl-simple-card{padding:8px 10px}' +
        '#pl-root .pl-simple-card .main{margin:5px 0 3px}' +
        '#pl-root .pl-simple-card .plain{line-height:1.4}' +
        '#pl-root .pl-simple-card .bar-meta{margin-top:3px}' +
        '#pl-root .pl-simple-card .bar{height:5px;margin-top:3px}' +
        '#pl-root .pl-market-radar{margin-top:7px;padding:8px 10px}' +
        '#pl-root .pl-market-radar-head{margin-bottom:6px}' +
        '#pl-root .pl-market-radar-grid{gap:7px}' +
        '#pl-root .pl-radar-card{padding:8px 9px}' +
        '#pl-root .pl-radar-dir{margin-top:5px}' +
        '#pl-root .pl-radar-heat{margin-top:5px}' +
        '#pl-root .pl-radar-note{line-height:1.4;margin-top:5px}' +
        '#pl-root .pl-radar-meta{margin-top:3px}' +
        '#pl-root .pl-safe-box{gap:7px;margin-top:7px;padding:0}' +
        '#pl-root .pl-safe-level{padding:6px 10px}' +
        '#pl-root .pl-safe-level .v{margin-top:2px}' +
        '#pl-root .pl-safe-level .s{margin-top:1px}' +
        '#pl-root .pl-safe-level .distance{margin-top:2px}' +
        '#pl-root .pl-safe-sep{height:36px}' +
        '#pl-root .pl-beginner-actions .pl-btn{padding:5px 8px}' +
      '}' +
      '@media(max-width:900px) and (orientation:portrait){#pl-root .pl-beginner-hero{grid-template-columns:minmax(0,1fr);text-align:center}' +
        '#pl-root .pl-beginner-gauge{margin:auto}#pl-root .pl-head{flex-wrap:wrap}' +
        '#pl-root .pl-hero-foot{flex-direction:column}#pl-root .pl-stock-check{width:min(100%,340px);max-width:100%}' +
        '#pl-root .pl-stock-check input{width:auto;min-width:0;flex:1 1 auto}#pl-root .pl-stock-check button{flex:0 0 auto}' +
        '#pl-root .pl-simple-signals,#pl-root .pl-market-radar-grid{grid-template-columns:1fr}#pl-root .pl-safe-box{grid-template-columns:1fr}' +
        '#pl-root .pl-safe-sep{width:100%;height:1px}#pl-root .pl-beginner-actions{justify-content:center}' +
        '#pl-root .pl-advanced-grid{grid-template-columns:1fr 1fr}}' +
      /* 舊 pl-expanded 已廢止：因子帳本改獨立頁，禁止再開 overflow:auto 撐破頂列 */
      '#pl-body.pl-expanded{overflow:hidden}' +
      /* KPI 細條：主數值略突出，但不再放大到擠壓 5 欄下區 */
      '#pl-root .pl-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;margin:0 0 6px;min-width:0;flex:0 0 auto}' +
      '#pl-root .pl-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:4px 6px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-strip .cell.hero{border-color:rgba(245,197,24,.35);' +
        'background:linear-gradient(180deg,rgba(28,38,58,.98),rgba(14,22,38,.98));box-shadow:inset 0 1px 0 rgba(245,197,24,.08)}' +
      '#pl-root .pl-strip .k{font-size:8px;color:#a8b6c8;letter-spacing:.3px;margin-bottom:1px;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .v{font-size:14px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums;' +
        'margin-bottom:2px}' +
      '#pl-root .pl-strip .cell.hero .v{font-size:15px;letter-spacing:-0.2px}' +
      '#pl-root .pl-strip .s{font-size:10px;margin-top:0;font-weight:800;line-height:1.25;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums}' +
      '#pl-root .pl-strip .s .pl-subq{font-size:8px;font-weight:600;color:#94a3b8;margin-left:3px}' +
      '#pl-root .pl-strip .badge{display:inline-flex;align-items:center;gap:3px;font-size:8px;color:var(--cyan)}' +
      '#pl-root .pl-strip .dot{width:4px;height:4px;border-radius:50%;background:var(--cyan);box-shadow:0 0 4px var(--cyan);flex-shrink:0}' +
      '#pl-root .pl-strip .viz-hide,#pl-root .pl-strip .viz-meter,#pl-root .pl-strip .viz-seg,' +
        '#pl-root .pl-strip .viz-chip{display:none!important}' +
      '#pl-root .pl-strip .vz-chip{display:none!important}' + /* 單顆 chip 改為全型態 tab 列 */
      /* 頂列水位 bar：指數動能／成交金額共用 vz-ref，全寬＋刻度對齊 */
      '#pl-root .pl-strip .vz-meter{display:none!important}' +
      '#pl-root .pl-strip .vz-ref{margin-top:3px;margin-bottom:11px;height:5px;width:100%;' +
        'border-radius:3px;box-sizing:border-box;flex:0 0 auto}' +
      '#pl-root .pl-strip .vz-ref .vz-tick-lbl{font-size:6px;top:6px}' +
      /* 市場趨勢型態 tabs：全列可見，當前 highlight、其餘反灰 */
      '#pl-root .pl-ttabs{display:flex;flex-wrap:wrap;gap:2px;margin-top:2px;min-width:0}' +
      '#pl-root .pl-ttabs span{font-size:6px;line-height:1.25;padding:1px 3px;border-radius:3px;' +
        'border:1px solid rgba(71,85,105,.55);color:#64748b;background:rgba(15,23,42,.35);' +
        'font-weight:600;white-space:nowrap;opacity:.38;letter-spacing:-0.15px}' +
      '#pl-root .pl-ttabs span.on{opacity:1;font-weight:800}' +
      '#pl-root .pl-ttabs span.on.buy{color:var(--red);border-color:rgba(239,68,68,.55);' +
        'background:rgba(239,68,68,.16)}' +
      '#pl-root .pl-ttabs span.on.sell{color:var(--green);border-color:rgba(34,197,94,.5);' +
        'background:rgba(34,197,94,.14)}' +
      '#pl-root .pl-ttabs span.on.mid{color:#cbd5e1;border-color:rgba(148,163,184,.5);' +
        'background:rgba(148,163,184,.14)}' +
      /* 上下兩區維持五框等寬，確保第二、第三排的視覺節奏一致。 */
      '#pl-root .pl-dash{flex:1;min-height:0;display:grid;gap:6px;' +
        'grid-template-rows:minmax(0,1fr) minmax(0,1fr)}' +
      '#pl-root .pl-zone{display:grid;gap:6px;min-width:0;min-height:0;height:100%;' +
        'grid-template-columns:repeat(5,minmax(0,1fr))}' +
      /* Widget 殼：略提亮底＋微亮邊框，與 --bg 頁底拉開層級 */
      '#pl-root .pl-sec{background:linear-gradient(180deg,rgba(17,27,46,.98),rgba(11,18,32,.99));' +
        'border:1px solid rgba(42,61,92,.92);box-shadow:inset 0 1px 0 rgba(232,240,255,.045);' +
        'border-radius:6px;padding:8px 10px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#pl-root .pl-sec h4{margin:0 0 6px;font-size:10px;font-weight:800;color:#f0d060;letter-spacing:.4px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px;flex-wrap:nowrap;min-width:0}' +
      '#pl-root .pl-sec h4 a{color:var(--cyan);cursor:pointer;font-size:8px;font-weight:600;text-decoration:none;white-space:nowrap;flex:0 0 auto}' +
      '#pl-root .pl-sec h4 a:hover{color:var(--gold)}' +
      '#pl-root .pl-sec-hint{font-size:8px;color:#94a3b8;font-weight:600;margin-right:auto;' +
        'min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-sec > .pl-fill{flex:1;min-height:0;overflow:auto}' +
      '#pl-root .pl-note{font-size:8px;color:#a8b6c8;line-height:1.35;margin-top:2px;flex:0 0 auto}' +
      '#pl-root .pl-loading{font-size:10px;color:#94a3b8;padding:12px 0}' +
      '#pl-root .pl-stale{display:inline-block;margin-left:4px;padding:0 5px;border-radius:3px;font-size:8px;font-weight:700;' +
        'background:rgba(56,189,248,.10);color:var(--cyan);border:1px solid rgba(56,189,248,.30)}' +
      '#pl-root .pl-empty{flex:1;min-height:48px;display:flex;flex-direction:column;align-items:center;justify-content:center;' +
        'gap:4px;text-align:center;color:#94a3b8;font-size:9px;line-height:1.4;padding:8px;' +
        'border:1px dashed rgba(148,163,184,.25);border-radius:6px;background:rgba(15,23,42,.35)}' +
      /* hidden 必須蓋過 .pl-empty{display:flex}，否則法人窗會露出空白虛線框 */
      '#pl-root .pl-empty[hidden]{display:none!important}' +
      '#pl-root .pl-empty b{color:var(--thi);font-size:10px}' +
      /* 市場脈動：綜合框 compact（勿再 1.35fr 搶寬），留給右邊體質／風險完整顯示 */
      '#pl-root .pl-score3{display:grid;grid-template-columns:minmax(0,0.9fr) minmax(0,1.05fr) minmax(0,1.05fr);' +
        'gap:3px;flex:0 0 auto;align-items:stretch;min-width:0}' +
      '#pl-root .pl-score3 .sc{background:var(--bg);border:1px solid var(--border);border-radius:4px;' +
        'padding:3px 4px;min-width:0;display:flex;flex-direction:column;gap:0;' +
        'writing-mode:horizontal-tb;text-orientation:mixed;overflow:hidden}' +
      '#pl-root .pl-score3 .sc.main{border-color:rgba(245,197,24,.45);' +
        'background:linear-gradient(180deg,rgba(36,48,72,.98),rgba(14,22,38,.98));padding:3px 4px}' +
      '#pl-root .pl-score3 .sc.child{opacity:.95}' +
      '#pl-root .pl-score3 .sc .k{font-size:7px;color:#a8b6c8;letter-spacing:.15px;min-width:0;' +
        'display:flex;flex-wrap:nowrap;align-items:baseline;justify-content:space-between;gap:2px;' +
        'writing-mode:horizontal-tb;overflow:hidden}' +
      '#pl-root .pl-score3 .sc .k > span:first-child{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-score3 .sc .k .w{color:#e8c84a;font-weight:700;font-size:7px;white-space:nowrap;flex:0 0 auto}' +
      '#pl-root .pl-score3 .sc .v{font-size:13px;font-weight:800;color:var(--thi);line-height:1.1;' +
        'white-space:nowrap;font-variant-numeric:tabular-nums;margin:1px 0}' +
      /* 綜合與子項同級 compact，勿再放大搶空間 */
      '#pl-root .pl-score3 .sc.main .v{font-size:14px;letter-spacing:-0.2px}' +
      '#pl-root .pl-score3 .sc .l{font-size:7px;font-weight:700;min-width:0;overflow:hidden;' +
        'text-overflow:ellipsis;white-space:nowrap;writing-mode:horizontal-tb}' +
      '#pl-root .pl-score3 .sc .l.pos{color:var(--gold)}' +
      '#pl-root .pl-score3 .sc .l.risk{color:var(--cyan)}' +
      '#pl-root .pl-score3 .sc .meter{margin-top:1px;min-width:0;max-height:4px;overflow:hidden}' +
      '#pl-root .pl-score3 .sc .meter .vz-meter,#pl-root .pl-score3 .sc .vz-meter{margin-top:0;height:3px}' +
      '#pl-root .pl-score-formula{font-size:8px;color:#94a3b8;margin:3px 0 0;line-height:1.35;flex:0 0 auto;' +
        'min-width:0;max-width:100%;overflow:hidden;white-space:normal;word-break:break-word;' +
        'overflow-wrap:anywhere}' +
      '#pl-root .pl-score-formula b{color:#cbd5e1;font-weight:700}' +
      '#pl-root .pl-score-meta{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-top:3px;flex:0 0 auto;min-width:0}' +
      '#pl-root .pl-score-meta .m{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:3px 5px;min-width:0}' +
      '#pl-root .pl-score-meta .m .k{font-size:8px;color:#a8b6c8}' +
      '#pl-root .pl-score-meta .m .v{font-size:11px;font-weight:800;margin-top:1px;color:var(--thi);' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-comp{height:3px;border-radius:2px;background:var(--bg3);overflow:hidden;margin-top:2px}' +
      '#pl-root .pl-comp > i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--gold))}' +
      '#pl-root .pl-drivers{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-top:3px;font-size:8px;' +
        'flex:1 1 0;min-height:0}' +
      '#pl-root .pl-drivers .box{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:3px 5px;min-height:0;overflow:auto}' +
      '#pl-root .pl-drivers .box .k{color:#a8b6c8;margin-bottom:1px;font-size:8px;font-weight:700}' +
      '#pl-root .pl-drivers .box .k span{color:#94a3b8;font-weight:600}' +
      '#pl-root .pl-drivers .box li{margin:1px 0;color:var(--text);list-style:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-sec-tog{display:inline-flex;gap:2px;margin-left:auto}' +
      '#pl-root .pl-sec-tog button{padding:1px 6px;border:1px solid var(--border);border-radius:3px;background:transparent;' +
        'color:#94a3b8;font-size:8px;font-family:inherit;cursor:pointer}' +
      '#pl-root .pl-sec-tog button.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      /* 加權／法人／廣度共用：上方一行四格 KPI，中間 flex 拉高線圖，底評論 */
      '#pl-root .pl-inst4,#pl-root .pl-bd4,#pl-root .pl-ohlc4{' +
        'display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;flex:0 0 auto}' +
      '#pl-root .pl-inst4 .c,#pl-root .pl-bd4 .c,#pl-root .pl-ohlc4 .c{' +
        'background:rgba(6,10,18,.45);border:1px solid rgba(42,61,92,.7);border-radius:5px;padding:4px 2px;text-align:center;min-width:0}' +
      '#pl-root .pl-inst4 .c .k,#pl-root .pl-bd4 .c .k,#pl-root .pl-ohlc4 .c .k{' +
        'font-size:8px;color:#a8b6c8;line-height:1.2}' +
      '#pl-root .pl-inst4 .c .v,#pl-root .pl-bd4 .c .v,#pl-root .pl-ohlc4 .c .v{' +
        'font-size:10px;font-weight:800;margin-top:2px;line-height:1.15;' +
        'font-variant-numeric:tabular-nums;letter-spacing:-0.2px;white-space:nowrap;' +
        'overflow:visible;max-width:100%}' +
      /* 加權 OHLC 整數千分位後對齊法人 10px；細字距避免 44,450 擁擠 */
      '#pl-root .pl-ohlc4 .c .v{letter-spacing:-0.3px;color:var(--thi)}' +
      '#pl-root .pl-inst-trend,#pl-root .pl-bd-trend,#pl-root .pl-ohlc-trend{' +
        'flex:1 1 0;min-height:0;margin:5px 0 3px;background:rgba(6,10,18,.55);' +
        'border:1px solid rgba(42,61,92,.75);border-radius:5px;padding:5px 7px;' +
        'display:flex;flex-direction:column;overflow:hidden;min-width:0}' +
      '#pl-root .pl-inst-trend .lab,#pl-root .pl-bd-trend .lab,#pl-root .pl-ohlc-trend .lab{' +
        'font-size:9px;color:#a8b6c8;flex:0 0 auto;margin-bottom:3px;' +
        'display:flex;justify-content:space-between;gap:4px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-inst-trend .lab > span:last-child,#pl-root .pl-bd-trend .lab > span:last-child,' +
        '#pl-root .pl-ohlc-trend .lab > span:last-child{' +
        'min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-inst-trend .chart,#pl-root .pl-bd-trend .chart,#pl-root .pl-ohlc-trend .chart{' +
        'flex:1 1 0;min-height:48px;min-width:0;overflow:visible;position:relative}' +
      '#pl-root .pl-inst-trend .chart .vz-spark-ax,#pl-root .pl-bd-trend .chart .vz-spark-ax,' +
        '#pl-root .pl-ohlc-trend .chart .vz-spark-ax{' +
        'height:100%;min-height:0;max-width:100%;min-width:0;overflow:visible}' +
      '#pl-root .pl-inst-trend .chart .vz-yunit,#pl-root .pl-inst-trend .chart .vz-ylabs,' +
        '#pl-root .pl-bd-trend .chart .vz-yunit,#pl-root .pl-bd-trend .chart .vz-ylabs,' +
        '#pl-root .pl-ohlc-trend .chart .vz-yunit,#pl-root .pl-ohlc-trend .chart .vz-ylabs{font-size:7px}' +
      '#pl-root .pl-inst-trend .chart .vz-plot,#pl-root .pl-bd-trend .chart .vz-plot,' +
        '#pl-root .pl-ohlc-trend .chart .vz-plot{min-width:0;min-height:0;overflow:visible}' +
      '#pl-root .pl-inst-trend .chart .vz-pt,#pl-root .pl-bd-trend .chart .vz-pt,' +
        '#pl-root .pl-ohlc-trend .chart .vz-pt{font-size:8px;padding:1px 3px;z-index:4}' +
      '#pl-root .pl-inst-trend .chart .vz-plot svg,#pl-root .pl-bd-trend .chart .vz-plot svg,' +
        '#pl-root .pl-ohlc-trend .chart .vz-plot svg{' +
        'width:100%;height:100%;min-width:0;min-height:0;' +
        'max-width:100%;max-height:100%;margin:0;display:block;box-sizing:border-box}' +
      '#pl-root .pl-inst-cmt,#pl-root .pl-bd-cmt,#pl-root .pl-ohlc-cmt{' +
        'font-size:9px;line-height:1.35;color:var(--text);margin-top:2px;flex:0 0 auto;' +
        'max-height:2.7em;min-height:0;overflow:hidden}' +
      '#pl-root .pl-inst-cmt b,#pl-root .pl-bd-cmt b,#pl-root .pl-ohlc-cmt b{color:var(--gold);font-weight:700}' +
      '#pl-root .pl-inst-cmt .up,#pl-root .pl-bd-cmt .up,#pl-root .pl-ohlc-cmt .up{color:var(--red)}' +
      '#pl-root .pl-inst-cmt .dn,#pl-root .pl-bd-cmt .dn,#pl-root .pl-ohlc-cmt .dn{color:var(--green)}' +
      '#pl-root .pl-chip{display:inline-block;margin:1px 3px 0 0;padding:0 5px;border-radius:999px;border:1px solid var(--border);font-size:8px;color:#94a3b8}' +
      /* 自選標籤＝純色點（省寬；機會金／風險淡紅／觀察灰青），勿用漲跌綠 */
      '#pl-root .pl-tag{display:inline-flex;align-items:center;justify-content:center;width:8px;height:8px;' +
        'margin:0 auto;padding:0;border-radius:50%;border:1px solid transparent;vertical-align:middle;' +
        'font-size:0;line-height:0;text-indent:-9999px;overflow:hidden}' +
      '#pl-root .pl-tag.hot{background:var(--gold);border-color:var(--gold-m);box-shadow:0 0 0 1px rgba(245,197,24,.25)}' +
      '#pl-root .pl-tag.cold{background:#f87171;border-color:rgba(239,68,68,.45);box-shadow:0 0 0 1px rgba(239,68,68,.2)}' +
      '#pl-root .pl-tag.ok{background:#64748b;border-color:rgba(148,163,184,.35)}' +
      '#pl-root .pl-tag.resonant{box-shadow:0 0 0 2px rgba(251,191,36,.18),0 0 8px rgba(251,191,36,.65)}' +
      '#pl-root .pl-tag.resonant.bear{box-shadow:0 0 0 2px rgba(251,146,60,.18),0 0 8px rgba(248,113,113,.62)}' +
      '#pl-root .pl-theme-heat{display:inline-flex;align-items:center;gap:3px;max-width:92px;padding:1px 5px;' +
        'border:1px solid rgba(251,191,36,.35);border-radius:999px;background:rgba(251,191,36,.10);' +
        'color:#fcd34d;font-size:7px;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#pl-root .pl-wl col.c-sym{width:40%}' +
      '#pl-root .pl-wl col.c-px{width:24%}' +
      '#pl-root .pl-wl col.c-chg{width:24%}' +
      '#pl-root .pl-wl col.c-tag{width:12%}' +
      '#pl-root .pl-wl td.tag{text-align:center;width:12%;padding-left:0;padding-right:0}' +
      '#pl-root .pl-wl td.px,#pl-root .pl-wl td.chg{font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}' +
      '#pl-root .pl-wl th:nth-child(2),#pl-root .pl-wl th:nth-child(3){text-align:right}' +
      '#pl-root .pl-wl .nm-only{color:#94a3b8;font-weight:500;font-size:7px;display:block;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%;line-height:1.2}' +
      /* 產業輪動：縮字符合窄欄（與近漲停／快訊同級） */
      '#pl-root #pl-sectors .pl-note{font-size:7px;line-height:1.25;margin:0 0 2px}' +
      '#pl-root #pl-sectors .pl-sec-tog button{font-size:7px;padding:1px 5px}' +
      '#pl-root .pl-sbar{display:flex;align-items:center;gap:3px;margin:0;font-size:8px;' +
        'cursor:pointer;border-radius:3px;padding:1px 2px;transition:background .12s,box-shadow .12s,opacity .12s;min-width:0;' +
        'line-height:1.2}' +
      '#pl-root .pl-sbar .nm{width:40px;flex-shrink:0;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
        'font-size:8px;letter-spacing:-0.15px}' +
      '#pl-root .pl-sbar .track{flex:1;height:4px;background:var(--bg);border-radius:3px;overflow:hidden;min-width:0}' +
      '#pl-root .pl-sbar .track > i{display:block;height:100%;border-radius:3px}' +
      '#pl-root .pl-sbar .pc{width:36px;text-align:right;font-weight:700;flex-shrink:0;font-size:8px;' +
        'font-variant-numeric:tabular-nums;letter-spacing:-0.3px;white-space:nowrap}' +
      '#pl-root .pl-sbar .ad{width:30px;text-align:right;font-size:6px;color:#94a3b8;flex-shrink:0;font-variant-numeric:tabular-nums}' +
      '#pl-root .pl-sbar .ad .u{color:var(--red)}#pl-root .pl-sbar .ad .d{color:var(--green)}' +
      '#pl-root .pl-sbar.hi{background:rgba(245,197,24,.10);box-shadow:inset 2px 0 0 var(--gold)}' +
      '#pl-root .pl-sbar.dim{opacity:.4}' +
      /* lists（近漲停／跌幅異常：縮字避免跳行） */
      '#pl-root .pl-list{list-style:none;margin:0;padding:0;flex:1 1 0;min-height:0;overflow:auto}' +
      '#pl-root .pl-list li{display:flex;justify-content:space-between;align-items:baseline;gap:3px;padding:2px 3px;border-bottom:1px solid rgba(26,39,64,.85);cursor:pointer;font-size:8px;' +
        'border-radius:3px;transition:background .12s,box-shadow .12s,opacity .12s;line-height:1.25;min-width:0}' +
      '#pl-root .pl-list li:nth-child(even){background:rgba(148,163,184,.035)}' +
      '#pl-root .pl-list li:hover{background:rgba(22,34,64,.88)}' +
      '#pl-root .pl-list li.hi{background:rgba(245,197,24,.10);box-shadow:inset 2px 0 0 var(--gold)}' +
      '#pl-root .pl-list li.dim{opacity:.35}' +
      '#pl-root .pl-list .nm{color:var(--thi);font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px}' +
      '#pl-root .pl-list .cd{color:#a8b6c8;font-size:7.5px;margin-right:2px}' +
      '#pl-root .pl-list .ind{display:inline-block;margin-left:2px;padding:0 2px;border-radius:3px;font-size:6px;font-weight:700;' +
        'color:var(--cyan);background:rgba(56,189,248,.08);border:1px solid rgba(56,189,248,.25);vertical-align:1px}' +
      '#pl-root .pl-movers .pl-list li > span:last-child{flex:0 0 auto;white-space:nowrap;font-size:9px;' +
        'font-variant-numeric:tabular-nums;letter-spacing:-0.25px}' +
      '#pl-root .pl-movers .pl-sec-hint,#pl-root .pl-movers h4 > span{font-size:7px!important}' +
      '#pl-root .pl-movers .vz-chip{font-size:6px;padding:0 3px;line-height:1.2}' +
      '#pl-root .pl-movers .vz-rowbar{max-width:48px;height:3px;margin-left:3px}' +
      /* 全球影響固定在 5×2 儀表板格內；內容超高時由卡片本身垂直捲動，避免下緣被殼層裁切。 */
      '#pl-root .pl-sec.pl-global-sec{overflow:hidden;min-height:0}' +
      '#pl-root .pl-global{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:min-content;' +
        'gap:3px;flex:1 1 0;align-content:start;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;' +
        'scrollbar-gutter:stable;scrollbar-width:thin;scrollbar-color:#3b506e transparent;' +
        'touch-action:pan-y;min-height:0;min-width:0;max-height:100%;padding-right:2px}' +
      '#pl-root .pl-global::-webkit-scrollbar{width:6px}' +
      '#pl-root .pl-global::-webkit-scrollbar-thumb{background:#3b506e;border-radius:6px}' +
      '#pl-root .pl-global:focus-visible{outline:1px solid var(--cyan);outline-offset:2px}' +
      '#pl-root .pl-kicker{display:none!important}' +
      '#pl-root .pl-global .g{background:rgba(6,10,18,.45);border:1px solid rgba(42,61,92,.7);border-radius:4px;padding:3px 5px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-global .g .k{font-size:7px;color:var(--tlo);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:0;' +
        'display:flex;justify-content:space-between;gap:2px;align-items:baseline}' +
      '#pl-root .pl-global .g .k .abbr{color:var(--thi);font-weight:800;letter-spacing:.2px}' +
      '#pl-root .pl-global .g .k .role{display:none}' +
      '#pl-root .pl-global .g .row{display:flex;align-items:baseline;justify-content:space-between;gap:3px;min-width:0}' +
      '#pl-root .pl-global .g .v{font-size:8px;font-weight:800;color:var(--thi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1 1 auto;' +
        'font-variant-numeric:tabular-nums;letter-spacing:-0.25px}' +
      '#pl-root .pl-global .g .s{font-size:7px;font-weight:700;flex:0 0 auto;white-space:nowrap;text-align:right;letter-spacing:-0.35px;' +
        'font-variant-numeric:tabular-nums;min-width:0;max-width:58%}' +
      /* 市場快訊：標題／搜尋／三個市場 tab／中樞固定同一列。 */
      '#pl-root #pl-flash-sec>h4{gap:2px}' +
      '#pl-root .pl-flash-title{white-space:nowrap;flex:0 0 auto}' +
      '#pl-root .pl-flash-tools{display:flex;align-items:center;gap:2px;flex:1 1 0;min-width:0;justify-content:flex-end;white-space:nowrap}' +
      '#pl-root #pl-flash-sec .pl-sec-tog{display:flex;flex:0 0 auto;flex-wrap:nowrap;gap:1px;margin-left:0}' +
      '#pl-root #pl-flash-sec .pl-sec-tog button{font-size:6.5px;line-height:1.2;padding:1px 3px;white-space:nowrap;flex:0 0 auto;min-width:0}' +
      '#pl-root #pl-flash-sec>h4>a{font-size:7px;margin-left:1px}' +
      '#pl-root .pl-flash-q{width:48px;min-width:38px;max-width:58px;flex:1 1 48px;padding:1px 3px;border:1px solid var(--border);border-radius:3px;' +
        'background:var(--bg);color:var(--thi);font-size:7px;font-family:inherit}' +
      '#pl-root .pl-flash-q:focus{outline:none;border-color:var(--gold-m)}' +
      '#pl-root .pl-flash{flex:1 1 0;min-height:0;overflow:auto;font-size:8px}' +
      '#pl-root .pl-flash .row{display:grid;grid-template-columns:36px 44px minmax(0,1fr);align-items:baseline;gap:3px;padding:2px 3px;' +
        'border-bottom:1px solid rgba(26,39,64,.85);cursor:pointer;line-height:1.35;min-width:0}' +
      '#pl-root .pl-flash .row:nth-child(even){background:rgba(148,163,184,.035)}' +
      '#pl-root .pl-flash .row:hover{background:rgba(22,34,64,.88)}' +
      '#pl-root .pl-flash .t{color:#a8b6c8;font-size:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#pl-root .pl-flash .cat{color:var(--cyan);font-size:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#pl-root .pl-flash .cat.us{color:var(--gold)}' +
      '#pl-root .pl-flash .ttl{color:#e2e8f0;font-size:8px;min-width:0;overflow:hidden;' +
        'text-overflow:ellipsis;white-space:nowrap;letter-spacing:-0.15px}' +
      /* 自選風險：縮字符合版面（與近漲停／快訊／產業輪動同級） */
      '#pl-root .pl-sec.pl-wl{overflow:hidden;min-height:0}' +
      '#pl-root #pl-watch-sec>h4.pl-wl-head{display:flex;align-items:center;justify-content:flex-start;gap:2px;' +
        'flex-wrap:nowrap;white-space:nowrap;overflow:hidden;min-width:0}' +
      '#pl-root .pl-wl-title{flex:0 0 auto}' +
      '#pl-root #pl-watch-sec .pl-theme-heat{flex:1 1 auto;min-width:0;max-width:92px}' +
      '#pl-root #pl-watch-sec .pl-sec-tog{display:inline-flex;flex:0 0 auto;flex-wrap:nowrap;gap:1px;margin-left:auto;white-space:nowrap}' +
      '#pl-root #pl-watch-sec .pl-sec-tog button{font-size:6.5px;line-height:1.15;padding:1px 3px;white-space:nowrap;flex:0 0 auto;min-width:0}' +
      '#pl-root #pl-watch-sec>h4>a{flex:0 0 auto;margin-left:1px;font-size:7px}' +
      '#pl-root .pl-wl-scroll{flex:1 1 0;min-height:0;overflow:auto;overscroll-behavior:contain}' +
      '#pl-root .pl-wl table{width:100%;border-collapse:collapse;font-size:8px;table-layout:fixed}' +
      '#pl-root .pl-wl th,#pl-root .pl-wl td{padding:4px 4px;border-bottom:1px solid rgba(26,39,64,.85);text-align:right;' +
        'line-height:1.25}' +
      '#pl-root .pl-wl th:first-child,#pl-root .pl-wl td:first-child{text-align:left}' +
      '#pl-root .pl-wl th{color:#a8b6c8;position:sticky;top:0;background:rgba(17,27,46,.98);z-index:1;font-size:7px}' +
      '#pl-root .pl-wl tr{cursor:pointer}' +
      '#pl-root .pl-wl tr:nth-child(even){background:rgba(148,163,184,.035)}' +
      '#pl-root .pl-wl tr:hover{background:rgba(22,34,64,.88)}' +
      '#pl-root .pl-wl tr.news-hit td:first-child{box-shadow:inset 2px 0 #f59e0b;background:rgba(245,158,11,.055)}' +
      '#pl-root .pl-news-mark{display:inline-block;margin-left:3px;color:#fbbf24;font-size:8px;text-shadow:0 0 7px rgba(251,191,36,.7)}' +
      '#pl-root .pl-wl tr[data-news-tier="HIGH"] .pl-news-mark{color:#fb7185;text-shadow:0 0 8px rgba(251,113,133,.75)}' +
      '#pl-root .pl-wl td.px{padding-right:5px}' +
      '#pl-root .pl-wl td.px,#pl-root .pl-wl td.chg{font-size:8px;font-variant-numeric:tabular-nums;letter-spacing:-0.25px}' +
      '#pl-root .pl-wl td:first-child{font-size:8px;font-weight:700;letter-spacing:-0.15px}' +
      '#pl-root .pl-wl .mkt{font-size:7px;color:#94a3b8;font-weight:600;margin-left:2px}' +
      '#pl-root .pl-wl .pl-tag{width:7px;height:7px}' +
      '#pl-root .pl-inst-ctx{display:none}' + /* Z/P 改由趨勢 meta／title 承載，免搶四格寬 */
      /* factors footer（展開時可捲） */
      '#pl-root .pl-extra{flex:0 0 auto;margin-top:4px}' +
      '#pl-root .pl-factors{margin-top:4px;scroll-margin-top:8px;padding:2px;border-radius:8px;transition:box-shadow .35s,background .35s}' +
      '#pl-root .pl-factors.flash{box-shadow:0 0 0 1px var(--gold-m),0 0 24px rgba(245,197,24,.18);background:rgba(245,197,24,.04)}' +
      '#pl-root .pl-factors > .pl-sec-title{font-family:\'Noto Serif TC\',serif;font-size:13px;font-weight:700;color:var(--thi);margin:0 0 6px;letter-spacing:.5px}' +
      '#pl-root .pl-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:6px}' +
      '#pl-root .pl-fac{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px;margin-bottom:4px;cursor:pointer}' +
      '#pl-root .pl-fac:hover{border-color:var(--gold-m);background:var(--bg3)}' +
      '#pl-root .pl-fac.open{border-color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .pl-fac .hd{display:flex;justify-content:space-between;gap:6px;font-size:10px;font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-fac .ds{font-size:9px;color:var(--tlo);line-height:1.4;margin-top:2px}' +
      '#pl-root .pl-fac .more{display:none;margin-top:4px;padding-top:4px;border-top:1px dashed var(--border);font-size:9px;color:var(--text);line-height:1.45}' +
      '#pl-root .pl-fac.open .more{display:block}' +
      '#pl-root .pl-fac .sc-pos{color:var(--red)}#pl-root .pl-fac .sc-risk{color:var(--cyan)}#pl-root .pl-fac .sc-pend{color:var(--tlo)}' +
      '#pl-root .pl-col{max-height:220px;overflow:auto}' +
      '#pl-root table.pillars{width:100%;border-collapse:collapse;font-size:10px}' +
      '#pl-root table.pillars th,#pl-root table.pillars td{padding:3px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root table.pillars th:first-child,#pl-root table.pillars td:first-child{text-align:left}' +
      '#pl-root table.pillars th{color:var(--tlo)}' +
      /* 手機橫式專業模式：維持 5+5；完整縮放每一類內容，不再以裁切冒充無碰撞。 */
      '@media(orientation:landscape) and (max-height:540px) and (pointer:coarse){' +
        '#view-pulse.sv-panel.on{padding:3px 5px 5px}' +
        '#pl-root{-webkit-text-size-adjust:100%;text-size-adjust:100%}' +
        '#pl-root .pl-head{gap:4px;margin-bottom:2px}' +
        '#pl-root .pl-head>div:first-child{gap:4px}' +
        '#pl-root .pl-title{font-size:12px}' +
        '#pl-root .pl-sub{font-size:7px}' +
        '#pl-root .pl-actions{gap:2px}' +
        '#pl-root .pl-btn,#pl-root .pl-mode-toggle button{font-size:7.5px;padding:2px 5px}' +
        '#pl-root .pl-strip{gap:4px;margin-bottom:4px}' +
        '#pl-root .pl-strip .cell{padding:3px 5px}' +
        '#pl-root .pl-strip .k{font-size:6px}' +
        '#pl-root .pl-strip .v{font-size:11px!important;line-height:1.1;margin-bottom:0}' +
        '#pl-root .pl-strip .cell.hero .v{font-size:12px!important}' +
        '#pl-root .pl-strip .v span[style]{font-size:7px!important}' +
        '#pl-root .pl-strip .s{font-size:5px;line-height:1.15;letter-spacing:-.08px}' +
        '#pl-root .pl-strip .s .pl-subq{font-size:5px}' +
        '#pl-root .pl-ttabs span{font-size:5.5px;padding:0 2px}' +
        '#pl-root .pl-strip .vz-ref{margin-top:2px;margin-bottom:6px;height:4px}' +
        '#pl-root .pl-dash{gap:4px;grid-template-rows:minmax(0,1fr) minmax(0,1fr)}' +
        '#pl-root .pl-zone{gap:4px;grid-template-columns:repeat(5,minmax(0,1fr))}' +
        '#pl-root .pl-sec{padding:4px 6px;height:100%;overflow:hidden}' +
        /* 5+5 十張專業卡片的標題需比資料內容更節制；只在手機橫式縮小，避免標題／控制項互相遮蔽。 */
        'html.st-vs5 #pl-root .pl-zone>.pl-sec>h4{margin:0 0 2px;padding-left:5px!important;font-size:7px!important;' +
          'line-height:10px;letter-spacing:0!important;gap:2px;flex-wrap:nowrap;min-width:0;max-height:none;overflow:visible}' +
        'html.st-vs5 #pl-root .pl-sec h4:before{width:1px!important}' +
        '#pl-root .pl-sec-title-text{flex:0 0 auto;min-width:0;white-space:nowrap}' +
        '#pl-root .pl-sec h4 a,#pl-root .pl-sec-hint{font-size:6.5px}' +
        '#pl-root #pl-inst-stale{flex:0 1 46px;max-width:46px;margin-left:1px;padding:0 2px;font-size:0;' +
          'white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
        '#pl-root #pl-inst-stale:after{content:attr(data-compact-label);font-size:6px;line-height:1.1}' +
        '#pl-root .pl-movers h4 .pl-movers-date,#pl-root .pl-movers h4 .pl-movers-note{font-size:0!important;flex:0 1 auto}' +
        '#pl-root .pl-movers h4 .pl-movers-date:after,#pl-root .pl-movers h4 .pl-movers-note:after{' +
          'content:attr(data-compact-label);font-size:5.5px;line-height:1.1}' +
        '#pl-root #pl-flash-sec>h4,#pl-root #pl-watch-sec>h4{flex-wrap:nowrap}' +
        '#pl-root .pl-note{font-size:7px;line-height:1.2;margin-top:2px}' +
        '#pl-root .pl-score3{gap:2px}' +
        '#pl-root .pl-score3 .sc,#pl-root .pl-score3 .sc.main{padding:2px 3px}' +
        '#pl-root .pl-score3 .sc .k,#pl-root .pl-score3 .sc .k .w,#pl-root .pl-score3 .sc .l{font-size:6.5px}' +
        '#pl-root .pl-score3 .sc .v{font-size:10px;line-height:1.05}' +
        '#pl-root .pl-score3 .sc.main .v{font-size:11px}' +
        '#pl-root .pl-score-formula,#pl-root .pl-drivers,#pl-root .pl-drivers .box .k{' +
          'font-size:6.5px;line-height:1.15}' +
        '#pl-root .pl-score-meta{gap:2px;margin-top:2px}' +
        '#pl-root .pl-score-meta .m{padding:2px 3px}' +
        '#pl-root .pl-score-meta .m .k{font-size:6.5px}' +
        '#pl-root .pl-score-meta .m .v{font-size:9px}' +
        '#pl-root .pl-drivers{gap:2px;margin-top:2px}' +
        '#pl-root .pl-drivers .box{padding:2px 3px}' +
        /* 四格 KPI 每格只有約 32px：縮排後讓完整六字符數值真的放得下。 */
        '#pl-root .pl-inst4,#pl-root .pl-bd4,#pl-root .pl-ohlc4{gap:2px}' +
        '#pl-root .pl-inst4 .c,#pl-root .pl-bd4 .c,#pl-root .pl-ohlc4 .c{padding:2px 1px}' +
        '#pl-root .pl-inst4 .c .k,#pl-root .pl-bd4 .c .k,#pl-root .pl-ohlc4 .c .k{' +
          'font-size:6.5px;line-height:1.05;white-space:nowrap}' +
        '#pl-root .pl-inst4 .c .v,#pl-root .pl-bd4 .c .v,#pl-root .pl-ohlc4 .c .v{' +
          'display:block;width:100%;font-size:8px!important;line-height:1.05;letter-spacing:-0.45px;text-align:center;' +
          'white-space:nowrap;overflow:visible;text-overflow:initial}' +
        '#pl-root .pl-ohlc4 .c .v{letter-spacing:-0.45px}' +
        /* 半高卡片只留線型；高低點與座標已由 KPI／標題重複呈現，移除可避免實際交疊。 */
        '#pl-root .pl-inst-trend .chart,#pl-root .pl-bd-trend .chart,#pl-root .pl-ohlc-trend .chart{' +
          'min-height:32px;overflow:hidden}' +
        '#pl-root .pl-inst-trend .chart .vz-yunit,#pl-root .pl-inst-trend .chart .vz-ylabs,' +
          '#pl-root .pl-inst-trend .chart .vz-xlabs,#pl-root .pl-inst-trend .chart .vz-xunit,' +
          '#pl-root .pl-inst-trend .chart .vz-pt,' +
          '#pl-root .pl-bd-trend .chart .vz-yunit,#pl-root .pl-bd-trend .chart .vz-ylabs,' +
          '#pl-root .pl-bd-trend .chart .vz-xlabs,#pl-root .pl-bd-trend .chart .vz-xunit,' +
          '#pl-root .pl-bd-trend .chart .vz-pt,' +
          '#pl-root .pl-ohlc-trend .chart .vz-yunit,#pl-root .pl-ohlc-trend .chart .vz-ylabs,' +
          '#pl-root .pl-ohlc-trend .chart .vz-xlabs,#pl-root .pl-ohlc-trend .chart .vz-xunit,' +
          '#pl-root .pl-ohlc-trend .chart .vz-pt{display:none!important}' +
        '#pl-root .pl-inst-trend .chart .vz-spark-ax,#pl-root .pl-bd-trend .chart .vz-spark-ax,' +
          '#pl-root .pl-ohlc-trend .chart .vz-spark-ax{' +
          'display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr);gap:0;padding:0;overflow:hidden}' +
        '#pl-root .pl-inst-trend .chart .vz-plot,#pl-root .pl-bd-trend .chart .vz-plot,' +
          '#pl-root .pl-ohlc-trend .chart .vz-plot{' +
          'grid-column:1;grid-row:1;border-left:0;min-width:0;min-height:0;overflow:hidden}' +
        '#pl-root .pl-inst-trend .lab,#pl-root .pl-bd-trend .lab,#pl-root .pl-ohlc-trend .lab{' +
          'font-size:7px;line-height:1.15;white-space:nowrap;overflow:hidden}' +
        '#pl-root .pl-inst-trend .lab>span,#pl-root .pl-bd-trend .lab>span,#pl-root .pl-ohlc-trend .lab>span{' +
          'min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
        '#pl-root .pl-inst-cmt,#pl-root .pl-bd-cmt,#pl-root .pl-ohlc-cmt{' +
          'font-size:7px;line-height:1.15;max-height:1.15em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
        '#pl-root .pl-sbar{gap:2px;font-size:7px;line-height:1.15;padding:0 1px}' +
        '#pl-root .pl-sbar .nm{width:48px;font-size:6.8px}' +
        '#pl-root .pl-sbar .pc{width:30px;font-size:7px}' +
        '#pl-root .pl-sbar .ad{width:22px;font-size:5px}' +
        '#pl-root .pl-list li{gap:2px;padding:1px 2px;font-size:7px;line-height:1.15}' +
        '#pl-root .pl-list .nm,#pl-root .pl-movers .pl-list li>span:last-child{font-size:7.5px}' +
        '#pl-root .pl-list .cd{font-size:6.5px;margin-right:1px}' +
        '#pl-root .pl-list .ind,#pl-root .pl-movers .vz-chip{font-size:5px}' +
        '#pl-root .pl-movers .vz-rowbar{max-width:36px;height:2px;margin-left:2px}' +
        '#pl-root .pl-global{gap:2px;padding-right:1px}' +
        '#pl-root .pl-global .g{padding:2px 3px}' +
        '#pl-root .pl-global .g .row{gap:2px}' +
        '#pl-root .pl-global .g .k{font-size:5.5px}' +
        '#pl-root .pl-global .g .s{font-size:5px;max-width:68%;letter-spacing:-.3px}' +
        '#pl-root .pl-global .g .v{font-size:5.5px;letter-spacing:-0.3px}' +
        '#pl-root .pl-flash{font-size:7px}' +
        '#pl-root .pl-flash .row{grid-template-columns:30px 36px minmax(0,1fr);gap:2px;padding:1px 2px;line-height:1.2}' +
        '#pl-root .pl-flash .t,#pl-root .pl-flash .cat{font-size:6px}' +
        '#pl-root .pl-flash .ttl{font-size:7px}' +
        '#pl-root .pl-flash-q{width:42px;min-width:34px;max-width:46px;font-size:6px}' +
        '#pl-root #pl-flash-sec .pl-sec-tog button,#pl-root #pl-watch-sec .pl-sec-tog button{' +
          'font-size:5.5px;padding:0 2px}' +
        '#pl-root .pl-wl table{font-size:7px}' +
        '#pl-root .pl-wl th,#pl-root .pl-wl td{padding:2px 2px;line-height:1.15}' +
        '#pl-root .pl-wl th,#pl-root .pl-wl .mkt,#pl-root .pl-wl .nm-only{font-size:6px}' +
        '#pl-root .pl-wl td.px,#pl-root .pl-wl td.chg,#pl-root .pl-wl td:first-child{font-size:7px}' +
      '}' +
      /* 手機直式專業模式：上下兩區各改為兩欄並允許頁面垂直捲動；橫式維持原始 5+5。 */
      '@media(max-width:900px) and (orientation:portrait){' +
        '#shell-views:has(#view-pulse.on){overflow-x:hidden!important;overflow-y:auto!important;display:block!important;' +
          'overscroll-behavior:contain;scrollbar-gutter:stable}' +
        '#view-pulse.sv-panel.on{height:auto;min-height:100%;overflow:visible;display:block!important;padding:6px 8px 18px}' +
        '#mount-pulse,#mount-pulse.sv-mount,#pl-root{height:auto;min-height:0;display:block;overflow:visible}' +
        '#pl-body.pl-mode-expert{display:block;overflow:visible;padding-bottom:12px}' +
        '#pl-root .pl-head{align-items:flex-start;gap:6px}' +
        '#pl-root .pl-head>div:first-child{gap:5px}' +
        '#pl-root .pl-title{font-size:17px}' +
        '#pl-root .pl-sub{font-size:10px;line-height:1.4}' +
        '#pl-root .pl-actions{justify-content:flex-start;flex-wrap:wrap;gap:5px}' +
        '#pl-root .pl-btn,#pl-root .pl-mode-toggle button{font-size:11px;min-height:30px;padding:5px 9px}' +
        '#pl-root .pl-strip{display:flex;gap:7px;overflow-x:auto;overflow-y:hidden;padding:1px 1px 7px;' +
          'scroll-snap-type:x proximity;scrollbar-width:thin;overscroll-behavior-x:contain}' +
        '#pl-root .pl-strip .cell{flex:0 0 clamp(142px,31vw,210px);scroll-snap-align:start;padding:7px 9px}' +
        '#pl-root .pl-strip .k{font-size:10px}' +
        '#pl-root .pl-strip .v,#pl-root .pl-strip .cell.hero .v{font-size:17px}' +
        '#pl-root .pl-strip .s{font-size:12px;line-height:1.35}' +
        '#pl-root .pl-strip .s .pl-subq{font-size:10px}' +
        '#pl-root .pl-ttabs span{font-size:8px;padding:2px 4px}' +
        '#pl-root .pl-dash{display:flex;flex:0 0 auto;flex-direction:column;height:auto;min-height:0;gap:8px;' +
          'grid-template-rows:none;overflow:visible}' +
        '#pl-root .pl-zone{grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:300px;' +
          'height:auto;min-height:0;gap:8px;align-items:stretch}' +
        '#pl-root .pl-sec{height:300px;min-height:300px;padding:9px 10px;border-radius:8px;overflow:hidden}' +
        '#pl-root .pl-sec h4{font-size:13px;line-height:1.35;margin-bottom:7px;gap:5px;flex-wrap:wrap}' +
        '#pl-root .pl-sec h4 a,#pl-root .pl-sec-hint{font-size:10px}' +
        '#pl-root .pl-note{font-size:10px;line-height:1.5}' +
        '#pl-root .pl-loading,#pl-root .pl-empty{font-size:11px}' +
        '#pl-root .pl-score3{grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}' +
        '#pl-root .pl-score3 .sc.main{grid-column:1/-1}' +
        '#pl-root .pl-score3 .sc{padding:5px 7px}' +
        '#pl-root .pl-score3 .sc .k,#pl-root .pl-score3 .sc .k .w,#pl-root .pl-score3 .sc .l{font-size:9px}' +
        '#pl-root .pl-score3 .sc .v,#pl-root .pl-score3 .sc.main .v{font-size:17px}' +
        '#pl-root .pl-score-formula,#pl-root .pl-drivers,#pl-root .pl-drivers .box .k{font-size:10px}' +
        '#pl-root .pl-score-meta .m .k{font-size:9px}' +
        '#pl-root .pl-score-meta .m .v{font-size:12px}' +
        '#pl-root .pl-inst4,#pl-root .pl-bd4,#pl-root .pl-ohlc4{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}' +
        '#pl-root .pl-inst4 .c,#pl-root .pl-bd4 .c,#pl-root .pl-ohlc4 .c{padding:5px 4px}' +
        '#pl-root .pl-inst4 .c .k,#pl-root .pl-bd4 .c .k,#pl-root .pl-ohlc4 .c .k{font-size:10px}' +
        '#pl-root .pl-inst4 .c .v,#pl-root .pl-bd4 .c .v,#pl-root .pl-ohlc4 .c .v{font-size:13px;' +
          'overflow:hidden;text-overflow:ellipsis}' +
        '#pl-root .pl-inst-trend .lab,#pl-root .pl-bd-trend .lab,#pl-root .pl-ohlc-trend .lab{font-size:10px}' +
        '#pl-root .pl-inst-cmt,#pl-root .pl-bd-cmt,#pl-root .pl-ohlc-cmt{font-size:10px;line-height:1.45}' +
        '#pl-root .pl-sec-tog button{font-size:9px;padding:2px 5px}' +
        '#pl-root .pl-sbar{font-size:10px;line-height:1.35;padding:2px}' +
        '#pl-root .pl-sbar .nm{width:54px;font-size:10px}' +
        '#pl-root .pl-sbar .pc{width:46px;font-size:10px}' +
        '#pl-root .pl-sbar .ad{width:38px;font-size:8px}' +
        '#pl-root .pl-list li{font-size:10px;line-height:1.4;padding:3px 4px}' +
        '#pl-root .pl-list .nm,#pl-root .pl-movers .pl-list li>span:last-child{font-size:11px}' +
        '#pl-root .pl-list .cd{font-size:9px}' +
        '#pl-root .pl-movers .vz-rowbar,#pl-root .pl-movers .vz-chip{display:none!important}' +
        '#pl-root .pl-global .g{padding:5px 6px}' +
        '#pl-root .pl-global .g .k,#pl-root .pl-global .g .s{font-size:9px}' +
        '#pl-root .pl-global .g .v{font-size:11px}' +
        '#pl-root #pl-flash-sec .pl-sec-tog button,#pl-root #pl-watch-sec .pl-sec-tog button{font-size:8px;padding:2px 4px}' +
        '#pl-root #pl-flash-sec>h4,#pl-root #pl-watch-sec>h4{align-content:flex-start;white-space:normal;overflow:visible}' +
        '#pl-root #pl-flash-sec .pl-flash-tools{flex:1 0 100%;justify-content:flex-start}' +
        '#pl-root #pl-watch-sec .pl-sec-tog{margin-left:0}' +
        '#pl-root .pl-flash-q{width:58px;min-width:46px;max-width:72px;font-size:9px}' +
        '#pl-root .pl-flash{font-size:10px}' +
        '#pl-root .pl-flash .row{grid-template-columns:42px 50px minmax(0,1fr);gap:4px;padding:3px 4px}' +
        '#pl-root .pl-flash .t,#pl-root .pl-flash .cat{font-size:9px}' +
        '#pl-root .pl-flash .ttl{font-size:10px}' +
        '#pl-root .pl-wl table{font-size:10px}' +
        '#pl-root .pl-wl col.c-sym{width:35%}' +
        '#pl-root .pl-wl col.c-px{width:29%}' +
        '#pl-root .pl-wl col.c-chg{width:25%}' +
        '#pl-root .pl-wl col.c-tag,#pl-root .pl-wl td.tag{width:11%}' +
        '#pl-root .pl-wl th{font-size:9px}' +
        '#pl-root .pl-wl td.px,#pl-root .pl-wl td.chg,#pl-root .pl-wl td:first-child{font-size:10px}' +
        '#pl-root .pl-wl .nm-only,#pl-root .pl-wl .mkt{font-size:9px}' +
      '}' +
      '@media(max-width:520px) and (orientation:portrait){' +
        '#view-pulse.sv-panel.on{padding-left:5px;padding-right:5px}' +
        '#pl-root .pl-zone{gap:5px;grid-auto-rows:310px}' +
        '#pl-root .pl-sec{height:310px;min-height:310px;padding:7px 7px}' +
        '#pl-root .pl-sec h4{font-size:12px}' +
        '#pl-root .pl-sec h4 a,#pl-root .pl-sec-hint{font-size:9px}' +
        '#pl-root .pl-inst4 .c .v,#pl-root .pl-bd4 .c .v,#pl-root .pl-ohlc4 .c .v{font-size:12px}' +
        '#pl-root .pl-global{grid-template-columns:1fr}' +
      '}';
  }

  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function marketCls(p, market) {
    if (p == null || p !== p) return 'flat';
    if (market === 'US') return p > 0 ? 'us-up' : p < 0 ? 'us-down' : 'flat';
    return tw(p);
  }

  /** 盤面語氣／偏多空標籤 → 台股紅綠（非體質金／風險青） */
  function biasCls(label) {
    var t = String(label || '');
    if (!t || t === '—' || t.indexOf('彙整') >= 0 || t.indexOf('資料') >= 0) return 'pl-bias-mid';
    if (t.indexOf('偏多') >= 0 || t.indexOf('偏強') >= 0 || t.indexOf('極度偏多') >= 0 ||
        (t.indexOf('強') >= 0 && t.indexOf('弱') < 0)) return 'pl-bias-bull';
    if (t.indexOf('偏空') >= 0 || t.indexOf('偏弱') >= 0 || t.indexOf('極度偏空') >= 0 ||
        t.indexOf('弱') >= 0 || t.indexOf('風險') >= 0) return 'pl-bias-bear';
    if (t.indexOf('中性') >= 0 || t.indexOf('糾結') >= 0 || t.indexOf('觀察') >= 0) return 'pl-bias-mid';
    return 'pl-bias-mid';
  }
  function pct(p, d) {
    if (p == null || p !== p) return '—';
    d = d == null ? 2 : d;
    return (p >= 0 ? '+' : '') + Number(p).toFixed(d) + '%';
  }
  function fmt(v, d) {
    if (v == null || !isFinite(v)) return '—';
    d = d == null ? 0 : d;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  }
  /** 漲跌點數（帶正負號）；優先用 change，否則 price − prevClose */
  function chgPts(obj, d) {
    if (!obj) return null;
    var chg = obj.change;
    if (chg == null && obj.price != null && obj.prevClose != null &&
        isFinite(obj.price) && isFinite(obj.prevClose)) {
      chg = Number(obj.price) - Number(obj.prevClose);
    }
    if (chg == null || !isFinite(chg)) return null;
    d = d == null ? 2 : d;
    var n = Number(chg);
    var body = Math.abs(n).toLocaleString('en-US', {
      maximumFractionDigits: d, minimumFractionDigits: d
    });
    return (n > 0 ? '+' : n < 0 ? '-' : '') + body;
  }
  /** 「+170.79 · +0.38%」；點數與％皆無則 — */
  function chgWithPct(obj, ptDigits, pctDigits) {
    var pts = chgPts(obj, ptDigits);
    var p = obj && obj.changePct;
    if (pts == null && (p == null || p !== p)) return '—';
    if (pts == null) return pct(p, pctDigits);
    if (p == null || p !== p) return pts;
    return pts + ' · ' + pct(p, pctDigits);
  }
  function yi(v) {
    if (v == null || !isFinite(v)) return '—';
    // accept 元 or already 億 (heuristic: |v| > 1e5 → 元)
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (v < 0 && x > 0 ? '-' : '') + (v >= 0 && Math.abs(v) > 1e5 ? '' : (v >= 0 && x >= 0 && Math.abs(v) <= 1e5 && v !== x ? '' : '')) +
      (Math.abs(v) > 1e5 ? (v / 1e8) : v).toFixed(1).replace(/^-/, v < 0 ? '-' : '') + ' 億';
  }
  function normalizeYiValue(v) {
    if (v == null || !isFinite(Number(v))) return null;
    var x = Number(v);
    return Math.abs(x) > 1e5 ? x / 1e8 : x;
  }
  function formatYiCompact(v, signed) {
    var x = normalizeYiValue(v);
    if (x == null) return '—';
    var a = Math.abs(x);
    var text;
    if (a >= 10000) {
      text = (a / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 2, minimumFractionDigits: 1 }) + '兆';
    } else {
      var digits = a >= 1000 ? 0 : (a >= 10 ? 1 : 2);
      text = a.toLocaleString('zh-TW', { maximumFractionDigits: digits, minimumFractionDigits: digits }) + '億';
    }
    return (x < 0 ? '-' : (signed && x > 0 ? '+' : '')) + text;
  }
  function moneyYi(v) {
    return formatYiCompact(v, true).replace(/(億|兆)$/, ' $1');
  }
  /** tip 法人四格專用：省略「億」以免窄欄 ellipsis；完整值放 title */
  function moneyYiCell(v) {
    var x = normalizeYiValue(v);
    if (x == null) return '—';
    return (x >= 0 ? '+' : '') + x.toFixed(1);
  }
  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function goRoute(id, opts) {
    if (window.ShellV5) window.ShellV5.go(id, opts || {});
  }
  function routeTrace(event, row) {
    try {
      var body = Object.assign({ ts: new Date().toISOString(), event: event }, row || {});
      fetch(SRV + '/diagnostics/ui-route', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), keepalive: true
      }).catch(function () {});
    } catch (e) {}
  }
  function traceMarketColor(surface, symbol, market, value, appliedClass) {
    if (market !== 'US' || value == null || !isFinite(Number(value)) || Number(value) === 0) return;
    var expected = Number(value) > 0 ? 'green' : 'red';
    var key = [surface, symbol, Number(value) > 0 ? 'up' : 'down', appliedClass].join('|');
    if (marketColorTraceSeen[key]) return;
    marketColorTraceSeen[key] = true;
    routeTrace('market_color_render_observed', {
      correlationId: 'market-color-' + Date.now(), from: 'pulse', to: surface,
      state: Number(value) > 0 ? 'up' : 'down',
      label: 'surface=' + surface + ';symbol=' + symbol + ';market=US;value=' + value +
        ';appliedClass=' + appliedClass + ';expected=' + expected
    });
  }
  window.addEventListener('shell:route', function (ev) {
    var d = (ev && ev.detail) || {};
    var opts = d.opts || {};
    if (!opts._traceId) return;
    routeTrace('route_applied', {
      correlationId: opts._traceId, to: opts._traceTarget,
      renderedRoute: d.route, label: opts._traceLabel
    });
  });
  function openChart(code, mkt) {
    if (window.ShellV5 && ShellV5.openChart) {
      ShellV5.openChart(code || '^TWII', mkt || 'TW');
      return;
    }
    if (code && typeof loadSym === 'function') {
      loadSym(code, mkt || 'TW');
      goRoute('chart');
    }
  }

  function styleBand(score, adv) {
    if (window.WaveDeckBridge && typeof window.WaveDeckBridge.styleFromScore === 'function') {
      return window.WaveDeckBridge.styleFromScore(score, adv);
    }
    return null;
  }

  function setWdLine(text) {
    var el = $('pl-wd');
    if (el) el.innerHTML = text || 'WaveDeck 覆寫：—';
  }

  function maybeAnnounceFlip(m) {
    var band = styleBand(m.score, m.advRatio);
    if (band == null) return;
    if (_prevBand == null) { _prevBand = band; return; }
    if (_prevBand === band) return;
    var prev = _prevBand;
    _prevBand = band;
    var msg = '宏觀風格帶切換 ' + prev + ' → ' + band +
      (Number(m.score) < 35 ? '（建議降載）' : '');
    if (typeof window.notifyToast === 'function') {
      try { window.notifyToast(msg); } catch (e) {}
    }
    setWdLine('WaveDeck 覆寫：風格帶 <b>' + prev + '→' + band + '</b> · 推送中…');
  }

  function ruleFallbackSummary(m) {
    m = m || {};
    var bits = [];
    bits.push('【規則摘要｜本機 LLM 未連線】');
    if (m.score != null) bits.push('大盤體質 ' + m.score + (m.label ? '（' + m.label + '）' : '') + '。');
    if (m.advRatio != null && isFinite(Number(m.advRatio))) {
      var pctAdv = Math.round(Number(m.advRatio) * 100);
      bits.push('上漲家數比約 ' + pctAdv + '%。');
      if (pctAdv < 40) bits.push('廣度偏弱，宜降低侵略性、嚴控新單。');
      else if (pctAdv > 60) bits.push('廣度偏強，可維持偏積極但留意追價。');
      else bits.push('廣度糾結，宜均衡風格、等待結構確認。');
    }
    if (m.rotationHealth === 'broad') bits.push('類股輪動偏廣，風險偏好可略升。');
    if (m.rotationHealth === 'narrow') bits.push('類股輪動偏窄，提防指數上漲、個股跟不上。');
    if (m.breadthDivergence) {
      bits.push('⚠ 權值／廣度背離：' + m.breadthDivergence + '；總體分數偏強時仍不宜追高非主流中小型股。');
    }
    if (m.themeResonance) bits.push('自選池族群共振：' + m.themeResonance + '。');
    if (m.spilloverProb != null && isFinite(Number(m.spilloverProb))) {
      var sp = Math.round(Number(m.spilloverProb) * 100);
      bits.push('供應鏈／類股外溢機率約 ' + sp + '%。');
      if (sp < 35) bits.push('外溢偏低，動能不易擴散至多數族群。');
    }
    if (m.summary) bits.push(String(m.summary));
    var style = (window.WaveDeckBridge && window.WaveDeckBridge.styleFromScore)
      ? window.WaveDeckBridge.styleFromScore(m.score, m.advRatio, {
          rotationHealth: m.rotationHealth,
          spilloverProb: m.spilloverProb
        }) : null;
    if (style != null) bits.push('建議 WaveDeck 進場風格 → ' + style +
      (Number(m.score) < 35 || Number(m.spilloverProb) < 0.30 ? '（並考慮降載）' : '') + '。');
    bits.push('⚠ 非投資建議。');
    return bits.join(' ');
  }

  function beginnerFallbackSummary(m) {
    m = m || {};
    var adv = m.advRatio == null ? null : Math.round(Number(m.advRatio) * 10);
    var state;
    if (m.decisionRegime === 'NARROW_RALLY') {
      state = '指數偏強，但上漲集中在少數大型股票。';
    } else if (m.decisionRegime === 'BROAD_RISK_ON') {
      state = '指數和多數股票同步走強，市場結構相對健康。';
    } else if (m.decisionRegime === 'DEFENSIVE_RISK_OFF' || m.decisionRegime === 'CAPITULATION') {
      state = '賣壓與風險偏高，先保留現金比急著找買點重要。';
    } else {
      state = '多空訊號還沒有完全站在同一邊，方向容易反覆。';
    }
    if (adv != null && isFinite(adv)) state += ' 每 10 家約 ' + adv + ' 家上漲。';
    if (m.breadthDivergence) state += ' ' + m.breadthDivergence + '，較像少數權值股拉抬。';
    var strategy = m.decisionPosture ? beginnerAction(m.decisionPosture) : '先觀望，不追價加碼。';
    var turn = adv != null && adv < 5
      ? '上漲家數比回到 50% 以上才算結構改善；若再降到 30% 以下，應降低風險。'
      : '觀察上漲家數、大戶與成交量是否同步轉弱，再決定是否減碼。';
    return '📌 3 大要點速覽\n' +
      '1. 大盤狀態：' + state + '\n' +
      '2. 操作策略：' + strategy + '\n' +
      '3. 關鍵轉折：' + turn + '\n' +
      '⚠ 非投資建議。';
  }

  function syncAiSummaryControls() {
    var box = $('pl-ai');
    var topBtn = $('pl-ai-sum');
    var beginnerBtn = $('pl-beginner-ai');
    if (box) box.style.display = aiSummaryVisible ? 'block' : 'none';
    if (topBtn) {
      topBtn.textContent = aiSummaryVisible
        ? (pulseMode === 'beginner' ? '收起白話 AI' : '收起 AI 摘要')
        : (pulseMode === 'beginner' ? '白話 AI' : 'AI 摘要');
      topBtn.title = aiSummaryVisible
        ? '收起摘要；結果會保留，不需重新產生'
        : (pulseMode === 'beginner'
          ? '產生 30 秒可讀完的白話市場懶人包'
          : '本機 LLM 盤面摘要（/ai/local）');
      topBtn.setAttribute('aria-expanded', String(aiSummaryVisible));
    }
    if (beginnerBtn) {
      beginnerBtn.textContent = aiSummaryVisible ? '收起 30 秒白話 AI 懶人包' : '展開 30 秒白話 AI 懶人包';
      beginnerBtn.setAttribute('aria-expanded', String(aiSummaryVisible));
      beginnerBtn.title = aiSummaryVisible
        ? '收起摘要；結果會保留'
        : '產生 30 秒可讀完的白話市場懶人包';
    }
    var fastBtn = $('pl-ai-fast');
    var deepBtn = $('pl-ai-deep');
    if (fastBtn) {
      fastBtn.classList.toggle('on', aiSummaryMode === 'fast');
      fastBtn.disabled = aiSummaryInFlight;
      fastBtn.setAttribute('aria-pressed', String(aiSummaryMode === 'fast'));
    }
    if (deepBtn) {
      deepBtn.classList.toggle('on', aiSummaryMode === 'deep');
      deepBtn.disabled = aiSummaryInFlight;
      deepBtn.setAttribute('aria-pressed', String(aiSummaryMode === 'deep'));
    }
    var speakBtn = $('pl-ai-speak');
    if (speakBtn) {
      speakBtn.textContent = aiSpeechActive ? '■ 停止' : '🎙 約15秒朗讀';
      speakBtn.setAttribute('aria-pressed', String(aiSpeechActive));
    }
  }

  function stopAiSpeech() {
    try {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    } catch (e) {}
    aiSpeechActive = false;
    syncAiSummaryControls();
  }

  function toggleAiSpeech() {
    if (aiSpeechActive) {
      stopAiSpeech();
      return;
    }
    var body = $('pl-ai-body');
    var meta = $('pl-ai-meta');
    var text = body ? String(body.textContent || '').trim() : '';
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
      if (meta) meta.textContent = '此瀏覽器不支援語音朗讀';
      return;
    }
    if (!text || text.indexOf('思考中') === 0) {
      if (meta) meta.textContent = '摘要完成後即可朗讀';
      return;
    }
    var utterance = new SpeechSynthesisUtterance(text.slice(0, 120));
    utterance.lang = 'zh-TW';
    utterance.rate = 1.2;
    utterance.onend = utterance.onerror = function () {
      aiSpeechActive = false;
      syncAiSummaryControls();
    };
    aiSpeechActive = true;
    syncAiSummaryControls();
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  function setAiSummaryVisible(visible) {
    aiSummaryVisible = !!visible;
    if (!aiSummaryVisible) stopAiSpeech();
    syncAiSummaryControls();
  }

  function toggleAiSummary() {
    if (aiSummaryVisible) {
      setAiSummaryVisible(false);
      return;
    }
    if (aiSummaryStarted) {
      setAiSummaryVisible(true);
      return;
    }
    runAiSummary('fast');
  }

  function aiModeFallback(mode) {
    return mode === 'deep' ? {
      mode: 'deep', host: 'EVO-T1', provider: 'Hermes Agent → NVIDIA',
      model: 'nvidia/nemotron-3-super-120b-a12b', dataBoundary: 'external-provider',
      estimateSeconds: 720,
      estimateLabel: '請預留約 12 分鐘（含 Hermes 啟動、供應商連線、上下文預填與深度推理）'
    } : {
      mode: 'fast', host: 'EVO-T1', provider: 'LM Studio', model: 'google/gemma-4-e4b',
      dataBoundary: 'local-only', estimateSeconds: 300,
      estimateLabel: '請預留約 5 分鐘（含模型載入、上下文預填與推理）'
    };
  }

  function loadAiRuntimeStatus() {
    return fetch(SRV + '/ai/local/status', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('status ' + r.status);
      return r.json();
    }).then(function (d) {
      aiRuntimeStatus = d && d.modes ? d : null;
      return aiRuntimeStatus;
    }).catch(function () { return null; });
  }

  function aiRouteLabel(route) {
    if (!route) return 'EVO-T1';
    var provider = String(route.provider || 'AI runtime');
    var model = String(route.model || '未回報模型');
    var boundary = route.dataBoundary === 'local-only' ? '本機資料邊界' : '外部供應商資料邊界';
    return String(route.host || 'EVO-T1') + ' · ' + provider + ' · ' + model + ' · ' + boundary;
  }

  function formatAiDuration(ms) {
    var sec = Math.max(0, Math.round(Number(ms || 0) / 1000));
    if (sec < 60) return sec + ' 秒';
    return Math.floor(sec / 60) + ' 分 ' + (sec % 60) + ' 秒';
  }

  function stopAiWaitTicker() {
    if (aiSummaryWaitTimer) clearInterval(aiSummaryWaitTimer);
    aiSummaryWaitTimer = null;
  }

  function startAiWaitTicker(startedAt, route, meta) {
    stopAiWaitTicker();
    function tick() {
      if (!meta || !aiSummaryInFlight) return;
      meta.textContent = aiRouteLabel(route) + ' · 已等待 ' + formatAiDuration(Date.now() - startedAt) +
        ' · 仍可能在模型載入、上下文預填或推理；請勿重複送出';
    }
    tick();
    aiSummaryWaitTimer = setInterval(tick, 5000);
  }

  function headerRoute(response, fallback) {
    var h = response && response.headers;
    if (!h) return fallback;
    var seconds = Number(h.get('X-ST-AI-Estimate-Seconds'));
    return {
      mode: h.get('X-ST-AI-Mode') || fallback.mode,
      host: h.get('X-ST-AI-Host') || fallback.host,
      provider: h.get('X-ST-AI-Provider') || fallback.provider,
      model: h.get('X-ST-AI-Model') || fallback.model,
      dataBoundary: h.get('X-ST-AI-Data-Boundary') || fallback.dataBoundary,
      estimateSeconds: isFinite(seconds) && seconds > 0 ? seconds : fallback.estimateSeconds,
      requestId: h.get('X-ST-AI-Request-ID') || ''
    };
  }

  function friendlyAiError(status, text) {
    var message = String(text || '').trim();
    try {
      var parsed = JSON.parse(message);
      message = String(parsed.error || parsed.message || message);
    } catch (e) {}
    if (!message) message = 'HTTP ' + status;
    return message.replace(/HTTP\/1\.[01][\s\S]*/g, '連線在回應期間中斷').slice(0, 220);
  }

  function runAiSummary(mode) {
    var box = $('pl-ai');
    var body = $('pl-ai-body');
    var st = $('pl-ai-st');
    var meta = $('pl-ai-meta');
    if (!box || !body || aiSummaryInFlight) return;
    mode = mode === 'deep' ? 'deep' : 'fast';
    aiSummaryMode = mode;
    aiSummaryInFlight = true;
    aiSummaryStarted = true;
    setAiSummaryVisible(true);
    syncAiSummaryControls();

    var m = _lastMacro || {};
    var ctx = [
      '來源: Stock Terminal Pulse',
      '大盤體質分數: ' + (m.score != null ? m.score : '未提供'),
      '體質標籤: ' + (m.label || '未提供'),
      '上漲家數比 advRatio: ' + (m.advRatio != null ? m.advRatio : '未提供'),
      '輪動: ' + (m.rotationHealth || '未提供'),
      '供應鏈外溢機率: ' + (m.spilloverProb != null ? m.spilloverProb : '未提供'),
      '供應鏈最強段: ' + (m.hotStage || '未提供'),
      '鏈上廣度/相鄰同向: ' +
        (m.chainBreadth != null ? m.chainBreadth : '—') + ' / ' +
        (m.chainContig != null ? m.chainContig : '—'),
      '加權指數: ' + (m.twii != null ? m.twii : '未提供') +
        (m.twiiChg != null ? (' (' + m.twiiChg + '%)') : ''),
      '規則摘要: ' + (m.summary || '未提供'),
      '盤面語氣: ' + (m.tone || '未提供'),
      '權值與廣度背離: ' + (m.breadthDivergence || '未命中'),
      '自選族群共振: ' + (m.themeResonance || '未提供')
    ].join('\n');
    var fastPrompt = pulseMode === 'beginner'
      ? '請用繁體中文輸出固定 3 點、30 秒可讀完的白話摘要，標題依序是「1. 大盤狀態」「2. 操作策略」「3. 關鍵轉折」。' +
        '向完全不懂股票的人解釋，避免 Z-Score、ATR、advRatio 等術語；若要提廣度，改說「每 10 家約幾家上漲」。' +
        '不可編造未提供數字，不可保證獲利，結尾加「⚠ 非投資建議」。'
      : '請用 4–6 句繁中，根據「目前提供的資料」做台股大盤即時語意解析：' +
        '1) 多空傾向 2) 廣度與體質是否背離 3) 供應鏈外溢與風險提示 4) 對進場侵略性（保守/均衡/積極）的建議。' +
        '不可編造未提供的數字。結尾加「⚠ 非投資建議」。';
    var deepPrompt = '請以繁體中文提供一份嚴謹、可審核的台股市場深度分析。依序說明：' +
      '1) 最強支持證據 2) 最強反方證據 3) 指數、廣度、資金與期貨是否衝突 4) 可能失效條件 ' +
      '5) 仍無法從資料確認的不確定性。限 8–12 句，不得補造資料，不得執行交易或改動任何系統狀態；結尾加「⚠ 非投資建議」。';
    var fallbackRoute = aiModeFallback(mode);
    var startedAt = Date.now();
    var traceId = 'pulse-ai-' + startedAt.toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    var endpoint = mode === 'deep' ? '/ai/deep' : '/ai/local';
    var activeRoute = fallbackRoute;
    var waitText = mode === 'deep' ? 'Hermes 深度分析' : '快速摘要';

    return loadAiRuntimeStatus().then(function (runtime) {
      activeRoute = runtime && runtime.modes && runtime.modes[mode] ? runtime.modes[mode] : fallbackRoute;
      var estimate = activeRoute.estimateLabel || fallbackRoute.estimateLabel;
      body.textContent = 'EVO-T1 正在準備' + waitText + '。\n' + estimate +
        '。通常會提早完成；此時間已納入冷啟動與模型載入，請勿重複送出。';
      if (mode === 'deep') body.textContent += '\n注意：深度分析會由 EVO-T1 經 Hermes 將本面板市場摘要送至外部 NVIDIA 模型。';
      if (st) st.textContent = aiRouteLabel(activeRoute);
      startAiWaitTicker(startedAt, activeRoute, meta);
      return fetch(SRV + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-ST-Trace-ID': traceId },
        body: JSON.stringify({ prompt: mode === 'deep' ? deepPrompt : fastPrompt, context: ctx })
      });
    }).then(function (r) {
      activeRoute = headerRoute(r, activeRoute);
      if (st) st.textContent = aiRouteLabel(activeRoute);
      startAiWaitTicker(startedAt, activeRoute, meta);
      if (!r.ok) return r.text().then(function (t) { throw new Error(friendlyAiError(r.status, t)); });
      if (!r.body || !r.body.getReader) return r.text().then(function (t) {
        if (!t.trim()) throw new Error('AI 未回傳內容');
        body.textContent = t;
        return t;
      });
      var reader = r.body.getReader();
      var dec = new TextDecoder();
      var acc = '';
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) {
            acc += dec.decode();
            if (!acc.trim()) throw new Error('AI 未回傳內容');
            body.textContent = acc;
            return acc;
          }
          acc += dec.decode(res.value || new Uint8Array(), { stream: true });
          body.textContent = acc;
          return pump();
        });
      }
      return pump();
    }).then(function () {
      if (meta) meta.textContent = '完成於 ' + new Date().toLocaleTimeString('zh-TW') + ' · 實際耗時 ' +
        formatAiDuration(Date.now() - startedAt) + ' · ' + aiRouteLabel(activeRoute) +
        (activeRoute.requestId ? ' · request ' + activeRoute.requestId.slice(0, 12) : '');
    }).catch(function (err) {
      body.textContent = pulseMode === 'beginner' ? beginnerFallbackSummary(m) : ruleFallbackSummary(m);
      if (st) st.textContent = (mode === 'deep' ? 'Hermes 深度分析' : '快速摘要') + '未完成 · 規則後援';
      if (meta) meta.textContent = 'EVO-T1 AI 路徑未完成：' + String(err && err.message || '未知錯誤').slice(0, 220) +
        ' · 已保留可讀的規則摘要 · trace ' + traceId;
    }).then(function () {
      stopAiWaitTicker();
      aiSummaryInFlight = false;
      syncAiSummaryControls();
    });
  }

  function scStagesPayload() {
    try {
      var ch = (window.SC_CHAINS && window.SC_CHAINS.TW) || null;
      if (!ch || !ch.length) return null;
      return ch.map(function (g) {
        return {
          stage: g.stage,
          codes: (g.stocks || []).map(function (pair) { return pair[0]; })
        };
      });
    } catch (e) {
      return null;
    }
  }

  function enrichChainSpillover() {
    var stages = scStagesPayload();
    if (!stages || !window.WaveDeckBridge ||
        typeof window.WaveDeckBridge.spilloverFromChainStages !== 'function') {
      return Promise.resolve(null);
    }
    return fetch(SRV + '/chain-momentum', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stages: stages }),
      cache: 'no-store'
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !Array.isArray(d.stages) || !d.stages.length) return null;
        var chain = window.WaveDeckBridge.spilloverFromChainStages(d.stages);
        var sectorSpill = _lastMacro && _lastMacro.spilloverProb;
        var blended = (typeof window.WaveDeckBridge.blendSpillover === 'function')
          ? window.WaveDeckBridge.blendSpillover(sectorSpill, chain)
          : chain.prob;
        if (!_lastMacro) return chain;
        _lastMacro.spilloverProb = blended;
        _lastMacro.hotStage = chain.hotStage;
        _lastMacro.chainBreadth = chain.breadth;
        _lastMacro.chainContig = chain.contig;
        if (chain.leaders && chain.leaders.length) {
          _lastMacro.leaders = chain.leaders;
        }
        _lastMacro.chainStages = d.stages;
        setWdLine('WaveDeck 覆寫：供應鏈外溢 <b>' + Math.round(blended * 100) + '%</b>' +
          (chain.hotStage ? (' · 最強段 ' + chain.hotStage) : '') + ' · 推送中…');
        return pushWd(false).then(function () { return chain; });
      })
      .catch(function () { return null; });
  }

  function pushWd(force) {
    if (!window.WaveDeckBridge || typeof window.WaveDeckBridge.syncFromMarket !== 'function') {
      setWdLine('WaveDeck 覆寫：<b>橋接未載入</b>');
      return Promise.resolve();
    }
    var m = _lastMacro || {};
    var summary = m.summary || '';
    if (m.rotationHealth) {
      summary = (summary ? summary + ' · ' : '') + '輪動 ' + m.rotationHealth;
    }
    if (m.spilloverProb != null && isFinite(Number(m.spilloverProb))) {
      summary = (summary ? summary + ' · ' : '') +
        '外溢 ' + Math.round(Number(m.spilloverProb) * 100) + '%';
    }
    if (m.hotStage) {
      summary = (summary ? summary + ' · ' : '') + '最強段 ' + m.hotStage;
    }
    return window.WaveDeckBridge.syncFromMarket({
      score: m.score,
      advRatio: m.advRatio,
      label: m.label,
      summary: summary,
      rotationHealth: m.rotationHealth,
      spilloverProb: m.spilloverProb,
      leaders: m.leaders || [],
      hotStage: m.hotStage || null,
      chainBreadth: m.chainBreadth,
      chainContig: m.chainContig,
      sectors: m.sectors || null,
      twii: m.twii,
      twiiChg: m.twiiChg,
      decisionRegime: m.decisionRegime,
      decisionConfidence: m.decisionConfidence,
      decisionPosture: m.decisionPosture,
      decisionInvalidation: m.decisionInvalidation,
      source: 'pulse_v5',
      force: !!force,
      silent: !force
    }).then(function (res) {
      if (!res) return;
      if (res.skipped) {
        var last = window.WaveDeckBridge.lastSync && window.WaveDeckBridge.lastSync();
        if (last && last.payload) {
          var meta = (last.payload.meta) || {};
          setWdLine('WaveDeck 覆寫：風格 <b>' + last.payload.style + '</b>' +
            (last.payload.delever ? ' · 降載' : '') +
            (meta.spillover_prob != null ? (' · 外溢 ' + Math.round(meta.spillover_prob * 100) + '%') : '') +
            '（節流中）');
        } else {
          setWdLine('WaveDeck 覆寫：待命（' + (res.reason || 'skip') + '）');
        }
        return;
      }
      if (res.ok && res.payload) {
        var meta2 = res.payload.meta || {};
        setWdLine('WaveDeck 覆寫：風格 <b>' + res.payload.style + '</b>' +
          (res.payload.delever ? ' · <b>降載</b>' : '') +
          (meta2.spillover_prob != null ? (' · 外溢 ' + Math.round(meta2.spillover_prob * 100) + '%') : '') +
          ' · 已推送');
      } else if (res.ok === false) {
        setWdLine('WaveDeck 覆寫：<b>失敗</b>（' + (res.error || '—') + '）');
      }
    });
  }

  function buildMacroFromPack(pack) {
    var p = pack.pulse || {};
    var ov = p.overview || {};
    var strip = (ov && ov.strip) || {};
    var t00 = strip.t00 || {};
    var sectors = ((ov.sectorsRanked || []).filter(function (s) {
      return s && s.name && s.changePct != null;
    })).slice();
    sectors.sort(function (a, b) { return (b.changePct || 0) - (a.changePct || 0); });
    var up = sectors.filter(function (s) { return (s.changePct || 0) > 0; });
    var dn = sectors.filter(function (s) { return (s.changePct || 0) < 0; });
    var rot = 'mixed';
    if (up.length >= 4 && dn.length <= 2) rot = 'broad';
    else if (up.length <= 2 && dn.length >= 4) rot = 'narrow';
    var leaders = up.slice(0, 4).map(function (s) { return s.name || s.code || ''; }).filter(Boolean);
    var secPick = { up: up.slice(0, 6), dn: dn.slice(-6).reverse() };
    var spill = (window.WaveDeckBridge && typeof window.WaveDeckBridge.spilloverFromRotation === 'function')
      ? window.WaveDeckBridge.spilloverFromRotation(rot, secPick)
      : (rot === 'broad' ? 0.72 : rot === 'narrow' ? 0.30 : 0.50);
    var decision = p.decisionSummary || {};
    var breadthDetail = (decision.divergenceDetails || []).filter(function (d) {
      return d && d.id === 'INDEX_UP_BREADTH_DOWN';
    })[0] || null;
    var observed = (breadthDetail && breadthDetail.observed) || {};
    var streak = observed.indexStreak != null ? Number(observed.indexStreak) :
      ((strip.t00Trend || {}).streak != null ? Number((strip.t00Trend || {}).streak) : null);
    var breadthDivergence = breadthDetail ? [
      streak > 0 ? ('指數連漲 ' + Math.round(streak) + ' 日') : '指數偏強',
      observed.advancers != null && observed.decliners != null
        ? ('上漲 ' + Math.round(observed.advancers) + '／下跌 ' + Math.round(observed.decliners))
        : (strip.advRatio != null ? ('市場廣度 ' + Math.round(Number(strip.advRatio) * 100) + '%') : ''),
      observed.longShortRatio != null ? ('多空比 ' + Number(observed.longShortRatio).toFixed(2)) : ''
    ].filter(Boolean).join(' · ') : null;
    var themePack = buildWatchThemeResonance(readWatchlist(), pack.wlQuotes || {});
    var themeLead = (themePack.leaders || [])[0] || null;
    return {
      score: p.healthScore,
      advRatio: strip.advRatio,
      label: p.healthLabel || null,
      summary: p.plainSummary || p.summary || null,
      tone: p.tone || null,
      rotationHealth: rot,
      spilloverProb: spill,
      leaders: leaders,
      sectors: secPick,
      twii: (t00.price != null && isFinite(Number(t00.price))) ? Number(t00.price) : null,
      twiiChg: (t00.changePct != null && isFinite(Number(t00.changePct))) ? Number(t00.changePct) : null,
      breadthDivergence: breadthDivergence,
      breadthDivergenceDetail: breadthDetail,
      themeResonance: themeLead ? (themeLead.label + ' ' + themeLead.sameCount + '／' +
        themeLead.totalCount + ' 同向 · 熱度 ' + themeLead.score) : null,
      decisionRegime: (decision.regime || {}).id || null,
      decisionConfidence: (decision.regime || {}).confidence,
      decisionPosture: decision.posture || null,
      decisionInvalidation: (decision.invalidation || [])[0] || null,
      decisionContractVersion: decision.contractVersion || null,
      decisionModel: decision.model || null,
      decisionAsOf: decision.asOf || null
    };
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-pulse');
    if (!panel) {
      var views = $('shell-views');
      if (views) {
        panel = document.createElement('section');
        panel.className = 'sv-panel';
        panel.id = 'view-pulse';
        panel.dataset.route = 'pulse';
        views.appendChild(panel);
      }
    }
    if (!panel) return null;
    var mount = $('mount-pulse');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-pulse';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('pl-root')) {
      mount.innerHTML =
        '<div id="pl-root">' +
          '<div class="pl-head"><div>' +
            '<div class="pl-title">市場總覽 <span id="pl-layout-probe" style="font-size:10px;font-weight:700;letter-spacing:.03em;padding:1px 7px;border-radius:999px;border:1px solid rgba(34,211,238,.45);background:rgba(34,211,238,.12);color:#67e8f9;vertical-align:middle">實測…</span></div>' +
            '<span class="pl-wd" id="pl-wd">WaveDeck 覆寫：—</span>' +
            '<div class="pl-sub" id="pl-sub">官方資料 · 一行五框 × 上下兩區 · ' + LAYOUT_ANCHOR + '</div>' +
          '</div><div class="pl-actions">' +
            '<span class="pl-mode-toggle" role="group" aria-label="總覽顯示模式">' +
              '<button type="button" id="pl-view-beginner" title="只看市場狀態、行動提示與三個白話訊號">新手</button>' +
              '<button type="button" id="pl-view-expert" title="顯示完整 5+5 儀表板與原始數據">專業</button>' +
            '</span>' +
            '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
            '<button type="button" class="pl-btn wd" id="pl-push-wd" title="將廣度／體質推送到 WaveDeck">→ WD</button>' +
            '<button type="button" class="pl-btn wd" id="pl-ai-sum" title="本機 LLM 盤面摘要（/ai/local）">AI 摘要</button>' +
            '<button type="button" class="pl-btn" data-go="decision" title="開啟策略決策中心">決策</button>' +
            '<button type="button" class="pl-btn primary" data-go="chart">圖表</button>' +
          '</div></div>' +
          '<div class="pl-ai" id="pl-ai" style="display:none">' +
            '<h4><span>大盤 AI 即時語意 <span id="pl-ai-st" style="font-weight:600;color:var(--tlo)"></span></span>' +
              '<span class="pl-ai-tools"><button type="button" class="pl-ai-speak" id="pl-ai-speak" aria-pressed="false">🎙 約15秒朗讀</button>' +
              '<button type="button" class="pl-ai-close" id="pl-ai-close" aria-label="關閉 AI 白話懶人包">× 關閉</button></span></h4>' +
            '<div class="pl-ai-modebar" role="group" aria-label="AI 分析模式">' +
              '<button type="button" class="pl-ai-mode on" id="pl-ai-fast" aria-pressed="true">⚡ 快速摘要 · 本機</button>' +
              '<button type="button" class="pl-ai-mode deep" id="pl-ai-deep" aria-pressed="false">◆ Hermes 深度分析 · 外部</button>' +
              '<span class="pl-ai-runtime-note">所有工作由 EVO-T1 執行；手機只顯示結果</span>' +
            '</div>' +
            '<div class="pl-ai-body" id="pl-ai-body">—</div>' +
            '<div class="pl-ai-meta" id="pl-ai-meta"></div>' +
          '</div>' +
          '<div id="pl-body" class="pl-loading">載入總覽儀表板…</div>' +
        '</div>';
      var r = $('pl-refresh');
      if (r) r.onclick = function () { refresh(true); };
      var beginnerBtn = $('pl-view-beginner');
      var expertBtn = $('pl-view-expert');
      if (beginnerBtn) beginnerBtn.onclick = function () { setPulseMode('beginner'); };
      if (expertBtn) expertBtn.onclick = function () { setPulseMode('expert'); };
      var pwd = $('pl-push-wd');
      if (pwd) pwd.onclick = function () { pushWd(true); };
      var pai = $('pl-ai-sum');
      if (pai) pai.onclick = toggleAiSummary;
      var aiClose = $('pl-ai-close');
      if (aiClose) aiClose.onclick = function () { setAiSummaryVisible(false); };
      var aiSpeak = $('pl-ai-speak');
      if (aiSpeak) aiSpeak.onclick = toggleAiSpeech;
      var aiFast = $('pl-ai-fast');
      if (aiFast) aiFast.onclick = function () { runAiSummary('fast'); };
      var aiDeep = $('pl-ai-deep');
      if (aiDeep) aiDeep.onclick = function () { runAiSummary('deep'); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          goRoute(b.getAttribute('data-go'), {
            sym: b.getAttribute('data-sym') || undefined,
            mkt: b.getAttribute('data-mkt') || undefined
          });
        };
      });
      syncModeControls();
    }
    return $('pl-body');
  }

  function syncModeControls() {
    var root = $('pl-root');
    var beginnerBtn = $('pl-view-beginner');
    var expertBtn = $('pl-view-expert');
    if (root) root.classList.toggle('beginner-mode', pulseMode === 'beginner');
    if (beginnerBtn) beginnerBtn.classList.toggle('on', pulseMode === 'beginner');
    if (expertBtn) expertBtn.classList.toggle('on', pulseMode === 'expert');
    syncAiSummaryControls();
  }

  function setPulseMode(mode) {
    pulseMode = mode === 'expert' ? 'expert' : 'beginner';
    if (pulseMode === 'expert') {
      beginnerAdvanced = false;
      var stockResult = $('pl-stock-result');
      if (stockResult) stockResult.className = 'pl-stock-result';
    }
    try { localStorage.setItem('st_pulse_view_mode_v1', pulseMode); } catch (e) {}
    syncModeControls();
    if (lastPack) render(lastPack);
  }


  function scrollToFactors() {
    var el = $('pl-factors');
    if (!el) return false;
    try { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    catch (e) { el.scrollIntoView(true); }
    el.classList.remove('flash');
    // reflow so animation retriggers
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(function () { el.classList.remove('flash'); }, 1400);
    return true;
  }


  function factorCol(title, cls, list, empty) {
    var html = '<div class="pl-sec pl-col"><h4>' + title + ' <span style="color:var(--tlo);font-weight:600">(' + (list || []).length + ')</span></h4>';
    if (!list || !list.length) return html + '<div class="pl-note">' + empty + '</div></div>';
    list.forEach(function (f) {
      var sc = f.score;
      var scTxt = cls === 'sc-pend' ? '不計分' : (cls === 'sc-pos' ? ((sc >= 0 ? '+' : '') + Number(sc).toFixed(1) + '分') : (Number(sc).toFixed(1) + '分'));
      var typ = f.type || (cls === 'sc-risk' ? 'risk' : (cls === 'sc-pend' ? 'pending' : 'positive'));
      var more = '類型 ' + typ +
        (f.score != null ? ' · 權重分 ' + Number(f.score).toFixed(2) : '') +
        ' · 點列可展開／收合細節';
      html += '<div class="pl-fac" tabindex="0" role="button" data-fac="' +
        esc(f.id || '') + '"><div class="hd"><span>' + esc(f.id || '') + '. ' + esc(f.name || '') +
        '</span><span class="' + cls + '">' + esc(scTxt) + '</span></div>' +
        '<div class="ds">' + esc(f.description || '') + '</div>' +
        '<div class="more">' + esc(more) + '</div></div>';
    });
    return html + '</div>';
  }

  function readWatchlist() {
    try {
      var raw = localStorage.getItem('st_wl');
      var arr = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(arr)) return [];
      /* 內滾＋分頁後可多載；報價批次仍有上限 */
      return arr.filter(function (x) { return x && x.t; }).slice(0, 36);
    } catch (e) { return []; }
  }

  function watchIsUs(w) {
    return !!(w && (w.m === 'US' || w.mkt === 'US'));
  }

  function filterWatchlist(list) {
    var all = list || [];
    if (watchMkt === 'US') return all.filter(watchIsUs);
    if (watchMkt === 'TW') return all.filter(function (w) { return !watchIsUs(w); });
    return all;
  }

  function breadthToneLabel(adv, ls) {
    if (adv == null && ls == null) return '—';
    if ((ls != null && ls >= 3) || (adv != null && adv >= 0.75)) return '極度偏多';
    if ((ls != null && ls >= 1.8) || (adv != null && adv >= 0.60)) return '偏多擴張';
    if ((ls != null && ls <= 0.35) || (adv != null && adv <= 0.30)) return '極度偏空';
    if ((ls != null && ls <= 0.55) || (adv != null && adv <= 0.40)) return '偏空收縮';
    return '廣度糾結';
  }

  /* 與 server/trend_quant.py、turnover_quant.py、breadthToneLabel 對齊的完整型態表 */
  var IDX_TREND_TABS = [
    { id: '連漲趨升', kind: 'buy' },
    { id: '溫和上行', kind: 'buy' },
    { id: '單日急漲', kind: 'buy' },
    { id: '區間震盪', kind: 'mid' },
    { id: '單日急跌', kind: 'sell' },
    { id: '溫和下行', kind: 'sell' },
    { id: '連跌趨降', kind: 'sell' }
  ];
  var TURN_TREND_TABS = [
    { id: '放量趨升', kind: 'buy' },
    { id: '溫和放量', kind: 'buy' },
    { id: '單日放量', kind: 'buy' },
    { id: '量能持穩', kind: 'mid' },
    { id: '單日縮量', kind: 'sell' },
    { id: '溫和縮量', kind: 'sell' },
    { id: '明顯縮量', kind: 'sell' }
  ];
  var BREADTH_TREND_TABS = [
    { id: '極度偏多', kind: 'buy' },
    { id: '偏多擴張', kind: 'buy' },
    { id: '廣度糾結', kind: 'mid' },
    { id: '偏空收縮', kind: 'sell' },
    { id: '極度偏空', kind: 'sell' }
  ];

  /** 全型態 tab：當前 highlight（buy/sell/mid），其餘反灰 */
  function renderTrendTabs(active, catalog) {
    var cur = active && active !== '—' ? String(active) : '';
    var html = '<div class="pl-ttabs" title="市場趨勢判斷 · 當前：' + esc(cur || '尚無') + '">';
    (catalog || []).forEach(function (t) {
      var on = cur && t.id === cur;
      html += '<span class="' + (on ? ('on ' + (t.kind || 'mid')) : 'off') +
        '" title="' + esc(t.id) + (on ? '（當前）' : '') + '">' + esc(t.id) + '</span>';
    });
    return html + '</div>';
  }

  function factorNames(list, n) {
    return (list || []).slice(0, n || 3).map(function (f) { return f.name; }).filter(Boolean);
  }

  function beginnerAction(posture) {
    var map = {
      ALLOW_MEASURED_RISK: '可以分批觀察強勢標的，但不要一次押滿。',
      LIMIT_NEW_RISK: '可以續抱觀察，但先別追高或增加槓桿。',
      PROBE_WITH_CONFIRMATION: '若要嘗試，只宜小量並先設定停損。',
      WAIT_FOR_CONFIRMATION: '方向還不一致，先觀望、等待訊號同步。',
      DEFENSIVE: '優先降低高波動部位，保留更多現金。',
      PRESERVE_LIQUIDITY: '先保存現金，不要急著摸底或攤平。',
      NO_NEW_DIRECTION: '資料還不夠完整，暫時不要新增方向。'
    };
    return map[posture] || '先看市場結構是否一致，再決定是否增加風險。';
  }

  function beginnerWeather(regimeId, score, adv) {
    var map = {
      BROAD_RISK_ON: {
        icon: '▲', label: '廣泛多頭・結構健康', cls: 'calm',
        slogan: '指數和多數股票一起走強，市場結構相對健康。'
      },
      NARROW_RALLY: {
        icon: '◐', label: '指數偏強・結構分化', cls: 'watch',
        slogan: '市場拉高，但只有少數大股票在漲；手上股票未必會跟著漲。'
      },
      RECOVERY_ATTEMPT: {
        icon: '↗', label: '結構修復・等待確認', cls: 'watch',
        slogan: '市場正在回穩，但還需要更多股票一起轉強才能確認。'
      },
      CONFLICT: {
        icon: '⇄', label: '訊號分歧・方向未定', cls: 'watch',
        slogan: '不同訊號互相打架，方向不明確，今天宜多看少動。'
      },
      DEFENSIVE_RISK_OFF: {
        icon: '▽', label: '風險趨避・防禦優先', cls: 'alert',
        slogan: '賣壓與風險同時升高，先守住資金比急著找買點重要。'
      },
      CAPITULATION: {
        icon: '▼', label: '極端賣壓・等待止穩', cls: 'alert',
        slogan: '市場出現極端賣壓，超跌不代表立刻安全，先等止穩。'
      },
      INSUFFICIENT_DATA: {
        icon: '…', label: '資料不足・暫緩判斷', cls: 'unknown',
        slogan: '核心資料尚未完整，現在不適合只靠單一數字判斷方向。'
      }
    };
    if (map[regimeId]) return map[regimeId];
    if (score != null && score >= 65 && adv != null && adv >= 0.55) return map.BROAD_RISK_ON;
    if (score != null && score >= 60 && adv != null && adv < 0.45) return map.NARROW_RALLY;
    if (score != null && score < 40) return map.DEFENSIVE_RISK_OFF;
    return map.INSUFFICIENT_DATA;
  }

  function beginnerScoreBand(score) {
    if (score == null) return '等待資料';
    if (score < 30) return '偏空防禦';
    if (score < 60) return '震盪中性';
    if (score < 80) return '偏多穩健';
    return '高檔過熱';
  }

  function beginnerModel(ov, p) {
    var strip = (ov && ov.strip) || {};
    var summary = p.decisionSummary || {};
    var regime = summary.regime || {};
    var score = p.totalScore != null ? Number(p.totalScore) :
      (p.healthScore != null ? Number(p.healthScore) : null);
    if (score != null) score = Math.max(0, Math.min(100, score));
    var adv = strip.advRatio != null ? Number(strip.advRatio) :
      (p.stocks && p.stocks.advRatio != null ? Number(p.stocks.advRatio) : null);
    var inst = (ov && ov.institutional) || ((p.snapshot || {}).inst) || {};
    var instForeignYi = normalizeYiValue(inst.foreignYi != null ? inst.foreignYi : inst.foreign);
    var instTrustYi = normalizeYiValue(inst.trustYi != null ? inst.trustYi : inst.trust);
    var instDealerYi = normalizeYiValue(inst.dealerYi != null ? inst.dealerYi : inst.dealer);
    var instTotal = normalizeYiValue(inst.totalYi != null ? inst.totalYi : inst.total);
    if (instTotal == null && [instForeignYi, instTrustYi, instDealerYi].some(function (x) { return x != null; })) {
      instTotal = Number(instForeignYi || 0) + Number(instTrustYi || 0) + Number(instDealerYi || 0);
    }
    var volumeScore = strip.volumeScore == null ? null : Number(strip.volumeScore);
    var levels = summary.levels || {};
    var levelMeta = summary.keyLevelMeta || {};
    var levelQuality = levelMeta.quality || {};
    var staleFields = ((summary.dataQuality || {}).staleFields || []);
    var levelsStale = levelQuality.stale === true || staleFields.indexOf('keyLevels') >= 0;
    var volatility = summary.volatility || {};
    var expectedMovePct = levelsStale ? null : radarNumber(volatility.expectedOneDayPct);
    var current = strip.t00 && strip.t00.price != null ? Number(strip.t00.price) : null;
    var extras = p.extras || {};
    return {
      score: score,
      scoreBand: beginnerScoreBand(score),
      weather: beginnerWeather(regime.id, score, adv),
      advice: beginnerAction(summary.posture),
      confidence: regime.confidence == null ? null : Math.round(Number(regime.confidence) * 100),
      completeness: p.dataCompleteness == null ? null : Math.round(Number(p.dataCompleteness)),
      adv: adv,
      up: strip.up,
      down: strip.down,
      instTotal: instTotal == null ? null : Number(instTotal),
      instForeign: instForeignYi,
      instTrust: instTrustYi,
      instDealer: instDealerYi,
      volumeScore: volumeScore,
      turnoverYi: strip.turnoverYi,
      current: current,
      twChange: strip.t00 && strip.t00.changePct != null ? Number(strip.t00.changePct) : null,
      ceiling: levels.r1,
      floor: levels.s1,
      levelsStale: levelsStale,
      levelReferenceDate: levelMeta.referenceDate || null,
      levelSource: levelMeta.source || null,
      expectedMovePct: expectedMovePct,
      expectedMovePoints: expectedMovePct != null && current != null
        ? Math.abs(current) * expectedMovePct / 100 : null,
      divergences: summary.divergences || [],
      divergenceDetails: summary.divergenceDetails || [],
      indexStreak: strip.t00Trend && strip.t00Trend.streak != null ? Number(strip.t00Trend.streak) : null,
      txOi: extras.txOi || summary.flow || null
    };
  }

  function beginnerBreadth(model) {
    if (model.adv == null || !isFinite(model.adv)) {
      return {
        main: '等待廣度資料', plain: '尚無法判斷有多少股票一起上漲。', bar: 0,
        kind: 'breadth',
        metric: '漲跌比待資料',
        method: '計算：上漲家數 ÷（上漲＋下跌家數），觀察有多少股票一起上漲。'
      };
    }
    var n = Math.max(0, Math.min(10, Math.round(model.adv * 10)));
    var main = model.adv >= 0.60 ? '多數股票有跟上' :
      model.adv >= 0.45 ? '市場冷熱接近' : model.adv >= 0.30 ? '漲勢集中少數股票' : '多數股票偏弱';
    var counts = model.up != null && model.down != null
      ? '（上漲 ' + fmt(model.up) + '／下跌 ' + fmt(model.down) + '）' : '';
    return {
      main: main,
      plain: '每 10 家約 ' + n + ' 家上漲' + counts + '。',
      bar: model.adv * 100,
      kind: 'breadth',
      metric: '漲跌比 ' + Math.round(model.adv * 100) + '%',
      method: '計算：上漲家數 ÷（上漲＋下跌家數），觀察有多少股票一起上漲。'
    };
  }

  function beginnerMoney(model) {
    var value = model.instTotal;
    var parts = [
      { label: '外資', value: radarNumber(model.instForeign) },
      { label: '投信', value: radarNumber(model.instTrust) },
      { label: '自營', value: radarNumber(model.instDealer) }
    ];
    if (value == null || !isFinite(value)) {
      return {
        main: '等待法人資料', plain: '尚無三大法人買賣合計。', bar: 50,
        kind: 'money',
        metric: '法人力道待資料',
        method: '資料：證交所三大法人買賣超合計，包含外資、投信與自營商。',
        parts: parts
      };
    }
    var main = value >= 50 ? '大戶明顯買進' : value >= 10 ? '大戶偏向買進' :
      value <= -50 ? '大戶明顯賣出' : value <= -10 ? '大戶偏向賣出' : '大戶動向接近平衡';
    return {
      main: main,
      plain: '三大法人合計' + (value >= 0 ? '買超 ' : '賣超 ') + formatYiCompact(Math.abs(value), false) + '。',
      bar: Math.max(0, Math.min(100, 50 + value / 4)),
      kind: 'money',
      metric: '法人力道 ' + (value >= 0 ? '偏買' : '偏賣'),
      method: '資料：證交所三大法人買賣超合計，包含外資、投信與自營商。',
      parts: parts
    };
  }

  function beginnerVolume(model) {
    var value = model.volumeScore;
    if (value == null || !isFinite(value)) {
      return {
        main: '等待量能資料', plain: '成交量資料尚未形成。', bar: 0,
        kind: 'volume',
        metric: '量能待資料',
        method: '計算：成交金額相對近期量能的活躍程度，換算為 0–100 分。'
      };
    }
    var main = value >= 75 ? '買賣非常活躍' : value >= 60 ? '市場動能偏熱' :
      value >= 40 ? '市場動能平穩' : '市場動能偏弱';
    var turnover = model.turnoverYi == null ? '' : '，成交約 ' + Number(model.turnoverYi).toFixed(0) + ' 億';
    return {
      main: main,
      plain: '量能分數 ' + value.toFixed(0) + turnover + '。',
      bar: value,
      kind: 'volume',
      metric: '量能 ' + value.toFixed(0) + '／100',
      method: '計算：成交金額相對近期量能的活躍程度，換算為 0–100 分。'
    };
  }

  function beginnerMoneySplit(parts) {
    parts = (parts || []).map(function (part) {
      return { label: part.label, value: normalizeYiValue(part.value) };
    });
    var maxAbs = Math.max.apply(null, parts.map(function (part) {
      return part.value == null ? 0 : Math.abs(Number(part.value) || 0);
    }).concat([1]));
    return '<div class="pl-money-split" title="三大法人分項；紅買超、綠賣超">' + parts.map(function (part) {
      var value = part.value == null ? null : Number(part.value);
      var cls = value == null || value === 0 ? 'flat' : value > 0 ? 'pos' : 'neg';
      var label = value == null ? '—' : formatYiCompact(value, true);
      var width = value == null ? 0 : Math.max(4, Math.abs(value) / maxAbs * 100);
      return '<span><em>' + esc(part.label) + '</em><b class="' + cls + '">' + esc(label) +
        '</b><i><u style="width:' + width.toFixed(1) + '%"></u></i></span>';
    }).join('') + '</div>';
  }

  function beginnerSignal(icon, title, signal, tooltip, go, id) {
    var barValue = Math.max(0, Math.min(100, Number(signal.bar) || 0));
    var visual = signal.parts ? beginnerMoneySplit(signal.parts) :
      '<div class="bar-meta"><span>' + esc(signal.metric || '目前狀態') + '</span><span>冷 → 熱</span></div>' +
      '<div class="bar" style="--bar:' + barValue + '%"><i style="width:' + barValue + '%"></i></div>';
    return '<div class="pl-simple-card ' + esc(signal.kind || '') + '"' + (id ? ' id="' + esc(id) + '"' : '') +
      ' data-method-card role="button" tabindex="0" aria-expanded="false" title="點擊查看怎麼計算">' +
      '<div class="head"><span class="icon">' + icon + '</span><span class="pl-tip" title="' + esc(tooltip) + '">' +
      esc(title) + '</span><span class="method-hint">怎麼算？</span></div><div class="main">' + esc(signal.main) + '</div>' +
      '<div class="plain">' + esc(signal.plain) + '</div>' + visual +
      '<div class="pl-method-pop" hidden>' + esc(signal.method || tooltip) +
      (go ? '<a data-go="' + esc(go) + '">查看詳細 →</a>' : '') + '</div></div>';
  }

  function radarNumber(value) {
    return value == null || !isFinite(Number(value)) ? null : Number(value);
  }

  function radarClamp(value) {
    return Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  }

  function radarChangeText(value) {
    value = radarNumber(value);
    if (value == null) return '—';
    if (value > 0) return '▲ +' + value.toFixed(2) + '%';
    if (value < 0) return '▼ ' + value.toFixed(2) + '%';
    return '• 0.00%';
  }

  function radarChangeClass(value) {
    value = radarNumber(value);
    return value == null || value === 0 ? 'radar-flat' : value > 0 ? 'radar-pos' : 'radar-neg';
  }

  function radarGlobalQuote(p, symbols) {
    var rows = (p && p.global) || [];
    for (var i = 0; i < symbols.length; i++) {
      for (var j = 0; j < rows.length; j++) {
        if (rows[j] && rows[j].symbol === symbols[i]) return rows[j];
      }
    }
    return {};
  }

  function radarRisk(level, reason) {
    return {
      cls: level === 'high' ? 'high' : level === 'mid' ? 'mid' : 'low',
      label: level === 'high' ? '● 風險偏高' : level === 'mid' ? '● 風險中等' : '● 風險低',
      reason: reason
    };
  }

  function buildMarketRadar(ov, p) {
    var strip = (ov && ov.strip) || {};
    var twii = strip.t00 || {};
    var twChg = radarNumber(twii.changePct);
    var adv = radarNumber(strip.advRatio);
    var riskScore = radarNumber(p.riskScore);
    /* 台股熱度條直接對應漲跌家數比，避免與量能或指數漲幅混淆。 */
    var twHeat = radarClamp(adv == null ? 50 + (twChg || 0) * 9 : adv * 100);
    var twDiverged = twChg != null && twChg > 0.2 && adv != null && adv < 0.45;
    var twTrend = twDiverged ? '指數偏強、個股分化' :
      twChg != null && twChg >= 0.5 && adv != null && adv >= 0.55 ? '多數股票同步偏強' :
      twChg != null && twChg <= -0.5 && adv != null && adv < 0.45 ? '指數與個股同步偏弱' :
      twChg != null && twChg > 0.15 ? '溫和偏多' : twChg != null && twChg < -0.15 ? '溫和偏空' : '區間整理';
    var twRisk = (riskScore != null && riskScore >= 65) || (twChg != null && twChg <= -1.5)
      ? radarRisk('high', '風險分或跌幅已進入警戒區')
      : (riskScore != null && riskScore >= 40) || twDiverged
        ? radarRisk('mid', twDiverged ? '指數上漲但多數股票未跟上' : '風險訊號偏高')
        : radarRisk('low', '目前未見明顯結構性壓力');
    var twNote = twDiverged
      ? '大盤上漲不代表多數個股上漲，追高前先看自己的持股。'
      : adv == null ? '廣度資料尚未完整，暫以指數方向觀察。'
        : '每 10 家約 ' + Math.round(adv * 10) + ' 家上漲，方向與個股參與度一起判讀。';

    var spx = radarGlobalQuote(p, ['^GSPC']);
    var ndx = radarGlobalQuote(p, ['^IXIC']);
    var sox = radarGlobalQuote(p, ['^SOX']);
    var vix = radarGlobalQuote(p, ['^VIX']);
    var usChanges = [spx, ndx, sox].map(function (q) { return radarNumber(q.changePct); })
      .filter(function (x) { return x != null; });
    var usChg = usChanges.length
      ? usChanges.reduce(function (sum, x) { return sum + x; }, 0) / usChanges.length : null;
    var vixValue = radarNumber(vix.price);
    var usHeat = radarClamp(50 + (usChg || 0) * 12);
    var usTrend = usChg == null ? '等待美股資料' : usChg >= 0.7 ? '科技與大盤明顯偏強' :
      usChg >= 0.15 ? '美股溫和偏多' : usChg <= -0.7 ? '科技與大盤明顯偏弱' :
      usChg <= -0.15 ? '美股溫和偏空' : '美股多空拉鋸';
    var usRisk = (vixValue != null && vixValue >= 30) || (usChg != null && Math.abs(usChg) >= 2)
      ? radarRisk('high', 'VIX 或單日波動已進入高檔')
      : (vixValue != null && vixValue >= 20) || (usChg != null && Math.abs(usChg) >= 1)
        ? radarRisk('mid', '海外市場波動正在升高')
        : radarRisk('low', 'VIX 與主要指數波動仍在一般範圍');
    var usNote = usChg == null ? '尚無可比較的美股主要指數資料。' :
      '綜合觀察標普、那斯達克與費半' + (vixValue == null ? '。' : '；VIX 約 ' + vixValue.toFixed(1) + '。');

    var txf = p.txf || {};
    var futChg = radarNumber(txf.changePct);
    var basisPct = radarNumber(strip.basisPct);
    var ampRate = radarNumber(txf.ampRate);
    var futHeat = radarClamp(50 + (futChg || 0) * 12 + (basisPct || 0) * 8);
    var futTrend = futChg == null ? '等待期貨資料' : futChg >= 0.6 ? '期貨多方偏強' :
      futChg <= -0.6 ? '期貨空方偏強' : futChg > 0.15 ? '期貨溫和偏多' :
      futChg < -0.15 ? '期貨溫和偏空' : '期貨區間整理';
    var futRisk = (ampRate != null && ampRate >= 2) || (futChg != null && Math.abs(futChg) >= 2)
      ? radarRisk('high', '期貨振幅或漲跌已進入高波動區')
      : (ampRate != null && ampRate >= 1) || (basisPct != null && Math.abs(basisPct) >= 0.5)
        ? radarRisk('mid', '振幅或期現價差需要留意')
        : radarRisk('low', '目前振幅與期現價差相對溫和');
    var session = txf.sessionLabel || (txf.session === 'night' ? '夜盤' : txf.session === 'day' ? '日盤' : '最近盤');
    var txOi = ((p.extras || {}).txOi) || {};
    var oiValue = radarNumber(txOi.oi);
    var oiChgPct = radarNumber(txOi.oiChgPct);
    var futNote = '台指期' + session + (basisPct == null ? '' : '，期現價差 ' + (basisPct >= 0 ? '+' : '') + basisPct.toFixed(2) + '%') +
      (ampRate == null ? '。' : '，振幅 ' + ampRate.toFixed(2) + '%。') +
      (oiValue == null ? '' : ' 總 OI ' + fmt(oiValue, 0) + ' 口' +
        (oiChgPct == null ? '' : '（日變 ' + (oiChgPct > 0 ? '+' : '') + oiChgPct.toFixed(1) + '%）') + '，非外資淨部位。');

    return [
      { key: 'tw', icon: '🇹🇼', name: '台股市場', trend: twTrend, change: twChg, heat: twHeat,
        heatLabel: adv == null ? '參與熱度 ' + twHeat : '漲跌比 ' + Math.round(adv * 100) + '%',
        risk: twRisk, note: twNote, meta: '加權指數＋上市股票廣度 · TWSE', go: 'breadth' },
      { key: 'us', icon: '🇺🇸', name: '美股市場', trend: usTrend, change: usChg, heat: usHeat,
        heatLabel: '指數熱度 ' + usHeat,
        risk: usRisk, note: usNote, meta: 'SPX／NASDAQ／SOX 最新可得盤 · Yahoo', go: 'international' },
      { key: 'fut', icon: '◈', name: '期貨市場', trend: futTrend, change: futChg, heat: futHeat,
        heatLabel: '期貨熱度 ' + futHeat,
        risk: futRisk, note: futNote, meta: '台指期近月 ' + session + ' · TAIFEX MIS', go: 'afterhours' }
    ];
  }

  function renderMarketRadar(ov, p) {
    var rows = buildMarketRadar(ov, p);
    return '<section class="pl-market-radar"><div class="pl-market-radar-head"><h3>三市場趨勢雷達</h3>' +
      '<span>方向看漲跌色；風險只用藍／黃／橙</span></div><div class="pl-market-radar-grid">' +
      rows.map(function (row) {
        return '<div class="pl-radar-card ' + row.key + '" data-go="' + row.go + '" role="link" tabindex="0"' +
          ' title="點擊查看' + esc(row.name) + '詳細資料"><div class="pl-radar-top">' +
          '<div class="pl-radar-name"><span class="icon">' + row.icon + '</span>' + esc(row.name) + '</div>' +
          '<span class="pl-risk-pill ' + row.risk.cls + '" title="' + esc(row.risk.reason) + '">' + row.risk.label + '</span></div>' +
          '<div class="pl-radar-dir"><div class="trend">' + esc(row.trend) + '</div>' +
          '<div class="change ' + radarChangeClass(row.change) + '">' + radarChangeText(row.change) + '</div></div>' +
          '<div class="pl-radar-heat"><span title="0 代表偏冷，100 代表偏熱；不是漲跌幅">' + esc(row.heatLabel) +
          '</span><div class="track" title="熱度／參與程度 ' + row.heat + '／100"><i style="width:' + row.heat + '%"></i></div></div>' +
          '<div class="pl-radar-note">' + esc(row.note) + '</div><div class="pl-radar-meta">' + esc(row.meta) + '</div></div>';
      }).join('') + '</div></section>';
  }

  function beginnerGauge(score, band) {
    var value = score == null ? 0 : Math.max(0, Math.min(100, Number(score)));
    var angle = Math.PI - Math.PI * (value / 100);
    var markerX = 105 + 85 * Math.cos(angle);
    var markerY = 102 - 85 * Math.sin(angle);
    var marker = score == null ? '' :
      '<circle class="marker-halo" cx="' + markerX.toFixed(1) + '" cy="' + markerY.toFixed(1) + '" r="9"/>' +
      '<circle class="marker" cx="' + markerX.toFixed(1) + '" cy="' + markerY.toFixed(1) + '" r="5"><title>目前 ' +
        Math.round(value) + ' 分，' + esc(band) + '</title></circle>';
    return '<div class="pl-beginner-gauge" role="img" aria-label="市場情緒 ' +
      (score == null ? '等待資料' : Math.round(score) + ' 分，' + band) + '">' +
      '<svg viewBox="0 0 210 118" aria-hidden="true"><defs><linearGradient id="plBeginnerGauge" x1="0" y1="0" x2="1" y2="0">' +
      '<stop offset="0" stop-color="#64748b"/><stop offset=".28" stop-color="#38bdf8"/>' +
      '<stop offset=".32" stop-color="#4ade80"/><stop offset=".58" stop-color="#22c55e"/>' +
      '<stop offset=".62" stop-color="#facc15"/><stop offset=".78" stop-color="#fb923c"/>' +
      '<stop offset=".82" stop-color="#f87171"/><stop offset="1" stop-color="#ef4444"/>' +
      '</linearGradient></defs><path class="track" pathLength="100" d="M20 102 A85 85 0 0 1 190 102"/>' +
      '<path class="value" pathLength="100" stroke-dasharray="' + value.toFixed(1) + ' 100" d="M20 102 A85 85 0 0 1 190 102"/>' +
      marker + '</svg>' +
      '<div class="score">' + (score == null ? '—' : Math.round(score)) +
      '<small>市場情緒 · ' + esc(band) + '</small></div></div>';
  }

  function beginnerLevelDistance(current, level, kind) {
    current = radarNumber(current);
    level = radarNumber(level);
    if (current == null || level == null || current === 0) return '距離等待資料';
    var raw = level - current;
    var points = Math.abs(raw);
    var ratio = points / Math.abs(current) * 100;
    if (kind === 'ceiling') {
      return raw >= 0
        ? '距目前 +' + fmt(points, 0) + ' 點 · ' + ratio.toFixed(2) + '%'
        : '目前已突破 ' + fmt(points, 0) + ' 點';
    }
    return raw <= 0
      ? '距目前 -' + fmt(points, 0) + ' 點 · ' + ratio.toFixed(2) + '%'
      : '目前已跌破 ' + fmt(points, 0) + ' 點';
  }

  function traceBeginnerBoundaries(model) {
    var current = radarNumber(model && model.current);
    var ceiling = radarNumber(model && model.ceiling);
    var floor = radarNumber(model && model.floor);
    var state = current == null || ceiling == null || floor == null ? 'incomplete' :
      current > ceiling ? 'above_ceiling' : current < floor ? 'below_floor' : 'inside_boundaries';
    var signature = [current, ceiling, floor, state, model && model.levelsStale ? 'stale' : 'fresh'].join('|');
    if (signature === lastBoundaryTraceSignature) return;
    lastBoundaryTraceSignature = signature;
    routeTrace('boundary_formula_observed', {
      correlationId: 'beginner-boundary-' + Date.now(),
      from: 'pulse', to: 'beginner_boundary', state: state,
      current: current, ceiling: ceiling, floor: floor,
      currentSource: 'overview.strip.t00.price',
      levelsSource: 'decisionSummary.levels.r1/s1',
      label: 'current=' + current + ';r1=' + ceiling + ';s1=' + floor + ';state=' + state
    });
  }

  function beginnerDivergence(model) {
    var change = radarNumber(model && model.twChange);
    var adv = radarNumber(model && model.adv);
    if (change == null || adv == null) return null;
    var detail = (model.divergenceDetails || []).filter(function (d) {
      return d && d.id === 'INDEX_UP_BREADTH_DOWN';
    })[0] || null;
    var observed = (detail && detail.observed) || {};
    var expectedAdv = Math.max(0.15, Math.min(0.85, 0.5 + change / 4));
    var conflict = (change > 0.2 && adv < 0.45) || (change < -0.2 && adv > 0.55) ||
      ((model.divergences || []).indexOf('INDEX_UP_BREADTH_DOWN') >= 0) || !!detail;
    var score = detail && detail.confidence != null
      ? Math.round(Number(detail.confidence) * 100)
      : radarClamp(Math.abs(expectedAdv - adv) * 200 + (conflict ? 20 : 0));
    if (!conflict && score < 45) return null;
    var counts = observed.advancers != null && observed.decliners != null
      ? '上漲 ' + Math.round(observed.advancers) + '／下跌 ' + Math.round(observed.decliners) : '';
    var ratio = observed.longShortRatio != null ? '多空比 ' + Number(observed.longShortRatio).toFixed(2) : '';
    var streak = observed.indexStreak > 0 ? '指數連漲 ' + Math.round(observed.indexStreak) + ' 日' : '';
    var evidenceLine = [streak, counts, ratio].filter(Boolean).join(' · ') ||
      ('指數偏強，但市場廣度僅 ' + Math.round(adv * 100) + '%');
    return {
      score: score,
      label: '權值／廣度背離',
      text: change > 0 && adv < 0.5
        ? (evidenceLine + '；偏向拉權值，非主流中小型股不宜追高。')
        : '指數方向與多數股票不同步，先降低追價速度。',
      formula: detail
        ? 'DecisionContext：同時檢查指數漲跌、連漲日數、上市股票上漲占比與漲跌家數。'
        : '以指數漲跌推估合理上漲家數比，再與實際漲跌比比較；方向相反時加重警示。'
    };
  }

  function renderBeginnerAdvanced(ov, p) {
    var strip = (ov && ov.strip) || {};
    var sectors = sectorsFromPack(ov).slice(0, 29);
    var globalRows = (p.global || []).slice(0, 5);
    var flash = (p.flash || []).slice(0, 4);
    var txOi = ((p.extras || {}).txOi) || {};
    var indices = [
      ['加權', strip.t00], ['櫃買', strip.o00], ['台指期', p.txf]
    ];
    return '<div class="pl-beginner-advanced"' + (beginnerAdvanced ? '' : ' hidden') + '>' +
      '<div class="pl-advanced-grid">' +
      '<div class="pl-advanced-card"><h3>📈 指數／期貨結構 <a data-go="afterhours">完整籌碼 →</a></h3>' + indices.map(function (row) {
        var q = row[1] || {};
        return '<div class="row"><span>' + row[0] + '</span><b>' + fmt(q.price, 0) + ' · ' + pct(q.changePct) + '</b></div>';
      }).join('') +
        '<div class="row"><span>期現價差</span><b>' + (strip.basisPct == null ? '—' : pct(strip.basisPct)) + '</b></div>' +
        '<div class="row"><span>近月總 OI（非外資）</span><b>' + (txOi.oi == null ? '—' : fmt(txOi.oi, 0) + ' 口') + '</b></div></div>' +
      '<div class="pl-advanced-card"><h3>🧱 ' + sectors.length + ' 類產業輪動 <a data-go="heat">完整熱圖 →</a></h3>' + (sectors.length ? sectors.map(function (row) {
        return '<div class="row"><span>' + esc(row.name || '—') + '</span><b>' + pct(row.changePct) + '</b></div>';
      }).join('') : '<div class="row"><span>資料載入中</span><b>—</b></div>') + '</div>' +
      '<div class="pl-advanced-card"><h3>🌍 全球焦點</h3>' + (globalRows.length ? globalRows.map(function (row) {
        return '<div class="row"><span>' + esc(globalAbbr(row)) + '</span><b>' + pct(row.changePct) + '</b></div>';
      }).join('') : '<div class="row"><span>資料載入中</span><b>—</b></div>') + '</div>' +
      '<div class="pl-advanced-card"><h3>📰 今日焦點</h3>' + (flash.length ? flash.map(function (row) {
        return '<div class="row"><span title="' + esc(row.title || '') + '">' + esc(row.title || '—') + '</span><b>' +
          esc(({ HIGH: '高影響', MEDIUM: '中影響', LOW: '一般' })[((row.impact || {}).tier)] || row.mkt || '—') + '</b></div>';
      }).join('') : '<div class="row"><span>尚無快訊</span><b>—</b></div>') + '</div>' +
      '</div></div>';
  }

  function renderBeginner(ov, p) {
    var model = beginnerModel(ov, p);
    traceBeginnerBoundaries(model);
    var breadth = beginnerBreadth(model);
    var money = beginnerMoney(model);
    var volume = beginnerVolume(model);
    var weather = model.weather;
    var divergence = beginnerDivergence(model);
    var levelReference = model.levelReferenceDate ? ' · 參考日 ' + model.levelReferenceDate : '';
    var staleDistance = '資料已過期' + levelReference + '，勿作今日停損依據';
    var expectedMove = model.expectedMovePoints == null ? '' :
      '<div class="pl-vol-envelope" title="由歷史實現波動估算，不保證落在區間內">統計波動參考 ±' +
        fmt(model.expectedMovePoints, 0) + ' 點</div>';
    var quality = '信心 ' + (model.confidence == null ? '—' : model.confidence + '%') +
      ' · 資料完整度 ' + (model.completeness == null ? '—' : model.completeness + '%') +
      ' · 僅供理解市場環境，非買賣指令';
    return '<div class="pl-beginner">' +
      '<section class="pl-beginner-hero weather-' + weather.cls + '">' + beginnerGauge(model.score, model.scoreBand) +
        '<div class="pl-beginner-copy"><div class="pl-weather ' + weather.cls + '"><span>' + weather.icon + '</span>' +
          esc(weather.label) + '</div><h2>' + esc(weather.slogan) + '</h2>' +
          (divergence ? '<div class="pl-divergence-warning" title="' + esc(divergence.formula) + '"><b>⚠ ' + esc(divergence.label || '結構背離') + ' ' +
            divergence.score + '／100</b><span>' + esc(divergence.text) + '</span></div>' : '') +
          '<p class="advice">今天怎麼做：' + esc(model.advice) + '</p>' +
          '<p class="why">先看「有多少股票一起漲」、大戶是否持續買進，以及成交量是否支持行情；三者一致時，方向才比較可靠。</p>' +
          '<div class="pl-hero-foot"><div class="quality">' + esc(quality) + '</div>' +
            '<form class="pl-stock-check" id="pl-stock-check"><input id="pl-stock-code" inputmode="text" autocomplete="off" ' +
              'maxlength="8" aria-label="輸入持股代號" placeholder="持股代號，如 2330">' +
              '<button type="submit">個股健診</button></form></div></div>' +
      '</section>' +
      '<div class="pl-stock-result" id="pl-stock-result" role="status" aria-live="polite">' +
        '<div><b id="pl-stock-result-title">個股健診</b><span id="pl-stock-result-body">輸入代號後顯示相對大盤表現。</span>' +
          '<small id="pl-stock-result-meta"></small></div>' +
        '<button type="button" id="pl-stock-open" hidden>開啟圖表</button>' +
        '<button type="button" id="pl-stock-close" aria-label="關閉個股健診">× 關閉</button></div>' +
      '<div class="pl-simple-signals">' +
        beginnerSignal('⚖', '市場熱度', breadth, '廣度：有多少股票一起上漲', 'breadth') +
        beginnerSignal('💰', '大戶動向', money, '大戶：三大法人買賣合計', 'institutional', 'pl-beginner-money') +
        beginnerSignal('🔋', '動能氣氛', volume, '動能：市場成交量是否活躍', 'afterhours') +
      '</div>' +
      renderMarketRadar(ov, p) +
      '<div class="pl-safe-box" title="' + esc(model.levelsStale ? staleDistance : '依前一交易日高低收計算；不是保證價位') + '">' +
        '<div class="pl-safe-level ceiling' + (model.levelsStale ? ' stale' : '') + '"><div class="k pl-tip" title="壓力：上方容易遇到賣壓">☁ ' +
          (model.levelsStale ? '歷史壓力參考' : '今日上方天花板') + '</div>' +
          '<div class="v">' + fmt(model.ceiling, 0) + '</div><div class="distance">' +
            esc(model.levelsStale ? staleDistance : beginnerLevelDistance(model.current, model.ceiling, 'ceiling')) + '</div>' +
          '<div class="s">' + (model.levelsStale ? '更新日線後才可重新作為操作關卡' : '拉高到這裡較容易遇到阻力') + '</div></div>' +
        '<div class="pl-safe-level floor' + (model.levelsStale ? ' stale' : '') + '"><div class="k pl-tip" title="支撐：下方可能出現承接">▰ ' +
          (model.levelsStale ? '歷史支撐參考' : '今日下方地板') + '</div>' +
          '<div class="v">' + fmt(model.floor, 0) + '</div><div class="distance">' +
            esc(model.levelsStale ? staleDistance : beginnerLevelDistance(model.current, model.floor, 'floor')) + '</div>' +
          '<div class="s">' + (model.levelsStale ? '舊資料僅供回顧，不代表今日支撐' : '回落到這裡可能出現承接，跌破仍需控管風險') + '</div></div>' +
        '<div class="pl-beginner-actions">' +
          expectedMove +
          '<button type="button" class="pl-btn" id="pl-beginner-advanced" aria-expanded="' + beginnerAdvanced + '">' +
            (beginnerAdvanced ? '收合進階觀察' : '展開進階觀察') + '</button>' +
          '<button type="button" class="pl-btn wd" id="pl-beginner-ai" aria-expanded="' + aiSummaryVisible + '">' +
            (aiSummaryVisible ? '收起 30 秒白話 AI 懶人包' : '展開 30 秒白話 AI 懶人包') + '</button>' +
          '<button type="button" class="pl-btn" id="pl-enter-expert">查看專業參數</button>' +
        '</div></div>' +
      renderBeginnerAdvanced(ov, p) + '</div>';
  }

  function stockHealthAssessment(q, model) {
    var price = radarNumber(q && q.price);
    var prev = radarNumber(q && q.prevClose);
    var marketChange = radarNumber(model && model.twChange);
    if (price == null || prev == null || prev === 0) return null;
    var change = (price - prev) / prev * 100;
    var relative = marketChange == null ? null : change - marketChange;
    var cls = relative != null && relative >= 0.6 && change > 0 ? 'strong' :
      relative != null && relative <= -0.6 ? 'weak' : 'neutral';
    var regime = ((_lastMacro || {}).decisionRegime || '');
    var message;
    if (cls === 'strong') {
      message = regime === 'NARROW_RALLY'
        ? '分化盤中明顯強於大盤，較可能屬於撐盤／主導型股票；仍不宜追高。'
        : '目前相對大盤偏強，可續看量價是否維持。';
    } else if (cls === 'weak') {
      message = regime === 'NARROW_RALLY'
        ? '大盤由少數權值股支撐，但這檔明顯落後；反彈時宜優先檢查風險。'
        : '目前相對大盤偏弱，先觀察是否止跌再增加部位。';
    } else {
      message = '表現接近大盤，暫未形成明顯相對強弱優勢。';
    }
    var quoteName = String(q.name || '').trim();
    var titleName = quoteName && quoteName !== String(q.code || '') ? ' ' + quoteName : '';
    return {
      cls: cls,
      title: String(q.code || '') + titleName + ' · ' +
        (change >= 0 ? '▲ +' : '▼ ') + change.toFixed(2) + '%',
      body: message + (relative == null ? '' : ' 相對大盤 ' + (relative >= 0 ? '+' : '') + relative.toFixed(2) + '%。'),
      meta: '現價 ' + fmt(price, price >= 1000 ? 1 : 2) + ' · ' + String(q.source || '市場報價') +
        (q.time ? ' · ' + q.time : '')
    };
  }

  function stockHealthFallbackQuote(code, controller, traceId, started) {
    routeTrace('stock_health_fallback_start', {
      correlationId: traceId, from: 'pulse', to: '/quote', state: 'mis_unavailable', label: code
    });
    return fetch(SRV + '/quote/' + encodeURIComponent(code + '.TW'), {
      cache: 'no-store', signal: controller ? controller.signal : undefined
    }).then(function (r) {
      routeTrace('stock_health_fallback_response', {
        correlationId: traceId, state: String(r.status), elapsedMs: Date.now() - started, label: code
      });
      if (!r.ok) throw new Error('fallback_http_' + r.status);
      return r.json();
    }).then(function (q) {
      if (!q || q.price == null || q.prevClose == null) throw new Error('fallback_quote_unavailable');
      return {
        ok: true, code: code, name: q.name || '',
        price: q.price, prevClose: q.prevClose,
        open: q.open, high: q.high, low: q.low, volume: q.volume,
        time: q.lastBarTime ? new Date(Number(q.lastBarTime) * 1000).toLocaleTimeString('zh-TW', { hour12: false }) : '',
        source: (q.source || 'Yahoo') + ' · MIS盤後備援'
      };
    });
  }

  function bindStockHealth() {
    var form = $('pl-stock-check');
    var input = $('pl-stock-code');
    var result = $('pl-stock-result');
    var title = $('pl-stock-result-title');
    var body = $('pl-stock-result-body');
    var meta = $('pl-stock-result-meta');
    var open = $('pl-stock-open');
    var close = $('pl-stock-close');
    if (!form || !input || !result || !title || !body || !meta || !open) return;
    if (close) close.onclick = function () { result.className = 'pl-stock-result'; };
    form.onsubmit = function (e) {
      e.preventDefault();
      var code = String(input.value || '').trim().toUpperCase();
      var traceId = 'stock-health-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);
      routeTrace('stock_health_command_received', { correlationId: traceId, from: 'pulse', to: 'twquote', label: code });
      result.className = 'pl-stock-result on';
      open.hidden = true;
      if (!/^[0-9A-Z]{4,8}$/.test(code)) {
        title.textContent = '代號格式不正確';
        body.textContent = '請輸入 4–8 碼台股代號，例如 2330 或 00631L。';
        meta.textContent = '';
        routeTrace('stock_health_terminal_failure', { correlationId: traceId, state: 'invalid_code', label: code });
        return;
      }
      setAiSummaryVisible(false);
      title.textContent = code + ' · 健診中…';
      body.textContent = '正在讀取證交所／櫃買即時報價並與目前大盤環境比較。';
      meta.textContent = '';
      routeTrace('stock_health_command_acknowledged', { correlationId: traceId, state: 'loading', label: code });
      routeTrace('stock_health_request_start', { correlationId: traceId, from: 'pulse', to: '/twquote', label: code });
      var started = Date.now();
      var controller = window.AbortController ? new AbortController() : null;
      var timeout = setTimeout(function () { if (controller) controller.abort(); }, 8000);
      fetch(SRV + '/twquote?code=' + encodeURIComponent(code), {
        cache: 'no-store', signal: controller ? controller.signal : undefined
      }).then(function (r) {
        routeTrace('stock_health_response', {
          correlationId: traceId, state: String(r.status), elapsedMs: Date.now() - started, label: code
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }).then(function (q) {
        if (q && q.ok !== false && q.price != null && q.prevClose != null) return q;
        return stockHealthFallbackQuote(code, controller, traceId, started);
      }).then(function (q) {
        var pack = (lastPack || {}).pulse || {};
        var assessment = stockHealthAssessment(q, beginnerModel(pack.overview || {}, pack));
        if (!q || q.ok === false || !assessment) throw new Error('quote_unavailable');
        result.className = 'pl-stock-result on ' + assessment.cls;
        title.textContent = assessment.title;
        body.textContent = assessment.body;
        meta.textContent = assessment.meta + ' · 僅為相對強弱觀察，非買賣指令';
        open.hidden = false;
        open.onclick = function () { openChart(code, 'TW'); };
        routeTrace('stock_health_terminal_success', {
          correlationId: traceId, state: assessment.cls, elapsedMs: Date.now() - started, label: code
        });
      }).catch(function (err) {
        result.className = 'pl-stock-result on';
        title.textContent = code + ' · 暫時無法健診';
        body.textContent = err && err.name === 'AbortError' ? '報價查詢逾時，請稍後重試。' : '目前找不到可用即時報價。';
        meta.textContent = '未使用推測價格';
        routeTrace('stock_health_terminal_failure', {
          correlationId: traceId, state: String(err && err.name || 'error'), elapsedMs: Date.now() - started, label: code
        });
      }).then(function () { clearTimeout(timeout); });
    };
  }

  function bindBeginner() {
    var advancedBtn = $('pl-beginner-advanced');
    var aiBtn = $('pl-beginner-ai');
    var expertBtn = $('pl-enter-expert');
    document.querySelectorAll('#pl-body [data-method-card]').forEach(function (card) {
      var pop = card.querySelector('.pl-method-pop');
      function toggleMethod(e) {
        if (e && e.target && e.target.closest && e.target.closest('[data-go]')) return;
        var opening = pop && pop.hidden;
        document.querySelectorAll('#pl-body .pl-method-pop').forEach(function (other) {
          other.hidden = true;
          if (other.parentElement) other.parentElement.setAttribute('aria-expanded', 'false');
        });
        if (pop && opening) {
          pop.hidden = false;
          card.setAttribute('aria-expanded', 'true');
        }
      }
      card.onclick = toggleMethod;
      card.onkeydown = function (e) {
        if (e.target !== card || (e.key !== 'Enter' && e.key !== ' ')) return;
        e.preventDefault();
        toggleMethod(e);
      };
    });
    if (advancedBtn) advancedBtn.onclick = function () {
      beginnerAdvanced = !beginnerAdvanced;
      if (lastPack) render(lastPack);
    };
    if (aiBtn) aiBtn.onclick = toggleAiSummary;
    if (expertBtn) expertBtn.onclick = function () { setPulseMode('expert'); };
    bindStockHealth();
    syncAiSummaryControls();
  }

  function fillBeginnerInstitutional(ov, p) {
    var current = beginnerModel(ov, p);
    if (current.instTotal != null && isFinite(current.instTotal)) return;
    jget('/pulse/history?kind=institutional&n=1').then(function (history) {
      if (pulseMode !== 'beginner') return;
      var row = history && history.rows && history.rows[0];
      var card = $('pl-beginner-money');
      if (!row || !card) return;
      var total = row.totalYi != null ? Number(row.totalYi) :
        (row.total != null ? Number(row.total) / 1e8 : null);
      if (total == null || !isFinite(total)) return;
      var signal = beginnerMoney({
        instTotal: total,
        instForeign: row.foreignYi != null ? Number(row.foreignYi) : Number(row.foreign || 0) / 1e8,
        instTrust: row.trustYi != null ? Number(row.trustYi) : Number(row.trust || 0) / 1e8,
        instDealer: row.dealerYi != null ? Number(row.dealerYi) : Number(row.dealer || 0) / 1e8
      });
      signal.plain = '最近法人日 ' + String(row.date || '—') + '：' + signal.plain;
      var main = card.querySelector('.main');
      var plain = card.querySelector('.plain');
      var metric = card.querySelector('.bar-meta span');
      var bar = card.querySelector('.bar i');
      var split = card.querySelector('.pl-money-split');
      if (main) main.textContent = signal.main;
      if (plain) plain.textContent = signal.plain;
      if (metric) metric.textContent = signal.metric;
      if (bar) bar.style.width = Math.max(0, Math.min(100, Number(signal.bar) || 0)) + '%';
      if (split) split.outerHTML = beginnerMoneySplit(signal.parts);
      card.title = '大戶：最近已公布的三大法人買賣合計（非即時）';
    });
  }

  function sparkSvg(closes) {
    if (!closes || closes.length < 2) {
      return '<div class="pl-note" style="padding:4px 0">近 20 日走勢尚在累積（同步資料後顯示）</div>';
    }
    var V = window.Viz;
    if (V && V.sparkLine) {
      return V.sparkLine(closes, {
        color: closes[closes.length - 1] >= closes[0] ? 'var(--red)' : 'var(--green)',
        h: 48, w: 220, compact: true,
        xUnit: '日', yUnit: '點', yDigits: 0
      });
    }
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = (hi - lo) || 1;
    var w = 280, h = 64, pad = 2;
    var pts = closes.map(function (c, i) {
      var x = pad + (i / (closes.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (c - lo) / span) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    var up = closes[closes.length - 1] >= closes[0];
    var col = up ? 'var(--red)' : 'var(--green)';
    var yBase = (h - pad).toFixed(1);
    var area = pad.toFixed(1) + ',' + yBase + ' ' + pts + ' ' + (w - pad).toFixed(1) + ',' + yBase;
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polygon fill="' + col + '" fill-opacity="0.18" points="' + area + '"/>' +
      '<polyline fill="none" stroke="' + col +
      '" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round" points="' + pts + '"/></svg>';
  }

  /** 價格／指數趨勢量化列（與成交金額量能同構；完整列放 title，畫面只顯主線） */
  function trendQuantBits(tr, streakUpLabel, streakDnLabel) {
    tr = tr || {};
    var bits = [];
    if (tr.chgPct != null) bits.push(pct(tr.chgPct) + '日');
    if (tr.vsMa5Pct != null) bits.push(pct(tr.vsMa5Pct) + 'vs5');
    if (tr.momScore != null) bits.push('分' + Number(tr.momScore).toFixed(0));
    if (tr.z20 != null) bits.push('Z' + Number(tr.z20).toFixed(1));
    if (tr.streak) {
      bits.push('日線' + (tr.streak > 0 ? (streakUpLabel || '連漲') : (streakDnLabel || '連跌')) +
        Math.abs(tr.streak));
    }
    return bits.length ? bits.join(' · ') : '';
  }

  /** 頂列可見主線：漲跌幅／連漲跌；Z／分／vs5 降頻為次要灰字（完整列亦在 title） */
  function trendPrimarySub(tr, streakUpLabel, streakDnLabel) {
    tr = tr || {};
    var main = [];
    if (tr.chgPct != null) main.push(pct(tr.chgPct));
    if (tr.streak) {
      main.push('日線' + (tr.streak > 0 ? (streakUpLabel || '連漲') : (streakDnLabel || '連跌')) +
        Math.abs(tr.streak));
    }
    var soft = [];
    if (tr.vsMa5Pct != null) soft.push(pct(tr.vsMa5Pct) + 'vs5');
    if (tr.momScore != null) soft.push('分' + Number(tr.momScore).toFixed(0));
    if (tr.z20 != null) soft.push('Z' + Number(tr.z20).toFixed(1));
    var html = main.join(' · ');
    if (soft.length) {
      html += (html ? ' ' : '') + '<span class="pl-subq">' + soft.join(' · ') + '</span>';
    }
    return html;
  }

  function renderTrendCell(opts) {
    var V = window.Viz;
    var tr = opts.trend || {};
    var tone = tr.trend || '';
    var tabs = renderTrendTabs(tone, opts.tabs || IDX_TREND_TABS);
    /* 動能分水位：與成交金額同一套 vz-ref（全寬軌道＋刻度），刻度 40／60、上限 100 */
    var meter = '';
    if (V && V.refMeter && tr.momScore != null && isFinite(Number(tr.momScore))) {
      meter = V.refMeter(Number(tr.momScore), [40, 60], {
        max: 100,
        tickFmt: function (t) { return '分' + t; },
        title: '動能分 ' + Number(tr.momScore).toFixed(0) + '／100（刻度 40／60）'
      });
    }
    var fullBits = trendQuantBits(tr, opts.streakUpLabel, opts.streakDnLabel);
    var subHtml = trendPrimarySub(tr, opts.streakUpLabel, opts.streakDnLabel);
    if (!subHtml && opts.fallbackSub) subHtml = opts.fallbackSub;
    if (!subHtml) subHtml = '—';
    var tip = (opts.tip || '即時漲跌＝同卡官方報價；日線量化＝vs5日均／動能分／近20日Z／連續漲跌') +
      (tone ? (' · 當前 ' + tone) : '') +
      (fullBits ? (' · ' + fullBits) : '');
    var levelHtml = tr.level
      ? ' <span style="font-size:9px;color:#94a3b8;font-weight:700">' + esc(tr.level) + '</span>'
      : '';
    var toneCls = tw(tr.chgPct != null ? tr.chgPct : tr.vsMa5Pct);
    /* 頂列不再畫 spark；水位 bar 與成交金額 refMeter 同構 */
    var nav = opts.go
      ? ' data-go="' + esc(opts.go) + '"' +
        (opts.sym ? ' data-sym="' + esc(opts.sym) + '"' : '') +
        (opts.mkt ? ' data-mkt="' + esc(opts.mkt) + '"' : '') +
        ' role="link" tabindex="0" style="cursor:pointer"'
      : '';
    return '<div class="cell' + (opts.hero ? ' hero' : '') + '"' + nav + ' title="' + esc(tip) + '">' +
      '<div class="k">' + opts.k + '</div>' +
      '<div class="v">' + opts.vHtml + levelHtml + '</div>' +
      '<div class="s ' + toneCls + '">' + subHtml + '</div>' +
      tabs + meter + '</div>';
  }

  function renderStrip(ov, p) {
    var V = window.Viz;
    var s = (ov && ov.strip) || {};
    var t00 = s.t00 || {};
    var o00 = s.o00 || {};
    var txf = p.txf || {};
    var t00Tr = s.t00Trend || {};
    var o00Tr = s.o00Trend || {};
    var txfTr = s.txfTrend || {};
    var adv = s.advRatio;
    var tone = breadthToneLabel(adv, s.lsRatio);
    /* 6 格：指數×3 + 量能 + 家數／廣度合併 + 官方漲跌停（中排 donut 負責結構細節） */
    var turnTone = s.turnoverTrend || '';
    var turnTabs = renderTrendTabs(turnTone, TURN_TREND_TABS);
    var turnMeter = (V && s.turnoverYi != null) ? V.refMeter(s.turnoverYi, [8000, 12000]) : '';
    var turnBits = [];
    if (s.turnoverChgPct != null) turnBits.push(pct(s.turnoverChgPct) + '日');
    if (s.turnoverVsMa5Pct != null) turnBits.push(pct(s.turnoverVsMa5Pct) + 'vs5');
    if (s.volumeScore != null) turnBits.push('分' + Number(s.volumeScore).toFixed(0));
    if (s.turnoverZ20 != null) turnBits.push('Z' + Number(s.turnoverZ20).toFixed(1));
    if (s.turnoverStreak) {
      turnBits.push((s.turnoverStreak > 0 ? '連放' : '連縮') + Math.abs(s.turnoverStreak));
    }
    var turnMain = [];
    if (s.turnoverChgPct != null) turnMain.push(pct(s.turnoverChgPct));
    if (s.turnoverStreak) {
      turnMain.push((s.turnoverStreak > 0 ? '連放' : '連縮') + Math.abs(s.turnoverStreak));
    }
    var turnSoft = [];
    if (s.turnoverVsMa5Pct != null) turnSoft.push(pct(s.turnoverVsMa5Pct) + 'vs5');
    if (s.volumeScore != null) turnSoft.push('分' + Number(s.volumeScore).toFixed(0));
    if (s.turnoverZ20 != null) turnSoft.push('Z' + Number(s.turnoverZ20).toFixed(1));
    var turnSub = turnMain.join(' · ') || (turnBits.length ? turnBits.join(' · ') : '—');
    if (turnSoft.length) {
      turnSub += (turnMain.length ? ' ' : '') +
        '<span class="pl-subq">' + turnSoft.join(' · ') + '</span>';
    }
    var turnTip = '量能量化：vs前日／vs5日均／量能分(8000億=50)／近20日Z／連續放縮；水位 8000／12000 億' +
      (turnTone ? (' · 當前 ' + turnTone) : '') +
      (turnBits.length ? (' · ' + turnBits.join(' · ')) : '');
    var advTabs = renderTrendTabs(tone, BREADTH_TREND_TABS);
    var txfSess = txf.sessionLabel || (txf.session === 'night' ? '夜盤' : (txf.session === 'day' ? '日盤' : ''));
    var idxTip = '趨勢量化：vs前日／vs5日均／動能分／近20日Z／連續漲跌（與成交金額量能同構）';
    var t00Fb = chgWithPct(t00, 2, 2);
    var o00Fb = chgWithPct(o00, 2, 2);
    /* Basis＝台指期 − 加權（點）；優先用後端 strip.basisPts／basisPct */
    var basisPts = s.basisPts;
    var basisPct = s.basisPct;
    if (basisPts == null && txf.price != null && t00.price != null && isFinite(txf.price) && isFinite(t00.price)) {
      basisPts = Math.round((Number(txf.price) - Number(t00.price)) * 100) / 100;
      if (Number(t00.price) > 0) {
        basisPct = Math.round((basisPts / Number(t00.price)) * 100000) / 1000;
      }
    }
    var basisBits = [];
    if (basisPts != null && isFinite(basisPts)) {
      basisBits.push((basisPts >= 0 ? '正價差 +' : '逆價差 ') + Number(basisPts).toFixed(1) + '點');
      if (basisPct != null && isFinite(basisPct)) {
        basisBits.push((basisPct >= 0 ? '+' : '') + Number(basisPct).toFixed(3) + '%');
      }
    }
    var txfFb = chgWithPct(txf, 0, 2) +
      (txf.ampRate != null ? ' · 振幅 ' + Number(txf.ampRate).toFixed(2) + '%' : '') +
      (basisBits.length ? ' · ' + basisBits.join(' ') : '');
    var bdSub = [];
    if (s.lsRatio != null) bdSub.push('多空 ' + s.lsRatio.toFixed(2));
    if (adv != null) bdSub.push('廣度 ' + (adv * 100).toFixed(1) + '%');
    bdSub.push(tone);
    var txfSrc = txf.source || '';
    var txfName = txf.name || '台指期近月';
    var txfTip = '即時報價＝TAIFEX MIS 台指期近月' +
      (txfSess ? ('（' + txfSess + '）') : '') +
      (txfSrc ? (' · source ' + txfSrc) : '') +
      '｜趨勢量化＝FinMind 近月連續（代號 __TXF__，日線）覆寫最新點為當前報價｜' +
      'Basis＝期貨−加權現貨（盤後＝夜盤期貨−加權最新／昨收）｜顯示名：' + txfName;
    return '<div class="pl-strip">' +
      renderTrendCell({
        k: '加權指數 TAIEX', hero: true,
        vHtml: fmt(t00.price, 2),
        trend: t00Tr, fallbackSub: t00Fb, tip: idxTip + ' · 加權',
        go: 'chart', sym: '^TWII', mkt: 'TW'
      }) +
      renderTrendCell({
        k: '櫃買指數 OTC',
        vHtml: fmt(o00.price, 2),
        trend: o00Tr, fallbackSub: o00Fb, tip: idxTip + ' · 櫃買',
        go: 'chart', sym: '^TWOII', mkt: 'TW'
      }) +
      renderTrendCell({
        k: '台指期近月' + (txfSess ? ' · ' + txfSess : '') +
          (basisPts != null && isFinite(basisPts)
            ? (' · Basis ' + (basisPts >= 0 ? '+' : '') + Number(basisPts).toFixed(1))
            : ''),
        hero: true,
        vHtml: fmt(txf.price, 0),
        trend: txfTr, fallbackSub: txfFb, tip: txfTip,
        go: 'afterhours', mkt: 'TW'
      }) +
      '<div class="cell hero" data-go="afterhours" role="link" tabindex="0" style="cursor:pointer" title="' + turnTip + '"><div class="k">成交金額 · 量能</div><div class="v">' +
        (s.turnoverYi != null ? Number(s.turnoverYi).toFixed(1) + ' 億' : '—') +
        (s.turnoverLevel ? ' <span style="font-size:9px;color:#94a3b8;font-weight:700">' + esc(s.turnoverLevel) + '</span>' : '') +
        '</div>' +
        '<div class="s ' + tw(s.turnoverVsMa5Pct != null ? s.turnoverVsMa5Pct : s.turnoverChgPct) + '">' +
          turnSub + '</div>' + turnTabs + turnMeter + '</div>' +
      '<div class="cell" data-go="breadth" title="上市上漲／下跌／平盤家數＋廣度占比／多空比（詳情見中排廣度窗）· 當前 ' +
        esc(tone) + '" style="cursor:pointer">' +
        '<div class="k">漲跌家數 · 廣度</div><div class="v" style="font-size:12px">' +
        '<span class="up">' + fmt(s.up) + '</span> / <span class="dn">' + fmt(s.down) + '</span> / <span class="flat">' +
        fmt(s.flat) + '</span></div>' +
        '<div class="s pl-st-mid">' + bdSub.join(' · ') + '</div>' + advTabs + '</div>' +
      '<div class="cell" data-go="breadth" title="證交所 MI_INDEX「股票」欄：上漲／下跌括號內＝官方漲停／跌停家數（上市普通股）。與下方「近漲停」清單家數不同（清單為 ≥9.9% 近似、不含櫃買／ETF）。點擊開廣度詳情。" style="cursor:pointer">' +
        '<div class="k">上市漲跌停 · 官方</div>' +
        '<div class="v" style="font-size:12px">' +
          '<span class="up">漲停 ' + fmt(s.limitUp) + '</span>' +
          '<span style="color:#94a3b8;font-weight:600"> · </span>' +
          '<span class="dn">跌停 ' + fmt(s.limitDown) + '</span></div>' +
        '<div class="s pl-st-mid">證交所括號' +
          (p.date ? ' · ' + esc(String(p.date)) : '') +
          ' · 詳情 →</div></div>' +
      '</div>';
  }

  function renderGauge(p) {
    var V = window.Viz;
    var total = p.totalScore;
    var health = p.healthScore;
    var risk = p.riskScore;
    var comp = p.dataCompleteness != null ? p.dataCompleteness : 0;
    var drivers = factorNames(p.positiveFactors, 3);
    var pressures = factorNames(p.riskFactors, 3);
    var totalMeter = V ? V.scoreMeter(total) : '';
    var healthMeter = V ? V.scoreMeter(health) : '';
    var riskMeter = V ? V.scoreMeter(risk, { color: 'var(--cyan)' }) : '';
    /* 母分綜合＝0.7×大盤體質＋0.3×(100−風險)；子項並列但視覺降級 */
    var formulaBits = '綜合=<b>70%</b>×體質+<b>30%</b>×(100−風險)';
    if (health != null && risk != null && total != null) {
      var chk = 0.7 * Number(health) + 0.3 * (100 - Number(risk));
      formulaBits += ' → <b>' + chk.toFixed(1) + '</b>';
    }
    return '<div class="pl-sec" data-pri="p0"><h4>市場脈動 <a data-go="factors">因子 →</a></h4>' +
      '<div class="pl-score3">' +
        '<div class="sc main" title="綜合脈動（母分）＝0.7×大盤體質＋0.3×(100−風險)">' +
          '<div class="k"><span>綜合</span></div>' +
          '<div class="v">' + (total != null ? Number(total).toFixed(1) : '—') + '</div>' +
          '<div class="l pos">' + esc(p.statusText || '—') + '</div>' +
          (totalMeter ? '<div class="meter">' + totalMeter + '</div>' : '') +
        '</div>' +
        '<div class="sc child" title="大盤體質子項（量能＋法人＋融資＋估值），權重 70%">' +
          '<div class="k"><span>大盤體質</span><span class="w">70%</span></div>' +
          '<div class="v">' + (health != null ? Number(health).toFixed(1) : '—') + '</div>' +
          '<div class="l pos">' + esc(p.healthLabel || '—') + '</div>' +
          (healthMeter ? '<div class="meter">' + healthMeter + '</div>' : '') +
        '</div>' +
        '<div class="sc child" title="風險因子軟封頂（越高越警戒）；綜合取 30%×(100−風險)">' +
          '<div class="k"><span>風險</span><span class="w">30%</span></div>' +
          '<div class="v">' + (risk != null ? Number(risk).toFixed(1) : '—') + '</div>' +
          '<div class="l risk">' + esc(p.riskLabel || '—') + '</div>' +
          (riskMeter ? '<div class="meter">' + riskMeter + '</div>' : '') +
        '</div>' +
      '</div>' +
      '<div class="pl-score-formula" title="與 /pulse 後端算式一致">' + formulaBits + '</div>' +
      '<div class="pl-score-meta">' +
        '<div class="m"><div class="k">正面因子合計</div><div class="v pl-st-pos">' +
          (p.positiveFactorScore != null ? Number(p.positiveFactorScore).toFixed(1) : '—') +
          '<span class="pl-st-mid" style="font-size:8px;font-weight:600"> · ' +
            ((p.positiveFactors || []).length) + ' 項</span></div></div>' +
        '<div class="m"><div class="k">資料可靠度</div><div class="v">' + Number(comp).toFixed(0) + '%' +
          '<span class="pl-st-mid" style="font-size:8px;font-weight:600"> · ' +
            (p.datasetsOk || 0) + '/' + (p.datasetsTotal || 0) + '</span></div>' +
          '<div class="pl-comp"><i style="width:' + comp + '%"></i></div></div>' +
      '</div>' +
      '<div class="pl-drivers">' +
        '<div class="box"><div class="k">正面因子 <span>· 支撐訊號</span></div><ul>' +
          (drivers.length ? drivers.map(function (n) { return '<li>· ' + esc(n) + '</li>'; }).join('') : '<li class="pl-st-mid">—</li>') +
        '</ul></div>' +
        '<div class="box"><div class="k">風險因子 <span>· 計入風險分</span></div><ul>' +
          (pressures.length ? pressures.map(function (n) { return '<li>· ' + esc(n) + '</li>'; }).join('') : '<li class="pl-st-mid">—</li>') +
        '</ul></div></div>' +
      '</div>';
  }

  /** 加權盤勢評論：日內位置／漲跌／振幅（不重複四格 OHLC 數字；點數整數、％一位） */
  function buildOhlcComment(o, twiiObj, ampPct, rangePos) {
    var parts = [];
    if (rangePos != null) {
      var band = rangePos >= 0.67 ? '偏高位' : rangePos <= 0.33 ? '偏低位' : '中段';
      parts.push('日內 <b>' + band + '</b>（' + (rangePos * 100).toFixed(0) + '%）');
    }
    parts.push('<span class="' + tw(o && o.changePct) + '">' + chgWithPct(twiiObj, 0, 1) + '</span>');
    if (ampPct != null) parts.push('振幅 ' + ampPct.toFixed(1) + '%');
    if (!parts.length) parts.push('走勢資料載入中');
    return parts.join(' · ');
  }

  /** 加權盤勢：結構對齊法人資金（上四格 OHLC → 中線圖 → 底評論） */
  function renderOhlc(ov, p) {
    var o = (ov && ov.ohlc) || {};
    var strip = (ov && ov.strip) || {};
    var t00Tr = strip.t00Trend || {};
    var twiiObj = {
      price: o.price, prevClose: o.prevClose, changePct: o.changePct,
      change: (o.price != null && o.prevClose != null) ? (o.price - o.prevClose) : null
    };
    var ampPct = null;
    if (o.high != null && o.low != null && o.prevClose && isFinite(o.prevClose) && o.prevClose !== 0) {
      ampPct = (Number(o.high) - Number(o.low)) / Number(o.prevClose) * 100;
    }
    var rangePos = null;
    if (o.high != null && o.low != null && o.price != null &&
        isFinite(o.high) && isFinite(o.low) && Number(o.high) > Number(o.low)) {
      rangePos = (Number(o.price) - Number(o.low)) / (Number(o.high) - Number(o.low));
      rangePos = Math.max(0, Math.min(1, rangePos));
    }
    var sparkBoot = '';
    if (t00Tr.spark && t00Tr.spark.length >= 2) {
      sparkBoot = sparkSvg(t00Tr.spark);
    } else {
      sparkBoot = '<div class="pl-note" style="padding:4px 0">載入近 20 日走勢…</div>';
    }
    var metaBoot = t00Tr.spark && t00Tr.spark.length
      ? ('加權 · 近 ' + t00Tr.spark.length + ' 日 · Y：點')
      : '載入…';
    return '<div class="pl-sec" data-pri="p0"><h4>加權盤勢' +
      '<a data-go="chart" data-sym="^TWII" data-mkt="TW">圖表 →</a></h4>' +
      '<div class="pl-ohlc4" id="pl-ohlc4">' +
        '<div class="c" title="當日開盤（整數點）"><div class="k">開盤</div><div class="v">' + fmt(o.open, 0) + '</div></div>' +
        '<div class="c" title="當日最高（整數點）"><div class="k">最高</div><div class="v">' + fmt(o.high, 0) + '</div></div>' +
        '<div class="c" title="當日最低（整數點）"><div class="k">最低</div><div class="v">' + fmt(o.low, 0) + '</div></div>' +
        '<div class="c" title="昨收（整數點）"><div class="k">昨收</div><div class="v">' + fmt(o.prevClose, 0) + '</div></div>' +
      '</div>' +
      '<div class="pl-ohlc-trend" id="pl-ohlc-trend">' +
        '<div class="lab"><span>加權 ^TWII · 近 20 日</span><span id="pl-ohlc-trend-meta">' + metaBoot + '</span></div>' +
        '<div class="chart" id="pl-ohlc-chart">' + sparkBoot + '</div>' +
      '</div>' +
      '<div class="pl-ohlc-cmt" id="pl-ohlc-cmt">' + buildOhlcComment(o, twiiObj, ampPct, rangePos) + '</div></div>';
  }

  function yiNum(v) {
    if (v == null || !isFinite(v)) return null;
    /* 已是億則原樣；否則當元轉億 */
    return Math.abs(v) >= 1e6 ? v / 1e8 : v;
  }

  function fmtYiSigned(v) {
    var y = yiNum(v);
    if (y == null) return '—';
    return (y >= 0 ? '+' : '') + y.toFixed(1) + ' 億';
  }

  /** 依當日法人＋歷史序列產生趨勢評論（不重複上方數字本身） */
  function buildInstComment(i, histNewestFirst) {
    var parts = [];
    var f = yiNum(i.foreign), t = yiNum(i.trust), d = yiNum(i.dealer);
    var tot = i.totalYi != null && isFinite(i.totalYi) ? Number(i.totalYi) : (
      (f != null || t != null || d != null) ? ((f || 0) + (t || 0) + (d || 0)) : null
    );
    var rows = (histNewestFirst || []).filter(function (r) {
      return r && r.totalYi != null && isFinite(r.totalYi);
    });
    var chrono = rows.slice().reverse(); /* 舊→新 */
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

  function instDayEmpty(i) {
    i = i || {};
    return i.foreign == null && i.trust == null && i.dealer == null && i.totalYi == null;
  }

  /** 法人合計序列脈絡：Z20／分位／近 N 日買賣超排名（與頂列指數 Z 同構） */
  function instFlowQuant(seriesYi, currentYi) {
    var empty = { z20: null, pctile: null, rank: null, rankLabel: null, n: 0, bits: '' };
    var series = [];
    (seriesYi || []).forEach(function (v) {
      if (v != null && isFinite(v)) series.push(Number(v));
    });
    var cur = currentYi != null && isFinite(currentYi) ? Number(currentYi) : null;
    if (cur != null) {
      if (!series.length) series = [cur];
      else if (Math.abs(series[series.length - 1] - cur) <= 0.05) series[series.length - 1] = cur;
      else series.push(cur);
    }
    if (!series.length || cur == null) return empty;
    var w = series.length >= 20 ? series.slice(-20) : series.slice();
    var n = w.length;
    var mu = w.reduce(function (a, b) { return a + b; }, 0) / n;
    var varSum = w.reduce(function (a, b) { return a + (b - mu) * (b - mu); }, 0) / n;
    var sd = Math.sqrt(varSum);
    var z20 = sd > 1e-9 ? (cur - mu) / sd : null;
    var le = 0;
    w.forEach(function (v) { if (v <= cur) le += 1; });
    var pctile = Math.round(100 * le / n); /* P10＝偏極端賣超側 */
    var sortedAsc = w.slice().sort(function (a, b) { return a - b; });
    var rankAsc = sortedAsc.indexOf(cur) + 1; /* 1＝最賣超 */
    var rankDesc = n - rankAsc + 1; /* 1＝最買超 */
    var rankLabel = null;
    if (cur < 0 && rankAsc <= 5) rankLabel = '近' + n + '日賣超#' + rankAsc;
    else if (cur > 0 && rankDesc <= 5) rankLabel = '近' + n + '日買超#' + rankDesc;
    var bits = [];
    if (z20 != null) bits.push('Z' + (z20 >= 0 ? '+' : '') + z20.toFixed(1));
    if (pctile != null) bits.push('P' + pctile);
    if (rankLabel) bits.push(rankLabel);
    return {
      z20: z20 != null ? Math.round(z20 * 100) / 100 : null,
      pctile: pctile,
      rank: cur < 0 ? rankAsc : rankDesc,
      rankLabel: rankLabel,
      n: n,
      bits: bits.join(' · ')
    };
  }

  function paintInstCells(i, opts) {
    opts = opts || {};
    var box = $('pl-inst4');
    if (!box) return;
    var totalTxt = i.totalYi != null
      ? ((i.totalYi >= 0 ? '+' : '') + Number(i.totalYi).toFixed(1))
      : '—';
    var q = opts.quant || {};
    /* 單位億掛 title；Z／P 僅 title＋趨勢 meta，不進四格 */
    var tipBase = '單位：億';
    var totTip = 'title="' + tipBase +
      (q.bits ? (' · 近' + (q.n || 20) + '日 ' + esc(q.bits) + '（Z／P／排名）') : '') + '"';
    box.innerHTML =
      '<div class="c" title="' + tipBase + '"><div class="k">外資</div><div class="v ' + tw(i.foreign) + '">' +
        moneyYiCell(i.foreign) + '</div></div>' +
      '<div class="c" title="' + tipBase + '"><div class="k">投信</div><div class="v ' + tw(i.trust) + '">' +
        moneyYiCell(i.trust) + '</div></div>' +
      '<div class="c" title="' + tipBase + '"><div class="k">自營</div><div class="v ' + tw(i.dealer) + '">' +
        moneyYiCell(i.dealer) + '</div></div>' +
      '<div class="c" ' + totTip + '><div class="k">合計</div><div class="v ' + tw(i.totalYi) + '">' +
        totalTxt + '</div></div>';
    box.style.display = '';
    var badge = $('pl-inst-stale');
    if (badge) {
      if (opts.stale && opts.date) {
        badge.hidden = false;
        badge.textContent = '預覽前一日 ' + opts.date;
        badge.setAttribute('data-compact-label', '前日 ' + String(opts.date).slice(5));
        badge.title = '當日法人尚未公布 · 顯示前一交易日籌碼';
      } else if (opts.pending) {
        badge.hidden = false;
        badge.textContent = '當日尚未公布';
        badge.setAttribute('data-compact-label', '待公布');
        badge.title = '夜盤／假日常見 · 正在載入前一交易日籌碼';
      } else {
        badge.hidden = true;
        badge.textContent = '';
        badge.removeAttribute('data-compact-label');
        badge.removeAttribute('title');
      }
    }
    var empty = $('pl-inst-empty');
    if (empty) empty.hidden = true;
  }

  function renderInst(ov) {
    var i = (ov && ov.institutional) || {};
    var empty = instDayEmpty(i);
    var totalTxt = i.totalYi != null
      ? ((i.totalYi >= 0 ? '+' : '') + Number(i.totalYi).toFixed(1))
      : '—';
    return '<div class="pl-sec" data-pri="p0"><h4><span class="pl-sec-title-text">法人資金</span>' +
      '<span class="pl-stale" id="pl-inst-stale" data-compact-label="待公布"' + (empty ? '' : ' hidden') + '>' +
        (empty ? '當日尚未公布' : '') +
      '</span>' +
      '<a data-go="institutional">籌碼 →</a></h4>' +
      '<div class="pl-empty" id="pl-inst-empty" hidden></div>' +
      '<div class="pl-inst4" id="pl-inst4">' +
        '<div class="c" title="單位：億"><div class="k">外資</div><div class="v ' + tw(i.foreign) + '">' +
          (empty ? '…' : moneyYiCell(i.foreign)) + '</div></div>' +
        '<div class="c" title="單位：億"><div class="k">投信</div><div class="v ' + tw(i.trust) + '">' +
          (empty ? '…' : moneyYiCell(i.trust)) + '</div></div>' +
        '<div class="c" title="單位：億"><div class="k">自營</div><div class="v ' + tw(i.dealer) + '">' +
          (empty ? '…' : moneyYiCell(i.dealer)) + '</div></div>' +
        '<div class="c" title="單位：億"><div class="k">合計</div><div class="v ' + tw(i.totalYi) + '">' +
          (empty ? '…' : totalTxt) + '</div></div>' +
      '</div>' +
      '<div class="pl-inst-trend" id="pl-inst-trend">' +
        '<div class="lab"><span>合計買賣超 · 億</span><span id="pl-inst-trend-meta">' +
          (i.date ? '法人日 ' + esc(i.date) : '載入…') + '</span></div>' +
        '<div class="chart" id="pl-inst-chart"><div class="pl-note" style="padding:4px 0">載入資金序列…</div></div>' +
      '</div>' +
      '<div class="pl-inst-cmt" id="pl-inst-cmt">分析資金變化中…</div></div>';
  }

  function fillInstTrend(ov) {
    var i = (ov && ov.institutional) || {};
    jget('/pulse/history?kind=institutional&n=20').then(function (h) {
      var V = window.Viz;
      var chart = $('pl-inst-chart');
      var meta = $('pl-inst-trend-meta');
      var cmt = $('pl-inst-cmt');
      var rows = (h && h.rows) || [];
      var display = i;
      var stale = false;
      /* 當日缺法人：自動改顯示歷史最新一筆（前一交易日），並標註日期 */
      if (instDayEmpty(i) && rows.length) {
        var latest = rows[0];
        display = {
          foreign: latest.foreign != null ? latest.foreign : latest.foreignYi,
          trust: latest.trust != null ? latest.trust : latest.trustYi,
          dealer: latest.dealer != null ? latest.dealer : latest.dealerYi,
          totalYi: latest.totalYi != null ? latest.totalYi : (
            latest.total != null ? latest.total / 1e8 : null
          ),
          date: latest.date
        };
        stale = true;
      } else if (instDayEmpty(i) && !rows.length) {
        paintInstCells({}, { stale: false, pending: true });
        var empty = $('pl-inst-empty');
        if (empty) {
          empty.hidden = false;
          empty.innerHTML = '<b>法人資料不足</b>假日或尚未同步 — 請按頂列「同步資料」預抓籌碼序列';
        }
        var box0 = $('pl-inst4');
        if (box0) box0.style.display = 'none';
      }
      var chrono = rows.slice().reverse();
      var totals = chrono.map(function (r) { return r.totalYi; });
      /* 歷史不含當日時，用 display.totalYi 補末端再算 Z／分位 */
      var histForZ = totals.slice();
      if (display.totalYi != null && isFinite(display.totalYi)) {
        if (!histForZ.length || Math.abs(histForZ[histForZ.length - 1] - display.totalYi) > 0.05) {
          /* 若 rows 已是 display 那日，totals 末端已含；否則不重複 append 於 quant 內處理 */
        }
      }
      var quant = instFlowQuant(histForZ, display.totalYi);
      if (!instDayEmpty(display)) {
        paintInstCells(display, {
          stale: stale,
          date: display.date,
          quant: quant,
          pending: stale
        });
      } else if (instDayEmpty(i) && !rows.length) {
        /* already handled above */
      } else {
        paintInstCells({}, { pending: true });
      }
      if (chart) {
        if (V && totals.filter(function (v) { return v != null && isFinite(v); }).length >= 2) {
          var last = totals[totals.length - 1];
          var col = last >= 0 ? 'var(--red)' : 'var(--green)';
          chart.innerHTML = V.sparkLine(totals, {
            color: col, h: 36, w: 200,
            xUnit: '日', yUnit: '億', yDigits: 0,
            compact: true
          });
        } else if (totals.length) {
          chart.innerHTML = (V ? V.sparkBars(totals) : '<div class="pl-note">序列不足</div>');
        } else {
          chart.innerHTML = '<div class="pl-empty" style="min-height:40px;border:none">' +
            '<b>尚無本機法人歷史</b>可按同步資料預抓</div>';
        }
      }
      if (meta) {
        var metaShort = (rows.length ? ('近 ' + rows.length + ' 日') : '無序列') +
          (display.date ? ' · ' + display.date : '') +
          (stale ? ' · 前交易日' : '') +
          (quant.bits ? ' · ' + quant.bits : '');
        meta.textContent = metaShort;
        meta.title = (rows.length ? ('近 ' + rows.length + ' 日 · Y：億') : '無序列') +
          (display.date ? ' · ' + display.date : '') +
          (stale ? ' · 前交易日' : '') +
          (quant.bits ? ' · ' + quant.bits : '');
      }
      if (cmt) {
        var base = buildInstComment(display, rows);
        if (quant.rankLabel) {
          base = '合計處 <b>' + esc(quant.rankLabel) + '</b>' +
            (quant.z20 != null ? '（Z' + (quant.z20 >= 0 ? '+' : '') + quant.z20.toFixed(1) +
              ' · P' + quant.pctile + '）' : '') + '。 ' + base;
        } else if (quant.z20 != null && Math.abs(quant.z20) >= 1.2) {
          base = '合計偏離近' + quant.n + '日均值約 <b>Z' +
            (quant.z20 >= 0 ? '+' : '') + quant.z20.toFixed(1) + '</b>（P' + quant.pctile + '）。 ' + base;
        }
        cmt.innerHTML = base;
      }
    });
  }

  /** 依當日廣度＋歷史序列產生趨勢評論（不重複頂列／圓餅數字本身） */
  function buildBreadthComment(st, histNewestFirst) {
    var parts = [];
    var up = st.up, dn = st.down, flat = st.flat != null ? st.flat : st.unchanged;
    var ls = st.lsRatio;
    if (ls == null && up != null && dn) ls = up / Math.max(dn, 1);
    var adv = st.advRatio;
    var net = st.net;
    if (net == null && up != null && dn != null) net = up - dn;
    var rows = (histNewestFirst || []).filter(function (r) {
      return r && (r.lsRatio != null || (r.up != null && r.down != null));
    });
    var chrono = rows.slice().reverse();
    function rowLs(r) {
      if (r.lsRatio != null && isFinite(r.lsRatio)) return Number(r.lsRatio);
      if (r.up != null && r.down) return r.up / Math.max(r.down, 1);
      return null;
    }
    var streak = 0;
    if (ls != null && ls !== 1 && chrono.length) {
      var bull = ls > 1;
      for (var k = chrono.length - 1; k >= 0; k--) {
        var v = rowLs(chrono[k]);
        if (v == null || v === 1 || (v > 1) !== bull) break;
        streak += 1;
      }
    }
    if (streak >= 3) {
      parts.push(ls > 1
        ? '多空比已連 <b class="up">' + streak + '</b> 日偏多，上漲面持續擴張。'
        : '多空比已連 <b class="dn">' + streak + '</b> 日偏空，上漲面持續收縮。');
    } else if (ls != null) {
      parts.push(ls >= 2
        ? '多空比明顯偏多，短線參與面寬。'
        : ls <= 0.5
          ? '多空比明顯偏空，短線承壓面廣。'
          : '多空比接近均衡，方向性訊號有限。');
    }
    if (chrono.length >= 2 && ls != null) {
      var prevLs = rowLs(chrono[chrono.length - 2]);
      if (prevLs != null && isFinite(prevLs)) {
        var dLs = ls - prevLs;
        if (Math.abs(dLs) >= 0.35) {
          parts.push(dLs > 0
            ? '較前日多空比轉強約 <span class="up">+' + dLs.toFixed(2) + '</span>。'
            : '較前日多空比轉弱約 <span class="dn">' + dLs.toFixed(2) + '</span>。');
        } else if (prevLs > 1 && ls < 1) {
          parts.push('多空比由多轉空，廣度氛圍轉向謹慎。');
        } else if (prevLs < 1 && ls > 1) {
          parts.push('多空比由空轉多，廣度回溫跡象。');
        }
      }
      var prevNet = chrono[chrono.length - 2].net;
      if (net != null && prevNet != null && isFinite(prevNet) && Math.abs(net - prevNet) >= 200) {
        parts.push(net > prevNet
          ? '淨上漲家數較前日明顯增加。'
          : '淨上漲家數較前日明顯減少。');
      }
    }
    if (adv != null) {
      if (adv >= 0.70) parts.push('上漲占比逾七成，擴散偏強。');
      else if (adv <= 0.35) parts.push('上漲占比偏低，擴散偏弱。');
    }
    /* 漲跌停僅在極端時評論，避免只複述家數 */
    var lu = st.limitUp, ld = st.limitDown;
    if (lu != null && ld != null) {
      if (lu >= 40 && ld <= 2) parts.push('漲停潮偏熱，留意短線過熱。');
      else if (ld >= 10 && lu <= 5) parts.push('跌停家數偏多，防禦情緒升溫。');
    }
    if (!parts.length) parts.push('廣度序列載入中或資料不足，暫無趨勢評論。');
    return parts.slice(0, 3).join(' ');
  }

  /** 廣度四格：上漲／平盤／下跌／多空比（結構對齊法人四格） */
  function paintBreadthCells(st) {
    st = st || {};
    var box = $('pl-bd4');
    if (!box) return;
    var up = st.up;
    var dn = st.down;
    var flat = st.flat != null ? st.flat : st.unchanged;
    var ls = st.lsRatio;
    if (ls == null && up != null && dn) ls = up / Math.max(dn, 1);
    var net = st.net;
    if (net == null && (up != null || dn != null)) net = (up || 0) - (dn || 0);
    var advTxt = st.advRatio != null ? (Number(st.advRatio) * 100).toFixed(1) + '%' : '—';
    var netTxt = net != null ? ((net >= 0 ? '+' : '') + net) : '—';
    var lsTxt = ls != null && isFinite(ls) ? Number(ls).toFixed(2) : '—';
    var lsTip = 'title="多空比＝上漲／下跌' +
      (st.advRatio != null ? (' · 上漲比 ' + advTxt) : '') +
      (net != null ? (' · 淨 ' + netTxt) : '') + '"';
    box.innerHTML =
      '<div class="c" title="上漲家數"><div class="k">上漲</div><div class="v up">' +
        (up != null ? fmt(up) : '—') + '</div></div>' +
      '<div class="c" title="平盤家數"><div class="k">平盤</div><div class="v flat">' +
        (flat != null ? fmt(flat) : '—') + '</div></div>' +
      '<div class="c" title="下跌家數"><div class="k">下跌</div><div class="v dn">' +
        (dn != null ? fmt(dn) : '—') + '</div></div>' +
      '<div class="c" ' + lsTip + '><div class="k">多空比</div><div class="v ' + tw(ls != null ? ls - 1 : null) + '">' +
        lsTxt + '</div></div>';
  }

  function renderDonut(ov, st) {
    st = st || (ov && ov.strip) || {};
    if (ov && ov.lsRatio != null && st.lsRatio == null) st.lsRatio = ov.lsRatio;
    var up = st.up;
    var dn = st.down;
    var flat = st.flat != null ? st.flat : st.unchanged;
    var ls = st.lsRatio;
    if (ls == null && up != null && dn) ls = up / Math.max(dn, 1);
    var lsTxt = ls != null && isFinite(ls) ? Number(ls).toFixed(2) : '—';
    return '<div class="pl-sec" data-pri="p0"><h4>市場廣度 <a data-go="breadth">詳情 →</a></h4>' +
      '<div class="pl-bd4" id="pl-bd4">' +
        '<div class="c" title="上漲家數"><div class="k">上漲</div><div class="v up">' +
          (up != null ? fmt(up) : '—') + '</div></div>' +
        '<div class="c" title="平盤家數"><div class="k">平盤</div><div class="v flat">' +
          (flat != null ? fmt(flat) : '—') + '</div></div>' +
        '<div class="c" title="下跌家數"><div class="k">下跌</div><div class="v dn">' +
          (dn != null ? fmt(dn) : '—') + '</div></div>' +
        '<div class="c" title="多空比＝上漲／下跌"><div class="k">多空比</div><div class="v ' +
          tw(ls != null ? ls - 1 : null) + '">' + lsTxt + '</div></div>' +
      '</div>' +
      '<div class="pl-bd-trend" id="pl-bd-trend">' +
        '<div class="lab"><span>多空比 · 倍</span><span id="pl-bd-trend-meta">載入…</span></div>' +
        '<div class="chart" id="pl-bd-chart"><div class="pl-note" style="padding:4px 0">載入廣度序列…</div></div>' +
      '</div>' +
      '<div class="pl-bd-cmt" id="pl-bd-cmt">分析廣度變化中…</div></div>';
  }

  function fillBreadthTrend(ov) {
    var st = Object.assign({}, (ov && ov.strip) || {});
    if (ov && ov.lsRatio != null && st.lsRatio == null) st.lsRatio = ov.lsRatio;
    jget('/pulse/history?kind=breadth&n=20').then(function (h) {
      var V = window.Viz;
      var chart = $('pl-bd-chart');
      var meta = $('pl-bd-trend-meta');
      var cmt = $('pl-bd-cmt');
      var rows = (h && h.rows) || [];
      /* 當日 strip 缺欄時，用歷史最新一筆對齊四格／評論／meta（與詳情頁同源） */
      if (rows.length && (st.up == null || st.lsRatio == null || st.advRatio == null)) {
        var latest = rows[0];
        ['up', 'down', 'flat', 'unchanged', 'limitUp', 'limitDown', 'advRatio', 'net', 'lsRatio'].forEach(function (k) {
          if (st[k] == null && latest[k] != null) st[k] = latest[k];
        });
      }
      paintBreadthCells(st);
      var chrono = rows.slice().reverse();
      var lsSeries = chrono.map(function (r) {
        if (r.lsRatio != null && isFinite(r.lsRatio)) return Number(r.lsRatio);
        if (r.up != null && r.down) return r.up / Math.max(r.down, 1);
        return null;
      });
      var usable = lsSeries.filter(function (v) { return v != null && isFinite(v); });
      if (chart) {
        if (V && usable.length >= 2) {
          var last = usable[usable.length - 1];
          var col = last >= 1 ? 'var(--red)' : 'var(--green)';
          chart.innerHTML = V.sparkLine(usable, {
            color: col, h: 36, w: 200,
            xUnit: '日', yUnit: '倍', yDigits: 2,
            compact: true
          });
        } else if (usable.length) {
          chart.innerHTML = V ? V.sparkBars(usable.map(function (v) { return v - 1; })) :
            '<div class="pl-note">序列不足</div>';
        } else {
          chart.innerHTML = '<div class="pl-empty" style="min-height:40px;border:none">' +
            '<b>尚無本機廣度歷史</b>可按同步資料預抓</div>';
        }
      }
      if (meta) {
        var net = st.net;
        if (net == null && (st.up != null || st.down != null)) net = (st.up || 0) - (st.down || 0);
        var advBit = st.advRatio != null ? (' · 上漲比 ' + (Number(st.advRatio) * 100).toFixed(1) + '%') : '';
        var netBit = net != null ? (' · 淨' + (net >= 0 ? '+' : '') + net) : '';
        var lsBit = st.lsRatio != null ? ('今 ' + Number(st.lsRatio).toFixed(2)) : '';
        meta.textContent = (rows.length ? ('近 ' + rows.length + ' 日') : '無序列') +
          (lsBit ? ' · ' + lsBit : '') + netBit;
        meta.title = (rows.length ? ('近 ' + rows.length + ' 日 · Y：倍') : '無序列') +
          (lsBit ? ' · ' + lsBit : '') + netBit + advBit;
      }
      if (cmt) cmt.innerHTML = buildBreadthComment(st, rows);
    });
  }

  function sectorsFromPack(ov) {
    if (sectorMkt === 'US' && sectorCache.US) return sectorCache.US;
    if (sectorMkt === 'TW' && sectorCache.TW) return sectorCache.TW;
    return (ov && ov.sectorsRanked) || [];
  }

  /** 產業別名正規化：半導體業／半導體 → 可互相比對的 key */
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

  function industryLabel(r) {
    if (!r) return '';
    return r.industryShort || (r.industry ? (
      r.industry.endsWith('業') && r.industry.length > 2 ? r.industry.slice(0, -1) : r.industry
    ) : '');
  }

  function renderSectors(ov) {
    var list = sectorsFromPack(ov).slice();
    list.sort(function (a, b) { return Math.abs(b.changePct || 0) - Math.abs(a.changePct || 0); });
    var maxAbs = 1;
    list.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.changePct || 0)); });
    var usOn = sectorMkt === 'US';
    var html = '<div class="pl-sec" id="pl-sectors" data-pri="p1"><h4>產業輪動' +
      '<span class="pl-sec-tog">' +
        '<button type="button" data-sec-mkt="TW" class="' + (usOn ? '' : 'on') + '">TW</button>' +
        '<button type="button" data-sec-mkt="US" class="' + (usOn ? 'on' : '') + '">US</button>' +
      '</span>' +
      ' <a data-go="heat" data-mkt="' + (usOn ? 'US' : 'TW') + '" data-sector="">熱力 →</a></h4>' +
      '<div class="pl-fill" id="pl-sectors-body">' +
      '<div class="pl-note" style="margin:0 0 3px">點列開熱力並高亮' +
        (usOn ? '' : ' · 懸停聯動近漲跌停') + '</div>';
    if (!list.length) {
      return html + '<div class="pl-note">' + (usOn ? '美股產業載入中…' : '類股資料暫缺 — 點「熱力 →」開啟') +
        '</div></div></div>';
    }
    list.slice(0, 10).forEach(function (s) {
      var w = Math.max(4, Math.round(Math.abs(s.changePct) / maxAbs * 100));
      /* 台股紅漲綠跌；美股綠漲紅跌 */
      var upCol = usOn ? 'var(--green)' : 'var(--red)';
      var dnCol = usOn ? 'var(--red)' : 'var(--green)';
      var col = (s.changePct || 0) >= 0 ? upCol : dnCol;
      var pcCls = marketCls(s.changePct, usOn ? 'US' : 'TW');
      var sk = sectorKey(s.name);
      html += '<div class="pl-sbar" data-go="heat" data-mkt="' + (usOn ? 'US' : 'TW') + '"' +
        ' data-sector="' + esc(s.name || '') + '" data-sector-key="' + esc(sk) + '"' +
        ' title="' + esc(s.name || '') + ' — 點擊開啟類股熱力' +
        (usOn ? '' : ' · 懸停聯動近漲跌停') + '">' +
        '<div class="nm">' + esc(s.name) + '</div>' +
        '<div class="track"><i style="width:' + w + '%;background:' + col + '"></i></div>' +
        '<div class="pc ' + pcCls + '">' + pct(s.changePct) + '</div></div>';
    });
    return html + '</div></div>';
  }

  function loadSectorsMkt(mkt) {
    sectorMkt = mkt || 'TW';
    if (sectorCache[sectorMkt] && lastPack) {
      var body = $('pl-body');
      if (body && lastPack) render(lastPack);
      return;
    }
    jget('/sectors?mkt=' + encodeURIComponent(sectorMkt)).then(function (d) {
      var rows = (d && d.sectors) || [];
      sectorCache[sectorMkt] = rows.map(function (s) {
        return { name: s.name, changePct: s.changePct, close: s.close, symbol: s.symbol };
      });
      if (lastPack) render(lastPack);
    });
  }

  function renderMovers(movers, side) {
    var V = window.Viz;
    var list = [];
    var title, empty, note;
    if (side === 'gainers') {
      /* 優先用後端 limitUp（上市普通股 ≥9.9%）；勿與頂列官方括號家數混為一談 */
      list = ((movers && movers.limitUp) || []).slice(0, 10);
      if (!list.length) {
        var raw = (movers && movers.gainers) || [];
        list = raw.filter(function (r) {
          return r && r.ex !== 'TPEx' && r.changePct != null && r.changePct >= 9.9 &&
            /^[1-9]\d{3}$/.test(String(r.code || ''));
        }).slice(0, 10);
      }
      title = '近漲停';
      empty = '尚無上市個股接近漲停（≥9.9%）';
      note = '上市≥9.9%・≠頂列官方家數';
    } else {
      var bad = ((movers && movers.limitDown) || []).slice();
      if (!bad.length) {
        bad = ((movers && movers.losers) || []).filter(function (r) {
          return r && r.changePct != null && r.changePct <= -7;
        });
      }
      list = bad.slice(0, 10);
      title = '跌幅異常';
      empty = '尚無大幅下跌標的';
      note = '';
    }
    var maxAbs = 0;
    list.forEach(function (r) {
      if (r.changePct != null && isFinite(r.changePct)) maxAbs = Math.max(maxAbs, Math.abs(r.changePct));
    });
    var moverDate = movers && movers.date ? String(movers.date) : '';
    var moverDateCompact = moverDate.replace(/^(?:\d{4})[-\/]?(\d{2})[-\/]?(\d{2})$/, '$1-$2');
    var html = '<div class="pl-sec pl-movers" data-pri="p1" data-movers-side="' + side + '"><h4>' +
      '<span class="pl-sec-title-text pl-movers-title">' + title + '</span>' +
      (moverDate ? ' <span class="pl-sec-hint pl-movers-date" style="margin-right:0" title="' + esc(moverDate) +
        '" data-compact-label="' + esc(moverDateCompact) + '">' + esc(moverDate) + '</span>' : '') +
      (note ? ' <span class="pl-sec-hint pl-movers-note" style="margin-right:0" title="' + esc(note) +
        '" data-compact-label="上市≥9.9%">' + esc(note) + '</span>' : '') +
      ' <a data-go="breadth">廣度 →</a></h4><ul class="pl-list">';
    if (!list.length) return html + '<li style="cursor:default;color:#94a3b8">' + empty + '</li></ul></div>';
    list.forEach(function (r) {
      var limChip = V ? V.limitChip(r.changePct) : '';
      var bar = V ? V.rowBar(r.changePct, maxAbs) : '';
      var ind = industryLabel(r);
      var indFull = r.industry || ind;
      var sk = sectorKey(ind || indFull);
      var indHtml = ind
        ? '<span class="ind" title="' + esc(indFull) + '">' + esc(ind) + '</span>'
        : '';
      html += '<li data-code="' + esc(r.code || '') + '"' +
        (indFull ? ' data-industry="' + esc(indFull) + '"' : '') +
        (sk ? ' data-sector-key="' + esc(sk) + '"' : '') +
        '><span class="nm"><span class="cd">' +
        esc(r.code || '') + '</span>' + esc(r.name || '') + indHtml +
        '</span><span class="' + tw(r.changePct) + '">' +
        pct(r.changePct) + limChip + bar + '</span></li>';
    });
    return html + '</ul></div>';
  }

  /** 產業輪動 ↔ 近漲跌停：hover 雙向高亮同產業 */
  function bindSectorMoverLink(root) {
    if (!root) return;
    var bars = root.querySelectorAll('#pl-sectors-body .pl-sbar[data-sector-key]');
    var movers = root.querySelectorAll('.pl-movers .pl-list li[data-sector-key]');
    if (!bars.length || !movers.length) return;

    function clear() {
      bars.forEach(function (el) { el.classList.remove('hi', 'dim'); });
      movers.forEach(function (el) { el.classList.remove('hi', 'dim'); });
    }

    function highlightByKey(key) {
      if (!key) { clear(); return; }
      var any = false;
      movers.forEach(function (el) {
        var match = sectorKeysMatch(key, el.getAttribute('data-sector-key'));
        el.classList.toggle('hi', match);
        el.classList.toggle('dim', !match);
        if (match) any = true;
      });
      bars.forEach(function (el) {
        var match = sectorKeysMatch(key, el.getAttribute('data-sector-key'));
        el.classList.toggle('hi', match);
        el.classList.toggle('dim', any ? !match : false);
      });
      if (!any) {
        /* 無對應個股時只亮產業列本身 */
        bars.forEach(function (el) {
          var match = sectorKeysMatch(key, el.getAttribute('data-sector-key'));
          el.classList.toggle('hi', match);
          el.classList.remove('dim');
        });
        movers.forEach(function (el) { el.classList.remove('hi', 'dim'); });
      }
    }

    bars.forEach(function (el) {
      el.onmouseenter = function () { highlightByKey(el.getAttribute('data-sector-key')); };
      el.onmouseleave = clear;
    });
    movers.forEach(function (el) {
      el.onmouseenter = function () { highlightByKey(el.getAttribute('data-sector-key')); };
      el.onmouseleave = clear;
    });
  }

  function globalImpactTone(items) {
    var n = 0, sum = 0;
    items.forEach(function (x) {
      if (x && x.changePct != null && isFinite(x.changePct) && x.symbol !== '^VIX') {
        n += 1; sum += x.changePct;
      }
    });
    if (!n) return '資料彙整中';
    var avg = sum / n;
    if (avg >= 0.6) return '偏多';
    if (avg <= -0.6) return '偏空';
    return '中性';
  }

  /** 全球列簡寫：爭取欄寬，完整名稱放 title */
  function globalAbbr(x) {
    var map = {
      '^DJI': 'DJI', '^GSPC': 'SPX', '^IXIC': 'NDX', '^SOX': 'SOX',
      '^N225': 'N225', '^KS11': 'KOSPI', '^VIX': 'VIX',
      'GC=F': 'GOLD', 'HG=F': 'COPPER', 'CL=F': 'OIL',
      'TWD=X': 'USD/TWD', 'DX-Y.NYB': 'DXY', 'DX=F': 'DXY',
      'US10Y': 'US10Y'
    };
    if (x && x.symbol && map[x.symbol]) return map[x.symbol];
    var n = String((x && (x.name || x.symbol)) || '');
    if (/道瓊|道琼斯|Dow/i.test(n)) return 'DJI';
    if (/S&P|標普/i.test(n)) return 'SPX';
    if (/納斯達克|Nasdaq|NASDAQ/i.test(n)) return 'NDX';
    if (/費半|SOX|半導體/i.test(n)) return 'SOX';
    return n.length > 6 ? n.slice(0, 6) : n;
  }

  /** 全球影響右側：漲跌點數 + ％（有點位必顯示數字） */
  function globalChgLabel(x, dig) {
    var bits = [];
    var pts = null;
    if (x && x.change != null && isFinite(Number(x.change))) pts = Number(x.change);
    else if (x && x.price != null && x.prevClose != null &&
        isFinite(Number(x.price)) && isFinite(Number(x.prevClose))) {
      pts = Number(x.price) - Number(x.prevClose);
    }
    /* 美債殖利率左側已是％點位，右側只顯示變動％（若有） */
    if (pts != null && x.symbol !== 'US10Y') {
      var pdig = dig;
      if (x.symbol === 'TWD=X') pdig = 3;
      else if (x.symbol === 'CL=F' || x.symbol === 'GC=F' || x.symbol === 'HG=F') pdig = 2;
      else if (Number(x.price) >= 1000) pdig = 0;
      var ptsTxt = chgPts({ change: pts }, pdig);
      if (ptsTxt) bits.push(ptsTxt);
    }
    if (x && x.changePct != null && isFinite(Number(x.changePct))) {
      bits.push(pct(x.changePct));
    }
    return bits.length ? bits.join(' · ') : '—';
  }

  function renderGlobal(p) {
    var g = p.global || [];
    var items = g.slice();
    if (p.us10y && p.us10y.value != null) {
      items.push({
        symbol: 'US10Y', name: '美10年債',
        price: p.us10y.value, changePct: null, unit: '%'
      });
    }
    var prefer = [
      '^DJI', '^GSPC', '^IXIC', '^SOX', '^N225', '^KS11',
      '^VIX', 'GC=F', 'HG=F', 'CL=F', 'TWD=X', 'DX-Y.NYB', 'DX=F', 'US10Y'
    ];
    items.sort(function (a, b) {
      var ia = prefer.indexOf(a.symbol); var ib = prefer.indexOf(b.symbol);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var tone = globalImpactTone(items);
    var html = '<div class="pl-sec pl-global-sec"><h4>全球影響' +
      ' <span class="' + biasCls(tone) + '" style="font-weight:700;font-size:9px;margin-left:4px">' + tone + '</span>' +
      ' <a data-go="international">國際 →</a></h4><div class="pl-global" tabindex="0" role="region" aria-label="全球影響報價，可上下捲動">';
    if (!items.length) html += '<div class="pl-note">國際報價載入中…</div>';
    items.slice(0, 14).forEach(function (x) {
      var dig = (x.unit === '%' || x.symbol === 'US10Y' || x.symbol === '^VIX' || x.symbol === 'TWD=X' ||
        x.symbol === 'HG=F' || x.symbol === 'CL=F') ? 2
        : (x.price > 1000 ? 0 : 2);
      if (x.symbol === 'TWD=X') dig = 3;
      var px = fmt(x.price, dig) + (x.unit === '%' || x.symbol === 'US10Y' ? '%' : '');
      var abbr = globalAbbr(x);
      var full = (x.name || x.symbol || abbr) + (x.role ? ' · ' + x.role : '') +
        (x.price != null ? (' · ' + px) : '');
      var chgLbl = globalChgLabel(x, dig);
      var globalClass = marketCls(x.changePct, 'US');
      traceMarketColor('pulse.global', x.symbol || abbr, 'US', x.changePct, globalClass);
      html += '<div class="g" title="' + esc(full) + '">' +
        '<div class="k"><span class="abbr">' + esc(abbr) + '</span>' +
          (x.role ? '<span class="role">' + esc(x.role) + '</span>' : '') +
        '</div>' +
        '<div class="row">' +
          '<div class="v" title="點位">' + px + '</div>' +
          '<div class="s ' + globalClass + '" title="漲跌點 · ％">' +
            chgLbl +
          '</div>' +
        '</div></div>';
    });
    return html + '</div></div>';
  }

  function renderEco(p) {
    var eco = p.economy || [];
    var html = '<div class="pl-sec"><h4>總經數據</h4><div class="pl-fill">';
    if (!eco.length) {
      return html + '<div class="pl-note">FRED／主計總處序列尚未就緒</div></div></div>';
    }
    eco.forEach(function (e) {
      html += '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border);font-size:10px">' +
        '<span style="color:var(--tlo)">' + esc(e.label || e.key) + '</span>' +
        '<span style="font-weight:700;color:var(--thi)">' + fmt(e.value, 2) + esc(e.unit || '') +
        '<span style="color:var(--tlo);font-weight:500;margin-left:6px;font-size:9px">' + esc(e.date || '') + '</span></span></div>';
    });
    return html + '</div></div>';
  }

  function flashIsUs(f) {
    return !!(f && ((f.mkt === 'US') || (f.cat && String(f.cat).indexOf('美股') >= 0)));
  }

  function filterFlash(list) {
    var all = list || [];
    if (flashMkt === 'US') all = all.filter(flashIsUs);
    else if (flashMkt === 'TW') all = all.filter(function (f) { return !flashIsUs(f); });
    var q = String(flashQ || '').trim().toLowerCase();
    if (!q) return all;
    return all.filter(function (f) {
      var hay = [
        f.title, f.cat, f.code, f.symbol, f.name, f.mkt
      ].map(function (x) { return String(x || '').toLowerCase(); }).join(' ');
      return hay.indexOf(q) >= 0;
    });
  }

  function renderFlash(p) {
    var flash = p.flash || [];
    var shown = filterFlash(flash);
    var html = '<div class="pl-sec" id="pl-flash-sec"><h4><span class="pl-flash-title">市場快訊</span>' +
      '<span class="pl-flash-tools">' +
        '<input type="search" class="pl-flash-q" id="pl-flash-q" placeholder="搜代號/關鍵字" ' +
          'value="' + esc(flashQ) + '" aria-label="快訊關鍵字搜尋" />' +
        '<span class="pl-sec-tog">' +
          '<button type="button" data-flash-mkt="ALL" class="' + (flashMkt === 'ALL' ? 'on' : '') + '">全部</button>' +
          '<button type="button" data-flash-mkt="TW" class="' + (flashMkt === 'TW' ? 'on' : '') + '">台股</button>' +
          '<button type="button" data-flash-mkt="US" class="' + (flashMkt === 'US' ? 'on' : '') + '">美股</button>' +
        '</span>' +
      '</span>' +
      '<a data-go="news">中樞 →</a></h4><div class="pl-flash" id="pl-flash-body">';
    if (!flash.length) {
      return html + '<div class="pl-note">載入台／美重大訊息中…</div></div></div>';
    }
    if (!shown.length) {
      return html + '<div class="pl-empty" style="min-height:56px;border:none">' +
        '<b>' + (flashQ ? '無符合關鍵字' : '此分類暫無快訊') + '</b>' +
        (flashQ ? '可清空搜尋或切換分類' : '可切換「全部」或稍後再試') +
        '</div></div></div>';
    }
    shown.slice(0, 14).forEach(function (f) {
      var isUs = flashIsUs(f);
      var catCls = isUs ? 'cat us' : 'cat';
      var title = f.title || '';
      var tier = String(((f.impact || {}).tier) || '').toUpperCase();
      var tierBit = tier && tier !== 'LOW' ? (' · ' + tier) : '';
      html += '<div class="row"' +
        (f.code ? ' data-code="' + esc(f.code) + '"' : '') +
        (f.mkt ? ' data-mkt="' + esc(f.mkt) + '"' : '') +
        (f.url ? ' data-url="' + esc(f.url) + '"' : '') +
        ' title="' + esc(title) + '">' +
        '<span class="t">' + esc(f.time || '') + '</span>' +
        '<span class="' + catCls + '">[' + esc((f.cat || (isUs ? '美股' : '重訊')) + tierBit) + ']</span>' +
        '<span class="ttl">' + esc(title) + '</span></div>';
    });
    return html + '</div></div>';
  }

  var WATCH_THEME_RULES = [
    {
      id: 'memory', label: '記憶體',
      symbols: ['MU', 'SNDK', 'WDC', 'STX', '2408', '2344', '2337', '3006', '8299'],
      words: ['記憶體', 'DRAM', 'NAND', '美光', 'SANDISK', '南亞科', '華邦電', '旺宏', '群聯']
    },
    {
      id: 'ai_chip', label: 'AI 晶片',
      symbols: ['NVDA', 'AMD', 'TSM', 'AVGO', '2330', '2454', '3661', '6669', '3017', '3443', '6223', '5347'],
      words: ['AI晶片', 'AI 晶片', '半導體', '晶片', '台積電', '聯發科', '世芯', '創意', '緯穎', '雍智']
    }
  ];

  function watchQuote(w, quotes) {
    return (quotes && (quotes[w.t] || quotes[w.t + '.TW'] || quotes[w.t + '.TWO'])) || {};
  }

  function watchTheme(w) {
    var sym = String((w && w.t) || '').toUpperCase().replace(/\.(TW|TWO)$/, '');
    var hay = [sym, w && w.name, w && w.industry, w && w.sector, w && w.theme]
      .map(function (x) { return String(x || '').toUpperCase(); }).join(' ');
    for (var i = 0; i < WATCH_THEME_RULES.length; i++) {
      var rule = WATCH_THEME_RULES[i];
      if (rule.symbols.indexOf(sym) >= 0 || rule.words.some(function (word) {
        return hay.indexOf(String(word).toUpperCase()) >= 0;
      })) return rule;
    }
    return null;
  }

  /* 自選池共振不是歷史相關係數：只量同一時點的同向參與率與平均漲跌強度。 */
  function buildWatchThemeResonance(wl, quotes) {
    if (window.MarketIntelV5 && typeof window.MarketIntelV5.buildThemeResonance === 'function') {
      return window.MarketIntelV5.buildThemeResonance(wl, quotes);
    }
    var groups = {};
    (wl || []).forEach(function (w) {
      var theme = watchTheme(w);
      if (!theme) return;
      var q = watchQuote(w, quotes);
      var cp = q.changePct != null ? Number(q.changePct) : Number(w.chg);
      if (!isFinite(cp)) return;
      var row = { symbol: String(w.t), changePct: cp };
      (groups[theme.id] || (groups[theme.id] = { id: theme.id, label: theme.label, rows: [] })).rows.push(row);
    });
    var signals = Object.keys(groups).map(function (id) {
      var group = groups[id], active = group.rows.filter(function (r) { return Math.abs(r.changePct) >= 0.15; });
      if (active.length < 2) return null;
      var up = active.filter(function (r) { return r.changePct > 0; });
      var down = active.filter(function (r) { return r.changePct < 0; });
      var dominant = up.length >= down.length ? up : down;
      var direction = up.length >= down.length ? 'bull' : 'bear';
      var participation = dominant.length / active.length;
      var avgAbs = dominant.reduce(function (sum, r) { return sum + Math.abs(r.changePct); }, 0) / dominant.length;
      var score = Math.round(Math.min(100, participation * 70 + Math.min(1, avgAbs / 6) * 30));
      if (dominant.length < 2 || participation < 0.66 || score < 60) return null;
      return {
        id: group.id, label: group.label, direction: direction, score: score,
        sameCount: dominant.length, totalCount: active.length, averageAbsPct: Math.round(avgAbs * 100) / 100,
        symbols: dominant.map(function (r) { return r.symbol; })
      };
    }).filter(Boolean).sort(function (a, b) { return b.score - a.score; });
    var bySymbol = {};
    signals.forEach(function (signal) {
      signal.symbols.forEach(function (sym) { if (!bySymbol[sym]) bySymbol[sym] = signal; });
    });
    return { leaders: signals, bySymbol: bySymbol };
  }

  function watchTag(cp, resonance) {
    if (cp == null || !isFinite(cp)) return '';
    var resonanceTitle = resonance ? (' · ' + resonance.label + '同向 ' + resonance.sameCount + '／' +
      resonance.totalCount + ' · 共振熱度 ' + resonance.score) : '';
    var resonanceClass = resonance ? (' resonant ' + resonance.direction) : '';
    if (cp >= 3) return '<span class="pl-tag hot' + resonanceClass + '" title="機會 · 漲幅 ≥ 3%' +
      esc(resonanceTitle) + '">機會</span>';
    if (cp <= -3) return '<span class="pl-tag cold' + resonanceClass + '" title="風險 · 跌幅 ≤ -3%' +
      esc(resonanceTitle) + '">風險</span>';
    return '<span class="pl-tag ok" title="觀察">觀察</span>';
  }

  function renderWatch(quotes, news) {
    var wlAll = readWatchlist();
    var wl = filterWatchlist(wlAll);
    var resonance = buildWatchThemeResonance(wl, quotes || {});
    var newsLinks = (window.MarketIntelV5 && typeof window.MarketIntelV5.linkNewsToWatchlist === 'function')
      ? window.MarketIntelV5.linkNewsToWatchlist(news || [], wl) : { bySymbol: {} };
    var heat = resonance.leaders[0] || null;
    var nTw = wlAll.filter(function (w) { return !watchIsUs(w); }).length;
    var nUs = wlAll.filter(watchIsUs).length;
    var html = '<div class="pl-sec pl-wl" id="pl-watch-sec" data-pri="p1"><h4 class="pl-wl-head"><span class="pl-wl-title">自選風險</span>' +
      (heat ? '<span class="pl-theme-heat" title="同向參與率＋平均漲跌強度；不是歷史相關係數">' +
        (heat.direction === 'bull' ? '🔥 ' : '⚠ ') + esc(heat.label) + ' ' + heat.score + '</span>' : '') +
      '<span class="pl-sec-tog">' +
        '<button type="button" data-watch-mkt="ALL" class="' + (watchMkt === 'ALL' ? 'on' : '') +
          '" title="全部 ' + wlAll.length + '">全部</button>' +
        '<button type="button" data-watch-mkt="TW" class="' + (watchMkt === 'TW' ? 'on' : '') +
          '" title="台股 ' + nTw + '">台股</button>' +
        '<button type="button" data-watch-mkt="US" class="' + (watchMkt === 'US' ? 'on' : '') +
          '" title="美股 ' + nUs + '">美股</button>' +
      '</span>' +
      '<a data-go="watchlist">自選 →</a></h4>';
    if (!wlAll.length) {
      return html + '<div class="pl-note">尚無自選 — 在圖表按 ＋ 加入</div></div>';
    }
    if (!wl.length) {
      return html + '<div class="pl-empty" style="min-height:48px;border:none">' +
        '<b>此市場無自選</b>可切換「全部」或至自選頁新增</div></div>';
    }
    html += '<div class="pl-wl-scroll"><table>' +
      '<colgroup><col class="c-sym"><col class="c-px"><col class="c-chg"><col class="c-tag"></colgroup>' +
      '<tr><th>代號</th><th>現價</th><th>漲跌</th><th title="金＝機會／紅＝風險／灰＝觀察">●</th></tr>';
    wl.forEach(function (w) {
      var mkt = watchIsUs(w) ? 'US' : (w.m || 'TW');
      var q = watchQuote(w, quotes);
      var px = q.price != null ? q.price : w.price;
      var cp = q.changePct != null ? q.changePct : w.chg;
      var dig = mkt === 'US' ? 2 : (px != null && Number(px) >= 1000 ? 1 : 2);
      var unit = mkt === 'US' ? '<span class="mkt">USD</span>' : '';
      var cpCls = marketCls(cp, mkt);
      var linkedNews = newsLinks.bySymbol[String(w.t).toUpperCase()] || [];
      var leadNews = linkedNews[0] || null;
      var newsTitle = leadNews ? ('新聞聯動 ' + linkedNews.length + ' 則 · ' + leadNews.tier + ' · ' + leadNews.title) : '';
      html += '<tr data-code="' + esc(w.t) + '" data-mkt="' + esc(mkt) + '"' +
        (leadNews ? (' class="news-hit" data-news-tier="' + esc(leadNews.tier) + '" title="' + esc(newsTitle) + '"') : '') + '>' +
        '<td style="color:var(--gold);font-weight:700">' +
          esc(w.t) + unit +
          (leadNews ? '<span class="pl-news-mark" aria-label="新聞聯動">✦</span>' : '') +
          (w.name ? '<span class="nm-only" title="' + esc(w.name) + '">' + esc(w.name) + '</span>' : '') +
        '</td><td class="px">' + fmt(px, dig) + '</td><td class="chg ' + cpCls + '">' + pct(cp) + '</td>' +
        '<td class="tag">' + watchTag(cp, resonance.bySymbol[String(w.t)] || null) + '</td></tr>';
    });
    return html + '</table></div></div>';
  }


  function bind(body) {
    body.querySelectorAll('[data-go]').forEach(function (a) {
      if (!a.hasAttribute('tabindex')) a.setAttribute('tabindex', '0');
      if (!a.hasAttribute('role')) a.setAttribute('role', 'link');
      a.onclick = function (e) {
        e.preventDefault();
        e.stopPropagation();
        var traceId = 'pulse-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        var target = a.getAttribute('data-go');
        var opts = {
          sym: a.getAttribute('data-sym') || undefined,
          mkt: a.getAttribute('data-mkt') || undefined,
          _traceId: traceId,
          _traceTarget: target,
          _traceLabel: (a.textContent || '').trim()
        };
        /* 產業輪動 → 熱力：帶入 mkt／sector（空字串表示清除聚焦） */
        if (a.hasAttribute('data-sector')) {
          opts.sector = a.getAttribute('data-sector') || null;
        }
        if (a.hasAttribute('data-sector-key')) {
          opts.sectorKey = a.getAttribute('data-sector-key') || null;
        }
        routeTrace('click_received', {
          correlationId: traceId, from: 'pulse', to: target,
          label: opts._traceLabel
        });
        goRoute(target, opts);
      };
      a.onkeydown = function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          a.click();
        }
      };
    });
    body.querySelectorAll('[data-code]').forEach(function (el) {
      el.onclick = function () {
        var url = el.getAttribute('data-url');
        /* 美股列：有原文連結時另開分頁；台股重訊以開圖表為主 */
        if (url && (el.getAttribute('data-mkt') || '') === 'US' && el.classList.contains('row')) {
          window.open(url, '_blank', 'noopener');
        }
        openChart(el.getAttribute('data-code'), el.getAttribute('data-mkt') || 'TW');
      };
    });
    body.querySelectorAll('.pl-fac[data-fac]').forEach(function (el) {
      function toggle() { el.classList.toggle('open'); }
      el.onclick = toggle;
      el.onkeydown = function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      };
    });
  }

  function render(pack) {
    var body = ensureMount();
    if (!body) return;
    lastPack = pack;
    syncModeControls();
    var p = pack.pulse || {};
    var ov = p.overview || {};
    var movers = p.movers || {};

    var sub = $('pl-sub');
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (p.date ? ' · 廣度日 ' + p.date : '') +
        (p.updatedAt ? ' · ' + String(p.updatedAt).replace('T', ' ') : '');
    }
    _lastMacro = buildMacroFromPack(pack);
    maybeAnnounceFlip(_lastMacro);
    pushWd(false);
    enrichChainSpillover();

    /* 因子帳本改獨立頁 #factors，總覽維持一屏鎖定，禁止 pl-expanded 內嵌展開 */
    body.className = '';
    var extra = '';
    if (!sectorCache.TW && ov.sectorsRanked && ov.sectorsRanked.length) {
      sectorCache.TW = ov.sectorsRanked.slice();
    }

    if (pulseMode === 'beginner') {
      body.className = 'pl-mode-beginner';
      body.innerHTML = renderBeginner(ov, p);
      bind(body);
      bindBeginner();
      fillBeginnerInstitutional(ov, p);
      probeLayoutCols();
      return;
    }

    /* 一行五框 × 上下兩區（一屏鎖定）；兩排皆維持等寬欄位。 */
    body.className = 'pl-mode-expert';
    body.innerHTML =
      renderStrip(ov, p) +
      '<div class="pl-dash" data-layout="' + LAYOUT_CONTRACT + '">' +
        '<div class="pl-zone z-top">' +
          renderGauge(p) + renderOhlc(ov, p) + renderInst(ov) +
          renderDonut(ov, ov.strip) + renderSectors(ov) +
        '</div>' +
        '<div class="pl-zone z-bot">' +
          renderMovers(movers, 'gainers') + renderMovers(movers, 'losers') +
          renderGlobal(p) + renderFlash(p) + renderWatch(pack.wlQuotes, p.flash) +
        '</div>' +
      '</div>' +
      extra;

    probeLayoutCols();
    setTimeout(probeLayoutCols, 0);
    setTimeout(probeLayoutCols, 500);

    bind(body);
    body.querySelectorAll('[data-sec-mkt]').forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        loadSectorsMkt(b.getAttribute('data-sec-mkt'));
      };
    });
    body.querySelectorAll('[data-flash-mkt]').forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        flashMkt = b.getAttribute('data-flash-mkt') || 'ALL';
        if (lastPack) render(lastPack);
      };
    });
    var fq = $('pl-flash-q');
    if (fq) {
      fq.oninput = function () {
        flashQ = fq.value || '';
        if (!lastPack) return;
        var selStart = fq.selectionStart;
        var selEnd = fq.selectionEnd;
        render(lastPack);
        var again = $('pl-flash-q');
        if (again) {
          again.focus();
          try { again.setSelectionRange(selStart, selEnd); } catch (e) {}
        }
      };
      fq.onclick = function (e) { e.stopPropagation(); };
      fq.onkeydown = function (e) { e.stopPropagation(); };
    }
    body.querySelectorAll('[data-watch-mkt]').forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        watchMkt = b.getAttribute('data-watch-mkt') || 'ALL';
        if (lastPack) render(lastPack);
      };
    });
    if (sectorMkt === 'TW') bindSectorMoverLink(body);
    if (sectorMkt === 'US' && !sectorCache.US) loadSectorsMkt('US');
    fillInstTrend(ov);
    fillBreadthTrend(ov);

    jget('/pulse/history?kind=index&n=20').then(function (h) {
      var chart = $('pl-ohlc-chart') || $('pl-spark');
      var meta = $('pl-ohlc-trend-meta');
      if (!chart) return;
      var rows = ((h && h.rows) || []).slice().reverse();
      var closes = rows.map(function (r) { return r.close; }).filter(function (c) {
        return c != null && isFinite(c);
      });
      chart.innerHTML = sparkSvg(closes);
      if (closes.length) {
        var last = closes[closes.length - 1];
        var lastTxt = Math.round(Number(last)).toLocaleString('en-US');
        chart.title = '加權 ^TWII 近 ' + closes.length + ' 日 · X：日 · Y：點 · 最新收 ' + lastTxt;
        if (meta) meta.textContent = '加權 · 近 ' + closes.length + ' 日 · 收 ' + lastTxt;
      } else if (meta) {
        meta.textContent = '無序列';
      }
    });
  }

  function warmCaches() {
    jget('/breadth');
    jget('/sectors?mkt=TW');
    jget('/marketflow');
    jget('/events');
  }

  function fetchWlQuotes() {
    var wl = readWatchlist();
    var tw = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(function (w) { return w.t; });
    var us = wl.filter(function (w) { return w.m === 'US'; }).map(function (w) { return w.t; });
    var tasks = [];
    if (tw.length) tasks.push(jget('/twquote-batch?codes=' + encodeURIComponent(tw.join(','))));
    else tasks.push(Promise.resolve(null));
    if (us.length) tasks.push(jget('/quote-batch?syms=' + encodeURIComponent(us.join(','))));
    else tasks.push(Promise.resolve(null));
    return Promise.all(tasks).then(function (arr) {
      var out = {};
      [arr[0], arr[1]].forEach(function (q) {
        if (!q || typeof q !== 'object') return;
        Object.keys(q).forEach(function (k) { out[k] = q[k]; });
      });
      return out;
    });
  }

  function refresh(force) {
    var body = ensureMount();
    if (!body) return;
    var btn = $('pl-refresh');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '↻ 更新中…';
    }
    // stale-while-revalidate：已有畫面時不整頁清空（體感延遲主因）
    if (!lastPack) {
      body.innerHTML = '<div class="pl-loading">載入總覽儀表板…</div>';
    } else {
      var tone = $('pl-tone');
      if (tone && tone.textContent.indexOf('更新中') < 0) {
        tone.textContent = (tone.textContent || '—') + ' · 更新中…';
      }
    }
    // 手動刷新打穿聚合快取；子源（movers/global/macro）仍走各自 TTL，伺服器側預算 ≤8s
    var q = force ? '/pulse?refresh=1' : '/pulse';
    var t0 = Date.now();
    Promise.all([jget(q), fetchWlQuotes()]).then(function (arr) {
      var pulse = arr[0];
      if (!pulse || !pulse.ok) {
        if (!lastPack) {
          body.innerHTML = '<div class="pl-note">脈動載入失敗' +
            (pulse && pulse.error ? '：' + pulse.error : '（請重啟 server）') +
            ' <button type="button" class="pl-btn" id="pl-retry">重試</button></div>';
          var retry = $('pl-retry');
          if (retry) retry.onclick = function () { refresh(true); };
        }
        warmCaches();
        return;
      }
      if (window.MarketData && window.MarketData.fromPulse) window.MarketData.fromPulse(pulse);
      if (window.DecisionData && window.DecisionData.fromPulse) window.DecisionData.fromPulse(pulse);
      render({ pulse: pulse, wlQuotes: arr[1] || {} });
      var ms = Date.now() - t0;
      var sub = $('pl-sub');
      if (sub) sub.textContent = (sub.textContent || '') + ' · ' + ms + 'ms';
      // 資料不完整：只暖快取 + soft 再取；禁止再打 refresh=1（舊邏輯會再卡 20s+）
      if ((pulse.dataCompleteness != null && pulse.dataCompleteness < 90) || !pulse.breadthOk) {
        warmCaches();
        setTimeout(function () {
          if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') {
            jget('/pulse').then(function (p2) {
              if (p2 && p2.ok) render({ pulse: p2, wlQuotes: arr[1] || {} });
            });
          }
        }, 1600);
      }
    }).finally(function () {
      var b = $('pl-refresh');
      if (b) {
        b.disabled = false;
        b.textContent = '↻ 重新整理';
      }
    });
  }

  function activate() {
    ensureMount();
    refresh(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') refresh(false);
    }, 50000);
  }

  function deactivate() {
    if (timer) { clearInterval(timer); timer = null; }
    showFactors = false;
    var body = $('pl-body');
    if (body) {
      body.className = '';
      body.classList.remove('pl-expanded');
    }
    var extra = document.querySelector('#pl-root .pl-extra');
    if (extra && extra.parentNode) extra.parentNode.removeChild(extra);
  }

  window.PulseV5 = {
    activate: activate,
    deactivate: deactivate,
    refresh: function () { refresh(true); },
    formatYiCompact: formatYiCompact,
    buildWatchThemeResonance: buildWatchThemeResonance,
    /** 相容舊呼叫：改導向獨立因子頁 */
    focusFactors: function () {
      if (window.ShellV5 && ShellV5.go) ShellV5.go('factors');
      else goRoute('factors');
    },
    last: function () { return lastPack; }
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'pulse') activate();
  });
  window.addEventListener('resize', function () {
    if (layoutResizeTimer) clearTimeout(layoutResizeTimer);
    layoutResizeTimer = setTimeout(probeLayoutCols, 120);
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();
