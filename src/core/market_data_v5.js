/* Canonical market headline store. One fetch, one event, many renderers. */
(function () {
  'use strict';
  var state = { quotes: {}, updatedAt: null, contractVersion: 1 };
  var inflight = null;
  function base() { return window.SERVER || location.origin || 'http://localhost:18432'; }
  function publish(snapshot, reason) {
    if (!snapshot || !snapshot.quotes) return state;
    state = { quotes: snapshot.quotes, updatedAt: snapshot.updatedAt || new Date().toISOString(), contractVersion: snapshot.contractVersion || 1 };
    window.dispatchEvent(new CustomEvent('marketData', { detail: { snapshot: state, reason: reason || 'refresh' } }));
    return state;
  }
  function fromPulse(pulse) {
    if (!pulse) return state;
    if (pulse.marketSnapshot && pulse.marketSnapshot.quotes) return publish(pulse.marketSnapshot, 'pulse');
    var indices = pulse.indices || {}, quotes = {};
    [['t00', '^TWII'], ['o00', '^TWOII']].forEach(function (pair) {
      var q = indices[pair[0]];
      if (q && q.market) quotes[pair[1]] = q;
    });
    if (pulse.txf && pulse.txf.market) quotes.__TXF__ = pulse.txf;
    return Object.keys(quotes).length ? publish({ quotes: quotes, updatedAt: pulse.updatedAt }, 'pulse') : state;
  }
  function refresh() {
    if (inflight) return inflight;
    inflight = fetch(base() + '/market/snapshot', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (x) { if (x && x.ok) publish(x, 'snapshot'); return state; })
      .catch(function () { return state; })
      .finally(function () { inflight = null; });
    return inflight;
  }
  window.MarketData = { get: function () { return state; }, publish: publish, fromPulse: fromPulse, refresh: refresh };
}());
