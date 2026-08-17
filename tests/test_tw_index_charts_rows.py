# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import tw_index_charts  # noqa: E402


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


if __name__ == '__main__':
    unittest.main()
