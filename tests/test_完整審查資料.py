"""完整審查 F08、F18、F20–F23 的離線局部回歸案例。"""
import json
import sqlite3
import sys
import unittest
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import benchmark_research as benchmark
import conditional_expectation as conditional
import datastore
import exposure_lab as exposure
import indicators
import portfolio
import shadow_multifactor as shadow
import trend_quant
import turnover_quant
import 台股交易參考 as calendar


def 日期(n):
    return [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]


def 日線(days):
    return [{'date': day, 'open': 100 + i, 'high': 102 + i,
             'low': 99 + i, 'close': 101 + i, 'volume': 1000}
            for i, day in enumerate(days)]


class 資料修正案例(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('案例禁止外網')))
        self.stack.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('案例禁止外網')))
        self.stack.enter_context(patch.object(datastore, 'get_conn', side_effect=AssertionError('案例禁止存取執行中資料庫')))

    def test_F18_跨日小變動追加同日大變動覆寫(self):
        bars = [{'date': '2026-10-12', 'close': 100}]
        next_day = trend_quant.price_series_quant(bars, latest=101, latest_date='2026-10-13')
        same_day = trend_quant.price_series_quant(bars, latest=150, latest_date='2026-10-12')
        unknown = trend_quant.price_series_quant(bars, latest=150)
        self.assertEqual((next_day['n'], next_day['spark']), (2, [100, 101]))
        self.assertEqual((same_day['n'], same_day['spark']), (1, [150]))
        self.assertEqual(unknown['spark'], [100])
        self.assertFalse(unknown['latestMerged'])

    def test_F18_成交額依來源日保留零值(self):
        bars = [{'sourceDate': '2026-10-12', 'amount': 100 * 1e8}]
        newer = turnover_quant.turnover_quant(bars, 101, '2026-10-13')
        same = turnover_quant.turnover_quant(bars, 150, '2026-10-12')
        zero = turnover_quant.turnover_quant(bars, 0, '2026-10-13')
        self.assertEqual((newer['n'], same['n'], zero['n']), (2, 1, 2))
        self.assertEqual(zero['yi'], 0)

    def test_F20_缺月後重新累積波動視窗(self):
        days = 日期(300)
        rows = [{'date': day, 'totalReturnIndex': 100 + i + (i % 2)} for i, day in enumerate(days)]
        rows = rows[:260] + rows[280:]
        with patch.object(calendar, 'verified_sessions', return_value=days):
            out = exposure._benchmark_volatility('FTSE_TAIWAN_50', {'rows': rows, 'quality': 'ready'})
        self.assertEqual(out['sampleDays'], 20)
        self.assertIsNone(out['stateDownside20AnnualPct']['value'])
        self.assertIsNone(out['realized252AnnualPct']['value'])
        self.assertEqual(out['status'], 'insufficient')

    def test_F20_日曆未知不得產生波動(self):
        with patch.object(calendar, 'verified_sessions', return_value=None):
            out = exposure._benchmark_volatility('FTSE_TAIWAN_50', {
                'rows': [{'date': d, 'totalReturnIndex': 100 + i} for i, d in enumerate(日期(300))]})
        self.assertEqual(out['sampleDays'], 0)
        self.assertIsNone(out['realized252AnnualPct']['value'])

    def test_F20_來源涵蓋失敗不得標示完整(self):
        days = 日期(757)
        rows = [{'date': d, 'priceIndex': 100 + i, 'totalReturnIndex': 100 + i} for i, d in enumerate(days)]
        with patch.object(benchmark, '_read_rows', return_value=rows), \
             patch.object(benchmark, '_read_coverage', return_value={'requestedStart': days[0], 'failedMonths': {'2025-06': 'TimeoutError'}}), \
             patch.object(benchmark, '_local_product_series', return_value={}), \
             patch.object(calendar, 'verified_sessions', return_value=days):
            out = benchmark.snapshot(allow_network=False)['FTSE_TAIWAN_50']
        self.assertEqual(out['quality'], 'partial_scope')
        self.assertFalse(out['coverage']['continuous'])

    def test_F21_最新狀態只統計同組成熟樣本(self):
        horizon = str(shadow.LONG_HORIZONS[0])
        observations = [
            {'binId': '甲', 'outcomes': {horizon: {'returnPct': 10, 'maxDrawdownPct': -2}}},
            {'binId': '乙', 'outcomes': {horizon: {'returnPct': -90, 'maxDrawdownPct': -95}}},
            {'binId': '甲', 'outcomes': {}},
        ]
        current = {'binId': '甲', 'binModelId': '測試模型', 'asOfDate': '2026-10-13'}
        with patch.object(shadow, '_collect_long_horizon_observations', return_value=observations), \
             patch.object(shadow, 'bin_state', return_value=current) as state, \
             patch.object(shadow, 'regime_at_date', return_value='測試狀態'), \
             patch.object(shadow, 'aggregate_horizon_stats', side_effect=lambda returns, drawdowns: {'returns': returns, 'drawdowns': drawdowns}):
            out = shadow._long_horizon_card('2330', bars=[], as_of=date(2026, 10, 13))
        self.assertEqual(out['binId'], '甲')
        self.assertEqual(out['asOfDate'], '2026-10-13')
        self.assertEqual(out['horizons'][horizon], {'returns': [10.0], 'drawdowns': [-2.0]})
        self.assertEqual(state.call_args.args[1], date(2026, 10, 13))

    def test_F22_缺交易日保留空列不壓縮持有期(self):
        days = 日期(4)
        bars = 日線(days)
        with patch.object(calendar, 'verified_sessions', return_value=days):
            rows = conditional._research_rows([bars[0], bars[2], bars[3]])
        self.assertEqual(len(rows), 4)
        self.assertIsNone(rows[1][4])
        self.assertIsNone(conditional._forward_outcome(rows, 0, 2, prepared=True))
        self.assertIsNone(shadow._forward_outcome(rows, 0, 2, prepared=True))
        self.assertAlmostEqual(conditional._forward_outcome(rows, 2, 1, prepared=True)['returnPct'], (104 / 103 - 1) * 100)

    def test_F22_未準備序列仍核對交易日(self):
        rows = [('2025-01-01', 100, 100, 100, 100, 1), ('2025-01-03', 110, 110, 110, 110, 1)]
        with patch.object(calendar, 'verified_sessions', return_value=日期(3)):
            self.assertIsNone(conditional._forward_outcome(rows, 0, 1))
            self.assertIsNone(shadow._forward_outcome(rows, 0, 1))

    def test_F23_缺量高低價不製造突破且保留收盤指標(self):
        bars = 日線(日期(65))
        bars[-2]['high'] = None
        bars[-2]['low'] = None
        bars[-2]['volume'] = None
        out = indicators.candle_snapshot(bars)
        self.assertIsNone(out['high20'])
        self.assertIsNone(out['low20'])
        self.assertIsNone(out['volRatio'])
        self.assertIsNotNone(out['sma60'])
        self.assertIsNotNone(out['rsi14'])

    def test_F23_日期缺口後重新暖機保留現價(self):
        days = 日期(65)
        bars = 日線(days)
        with patch.object(calendar, 'verified_sessions', return_value=days), \
             patch.object(calendar, 'trading_status', return_value=None):
            out = indicators.dated_candle_snapshot(bars[:60] + bars[61:], 'TW', '2330')
        self.assertEqual(out['continuousBars'], 4)
        self.assertEqual(out['close'], 165)
        self.assertIsNone(out['sma5'])
        self.assertIsNone(out['rsi14'])

    def test_F08_未知涵蓋與已知分割不可使用原價(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.executescript(datastore.SCHEMA)
        bars = 日線(['2026-10-12', '2026-10-13'])
        with patch.object(calendar, 'split_references', return_value=[]), \
             patch.object(calendar, 'trading_status', return_value=None):
            series, issue = portfolio._risk_series(conn, '2330', bars)
        self.assertEqual(series, {})
        self.assertIn('涵蓋不足', issue)
        with patch.object(calendar, 'split_references', return_value=[{'date': '2026-10-13'}]), \
             patch.object(calendar, 'trading_status', return_value=None):
            series, issue = portfolio._risk_series(conn, '2330', bars)
        self.assertEqual(series, {})
        self.assertIn('公司行動', issue)

    def test_F08_有效還原快照被採用且來源衝突優先阻擋(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.executescript(datastore.SCHEMA)
        conn.execute('CREATE TABLE stock_adjustment_snapshots(market TEXT,symbol TEXT,fetched_at INTEGER,payload TEXT)')
        bars = 日線(['2026-10-12', '2026-10-13'])
        snapshot = {'rows': [{'date': b['date'], 'rawClose': b['close'], 'adjClose': b['close'] / 2} for b in bars], 'events': {}}
        conn.execute('INSERT INTO stock_adjustment_snapshots VALUES(?,?,?,?)', ('TW', '2330', 1, json.dumps(snapshot)))
        with patch.object(calendar, 'trading_status', return_value=None):
            series, issue = portfolio._risk_series(conn, '2330', bars)
        self.assertIsNone(issue)
        self.assertEqual(series, {'2026-10-12': 50.5, '2026-10-13': 51})
        with patch('daily_quality.quality_evidence', return_value={'2026-10-12': {'sourceConflict': True}}):
            rejected, issue = portfolio._risk_series(conn, '2330', bars)
        self.assertEqual(rejected, {})
        self.assertIn('衝突', issue)

    def test_F08_缺資料持倉仍保留完整權重分母(self):
        from contextlib import nullcontext
        days = 日期(65)
        valid = {day: 100 + i + i % 2 for i, day in enumerate(days)}
        with patch.object(datastore, 'read_snapshot', return_value=nullcontext(object())), \
             patch.object(datastore, 'get_bars_bulk', return_value={}), \
             patch.object(portfolio, '_risk_series', side_effect=lambda conn, code, rows, **kw: (valid, None) if code != '2317' else ({}, '缺少歷史')), \
             patch.object(calendar, 'verified_sessions', return_value=days):
            out = portfolio.compute([{'sym': '2330', 'weight': 1}, {'sym': '2317', 'weight': 3}])
        self.assertEqual(out['stocks']['2330']['weight'], 25)
        self.assertEqual(out['quality']['holdingCoveragePct'], 25)
        self.assertIsNone(out['portfolio']['vol'])
        self.assertEqual(out['skipped'], ['2317'])

    def test_F22_短期限成熟不必等待最長期限(self):
        days = 日期(22)
        def sessions(start, stop, **kwargs):
            return [day for day in days if start <= day <= stop]
        with patch.object(calendar, 'verified_sessions', side_effect=sessions):
            out = conditional.collect_pit_observations('2330', 日線(days), regime_lookup=lambda day: '測試狀態')
        self.assertEqual([item['sessionDate'] for item in out], days[19:21])
        self.assertTrue(all('1' in item['outcomes'] for item in out))
        self.assertTrue(all('20' not in item['outcomes'] for item in out))
    def _pulse(self, target_day, quote, *, night=False):
        from unittest.mock import MagicMock
        import pulse_orchestration as pulse
        import industry_revenue
        import pulse_intel
        payload = json.dumps({'chart': {'result': [quote]}}).encode()
        cache = MagicMock()
        cache.get.return_value = None
        fetch = MagicMock(return_value=(None, payload, None))
        deps = pulse.PulseDeps(
            cache=cache, pulse_extras_pool=MagicMock(), pulse_side_pool=MagicMock(),
            build_tw_market_fundamental=lambda *a, **k: {},
            build_breadth_payload=lambda **k: {'ok': True, 'date': target_day,
                'indices': {'t00': {'price': 101, 'sourceDate': target_day, 'source': '測試來源'}}},
            fmtqik_turnover=lambda **k: [],
            fmtqik_index_closes=lambda *a, **k: [],
            tw_index_closes=lambda *a, **k: [{'date': '2026-10-12', 'close': 100}],
            turnover_quant=turnover_quant.turnover_quant,
            price_series_quant=trend_quant.price_series_quant,
            macro_latest=lambda *a, **k: None, fetch_one=fetch,
        )
        handler = MagicMock()
        handler._txf_mis_session.return_value = ({'session': 'night', 'price': 120, 'tradeDate': '2026-10-13'} if night else None)
        with patch.object(pulse, '_deps', deps), \
             patch.object(pulse, 'collect_named', return_value=({}, {})), \
             patch.object(industry_revenue, 'get_aggregate', return_value={'ok': False}), \
             patch.object(industry_revenue, 'market_flash_item', return_value=None), \
             patch.object(pulse_intel, 'build_pulse_intel', return_value={'ok': False}), \
             patch.object(datastore, 'get_bars', side_effect=RuntimeError('案例不執行非受測決策發布')):
            out = json.loads(pulse.build_pulse_payload(handler, '/pulse?refresh=1'))
        fetch.assert_called_once_with('^TWII', '5d', '1d', False)
        cache.set.assert_not_called()
        return out

    def test_F19_只回補同日同列不跨欄取舊值(self):
        quote = {'timestamp': ['2026-10-12', '2026-10-13'], 'indicators': {'quote': [{
            'open': [80, 100], 'high': [200, None], 'low': [70, 99]}]}}
        out = self._pulse('2026-10-13', quote)['overview']['ohlc']
        self.assertEqual(out['open'], 100)
        self.assertIsNone(out['high'])
        self.assertEqual(out['low'], 99)
        self.assertEqual(out['sourceDate'], '2026-10-13')

    def test_F19_來源日期不符與價格矛盾不回補(self):
        for source_day, high in [('2026-10-12', 102), ('2026-10-13', 90)]:
            with self.subTest(來源日=source_day, 最高價=high):
                quote = {'timestamp': [source_day], 'indicators': {'quote': [{
                    'open': [100], 'high': [high], 'low': [99]}]}}
                out = self._pulse('2026-10-13', quote)['overview']['ohlc']
                self.assertIsNone(out['open'])
                self.assertIsNone(out['high'])
                self.assertIsNone(out['low'])
                self.assertEqual(out['source'], '測試來源')

    def test_F18_夜盤現價不得覆寫日線(self):
        quote = {'timestamp': ['2026-10-13'], 'indicators': {'quote': [{
            'open': [100], 'high': [102], 'low': [99]}]}}
        out = self._pulse('2026-10-13', quote, night=True)
        self.assertEqual(out['txf']['price'], 120)
        self.assertEqual(out['overview']['strip']['txfTrend']['spark'], [100])
        self.assertFalse(out['overview']['strip']['txfTrend']['latestMerged'])

if __name__ == '__main__':
    unittest.main()
