/* Shadow / experimental feature flags — default OFF for main-path users. */
(function () {
  'use strict';

  var STORAGE_KEY = 'st_feature_flags_v1';
  var DEFAULTS = {
    shadowOvernightIntraday: false,
    shadowEarlyWarning: false,
    shadowConsensusAttention: false,
    shadowConditionalExpectation: false,
    shadowChipPathState: false,
    shadowPeakObservation: true,
    shadowTouxin5d: true,
    shadowVolRegimeSwitch: false,
    shadowMultifactor: false,
    shadowMlExperiment: false
  };
  var serverFlags = Object.assign({}, DEFAULTS);
  var ready = false;

  function publish(reason) {
    window.dispatchEvent(new CustomEvent('featureFlags', {
      detail: { flags: serverFlags, serverFlags: serverFlags, reason: reason || 'update' }
    }));
  }

  function apply(next, reason) {
    serverFlags = Object.assign({}, DEFAULTS, next || {});
    publish(reason);
    return serverFlags;
  }

  function refresh() {
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    return fetch(base + '/features', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        ready = true;
        return apply((payload && payload.flags) || null, 'server');
      })
      .catch(function () {
        ready = true;
        return apply(null, 'offline');
      });
  }

  function isEnabled(key) {
    return !!serverFlags[key];
  }

  function enableHint(key) {
    var env = {
      shadowOvernightIntraday: 'ST_SHADOW_OVERNIGHT_INTRADAY=1',
      shadowEarlyWarning: 'ST_SHADOW_EARLY_WARNING=1',
      shadowConsensusAttention: 'ST_SHADOW_CONSENSUS_ATTENTION=1',
      shadowConditionalExpectation: 'ST_SHADOW_CONDITIONAL_EXPECTATION=1',
      shadowChipPathState: 'ST_SHADOW_CHIP_PATH_STATE=1',
      shadowPeakObservation: 'ST_SHADOW_PEAK_OBSERVATION=1（預設開啟；設 0 關閉）',
      shadowTouxin5d: 'ST_SHADOW_TOUXIN_5D=1（預設開啟；設 0 關閉）',
      shadowVolRegimeSwitch: 'ST_SHADOW_VOL_REGIME_SWITCH=1',
      shadowMultifactor: 'ST_SHADOW_MULTIFACTOR=1',
      shadowMlExperiment: 'ST_SHADOW_ML_EXPERIMENT=1'
    };
    return '伺服器旗標關閉。請設定 ' + (env[key] || 'ST_ENABLE_SHADOW_RESEARCH=1') +
      ' 或 data/feature_flags.local.json 後重新啟動伺服器。';
  }

  window.FeatureFlags = {
    get: function () { return serverFlags; },
    getServer: function () { return serverFlags; },
    defaults: function () { return Object.assign({}, DEFAULTS); },
    isEnabled: isEnabled,
    enableHint: enableHint,
    refresh: refresh,
    storageKey: STORAGE_KEY,
    ready: function () { return ready; }
  };

  try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  apply(null, 'boot');
  refresh();
}());
