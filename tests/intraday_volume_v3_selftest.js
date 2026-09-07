const fs = require('fs');
const path = require('path');
const volume = require(path.resolve(__dirname, '..', 'src/core/intraday_volume_v3.js'));

function ok(value, message) {
  if (!value) throw new Error('FAIL ' + message);
  console.log('OK  ', message);
}
function eq(actual, expected, message) {
  ok(JSON.stringify(actual) === JSON.stringify(expected),
    message + ' (actual=' + JSON.stringify(actual) + ', expected=' + JSON.stringify(expected) + ')');
}
function sample(tracker, values) {
  return tracker.observe(Object.assign({
    context: '00685L', source: 'twse-mis', bucket: 100 * 60,
    sampleTimestampMs: 100000, receivedAtMs: 100000, requestSeq: 1,
    realtime: true,
  }, values));
}
function twEpoch(hour, minute, second) {
  return Date.UTC(2026, 7, 17, hour - 8, minute, second || 0) / 1000;
}

eq(volume.canonicalShares({ volume: 151164, volumeUnit: 'lot', volumeLotSize: 1000 }),
  151164000, 'MIS legacy lots normalize to shares');
eq(volume.canonicalShares({ volume: 147122.573, volumeShares: 147122573, volumeUnit: 'lot' }),
  147122573, 'canonical Yahoo odd-lot shares are not multiplied again');
eq(volume.canonicalShares({ volume: null }), null, 'missing cumulative volume remains missing');

ok(volume.isTwRegularSessionTimestamp(twEpoch(9, 0)), 'TW regular session includes the 09:00 open');
ok(volume.isTwRegularSessionTimestamp(twEpoch(13, 30)), 'TW regular session includes the 13:30 closing auction');
ok(!volume.isTwRegularSessionTimestamp(twEpoch(8, 59)), 'TW regular session rejects pre-open bars');
ok(!volume.isTwRegularSessionTimestamp(twEpoch(13, 31)), 'TW regular session rejects every post-close minute');
eq(volume.twRegularSessionTimestamp(twEpoch(13, 40), { clampAfterClose: true }),
  twEpoch(13, 30), 'post-close synthetic fallback is capped at the 13:30 close');
eq(volume.twRegularSessionBucket(twEpoch(13, 30) * 1000, 8 * 3600),
  twEpoch(13, 30) + 8 * 3600, 'realtime chart bucket uses the exchange timestamp');
eq(volume.twRegularSessionBucket(twEpoch(13, 40) * 1000, 8 * 3600), null,
  'a 13:40 exchange timestamp cannot create a realtime bar');
ok(volume.sameTaipeiDate(twEpoch(9, 0), twEpoch(13, 30)), 'same Taiwan trade date is accepted');
ok(!volume.sameTaipeiDate(twEpoch(13, 30), twEpoch(13, 30) + 86400),
  'a prior-day quote is rejected after the next open');

const sessionBars = [8 * 60 + 59, 9 * 60, 13 * 60 + 30, 13 * 60 + 31]
  .map(minute => ({ time: twEpoch(Math.floor(minute / 60), minute % 60), close: minute }));
let sessionOut = volume.filterTwRegularSession(sessionBars, 'TW');
eq([sessionOut.candles.map(x => x.close), sessionOut.dropped], [[540, 810], 2],
  'TW historical bars are filtered to 09:00–13:30 before render');
sessionOut = volume.filterTwRegularSession(sessionBars, 'US');
eq([sessionOut.candles.length, sessionOut.dropped], [4, 0], 'US extended-session data is not changed by the TW contract');

