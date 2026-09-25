# -*- coding: utf-8 -*-
"""P0：推播 daemon 與畫面指標同口徑（Wilder RSI），RSI 反彈須為「跨越事件」。"""
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import alert_daemon  # noqa: E402
import indicators as ind  # noqa: E402
import watch_daemon  # noqa: E402


def _candles(closes):
    return [{'close': c, 'high': c * 1.01, 'low': c * 0.99, 'volume': 1000 + i}
            for i, c in enumerate(closes)]


def _random_walk(seed, n=260):
    rnd = random.Random(seed)
    px = [100.0]
    for _ in range(n - 1):
        px.append(px[-1] * (1 + rnd.gauss(0.0004, 0.018)))
    return px


class DaemonRsiParityTests(unittest.TestCase):
    def test_alert_daemon_rsi_is_wilder(self):
        for seed in (1, 7, 42):
            closes = _random_walk(seed)
            for k in (40, 120, 260):
                got = alert_daemon._calc_ind(_candles(closes[:k]))['rsi14']
                self.assertAlmostEqual(got, ind.rsi_wilders(closes[:k], 14), places=12)

    def test_watch_daemon_rsi_is_wilder(self):
        closes = _random_walk(3)
        for k in (30, 90, 200):
            got = watch_daemon._ind(_candles(closes[:k]))['rsi14']
            self.assertAlmostEqual(got, ind.rsi_wilders(closes[:k], 14), places=12)

    def test_alert_daemon_keeps_contract_keys(self):
        snap = alert_daemon._calc_ind(_candles(_random_walk(5, 80)))
        self.assertEqual(set(snap), {'close', 'sma20', 'sma60', 'rsi14', 'bbL', 'bbU',
                                     'volRatio', 'high20'})
        self.assertLess(snap['bbL'], snap['sma20'])
        self.assertGreater(snap['bbU'], snap['sma20'])

    def test_short_history_does_not_crash_rules(self):
        snap = watch_daemon._ind(_candles([100.0 + i for i in range(10)]))
        self.assertIsNone(snap['rsi14'])
        self.assertEqual(watch_daemon._eval('rsi_oversold_bounce', snap, {})[0], 'none')
        self.assertEqual(watch_daemon._eval('rsi_overheat', snap, {})[0], 'none')


class RsiBounceCrossingTests(unittest.TestCase):
    def test_level_without_prior_oversold_is_not_a_bounce(self):
        # RSI 從高檔一路往下到 30~38：不是「超賣反彈」
        status, detail = watch_daemon._rsi_bounce_state(35.0, 41.0)
        self.assertEqual(status, 'wait')
        self.assertIn('未曾跌破 30', detail)

    def test_cross_back_above_30_triggers(self):
        status, _ = watch_daemon._rsi_bounce_state(32.5, 27.0)
        self.assertEqual(status, 'trigger')

    def test_still_oversold_waits(self):
        self.assertEqual(watch_daemon._rsi_bounce_state(24.0, 20.0)[0], 'wait')

    def test_left_zone_expires(self):
        self.assertEqual(watch_daemon._rsi_bounce_state(44.0, 28.0)[0], 'expired')

    def test_end_to_end_on_price_path(self):
        # 震盪 40 根後連跌 5 根（RSI < 30），隔日 +2%：RSI 回升站上 30 → 觸發
        closes = [100.0]
        for i in range(40):
            closes.append(closes[-1] * (1.012 if i % 2 == 0 else 0.99))
        for _ in range(5):
            closes.append(closes[-1] * 0.975)
        still_low = watch_daemon._ind(_candles(closes + [closes[-1] * 1.01]))
        self.assertLess(still_low['rsi14'], 30)
        self.assertEqual(watch_daemon._eval('rsi_oversold_bounce', still_low, {})[0], 'wait')
        snap = watch_daemon._ind(_candles(closes + [closes[-1] * 1.02]))
        self.assertLess(snap['rsiPrevMin5'], 30)
        self.assertTrue(30 <= snap['rsi14'] <= 38)
        self.assertEqual(watch_daemon._eval('rsi_oversold_bounce', snap, {})[0], 'trigger')


class SharedIndicatorTests(unittest.TestCase):
    def test_ema_seed_is_sma(self):
        vals = [float(v) for v in range(1, 21)]
        ema = ind.ema_series(vals, 5)
        self.assertIsNone(ema[3])
        self.assertAlmostEqual(ema[4], 3.0, places=12)
        self.assertAlmostEqual(ema[5], (2 / 6) * 6 + (4 / 6) * 3.0, places=12)

    def test_macd_lines_align(self):
        closes = _random_walk(11, 120)
        m = ind.macd_series(closes)
        self.assertIsNone(m['macd'][24])
        self.assertIsNotNone(m['macd'][25])
        self.assertIsNone(m['signal'][32])
        self.assertIsNotNone(m['signal'][33])
        self.assertAlmostEqual(m['hist'][-1], m['macd'][-1] - m['signal'][-1], places=12)

    def test_bollinger_uses_population_stdev(self):
        vals = [float(v) for v in range(1, 21)]
        bb = ind.bollinger_series(vals, 20, 2.0)
        mean = sum(vals) / 20
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / 20)
        self.assertAlmostEqual(bb['upper'][-1], mean + 2 * sd, places=12)
        self.assertAlmostEqual(bb['lower'][-1], mean - 2 * sd, places=12)

    def test_atr_wilder_seed_and_smoothing(self):
        highs = [10.0, 11.0, 12.0, 13.0]
        lows = [9.0, 10.0, 10.5, 12.0]
        closes = [9.5, 10.5, 11.5, 12.5]
        atr = ind.atr_wilders_series(highs, lows, closes, 3)
        tr = [1.0, 1.5, 1.5, 1.5]  # 首根 high-low；之後 max(h-l, |h-pc|, |l-pc|)
        self.assertEqual(ind.true_range_series(highs, lows, closes), tr)
        self.assertAlmostEqual(atr[2], (1.0 + 1.5 + 1.5) / 3, places=12)
        self.assertAlmostEqual(atr[3], (atr[2] * 2 + 1.5) / 3, places=12)

    def test_prior_extreme_excludes_current_bar(self):
        self.assertEqual(ind.prior_extreme([1, 5, 3, 9], 3, highest=True), 5.0)
        self.assertEqual(ind.prior_extreme([1, 5, 3, 0], 3, highest=False), 1.0)
        self.assertIsNone(ind.prior_extreme([1, 2], 3))

    def test_sma_series_matches_scalar(self):
        vals = _random_walk(9, 70)
        series = ind.sma_series(vals, 20)
        for i in (19, 40, 69):
            self.assertEqual(series[i], ind.sma(vals, 20, i))


if __name__ == '__main__':
    unittest.main()
