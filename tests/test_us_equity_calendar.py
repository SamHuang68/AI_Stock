"""美股日曆及體檢接合的定點離線回歸；不連 provider、不讀正式 DB。"""
import sys
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import us_equity_calendar as calendar
import stock_signals_routes as routes
import 個股資料品質 as quality


class USEquityCalendarTests(unittest.TestCase):
    def state(self, stamp, last):
        return routes.session_state('US', last, datetime.fromisoformat(stamp))

    def test_announced_holidays_and_observed_dates(self):
        for stamp, previous in (
            ('2026-12-25T12:00:00-05:00', '2026-12-24'),
            ('2026-07-03T12:00:00-04:00', '2026-07-02'),
            ('2026-04-03T12:00:00-04:00', '2026-04-02'),
            ('2027-06-18T12:00:00-04:00', '2027-06-17'),
            ('2027-07-05T12:00:00-04:00', '2027-07-02'),
        ):
            with self.subTest(stamp=stamp):
                value = self.state(stamp, previous)
                self.assertEqual(value['expectedLastDate'], previous)
                self.assertFalse(value['sessionOpen'])
                self.assertFalse(value['provisional'])
                self.assertEqual(value['calendar']['status'], 'closed')

    def test_early_close_includes_only_existing_thirty_minute_settle(self):
        for day, offset in (('2026-12-24', '-05:00'), ('2026-11-27', '-05:00'), ('2028-07-03', '-04:00')):
            for clock, provisional in (('12:59:00', True), ('13:29:59', True), ('13:30:00', False), ('14:00:00', False)):
                with self.subTest(day=day, clock=clock):
                    value = self.state(day+'T'+clock+offset, day)
                    self.assertEqual(value['provisional'], provisional)
                    self.assertEqual(value['sessionOpen'], provisional)
                    self.assertEqual(value['calendar']['close'], '13:00')

    def test_new_year_saturday_is_not_guessed_as_friday_observed(self):
        value = self.state('2027-12-31T12:00:00-05:00', '2027-12-31')
        self.assertEqual(value['calendar']['status'], 'scheduled')
        self.assertEqual(value['calendar']['close'], '16:00')
        self.assertTrue(value['sessionOpen'])
        weekend = self.state('2028-01-02T12:00:00-05:00', '2027-12-31')
        self.assertEqual(weekend['expectedLastDate'], '2027-12-31')

    def test_dst_utc_and_taipei_inputs_resolve_exchange_time(self):
        for stamp, day, opened in (
            ('2026-03-06T14:29:00+00:00', '2026-03-06', False),
            ('2026-03-06T14:30:00+00:00', '2026-03-06', True),
            ('2026-03-09T13:30:00+00:00', '2026-03-09', True),
            ('2026-11-02T14:30:00+00:00', '2026-11-02', True),
            ('2026-07-06T21:30:00+08:00', '2026-07-06', True),
        ):
            with self.subTest(stamp=stamp):
                value = self.state(stamp, day)
                self.assertEqual(value['sessionOpen'], opened)
                self.assertEqual(value['provisional'], opened)

    def test_unknown_year_and_missing_timezone_never_claim_final_today(self):
        for stamp in ('2025-12-31T20:00:00-05:00', '2029-01-02T20:00:00-05:00'):
            value = self.state(stamp, stamp[:10])
            self.assertIsNone(value['expectedLastDate'])
            self.assertFalse(value['sessionOpen'])
            self.assertTrue(value['provisional'])
            self.assertEqual(value['calendar']['status'], 'unknown')
        with patch.object(calendar, 'TZ', None):
            value = self.state('2026-07-06T20:00:00-04:00', '2026-07-06')
            self.assertIsNone(value['expectedLastDate'])
            self.assertEqual(value['calendar']['status'], 'unknown')

    def test_holiday_and_early_close_do_not_refetch_complete_history(self):
        for now, last in (
            ('2026-12-25T12:00:00-05:00', '2026-12-24'),
            ('2026-12-24T14:00:00-05:00', '2026-12-24'),
            ('2026-12-28T08:00:00-05:00', '2026-12-24'),
        ):
            final = datetime.fromisoformat(last+'T16:00:00-05:00')
            rows = [(int((final-timedelta(days=i)).timestamp()), 100, 101, 99, 100, 10) for i in reversed(range(150))]
            db = SimpleNamespace(get_bars=Mock(return_value=rows), upsert_bars=Mock())
            routes.clear_cache()
            with patch.object(routes, '_datastore', return_value=db), patch.object(routes, '_fetch_remote') as fetch:
                result = routes.load_bars('AAPL', 'US', now=datetime.fromisoformat(now))
            self.assertEqual(result['staleDays'], 0)
            self.assertFalse(result['provisional'])
            fetch.assert_not_called()
            db.upsert_bars.assert_not_called()

    def test_unknown_current_day_is_not_written_as_final(self):
        now = datetime.fromisoformat('2029-01-02T20:00:00-05:00')
        row = (int(now.timestamp()), 100, 101, 99, 100, 10)
        db = SimpleNamespace(get_bars=Mock(return_value=[]), upsert_bars=Mock(),
                             source_revision_status=Mock(return_value={'count': 0}))
        routes.clear_cache()
        with patch.object(routes, '_datastore', return_value=db), patch.object(routes, '_fetch_remote', return_value=[row]):
            result = routes.load_bars('AAPL', 'US', now=now)
        self.assertIsNone(result['staleDays'])
        self.assertTrue(result['provisional'])
        self.assertIn('新鮮度待確認', result['error'])
        db.upsert_bars.assert_not_called()

    def test_known_holiday_provider_row_is_not_inserted(self):
        now = datetime.fromisoformat('2026-12-25T17:00:00-05:00')
        row = (int(now.timestamp()), 100, 101, 99, 100, 10)
        db = SimpleNamespace(get_bars=Mock(return_value=[]), upsert_bars=Mock(),
                             source_revision_status=Mock(return_value={'count': 0}))
        routes.clear_cache()
        with patch.object(routes, '_datastore', return_value=db), patch.object(routes, '_fetch_remote', return_value=[row]):
            routes.load_bars('AAPL', 'US', now=now)
        db.upsert_bars.assert_not_called()

    def test_api_preserves_calendar_evidence_and_existing_session_note(self):
        for stamp, lag in (('2026-12-24T14:00:00-05:00', 0),
                           ('2029-01-02T20:00:00-05:00', 0),
                           ('2029-01-02T20:00:00-05:00', 1)):
            now = datetime.fromisoformat(stamp)
            rows = [(int((now-timedelta(days=i+lag)).timestamp()), 100, 101, 99, 100, 10) for i in reversed(range(150))]
            db = SimpleNamespace(get_bars=Mock(return_value=rows), upsert_bars=Mock(),
                                 read_snapshot=lambda: nullcontext(None),
                                 get_bars_bulk=lambda *args, **kwargs: {})
            with patch.object(routes, '_datastore', return_value=db):
                loaded = routes.load_bars('AAPL', 'US', now=now, allow_network=False)
            with patch.dict(sys.modules, {'datastore': db, 'signal_stats_pool': SimpleNamespace(load_cached=lambda market: None)}):
                result = routes.analyze_symbol('AAPL', 'US', now=now, with_stats=False,
                                               bars_loader=lambda *args, **kwargs: loaded, use_cache=False)
            self.assertTrue(result['ok'])
            self.assertEqual(result['session']['calendar']['version'], 'us-equity-sessions-1')
            self.assertEqual(result['session']['calendar']['source'], 'https://www.nyse.com/trade/hours-calendars')
            self.assertEqual(result['session']['expectedLastDate'], loaded['session']['expectedLastDate'])
            if now.year == 2029:
                self.assertIn('交易日曆待確認', result['session']['note'])
                self.assertNotIn('已收盤', result['session']['note'])
                self.assertEqual(result['session']['provisional'], lag == 0)
                if lag:
                    self.assertIn('最新應有交易日尚不能確認', result['session']['note'])
            else:
                self.assertIn('已收盤', result['session']['note'])
            db.upsert_bars.assert_not_called()

    def test_quality_uses_same_early_close_cutoff(self):
        now = datetime.fromisoformat('2026-12-24T19:00:00+00:00')  # 美東 14:00
        result = {'symbol': 'AAPL', 'market': 'US', 'asOf': '2026-12-24', 'session': {'provisional': False}}
        output = quality.assess(result, [{'date':'2026-12-23'}, {'date':'2026-12-24'}], now=now)
        self.assertEqual(output['referenceSession'], '2026-12-24')
        self.assertEqual(output['items'][0]['status'], 'aligned')
        unknown = quality.assess({**result, 'asOf':'2029-01-02'}, [{'date':'2028-12-29'}, {'date':'2029-01-02'}],
                                 now=datetime.fromisoformat('2029-01-02T20:00:00-05:00'))
        self.assertEqual(unknown['referenceSession'], '2028-12-29')
        self.assertEqual(unknown['status'], 'attention')
        self.assertTrue(any('日曆未涵蓋' in note for note in unknown['notes']))


if __name__ == '__main__':
    unittest.main()
