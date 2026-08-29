/* Stock Terminal 5.0 — auditable Strategic Decision page. */
(function () {
  'use strict';
  var SRV = window.SERVER || '';
  var timer = null;
  var lastContext = null;
  var lastEvidenceContext = null;
  var lastHoldings = [];
  var riskDraft = {};
  var portfolioMode = 'actual';
  var optionsLabOpen = true;
  var oiLabOpen = true;
  var optionsRefreshStarted = false;
  var evidenceView = { category: 'all', mode: 'all', scope: 'all', query: '' };
  var pendingFocus = null;
  var AI_TIMEOUT_MS = 12 * 60 * 1000;
  var aiBusy = false;
  var aiController = null;
  var aiAccessPromise = null;
  var privateProfile = window.ST_PRIVATE_WEB_PROFILE || null;
  var aiAccessRole = privateProfile
    ? (privateProfile.role === 'owner' ? 'owner' : (privateProfile.role === 'reader' ? 'reader' : 'unknown'))
    : 'owner';
  var aiDisplayState = { visible: false, text: '', error: false };

  var ACTIONS = {
    ALLOW_MEASURED_RISK: '允許受控增加風險', LIMIT_NEW_RISK: '限制新增風險',
    PROBE_WITH_CONFIRMATION: '僅可小幅試探', WAIT_FOR_CONFIRMATION: '等待訊號確認',
    DEFENSIVE: '採取防禦姿態', PRESERVE_LIQUIDITY: '優先保存流動性',
    NO_NEW_DIRECTION: '不建立新方向', HOLD: '維持既有曝險',
    ADD_RISK_WITHIN_LIMITS: '在限制內增加風險', ROTATE_TO_LOWER_BETA: '轉向較低 Beta',
    REVIEW_HEDGE: '檢查對沖', SMALL_PROBE: '小幅試探', REDUCE_CONCENTRATION: '降低集中曝險',
    REVIEW_LIQUIDITY: '檢查流動性', WAIT_FOR_REPAIR: '等待結構修復',
    REVIEW_DATA_QUALITY: '先檢查資料品質', ADD_LEVERAGE: '新增槓桿',
    CHASE_GAP_UP: '追逐跳空', ADD_DIRECTIONAL_RISK: '增加方向性風險',
    ADD_RISK: '增加風險', AVERAGE_DOWN_WITHOUT_CONFIRMATION: '無確認攤平',
    TREAT_OVERSOLD_AS_BUY_SIGNAL: '把超跌當買點', PUBLISH_POSITION_PERCENTAGE: '發布倉位百分比'
  };
  var CONSTRAINTS = {
    risk_profile_not_configured: '尚未設定 Risk Profile',
    risk_profile_invalid_numeric: 'Risk Profile 數值格式無效',
    risk_profile_invalid_exposure: 'Risk Profile 曝險上下限無效',
    portfolio_overlay_unavailable: '實際投組 Beta／VaR 覆蓋不可用，停止輸出範圍',
    portfolio_beta_cap: 'Portfolio Beta 觸發曝險上限',
    portfolio_var_cap: '單日 VaR 觸發曝險上限',
    single_name_over_limit: '單一持倉超過設定上限',
    sector_over_limit: '產業曝險超過設定上限',
    exposure_lab_research_cap: 'Exposure Lab 中長期研究上限',
    current_effective_gross_over_limit: '每日槓桿穿透後總曝險超過上限',
    lookthrough_tsmc_over_limit: '台積電經濟曝險超過單一持倉上限',
    insufficient_data_no_position_range: '核心資料不足，不發布曝險百分比',
    portfolio_not_provided: '未提供實際投組；範圍未套用投組風險上限',
    observation_pool_not_risk_overlay: '等權自選僅供觀察，不作投組風險上限'
    ,breadth_divergence_risk_lock: '指數與廣度背離信心高於 70%，啟動追價／槓桿鎖定'
  };

  function $(id) { return document.getElementById(id); }
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function num(v, d) { return v == null || !isFinite(Number(v)) ? '—' : Number(v).toFixed(d == null ? 2 : d); }
  function pct01(v) { return v == null ? '—' : Math.round(Number(v) * 100) + '%'; }
  function label(v) { return ACTIONS[v] || String(v || '—').replace(/_/g, ' '); }
  function listLabels(items) { return (items || []).map(label).join('・') || '—'; }
  function constraintLabel(v) {
    if (String(v || '').indexOf('risk_profile_missing:') === 0) return 'Risk Profile 欄位不完整';
    return CONSTRAINTS[v] || String(v || '').replace(/_/g, ' ');
  }

  function injectCSS() {
    var s = $('decision-v5-css');
    if (!s) { s = document.createElement('style'); s.id = 'decision-v5-css'; document.head.appendChild(s); }
    s.textContent =
      '#view-decision.sv-panel.on{overflow:auto!important;background:#060c16}' +
      '#mount-decision{min-height:100%;width:100%;min-width:0;box-sizing:border-box;padding:10px 12px 22px;overflow-x:hidden}' +
      '#dc-root{font-family:"JetBrains Mono",monospace;color:var(--text);width:100%;min-width:0;max-width:1780px;margin:auto}' +
      '#dc-root *{box-sizing:border-box}' +
      '#dc-root .dc-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:8px}' +
      '#dc-root .dc-title{font-family:"Noto Serif TC",serif;font-size:20px;color:var(--thi);font-weight:800}' +
      '#dc-root .dc-sub{font-size:9px;color:var(--tlo);margin-top:3px}' +
      '#dc-root .dc-actions{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}' +
      '#dc-root .dc-btn{border:1px solid var(--border);background:var(--bg3);color:var(--text);border-radius:5px;padding:5px 8px;font:700 9px "JetBrains Mono",monospace;cursor:pointer}' +
      '#dc-root .dc-btn:hover{border-color:var(--gold);color:var(--gold)}#dc-root .dc-btn:disabled{cursor:not-allowed;opacity:.55;border-color:#26364f;color:#75869d}' +
      '#dc-root .dc-btn.primary{background:var(--gold);color:#07101e;border-color:var(--gold)}' +
      '#dc-root .dc-command-fold{margin:0 0 8px;border:1px solid #26364f;border-radius:8px;background:#091321;overflow:hidden}' +
      '#dc-root .dc-command-fold>summary{list-style:none;display:flex;align-items:center;gap:8px;margin:0!important;padding:7px 10px;' +
        'color:#dbe6f2!important;font-size:9px!important;cursor:pointer;user-select:none}' +
      '#dc-root .dc-command-fold>summary::-webkit-details-marker{display:none}' +
      '#dc-root .dc-command-fold>summary .name{color:var(--gold);font-weight:850}' +
      '#dc-root .dc-command-fold>summary .brief{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aebdd0}' +
      '#dc-root .dc-command-fold>summary:after{content:"展開";margin-left:auto;color:var(--cyan);font-weight:800}' +
      '#dc-root .dc-command-fold[open]>summary{border-bottom:1px solid #26364f}' +
      '#dc-root .dc-command-fold[open]>summary:after{content:"收合"}' +
      '#dc-root .dc-command{display:grid;grid-template-columns:1.05fr 1.25fr 1.25fr;gap:7px;padding:7px}' +
      '#dc-root .dc-command .box{background:linear-gradient(180deg,#111b2e,#0b1220);border:1px solid #26364f;border-radius:8px;padding:9px 11px;min-width:0}' +
      '#dc-root .dc-command .box.regime{border-color:rgba(245,197,24,.55)}' +
      '#dc-root .k{font-size:9px;color:#92a4ba;letter-spacing:.5px}#dc-root .v{font-size:15px;color:var(--thi);font-weight:850;margin:3px 0;line-height:1.25}' +
      '#dc-root .s{font-size:9px;color:#b2c0d2;line-height:1.45}' +
      '#dc-root .dc-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:8px;align-items:start;min-width:0;max-width:100%}' +
      '#dc-root .dc-grid>div,#dc-root .dc-ledger,#dc-root .dc-ledger-table{min-width:0;max-width:100%}' +
      '#dc-root .dc-card{background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:8px 9px;margin-bottom:8px;min-width:0}' +
      '#dc-root .dc-focus{border-color:rgba(125,211,252,.78)!important;box-shadow:0 0 0 2px rgba(56,189,248,.14),0 0 24px rgba(56,189,248,.14)!important;' +
        'animation:dcFocusPulse 1.15s ease-in-out 2}' +
      '@keyframes dcFocusPulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.12)}}' +
      '#dc-root .dc-card h3{font-size:11px;color:var(--gold);margin:0 0 7px;border-left:2px solid var(--gold);padding-left:6px;display:flex;justify-content:space-between;gap:8px}' +
      '#dc-root .dc-portfolio-head{align-items:center;flex-wrap:wrap}' +
      '#dc-root .dc-portfolio-switch{display:flex;align-items:center;gap:3px;margin-left:auto}' +
      '#dc-root .dc-source-btn{padding:3px 7px;border:1px solid #30425c;border-radius:5px;background:#091422;color:#91a4bc;' +
        'font:700 7.5px "Noto Sans TC",sans-serif;cursor:pointer;white-space:nowrap}' +
      '#dc-root .dc-source-btn:hover{border-color:var(--cyan);color:#dbeafe}' +
      '#dc-root .dc-source-btn.on{border-color:rgba(245,197,24,.62);background:rgba(245,197,24,.12);color:var(--gold);' +
        'box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}' +
      '#dc-root .dc-scenario{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}' +
      '#dc-root .dc-feature{background:#0a1322;border:1px solid #203049;border-radius:5px;padding:6px;min-width:0;overflow:hidden}' +
      '#dc-root .dc-feature-head{display:flex;align-items:center;justify-content:space-between;gap:5px}.dc-feature-head .k{min-width:0}' +
      '#dc-root .dc-signal{padding:1px 5px;border-radius:999px;border:1px solid currentColor;font-size:7px;white-space:nowrap}' +
      '#dc-root .dc-signal.strong{color:#67e8f9}.dc-signal.positive{color:#7dd3fc}.dc-signal.neutral{color:#cbd5e1}.dc-signal.watch{color:#facc15}.dc-signal.alert{color:#fb923c}' +
      '#dc-root .dc-feature>.s{height:26px;overflow:hidden;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}' +
      '#dc-root .dc-feature .meter{height:5px;background:#17243a;border-radius:5px;overflow:hidden;margin-top:5px;position:relative}' +
      '#dc-root .dc-feature .meter:after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:#52627a}' +
      '#dc-root .dc-feature .meter i{display:block;height:100%;background:var(--cyan)}#dc-root .dc-feature.risk .meter i{background:#facc15}' +
      '#dc-root .dc-scale-legend{display:flex;justify-content:space-between;margin-top:3px;color:#60738d;font-size:6.5px}' +
      '#dc-root .dc-levels{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px}' +
      '#dc-root .dc-level{text-align:center;background:#0a1322;border:1px solid #203049;border-radius:5px;padding:7px 3px}' +
      '#dc-root .dc-level b{display:block;color:var(--thi);font-size:13px;margin-top:3px}' +
      '#dc-root .dc-div{padding:6px 7px;border:1px solid #2a3a52;border-radius:5px;margin:5px 0;background:#0a1322}' +
      '#dc-root .dc-div.warn{border-color:rgba(251,146,60,.55)}#dc-root .dc-div.critical{border-color:rgba(248,113,113,.65)}' +
      '#dc-root .dc-div.news-linked{border-color:rgba(245,197,24,.55);box-shadow:inset 2px 0 rgba(245,197,24,.8),0 0 12px rgba(245,197,24,.06)}' +
      '#dc-root .dc-news-links{display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-top:5px}' +
      '#dc-root .dc-news-links>span:first-child{color:#fbbf24;font-size:8px;font-weight:800}' +
      '#dc-root .dc-news-watch{padding:2px 6px;border:1px solid rgba(251,191,36,.35);border-radius:999px;' +
        'background:rgba(251,191,36,.08);color:#fde68a;font:700 8px "JetBrains Mono",monospace;cursor:pointer}' +
      '#dc-root .dc-news-watch:hover{background:rgba(251,191,36,.18);border-color:#fbbf24}' +
      '#dc-root .dc-div-head{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:32px}' +
      '#dc-root .dc-div b{font-size:10px;color:var(--thi)}#dc-root .dc-div p{margin:3px 0 0;font-size:8px;color:var(--tlo);line-height:1.4}' +
      '#dc-root .dc-div-insight{margin:5px 0 7px;padding:6px 8px;border-left:3px solid #f59e0b;background:rgba(245,158,11,.08);' +
        'color:#fde7bd;font:700 9px/1.5 "Noto Sans TC",sans-serif;border-radius:3px}' +
      '#dc-root .dc-metrics{display:flex;gap:4px;flex-wrap:wrap;margin:5px 0}' +
      '#dc-root .dc-metric{min-width:72px;padding:4px 6px;border:1px solid #263a55;border-radius:5px;background:#07111f}' +
      '#dc-root .dc-metric span{display:block;font-size:6.5px;color:#71849c}.dc-metric b{font-size:9px!important;color:#d9e8f7!important}' +
      '#dc-root .dc-structure{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(180px,.65fr);gap:7px;margin:6px 0}' +
      '#dc-root .dc-overlay{height:104px;border:1px solid #223650;border-radius:6px;background:linear-gradient(180deg,#07111f,#091625);overflow:hidden}' +
      '#dc-root .dc-overlay svg{display:block;width:100%;height:100%}.dc-overlay .idx{fill:none;stroke:#fbbf24;stroke-width:2.2}' +
      '#dc-root .dc-overlay .adv{fill:rgba(34,211,238,.28)}.dc-overlay .adv.weak{fill:rgba(251,146,60,.34)}' +
      '#dc-root .dc-overlay .warn-zone{fill:rgba(245,158,11,.09)}.dc-overlay text{font:6px "JetBrains Mono",monospace;fill:#71849b}' +
      '#dc-root .dc-structure-side{display:flex;flex-direction:column;gap:6px;min-width:0}' +
      '#dc-root .dc-breadth-bar{height:16px;display:flex;overflow:hidden;border-radius:5px;border:1px solid #2a3a50;background:#101a29}' +
      '#dc-root .dc-breadth-bar i{display:grid;place-items:center;min-width:0;font:800 6.5px "JetBrains Mono",monospace;color:#07111f;white-space:nowrap;overflow:hidden}' +
      '#dc-root .dc-breadth-bar .up{background:#fb7185}.dc-breadth-bar .flat{background:#94a3b8}.dc-breadth-bar .down{background:#34d399}' +
      '#dc-root .dc-basis-gauge{position:relative;height:36px;margin:9px 7px 5px;border-radius:18px;border:1px solid #2a415f;' +
        'background:linear-gradient(90deg,rgba(56,189,248,.20),rgba(148,163,184,.08) 42%,rgba(148,163,184,.08) 58%,rgba(251,146,60,.22))}' +
      '#dc-root .dc-basis-gauge:before{content:"";position:absolute;left:50%;top:4px;bottom:4px;width:1px;background:#91a4bb}' +
      '#dc-root .dc-basis-marker{position:absolute;top:50%;width:17px;height:17px;border-radius:50%;transform:translate(-50%,-50%);' +
        'background:#fbbf24;border:3px solid #fff3c4;box-shadow:0 0 14px rgba(251,191,36,.7)}' +
      '#dc-root .dc-gauge-scale{display:flex;justify-content:space-between;color:#6f829b;font-size:6.5px;margin:0 8px}' +
      '#dc-root .dc-mode-tag{display:inline-flex;padding:2px 6px;border-radius:999px;border:1px solid #3b516d;color:#a9bdd3;font-size:7px}' +
      '#dc-root .dc-mandatory{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px;margin:0 0 7px}' +
      '#dc-root .dc-stop{display:grid;grid-template-columns:24px 1fr;gap:6px;align-items:center;padding:6px;border:1px solid rgba(248,113,113,.62);' +
        'border-radius:6px;background:linear-gradient(135deg,rgba(127,29,29,.30),rgba(60,12,22,.22));box-shadow:inset 2px 0 #fb7185}' +
      '#dc-root .dc-stop .lamp{width:22px;height:22px;display:grid;place-items:center;border-radius:50%;background:#ef4444;color:white;' +
        'font-size:11px;box-shadow:0 0 14px rgba(239,68,68,.55)}.dc-stop b{font-size:8.5px;color:#fecaca}.dc-stop span{font-size:6.5px;color:#dba5ad}' +
      '#dc-root .dc-confidence{position:relative;display:inline-grid;place-items:center;width:54px;height:54px;border-radius:50%;' +
        'background:conic-gradient(#22d3ee var(--confidence),#203149 0);box-shadow:0 0 15px rgba(34,211,238,.18);flex:0 0 auto;transition:.18s ease}' +
      '#dc-root .dc-confidence:before{content:"";position:absolute;inset:5px;border-radius:50%;background:linear-gradient(145deg,#0c192a,#07101d);' +
        'border:1px solid rgba(103,232,249,.28);box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}' +
      '#dc-root .dc-confidence:hover{filter:brightness(1.12);box-shadow:0 0 19px rgba(34,211,238,.32)}' +
      '#dc-root .dc-confidence strong{position:relative;z-index:1;color:#dffbff;font-size:13px;line-height:1;font-weight:900;letter-spacing:-.35px}' +
      '#dc-root .dc-confidence small{font-size:8px;color:#67e8f9;margin-left:1px}' +
      '#dc-root .dc-breadth{height:56px;display:flex;align-items:flex-end;gap:2px;padding:5px 4px 2px;' +
        'background:#07101d;border:1px solid #203049;border-radius:5px;margin-bottom:6px;overflow:hidden}' +
      '#dc-root .dc-breadth i{flex:1 1 0;min-width:2px;max-width:12px;border-radius:2px 2px 0 0;background:var(--green);opacity:.82}' +
      '#dc-root .dc-breadth i.pos{background:var(--red)}' +
      '#dc-root table{width:100%;border-collapse:collapse;font-size:8px}#dc-root th,#dc-root td{padding:4px 5px;border-bottom:1px solid #1d2a40;text-align:left;vertical-align:top}' +
      '#dc-root th{color:#91a4bc;position:sticky;top:0;background:var(--bg2)}#dc-root td{color:#c5d0de}' +
      '#dc-root .dc-scroll{max-height:230px;overflow:auto}' +
      '#dc-root .tag{display:inline-flex;padding:1px 5px;border-radius:999px;border:1px solid #34455e;font-size:7px;color:#a9bad0;margin-right:3px}' +
      '#dc-root .tag.high{border-color:#f87171;color:#fecaca}#dc-root .tag.medium{border-color:#fb923c;color:#fed7aa}' +
      '#dc-root .dc-ledger{border:1px solid #203049;border-radius:7px;overflow:hidden;background:#07111e}' +
      '#dc-root .dc-ledger-toolbar{display:grid;grid-template-columns:minmax(150px,1fr) auto;gap:6px;padding:7px;border-bottom:1px solid #203049;background:#0a1524}' +
      '#dc-root .dc-ledger-search{position:relative}.dc-ledger-search input{margin:0;padding:6px 8px 6px 25px;font-size:8px}' +
      '#dc-root .dc-ledger-search:before{content:"⌕";position:absolute;left:8px;top:5px;color:var(--cyan);font-size:12px;z-index:1}' +
      '#dc-root .dc-ledger-actions,#dc-root .dc-ledger-tabs{display:flex;align-items:center;gap:4px;flex-wrap:wrap}' +
      '#dc-root .dc-ledger-tabs{padding:6px 7px;border-bottom:1px solid #1c2b40;background:#081320}' +
      '#dc-root .dc-ledger-tabs+.dc-ledger-tabs{padding-top:0}' +
      '#dc-root .dc-ledger-btn{border:1px solid #30445f;background:#091625;color:#9fb1c7;border-radius:999px;padding:3px 7px;' +
        'font:750 7px "Noto Sans TC",sans-serif;cursor:pointer;white-space:nowrap}' +
      '#dc-root .dc-ledger-btn:hover{border-color:var(--cyan);color:#dff8ff}.dc-ledger-btn.on{border-color:rgba(34,211,238,.68);background:rgba(34,211,238,.11);color:#8cecff}' +
      '#dc-root .dc-ledger-copy{border-radius:5px}.dc-ledger-feedback{min-width:48px;color:#67e8f9;font-size:7px;text-align:right}' +
      '#dc-root .dc-ledger-table{max-height:300px;overflow:auto}.dc-ledger-table table{table-layout:fixed}' +
      '#dc-root .dc-ledger-table th:nth-child(1){width:28px}.dc-ledger-table th:nth-child(2){width:29%}.dc-ledger-table th:nth-child(3){width:25%}.dc-ledger-table th:nth-child(5){width:21%}' +
      '#dc-root .dc-ledger-table td{vertical-align:middle;padding-top:6px;padding-bottom:6px;overflow-wrap:anywhere}' +
      '#dc-root .dc-ledger-row[hidden]{display:none!important}.dc-ledger-row.alert{background:linear-gradient(90deg,rgba(245,158,11,.07),transparent 55%)}' +
      '#dc-root .dc-fresh-dot{display:inline-block;width:9px;height:9px;border-radius:50%;box-shadow:0 0 8px currentColor}' +
      '#dc-root .dc-fresh-dot.fresh{color:#22d3ee;background:#22d3ee}.dc-fresh-dot.delay{color:#facc15;background:#facc15}' +
      '#dc-root .dc-fresh-dot.stale{color:#fb923c;background:#fb923c}.dc-fresh-dot.reference{color:#60a5fa;background:#60a5fa}' +
      '#dc-root .dc-evidence-key{display:flex;align-items:center;gap:4px;flex-wrap:wrap}.dc-evidence-key b{font-size:8.5px;color:#dce8f5}' +
      '#dc-root .dc-evidence-metric{font-size:7px;color:#7f93ab;margin-top:2px}.dc-category{font-size:6px;padding:1px 4px;border-radius:999px;background:#14243a;color:#89a6c5}' +
      '#dc-root .dc-value-main{font-size:9px;font-weight:850;color:#dbe8f5}.dc-value-note{font-size:6.5px;color:#8498b0;margin-top:2px}' +
      '#dc-root .dc-value-main.tw-up{color:var(--red)}#dc-root .dc-value-main.tw-down{color:var(--green)}' +
      '#dc-root .dc-value-main.us-up{color:var(--green)}#dc-root .dc-value-main.us-down{color:var(--red)}' +
      '#dc-root .dc-value-main.risk{color:#fb923c}.dc-value-main.watch{color:#facc15}' +
      '#dc-root .dc-kv-list{display:flex;gap:3px;flex-wrap:wrap}.dc-kv{display:inline-flex;gap:3px;padding:2px 4px;border:1px solid #29405e;border-radius:4px;background:#0a1727;font-size:6.5px}' +
      '#dc-root .dc-kv i{font-style:normal;color:#7890aa}.dc-kv b{color:#d7e5f4}' +
      '#dc-root .dc-source-link{color:#8ddff0;text-decoration:none;font-size:7.5px}.dc-source-link:hover{text-decoration:underline;color:#d7fbff}' +
      '#dc-root .dc-source-meta,.dc-fresh-label{font-size:6.5px;color:#72869f;margin-top:2px;line-height:1.35}' +
      '#dc-root .dc-linkage{display:inline-flex;padding:1px 4px;border:1px solid rgba(245,158,11,.5);border-radius:999px;color:#fbbf24;font-size:6px}' +
      '#dc-root .dc-ledger-empty{padding:16px;text-align:center;color:#7589a2;font-size:8px}' +
      '#dc-root .dc-risk-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}' +
      '#dc-root label{font-size:8px;color:#92a4ba}#dc-root input,#dc-root select{display:block;width:100%;margin-top:2px;background:#07101d;color:var(--thi);border:1px solid #2b3a52;border-radius:4px;padding:5px;font:9px "JetBrains Mono",monospace}' +
      '#dc-root details summary{cursor:pointer;color:var(--cyan);font-size:9px;margin-bottom:6px}' +
      '#dc-root .dc-lab>summary{list-style:none;display:flex;align-items:center;gap:7px;margin:-1px 0 0!important;padding:2px 0 7px;color:var(--gold);font-size:11px;font-weight:850}' +
      '#dc-root .dc-lab>summary::-webkit-details-marker{display:none}#dc-root .dc-lab>summary:after{content:"展開研究";margin-left:auto;color:var(--cyan);font-size:8px}' +
      '#dc-root .dc-lab[open]>summary:after{content:"收合研究"}#dc-root .dc-lab-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}' +
      '#dc-root .dc-lab-box{background:#081321;border:1px solid #263750;border-radius:6px;padding:7px;min-width:0}' +
      '#dc-root .dc-lab-box .v{font-size:12px}#dc-root .dc-lab-table td,#dc-root .dc-lab-table th{font-size:7.5px}' +
      '#dc-root .dc-temp{display:grid;grid-template-columns:130px minmax(0,1fr);gap:8px;padding:8px;border:1px solid #2b3d58;border-radius:7px;background:linear-gradient(135deg,#081321,#0b1727)}' +
      '#dc-root .dc-temp-main{display:grid;grid-template-columns:34px 1fr;align-items:center;gap:7px;border-right:1px solid #24344b;padding-right:8px}' +
      '#dc-root .dc-thermo{height:72px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}' +
      '#dc-root .dc-thermo .tube{position:relative;width:12px;height:54px;border:2px solid #53657d;border-bottom:0;border-radius:8px 8px 0 0;background:#07101d;overflow:hidden}' +
      '#dc-root .dc-thermo .tube b{position:absolute;left:2px;right:2px;bottom:0;border-radius:4px 4px 0 0;min-height:3px}' +
      '#dc-root .dc-thermo .bulb{display:block;width:22px;height:22px;border:3px solid #53657d;border-radius:50%;margin-top:-3px}' +
      '#dc-root .dc-temp-score{font-size:23px;line-height:1;color:var(--thi);font-weight:900}#dc-root .dc-temp-score small{font-size:9px;color:#8fa2bb;margin-left:2px}' +
      '#dc-root .dc-temp-state{font-size:11px;font-weight:850;margin-top:3px}#dc-root .dc-temp-help{font-size:7px;line-height:1.35;color:#71839a;margin-top:4px}' +
      '#dc-root .dc-temp-lights{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}' +
      '#dc-root .dc-temp-light{display:grid;grid-template-columns:10px 1fr;align-items:center;gap:5px;padding:6px;background:#07101d;border:1px solid #203049;border-radius:6px;min-width:0}' +
      '#dc-root .dc-temp-light .lamp{width:9px;height:9px;border-radius:50%;box-shadow:0 0 8px currentColor}' +
      '#dc-root .dc-temp-light .k{font-size:7.5px;color:#8fa2bb}.dc-temp-light .v{font-size:9px;font-weight:850;color:#d8e3f0;white-space:nowrap}' +
      '#dc-root .dc-temp-light .s{grid-column:1/-1;text-align:center;font-size:6.5px;color:#667990;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#dc-root .dc-tone-cool{color:#60a5fa}#dc-root .dc-tone-steady{color:#38bdf8}#dc-root .dc-tone-watch{color:#facc15}#dc-root .dc-tone-hot{color:#fb923c}#dc-root .dc-tone-unknown{color:#64748b}' +
      '#dc-root .dc-lab-detail{margin-top:7px;border-top:1px solid #24344b;padding-top:6px}#dc-root .dc-lab-detail>summary{margin:0!important;font-weight:800}' +
      '#dc-root .dc-lab-authority{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:7px 0}' +
      '#dc-root .dc-lab-authority>div{padding:8px 10px;border:1px solid #29405c;border-radius:7px;background:linear-gradient(145deg,#081522,#0a1828)}' +
      '#dc-root .dc-lab-authority b{display:block;color:#8cecff;font-size:9px;margin-bottom:3px}.dc-lab-authority span{display:block;color:#b7c7d9;font-size:8px;line-height:1.45}' +
      '#dc-root .dc-lab-scroll{max-height:205px;margin-top:7px;border:1px solid #21334c;border-radius:7px}.dc-lab-scroll table{min-width:840px}' +
      '#dc-root .dc-lab-table td small,#dc-root .dc-lab-table th small{display:block;margin-top:2px;color:#71869f;font-size:6.5px;font-weight:650}' +
      '#dc-root .dc-edge{font-size:9px;color:#facc15}.dc-edge.pos{color:#67e8f9}.dc-edge.warn{color:#fb923c}' +
      '#dc-root .dc-research-status{display:inline-flex;padding:2px 6px;border:1px solid #36506f;border-radius:999px;color:#a9bdd3;font-size:6.5px;white-space:nowrap}' +
      '#dc-root .dc-research-status.edge_positive_research{border-color:rgba(34,211,238,.45);color:#8cecff}.dc-research-status.indeterminate{border-color:rgba(250,204,21,.55);color:#fde68a}' +
      '#dc-root .dc-research-status.no_2x_edge{border-color:rgba(251,146,60,.55);color:#fdba74}.dc-research-status.research_data_incomplete{color:#94a3b8}' +
      '#dc-root .dc-lab-subdetail{margin-top:8px;padding:8px;border:1px dashed #31465f;border-radius:7px;background:rgba(10,23,39,.55)}' +
      '#dc-root .dc-lab-subdetail>summary{margin:0!important;color:#9fcae0;font-weight:800}.dc-lab-subdetail[open]>summary{margin-bottom:7px!important}' +
      '#dc-root .dc-validation-note{display:grid;grid-template-columns:145px minmax(0,1fr);gap:9px;align-items:start;margin-top:8px;padding:9px 10px;border-left:3px solid #facc15;background:rgba(250,204,21,.06);border-radius:5px}' +
      '#dc-root .dc-validation-note b{color:#fde68a;font-size:8.5px}.dc-validation-note span{color:#b8c5d5;font-size:8px;line-height:1.5}' +
      '#dc-root .dc-options-lab>summary{min-width:0}.dc-options-lab>summary .dc-options-name{white-space:nowrap}' +
      '#dc-root .dc-options-lab>summary .dc-options-meta{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#91a5bd;font-size:7.5px;font-weight:700}' +
      '#dc-root .dc-options-lab>summary:after{content:"展開結構"}#dc-root .dc-options-lab[open]>summary:after{content:"收合結構"}' +
      '#dc-root .dc-options-status{border-radius:999px;padding:1px 6px;border:1px solid #35506f;color:#8fdff0;font-size:7px;white-space:nowrap}' +
      '#dc-root .dc-options-status.stale{border-color:rgba(251,146,60,.55);color:#fdba74}.dc-options-status.insufficient{color:#94a3b8}' +
      '#dc-root .dc-options-layer{min-width:0;margin-top:7px;padding:8px;border:1px solid #263750;border-radius:7px;overflow:hidden;background:#081321}' +
      '#dc-root .dc-options-layer.observed{border-left:3px solid #22d3ee}.dc-options-layer.derived{border-left:3px solid #60a5fa}' +
      '#dc-root .dc-options-layer.modeled{border:1px dashed rgba(251,191,36,.48);background:rgba(245,158,11,.045)}' +
      '#dc-root .dc-options-layer>header{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:6px}' +
      '#dc-root .dc-options-layer>header b{color:#dce9f6;font-size:9px}.dc-options-layer>header span{color:#778da7;font-size:7px;text-align:right}' +
      '#dc-root .dc-options-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}' +
      '#dc-root .dc-options-kpis.five{grid-template-columns:repeat(5,minmax(0,1fr))}' +
      '#dc-root .dc-options-kpi{min-width:0;padding:6px 7px;border:1px solid #263a55;border-radius:6px;background:#07111f}' +
      '#dc-root .dc-options-kpi .k{font-size:7px}.dc-options-kpi .v{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#dc-root .dc-options-chart{width:100%;min-width:0;overflow:hidden;margin-top:5px;border:1px solid #1e3048;border-radius:6px;background:#06101c}' +
      '#dc-root .dc-options-chart svg{display:block;width:100%;height:118px}.dc-options-axis{stroke:#2c405b;stroke-width:1}.dc-options-spot{stroke:#fbbf24;stroke-width:1;stroke-dasharray:3 2}' +
      '#dc-root .dc-options-call{fill:#67e8f9;opacity:.82}.dc-options-put{fill:#60a5fa;opacity:.72}.dc-options-chart text{fill:#7890aa;font:7px "JetBrains Mono",monospace}' +
      '#dc-root .dc-options-gamma{display:grid;gap:4px;margin-top:6px}.dc-options-gamma-row{display:grid;grid-template-columns:52px minmax(0,1fr) 62px;gap:6px;align-items:center;font-size:7.5px;color:#9fb1c7}' +
      '#dc-root .dc-options-gamma-bar{height:7px;border-radius:99px;background:#16253a;overflow:hidden}.dc-options-gamma-bar i{display:block;height:100%;background:linear-gradient(90deg,#38bdf8,#67e8f9);border-radius:inherit}' +
      '#dc-root .dc-options-density-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:6px;margin-top:6px}' +
      '#dc-root .dc-options-density-card{min-width:0;padding:7px;border:1px solid #263750;border-radius:6px;background:#07111f}' +
      '#dc-root .dc-options-density-card>header{display:flex;justify-content:space-between;gap:6px;margin-bottom:5px;color:#92a8c0;font-size:7px}' +
      '#dc-root .dc-options-density-card>header b{color:#dce9f6;font-size:8px}.dc-options-density-card.vega .dc-options-gamma-bar i{background:linear-gradient(90deg,#818cf8,#c4b5fd)}' +
      '#dc-root .dc-options-change{margin-top:6px;padding:6px 7px;border:1px solid #243750;border-radius:6px;background:#07111f}' +
      '#dc-root .dc-options-change-head{display:flex;justify-content:space-between;gap:6px;color:#8ea5bd;font-size:7px}' +
      '#dc-root .dc-options-change-head b{color:#cce6ee;font-size:8px}.dc-options-change-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(82px,1fr));gap:4px;margin-top:4px}' +
      '#dc-root .dc-options-change-cell{min-width:0;padding:4px 5px;border-left:2px solid #334a66;background:rgba(255,255,255,.015)}' +
      '#dc-root .dc-options-change-cell .k{font-size:6.5px}.dc-options-change-cell .v{font-size:9px;margin:1px 0;color:#a5f3fc}' +
      '#dc-root .dc-options-scroll{max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain;scrollbar-gutter:stable}' +
      '#dc-root .dc-options-table{min-width:720px}.dc-options-table td:first-child,.dc-options-table th:first-child{white-space:nowrap}' +
      '#dc-root .dc-options-warn{margin-top:6px;padding:6px 8px;border-left:3px solid #fbbf24;background:rgba(251,191,36,.07);color:#d8c99a;font-size:7.5px;line-height:1.45}' +
      '#dc-root .dc-options-actions{display:flex;align-items:center;gap:7px;margin-top:7px}.dc-options-actions .dc-note{min-width:0}' +
      '#dc-root .dc-oi-lab>summary:after{content:"收合觀察"}.dc-oi-lab:not([open])>summary:after{content:"展開觀察"}' +
      '#dc-root .dc-oi-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}' +
      '#dc-root .dc-oi-market{min-width:0;padding:10px;border:1px solid #29405c;border-radius:8px;background:linear-gradient(145deg,#081522,#0a1828)}' +
      '#dc-root .dc-oi-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px}' +
      '#dc-root .dc-oi-head b{font-size:12px;color:#dce9f6}.dc-oi-head .s{text-align:right}' +
      '#dc-root .dc-oi-state{display:flex;align-items:center;gap:7px;margin:4px 0 8px;padding:7px 8px;border-left:3px solid #22d3ee;background:rgba(34,211,238,.055);border-radius:5px}' +
      '#dc-root .dc-oi-state b{font-size:12px;color:#d8f7ff}.dc-oi-state span{margin-left:auto;font-size:10px;color:#8cecff;white-space:nowrap}' +
      '#dc-root .dc-oi-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}' +
      '#dc-root .dc-oi-kpi{min-width:0;padding:8px;border:1px solid #263a55;border-radius:7px;background:#07111f}' +
      '#dc-root .dc-oi-kpi .v{font-size:16px;margin:3px 0}.dc-oi-kpi .s{font-size:9px;overflow-wrap:anywhere}' +
      '#dc-root .dc-oi-kpi .tw-up{color:var(--red)}#dc-root .dc-oi-kpi .tw-down{color:var(--green)}' +
      '#dc-root .dc-oi-kpi .us-up{color:var(--green)}#dc-root .dc-oi-kpi .us-down{color:var(--red)}' +
      '#dc-root .dc-oi-table .tw-up{color:var(--red)}#dc-root .dc-oi-table .tw-down{color:var(--green)}' +
      '#dc-root .dc-oi-table .us-up{color:var(--green)}#dc-root .dc-oi-table .us-down{color:var(--red)}' +
      '#dc-root .dc-oi-quality{display:inline-flex;padding:2px 7px;border:1px solid #38516d;border-radius:999px;color:#8fdff0;font-size:9px;white-space:nowrap}' +
      '#dc-root .dc-oi-quality.mixed{border-color:rgba(250,204,21,.55);color:#fde68a}.dc-oi-quality.insufficient,.dc-oi-quality.stale{border-color:rgba(251,146,60,.55);color:#fdba74}' +
      '#dc-root .dc-oi-detail{margin-top:8px}.dc-oi-detail>summary{margin:0!important;color:#9fcae0!important;font-weight:800}' +
      '#dc-root .dc-oi-scroll{max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain;margin-top:7px}' +
      '#dc-root .dc-oi-table{min-width:720px}.dc-oi-table td:first-child{white-space:nowrap}' +
      '#dc-root .dc-oi-authority{margin-top:8px;padding:8px 10px;border-left:3px solid #facc15;background:rgba(250,204,21,.06);color:#d8c99a;font-size:10px;line-height:1.5;border-radius:5px}' +
      '#dc-root .dc-oi-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}' +
      '#dc-root .dc-ai{white-space:pre-wrap;font-family:"Noto Sans TC",sans-serif;font-size:10px;line-height:1.65;color:#d4deea}' +
      '#dc-root .dc-ai.is-error{color:#fecaca}' +
      '#dc-root .dc-note{font-size:8px;color:#71839a;line-height:1.5}' +
      '#dc-root .dc-empty{text-align:center;padding:26px 14px}' +
      '#dc-root .dc-empty .v{font-size:14px;margin-bottom:8px}' +
      '#dc-root .dc-empty .dc-actions{justify-content:center;margin-top:12px}' +
      '#dc-root .dc-status{font-size:9px;color:var(--cyan);margin-top:8px;min-height:14px}' +
      /* Executive readability floor: use the available canvas instead of 6–9px telemetry text. */
      '#dc-root{font-size:12px;line-height:1.45;max-width:1880px;padding:2px 4px 18px}' +
      '#dc-root .dc-head{gap:16px;margin-bottom:12px}.dc-title{font-size:24px!important}.dc-sub{font-size:11px!important}' +
      '#dc-root .dc-actions{gap:8px}.dc-btn{font-size:11px!important;padding:7px 11px!important;border-radius:7px!important}' +
      '#dc-root .dc-command-fold{margin-bottom:11px;border-radius:10px}.dc-command-fold>summary{font-size:11px!important;padding:10px 13px!important}' +
      '#dc-root .dc-command{gap:10px;padding:10px}.dc-command .box{padding:12px 14px!important;border-radius:9px!important}' +
      '#dc-root .k{font-size:10.5px}.dc-v,#dc-root .v{font-size:17px}.dc-s,#dc-root .s{font-size:10.5px;line-height:1.55}' +
      '#dc-root .dc-grid{gap:12px}.dc-card{padding:12px 13px;margin-bottom:12px;border-radius:10px}.dc-card h3{font-size:14px;margin-bottom:10px;padding-left:9px}' +
      '#dc-root .dc-scenario{gap:8px}.dc-feature{padding:10px;border-radius:8px}.dc-signal{font-size:9px;padding:2px 7px}' +
      '#dc-root .dc-feature>.s{height:auto;min-height:34px}.dc-feature .meter{height:7px;margin-top:8px}.dc-scale-legend{font-size:8.5px}' +
      '#dc-root .dc-level{padding:10px 5px;border-radius:7px}.dc-level b{font-size:16px}.dc-div{padding:9px 10px;margin:8px 0;border-radius:8px}' +
      '#dc-root .dc-div b{font-size:12px}.dc-div p{font-size:10px;line-height:1.55}.dc-div-insight{font-size:10px!important;padding:9px 11px!important}' +
      '#dc-root .dc-metrics{gap:6px;margin:7px 0}.dc-metric{min-width:94px;padding:6px 8px}.dc-metric span{font-size:8.5px}.dc-metric b{font-size:11px!important}' +
      '#dc-root table{font-size:10px}#dc-root th,#dc-root td{padding:7px 8px}.dc-ledger-table td{padding-top:8px;padding-bottom:8px}' +
      '#dc-root .tag{font-size:9px;padding:2px 7px}.dc-ledger-btn{font-size:9px!important;padding:5px 9px!important}.dc-ledger-feedback{font-size:9px}' +
      '#dc-root .dc-evidence-key b{font-size:10.5px}.dc-evidence-metric{font-size:9px}.dc-category{font-size:8px}.dc-value-main{font-size:11px}.dc-value-note{font-size:9px}' +
      '#dc-root .dc-kv{font-size:9px;padding:3px 6px}.dc-source-link{font-size:9.5px}.dc-source-meta,.dc-fresh-label{font-size:8.5px}.dc-linkage{font-size:8px}' +
      '#dc-root label{font-size:10px}#dc-root input,#dc-root select{font-size:11px!important;padding:7px!important}.dc-note{font-size:10px!important}' +
      '#dc-root .dc-lab>summary{font-size:14px}.dc-lab>summary:after{font-size:10px}.dc-lab-box{padding:10px}.dc-lab-box .v{font-size:15px}.dc-lab-table td,#dc-root .dc-lab-table th{font-size:9.5px}' +
      '#dc-root .dc-temp{grid-template-columns:160px minmax(0,1fr);padding:11px;gap:12px}.dc-temp-score{font-size:28px}.dc-temp-state{font-size:13px}.dc-temp-help{font-size:9px}' +
      '#dc-root .dc-temp-lights{gap:8px}.dc-temp-light{padding:9px}.dc-temp-light .k{font-size:9px}.dc-temp-light .v{font-size:11px}.dc-temp-light .s{font-size:8.5px}' +
      '#dc-root .dc-options-layer{padding:11px}.dc-options-layer>header b{font-size:11px}.dc-options-layer>header span{font-size:9px}.dc-options-status{font-size:9px}' +
      '#dc-root .dc-options-kpi{padding:8px 9px}.dc-options-kpi .k{font-size:9px}.dc-options-kpi .v{font-size:14px}.dc-options-warn{font-size:9.5px}' +
      '#dc-root .dc-confidence{width:62px;height:62px}.dc-confidence strong{font-size:15px}.dc-confidence small{font-size:9px}.dc-stop b{font-size:10.5px}.dc-stop span{font-size:8.5px}' +
      '#dc-root .dc-action-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:2px 0 10px}' +
      '#dc-root .dc-action-cell{display:grid;grid-template-columns:30px minmax(0,1fr);gap:8px;align-items:center;min-height:64px;padding:9px 10px;border:1px solid #29405c;border-radius:8px;background:#081422}' +
      '#dc-root .dc-action-cell>i{display:grid;place-items:center;width:29px;height:29px;border-radius:50%;font-style:normal;font-size:15px;font-weight:900;background:rgba(56,189,248,.13);color:#67e8f9;box-shadow:0 0 13px rgba(34,211,238,.12)}' +
      '#dc-root .dc-action-cell b{display:block;font-size:12px;color:#dce9f6;margin-bottom:3px}.dc-action-cell span{display:block;font-size:10px;color:#a7b8cc;line-height:1.4;overflow-wrap:anywhere}' +
      '#dc-root .dc-action-cell.limit>i{color:#facc15;background:rgba(250,204,21,.12);box-shadow:0 0 13px rgba(250,204,21,.12)}' +
      '#dc-root .dc-action-cell.stop>i{color:#fb923c;background:rgba(251,146,60,.12);box-shadow:0 0 13px rgba(251,146,60,.12)}' +
      '#dc-root .dc-warning-card{border-color:#304664;background:linear-gradient(145deg,rgba(11,25,43,.96),rgba(7,15,27,.98));overflow:hidden}' +
      '#dc-root .dc-warning-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.dc-warning-head .tag{margin-left:auto}' +
      '#dc-root .dc-warning-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}' +
      '#dc-root .dc-warning-signal{display:grid;grid-template-columns:88px minmax(0,1fr);gap:12px;align-items:center;padding:12px;border:1px solid #2a405d;border-radius:10px;background:#081421;min-width:0}' +
      '#dc-root .dc-warning-signal.upside{--tone:#38bdf8;box-shadow:inset 3px 0 rgba(56,189,248,.72)}' +
      '#dc-root .dc-warning-signal.downside{--tone:#fb923c;box-shadow:inset 3px 0 rgba(251,146,60,.78)}' +
      '#dc-root .dc-warning-ring{position:relative;width:82px;height:82px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--tone) var(--p),#1b2a3e 0);box-shadow:0 0 20px color-mix(in srgb,var(--tone) 22%,transparent)}' +
      '#dc-root .dc-warning-ring:before{content:"";position:absolute;inset:8px;border-radius:50%;background:#07111e;border:1px solid #2b405b}' +
      '#dc-root .dc-warning-ring strong,#dc-root .dc-warning-ring small{position:relative;z-index:1}.dc-warning-ring strong{font-size:22px;color:#eef8ff}.dc-warning-ring small{font-size:9px;color:#8ea4bc;margin-left:2px}' +
      '#dc-root .dc-warning-copy{min-width:0}.dc-warning-title{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:5px}.dc-warning-title b{font-size:14px;color:#e6f0fb}' +
      '#dc-root .dc-warning-state{padding:2px 7px;border-radius:999px;border:1px solid var(--tone);color:var(--tone);font-size:9px;font-weight:850}' +
      '#dc-root .dc-warning-reasons{margin:0;padding-left:17px;color:#bdcadd;font:700 10px/1.55 "Noto Sans TC",sans-serif}.dc-warning-reasons li::marker{color:var(--tone)}' +
      '#dc-root .dc-warning-rule{margin-top:6px;padding-top:6px;border-top:1px dashed #293b53;color:#8195ad;font-size:9px;line-height:1.45}' +
      '#dc-root .dc-warning-components{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.dc-warning-component{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;border:1px solid #2a415e;border-radius:999px;background:#091726;color:#aec0d3;font-size:9px}' +
      '#dc-root .dc-warning-component b{color:#e4eef8}.dc-warning-component.mixed{border-color:#665b32;color:#e5cf78}' +
      '#dc-root .dc-warning-validation{margin-top:10px;padding:10px;border:1px solid #29415d;border-radius:10px;background:rgba(5,15,27,.72)}' +
      '#dc-root .dc-warning-validation-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:8px}.dc-warning-validation-head b{font-size:11px;color:#d9e8f7}.dc-warning-validation-head span{font-size:9px;color:#7f95ad}' +
      '#dc-root .dc-warning-validation-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.dc-warning-validation-cell{padding:8px 9px;border:1px solid #263b55;border-radius:8px;background:#081522;min-width:0}' +
      '#dc-root .dc-warning-validation-cell .k{font-size:9px;color:#8297ae}.dc-warning-validation-cell .v{margin:3px 0 2px;font-size:15px;font-weight:900;color:#dcebf8}.dc-warning-validation-cell .s{font-size:8.5px;line-height:1.35;color:#71879f}' +
      '#dc-root .dc-warning-validation-note{margin-top:7px;color:#758ba4;font-size:8.5px;line-height:1.45}' +
      '#dc-root .dc-warning-foot{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:8px;color:#758ba4;font-size:9px}' +
      '@media(max-width:1000px){#dc-root .dc-command,#dc-root .dc-grid{grid-template-columns:1fr}#dc-root .dc-scenario{grid-template-columns:repeat(2,1fr)}#dc-root .dc-risk-grid,#dc-root .dc-lab-grid{grid-template-columns:repeat(2,1fr)}#dc-root .dc-temp{grid-template-columns:1fr}#dc-root .dc-temp-main{border-right:0;border-bottom:1px solid #24344b;padding:0 0 7px}#dc-root .dc-temp-lights{grid-template-columns:repeat(2,1fr)}#dc-root .dc-structure,#dc-root .dc-oi-grid{grid-template-columns:1fr}}' +
      '@media(max-width:650px){#dc-root .dc-ledger-toolbar,#dc-root .dc-action-summary,#dc-root .dc-lab-authority,#dc-root .dc-validation-note,#dc-root .dc-warning-grid{grid-template-columns:1fr}.dc-ledger-actions{justify-content:flex-start}#dc-root .dc-ledger-table table{min-width:720px}#dc-root .dc-options-kpis,#dc-root .dc-options-kpis.five{grid-template-columns:repeat(2,minmax(0,1fr))}#dc-root .dc-options-scroll table{min-width:720px}#dc-root .dc-oi-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}#dc-root .dc-oi-kpi:last-child{grid-column:1/-1}#dc-root .dc-warning-signal{grid-template-columns:72px minmax(0,1fr);padding:10px;gap:9px}#dc-root .dc-warning-ring{width:68px;height:68px}.dc-warning-ring strong{font-size:18px!important}#dc-root .dc-warning-validation-grid{grid-template-columns:repeat(3,minmax(0,1fr))}#dc-root .dc-warning-validation-cell{padding:7px 6px}.dc-warning-validation-cell .v{font-size:13px}}';
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-decision');
    if (!panel) return null;
    var mount = $('mount-decision');
    if (!mount) { mount = document.createElement('div'); mount.id = 'mount-decision'; panel.appendChild(mount); }
    if (!$('dc-root')) {
      mount.innerHTML = '<div id="dc-root"><div class="dc-head"><div><div class="dc-title">策略決策中心</div>' +
        '<div class="dc-sub" id="dc-sub">DecisionContext v1 · deterministic first · evidence before confidence</div></div>' +
        '<div class="dc-actions"><button class="dc-btn" data-shell-back>← 儀表板</button>' +
        '<button class="dc-btn" id="dc-ai-btn">AI 解釋</button><button class="dc-btn primary" id="dc-refresh">↻ 更新市場資料</button></div></div>' +
        '<div id="dc-body"><div class="dc-card">決策資料載入中…</div></div></div>';
      $('dc-refresh').onclick = refreshMarketData;
      $('dc-ai-btn').onclick = runAi;
    }
    syncAiButtonState();
    bindPortfolioSwitch();
    return $('dc-body');
  }

  function syncAiButtonState() {
    var button = $('dc-ai-btn');
    if (!button) return;
    button.disabled = !!aiBusy || aiAccessRole === 'reader';
    button.setAttribute('aria-busy', aiBusy ? 'true' : 'false');
    if (aiBusy) {
      button.textContent = 'AI 解釋中…';
      button.title = '分析在 EVO-T1 執行；請勿重複送出。';
    } else if (aiAccessRole === 'reader') {
      button.textContent = 'AI 解釋（Owner）';
      button.title = 'Reader 可閱讀既有決策資料；啟動 EVO-T1 AI 運算僅限 Owner。';
    } else {
      button.textContent = aiDisplayState.error ? '重試 AI 解釋' : 'AI 解釋';
      button.title = aiAccessRole === 'unknown' ? '首次使用會先確認 Private Web 權限。' : '由 EVO-T1 本機模型唯讀解釋 DecisionContext。';
    }
  }

  function resolveAiAccess() {
    if (!window.ST_PRIVATE_WEB_PROFILE) {
      aiAccessRole = 'owner';
      syncAiButtonState();
      return Promise.resolve(aiAccessRole);
    }
    if (aiAccessRole === 'owner' || aiAccessRole === 'reader') return Promise.resolve(aiAccessRole);
    if (aiAccessPromise) return aiAccessPromise;
    aiAccessPromise = fetch(SRV + '/gateway/whoami', {
      method: 'GET', cache: 'no-store', credentials: 'same-origin'
    }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    }).then(function (payload) {
      aiAccessRole = payload && payload.role === 'owner' ? 'owner' : 'reader';
      return aiAccessRole;
    }).catch(function () {
      aiAccessRole = 'unknown';
      return aiAccessRole;
    }).then(function (role) {
      aiAccessPromise = null;
      syncAiButtonState();
      return role;
    });
    return aiAccessPromise;
  }

  function setAiDisplay(text, error) {
    aiDisplayState = { visible: true, text: String(text || ''), error: !!error };
    restoreAiDisplay();
  }

  function restoreAiDisplay() {
    var card = $('dc-ai-card'), box = $('dc-ai-body');
    if (!card || !box || !aiDisplayState.visible) return;
    card.style.display = '';
    box.textContent = aiDisplayState.text;
    box.classList.toggle('is-error', !!aiDisplayState.error);
  }

  function safeAiErrorDetail(text) {
    var raw = String(text || '').trim();
    if (!raw) return '';
    try {
      var payload = JSON.parse(raw);
      raw = payload && (payload.error || payload.message) ? String(payload.error || payload.message) : raw;
    } catch (e) {}
    return raw.replace(/\s+/g, ' ').slice(0, 220);
  }

  function aiErrorMessage(error, fallbackRequestId) {
    var requestId = error && error.requestId
      ? String(error.requestId)
      : String(fallbackRequestId || '');
    var suffix = requestId ? '\n\n請求編號：' + requestId : '';
    if (error && error.name === 'AbortError') {
      return 'AI 解釋等待超過 12 分鐘，已停止本次請求；DecisionContext 不受影響，可稍後重試。' + suffix;
    }
    var status = Number(error && error.status);
    if (status === 403) return '此登入帳號為 Reader；AI 解釋會使用 EVO-T1 運算資源，目前僅 Owner 可執行。' + suffix;
    if (status === 401) return '登入狀態已失效，請重新登入 Private Web 後再執行 AI 解釋。' + suffix;
    if (status === 413) return '本次 DecisionContext 超過 AI 服務可接受大小；請先更新資料後重試。' + suffix;
    if (status === 429) return 'EVO-T1 AI 請求過於頻繁，請稍後再試。' + suffix;
    if (status === 502) return 'Private Web 無法連到 EVO-T1 後端；請確認遠端服務已啟動後再試。' + suffix;
    if (status === 503) return 'EVO-T1 本機模型尚未就緒或正在忙碌，請稍後重試。' + suffix;
    var detail = safeAiErrorDetail(error && error.detail);
    return (detail || '無法連線到 EVO-T1 AI 服務；deterministic DecisionContext 不受影響。') + suffix;
  }

  function aiRuntimeFailureDetail(answer) {
    var text = String(answer || '').trim();
    if (text.indexOf('⚠') !== 0) return '';
    var warning = text.match(/^⚠\s*([^\n]+)/);
    if (!warning) return '';
    var detail = String(warning[1] || '').trim();
    if (/^非投資建議[。.!！]?$/.test(detail)) return '';
    return detail;
  }

  function trace(event, id, details) {
    if (window.DecisionData && DecisionData.trace) DecisionData.trace(event, id, details);
  }

  function nextCorrelationId() {
    if (window.DecisionData && DecisionData.correlationId) return DecisionData.correlationId('market-refresh');
    return 'market-refresh-' + Date.now().toString(36);
  }

  function setRefreshState(active) {
    var btn = $('dc-refresh');
    if (!btn) return;
    btn.disabled = !!active;
    btn.textContent = active ? '↻ 市場資料更新中…' : '↻ 更新市場資料';
  }

  function emptyHtml(message, detail) {
    return '<div class="dc-card dc-empty"><div class="v">' + esc(message) + '</div>' +
      '<div class="s">' + esc(detail || '更新會重新取得總覽資料，並建立可稽核的 DecisionContext。') + '</div>' +
      '<div class="dc-actions"><button type="button" class="dc-btn primary" id="dc-empty-refresh">↻ 立即更新市場資料</button>' +
      '<button type="button" class="dc-btn" id="dc-empty-pulse">前往總覽</button></div>' +
      '<div class="dc-status" id="dc-empty-status"></div></div>';
  }

  function bindEmptyActions() {
    var refreshBtn = $('dc-empty-refresh');
    var pulseBtn = $('dc-empty-pulse');
    if (refreshBtn) refreshBtn.onclick = refreshMarketData;
    if (pulseBtn) pulseBtn.onclick = function () {
      if (window.ShellV5 && ShellV5.go) ShellV5.go('pulse');
      else location.hash = '#pulse';
    };
  }

  function showEmpty(message, detail) {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = emptyHtml(message, detail);
    bindEmptyActions();
  }

  function refreshMarketData() {
    var body = ensureMount();
    if (!body) return Promise.resolve(null);
    var id = nextCorrelationId();
    var started = Date.now();
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeoutId = controller ? setTimeout(function () { controller.abort(); }, 20000) : null;
    trace('market_refresh_command_received', id, { route: 'decision' });
    setRefreshState(true);
    body.innerHTML = '<div class="dc-card dc-empty"><div class="v">正在更新市場資料…</div>' +
      '<div class="s">依序取得總覽 Pulse、建立 DecisionContext、再載入完整證據。</div>' +
      '<div class="dc-status">請稍候，最長等待 20 秒。</div></div>';
    trace('market_refresh_command_acknowledged', id, { uiState: 'loading' });
    trace('pulse_request_start', id, {
      method: 'GET', path: '/pulse?refresh=1', origin: location.origin || null
    });
    var pulseRequest = window.AppKernel && window.AppKernel.api
      ? window.AppKernel.api.request('/pulse?refresh=1', {
          cache: 'no-store', signal: controller ? controller.signal : undefined, timeoutMs: 20000,
          headers: { 'X-ST-Trace-ID': id }
        })
      : fetch(SRV + '/pulse?refresh=1', {
          cache: 'no-store', signal: controller ? controller.signal : undefined
        });
    return pulseRequest.then(function (response) {
      return response.text().then(function (raw) {
        trace('pulse_response', id, {
          status: response.status,
          ok: response.ok,
          responseChars: raw.length,
          elapsedMs: Date.now() - started
        });
        if (!response.ok) throw new Error('Pulse HTTP ' + response.status);
        try { return JSON.parse(raw); }
        catch (e) { throw new Error('Pulse JSON 解析失敗'); }
      });
    }).then(function (pulse) {
      if (!pulse || !pulse.ok) throw new Error((pulse && pulse.error) || 'Pulse 未回傳有效資料');
      if (window.MarketData && MarketData.fromPulse) MarketData.fromPulse(pulse);
      if (window.DecisionData && DecisionData.fromPulse) DecisionData.fromPulse(pulse, id);
      trace('pulse_applied', id, {
        asOf: pulse.updatedAt || null,
        hasDecisionSummary: !!(pulse.decisionSummary && pulse.decisionSummary.regime)
      });
      lastHoldings = portfolioMode === 'observation_pool' ? holdingsFromWatch() : holdingsFromPositions();
      if (!window.DecisionData || !DecisionData.refresh) throw new Error('DecisionData 尚未載入');
      return DecisionData.refresh({
        force: true,
        holdings: lastHoldings,
        portfolioKind: portfolioMode,
        correlationId: id
      });
    }).then(function (state) {
      var ctx = state && state.context;
      if (!ctx) throw new Error('更新完成，但後端尚未建立 DecisionContext');
      render(ctx);
      trace('market_refresh_terminal_success', id, {
        regime: (ctx.regime || {}).id || null,
        asOf: ctx.asOf || null,
        elapsedMs: Date.now() - started
      });
      return ctx;
    }).catch(function (err) {
      var message = err && err.name === 'AbortError' ? '市場資料更新逾時' : '市場資料更新失敗';
      var detail = String(err && err.message || err || '未知錯誤');
      showEmpty(message, detail + '；可重試或前往總覽檢查服務狀態。');
      trace('market_refresh_terminal_failure', id, {
        error: detail,
        elapsedMs: Date.now() - started
      });
      return null;
    }).finally(function () {
      if (timeoutId) clearTimeout(timeoutId);
      setRefreshState(false);
    });
  }

  function holdingsFromPositions() {
    try {
      var state = (typeof S !== 'undefined' && S) ? S : (window.Store || {});
      var rows = Object.keys(state.positions || {}).map(function (code) {
        var p = state.positions[code] || {};
        var value = Number(p.lastPrice || p.entry || 0) * Number(p.shares || 0);
        return { sym: code, weight: value };
      }).filter(function (x) { return x.weight > 0; });
      return rows;
    } catch (e) { return []; }
  }

  function holdingsFromWatch() {
    try {
      var state = (typeof S !== 'undefined' && S) ? S : {};
      var direct = Array.isArray(state.wl) ? state.wl :
        (state.watches && typeof state.watches === 'object' ? Object.keys(state.watches) : null);
      var raw = direct || JSON.parse(localStorage.getItem('st_wl') || localStorage.getItem('wl_v2') ||
        localStorage.getItem('watchlist') || '[]');
      return (raw || []).map(function (x) {
        var sym = typeof x === 'string' ? x : (x.sym || x.t || x.code);
        return sym ? { sym: sym, weight: 1 } : null;
      }).filter(Boolean).slice(0, 40);
    } catch (e) { return []; }
  }

  function decisionWatchlist() {
    try {
      if (typeof S !== 'undefined' && S && Array.isArray(S.wl)) return S.wl.slice(0, 40);
    } catch (e) {}
    try {
      var raw = JSON.parse(localStorage.getItem('st_wl') || localStorage.getItem('wl_v2') ||
        localStorage.getItem('watchlist') || '[]');
      return Array.isArray(raw) ? raw.slice(0, 40) : [];
    } catch (e2) { return []; }
  }

  function signed(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return (n > 0 ? '+' : '') + n.toFixed(digits == null ? 2 : digits);
  }

  function signedUnit(value, digits, unit) {
    var n = Number(value);
    return isFinite(n) ? signed(n, digits) + (unit || '') : '—';
  }

  function scenarioDetail(name, raw) {
    raw = raw || {};
    if (name === '趨勢') return '指數 ' + signedUnit(raw.changePct, 2, '%') + ' · 動能 ' + num(raw.momScore, 0) + '/100';
    if (name === '廣度') return '上漲占比 ' + num(Number(raw.advRatio) * 100, 1) + '% · 3/5日斜率 ' +
      signed(raw.velocity3, 3) + ' / ' + signed(raw.velocity5, 3) + ' · 弱於中線 ' + num(raw.belowNeutralStreak, 0) + ' 日';
    if (name === '資金') return '法人 ' + signedUnit(raw.institutionalNetYi, 1, '億') + ' · 量能 ' + num(raw.volumeScore, 0) + ' · OI ' + signedUnit(raw.txOiChangePct, 2, '%');
    if (name === '產業') return '參與度 ' + num(raw.participationPct, 1) + '% · ' + (raw.mode === 'participation_proxy' ? '市場參與代理' : '同範圍產業資料');
    if (name === '國際科技') return '美國科技 ' + signedUnit(raw.usTechChangePct, 2, '%');
    if (name === '風險負擔') return '體質 ' + num(raw.healthScore, 0) + '/100 · 風險 ' + num(raw.riskScore, 0) + '/100';
    if (typeof raw === 'number') return num(raw, 2);
    if (typeof raw === 'string') return raw;
    return '資料已標準化';
  }

  function featureSignal(name, value) {
    var n = Number(value);
    if (!isFinite(n)) return { label: '資料不足', cls: 'neutral' };
    if (name === '風險負擔') {
      if (n < 0.25) return { label: '負擔低', cls: 'positive' };
      if (n < 0.55) return { label: '負擔中等', cls: 'watch' };
      return { label: '負擔高', cls: 'alert' };
    }
    if (n >= 0.60) return { label: '明顯偏強', cls: 'strong' };
    if (n >= 0.20) return { label: '偏強', cls: 'positive' };
    if (n > -0.20) return { label: '中性', cls: 'neutral' };
    if (n > -0.60) return { label: '偏弱', cls: 'watch' };
    return { label: '明顯偏弱', cls: 'alert' };
  }

  function featureHtml(name, f) {
    f = f || {};
    var v = f.value;
    var risk = name === '風險負擔';
    var directional = v == null ? null : (risk ? -Math.abs(Number(v)) : Number(v));
    var w = directional == null ? 0 : Math.max(0, Math.min(100, (directional + 1) * 50));
    var signal = featureSignal(name, v);
    return '<div class="dc-feature' + (risk ? ' risk' : '') + '"><div class="dc-feature-head"><div class="k">' + esc(name) +
      '</div><span class="dc-signal ' + signal.cls + '">' + esc(signal.label) + '</span></div><div class="v">' +
      (directional == null || !isFinite(directional) ? '資料不足' : signed(directional, 2)) + '</div>' +
      '<div class="s" title="' + esc(scenarioDetail(name, f.raw)) + '">' + esc(scenarioDetail(name, f.raw)) + '</div>' +
      '<div class="meter"><i style="width:' + w + '%"></i></div><div class="dc-scale-legend"><span>-1 負向</span><span>0</span><span>+1 正向</span></div></div>';
  }

  function levelsHtml(ctx) {
    var kl = ctx.keyLevels || {}, lv = kl.levels || {}, vol = kl.volatility || {};
    var order = [['R2', lv.r2], ['R1', lv.r1], ['PIVOT', lv.pivot], ['S1', lv.s1], ['S2', lv.s2]];
    return '<div class="dc-levels">' + order.map(function (x) {
      return '<div class="dc-level"><span class="k">' + x[0] + '</span><b>' + num(x[1], 0) + '</b></div>';
    }).join('') + '</div><div class="dc-note" style="margin-top:6px">' +
      esc(kl.method || '尚無方法') + ' · ' + esc(kl.timeframe || '') + ' · reference ' + esc(kl.referenceDate || '—') +
      ' · ATR14 ' + num((kl.atr || {}).value, 2) + ' (' + num((kl.atr || {}).pct, 2) + '%)' +
      ' · realized vol20/60 ' + num(vol.realized20AnnualPct, 1) + '% / ' + num(vol.realized60AnnualPct, 1) + '% 年化' +
      ' · 下行狀態/中長期預估 ' + num(vol.stateDownside20AnnualPct, 1) + '% / ' + num(vol.horizonForecastAnnualPct, 1) + '%' +
      '（比 ' + num(vol.stateToForecastRatio, 2) + '）' +
      ' · 1日常態95% ±' + num(vol.normal95OneDayPct, 2) + '%' +
      ' · gap P90 ' + num((vol.gap60 || {}).absP90Pct, 2) + '%（歷史代理，非 IV）</div>';
  }

  function confidenceIcon(value) {
    var confidence = Math.max(0, Math.min(1, Number(value) || 0));
    var percentage = Math.round(confidence * 100);
    var label = '信心 ' + percentage + '%';
    return '<span class="dc-confidence" role="img" aria-label="' + esc(label) + '" title="' + esc(label) +
      '" style="--confidence:' + percentage + '%"><strong>' + percentage + '<small>%</small></strong></span>';
  }

  function compactObserved(value) {
    if (typeof value === 'number') return isFinite(value) ? Number(value.toFixed(2)) : null;
    if (Array.isArray(value)) return value.map(compactObserved);
    if (value && typeof value === 'object') {
      return Object.keys(value).reduce(function (out, key) {
        out[key] = compactObserved(value[key]);
        return out;
      }, {});
    }
    return value;
  }

  function metricHtml(name, value) {
    return '<span class="dc-metric"><span>' + esc(name) + '</span><b>' + esc(value == null ? '—' : value) + '</b></span>';
  }

  function indexBreadthVisual(d) {
    var visual = d.visual || {}, series = (visual.series || []).filter(function (x) {
      return x && x.indexClose != null && x.advRatio != null;
    });
    var width = 360, height = 104, padX = 15;
    var closes = series.map(function (x) { return Number(x.indexClose); });
    var lo = closes.length ? Math.min.apply(null, closes) : 0;
    var hi = closes.length ? Math.max.apply(null, closes) : 1;
    var span = Math.max(1, hi - lo);
    var step = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0;
    var points = series.map(function (x, i) {
      var px = padX + i * step;
      var py = 8 + (hi - Number(x.indexClose)) / span * 42;
      return px.toFixed(1) + ',' + py.toFixed(1);
    }).join(' ');
    var marks = series.map(function (x, i) {
      var px = padX + i * step;
      var barH = Math.max(3, Math.min(46, Number(x.advRatio) * 46));
      return (x.divergent ? '<rect class="warn-zone" x="' + Math.max(0, px - 7).toFixed(1) + '" y="2" width="14" height="98" rx="3"></rect>' : '') +
        '<rect class="adv' + (Number(x.advRatio) < .5 ? ' weak' : '') + '" x="' + (px - 3).toFixed(1) + '" y="' +
        (98 - barH).toFixed(1) + '" width="6" height="' + barH.toFixed(1) + '" rx="2"></rect>';
    }).join('');
    var firstDate = series.length ? String(series[0].asOf || '').slice(5, 10) : '';
    var lastDate = series.length ? String(series[series.length - 1].asOf || '').slice(5, 10) : '';
    var svg = '<div class="dc-overlay"><svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" role="img" aria-label="加權指數與市場廣度雙軸趨勢">' +
      '<line x1="0" y1="75" x2="360" y2="75" stroke="#263a53" stroke-width="1"></line>' + marks +
      (points ? '<polyline class="idx" points="' + points + '"></polyline>' : '') +
      '<text x="7" y="10">^TWII</text><text x="7" y="96">advRatio</text><text x="315" y="10">' + num(hi, 0) + '</text>' +
      '<text x="7" y="102">' + esc(firstDate) + '</text><text x="327" y="102">' + esc(lastDate) + '</text></svg></div>';
    var bar = visual.breadthBar || {};
    var up = Math.max(0, Number(bar.upPct) || 0), flat = Math.max(0, Number(bar.flatPct) || 0), down = Math.max(0, Number(bar.downPct) || 0);
    var breadthBar = '<div><div class="k">當日漲跌結構</div><div class="dc-breadth-bar" title="上漲 ' + num(up, 1) + '%｜平盤 ' + num(flat, 1) + '%｜下跌 ' + num(down, 1) + '%">' +
      '<i class="up" style="width:' + up + '%">' + num(up, 0) + '%</i><i class="flat" style="width:' + flat + '%"></i>' +
      '<i class="down" style="width:' + down + '%">' + num(down, 0) + '%</i></div></div>';
    var contribution = visual.topWeightContribution || {};
    var note = contribution.available ? esc(contribution.label || '') : esc(contribution.reason || '權值貢獻資料尚未形成');
    return '<div class="dc-structure">' + svg + '<div class="dc-structure-side">' + breadthBar +
      '<div class="dc-note">黃線＝加權指數；柱＝上漲占比；黃影＝指數創高但廣度低於 50%。</div>' +
      '<div class="dc-note">' + note + '</div></div></div>';
  }

  function basisVisual(d) {
    var basis = ((d.visual || {}).basis) || {};
    var z = Number(basis.basisZ20), hasZ = isFinite(z);
    var marker = hasZ ? Math.max(2, Math.min(98, (z + 3) / 6 * 100)) : 50;
    var mode = {
      fair_value_adjusted: '合理價差調整後',
      same_session_nominal_basis: '同盤名目基差',
      cross_session_nominal_gap: '跨盤名目價差'
    }[basis.mode] || '資料待確認';
    return '<div><div style="display:flex;justify-content:space-between;align-items:center;gap:6px"><span class="dc-mode-tag">' +
      esc(mode) + '</span><span class="dc-mode-tag">' + esc(basis.sessionTag || '—') + '</span></div>' +
      '<div class="dc-basis-gauge" title="日盤基差 Z20 ' + (hasZ ? signed(z, 2) : '樣本不足') + '">' +
      (hasZ ? '<i class="dc-basis-marker" style="left:' + marker + '%"></i>' : '') + '</div>' +
      '<div class="dc-gauge-scale"><span>逆基差 -3Z</span><span>0</span><span>正基差 +3Z</span></div>' +
      '<div class="dc-note" style="margin-top:5px">' + esc(basis.reference || '') +
      (basis.adjustmentAvailable ? '' : '；未取得完整合理價差／股息扣抵，不把夜盤價差判為實質套利異常。') + '</div></div>';
  }

  function divergenceMetrics(d) {
    var o = d.observed || {};
    if (d.id === 'INDEX_UP_BREADTH_DOWN') return '<div class="dc-metrics">' +
      metricHtml('DI 原值', num(o.divergenceIntensityRaw, 2)) + metricHtml('強度', num(o.divergenceIntensityScore, 0) + '/100') +
      metricHtml('廣度', num(Number(o.advRatio) * 100, 1) + '%') + metricHtml('3日斜率', signed(o.breadthVelocity3, 3)) +
      metricHtml('5日斜率', signed(o.breadthVelocity5, 3)) + metricHtml('弱於中線', num(o.belowNeutralStreak, 0) + '日') + '</div>';
    if (d.id === 'SPOT_FUTURES_CONFLICT') return '<div class="dc-metrics">' +
      metricHtml('跨盤價差', signedUnit(o.basisPts, 0, '點')) + metricHtml('日盤 Z20', signed(o.basisZ20, 2)) +
      metricHtml('日盤 Z60', signed(o.basisZ60, 2)) + metricHtml('期貨落後', signedUnit(o.futuresLagPctPoint, 2, 'pp')) +
      metricHtml('OI變化', signedUnit(o.txOiChangePct, 2, '%')) + '</div>';
    var items = [];
    Object.keys(o).slice(0, 6).forEach(function (key) {
      if (o[key] == null || typeof o[key] === 'object' || key === 'formula') return;
      items.push(metricHtml(key, typeof o[key] === 'number' ? num(o[key], 2) : String(o[key])));
    });
    return '<div class="dc-metrics">' + items.join('') + '</div>';
  }

  function basisContextMonitorHtml(ctx) {
    var basis = ctx.basisContext || {};
    if (basis.liveGapPts == null && basis.basisZ20 == null) return '';
    var fake = { id: 'SPOT_FUTURES_CONFLICT', observed: {
      basisPts: basis.liveGapPts, basisZ20: basis.basisZ20, basisZ60: basis.basisZ60,
      futuresLagPctPoint: basis.futuresLagPctPoint, txOiChangePct: basis.oiChangePct
    }};
    var insight = basis.shortCoveringRisk
      ? '期貨落後且 OI 明顯減少，較符合短空回補／避險退場；仍不能辨認多空持倉人身分。'
      : ('目前未命中期現衝突。' + (basis.sessionComparable
        ? '同盤基差仍在監測門檻內。'
        : '夜盤相對現貨收盤屬跨盤參考，不視為可套利的實質基差。'));
    return '<div class="dc-div"><div class="dc-div-head"><b>SPOT_FUTURES_CONTEXT</b><span class="dc-mode-tag">未確認衝突</span></div>' +
      '<div class="dc-div-insight" style="border-left-color:#38bdf8;background:rgba(56,189,248,.07);color:#c8f1ff">' + esc(insight) + '</div>' +
      divergenceMetrics(fake) + basisVisual({ visual: { basis: basis } }) + '</div>';
  }

  function divergencesHtml(ctx) {
    var rows = ctx.divergences || [];
    var html = rows.map(function (d) {
    return '<div class="dc-div ' + esc(d.severity || '') + '" data-dc-highlight="' + esc(d.id) + '"><div class="dc-div-head"><b>' + esc(d.id) +
        '</b>' + confidenceIcon(d.confidence) + '</div>' +
        (d.insight ? '<div class="dc-div-insight">' + esc(d.insight) + '</div>' : '') + divergenceMetrics(d) +
        (d.id === 'INDEX_UP_BREADTH_DOWN' ? indexBreadthVisual(d) : (d.id === 'SPOT_FUTURES_CONFLICT' ? basisVisual(d) : '')) +
        '<p>確認：' + esc(d.confirmation || '—') + '<br>失效：' + esc(d.invalidation || '—') +
        ((d.observed || {}).formula ? '<br>公式：' + esc(d.observed.formula) : '') + '</p></div>';
    }).join('');
    if (!rows.some(function (d) { return d.id === 'SPOT_FUTURES_CONFLICT'; })) html += basisContextMonitorHtml(ctx);
    return html || '<div class="dc-note">目前沒有命中具名背離規則。</div>';
  }

  function breadthTrendHtml(ctx) {
    var trend = ctx.breadthTrend || {}, rows = (trend.rows || []).slice().reverse();
    if (!rows.length) return '<div class="dc-note">廣度歷史尚未累積。</div>';
    var bars = rows.map(function (r) {
      var ratio = Math.max(0, Math.min(1, Number(r.advRatio) || 0));
      return '<i class="' + (ratio >= 0.5 ? 'pos' : '') + '" style="height:' +
        Math.max(5, ratio * 100) + '%" title="' + esc(r.asOf || 'current') + ' · advRatio ' + num(ratio, 2) + '"></i>';
    }).join('');
    var delta = trend.changeVs3;
    return '<div class="dc-breadth" role="img" aria-label="近二十期市場廣度趨勢">' + bars + '</div>' +
      '<div class="dc-note">最新 advRatio ' + num(trend.current, 2) + ' · 相對前三期 ' +
      (delta == null ? '—' : (Number(delta) >= 0 ? '+' : '') + num(delta, 2)) + ' · ' + esc(trend.reference || '') + '</div>';
  }

  var EVIDENCE_CATEGORIES = {
    all: '全部', market: '市場廣度', flow: '法人籌碼', derivatives: '期貨價差',
    options: '期權結構', session: '盤別動量', system: '系統指標', external: '外部／基本面'
  };

  function evidenceCategory(e) {
    var id = String(e.id || '');
    if (/^(shadow\.)?overnight_intraday\.|^shadow\.overnight_intraday\./.test(id)) return 'session';
    if (/^options\./.test(id)) return 'options';
    if (/^(txf\.|basis\.)/.test(id)) return 'derivatives';
    if (/^(flow\.|risk\.margin)/.test(id)) return 'flow';
    if (/^(pulse\.|sector\.)/.test(id)) return 'system';
    if (/^(global\.|fundamental\.|research\.|product\.)/.test(id)) return 'external';
    return 'market';
  }

  function evidenceScope(e) {
    var scope = String(e.marketScope || '').toUpperCase();
    if (scope === 'US' || /^global\./.test(String(e.id || ''))) return 'US';
    return 'TW';
  }

  function sourceInfo(e) {
    var source = String(e.source || 'unknown');
    var info = { url: '', cadence: '依來源資料週期更新', label: source };
    if (/TAIFEX/i.test(source)) {
      info.url = 'https://www.taifex.com.tw/'; info.cadence = '期交所交易日／盤別資料';
    } else if (/TWSE/i.test(source)) {
      info.url = 'https://www.twse.com.tw/'; info.cadence = '證交所即時或交易日資料';
    } else if (/FinMind/i.test(source)) {
      info.url = 'https://finmind.github.io/'; info.cadence = 'FinMind 交易日資料鏡像';
    } else if (/Yahoo Finance/i.test(source)) {
      info.url = 'https://finance.yahoo.com/'; info.cadence = '最近可得海外市場盤';
    } else if (/TSMC|quarterly earnings/i.test(source)) {
      info.url = 'https://investor.tsmc.com/'; info.cadence = '台積電季度法說／財報';
    } else if (/tw-pulse-intel/i.test(source)) {
      info.cadence = '本機 deterministic Pulse 更新時重算';
    }
    return info;
  }

  function relativeTimeInfo(e) {
    var raw = String(e.asOf || '').trim();
    var now = Date.now(), parsed, diff, days;
    if (!raw) return { state: 'stale', label: '無時間戳', title: '來源未提供可驗證時間', live: false };
    if (/^\d{4}Q[1-4]$/i.test(raw)) {
      return { state: 'reference', label: raw.replace('Q', ' Q'), title: '季度研究基準，不以分鐘新鮮度判定', live: false };
    }
    if (/^\d{6}$/.test(raw)) {
      parsed = new Date();
      parsed.setHours(Number(raw.slice(0, 2)), Number(raw.slice(2, 4)), Number(raw.slice(4, 6)), 0);
      diff = Math.max(0, now - parsed.getTime());
      if (diff < 60000) return { state: 'fresh', label: Math.max(1, Math.round(diff / 1000)) + ' 秒前', title: raw + ' · 即時盤', live: true };
      if (diff < 900000) return { state: 'delay', label: Math.round(diff / 60000) + ' 分鐘前', title: raw + ' · 盤中延遲', live: true };
      return { state: 'stale', label: raw.slice(0, 2) + ':' + raw.slice(2, 4), title: raw + ' · 超過 15 分鐘', live: true };
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      parsed = new Date(raw + 'T00:00:00');
      days = Math.max(0, Math.floor((new Date().setHours(0, 0, 0, 0) - parsed.getTime()) / 86400000));
      if (days === 0) return { state: 'fresh', label: '今日交易日', title: raw + ' · 交易日快照', live: false };
      if (days <= 3) return { state: 'reference', label: days === 1 ? '前一交易日' : days + ' 日前', title: raw + ' · 最近交易日資料', live: false };
      return { state: 'stale', label: days + ' 日前', title: raw + ' · 交易日資料可能過期', live: false };
    }
    parsed = new Date(raw);
    if (!isNaN(parsed.getTime())) {
      diff = Math.max(0, now - parsed.getTime());
      if (diff < 60000) return { state: 'fresh', label: Math.max(1, Math.round(diff / 1000)) + ' 秒前', title: raw, live: true };
      if (diff < 900000) return { state: 'delay', label: Math.round(diff / 60000) + ' 分鐘前', title: raw, live: true };
      if (diff < 86400000) return { state: 'stale', label: Math.round(diff / 3600000) + ' 小時前', title: raw, live: true };
      days = Math.floor(diff / 86400000);
      return { state: 'stale', label: days + ' 日前', title: raw, live: false };
    }
    return { state: 'reference', label: raw, title: '來源提供的研究／盤別基準', live: false };
  }

  function divergenceLink(ctx, e) {
    var id = String(e.id || ''), rows = ctx.divergences || [];
    for (var i = 0; i < rows.length; i += 1) {
      var d = rows[i] || {}, matched = false;
      if (d.id === 'INDEX_UP_BREADTH_DOWN') matched = /^(twii\.live|breadth\.)/.test(id);
      if (d.id === 'SPOT_FUTURES_CONFLICT') matched = /^(twii\.live|txf\.live|basis\.|flow\.tx_oi)/.test(id);
      if (matched) return { id: d.id, confidence: Math.round(Number(d.confidence || 0) * 100) };
    }
    return null;
  }

  function evidenceAlert(ctx, e) {
    var value = e.value, metric = String(e.metric || '');
    if (divergenceLink(ctx, e)) return true;
    if (e.comparison === 'extreme' || e.comparison === 'below_neutral') return true;
    if (metric === 'riskScore' && Number(value) >= 60) return true;
    if (/Percentile52w/.test(metric) && Number(value) >= 80) return true;
    if (value && typeof value === 'object' && Number(value.slope5) < 0 && Number(value.belowNeutralStreak) > 0) return true;
    return false;
  }

  function evidenceObjectHtml(value) {
    var aliases = {
      slope3: '3日斜率', slope5: '5日斜率', belowNeutralStreak: '弱於中線',
      expiry: '到期日', callOi: 'Call OI', putOi: 'Put OI', oiPutCallRatio: 'OI P/C',
      callOiMaxStrike: 'Call OI 高峰', putOiMaxStrike: 'Put OI 高峰',
      callWall: 'Call OI 高峰', putWall: 'Put OI 高峰', scenarios: '情境模型',
      atmIvPct: 'ATM IV', ivSkew25dPctPoint: '25Δ Skew', coveragePct: '覆蓋率',
      totalYi: 'Gamma密度', ivOiCoveragePct: 'IV/OI覆蓋', directionConsensus: '方向共識',
      totalWan: 'Vega密度', vegaOiCoveragePct: 'Vega/OI覆蓋',
      flipLow: 'Flip下緣', flipHigh: 'Flip上緣', flipWidthPct: 'Band寬度',
      flipStability: '穩定度', balancedGexYi: '平衡GEX', balancedVexYi: '平衡VEX', balancedFlip: '平衡Flip',
      coefficientVersion: '係數版本', baselineTradeDate: '比較基準日',
      callOiChangePct: 'Call OI變化', putOiChangePct: 'Put OI變化',
      atmIvChangePctPoint: 'ATM IV變化', gammaDensityChangePct: 'Gamma密度變化',
      vegaDensityChangePct: 'Vega密度變化'
      ,overnight20Pct: '隔夜20日', intraday20Pct: '日間20日', synchronizationPct: '同步率',
      gapRetention: '缺口保留', members: '有效成員', regime: '結構狀態'
    };
    function objectSummary(raw) {
      if (!raw || typeof raw !== 'object') return raw == null ? '—' : String(raw);
      if (Array.isArray(raw)) return raw.map(function (item, index) {
        if (!item || typeof item !== 'object') return String(item);
        var label = item.label || item.name || item.id || ('情境 ' + (index + 1));
        var gex = item.signedGexYi == null ? '' : ((Number(item.signedGexYi) > 0 ? '+' : '') + num(item.signedGexYi, 1) + '億');
        var flip = item.primaryFlip == null ? '' : ('Flip ' + num(item.primaryFlip, 0));
        return [label, gex, flip].filter(Boolean).join(' · ');
      }).join(' / ');
      if (raw.strike != null) {
        var oi = raw.openInterest == null ? '' : (' · OI ' + num(raw.openInterest, 0));
        return num(raw.strike, 0) + oi;
      }
      return '展開於專屬面板';
    }
    return '<div class="dc-kv-list">' + Object.keys(value || {}).map(function (key) {
      var raw = value[key], formatted = raw == null ? '—' : raw;
      if (typeof raw === 'number') formatted = (raw > 0 ? '+' : '') + num(raw, 3);
      if (key === 'belowNeutralStreak' && raw != null) formatted = num(raw, 0) + ' 日';
      if (/Yi$/.test(key) && raw != null) formatted = (Number(raw) > 0 ? '+' : '') + num(raw, 2) + ' 億';
      if (/Wan$/.test(key) && raw != null) formatted = (Number(raw) > 0 ? '+' : '') + num(raw, 1) + ' 萬';
      if (/Pct$/.test(key) && raw != null) formatted = num(raw, 1) + '%';
      if (/PctPoint$/.test(key) && raw != null) formatted = (Number(raw) > 0 ? '+' : '') + num(raw, 2) + 'pp';
      if (/Strike$|Flip$|flipLow|flipHigh/.test(key) && raw != null) formatted = num(raw, 0);
      if (key === 'directionConsensus') formatted = ({ DIRECTION_AMBIGUOUS: '情境方向分歧', CONSISTENT_POSITIVE: '各情境同向偏正', CONSISTENT_NEGATIVE: '各情境同向偏負' })[String(raw)] || formatted;
      if (key === 'flipStability') formatted = ({ low: '低穩定', medium: '中穩定', high: '高穩定' })[String(raw)] || formatted;
      if (raw && typeof raw === 'object') formatted = objectSummary(raw);
      return '<span class="dc-kv"><i>' + esc(aliases[key] || key) + '</i><b>' + esc(formatted) + '</b></span>';
    }).join('') + '</div>';
  }

  function evidenceValueHtml(e) {
    var metric = String(e.metric || ''), value = e.value;
    if (value && typeof value === 'object') return evidenceObjectHtml(value);
    var n = Number(value), valid = value !== '' && value != null && isFinite(n), main = value == null ? '—' : String(value);
    var note = '', cls = '';
    if (valid && metric === 'advRatio') { main = num(n * 100, 1) + '%'; note = n < 0.5 ? '廣度低於中線' : '廣度高於中線'; cls = n < 0.5 ? 'watch' : ''; }
    else if (valid && /institutionalNetYi|sblSellYi/.test(metric)) {
      main = (n > 0 ? '+' : '') + num(n, 1) + ' 億';
      note = /institutional/.test(metric) ? (n > 0 ? '買超' : (n < 0 ? '賣超' : '持平')) : '借券賣出金額';
      if (/institutional/.test(metric)) cls = n > 0 ? 'tw-up' : (n < 0 ? 'tw-down' : '');
    } else if (valid && /displayChangePct/.test(metric)) {
      main = (n > 0 ? '+' : '') + num(n, 2) + '%'; note = n > 0 ? '上漲' : (n < 0 ? '下跌' : '平盤');
      cls = evidenceScope(e) === 'US' ? (n > 0 ? 'us-up' : (n < 0 ? 'us-down' : '')) : (n > 0 ? 'tw-up' : (n < 0 ? 'tw-down' : ''));
    } else if (valid && /OiChangePct/.test(metric)) {
      main = (n > 0 ? '+' : '') + num(n, 2) + '%'; note = n > 0 ? '未平倉增倉' : (n < 0 ? '未平倉減倉' : '未平倉持平');
    } else if (valid && /BasisZ/.test(metric)) {
      main = (n > 0 ? '+' : '') + num(n, 2) + 'σ'; note = Math.abs(n) >= 2 ? '異常區間' : '正常區間'; cls = Math.abs(n) >= 2 ? 'risk' : '';
    } else if (valid && /Score$/.test(metric)) {
      main = num(n, 0) + '/100'; note = /risk/i.test(metric) ? '風險負擔' : '模型分數'; cls = /risk/i.test(metric) && n >= 60 ? 'risk' : '';
    } else if (valid && /Pct|Percentile|Rate/.test(metric)) {
      main = (n > 0 && /Change|meanChange/.test(metric) ? '+' : '') + num(n, 2) + '%';
    } else if (valid) main = num(n, Math.abs(n) >= 100 ? 1 : 3);
    return '<div class="dc-value-main ' + cls + '">' + esc(main) + '</div>' + (note ? '<div class="dc-value-note">' + esc(note) + '</div>' : '');
  }

  function evidenceRowMatches(e, ctx) {
    var text = [e.id, e.metric, e.source, e.reference, e.marketScope, e.session].join(' ').toLowerCase();
    var fresh = relativeTimeInfo(e);
    return (evidenceView.category === 'all' || evidenceCategory(e) === evidenceView.category) &&
      (evidenceView.mode === 'all' || (evidenceView.mode === 'alert' && evidenceAlert(ctx, e)) || (evidenceView.mode === 'live' && fresh.live)) &&
      (evidenceView.scope === 'all' || evidenceScope(e) === evidenceView.scope) &&
      (!evidenceView.query || text.indexOf(evidenceView.query.toLowerCase()) >= 0);
  }

  function evidenceHtml(ctx) {
    var rows = ctx.evidence || [];
    if (!rows.length) return '<div class="dc-note">核心證據尚未形成。</div>';
    var categoryTabs = Object.keys(EVIDENCE_CATEGORIES).map(function (key) {
      return '<button type="button" class="dc-ledger-btn' + (evidenceView.category === key ? ' on' : '') +
        '" data-evidence-category="' + key + '" aria-pressed="' + (evidenceView.category === key) + '">' + EVIDENCE_CATEGORIES[key] + '</button>';
    }).join('');
    var modeTabs = [['all', '全部狀態'], ['alert', '警示／異常'], ['live', '即時資料']].map(function (item) {
      return '<button type="button" class="dc-ledger-btn' + (evidenceView.mode === item[0] ? ' on' : '') +
        '" data-evidence-mode="' + item[0] + '" aria-pressed="' + (evidenceView.mode === item[0]) + '">' + item[1] + '</button>';
    }).join('');
    var scopeTabs = [['all', '全市場'], ['TW', '台股'], ['US', '美股']].map(function (item) {
      return '<button type="button" class="dc-ledger-btn' + (evidenceView.scope === item[0] ? ' on' : '') +
        '" data-evidence-scope="' + item[0] + '" aria-pressed="' + (evidenceView.scope === item[0]) + '">' + item[1] + '</button>';
    }).join('');
    var body = rows.map(function (e, index) {
      var category = evidenceCategory(e), fresh = relativeTimeInfo(e), source = sourceInfo(e), linked = divergenceLink(ctx, e);
      var alert = evidenceAlert(ctx, e), visible = evidenceRowMatches(e, ctx);
      var sourceTitle = source.cadence + ' · 品質 ' + (e.quality || '未標示') + ' · ' + (e.reference || '無計算基準');
      var sourceHtml = source.url ? '<a class="dc-source-link" href="' + esc(source.url) + '" target="_blank" rel="noopener noreferrer" title="' + esc(sourceTitle) + '">' + esc(source.label) + ' ↗</a>' :
        '<span class="dc-source-link" title="' + esc(sourceTitle) + '">' + esc(source.label) + ' ⓘ</span>';
      return '<tr class="dc-ledger-row' + (alert ? ' alert' : '') + '" data-evidence-index="' + index + '" data-category="' + category +
        '" data-mode-alert="' + alert + '" data-mode-live="' + fresh.live + '" data-scope="' + evidenceScope(e) + '"' + (visible ? '' : ' hidden') + '>' +
        '<td><i class="dc-fresh-dot ' + fresh.state + '" title="' + esc(fresh.title) + '"></i></td>' +
        '<td><div class="dc-evidence-key"><b>' + esc(e.id) + '</b><span class="dc-category">' + esc(EVIDENCE_CATEGORIES[category]) + '</span>' +
          (linked ? '<span class="dc-linkage" title="連動上游具名背離">' + esc(linked.id.replace(/_/g, ' ')) + ' ' + linked.confidence + '%</span>' : '') +
          '</div><div class="dc-evidence-metric">' + esc(e.metric) + '</div></td>' +
        '<td>' + evidenceValueHtml(e) + '</td>' +
        '<td>' + sourceHtml + '<div class="dc-fresh-label">' + esc(fresh.label) + ' · ' + esc(e.quality || '—') + '</div></td>' +
        '<td><div class="dc-source-meta">' + esc(e.marketScope || '—') + ' / ' + esc(e.session || '—') + '</div><div class="dc-source-meta" title="' + esc(e.reference || '') + '">' + esc(e.reference || '—') + '</div></td></tr>';
    }).join('');
    return '<div class="dc-ledger" aria-label="可搜尋、可匯出的證據帳本"><div class="dc-ledger-toolbar">' +
      '<label class="dc-ledger-search"><input id="dc-evidence-query" type="search" value="' + esc(evidenceView.query) + '" placeholder="搜尋證據 Key、指標或來源…" aria-label="搜尋證據 Key、指標或來源"></label>' +
      '<div class="dc-ledger-actions"><button type="button" class="dc-ledger-btn dc-ledger-copy" data-evidence-copy="json">複製 JSON</button>' +
      '<button type="button" class="dc-ledger-btn dc-ledger-copy" data-evidence-copy="csv">複製 CSV</button>' +
      '<button type="button" class="dc-ledger-btn dc-ledger-copy" data-evidence-copy="debug">複製除錯資訊</button><span class="dc-ledger-feedback" id="dc-ledger-feedback"></span></div></div>' +
      '<div class="dc-ledger-tabs" aria-label="狀態與市場篩選">' + modeTabs + '<span style="width:5px"></span>' + scopeTabs +
      '<span class="dc-ledger-feedback" id="dc-ledger-visible"></span></div><div class="dc-ledger-tabs" aria-label="證據分類">' + categoryTabs + '</div>' +
      '<div class="dc-ledger-table"><table><thead><tr><th>狀態</th><th>證據項目</th><th>語意值</th><th>來源／新鮮度</th><th>盤別／基準</th></tr></thead><tbody>' + body +
      '</tbody></table><div class="dc-ledger-empty" id="dc-ledger-empty" hidden>沒有符合目前條件的證據。</div></div></div>';
  }

  function evidenceCsv(rows) {
    var fields = ['id', 'metric', 'value', 'source', 'asOf', 'marketScope', 'session', 'reference', 'quality', 'comparison'];
    function cell(value) {
      var raw = value && typeof value === 'object' ? JSON.stringify(value) : String(value == null ? '' : value);
      return '"' + raw.replace(/"/g, '""') + '"';
    }
    return [fields.join(',')].concat((rows || []).map(function (row) { return fields.map(function (key) { return cell(row[key]); }).join(','); })).join('\r\n');
  }

  function copyText(text, done) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }).catch(function () { done(false); });
      return;
    }
    var area = document.createElement('textarea');
    area.value = text; area.style.position = 'fixed'; area.style.opacity = '0'; document.body.appendChild(area); area.select();
    var ok = false; try { ok = document.execCommand('copy'); } catch (ignore) {}
    document.body.removeChild(area); done(ok);
  }

  function applyEvidenceFilter() {
    var root = $('dc-root'), ctx = lastEvidenceContext || lastContext;
    if (!root || !ctx) return;
    var visible = 0;
    root.querySelectorAll('.dc-ledger-row').forEach(function (row) {
      var e = (ctx.evidence || [])[Number(row.getAttribute('data-evidence-index'))] || {};
      var show = evidenceRowMatches(e, ctx); row.hidden = !show; if (show) visible += 1;
    });
    var count = $('dc-ledger-visible'), empty = $('dc-ledger-empty');
    if (count) count.textContent = visible + ' / ' + (ctx.evidence || []).length + ' 筆';
    if (empty) empty.hidden = visible !== 0;
  }

  function bindEvidenceLedger() {
    var root = $('dc-root');
    if (!root) return;
    var query = $('dc-evidence-query');
    if (query) query.oninput = function () { evidenceView.query = query.value.trim(); applyEvidenceFilter(); };
    root.querySelectorAll('[data-evidence-category],[data-evidence-mode],[data-evidence-scope]').forEach(function (button) {
      button.onclick = function () {
        var group, value;
        if (button.hasAttribute('data-evidence-category')) { group = 'category'; value = button.getAttribute('data-evidence-category'); }
        else if (button.hasAttribute('data-evidence-mode')) { group = 'mode'; value = button.getAttribute('data-evidence-mode'); }
        else { group = 'scope'; value = button.getAttribute('data-evidence-scope'); }
        evidenceView[group] = value;
        root.querySelectorAll('[data-evidence-' + group + ']').forEach(function (item) {
          var on = item.getAttribute('data-evidence-' + group) === value; item.classList.toggle('on', on); item.setAttribute('aria-pressed', String(on));
        });
        applyEvidenceFilter();
      };
    });
    root.querySelectorAll('[data-evidence-copy]').forEach(function (button) {
      button.onclick = function () {
        var ledgerContext = lastEvidenceContext || lastContext;
        var kind = button.getAttribute('data-evidence-copy'), rows = (ledgerContext && ledgerContext.evidence) || [], payload;
        if (kind === 'csv') payload = evidenceCsv(rows);
        else if (kind === 'debug') payload = JSON.stringify({ contractVersion: lastContext.contractVersion, model: lastContext.model,
          asOf: lastContext.asOf, regime: lastContext.regime, actionEnvelope: lastContext.actionEnvelope,
          divergences: lastContext.divergences, dataQuality: lastContext.dataQuality, evidence: rows }, null, 2);
        else payload = JSON.stringify(rows, null, 2);
        copyText(payload, function (ok) {
          var feedback = $('dc-ledger-feedback'); if (feedback) feedback.textContent = ok ? '已複製' : '複製失敗';
          setTimeout(function () { if (feedback) feedback.textContent = ''; }, 1800);
        });
      };
    });
    applyEvidenceFilter();
  }

  function sectorHtml(ctx) {
    var sf = ctx.sectorFlow || {}, rows = sf.rows || [];
    var hist = sf.historyStatus || {};
    var meta = '<div class="s">' + esc(sf.label || '—') + ' · scope ' + esc(sf.marketScope || '—') +
      ' · 上漲參與 ' + num(sf.participationPct, 1) + '% · 成交覆蓋 ' + num(sf.turnoverCoveragePct, 1) +
      '% · Top3 ' + num(sf.top3SharePct, 1) + '% · HHI ' + num(sf.hhi, 0) +
      (sf.turnoverScope ? ' · 成交口徑：上市普通股產業內占比' : '') +
      ' · RS20 ' + (hist.rs20Available ? '完整' : ('建置 ' + num(hist.historyDates, 0) + '/21 交易日')) + '</div>';
    if (!rows.length) return meta;
    return meta + '<div class="dc-scroll" style="max-height:150px"><table><tr><th>產業</th><th>漲跌</th><th>成交占比</th><th>RS20</th><th>口徑</th></tr>' +
      rows.slice().sort(function (a, b) {
        var as = a.marketSharePct == null ? -1 : Number(a.marketSharePct);
        var bs = b.marketSharePct == null ? -1 : Number(b.marketSharePct);
        return bs !== as ? bs - as : Math.abs(b.changePct || 0) - Math.abs(a.changePct || 0);
      }).slice(0, 12).map(function (r) {
        return '<tr><td>' + esc(r.sector || r.name) + '</td><td>' + num(r.changePct, 2) + '%</td><td>' +
          (r.marketSharePct == null ? '—' : num(r.marketSharePct, 2) + '%') + '</td><td>' +
          (r.rs20VsBenchmarkPct == null ? '—' : signedUnit(r.rs20VsBenchmarkPct, 2, '%')) + '</td><td>' +
          (r.proxyBasket ? 'proxyBasket' : (r.turnoverEligible === false ? '複合指數' : esc(r.turnoverScope || r.marketScope || '—'))) + '</td></tr>';
      }).join('') + '</table></div>';
  }

  function portfolioHtml(ctx) {
    var p = ctx.portfolioOverlay;
    if (!p) return '<div class="dc-note">未偵測到實際持倉；不以自選池冒充投資組合。</div>';
    if (p.available === false) return '<div class="dc-note">投組資料不可用：' + esc(p.error || '價格序列不足') +
      '。在完成 Beta／VaR 檢查前不產生倉位範圍。</div>';
    var look = p.lookThrough || {};
    var rows = look.rows || [];
    return '<div class="dc-scenario">' +
      featureHtml('Portfolio Beta', { value: p.portfolioBeta == null ? null : Math.max(-1, Math.min(1, p.portfolioBeta - 1)), raw: p.portfolioBeta }) +
      featureHtml('1日 95% VaR', { value: p.var95DailyPct == null ? null : Math.min(1, p.var95DailyPct / 4), raw: p.var95DailyPct + '%' }) +
      featureHtml('平均相關', { value: p.averageCorrelation, raw: p.averageCorrelation }) + '</div>' +
      '<div class="dc-note">單一持倉上限 ' + num(p.maxSingleNameWeightPct, 1) + '% · 最大產業 ' + esc(p.topSector || '—') +
      ' ' + num(p.topSectorWeightPct, 1) + '% · 樣本 ' + esc(p.sampleDays || '—') + ' 日</div>' +
      (look.effectiveGrossExposurePct == null ? '' : '<div class="dc-lab-grid" style="margin-top:6px">' +
        '<div class="dc-lab-box"><div class="k">每日槓桿穿透總曝險</div><div class="v">' + num(look.effectiveGrossExposurePct, 1) + '%</div></div>' +
        '<div class="dc-lab-box"><div class="k">台積電經濟曝險</div><div class="v">' + num(look.tsmcEconomicExposurePct, 1) + '%</div></div>' +
        '<div class="dc-lab-box"><div class="k">科技經濟曝險</div><div class="v">' + num(look.technologyEconomicExposurePct, 1) + '%</div></div>' +
        '<div class="dc-lab-box"><div class="k">分散判定</div><div class="v">' + (look.leveragedOverlap ? '集中重疊' : '—') + '</div></div></div>' +
        (look.overlapNote ? '<div class="dc-note" style="margin-top:5px;color:var(--orange)">' + esc(look.overlapNote) + '</div>' : '') +
        (rows.length ? '<div class="dc-scroll" style="max-height:130px;margin-top:5px"><table><tr><th>標的</th><th>表面</th><th>倍數</th><th>有效曝險</th><th>台積電曝險</th><th>角色</th></tr>' + rows.map(function (row) {
          return '<tr><td>' + esc(row.symbol) + '</td><td>' + num(row.surfaceWeightPct, 1) + '%</td><td>' + num(row.leverageMultiple, 1) + 'x</td><td>' +
            num(row.effectiveGrossPct, 1) + '%</td><td>' + num(row.tsmcEconomicExposurePct, 1) + '%</td><td>' + esc(row.role) + '</td></tr>';
        }).join('') + '</table></div>' : ''));
  }

  function portfolioSwitchHtml() {
    return '<span class="dc-portfolio-switch" role="group" aria-label="投組資料來源">' +
      '<button type="button" class="dc-source-btn' + (portfolioMode === 'actual' ? ' on' : '') +
        '" id="dc-use-positions" aria-pressed="' + (portfolioMode === 'actual') +
        '">實際持倉</button>' +
      '<button type="button" class="dc-source-btn' + (portfolioMode === 'observation_pool' ? ' on' : '') +
        '" id="dc-use-watch" aria-pressed="' + (portfolioMode === 'observation_pool') +
        '">等權自選觀察池</button></span>';
  }

  function compactNtd(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    if (Math.abs(n) >= 1e8) return num(n / 1e8, 2) + ' 億';
    if (Math.abs(n) >= 1e4) return num(n / 1e4, 1) + ' 萬';
    return num(n, 0);
  }

  function optionsDensityRows(rows, valueKey) {
    rows = rows || [];
    var maxValue = Math.max.apply(null, rows.map(function (row) { return Math.abs(Number(row[valueKey]) || 0); }).concat([1]));
    return rows.map(function (row) {
      var value = Number(row[valueKey]) || 0;
      var width = Math.max(2, Math.abs(value) / maxValue * 100);
      return '<div class="dc-options-gamma-row"><b>' + esc(num(row.strike, 0)) + '</b>' +
        '<span class="dc-options-gamma-bar"><i style="width:' + num(width, 1) + '%"></i></span><span>' + compactNtd(value) + '</span></div>';
    }).join('') || '<div class="dc-note">履約價密度資料不足。</div>';
  }

  function optionsChangeText(value, digits, suffix) {
    var n = Number(value);
    if (!isFinite(n)) return null;
    return (n > 0 ? '▲ +' : (n < 0 ? '▼ ' : '• ')) + num(n, digits) + (suffix || '');
  }

  function optionsHistoryHtml(history) {
    history = history || {};
    var status = history.status || 'unavailable';
    var count = Number(history.sampleCount) || 0, required = Number(history.requiredSamples) || 2;
    if (status !== 'ready') {
      var message = status === 'new_expiry' ? '新到期別，已重新累積' :
        (status === 'building' ? '同到期歷史建置中' : '同到期歷史尚不可用');
      var progress = status === 'unavailable' ? '' : (' · ' + count + '/' + required + ' 個日終快照');
      return '<div class="dc-options-change"><div class="dc-options-change-head"><b>' + esc(message) + '</b><span>不跨到期別比較' + esc(progress) + '</span></div></div>';
    }
    var changes = history.changes || {};
    var cells = [
      ['Call OI', optionsChangeText(changes.callOpenInterestPct, 1, '%')],
      ['Put OI', optionsChangeText(changes.putOpenInterestPct, 1, '%')],
      ['ATM IV', optionsChangeText(changes.atmIvPctPoint, 2, 'pp')],
      ['Gamma 密度', optionsChangeText(changes.totalOiGammaPct, 1, '%')],
      ['Vega 密度', optionsChangeText(changes.totalOiVegaPct, 1, '%')]
    ].filter(function (item) { return item[1] != null; });
    var baseline = String(history.baselineTradeDate || '').slice(5).replace('-', '/');
    return '<div class="dc-options-change"><div class="dc-options-change-head"><b>同到期變化 · 對 ' + esc(baseline || '前一期') + ' 日終</b>' +
      '<span>' + esc(count + ' 個同到期快照') + '</span></div>' +
      (cells.length ? '<div class="dc-options-change-grid">' + cells.map(function (item) {
        return '<div class="dc-options-change-cell"><div class="k">' + esc(item[0]) + '</div><div class="v">' + esc(item[1]) + '</div></div>';
      }).join('') + '</div>' : '<div class="dc-note">前一期基準為零或欄位不足，暫不計算百分比。</div>') + '</div>';
  }

  function optionsDirectionLabel(value) {
    return {
      positive: '三情境同為正 Gamma', negative: '三情境同為負 Gamma',
      DIRECTION_AMBIGUOUS: '情境方向分歧'
    }[value] || '方向尚未形成';
  }

  function optionsStabilityLabel(value) {
    return { low: '低穩定', normal: '一般', unavailable: '不可用' }[value] || '不可用';
  }

  function optionsWarningLabel(value) {
    return {
      PARITY_DIVIDEND_YIELD_OUTLIER: '短天期 parity carry 年化偏離，已保留模型假設',
      PARITY_CARRY_ANNUALIZATION_EXTREME: '短天期 parity carry 年化偏離，已保留模型假設',
      SPOT_CHAIN_TIMESTAMP_MISMATCH: '現貨與期權鏈資料日不同，模型已停用',
      IV_OI_COVERAGE_BELOW_80PCT: '有效 IV 對應 OI 未達 80%，模型已停用',
      STALE_OR_HYBRID_REFERENCE: '資料過期或時點混合',
      SOURCE_REFRESH_FAILED: '官方來源更新失敗，顯示最近快取'
    }[value] || String(value || '');
  }

  function optionsProfileSvg(rows, spot) {
    rows = (rows || []).slice(0, 17);
    if (!rows.length) return '<div class="dc-note">本到期別沒有可顯示的履約價資料。</div>';
    var width = 620, height = 118, left = 18, right = 10, middle = 55;
    var inner = width - left - right, slot = inner / rows.length;
    var maxOi = Math.max.apply(null, rows.map(function (r) { return Math.max(Number(r.callOi) || 0, Number(r.putOi) || 0); }).concat([1]));
    var bars = rows.map(function (r, i) {
      var x = left + i * slot + slot * 0.16, w = Math.max(2, slot * 0.68);
      var ch = Math.max(1, (Number(r.callOi) || 0) / maxOi * 39);
      var ph = Math.max(1, (Number(r.putOi) || 0) / maxOi * 39);
      var labelY = height - 5;
      return '<g><title>' + esc(num(r.strike, 0) + ' · Call OI ' + num(r.callOi, 0) + ' · Put OI ' + num(r.putOi, 0)) + '</title>' +
        '<rect class="dc-options-call" x="' + num(x, 1) + '" y="' + num(middle - ch, 1) + '" width="' + num(w, 1) + '" height="' + num(ch, 1) + '" rx="1"/>' +
        '<rect class="dc-options-put" x="' + num(x, 1) + '" y="' + (middle + 1) + '" width="' + num(w, 1) + '" height="' + num(ph, 1) + '" rx="1"/>' +
        ((i % 2 === 0 || rows.length <= 9) ? '<text x="' + num(x + w / 2, 1) + '" y="' + labelY + '" text-anchor="middle">' + esc(num(r.strike, 0)) + '</text>' : '') + '</g>';
    }).join('');
    var closest = 0;
    rows.forEach(function (r, i) { if (Math.abs(Number(r.strike) - Number(spot)) < Math.abs(Number(rows[closest].strike) - Number(spot))) closest = i; });
    var spotX = left + closest * slot + slot / 2;
    return '<div class="dc-options-chart"><svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-labelledby="dc-options-profile-title" preserveAspectRatio="none">' +
      '<title id="dc-options-profile-title">TXO 履約價 Call 與 Put 未平倉分布；上方為 Call，下方為 Put</title>' +
      '<line class="dc-options-axis" x1="' + left + '" y1="' + middle + '" x2="' + (width - right) + '" y2="' + middle + '"/>' +
      '<line class="dc-options-spot" x1="' + num(spotX, 1) + '" y1="8" x2="' + num(spotX, 1) + '" y2="101"/>' + bars +
      '<text x="4" y="12">CALL</text><text x="4" y="69">PUT</text></svg></div>';
  }

  function optionsStructureHtml(ctx) {
    var lab = ctx.optionsStructure || {}, status = lab.status || 'insufficient';
    var observed = lab.observed || {}, derived = lab.derived || {}, modeled = lab.modeled || {}, quality = lab.quality || {}, history = lab.history || {};
    var statusLabel = status === 'ready' ? '資料完成' : (status === 'stale' ? '資料過期' : '尚未載入');
    var expiry = observed.expiry || '—';
    var summaryMeta = expiry + (observed.tradeDate ? ' · 資料日 ' + observed.tradeDate : '') + ' · TAIFEX';
    var openAttr = optionsLabOpen ? ' open' : '';
    if (status === 'insufficient') {
      return '<details id="dc-options-lab" class="dc-lab dc-options-lab"' + openAttr + '><summary><span class="dc-options-name">台指選擇權結構</span>' +
        '<span class="dc-options-status insufficient">' + statusLabel + '</span><span class="dc-options-meta">日終研究 · 不推定造市商持倉</span></summary>' +
        '<div class="dc-options-layer observed"><header><b>等待官方日終鏈</b><span>首次展開會自動更新</span></header>' +
        '<div class="dc-note">先取得精確到期日、一般盤 OI 與結算價，資料不足時不產生 IV、Signed GEX 或 Flip。</div>' +
        '<div class="dc-options-actions"><button type="button" class="dc-btn" id="dc-options-refresh">更新期權結構</button><span class="dc-note" id="dc-options-refresh-status">—</span></div></div></details>';
    }
    var callWall = observed.callWall || {}, putWall = observed.putWall || {};
    var gammaRows = optionsDensityRows(derived.topGammaStrikes, 'absoluteGamma1PctNtd');
    var vegaRows = optionsDensityRows(derived.topVegaStrikes, 'oiVega1VolPointNtd');
    var scenarios = modeled.scenarios || [];
    var scenarioRows = scenarios.map(function (row) {
      return '<tr><td>' + esc(row.label || row.id) + '</td><td>' + (row.signedGexYi == null ? '—' : num(row.signedGexYi, 2) + ' 億') + '</td><td>' +
        (row.scenarioVex1VolPointNtd == null ? '—' : compactNtd(row.scenarioVex1VolPointNtd)) + '</td><td>' +
        (row.primaryFlip == null ? '—' : num(row.primaryFlip, 0)) + '</td><td>' + esc(row.assumption || '—') + '</td></tr>';
    }).join('');
    var band = modeled.flipBand || {};
    var modeledBody = modeled.eligible ?
      '<div class="dc-options-kpis"><div class="dc-options-kpi"><div class="k">方向共識</div><div class="v">' + esc(optionsDirectionLabel(modeled.directionConsensus)) + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">Flip Band</div><div class="v">' + (band.low == null ? '—' : num(band.low, 0) + '–' + num(band.high, 0)) + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">Band 寬度</div><div class="v">' + (band.widthPct == null ? '—' : num(band.widthPct, 2) + '%') + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">穩定度</div><div class="v">' + esc(optionsStabilityLabel(band.stability)) + '</div></div></div>' +
      '<div class="dc-options-scroll"><table class="dc-options-table" data-st-sort="off"><caption class="dc-note">情境式淨 Gamma／Vega；持倉係數皆為模型假設</caption><tr><th scope="col">情境</th><th scope="col">Modeled Signed GEX</th><th scope="col">Modeled Signed VEX</th><th scope="col">Primary Flip</th><th scope="col">持倉假設</th></tr>' + scenarioRows + '</table></div>' :
      '<div class="dc-note">模型已停用：資料過期、時點不一致或有效 IV 對應 OI 未達 80%。仍可閱讀上方官方 OI 事實。</div>';
    return '<details id="dc-options-lab" class="dc-lab dc-options-lab"' + openAttr + '><summary><span class="dc-options-name">台指選擇權結構</span>' +
      '<span class="dc-options-status ' + esc(status) + '">' + statusLabel + '</span><span class="dc-options-meta">' + esc(summaryMeta) + '</span></summary>' +
      '<section class="dc-options-layer observed" data-layer="observed"><header><b>已觀測資料</b><span>OI／成交量／履約價 · 官方一般盤日終資料</span></header>' +
      '<div class="dc-options-kpis"><div class="dc-options-kpi"><div class="k">參考現貨</div><div class="v">' + num(observed.spot, 0) + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">Call OI 高峰</div><div class="v">' + num(callWall.strike, 0) + '</div><div class="s">OI ' + num(callWall.openInterest, 0) + ' · 現貨±10%</div></div>' +
      '<div class="dc-options-kpi"><div class="k">Put OI 高峰</div><div class="v">' + num(putWall.strike, 0) + '</div><div class="s">OI ' + num(putWall.openInterest, 0) + ' · 現貨±10%</div></div>' +
      '<div class="dc-options-kpi"><div class="k">OI Put/Call</div><div class="v">' + num(observed.oiPutCallRatio, 2) + '</div><div class="s">到期 ' + esc(expiry) + '</div></div></div>' +
      optionsProfileSvg(observed.profile, observed.spot) + optionsHistoryHtml(history) + '</section>' +
      '<section class="dc-options-layer derived" data-layer="derived"><header><b>衍生計算</b><span>方向中立 · Black–Scholes／OI Gamma／Vega Density</span></header>' +
      '<div class="dc-options-kpis five"><div class="dc-options-kpi"><div class="k">ATM IV</div><div class="v">' + (derived.atmIvPct == null ? '—' : num(derived.atmIvPct, 1) + '%') + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">25Δ Put−Call Skew</div><div class="v">' + (derived.ivSkew25dPctPoint == null ? '—' : num(derived.ivSkew25dPctPoint, 1) + 'pp') + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">IV 對應 OI 覆蓋</div><div class="v">' + num(derived.ivOiCoveragePct, 1) + '%</div></div>' +
      '<div class="dc-options-kpi"><div class="k">OI Gamma／指數 1%</div><div class="v">' + compactNtd(derived.totalOiGamma1PctNtd) + '</div></div>' +
      '<div class="dc-options-kpi"><div class="k">OI Vega／IV 1pt</div><div class="v">' + compactNtd(derived.totalOiVega1VolPointNtd) + '</div></div></div>' +
      '<div class="dc-options-density-grid"><div class="dc-options-density-card gamma"><header><b>OI Gamma 密度</b><span>指數變動 1%</span></header>' + gammaRows + '</div>' +
      '<div class="dc-options-density-card vega"><header><b>OI Vega 密度</b><span>IV +1 波動率點（1 vol pt）</span></header>' + vegaRows + '</div></div>' +
      '<div class="dc-options-warn">Gamma／Vega 密度是方向中立的一側 OI 結構敏感度，不是已觀測的造市商淨曝險。</div></section>' +
      '<section class="dc-options-layer modeled" data-layer="modeled"><header><b>情境模型 · Shadow</b><span>Modeled Signed GEX／VEX／Flip Band</span></header>' + modeledBody +
      '<div class="dc-options-warn">' + esc(modeled.warning || '公開 OI 無法證明造市商位於多方或空方；本層不作直接買賣訊號。') + ' Modeled Signed VEX 不是期貨避險流、方向預測或結算釘價機率。</div></section>' +
      '<div class="dc-options-actions"><button type="button" class="dc-btn" id="dc-options-refresh">重新整理期權結構</button><span class="dc-note" id="dc-options-refresh-status">' +
      esc((quality.warnings || []).map(optionsWarningLabel).join(' · ') || '資料來源與假設已寫入 Evidence Ledger') + '</span></div></details>';
  }

  function refreshOptionsStructure(force) {
    if (optionsRefreshStarted && !force) return;
    optionsRefreshStarted = true;
    var button = $('dc-options-refresh'), status = $('dc-options-refresh-status');
    if (button) { button.disabled = true; button.textContent = '更新中…'; }
    if (status) status.textContent = '下載 TAIFEX 日終鏈並驗證精確到期別…';
    fetch(SRV + '/options/txo/refresh', {
      method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: !!force })
    }).then(function (r) {
      return r.text().then(function (raw) {
        if (!r.ok) throw new Error(raw || ('HTTP ' + r.status));
        return JSON.parse(raw);
      });
    }).then(function (ctx) {
      if (window.DecisionData && DecisionData.publish) DecisionData.publish(ctx, 'options-refresh');
    }).catch(function (err) {
      optionsRefreshStarted = false;
      if (button) { button.disabled = false; button.textContent = '重試更新'; }
      if (status) status.textContent = '更新失敗：' + String(err && err.message || err).slice(0, 120);
    });
  }

  function bindOptionsLab() {
    var details = $('dc-options-lab'), button = $('dc-options-refresh');
    if (!details) return;
    details.addEventListener('toggle', function () {
      optionsLabOpen = !!details.open;
      var current = (lastContext && lastContext.optionsStructure) || {};
      var derived = current.derived || {};
      var needsV2 = Number(current.contractVersion || 0) < 2 || derived.totalOiVega1VolPointNtd == null;
      if (optionsLabOpen && ((current.status || 'insufficient') === 'insufficient' || needsV2)) refreshOptionsStructure(false);
    });
    if (button) button.onclick = function (event) {
      event.preventDefault();
      event.stopPropagation();
      refreshOptionsStructure(true);
    };
  }

  function bindPortfolioSwitch() {
    var root = $('dc-root');
    if (!root || root.getAttribute('data-portfolio-switch-bound') === '1') return;
    root.setAttribute('data-portfolio-switch-bound', '1');
    root.addEventListener('click', function (event) {
      var button = event.target && event.target.closest ? event.target.closest('.dc-source-btn') : null;
      if (!button || !root.contains(button)) return;
      var nextMode = button.id === 'dc-use-watch' ? 'observation_pool' : 'actual';
      setPortfolioMode(nextMode);
    }, true);
  }

  function setPortfolioMode(mode) {
    var nextMode = mode === 'observation_pool' ? 'observation_pool' : 'actual';
    if (portfolioMode === nextMode) return;
    portfolioMode = nextMode;
    var root = $('dc-root');
    if (root) root.querySelectorAll('.dc-source-btn').forEach(function (item) {
      var on = (item.id === 'dc-use-watch') === (portfolioMode === 'observation_pool');
      item.classList.toggle('on', on);
      item.setAttribute('aria-pressed', String(on));
    });
    load(true);
  }

  function oiTone(market, value) {
    var n = Number(value);
    if (!isFinite(n) || n === 0) return '';
    return String(market).toUpperCase() === 'US' ? (n > 0 ? 'us-up' : 'us-down') : (n > 0 ? 'tw-up' : 'tw-down');
  }

  function oiSignedPct(value) {
    var n = Number(value);
    return !isFinite(n) ? '—' : (n > 0 ? '+' : '') + num(n, 2) + '%';
  }

  function oiQualityLabel(value) {
    return ({ good: '資料完整', mixed: '部分降級', stale: '快取過期', insufficient: '資料不足' })[value] || '等待資料';
  }

  function oiRegimeLabel(regime) {
    regime = regime || {};
    return regime.label || ({
      OVERNIGHT_CONFIRMED: '隔夜定價與日間承接同向',
      GAP_FADE_DISTRIBUTION: '隔夜上修、日間回吐',
      CASH_SESSION_ACCUMULATION: '日間承接主導',
      BROAD_CORRECTION: '隔夜與日間同步轉弱',
      MIXED_LOW_CONFIDENCE: '盤別訊號分歧',
      INSUFFICIENT_DATA: '資料不足'
    })[regime.id] || '等待結構判定';
  }

  function oiMarketHtml(market) {
    market = market || {};
    var summary = market.summary || {}, quality = market.quality || {}, regime = summary.regime || {};
    var relative = summary.benchmarkRelative || {}, breadth = summary.breadth || {};
    var members = market.members || [], benchmark = market.benchmark || {};
    var memberRows = members.map(function (member) {
      var raw = member.raw || {}, rel = member.relative || {}, gap = raw.gapRetention || {}, mq = member.quality || {};
      return '<tr><td><b>' + esc(member.name || member.symbol) + '</b><br><span class="dc-note">' + esc(member.symbol) + '</span></td>' +
        '<td class="' + oiTone(market.market, raw.overnight20Pct) + '">' + oiSignedPct(raw.overnight20Pct) + '</td>' +
        '<td class="' + oiTone(market.market, raw.intraday20Pct) + '">' + oiSignedPct(raw.intraday20Pct) + '</td>' +
        '<td>' + oiSignedPct(rel.overnight20Pct) + ' / ' + oiSignedPct(rel.intraday20Pct) + '</td>' +
        '<td>' + (gap.value == null ? '—' : num(gap.value, 2) + '×') + '<br><span class="dc-note">' + num(gap.sample, 0) + ' gaps</span></td>' +
        '<td>' + num(raw.sampleSize, 0) + '<br><span class="dc-note">' + esc(mq.status || '—') + '</span></td></tr>';
    }).join('');
    return '<section class="dc-oi-market"><div class="dc-oi-head"><div><b>' + esc(market.label || market.market || '—') + '</b>' +
      '<div class="s">' + esc((market.universe || {}).id || 'memory_v1') + ' · ' + esc(summary.asOf || '—') + '</div></div>' +
      '<span class="dc-oi-quality ' + esc(quality.status || 'insufficient') + '">' + esc(oiQualityLabel(quality.status)) + '</span></div>' +
      '<div class="dc-oi-state"><b>' + esc(oiRegimeLabel(regime)) + '</b><span>證據強度 ' +
        (regime.evidenceStrength == null ? '—' : Math.round(Number(regime.evidenceStrength) * 100) + '%') + '</span></div>' +
      '<div class="dc-oi-kpis"><div class="dc-oi-kpi"><div class="k">隔夜定價 · 20日</div><div class="v ' +
        oiTone(market.market, summary.overnightRepricing20Pct) + '">' + oiSignedPct(summary.overnightRepricing20Pct) + '</div><div class="s">相對 ' +
        esc(benchmark.symbol || '基準') + ' ' + oiSignedPct(relative.overnight20Pct) + '</div></div>' +
      '<div class="dc-oi-kpi"><div class="k">日間承接 · 20日</div><div class="v ' + oiTone(market.market, summary.cashSessionAcceptance20Pct) + '">' +
        oiSignedPct(summary.cashSessionAcceptance20Pct) + '</div><div class="s">相對基準 ' + oiSignedPct(relative.intraday20Pct) + '</div></div>' +
      '<div class="dc-oi-kpi"><div class="k">族群同步率</div><div class="v">' + num(summary.synchronizationPct, 1) + '%</div><div class="s">正向 ' +
        num(breadth.positive, 0) + ' / 有效 ' + num(breadth.eligible, 0) + '；覆蓋 ' + num(summary.memberCount, 0) + '/' +
        num(summary.expectedMemberCount, 0) + '</div></div></div>' +
      '<details class="dc-oi-detail"><summary>逐檔、基準與資料品質</summary><div class="dc-oi-scroll"><table class="dc-oi-table"><thead><tr>' +
        '<th>標的</th><th>隔夜20日</th><th>日間20日</th><th>相對基準 ON / ID</th><th>缺口保留</th><th>樣本</th></tr></thead><tbody>' +
        memberRows + '</tbody></table></div><div class="dc-note">基準 ' + esc(benchmark.symbol || '—') + ' · ' + esc(benchmark.method || '—') +
        ' · quorum ' + num((quality.quorum || {}).eligible, 0) + '/' + num((quality.quorum || {}).required, 0) +
        ' · 調整 ' + esc(quality.adjustmentMode || '—') + '</div></details></section>';
  }

  function sessionMomentumHtml(ctx) {
    var research = ((ctx.researchObservations || {}).overnightIntraday) || {};
    var status = ((research.quality || {}).status) || 'insufficient';
    var markets = research.markets || [];
    var openAttr = oiLabOpen ? ' open' : '';
    var body = markets.length ? '<div class="dc-oi-grid">' + markets.map(oiMarketHtml).join('') + '</div>' :
      '<div class="dc-note">盤別研究尚未更新。此區不會用 0% 冒充缺失資料；按下更新後才會取得固定觀察籃子日線。</div>';
    return '<details id="dc-oi-lab" class="dc-lab dc-oi-lab"' + openAttr + '><summary><span>盤別動量結構 · Overnight × Intraday</span>' +
      '<span class="tag">Shadow · 觀察</span><span class="dc-oi-quality ' + esc(status) + '">' + esc(oiQualityLabel(status)) + '</span></summary>' +
      body + '<div class="dc-oi-authority">觀察性研究：隔夜代表收盤後至次日開盤的價格重估，不等同法人或 Smart Money 流向；本模組不改寫市場狀態、信心、Key Levels、Action Envelope 或槓桿限制。</div>' +
      '<div class="dc-oi-actions"><button type="button" class="dc-btn" id="dc-oi-refresh">更新盤別研究</button><span class="dc-note" id="dc-oi-refresh-status">' +
        esc(research.methodologyVersion || '固定觀察籃子 · Yahoo adjusted daily') + '</span></div></details>';
  }

  function bindSessionMomentumLab() {
    var details = $('dc-oi-lab'), button = $('dc-oi-refresh'), status = $('dc-oi-refresh-status');
    if (details) details.addEventListener('toggle', function () { oiLabOpen = !!details.open; });
    if (button) button.onclick = function (event) {
      event.preventDefault(); event.stopPropagation(); button.disabled = true; button.textContent = '更新中…';
      if (status) status.textContent = '正在取得固定白名單的調整後日線並驗證盤別恆等式…';
      if (window.DecisionData && DecisionData.refreshOvernightResearch) {
        DecisionData.refreshOvernightResearch(true).finally(function () {
          var current = $('dc-oi-refresh'); if (current) { current.disabled = false; current.textContent = '更新盤別研究'; }
        });
      }
    };
  }

  function contextWithResearchEvidence(ctx) {
    var research = ((ctx.researchObservations || {}).overnightIntraday) || {};
    return Object.assign({}, ctx, { evidence: (ctx.evidence || []).concat(research.evidence || []) });
  }

  function exposureLabHtml(ctx) {
    var lab = ctx.exposureLab || {};
    if (!lab.model) return '<div class="dc-note">Exposure Lab 尚未形成。</div>';
    var rel = (((lab.fundamentalReliability || {}).tsmcGuidanceHistory || {}).value) || {};
    var eps = (((lab.fundamentalReliability || {}).tsmcEpsEvidence || {}).value) || {};
    var core = lab.coreResearch || {}, weekly = lab.weeklyHealth || {};
    var vol = lab.volatility || {};
    var stateVol = ((vol.stateDownside20AnnualPct || {}).value);
    var forecastVol = ((vol.horizonForecastAnnualPct || {}).value);
    var hypotheses = lab.hypotheses || [];
    var statusLabels = {
      EDGE_POSITIVE_RESEARCH: '效率差為正（研究）',
      INDETERMINATE: '情境跨零',
      NO_2X_EDGE: '效率差不為正',
      RESEARCH_DATA_INCOMPLETE: '研究資料未完整'
    };
    var rows = Object.keys(lab.benchmarks || {}).map(function (id) {
      var b = lab.benchmarks[id] || {}, base = (b.scenarios || {}).base || {}, edge = b.leveragedCarryEdge2x || {};
      var bVol = (((b.volatility || {}).horizonForecastAnnualPct || {}).value);
      return '<tr><td><b>' + esc(b.label || id) + '</b><small>' + esc(id) + '</small></td><td>' + num(b.tsmcWeightPct, 1) +
        '%<small>' + esc(b.weightAsOf || '無日期') + '</small></td><td>' + num(base.expectedGeometricReturnPct, 1) +
        '%<small>乘法差 ' + num(base.approximationDeltaPctPoint, 2) + 'pp</small></td><td>' + num(bVol, 1) +
        '%</td><td><b class="dc-edge ' + (Number(edge.basePctPoint) > 0 ? 'pos' : 'warn') + '">' +
        (edge.basePctPoint == null ? '—' : (Number(edge.basePctPoint) > 0 ? '+' : '') + num(edge.basePctPoint, 1) + 'pp') +
        '</b><small>' + num(edge.bearPctPoint, 1) + ' / ' + num(edge.bullPctPoint, 1) + '</small></td><td>' +
        '<span class="dc-research-status ' + esc(String(b.status || '').toLowerCase()) + '">' +
        esc(statusLabels[b.status] || b.status || '—') + '</span></td></tr>';
    }).join('');
    var finalRange = lab.finalEligibleRange;
    var temp = lab.temperature || {};
    var tempScore = temp.score == null ? 0 : Math.max(0, Math.min(100, Number(temp.score) || 0));
    var tone = /^(cool|steady|watch|hot)$/.test(temp.tone) ? temp.tone : 'unknown';
    var toneColor = { cool: '#60a5fa', steady: '#38bdf8', watch: '#facc15', hot: '#fb923c', unknown: '#64748b' }[tone];
    var pressureState = { cool: '偏低', steady: '中性', watch: '偏高', hot: '過熱', unknown: '資料不足' };
    var pressureLabels = { volatility: '波動壓力', margin: '融資擁擠', leverage: '槓桿適配', portfolio: '投組曝險' };
    var lights = (temp.components || []).map(function (item) {
      var itemTone = /^(cool|steady|watch|hot)$/.test(item.tone) ? item.tone : 'unknown';
      return '<div class="dc-temp-light" title="' + esc(item.detail || '') + '"><i class="lamp dc-tone-' + itemTone + '" style="background:currentColor"></i>' +
        '<div><div class="k">' + esc(pressureLabels[item.key] || item.label || '—') + '</div><div class="v">' + pressureState[itemTone] +
        (item.score == null ? '' : ' · ' + esc(item.score)) + '</div></div><div class="s">' + esc(item.detail || '') + '</div></div>';
    }).join('');
    var temperature = '<div class="dc-temp"><div class="dc-temp-main"><div class="dc-thermo" aria-hidden="true"><i class="tube"><b style="height:' +
      tempScore + '%;background:' + toneColor + '"></b></i><i class="bulb" style="background:' + toneColor + ';box-shadow:0 0 12px ' + toneColor + '"></i></div>' +
      '<div><div class="k">曝險壓力</div><div class="dc-temp-score">' + (temp.score == null ? '—' : esc(temp.score)) + '<small>/100</small></div>' +
      '<div class="dc-temp-state dc-tone-' + tone + '">' + pressureState[tone] + '</div><div class="dc-temp-help">分數越高，曝險約束應越嚴格；與市場方向無關</div></div></div>' +
      '<div class="dc-temp-lights">' + lights + '</div></div>';
    var flags = (weekly.flags || []).map(function (item) {
      var labels = { short_vol_elevated: '短期波動偏高', margin_elevated: '融資高檔', margin_elevated_and_rising: '融資高檔增加', core_anchor_move: '核心錨偏離' };
      return '<span class="tag medium">' + esc(labels[item] || item) + '</span>';
    }).join('') || '<span class="tag">無監控旗標</span>';
    var assumptions = (((lab.assumptions || {}).core || {}).value) || {};
    var baseFairPe = (((((lab.benchmarks || {}).FTSE_TAIWAN_50 || {}).scenarios || {}).base || {}).fairPe);
    var mechanics = ((lab.productMechanics || {}).rows || []).map(function (item) {
      return '<tr><td><b>' + esc(item.symbol) + '</b><small>' + esc(item.underlyingBenchmarkId || '—') + '</small></td><td>' +
        num(item.targetLeverage, 1) + 'x<small>' + esc(item.resetFrequency || '—') + '</small></td><td>' +
        (item.rollingBeta == null ? '—' : num(item.rollingBeta, 2)) + '</td><td>' +
        (item.trackingResidualAnnualPct == null ? '—' : num(item.trackingResidualAnnualPct, 1) + '%') + '</td><td>' +
        (item.empiricalCostGapAnnualPct == null ? '—' : num(item.empiricalCostGapAnnualPct, 1) + '%') +
        '<small>' + esc(item.quality || '—') + '</small></td><td>' + esc(item.holderMarginCallRisk ? '有' : '無') + '</td></tr>';
    }).join('');
    var validation = lab.externalValidation || {};
    return '<details class="dc-lab" open><summary><span>中長期曝險研究 · Exposure Lab</span><span class="tag">Shadow · 研究上限</span></summary>' +
      temperature + '<details class="dc-lab-detail" open><summary>數據與判定依據</summary>' +
      '<div class="dc-lab-authority"><div><b>月度核心</b><span>' + esc(core.asOf || '—') + ' 建立 · 凍結至 ' + esc(core.frozenUntil || '—') +
        '</span></div><div><b>週度健康</b><span>' + esc(weekly.headline || '監控資料不足') + ' · 只複查、不調倉</span></div><div><b>基準</b><span>' +
        esc(lab.selectedBenchmarkId || '—') + '</span></div></div>' +
      '<div class="dc-lab-grid"><div class="dc-lab-box"><div class="k">台積電財測執行紀錄</div><div class="v">' +
        esc(rel.atOrAboveHighCount || 0) + '/' + esc(rel.observations || 0) + ' 達上緣以上</div><div class="s">上半區 ' +
        num(rel.upperHalfRatePct, 1) + '%；提高情境信心，不把未來假設當必然。</div></div>' +
      '<div class="dc-lab-box"><div class="k">2026 EPS 證據層</div><div class="v">實績 ' + esc(eps.actualQuarters || 0) +
        ' · 財測推導 ' + esc(eps.guidanceDerivedQuarters || 0) + ' · 模型 ' + esc(eps.modelQuarters || 0) +
        '</div><div class="s">Base ' + num(eps.epsBase, 2) + '；Q3/Q4 不標成官方實績。</div></div>' +
      '<div class="dc-lab-box"><div class="k">同基準短期／中長期波動</div><div class="v">' +
        num(stateVol, 1) + '% / ' + num(forecastVol, 1) + '%</div><div class="s">比值 ' + num(vol.stateToForecastRatio, 2) +
        '；' + esc((vol.horizonForecastAnnualPct || {}).methodVersion || '—') + '。</div></div>' +
      '<div class="dc-lab-box"><div class="k">週度健康監控</div><div class="v">' + esc(weekly.headline || '資料不足') +
        '</div><div class="s">' + flags + '<br>融資 ' + num(weekly.marginPercentile52w, 1) + ' 百分位 · 核心錨偏離 ' +
        num(weekly.coreAnchorMovePct, 1) + '%</div></div>' +
      '<div class="dc-lab-box"><div class="k">Risk Profile 對應研究上限</div><div class="v">' +
        (lab.selectedResearchCeilingPct == null ? '未設定' : num(lab.selectedResearchCeilingPct, 1) + '%') + '</div><div class="s">模式 ' +
        esc(lab.riskMode || '—') + (finalRange ? ' · 範圍上限 ' + num(finalRange.upperPct, 1) + '%' : ' · 不輸出最終配置') +
        '</div></div><div class="dc-lab-box"><div class="k">模型治理</div><div class="v">週度擇時未通過外部 OOS</div><div class="s">' +
        esc(validation.status || '—') + ' · ST 重現 ' + esc(validation.stReproduced ? '完成' : '尚未完成') + '</div></div></div>' +
      '<div class="dc-scroll dc-lab-scroll"><table class="dc-lab-table" data-st-sort="off"><tr><th>底層</th><th>TSMC 權重</th><th>模型長期報酬</th><th>中長期波動</th><th>正二效率差 M<br><small>Base；Bear/Bull</small></th><th>狀態</th></tr>' + rows + '</table></div>' +
      '<details class="dc-lab-subdetail" open><summary>模型假設、商品機制與外部驗證</summary>' +
      '<div class="dc-lab-grid"><div class="dc-lab-box"><div class="k">核心假設</div><div class="v">Forward EPS ' + num(assumptions.tsmcForwardEps, 1) +
        ' · 合理 P/E ' + num(baseFairPe, 1) +
        '</div><div class="s">台積電成長／其他成分成長／股息／估值皆為模型假設。</div></div>' +
      '<div class="dc-lab-box"><div class="k">正二增量成本</div><div class="v">' + num(assumptions.incremental2xCostPct, 1) +
        '% / 年</div><div class="s">外部研究複合假設；未拆清前不再疊加 empirical cost gap。</div></div></div>' +
      '<div class="dc-scroll dc-lab-scroll"><table class="dc-lab-table" data-st-sort="off"><tr><th>產品</th><th>目標／重設</th><th>Rolling β</th><th>追蹤殘差</th><th>實證成本缺口</th><th>持有人追繳</th></tr>' +
        mechanics + '</table></div>' +
      '<div class="dc-validation-note"><b>外部樣本外證據</b><span>動態 Kelly CAGR ' + num(validation.dynamicCagrPct, 2) +
        '%；同平均曝險固定配置 ' + num(validation.matchedExposureFixedCagrPct, 2) + '%；差 ' +
        num(validation.differencePctPoint, 2) + 'pp。這只否定受測的週度落後波動策略族，不代表完整基本面核心已通過回測。</span></div></details>' +
      hypotheses.map(function (h) { return '<div class="dc-div warn"><b>' + esc(h.symbol) + ' · ' + esc(h.id) + ' · ' + esc(h.status) +
        '</b><p>' + esc(h.claim) + '<br>' + esc(h.modelTreatment) + '<br>確認：' + esc(h.confirmationRule) + '<br>失效：' + esc(h.invalidationRule) + '</p></div>'; }).join('') +
      '<div class="dc-note">0050 是大型權值／科技高度集中工具，不標示為純 AI ETF。正二效率差為正只代表模型複利效率，不是買進或加碼訊號；研究上限不是配置目標。</div></details></details>';
  }

  function riskFormHtml(ctx) {
    var fields = [
      ['baseGrossExposure', '基準總曝險 %', 'number'], ['maxGrossExposure', '最大總曝險 %', 'number'],
      ['maxLeverage', '最大槓桿倍數', 'number'], ['maxSingleNameWeight', '單一持倉上限 %', 'number'],
      ['maxSectorWeight', '產業上限 %', 'number'], ['maxPortfolioBeta', 'Portfolio Beta 上限', 'number'],
      ['maxDailyVaR', '單日 VaR 上限 %', 'number'], ['investmentHorizon', '投資週期', 'text']
    ];
    var envelope = ctx.actionEnvelope || {};
    var range = envelope.positionRange;
    var constraints = envelope.constraints || [];
    return '<details open><summary>Risk Profile（八欄完整才會產生倉位範圍）</summary><div class="dc-risk-grid">' +
      fields.map(function (f) { return '<label>' + esc(f[1]) + '<input data-risk="' + f[0] + '" type="' + f[2] +
        '" value="' + esc(riskDraft[f[0]] || '') + '"></label>'; }).join('') + '</div>' +
      '<div style="display:flex;gap:6px;align-items:center;margin-top:7px"><button class="dc-btn primary" id="dc-risk-apply">套用透明公式</button>' +
      '<span class="dc-note" id="dc-risk-status">不儲存、不交給 AI</span></div></details>' +
      (range ? '<div class="dc-feature" style="margin-top:7px"><div class="k">計算後總曝險區間</div><div class="v">' +
        num(range.lowerPct, 1) + '% — ' + num(range.upperPct, 1) + '%</div><div class="s">target ' + num(range.targetPct, 1) +
        '% · cap ' + num(range.capPct, 1) + '% · ' + esc(range.formula) + '</div></div>' : '') +
      (constraints.length ? '<div class="dc-note" style="margin-top:6px">限制條件：' +
        esc(constraints.map(constraintLabel).join('；')) + '</div>' : '');
  }

  function mandatoryControlsHtml(envelope) {
    var rows = (envelope && envelope.mandatoryControls) || [];
    if (!rows.length) return '';
    return '<div class="dc-mandatory" aria-label="強制風控紅燈">' + rows.map(function (row) {
      return '<div class="dc-stop"><i class="lamp">!</i><div><b>' + esc(label(row.action || row.id)) +
        ' · 強制限制</b><br><span>' + esc(row.reason || '') + '</span></div></div>';
    }).join('') + '</div>';
  }

  function actionSummaryHtml(envelope) {
    envelope = envelope || {};
    return '<div class="dc-action-summary" aria-label="決策動作邊界">' +
      '<div class="dc-action-cell"><i>✓</i><div><b>允許</b><span>' + esc(listLabels(envelope.allowed)) + '</span></div></div>' +
      '<div class="dc-action-cell limit"><i>△</i><div><b>限制</b><span>' + esc(listLabels(envelope.restricted)) + '</span></div></div>' +
      '<div class="dc-action-cell stop"><i>×</i><div><b>禁止</b><span>' + esc(listLabels(envelope.prohibited)) + '</span></div></div></div>';
  }

  function warningStateLabel(value) {
    return ({
      OBSERVATION: '觀測', WATCH: '注意', ARMED: '戒備', CONFIRMED: '確認', ACTIVE: '生效',
      CONFLICT: '衝突', RECOVERY: '回復觀察', INVALIDATED: '失效', EXPIRED: '逾期'
    })[value] || String(value || '等待資料');
  }

  function warningSignalHtml(signal, direction) {
    signal = signal || {};
    var strength = Math.max(0, Math.min(100, Number(signal.strength) || 0));
    var reasons = (signal.reasons || []).slice(0, 3);
    if (!reasons.length) reasons = ['尚未累積足夠的獨立來源'];
    return '<div class="dc-warning-signal ' + direction + '" data-dc-highlight="' + esc(signal.signalId || '') + '">' +
      '<div class="dc-warning-ring" style="--p:' + strength.toFixed(0) + '%"><div><strong>' + strength.toFixed(0) +
        '</strong><small>/100</small></div></div><div class="dc-warning-copy"><div class="dc-warning-title"><b>' +
        esc(signal.label || (direction === 'upside' ? '台股強攻蓄勢' : '台股下跌前兆')) + '</b><span class="dc-warning-state">' +
        esc(warningStateLabel(signal.state)) + '</span></div><ul class="dc-warning-reasons">' + reasons.map(function (row) {
          return '<li>' + esc(row) + '</li>';
        }).join('') + '</ul><div class="dc-warning-rule">確認：' + esc(signal.confirmation || '等待現貨與廣度同向') +
        '<br>失效：' + esc(signal.invalidation || '訊號轉弱或核心方向反轉') + '</div></div></div>';
  }

  function prospectiveValidationHtml(warning) {
    var validation = (warning && warning.prospectiveValidation) || {};
    var status = String(validation.status || 'empty');
    var rows = validation.horizons || [];
    var minimum = Number(validation.minimumSampleForRates) || 20;
    if (status === 'unavailable') {
      return '<div class="dc-warning-validation"><div class="dc-warning-validation-head"><b>前瞻驗證暫時不可用</b>' +
        '<span>不影響目前訊號觀測</span></div><div class="dc-warning-validation-note">帳本錯誤已隔離；不以缺失結果補成命中率。</div></div>';
    }
    var cells = [1, 3, 5].map(function (sessions) {
      var row = rows.find(function (item) { return Number(item.sessions) === sessions; }) || {};
      var resolved = Number(row.resolvedCount) || 0;
      var ready = !!row.ratesAvailable;
      var value = ready ? num(row.directionHitRatePct, 1) + '%' : resolved + '/' + minimum;
      var detail = ready
        ? '歷史方向命中 · 實質波動 ' + num(row.materialMoveHitRatePct, 1) + '%'
        : '已完成樣本／最低門檻';
      return '<div class="dc-warning-validation-cell"><div class="k">' + sessions + ' 日驗證</div><div class="v">' +
        esc(value) + '</div><div class="s">' + esc(detail) + '</div></div>';
    }).join('');
    var headline = status === 'ready' ? '前瞻實證（歷史樣本）' : '前瞻驗證建置中';
    return '<div class="dc-warning-validation"><div class="dc-warning-validation-head"><b>' + headline + '</b><span>試驗 ' +
      esc(String(validation.totalTrials || 0)) + ' · 結果 ' + esc(String(validation.resolvedOutcomes || 0)) +
      ' · 覆蓋 ' + num(validation.coveragePct, 1) + '%</span></div><div class="dc-warning-validation-grid">' + cells +
      '</div><div class="dc-warning-validation-note">只從首次觀測後開始記錄，不回填歷史；這是歷史實證，不是未來機率，也不取得下單權限。</div></div>';
  }

  function earlyWarningHtml(ctx) {
    var warning = ctx.earlyWarnings || {};
    var signals = warning.signals || [];
    if (!warning.ok && !signals.length) {
      return '<div class="dc-card dc-warning-card" id="dc-section-precursors" data-dc-section="precursors"><h3><span>跨市場前兆雷達</span><span>SHADOW</span></h3>' +
        '<div class="dc-note">核心來源尚未齊備；系統不會用新聞或單一股票補成方向訊號。</div></div>';
    }
    function find(id) { return signals.find(function (row) { return row.signalId === id; }) || {}; }
    var down = find('TW_DOWNSIDE_PRECURSOR'), up = find('TW_ATTACK_BUILDUP');
    var components = [find('AI_WAFER_DOUBLE_ARROW'), find('MEMORY_CYCLE_RESONANCE')];
    return '<div class="dc-card dc-warning-card" id="dc-section-precursors" data-dc-section="precursors"><h3 class="dc-warning-head"><span>跨市場前兆雷達</span>' +
      '<span>觀測 → 注意 → 戒備 → 確認 → 生效</span><span class="tag">SHADOW · 非下單訊號</span></h3>' +
      '<div class="dc-warning-grid">' + warningSignalHtml(down, 'downside') + warningSignalHtml(up, 'upside') + '</div>' +
      '<div class="dc-warning-components">' + components.map(function (row) {
        var cls = row.direction === 'mixed' ? ' mixed' : '';
        return '<span class="dc-warning-component' + cls + '" data-dc-highlight="' + esc(row.signalId || '') + '"><b>' + esc(row.label || row.signalId || '核心連動') + '</b>' +
          esc(warningStateLabel(row.state)) + ' · ' + num(row.strength, 0) + '</span>';
      }).join('') + '</div>' + prospectiveValidationHtml(warning) + '<div class="dc-warning-foot"><span>獨立來源 ' +
        esc(String(((warning.dataQuality || {}).availableDomains) || 0)) + '/5 · 證據品質 ' + pct01(warning.evidenceQuality) +
        '</span><span>訊號強度不是機率 · AI 不參與觸發 · ' + esc(String(warning.asOf || '—').replace('T', ' ').slice(0, 19)) +
        '</span></div></div>';
  }

  function newsHtml(ctx) {
    var rows = ctx.newsImpact || [];
    if (!rows.length) return '<div class="dc-note">目前沒有帶入已標記的重大訊息。</div>';
    var linkage = (window.MarketIntelV5 && typeof window.MarketIntelV5.linkNewsToWatchlist === 'function')
      ? window.MarketIntelV5.linkNewsToWatchlist(rows, decisionWatchlist()) : { byNews: {} };
    return rows.slice(0, 8).map(function (r, index) {
      var im = r.impact || {}, cls = String(im.tier || '').toLowerCase();
      var linked = linkage.byNews[index] || [];
      var chips = linked.length ? '<div class="dc-news-links"><span>✦ 自選聯動</span>' + linked.slice(0, 8).map(function (x) {
        return '<button type="button" class="dc-news-watch" data-news-watch="' + esc(x.symbol) + '" data-news-market="' +
          esc(x.market || 'TW') + '" title="' + esc((x.match === 'direct' ? '新聞直接點名' : (x.theme || '同主題') + '供應鏈聯動') +
          ' · ' + x.tier) + '">' + esc(x.symbol) + '</button>';
      }).join('') + '</div>' : '';
      return '<div class="dc-div' + (linked.length ? ' news-linked' : '') + '"><b><span class="tag ' + cls + '">' + esc(im.tier || 'LOW') + '</span>' +
        esc(r.code || r.mkt || '') + ' ' + esc(r.title || '') + '</b><p>' + esc(im.reason || '') +
        ' · ' + esc((im.scope || []).join(' / ')) + ' · direction 不由規則臆測</p>' + chips + '</div>';
    }).join('');
  }

  function bindNewsLinks() {
    document.querySelectorAll('#dc-root [data-news-watch]').forEach(function (el) {
      el.onclick = function () {
        var symbol = el.getAttribute('data-news-watch');
        var market = el.getAttribute('data-news-market') || 'TW';
        if (window.ShellV5 && typeof window.ShellV5.openChart === 'function') {
          window.ShellV5.openChart(symbol, market);
        }
      };
    });
  }

  function applyPendingFocus() {
    if (!pendingFocus) return;
    var section = String(pendingFocus.focusSection || 'summary');
    var highlight = String(pendingFocus.highlightId || '');
    var target = null;
    if (highlight) {
      Array.prototype.some.call(document.querySelectorAll('#dc-root [data-dc-highlight]'), function (node) {
        if (node.getAttribute('data-dc-highlight') === highlight) { target = node; return true; }
        return false;
      });
    }
    if (!target) target = $('dc-section-' + section) || $('dc-section-summary');
    if (!target) return;
    var details = target.closest && target.closest('details');
    if (details) details.open = true;
    document.querySelectorAll('#dc-root .dc-focus').forEach(function (node) { node.classList.remove('dc-focus'); });
    target.classList.add('dc-focus');
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    var behavior = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    setTimeout(function () {
      try { target.scrollIntoView({ behavior: behavior, block: 'center', inline: 'nearest' }); } catch (e) {}
      try { target.focus({ preventScroll: true }); } catch (eFocus) {}
    }, 80);
    setTimeout(function () { target.classList.remove('dc-focus'); }, 3600);
    pendingFocus = null;
  }

  function render(ctx) {
    var body = ensureMount();
    if (!body || !ctx) return;
    lastContext = ctx;
    lastEvidenceContext = contextWithResearchEvidence(ctx);
    var r = ctx.regime || {}, q = ctx.dataQuality || {}, a = ctx.actionEnvelope || {};
    var sub = $('dc-sub');
    if (sub) sub.textContent = (ctx.model || 'DecisionContext') + ' · asOf ' + (ctx.asOf || '—') +
      ' · contract ' + (ctx.contractVersion || 1);
    var sc = ctx.scenario || {};
    body.innerHTML =
      '<details class="dc-command-fold" open><summary id="dc-section-summary" data-dc-section="summary"><span class="name">決策摘要</span><span class="brief">' +
        esc(r.label || r.id || '等待市場狀態') + ' · ' + esc(label(a.posture)) +
        '</span></summary><div class="dc-command"><div class="box regime"><div class="k">市場狀態</div><div class="v">' + esc(r.id || '—') +
        '</div><div class="s">' + esc(r.label || '') + ' · 信心 ' + pct01(r.confidence) + ' · 資料 ' + pct01(q.completeness) + '</div></div>' +
      '<div class="box"><div class="k">可採取範圍</div><div class="v">' + esc(label(a.posture)) + '</div><div class="s">允許：' +
        esc(listLabels(a.allowed)) + '<br>限制：' + esc(listLabels(a.restricted)) + '</div></div>' +
      '<div class="box"><div class="k">確認／失效條件</div><div class="v" style="font-size:11px">' + esc((ctx.confirmation || [])[0] || '等待證據') +
        '</div><div class="s">失效：' + esc((ctx.invalidation || [])[0] || '—') + '</div></div></div></details>' +
      earlyWarningHtml(ctx) +
      '<div class="dc-grid"><div>' +
        '<div class="dc-card"><h3><span>情境訊號矩陣</span><span>負向 -1 · 中性 0 · 正向 +1</span></h3><div class="dc-scenario">' +
          featureHtml('趨勢', sc.trend) + featureHtml('廣度', sc.breadth) + featureHtml('資金', sc.flow) +
          featureHtml('產業', sc.sector) + featureHtml('國際科技', sc.global) + featureHtml('風險負擔', sc.risk) + '</div></div>' +
        '<div class="dc-card"><h3><span>Key Levels & Realized Volatility</span><span>' + esc((ctx.keyLevels || {}).source || '—') + '</span></h3>' + levelsHtml(ctx) + '</div>' +
        '<div class="dc-card" id="dc-section-options" data-dc-section="options">' + optionsStructureHtml(ctx) + '</div>' +
        '<div class="dc-card" id="dc-section-divergences" data-dc-section="divergences"><h3><span>廣度趨勢與具名背離</span><span>' + (ctx.divergences || []).length + '</span></h3>' +
          breadthTrendHtml(ctx) + '<div style="margin-top:6px">' + divergencesHtml(ctx) + '</div></div>' +
        '<div class="dc-card"><h3><span>產業資金流／參與</span><span>' + esc((ctx.sectorFlow || {}).mode || '—') + '</span></h3>' + sectorHtml(ctx) + '</div>' +
        '<div class="dc-card">' + sessionMomentumHtml(ctx) + '</div>' +
      '</div><div>' +
        '<div class="dc-card" id="dc-section-action" data-dc-section="action"><h3><span>Action Envelope</span><span>不是下單訊號</span></h3>' +
          mandatoryControlsHtml(a) + actionSummaryHtml(a) + '<div style="margin-top:7px">' + riskFormHtml(ctx) + '</div></div>' +
        '<div class="dc-card" id="dc-section-exposure" data-dc-section="exposure">' + exposureLabHtml(ctx) + '</div>' +
        '<div class="dc-card"><h3 class="dc-portfolio-head"><span>Portfolio Overlay</span>' + portfolioSwitchHtml() +
          '</h3>' + portfolioHtml(ctx) + '</div>' +
        '<div class="dc-card" id="dc-section-evidence" data-dc-section="evidence"><h3><span>Evidence Ledger · 證據帳本</span><span>' + (lastEvidenceContext.evidence || []).length + ' 筆 · 原始值未改寫</span></h3>' + evidenceHtml(lastEvidenceContext) + '</div>' +
        '<div class="dc-card"><h3><span>News Impact</span><span>deterministic tag</span></h3>' + newsHtml(ctx) + '</div>' +
        '<div class="dc-card"><h3><span>Regime History</span><span id="dc-hist-meta">載入中</span></h3><div id="dc-history" class="dc-note">—</div></div>' +
        '<div class="dc-card" id="dc-ai-card" style="display:none"><h3><span>AI Explanation</span><span>唯讀解釋</span></h3><div id="dc-ai-body" class="dc-ai"></div></div>' +
      '</div></div><div class="dc-note">Decision support only · AI 不得覆寫 regime、confidence、key levels 或倉位公式。</div>';
    restoreAiDisplay();
    bindRisk();
    bindEvidenceLedger();
    bindNewsLinks();
    bindOptionsLab();
    bindSessionMomentumLab();
    loadHistory();
    applyPendingFocus();
  }

  function bindRisk() {
    document.querySelectorAll('#dc-root [data-risk]').forEach(function (el) {
      el.oninput = function () { riskDraft[el.getAttribute('data-risk')] = el.value; };
    });
    var btn = $('dc-risk-apply');
    if (btn) btn.onclick = function () {
      var keys = ['baseGrossExposure', 'maxGrossExposure', 'maxLeverage', 'maxSingleNameWeight', 'maxSectorWeight', 'maxPortfolioBeta', 'maxDailyVaR', 'investmentHorizon'];
      var missing = keys.filter(function (k) { return riskDraft[k] == null || riskDraft[k] === ''; });
      var st = $('dc-risk-status');
      if (missing.length) { if (st) st.textContent = '尚缺 ' + missing.length + ' 欄；不輸出倉位百分比'; return; }
      if (st) st.textContent = '計算中…';
      load(true, riskDraft);
    };
  }

  function loadHistory() {
    fetch(SRV + '/decision/history?n=12', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var box = $('dc-history'), meta = $('dc-hist-meta');
        if (!box) return;
        var rows = (d && d.rows) || [];
        if (meta) meta.textContent = rows.length + ' 筆';
        box.innerHTML = rows.length ? rows.map(function (x) {
          return '<span class="tag">' + esc(String(x.asOf || '').replace('T', ' ').slice(5, 16)) + ' ' + esc(x.regime) + '</span>';
        }).join('') : '歷史尚在累積。';
      }).catch(function () {});
  }

  function load(force, riskProfile) {
    var body = ensureMount();
    if (!body) return;
    lastHoldings = portfolioMode === 'observation_pool' ? holdingsFromWatch() : holdingsFromPositions();
    if (!lastContext) body.innerHTML = '<div class="dc-card">決策資料載入中…</div>';
    var opts = { force: !!force, holdings: lastHoldings, portfolioKind: portfolioMode };
    if (riskProfile) opts.riskProfile = riskProfile;
    if (window.DecisionData && DecisionData.refresh) {
      DecisionData.refresh(opts).then(function (st) {
        var ctx = st && st.context;
        if (ctx) render(ctx);
        else if (!lastContext) showEmpty(
          'DecisionContext 尚未形成',
          '直接按下方按鈕即可更新市場資料，不必先切換頁面。'
        );
      });
    }
  }

  function runAi() {
    if (aiBusy) return;
    if (aiAccessRole === 'unknown') {
      resolveAiAccess().then(function (role) {
        if (role === 'owner') runAi();
        else if (role === 'reader') syncAiButtonState();
        else setAiDisplay('目前無法確認 Private Web 權限，請檢查連線後再試。', true);
      });
      return;
    }
    if (aiAccessRole !== 'owner') {
      setAiDisplay('此登入帳號為 Reader；AI 解釋會使用 EVO-T1 運算資源，目前僅 Owner 可執行。', true);
      return;
    }
    if (!lastContext) {
      showEmpty('AI 解釋尚無可用資料', '請先按「更新市場資料」，建立 DecisionContext 後再執行 AI 解釋。');
      return;
    }
    aiBusy = true;
    syncAiButtonState();
    setAiDisplay('EVO-T1 正在準備本機快速模型。請預留約 8 分鐘；此時間已包含冷啟動、模型載入、上下文預填與推理，通常會提早完成。最長等待 12 分鐘。', false);
    aiController = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeoutId = aiController ? setTimeout(function () { aiController.abort(); }, AI_TIMEOUT_MS) : null;
    var slim = {
      regime: lastContext.regime, actionEnvelope: lastContext.actionEnvelope,
      divergences: lastContext.divergences, confirmation: lastContext.confirmation,
      invalidation: lastContext.invalidation, evidence: (lastContext.evidence || []).slice(0, 12)
    };
    var contextKey = JSON.stringify(slim);
    var localRequestId = window.DecisionData && DecisionData.correlationId
      ? DecisionData.correlationId('decision-ai')
      : 'decision-ai-' + Date.now().toString(36);
    var prompt = '請以 5–8 句繁中解釋既有 DecisionContext，先說支持證據，再提出最強反方觀點、衝突與失效條件；引用 evidence id。' +
      '不得改寫 regime、confidence、價格關卡或倉位數字，不得創造未提供的資料，結尾加「⚠ 非投資建議」。';
    fetch(SRV + '/ai/local', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ST-Trace-ID': localRequestId },
      body: JSON.stringify({ prompt: prompt, context: JSON.stringify(slim) }),
      credentials: 'same-origin', signal: aiController ? aiController.signal : undefined
    }).then(function (response) {
      var requestId = response.headers.get('X-ST-AI-Request-ID') || response.headers.get('X-ST-Trace-ID') || localRequestId;
      return response.text().then(function (text) {
        if (!response.ok) {
          var httpError = new Error('HTTP ' + response.status);
          httpError.status = response.status;
          httpError.detail = text;
          httpError.requestId = requestId;
          throw httpError;
        }
        var answer = String(text || '').trim();
        if (!answer) {
          var emptyError = new Error('empty AI response');
          emptyError.detail = '模型完成推理但沒有輸出可見正文，請重試。';
          emptyError.requestId = requestId;
          throw emptyError;
        }
        var runtimeFailure = aiRuntimeFailureDetail(answer);
        if (runtimeFailure) {
          var streamError = new Error('AI stream failure');
          streamError.detail = runtimeFailure;
          streamError.requestId = requestId;
          throw streamError;
        }
        var currentSlim = lastContext ? {
          regime: lastContext.regime, actionEnvelope: lastContext.actionEnvelope,
          divergences: lastContext.divergences, confirmation: lastContext.confirmation,
          invalidation: lastContext.invalidation, evidence: (lastContext.evidence || []).slice(0, 12)
        } : null;
        if (!currentSlim || JSON.stringify(currentSlim) !== contextKey) {
          setAiDisplay('市場資料已在分析期間更新；為避免舊解釋對應新畫面，本次結果已丟棄，請重新執行 AI 解釋。\n\n請求編號：' + requestId, true);
          return;
        }
        var suffix = requestId ? '\n\n請求編號：' + requestId : '';
        setAiDisplay(answer + suffix, false);
      });
    }).catch(function (error) {
      setAiDisplay(aiErrorMessage(error, localRequestId), true);
    }).then(function () {
      if (timeoutId) clearTimeout(timeoutId);
      aiController = null;
      aiBusy = false;
      syncAiButtonState();
    });
  }

  function activate(opts) {
    if (opts && (opts.focusSection || opts.highlightId)) pendingFocus = opts;
    ensureMount();
    resolveAiAccess();
    load(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && ShellV5.route && ShellV5.route() === 'decision') load(false);
    }, 60000);
  }
  function deactivate() { if (timer) { clearInterval(timer); timer = null; } }

  window.DecisionV5 = {
    activate: activate,
    deactivate: deactivate,
    refresh: load,
    refreshMarketData: refreshMarketData,
    setPortfolioMode: setPortfolioMode
  };
  window.addEventListener('decisionData', function (ev) {
    var ctx = ev && ev.detail && ev.detail.state && ev.detail.state.context;
    if (ctx && window.ShellV5 && ShellV5.route && ShellV5.route() === 'decision') render(ctx);
  });
  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'decision') activate(ev.detail.opts || {});
  });
}());
