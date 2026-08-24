/**
 * layout_visual_v5_selftest.js — overview/breadth layout and shared visual contracts.
 * Run: node tests/layout_visual_v5_selftest.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
function read(rel) { return fs.readFileSync(path.join(root, rel), 'utf8'); }

const pulse = read('src/ui/pulse_v5.js');
const breadth = read('src/ui/breadth_v5.js');
const news = read('src/ui/news_v5.js');
const book = read('src/ui/book_v5.js');
const visual = read('src/ui/visual_system_v5.js');
const decision = read('src/ui/decision_v5.js');

let failed = 0;
function ok(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

ok(!pulse.includes('線型＝加權 ^TWII（非台指期）；櫃買／台指期近月見頂列'),
  'overview removes the redundant weighted-index annotation');
ok(pulse.includes('grid-template-columns:repeat(5,minmax(0,1fr))') &&
  !pulse.includes('#pl-root .pl-zone.z-top{') && !pulse.includes('#pl-root .pl-zone.z-bot{'),
  'overview desktop second and third rows keep five equal-width panels');
ok(pulse.includes("MOBILE_LAYOUT_CONTRACT = '2col-scroll'") &&
  pulse.includes('#pl-root .pl-zone{grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:300px') &&
  pulse.includes('#pl-body.pl-mode-expert{display:block;overflow:visible') &&
  pulse.includes('#shell-views:has(#view-pulse.on){overflow-x:hidden!important;overflow-y:auto!important'),
  'overview mobile second and third rows use two readable columns with page scrolling');
ok(pulse.includes('#pl-root .pl-inst4,#pl-root .pl-bd4,#pl-root .pl-ohlc4{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px') &&
  pulse.includes('#pl-root .pl-score3 .sc.main{grid-column:1/-1}') &&
  pulse.includes('#pl-root .pl-strip{display:flex;gap:7px;overflow-x:auto') &&
  pulse.includes('#pl-root .pl-movers .vz-rowbar,#pl-root .pl-movers .vz-chip{display:none!important}') &&
  pulse.includes('@media(max-width:520px)') && pulse.includes('#pl-root .pl-global{grid-template-columns:1fr}') &&
  pulse.includes('#pl-root .pl-wl col.c-px{width:29%}'),
  'overview mobile KPI internals and headline strip avoid numeric/text collisions');
ok(pulse.includes('overflow-x:hidden;overflow-y:auto') && pulse.includes('scrollbar-gutter:stable'),
  'beginner short viewport scrolls safely instead of clipping its lower edge');

ok(breadth.includes('minmax(200px,.72fr)') && breadth.includes('minmax(390px,1.4fr)'),
  'breadth grid shifts width from structure to movers');
ok(breadth.includes('bd-sec bd-structure') && breadth.includes('bd-sec bd-movers'),
  'breadth sections expose semantic layout hooks');
ok(breadth.includes('#bd-root .bd-movers table.bd-hist{font-size:11px}'),
  'mover rankings receive a readable table scale');
ok(breadth.includes('.bd-structure .bd-score-wrap{flex:0 0 auto'),
  'compact breadth score stays beside its structure signal instead of drifting');

ok(news.includes('class="nw-empty"') && news.includes('目前沒有除權息事件'),
  'news empty data uses a deliberate empty state');
ok(book.includes('class="bk-empty"') && book.includes('尚未建立投組樣本'),
  'portfolio analysis empty state provides a three-step path');
ok(visual.includes('#bd-root .bd-movers') && visual.includes('.pl-sec h4:before'),
  'shared visual layer strengthens priority and section hierarchy');
ok(visual.includes('#pl-root .pl-strip .cell') && visual.includes('#nw-root .nw-strip .cell'),
  'overview and news KPI strips share the surface system');
ok(decision.includes('.dc-options-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))') &&
  decision.includes('.dc-options-scroll{max-width:100%;overflow-x:auto') &&
  decision.includes('.dc-options-chart svg{display:block;width:100%;height:118px') &&
  decision.includes('#dc-root .dc-options-kpis,#dc-root .dc-options-kpis.five{grid-template-columns:repeat(2,minmax(0,1fr))'),
  'options lab uses bounded four-to-two-column layout and contained horizontal overflow');
ok(decision.includes('.dc-options-density-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))') &&
  decision.includes('.dc-options-table{min-width:720px}') && decision.includes('.dc-options-change-grid{display:grid'),
  'options V2 density and history surfaces reflow by container while the five-column scenario table scrolls internally');
ok(visual.includes('#dc-root .dc-options-kpi') && visual.includes('#dc-root .dc-options-layer') &&
  visual.includes('summary:focus-visible'),
  'options lab inherits shared inset surfaces and keyboard focus treatment');
ok(visual.includes('--dc-font-ui:') && visual.includes('font-family:var(--dc-font-ui)!important') &&
  visual.includes('#dc-root .dc-title{') && visual.includes('font-size:24px!important') &&
  visual.includes('#dc-root table{font-size:10.5px!important'),
  'decision center separates readable Chinese UI type from monospaced market figures');
ok(visual.includes('grid-template-columns:minmax(0,1fr) minmax(0,1fr)!important') &&
  visual.includes('#dc-root .dc-evidence-key b{font-size:10.5px!important') &&
  visual.includes('#dc-root .dc-temp-light .s{font-size:9px!important'),
  'decision center uses both columns and raises dense evidence and exposure copy above micro-text sizes');
ok(visual.includes('@media(max-width:650px)') &&
  visual.includes('#dc-root .dc-scenario,') &&
  visual.includes('#dc-root .dc-risk-grid,') &&
  visual.includes('grid-template-columns:1fr!important'),
  'decision center reflows dense cards to one column on narrow screens');
ok(decision.includes('.dc-oi-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))') &&
  decision.includes('.dc-oi-scroll{max-width:100%;overflow-x:auto') &&
  decision.includes('#dc-root .dc-oi-kpis{grid-template-columns:repeat(2,minmax(0,1fr))') &&
  visual.includes('#dc-root .dc-oi-kpi .v{font:800 15px') &&
  visual.includes('#dc-root .dc-oi-grid{grid-template-columns:1fr!important'),
  'overnight/intraday lab has readable desktop KPIs, contained detail overflow and narrow-screen reflow');

if (failed) process.exit(1);
console.log('\nlayout_visual_v5_selftest PASSED');
