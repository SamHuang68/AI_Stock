/* Canonical DecisionContext store: one writer, many renderers. */
(function () {
  'use strict';
  // 身份欄位隨 context 一併保存，供渲染者比對快照世代與授權範圍。
  var state = {
    context: null,
    summary: null,
    updatedAt: null,
    contractVersion: 1,
    snapshotId: null,
    revision: 0,
    inputHash: null,
    rulesDigest: null,
    persistence: null,
    viewScope: null,
    parentSnapshotId: null,
    parentRevision: 0,
    portfolioInputKey: null
  };
  // 以 requestKey 區分 inflight，確保不同參數的 POST 不互相覆蓋。
  var inflightMap = Object.create(null);
  var requestSequence = 0;
  var researchInflight = null;
  var researchUpdatedAt = 0;
  var researchController = null;
  var TRACE_KEY = 'st_decision_ui_trace_v1';

  function base() {
    if (typeof window !== 'undefined' && window.SERVER) return window.SERVER;
    if (typeof location !== 'undefined' && location.origin) return location.origin;
    return 'http://localhost:18432';
  }

  function canUpdateMarket() {
    var profile = (typeof window !== 'undefined') ? window.ST_PRIVATE_WEB_PROFILE : null;
    return !profile || profile.role === 'owner';
  }

  function pulseJob(payload) {
    var update = payload && payload.updateState;
    return update && (update.job || (update.status ? update : null));
  }

  // 讀者僅 GET /pulse；擁有者才會 POST /pulse/refresh 建立持久 job 並輪詢 /pulse/update-status。
  // 取消僅停止瀏覽器端等待，不保證取消伺服器工作。
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
      if (controller.signal.aborted) {
        var cancelled = new Error('已停止等待市場快照');
        cancelled.name = 'AbortError';
        throw cancelled;
      }
      var response = await fetch(base() + path, Object.assign({ cache: 'no-store', signal: controller.signal }, request || {}));
      var payload = await response.json();
      if (!response.ok) {
        var failure = new Error((payload && payload.error) || ('HTTP ' + response.status));
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
          var error = new Error('已停止等待市場更新');
          error.name = 'AbortError';
          reject(error);
        }
        var timer = setTimeout(function () {
          controller.signal.removeEventListener('abort', cancelled);
          resolve();
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
        timeoutError.name = 'TimeoutError';
        throw timeoutError;
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

  function identityFields(source) {
    source = source || {};
    return {
      snapshotId: source.snapshotId || null,
      revision: Number(source.revision || 0),
      parentRevision: Number(source.parentRevision || 0),
      inputHash: source.inputHash || null,
      rulesDigest: source.rulesDigest || null,
      persistence: source.persistence || null,
      viewScope: source.viewScope || null,
      parentSnapshotId: source.parentSnapshotId || null,
      portfolioInputKey: source.portfolioInputKey || null
    };
  }

  function effectiveRevision(source) {
    if (!source) return -1;
    var rev = Number(source.revision || 0);
    var parentRev = Number(source.parentRevision || 0);
    return Math.max(rev, parentRev);
  }

  function sameScope(a, b) {
    if (!a || !b) return false;
    return (a.viewScope || null) === (b.viewScope || null)
      && (a.portfolioInputKey || null) === (b.portfolioInputKey || null);
  }

  // 不同 scope 仍共用市場修訂水位，舊快照不得覆蓋較新 canonical；
  // 若來源為 derived 快照，其 parentRevision 也納入比較。
  function isStaleSnapshot(incoming) {
    return effectiveRevision(incoming) < Math.max(effectiveRevision(state.context), effectiveRevision(state.summary));
  }

  function publish(context, reason, id, portfolioInputKey) {
    if (!context || !context.regime) return state;
    context = Object.assign({}, context, { portfolioInputKey: portfolioInputKey || context.portfolioInputKey || null });
    if (isStaleSnapshot(context)) {
      trace('context_stale_discarded', id || null, {
        reason: reason || 'context',
        incomingRevision: effectiveRevision(context),
        currentRevision: effectiveRevision(state.context)
      });
      return state;
    }
    if (!context.researchObservations && state.context && state.context.researchObservations && sameScope(context, state.context)) {
      context = Object.assign({}, context, { researchObservations: state.context.researchObservations });
    }
    var ident = identityFields(context);
    var summary = {
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
      model: context.model,
      // summary 與 context 由同一來源同步建立，身份欄位一致以免逆序配對。
      snapshotId: ident.snapshotId,
      revision: ident.revision,
      inputHash: ident.inputHash,
      rulesDigest: ident.rulesDigest,
      persistence: ident.persistence,
      viewScope: ident.viewScope,
      parentSnapshotId: ident.parentSnapshotId,
      parentRevision: ident.parentRevision,
      portfolioInputKey: ident.portfolioInputKey
    };
    state = {
      context: context,
      summary: summary,
      updatedAt: context.asOf || new Date().toISOString(),
      contractVersion: context.contractVersion || 1,
      snapshotId: ident.snapshotId,
      revision: ident.revision,
      inputHash: ident.inputHash,
      rulesDigest: ident.rulesDigest,
      persistence: ident.persistence,
      viewScope: ident.viewScope,
      parentSnapshotId: ident.parentSnapshotId,
      parentRevision: ident.parentRevision,
      portfolioInputKey: ident.portfolioInputKey
    };
    trace('context_published', id || null, {
      reason: reason || 'context',
      regime: context.regime.id || null,
      asOf: context.asOf || null,
      snapshotId: ident.snapshotId,
      revision: ident.revision
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
    if (!window.FeatureFlags || !FeatureFlags.isEnabled || !FeatureFlags.isEnabled('shadowOvernightIntraday')) return Promise.resolve(state);
    if (researchInflight) return researchInflight;
    if (!force && researchUpdatedAt && Date.now() - researchUpdatedAt < 15 * 60 * 1000) return Promise.resolve(state);
    var path = base() + '/research/overnight-intraday?market=all';
    var own = new AbortController(); researchController = own;
    var timeout = setTimeout(function () { own.abort(); }, force ? 660000 : 15000);
    researchInflight = fetch(path, { cache: 'no-store', signal: own.signal })
      .then(function (response) { return parseResponse(response, id, 'overnight_cache_response'); })
      .then(async function (cached) {
        if (!force || !canUpdateMarket()) return cached;
        trace('overnight_refresh_start', id, { scope: 'memory_v1', market: 'all' });
        if (!window.UpdateJobs) throw new Error('更新工作中心尚未載入');
        await UpdateJobs.refresh();
        if (own.signal.aborted) throw new Error('已停止等待研究更新');
        var accepted = await UpdateJobs.submit('research', { market: 'all', force: true });
        await UpdateJobs.wait(accepted.job.jobId, { signal: own.signal, timeoutMs: 650000 });
        return fetch(path, { cache: 'no-store', signal: own.signal })
          .then(function (response) { return parseResponse(response, id, 'overnight_refresh_response'); });
      })
      .then(function (payload) {
        if (own.signal.aborted) return state;
        researchUpdatedAt = Date.now();
        var current = state.context || context;
        if (payload && payload.ok && current && current.regime) publish(withOvernightResearch(current, payload), 'overnight-research', id, state.portfolioInputKey);
        return state;
      })
      .catch(function (error) {
        researchUpdatedAt = Date.now();
        trace('overnight_refresh_error', id, { error: String(error && error.message || error) });
        if (force && !own.signal.aborted) throw error;
        return state;
      })
      .finally(function () { clearTimeout(timeout); if (researchController === own) { researchController = null; researchInflight = null; } });
    return researchInflight;
  }

  function fromPulse(pulse, id) {
    var summary = pulse && pulse.decisionSummary;
    if (!summary || !summary.regime) {
      trace('pulse_summary_missing', id || null, { pulseOk: !!(pulse && pulse.ok) });
      return state;
    }
    // 避免以舊 revision 的 pulse summary 蓋掉較新 context；維持 summary 與 context 同序或較新。
    if (effectiveRevision(summary) < Math.max(effectiveRevision(state.context), effectiveRevision(state.summary))) {
      trace('pulse_summary_stale', id || null, {
        incomingRevision: effectiveRevision(summary),
        currentRevision: effectiveRevision(state.context)
      });
      return state;
    }
    if (state.context && effectiveRevision(summary) === effectiveRevision(state.context)) return state;
    var ident = identityFields(summary);
    state = {
      context: null,
      summary: summary,
      updatedAt: summary.asOf || pulse.updatedAt || state.updatedAt,
      contractVersion: summary.contractVersion || 1,
      snapshotId: ident.snapshotId,
      revision: ident.revision,
      inputHash: ident.inputHash,
      rulesDigest: ident.rulesDigest,
      persistence: ident.persistence,
      viewScope: ident.viewScope,
      parentSnapshotId: ident.parentSnapshotId,
      parentRevision: ident.parentRevision,
      portfolioInputKey: ident.portfolioInputKey
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
      portfolioKind: opts.portfolioKind || 'actual',
      portfolioInputStatus: personalized ? (opts.portfolioInputStatus || undefined) : undefined
    };
    var requestBody = JSON.stringify(input);
    var requestKey = requestBody + '|' + String(opts.portfolioInputKey || '');
    var strict = !!opts.strict;
    // 嚴格模式不共用快取；相同輸入才共用 inflight，不同參數 POST 各自獨立。
    if (!strict && !opts.force && !opts.signal && inflightMap[requestKey]) return inflightMap[requestKey];
    var sequence = ++requestSequence;
    var id = opts.correlationId || correlationId('context');
    var started = Date.now();
    var hasBody = personalized && !!(input.riskProfile || input.portfolioInputStatus || (input.holdings && input.holdings.length));
    var req = { cache: 'no-store' };
    if (opts.signal) req.signal = opts.signal;
    if (hasBody) {
      req.method = 'POST';
      req.headers = { 'Content-Type': 'application/json' };
      req.body = requestBody;
    }
    req.headers = Object.assign({}, req.headers || {}, { 'X-ST-Trace-ID': id });
    trace('context_request_start', id, {
      method: req.method || 'GET',
      path: '/decision/context',
      portfolioKind: opts.portfolioKind || null,
      holdingsCount: (opts.holdings || []).length,
      strict: strict,
      sequence: sequence
    });
    var requestPromise = fetch(base() + '/decision/context', req)
      .then(function (r) {
        return r.text().then(function (raw) {
          trace('context_response', id, {
            status: r.status,
            ok: r.ok,
            responseChars: raw.length,
            elapsedMs: Date.now() - started
          });
          if (!r.ok || !raw) {
            if (strict) {
              var error = new Error('DecisionContext HTTP ' + r.status);
              error.status = r.status;
              throw error;
            }
            return null;
          }
          try { return JSON.parse(raw); }
          catch (e) {
            trace('context_parse_error', id, { error: String(e && e.message || e) });
            if (strict) throw new Error('DecisionContext JSON invalid');
            return null;
          }
        });
      })
      .then(function (ctx) {
        // 取消後：即使 fetch 已回傳，也不得發布至 state。
        if ((opts.signal && opts.signal.aborted) || (opts.isCurrent && !opts.isCurrent())) {
          trace('context_response_discarded', id, { reason: 'aborted', sequence: sequence });
          return state;
        }
        // 更晚發起的請求若已存在，則丟棄此次世代，避免逆序覆蓋。
        if (sequence !== requestSequence) {
          trace('context_response_discarded', id, { reason: 'superseded', sequence: sequence });
          return state;
        }
        if (strict && (!ctx || !ctx.regime || ctx.ok === false)) {
          throw new Error('DecisionContext unavailable');
        }
        if (ctx) {
          var published = publish(ctx, hasBody ? 'profile' : 'refresh', id, opts.portfolioInputKey);
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
        if (strict) throw err;
        return state;
      })
      .finally(function () {
        if (inflightMap[requestKey] === requestPromise) delete inflightMap[requestKey];
      });
    if (!strict && !opts.signal) inflightMap[requestKey] = requestPromise;
    return requestPromise;
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
    stopResearchWait: function () { if (researchController) researchController.abort(); },
    trace: trace,
    correlationId: correlationId,
    traceKey: TRACE_KEY
  };
}());
