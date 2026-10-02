"""獨立期望值：市場、交易日期、來源身分、缺值切段與官方雜湊。"""
import copy
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import daily_cache_jobs as jobs
import datastore as ds
import portfolio
import stock_signals as ss
import signal_stats_pool as pool
import 台股日線 as daily
from tests.test_stock_signals import make_bars


class DataBoundaries(unittest.TestCase):
    def test_market_and_input_shapes_are_rejected_before_network(self):
        for body in (None, [], {'symbols': [{'symbol': 'AAPL', 'market': 'TW'}]},
                     {'symbols': [{'symbol': '2330.TW', 'market': 'US'}]},
                     {'symbols': [{'symbol': '^TWII', 'market': 'US'}]},
                     {'symbols': [{'symbol': 'AAPL', 'market': 'US'}], 'range': []}):
            with self.subTest(body=body), self.assertRaises(ValueError): jobs.validate(body)
        self.assertEqual(jobs.validate({'symbols': [{'symbol': '00632R', 'market': 'TW'}]})[0][0]['symbol'], '00632R')

    def test_provider_identity_mismatch_never_returns_rows(self):
        base = {'chart': {'result': [{'meta': {}, 'timestamp': [1], 'indicators': {'quote': [
            {k: [v] for k, v in {'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 1}.items()}]}}]}}
        for meta in ({'symbol': '2317.TW'}, {'symbol': '2330.TW', 'exchangeTimezoneName': 'America/New_York'}, {'dataGranularity': '1m'}):
            value = copy.deepcopy(base); value['chart']['result'][0]['meta'] = meta
            with patch.object(ds.urllib.request, 'urlopen', side_effect=lambda *a, **k: StringIO(json.dumps(value))), self.assertRaises(RuntimeError):
                ds.fetch_yahoo_daily('2330', 'TW', retries=1)

    def test_equal_sessions_with_different_times_have_equal_returns(self):
        rows = [(daily.stamp(date(2026, 1, 1) + timedelta(days=i)), 100+i, 101+i, 99+i, 100+i, 1000) for i in range(90)]
        offset = [(r[0]+3600, *r[1:]) for r in rows]
        with patch.object(ds, 'get_bars_bulk', return_value={'2330': rows, '2317': offset, '^TWII': rows}):
            result = portfolio.compute([{'sym': '2330', 'weight': 1}, {'sym': '2317', 'weight': 1}])
        self.assertEqual(result['portfolio']['days'], 89)
        self.assertEqual(result['corr']['2330|2317'], 1)
        self.assertEqual(result['stocks']['2317']['beta'], 1)

    def test_unknown_volume_preserves_gap_and_restarts_health_warmup(self):
        rows = make_bars([100.0] * 140)
        rows[100]['volume'] = None
        normalized = ss.normalize_bars(rows)
        self.assertEqual(len(normalized), 140)
        self.assertIsNone(normalized[100]['volume'])
        self.assertFalse(ss.complete_bar(normalized[100]))
        zero = {**normalized[100], 'volume': 0}
        self.assertTrue(ss.complete_bar(zero))
        result = ss.analyze(normalized, symbol='2330')
        self.assertFalse(result['ok']); self.assertEqual(result['bars'], 39)
        frame = ss.build_frame(normalized)
        self.assertIsNone(frame['sma60'][110])
        self.assertEqual(ss.forward_outcomes(frame, [98], 5, 'bull'), [])

    def test_pooled_baseline_cannot_cross_missing_price_or_volume(self):
        rows = make_bars([100+i for i in range(300)])
        rows[150]['high'] = None
        result = pool.compute_pooled([('2330', ss.normalize_bars(rows))], horizons=[5])
        # 150 根與149根的兩段，各自60根暖機，保留5根前瞻。
        expected = (150 - 60 - 5) + (149 - 60 - 5)
        self.assertEqual(next(iter(result['signals'].values()))['horizons'][0]['baseN'], expected)

    def test_official_response_symbol_and_month_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'test.db'
            base = {'stat': 'OK', 'date': '20250901', 'title': '114年09月 2330 台積電 各日成交資訊',
                    'fields': ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價'],
                    'data': [['114/09/01', '1000', '100000', '100', '101', '99', '100']]}
            for change in ({'title': '114年09月 2317 鴻海 各日成交資訊'}, {'date': '20250801'}, {'title': ''}):
                response = {**base, **change}
                with patch.object(daily, 'stored_calendar', return_value=(set(), set())), patch.object(daily, 'reconcile_sessions'), patch.object(ds, 'upsert_bars') as write, self.assertRaisesRegex(ValueError, '身分'):
                    daily.seed_research(db, years=1, now=datetime(2026,9,11,20,tzinfo=daily.TZ), fetch=lambda url:(response,'fixture'))
                write.assert_not_called()

    def test_official_conflict_preserves_original_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'test.db'; ds.init_db(db)
            row = (daily.stamp(date(2026,9,11)),100,102,99,101,1000)
            ds.upsert_bars('2330','TW',[row],source='TWSE',source_hash='原始雜湊',path=db)
            ds.upsert_bars('2330','TW',[(row[0],100,102,99,102,1000)],source='TWSE',source_hash='修訂雜湊',path=db)
            with ds.read_snapshot(db) as conn:
                self.assertEqual(conn.execute('SELECT close FROM bars').fetchone()[0], 101)
                quality = conn.execute('SELECT source,source_hash,issues FROM bar_quality').fetchone()
                self.assertEqual(quality[:2], ('TWSE','原始雜湊'))
                self.assertIn('原始值保留', quality[2])
                self.assertEqual(conn.execute('SELECT count(*) FROM official_daily_observations').fetchone()[0], 2)


if __name__ == '__main__': unittest.main()
