"""資料品質、還原成本與實際留存的邊界驗證；不使用外部來源。"""
import json
import io
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import stock_signals as ss
import datastore
import 個股資料品質 as quality
import 個股還原研究 as adjusted
import 每日個股留存 as daily
import 個股研究維護 as maintenance
import industry_revenue as revenue
from test_個股訊號研究 import bars


class QualityTests(unittest.TestCase):
    def test_weekend_uses_known_sessions_and_does_not_claim_calendar_completeness(self):
        now = datetime(2026, 9, 27, 18, tzinfo=ss._TZ['TW'])
        r = {'market': 'TW', 'asOf': '2026-09-24', 'chip': {'asOf': '2026-09-24'}}
        p = {'window': {'to': '2026-09-24'}, 'generatedAt': now.isoformat()}
        out = quality.assess(r, [{'date': '2026-09-24'}], p, now)
        self.assertEqual(out['status'], 'aligned')
        self.assertTrue(out['notes'])
        self.assertEqual(out['items'][0]['lagSessions'], 0)

    def test_missing_chips_and_old_recalculation_are_separate(self):
        now = datetime(2026, 9, 27, 18, tzinfo=ss._TZ['TW'])
        p = {'window': {'to': '2026-09-24'}, 'generatedAt': '2026-09-01T18:00:00+08:00'}
        out = quality.assess({'market': 'TW', 'asOf': '2026-09-23'}, [{'date': '2026-09-24'}], p, now)
        self.assertEqual([r['status'] for r in out['items']], ['stale', 'missing', 'aligned', 'stale'])
        self.assertFalse(out['changesSignal'])

    def test_unknown_calendar_is_not_zero_lag(self):
        out = quality.assess({'market': 'TW', 'asOf': '2026-09-24'}, [])
        self.assertIsNone(out['items'][0]['lagSessions'])
        self.assertEqual(out['items'][0]['status'], 'unknown')

    def test_partial_revenue_title_and_sector_carry_coverage(self):
        source = json.loads((ROOT / 'tests/fixtures/industry_revenue_sample.json').read_text(encoding='utf-8'))
        with patch.object(revenue, '_cache', {'day': None, 'agg': None}):
            agg = revenue.get_aggregate(loader=lambda ds: source if ds == 't187ap05_L' else [])
        self.assertNotIn('上市櫃合計', revenue.market_flash_title(agg))
        self.assertIn('部分來源', revenue.market_flash_title(agg))
        key = next(iter(agg['byIndustryKey']))
        rows = revenue.attach_sector_revenue([{'sector': key}], agg)
        self.assertFalse(rows[0]['revenueSourceCoverage']['complete'])


