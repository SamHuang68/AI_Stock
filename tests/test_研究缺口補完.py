"""公司行動、交易日與共用行情回退的回歸；全部離線。"""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore as ds
import stock_signals as ss
import pulse_extras as px
import 個股還原研究 as adj
import 每日個股留存 as daily
import 台股交易參考 as ref
import stock_signals_routes as routes
from deadline import Deadline


def bar(day, close):
    return {'date': day, 'open': close, 'high': close + 1, 'low': close - 1, 'close': close, 'volume': 100}


class ResearchGapTests(unittest.TestCase):
    def test_health_loader_does_not_refetch_during_holiday_or_next_premarket(self):
        routes.clear_cache()
        end = datetime(2026, 9, 24, tzinfo=ss._TZ['TW'])
        rows = [(int((end-timedelta(days=i)).timestamp()), 100, 101, 99, 100, 10) for i in reversed(range(150))]
        for now in (datetime(2026, 9, 28, 15, tzinfo=ss._TZ['TW']), datetime(2026, 9, 29, 1, tzinfo=ss._TZ['TW'])):
            with patch.object(routes, '_datastore', return_value=ds), patch.object(ds, 'get_bars', return_value=rows), \
                    patch.object(routes, '_fetch_remote') as fetch, patch.object(ds, 'upsert_bars') as write:
                result = routes.load_bars('2330', 'TW', now=now)
            self.assertEqual(result['staleDays'], 0)
            self.assertFalse(result['provisional'])
            fetch.assert_not_called()
            write.assert_not_called()
        opened = routes.session_state('TW', '2026-09-29', datetime(2026, 9, 29, 11, tzinfo=ss._TZ['TW']))
        self.assertTrue(opened['provisional'])
        self.assertEqual(opened['expectedLastDate'], '2026-09-29')

    def test_unknown_calendar_does_not_infer_staleness_or_open_market(self):
        now = datetime(2027, 9, 29, 11, tzinfo=ss._TZ['TW'])
        for hour in (1, 11, 15):
            state = routes.session_state('TW', '2027-09-29', now.replace(hour=hour))
            self.assertIsNone(state['expectedLastDate'])
            self.assertFalse(state['sessionOpen'])
            # 年度日曆未知時不能按鐘點推定今日已完成；與持久化入口的保守界線一致。
            self.assertTrue(state['provisional'])
            prior = routes.session_state('TW', '2027-09-28', now.replace(hour=hour))
            self.assertFalse(prior['provisional'])
            self.assertIsNone(prior['expectedLastDate'])
            self.assertFalse(prior['sessionOpen'])
        rows = [(int((now-timedelta(days=i)).timestamp()), 100, 101, 99, 100, 10) for i in reversed(range(1, 151))]
        routes.clear_cache()
        with patch.object(routes, '_datastore', return_value=ds), patch.object(ds, 'get_bars', return_value=rows), \
                patch.object(routes, '_fetch_remote') as fetch:
            result = routes.load_bars('2330', 'TW', now=now)
        self.assertIsNone(result['staleDays'])
        self.assertIn('新鮮度待確認', result['error'])
        fetch.assert_not_called()
        intraday = [(int(now.timestamp()), 100, 101, 99, 100, 10)]
        with patch.object(routes, '_datastore', return_value=ds), patch.object(ds, 'get_bars', return_value=[]), \
                patch.object(routes, '_fetch_remote', return_value=intraday), patch.object(ds, 'upsert_bars') as write, \
                patch.object(ds, 'source_revision_status', return_value={'count': 0}):
            result = routes.load_bars('2330', 'TW', now=now)
        self.assertTrue(result['provisional'])
        write.assert_not_called()

    def test_holiday_rows_cannot_accelerate_pending_outcomes(self):
        origin = datetime(2026, 9, 17, 15, tzinfo=ss._TZ['TW'])
        history = [bar((origin.date()-timedelta(days=i)).isoformat(), 100) for i in reversed(range(150))]
        event = {'date': '2026-09-17', 'signalId': 'mom_rsi_rebound', 'provisional': False}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '帳本.sqlite3'
            daily.enable(path, origin-timedelta(days=1))
            with patch.object(ss, 'analyze', return_value={'events': [event]}) as analyze:
                self.assertEqual(daily.capture(path, [('2330', history)], history, now=origin)['eventsAdded'], 1)
                self.assertTrue(all(ref.session(b['date'])['status'] != 'closed' for b in analyze.call_args.args[0]))
            # 模擬先前版本已留存的錯標休市列；保留帳本但不得參與結果計算。
            bad = bar('2026-09-25', 300)
            with closing(sqlite3.connect(path)) as c, c:
                c.execute('INSERT INTO daily_prices VALUES(?,?,?,?)', ('2330', bad['date'], origin.isoformat(), json.dumps(bad)))
            future = history + [bar(day, 110) for day in ('2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25')]
            holiday = datetime(2026, 9, 25, 15, tzinfo=ss._TZ['TW'])
            self.assertEqual(daily.capture(path, [('2330', future)], future, now=holiday)['outcomesAdded'], 0)
            future += [bar('2026-09-29', 121)]
            with patch.object(ss, 'analyze', return_value={'events': []}):
                result = daily.capture(path, [('2330', future)], future, now=holiday.replace(day=29))
            self.assertEqual(result['outcomesAdded'], 1)
            with closing(sqlite3.connect(path)) as c:
                outcome = json.loads(c.execute('SELECT payload FROM daily_outcomes').fetchone()[0])
                self.assertEqual(c.execute("SELECT count(*) FROM daily_prices WHERE session_date='2026-09-25'").fetchone()[0], 1)
            self.assertEqual(outcome['endDate'], '2026-09-29')
            self.assertAlmostEqual(outcome['ret'], .1)
            self.assertNotIn('2026-09-25', outcome['expectedSessions'])

    def test_split_basis_requires_event_and_preserves_original(self):
        b = [bar('2026-09-01', 100), bar('2026-09-03', 51)]
        split = {'date': int(datetime(2026, 9, 2, tzinfo=ss._TZ['TW']).timestamp()), 'numerator': 2, 'denominator': 1}
        s = {'rows': [{'date': b[0]['date'], 'rawClose': 50, 'adjClose': 48},
                      {'date': b[1]['date'], 'rawClose': 51, 'adjClose': 51}],
             'events': {'splits': {'1': split}}, 'source': '離線測試'}
        self.assertEqual(adj.adjusted_bars(b, s)[0]['close'], 48)
        proof = adj.alignment_issues(b, s)
        self.assertEqual(proof['status'], 'aligned')
        self.assertEqual(proof['basisConversions'][0]['ratio'], 2)
        self.assertEqual(b[0]['close'], 100)
        self.assertIsNone(adj.adjusted_bars(b, {**s, 'events': {}}))
        s['rows'][0]['rawClose'] = 49
        self.assertIsNone(adj.adjusted_bars(b, s))

    def test_future_split_and_split_day_are_not_applied_to_earlier_snapshot(self):
        b = [bar('2026-09-01', 100)]
        s = {'rows': [{'date': '2026-09-01', 'rawClose': 50, 'adjClose': 50}],
             'events': {'splits': {'1': {'date': int(datetime(2026, 9, 2, tzinfo=ss._TZ['TW']).timestamp()),
                                       'numerator': 2, 'denominator': 1}}}}
        self.assertIsNone(adj.adjusted_bars(b, s))
        s['events']['splits']['1']['date'] -= 86400
        self.assertIsNone(adj.adjusted_bars(b, s))

    def test_official_fund_split_reference_is_source_bound(self):
        b = [bar('2026-06-30', 240), bar('2026-07-07', 10)]
        s = {'symbol': '00685L', 'rows': [{'date': x['date'], 'rawClose': 10, 'adjClose': 10} for x in b]}
        self.assertEqual(adj.adjusted_bars(b, s)[0]['close'], 10)
        self.assertIn('capitalfund.com.tw', adj.alignment_issues(b, s)['basisConversions'][0]['events'][0]['source'])
        self.assertIsNone(adj.adjusted_bars(b, {**s, 'symbol': '2330'}))

    def test_post_termination_prices_are_retained_but_not_accepted(self):
        b = [bar('2026-09-22', 100)]
        s = {'symbol': '00793B', 'rows': [{'date': b[0]['date'], 'rawClose': 100, 'adjClose': 100}]}
        self.assertIsNone(adj.adjusted_bars(b, s))
        self.assertEqual(adj.alignment_issues(b, s)['invalidTradeDates'], ['2026-09-22'])
        self.assertEqual(b[0]['close'], 100)

    def test_calendar_distinguishes_official_holiday_and_unknown_year(self):
        self.assertEqual(ref.session('2026-09-28')['status'], 'closed')
        self.assertEqual(ref.session('2026-09-29')['status'], 'scheduled')
        self.assertEqual(ref.session('2027-09-29')['status'], 'unknown')
        self.assertIsNone(ref.instrument('4130', '2026-07-21'))
        self.assertEqual(ref.instrument('4130', '2026-07-22')['status'], 'terminated')

    def test_holiday_cannot_create_events_even_with_bad_dated_prices(self):
        now = datetime(2026, 9, 28, 15, tzinfo=ss._TZ['TW'])
        b = [bar((now.date() - timedelta(days=i)).isoformat(), 100) for i in reversed(range(150))]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '帳本.sqlite3'
            daily.enable(p, now - timedelta(days=1))
            with patch.object(ss, 'analyze') as analyze:
                result = daily.capture(p, [('2330', b)], b, now=now)
            self.assertEqual(result['status'], 'closed')
            self.assertEqual(result['eventsAdded'], 0)
            analyze.assert_not_called()

    def test_real_session_flow_deduplicates_and_excludes_terminated(self):
        now = datetime(2026, 9, 29, 15, tzinfo=ss._TZ['TW'])
        b = [bar((now.date() - timedelta(days=i)).isoformat(), 100) for i in reversed(range(150))]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '帳本.sqlite3'
            daily.enable(p, now - timedelta(days=2))
            event = {'date': '2026-09-29', 'signalId': 'mom_rsi_rebound', 'provisional': False}
            with patch.object(ss, 'analyze', return_value={'events': [event]}):
                a = daily.capture(p, [('2330', b), ('00793B', b)], b, now=now)
                z = daily.capture(p, [('2330', b), ('00793B', b)], b, now=now)
            self.assertEqual(a['eventsAdded'], 1)
            self.assertEqual(z['eventsAdded'], 0)
            self.assertEqual(a['excludedInstruments'][0]['symbol'], '00793B')

    def test_regular_yahoo_fetch_uses_otc_fallback_and_closes_error(self):
        p = {'chart': {'result': [{'timestamp': [1704153600], 'meta': {'dataGranularity': '1d'},
             'indicators': {'quote': [{'open': [99], 'high': [101], 'low': [98], 'close': [100], 'volume': [10]}]}}]}}
        stream = io.BytesIO(b'404')
        with patch.object(ds.urllib.request, 'urlopen', side_effect=[
                urllib.error.HTTPError('來源', 404, '無資料', {}, stream), io.BytesIO(json.dumps(p).encode())]) as fetch:
            self.assertEqual(ds.fetch_yahoo_daily('5274', 'TW', '2y', retries=1)[0][4], 100)
        self.assertIn('5274.TWO', fetch.call_args_list[-1].args[0].full_url)
        self.assertTrue(stream.closed)

    def test_deadline_exhaustion_does_not_start_another_request(self):
        with patch.object(ds.urllib.request, 'urlopen') as fetch:
            with self.assertRaises(TimeoutError):
                ds.fetch_yahoo_daily('6488', 'TW', deadline=Deadline(0))
        fetch.assert_not_called()

    def test_pulse_reuses_canonical_loader_and_rejects_short_history(self):
        stamp = 1704153600
        rows = [(stamp + i*86400, 99, 101, 98, 100, 10) for i in range(260)]
        codes = [str(5000+i) for i in range(13)]
        def fetch(code, *args, **kwargs):
            return rows[:200] if code == codes[-1] else rows
        with patch.object(ds, 'DB_PATH', '不存在的行情資料庫'), patch.object(px, '_NHNL_UNIVERSE', codes), \
                patch.object(px, '_cache_get', return_value=None), patch.object(px, '_cache_set'), \
                patch.object(ds, 'fetch_yahoo_daily', side_effect=fetch) as loader:
            result = px.fetch_nhnl_sample()
        self.assertEqual(result['sampleN'], 12)
        self.assertEqual(result['excludedSymbols'], [codes[-1]])
        self.assertEqual(result['date'], ss.bar_date(rows[-1][0]))
        self.assertEqual(loader.call_count, 13)


if __name__ == '__main__':
    unittest.main()
