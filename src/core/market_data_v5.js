/* Canonical market headline store. One fetch, one event, many renderers. */
(function () {
  'use strict';
  var state = {
    quotes: {}, updatedAt: null, marketAsOf: null, generatedAt: null,
    sessionDate: null, session: 'unknown', sourceStatus: {}, contractVersion: 2,
    freshness: null, worstAsOf: null
  };
  var inflight = null;
  function base() { return window.SERVER || location.origin || 'http://localhost:18432'; }
  function attachFreshness(snapshot) {
    if (!window.MarketFreshness || !MarketFreshness.snapshotSummary) return snapshot;
    var summary = MarketFreshness.snapshotSummary(snapshot);
    snapshot.freshness = summary;
    snapshot.worstAsOf = summary.worstAsOf;
    return snapshot;
  }
  function publish(snapshot, reason) {
    if (!snapshot || !snapshot.quotes) return state;
    attachFreshness(snapshot);
    state = {
      quotes: snapshot.quotes,
      updatedAt: snapshot.marketAsOf || snapshot.updatedAt || null,
      marketAsOf: snapshot.marketAsOf || snapshot.updatedAt || null,
      generatedAt: snapshot.generatedAt || null,
      sessionDate: snapshot.sessionDate || null,
      session: snapshot.session || 'unknown',
      sourceStatus: snapshot.sourceStatus || {},
      contractVersion: snapshot.contractVersion || 2,
      freshness: snapshot.freshness || null,
      worstAsOf: snapshot.worstAsOf || null
    };
    window.dispatchEvent(new CustomEvent('marketData', { detail: { snapshot: state, reason: reason || 'refresh' } }));
    return state;
  }
  function fromPulse(pulse) {
    if (!pulse) return state;
    if (pulse.marketSnapshot && pulse.marketSnapshot.quotes) {
      return publish(pulse.marketSnapshot, 'pulse');
    }
    var indices = pulse.indices || {}, quotes = {};
    [['t00', '^TWII'], ['o00', '^TWOII']].forEach(function (pair) {
      var q = indices[pair[0]];
      if (q && q.market) quotes[pair[1]] = q;
    });
    if (pulse.txf && pulse.txf.market) quotes.__TXF__ = pulse.txf;
    if (!Object.keys(quotes).length) return state;
    return publish({
      quotes: quotes,
      generatedAt: pulse.updatedAt || null,
      marketAsOf: pulse.updatedAt || null,
      sessionDate: null,
      session: 'unknown',
      sourceStatus: {},
      contractVersion: 2
    }, 'pulse');
  }
  function refresh() {
    if (inflight) return inflight;
    var request = window.AppKernel && window.AppKernel.api
      ? window.AppKernel.api.getJson('/market/snapshot', { timeoutMs: 12000 })
      : fetch(base() + '/market/snapshot', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; });
    inflight = request
      .then(function (x) { if (x && x.ok) publish(x, 'snapshot'); return state; })
      .catch(function () { return state; })
      .finally(function () { inflight = null; });
    return inflight;
  }
  window.MarketData = { get: function () { return state; }, publish: publish, fromPulse: fromPulse, refresh: refresh };
}());
