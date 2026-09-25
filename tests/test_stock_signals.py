# -*- coding: utf-8 -*-
"""個股訊號引擎（st-stock-signals/v1）：事件、生命週期、PIT、體檢、推播與 HTTP 契約。"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import signal_digest  # noqa: E402
import stock_signals as ss  # noqa: E402
import stock_signals_routes as routes  # noqa: E402

TPE = timezone(timedelta(hours=8))


def make_bars(closes, vols=None, start=date(2024, 1, 1)):
    """由收盤價產生工作日日 K（high/low 為 ±1%）。"""
    out, d = [], start
    for i, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({'date': d.isoformat(), 'open': c, 'high': c * 1.01, 'low': c * 0.99,
                    'close': float(c), 'volume': float(vols[i] if vols else 1000.0)})
        d += timedelta(days=1)
    return out


def random_walk(seed, n=400, drift=0.0004, vol=0.018, start=100.0):
    rnd = random.Random(seed)
    px, out = start, []
    for _ in range(n):
        px *= 1 + rnd.gauss(drift, vol)
        out.append(px)
    return out


class NormalizeTests(unittest.TestCase):
    def test_tuple_rows_sorted_and_deduped_by_fuller_bar(self):
        ts = int(datetime(2026, 9, 24, 9, 0, tzinfo=TPE).timestamp())
        partial = int(datetime(2026, 9, 24, 12, 30, tzinfo=TPE).timestamp())
        rows = [(ts + 86400, 10, 11, 9, 10.5, 500), (partial, 10, 10.2, 9.9, 10.1, 300),
                (ts, 10, 10.4, 9.8, 10.2, 900), (ts - 86400, 9, 9, 9, None, 1)]
        bars = ss.normalize_bars(rows, 'TW')
        self.assertEqual([b['date'] for b in bars], ['2026-09-24', '2026-09-25'])
        self.assertEqual(bars[0]['volume'], 900)   # 完整日 K 勝過盤中快照
        self.assertEqual(bars[0]['close'], 10.2)

    def test_bar_date_uses_exchange_timezone(self):
        ts = int(datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc).timestamp())
        self.assertEqual(ss.bar_date(ts, 'TW'), '2026-09-25')
        self.assertEqual(ss.bar_date(ts, 'US'), '2026-09-24')


class DetectorTests(unittest.TestCase):
    def _frame(self, closes, vols=None):
        return ss.build_frame(make_bars(closes, vols))

    def test_reclaim_ma60_fires_only_on_the_cross(self):
        closes = [100.0] * 60 + [99.0] * 5 + [101.5, 102.0]
        f = self._frame(closes)
        spec = ss.SIGNAL_BY_ID['trend_reclaim_ma60']
        self.assertIsNotNone(spec['detect'](f, 65))
        self.assertIsNone(spec['detect'](f, 66))   # 已在季線上，不再重複觸發

    def test_golden_cross(self):
        closes = [100 - 0.1 * i for i in range(80)] + [92 + 0.6 * i for i in range(40)]
        f = self._frame(closes)
        hits = ss.event_indices(f, ss.SIGNAL_BY_ID['trend_golden_cross'])
        self.assertTrue(hits)
        i = hits[0]
        self.assertGreater(f['sma20'][i], f['sma60'][i])
        self.assertLessEqual(f['sma20'][i - 1], f['sma60'][i - 1])

    def test_rsi_rebound_is_a_cross_not_a_level(self):
        closes = [100.0]
        for i in range(40):
            closes.append(closes[-1] * (1.012 if i % 2 == 0 else 0.99))
        for _ in range(5):
            closes.append(closes[-1] * 0.975)
        closes.append(closes[-1] * 1.02)
        f = self._frame([100.0] * 30 + closes)
        spec = ss.SIGNAL_BY_ID['mom_rsi_rebound']
        last = len(f['close']) - 1
        self.assertLess(f['rsi'][last - 1], 30)
        self.assertGreaterEqual(f['rsi'][last], 30)
        hit = spec['detect'](f, last)
        self.assertIsNotNone(hit)
        self.assertEqual(hit['level'], min(f['low'][last - 10: last + 1]))

    def test_breakout_requires_volume(self):
        closes = [100.0 + (i % 5) * 0.2 for i in range(60)] + [104.0]
        quiet = self._frame(closes, [1000.0] * 61)
        loud = self._frame(closes, [1000.0] * 60 + [2500.0])
        spec = ss.SIGNAL_BY_ID['vol_breakout_20d']
        self.assertIsNone(spec['detect'](quiet, 60))
        hit = spec['detect'](loud, 60)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit['level'], max(loud['high'][40:60]))

    def test_chip_streak_needs_a_known_fourth_day(self):
        bars = make_bars([100.0] * 80)
        spec = ss.SIGNAL_BY_ID['chip_trust_buy3']
        # 只有 3 天籌碼：無法確定是「剛好第 3 天」
        chips = [{'date': b['date'], 'trust': 1000.0, 'foreign': 0.0} for b in bars[-3:]]
        f = ss.build_frame(bars, chips)
        self.assertIsNone(spec['detect'](f, 79))
        chips = [{'date': bars[-4]['date'], 'trust': -5.0, 'foreign': 0.0}] + chips
        f = ss.build_frame(bars, chips)
        self.assertIsNotNone(spec['detect'](f, 79))
        self.assertIsNone(spec['detect'](f, 78))


class PointInTimeTests(unittest.TestCase):
    def test_detection_never_uses_future_bars(self):
        bars = make_bars(random_walk(21, 420), [1000 + (i * 37) % 900 for i in range(420)])
        full = ss.build_frame(bars)
        for k in range(150, 420, 7):
            part = ss.build_frame(bars[:k + 1])
            a = [(e['signalId'], e.get('level')) for e in ss.detect_at(full, k)]
            b = [(e['signalId'], e.get('level')) for e in ss.detect_at(part, k)]
            self.assertEqual(a, b, f'look-ahead at bar {k}')

    def test_stats_only_count_completed_horizons(self):
        bars = make_bars(random_walk(4, 300))
        f = ss.build_frame(bars)
        outs = ss.forward_outcomes(f, [280, 290, 296], 5, 'bull')
        self.assertEqual(len(outs), 2)   # 296+5 > 299 → 未完成，不計
        self.assertAlmostEqual(outs[0]['ret'], f['close'][285] / f['close'][280] - 1)
        lagged = ss.forward_outcomes(f, [280], 5, 'bull', entry_lag=1)
        self.assertAlmostEqual(lagged[0]['ret'], f['close'][286] / f['close'][281] - 1)


class LifecycleTests(unittest.TestCase):
    def test_breakout_then_failure_is_invalidated(self):
        closes = [100.0 + (i % 5) * 0.2 for i in range(60)] + [104.0, 104.5, 100.2, 100.0]
        vols = [1000.0] * 60 + [2500.0, 1200, 1100, 1000]
        f = ss.build_frame(make_bars(closes, vols))
        events = {e['signalId']: e for e in ss.recent_events(f)}
        ev = events['vol_breakout_20d']
        self.assertEqual(ev['status'], 'invalidated')
        self.assertEqual(ev['barsAgo'], 3)

    def test_confirmed_after_three_bars_and_new_on_last_bar(self):
        closes = [100.0 + (i % 5) * 0.2 for i in range(60)] + [104.0, 104.5, 105.0, 105.2]
        vols = [1000.0] * 60 + [2500.0, 1200, 1100, 1000]
        f = ss.build_frame(make_bars(closes, vols))
        ev = {e['signalId']: e for e in ss.recent_events(f)}['vol_breakout_20d']
        self.assertEqual(ev['status'], 'confirmed')
        f2 = ss.build_frame(make_bars(closes[:61], vols[:61]))
        ev2 = {e['signalId']: e for e in ss.recent_events(f2, provisional_last=True)}['vol_breakout_20d']
        self.assertEqual(ev2['status'], 'new')
        self.assertTrue(ev2['provisional'])


class AnalyzeTests(unittest.TestCase):
    def test_insufficient_bars_fails_closed(self):
        r = ss.analyze(make_bars([100.0] * 30), symbol='X', market='TW')
        self.assertFalse(r['ok'])
        self.assertEqual(r['reason'], 'INSUFFICIENT_BARS')

    def test_contract_and_plain_language_guardrails(self):
        bars = make_bars(random_walk(8, 500))
        r = ss.analyze(bars, symbol='2330', market='TW')
        self.assertTrue(r['ok'])
        self.assertEqual([l['key'] for l in r['health']['lights']],
                         ['trend', 'momentum', 'volume', 'chip', 'risk'])
        text = r['health']['summary']['sentence'] + ''.join(l['plain'] for l in r['health']['lights'])
        text += ''.join(e['plain'] + e['detail'] for e in r['events'])
        for banned in ('買進', '賣出', '保證', '必漲', '必跌'):
            self.assertNotIn(banned, text)
        for e in r['events']:
            self.assertIn(e['evidenceId'], r['evidence'])
        self.assertIn('ind.close', r['evidence'])
        json.dumps(r, ensure_ascii=False)   # 可序列化

    def test_us_symbol_has_no_chip_light(self):
        r = ss.analyze(make_bars(random_walk(2, 200)), symbol='AAPL', market='US')
        chip = [l for l in r['health']['lights'] if l['key'] == 'chip'][0]
        self.assertEqual(chip['state'], 'unknown')

    def test_stats_gate_hides_ratios_below_min_sample(self):
        f = ss.build_frame(make_bars(random_walk(5, 700)))
        for spec in ss.SIGNALS:
            st = ss.signal_stats(f, spec)
            for row in st['horizons']:
                if row['n'] < ss.MIN_SAMPLE:
                    self.assertIsNone(row['upRatio'])
                    self.assertEqual(row['gate'], 'insufficient')
                else:
                    self.assertEqual(row['gate'], 'ok')
                    self.assertTrue(0.0 <= row['upRatio'] <= 1.0)

    def test_chip_streaks_match_legacy_semantics(self):
        series = [{'date': '2026-09-2%d' % i, 'foreign': v, 'trust': t, 'dealer': None}
                  for i, (v, t) in enumerate([(5, -1), (-3, 2), (-4, 3), (-1, 4)])]
        self.assertEqual(ss.chip_streaks(series), {'foreign': -3, 'trust': 3, 'dealer': 0})

    def test_load_chip_series_reads_history_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for day, trust in (('20260922', 1.0), ('20260923', 2.0), ('20260924', None)):
                rec = {'2330': {'foreign': 1.0, 'trust': trust}} if trust is not None else {'2317': {}}
                Path(tmp, day + '.json').write_text(json.dumps(rec), encoding='utf-8')
            s = ss.load_chip_series('2330', tmp)
        self.assertEqual([r['date'] for r in s], ['2026-09-22', '2026-09-23'])


class RoutesTests(unittest.TestCase):
    def setUp(self):
        routes.clear_cache()

    def test_session_state_marks_intraday_bar_provisional(self):
        during = datetime(2026, 9, 25, 11, 0, tzinfo=TPE)
        after = datetime(2026, 9, 25, 14, 30, tzinfo=TPE)
        self.assertTrue(routes.session_state('TW', '2026-09-25', during)['provisional'])
        self.assertFalse(routes.session_state('TW', '2026-09-25', after)['provisional'])
        weekend = datetime(2026, 9, 27, 11, 0, tzinfo=TPE)
        self.assertEqual(routes.session_state('TW', '2026-09-25', weekend)['expectedLastDate'], '2026-09-25')
        early = datetime(2026, 9, 28, 8, 0, tzinfo=TPE)
        self.assertEqual(routes.session_state('TW', None, early)['expectedLastDate'], '2026-09-25')

    def test_symbol_cleaning_and_market_inference(self):
        self.assertEqual(routes.clean_symbol('2330.tw'), '2330')
        self.assertEqual(routes.clean_symbol('6488.TWO'), '6488')
        self.assertIsNone(routes.clean_symbol('../etc/passwd'))
        self.assertEqual(routes.infer_market('AAPL'), 'US')
        self.assertEqual(routes.infer_market('00631L'), 'TW')
        self.assertEqual(routes._parse_batch('2330, AAPL:US,2330,bad/x'), [('2330', 'TW'), ('AAPL', 'US')])

    def test_analyze_symbol_uses_injected_loader_and_caches(self):
        calls = []

        def loader(code, market, **kw):
            calls.append(code)
            return {'bars': make_bars(random_walk(3, 300)), 'source': 'fixture', 'provisional': False,
                    'staleDays': 0, 'error': None}
        with tempfile.TemporaryDirectory() as tmp:
            a = routes.analyze_symbol('9999', 'TW', bars_loader=loader, chip_dir=tmp)
            b = routes.analyze_symbol('9999', 'TW', bars_loader=loader, chip_dir=tmp)
        self.assertTrue(a['ok'])
        self.assertIs(a, b)
        self.assertEqual(calls, ['9999'])
        self.assertEqual(a['dataSource'], 'fixture')

    def test_watchlist_save_filters_indices_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(routes, 'WATCHLIST_FILE', os.path.join(tmp, 'wl.json')):
            saved = routes.save_watchlist([{'t': '2330', 'm': 'TW'}, {'t': '2330', 'm': 'TW'},
                                           {'t': '^TWII', 'm': 'TW'}, {'t': 'aapl', 'm': 'US'},
                                           {'t': '__TXF__'}])
            self.assertEqual(saved, [{'sym': '2330', 'market': 'TW'}, {'sym': 'AAPL', 'market': 'US'}])
            self.assertEqual(routes.load_watchlist(), saved)


class DigestTests(unittest.TestCase):
    def _result(self, sym='2330', provisional=False):
        bars = make_bars([100.0 + (i % 5) * 0.2 for i in range(80)] + [104.0], [1000.0] * 80 + [2600.0])
        r = ss.analyze(bars, symbol=sym, market='TW', provisional_last=provisional)
        self.assertTrue(any(e['barsAgo'] == 0 for e in r['events']))
        return r

    def test_realtime_pushes_each_event_once(self):
        sent = []
        result = self._result()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(signal_digest, 'STATE_FILE', os.path.join(tmp, 'st.json')), \
                mock.patch.object(signal_digest, 'symbols', lambda: [{'sym': '2330', 'market': 'TW'}]), \
                mock.patch.object(signal_digest.routes, 'analyze_symbol', lambda *a, **k: result), \
                mock.patch.object(signal_digest, 'alert_daemon') as ad:
            ad.load_config.return_value = {'stock_signal_push': 'realtime'}
            notify = lambda text, subject: sent.append((subject, text))
            before_close = datetime(2026, 9, 25, 11, 0, tzinfo=TPE)
            first = signal_digest.check_once(now=before_close, notify=notify)
            second = signal_digest.check_once(now=before_close, notify=notify)
        self.assertGreaterEqual(first['events'], 1)
        self.assertEqual(second['events'], 0)
        self.assertEqual(len(sent), 1)
        self.assertIn('帶量突破 20 日高', sent[0][1])

    def test_digest_once_per_day_after_close(self):
        sent = []
        result = self._result()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(signal_digest, 'STATE_FILE', os.path.join(tmp, 'st.json')), \
                mock.patch.object(signal_digest, 'symbols', lambda: [{'sym': '2330', 'market': 'TW'}]), \
                mock.patch.object(signal_digest.routes, 'analyze_symbol', lambda *a, **k: result), \
                mock.patch.object(signal_digest, 'alert_daemon') as ad:
            ad.load_config.return_value = {'stock_signal_push': 'digest'}
            notify = lambda text, subject: sent.append(subject)
            self.assertEqual(signal_digest.check_once(
                now=datetime(2026, 9, 25, 13, 0, tzinfo=TPE), notify=notify)['digests'], 0)
            self.assertEqual(signal_digest.check_once(
                now=datetime(2026, 9, 25, 15, 0, tzinfo=TPE), notify=notify)['digests'], 1)
            self.assertEqual(signal_digest.check_once(
                now=datetime(2026, 9, 25, 16, 0, tzinfo=TPE), notify=notify)['digests'], 0)
        self.assertEqual(len(sent), 1)

    def test_off_mode_sends_nothing(self):
        with mock.patch.object(signal_digest, 'alert_daemon') as ad:
            ad.load_config.return_value = {}
            self.assertEqual(signal_digest.check_once(notify=lambda *a: self.fail('sent')),
                             {'events': 0, 'digests': 0})

    def test_block_format_mentions_invalidation(self):
        block = signal_digest.format_symbol_block(self._result())
        self.assertIn('失效：', block)
        self.assertIn('2330', block)


SPEC = importlib.util.spec_from_file_location('st_stock_signals_http_test', SERVER_DIR / 'server.py')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


class StockSignalsHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), ST.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        routes.clear_cache()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return json.load(r)

    def test_catalog(self):
        d = self._get('/stock-signals/catalog')
        self.assertEqual(len(d['signals']), len(ss.SIGNALS))
        self.assertEqual(d['minSample'], ss.MIN_SAMPLE)

    def test_single_and_batch_with_fixture_loader(self):
        def loader(code, market, **kw):
            return {'bars': make_bars(random_walk(len(code), 260)), 'source': 'fixture',
                    'provisional': False, 'staleDays': 0, 'error': None}
        with mock.patch.object(routes, 'load_bars', loader):
            d = self._get('/stock-signals?sym=2330&market=TW&cacheOnly=1')
            b = self._get('/stock-signals/batch?syms=2330,AAPL:US')
        self.assertTrue(d['ok'])
        self.assertEqual(d['symbol'], '2330')
        self.assertEqual([i['symbol'] for i in b['items']], ['2330', 'AAPL'])
        self.assertNotIn('evidence', b['items'][0])

    def test_rejects_missing_or_bad_symbol(self):
        for path in ('/stock-signals', '/stock-signals?sym=..%2Fx', '/stock-signals/batch'):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get(path)
            self.assertEqual(ctx.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
