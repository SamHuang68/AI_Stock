"""審查 IND-01：WATCH「突破 N 日新高」的量能用當日量／前 20 日均量，與個股訊號「帶量突破」同口徑。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import indicators  # noqa: E402
import stock_signals  # noqa: E402
import watch_daemon  # noqa: E402


def _bars(last_volume):
    bars = [{'date': f'2026-09-{i + 1:02d}', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0, 'volume': 1000.0}
            for i in range(25)]
    bars.append({'date': '2026-09-26', 'open': 101.0, 'high': 106.0, 'low': 100.5, 'close': 105.0, 'volume': last_volume})
    return bars


class WatchBreakoutDayVolumeTest(unittest.TestCase):
    def test_single_day_triple_volume_breakout_triggers(self):
        bars = _bars(3000.0)
        ind = indicators.candle_snapshot(bars)
        self.assertAlmostEqual(ind['volVs20d'], 3.0)
        self.assertAlmostEqual(ind['volRatio'], (3000 + 4 * 1000) / 5 / ((3000 + 19 * 1000) / 20))  # 5 日／20 日口徑不變
        self.assertLess(ind['volRatio'], 1.5)
        self.assertAlmostEqual(stock_signals.build_frame(bars)['volx'][-1], ind['volVs20d'])
        state, detail = watch_daemon._eval('breakout_n_high', ind, {'days': 20, 'volMult': 1.5})
        self.assertEqual(state, 'trigger', detail)

    def test_breakout_on_normal_volume_is_partial(self):
        ind = indicators.candle_snapshot(_bars(1200.0))
        self.assertEqual(watch_daemon._eval('breakout_n_high', ind, {'days': 20, 'volMult': 1.5})[0], 'partial')

    def test_short_history_has_no_day_volume_ratio(self):
        self.assertIsNone(indicators.candle_snapshot(_bars(3000.0)[-20:])['volVs20d'])
        self.assertIsNone(indicators.candle_snapshot([])['volVs20d'])


if __name__ == '__main__':
    unittest.main()
