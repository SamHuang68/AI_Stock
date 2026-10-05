"""台指期時效：夜盤收盤（05:00）與日盤收盤（13:45）之後、下一場次開始之前，是「已完成場次」。

過去只有「30 分鐘內」一條規則，所以 05:30～08:45 決策中心完全不採用夜盤收盤，
而那正是開盤前最重要的期貨訊號。這裡用整條時間軸驗證，包含不該被誤判為新鮮的情況。
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import decision_context as dc  # noqa: E402

TW = timezone(timedelta(hours=8))
TWII = {'price': 49000.0, 'asOf': None}


def at(day, hh, mm, ss=0):
    return datetime(2026, 10, day, hh, mm, ss, tzinfo=TW)


def txf_quote(asof, *, session='night', stale=False):
    market = {'asOf': asof.isoformat() if asof else None, 'session': session}
    if stale:
        market['stale'] = True
    return {'price': 50000.0, 'asOf': market['asOf'], 'market': market}


def txf_status(now, last_tick, calendar=None, **kw):
    out = dc._source_quality({}, TWII, txf_quote(last_tick, **kw), now, calendar)['txf']
    return out['status'], out['freshness']


# 2026-10-05 週一、10-06 週二、10-09 週五、10-10 週六、10-11 週日、10-12 週一
class TxfSessionTimeline(unittest.TestCase):
    def test_night_session_close_stays_usable_until_the_day_session_opens(self):
        last = at(6, 4, 59, 50)                                  # 週二 05:00 收盤前最後一筆
        for hh, mm in ((5, 0), (5, 10), (5, 40), (7, 30), (8, 44)):
            with self.subTest(now=f'{hh:02d}:{mm:02d}'):
                self.assertEqual(txf_status(at(6, hh, mm), last), ('completed_session', 1.0))

    def test_day_session_open_retires_the_previous_nights_quote(self):
        last = at(6, 4, 59, 50)
        status, freshness = txf_status(at(6, 8, 46), last)       # 08:45 日盤開始，夜盤收盤不再是最新
        self.assertEqual(status, 'stale')
        self.assertLess(freshness, 0.25)

    def test_day_session_close_is_usable_until_the_night_session_opens(self):
        last = at(6, 13, 44, 58)
        for hh, mm in ((13, 46), (14, 20), (14, 59)):
            with self.subTest(now=f'{hh:02d}:{mm:02d}'):
                self.assertEqual(txf_status(at(6, hh, mm), last, session='day')[0], 'completed_session')
        self.assertEqual(txf_status(at(6, 15, 1), last, session='day')[0], 'stale')

    def test_live_session_rules_are_unchanged(self):
        self.assertEqual(txf_status(at(5, 20, 0, 30), at(5, 20, 0)), ('observed', 1.0))             # 夜盤進行中
        self.assertEqual(txf_status(at(6, 0, 27), at(6, 0, 26, 40)), ('observed', 1.0))             # 跨午夜
        self.assertEqual(txf_status(at(6, 10, 0, 30), at(6, 10, 0), session='day'), ('observed', 1.0))
        status, freshness = txf_status(at(5, 20, 40), at(5, 20, 0))                                  # 夜盤中卻 40 分鐘沒報價
        self.assertEqual(status, 'stale')
        self.assertLess(freshness, 0.25)

    def test_weekend_keeps_fridays_night_close_until_monday_open(self):
        last = at(10, 4, 59, 55)                                  # 週六 05:00（週五夜盤）
        for now in (at(10, 6, 0), at(10, 18, 0), at(11, 12, 0), at(12, 8, 44)):
            with self.subTest(now=now.isoformat()):
                self.assertEqual(txf_status(now, last)[0], 'completed_session')
        self.assertEqual(txf_status(at(12, 8, 46), last)[0], 'stale')

    def test_a_quote_that_is_not_the_last_of_its_session_is_not_rescued(self):
        # 夜盤 02:00 的報價，到 07:00 已是 5 小時前，且不在收盤前 30 分鐘內 → 過期
        status, freshness = txf_status(at(6, 7, 0), at(6, 2, 0))
        self.assertEqual(status, 'stale')
        self.assertLess(freshness, 0.25)

    def test_a_quote_from_an_earlier_session_is_not_accepted_as_the_latest(self):
        # 週二 06:00，手上是「週一日盤收盤」13:45，而最近結束的場次是週二 05:00 的夜盤 → 過期
        self.assertEqual(txf_status(at(6, 6, 0), at(5, 13, 44, 58), session='day')[0], 'stale')

    def test_unknown_time_and_explicit_stale_flag_never_become_completed(self):
        self.assertEqual(txf_status(at(6, 6, 0), None)[0], 'unknown')
        self.assertEqual(txf_status(at(6, 6, 0), at(6, 4, 59, 50), stale=True)[0], 'stale')
        self.assertEqual(txf_status(at(6, 6, 0), at(6, 7, 0))[0], 'future')

    def test_exchange_calendar_holiday_moves_the_next_open(self):
        # 週一 10-12 休市（有載入交易所日曆）→ 週五夜盤收盤（週六 05:00）可用到週二 08:45
        calendar = {'coveredYears': [2026], 'sessions': ['2026-10-08', '2026-10-09', '2026-10-13']}
        last = at(10, 4, 59, 55)
        self.assertEqual(txf_status(at(12, 9, 30), last, calendar)[0], 'completed_session')
        self.assertEqual(txf_status(at(13, 8, 44), last, calendar)[0], 'completed_session')
        self.assertEqual(txf_status(at(13, 8, 46), last, calendar)[0], 'stale')

    def test_the_index_rules_are_untouched(self):
        # 加權指數仍以自己的 completed_session 規則判定（本變更只動台指期）
        twii = {'price': 49000.0, 'asOf': at(5, 13, 33).isoformat(), 'market': {'asOf': at(5, 13, 33).isoformat(), 'session': 'regular'}}
        out = dc._source_quality({}, twii, txf_quote(None), at(5, 19, 0), None)
        self.assertEqual(out['twii']['status'], 'completed_session')
        self.assertEqual(out['txf']['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