class AdjustmentTests(unittest.TestCase):
    def test_source_update_includes_short_history_and_does_not_duplicate_session(self):
        spec = importlib.util.spec_from_file_location('research_source_test', ROOT / 'scripts/個股研究資料更新.py')
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as tmp, patch.object(datastore, 'DB_PATH', str(Path(tmp) / 'market.db')):
            # 9/25 為官方休市日；此案例用 9/23、9/24 驗證有效交易日追加。
            stamp = int(datetime(2026, 9, 23, 9, tzinfo=ss._TZ['TW']).timestamp())
            with closing(sqlite3.connect(datastore.DB_PATH)) as conn, conn:
                conn.executescript(datastore.SCHEMA)
                conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', stamp, 10, 10, 10, 10, 1))
            pack = {'timestamps': [stamp + 3600, stamp + 86400], 'quoteClose': [11, 12], 'adjclose': [10, 12],
                    'events': {}, 'source': '本機測試', 'fetchedAt': 1,
                    'rows': [(stamp - 86400, 9, 9, 9, 9, 1), (stamp + 3600, 11, 11, 11, 11, 1),
                             (stamp + 86400, 12, 12, 12, 12, 1)]}
            with patch.object(datastore, 'update', return_value=0), patch.object(datastore, 'fetch_yahoo_daily', return_value=pack) as fetch, \
                    patch.object(updater.tracker, 'CHIP_HISTORY_PATH', str(Path(tmp) / 'chip_history')), redirect_stdout(io.StringIO()):
                code = updater.main(['--start', '2026-09-27', '--end', '2026-09-27', '--data-dir', tmp, '--adjustments'])
            self.assertEqual(code, 0)
            self.assertEqual(fetch.call_args.kwargs['start_ts'], stamp - 86400)
            self.assertEqual([row[4] for row in datastore.get_bars('2330')], [10, 12])

    def test_explicit_period_preserves_daily_history_and_otc_fallback(self):
        import urllib.error
        payload = {'chart': {'result': [{'meta': {'dataGranularity': '1d'}, 'timestamp': [1704153600],
            'indicators': {'quote': [{'close': [100], 'open': [99], 'high': [101], 'low': [98], 'volume': [5]}],
                           'adjclose': [{'adjclose': [90]}]}, 'events': {}}]}}
        error_stream = io.BytesIO(b'not found')
        with patch.object(datastore.urllib.request, 'urlopen', side_effect=[
                urllib.error.HTTPError('來源', 404, '無資料', {}, error_stream),
                io.BytesIO(json.dumps(payload).encode())]) as call:
            out = datastore.fetch_yahoo_daily('5347', 'TW', retries=1, with_research=True, start_ts=1000)
        urls = [item.args[0].full_url for item in call.call_args_list]
        self.assertTrue(all('period1=1000&' in url and 'range=' not in url for url in urls))
        self.assertIn('5347.TWO?', out['source'])
        self.assertEqual(out['adjclose'], [90])
        self.assertTrue(error_stream.closed)

    def test_source_monthly_granularity_is_rejected(self):
        payload = {'chart': {'result': [{'meta': {'dataGranularity': '1mo'}}]}}
        with patch.object(datastore.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaisesRegex(RuntimeError, '非日線'):
                datastore.fetch_yahoo_daily('2330', 'TW', 'max', retries=1, with_research=True)

    def test_dividend_adjustment_and_missing_day_rejection(self):
        b = [{'date': '2026-01-02', 'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 5},
             {'date': '2026-01-05', 'open': 95, 'high': 96, 'low': 94, 'close': 95, 'volume': 5}]
        snap = {'rows': [{'date': '2026-01-02', 'rawClose': 100, 'adjClose': 95},
                         {'date': '2026-01-05', 'rawClose': 95, 'adjClose': 95}]}
        a = adjusted.adjusted_bars(b, snap)
        self.assertEqual(a[0]['close'], a[1]['close'])
        self.assertEqual(b[0]['close'], 100)
        self.assertEqual(a[0]['volume'], b[0]['volume'])
        self.assertIsNone(adjusted.adjusted_bars(b, {'rows': snap['rows'][:1]}))
        self.assertEqual(adjusted.alignment_issues(b, {'rows': snap['rows'][:1]})['missingDates'], ['2026-01-05'])
        snap['rows'][0]['rawClose'] = 99
        self.assertIsNone(adjusted.adjusted_bars(b, snap))
        self.assertEqual(adjusted.alignment_issues(b, snap)['priceMismatches'][0]['sourceClose'], 99)

    def test_cost_formula_threshold_and_nonfinite(self):
        self.assertAlmostEqual(adjusted.net_return(.1, 100), 1.1 * .995 / 1.005 - 1)
        self.assertEqual(adjusted.net_return(.1, 0), 1.1 - 1)
        self.assertIsNone(adjusted.summary([.1] * 19)['medianRet'])
        self.assertEqual(adjusted.summary([.1] * 20)['medianRet'], .1)
        with self.assertRaises(ValueError):
            adjusted.net_return(.1, float('nan'))

    def test_snapshots_do_not_rewrite_bars_and_do_not_mix_versions(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(datastore, 'DB_PATH', str(Path(tmp) / 'market.db')):
            with closing(sqlite3.connect(datastore.DB_PATH)) as c:
                c.executescript(datastore.SCHEMA)
            pack = {'timestamps': [1704153600], 'quoteClose': [100], 'adjclose': [90],
                    'events': {}, 'source': '本機測試', 'fetchedAt': 1}
            adjusted.save_snapshot('2330', 'TW', pack)
            adjusted.save_snapshot('2330', 'TW', {**pack, 'fetchedAt': 2, 'adjclose': [95]})
            with datastore.read_snapshot() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM bars').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT count(*) FROM stock_adjustment_snapshots').fetchone()[0], 2)
                self.assertEqual(adjusted.load_snapshot(c, '2330')['rows'][0]['adjClose'], 95)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '每日.sqlite3'
        self.bars = bars(160)
        self.day = datetime.fromisoformat(self.bars[-1]['date']).replace(hour=15, tzinfo=ss._TZ['TW'])
        self.event = {'signalId': 'mom_rsi_rebound', 'date': self.bars[-1]['date'], 'provisional': False,
                      'rule': '固定測試條件'}

    def record(self, now=None, series=None, benchmark=None):
        with patch.object(ss, 'analyze', return_value={'events': [self.event], 'evidence': {'proof': 1}}):
            return daily.capture(self.path, series or [('2330', self.bars)], benchmark or self.bars, now=now or self.day)

    def test_no_backfill_activation_day_or_intraday(self):
        daily.enable(self.path, self.day)
        self.assertEqual(self.record()['eventsAdded'], 0)
        self.assertEqual(self.record(now=self.day + timedelta(days=1))['eventsAdded'], 0)
        self.assertEqual(self.record(now=self.day.replace(hour=10))['eventsAdded'], 0)

    def test_dedup_freezes_original_input_and_zero_event_scan(self):
        daily.enable(self.path, self.day - timedelta(days=1))
        self.assertEqual(self.record()['eventsAdded'], 1)
        self.bars[-1]['close'] *= 1.1
        with patch.object(daily, 'engine_digest', return_value='新引擎'):
            self.assertEqual(self.record()['eventsAdded'], 0)
        self.assertEqual(daily.status(self.path)['events'], 1)

    def test_outcomes_wait_for_all_sessions_and_are_immutable(self):
        daily.enable(self.path, self.day - timedelta(days=1))
        self.record()
        future = bars(168)
        now = datetime.fromisoformat(future[-1]['date']).replace(hour=15, tzinfo=ss._TZ['TW'])
        missing = future[:162] + future[163:]
        self.assertEqual(self.record(now, [('2330', missing)], future)['outcomesAdded'], 0)
        self.assertEqual(self.record(now, [('2330', future)], future)['outcomesAdded'], 1)
        with closing(sqlite3.connect(self.path)) as c:
            original = c.execute('SELECT payload FROM daily_outcomes').fetchone()[0]
        for b in future[160:]:
            b['close'] *= 2
        self.record(now, [('2330', future)], future)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute('SELECT payload FROM daily_outcomes').fetchone()[0], original)

    def test_no_benchmark_no_event(self):
        daily.enable(self.path, self.day - timedelta(days=1))
        with patch.object(ss, 'analyze', return_value={'events': [self.event]}):
            out = daily.capture(self.path, [('2330', self.bars)], [], now=self.day)
        self.assertEqual(out['eventsAdded'], 0)
        self.assertEqual(out['status'], 'waiting')

    def test_missing_benchmark_session_cannot_shift_outcome(self):
        daily.enable(self.path, self.day - timedelta(days=1))
        self.record()
        future = bars(168)
        now = datetime.fromisoformat(future[-1]['date']).replace(hour=15, tzinfo=ss._TZ['TW'])
        benchmark = future[:162] + future[163:]
        self.assertEqual(self.record(now, [('2330', future)], benchmark)['outcomesAdded'], 0)


