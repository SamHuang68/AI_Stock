# -*- coding: utf-8 -*-
"""週間官方休市日不得被當成交易日：最近收盤日、下一交易日、報價盤中防線與籌碼落後計數共用官方日曆。"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 台股交易參考 as ref  # noqa: E402
import conditional_expectation as ce  # noqa: E402
import market_routes  # noqa: E402
import peak_observation  # noqa: E402
import postmarket_report  # noqa: E402
import touxin_5d  # noqa: E402

TPE = timezone(timedelta(hours=8))


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TPE)


class ClosedDayTests(unittest.TestCase):
    # 2026-10-09（週五）為官方休市日（國慶補假），10-10 為週六。
    def test_official_weekday_holiday_is_closed(self):
        self.assertTrue(ref.is_closed_day('2026-10-09'))
        self.assertFalse(ref.is_closed_day('2026-10-08'))
        self.assertTrue(ref.is_closed_day('2026-10-10'))

    def test_last_close_day_skips_the_weekday_holiday(self):
        self.assertEqual(ref.last_close_day(at(2026, 10, 9, 15)).isoformat(), '2026-10-08')
        self.assertEqual(ref.last_close_day(at(2026, 10, 12, 9)).isoformat(), '2026-10-08')
        self.assertEqual(ref.last_close_day(at(2026, 10, 12, 14)).isoformat(), '2026-10-12')

    def test_every_module_copy_uses_the_calendar(self):
        for module in (ce, touxin_5d, peak_observation):
            with self.subTest(module=module.__name__):
                self.assertEqual(module._last_tw_close_day(at(2026, 10, 9, 15)).isoformat(), '2026-10-08')

    def test_next_session_skips_holiday_and_weekend(self):
        self.assertEqual(ref.next_session_day('2026-10-08').isoformat(), '2026-10-12')
        self.assertEqual(postmarket_report._next_tw_session_date(at(2026, 10, 8, 18)), '2026-10-12')

    def test_quote_guard_keeps_last_trade_on_a_weekday_holiday(self):
        last_trade = int(at(2026, 10, 8, 13, 30).timestamp() * 1000)
        quote = {'ok': True, 'price': 1375.0, 'prevClose': 1360.0, 'timestampMs': last_trade, 'source': 'twse-mis'}
        out = market_routes.guard_tw_quote(quote, now=at(2026, 10, 9, 10))
        self.assertTrue(out['ok'])
        self.assertEqual(out['price'], 1375.0)
        self.assertNotEqual(out.get('quoteStatus'), 'stale')
        # 真正的交易日盤中，跨日的價格仍要被拒絕。
        guarded = market_routes.guard_tw_quote(quote, now=at(2026, 10, 12, 10))
        self.assertFalse(guarded['ok'])
        self.assertIsNone(guarded['price'])

    def test_chip_lag_does_not_count_the_holiday(self):
        # 10-12（週一）早上：最近收盤日是 10-08（10-09 休市）。10-06 的籌碼落後 2 個交易日，未超過門檻。
        # 舊寫法把 10-09 當收盤日，會算成落後 3 日而判逾期。
        out = ce.evaluate_asof_gate(quote=None, chips={'asOf': '2026-10-06'}, now=at(2026, 10, 12, 9))
        self.assertFalse(any('chips asOf' in reason for reason in out['reasons']), out['reasons'])
        stale = ce.evaluate_asof_gate(quote=None, chips={'asOf': '2026-10-02'}, now=at(2026, 10, 12, 9))
        self.assertTrue(any('chips asOf' in reason for reason in stale['reasons']), stale['reasons'])


if __name__ == '__main__':
    unittest.main()
