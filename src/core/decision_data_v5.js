/* Canonical DecisionContext store: one writer, many renderers. */
(function () {
  'use strict';
  var state = { context: null, summary: null, updatedAt: null, contractVersion: 1 };
  var inflight = null;
  var TRACE_KEY = 'st_decision_ui_trace_v1';

  function base() { return window.SERVER || location.origin || 'http://localhost:18432'; }

  function correlationId(prefix) {
    return String(prefix || 'decision') + '-' + Date.now().toString(36) + '-' +
      Math.random().toString(36).slice(2, 8);
  }

  function trace(event, id, details) {
    try {
      var rows = JSON.parse(localStorage.getItem(TRACE_KEY) || '[]');
      if (!Array.isArray(rows)) rows = [];
      rows.push({
        timestamp: new Date().toISOString(),
        component: 'decision-data',
        event: event,
        correlationId: id || null,
        details: details || {}
      });
      localStorage.setItem(TRACE_KEY, JSON.stringify(rows.slice(-80)));
    } catch (e) {}
  }

  function emit(reason) {
    try {
      window.dispatchEvent(new CustomEvent('decisionData', {
        detail: { state: state, reason: reason || 'publish' }
      }));
    } catch (e) {}
  }

  function publish(context, reason, id) {
    if (!context || !context.regime) return state;
    state = {
      context: context,
      summary: {
        contractVersion: context.contractVersion || 1,
        asOf: context.asOf,
        regime: context.regime,
        posture: (context.actionEnvelope || {}).posture,
        allowed: (context.actionEnvelope || {}).allowed || [],
        restricted: (context.actionEnvelope || {}).restricted || [],
        confirmation: context.confirmation || [],
        invalidation: context.invalidation || [],
        levels: ((context.keyLevels || {}).levels || {}),
        keyLevelMeta: {
          referenceDate: (context.keyLevels || {}).referenceDate || null,
          source: (context.keyLevels || {}).source || null,
          method: (context.keyLevels || {}).method || null,
          quality: (context.keyLevels || {}).quality || {}
        },
        volatility: context.volatility || {},
        flow: ((((context.scenario || {}).flow || {}).raw) || {}),
        divergences: (context.divergences || []).map(function (x) { return x.id; }),
        divergenceDetails: (context.divergences || []).slice(0, 3),
        dataQuality: context.dataQuality || {},
        model: context.model
      },
      updatedAt: context.asOf || new Date().toISOString(),
      contractVersion: context.contractVersion || 1
    };
    trace('context_published', id || null, {
      reason: reason || 'context',
      regime: context.regime.id || null,
      asOf: context.asOf || null
    });
    emit(reason || 'context');
    return state;
  }

  function fromPulse(pulse, id) {
    var summary = pulse && pulse.decisionSummary;
    if (!summary || !summary.regime) {
      trace('pulse_summary_missing', id || null, { pulseOk: !!(pulse && pulse.ok) });
      return state;
    }
    state = {
      context: state.context,
      summary: summary,
      updatedAt: summary.asOf || pulse.updatedAt || state.updatedAt,
      contractVersion: summary.contractVersion || 1
    };
    trace('pulse_summary_received', id || null, {
      regime: summary.regime.id || null,
      asOf: summary.asOf || pulse.updatedAt || null
    });
    emit('pulse-summary');
    return state;
  }

  function refresh(opts) {
    opts = opts || {};
    if (inflight && !opts.force) return inflight;
    var id = opts.correlationId || correlationId('context');
    var started = Date.now();
    var hasBody = !!(opts.riskProfile || (opts.holdings && opts.holdings.length));
    var req = { cache: 'no-store' };
    if (hasBody) {
      req.method = 'POST';
      req.headers = { 'Content-Type': 'application/json' };
      req.body = JSON.stringify({
        riskProfile: opts.riskProfile || null,
        holdings: opts.holdings || [],
        portfolioKind: opts.portfolioKind || 'actual'
      });
    }
    trace('context_request_start', id, {
      method: req.method || 'GET',
      path: '/decision/context',
      portfolioKind: opts.portfolioKind || null,
      holdingsCount: (opts.holdings || []).length
    });
    inflight = fetch(base() + '/decision/context', req)
      .then(function (r) {
        return r.text().then(function (raw) {
          trace('context_response', id, {
            status: r.status,
            ok: r.ok,
            responseChars: raw.length,
            elapsedMs: Date.now() - started
          });
          if (!r.ok || !raw) return null;
          try { return JSON.parse(raw); }
          catch (e) {
            trace('context_parse_error', id, { error: String(e && e.message || e) });
            return null;
          }
        });
      })
      .then(function (ctx) {
        if (ctx) return publish(ctx, hasBody ? 'profile' : 'refresh', id);
        trace('context_unavailable', id, { elapsedMs: Date.now() - started });
        return state;
      })
      .catch(function (err) {
        trace('context_network_error', id, {
          error: String(err && err.message || err),
          elapsedMs: Date.now() - started
        });
        return state;
      })
      .finally(function () { inflight = null; });
    return inflight;
  }

  window.DecisionData = {
    get: function () { return state; },
    publish: publish,
    fromPulse: fromPulse,
    refresh: refresh,
    trace: trace,
    correlationId: correlationId,
    traceKey: TRACE_KEY
  };
}());
