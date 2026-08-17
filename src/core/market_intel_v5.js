/* Shared theme resonance and news-to-watchlist linkage.
 * One taxonomy feeds Pulse opportunity lights and Decision News Impact.
 */
(function () {
  'use strict';

  var THEME_RULES = [
    {
      id: 'memory', label: '記憶體',
      symbols: ['MU', 'SNDK', 'WDC', 'STX', '2408', '2344', '2337', '3006', '8299'],
      words: ['記憶體', 'DRAM', 'NAND', '美光', 'MICRON', 'SANDISK', '南亞科', '華邦電', '旺宏', '群聯']
    },
    {
      id: 'ai_chip', label: 'AI 晶片',
      symbols: ['NVDA', 'AMD', 'TSM', 'AVGO', '2330', '2454', '3661', '6669', '3017', '3443', '6223', '5347'],
      words: ['AI晶片', 'AI 晶片', '半導體', '晶片', 'GPU', '台積電', '聯發科', '世芯', '創意', '緯穎', '雍智']
    }
  ];
  var TIER_RANK = { HIGH: 3, MEDIUM: 2, LOW: 1 };
  var PROPAGATION_WORDS = [
    '財測', '展望', '營收', '需求', '訂單', '供應', '擴產', '產能', '產品', '出貨', '報價',
    'guidance', 'forecast', 'outlook', 'earnings', 'revenue', 'demand', 'order', 'supply',
    'capacity', 'product', 'shipment', 'dram', 'nand'
  ];
  var CAPITAL_EVENT_WORDS = [
    '發債', '債券', '募資', '增資', '配股', '可轉債', '庫藏股',
    'debt', 'bond', 'offering', 'issuance', 'financing', 'convertible', 'buyback'
  ];

  function normSymbol(value) {
    return String(value || '').trim().toUpperCase().replace(/\.(TW|TWO)$/, '');
  }

  function haystack(value) {
    return String(value || '').toUpperCase();
  }

  function themeFor(value) {
    value = value || {};
    var sym = normSymbol(value.t || value.code || value.symbol);
    var hay = [sym, value.name, value.industry, value.sector, value.theme, value.title]
      .map(haystack).join(' ');
    for (var i = 0; i < THEME_RULES.length; i++) {
      var rule = THEME_RULES[i];
      if (rule.symbols.indexOf(sym) >= 0 || rule.words.some(function (word) {
        return hay.indexOf(haystack(word)) >= 0;
      })) return rule;
    }
    return null;
  }

  function quoteFor(row, quotes) {
    var sym = normSymbol(row && (row.t || row.code || row.symbol));
    return (quotes && (quotes[sym] || quotes[sym + '.TW'] || quotes[sym + '.TWO'])) || {};
  }

  function buildThemeResonance(watchlist, quotes) {
    var groups = {};
    (watchlist || []).forEach(function (row) {
      var theme = themeFor(row);
      if (!theme) return;
      var quote = quoteFor(row, quotes);
      var raw = quote.changePct != null ? quote.changePct : row.chg;
      var change = Number(raw);
      if (!isFinite(change)) return;
      var item = { symbol: normSymbol(row.t || row.code || row.symbol), changePct: change };
      (groups[theme.id] || (groups[theme.id] = { id: theme.id, label: theme.label, rows: [] })).rows.push(item);
    });
    var signals = Object.keys(groups).map(function (id) {
      var group = groups[id];
      var active = group.rows.filter(function (row) { return Math.abs(row.changePct) >= 0.15; });
      if (active.length < 2) return null;
      var up = active.filter(function (row) { return row.changePct > 0; });
      var down = active.filter(function (row) { return row.changePct < 0; });
      var dominant = up.length >= down.length ? up : down;
      var direction = up.length >= down.length ? 'bull' : 'bear';
      var participation = dominant.length / active.length;
      var avgAbs = dominant.reduce(function (sum, row) { return sum + Math.abs(row.changePct); }, 0) / dominant.length;
      var score = Math.round(Math.min(100, participation * 70 + Math.min(1, avgAbs / 6) * 30));
      if (dominant.length < 2 || participation < 0.66 || score < 60) return null;
      return {
        id: group.id, label: group.label, direction: direction, score: score,
        sameCount: dominant.length, totalCount: active.length,
        averageAbsPct: Math.round(avgAbs * 100) / 100,
        symbols: dominant.map(function (row) { return row.symbol; })
      };
    }).filter(Boolean).sort(function (a, b) { return b.score - a.score; });
    var bySymbol = {};
    signals.forEach(function (signal) {
      signal.symbols.forEach(function (sym) { if (!bySymbol[sym]) bySymbol[sym] = signal; });
    });
    return { leaders: signals, bySymbol: bySymbol };
  }

  function propagationEligible(item) {
    var text = String((item && item.title) || '').toLowerCase();
    if (CAPITAL_EVENT_WORDS.some(function (word) {
      return text.indexOf(String(word).toLowerCase()) >= 0;
    })) return false;
    return PROPAGATION_WORDS.some(function (word) { return text.indexOf(String(word).toLowerCase()) >= 0; });
  }

  function linkNewsToWatchlist(news, watchlist) {
    var watches = (watchlist || []).map(function (row) {
      return { row: row, symbol: normSymbol(row.t || row.code || row.symbol), theme: themeFor(row) };
    }).filter(function (row) { return row.symbol; });
    var links = [];
    (news || []).forEach(function (item, newsIndex) {
      if (!item) return;
      var code = normSymbol(item.code || item.symbol);
      var impact = item.impact || {};
      var tier = String(impact.tier || 'LOW').toUpperCase();
      var newsTheme = themeFor(item);
      var allowTheme = !!newsTheme && propagationEligible(item);
      var seen = {};
      watches.forEach(function (watch) {
        var match = null;
        if (code && watch.symbol === code) match = 'direct';
        else if (allowTheme && watch.theme && watch.theme.id === newsTheme.id) match = 'theme';
        if (!match || seen[watch.symbol]) return;
        seen[watch.symbol] = true;
        links.push({
          symbol: watch.symbol, name: watch.row.name || watch.symbol,
          market: watch.row.m || watch.row.mkt || (watch.symbol.match(/^\d/) ? 'TW' : 'US'),
          match: match, theme: newsTheme ? newsTheme.label : null,
          tier: tier, tierRank: TIER_RANK[tier] || 1, newsIndex: newsIndex,
          code: code || null, title: item.title || '', source: impact.source || item.source || 'unknown'
        });
      });
    });
    links.sort(function (a, b) { return b.tierRank - a.tierRank || a.newsIndex - b.newsIndex; });
    var bySymbol = {}, byNews = {};
    links.forEach(function (link) {
      (bySymbol[link.symbol] || (bySymbol[link.symbol] = [])).push(link);
      (byNews[link.newsIndex] || (byNews[link.newsIndex] = [])).push(link);
    });
    return { links: links, bySymbol: bySymbol, byNews: byNews };
  }

  window.MarketIntelV5 = {
    themeRules: THEME_RULES.slice(),
    themeFor: themeFor,
    buildThemeResonance: buildThemeResonance,
    linkNewsToWatchlist: linkNewsToWatchlist
  };
})();
