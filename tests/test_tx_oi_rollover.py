"""審查 D-03：台指期主力契約切換日不得把轉倉算成同契約增倉。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))

import pulse_extras as px  # noqa: E402


def _row(contract, volume, oi, close):
    return {'contract_date': contract, 'volume': volume, 'open_interest': oi, 'close': close}


class TxOiRolloverTest(unittest.TestCase):
    def test_main_contract_switch_returns_none(self):
        # 前一日近月為主力；當日次月量超過近月。舊版以次月前一日 30k 為基準得到 +50% 假增倉，
        # 實際全月份 OI 由 110k 降到 85k。
        by_day = {
            '2026-10-14': [_row('202610', 120000, 80000, 23000), _row('202611', 30000, 30000, 23050)],
            '2026-10-15': [_row('202610', 60000, 40000, 23100), _row('202611', 110000, 45000, 23188)],
        }
        self.assertIsNone(px.compute_tx_oi(by_day))

    def test_same_main_contract_keeps_daily_change(self):
        by_day = {
            '2026-10-21': [_row('202611', 110000, 45000, 23188), _row('202610', 60000, 40000, 23100)],
            '2026-10-22': [_row('202611', 120000, 49500, 23300), _row('202612', 9000, 6000, 23350)],
        }
        out = px.compute_tx_oi(by_day)
        self.assertEqual(out['contract'], '202611')
        self.assertEqual(out['prevDate'], '2026-10-21')
        self.assertAlmostEqual(out['oiChgPct'], 10.0)

    def test_existing_roll_without_prior_contract_still_none(self):
        by_day = {
            '2026-07-31': [_row('202608', 90, 100000, 23000)],
            '2026-08-01': [_row('202609', 100, 80000, 23100)],
        }
        self.assertIsNone(px.compute_tx_oi(by_day))


if __name__ == '__main__':
    unittest.main()
