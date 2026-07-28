// ============================================================
// chart_registry_v3.js — 與 server/chart_registry.py 對齊（H0）
// 格上報價／主序列選擇：绝不可 fallback 到右軸指數
// ============================================================
(function () {
  'use strict';

  const CHART_PRIMARY_KEYS = {
    '__TW_RATES__': 'discount',
    '__TW_MARGIN_MIX__': 'yoy',
    '__TW_MARGIN_CYCLE__': 'margin_ratio',
    '__US_RATES_CREDIT__': 'fedfunds',
    '__US_CPI_FIN__': 'us_cpi_yoy',
    '__MARGIN_RATIO__': 'margin_ratio',
  };
  const HOLDERS_PRIMARY_KEY = 'major_pct';
  const MACRO_TRACK_IDS = [
    '__TW_RATES__', '__TW_MARGIN_MIX__', '__TW_MARGIN_CYCLE__',
    '__US_RATES_CREDIT__', '__US_CPI_FIN__',
  ];

  function normalize(id) {
    return String(id || '').trim().toUpperCase();
  }

  function isHoldersChart(id) {
    const c = normalize(id);
    return c.indexOf('__HOLDERS_') === 0 && c.slice(-2) === '__';
  }

  function primaryKeyFor(chartId) {
    const cid = normalize(chartId);
    if (Object.prototype.hasOwnProperty.call(CHART_PRIMARY_KEYS, cid)) {
      return CHART_PRIMARY_KEYS[cid];
    }
    if (isHoldersChart(cid)) return HOLDERS_PRIMARY_KEY;
    return null;
  }

  function pickPrimarySeries(series, chartId) {
    const list = series || [];
    const want = primaryKeyFor(chartId);
    if (want) {
      const hit = list.find(s => s && s.key === want && s.points && s.points.length);
      if (hit) return hit;
    }
    return list.find(s => s && s.scale === 'left' && s.points && s.points.length) || null;
  }

  window.ChartRegistry = {
    CHART_PRIMARY_KEYS,
    HOLDERS_PRIMARY_KEY,
    MACRO_TRACK_IDS,
    primaryKeyFor,
    pickPrimarySeries,
    isHoldersChart,
    normalize,
  };
})();
