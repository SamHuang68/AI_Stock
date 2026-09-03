// Stock Terminal — intraday cumulative-volume integrity helpers.
// Pure state machine: provider totals are never guessed into missing minutes.
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.IntradayVolumeV3 = api;
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var TW_OPEN_MINUTE = 9 * 60;
  var TW_CLOSE_MINUTE = 13 * 60 + 30;

  function nonNegative(value) {
    if (value == null || value === '') return null;
    var n = Number(value);
    return isFinite(n) && n >= 0 ? n : null;
  }

  function canonicalShares(quote) {
    quote = quote || {};
    var shares = nonNegative(quote.volumeShares);
    if (shares != null) return shares;
    var legacy = nonNegative(quote.volume);
    if (legacy == null) return null;
    var unit = String(quote.volumeUnit || 'lot').toLowerCase();
    if (unit === 'share') return legacy;
    return legacy * (nonNegative(quote.volumeLotSize) || 1000);
  }

  function createTracker(options) {
    options = options || {};
    var maxContinuityMs = nonNegative(options.maxContinuityMs) || 15000;
    var state = {};

    function clear(context, reason, seed) {
      seed = seed || {};
      var seedBucket = isFinite(Number(seed.bucket)) ? Number(seed.bucket) : null;
      var seedVolume = nonNegative(seed.volume) || 0;
      state = {
        context: context || null,
        source: null,
        bucket: seedBucket,
        baselineCum: null,
        baselineDisplayed: seedVolume,
        displayed: seedVolume,
        lastCum: null,
        lastSampleTimestampMs: null,
        lastReceivedAtMs: null,
        lastRequestSeq: null,
        forceRebaseReason: null,
        resetReason: reason || 'manual',
      };
      return snapshot();
    }

    function snapshot() {
      var out = {};
      Object.keys(state).forEach(function (key) { out[key] = state[key]; });
      return out;
    }

    function result(action, reason, accepted) {
      return {
        action: action,
        reason: reason,
        accepted: accepted !== false,
        volume: state.displayed || 0,
        state: snapshot(),
      };
    }

    function baseline(sample, reason, preserveCurrentBucket) {
      var sameBucket = preserveCurrentBucket && state.bucket === sample.bucket;
      var kept = sameBucket ? (state.displayed || 0) : 0;
      state.context = sample.context;
      state.source = sample.source;
      state.bucket = sample.bucket;
      state.baselineCum = sample.cumulative;
      state.baselineDisplayed = kept;
      state.displayed = kept;
      state.lastCum = sample.cumulative;
      state.lastSampleTimestampMs = sample.sampleTimestampMs;
      state.lastReceivedAtMs = sample.receivedAtMs;
      state.lastRequestSeq = sample.requestSeq;
      state.forceRebaseReason = null;
      state.resetReason = reason;
      return result('baseline', reason, true);
    }

    function observe(raw) {
      raw = raw || {};
      var sample = {
        context: String(raw.context || ''),
        source: String(raw.source || 'unknown'),
        bucket: Number(raw.bucket),
        cumulative: nonNegative(raw.cumulative),
        sampleTimestampMs: nonNegative(raw.sampleTimestampMs),
        receivedAtMs: nonNegative(raw.receivedAtMs),
        requestSeq: nonNegative(raw.requestSeq),
        realtime: raw.realtime !== false,
      };
      if (!sample.context || !isFinite(sample.bucket) || sample.cumulative == null) {
        return result('ignore', 'invalid_sample', false);
      }
      if (sample.requestSeq != null && state.lastRequestSeq != null &&
          sample.requestSeq <= state.lastRequestSeq) {
        return result('ignore', 'out_of_order_response', false);
      }
      if (!state.context || state.context !== sample.context) {
        return baseline(sample, state.context ? 'context_change' : 'initial', false);
      }
      if (state.lastCum == null) {
        return baseline(sample, state.resetReason || 'initial', true);
      }
      if (state.forceRebaseReason) {
        return baseline(sample, state.forceRebaseReason, true);
      }
      if (!sample.realtime) {
        return baseline(sample, 'allocation_unsafe_source', true);
      }
      if (state.source !== sample.source) {
        return baseline(sample, 'source_change', true);
      }
      if (sample.sampleTimestampMs != null && state.lastSampleTimestampMs != null &&
          sample.sampleTimestampMs < state.lastSampleTimestampMs) {
        return result('ignore', 'stale_sample', false);
      }
      if (sample.bucket < state.bucket) {
        return result('ignore', 'older_bucket', false);
      }
      if (sample.cumulative < state.lastCum) {
        return baseline(sample, 'counter_reset', true);
      }

      var bucketGap = Math.round((sample.bucket - state.bucket) / 60);
      var elapsed = (sample.receivedAtMs != null && state.lastReceivedAtMs != null)
        ? sample.receivedAtMs - state.lastReceivedAtMs : null;
      if (bucketGap > 1 || (bucketGap > 0 && elapsed != null && elapsed > maxContinuityMs)) {
        return baseline(sample, 'minute_gap', false);
      }
      if (sample.bucket > state.bucket) {
        // With uninterrupted polling the at-most-one-poll boundary delta is
        // assigned to the new minute. A larger gap is deliberately not guessed.
        state.bucket = sample.bucket;
        state.baselineCum = state.lastCum;
        state.baselineDisplayed = 0;
        state.displayed = Math.max(0, sample.cumulative - state.baselineCum);
      } else {
        state.displayed = state.baselineDisplayed +
          Math.max(0, sample.cumulative - state.baselineCum);
      }
      state.lastCum = sample.cumulative;
      state.lastSampleTimestampMs = sample.sampleTimestampMs;
      state.lastReceivedAtMs = sample.receivedAtMs;
      state.lastRequestSeq = sample.requestSeq;
      state.resetReason = null;
      return result('update', 'continuous', true);
    }

    function rebaseNext(reason) {
      state.forceRebaseReason = reason || 'suspended';
      return snapshot();
    }

    clear(null, 'init');
    return { reset: clear, rebaseNext: rebaseNext, observe: observe, state: snapshot };
  }

  function taipeiMinute(timestampSeconds) {
    var n = Number(timestampSeconds);
    if (!isFinite(n) || n <= 0) return null;
    var d = new Date((n + 8 * 3600) * 1000);
    return d.getUTCHours() * 60 + d.getUTCMinutes();
  }

  function taipeiDateKey(timestampSeconds) {
    var n = Number(timestampSeconds);
    if (!isFinite(n) || n <= 0) return null;
    var d = new Date((n + 8 * 3600) * 1000);
    return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()].join('-');
  }

  function isTwRegularSessionTimestamp(timestampSeconds) {
    var minute = taipeiMinute(timestampSeconds);
    return minute != null && minute >= TW_OPEN_MINUTE && minute <= TW_CLOSE_MINUTE;
  }

  function twRegularSessionTimestamp(timestampSeconds, options) {
    options = options || {};
    var n = Number(timestampSeconds);
    if (!isFinite(n) || n <= 0) return null;
    var minute = taipeiMinute(n);
    if (minute == null || minute < TW_OPEN_MINUTE) return null;
    var minuteBucket = Math.floor(n / 60) * 60;
    if (minute <= TW_CLOSE_MINUTE) return minuteBucket;
    if (options.clampAfterClose !== true) return null;
    return minuteBucket - (minute - TW_CLOSE_MINUTE) * 60;
  }

  function twRegularSessionBucket(timestampMs, chartOffsetSeconds) {
    var ms = Number(timestampMs);
    if (!isFinite(ms) || ms <= 0) return null;
    var timestamp = twRegularSessionTimestamp(ms / 1000);
    if (timestamp == null) return null;
    var offset = Number(chartOffsetSeconds);
    return timestamp + (isFinite(offset) ? offset : 0);
  }

  function sameTaipeiDate(firstTimestampSeconds, secondTimestampSeconds) {
    var first = taipeiDateKey(firstTimestampSeconds);
    var second = taipeiDateKey(secondTimestampSeconds);
    return first != null && second != null && first === second;
  }

  function filterTwRegularSession(candles, market) {
    var source = Array.isArray(candles) ? candles : [];
    if (market !== 'TW') {
      return { candles: source.slice(), dropped: 0, firstDroppedTime: null, lastDroppedTime: null };
    }
    var kept = [];
    var dropped = 0;
    var firstDroppedTime = null;
    var lastDroppedTime = null;
    source.forEach(function (candle) {
      if (candle && isTwRegularSessionTimestamp(candle.time)) {
        kept.push(candle);
        return;
      }
      dropped += 1;
      var time = candle && candle.time != null ? Number(candle.time) : null;
      if (firstDroppedTime == null) firstDroppedTime = time;
      lastDroppedTime = time;
    });
    return {
      candles: kept,
      dropped: dropped,
      firstDroppedTime: firstDroppedTime,
      lastDroppedTime: lastDroppedTime,
    };
  }

  function backfillClosingAuction(candles, meta, market) {
    if (market !== 'TW') return { applied: false, reason: 'not_tw' };
    if (!Array.isArray(candles) || candles.length < 2 || !meta) {
      return { applied: false, reason: 'insufficient' };
    }
    var total = nonNegative(meta.regularMarketVolume);
    var marketTime = nonNegative(meta.regularMarketTime);
    var last = candles[candles.length - 1] || {};
    var lastMinute = taipeiMinute(last.time);
    var marketMinute = taipeiMinute(marketTime);
    // Only a final 13:25–13:30 TW snapshot may absorb closing-auction volume.
    // During the session a delayed Yahoo tail is never a valid minute bucket.
    // The provider must explicitly attest that all earlier minute buckets are
    // present; otherwise the remainder may include any delayed/missing segment.
    if (meta.intradayVolumeComplete !== true ||
        total == null || marketMinute == null || marketMinute < 13 * 60 + 30 ||
        lastMinute == null || lastMinute < 13 * 60 + 25 || lastMinute > 13 * 60 + 30 ||
        taipeiDateKey(last.time) !== taipeiDateKey(marketTime)) {
      return { applied: false, reason: 'not_final_snapshot' };
    }
    var prior = 0;
    for (var i = 0; i < candles.length - 1; i++) prior += nonNegative(candles[i].volume) || 0;
    var remainder = total - prior;
    var current = nonNegative(last.volume) || 0;
    if (!(remainder > current)) return { applied: false, reason: 'no_positive_remainder' };
    last.volume = remainder;
    return { applied: true, reason: 'closing_auction', volume: remainder };
  }

  return {
    canonicalShares: canonicalShares,
    createTracker: createTracker,
    backfillClosingAuction: backfillClosingAuction,
    taipeiMinute: taipeiMinute,
    taipeiDateKey: taipeiDateKey,
    isTwRegularSessionTimestamp: isTwRegularSessionTimestamp,
    twRegularSessionTimestamp: twRegularSessionTimestamp,
    twRegularSessionBucket: twRegularSessionBucket,
    sameTaipeiDate: sameTaipeiDate,
    filterTwRegularSession: filterTwRegularSession,
    TW_OPEN_MINUTE: TW_OPEN_MINUTE,
    TW_CLOSE_MINUTE: TW_CLOSE_MINUTE,
  };
});
