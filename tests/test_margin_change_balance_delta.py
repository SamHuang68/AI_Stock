"""審查 CM-04：個股融資／融券增減＝今日餘額−前日餘額；盤後融資異常門檻為 500 張。不連網。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))

import chip_api as ca  # noqa: E402
import postmarket_report as pr  # noqa: E402

FIELDS = ['代號', '名稱',
          '買進', '賣出', '現金償還', '前日餘額', '今日餘額', '次一營業日限額',
          '買進', '賣出', '現券償還', '前日餘額', '今日餘額', '次一營業日限額',
          '資券互抵', '註記']
# TWSE MI_MARGN 2026-10-16 實際兩列（唯讀公開資料）
ROWS = [
    ['1101', '台泥', '3,523', '2,588', '3', '39,166', '40,098', '1,880,795', '5', '68', '0', '196', '259', '1,880,795', '13', ' '],
    ['2330', '台積電', '1,157', '1,160', '110', '34,223', '34,110', '6,483,092', '3', '4', '0', '8', '9', '6,483,092', '2', ' '],
]


class MarginChangeTest(unittest.TestCase):
    def setUp(self):
        payload = {'stat': 'OK', 'tables': [{'title': '融資融券彙總 (全部)', 'fields': FIELDS, 'data': ROWS}]}
        patcher = mock.patch.object(ca, '_fetch_json', return_value=payload)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ca._SNAP.clear)
        ca._SNAP.clear()
        self.by = ca.snap_margn('20261016')

    def test_margin_change_includes_cash_repayment(self):
        # 2330：買進−賣出只有 −3 張，含現金償還 110 張後實際 −113 張
        self.assertEqual(self.by['2330']['marginChange'], -113 * 1000.0)
        self.assertEqual(self.by['1101']['marginChange'], 932 * 1000.0)

    def test_short_change_sign_follows_balance(self):
        # 1101：融券賣出 68、回補 5，餘額 196→259 增加 63 張；舊版算成 −63
        self.assertEqual(self.by['1101']['shortChange'], 63 * 1000.0)
        self.assertEqual(self.by['2330']['shortChange'], 1 * 1000.0)

    def test_missing_prior_balance_gives_unknown_change(self):
        row = list(ROWS[0])
        row[5] = row[11] = ''          # 前日餘額缺值：不可再退回「買進−賣出」或補 0
        payload = {'stat': 'OK', 'tables': [{'title': '融資融券彙總 (全部)', 'fields': FIELDS, 'data': [row]}]}
        ca._SNAP.clear()
        with mock.patch.object(ca, '_fetch_json', return_value=payload):
            by = ca.snap_margn('20261015')
        self.assertIsNone(by['1101']['marginChange'])
        self.assertIsNone(by['1101']['shortChange'])
        self.assertEqual(by['1101']['marginBalance'], 40098 * 1000.0)


class MarginAnomalyThresholdTest(unittest.TestCase):
    def ids(self, change):
        return {a['id']: a for a in pr.detect_anomalies({}, {}, {'margin': {'marginChange': change}})}

    def test_threshold_is_500_lots(self):
        self.assertEqual(self.ids(-113_000.0), {})          # 113 張：舊門檻（500 股）會標異常
        self.assertEqual(self.ids(499_000.0), {})
        hit = self.ids(500_000.0)['margin_expanding']
        self.assertEqual(hit['label'], '融資餘額增加 500 張')
        low = self.ids(-650_000.0)['margin_contracting']
        self.assertEqual(low['label'], '融資餘額減少 650 張')


if __name__ == '__main__':
    unittest.main()