let t = volume.createTracker({ maxContinuityMs: 15000 });
let out = [];
out.push(sample(t, { cumulative: 146000000 }).volume);
out.push(sample(t, { cumulative: 146010000, sampleTimestampMs: 103000, receivedAtMs: 103000, requestSeq: 2 }).volume);
out.push(sample(t, { cumulative: 146090000, source: 'yahoo-v8-chart', sampleTimestampMs: 106000, receivedAtMs: 106000, requestSeq: 3 }).volume);
out.push(sample(t, { cumulative: 146095000, source: 'yahoo-v8-chart', sampleTimestampMs: 109000, receivedAtMs: 109000, requestSeq: 4 }).volume);
eq(out, [0, 10000, 10000, 15000], 'source switch re-baselines without erasing accepted minute volume');

t = volume.createTracker({ maxContinuityMs: 15000 });
sample(t, { cumulative: 146000000 });
sample(t, { cumulative: 146010000, sampleTimestampMs: 103000, receivedAtMs: 103000, requestSeq: 2 });
out = sample(t, { cumulative: 146090000, source: 'yahoo-v8-chart', realtime: false,
  sampleTimestampMs: 106000, receivedAtMs: 106000, requestSeq: 3 });
eq(out.volume, 10000, 'allocation-unsafe Yahoo total cannot add delayed volume');
out = sample(t, { cumulative: 146095000, source: 'yahoo-v8-chart', realtime: false,
  sampleTimestampMs: 109000, receivedAtMs: 109000, requestSeq: 4 });
eq(out.volume, 10000, 'repeated unsafe totals remain baseline-only');

t = volume.createTracker({ maxContinuityMs: 15000 });
sample(t, { cumulative: 146000000 });
sample(t, { cumulative: 146010000, sampleTimestampMs: 103000, receivedAtMs: 103000, requestSeq: 2 });
out = sample(t, { cumulative: 146500000, bucket: 115 * 60,
  sampleTimestampMs: 1000000, receivedAtMs: 1000000, requestSeq: 3 });
eq([out.reason, out.volume], ['minute_gap', 0], 'hidden/skipped interval total is not assigned to resume minute');
out = sample(t, { cumulative: 146505000, bucket: 115 * 60,
  sampleTimestampMs: 1003000, receivedAtMs: 1003000, requestSeq: 4 });
eq(out.volume, 5000, 'post-gap same-minute delta resumes from the new baseline');

t = volume.createTracker();
sample(t, { cumulative: 146000000 });
sample(t, { cumulative: 146010000, sampleTimestampMs: 103000, receivedAtMs: 103000, requestSeq: 2 });
out = sample(t, { cumulative: 100000, sampleTimestampMs: 106000, receivedAtMs: 106000, requestSeq: 3 });
eq([out.reason, out.volume], ['counter_reset', 10000], 'counter reset preserves the current accepted volume');
out = sample(t, { cumulative: 110000, sampleTimestampMs: 109000, receivedAtMs: 109000, requestSeq: 4 });
eq(out.volume, 20000, 'counter resumes from its new baseline');

t = volume.createTracker();
sample(t, { cumulative: 100000, requestSeq: 2 });
out = sample(t, { cumulative: 110000, requestSeq: 1, sampleTimestampMs: 103000, receivedAtMs: 103000 });
eq([out.accepted, out.reason], [false, 'out_of_order_response'], 'late response cannot mutate tracker state');

t = volume.createTracker();
sample(t, { cumulative: 100000, requestSeq: 1, sampleTimestampMs: 103000 });
out = sample(t, { cumulative: 110000, requestSeq: 2, sampleTimestampMs: 102000, receivedAtMs: 104000 });
eq([out.accepted, out.reason], [false, 'stale_sample'], 'exchange timestamp rollback is rejected');

t = volume.createTracker({ maxContinuityMs: 15000 });
sample(t, { cumulative: 100000, bucket: 100 * 60, receivedAtMs: 100000 });
out = sample(t, { cumulative: 103000, bucket: 101 * 60,
  sampleTimestampMs: 103000, receivedAtMs: 103000, requestSeq: 2 });
eq(out.volume, 3000, 'normal adjacent-minute polling keeps its small boundary delta');

