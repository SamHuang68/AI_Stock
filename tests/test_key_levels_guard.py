"""關鍵價位是「某個已完成交易日」的靜態價位：參考日必須是最近完成的交易日，現價偏離太多時不再產生決策條件。

起因：決策中心顯示的 R2/R1/PIVOT/S1/S2 = 48,328/48,177/47,966/47,814/47,603（反推：參考日高 48,118、低 47,755、收 48,025），
而台指期夜盤已 5 萬點。舊規則只在參考日超過 7 個日曆日才標過期，而且完全不看現價。
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'tests')]
import decision_context as dc  # noqa: E402
import key_levels  # noqa: E402
from test_decision_context import pulse  # noqa: E402

TW = timezone(timedelta(hours=8))
PROFILE = {'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
           'maxSingleNameWeight': 100, 'maxSectorWeight': 100, 'maxPortfolioBeta': 10,
           'maxDailyVaR': 0.1, 'investmentHorizon': 'swing'}
# 使用者貼的那一組價位對應的參考日 K 棒
REF_BAR = {'high': 48118.0, 'low': 47755.0, 'close': 48025.0}


def bars(last_date: str, n: int = 40):
    """以 last_date 結尾的 n 根日 K；最後一根是 REF_BAR。"""
    end = datetime.fromisoformat(last_date).date()
    rows = []
    for i in range(n):
        day = end - timedelta(days=n - 1 - i)
        drift = (n - 1 - i) * 25.0
        rows.append({'date': day.isoformat(), 'open': 47900.0 - drift, 'high': 48118.0 - drift,
                     'low': 47755.0 - drift, 'close': 48025.0 - drift, 'volume': 1000})
    return rows


def levels_for(last_date: str):
    return key_levels.calculate_key_levels(bars(last_date), today=datetime.fromisoformat(last_date).date())


def context(now: datetime, ref_date: str, *, twii_price=48025.0, twii_asof=None, txf_price=None, txf_asof=None,
            calendar=None):
    p = pulse(updated=now.isoformat())
    p['date'] = now.date().isoformat()
    q = p['marketSnapshot']['quotes']
    q['^TWII']['price'] = twii_price
    twii_at = (twii_asof or datetime(now.year, now.month, now.day, 13, 33, tzinfo=TW)).isoformat()
    q['^TWII']['asOf'] = q['^TWII']['market']['asOf'] = twii_at
    if txf_price is None:
        q.pop('__TXF__', None)
    else:
        q['__TXF__']['price'] = txf_price
        q['__TXF__']['market']['asOf'] = q['__TXF__']['asOf'] = (txf_asof or now - timedelta(seconds=30)).isoformat()
    # 約束清單要在設定了 Risk Profile 之後才會計算（沒設定時更早就回傳 risk_profile_not_configured）
    return dc.build_decision_context(p, key_levels=levels_for(ref_date), now=now, session_calendar=calendar,
                                     risk_profile=PROFILE)


class ReproduceTheReportedLevels(unittest.TestCase):
    def test_the_reported_numbers_come_from_that_reference_bar(self):
        out = levels_for('2026-10-05')
        lv = out['levels']
        reported = {'r2': 48328, 'r1': 48177, 'pivot': 47966, 's1': 47814, 's2': 47603}
        # 畫面上的 K 棒價位有小數，這裡以整數還原，所以容許 ±1 的四捨五入差
        for name, value in reported.items():
            self.assertAlmostEqual(lv[name], value, delta=1.0, msg=name)
        self.assertEqual(out['referenceBar']['close'], 48025.0)
        self.assertEqual(out['referenceBar']['date'], '2026-10-05')


class OffReferenceGuard(unittest.TestCase):
    NIGHT = datetime(2026, 10, 5, 20, 30, tzinfo=TW)        # 週一夜盤

    def test_night_futures_at_50000_flag_the_levels_and_remove_the_decision_conditions(self):
        out = context(self.NIGHT, '2026-10-05', txf_price=50000.0)
        quality = out['keyLevels']['quality']
        self.assertTrue(quality['offReference'])
        self.assertFalse(quality['levelsActionable'])
        self.assertFalse(quality['stale'])                    # 參考日正確（就是今天收盤），所以不是「過期」
        self.assertEqual(quality['liveReference']['symbol'], '__TXF__')
        self.assertAlmostEqual(quality['liveDeviationPct'], 4.1, places=1)
        self.assertGreaterEqual(quality['liveDeviationPct'], quality['deviationThresholdPct'])
        joined = ' '.join(out['confirmation'] + out['invalidation'])
        self.assertNotIn('R1', joined)
        self.assertNotIn('S1', joined)
        self.assertIn('key_levels_off_reference', out['actionEnvelope']['constraints'])
        self.assertNotIn('key_levels_stale', out['actionEnvelope']['constraints'])
        # 價位本身仍保留供閱讀，波動度統計不受影響（它們與現價無關）
        self.assertEqual(round(out['keyLevels']['levels']['r1']), 48177)
        self.assertIsNotNone(out['keyLevels']['volatility']['realized20AnnualPct'])

    def test_price_near_the_reference_close_keeps_the_conditions(self):
        out = context(self.NIGHT, '2026-10-05', txf_price=48200.0)
        quality = out['keyLevels']['quality']
        self.assertFalse(quality['offReference'])
        self.assertTrue(quality['levelsActionable'])
        joined = ' '.join(out['confirmation'] + out['invalidation'])
        self.assertIn('R1', joined)
        self.assertIn('S1', joined)
        self.assertNotIn('key_levels_off_reference', out['actionEnvelope']['constraints'])

    def test_a_drop_is_flagged_as_well_as_a_rally(self):
        out = context(self.NIGHT, '2026-10-05', txf_price=46900.0)
        self.assertTrue(out['keyLevels']['quality']['offReference'])
        self.assertLess(out['keyLevels']['quality']['liveDeviationPct'], -2.0)

    def test_the_threshold_scales_with_volatility(self):
        # ATR% 很大時門檻放寬：同樣 +2.5% 在 1.5% ATR 的市場（門檻 3%）不算偏離
        levels = levels_for('2026-10-05')
        levels['atr']['pct'] = 1.5
        q = {'status': 'observed', 'asOf': self.NIGHT.isoformat()}
        guarded = dc._guard_key_levels(levels, {'price': 48025.0}, {'price': 48025.0 * 1.025},
                                       {'twii': {'status': 'unknown'}, 'txf': q}, self.NIGHT)
        self.assertEqual(guarded['quality']['deviationThresholdPct'], 3.0)
        self.assertFalse(guarded['quality']['offReference'])
        guarded = dc._guard_key_levels(levels, {'price': 48025.0}, {'price': 48025.0 * 1.035},
                                       {'twii': {'status': 'unknown'}, 'txf': q}, self.NIGHT)
        self.assertTrue(guarded['quality']['offReference'])

    def test_the_fresher_of_futures_and_index_is_used_and_unusable_quotes_are_ignored(self):
        levels = levels_for('2026-10-05')
        sq = {'twii': {'status': 'completed_session', 'asOf': '2026-10-05T13:33:00+08:00'},
              'txf': {'status': 'stale', 'asOf': '2026-10-05T20:29:30+08:00'}}
        guarded = dc._guard_key_levels(levels, {'price': 48025.0}, {'price': 50000.0}, sq, self.NIGHT)
        self.assertEqual(guarded['quality']['liveReference']['symbol'], '^TWII')       # 過期的期貨不採用
        self.assertFalse(guarded['quality']['offReference'])
        sq['txf']['status'] = 'unknown'
        self.assertEqual(dc._guard_key_levels(levels, {'price': 48025.0}, {'price': 50000.0}, sq,
                                              self.NIGHT)['quality']['liveReference']['symbol'], '^TWII')


class ReferenceMustBeTheLatestCompletedSession(unittest.TestCase):
    def test_a_reference_older_than_the_latest_completed_session_is_stale_even_within_7_days(self):
        now = datetime(2026, 10, 5, 19, 0, tzinfo=TW)                        # 週一 19:00，應該已有當日日 K
        out = context(now, '2026-10-02')                                       # 但只到上週五（3 個日曆日前）
        quality = out['keyLevels']['quality']
        self.assertTrue(quality['stale'])
        self.assertEqual(quality['reason'], 'reference_not_latest_completed_session')
        self.assertEqual(quality['expectedReferenceDate'], '2026-10-05')
        self.assertIn('key_levels_stale', out['actionEnvelope']['constraints'])
        joined = ' '.join(out['confirmation'] + out['invalidation'])
        self.assertNotIn('R1', joined)
        # 舊規則在這裡不會標過期（只有 > 7 個日曆日才過期）
        self.assertFalse(key_levels.calculate_key_levels(bars('2026-10-02'), today=datetime(2026, 10, 5).date())['quality']['stale'])

    def test_before_18_the_previous_trading_day_is_expected(self):
        now = datetime(2026, 10, 6, 10, 0, tzinfo=TW)                         # 週二日盤中
        ok = context(now, '2026-10-05')
        self.assertFalse(ok['keyLevels']['quality']['stale'])
        self.assertEqual(ok['keyLevels']['quality']['expectedReferenceDate'], '2026-10-05')
        old = context(now, '2026-10-02')                                       # 少了週一
        self.assertTrue(old['keyLevels']['quality']['stale'])

    def test_weekend_expects_friday(self):
        now = datetime(2026, 10, 10, 12, 0, tzinfo=TW)                         # 週六
        self.assertFalse(context(now, '2026-10-09')['keyLevels']['quality']['stale'])
        self.assertTrue(context(now, '2026-10-08')['keyLevels']['quality']['stale'])

    def test_exchange_calendar_holiday_is_respected(self):
        calendar = {'coveredYears': [2026], 'sessions': ['2026-10-08', '2026-10-09', '2026-10-13']}   # 10-12 休市
        now = datetime(2026, 10, 12, 19, 0, tzinfo=TW)
        self.assertFalse(context(now, '2026-10-09', calendar=calendar)['keyLevels']['quality']['stale'])


class LegacyAndMissingInputs(unittest.TestCase):
    def test_key_levels_without_reference_fields_are_unchanged(self):
        legacy = {'symbol': '^TWII', 'levels': {'r1': 23150, 's1': 22800}, 'atr': {'pct': 1.5},
                  'volatility': {}, 'quality': {'complete': True, 'stale': False}}
        guarded = dc._guard_key_levels(copy.deepcopy(legacy), {'price': 99999.0}, {}, {}, datetime(2026, 8, 11, 9, 0, tzinfo=TW))
        self.assertFalse(guarded['quality']['stale'])
        self.assertTrue(guarded['quality']['levelsActionable'])
        self.assertNotIn('offReference', guarded['quality'])

    def test_no_usable_live_quote_means_no_deviation_verdict(self):
        levels = levels_for('2026-10-05')
        guarded = dc._guard_key_levels(levels, {'price': 50000.0}, {'price': 50000.0},
                                       {'twii': {'status': 'stale', 'asOf': 'x'}, 'txf': {'status': 'unknown', 'asOf': None}},
                                       datetime(2026, 10, 5, 20, 30, tzinfo=TW))
        self.assertNotIn('liveDeviationPct', guarded['quality'])
        self.assertTrue(guarded['quality']['levelsActionable'])

    def test_the_input_is_not_mutated(self):
        levels = levels_for('2026-10-05')
        before = copy.deepcopy(levels)
        dc._guard_key_levels(levels, {'price': 50000.0}, {}, {'twii': {'status': 'observed', 'asOf': 'a'}},
                             datetime(2026, 10, 5, 20, 30, tzinfo=TW))
        self.assertEqual(levels, before)


if __name__ == '__main__':
    unittest.main()
