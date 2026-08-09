/* ============================================================================
 * wavedeck_bridge_v5.js — Stock Terminal → WaveDeck 入口與宏觀覆寫
 * ----------------------------------------------------------------------------
 * - 側欄「執行」→ open()
 * - syncFromMarket({score, advRatio, …}) → POST /bridge/st（節流／去重）
 * - styleFromScore：廣度＋體質 → 進場風格 35–65
 * 鐵律：失敗僅 toast／console，不阻斷 ST 主流程。
 * ========================================================================== */
(function () {
  'use strict';

  var DEFAULT_URL = 'http://127.0.0.1:18433/';
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

  /** Map ST market score + breadth advRatio → WaveDeck style. */
  function styleFromScore(score, advRatio) {
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
    return Math.max(20, Math.min(90, Math.round(hint)));
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
   * @param {{score?:number, advRatio?:number, label?:string, summary?:string, force?:boolean, silent?:boolean}} ctx
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
    var style = styleFromScore(score, adv);
    var delever = isFinite(Number(score)) && Number(score) < 35;
    var note = buildNote(ctx, style, delever);
    var key = style + '|' + (delever ? 1 : 0);
    var now = Date.now();
    if (!ctx.force && key === _lastKey && (now - _lastAt) < MIN_INTERVAL_MS) {
      return Promise.resolve({ skipped: true, reason: 'throttle', style: style, delever: delever });
    }

    var payload = {
      style: style,
      delever: delever,
      note: note,
      meta: {
        score: score,
        advRatio: adv,
        label: ctx.label || null,
        source: ctx.source || 'st-macro'
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

  window.WaveDeckBridge = {
    VERSION: '5.0-WD2',
    base: function () { return BASE; },
    open: open,
    pushOverlay: pushOverlay,
    ping: ping,
    styleFromScore: styleFromScore,
    syncFromMarket: syncFromMarket,
    lastSync: lastSync,
    autoEnabled: autoEnabled,
    setAutoEnabled: setAutoEnabled
  };

  try { console.log('[wavedeck-bridge] ready → ' + BASE); } catch (e) {}
})();