t = volume.createTracker();
sample(t, { cumulative: 100000 });
sample(t, { cumulative: 110000, requestSeq: 2, sampleTimestampMs: 103000, receivedAtMs: 103000 });
t.rebaseNext('visibility_resume');
out = sample(t, { cumulative: 500000, bucket: 115 * 60,
  requestSeq: 3, sampleTimestampMs: 1000000, receivedAtMs: 1000000 });
eq([out.reason, out.volume], ['visibility_resume', 0], 'foreground resume first sample is baseline-only');

const beforeClose = [
  { time: Date.UTC(2026, 7, 17, 1, 0) / 1000, volume: 20 },
  { time: Date.UTC(2026, 7, 17, 4, 28) / 1000, volume: 18 },
];
out = volume.backfillClosingAuction(beforeClose, {
  regularMarketTime: Date.UTC(2026, 7, 17, 4, 48) / 1000,
  regularMarketVolume: 100,
}, 'TW');
eq([out.applied, beforeClose[1].volume], [false, 18], '12:48 delayed tail is never remainder-filled');

const closeBars = [
  { time: Date.UTC(2026, 7, 17, 1, 0) / 1000, volume: 20 },
  { time: Date.UTC(2026, 7, 17, 5, 25) / 1000, volume: 18 },
];
out = volume.backfillClosingAuction(closeBars, {
  regularMarketTime: Date.UTC(2026, 7, 17, 5, 30) / 1000,
  regularMarketVolume: 100,
}, 'TW');
eq([out.applied, closeBars[1].volume], [false, 18], 'even after close, an unattested minute series fails closed');
out = volume.backfillClosingAuction(closeBars, {
  regularMarketTime: Date.UTC(2026, 7, 17, 5, 30) / 1000,
  regularMarketVolume: 100,
  intradayVolumeComplete: true,
}, 'TW');
eq([out.applied, closeBars[1].volume], [true, 80], 'explicit complete close snapshot may absorb auction remainder');

const root = path.resolve(__dirname, '..');
const shell = fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8');
const multi = fs.readFileSync(path.join(root, 'src/chart/multichart_v3.js'), 'utf8');
const realtime = fs.readFileSync(path.join(root, 'src/core/realtime_v3.js'), 'utf8');
ok(/_volumeUnknown:\s*true/.test(shell) && /volume:\s*0/.test(shell),
  'synthetic intraday quote never maps session cumulative volume to one minute');
ok(!/const _rem = _rmv - _sumEx/.test(shell) && !/const _rem = _rmv - _sumEx/.test(multi),
  'main and multi-chart have no unconditional intraday remainder allocator');
ok(/backfillClosingAuction/.test(shell) && /backfillClosingAuction/.test(multi),
  'all intraday chart surfaces share the same fail-closed auction gate');
ok(/filterTwRegularSession/.test(shell) && /filterTwRegularSession/.test(multi),
  'main and multi-chart filter TW intraday history through one regular-session contract');
ok(/IntradayVolumeV3 && !_isTxf/.test(shell) && /IntradayVolumeV3 && !_isTxf/.test(multi),
  'TXF 1-day keeps night minutes outside the cash 09:00-13:30 filter');
ok(/twRegularSessionBucket\(sampleTimestampMs, off\)/.test(realtime) &&
   !/Math\.floor\(Date\.now\(\) \/ 1000 \/ 60\) \* 60 \+ off/.test(realtime),
  'realtime bars use the exchange timestamp rather than browser receipt time');
ok(!/hm\s*<=\s*820/.test(realtime) && /hm\s*<=\s*810/.test(realtime),
  'realtime poll window ends at 13:30 instead of the old 13:40 grace period');
ok(/intraday_session_rejected/.test(realtime) && /intraday_session_filtered/.test(shell),
  'session rejects and historical cleanup remain observable in persistent UI diagnostics');

console.log('intraday_volume_v3_selftest PASSED');
