/* ============================================================================
 * wavedeck_bridge_v5.js — Stock Terminal → WaveDeck 入口與宏觀覆寫
 * ----------------------------------------------------------------------------
 * - 側欄「執行」→ open()
 * - syncFromMarket({score, advRatio, rotationHealth, spilloverProb, …})
 *   → POST /bridge/st（節流／去重；輪動／外溢寫入 meta）
 * - WD→ST→Browser：SSE /bridge/wavedeck/stream（FULL_SYNC／POSITION_STATE_CHANGE）
 *   取代 Watch／Book 對 WD 的 REST 輪詢；chip 以 symbol 字典原子更新
 * - fetchCostMeter / lastWdReport ← ST GET /bridge/wavedeck（REST 後援）
 * - styleFromScore：廣度＋體質＋輪動＋外溢 → 進場風格 35–65
 * 鐵律：失敗僅 toast／console，不阻斷 ST 主流程。
 * ========================================================================== */
(function () {
  'use strict';

  var PRIVATE_WEB_NO_WD = !!(window.ST_PRIVATE_WEB_PROFILE &&
    window.ST_PRIVATE_WEB_PROFILE.wavedeck === false);

  var DEFAULT_URL = 'http://127.0.0.1:18433/';
  var ST_URL = (typeof window.SERVER === 'string' && window.SERVER)
    ? String(window.SERVER).replace(/\/?$/, '')
    : '';
  function isReservedPrivateWebUrl(value) {
    try {
      var parsed = new URL(String(value), window.location.href);
      var loopback = parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost';
      return loopback && (parsed.port === '18434' || parsed.port === '18435');
    } catch (e) {
      return false;
    }
  }
  var CANDIDATES = [
    'http://127.0.0.1:18433/',
    'http://127.0.0.1:18765/',
    'http://127.0.0.1:28765/',
    'http://127.0.0.1:38433/',
    'http://127.0.0.1:8765/'
  ];
  var configuredBase = (typeof window.WAVEDECK_URL === 'string' && window.WAVEDECK_URL)
    ? String(window.WAVEDECK_URL)
    : '';
  if (isReservedPrivateWebUrl(configuredBase)) configuredBase = '';
  var BASE = configuredBase
    ? configuredBase.replace(/\/?$/, '/')
    : DEFAULT_URL;

  var AUTO_KEY = 'st5.wd.autoOverlay';
  /* Same-key heartbeat：至少每 45s 重送一次，避免 WD overlay 因節流超過 90s 過期 */
  var HEARTBEAT_MS = 45000;
  var MIN_INTERVAL_MS = 12000;
  var _lastKey = '';
  var _lastAt = 0;
  var _lastPayload = null;
  var _resolving = null;
  var _costCache = null;
  var _costAt = 0;
  var COST_TTL_MS = 10000;
  var _hbTimer = null;

  function toast(msg) {
    if (typeof window.notifyToast === 'function') {
      try { window.notifyToast(String(msg)); return; } catch (e) {}
    }
    try { console.log('[WaveDeck]', msg); } catch (e2) {}
  }

  function autoEnabled() {
    try {
      var v = localStorage.getItem(AUTO_KEY);
      if (v === null || v === undefined || v === '') return true;
      return v === '1' || v === 'true';
    } catch (e) {
      return true;
    }
  }

  function setAutoEnabled(on) {
    try { localStorage.setItem(AUTO_KEY, on ? '1' : '0'); } catch (e) {}
  }

  /**
   * Map ST market score + breadth + rotation/spillover → WaveDeck style.
   * @param {number} score
   * @param {number} advRatio
   * @param {{rotationHealth?:string, spilloverProb?:number}|number} [optsOrSpill]
   */
  function styleFromScore(score, advRatio, optsOrSpill) {
    var opts = {};
    if (optsOrSpill != null && typeof optsOrSpill === 'object') opts = optsOrSpill;
    else if (optsOrSpill != null && isFinite(Number(optsOrSpill))) {
      opts = { spilloverProb: Number(optsOrSpill) };
    }
    var s = Number(score);
    var adv = Number(advRatio);
    if (!isFinite(s)) s = 50;
    var hint = 50;
    if (s >= 70) hint = 65;
    else if (s >= 55) hint = 55;
    else if (s >= 45) hint = 50;
    else if (s >= 30) hint = 40;
    else hint = 35;
    if (isFinite(adv)) {
      if (adv < 0.35) hint = Math.min(hint, 40);
      if (adv > 0.65) hint = Math.max(hint, 55);
    }
    var rot = opts.rotationHealth || opts.rotation || null;
    if (rot === 'broad') hint = Math.min(90, hint + 5);
    if (rot === 'narrow') hint = Math.max(20, hint - 5);
    var spill = Number(opts.spilloverProb);
    if (isFinite(spill)) {
      if (spill < 0.35) hint = Math.min(hint, 40);
      else if (spill > 0.65) hint = Math.max(hint, Math.min(65, hint + 5));
    }
    return Math.max(20, Math.min(90, Math.round(hint)));
  }

  /** Sector rotation + leaders → spillover probability in [0.05, 0.95]. */
  function spilloverFromRotation(rotationHealth, sectorPack) {
    var rot = rotationHealth || 'mixed';
    var up = (sectorPack && sectorPack.up) || [];
    var dn = (sectorPack && sectorPack.dn) || [];
    var upN = up.length;
    var dnN = dn.length;
    var total = upN + dnN;
    var base = rot === 'broad' ? 0.72 : rot === 'narrow' ? 0.30 : 0.50;
    var breadth = total ? (upN / total) : (rot === 'broad' ? 0.6 : rot === 'narrow' ? 0.35 : 0.5);
    var spill = 0.55 * base + 0.45 * breadth;
    // Concentration penalty: only 1–2 leaders → harder for gains to spill
    if (upN > 0 && upN <= 2) spill -= 0.08;
    if (upN >= 5) spill += 0.06;
    return Math.max(0.05, Math.min(0.95, Math.round(spill * 100) / 100));
  }

  /**
   * AI 供應鏈節點動能 → 外溢機率（沿鏈相鄰同向＝動能可擴散）。
   * @param {Array<{stage?:string,n?:number,mom5?:number,mom20?:number,accel?:number,leaders?:Array}>} stages
   * @returns {{prob:number, hotStage:?string, leaders:string[], breadth:number, contig:number}}
   */
  function spilloverFromChainStages(stages) {
    stages = Array.isArray(stages) ? stages : [];
    var withData = stages.filter(function (s) {
      return s && Number(s.n) > 0 && s.mom5 != null && isFinite(Number(s.mom5));
    });
    if (!withData.length) {
      return { prob: 0.45, hotStage: null, leaders: [], breadth: 0, contig: 0 };
    }
    var up = withData.filter(function (s) { return Number(s.mom5) > 0; });
    var breadth = up.length / withData.length;
    var contigPairs = 0;
    var contigPossible = 0;
    for (var i = 0; i < stages.length - 1; i++) {
      var a = stages[i];
      var b = stages[i + 1];
      if (!a || !b || !a.n || !b.n || a.mom5 == null || b.mom5 == null) continue;
      if (!isFinite(Number(a.mom5)) || !isFinite(Number(b.mom5))) continue;
      contigPossible++;
      if (Number(a.mom5) > 0 && Number(b.mom5) > 0) contigPairs++;
    }
    var contig = contigPossible ? contigPairs / contigPossible : 0;
    var inflow = withData.filter(function (s) {
      var accel = s.accel;
      if (accel == null && s.mom5 != null && s.mom20 != null) {
        accel = Number(s.mom5) - Number(s.mom20);
      }
      return accel != null && isFinite(Number(accel)) && Number(accel) > 0.05;
    }).length;
    var inflowRatio = inflow / withData.length;
    var hot = withData.slice().sort(function (x, y) {
      var mx = Number(x.mom20 != null ? x.mom20 : x.mom5);
      var my = Number(y.mom20 != null ? y.mom20 : y.mom5);
      return my - mx;
    })[0];
    var leaders = [];
    if (hot && Array.isArray(hot.leaders)) {
      leaders = hot.leaders.map(function (l) {
        return (l && (l.name || l.code)) || '';
      }).filter(Boolean).slice(0, 4);
    }
    // 廣度 40% + 相鄰同向 35% + 加速流入 25%
    var prob = 0.40 * breadth + 0.35 * contig + 0.25 * Math.min(1, inflowRatio * 2);
    prob = Math.max(0.05, Math.min(0.95, Math.round(prob * 100) / 100));
    return {
      prob: prob,
      hotStage: hot && hot.stage ? String(hot.stage) : null,
      leaders: leaders,
      breadth: Math.round(breadth * 100) / 100,
      contig: Math.round(contig * 100) / 100
    };
  }

  /** Blend sector spillover with supply-chain spillover (chain weighted higher when present). */
  function blendSpillover(sectorProb, chainResult) {
    var s = Number(sectorProb);
    var c = chainResult && isFinite(Number(chainResult.prob)) ? Number(chainResult.prob) : null;
    if (!isFinite(s) && c == null) return null;
    if (c == null) return Math.max(0.05, Math.min(0.95, Math.round(s * 100) / 100));
    if (!isFinite(s)) return c;
    return Math.max(0.05, Math.min(0.95, Math.round((0.60 * c + 0.40 * s) * 100) / 100));
  }

  function buildNote(ctx, style, delever) {
    var bits = ['ST 宏觀覆寫'];
    if (ctx.score != null && isFinite(Number(ctx.score))) {
      bits.push('體質 ' + Math.round(Number(ctx.score)));
    }
    if (ctx.label) bits.push(String(ctx.label));
    if (ctx.advRatio != null && isFinite(Number(ctx.advRatio))) {
      bits.push('廣度 ' + Math.round(Number(ctx.advRatio) * 100) + '%');
    }
    if (ctx.rotationHealth) bits.push('輪動 ' + ctx.rotationHealth);
    if (ctx.spilloverProb != null && isFinite(Number(ctx.spilloverProb))) {
      bits.push('外溢 ' + Math.round(Number(ctx.spilloverProb) * 100) + '%');
    }
    bits.push('風格→' + style);
    if (delever) bits.push('降載');
    if (ctx.summary) bits.push(String(ctx.summary).slice(0, 60));
    if (ctx.decisionRegime) bits.push('Regime ' + String(ctx.decisionRegime));
    return bits.join(' · ');
  }

  function probeUrl(url) {
    if (PRIVATE_WEB_NO_WD) return Promise.resolve(null);
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, 700);
    return fetch(String(url).replace(/\/?$/, '') + '/health', {
      signal: ctrl && ctrl.signal,
      cache: 'no-store'
    }).then(function (r) {
      clearTimeout(t);
      return r.ok ? r.json() : Promise.reject();
    }).then(function (j) {
      if (j && j.ok) return String(url).replace(/\/?$/, '/');
      return Promise.reject();
    }).catch(function () {
      clearTimeout(t);
      return null;
    });
  }

  function ensureBase() {
    if (PRIVATE_WEB_NO_WD) return Promise.resolve(null);
    if (_resolving) return _resolving;
    _resolving = probeUrl(BASE).then(function (ok) {
      if (ok) return BASE;
      var list = CANDIDATES.filter(function (u) { return u !== BASE; });
      var i = 0;
      function next() {
        if (i >= list.length) return null;
        return probeUrl(list[i++]).then(function (hit) {
          if (hit) {
            BASE = hit;
            return BASE;
          }
          return next();
        });
      }
      return next();
    }).finally(function () { _resolving = null; });
    return _resolving;
  }

  function open(url) {
    if (PRIVATE_WEB_NO_WD) return;
    if (url) {
      if (isReservedPrivateWebUrl(url)) {
        toast('WaveDeck 網址使用 Private Web 保留埠，已拒絕開啟');
        return;
      }
      window.open(url, '_blank', 'noopener');
      toast('已開啟 WaveDeck');
      return;
    }
    ensureBase().then(function (base) {
      var target = base || BASE;
      window.open(target, '_blank', 'noopener');
      toast(base ? ('已開啟 WaveDeck · ' + target) : '已開啟 WaveDeck（若空白請先 START_WAVEDECK）');
    });
  }

  function pushOverlay(payload) {
    var body = payload || {};
    return ensureBase().then(function (base) {
      if (!base) throw new Error('WaveDeck 未連線（:18433）');
      return fetch(base.replace(/\/$/, '') + '/bridge/st', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store'
      });
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || j.ok === false) throw new Error((j && j.error) || r.statusText);
        return j;
      });
    });
  }

  /**
   * Sync ST macro → WaveDeck overlay.
   * @param {{score?:number, advRatio?:number, label?:string, summary?:string,
   *   rotationHealth?:string, spilloverProb?:number, leaders?:string[],
   *   force?:boolean, silent?:boolean, source?:string}} ctx
   */
  function syncFromMarket(ctx) {
    if (PRIVATE_WEB_NO_WD) {
      return Promise.resolve({ skipped: true, reason: 'private-web-disabled' });
    }
    ctx = ctx || {};
    if (!ctx.force && !autoEnabled()) {
      return Promise.resolve({ skipped: true, reason: 'auto-off' });
    }
    var score = ctx.score;
    var adv = ctx.advRatio;
    if (score == null && (adv == null || !isFinite(Number(adv)))) {
      return Promise.resolve({ skipped: true, reason: 'no-data' });
    }
    var rot = ctx.rotationHealth || ctx.rotation || null;
    var spill = ctx.spilloverProb;
    if (spill == null && ctx.sectors) {
      spill = spilloverFromRotation(rot, ctx.sectors);
    }
    var style = styleFromScore(score, adv, { rotationHealth: rot, spilloverProb: spill });
    var delever = isFinite(Number(score)) && Number(score) < 35;
    if (isFinite(Number(spill)) && Number(spill) < 0.30) delever = true;
    var note = buildNote(Object.assign({}, ctx, { rotationHealth: rot, spilloverProb: spill }), style, delever);
    var key = style + '|' + (delever ? 1 : 0) + '|' + (rot || '') + '|' +
      (isFinite(Number(spill)) ? Math.round(Number(spill) * 20) : '');
    var now = Date.now();
    // 同鍵：45s 心跳重送；異鍵：12s 去抖
    if (!ctx.force) {
      if (key === _lastKey && (now - _lastAt) < HEARTBEAT_MS) {
        return Promise.resolve({ skipped: true, reason: 'throttle', style: style, delever: delever });
      }
      if (key !== _lastKey && (now - _lastAt) < MIN_INTERVAL_MS) {
        return Promise.resolve({ skipped: true, reason: 'debounce', style: style, delever: delever });
      }
    }

    var leaders = Array.isArray(ctx.leaders) ? ctx.leaders.slice(0, 6) : [];
    var payload = {
      style: style,
      delever: delever,
      note: note,
      meta: {
        score: score,
        advRatio: adv,
        label: ctx.label || null,
        source: ctx.source || 'st-macro',
        rotation: rot,
        spillover_prob: isFinite(Number(spill)) ? Number(spill) : null,
        leaders: leaders,
        hot_stage: ctx.hotStage || ctx.hot_stage || null,
        chain_breadth: ctx.chainBreadth != null ? ctx.chainBreadth : null,
        chain_contig: ctx.chainContig != null ? ctx.chainContig : null,
        twii: (ctx.twii != null && isFinite(Number(ctx.twii))) ? Number(ctx.twii) : null,
        twii_chg: (ctx.twiiChg != null && isFinite(Number(ctx.twiiChg))) ? Number(ctx.twiiChg) : null,
        decision_regime: ctx.decisionRegime || null,
        decision_confidence: (ctx.decisionConfidence != null && isFinite(Number(ctx.decisionConfidence))) ? Number(ctx.decisionConfidence) : null,
        decision_posture: ctx.decisionPosture || null,
        decision_invalidation: ctx.decisionInvalidation || null,
        decision_contract_version: ctx.decisionContractVersion || null,
        decision_model: ctx.decisionModel || null,
        decision_as_of: ctx.decisionAsOf || null
      }
    };

    return pushOverlay(payload).then(function (j) {
      _lastKey = key;
      _lastAt = now;
      _lastPayload = payload;
      try {
        window.dispatchEvent(new CustomEvent('wavedeck:overlay', { detail: payload }));
      } catch (e) {}
      if (!ctx.silent) {
        toast('已推送 WaveDeck · 風格 ' + style + (delever ? ' · 降載' : ''));
      }
      return { ok: true, payload: payload, state: j && j.state };
    }).catch(function (err) {
      if (!ctx.silent) toast('WaveDeck 覆寫失敗：' + (err && err.message ? err.message : err));
      try { console.warn('[wavedeck-bridge] sync', err); } catch (e2) {}
      return { ok: false, error: String(err && err.message ? err.message : err) };
    });
  }

  async function ping() {
    try {
      var base = await ensureBase();
      return !!base;
    } catch (e) {
      return false;
    }
  }

  function lastSync() {
    return _lastPayload ? {
      at: _lastAt,
      payload: _lastPayload
    } : null;
  }

  var _stateCache = null;
  var _stateAt = 0;
  var STATE_TTL_MS = 8000;

  /** symbol → lightweight POSITION_STATE chip (SSE / bus). */
  var _chipStore = Object.create(null);
  var _stream = null;
  var _streamOk = false;
  var _streamRetry = null;
  var _macroChip = null; // last macro overlay soft-chip fields
  var _linkOffline = false;

  function stateFromBusReport(report) {
    if (!report) return null;
    return {
      symbol: report.symbol || 'TXF',
      mode: report.mode,
      fsm: report.fsm,
      style: report.style,
      kill_switch: report.kill_switch,
      ai: report.ai || {},
      positions: report.positions || {},
      st_overlay: report.st_overlay || {},
      costs: report.costs || {},
      account: report.account || {},
      st_link: report.st_link || {},
      chip: report.chip || null,
      fromBus: true
    };
  }

  function normSym(code) {
    return String(code || '').toUpperCase().replace(/\.TW|\.TWO/g, '').trim();
  }

  function chipToHint(chip, opts) {
    opts = opts || {};
    if (!chip) return null;
    var dir = chip.direction || 'EMPTY';
    var qty = chip.position_size != null ? chip.position_size : 0;
    var inv = chip.invalidation_price != null
      ? { price: chip.invalidation_price, side: chip.invalidation_side || 'below' }
      : null;
    var mode = (chip.wd_mode === 'REAL') ? 'live' : 'paper';
    var macroOnly = !!opts.macroOnly;
    return {
      symbol: chip.symbol,
      market: chip.market || 'TW',
      direction: dir,
      position_size: qty,
      action: chip.action_label || chip.action || (macroOnly ? '宏觀' : '—'),
      action_label: chip.action_label || chip.action,
      confidence: chip.ai_confidence,
      invalidation: inv,
      invalidation_price: chip.invalidation_price,
      qty: dir === 'SHORT' ? -qty : qty,
      mode: mode,
      wd_mode: chip.wd_mode || 'PAPER',
      fsm: chip.fsm || '—',
      style: chip.macro_style != null ? chip.macro_style : chip.style,
      spillover: chip.spillover_prob,
      rotation: chip.rotation,
      hotStage: chip.hot_stage || null,
      fail_safe: !!chip.fail_safe,
      linkOffline: !!opts.linkOffline,
      macroOnly: macroOnly,
      compact: true
    };
  }

  function upsertChip(chip, meta) {
    if (!chip || !chip.symbol) return;
    var sym = normSym(chip.symbol);
    chip = Object.assign({}, chip, { symbol: sym });
    _chipStore[sym] = chip;
    // TXF aliases
    if (sym === 'TXF' || sym === 'TX') {
      _chipStore.TXF = chip;
      _chipStore.TX = chip;
    }
    if (chip.macro_style != null || chip.spillover_prob != null) {
      _macroChip = {
        style: chip.macro_style != null ? chip.macro_style : chip.style,
        spillover: chip.spillover_prob,
        rotation: chip.rotation,
        hotStage: chip.hot_stage,
        fail_safe: !!chip.fail_safe
      };
    }
    _linkOffline = false;
    try {
      window.dispatchEvent(new CustomEvent('wavedeck:chip', {
        detail: {
          symbol: sym,
          chip: chip,
          hint: chipToHint(chip),
          event_type: (meta && meta.event_type) || 'POSITION_STATE_CHANGE',
          costs: meta && meta.costs,
          timestamp: meta && meta.timestamp
        }
      }));
    } catch (e) {}
  }

  function applyStreamEvent(evt) {
    if (!evt || typeof evt !== 'object') return;
    var et = evt.event_type || 'POSITION_STATE_CHANGE';
    if (evt.costs) {
      _costCache = Object.assign(_costCache || { ok: true }, { costs: evt.costs, ok: true });
      _costAt = Date.now();
    }
    if (et === 'FULL_SYNC') {
      var pack = evt.data || {};
      var list = Array.isArray(pack.positions) ? pack.positions : [];
      _chipStore = Object.create(null);
      for (var i = 0; i < list.length; i++) upsertChip(list[i], { event_type: 'FULL_SYNC', costs: evt.costs, timestamp: evt.timestamp });
      try {
        window.dispatchEvent(new CustomEvent('wavedeck:full_sync', { detail: evt }));
      } catch (e2) {}
      return;
    }
    if (et === 'LINK_STATUS') {
      var st = (evt.data && evt.data.status) || '';
      _linkOffline = (st === 'down' || st === 'offline');
      try {
        window.dispatchEvent(new CustomEvent('wavedeck:link', { detail: evt.data || {} }));
      } catch (e3) {}
      return;
    }
    // POSITION_STATE_CHANGE
    if (evt.data && evt.data.symbol) {
      upsertChip(evt.data, { event_type: et, costs: evt.costs, timestamp: evt.timestamp });
    }
  }

  function setStreamOk(ok) {
    var prev = _streamOk;
    _streamOk = !!ok;
    if (prev !== _streamOk) {
      _linkOffline = !_streamOk;
      try {
        window.dispatchEvent(new CustomEvent('wavedeck:stream', {
          detail: { ok: _streamOk, offline: _linkOffline }
        }));
      } catch (e) {}
    }
  }

  function startChipStream() {
    if (PRIVATE_WEB_NO_WD) return;
    if (typeof EventSource === 'undefined') return;
    if (_stream) {
      try { _stream.close(); } catch (e0) {}
      _stream = null;
    }
    var url = (ST_URL || '') + '/bridge/wavedeck/stream';
    try {
      _stream = new EventSource(url);
    } catch (e1) {
      setStreamOk(false);
      scheduleStreamRetry();
      return;
    }
    _stream.addEventListener('FULL_SYNC', function (ev) {
      try { applyStreamEvent(JSON.parse(ev.data)); setStreamOk(true); } catch (e) {}
    });
    _stream.addEventListener('POSITION_STATE_CHANGE', function (ev) {
      try { applyStreamEvent(JSON.parse(ev.data)); setStreamOk(true); } catch (e) {}
    });
    _stream.addEventListener('LINK_STATUS', function (ev) {
      try { applyStreamEvent(JSON.parse(ev.data)); } catch (e) {}
    });
    _stream.onmessage = function (ev) {
      try { applyStreamEvent(JSON.parse(ev.data)); setStreamOk(true); } catch (e) {}
    };
    _stream.onopen = function () { setStreamOk(true); };
    _stream.onerror = function () {
      setStreamOk(false);
      try { if (_stream) _stream.close(); } catch (e2) {}
      _stream = null;
      scheduleStreamRetry();
    };
  }

  function scheduleStreamRetry() {
    if (PRIVATE_WEB_NO_WD) return;
    if (_streamRetry) return;
    _streamRetry = setTimeout(function () {
      _streamRetry = null;
      startChipStream();
    }, 4000);
  }

  function fetchState(force) {
    if (PRIVATE_WEB_NO_WD) return Promise.resolve(null);
    var now = Date.now();
    if (!force && _stateCache && (now - _stateAt) < STATE_TTL_MS) {
      return Promise.resolve(_stateCache);
    }
    return ensureBase().then(function (base) {
      if (!base) return null;
      return fetch(base.replace(/\/$/, '') + '/api/state', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          var st = j && j.state ? j.state : null;
          _stateCache = st;
          _stateAt = Date.now();
          if (st && st.symbol) {
            // seed chip store from WD pull fallback
            var syn = stateFromBusReport(st);
            if (syn) {
              var fakeReport = {
                symbol: syn.symbol,
                mode: syn.mode,
                fsm: syn.fsm,
                style: syn.style,
                ai: syn.ai,
                positions: syn.positions,
                st_overlay: syn.st_overlay,
                st_link: syn.st_link
              };
              // derive via REST meter path when possible
            }
          }
          return st;
        })
        .catch(function () { return null; });
    });
  }

  /** ST reverse bus / shared cost meter (REST fallback; SSE is primary). */
  function fetchCostMeter(force) {
    if (PRIVATE_WEB_NO_WD) return Promise.resolve(null);
    var now = Date.now();
    if (!force && _costCache && (now - _costAt) < COST_TTL_MS) {
      return Promise.resolve(_costCache);
    }
    var url = (ST_URL || '') + '/bridge/wavedeck';
    return fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (j && j.ok) {
          _costCache = j;
          _costAt = Date.now();
          var syn = stateFromBusReport(j.report);
          if (syn) {
            _stateCache = syn;
            _stateAt = Date.now();
          }
          if (j.chip) upsertChip(j.chip, { event_type: 'REST_SNAPSHOT', costs: j.costs });
          else if (j.report && j.report.chip) upsertChip(j.report.chip, { event_type: 'REST_SNAPSHOT', costs: j.costs });
        }
        return j;
      })
      .catch(function () { return null; });
  }

  /**
   * Chip/UI state: prefer SSE chip store → ST bus REST → WD pull.
   */
  function fetchChipState(force) {
    var keys = Object.keys(_chipStore);
    if (!force && keys.length) {
      var primary = _chipStore.TXF || _chipStore[keys[0]];
      if (primary) {
        return Promise.resolve({
          symbol: primary.symbol,
          mode: primary.wd_mode === 'REAL' ? 'live' : 'paper',
          fsm: primary.fsm,
          style: primary.style,
          ai: {
            action: primary.action,
            action_label: primary.action_label,
            confidence: primary.ai_confidence,
            invalidation: primary.invalidation_price != null
              ? { price: primary.invalidation_price, side: primary.invalidation_side || 'below' }
              : {}
          },
          positions: {
            account: primary.direction === 'SHORT'
              ? -primary.position_size
              : primary.position_size
          },
          st_overlay: {
            aggressiveness: primary.macro_style,
            spillover_prob: primary.spillover_prob,
            fail_safe: primary.fail_safe
          },
          fromChipStore: true
        });
      }
    }
    return fetchCostMeter(!!force).then(function (meter) {
      if (meter && meter.report) {
        var syn = stateFromBusReport(meter.report);
        if (syn) return syn;
      }
      return fetchState(!!force);
    });
  }

  function lastWdReport() {
    return (_costCache && _costCache.report) || null;
  }

  function getChip(code) {
    var want = normSym(code);
    if (!want) return _chipStore.TXF || null;
    return _chipStore[want] || null;
  }

  function streamStatus() {
    return { ok: _streamOk, offline: _linkOffline, chips: Object.keys(_chipStore).length };
  }

  /** Near invalidation (<1%) → alert styling. */
  function nearInvalidation(chipOrHint, lastPrice) {
    var px = Number(lastPrice);
    var inv = null;
    if (chipOrHint && chipOrHint.invalidation_price != null) inv = Number(chipOrHint.invalidation_price);
    else if (chipOrHint && chipOrHint.invalidation && chipOrHint.invalidation.price != null) {
      inv = Number(chipOrHint.invalidation.price);
    }
    if (!isFinite(px) || !isFinite(inv) || inv === 0) return false;
    return Math.abs(px - inv) / Math.abs(inv) < 0.01;
  }

  /** Plain chip label（無 HTML；頂列 WD 狀態列用，避免 textContent 露出標籤） */
  function chipLabelFromHint(h) {
    if (!h) return '';
    var offline = !!h.linkOffline || _linkOffline;
    if (offline) return '失聯';
    if (h.macroOnly) {
      var spill = (h.spillover != null && isFinite(h.spillover))
        ? Math.round(Number(h.spillover) * 100) + '%' : '';
      return 'MAC' + (h.style != null ? ' ' + h.style : '') + (spill ? ' · ' + spill : '');
    }
    var dirZh = h.direction === 'LONG' ? '多' : h.direction === 'SHORT' ? '空' : '觀望';
    var size = h.position_size != null ? h.position_size : (h.qty != null ? Math.abs(h.qty) : 0);
    var invTxt = h.invalidation_price != null
      ? ('防守 ' + h.invalidation_price)
      : (h.invalidation && h.invalidation.price != null ? ('防守 ' + h.invalidation.price) : '');
    if (h.direction === 'EMPTY' || !size) {
      return (h.wd_mode === 'PAPER' || h.mode === 'paper' ? '紙上' : '實盤') + ' | ' + dirZh;
    }
    return dirZh + ' ' + size + (invTxt ? ' | ' + invTxt : '');
  }

  /**
   * Compact plain label for shell status (never HTML).
   * @param {string} code
   * @param {{lastPrice?:number}|number} [optsOrPrice]
   */
  function chipLabel(code, optsOrPrice) {
    var opts = (optsOrPrice != null && typeof optsOrPrice === 'object') ? optsOrPrice : { lastPrice: optsOrPrice };
    var h = hintForSymbol(normSym(code), null, opts.lastPrice);
    return chipLabelFromHint(h);
  }

  /**
   * Compact chip HTML for Watch／Book atomic paint.
   * @param {string} code
   * @param {{lastPrice?:number}|number} [optsOrPrice]
   */
  function chipHtml(code, optsOrPrice) {
    var opts = (optsOrPrice != null && typeof optsOrPrice === 'object') ? optsOrPrice : { lastPrice: optsOrPrice };
    var want = normSym(code);
    var h = hintForSymbol(want, null, opts.lastPrice);
    if (!h) return '';
    var alert = !!h.alert || nearInvalidation(h, opts.lastPrice);
    var offline = !!h.linkOffline || _linkOffline;
    var border = offline ? 'rgba(148,163,184,.45)'
      : alert ? 'rgba(251,146,60,.85)'
      : h.macroOnly ? 'rgba(148,163,184,.35)'
      : (h.wd_mode === 'REAL' || h.mode === 'live') ? 'rgba(52,211,153,.55)' : 'rgba(103,232,249,.35)';
    var color = offline ? '#94a3b8'
      : alert ? '#fb923c'
      : h.macroOnly ? '#94a3b8'
      : (h.wd_mode === 'REAL' || h.mode === 'live') ? '#34d399' : 'var(--cyan)';
    var bg = offline ? 'rgba(148,163,184,.08)'
      : alert ? 'rgba(251,146,60,.12)'
      : h.macroOnly ? 'rgba(148,163,184,.1)'
      : 'rgba(103,232,249,.1)';
    var anim = alert && !offline ? 'animation:wdChipPulse 1.1s ease-in-out infinite;' : '';
    var label = chipLabelFromHint(h);
    var tip = h.tip || [
      offline ? 'WaveDeck 串流中斷' : 'WaveDeck',
      h.action,
      (h.confidence != null && isFinite(h.confidence)) && ('AI 信心 ' + Math.round(Number(h.confidence) * 100) + '%'),
      h.invalidation_price != null && ('失效價 ' + h.invalidation_price),
      h.fsm && ('FSM ' + h.fsm),
      h.wd_mode || h.mode,
      alert && '接近防守線'
    ].filter(Boolean).join(' · ');
    return '<span data-wd-chip="' + want + '" title="' + String(tip).replace(/"/g, '&quot;') + '" style="font-family:monospace;font-size:8.5px;font-weight:700;padding:2px 6px;border-radius:3px;background:' + bg + ';color:' + color + ';border:1px solid ' + border + ';white-space:nowrap;' + anim + '">WD ' + label + '</span>';
  }

  /** Return compact WD hint for a symbol (chip store → bus state → macro). */
  function hintForSymbol(code, state, lastPrice) {
    var want = normSym(code);
    if (_linkOffline && !getChip(want) && !(_chipStore.TXF)) {
      return {
        symbol: want || 'TXF',
        linkOffline: true,
        macroOnly: false,
        action: '失聯',
        tip: 'WaveDeck 串流中斷 — 請檢查 WD／ST 連線'
      };
    }
    var chip = getChip(want);
    if (!chip && (want === 'TXF' || want === 'TX' || want === '^TWII' || want === 'TWII')) {
      chip = _chipStore.TXF || _chipStore.TX || null;
    }
    if (chip) {
      var h = chipToHint(chip, { linkOffline: _linkOffline });
      h.alert = nearInvalidation(chip, lastPrice);
      h.tip = [
        h.action,
        (h.confidence != null && isFinite(h.confidence)) && ('AI 信心度 ' + Math.round(Number(h.confidence) * 100) + '%'),
        h.invalidation_price != null && ('預期結構防守 ' + h.invalidation_price),
        '模式 ' + (h.wd_mode || h.mode),
        h.fsm && ('FSM ' + h.fsm),
        h.fail_safe && 'Fail-safe',
        h.alert && '現價距失效價 <1%'
      ].filter(Boolean).join(' · ');
      return h;
    }

    var st = state || _stateCache;
    if (!st) {
      // Soft macro chip for equities when only overlay known
      if (_macroChip && want && want !== 'TXF' && want !== 'TX') {
        return {
          symbol: want,
          action: 'MACRO',
          action_label: '宏觀',
          style: _macroChip.style,
          spillover: _macroChip.spillover,
          rotation: _macroChip.rotation,
          hotStage: _macroChip.hotStage,
          macroOnly: true,
          mode: 'paper',
          tip: '宏觀覆寫 · 風格 ' + (_macroChip.style != null ? _macroChip.style : '—')
        };
      }
      return null;
    }
    var wdSym = normSym(st.symbol || 'TXF');
    var match = !want || want === wdSym ||
      (want === 'TXF' && (wdSym === 'TXF' || wdSym === 'TX')) ||
      (want === '^TWII' && (wdSym === 'TXF' || wdSym === 'TWII'));
    var ai = st.ai || {};
    var inv = ai.invalidation || {};
    var pos = st.positions || {};
    var ov = st.st_overlay || {};

    if (!match) {
      if (ov.aggressiveness == null && !ov.note && ov.spillover_prob == null) return null;
      var stage = null;
      try {
        if (window.SC_STAGE && want && window.SC_STAGE[want]) stage = window.SC_STAGE[want];
      } catch (e0) {}
      return {
        symbol: want,
        action: 'MACRO',
        action_label: '宏觀',
        confidence: null,
        style: ov.aggressiveness != null ? ov.aggressiveness : st.style,
        spillover: ov.spillover_prob,
        rotation: ov.rotation,
        hotStage: ov.hot_stage || null,
        leaders: ov.leaders || [],
        scStage: stage,
        mode: st.mode || 'paper',
        fsm: st.fsm || '—',
        macroOnly: true
      };
    }
    var qty = pos.account != null ? pos.account : pos.txt_target;
    var qn = Number(qty) || 0;
    return {
      symbol: wdSym,
      direction: qn > 0 ? 'LONG' : qn < 0 ? 'SHORT' : 'EMPTY',
      position_size: Math.abs(qn),
      action: ai.action_label || ai.action || '—',
      confidence: ai.confidence,
      biasLong: ai.bias_long,
      biasShort: ai.bias_short,
      invalidation: inv.price != null ? { price: inv.price, side: inv.side || 'below' } : null,
      invalidation_price: inv.price,
      qty: qty,
      mode: st.mode || 'paper',
      wd_mode: (st.mode === 'live') ? 'REAL' : 'PAPER',
      fsm: st.fsm || '—',
      style: st.style,
      spillover: ov.spillover_prob,
      rotation: ov.rotation,
      hotStage: ov.hot_stage || null,
      leaders: ov.leaders || [],
      macroOnly: false,
      alert: nearInvalidation({ invalidation_price: inv.price }, lastPrice)
    };
  }

  function ensureChipPulseStyle() {
    if (document.getElementById('wd-chip-pulse-style')) return;
    var s = document.createElement('style');
    s.id = 'wd-chip-pulse-style';
    s.textContent = '@keyframes wdChipPulse{0%,100%{opacity:1}50%{opacity:.55}}';
    document.head.appendChild(s);
  }

  /** Atomic DOM patch: only nodes with data-wd-chip=symbol. */
  function paintChipNodes(symbol, lastPrice) {
    ensureChipPulseStyle();
    var want = normSym(symbol);
    var nodes = document.querySelectorAll('[data-wd-chip]');
    if (!nodes || !nodes.length) return 0;
    var n = 0;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var sym = normSym(el.getAttribute('data-wd-chip'));
      if (want && sym !== want && !(want === 'TXF' && (sym === 'TXF' || sym === 'TX' || sym === '^TWII'))) {
        // still allow macro soft chips refresh on FULL_SYNC (want empty)
        if (want) continue;
      }
      var html = chipHtml(sym, { lastPrice: lastPrice });
      if (!html) continue;
      var wrap = document.createElement('div');
      wrap.innerHTML = html;
      var neu = wrap.firstChild;
      if (neu && el.parentNode) {
        el.parentNode.replaceChild(neu, el);
        n++;
      }
    }
    return n;
  }

  window.WaveDeckBridge = {
    VERSION: '5.0-WD8',
    base: function () { return BASE; },
    open: open,
    pushOverlay: pushOverlay,
    ping: ping,
    styleFromScore: styleFromScore,
    spilloverFromRotation: spilloverFromRotation,
    spilloverFromChainStages: spilloverFromChainStages,
    blendSpillover: blendSpillover,
    syncFromMarket: syncFromMarket,
    lastSync: lastSync,
    autoEnabled: autoEnabled,
    setAutoEnabled: setAutoEnabled,
    fetchState: fetchState,
    fetchChipState: fetchChipState,
    hintForSymbol: hintForSymbol,
    chipLabel: chipLabel,
    chipHtml: chipHtml,
    getChip: getChip,
    paintChipNodes: paintChipNodes,
    nearInvalidation: nearInvalidation,
    streamStatus: streamStatus,
    startChipStream: startChipStream,
    fetchCostMeter: fetchCostMeter,
    lastWdReport: lastWdReport,
    stateFromBusReport: stateFromBusReport
  };

  try {
    ensureChipPulseStyle();
    startChipStream();
    window.addEventListener('wavedeck:chip', function (ev) {
      var d = ev && ev.detail;
      if (!d) return;
      paintChipNodes(d.symbol);
    });
    window.addEventListener('wavedeck:stream', function () {
      paintChipNodes('');
    });
    window.addEventListener('wavedeck:full_sync', function () {
      paintChipNodes('');
    });
  } catch (eBoot) {}

  function startOverlayHeartbeat() {
    if (PRIVATE_WEB_NO_WD) return;
    if (_hbTimer) return;
    _hbTimer = setInterval(function () {
      try {
        if (!autoEnabled()) return;
        if (!_lastPayload) return;
        if (Date.now() - _lastAt < HEARTBEAT_MS - 2000) return;
        pushOverlay(_lastPayload).then(function () {
          _lastAt = Date.now();
          try { console.log('[wavedeck-bridge] overlay heartbeat republish'); } catch (e0) {}
        }).catch(function (err) {
          try { console.warn('[wavedeck-bridge] heartbeat', err); } catch (e1) {}
        });
      } catch (e2) {}
    }, 15000);
  }
  startOverlayHeartbeat();

  try { console.log('[wavedeck-bridge] ready → ' + BASE + ' · SSE chip stream'); } catch (e) {}
})();
