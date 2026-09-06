/* Canonical DecisionContext store: one writer, many renderers. */
(function () {
  'use strict';
  var state = { context: null, summary: null, updatedAt: null, contractVersion: 1 };
  var inflight = null;
  var researchInflight = null;
  var researchUpdatedAt = 0;
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
    if (!context.researchObservations && state.context && state.context.researchObservations) {
      context = Object.assign({}, context, { researchObservations: state.context.researchObservations });
    }
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
        consensusAttention: context.consensusAttention || null,
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

  function withOvernightResearch(context, payload) {
    var observations = Object.assign({}, (context && context.researchObservations) || {});
    observations.overnightIntraday = payload || null;
    return Object.assign({}, context || {}, { researchObservations: observations });
  }

  function parseResponse(response, id, event) {
    return response.text().then(function (raw) {
      trace(event, id, { status: response.status, ok: response.ok, responseChars: raw.length });
      if (!response.ok || !raw) return null;
      try { return JSON.parse(raw); }
      catch (error) {
        trace(event + '_parse_error', id, { error: String(error && error.message || error) });
        return null;
      }
    });
  }

  function refreshOvernightResearch(context, id, force) {
    if (!context || !context.regime) return Promise.resolve(state);
    if (window.FeatureFlags && FeatureFlags.isEnabled && !FeatureFlags.isEnabled('shadowOvernightIntraday')) {
      return Promise.resolve(state);
    }
    if (researchInflight) return researchInflight;
    if (!force && researchUpdatedAt && Date.now() - researchUpdatedAt < 15 * 60 * 1000) return Promise.resolve(state);
    var path = base() + '/research/overnight-intraday?market=all';
    researchInflight = fetch(path, { cache: 'no-store' })
      .then(function (response) { return parseResponse(response, id, 'overnight_cache_response'); })
      .then(function (cached) {
        if (!force && cached && cached.ok) return cached;
        trace('overnight_refresh_start', id, { scope: 'memory_v1', market: 'all' });
        return fetch(base() + '/research/overnight-intraday/refresh?market=all', {
          method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ market: 'all', force: !!force })
        }).then(function (response) { return parseResponse(response, id, 'overnight_refresh_response'); });
      })
      .then(function (payload) {
        researchUpdatedAt = Date.now();
        var current = state.context || context;
        if (payload && current && current.regime) publish(withOvernightResearch(current, payload), 'overnight-research', id);
        return state;
      })
      .catch(function (error) {
        researchUpdatedAt = Date.now();
        trace('overnight_refresh_error', id, { error: String(error && error.message || error) });
        return state;
      })
      .finally(function () { researchInflight = null; });
    return researchInflight;
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
        if (ctx) {
          var published = publish(ctx, hasBody ? 'profile' : 'refresh', id);
          refreshOvernightResearch(state.context, id, false);
          return published;
        }
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
    refreshOvernightResearch: function (force) {
      return refreshOvernightResearch(state.context, correlationId('overnight'), !!force);
    },
    trace: trace,
    correlationId: correlationId,
    traceKey: TRACE_KEY
  };
}());
