/* ============================================================================
 * wavedeck_bridge_v5.js — Stock Terminal → WaveDeck 入口與宏觀覆寫
 * ----------------------------------------------------------------------------
 * - 側欄「執行」→ open()
 * - syncFromMarket({score, advRatio, rotationHealth, spilloverProb, …})
 *   → POST /bridge/st（節流／去重；輪動／外溢寫入 meta）
 * - fetchCostMeter / lastWdReport ← ST GET /bridge/wavedeck（反向繁線）
 * - styleFromScore：廣度＋體質＋輪動＋外溢 → 進場風格 35–65
 * 鐵律：失敗僅 toast／console，不阻斷 ST 主流程。
 * ========================================================================== */
(function () {
  'use strict';

  var DEFAULT_URL = 'http://127.0.0.1:18433/';
  var ST_URL = (typeof window.SERVER === 'string' && window.SERVER)
    ? String(window.SERVER).replace(/\/?$/, '')
    : '';
  var CANDIDATES = [
    'http://127.0.0.1:18433/',
    'http://127.0.0.1:18434/',
    'http://127.0.0.1:18765/',
    'http://127.0.0.1:28765/',
    'http://127.0.0.1:38433/',
    'http://127.0.0.1:8765/'
  ];
  var BASE = (typeof window.WAVEDECK_URL === 'string' && window.WAVEDECK_URL)
    ? String(window.WAVEDECK_URL).replace(/\/?$/, '/')
    : DEFAULT_URL;

  var AUTO_KEY = 'st5.wd.autoOverlay';
  var MIN_INTERVAL_MS = 60000;
  var _lastKey = '';
  var _lastAt = 0;
  var _lastPayload = null;
  var _resolving = null;
  var _costCache = null;
  var _costAt = 0;
  var COST_TTL_MS = 10000;

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
    return bits.join(' · ');
  }

  function probeUrl(url) {
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
    if (url) {
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
    if (!ctx.force && key === _lastKey && (now - _lastAt) < MIN_INTERVAL_MS) {
      return Promise.resolve({ skipped: true, reason: 'throttle', style: style, delever: delever });
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
        chain_contig: ctx.chainContig != null ? ctx.chainContig : null
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

  function fetchState(force) {
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
          return st;
        })
        .catch(function () { return null; });
    });
  }

  /** ST reverse bus / shared cost meter. */
  function fetchCostMeter(force) {
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
        }
        return j;
      })
      .catch(function () { return null; });
  }

  function lastWdReport() {
    return (_costCache && _costCache.report) || null;
  }

  function normSym(code) {
    return String(code || '').toUpperCase().replace(/\.TW|\.TWO/g, '').trim();
  }

  /** Return compact WD hint for a symbol (TXF match or macro-only for equities). */
  function hintForSymbol(code, state) {
    var st = state || _stateCache;
    if (!st) return null;
    var want = normSym(code);
    var wdSym = normSym(st.symbol || 'TXF');
    var match = !want || want === wdSym ||
      (want === 'TXF' && (wdSym === 'TXF' || wdSym === 'TX')) ||
      (want === '^TWII' && (wdSym === 'TXF' || wdSym === 'TWII'));
    var ai = st.ai || {};
    var inv = ai.invalidation || {};
    var pos = st.positions || {};
    var ov = st.st_overlay || {};

    if (!match) {
      // Non-TXF equities: expose macro overlay (style / spillover) as soft chip
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
    return {
      symbol: wdSym,
      action: ai.action_label || ai.action || '—',
      confidence: ai.confidence,
      biasLong: ai.bias_long,
      biasShort: ai.bias_short,
      invalidation: inv.price != null ? { price: inv.price, side: inv.side || 'below' } : null,
      qty: pos.account != null ? pos.account : pos.txt_target,
      mode: st.mode || 'paper',
      fsm: st.fsm || '—',
      style: st.style,
      spillover: ov.spillover_prob,
      rotation: ov.rotation,
      hotStage: ov.hot_stage || null,
      leaders: ov.leaders || [],
      macroOnly: false
    };
  }

  window.WaveDeckBridge = {
    VERSION: '5.0-WD6',
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
    hintForSymbol: hintForSymbol,
    fetchCostMeter: fetchCostMeter,
    lastWdReport: lastWdReport
  };

  try { console.log('[wavedeck-bridge] ready → ' + BASE); } catch (e) {}
})();
