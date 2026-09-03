/* ============================================================================
 * visual_system_v5.js — Stock Terminal 5.0 executive visual system
 * ----------------------------------------------------------------------------
 * One late-cascade layer for elevation, borders, typography, controls and
 * dense financial tables. Directional colors remain owned by Colors/Market.
 * ========================================================================== */
(function () {
  'use strict';

  var STYLE_ID = 'visual-system-v5-css';
  var CSS = `
    :root{
      --bg:#050912;
      --bg2:#0a1321;
      --bg3:#101d2f;
      --bg4:#17263b;
      --border:rgba(148,163,184,.14);
      --bhi:rgba(125,211,252,.34);
      --vs-surface-0:#050912;
      --vs-surface-1:rgba(10,19,33,.92);
      --vs-surface-2:rgba(15,28,46,.88);
      --vs-surface-3:rgba(21,38,59,.9);
      --vs-border:rgba(148,163,184,.14);
      --vs-border-hi:rgba(125,211,252,.28);
      --vs-highlight:rgba(255,255,255,.055);
      --vs-cyan:rgba(56,189,248,.72);
      --vs-gold:rgba(245,197,24,.72);
      --vs-shadow-1:0 8px 24px -14px rgba(0,0,0,.72),inset 0 1px 0 rgba(255,255,255,.035);
      --vs-shadow-2:0 16px 38px -18px rgba(0,0,0,.82),0 0 0 1px rgba(2,8,23,.38),inset 0 1px 0 rgba(255,255,255,.05);
      --vs-radius-lg:11px;
      --vs-radius-md:8px;
      --vs-radius-sm:6px;
      --vs-beginner-card:
        radial-gradient(420px 190px at -5% -18%,rgba(56,189,248,.075),transparent 72%),
        radial-gradient(360px 170px at 105% -22%,rgba(245,197,24,.035),transparent 75%),
        linear-gradient(180deg,rgba(15,28,46,.96),rgba(8,17,31,.985));
      --vs-beginner-inset:
        linear-gradient(155deg,rgba(255,255,255,.035),transparent 42%),
        linear-gradient(180deg,rgba(16,29,48,.94),rgba(9,18,32,.985));
      --vs-title:#eef6ff;
      --vs-copy:#b8c7d9;
      --vs-muted:#7d91aa;
    }

    html.st-vs5,html.st-vs5 body{
      background-color:var(--vs-surface-0)!important;
      background-image:
        radial-gradient(900px 430px at 8% -12%,rgba(14,165,233,.11),transparent 68%),
        radial-gradient(720px 380px at 96% 2%,rgba(245,197,24,.055),transparent 70%),
        linear-gradient(180deg,#07101c 0%,#050912 56%,#040811 100%)!important;
    }
    html.st-vs5 body{font-synthesis:none;text-rendering:optimizeLegibility}
    html.st-vs5 #shell-views{
      background:
        radial-gradient(760px 360px at 15% 0%,rgba(14,165,233,.055),transparent 72%),
        radial-gradient(620px 300px at 88% 8%,rgba(245,197,24,.035),transparent 74%),
        linear-gradient(180deg,rgba(6,13,24,.98),rgba(4,9,18,.99))!important;
    }
    html.st-vs5 .sv-panel,html.st-vs5 .sv-mount{background:transparent}

    html.st-vs5 #topbar{
      background:linear-gradient(180deg,rgba(13,24,40,.96),rgba(7,15,27,.94))!important;
      border-bottom-color:rgba(125,211,252,.16)!important;
      box-shadow:0 10px 28px -20px rgba(0,0,0,.95),inset 0 -1px 0 rgba(255,255,255,.025);
      backdrop-filter:blur(14px) saturate(125%);
    }
    html.st-vs5 #wlbar,html.st-vs5 #rangebar,html.st-vs5 #rtabs,
    html.st-vs5 #indbar,html.st-vs5 #right{
      background:linear-gradient(180deg,rgba(12,22,37,.96),rgba(8,16,29,.98))!important;
      border-color:var(--vs-border)!important;
    }
    html.st-vs5 #chartarea{
      background:linear-gradient(145deg,rgba(5,10,19,.99),rgba(7,15,27,.98))!important;
    }

    html.st-vs5 #pl-root,html.st-vs5 .hub-root,html.st-vs5 #dc-root,
    html.st-vs5 #bd-root,html.st-vs5 #ht-root,html.st-vs5 #ah-root,
    html.st-vs5 #ai5-root,html.st-vs5 #bk-root,html.st-vs5 #nw-root,
    html.st-vs5 #sc-root,html.st-vs5 #right{
      font-variant-numeric:tabular-nums lining-nums;
    }
    html.st-vs5 #pl-root,html.st-vs5 .hub-root,html.st-vs5 #dc-root,
    html.st-vs5 #bd-root,html.st-vs5 #ht-root,html.st-vs5 #ah-root,
    html.st-vs5 #ai5-root,html.st-vs5 #bk-root,html.st-vs5 #nw-root,
    html.st-vs5 #sc-root{isolation:isolate}

    html.st-vs5 #pl-root .pl-head,html.st-vs5 .hub-root .hub-head,
    html.st-vs5 #dc-root .dc-head,html.st-vs5 #bd-root .bd-head,
    html.st-vs5 #ht-root .ht-head,html.st-vs5 #ah-root .ah-head,
    html.st-vs5 #ai5-root .ai5-head,html.st-vs5 #bk-root .bk-head,
    html.st-vs5 #nw-root .nw-head,html.st-vs5 #sc-root .sc-head{
      padding:1px 2px 5px!important;
      border-bottom:1px solid rgba(148,163,184,.1);
      box-shadow:0 7px 18px -18px rgba(0,0,0,.92);
    }
    html.st-vs5 #pl-root .pl-title,html.st-vs5 .hub-root .hub-title,
    html.st-vs5 #dc-root .dc-title,html.st-vs5 #bd-root .bd-title,
    html.st-vs5 #ht-root .ht-title,html.st-vs5 #ah-root .ah-title,
    html.st-vs5 #ai5-root .ai5-title,html.st-vs5 #bk-root .bk-title,
    html.st-vs5 #nw-root .nw-title,html.st-vs5 #sc-root .sc-title{
      color:var(--vs-title)!important;text-shadow:0 2px 16px rgba(0,0,0,.52);
    }

    html.st-vs5 #pl-root .pl-beginner-hero,
    html.st-vs5 #pl-root .pl-market-radar,
    html.st-vs5 #pl-root .pl-beginner-advanced,
    html.st-vs5 .hub-root .hub-sec,
    html.st-vs5 #dc-root .dc-card,
    html.st-vs5 #dc-root .dc-command-fold,
    html.st-vs5 #dc-root .dc-lab-box,
    html.st-vs5 #bd-root .bd-sec,
    html.st-vs5 #ht-root .ht-wd,
    html.st-vs5 #ht-root .ht-dash>div,
    html.st-vs5 #ah-root .ah-sec,
    html.st-vs5 #ai5-root .ai5-sec,
    html.st-vs5 #bk-root .bk-panel,
    html.st-vs5 #nw-root .nw-card,
    html.st-vs5 #sc-root .sc-grp,
    html.st-vs5 #sc-root #sc-results{
      background:var(--vs-beginner-card)!important;
      border:1px solid var(--vs-border)!important;
      border-radius:var(--vs-radius-lg)!important;
      box-shadow:var(--vs-shadow-1),inset 0 1px 0 rgba(125,211,252,.045);
    }

    html.st-vs5 #dc-root .dc-card h3,
    html.st-vs5 #pl-root .pl-sec h4,
    html.st-vs5 .hub-root .hub-sec h4,
    html.st-vs5 #bd-root .bd-sec h4,
    html.st-vs5 #ht-root .ht-wd h4,
    html.st-vs5 #ht-root .ht-dash h4,
    html.st-vs5 #ah-root .ah-sec h4,
    html.st-vs5 #ai5-root .ai5-sec h4,
    html.st-vs5 #bk-root .bk-panel h4,
    html.st-vs5 #nw-root .nw-card h4,
    html.st-vs5 #sc-root .sc-grp h4{
      font-family:"Noto Sans TC",sans-serif!important;font-weight:850!important;
      letter-spacing:.35px;text-shadow:0 2px 12px rgba(0,0,0,.38);
    }

    html.st-vs5 #pl-root .pl-sec h4,
    html.st-vs5 .hub-root .hub-sec h4,
    html.st-vs5 #bd-root .bd-sec h4,
    html.st-vs5 #ah-root .ah-sec h4,
    html.st-vs5 #ai5-root .ai5-sec h4,
    html.st-vs5 #nw-root .nw-card h4,
    html.st-vs5 #sc-root .sc-grp h4{
      position:relative;padding-left:8px;
    }
    html.st-vs5 #pl-root .pl-sec h4:before,
    html.st-vs5 .hub-root .hub-sec h4:before,
    html.st-vs5 #bd-root .bd-sec h4:before,
    html.st-vs5 #ah-root .ah-sec h4:before,
    html.st-vs5 #ai5-root .ai5-sec h4:before,
    html.st-vs5 #nw-root .nw-card h4:before,
    html.st-vs5 #sc-root .sc-grp h4:before{
      content:"";position:absolute;left:0;top:18%;bottom:18%;width:2px;border-radius:999px;
      background:linear-gradient(180deg,rgba(125,211,252,.9),rgba(245,197,24,.52));
      box-shadow:0 0 10px rgba(56,189,248,.22);
    }
    html.st-vs5 #bd-root .bd-movers{
      border-color:rgba(125,211,252,.24)!important;
      box-shadow:var(--vs-shadow-1),inset 0 1px 0 rgba(125,211,252,.07)!important;
    }

    html.st-vs5 #pl-root .pl-simple-card,
    html.st-vs5 #pl-root .pl-radar-card,
    html.st-vs5 #pl-root .pl-safe-level,
    html.st-vs5 #pl-root .pl-advanced-card,
    html.st-vs5 .hub-root .hub-card,
    html.st-vs5 .hub-root .hub-strip .cell,
    html.st-vs5 .hub-root .hub-inst-hero>div,
    html.st-vs5 #pl-root .pl-strip .cell,
    html.st-vs5 #dc-root .dc-feature,
    html.st-vs5 #dc-root .dc-level,
    html.st-vs5 #dc-root .dc-temp-light,
    html.st-vs5 #dc-root .dc-options-kpi,
    html.st-vs5 #dc-root .dc-options-layer,
    html.st-vs5 #dc-root .dc-options-density-card,
    html.st-vs5 #dc-root .dc-options-change,
    html.st-vs5 #bd-root .bd-strip .cell,
    html.st-vs5 #ht-root .ht-kpi .k,
    html.st-vs5 #ah-root .ah-strip .cell,
    html.st-vs5 #ai5-root .ai5-strip .cell,
    html.st-vs5 #bk-root .bk-card,
    html.st-vs5 #nw-root .nw-strip .cell,
    html.st-vs5 #nw-root .nw-stat{
      background:var(--vs-beginner-inset)!important;
      border-color:var(--vs-border)!important;
      border-radius:var(--vs-radius-md)!important;
      box-shadow:inset 0 1px 0 rgba(255,255,255,.035),0 7px 18px -16px rgba(0,0,0,.9);
    }

    html.st-vs5 .hub-root .hub-strip .cell,
    html.st-vs5 .hub-root .hub-inst-hero>div,
    html.st-vs5 #pl-root .pl-strip .cell,
    html.st-vs5 #dc-root .dc-feature,
    html.st-vs5 #bd-root .bd-strip .cell,
    html.st-vs5 #ht-root .ht-kpi .k,
    html.st-vs5 #ah-root .ah-strip .cell,
    html.st-vs5 #ai5-root .ai5-strip .cell,
    html.st-vs5 #nw-root .nw-strip .cell{
      position:relative;overflow:hidden;
      box-shadow:inset 0 1px 0 rgba(125,211,252,.14),0 8px 20px -17px rgba(0,0,0,.92)!important;
      transition:border-color .16s ease,box-shadow .16s ease,filter .16s ease;
    }
    html.st-vs5 .hub-root .hub-strip .cell:before,
    html.st-vs5 .hub-root .hub-inst-hero>div:before,
    html.st-vs5 #pl-root .pl-strip .cell:before,
    html.st-vs5 #dc-root .dc-feature:before,
    html.st-vs5 #bd-root .bd-strip .cell:before,
    html.st-vs5 #ht-root .ht-kpi .k:before,
    html.st-vs5 #ah-root .ah-strip .cell:before,
    html.st-vs5 #ai5-root .ai5-strip .cell:before,
    html.st-vs5 #nw-root .nw-strip .cell:before{
      content:"";position:absolute;left:12px;right:12px;top:0;height:1px;pointer-events:none;
      background:linear-gradient(90deg,transparent,rgba(125,211,252,.52),rgba(245,197,24,.22),transparent);
    }
    html.st-vs5 .hub-root .hub-strip .cell:hover,
    html.st-vs5 #pl-root .pl-strip .cell:hover,
    html.st-vs5 #dc-root .dc-feature:hover,
    html.st-vs5 #bd-root .bd-strip .cell:hover,
    html.st-vs5 #ht-root .ht-kpi .k:hover,
    html.st-vs5 #ah-root .ah-strip .cell:hover,
    html.st-vs5 #ai5-root .ai5-strip .cell:hover,
    html.st-vs5 #nw-root .nw-strip .cell:hover{
      border-color:var(--vs-border-hi)!important;
      box-shadow:inset 0 1px 0 rgba(125,211,252,.2),0 10px 23px -17px rgba(0,0,0,.95)!important;
    }
    html.st-vs5 .hub-root .hub-strip .v,
    html.st-vs5 #pl-root .pl-strip .v,
    html.st-vs5 #bd-root .bd-strip .v,
    html.st-vs5 #ah-root .ah-strip .v,
    html.st-vs5 #ai5-root .ai5-strip .v,
    html.st-vs5 #nw-root .nw-strip .v{
      color:var(--vs-title);text-shadow:0 2px 13px rgba(0,0,0,.42);
    }

    html.st-vs5 #bk-root .bk-empty-card,
    html.st-vs5 #nw-root .nw-empty{
      box-shadow:var(--vs-shadow-2);
    }

    html.st-vs5 #pl-root .pl-simple-card,
    html.st-vs5 #pl-root .pl-radar-card,
    html.st-vs5 .hub-root .hub-card,
    html.st-vs5 #bk-root .bk-card{
      transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease,background .16s ease;
    }
    html.st-vs5 #pl-root .pl-simple-card:hover,
    html.st-vs5 #pl-root .pl-radar-card:hover,
    html.st-vs5 .hub-root .hub-card:hover,
    html.st-vs5 #bk-root .bk-card:hover{
      transform:translateY(-1px);
      border-color:var(--vs-border-hi)!important;
      box-shadow:0 13px 28px -18px rgba(0,0,0,.92),0 0 0 1px rgba(56,189,248,.06),inset 0 1px 0 rgba(255,255,255,.055);
    }

    html.st-vs5 #pl-root .pl-beginner-hero{
      background:
        radial-gradient(420px 210px at 3% 0%,rgba(56,189,248,.13),transparent 70%),
        radial-gradient(520px 250px at 98% 0%,rgba(245,197,24,.055),transparent 72%),
        linear-gradient(135deg,rgba(17,32,53,.97),rgba(8,18,32,.98) 62%,rgba(9,27,38,.96))!important;
      border-color:rgba(125,211,252,.24)!important;
      box-shadow:var(--vs-shadow-2),0 0 34px -25px rgba(56,189,248,.65)!important;
    }
    html.st-vs5 #pl-root .pl-beginner-hero:before{
      content:"";position:absolute;left:18px;right:18px;top:0;height:1px;z-index:2;pointer-events:none;
      background:linear-gradient(90deg,transparent,rgba(125,211,252,.72),rgba(245,197,24,.36),transparent);
    }
    html.st-vs5 #pl-root .pl-beginner-gauge{filter:drop-shadow(0 10px 18px rgba(0,0,0,.34))}
    html.st-vs5 #pl-root .pl-beginner-copy h2{text-shadow:0 2px 18px rgba(0,0,0,.45)}
    html.st-vs5 #pl-root .pl-simple-card:before{
      content:"";position:absolute;left:12px;right:12px;top:-1px;height:1px;border-radius:999px;opacity:.9;
      background:linear-gradient(90deg,transparent,rgba(125,211,252,.58),transparent);
    }
    html.st-vs5 #pl-root .pl-simple-card.money:before{background:linear-gradient(90deg,transparent,rgba(245,197,24,.64),transparent)}
    html.st-vs5 #pl-root .pl-simple-card.volume:before{background:linear-gradient(90deg,transparent,rgba(167,139,250,.58),transparent)}
    html.st-vs5 #pl-root .pl-market-radar{
      box-shadow:var(--vs-shadow-2)!important;
      border-color:rgba(125,211,252,.18)!important;
    }
    html.st-vs5 #pl-root .pl-safe-level.ceiling{box-shadow:inset 2px 0 0 rgba(248,113,113,.48),var(--vs-shadow-1)}
    html.st-vs5 #pl-root .pl-safe-level.floor{box-shadow:inset 2px 0 0 rgba(74,222,128,.45),var(--vs-shadow-1)}
    html.st-vs5 #pl-root .pl-safe-level.stale{box-shadow:inset 2px 0 0 rgba(250,204,21,.45),var(--vs-shadow-1)}

    html.st-vs5 .pl-btn:not(.primary):not(.on),
    html.st-vs5 .hub-btn:not(.primary):not(.on),
    html.st-vs5 .dc-btn:not(.primary),
    html.st-vs5 .bd-btn:not(.primary):not(.on),
    html.st-vs5 .ht-btn:not(.primary):not(.on),
    html.st-vs5 .ah-btn:not(.primary):not(.on),
    html.st-vs5 .ai5-btn:not(.primary):not(.on),
    html.st-vs5 .bk-btn:not(.primary):not(.on),
    html.st-vs5 .nw-btn:not(.primary):not(.on),
    html.st-vs5 .sc-btn:not(.primary),
    html.st-vs5 .mktbtn,html.st-vs5 #keybtn,
    html.st-vs5 .m-btn-sec{
      background:linear-gradient(180deg,rgba(24,40,62,.82),rgba(12,24,40,.9))!important;
      border-color:rgba(148,163,184,.19)!important;
      border-radius:var(--vs-radius-sm)!important;
      box-shadow:inset 0 1px 0 rgba(255,255,255,.035),0 4px 12px -10px rgba(0,0,0,.9);
    }
    html.st-vs5 .pl-btn:hover,html.st-vs5 .hub-btn:hover,html.st-vs5 .dc-btn:hover,
    html.st-vs5 .bd-btn:hover,html.st-vs5 .ht-btn:hover,html.st-vs5 .ah-btn:hover,
    html.st-vs5 .ai5-btn:hover,html.st-vs5 .bk-btn:hover,html.st-vs5 .nw-btn:hover,
    html.st-vs5 .sc-btn:hover,html.st-vs5 .mktbtn:hover,html.st-vs5 #keybtn:hover{
      border-color:var(--vs-border-hi)!important;
      box-shadow:0 7px 16px -12px rgba(0,0,0,.95),0 0 0 1px rgba(56,189,248,.055);
    }
    html.st-vs5 .pl-btn.primary,html.st-vs5 .pl-btn.on,
    html.st-vs5 .hub-btn.primary,html.st-vs5 .hub-btn.on,
    html.st-vs5 .dc-btn.primary,html.st-vs5 .bd-btn.primary,html.st-vs5 .bd-btn.on,
    html.st-vs5 .ht-btn.primary,html.st-vs5 .ht-btn.on,
    html.st-vs5 .ah-btn.primary,html.st-vs5 .ah-btn.on,
    html.st-vs5 .ai5-btn.primary,html.st-vs5 .ai5-btn.on,
    html.st-vs5 .bk-btn.primary,html.st-vs5 .bk-btn.on,
    html.st-vs5 .nw-btn.primary,html.st-vs5 .nw-btn.on{
      box-shadow:0 7px 18px -11px rgba(245,197,24,.55),inset 0 1px 0 rgba(255,255,255,.2)!important;
    }

    html.st-vs5 #dc-root details>summary,
    html.st-vs5 #pl-root details>summary,
    html.st-vs5 .hub-root details>summary,
    html.st-vs5 #bd-root details>summary,
    html.st-vs5 #ht-root details>summary,
    html.st-vs5 #ah-root details>summary,
    html.st-vs5 #ai5-root details>summary,
    html.st-vs5 #bk-root details>summary,
    html.st-vs5 #nw-root details>summary,
    html.st-vs5 #sc-root details>summary{
      border-radius:var(--vs-radius-sm);transition:color .16s ease,background .16s ease;
    }
    html.st-vs5 #dc-root details>summary:hover,
    html.st-vs5 #pl-root details>summary:hover,
    html.st-vs5 .hub-root details>summary:hover,
    html.st-vs5 #bd-root details>summary:hover,
    html.st-vs5 #ht-root details>summary:hover,
    html.st-vs5 #ah-root details>summary:hover,
    html.st-vs5 #ai5-root details>summary:hover,
    html.st-vs5 #bk-root details>summary:hover,
    html.st-vs5 #nw-root details>summary:hover,
    html.st-vs5 #sc-root details>summary:hover{background:rgba(56,189,248,.045)}

    html.st-vs5 .pl-weather,html.st-vs5 .pl-risk-pill,
    html.st-vs5 .hub-root .badge,html.st-vs5 .hub-root .hub-seg,
    html.st-vs5 #dc-root .tag,html.st-vs5 #dc-root .dc-signal,
    html.st-vs5 .vz-chip,html.st-vs5 .phase-badge{
      box-shadow:inset 0 1px 0 rgba(255,255,255,.045),0 5px 14px -12px rgba(0,0,0,.9);
      backdrop-filter:blur(8px) saturate(120%);
    }

    html.st-vs5 .hub-root table,html.st-vs5 #dc-root table,
    html.st-vs5 #bd-root table,html.st-vs5 #ht-root table,
    html.st-vs5 #ah-root table,html.st-vs5 #ai5-root table,
    html.st-vs5 #bk-root table,html.st-vs5 #nw-root table,
    html.st-vs5 #sc-root table{
      border-collapse:separate;border-spacing:0;
    }
    html.st-vs5 .hub-root th,html.st-vs5 #dc-root th,
    html.st-vs5 #bd-root th,html.st-vs5 #ht-root th,
    html.st-vs5 #ah-root th,html.st-vs5 #ai5-root th,
    html.st-vs5 #bk-root th,html.st-vs5 #nw-root th,
    html.st-vs5 #sc-root th{
      background:linear-gradient(180deg,rgba(19,34,54,.98),rgba(10,21,36,.98))!important;
      border-bottom-color:rgba(148,163,184,.18)!important;
      box-shadow:inset 0 -1px 0 rgba(255,255,255,.02);
    }
    html.st-vs5 .hub-root tbody tr:nth-child(even) td,
    html.st-vs5 #dc-root tbody tr:nth-child(even) td,
    html.st-vs5 #bd-root tbody tr:nth-child(even) td,
    html.st-vs5 #ah-root tbody tr:nth-child(even) td,
    html.st-vs5 #ai5-root tbody tr:nth-child(even) td,
    html.st-vs5 #bk-root tbody tr:nth-child(even) td,
    html.st-vs5 #nw-root tbody tr:nth-child(even) td,
    html.st-vs5 #sc-root tbody tr:nth-child(even) td{background:rgba(148,163,184,.018)}
    html.st-vs5 .hub-root tbody tr:hover td,html.st-vs5 #dc-root tbody tr:hover td,
    html.st-vs5 #bd-root tbody tr:hover td,html.st-vs5 #ah-root tbody tr:hover td,
    html.st-vs5 #ai5-root tbody tr:hover td,html.st-vs5 #bk-root tbody tr:hover td,
    html.st-vs5 #nw-root tbody tr:hover td,html.st-vs5 #sc-root tbody tr:hover td{
      background:rgba(56,189,248,.055)!important;
    }

    /* Strategy Decision Center: readability contract.
       Chinese UI copy uses a proportional face; figures and market codes stay mono. */
    html.st-vs5 #dc-root{
      --dc-font-ui:"Noto Sans TC","PingFang TC","Microsoft JhengHei UI",sans-serif;
      --dc-font-mono:"JetBrains Mono","IBM Plex Mono",Consolas,monospace;
      font-family:var(--dc-font-ui)!important;font-size:11px;line-height:1.55;
      text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased;
    }
    html.st-vs5 #dc-root .dc-title{
      font-family:var(--dc-font-ui)!important;font-size:24px!important;font-weight:700!important;
      line-height:1.25!important;letter-spacing:.01em;
    }
    html.st-vs5 #dc-root .dc-sub{font-size:11px!important;line-height:1.5!important}
    html.st-vs5 #dc-root .dc-btn{
      padding:6px 10px!important;font:700 11px/1.35 var(--dc-font-ui)!important;
    }
    html.st-vs5 #dc-root .dc-command-fold>summary{
      padding:9px 11px!important;font-size:11.5px!important;line-height:1.45!important;
    }
    html.st-vs5 #dc-root .dc-command{gap:9px!important;padding:9px!important}
    html.st-vs5 #dc-root .dc-command .box{padding:10px 12px!important}
    html.st-vs5 #dc-root .dc-grid{
      grid-template-columns:minmax(0,1fr) minmax(0,1fr)!important;gap:10px!important;
    }
    html.st-vs5 #dc-root .dc-card{padding:11px 12px!important;margin-bottom:10px!important}
    html.st-vs5 #dc-root .dc-card h3{
      padding-left:8px!important;margin-bottom:10px!important;font-size:13.5px!important;
      line-height:1.4!important;font-weight:700!important;
    }
    html.st-vs5 #dc-root .k{font-size:10.5px!important;line-height:1.45!important}
    html.st-vs5 #dc-root .v{
      font:800 16px/1.3 var(--dc-font-mono)!important;letter-spacing:-.02em;
    }
    html.st-vs5 #dc-root .s{font-size:10.5px!important;line-height:1.55!important}
    html.st-vs5 #dc-root .dc-scenario{gap:8px!important}
    html.st-vs5 #dc-root .dc-feature{padding:9px!important}
    html.st-vs5 #dc-root .dc-feature>.s{
      height:auto!important;min-height:34px;line-height:1.55!important;
    }
    html.st-vs5 #dc-root .dc-signal,html.st-vs5 #dc-root .tag{
      padding:2px 6px!important;font-size:9px!important;line-height:1.25!important;
    }
    html.st-vs5 #dc-root .dc-scale-legend,
    html.st-vs5 #dc-root .dc-gauge-scale{font-size:8.5px!important}
    html.st-vs5 #dc-root .dc-level{padding:9px 4px!important}
    html.st-vs5 #dc-root .dc-level b{
      font:800 15px/1.25 var(--dc-font-mono)!important;
    }
    html.st-vs5 #dc-root .dc-div{padding:9px 10px!important;margin:7px 0!important}
    html.st-vs5 #dc-root .dc-div b{font-size:12px!important;line-height:1.45!important}
    html.st-vs5 #dc-root .dc-div p,
    html.st-vs5 #dc-root .dc-div-insight{font-size:10.5px!important;line-height:1.55!important}
    html.st-vs5 #dc-root .dc-news-links>span:first-child,
    html.st-vs5 #dc-root .dc-news-watch{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-metric{min-width:88px!important;padding:6px 8px!important}
    html.st-vs5 #dc-root .dc-metric span{font-size:9px!important}
    html.st-vs5 #dc-root .dc-metric b{font:800 11px/1.4 var(--dc-font-mono)!important}
    html.st-vs5 #dc-root .dc-overlay text,
    html.st-vs5 #dc-root .dc-breadth-bar i{font-size:8px!important}
    html.st-vs5 #dc-root .dc-mode-tag{font-size:9px!important}
    html.st-vs5 #dc-root .dc-stop{padding:8px!important}
    html.st-vs5 #dc-root .dc-stop b{font-size:10.5px!important}
    html.st-vs5 #dc-root .dc-confidence strong{font-size:14px!important}
    html.st-vs5 #dc-root .dc-confidence small{font-size:9px!important}
    html.st-vs5 #dc-root .dc-warning-time-chip,
    html.st-vs5 #dc-root .dc-warning-threshold{
      font-size:10px!important;line-height:1.4!important;
    }
    html.st-vs5 #dc-root .dc-warning-market-cell,
    html.st-vs5 #dc-root .dc-warning-disclaimer,
    html.st-vs5 #dc-root .dc-warning-divergence{
      font-size:10px!important;line-height:1.5!important;
    }
    html.st-vs5 #dc-root .dc-warning-market-value{
      font:800 12px/1.35 var(--dc-font-mono)!important;
    }

    html.st-vs5 #dc-root table{font-size:10.5px!important;line-height:1.45!important}
    html.st-vs5 #dc-root th,html.st-vs5 #dc-root td{padding:7px 8px!important}
    html.st-vs5 #dc-root th{font-weight:700!important;letter-spacing:.02em}
    html.st-vs5 #dc-root .dc-scroll{max-height:300px!important}
    html.st-vs5 #dc-root .dc-ledger-toolbar{gap:8px!important;padding:9px!important}
    html.st-vs5 #dc-root .dc-ledger-tabs{gap:5px!important;padding:7px 9px!important}
    html.st-vs5 #dc-root .dc-ledger-search input{
      padding:7px 9px 7px 28px!important;font-size:10.5px!important;
    }
    html.st-vs5 #dc-root .dc-ledger-btn{padding:4px 8px!important;font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-ledger-feedback{font-size:9px!important}
    html.st-vs5 #dc-root .dc-ledger-table{max-height:360px!important}
    html.st-vs5 #dc-root .dc-evidence-key b{font-size:10.5px!important}
    html.st-vs5 #dc-root .dc-evidence-metric{font-size:9px!important}
    html.st-vs5 #dc-root .dc-category{font-size:8.5px!important}
    html.st-vs5 #dc-root .dc-value-main{
      font:800 11px/1.4 var(--dc-font-mono)!important;
    }
    html.st-vs5 #dc-root .dc-value-note,
    html.st-vs5 #dc-root .dc-source-meta,
    html.st-vs5 #dc-root .dc-fresh-label{font-size:9px!important;line-height:1.45!important}
    html.st-vs5 #dc-root .dc-kv{font-size:9px!important;padding:3px 5px!important}
    html.st-vs5 #dc-root .dc-source-link{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-linkage{font-size:8.5px!important}
    html.st-vs5 #dc-root .dc-ledger-empty{font-size:10.5px!important}
    html.st-vs5 #dc-root label{font-size:10px!important;line-height:1.45!important}
    html.st-vs5 #dc-root input,html.st-vs5 #dc-root select{
      padding:7px!important;font:11px/1.4 var(--dc-font-mono)!important;
    }
    html.st-vs5 #dc-root details>summary{font-size:11px!important;line-height:1.45!important}

    html.st-vs5 #dc-root .dc-lab>summary{font-size:13px!important;padding-bottom:9px!important}
    html.st-vs5 #dc-root .dc-lab>summary:after{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-lab-box{padding:9px!important}
    html.st-vs5 #dc-root .dc-lab-box .v{font-size:14px!important}
    html.st-vs5 #dc-root .dc-lab-table td,html.st-vs5 #dc-root .dc-lab-table th{font-size:10px!important}
    html.st-vs5 #dc-root .dc-temp{grid-template-columns:155px minmax(0,1fr)!important;padding:10px!important}
    html.st-vs5 #dc-root .dc-temp-state{font-size:13px!important;line-height:1.4!important}
    html.st-vs5 #dc-root .dc-temp-help{font-size:9.5px!important;line-height:1.5!important}
    html.st-vs5 #dc-root .dc-temp-light{padding:8px!important}
    html.st-vs5 #dc-root .dc-temp-light .k{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-temp-light .v{font-size:11.5px!important}
    html.st-vs5 #dc-root .dc-temp-light .s{font-size:9px!important}

    html.st-vs5 #dc-root .dc-oi-market{padding:10px!important}
    html.st-vs5 #dc-root .dc-oi-head b,
    html.st-vs5 #dc-root .dc-oi-state b{font-size:12px!important;line-height:1.45!important}
    html.st-vs5 #dc-root .dc-oi-state span,
    html.st-vs5 #dc-root .dc-oi-quality{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-oi-kpi{padding:8px!important}
    html.st-vs5 #dc-root .dc-oi-kpi .v{font:800 15px/1.3 var(--dc-font-mono)!important}
    html.st-vs5 #dc-root .dc-oi-kpi .s,
    html.st-vs5 #dc-root .dc-oi-authority{font-size:10px!important;line-height:1.5!important}
    html.st-vs5 #dc-root .dc-oi-detail>summary{font-size:10.5px!important}

    html.st-vs5 #dc-root .dc-options-meta,
    html.st-vs5 #dc-root .dc-options-status{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-options-layer{padding:10px!important}
    html.st-vs5 #dc-root .dc-options-layer>header b{font-size:11px!important}
    html.st-vs5 #dc-root .dc-options-layer>header span{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-options-kpi{padding:8px!important}
    html.st-vs5 #dc-root .dc-options-kpi .k{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-options-kpi .v{font-size:14px!important}
    html.st-vs5 #dc-root .dc-options-chart text{font-size:8.5px!important}
    html.st-vs5 #dc-root .dc-options-gamma-row{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-options-density-card{padding:9px!important}
    html.st-vs5 #dc-root .dc-options-density-card>header{font-size:9.5px!important}
    html.st-vs5 #dc-root .dc-options-density-card>header b{font-size:10.5px!important}
    html.st-vs5 #dc-root .dc-options-change-head{font-size:9px!important}
    html.st-vs5 #dc-root .dc-options-change-head b{font-size:10.5px!important}
    html.st-vs5 #dc-root .dc-options-change-cell .k{font-size:9px!important}
    html.st-vs5 #dc-root .dc-options-change-cell .v{font-size:11px!important}
    html.st-vs5 #dc-root .dc-options-warn,
    html.st-vs5 #dc-root .dc-note,
    html.st-vs5 #dc-root .dc-status{font-size:10px!important;line-height:1.55!important}
    html.st-vs5 #dc-root .dc-ai{font-size:12px!important;line-height:1.7!important}
    html.st-vs5 #dc-root .dc-source-btn{font-size:10px!important;padding:4px 8px!important}
    html.st-vs5 #dc-root .dc-title,html.st-vs5 #dc-root .dc-card h3,
    html.st-vs5 #dc-root .dc-div b,html.st-vs5 #dc-root th,
    html.st-vs5 #dc-root .dc-lab>summary{overflow-wrap:anywhere}

    @media(max-width:1000px){
      html.st-vs5 #dc-root .dc-grid,html.st-vs5 #dc-root .dc-temp,
      html.st-vs5 #dc-root .dc-oi-grid{grid-template-columns:1fr!important}
    }
    @media(max-width:650px){
      html.st-vs5 #dc-root .dc-title{font-size:21px!important}
      html.st-vs5 #dc-root .dc-scenario,
      html.st-vs5 #dc-root .dc-risk-grid,
      html.st-vs5 #dc-root .dc-lab-grid{grid-template-columns:1fr!important}
      html.st-vs5 #dc-root .dc-oi-kpis{grid-template-columns:repeat(2,minmax(0,1fr))!important}
      html.st-vs5 #dc-root .dc-oi-kpi:last-child{grid-column:1/-1}
      html.st-vs5 #dc-root .dc-card{padding:10px!important}
      html.st-vs5 #dc-root .dc-card h3{align-items:flex-start;flex-direction:column;gap:5px}
      html.st-vs5 #dc-root .dc-portfolio-switch{margin-left:0}
    }

    html.st-vs5 .stat-sect{
      background:linear-gradient(90deg,rgba(14,165,233,.055),rgba(5,9,18,.92) 52%,rgba(245,197,24,.025))!important;
      border-color:var(--vs-border)!important;color:#7890aa!important;
    }
    html.st-vs5 .stat-row{border-color:rgba(148,163,184,.1)!important}
    html.st-vs5 .stat-row:hover{background:rgba(56,189,248,.035)}
    html.st-vs5 .modal{background:rgba(2,6,14,.78)!important;backdrop-filter:blur(8px)}
    html.st-vs5 .mbox,html.st-vs5 .info-popup,html.st-vs5 #uni-box{
      background:linear-gradient(145deg,rgba(17,31,50,.98),rgba(7,15,27,.99))!important;
      border-color:rgba(125,211,252,.24)!important;border-radius:var(--vs-radius-lg)!important;
      box-shadow:0 24px 70px rgba(0,0,0,.62),inset 0 1px 0 rgba(255,255,255,.05)!important;
    }

    html.st-vs5 input,html.st-vs5 select,html.st-vs5 textarea{
      border-color:rgba(148,163,184,.18)!important;
      box-shadow:inset 0 1px 3px rgba(0,0,0,.28);
    }
    html.st-vs5 input:focus,html.st-vs5 select:focus,html.st-vs5 textarea:focus{
      border-color:rgba(125,211,252,.58)!important;
      box-shadow:0 0 0 2px rgba(56,189,248,.09),inset 0 1px 3px rgba(0,0,0,.22)!important;
      outline:none;
    }
    html.st-vs5 button:focus-visible,html.st-vs5 [role=button]:focus-visible,
    html.st-vs5 [role=link]:focus-visible,html.st-vs5 a:focus-visible,
    html.st-vs5 summary:focus-visible{
      outline:2px solid rgba(125,211,252,.85)!important;outline-offset:2px!important;
    }
    html.st-vs5 *{scrollbar-color:rgba(100,116,139,.52) rgba(5,9,18,.32);scrollbar-width:thin}
    html.st-vs5 ::-webkit-scrollbar{width:8px;height:8px}
    html.st-vs5 ::-webkit-scrollbar-track{background:rgba(5,9,18,.32)}
    html.st-vs5 ::-webkit-scrollbar-thumb{background:rgba(100,116,139,.5);border:2px solid transparent;border-radius:999px;background-clip:padding-box}
    html.st-vs5 ::-webkit-scrollbar-thumb:hover{background:rgba(125,211,252,.42);border:2px solid transparent;background-clip:padding-box}

    @media(max-width:900px){
      :root{--vs-radius-lg:9px;--vs-radius-md:7px}
      html.st-vs5 #pl-root .pl-beginner-hero{box-shadow:var(--vs-shadow-1)!important}
    }
    @media(prefers-reduced-motion:reduce){
      html.st-vs5 #pl-root .pl-simple-card,html.st-vs5 #pl-root .pl-radar-card,
      html.st-vs5 .hub-root .hub-card,html.st-vs5 #bk-root .bk-card{transition:none!important}
      html.st-vs5 #pl-root .pl-simple-card:hover,html.st-vs5 #pl-root .pl-radar-card:hover,
      html.st-vs5 .hub-root .hub-card:hover,html.st-vs5 #bk-root .bk-card:hover{transform:none!important}
    }
    @media print{
      html.st-vs5,html.st-vs5 body,html.st-vs5 #shell-views{background:#fff!important;background-image:none!important}
      html.st-vs5 *{box-shadow:none!important;backdrop-filter:none!important}
    }
  `;

  function inject() {
    var style = document.getElementById(STYLE_ID);
    if (!style) {
      style = document.createElement('style');
      style.id = STYLE_ID;
    }
    style.textContent = CSS;
    document.head.appendChild(style); // Move to the end of the cascade.
    document.documentElement.classList.add('st-vs5');
  }

  function schedule() { setTimeout(inject, 0); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule, { once: true });
  } else {
    schedule();
  }
  window.addEventListener('shell:route', schedule, { passive: true });
  window.VisualSystemV5 = { inject: inject, version: '5.0.0' };
})();