class MaintenanceTests(unittest.TestCase):
    def test_new_stock_with_100_bars_is_included_in_daily_capture(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(datastore, 'DB_PATH', str(Path(tmp) / 'market.db')):
            data = bars(100)
            today = datetime.fromisoformat(data[-1]['date']).replace(hour=15, tzinfo=ss._TZ['TW'])
            with closing(sqlite3.connect(datastore.DB_PATH)) as c, c:
                c.executescript(datastore.SCHEMA)
                for symbol in ('2330', '^TWII'):
                    c.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)',
                        [(symbol, 'TW', datetime.fromisoformat(b['date']).replace(tzinfo=ss._TZ['TW']).timestamp(),
                          b['open'], b['high'], b['low'], b['close'], b['volume']) for b in data])
            daily.enable(maintenance.paths()[1], today - timedelta(days=1))
            with patch.object(ss, 'analyze', return_value={'events': [{'signalId': 'mom_rsi_rebound', 'date': data[-1]['date']}]}):
                result = maintenance.capture(today)
            self.assertEqual(result['currentSymbols'], 1)
            self.assertEqual(result['eventsAdded'], 1)

    def test_private_routes_require_owner(self):
        import private_web_gateway as gateway
        from types import SimpleNamespace
        settings = SimpleNamespace(extra_read_paths=(), extra_control_paths=())
        for method, path in [('GET', '/stock-signals/research/status'), ('POST', '/stock-signals/research/refresh')]:
            self.assertFalse(gateway.route_permission(method, path, 'reader', settings))
            self.assertTrue(gateway.route_permission(method, path, 'owner', settings))

    def test_failure_is_persisted_and_cannot_be_called_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'data/state.json'
            state.parent.mkdir()
            with patch.object(maintenance, 'paths', return_value=(state, state.with_suffix('.sqlite3'))), \
                    patch.object(maintenance, 'inventory', side_effect=ValueError('資料失敗')), \
                    self.assertRaises(ValueError):
                maintenance.run()
            saved = json.loads(state.read_text(encoding='utf-8'))
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['steps'][0]['status'], 'failed')
            events = [json.loads(s) for s in (Path(tmp) / 'logs/stock_research_maintenance.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len({e['runId'] for e in events}), 1)
            self.assertEqual(events[-1]['event'], '工作失敗')


if __name__ == '__main__':
    unittest.main()
