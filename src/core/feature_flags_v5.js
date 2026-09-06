/* Shadow / experimental feature flags — default OFF for main-path users. */
(function () {
  'use strict';

  var STORAGE_KEY = 'st_feature_flags_v1';
  var DEFAULTS = {
    shadowOvernightIntraday: false,
    shadowEarlyWarning: false,
    shadowConsensusAttention: false
  };
  var state = Object.assign({}, DEFAULTS);
  var serverFlags = null;
  var ready = false;

  function readLocal() {
    try {
      var parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (e) { return {}; }
  }

  function writeLocal(map) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(map)); } catch (e) {}
  }

  function mergeFlags(server, local) {
    var out = Object.assign({}, DEFAULTS);
    if (server && typeof server === 'object') {
      Object.keys(DEFAULTS).forEach(function (key) {
        if (typeof server[key] === 'boolean') out[key] = server[key];
      });
    }
    Object.keys(DEFAULTS).forEach(function (key) {
      if (typeof local[key] === 'boolean') out[key] = local[key];
    });
    return out;
  }

  function publish(reason) {
    window.dispatchEvent(new CustomEvent('featureFlags', {
      detail: { flags: state, reason: reason || 'update' }
    }));
  }

  function apply(next, reason) {
    state = Object.assign({}, DEFAULTS, next || {});
    publish(reason);
    return state;
  }

  function refresh() {
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    return fetch(base + '/features', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        serverFlags = payload && payload.flags ? payload.flags : null;
        ready = true;
        return apply(mergeFlags(serverFlags, readLocal()), 'server');
      })
      .catch(function () {
        ready = true;
        return apply(mergeFlags(null, readLocal()), 'local');
      });
  }

  function setLocal(key, enabled) {
    if (!DEFAULTS.hasOwnProperty(key)) return state;
    var local = readLocal();
    local[key] = !!enabled;
    writeLocal(local);
    return apply(mergeFlags(serverFlags, local), 'local-set');
  }

  function isEnabled(key) {
    return !!state[key];
  }

  window.FeatureFlags = {
    get: function () { return state; },
    defaults: function () { return Object.assign({}, DEFAULTS); },
    isEnabled: isEnabled,
    refresh: refresh,
    setLocal: setLocal,
    storageKey: STORAGE_KEY,
    ready: function () { return ready; }
  };

  apply(mergeFlags(null, readLocal()), 'boot');
  refresh();
}());
