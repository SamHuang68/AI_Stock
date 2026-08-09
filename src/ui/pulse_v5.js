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

  var SRV = window.SERVER || '';
  var timer = null;
  var lastPack = null;
  var showFactors = false;
  var sectorMkt = 'TW';
  var sectorCache = { TW: null, US: null };
  var flashMkt = 'ALL'; /* ALL | TW | US */
  var flashQ = '';      /* 快訊關鍵字（代號／標題） */
  var watchMkt = 'ALL'; /* ALL | TW | US */
  var _lastMacro = null;
  var _prevBand = null;

  function $(id) { return document.getElementById(id); }

  /** 實測 DOM 欄數；用於分辨「程式是五框但本機仍載到舊兩框 JS」 */
  function probeLayoutCols() {
    var zones = document.querySelectorAll('#pl-root .pl-zone');
    var parts = [];
    var ok = zones.length === 2;
    for (var i = 0; i < zones.length; i++) {
      var z = zones[i];
      var gtc = window.getComputedStyle(z).gridTemplateColumns || '';
      var cols = (gtc && gtc !== 'none') ? gtc.trim().split(/\s+/).length : 0;
      var kids = z.children ? z.children.length : 0;
      parts.push(cols + '/' + kids);
      if (cols !== 5 || kids !== 5) ok = false;
    }
    var probe = $('pl-layout-probe');
    if (probe) {
      probe.textContent = ok
        ? ('實測 5+5 · ' + LAYOUT_CONTRACT)
        : ('⚠實測 ' + (parts.join(' + ') || '0') + ' · 非五框＝舊 JS／舊 server');
      probe.style.borderColor = ok ? 'rgba(34,211,238,.45)' : 'rgba(248,113,113,.65)';
      probe.style.color = ok ? '#67e8f9' : '#fecaca';
      probe.style.background = ok ? 'rgba(34,211,238,.12)' : 'rgba(248,113,113,.15)';
      probe.title = LAYOUT_ANCHOR;
    }
    try {
      console.log('[pulse-v5] ' + LAYOUT_ANCHOR + ' contract=' + LAYOUT_CONTRACT +
        ' probe=' + (parts.join('+') || 'none') + ' ok=' + ok);
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
      '#pl-root .pl-tone{margin:0;font-size:10px;font-weight:700}' +
      '#pl-root .pl-wd{margin:0;font-size:9px;color:var(--tlo)}' +
      '#pl-root .pl-wd b{color:var(--cyan)}' +
      '#pl-root .pl-btn.wd{border-color:rgba(103,232,249,.35);color:var(--cyan)}' +
      '#pl-root .pl-ai{margin:4px 0 0;padding:6px 8px;background:var(--bg2);border:1px solid var(--border);border-radius:6px;flex:0 0 auto}' +
      '#pl-root .pl-ai h4{margin:0 0 4px;font-size:9px;color:var(--gold);letter-spacing:1px;display:flex;justify-content:space-between;align-items:center}' +
      '#pl-root .pl-ai .pl-ai-body{font-size:10px;line-height:1.55;color:var(--text);min-height:2em;white-space:pre-wrap}' +
      '#pl-root .pl-ai .pl-ai-meta{margin-top:4px;font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '#pl-root .pl-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;flex:0 0 auto;white-space:nowrap}' +
      '#pl-root .pl-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .pl-btn.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .up{color:var(--red)}#pl-root .dn{color:var(--green)}#pl-root .flat{color:var(--tlo)}' +
      /* 盤面多空／偏強弱：台股慣例紅漲綠跌（與 .up/.dn 對齊） */
      '#pl-root .pl-bias-bull{color:var(--red)}#pl-root .pl-bias-bear{color:var(--green)}' +
      '#pl-root .pl-bias-mid{color:#94a3b8}' +
      /* 體質／風險分數：金／青，勿當漲跌色 */
      '#pl-root .pl-st-pos{color:var(--gold)}#pl-root .pl-st-risk{color:var(--cyan)}' +
      '#pl-root .pl-st-mid{color:#94a3b8}' +
      /* 三排平均分（頂 KPI／中決策／底列表各 1fr）；溢出可下拉，避免硬裁切遮蔽 */
      '#pl-body{flex:1;min-height:0;display:grid!important;' +
        'grid-template-rows:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr);gap:6px;overflow:auto}' +
      '#pl-body.pl-expanded{overflow:auto;grid-template-rows:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) auto}' +
      /* KPI 頂列：格內 flex，spark 吃剩餘高度 */
      '#pl-root .pl-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;' +
        'margin:0;min-width:0;min-height:0;height:100%;align-items:stretch}' +
      '#pl-root .pl-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:4px 6px;min-width:0;min-height:0;' +
        'overflow:hidden;display:flex;flex-direction:column;height:100%;box-sizing:border-box}' +
      '#pl-root .pl-strip .cell.hero{border-color:rgba(245,197,24,.35);' +
        'background:linear-gradient(180deg,rgba(28,38,58,.98),rgba(14,22,38,.98));box-shadow:inset 0 1px 0 rgba(245,197,24,.08)}' +
      '#pl-root .pl-strip .k{font-size:8px;color:#a8b6c8;letter-spacing:.3px;margin-bottom:1px;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:0 0 auto}' +
      '#pl-root .pl-strip .v{font-size:14px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums;' +
        'margin-bottom:1px;flex:0 0 auto}' +
      '#pl-root .pl-strip .cell.hero .v{font-size:15px;letter-spacing:-0.2px}' +
      '#pl-root .pl-strip .s{font-size:9px;margin-top:0;font-weight:800;line-height:1.25;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums;flex:0 0 auto}' +
      '#pl-root .pl-strip .s .pl-subq{font-size:7px;font-weight:600;color:#94a3b8;margin-left:3px}' +
      '#pl-root .pl-strip .badge{display:inline-flex;align-items:center;gap:3px;font-size:8px;color:var(--cyan)}' +
      '#pl-root .pl-strip .dot{width:4px;height:4px;border-radius:50%;background:var(--cyan);box-shadow:0 0 4px var(--cyan);flex-shrink:0}' +
      '#pl-root .pl-strip .viz-hide,#pl-root .pl-strip .viz-meter,#pl-root .pl-strip .viz-seg,' +
        '#pl-root .pl-strip .viz-chip{display:none!important}' +
      '#pl-root .pl-strip .pl-ttabs{flex:0 0 auto;max-height:2.6em;overflow:hidden}' +
      '#pl-root .pl-strip .vz-meter{margin-top:1px;height:3px;flex:0 0 auto}' +
      '#pl-root .pl-strip .pl-turn-meter{flex:1 1 0;min-height:18px;margin-top:2px;display:flex;align-items:center}' +
      '#pl-root .pl-strip .pl-turn-meter .vz-ref{margin:0;height:6px;width:100%;flex:1 1 auto}' +
      '#pl-root .pl-strip .pl-turn-meter .vz-ref .vz-tick-lbl{display:none}' +
      '#pl-root .pl-strip .pl-idx-spark{flex:1 1 0;min-height:22px;margin-top:2px;opacity:.95;' +
        'min-width:0;overflow:hidden;display:flex;align-items:stretch}' +
      '#pl-root .pl-strip .pl-idx-spark .vz-spark{width:100%;height:100%;min-height:22px;display:block;margin:0}' +
      '#pl-root .pl-strip .vz-chip{display:none!important}' + /* 單顆 chip 改為全型態 tab 列 */
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
      /* dash 透傳：z-top／z-bot 成為 body 的第 2／3 列，三排等分 */
      '#pl-root .pl-dash{display:contents}' +
      '#pl-root .pl-zone{display:grid;gap:6px;min-width:0;min-height:0;' +
        'grid-template-columns:repeat(5,minmax(0,1fr));align-content:stretch}' +
      '#pl-root .z-bot .pl-sec{padding:6px 8px}' +
      '#pl-root .z-bot .pl-sec h4{margin:0 0 4px}' +
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
        'font-size:8px;color:#a8b6c8;flex:0 0 auto;margin-bottom:3px;' +
        'display:flex;justify-content:space-between;gap:4px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-inst-trend .lab > span:last-child,#pl-root .pl-bd-trend .lab > span:last-child,' +
        '#pl-root .pl-ohlc-trend .lab > span:last-child{' +
        'min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-inst-trend .chart,#pl-root .pl-bd-trend .chart,#pl-root .pl-ohlc-trend .chart{' +
        'flex:1 1 0;min-height:0;min-width:0;overflow:hidden;position:relative}' +
      '#pl-root .pl-inst-trend .chart .vz-spark-ax,#pl-root .pl-bd-trend .chart .vz-spark-ax,' +
        '#pl-root .pl-ohlc-trend .chart .vz-spark-ax{' +
        'height:100%;min-height:0;max-width:100%;min-width:0;overflow:hidden}' +
      '#pl-root .pl-inst-trend .chart .vz-yunit,#pl-root .pl-inst-trend .chart .vz-ylabs,' +
        '#pl-root .pl-bd-trend .chart .vz-yunit,#pl-root .pl-bd-trend .chart .vz-ylabs,' +
        '#pl-root .pl-ohlc-trend .chart .vz-yunit,#pl-root .pl-ohlc-trend .chart .vz-ylabs{font-size:6px}' +
      '#pl-root .pl-inst-trend .chart .vz-plot,#pl-root .pl-bd-trend .chart .vz-plot,' +
        '#pl-root .pl-ohlc-trend .chart .vz-plot{min-width:0;min-height:0;overflow:hidden}' +
      '#pl-root .pl-inst-trend .chart .vz-plot svg,#pl-root .pl-bd-trend .chart .vz-plot svg,' +
        '#pl-root .pl-ohlc-trend .chart .vz-plot svg{' +
        'width:100%;height:100%;min-width:0;min-height:0;' +
        'max-width:100%;max-height:100%;margin:0;display:block;box-sizing:border-box}' +
      '#pl-root .pl-inst-cmt,#pl-root .pl-bd-cmt,#pl-root .pl-ohlc-cmt{' +
        'font-size:8px;line-height:1.35;color:var(--text);margin-top:2px;flex:0 0 auto;' +
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
      '#pl-root .pl-list .nm{color:var(--thi);font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:8px}' +
      '#pl-root .pl-list .cd{color:#a8b6c8;font-size:7px;margin-right:2px}' +
      '#pl-root .pl-list .ind{display:inline-block;margin-left:2px;padding:0 2px;border-radius:3px;font-size:6px;font-weight:700;' +
        'color:var(--cyan);background:rgba(56,189,248,.08);border:1px solid rgba(56,189,248,.25);vertical-align:1px}' +
      '#pl-root .pl-movers .pl-list li > span:last-child{flex:0 0 auto;white-space:nowrap;font-size:8px;' +
        'font-variant-numeric:tabular-nums;letter-spacing:-0.25px}' +
      '#pl-root .pl-movers .pl-sec-hint,#pl-root .pl-movers h4 > span{font-size:7px!important}' +
      '#pl-root .pl-movers .vz-chip{font-size:6px;padding:0 3px;line-height:1.2}' +
      '#pl-root .pl-movers .vz-rowbar{max-width:36px;height:3px;margin-left:2px}' +
      /* global：代號優先可見；漲跌欄不得擠掉 abbr；內容可捲 */
      '#pl-root .pl-global{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px;flex:1 1 0;' +
        'align-content:start;overflow:auto;overscroll-behavior:contain;min-height:0;min-width:0}' +
      '#pl-root .pl-kicker{display:none!important}' +
      '#pl-root .pl-global .g{background:rgba(6,10,18,.45);border:1px solid rgba(42,61,92,.7);border-radius:4px;' +
        'padding:3px 4px;min-width:0;overflow:hidden;display:flex;flex-direction:column;gap:1px}' +
      '#pl-root .pl-global .g .k{font-size:8px;color:var(--tlo);margin-bottom:0;flex:0 0 auto;' +
        'display:flex;justify-content:flex-start;gap:2px;align-items:baseline;min-width:0}' +
      '#pl-root .pl-global .g .k .abbr{color:var(--thi);font-weight:800;letter-spacing:0;' +
        'flex:0 0 auto;min-width:2em;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-global .g .k .role{display:none}' +
      '#pl-root .pl-global .g .row{display:flex;align-items:baseline;justify-content:space-between;gap:4px;min-width:0;flex:0 0 auto}' +
      '#pl-root .pl-global .g .v{font-size:8px;font-weight:800;color:var(--thi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
        'min-width:0;flex:1 1 auto;font-variant-numeric:tabular-nums;letter-spacing:-0.2px}' +
      '#pl-root .pl-global .g .s{font-size:7px;font-weight:700;flex:0 1 auto;white-space:nowrap;text-align:right;letter-spacing:-0.2px;' +
        'font-variant-numeric:tabular-nums;min-width:0;max-width:46%;overflow:hidden;text-overflow:ellipsis}' +
      /* 市場快訊：縮字＋單行；市場 tab 與自選風險同級（7px） */
      '#pl-root .pl-flash-tools{display:flex;align-items:center;gap:3px;flex:1 1 auto;min-width:0;justify-content:flex-end}' +
      '#pl-root #pl-flash-sec .pl-sec-tog button{font-size:7px;padding:1px 5px}' +
      '#pl-root .pl-flash-q{width:64px;min-width:48px;max-width:88px;padding:1px 4px;border:1px solid var(--border);border-radius:3px;' +
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
      '#pl-root .pl-wl .pl-sec-tog button{font-size:7px;padding:1px 5px}' +
      '#pl-root .pl-wl-scroll{flex:1 1 0;min-height:0;overflow:auto;overscroll-behavior:contain}' +
      '#pl-root .pl-wl table{width:100%;border-collapse:collapse;font-size:8px;table-layout:fixed}' +
      '#pl-root .pl-wl th,#pl-root .pl-wl td{padding:4px 4px;border-bottom:1px solid rgba(26,39,64,.85);text-align:right;' +
        'line-height:1.25}' +
      '#pl-root .pl-wl th:first-child,#pl-root .pl-wl td:first-child{text-align:left}' +
      '#pl-root .pl-wl th{color:#a8b6c8;position:sticky;top:0;background:rgba(17,27,46,.98);z-index:1;font-size:7px}' +
      '#pl-root .pl-wl tr{cursor:pointer}' +
      '#pl-root .pl-wl tr:nth-child(even){background:rgba(148,163,184,.035)}' +
      '#pl-root .pl-wl tr:hover{background:rgba(22,34,64,.88)}' +
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
      '#pl-root table.pillars th{color:var(--tlo)}';
  }

  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
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
  function moneyYi(v) {
    if (v == null || !isFinite(v)) return '—';
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (x >= 0 ? '+' : '') + x.toFixed(1) + ' 億';
  }
  /** tip 法人四格專用：省略「億」以免窄欄 ellipsis；完整值放 title */
  function moneyYiCell(v) {
    if (v == null || !isFinite(v)) return '—';
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
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

  function runAiSummary() {
    var box = $('pl-ai');
    var body = $('pl-ai-body');
    var st = $('pl-ai-st');
    var meta = $('pl-ai-meta');
    if (!box || !body) return;
    box.style.display = 'block';
    body.textContent = '思考中…（本機 /ai/local，首次載入可能較久）';
    if (st) st.textContent = 'LM Studio';
    if (meta) meta.textContent = '';

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
      '盤面語氣: ' + (m.tone || '未提供')
    ].join('\n');
    var prompt =
      '請用 4–6 句繁中，根據「目前提供的資料」做台股大盤即時語意解析：' +
      '1) 多空傾向 2) 廣度與體質是否背離 3) 供應鏈外溢與風險提示 4) 對進場侵略性（保守/均衡/積極）的建議。' +
      '不可編造未提供的數字。結尾加「⚠ 非投資建議」。';

    fetch(SRV + '/ai/local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prompt, context: ctx })
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      if (!r.body || !r.body.getReader) return r.text().then(function (t) { body.textContent = t; });
      var reader = r.body.getReader();
      var dec = new TextDecoder();
      var acc = '';
      body.textContent = '';
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) {
            if (!acc.trim()) {
              body.textContent = ruleFallbackSummary(m);
              if (st) st.textContent = '規則後援';
            } else if (meta) {
              meta.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') + ' · 本機 LLM';
            }
            return;
          }
          acc += dec.decode(res.value || new Uint8Array(), { stream: true });
          body.textContent = acc;
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      body.textContent = ruleFallbackSummary(m);
      if (st) st.textContent = '規則後援（LM Studio 未連線）';
      if (meta) meta.textContent = '可啟動 LM Studio Local Server 後再按 AI 摘要';
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
      twiiChg: (t00.changePct != null && isFinite(Number(t00.changePct))) ? Number(t00.changePct) : null
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
            '<div class="pl-tone" id="pl-tone">—</div>' +
            '<div class="pl-wd" id="pl-wd">WaveDeck 覆寫：—</div>' +
            '<div class="pl-sub" id="pl-sub">官方資料 · 一行五框 × 上下兩區 · ' + LAYOUT_ANCHOR + '</div>' +
          '</div><div class="pl-actions">' +
            '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
            '<button type="button" class="pl-btn wd" id="pl-push-wd" title="將廣度／體質推送到 WaveDeck">→ WD</button>' +
            '<button type="button" class="pl-btn wd" id="pl-ai-sum" title="本機 LLM 盤面摘要（/ai/local）">AI 摘要</button>' +
            '<button type="button" class="pl-btn" id="pl-toggle-fac">因子帳本</button>' +
            '<button type="button" class="pl-btn" data-go="breadth">廣度</button>' +
            '<button type="button" class="pl-btn" data-go="heat">熱力</button>' +
            '<button type="button" class="pl-btn" data-go="afterhours">盤後</button>' +
            '<button type="button" class="pl-btn primary" data-go="chart">圖表</button>' +
          '</div></div>' +
          '<div class="pl-ai" id="pl-ai" style="display:none">' +
            '<h4>大盤 AI 即時語意 <span id="pl-ai-st" style="font-weight:600;color:var(--tlo)"></span></h4>' +
            '<div class="pl-ai-body" id="pl-ai-body">—</div>' +
            '<div class="pl-ai-meta" id="pl-ai-meta"></div>' +
          '</div>' +
          '<div id="pl-body" class="pl-loading">載入總覽儀表板…</div>' +
        '</div>';
      var r = $('pl-refresh');
      if (r) r.onclick = function () { refresh(true); };
      var pwd = $('pl-push-wd');
      if (pwd) pwd.onclick = function () { pushWd(true); };
      var pai = $('pl-ai-sum');
      if (pai) pai.onclick = function () { runAiSummary(); };
      var tf = $('pl-toggle-fac');
      if (tf) tf.onclick = function () { focusFactors(); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          goRoute(b.getAttribute('data-go'), {
            sym: b.getAttribute('data-sym') || undefined,
            mkt: b.getAttribute('data-mkt') || undefined
          });
        };
      });
    }
    syncFactorBtn();
    return $('pl-body');
  }

  function syncFactorBtn() {
    var tf = $('pl-toggle-fac');
    if (!tf) return;
    tf.classList.toggle('on', !!showFactors);
    tf.setAttribute('aria-pressed', showFactors ? 'true' : 'false');
    tf.title = showFactors ? '捲動至因子帳本（再按一次可收合）' : '顯示因子帳本';
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

  /** 因子帳本：優先「顯示並捲動」；已顯示且已在視窗內則收合 */
  function focusFactors() {
    var el = $('pl-factors');
    if (showFactors && el) {
      var rect = el.getBoundingClientRect();
      var viewH = window.innerHeight || 800;
      var inView = rect.top < viewH * 0.85 && rect.bottom > 80;
      if (inView) {
        showFactors = false;
        syncFactorBtn();
        if (lastPack) render(lastPack);
        else refresh(false);
        return;
      }
      scrollToFactors();
      syncFactorBtn();
      return;
    }
    showFactors = true;
    syncFactorBtn();
    if (lastPack) render(lastPack);
    else refresh(false);
    // render 後下一幀再捲動（DOM 已掛上 #pl-factors）
    setTimeout(function () { scrollToFactors(); }, 40);
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

  function sparkSvg(closes) {
    if (!closes || closes.length < 2) {
      return '<div class="pl-note" style="padding:4px 0">近 20 日走勢尚在累積（同步資料後顯示）</div>';
    }
    var V = window.Viz;
    if (V && V.sparkLine) {
      return V.sparkLine(closes, {
        color: closes[closes.length - 1] >= closes[0] ? 'var(--red)' : 'var(--green)',
        h: 36, w: 200, compact: true,
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
      bits.push((tr.streak > 0 ? (streakUpLabel || '連漲') : (streakDnLabel || '連跌')) +
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
      main.push((tr.streak > 0 ? (streakUpLabel || '連漲') : (streakDnLabel || '連跌')) +
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
    var meter = (V && tr.momScore != null && V.scoreMeter) ? V.scoreMeter(tr.momScore) : '';
    var spark = '';
    if (V && V.sparkLine && tr.spark && tr.spark.length >= 2) {
      spark = '<div class="pl-idx-spark">' + V.sparkLine(tr.spark, {
        h: 48, w: 160, grid: false, marks: false, pad: 3, strokeWidth: 2.4,
        color: (tr.spark[tr.spark.length - 1] >= tr.spark[0]) ? 'var(--red)' : 'var(--green)'
      }) + '</div>';
    }
    var fullBits = trendQuantBits(tr, opts.streakUpLabel, opts.streakDnLabel);
    var subHtml = trendPrimarySub(tr, opts.streakUpLabel, opts.streakDnLabel);
    if (!subHtml && opts.fallbackSub) subHtml = opts.fallbackSub;
    if (!subHtml) subHtml = '—';
    var tip = (opts.tip || '趨勢量化：vs前日／vs5日均／動能分／近20日Z／連續漲跌') +
      (tone ? (' · 當前 ' + tone) : '') +
      (fullBits ? (' · ' + fullBits) : '');
    var levelHtml = tr.level
      ? ' <span style="font-size:9px;color:#94a3b8;font-weight:700">' + esc(tr.level) + '</span>'
      : '';
    var toneCls = tw(tr.chgPct != null ? tr.chgPct : tr.vsMa5Pct);
    return '<div class="cell' + (opts.hero ? ' hero' : '') + '" title="' + esc(tip) + '">' +
      '<div class="k">' + opts.k + '</div>' +
      '<div class="v">' + opts.vHtml + levelHtml + '</div>' +
      '<div class="s ' + toneCls + '">' + subHtml + '</div>' +
      tabs + meter + spark + '</div>';
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
    var txfTip = idxTip + ' · 台指期 · Basis＝期貨−現貨（正價差／逆價差）';
    return '<div class="pl-strip">' +
      renderTrendCell({
        k: '加權指數 TAIEX', hero: true,
        vHtml: fmt(t00.price, 0),
        trend: t00Tr, fallbackSub: t00Fb, tip: idxTip + ' · 加權'
      }) +
      renderTrendCell({
        k: '櫃買指數 OTC',
        vHtml: fmt(o00.price, 0),
        trend: o00Tr, fallbackSub: o00Fb, tip: idxTip + ' · 櫃買'
      }) +
      renderTrendCell({
        k: '台指期 TXF' + (txfSess ? ' · ' + txfSess : '') +
          (basisPts != null && isFinite(basisPts)
            ? (' · Basis ' + (basisPts >= 0 ? '+' : '') + Number(basisPts).toFixed(1))
            : ''),
        hero: true,
        vHtml: fmt(txf.price, 0),
        trend: txfTr, fallbackSub: txfFb, tip: txfTip
      }) +
      '<div class="cell hero" title="' + turnTip + '"><div class="k">成交金額 · 量能</div><div class="v">' +
        (s.turnoverYi != null ? Math.round(Number(s.turnoverYi)).toLocaleString('en-US') + ' 億' : '—') +
        (s.turnoverLevel ? ' <span style="font-size:9px;color:#94a3b8;font-weight:700">' + esc(s.turnoverLevel) + '</span>' : '') +
        '</div>' +
        '<div class="s ' + tw(s.turnoverVsMa5Pct != null ? s.turnoverVsMa5Pct : s.turnoverChgPct) + '">' +
          turnSub + '</div>' + turnTabs +
        '<div class="pl-idx-spark pl-turn-meter" title="' + turnTip + '">' + turnMeter + '</div></div>' +
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
    return '<div class="pl-sec" data-pri="p0"><h4>市場脈動 <a data-go="pulse">因子 →</a></h4>' +
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
    if (!parts.length) parts.push('櫃買／台指期見頂列');
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
      ? ('近 ' + t00Tr.spark.length + ' 日 · Y：點')
      : '載入…';
    return '<div class="pl-sec" data-pri="p0"><h4>加權盤勢' +
      '<span class="pl-sec-hint">櫃買／台指期見頂列</span>' +
      '<a data-go="chart" data-sym="^TWII" data-mkt="TW">圖表 →</a></h4>' +
      '<div class="pl-ohlc4" id="pl-ohlc4">' +
        '<div class="c" title="當日開盤（整數點）"><div class="k">開盤</div><div class="v">' + fmt(o.open, 0) + '</div></div>' +
        '<div class="c" title="當日最高（整數點）"><div class="k">最高</div><div class="v">' + fmt(o.high, 0) + '</div></div>' +
        '<div class="c" title="當日最低（整數點）"><div class="k">最低</div><div class="v">' + fmt(o.low, 0) + '</div></div>' +
        '<div class="c" title="昨收（整數點）"><div class="k">昨收</div><div class="v">' + fmt(o.prevClose, 0) + '</div></div>' +
      '</div>' +
      '<div class="pl-ohlc-trend" id="pl-ohlc-trend">' +
        '<div class="lab"><span>近 20 日 · 點</span><span id="pl-ohlc-trend-meta">' + metaBoot + '</span></div>' +
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
        badge.title = '當日法人尚未公布 · 顯示前一交易日籌碼';
      } else if (opts.pending) {
        badge.hidden = false;
        badge.textContent = '當日尚未公布';
        badge.title = '夜盤／假日常見 · 正在載入前一交易日籌碼';
      } else {
        badge.hidden = true;
        badge.textContent = '';
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
    return '<div class="pl-sec" data-pri="p0"><h4>法人資金' +
      '<span class="pl-stale" id="pl-inst-stale"' + (empty ? '' : ' hidden') + '>' +
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
      ' <a data-go="heat">熱力 →</a></h4><div class="pl-fill" id="pl-sectors-body">' +
      (usOn ? '' : '<div class="pl-note" style="margin:0 0 3px">懸停高亮同產業近漲跌停</div>');
    if (!list.length) {
      return html + '<div class="pl-note">' + (usOn ? '美股產業載入中…' : '類股資料暫缺 — 開啟熱力可預熱') +
        '</div></div></div>';
    }
    list.slice(0, 10).forEach(function (s) {
      var w = Math.max(4, Math.round(Math.abs(s.changePct) / maxAbs * 100));
      /* 台股紅漲綠跌；美股綠漲紅跌 */
      var upCol = usOn ? 'var(--green)' : 'var(--red)';
      var dnCol = usOn ? 'var(--red)' : 'var(--green)';
      var col = (s.changePct || 0) >= 0 ? upCol : dnCol;
      /* US：綠漲紅跌 → 借用 .dn/.up 顏色類別對調 */
      var pcCls = usOn
        ? ((s.changePct || 0) > 0 ? 'dn' : (s.changePct || 0) < 0 ? 'up' : 'flat')
        : tw(s.changePct);
      var sk = sectorKey(s.name);
      html += '<div class="pl-sbar" data-sector="' + esc(s.name || '') + '" data-sector-key="' + esc(sk) + '"' +
        ' title="' + esc(s.name || '') + (usOn ? '' : ' — 懸停聯動近漲跌停') + '">' +
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
    var html = '<div class="pl-sec pl-movers" data-pri="p1" data-movers-side="' + side + '"><h4>' + title +
      (movers && movers.date ? ' <span class="pl-sec-hint" style="margin-right:0">' + movers.date + '</span>' : '') +
      (note ? ' <span class="pl-sec-hint" style="margin-right:0">' + note + '</span>' : '') +
      ' <a data-go="afterhours">盤後 →</a></h4><ul class="pl-list">';
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
    var html = '<div class="pl-sec"><h4>全球影響' +
      ' <span class="' + biasCls(tone) + '" style="font-weight:700;font-size:9px;margin-left:4px">' + tone + '</span>' +
      ' <a data-go="international">國際 →</a></h4><div class="pl-global">';
    if (!items.length) html += '<div class="pl-note">國際報價載入中…</div>';
    items.slice(0, 14).forEach(function (x) {
      var dig = (x.unit === '%' || x.symbol === 'US10Y' || x.symbol === '^VIX' || x.symbol === 'TWD=X' ||
        x.symbol === 'HG=F' || x.symbol === 'CL=F') ? 2
        : (x.price > 1000 ? 0 : 2);
      if (x.symbol === 'TWD=X') dig = 3;
      if (x.symbol === 'GC=F') dig = 0;
      var px = fmt(x.price, dig) + (x.unit === '%' || x.symbol === 'US10Y' ? '%' : '');
      var abbr = globalAbbr(x);
      var chgFull = globalChgLabel(x, dig);
      /* 畫面只顯％，完整「點·％」掛 title，避免右側欄擠掉代號 */
      var chgShort = (x.changePct != null && isFinite(Number(x.changePct)))
        ? pct(x.changePct, 1) : (chgFull === '—' ? '—' : chgFull);
      var full = (x.name || x.symbol || abbr) + (x.role ? ' · ' + x.role : '') +
        (x.price != null ? (' · ' + px) : '') +
        (chgFull && chgFull !== '—' ? (' · ' + chgFull) : '');
      html += '<div class="g" title="' + esc(full) + '">' +
        '<div class="k"><span class="abbr">' + esc(abbr) + '</span>' +
          (x.role ? '<span class="role">' + esc(x.role) + '</span>' : '') +
        '</div>' +
        '<div class="row">' +
          '<div class="v" title="點位">' + px + '</div>' +
          '<div class="s ' + tw(x.changePct) + '" title="' + esc(chgFull) + '">' +
            chgShort +
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
    var html = '<div class="pl-sec" id="pl-flash-sec"><h4>市場快訊' +
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
      html += '<div class="row"' +
        (f.code ? ' data-code="' + esc(f.code) + '"' : '') +
        (f.mkt ? ' data-mkt="' + esc(f.mkt) + '"' : '') +
        (f.url ? ' data-url="' + esc(f.url) + '"' : '') +
        ' title="' + esc(title) + '">' +
        '<span class="t">' + esc(f.time || '') + '</span>' +
        '<span class="' + catCls + '">[' + esc(f.cat || (isUs ? '美股' : '重訊')) + ']</span>' +
        '<span class="ttl">' + esc(title) + '</span></div>';
    });
    return html + '</div></div>';
  }

  function watchTag(cp) {
    if (cp == null || !isFinite(cp)) return '';
    if (cp >= 3) return '<span class="pl-tag hot" title="機會 · 漲幅 ≥ 3%">機會</span>';
    if (cp <= -3) return '<span class="pl-tag cold" title="風險 · 跌幅 ≤ -3%">風險</span>';
    return '<span class="pl-tag ok" title="觀察">觀察</span>';
  }

  function renderWatch(quotes) {
    var wlAll = readWatchlist();
    var wl = filterWatchlist(wlAll);
    var nTw = wlAll.filter(function (w) { return !watchIsUs(w); }).length;
    var nUs = wlAll.filter(watchIsUs).length;
    var html = '<div class="pl-sec pl-wl" id="pl-watch-sec" data-pri="p1"><h4>自選風險' +
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
      var q = (quotes && (quotes[w.t] || quotes[w.t + '.TW'] || quotes[w.t + '.TWO'])) || {};
      var px = q.price != null ? q.price : w.price;
      var cp = q.changePct != null ? q.changePct : w.chg;
      var dig = mkt === 'US' ? 2 : (px != null && Number(px) >= 1000 ? 1 : 2);
      var unit = mkt === 'US' ? '<span class="mkt">USD</span>' : '';
      /* 美股漲跌色：綠漲紅跌（與產業 US 一致） */
      var cpCls = mkt === 'US'
        ? ((cp > 0) ? 'dn' : (cp < 0) ? 'up' : 'flat')
        : tw(cp);
      html += '<tr data-code="' + esc(w.t) + '" data-mkt="' + esc(mkt) + '">' +
        '<td style="color:var(--gold);font-weight:700">' +
          esc(w.t) + unit +
          (w.name ? '<span class="nm-only" title="' + esc(w.name) + '">' + esc(w.name) + '</span>' : '') +
        '</td><td class="px">' + fmt(px, dig) + '</td><td class="chg ' + cpCls + '">' + pct(cp) + '</td>' +
        '<td class="tag">' + watchTag(cp) + '</td></tr>';
    });
    return html + '</table></div></div>';
  }

  function renderFactors(p) {
    if (!showFactors) {
      return '<div id="pl-factors" class="pl-factors" hidden></div>';
    }
    var rows = p.marketRows || [];
    var nPos = (p.positiveFactors || []).length;
    var nRisk = (p.riskFactors || []).length;
    var nPend = (p.pendingFactors || []).length;
    var pillars = '<div class="pl-sec"><h4>體質支柱</h4>';
    if (!rows.length) pillars += '<div class="pl-note">支柱尚未就緒</div></div>';
    else {
      pillars += '<table class="pillars"><tr><th>項目</th><th>數值</th><th>評分</th></tr>';
      rows.forEach(function (r) {
        pillars += '<tr><td>' + (r.k || '') + '</td><td>' + (r.v || '—') + '</td><td>' +
          (r.score != null ? Number(r.score).toFixed(1) : '—') + '</td></tr>';
      });
      pillars += '</table></div>';
    }
    return '<div id="pl-factors" class="pl-factors">' +
      '<div class="pl-sec-title">因子帳本 · 正 ' + nPos + ' / 風險 ' + nRisk + ' / 未納入 ' + nPend + '</div>' +
      pillars +
      '<div class="pl-three">' +
        factorCol('正面因素', 'sc-pos', p.positiveFactors, '尚無') +
        factorCol('風險因素', 'sc-risk', p.riskFactors, '尚無') +
        factorCol('尚未納入', 'sc-pend', p.pendingFactors, '無') +
      '</div>' +
      '<div class="pl-note">分數來自 /pulse 因子帳本；點單列展開細節，頂列「因子帳本」可再次捲動至此。</div>' +
    '</div>';
  }

  function bind(body) {
    body.querySelectorAll('[data-go]').forEach(function (a) {
      a.onclick = function (e) {
        e.preventDefault();
        goRoute(a.getAttribute('data-go'), {
          sym: a.getAttribute('data-sym') || undefined,
          mkt: a.getAttribute('data-mkt') || undefined
        });
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
    var p = pack.pulse || {};
    var ov = p.overview || {};
    var movers = p.movers || {};

    var sub = $('pl-sub');
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (p.date ? ' · 廣度日 ' + p.date : '') +
        (p.updatedAt ? ' · ' + String(p.updatedAt).replace('T', ' ') : '');
    }
    var toneEl = $('pl-tone');
    if (toneEl) {
      /* 盤面語氣：偏多紅／偏空綠／中性灰（與漲跌慣例一致） */
      toneEl.className = 'pl-tone ' + biasCls(p.tone);
      toneEl.textContent = p.tone || '資料彙整中';
    }

    _lastMacro = buildMacroFromPack(pack);
    maybeAnnounceFlip(_lastMacro);
    pushWd(false);
    enrichChainSpillover();

    body.className = showFactors ? 'pl-expanded' : '';
    var extra = '';
    if (showFactors) {
      extra =
        '<div class="pl-extra">' +
          renderFactors(p) +
          '<div id="pl-hist" class="pl-loading" style="margin-top:6px">載入脈動歷史…</div>' +
        '</div>';
    }
    if (!sectorCache.TW && ov.sectorsRanked && ov.sectorsRanked.length) {
      sectorCache.TW = ov.sectorsRanked.slice();
    }

    /* 一行五框 × 上下兩區（一屏鎖定）— 錨點 3cab212，禁止改 2/4 欄 */
    body.innerHTML =
      renderStrip(ov, p) +
      '<div class="pl-dash" data-layout="' + LAYOUT_CONTRACT + '">' +
        '<div class="pl-zone z-top">' +
          renderGauge(p) + renderOhlc(ov, p) + renderInst(ov) +
          renderDonut(ov, ov.strip) + renderSectors(ov) +
        '</div>' +
        '<div class="pl-zone z-bot">' +
          renderMovers(movers, 'gainers') + renderMovers(movers, 'losers') +
          renderGlobal(p) + renderFlash(p) + renderWatch(pack.wlQuotes) +
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
        chart.title = '加權近 ' + closes.length + ' 日 · X：日 · Y：點 · 最新收 ' + lastTxt;
        if (meta) meta.textContent = '近 ' + closes.length + ' 日 · 收 ' + lastTxt;
      } else if (meta) {
        meta.textContent = '無序列';
      }
    });

    jget('/pulse/history?kind=pulse&n=12').then(function (h) {
      var V = window.Viz;
      var box = $('pl-hist');
      if (!box) return;
      var rows = (h && h.rows) || [];
      if (!rows.length) {
        box.className = 'pl-note';
        box.textContent = '脈動歷史尚在累積 — 按頂列「同步資料」預抓指數／廣度／法人後，每日 /pulse 會自動 merge 分數。';
        return;
      }
      var chrono = rows.slice().reverse();
      var healthSeries = chrono.map(function (r) { return r.health; });
      var riskSeries = chrono.map(function (r) { return r.risk; });
      var sparks = '';
      if (V) {
        var hSpark = healthSeries.filter(function (v) { return v != null && isFinite(v); }).length >= 2
          ? V.sparkLine(healthSeries, { color: 'var(--gold)', xUnit: '日', yUnit: '分', yDigits: 0 }) : '';
        var rSpark = riskSeries.filter(function (v) { return v != null && isFinite(v); }).length >= 2
          ? V.sparkLine(riskSeries, { color: 'var(--cyan)', xUnit: '日', yUnit: '分', yDigits: 0 }) : '';
        if (hSpark || rSpark) {
          sparks = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">' +
            (hSpark ? '<div><div style="font-size:9px;color:var(--tlo)">大盤體質（X：日 · Y：分）</div>' + hSpark + '</div>' : '') +
            (rSpark ? '<div><div style="font-size:9px;color:var(--tlo)">風險（X：日 · Y：分）</div>' + rSpark + '</div>' : '') +
            '</div>';
        }
      }
      var html = '<div class="pl-sec"><h4>市場脈搏歷史（本機庫）</h4>' + sparks +
        '<table style="width:100%;border-collapse:collapse;font-size:11px">' +
        '<tr style="color:var(--tlo)"><th style="text-align:left;padding:4px">日期</th>' +
        '<th style="padding:4px">體質</th><th style="padding:4px">風險</th><th style="padding:4px">綜合</th>' +
        '<th style="padding:4px">可靠度</th><th style="padding:4px">狀態</th></tr>';
      rows.forEach(function (r) {
        html += '<tr><td style="padding:4px">' + esc(r.date) + '</td><td style="padding:4px;text-align:right">' +
          (r.health != null ? Number(r.health).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.risk != null ? Number(r.risk).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.total != null ? Number(r.total).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.completeness != null ? Number(r.completeness).toFixed(0) + '%' : '—') +
          '</td><td style="padding:4px">' + esc(r.statusText || '') + '</td></tr>';
      });
      box.className = '';
      box.innerHTML = html + '</table></div>';
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
  }

  window.PulseV5 = {
    activate: activate,
    deactivate: deactivate,
    refresh: function () { refresh(true); },
    focusFactors: focusFactors,
    last: function () { return lastPack; }
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'pulse') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();
