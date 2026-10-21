# -*- coding: utf-8 -*-
"""警報盤中條件（漲跌幅、預估量比）、只提醒一次，以及既有價位規則行為不變。無網路。"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import alert_daemon  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))


def taipei_ms(hour, minute, day=15):
    return datetime(2026, 1, day, hour, minute, tzinfo=TAIPEI).timestamp() * 1000


class AlertConditionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent = []
        self.quote = {'ok': True, 'price': 101.0, 'prevClose': 100.0, 'timestampMs': taipei_ms(10, 0),
                      'volumeShares': 3_000_000}
        self.mis_calls = []
        self.now = [1_000_000.0]

        def tw_quote(code):
            self.mis_calls.append(code)
            return dict(self.quote)

        def deliver(cfg, text, subject='Stock Terminal 警報', *, source='alert', now=None):
            self.sent.append((source, text))
            return {'status': 'sent', 'id': str(len(self.sent))}

        for p in (patch.object(alert_daemon, 'RULES_FILE', os.path.join(self.tmp.name, 'alert_rules.json')),
                  patch.object(alert_daemon, 'load_config', return_value={'enabled': True}),
                  patch.object(alert_daemon, 'deliver', side_effect=deliver),
                  patch.object(alert_daemon, '_log'),
                  patch.object(alert_daemon.time, 'time', side_effect=lambda: self.now[0]),
                  patch.object(alert_daemon, '_TW_QUOTE', tw_quote)):
            p.start()
            self.addCleanup(p.stop)

    def save(self, rules):
        alert_daemon.save_rules(rules)

    def rules(self):
        with open(alert_daemon.RULES_FILE, encoding='utf-8') as fh:
            return json.load(fh)

    def tick(self, seconds=60, **quote):
        self.now[0] += seconds
        self.quote.update(quote)
        alert_daemon._check_once()

    # ---- 漲跌幅 -------------------------------------------------------
    def test_pct_up_initializes_then_fires_on_each_new_crossing_with_cooldown(self):
        self.save([{'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'pct_up', 'threshold': 3, 'enabled': True}])
        self.tick(price=101.0)                       # 首次觀察只初始化
        self.assertEqual(self.sent, [])
        self.tick(price=103.5)                       # 不成立 → 成立：觸發
        self.assertEqual(len(self.sent), 1)
        self.assertIn('漲幅達 3%', self.sent[0][1])
        self.assertIn('+3.50%', self.sent[0][1])
        self.tick(price=104.0)                       # 持續成立不重複
        self.tick(price=101.0)                       # 回落：重新武裝
        self.tick(seconds=30, price=103.2)           # 再次成立但距上次不到 5 分鐘：冷卻
        self.assertEqual(len(self.sent), 1)
        self.tick(seconds=30, price=101.0)
        self.tick(seconds=400, price=103.2)          # 冷卻後再次成立：觸發
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.mis_calls[0], '2330', '台股走注入的官方報價')

    def test_pct_down_compares_against_negative_threshold(self):
        self.save([{'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'pct_down', 'threshold': 2, 'enabled': True}])
        self.tick(price=99.0)
        self.tick(price=98.5)                        # -1.5%：未達
        self.assertEqual(self.sent, [])
        self.tick(price=97.9)                        # -2.1%：觸發
        self.assertEqual(len(self.sent), 1)
        self.assertIn('跌幅達 2%', self.sent[0][1])

    # ---- 預估量比 -----------------------------------------------------
    def test_volume_ratio_linear_projection_after_warmup(self):
        bars = [{'date': '2026-01-13', 'volume': 9_000_000}, {'date': '2026-01-14', 'volume': 4_500_000},
                {'date': '2026-01-15', 'volume': 999}]  # 當日未完成日線不得當成昨量
        self.save([{'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'volume_ratio', 'threshold': 2, 'enabled': True}])
        with patch.object(alert_daemon, '_fetch_daily_candles', return_value=bars):
            self.tick(timestampMs=taipei_ms(9, 30), volumeShares=1_000_000)   # 30 分：1e6/(30/270)/4.5e6 = 2.0 → 成立，但首次只初始化
            self.tick(timestampMs=taipei_ms(9, 45), volumeShares=1_000_000)   # 45 分：1.33 倍 → 不成立
            self.assertEqual(self.sent, [])
            self.tick(timestampMs=taipei_ms(10, 0), volumeShares=3_000_000)   # 60 分：3e6/(60/270)/4.5e6 = 3.0 → 觸發
        self.assertEqual(len(self.sent), 1)
        text = self.sent[0][1]
        self.assertIn('3.0 倍昨量', text)
        self.assertIn('線性估算', text)
        self.assertIn('昨量 4,500,000 股', text)

    def test_volume_ratio_skips_warmup_and_missing_previous_volume(self):
        self.save([{'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'volume_ratio', 'threshold': 2, 'enabled': True}])
        with patch.object(alert_daemon, '_fetch_daily_candles', return_value=[{'date': '2026-01-14', 'volume': 1}]):
            self.tick(timestampMs=taipei_ms(9, 10), volumeShares=5_000_000)  # 開盤 10 分鐘：不判斷
        self.assertNotIn('_last_cond', self.rules()[0])
        with patch.object(alert_daemon, '_fetch_daily_candles', return_value=[]), \
                patch('log_once.log_once') as logged:
            self.tick(timestampMs=taipei_ms(11, 0), volumeShares=9_000_000)
        self.assertEqual(self.sent, [])
        self.assertNotIn('_last_cond', self.rules()[0])
        self.assertTrue(any('昨' in str(c) for c in logged.call_args_list), '缺昨量要留紀錄')

    def test_metric_value_after_close_uses_full_session(self):
        quote = {'price': 1, 'prevClose': 1, 'sessionStart': 0, 'sessionEnd': 270 * 60,
                 'time': 400 * 60, 'volumeShares': 900}
        value, _ = alert_daemon.metric_value({'type': 'volume_ratio'}, quote, prev_volume=300)
        self.assertAlmostEqual(value, 3.0)

    # ---- 報價來源 -----------------------------------------------------
    def test_tw_falls_back_to_yahoo_only_without_official_trade(self):
        meta = {'regularMarketPrice': 50.0, 'chartPreviousClose': 48.0, 'regularMarketTime': taipei_ms(10, 0) / 1000,
                'regularMarketVolume': 100, 'currentTradingPeriod': {'regular': {'start': 1, 'end': 2}}}
        with patch.object(alert_daemon, '_yahoo_chart_meta', return_value=meta) as yahoo:
            official = alert_daemon.intraday_quote('2330', 'TW')
            yahoo.assert_not_called()
            self.assertEqual(official['source'], 'twse-mis')
            self.quote.update(ok=False)
            fallback = alert_daemon.intraday_quote('2330', 'TW')
            yahoo.assert_called_once()
        self.assertEqual(fallback['source'], 'yahoo-v8-chart')
        self.assertAlmostEqual(fallback['prevClose'], 48.0)

    # ---- 只提醒一次 ---------------------------------------------------
    def test_once_stops_after_first_alert_for_metric_and_cross_rules(self):
        self.save([
            {'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'pct_up', 'threshold': 1, 'enabled': True, 'once': True},
            {'id': 2, 'sym': 'AAPL', 'market': 'US', 'type': 'cross_up', 'price': 200, 'enabled': True, 'once': True},
        ])
        prices = iter([190.0, 205.0, 190.0, 205.0, 190.0, 205.0])
        with patch.object(alert_daemon, 'fetch_price', side_effect=lambda sym, mkt: next(prices)):
            self.tick(price=100.0)
            self.tick(price=102.0)                   # 兩條規則各觸發一次
            self.assertEqual(len(self.sent), 2)
            for _ in range(2):
                self.tick(seconds=400, price=100.0)  # 回落
                self.tick(seconds=400, price=102.0)  # 再次成立：已提醒過，不再觸發
        self.assertEqual(len(self.sent), 2)
        self.assertTrue(all(rule.get('_last_once_done') for rule in self.rules()))
        self.assertTrue(all(rule.get('enabled') for rule in self.rules()), '不改使用者的啟用設定')

    # ---- 規則驗證與既有行為 ---------------------------------------------
    def test_save_rules_validates_new_thresholds_and_keeps_legacy_rules(self):
        legacy = {'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'cross_up', 'price': 600, 'enabled': True}
        self.save([legacy])
        for bad in ({'type': 'pct_up'}, {'type': 'pct_down', 'threshold': 0}, {'type': 'volume_ratio', 'threshold': 50},
                    {'type': 'pct_up', 'threshold': 'abc'}):
            with self.assertRaises(ValueError):
                self.save([legacy, {'id': 2, 'sym': '2330', 'market': 'TW', 'enabled': True, **bad}])
        self.assertEqual(self.rules(), [legacy], '驗證失敗不得寫入')
        self.save([legacy, {'id': 2, 'sym': '2330', 'market': 'TW', 'type': 'volume_ratio', 'threshold': 2.5, 'enabled': True}])
        self.assertEqual(len(self.rules()), 2)

    def test_existing_cross_rule_behaviour_unchanged(self):
        self.save([{'id': 1, 'sym': '2330', 'market': 'TW', 'type': 'cross_up', 'price': 100, 'enabled': True}])
        prices = iter([95.0, 101.0, 99.5, 101.0, 98.0, 101.0])
        with patch.object(alert_daemon, 'fetch_price', side_effect=lambda sym, mkt: next(prices)):
            self.tick()                              # 初始化（below）
            self.tick()                              # 突破：觸發
            self.tick(seconds=400)                   # 99.5：未跌破 1% 緩衝，不重設
            self.tick(seconds=400)                   # 101：不重複
            self.assertEqual(len(self.sent), 1)
            self.tick(seconds=400)                   # 98：跌破 1% 緩衝，重設
            self.tick(seconds=400)                   # 101：再次突破
        self.assertEqual(len(self.sent), 2)
        self.assertTrue(all(source == 'price' for source, _ in self.sent))
        self.assertEqual(self.mis_calls, [], '價位規則仍走原本的 fetch_price')

    def test_fetch_price_keeps_extended_hours_selection(self):
        with patch.object(alert_daemon, '_yahoo_chart_meta', return_value={
                'marketState': 'POST', 'postMarketPrice': 210.5, 'regularMarketPrice': 200.0}):
            self.assertEqual(alert_daemon.fetch_price('AAPL', 'US'), 210.5)
        with patch.object(alert_daemon, '_yahoo_chart_meta', return_value={
                'marketState': 'PRE', 'preMarketPrice': 198.0, 'regularMarketPrice': 200.0}):
            self.assertEqual(alert_daemon.fetch_price('AAPL', 'US'), 198.0)
        with patch.object(alert_daemon, '_yahoo_chart_meta', return_value=None):
            self.assertIsNone(alert_daemon.fetch_price('AAPL', 'US'))

    def test_yahoo_meta_logs_after_both_hosts_fail(self):
        with patch('urllib.request.urlopen', side_effect=ConnectionResetError('reset')) as opened, \
                patch('log_once.log_once') as logged:
            self.assertIsNone(alert_daemon._yahoo_chart_meta('AAPL'))
        self.assertEqual(opened.call_count, 2)
        logged.assert_called_once()


if __name__ == '__main__':
    unittest.main()
