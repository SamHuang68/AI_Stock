// ============================================================
// Stock Terminal v5.0 — Chart Workspace Visual Contract
// ------------------------------------------------------------
// 圖表頁專用視覺層：
//   1. K 線／成交量／均線共用一份市場感知色票。
//   2. 只處理圖表工作站既有 DOM，不改其他 shell route 的排版。
//   3. 價格方向仍由 Colors（單一真理來源）決定；此檔只提升對比與層級。
// ============================================================
(function () {
  'use strict';

  function isRedUp(sym, mkt) {
    var value = String(sym || '').trim();
    if (value && window.Colors && typeof window.Colors.isRedUp === 'function') {
      return !!window.Colors.isRedUp(value);
    }
    return String(mkt || '').toUpperCase() === 'TW' || String(mkt || '').toUpperCase() === 'JP';
  }

  function themeFor(sym, mkt) {
    var redUp = isRedUp(sym, mkt);
    var red = '#ff6b7a';
    var green = '#42df91';
    return {
      redUp: redUp,
      chartBg: '#08111d',
      axisText: '#71829a',
      gridVertical: 'rgba(148,163,184,.035)',
      gridHorizontal: 'rgba(148,163,184,.050)',
      scaleBorder: 'rgba(148,163,184,.16)',
      crosshair: 'rgba(246,200,76,.52)',
      crosshairLabel: '#a97808',
      candleUp: redUp ? red : green,
      candleDown: redUp ? green : red,
      candleFlat: '#9ca3af',
      volumeUp: redUp ? 'rgba(255,107,122,.42)' : 'rgba(66,223,145,.42)',
      volumeDown: redUp ? 'rgba(66,223,145,.42)' : 'rgba(255,107,122,.42)',
      volumeFlat: 'rgba(156,163,175,.30)',
      ma20: '#f6c84c',
      ma60: '#67d8e8',
      band: 'rgba(96,165,250,.42)'
    };
  }

  function injectStyle() {
    if (typeof document === 'undefined' || document.getElementById('chart-visual-v5-style')) return;
    var style = document.createElement('style');
    style.id = 'chart-visual-v5-style';
    style.textContent = `
/* ── 圖表工作站：背景、邊界與環境光 ───────────────────── */
html.st-vs5 #body{
  background:linear-gradient(180deg,rgba(8,17,29,.98),rgba(5,11,20,.99));
}
html.st-vs5 #chartarea{
  isolation:isolate;overflow:hidden;
  background:#08111d;
  border:1px solid rgba(255,255,255,.075);
  border-radius:9px;
  box-shadow:inset 0 0 30px rgba(0,0,0,.34),0 12px 34px rgba(0,0,0,.20);
}
html.st-vs5 #chartarea:before{
  content:"";position:absolute;inset:0;z-index:1;pointer-events:none;
  background:radial-gradient(circle at 78% 12%,rgba(63,195,216,.045),transparent 34%);
}
html.st-vs5 #chart-wrap{background:#08111d}
html.st-vs5 #chart-wrap canvas{image-rendering:auto}
html.st-vs5 #chart-info{z-index:6}
html.st-vs5 #ci-ohlc{
  background:rgba(8,17,29,.82);border-color:rgba(255,255,255,.10);
  border-radius:6px;box-shadow:0 8px 22px rgba(0,0,0,.20);
}

/* ── 搜尋：輸入與 GO 成為一個操作元件 ─────────────────── */
html.st-vs5 #chart-search{display:flex;align-items:stretch;isolation:isolate}
html.st-vs5 #chart-search #syminput{
  width:108px;margin:0;border-radius:7px 0 0 7px;border-right:0;
  background:rgba(6,13,23,.78);box-shadow:inset 0 2px 5px rgba(0,0,0,.38);
}
html.st-vs5 #chart-search #syminput:focus{
  position:relative;z-index:1;border-color:rgba(246,200,76,.72);
  box-shadow:inset 0 2px 5px rgba(0,0,0,.38),0 0 0 2px rgba(246,200,76,.10);
}
html.st-vs5 #chart-search #gobtn{
  margin:0;border-radius:0 7px 7px 0;padding-inline:15px;
  background:linear-gradient(135deg,#ffd53d 0%,#e2a90b 100%);
  box-shadow:0 5px 15px rgba(226,169,11,.18),inset 0 1px 0 rgba(255,255,255,.38);
}
html.st-vs5 #chart-search #gobtn:hover{
  filter:brightness(1.06);box-shadow:0 7px 19px rgba(226,169,11,.25),inset 0 1px 0 rgba(255,255,255,.42);
}

/* ── 自選列：兩排固定；名稱＋meta 兩層，ETF 狀態為固定窄欄 ── */
html.st-vs5 #wlbar{height:67px!important;padding:2px 4px;gap:3px;background:rgba(9,17,29,.94)}
html.st-vs5 #wlchips{grid-template-rows:repeat(2,minmax(0,1fr));column-gap:3px;row-gap:2px;align-items:stretch}
html.st-vs5 .wlchip{
  height:30px!important;margin:0!important;padding:0 6px!important;align-self:center;overflow:visible;
  border:1px solid rgba(255,255,255,.065)!important;border-radius:7px;
  background:linear-gradient(180deg,rgba(255,255,255,.034),rgba(255,255,255,.014));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.025);
  transition:background .16s ease,border-color .16s ease,box-shadow .16s ease,transform .16s ease;
}
html.st-vs5 .wlchip-grip{font-size:8px;margin-right:0}
html.st-vs5 .wlchip-stack{padding:0!important;max-height:27px;overflow:visible}
html.st-vs5 .wlchip-meta{min-height:8px;line-height:1}
html.st-vs5 .wlchip-stack .wlchip-p{line-height:1!important;margin:0!important}
html.st-vs5 .wlchip:hover{
  background:rgba(255,255,255,.07);border-color:rgba(122,220,232,.24)!important;
  box-shadow:0 5px 14px rgba(0,0,0,.18),inset 0 1px 0 rgba(255,255,255,.05);
  transform:translateY(-1px);
}
html.st-vs5 .wlchip.active{
  background:linear-gradient(180deg,rgba(246,200,76,.11),rgba(246,200,76,.045));
  border-color:rgba(246,200,76,.30)!important;
  box-shadow:inset 2px 0 0 #f6c84c,0 4px 13px rgba(0,0,0,.15);
}
html.st-vs5 .wlchip-p{padding:0 2px;border-radius:999px;background:rgba(255,255,255,.035)}
html.st-vs5 .wladd{height:62px;border:1px solid rgba(255,255,255,.06);border-radius:7px;background:rgba(255,255,255,.02)}

/* 時間週期列使用完整寬度分區，26px 仍可點擊並把垂直空間還給圖表。 */
html.st-vs5 #rangebar{height:26px!important;scrollbar-width:none}
html.st-vs5 #rangebar::-webkit-scrollbar{display:none}
html.st-vs5 #rangebar .rgbtn{
  height:25px!important;min-height:25px!important;padding:0 4px!important;
  font-size:9px!important;line-height:25px!important;
}

/* ── 今／昨軸標籤：沿用既有正確價位，提升焦點而不重複 ───── */
html.st-vs5 #ctag-now{
  right:3px!important;padding:2px 5px!important;font-size:8px!important;
  background:rgba(7,14,24,.94)!important;border:1px solid currentColor!important;
  border-radius:4px!important;box-shadow:0 0 11px color-mix(in srgb,currentColor 28%,transparent),0 4px 10px rgba(0,0,0,.30)!important;
  text-shadow:none!important;
}
html.st-vs5 #ctag-prev{
  right:3px!important;padding:1px 4px!important;font-size:7px!important;
  background:rgba(7,14,24,.86)!important;border:1px solid rgba(190,195,205,.24)!important;
  border-radius:4px!important;text-shadow:none!important;
}

/* ── 右側雙分數卡：數字先讀、描述後讀 ─────────────────── */
html.st-vs5 #right{background:linear-gradient(180deg,rgba(11,20,34,.97),rgba(7,14,24,.99))}
html.st-vs5 .dual-card{gap:10px;padding:11px;border-bottom-color:rgba(255,255,255,.07)}
html.st-vs5 .dual-half{
  position:relative;overflow:hidden;display:flex;flex-direction:column;align-items:center;
  min-height:112px;padding:9px 8px 8px;
  background:linear-gradient(155deg,rgba(17,30,49,.94),rgba(8,17,29,.96));
  border:1px solid rgba(255,255,255,.085);border-radius:10px;
  box-shadow:0 8px 22px rgba(0,0,0,.22),inset 0 1px 0 rgba(255,255,255,.035);
}
html.st-vs5 .dual-half:after{
  content:"";position:absolute;left:14%;right:14%;bottom:-24px;height:40px;
  background:var(--score-color,rgba(103,216,232,.35));filter:blur(22px);opacity:.18;pointer-events:none;
}
html.st-vs5 .dual-half .lbl{min-height:22px;display:flex;align-items:center;justify-content:center}
html.st-vs5 .score-ring{
  --score:0;--score-color:#71829a;
  position:relative;
  width:58px;height:58px;margin:1px 0 3px;padding:4px;border-radius:50%;
  background:conic-gradient(var(--score-color) calc(var(--score) * 1%),rgba(255,255,255,.07) 0);
  box-shadow:0 0 18px color-mix(in srgb,var(--score-color) 18%,transparent);
}
html.st-vs5 .score-ring:before{
  content:"";display:block;width:100%;height:100%;border-radius:50%;
  background:#0a1422;border:1px solid rgba(255,255,255,.07);
}
html.st-vs5 .score-ring .score{
  position:absolute;left:50%;top:50%;z-index:1;transform:translate(-50%,-50%);
  font-size:23px!important;line-height:1!important;
}
html.st-vs5 .dual-half .tag{position:relative;z-index:1;padding:2px 7px;border:1px solid currentColor;border-radius:999px;background:rgba(255,255,255,.025)}

/* ── POC / VAH / VAL：與主圖同色的左側索引 ─────────────── */
html.st-vs5 .vp-panel{padding-bottom:5px}
html.st-vs5 .vp-panel .stat-sect{margin-bottom:4px}
html.st-vs5 .vp-panel .stat-row{
  position:relative;margin:3px 8px;padding:7px 9px 7px 13px;
  background:rgba(255,255,255,.018);border:1px solid rgba(255,255,255,.055);border-radius:6px;
}
html.st-vs5 .vp-panel .stat-row:before{
  content:"";position:absolute;left:0;top:5px;bottom:5px;width:3px;border-radius:0 3px 3px 0;background:#71829a;
}
html.st-vs5 .vp-panel .vp-poc:before{background:#a78bfa;box-shadow:0 0 9px rgba(167,139,250,.32)}
html.st-vs5 .vp-panel .vp-vah:before{background:#60a5fa}
html.st-vs5 .vp-panel .vp-val:before{background:#67d8e8}
html.st-vs5 .vp-panel .vp-position:before{background:#f6c84c}
html.st-vs5 .vp-state{display:inline-flex;padding:2px 7px;border:1px solid currentColor;border-radius:999px;background:rgba(255,255,255,.025)}
html.st-vs5 .vp-state.above{color:#7dd3fc}
html.st-vs5 .vp-state.inside{color:#f6c84c}
html.st-vs5 .vp-state.below{color:#fb923c}

/* ── 底部市場列：2×N 小型卡片，維持原高度 ─────────────── */
html.st-vs5 #mkt-bar{
  padding:4px;background:linear-gradient(180deg,rgba(10,18,31,.98),rgba(7,14,24,.99));
  border-top-color:rgba(255,255,255,.075);
}
html.st-vs5 #mkt-bar-tabs{margin-right:4px;border:1px solid rgba(255,255,255,.065);border-radius:7px;overflow:hidden;background:rgba(4,10,18,.62)}
html.st-vs5 #mkt-bar-inner,html.st-vs5 .mkt-bar-inner{gap:4px}
html.st-vs5 .mkt-cell{
  min-height:31px;padding:3px 10px;
  background:linear-gradient(145deg,rgba(255,255,255,.028),rgba(255,255,255,.010));
  border:1px solid rgba(255,255,255,.06)!important;border-radius:6px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.025);
  transition:background .15s ease,border-color .15s ease,transform .15s ease;
}
html.st-vs5 .mkt-cell:hover{
  background:rgba(255,255,255,.055);border-color:rgba(122,220,232,.20)!important;transform:translateY(-1px);
}
html.st-vs5 .mkt-cell .nm{color:#8291a7}
html.st-vs5 .mkt-cell .px{font-size:12.5px;color:#edf4fb}
html.st-vs5 .mkt-cell .ch:before{content:"· ";color:#536178}

@media(max-width:900px){
  html.st-vs5 #wlbar{height:65px!important;padding:0 4px;gap:2px}
  html.st-vs5 #wlchips{column-gap:2px;row-gap:0}
  html.st-vs5 .wlchip{height:30px!important;padding:0 5px!important}
  html.st-vs5 .wladd{height:64px}
  html.st-vs5 #topbar{padding-right:46px!important}
  html.st-vs5 #topbar #keybtn{margin-right:36px!important}
  html.st-vs5 #topbar .shell-dash-btn{
    position:absolute!important;right:4px;top:5px;z-index:20;
    width:34px;height:32px;margin:0!important;padding:4px!important;gap:0;
    justify-content:center;
  }
  html.st-vs5 #topbar .shell-dash-btn .shell-dash-label{display:none!important}
  html.st-vs5 #topbar .shell-dash-btn .shell-dash-glyph{width:23px;height:23px}
  html.st-vs5 #chart-search #syminput{width:88px}
  html.st-vs5 .dual-half{min-height:102px}
  html.st-vs5 #ctag-now,html.st-vs5 #ctag-prev{right:1px!important}
}
@media(prefers-reduced-motion:reduce){
  html.st-vs5 .wlchip,html.st-vs5 .mkt-cell,html.st-vs5 #chart-search #gobtn{transition:none!important}
  html.st-vs5 .wlchip:hover,html.st-vs5 .mkt-cell:hover{transform:none!important}
}
@media print{
  html.st-vs5 #chartarea,html.st-vs5 .dual-half,html.st-vs5 .mkt-cell{box-shadow:none!important;background:#fff!important}
}
`;
    document.head.appendChild(style);
  }

  window.ChartVisualV5 = {
    version: '5.0.0',
    isRedUp: isRedUp,
    themeFor: themeFor
  };

  injectStyle();
  console.info('[chart-visual-v5] chart workspace contract ready');
})();
