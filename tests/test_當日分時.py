"""兩標的真實分鐘節錄及明示合成邊界；網路與日線寫入均隔離。"""
import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import txf_intraday as minute
with patch('slog.get_logger', return_value=Mock()):
    import quote_api
import tw_index_charts as daily


def recorded(symbol):
    path = Path(__file__).with_name('fixtures') / '當日分鐘來源.json'
    return json.loads(path.read_text(encoding='utf-8'))['sources'][symbol]


def html(chart, key=None):
    key = key or chart['meta']['symbol']
    return 'root.App.main = ' + json.dumps({'context': {'dispatcher': {'stores': {
        'MarketChartStore': {'libra': {'不相關節點': {'timestamp': [1]}, key: chart}}
    }}}}) + ';'


class IntradayTests(unittest.TestCase):
    def setUp(self):
        for target, name, replacement in (
            (minute, '_cached', None), (minute, '_twoii_cached', None),
            (minute, 'urlopen', Mock(side_effect=AssertionError('測試禁止連外'))),
            (daily, '_write_csv', Mock(side_effect=AssertionError('分鐘不得寫日線'))),
        ):
            guard = patch.object(target, name, replacement)
            guard.start()
            self.addCleanup(guard.stop)
            if isinstance(replacement, Mock):
                self.addCleanup(replacement.assert_not_called)
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('測試禁止備援連外'))
        network = guard.start()
        self.addCleanup(guard.stop)
        self.addCleanup(network.assert_not_called)

    def parse(self, symbol, chart=None):
        item = recorded(symbol)
        return minute.parse_html(html(chart or item['chart'], minute.SOURCES[symbol][0]),
                                 symbol=symbol, now=datetime.fromisoformat(item['observedAt']).timestamp())

    def test_recorded_two_symbols_preserve_real_ohlcv(self):
        for symbol in minute.SOURCES:
            with self.subTest(symbol=symbol):
                chart = recorded(symbol)['chart']
                result = self.parse(symbol)
                quotes = chart['indicators']['quote'][0]
                valid = [i for i in range(len(chart['timestamp'])) if all(quotes[k][i] is not None for k in ('open', 'high', 'low', 'close'))]
                self.assertEqual([r['time'] for r in result['candles']], [chart['timestamp'][i] for i in valid])
                for key in ('open', 'high', 'low', 'close', 'volume'):
                    self.assertEqual([r[key] for r in result['candles']], [quotes[key][i] for i in valid])
                self.assertEqual(result['sourceTimestamp'], chart['meta']['regularMarketTime'])
                self.assertEqual(result['previousClose'], chart['meta']['chartPreviousClose'])

    def test_recorded_txf_0500_endpoint_and_0845_session(self):
        result = self.parse('__TXF__')
        by_time = {r['time']: r for r in result['candles']}
        self.assertEqual(by_time[result['sessions'][0]['end']]['session'], 0)
        start = result['sessions'][1]['start']
        # 實際來源 08:45 是空列；必須保留 fixture 並省略空價格，不補造開盤。
        self.assertIn(start, recorded('__TXF__')['chart']['timestamp'])
        self.assertNotIn(start, by_time)
        self.assertEqual(result['candles'][-1]['session'], 1)

    def test_twoii_real_ohlc_is_not_close_repeated(self):
        rows = self.parse('^TWOII')['candles']
        self.assertTrue(any(len({r['open'], r['high'], r['low'], r['close']}) > 1 for r in rows))

    def test_synthetic_closing_boundaries_include_end_reject_next_minute(self):
        # 明示合成案例：沿用來源盤別，單根價格只作邊界驗證，不是實際成交證據。
        for symbol in minute.SOURCES:
            original = recorded(symbol)['chart']
            periods = original['meta'].get('sourceTradingPeriods') or original['meta']['tradingPeriods']
            end = periods[0][0]['end']
            for delta in (0, 60):
                with self.subTest(symbol=symbol, delta=delta):
                    chart = copy.deepcopy(original)
                    chart['timestamp'] = [end + delta]
                    chart['meta']['regularMarketTime'] = end + delta
                    chart['indicators']['quote'] = [{'open': [100], 'high': [102], 'low': [99], 'close': [101], 'volume': [1]}]
                    if delta:
                        with self.assertRaisesRegex(ValueError, '超出'):
                            minute.parse_html(html(chart), symbol=symbol, now=end + 120)
                    else:
                        result = minute.parse_html(html(chart), symbol=symbol, now=end + 120)
                        self.assertEqual(result['candles'][0]['time'], end)

    def test_identity_timezone_granularity_range_and_future_rejected(self):
        for symbol in minute.SOURCES:
            for key, value in (('symbol', '錯誤標的'), ('exchange', '錯誤交易所'),
                               ('exchangeTimezoneName', 'UTC'), ('dataGranularity', '1d'),
                               ('range', '1y'), ('regularMarketTime', 9999999999)):
                with self.subTest(symbol=symbol, field=key):
                    chart = recorded(symbol)['chart']
                    chart['meta'][key] = value
                    with self.assertRaises(ValueError):
                        self.parse(symbol, chart)

    def test_named_node_required(self):
        for symbol in minute.SOURCES:
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                minute.parse_html(html(recorded(symbol)['chart'], '錯誤節點'), symbol=symbol)

    def test_missing_prices_volume_and_previous_close_not_fabricated(self):
        for symbol in minute.SOURCES:
            with self.subTest(symbol=symbol):
                chart = recorded(symbol)['chart']
                quotes = chart['indicators']['quote'][0]
                valid = [i for i in range(len(chart['timestamp'])) if quotes['open'][i] is not None]
                first = chart['timestamp'][valid[0]]
                quotes['open'][valid[0]] = None
                quotes['volume'][valid[1]] = None
                chart['meta']['chartPreviousClose'] = None
                result = self.parse(symbol, chart)
                self.assertNotIn(first, [r['time'] for r in result['candles']])
                self.assertIsNone(result['candles'][0]['volume'])
                self.assertIsNone(result['previousClose'])
                self.assertEqual(result['missing'], {'invalidPriceBars': 1, 'unknownVolumeBars': 1})

    def test_chart_json_preserves_minute_contract(self):
        for symbol in minute.SOURCES:
            with self.subTest(symbol=symbol):
                result = self.parse(symbol)
                payload = json.loads(minute.chart_json(symbol, result=result))['chart']
                chart = payload['result'][0]
                self.assertIsNone(payload['error'])
                self.assertEqual(chart['meta']['symbol'], symbol)
                self.assertEqual(chart['meta']['dataGranularity'], '1m')
                self.assertEqual(chart['meta']['range'], '1d')
                self.assertTrue(chart['meta']['_verifiedIntraday'])
                self.assertEqual(chart['timestamp'], [r['time'] for r in result['candles']])
                self.assertEqual(chart['meta']['sourceTradingPeriods'], [result['sessions']])
                for key in ('open', 'high', 'low', 'close', 'volume'):
                    self.assertEqual(chart['indicators']['quote'][0][key], [r[key] for r in result['candles']])

    def test_cache_isolated_between_symbols_and_returned_copies(self):
        now = datetime.fromisoformat(recorded('__TXF__')['observedAt']).timestamp()
        for symbol in minute.SOURCES:
            minute.get(symbol=symbol, now=now, fetch=lambda s=symbol: html(recorded(s)['chart']))
        for symbol in minute.SOURCES:
            result = minute.get(symbol=symbol, now=now + 1, fetch=lambda: self.fail('快取命中不應抓取'))
            self.assertEqual(result['symbol'], symbol)
            self.assertTrue(result['cached'])
            result['candles'].clear()
            self.assertTrue(minute.get(symbol=symbol, now=now + 2)['candles'])

    def test_fetch_failure_returns_empty_chart_without_daily_write(self):
        for symbol in minute.SOURCES:
            with self.subTest(symbol=symbol):
                result = minute.get(symbol=symbol, fetch=Mock(side_effect=ValueError('合成來源錯誤')))
                chart = json.loads(minute.chart_json(symbol, result=result))['chart']
                self.assertIsNone(chart['result'])
                self.assertFalse(chart['error']['ok'])
                self.assertEqual(chart['error']['candles'], [])
        daily._write_csv.assert_not_called()

    def test_quote_route_uses_existing_minute_source_and_no_daily_cache(self):
        cache = Mock()
        cache.get.return_value = '不可誤用的日線快取'.encode()
        with patch.dict(quote_api._CFG, {'cache': cache}), patch.object(daily, 'chart_json') as daily_chart:
            for symbol in minute.SOURCES:
                expected = minute.chart_json(symbol, result=self.parse(symbol))
                with patch.object(minute, 'chart_json', return_value=expected) as source:
                    self.assertEqual(quote_api.fetch_one(symbol, rng='1d', interval='1m'), (symbol, expected, False))
                    source.assert_called_once_with(symbol)
            cache.get.assert_not_called()
            cache.set.assert_not_called()
            daily_chart.assert_not_called()

    def test_quote_source_exception_never_falls_through_to_yahoo(self):
        for symbol in ('__TXF__', '^TWOII', '%5ETWOII', 'TXF'):
            with self.subTest(symbol=symbol), patch.object(minute, 'chart_json', side_effect=ValueError('合成來源錯誤')), patch.object(daily, 'chart_json') as daily_chart:
                _, payload, cached = quote_api.fetch_one(symbol, rng='1d', interval='1m')
                self.assertIsNone(payload['chart']['result'])
                self.assertTrue(payload['chart']['error'])
                self.assertFalse(cached)
                daily_chart.assert_not_called()

    def test_daily_route_preserves_existing_provider_and_cache(self):
        for symbol in minute.SOURCES:
            with self.subTest(symbol=symbol):
                cache = Mock()
                cache.get.return_value = None
                with patch.dict(quote_api._CFG, {'cache': cache}), patch.object(daily, 'chart_json', return_value='日線契約'.encode()) as provider, patch.object(minute, 'chart_json') as intraday:
                    self.assertEqual(quote_api.fetch_one(symbol, rng='1d', interval='1d'), (symbol, '日線契約'.encode(), False))
                    provider.assert_called_once_with(symbol, range_key='1d')
                    cache.get.assert_called_once_with(f'{symbol}|1d|1d')
                    cache.set.assert_called_once_with(f'{symbol}|1d|1d', '日線契約'.encode())
                    intraday.assert_not_called()
                daily._write_csv.assert_not_called()


if __name__ == '__main__':
    unittest.main()
