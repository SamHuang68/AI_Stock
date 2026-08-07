/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0：總覽儀表板
 * ----------------------------------------------------------------------------
 * 版面編排／密度參考外部 compact dashboard（非產品名）：
 *   ①脈動與組成 ②盤勢走勢 ③法人資金
 *   ④廣度 ⑤產業輪動 ⑥漲停監控 ⑦跌幅異常
 *   ⑧全球影響 ⑨市場快訊 ⑩自選風險與機會
 * 產品名固定 Stock Terminal 5.0；資料一律真實端點，禁止灌假分數。
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var lastPack = null;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('pulse-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'pulse-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-pulse.on){overflow:hidden}' +
      '#view-pulse.sv-panel{' +
        'max-width:none!important;width:100%;min-width:0;padding:10px 12px 12px;box-sizing:border-box;' +
        'overflow:hidden;display:flex;flex-direction:column;flex:1;min-height:0;height:100%;' +
        'background:radial-gradient(900px 420px at 8% -8%,rgba(245,197,24,.05),transparent 55%),#070B14;color:#E2E8F0}' +
      '#mount-pulse,#mount-pulse.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:100%}' +
      '#pl-root{font-family:\'Noto Sans TC\',\'JetBrains Mono\',sans-serif;width:100%;max-width:1600px;margin:0 auto;' +
        'box-sizing:border-box;flex:1;min-height:0;display:flex;flex-direction:column;color:#E2E8F0}' +

      /* header */
      '#pl-root .pl-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px;flex:0 0 auto}' +
      '#pl-root .pl-kicker{font-family:\'JetBrains Mono\',monospace;font-size:9px;font-weight:700;color:var(--gold);' +
        'letter-spacing:1.4px;margin-bottom:1px}' +
      '#pl-root .pl-title{font-family:\'Noto Serif TC\',serif;font-size:clamp(16px,1.5vw,20px);font-weight:700;color:#F8FAFC;line-height:1.1}' +
      '#pl-root .pl-sub{font-family:\'JetBrains Mono\',monospace;font-size:9px;color:#64748B;margin-top:1px}' +
      '#pl-root .pl-actions{display:flex;gap:5px;align-items:center;flex-wrap:wrap}' +
      '#pl-root .pl-btn{padding:4px 9px;border:1px solid #1E293B;border-radius:6px;background:#0F172A;' +
        'color:#94A3B8;font-size:10px;cursor:pointer;font-weight:600;font-family:\'JetBrains Mono\',monospace;' +
        'transition:border-color .15s ease,color .15s ease,background .15s ease}' +
      '#pl-root .pl-btn:hover{border-color:var(--gold-m);color:#F8FAFC}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .up{color:#FF4D4D!important;font-weight:700}' +
      '#pl-root .dn{color:#22C55E!important;font-weight:700}' +
      '#pl-root .flat{color:#94A3B8!important}' +
      '#pl-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +

      /* dashboard grid — reference 3 / 4 / 3 */
      '#pl-root .pl-dash{flex:1;min-height:0;display:grid;gap:8px;' +
        'grid-template-rows:minmax(0,1.2fr) minmax(0,1.05fr) minmax(0,.95fr)}' +
      '#pl-root .pl-row{display:grid;gap:8px;min-width:0;min-height:0;height:100%}' +
      '#pl-root .pl-row.r-top{grid-template-columns:minmax(0,1.05fr) minmax(0,1.45fr) minmax(0,1.05fr)}' +
      '#pl-root .pl-row.r-mid{grid-template-columns:repeat(4,minmax(0,1fr))}' +
      '#pl-root .pl-row.r-bot{grid-template-columns:minmax(0,1.35fr) minmax(0,1fr) minmax(0,1fr)}' +

      /* card chrome */
      '#pl-root .card{background:linear-gradient(180deg,#0D1524 0%,#0A121E 100%);border:1px solid #15263F;' +
        'border-radius:10px;padding:9px 11px;box-sizing:border-box;display:flex;flex-direction:column;' +
        'min-width:0;min-height:0;height:100%;overflow:hidden;box-shadow:inset 0 1px 0 rgba(255,255,255,.03);' +
        'opacity:0;transform:translateY(4px);animation:plCardIn .32s ease forwards}' +
      '#pl-root .pl-row.r-top .card:nth-child(1){animation-delay:.02s}' +
      '#pl-root .pl-row.r-top .card:nth-child(2){animation-delay:.06s}' +
      '#pl-root .pl-row.r-top .card:nth-child(3){animation-delay:.1s}' +
      '#pl-root .pl-row.r-mid .card:nth-child(1){animation-delay:.12s}' +
      '#pl-root .pl-row.r-mid .card:nth-child(2){animation-delay:.15s}' +
      '#pl-root .pl-row.r-mid .card:nth-child(3){animation-delay:.18s}' +
      '#pl-root .pl-row.r-mid .card:nth-child(4){animation-delay:.21s}' +
      '#pl-root .pl-row.r-bot .card:nth-child(1){animation-delay:.24s}' +
      '#pl-root .pl-row.r-bot .card:nth-child(2){animation-delay:.27s}' +
      '#pl-root .pl-row.r-bot .card:nth-child(3){animation-delay:.3s}' +
      '@keyframes plCardIn{to{opacity:1;transform:translateY(0)}}' +
      '#pl-root .card-h{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px;flex:0 0 auto;gap:6px}' +
      '#pl-root .card-t{font-size:12px;font-weight:700;color:#F1F5F9;display:flex;align-items:center;gap:6px;letter-spacing:.2px}' +
      '#pl-root .card-t .ico{width:18px;height:18px;border-radius:5px;display:inline-flex;align-items:center;justify-content:center;' +
        'background:rgba(245,197,24,.1);border:1px solid rgba(245,197,24,.25);font-size:10px;color:var(--gold)}' +
      '#pl-root .card-a{color:#38BDF8;font-size:10px;cursor:pointer;text-decoration:none;font-weight:600;white-space:nowrap;' +
        'transition:color .15s ease}' +
      '#pl-root .card-a:hover{color:var(--gold)}' +
      '#pl-root .mono{font-family:\'JetBrains Mono\',monospace}' +

      /* ① pulse gauge */
      '#pl-root .g-wrap{display:flex;gap:12px;align-items:stretch;flex:1;min-height:0}' +
      '#pl-root .g-arc{position:relative;width:118px;flex:0 0 118px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}' +
      '#pl-root .g-arc svg{width:118px;height:70px;display:block}' +
      '#pl-root .g-arc .score{position:absolute;bottom:18px;text-align:center;width:100%}' +
      '#pl-root .g-arc .score b{font-family:\'JetBrains Mono\',monospace;font-size:22px;font-weight:800;color:#F8FAFC;line-height:1}' +
      '#pl-root .g-arc .score i{font-style:normal;font-size:10px;color:#64748B;margin-left:2px}' +
      '#pl-root .g-arc .badge{margin-top:2px;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;' +
        'background:rgba(245,158,11,.14);color:#FBBF24;border:1px solid rgba(245,158,11,.35)}' +
      '#pl-root .g-side{flex:1;display:flex;flex-direction:column;gap:7px;min-width:0}' +
      '#pl-root .ring-row{display:grid;grid-template-columns:1fr 1fr;gap:7px}' +
      '#pl-root .ring-box{background:#070E1A;border:1px solid #132238;border-radius:8px;padding:7px 8px;' +
        'display:flex;align-items:center;gap:8px}' +
      '#pl-root .ring{width:36px;height:36px;flex-shrink:0;position:relative}' +
      '#pl-root .ring svg{width:36px;height:36px;transform:rotate(-90deg)}' +
      '#pl-root .ring .rv{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:9px;font-weight:800;color:#F8FAFC}' +
      '#pl-root .ring-meta .k{font-size:9px;color:#64748B}' +
      '#pl-root .ring-meta .v{font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:800;color:#F8FAFC;margin-top:1px}' +
      '#pl-root .ring-meta .l{font-size:9px;color:#38BDF8;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .comp-box{background:#070E1A;border:1px solid #132238;border-radius:8px;padding:7px 8px}' +
      '#pl-root .comp-box .row{display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px}' +
      '#pl-root .comp-box .row .k{color:#64748B}' +
      '#pl-root .comp-box .row .v{font-family:\'JetBrains Mono\',monospace;font-weight:700;color:#F8FAFC}' +
      '#pl-root .bar{height:4px;background:#1E293B;border-radius:2px;overflow:hidden}' +
      '#pl-root .bar>i{display:block;height:100%;background:linear-gradient(90deg,#38BDF8,var(--gold));border-radius:2px;' +
        'transition:width .45s ease}' +
      '#pl-root .drive{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;flex:0 0 auto}' +
      '#pl-root .drive .box{background:#070E1A;border:1px solid #132238;border-radius:7px;padding:6px 8px;min-width:0}' +
      '#pl-root .drive .box .k{font-size:9px;color:#64748B;margin-bottom:3px}' +
      '#pl-root .drive .box li{list-style:none;font-size:10px;color:#CBD5E1;margin:2px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +

      /* ② trend */
      '#pl-root .trend-hero{display:flex;align-items:baseline;gap:8px;margin-bottom:4px;flex:0 0 auto}' +
      '#pl-root .trend-hero .lbl{font-size:11px;color:#94A3B8}' +
      '#pl-root .trend-hero .px{font-family:\'JetBrains Mono\',monospace;font-size:20px;font-weight:800;color:#F8FAFC}' +
      '#pl-root .trend-hero .ch{font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:700}' +
      '#pl-root .spark{flex:1;min-height:56px;background:#070E1A;border:1px solid #132238;border-radius:8px;padding:4px 6px;margin:4px 0 8px}' +
      '#pl-root .spark svg{width:100%;height:100%;display:block}' +
      '#pl-root .ohlc{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;flex:0 0 auto}' +
      '#pl-root .ohlc .b{background:#070E1A;border:1px solid #132238;border-radius:7px;padding:6px 8px}' +
      '#pl-root .ohlc .b .k{font-size:9px;color:#64748B}' +
      '#pl-root .ohlc .b .v{font-family:\'JetBrains Mono\',monospace;font-size:13px;font-weight:700;color:#F8FAFC;margin-top:2px}' +

      /* ③ institutional */
      '#pl-root .inst-list{display:flex;flex-direction:column;gap:8px;flex:1;min-height:0}' +
      '#pl-root .inst-row{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'background:#070E1A;border:1px solid #132238;border-radius:8px;padding:8px 10px}' +
      '#pl-root .inst-row .nm{font-size:12px;font-weight:700;color:#F1F5F9;width:42px}' +
      '#pl-root .inst-row .meta{font-size:10px;color:#64748B;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .inst-row .amt{font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:800}' +
      '#pl-root .inst-total{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;' +
        'background:rgba(56,189,248,.06);border:1px solid rgba(56,189,248,.2);border-radius:8px;margin:6px 0;flex:0 0 auto}' +
      '#pl-root .inst-total .k{font-size:11px;font-weight:700;color:#CBD5E1}' +
      '#pl-root .inst-total .v{font-family:\'JetBrains Mono\',monospace;font-size:16px;font-weight:800}' +
      '#pl-root .cons{margin-top:auto;border-radius:8px;padding:8px 10px;flex:0 0 auto}' +
      '#pl-root .cons.bull{background:rgba(255,77,77,.07);border:1px solid rgba(255,77,77,.28)}' +
      '#pl-root .cons.bear{background:rgba(34,197,94,.07);border:1px solid rgba(34,197,94,.28)}' +
      '#pl-root .cons.mid{background:rgba(148,163,184,.06);border:1px solid rgba(148,163,184,.2)}' +
      '#pl-root .cons .hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}' +
      '#pl-root .cons .tt{font-size:12px;font-weight:800}' +
      '#pl-root .cons.bull .tt,#pl-root .cons.bull .tg{color:#FF4D4D}' +
      '#pl-root .cons.bear .tt,#pl-root .cons.bear .tg{color:#22C55E}' +
      '#pl-root .cons.mid .tt,#pl-root .cons.mid .tg{color:#94A3B8}' +
      '#pl-root .cons .tg{font-size:9px;font-weight:700;padding:1px 6px;border-radius:4px;background:rgba(255,255,255,.04)}' +
      '#pl-root .cons .sub{font-size:10px;color:#94A3B8}' +

      /* ④ breadth */
      '#pl-root .br-wrap{display:flex;align-items:center;gap:12px;flex:1;min-height:0}' +
      '#pl-root .donut{width:88px;height:88px;position:relative;flex-shrink:0}' +
      '#pl-root .donut svg{width:88px;height:88px}' +
      '#pl-root .donut .mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}' +
      '#pl-root .donut .mid b{font-family:\'JetBrains Mono\',monospace;font-size:16px;font-weight:800;color:#F8FAFC}' +
      '#pl-root .donut .mid span{font-size:9px;color:#64748B}' +
      '#pl-root .br-leg{flex:1;font-size:12px;line-height:1.55;min-width:0}' +
      '#pl-root .br-leg .li{display:flex;justify-content:space-between;align-items:center;gap:6px}' +
      '#pl-root .br-leg i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px}' +
      '#pl-root .br-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;flex:0 0 auto}' +
      '#pl-root .br-stats .b{background:#070E1A;border:1px solid #132238;border-radius:7px;padding:6px 8px}' +
      '#pl-root .br-stats .k{font-size:9px;color:#64748B}' +
      '#pl-root .br-stats .v{font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:800;color:#F8FAFC;margin-top:1px}' +
      '#pl-root .br-tone{margin-top:6px;font-size:11px;color:#94A3B8;flex:0 0 auto}' +
      '#pl-root .br-tone b{color:#F8FAFC}' +

      /* ⑤ sectors */
      '#pl-root .sec-list{display:flex;flex-direction:column;gap:5px;flex:1;min-height:0;overflow:auto}' +
      '#pl-root .sec{display:grid;grid-template-columns:72px 1fr 48px;gap:6px;align-items:center;font-size:11px}' +
      '#pl-root .sec .nm{color:#E2E8F0;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .sec .sub{font-size:9px;color:#64748B;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .sec .track{height:6px;background:#111827;border-radius:3px;overflow:hidden}' +
      '#pl-root .sec .track>i{display:block;height:100%;border-radius:3px;transition:width .4s ease}' +
      '#pl-root .sec .pc{font-family:\'JetBrains Mono\',monospace;font-weight:800;text-align:right;font-size:11px}' +

      /* ⑥⑦ movers */
      '#pl-root .mv-list{list-style:none;margin:0;padding:0;flex:1;min-height:0;overflow:auto}' +
      '#pl-root .mv-list li{display:flex;align-items:center;justify-content:space-between;gap:6px;' +
        'padding:5px 2px;border-bottom:1px solid #132238;cursor:pointer;font-size:11px}' +
      '#pl-root .mv-list li:hover{background:rgba(255,255,255,.02)}' +
      '#pl-root .mv-list .idx{width:18px;height:18px;border-radius:50%;background:#152033;color:#94A3B8;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0}' +
      '#pl-root .mv-list .left{display:flex;align-items:center;gap:7px;min-width:0}' +
      '#pl-root .mv-list .nm{color:#F8FAFC;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .mv-list .cd{color:#64748B;font-size:10px;font-family:\'JetBrains Mono\',monospace}' +
      '#pl-root .mv-list .meta{font-size:9px;color:#64748B}' +
      '#pl-root .mv-list .pc{font-family:\'JetBrains Mono\',monospace;font-weight:800;font-size:12px;flex-shrink:0}' +
      '#pl-root .chip{display:inline-block;margin-left:4px;padding:0 5px;border-radius:3px;font-size:9px;font-weight:700;' +
        'background:rgba(245,197,24,.12);color:var(--gold);border:1px solid rgba(245,197,24,.3)}' +

      /* ⑧ global */
      '#pl-root .g-head{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex:0 0 auto}' +
      '#pl-root .pill{padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;' +
        'background:rgba(56,189,248,.12);color:#38BDF8;border:1px solid rgba(56,189,248,.3)}' +
      '#pl-root .g-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;flex:1;align-content:start}' +
      '#pl-root .g-box{background:#070E1A;border:1px solid #132238;border-radius:8px;padding:8px 9px;min-width:0}' +
      '#pl-root .g-box .k{font-size:10px;color:#64748B;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .g-box .v{font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:800;color:#F8FAFC;margin-top:3px}' +
      '#pl-root .g-box .p{font-family:\'JetBrains Mono\',monospace;font-size:11px;font-weight:700;margin-top:2px}' +

      /* ⑨ news */
      '#pl-root .news{flex:1;min-height:0;overflow:auto}' +
      '#pl-root .news .row{padding:7px 0;border-bottom:1px solid #132238;cursor:default}' +
      '#pl-root .news .row[data-code]{cursor:pointer}' +
      '#pl-root .news .t{font-family:\'JetBrains Mono\',monospace;font-size:9px;color:#64748B;margin-right:6px}' +
      '#pl-root .news .cat{color:#38BDF8;font-size:9px;margin-right:5px}' +
      '#pl-root .news .ttl{font-size:11px;color:#E2E8F0;font-weight:600}' +

      /* ⑩ watchlist */
      '#pl-root .wl{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:6px}' +
      '#pl-root .wl .item{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'background:#070E1A;border:1px solid #132238;border-radius:8px;padding:8px 10px;cursor:pointer}' +
      '#pl-root .wl .item:hover{border-color:#243652}' +
      '#pl-root .wl .code{font-family:\'JetBrains Mono\',monospace;color:var(--gold);font-weight:800;font-size:12px}' +
      '#pl-root .wl .name{color:#94A3B8;font-size:11px;margin-left:6px}' +
      '#pl-root .wl .tag{margin-left:6px;font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px}' +
      '#pl-root .wl .tag.hot{background:rgba(245,197,24,.12);color:var(--gold)}' +
      '#pl-root .wl .tag.cold{background:rgba(56,189,248,.1);color:#38BDF8}' +
      '#pl-root .wl .tag.ok{background:rgba(34,197,94,.1);color:#22C55E}' +
      '#pl-root .wl .px{font-family:\'JetBrains Mono\',monospace;font-size:13px;font-weight:800;color:#F8FAFC}' +
      '#pl-root .wl .ch{font-family:\'JetBrains Mono\',monospace;font-size:11px;font-weight:700;margin-left:8px}' +

      '#pl-root .empty{padding:12px 4px;color:#64748B;font-size:11px}' +

      '@media (max-width:1280px){' +
        '#view-pulse.sv-panel,#pl-body{overflow:auto}' +
        '#pl-root .pl-dash{display:block}' +
        '#pl-root .pl-row{height:auto;margin-bottom:8px}' +
        '#pl-root .pl-row.r-top,#pl-root .pl-row.r-mid,#pl-root .pl-row.r-bot{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .g-grid{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '}' +
      '@media (max-width:820px){' +
        '#pl-root .pl-row.r-top,#pl-root .pl-row.r-mid,#pl-root .pl-row.r-bot{grid-template-columns:1fr}' +
        '#pl-root .g-grid{grid-template-columns:repeat(2,minmax(0,1fr))}' +
      '}' +
      '@media (max-height:820px) and (min-width:1281px){' +
        '#pl-root .g-arc{width:100px;flex-basis:100px}' +
        '#pl-root .g-arc svg{width:100px;height:60px}' +
        '#pl-root .donut,#pl-root .donut svg{width:72px;height:72px}' +
        '#pl-root .spark{min-height:44px}' +
        '#view-pulse.sv-panel{padding:8px 10px}' +
      '}';
  }

  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
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
  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
  function moneyYi(v) {
    if (v == null || !isFinite(v)) return '—';
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (x >= 0 ? '+' : '') + Number(x).toFixed(1) + ' 億';
  }
  function sectorNote(cp) {
    if (cp == null || !isFinite(cp)) return '資料觀察中';
    if (cp >= 2) return '資金加速';
    if (cp >= 0.8) return '偏強';
    if (cp >= 0.2) return '緩升';
    if (cp > -0.2) return '中性';
    if (cp > -0.8) return '偏弱';
    return '資金流出';
  }
  function breadthTone(adv, ls) {
    if (adv == null && ls == null) return '資料彙整中';
    if ((ls != null && ls >= 3) || (adv != null && adv >= 0.75)) return '極度偏多';
    if ((ls != null && ls >= 1.8) || (adv != null && adv >= 0.60)) return '偏多擴張';
    if ((ls != null && ls <= 0.35) || (adv != null && adv <= 0.30)) return '極度偏空';
    if ((ls != null && ls <= 0.55) || (adv != null && adv <= 0.40)) return '偏空收縮';
    return '廣度糾結';
  }
  function ringSvg(score, color) {
    var v = (score != null && isFinite(score)) ? Math.max(0, Math.min(100, score)) : 0;
    var c = 2 * Math.PI * 14;
    var dash = (v / 100) * c;
    return '<div class="ring"><svg viewBox="0 0 36 36">' +
      '<circle cx="18" cy="18" r="14" fill="none" stroke="#1E293B" stroke-width="3.5"/>' +
      '<circle cx="18" cy="18" r="14" fill="none" stroke="' + color + '" stroke-width="3.5" ' +
        'stroke-linecap="round" stroke-dasharray="' + dash.toFixed(2) + ' ' + c.toFixed(2) + '"/>' +
      '</svg><div class="rv">' + (score != null && isFinite(score) ? Number(score).toFixed(0) : '—') + '</div></div>';
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
            '<div class="pl-kicker">STOCK TERMINAL · v5.0</div>' +
            '<div class="pl-title" id="pl-title">市場總覽</div>' +
            '<div class="pl-sub" id="pl-sub">官方資料混成 · 缺資料不灌假分數</div>' +
          '</div><div class="pl-actions">' +
            '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
            '<button type="button" class="pl-btn" data-go="breadth">廣度</button>' +
            '<button type="button" class="pl-btn" data-go="heat">熱力</button>' +
            '<button type="button" class="pl-btn primary" data-go="chart" data-sym="^TWII" data-mkt="TW">圖表</button>' +
          '</div></div>' +
          '<div id="pl-body"><div class="empty">載入總覽儀表板…</div></div>' +
        '</div>';
      var rbtn = $('pl-refresh');
      if (rbtn) rbtn.onclick = function () { refresh(true); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          goRoute(b.getAttribute('data-go'), {
            sym: b.getAttribute('data-sym') || undefined,
            mkt: b.getAttribute('data-mkt') || undefined
          });
        };
      });
    }
    return $('pl-body');
  }

  /* ① 市場脈動與組成 */
  function renderPulse(p) {
    var score = p.totalScore;
    var pctVal = (score != null && isFinite(score)) ? Math.max(0, Math.min(100, score)) / 100 : 0;
    var arc = 172;
    var drivers = (p.positiveFactors || []).slice(0, 3).map(function (f) { return f.name; }).filter(Boolean);
    var pressures = (p.riskFactors || []).slice(0, 3).map(function (f) { return f.name; }).filter(Boolean);
    var svg =
      '<svg viewBox="0 0 140 80">' +
        '<defs><linearGradient id="stGauge" x1="0%" y1="0%" x2="100%" y2="0%">' +
          '<stop offset="0%" stop-color="#EF4444"/><stop offset="55%" stop-color="#F59E0B"/><stop offset="100%" stop-color="#22C55E"/>' +
        '</linearGradient></defs>' +
        '<path d="M 15 70 A 55 55 0 0 1 125 70" fill="none" stroke="#1E293B" stroke-width="11" stroke-linecap="round"/>' +
        '<path d="M 15 70 A 55 55 0 0 1 125 70" fill="none" stroke="url(#stGauge)" stroke-width="11" stroke-linecap="round" ' +
          'stroke-dasharray="' + arc + '" stroke-dashoffset="' + (arc * (1 - pctVal)).toFixed(1) + '"/>' +
      '</svg>';
    return '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">◎</span>市場脈動與組成</div>' +
      '<a class="card-a" data-go="signals">詳情 →</a></div>' +
      '<div class="g-wrap"><div class="g-arc">' + svg +
        '<div class="score"><b class="mono">' + (score != null && isFinite(score) ? Number(score).toFixed(1) : '—') +
        '</b><i>/100</i></div>' +
        '<div class="badge">' + esc(p.statusText || '資料彙整中') + '</div></div>' +
      '<div class="g-side"><div class="ring-row">' +
        '<div class="ring-box">' + ringSvg(p.healthScore, '#38BDF8') +
          '<div class="ring-meta"><div class="k">市場動能</div><div class="v">' +
          (p.healthScore != null ? Number(p.healthScore).toFixed(1) : '—') +
          '</div><div class="l">' + esc(p.healthLabel || '') + '</div></div></div>' +
        '<div class="ring-box">' + ringSvg(p.riskScore, '#F59E0B') +
          '<div class="ring-meta"><div class="k">市場風險</div><div class="v">' +
          (p.riskScore != null ? Number(p.riskScore).toFixed(1) : '—') +
          '</div><div class="l">' + esc(p.riskLabel || '') + '</div></div></div>' +
      '</div><div class="comp-box"><div class="row"><span class="k">資料可信度</span><span class="v">' +
        (p.dataCompleteness != null ? Number(p.dataCompleteness).toFixed(0) + '%' : '—') +
        ' · ' + (p.datasetsOk || 0) + '/' + (p.datasetsTotal || 0) + '</span></div>' +
        '<div class="bar"><i style="width:' + (p.dataCompleteness != null ? Number(p.dataCompleteness) : 0) + '%"></i></div>' +
      '</div></div></div>' +
      '<div class="drive"><div class="box"><div class="k">主要動能</div><ul>' +
        (drivers.length ? drivers.map(function (n) { return '<li>· ' + esc(n) + '</li>'; }).join('') : '<li style="color:#64748B">—</li>') +
      '</ul></div><div class="box"><div class="k">主要壓力</div><ul>' +
        (pressures.length ? pressures.map(function (n) { return '<li>· ' + esc(n) + '</li>'; }).join('') : '<li style="color:#64748B">—</li>') +
      '</ul></div></div></div>';
  }

  /* ② 市場盤勢走勢 */
  function renderTrend(ov) {
    var o = (ov && ov.ohlc) || {};
    return '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">◈</span>市場盤勢走勢</div>' +
      '<a class="card-a" data-go="chart" data-sym="^TWII" data-mkt="TW">圖表 →</a></div>' +
      '<div class="trend-hero"><span class="lbl">近 20 日收盤</span>' +
        '<span class="px">' + fmt(o.price, 2) + '</span>' +
        '<span class="ch ' + tw(o.changePct) + '">' + pct(o.changePct) + '</span>' +
        (o.otcPrice != null ? '<span class="lbl" style="margin-left:auto">櫃買 ' + fmt(o.otcPrice, 2) +
          ' <span class="' + tw(o.otcChangePct) + '">' + pct(o.otcChangePct) + '</span></span>' : '') +
      '</div>' +
      '<div class="spark" id="pl-spark"><div class="empty">載入近 20 日走勢…</div></div>' +
      '<div class="ohlc">' +
        '<div class="b"><div class="k">開盤</div><div class="v">' + fmt(o.open, 2) + '</div></div>' +
        '<div class="b"><div class="k">最高</div><div class="v">' + fmt(o.high, 2) + '</div></div>' +
        '<div class="b"><div class="k">最低</div><div class="v">' + fmt(o.low, 2) + '</div></div>' +
        '<div class="b"><div class="k">昨收</div><div class="v">' + fmt(o.prevClose, 2) + '</div></div>' +
      '</div></div>';
  }

  /* ③ 法人分歧與資金 */
  function renderInst(ov) {
    var i = (ov && ov.institutional) || {};
    var foreign = i.foreign, trust = i.trust, dealer = i.dealer, totalYi = i.totalYi;
    var note = i.date ? ('法人日 ' + i.date) : '單位億元';
    var cls = 'mid', title = '法人方向', tag = '—', sub = '資料彙整中';
    if (foreign != null && trust != null && dealer != null) {
      var buyN = [foreign, trust, dealer].filter(function (v) { return v > 0; }).length;
      var sellN = [foreign, trust, dealer].filter(function (v) { return v < 0; }).length;
      if (buyN === 3) { cls = 'bull'; title = '法人一致偏多'; tag = '3/3'; sub = '外資、投信、自營同步買超'; }
      else if (sellN === 3) { cls = 'bear'; title = '法人一致偏空'; tag = '3/3'; sub = '外資、投信、自營同步賣超'; }
      else if (foreign > 0 && dealer < 0) { cls = 'mid'; title = '結構分歧'; tag = buyN + '/3'; sub = '外資買超、自營賣超'; }
      else { cls = 'mid'; title = '法人分歧'; tag = buyN + '/3 偏多'; sub = note; }
    }
    function row(name, v) {
      return '<div class="inst-row"><span class="nm">' + name + '</span>' +
        '<span class="meta">' + esc(note) + '</span>' +
        '<span class="amt ' + tw(v) + '">' + moneyYi(v) + '</span></div>';
    }
    return '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">₴</span>法人分歧與資金</div>' +
      '<a class="card-a" data-go="institutional">詳情 →</a></div>' +
      '<div class="inst-list">' + row('外資', foreign) + row('投信', trust) + row('自營', dealer) + '</div>' +
      '<div class="inst-total"><span class="k">法人合計</span><span class="v ' + tw(totalYi) + '">' +
        (totalYi != null && isFinite(totalYi) ? ((totalYi >= 0 ? '+' : '') + Number(totalYi).toFixed(1) + ' 億') : '—') +
      '</span></div>' +
      '<div class="cons ' + cls + '"><div class="hd"><span class="tt">' + esc(title) + '</span>' +
        '<span class="tg">' + esc(tag) + '</span></div><div class="sub">' + esc(sub) + '</div></div></div>';
  }

  /* ④ 市場廣度 */
  function renderBreadth(st) {
    st = st || {};
    var up = st.up != null ? st.up : 0;
    var dn = st.down != null ? st.down : 0;
    var flat = st.flat != null ? st.flat : (st.unchanged || 0);
    var sum = up + dn + flat;
    var ls = st.lsRatio;
    if (ls == null && up > 0 && dn > 0) ls = up / dn;
    var adv = st.advRatio != null ? st.advRatio : (sum ? up / sum : null);
    var tone = breadthTone(adv, ls);
    var C = 2 * Math.PI * 30;
    var uLen = sum ? C * up / sum : 0;
    var fLen = sum ? C * flat / sum : 0;
    var dLen = sum ? C * dn / sum : 0;
    var svg =
      '<svg viewBox="0 0 80 80">' +
        '<circle cx="40" cy="40" r="30" fill="none" stroke="#1E293B" stroke-width="9"/>' +
        '<circle cx="40" cy="40" r="30" fill="none" stroke="#FF4D4D" stroke-width="9" transform="rotate(-90 40 40)" ' +
          'stroke-dasharray="' + uLen.toFixed(2) + ' ' + C.toFixed(2) + '" stroke-dashoffset="0"/>' +
        '<circle cx="40" cy="40" r="30" fill="none" stroke="#F59E0B" stroke-width="9" transform="rotate(-90 40 40)" ' +
          'stroke-dasharray="' + fLen.toFixed(2) + ' ' + C.toFixed(2) + '" stroke-dashoffset="' + (-uLen).toFixed(2) + '"/>' +
        '<circle cx="40" cy="40" r="30" fill="none" stroke="#22C55E" stroke-width="9" transform="rotate(-90 40 40)" ' +
          'stroke-dasharray="' + dLen.toFixed(2) + ' ' + C.toFixed(2) + '" stroke-dashoffset="' + (-(uLen + fLen)).toFixed(2) + '"/>' +
      '</svg>';
    return '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">▤</span>市場廣度</div>' +
      '<a class="card-a" data-go="breadth">詳情 →</a></div>' +
      '<div class="br-wrap"><div class="donut">' + svg +
        '<div class="mid"><b>' + (sum || '—') + '</b><span>總家數</span></div></div>' +
      '<div class="br-leg">' +
        '<div class="li"><span><i style="background:#FF4D4D"></i>上漲</span><b class="up mono">' + fmt(up) + '</b></div>' +
        '<div class="li"><span><i style="background:#F59E0B"></i>平盤</span><b class="flat mono">' + fmt(flat) + '</b></div>' +
        '<div class="li"><span><i style="background:#22C55E"></i>下跌</span><b class="dn mono">' + fmt(dn) + '</b></div>' +
      '</div></div>' +
      '<div class="br-stats">' +
        '<div class="b"><div class="k">多空比</div><div class="v">' + (ls != null && isFinite(ls) ? Number(ls).toFixed(2) : '—') + '</div></div>' +
        '<div class="b"><div class="k">上漲占比</div><div class="v">' + (adv != null ? (adv * 100).toFixed(1) + '%' : '—') + '</div></div>' +
      '</div>' +
      '<div class="br-tone">廣度狀態 · <b>' + esc(tone) + '</b>' +
        (st.limitUp != null ? ' · 漲停 ' + fmt(st.limitUp) : '') +
        (st.limitDown != null ? ' · 跌停 ' + fmt(st.limitDown) : '') +
      '</div></div>';
  }

  /* ⑤ 產業輪動 */
  function renderSectors(ov) {
    var list = (ov && ov.sectorsRanked) || [];
    var maxAbs = 1;
    list.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.changePct || 0)); });
    var html = '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">▦</span>產業輪動</div>' +
      '<a class="card-a" data-go="heat">熱力 →</a></div><div class="sec-list">';
    if (!list.length) return html + '<div class="empty">類股資料暫缺 — 開啟熱力可預熱</div></div></div>';
    list.slice(0, 7).forEach(function (s) {
      var cp = s.changePct || 0;
      var w = Math.max(6, Math.round(Math.abs(cp) / maxAbs * 100));
      var col = cp >= 0 ? '#FF4D4D' : '#22C55E';
      html += '<div class="sec"><div><div class="nm" title="' + esc(s.name) + '">' + esc(s.name) + '</div>' +
        '<div class="sub">' + esc(sectorNote(cp)) + '</div></div>' +
        '<div class="track"><i style="width:' + w + '%;background:' + col + '"></i></div>' +
        '<div class="pc ' + tw(cp) + '">' + pct(cp) + '</div></div>';
    });
    return html + '</div></div>';
  }

  /* ⑥⑦ 漲停／跌幅 */
  function renderMovers(movers, side) {
    var raw = (movers && movers[side]) || [];
    var isUp = side === 'gainers';
    var title = isUp ? '漲停監控' : '跌幅異常';
    var list;
    if (isUp) {
      var lim = raw.filter(function (r) { return r.changePct != null && r.changePct >= 9.5; });
      list = (lim.length ? lim : raw).slice(0, 7);
    } else {
      var bad = raw.filter(function (r) { return r.changePct != null && r.changePct <= -7; });
      list = (bad.length ? bad : raw).slice(0, 7);
    }
    var html = '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">' +
      (isUp ? '▲' : '▼') + '</span>' + title + '</div>' +
      '<a class="card-a" data-go="afterhours">盤後 →</a></div><ul class="mv-list">';
    if (!list.length) {
      return html + '<li style="cursor:default;color:#64748B">' +
        (isUp ? '尚無接近／觸及漲停標的' : '尚無大幅下跌標的') + '</li></ul></div>';
    }
    list.forEach(function (r, idx) {
      var cp = r.changePct;
      var amt = r.amt || (r.volume != null ? fmt(r.volume) + ' 張' : '');
      var chip = (cp != null && Math.abs(cp) >= 9.5) ? '<span class="chip">' + (isUp ? '漲停' : '跌停') + '</span>' : '';
      html += '<li data-code="' + esc(r.code || '') + '"><div class="left">' +
        '<span class="idx">' + (idx + 1) + '</span><div>' +
        '<div class="nm">' + esc(r.name || r.code) + ' <span class="cd">' + esc(r.code || '') + '</span>' + chip + '</div>' +
        (amt ? '<div class="meta">' + esc(amt) + '</div>' : '') +
        '</div></div><span class="pc ' + tw(cp) + '">' + pct(cp) + '</span></li>';
    });
    return html + '</ul></div>';
  }

  /* ⑧ 全球影響 */
  function renderGlobal(p) {
    var list = (p.global && p.global.length) ? p.global.slice() : [];
    var prefer = ['^DJI', '^GSPC', '^IXIC', '^VIX', 'TWD=X', 'DX-Y.NYB', 'DX=F', 'CL=F'];
    list.sort(function (a, b) {
      var ia = prefer.indexOf(a.symbol), ib = prefer.indexOf(b.symbol);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var n = 0, sum = 0;
    list.forEach(function (x) {
      if (x && x.changePct != null && isFinite(x.changePct) && x.symbol !== '^VIX') {
        n += 1; sum += x.changePct;
      }
    });
    var tone = !n ? '資料彙整中' : (sum / n >= 0.6 ? '偏多' : (sum / n <= -0.6 ? '偏空' : '中性'));
    var html = '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">◎</span>全球市場對台股影響</div>' +
      '<a class="card-a" data-go="international">國際 →</a></div>' +
      '<div class="g-head"><span class="pill">影響方向 · ' + esc(tone) + '</span>' +
        '<span style="font-size:10px;color:#64748B">真實報價均幅粗分，非預測</span></div><div class="g-grid">';
    if (!list.length) html += '<div class="empty" style="grid-column:1/-1">國際報價載入中…</div>';
    list.slice(0, 5).forEach(function (g) {
      var dig = (g.symbol === '^VIX' || g.symbol === 'TWD=X' || g.unit === '%') ? 2 : (g.price > 1000 ? 0 : 2);
      html += '<div class="g-box"><div class="k">' + esc(g.name || g.symbol) + '</div>' +
        '<div class="v">' + fmt(g.price, dig) + (g.unit === '%' ? '%' : '') + '</div>' +
        '<div class="p ' + tw(g.changePct) + '">' + pct(g.changePct) + '</div></div>';
    });
    return html + '</div></div>';
  }

  /* ⑨ 快訊 */
  function renderNews(p) {
    var list = p.flash || [];
    var html = '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">◉</span>市場快訊</div>' +
      '<a class="card-a" data-go="news">中樞 →</a></div><div class="news">';
    if (!list.length) return html + '<div class="empty">尚無快訊</div></div></div>';
    list.slice(0, 8).forEach(function (n) {
      html += '<div class="row"' + (n.code ? ' data-code="' + esc(n.code) + '"' : '') + '>' +
        '<span class="t">' + esc(n.time || '') + '</span>' +
        (n.cat ? '<span class="cat">[' + esc(n.cat) + ']</span>' : '') +
        '<span class="ttl">' + esc(n.title || '') + '</span></div>';
    });
    return html + '</div></div>';
  }

  function readWatchlist() {
    try {
      var raw = localStorage.getItem('st_wl');
      var arr = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(arr)) return [];
      return arr.filter(function (x) { return x && x.t; }).slice(0, 6);
    } catch (e) { return []; }
  }
  function watchTag(cp) {
    if (cp == null || !isFinite(cp)) return '<span class="tag ok">觀察</span>';
    if (cp >= 3) return '<span class="tag hot">機會</span>';
    if (cp <= -3) return '<span class="tag cold">風險</span>';
    return '<span class="tag ok">觀察</span>';
  }

  /* ⑩ 自選 */
  function renderWatch(pack) {
    var wl = readWatchlist();
    var quotes = (pack && pack.wlQuotes) || {};
    var html = '<div class="card"><div class="card-h"><div class="card-t"><span class="ico">★</span>自選股風險與機會</div>' +
      '<a class="card-a" data-go="watchlist">自選 →</a></div><div class="wl">';
    if (!wl.length) return html + '<div class="empty">尚無自選 — 在圖表按 ＋ 加入</div></div></div>';
    wl.forEach(function (w) {
      var q = quotes[w.t] || quotes[w.t + '.TW'] || quotes[w.t + '.TWO'] || {};
      var px = q.price != null ? q.price : w.price;
      var cp = q.changePct != null ? q.changePct : w.chg;
      html += '<div class="item" data-code="' + esc(w.t) + '" data-mkt="' + esc(w.m || 'TW') + '">' +
        '<div><span class="code">' + esc(w.t) + '</span>' +
          (w.name ? '<span class="name">' + esc(w.name) + '</span>' : '') +
          watchTag(cp) + '</div>' +
        '<div><span class="px">' + fmt(px, 2) + '</span>' +
          '<span class="ch ' + tw(cp) + '">' + pct(cp) + '</span></div></div>';
    });
    return html + '</div></div>';
  }

  function sparkSvg(closes) {
    if (!closes || closes.length < 2) {
      return '<div class="empty">近 20 日走勢尚在累積（同步資料後顯示）</div>';
    }
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = (hi - lo) || 1;
    var w = 360, h = 72, pad = 4;
    var pts = closes.map(function (c, i) {
      var x = pad + (i / (closes.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (c - lo) / span) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    });
    var line = pts.join(' ');
    var area = pts[0] + ' ' + line + ' ' + (w - pad).toFixed(1) + ',' + (h - pad) + ' ' + pad + ',' + (h - pad);
    var up = closes[closes.length - 1] >= closes[0];
    var col = up ? '#FF4D4D' : '#22C55E';
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<defs><linearGradient id="stArea" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + col + '" stop-opacity=".28"/><stop offset="100%" stop-color="' + col + '" stop-opacity="0"/>' +
      '</linearGradient></defs>' +
      '<polygon fill="url(#stArea)" points="' + area + '"/>' +
      '<polyline fill="none" stroke="' + col + '" stroke-width="2" points="' + line + '"/>' +
      '</svg>';
  }

  function enrichStrip(ov, breadth) {
    var st = (ov && ov.strip) ? Object.assign({}, ov.strip) : {};
    var stocks = (breadth && breadth.stocks) || {};
    if (st.up == null && stocks.up != null) st.up = stocks.up;
    if (st.down == null && stocks.down != null) st.down = stocks.down;
    if (st.flat == null) st.flat = stocks.unchanged != null ? stocks.unchanged : stocks.flat;
    if (st.limitUp == null && stocks.limitUp != null) st.limitUp = stocks.limitUp;
    if (st.limitDown == null && stocks.limitDown != null) st.limitDown = stocks.limitDown;
    if (st.advRatio == null && stocks.advRatio != null) st.advRatio = stocks.advRatio;
    if (st.lsRatio == null && st.up != null && st.down > 0) st.lsRatio = st.up / st.down;
    if (ov && ov.lsRatio != null && st.lsRatio == null) st.lsRatio = ov.lsRatio;
    return st;
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
        openChart(el.getAttribute('data-code'), el.getAttribute('data-mkt') || 'TW');
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
    var st = enrichStrip(ov, pack.breadth);

    var sub = $('pl-sub');
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (p.date ? ' · 廣度日 ' + p.date : '') +
        (p.dataCompleteness != null ? ' · 可靠度 ' + Number(p.dataCompleteness).toFixed(0) + '%' : '') +
        ' · ⚠ 非投資建議';
    }

    body.innerHTML =
      '<div class="pl-dash">' +
        '<div class="pl-row r-top">' + renderPulse(p) + renderTrend(ov) + renderInst(ov) + '</div>' +
        '<div class="pl-row r-mid">' + renderBreadth(st) + renderSectors(ov) +
          renderMovers(movers, 'gainers') + renderMovers(movers, 'losers') + '</div>' +
        '<div class="pl-row r-bot">' + renderGlobal(p) + renderNews(p) + renderWatch(pack) + '</div>' +
      '</div>';

    bind(body);

    jget('/pulse/history?kind=index&n=20').then(function (h) {
      var box = $('pl-spark');
      if (!box) return;
      var rows = ((h && h.rows) || []).slice().reverse();
      var closes = rows.map(function (r) { return r.close; }).filter(function (c) {
        return c != null && isFinite(c);
      });
      box.innerHTML = sparkSvg(closes);
      if (closes.length) {
        box.title = '近 ' + closes.length + ' 日 · 最新收 ' +
          Number(closes[closes.length - 1]).toLocaleString('en-US', { maximumFractionDigits: 2 });
      }
    });
  }

  function fetchWlQuotes() {
    var wl = readWatchlist();
    var twCodes = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(function (w) { return w.t; });
    var us = wl.filter(function (w) { return w.m === 'US'; }).map(function (w) { return w.t; });
    var tasks = [];
    if (twCodes.length) tasks.push(jget('/twquote-batch?codes=' + encodeURIComponent(twCodes.join(','))));
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
    if (btn) { btn.disabled = true; btn.textContent = '↻ 更新中…'; }
    if (!lastPack) body.innerHTML = '<div class="empty">載入總覽儀表板…</div>';
    var q = force ? '/pulse?refresh=1' : '/pulse';
    Promise.all([jget(q), fetchWlQuotes(), jget('/breadth')]).then(function (arr) {
      var pulse = arr[0];
      if (!pulse || !pulse.ok) {
        if (!lastPack) {
          body.innerHTML = '<div class="empty">脈動載入失敗' +
            (pulse && pulse.error ? '：' + esc(pulse.error) : '（請重啟 server）') +
            ' <button type="button" class="pl-btn" id="pl-retry">重試</button></div>';
          var retry = $('pl-retry');
          if (retry) retry.onclick = function () { refresh(true); };
        }
        return;
      }
      render({ pulse: pulse, wlQuotes: arr[1] || {}, breadth: arr[2] || null });
    }).finally(function () {
      var b = $('pl-refresh');
      if (b) { b.disabled = false; b.textContent = '↻ 重新整理'; }
    });
  }

  function activate() {
    ensureMount();
    if (lastPack) render(lastPack);
    refresh(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') refresh(false);
    }, 45000);
  }

  window.PulseV5 = {
    activate: activate,
    refresh: function () { refresh(true); },
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
