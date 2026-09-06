/* Per-quote asOf freshness helpers for MarketData / Pulse / shell health. */
(function () {
  'use strict';

  function parseAsOf(value) {
    if (!value) return null;
    var raw = String(value).trim();
    if (!raw) return null;
    var ms = Date.parse(raw);
    return Number.isFinite(ms) ? ms : null;
  }

  function quoteAsOf(quote) {
    if (!quote || typeof quote !== 'object') return null;
    var market = quote.market;
    if (market && market.asOf) return parseAsOf(market.asOf);
    return parseAsOf(quote.asOf);
  }

  function quoteSession(quote) {
    if (!quote || typeof quote !== 'object') return null;
    var market = quote.market;
    return (market && market.session) || quote.session || null;
  }

  function quoteSource(quote) {
    if (!quote || typeof quote !== 'object') return null;
    var market = quote.market;
    return (market && market.source) || quote.source || null;
  }

  function summarizeQuote(symbol, quote) {
    var asOfMs = quoteAsOf(quote);
    return {
      symbol: symbol || null,
      asOf: asOfMs ? new Date(asOfMs).toISOString() : null,
      session: quoteSession(quote),
      source: quoteSource(quote)
    };
  }

  function worstAsOfMs(quotes) {
    var rows = quotes && typeof quotes === 'object' ? Object.keys(quotes) : [];
    var values = [];
    rows.forEach(function (key) {
      var ms = quoteAsOf(quotes[key]);
      if (ms != null) values.push(ms);
    });
    if (!values.length) return null;
    return Math.min.apply(null, values);
  }

  function freshnessClass(ageSeconds) {
    if (ageSeconds == null || !Number.isFinite(ageSeconds)) return 'unknown';
    if (ageSeconds <= 120) return 'fresh';
    if (ageSeconds <= 900) return 'delayed';
    return 'stale';
  }

  function snapshotSummary(snapshot) {
    var quotes = (snapshot && snapshot.quotes) || {};
    var worstMs = worstAsOfMs(quotes);
    var generatedMs = parseAsOf(snapshot && snapshot.generatedAt);
    var now = Date.now();
    var ageSeconds = worstMs != null ? Math.max(0, (now - worstMs) / 1000) : null;
    var perQuote = {};
    Object.keys(quotes).forEach(function (key) {
      perQuote[key] = summarizeQuote(key, quotes[key]);
    });
    return {
      worstAsOf: worstMs ? new Date(worstMs).toISOString() : null,
      marketAsOf: snapshot && (snapshot.marketAsOf || snapshot.updatedAt) || null,
      generatedAt: snapshot && snapshot.generatedAt || null,
      session: snapshot && snapshot.session || 'unknown',
      ageSeconds: ageSeconds == null ? null : Math.round(ageSeconds * 10) / 10,
      freshness: freshnessClass(ageSeconds),
      perQuote: perQuote
    };
  }

  function formatCompact(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').replace('+00:00', 'Z').slice(0, 19);
  }

  function shellHealthText(summary) {
    summary = summary || {};
    if (!summary.worstAsOf) return { mode: 'warn', text: 'LOCAL' };
    var fresh = summary.freshness || 'unknown';
    var mode = fresh === 'stale' ? 'err' : (fresh === 'delayed' ? 'warn' : 'ok');
    var sess = summary.session && summary.session !== 'unknown' ? (' · ' + summary.session) : '';
    return {
      mode: mode,
      text: formatCompact(summary.worstAsOf) + sess
    };
  }

  window.MarketFreshness = {
    parseAsOf: parseAsOf,
    quoteAsOf: quoteAsOf,
    quoteSession: quoteSession,
    quoteSource: quoteSource,
    worstAsOfMs: worstAsOfMs,
    freshnessClass: freshnessClass,
    snapshotSummary: snapshotSummary,
    formatCompact: formatCompact,
    shellHealthText: shellHealthText
  };
}());
