# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import tw_index_charts  # noqa: E402


class TwIndexChartRowsTest(unittest.TestCase):
    def test_daily_import_rejects_night_and_unknown_sessions(self):
        base = {'contract_date': '202610', 'open': 100, 'max': 105, 'min': 99, 'close': 101, 'volume': 10}
        payload = {'status': 200, 'data': [
            {**base, 'date': '2026-09-16', 'trading_session': 'position'},
            {**base, 'date': '2026-09-16', 'trading_session': 'after_market', 'close': 102, 'volume': 500},
            {**base, 'date': '2026-09-17', 'trading_session': 'after_market'},
            {**base, 'date': '2026-09-18', 'trading_session': 'unknown'},
            {**base, 'date': '2026-09-21'},
            {**base, 'date': '2026-09-22', 'trading_session': ''},
        ]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(tw_index_charts, '_throttle'), patch.object(
                tw_index_charts.urllib.request, 'urlopen', return_value=response):
            rows = tw_index_charts._fetch_txf_finmind('2026-09-01', '2026-09-22')
        self.assertEqual(rows, [('2026-09-16', 100., 105., 99., 101., 10.)])

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


if __name__ == '__main__':
    unittest.main()
