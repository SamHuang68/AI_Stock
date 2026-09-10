# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import quote_api  # noqa: E402
import tw_index_charts  # noqa: E402

# 2026-09-07 15:01 / 15:02 / 15:03 Asia/Taipei（夜盤開盤後 1 分 K）
_WTX_HTML = (
    '<html><script>root.App.main = {"x":1};\n</script>'
    '"dataGranularity":"1m",'
    '"timestamp":[1757228460,1757228520,1757228580],'
    '"close":[47400.0,null,47350.0],'
    '"open":[47410,47405,47390],'
    '"high":[47420,47410,47400],'
    '"low":[47390,47380,47340],'
    '"volume":[10,11,20],'
    '"chartPreviousClose":47462.0,'
    '"regularMarketPrice":47350.0'
    '</html>'
)


class TwIndexChartRowsTest(unittest.TestCase):
    def test_recent_txf_rows_preserve_dates_for_same_session_basis(self):
        rows = [
            ('2026-08-12', 100, 102, 99, 101, 10),
            ('2026-08-13', 101, 104, 100, 103, 20),
        ]
        with patch.dict(tw_index_charts._mem, {'__TXF__': (1.0, rows)}, clear=False):
            out = tw_index_charts.recent_rows('__TXF__', 2, allow_network=False)
        self.assertEqual([x['date'] for x in out], ['2026-08-12', '2026-08-13'])
        self.assertEqual(out[-1]['close'], 103)
        self.assertEqual(out[-1]['session'], 'day')


class TxfIntradayChartTest(unittest.TestCase):
    def test_is_txf_intraday_request_only_one_day(self):
        self.assertTrue(tw_index_charts.is_txf_intraday_request('1d', '1m'))
        self.assertTrue(tw_index_charts.is_txf_intraday_request('1d', '5m'))
        self.assertTrue(tw_index_charts.is_txf_intraday_request('1d', ''))
        self.assertFalse(tw_index_charts.is_txf_intraday_request('1d', '1d'))
        self.assertFalse(tw_index_charts.is_txf_intraday_request('1y', '1m'))
        self.assertFalse(tw_index_charts.is_txf_intraday_request('3mo', '1d'))
        self.assertFalse(tw_index_charts.is_txf_intraday_request('6mo', '1d'))

    def test_parse_wtx_intraday_embed_keeps_night_minutes(self):
        parsed = tw_index_charts.parse_wtx_intraday_embed(_WTX_HTML)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['timestamp'], [1757228460, 1757228580])
        self.assertEqual(parsed['close'], [47400.0, 47350.0])
        self.assertEqual(parsed['chartPreviousClose'], 47462.0)
        self.assertEqual(parsed['regularMarketPrice'], 47350.0)
        # 相鄰有效棒 120 秒，不是日線 86400
        self.assertEqual(parsed['timestamp'][1] - parsed['timestamp'][0], 120)

    def test_chart_json_txf_intraday_yahoo_shape(self):
        with patch.object(tw_index_charts, '_wtx_quote_html', return_value=_WTX_HTML):
            raw = tw_index_charts.chart_json_txf_intraday('1m')
        body = json.loads(raw)
        result = body['chart']['result'][0]
        meta = result['meta']
        self.assertEqual(meta['symbol'], '__TXF__')
        self.assertEqual(meta['dataGranularity'], '1m')
        self.assertEqual(meta['range'], '1d')
        self.assertIn('WTX', meta.get('_source') or '')
        self.assertNotIn('FinMind', meta.get('_source') or '')
        self.assertEqual(result['timestamp'], [1757228460, 1757228580])
        self.assertEqual(result['indicators']['quote'][0]['close'][-1], 47350.0)

    def test_resample_5m_buckets(self):
        parsed = {
            'timestamp': [100, 160, 220],
            'open': [1.0, 2.0, 3.0],
            'high': [1.5, 2.5, 3.5],
            'low': [0.5, 1.5, 2.5],
            'close': [1.2, 2.2, 3.2],
            'volume': [10, 20, 30],
            'regularMarketPrice': 3.2,
            'chartPreviousClose': 1.0,
        }
        out = tw_index_charts._resample_ohlc(parsed, 300)
        self.assertEqual(out['timestamp'], [0])
        self.assertEqual(out['open'], [1.0])
        self.assertEqual(out['high'], [3.5])
        self.assertEqual(out['low'], [0.5])
        self.assertEqual(out['close'], [3.2])
        self.assertEqual(out['volume'], [60])


class QuoteApiTxfRouteTest(unittest.TestCase):
    def setUp(self):
        quote_api.configure(cache=None, src_record=None, yf_headers={})

    def test_fetch_one_txf_1d_1m_uses_wtx_intraday(self):
        fake = b'{"chart":{"result":[{"meta":{"dataGranularity":"1m","_source":"yahoo-tw-WTX 1m"}}]}}'
        with patch('tw_index_charts.chart_json_txf_intraday', return_value=fake) as intra:
            with patch('tw_index_charts.chart_json') as daily:
                sym, data, cached = quote_api.fetch_one('__TXF__', rng='1d', interval='1m')
        intra.assert_called_once_with('1m')
        daily.assert_not_called()
        self.assertEqual(sym, '__TXF__')
        self.assertEqual(data, fake)
        self.assertFalse(cached)

    def test_fetch_one_txf_1y_stays_finmind_daily(self):
        fake = b'{"chart":{"result":[{"meta":{"dataGranularity":"1d","_source":"FinMind TaiwanFuturesDaily TX"}}]}}'
        with patch('tw_index_charts.chart_json', return_value=fake) as daily:
            with patch('tw_index_charts.chart_json_txf_intraday') as intra:
                quote_api.fetch_one('__TXF__', rng='1y', interval='1d')
        daily.assert_called_once()
        intra.assert_not_called()


if __name__ == '__main__':
    unittest.main()
