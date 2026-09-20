/* Canonical DecisionContext store: one writer, many renderers. */
(function () {
  'use strict';
  var state = { context: null, summary: null, updatedAt: null, contractVersion: 1 };
  var inflight = null;
  var inflightKey = null;
  var requestSequence = 0;
  var researchInflight = null;
  var researchUpdatedAt = 0;
  var TRACE_KEY = 'st_decision_ui_trace_v1';

  function base() { return window.SERVER || location.origin || 'http://localhost:18432'; }

  function canUpdateMarket() {
    var profile = window.ST_PRIVATE_WEB_PROFILE;
    return !profile || profile.role === 'owner';
  }

  function pulseJob(payload) {
    var update = payload && payload.updateState;
    return update && (update.job || (update.status ? update : null));
  }

  // 純讀與明確更新共用工作協議；取消只停止此瀏覽器等待，不取消伺服器工作。
  async function refreshPulse(options) {
    options = options || {};
    var update = options.update === true && canUpdateMarket();
    var controller = new AbortController();
    var timedOut = false;
    var external = options.signal;
    function abort() { controller.abort(); }
    if (external) {
      if (external.aborted) abort();
      else external.addEventListener('abort', abort, { once: true });
    }
    var timeout = setTimeout(function () { timedOut = true; abort(); }, update ? 90000 : 12000);
    async function json(path, request) {
      if (controller.signal.aborted) { var cancelled = new Error('已停止等待市場快照'); cancelled.name = 'AbortError'; throw cancelled; }
      var response = await fetch(base() + path, Object.assign({ cache: 'no-store', signal: controller.signal }, request || {}));
      var payload = await response.json();
      if (!response.ok) {
        var failure = new Error(payload && payload.error || ('HTTP ' + response.status));
        failure.status = response.status;
        throw failure;
      }
      return payload;
    }
    function pause() {
      return new Promise(function (resolve, reject) {
        function cancelled() {
          clearTimeout(timer);
          controller.signal.removeEventListener('abort', cancelled);
          var error = new Error('已停止等待市場更新'); error.name = 'AbortError'; reject(error);
        }
        var timer = setTimeout(function () {
          controller.signal.removeEventListener('abort', cancelled); resolve();
        }, 1000);
        if (controller.signal.aborted) cancelled();
        else controller.signal.addEventListener('abort', cancelled, { once: true });
      });
    }
    try {
      if (!update) {
        var current = await json('/pulse');
        return { pulse: current, job: pulseJob(current), requestedUpdate: false, error: null };
      }
      var accepted = await json('/pulse/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
      });
      var job = accepted && accepted.job;
      if (!job || !job.jobId) throw new Error('伺服器未提供市場更新工作識別');
      if (options.onStatus) options.onStatus(job);
      while (job.status === 'queued' || job.status === 'running') {
        await pause();
        var progress = await json('/pulse/update-status?jobId=' + encodeURIComponent(job.jobId));
        if (!progress || !progress.job || progress.job.jobId !== job.jobId) throw new Error('市場更新工作狀態不一致');
        job = progress.job;
        if (options.onStatus) options.onStatus(job);
      }
      if (['succeeded', 'failed', 'interrupted'].indexOf(job.status) < 0) throw new Error('無法辨識市場更新工作狀態');
      var pulse = await json('/pulse');
      var error = job.status === 'succeeded' ? null : String(job.error || (job.status === 'interrupted' ? '市場更新工作已中斷' : '市場更新失敗'));
      if (!error && (!pulse || !pulse.ok)) error = '工作已結束，但尚未讀到已提交快照';
      return { pulse: pulse, job: job, requestedUpdate: true, coalesced: !!accepted.coalesced, error: error };
    } catch (error) {
      if (timedOut) {
        var timeoutError = new Error(update ? '等待市場更新逾時；伺服器工作仍可能繼續，可重新讀取狀態。' : '讀取市場快照逾時');
        timeoutError.name = 'TimeoutError'; throw timeoutError;
      }
      throw error;
    } finally {
      clearTimeout(timeout);
      if (external) external.removeEventListener('abort', abort);
    }
  }

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
        snapshotId: context.snapshotId || null,
        parentSnapshotId: context.parentSnapshotId || null,
        revision: context.revision == null ? null : context.revision,
        inputHash: context.inputHash || null,
        rulesDigest: context.rulesDigest || null,
        publicationStatus: context.publicationStatus || null,
        persistence: context.persistence || null,
        viewScope: context.viewScope || null,
        viewState: context.viewState || null,
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
    if (researchInflight) return researchInflight;
    if (!force && researchUpdatedAt && Date.now() - researchUpdatedAt < 15 * 60 * 1000) return Promise.resolve(state);
    var path = base() + '/research/overnight-intraday?market=all';
    researchInflight = fetch(path, { cache: 'no-store' })
      .then(function (response) { return parseResponse(response, id, 'overnight_cache_response'); })
      .then(function (cached) {
        if (!force || !canUpdateMarket()) return cached;
        trace('overnight_refresh_start', id, { scope: 'memory_v1', market: 'all' });
        return fetch(base() + '/research/overnight-intraday/refresh?market=all', {
          method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ market: 'all', force: !!force })
        }).then(function (response) { return parseResponse(response, id, 'overnight_refresh_response'); });
      })
      .then(function (payload) {
        researchUpdatedAt = Date.now();
        var current = state.context || context;
        if (payload && payload.ok && current && current.regime) publish(withOvernightResearch(current, payload), 'overnight-research', id);
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
    var personalized = canUpdateMarket();
    var input = {
      riskProfile: personalized ? (opts.riskProfile || null) : null,
      holdings: personalized ? (opts.holdings || []) : [],
      portfolioKind: opts.portfolioKind || 'actual'
    };
    var requestKey = JSON.stringify(input);
    if (inflight && !opts.force && inflightKey === requestKey) return inflight;
    // 相同輸入共用請求；輸入改變或強制更新時，只有最新一代能發布。
    var sequence = ++requestSequence;
    var id = opts.correlationId || correlationId('context');
    var started = Date.now();
    var hasBody = !!(input.riskProfile || input.holdings.length);
    var req = { cache: 'no-store' };
    if (opts.signal) req.signal = opts.signal;
    if (hasBody) {
      req.method = 'POST';
      req.headers = { 'Content-Type': 'application/json' };
      req.body = requestKey;
    }
    trace('context_request_start', id, {
      method: req.method || 'GET',
      path: '/decision/context',
      portfolioKind: opts.portfolioKind || null,
      holdingsCount: (opts.holdings || []).length
    });
    var request = fetch(base() + '/decision/context', req)
      .then(function (r) {
        return r.text().then(function (raw) {
          trace('context_response', id, {
            status: r.status,
            ok: r.ok,
            responseChars: raw.length,
            elapsedMs: Date.now() - started
          });
          if (!r.ok || !raw) {
            if (opts.throwOnError) {
              var error = new Error(!r.ok ? '讀取決策快照失敗（HTTP ' + r.status + '）' : '決策快照回應為空');
              error.status = r.status;
              throw error;
            }
            return null;
          }
          try { return JSON.parse(raw); }
          catch (e) {
            trace('context_parse_error', id, { error: String(e && e.message || e) });
            if (opts.throwOnError) throw new Error('決策快照回應格式無效');
            return null;
          }
        });
      })
      .then(function (ctx) {
        if (opts.signal && opts.signal.aborted) return state;
        if (sequence !== requestSequence) {
          trace('context_response_discarded', id, { reason: 'superseded_input', sequence: sequence });
          return inflight || state;
        }
        if (opts.throwOnError && (!ctx || !ctx.regime)) throw new Error('決策快照缺少必要內容');
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
        if (sequence !== requestSequence) return inflight || state;
        if (opts.throwOnError) throw err;
        return state;
      })
      .finally(function () {
        if (inflight === request) { inflight = null; inflightKey = null; }
      });
    inflight = request;
    inflightKey = requestKey;
    return request;
  }

  window.DecisionData = {
    canUpdateMarket: canUpdateMarket,
    refreshPulse: refreshPulse,
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
