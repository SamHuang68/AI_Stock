"""估值研究唯讀、來源門檻與缺值測試；不呼叫網路。"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import daily_quality
import datastore
import 估值趨勢 as research

NOW = datetime(2026, 10, 2, 20, tzinfo=research.TAIPEI)


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'market.db'
        self.days = [(NOW.date() - timedelta(days=i)).isoformat() for i in range(180, -1, -1)
                     if (NOW.date() - timedelta(days=i)).weekday() < 5]
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript(datastore.SCHEMA + daily_quality.SCHEMA)
            conn.execute('INSERT INTO calendar_years VALUES(?,?,?,?)', (2026, '[]', '[]', NOW.isoformat()))
            conn.executemany('INSERT INTO market_sessions VALUES(?,?)', [(d, 'TWSE開休市') for d in self.days])
            for day in self.days:
                ts = datetime.fromisoformat(day).replace(hour=9, tzinfo=research.TAIPEI).timestamp()
                conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', ts, 100, 102, 98, 100, 1000))
                conn.execute('INSERT INTO bar_quality VALUES(?,?,?,?,?,?,?,?,?,?)',
                             ('TW', '2330', ts, day, 'TWSE', '股', '原始價格', '[]', NOW.isoformat(), '測試來源'))
        self.rows = {research.PE_DATASETS[0]: {'Code': '2330', 'Date': '1151002', 'PEratio': '25', 'DividendYield': '0'},
                     research.REVENUE_DATASETS[0]: {'公司代號': '2330', '出表日期': '1151002', '資料年月': '11509',
                         '營業收入-當月營收': '1000', '營業收入-去年同月增減(%)': '0'}}
        self.lookup = lambda datasets, code: self.rows.get(datasets[0])

    def tearDown(self):
        self.temp.cleanup()

    def detail(self, code='2330', **options):
        return research.get_research(code, database=self.db, lookup=self.lookup, now=NOW, **options)['row']

    def update(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(sql, params)

    def test_contract_retains_zero_and_readonly_hash(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        row = self.detail()
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        self.assertEqual((row['per'], row['yield'], row['revYoy']), (25, 0, 0))
        self.assertTrue(row['research']['scopeEligible'])
        self.assertEqual(row['research']['dataStatus'], 'available')
        self.assertEqual(row['research']['drawdown100'], 0)
        self.assertEqual(row['research']['breakoutVolumeRatio'], 1)
        self.assertEqual(row['research']['rangePosition'], '接近上緣')
        self.assertEqual(row['market']['asOf'], '2026-10-02')
        self.assertEqual(row['market']['source'], 'TWSE')
        self.assertFalse(row['research']['strategyValidated'])
        self.assertFalse(row['research']['pitFinancialsAvailable'])
        # available 僅代表估值範圍與價格結構；不能推論財報或其他資料齊備。
        self.assertIsNone(row['research']['income'])
        self.assertTrue(any('當時可得財報' in reason for reason in row['research']['missing']))
        json.dumps(row, allow_nan=False)

    def test_default_30_adjustable_40_and_exceptions(self):
        self.rows[research.PE_DATASETS[0]]['PEratio'] = '35'
        self.assertEqual(self.detail()['research']['scopeReasonCode'], 'excludedPeAbove')
        self.assertTrue(self.detail(settings={'peMax': 40})['research']['scopeEligible'])
        self.assertEqual(self.detail('3529')['research']['scopeReasonCode'], 'excludedIp')
        self.assertEqual(self.detail('6643')['research']['valuationModel'], '另案估值')
        self.assertTrue(self.detail('3529', settings={'excludeIp': False, 'peMax': 40})['research']['scopeEligible'])

    def test_etf_and_other_markets_do_not_read_company_fundamentals(self):
        self.lookup = Mock(side_effect=AssertionError('不適用市場不可查公司基本面'))
        for symbol, market in [('0050', 'TW'), ('00631L', 'TW'), ('2330', 'US'), ('AAPL', 'US')]:
            row = self.detail(symbol, market=market)
            self.assertEqual(row['research']['dataStatus'], 'not_applicable')
            self.assertIsNone(row['close'])
            self.assertIsNone(row['per'])

    def test_valuation_dates_absent_conflicting_future_and_stale(self):
        for raw, reason in [({}, 'excludedSourceDate'), ({'Date': '錯誤'}, 'excludedSourceDate'),
                           ({'Date': '1151003'}, 'excludedSourceDate'),
                           ({'Date': '1151002', '日期': '1151001'}, 'excludedSourceDate'),
                           ({'Date': '1151001'}, 'excludedStale')]:
            with self.subTest(raw=raw):
                self.rows[research.PE_DATASETS[0]] = {'PEratio': '25', **raw}
                row = self.detail()
                self.assertFalse(row['research']['scopeEligible'])
                self.assertEqual(row['research']['scopeReasonCode'], reason)

    def test_nonfinite_and_nonpositive_pe_never_eligible(self):
        for value in ('NaN', 'Infinity', True, '', None, 0, -1):
            self.rows[research.PE_DATASETS[0]]['PEratio'] = value
            row = self.detail()
            self.assertFalse(row['research']['scopeEligible'])
            json.dumps(row, allow_nan=False)

    def test_market_identity_is_not_stripped_into_wrong_exchange(self):
        mismatch = self.detail('2330.TWO')
        self.assertEqual(mismatch['research']['scopeReasonCode'], 'excludedMarket')
        self.assertEqual(mismatch['research']['scopeReason'], research.SCOPE_REASONS['excludedMarket'])
        self.assertFalse(mismatch['research']['scopeEligible'])
        self.assertEqual(mismatch['research']['dataStatus'], 'partial')
        # 官方估值本身的日期仍留作追溯，不能因此提供不同交易市場的價格。
        self.assertEqual(mismatch['research']['valuationDate'], '2026-10-02')
        self.assertEqual(mismatch['research']['valuationSource'], 'TWSE BWIBBU_ALL')
        self.assertIsNone(mismatch['research']['priceAsOf'])
        self.assertIsNone(mismatch['research']['priceSource'])
        self.assertFalse(mismatch['research']['priceFresh'])
        self.assertIsNone(mismatch['market']['asOf'])
        self.rows[research.PE_DATASETS[1]] = self.rows[research.PE_DATASETS[0]]
        self.assertEqual(self.detail()['research']['scopeReasonCode'], 'excludedMarket')
        del self.rows[research.PE_DATASETS[0]]
        row = self.detail('2330.TWO')
        self.assertIsNone(row['close'])
        self.assertIsNone(row['research']['priceAsOf'])
        self.assertIsNone(row['research']['priceSource'])
        self.assertFalse(row['research']['priceFresh'])
        self.assertEqual(row['research']['valuationSource'], 'TPEx peratio')
        self.assertEqual(row['research']['valuationDate'], '2026-10-02')
        self.assertEqual(row['research']['dataStatus'], 'partial')
        self.assertIn('日線來源與估值交易市場不一致', row['research']['missing'])

    def test_price_and_volume_gaps_never_receive_fallbacks(self):
        self.update('UPDATE bars SET volume=NULL WHERE ts=(SELECT MAX(ts) FROM bars)')
        row = self.detail()
        self.assertEqual(row['close'], 100)
        self.assertIsNone(row['volRatio'])
        self.assertIsNone(row['research']['rangePosition'])
        self.update('UPDATE bars SET high=NULL WHERE ts=(SELECT MAX(ts) FROM bars)')
        row = self.detail()
        self.assertIsNone(row['close'])
        self.assertIsNone(row['market']['price'])

    def test_no_trade_zero_is_preserved_without_breakout(self):
        self.update('UPDATE bars SET volume=0 WHERE ts=(SELECT MAX(ts) FROM bars)')
        row = self.detail()
        self.assertEqual(row['research']['volumeShares'], 0)
        self.assertEqual(row['volRatio'], 0)
        self.assertIsNone(row['research']['rangePosition'])

    def test_missing_session_prevents_compression_and_false_drawdown(self):
        self.update('DELETE FROM bars WHERE ts=(SELECT ts FROM bars ORDER BY ts DESC LIMIT 1 OFFSET 5)')
        row = self.detail()
        self.assertIsNone(row['research']['rangeTop'])
        self.assertIsNone(row['research']['drawdown100'])
        self.assertIsNone(row['volRatio'])

    def test_calendar_and_source_quality_are_required(self):
        self.update("UPDATE bar_quality SET source='未確認' WHERE ts=(SELECT MAX(ts) FROM bars)")
        self.assertIsNone(self.detail()['close'])
        self.update('DELETE FROM calendar_years')
        row = self.detail()
        self.assertEqual(row['research']['scopeReasonCode'], 'excludedStale')
        self.assertFalse(row['research']['priceFresh'])

    def test_prior_intraday_cutoff_never_uses_uncompleted_session(self):
        morning = NOW.replace(hour=10)
        row = research.get_research('2330', database=self.db, lookup=self.lookup, now=morning)['row']
        self.assertEqual(row['research']['priceAsOf'], '2026-10-01')
        self.assertFalse(row['research']['scopeEligible'])

    def test_bad_revenue_source_date_is_not_labeled_zero_growth(self):
        self.rows[research.REVENUE_DATASETS[0]]['出表日期'] = '1151003'
        self.assertIsNone(self.detail()['revYoy'])
        self.rows[research.REVENUE_DATASETS[0]].pop('出表日期')
        self.assertIsNone(self.detail()['revYoy'])

    def test_screen_shares_contract_and_missing_filter_fails(self):
        args = dict(symbols=['2330'], database=self.db, lookup=self.lookup, now=NOW)
        payload = research.run_screen({'research': {'enabled': True}}, **args)
        self.assertEqual(payload['matched'], 1)
        self.assertEqual(payload['results'][0]['research'], self.detail()['research'])
        self.assertEqual(research.run_screen({'chip': {'trustBuyDays': 1}}, **args)['matched'], 0)
        self.assertEqual(research.run_screen({'tech': {'rsiMax': 30}}, **args)['researchMeta']['excluded']['missingTechnical'], 1)
        disabled = {'aboveSma20': False, 'aboveSma60': False, 'bullishAlign': False,
                    'newHigh20': False, 'rsiMin': None, 'rsiMax': None, 'volRatioMin': None}
        self.assertEqual(research.run_screen({'tech': disabled}, **args)['matched'], 1)
        self.assertEqual([r['sym'] for r in payload['researchMeta']['separateSymbols']], ['3529', '6643'])
        self.assertTrue(all(r['excludedFromGeneral'] for r in payload['researchMeta']['separateSymbols']))

    def test_cache_adapter_is_pure_and_preserves_dates(self):
        cache = {'__list__' + research.PE_DATASETS[0]: ('20991231', [self.rows[research.PE_DATASETS[0]]])}
        lookup = research.cached_lookup(cache)
        self.assertEqual(lookup([research.PE_DATASETS[0]], '2330')['Date'], '1151002')
        self.assertIsNone(lookup([research.PE_DATASETS[0]], '9999'))
        found = lookup([research.PE_DATASETS[0]], '2330')
        found['Date'] = '20990101'
        self.assertEqual(lookup([research.PE_DATASETS[0]], '2330')['Date'], '1151002')

    def test_zero_results_include_chinese_exclusion_reasons(self):
        args = dict(symbols=['0050', '2330', '3529'], database=self.db, lookup=self.lookup, now=NOW)
        result = research.run_screen({'tech': {'rsiMax': 30}}, **args)
        self.assertEqual(result['results'], [])
        expected = {'excludedNonStock': 1, 'excludedIp': 1, 'missingTechnical': 1}
        self.assertEqual(result['researchMeta']['excluded'], expected)
        exclusions = result['researchMeta']['exclusions']
        self.assertEqual({item['code']: item['count'] for item in exclusions}, expected)
        for item in exclusions:
            self.assertRegex(item['reason'], '[\u4e00-\u9fff]')
            self.assertEqual(item['reason'], research.EXCLUSION_REASONS[item['code']])
        self.assertEqual(research.run_screen({}, **{**args, 'symbols': ['2330']})['researchMeta']['exclusions'], [])

    def test_missing_database_remains_missing_without_creating_file(self):
        target = Path(self.temp.name) / '不存在.db'
        payload = research.get_research('2330', database=target, lookup=lambda *_: None, now=NOW)
        self.assertFalse(target.exists())
        self.assertIsNone(payload['row']['close'])
        self.assertTrue(payload['row']['research']['missing'])

    def test_invalid_settings_rejected(self):
        for value in (None, True, 'NaN', 0, -1, 201):
            with self.assertRaises(ValueError):
                research.validate_settings({'peMax': value})
        with self.assertRaises(ValueError):
            research.validate_settings({'excludeIp': 'false'})


if __name__ == '__main__':
    unittest.main()
