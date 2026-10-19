"""警報使用既有 DB；無網路、無執行期檔案的來源選擇回歸。"""
import sys
import json
import unittest
from pathlib import Path
from contextlib import nullcontext
from datetime import date, timedelta
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals_routes as routes
import alert_daemon
import watch_daemon


class 警報日線來源(unittest.TestCase):
    def setUp(self):
        self.days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(65)]
        self.bars = [{'date': day, 'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 1000} for day in self.days]
        self.ds = Mock()
        self.conn = Mock()
        self.conn.execute.return_value.fetchall.return_value = []
        self.ds.read_snapshot.side_effect = lambda: nullcontext(self.conn)
        self.ds.get_bars_bulk.return_value = {'2330': self.bars}
        self.ds.source_revision_status.return_value = {'count': 0}
        patches = [patch.object(routes, '_datastore', return_value=self.ds),
                   patch.object(routes, 'session_state', return_value={'expectedLastDate': self.days[-1]}),
                   patch('daily_quality.quality_evidence', return_value={}),
                   patch('台股交易參考.trading_status', return_value=None),
                   patch('台股交易參考.verified_sessions', side_effect=lambda start, end, **kw: [d for d in self.days if start <= d <= end])]
        for context in patches:
            context.start()
            self.addCleanup(context.stop)

    def test_完整本機日線不碰Yahoo空值(self):
        remote = Mock(side_effect=AssertionError('不得連外'))
        out = routes.load_alert_bars('2330', 'TW', remote)
        self.assertEqual(len(out['bars']), 65)
        self.assertEqual(out['source'], 'local-db')
        remote.assert_not_called()

    def test_缺日可選同基準完整備援但不拼接(self):
        self.ds.get_bars_bulk.return_value = {'2330': self.bars[:60] + self.bars[61:]}
        out = routes.load_alert_bars('2330', 'TW', Mock(return_value=self.bars))
        self.assertEqual(out['source'], 'yahoo')
        self.assertEqual(len(out['bars']), 65)

    def test_不同基準不可補缺日(self):
        self.ds.get_bars_bulk.return_value = {'2330': self.bars[:60] + self.bars[61:]}
        remote = [{**bar, 'close': 100} for bar in self.bars]
        out = routes.load_alert_bars('2330', 'TW', Mock(return_value=remote))
        self.assertEqual(out['source'], 'local-db')
        self.assertEqual(len(out['bars']), 64)

    def test_來源修訂與未知拒絕且不退到Yahoo(self):
        for revision in ({'count': 1}, OSError('資料庫無法讀取')):
            self.ds.source_revision_status.side_effect = revision if isinstance(revision, Exception) else None
            self.ds.source_revision_status.return_value = revision
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
            self.assertEqual(out['bars'], [])
            self.assertTrue(out['error'])
            remote.assert_not_called()

    def test_價格衝突遮罩價格但保留日期且不繞過(self):
        with patch('daily_quality.quality_evidence', return_value={self.days[-1]: {'priceConflict': True}}):
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
        self.assertEqual(len(out['bars']), 65)
        self.assertIsNone(out['bars'][-1]['close'])
        self.assertEqual(out['bars'][-1]['volume'], 1000)
        remote.assert_not_called()

    def test_純量衝突保留RSI價格並阻擋量比(self):
        with patch('daily_quality.quality_evidence', return_value={self.days[-1]: {'priceVerified': True, 'volumeConflict': True}}):
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
        self.assertEqual(out['bars'][-1]['close'], 101)
        self.assertIsNone(out['bars'][-1]['volume'])
        snapshot = watch_daemon._ind(out['bars'], 'TW', '2330')
        self.assertIsNotNone(snapshot['rsi14'])
        self.assertIsNone(snapshot['volRatio'])
        remote.assert_not_called()

    def test_來源修訂依欄位與日期遮罩(self):
        for day, index in ((self.days[-1], 5), (self.days[0], 4)):
            old = [0, 100, 102, 99, 101, 1000]
            revised = old.copy()
            revised[index] = 2000 if index == 5 else 100
            self.ds.source_revision_status.return_value = {'count': 1}
            self.conn.execute.return_value.fetchall.return_value = [(day, json.dumps({'original': old, 'revision': revised}))]
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
            snapshot = watch_daemon._ind(out['bars'], 'TW', '2330')
            self.assertEqual(snapshot['close'], 101)
            self.assertIsNotNone(snapshot['rsi14'])
            if index == 5:
                self.assertIsNone(snapshot['volRatio'])
            else:
                self.assertIsNotNone(snapshot['volRatio'])
            remote.assert_not_called()

    def test_最新收盤修訂阻擋價格訊號(self):
        self.ds.source_revision_status.return_value = {'count': 1}
        self.conn.execute.return_value.fetchall.return_value = [(self.days[-1], json.dumps({
            'original': [0, 100, 102, 99, 101, 1000],
            'revision': [0, 100, 102, 99, 100, 1000]}))]
        remote = Mock()
        out = routes.load_alert_bars('2330', 'TW', remote)
        snapshot = watch_daemon._ind(out['bars'], 'TW', '2330')
        self.assertIsNone(snapshot['close'])
        self.assertIsNone(snapshot['rsi14'])
        remote.assert_not_called()

    def test_無效來源觀測遮罩當日全欄(self):
        with patch('daily_quality.quality_evidence', return_value={self.days[-1]: {'invalidObservation': True}}):
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
        self.assertEqual(len(out['bars']), 65)
        for key in ('open', 'high', 'low', 'close', 'volume'):
            self.assertIsNone(out['bars'][-1][key])
            self.assertIsNotNone(out['bars'][-2][key])
        snapshot = watch_daemon._ind(out['bars'], 'TW', '2330')
        self.assertIsNone(snapshot['close'])
        self.assertIsNone(snapshot['rsi14'])
        self.assertIsNone(snapshot['volRatio'])
        remote.assert_not_called()

    def test_未知交易日曆不可由遠端繞過(self):
        with patch.object(routes, 'session_state', return_value={'expectedLastDate': None}):
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
        self.assertEqual(out['bars'], [])
        remote.assert_not_called()

    def test_過期日線不更新狀態(self):
        self.ds.get_bars_bulk.return_value = {'2330': self.bars[:-1]}
        out = routes.load_alert_bars('2330', 'TW', Mock(return_value=self.bars[:-1]))
        self.assertEqual(out['bars'], [])
        self.assertTrue(out['error'])

    def test_美股沿用原日線來源(self):
        remote = Mock(return_value=self.bars)
        out = routes.load_alert_bars('AAPL', 'US', remote)
        self.assertEqual(out['bars'], self.bars)
        remote.assert_called_once_with('AAPL', 'US')
        self.ds.read_snapshot.assert_not_called()

    def test_複合未知保留去重狀態(self):
        rule = {'sym': '2330', 'type': 'composite', '_last_fired': True,
                'conditions': [{'left': 'rsi14', 'op': 'gt', 'right': '70'}]}
        with patch.object(alert_daemon, '_fetch_daily_candles', return_value=self.bars), \
             patch.object(alert_daemon, '_calc_ind', return_value={'rsi14': None}):
            self.assertFalse(alert_daemon._check_composite(rule, {}))
        self.assertTrue(rule['_last_fired'])

    def test_複合三值邏輯更新去重狀態(self):
        for combine, close, previous, expected, changed in (
                ('AND', 90, True, False, True),
                ('AND', 110, True, True, False),
                ('OR', 110, False, True, True),
                ('OR', 90, True, True, False)):
            with self.subTest(combine=combine, close=close):
                rule = {'sym': '2330', 'type': 'composite', 'combine': combine,
                        '_last_fired': previous, 'conditions': [
                            {'left': 'close', 'op': 'gt', 'right': '100'},
                            {'left': 'rsi14', 'op': 'gt', 'right': '70'}]}
                with patch.object(alert_daemon, '_fetch_daily_candles', return_value=self.bars), \
                     patch.object(alert_daemon, '_calc_ind', return_value={'close': close, 'rsi14': None}), \
                     patch.object(alert_daemon, 'notify'):
                    self.assertEqual(alert_daemon._check_composite(rule, {}), changed)
                self.assertEqual(rule['_last_fired'], expected)

    def test_突破量比未知不重設既有觸發(self):
        old = {'2330:x': {'status': 'trigger', 'last_fired_time': 100, 'fired_price': 100}}
        ind = {'close': 120, 'highs': [100] * 21, 'volVs20d': None}
        self.assertEqual(watch_daemon._eval('breakout_n_high', ind, {})[0], 'none')
        with patch.object(watch_daemon.alert_daemon, 'load_config', return_value={'watch_enabled': True}), \
             patch.object(watch_daemon, 'load_rules', return_value={'2330': {'signals': [{'id': 'x', 'strategy': 'breakout_n_high'}]}}), \
             patch.object(watch_daemon, '_load_state', return_value=old.copy()), \
             patch.object(watch_daemon, '_fetch_daily', return_value=self.bars), \
             patch.object(watch_daemon, '_ind', return_value=ind), \
             patch.object(watch_daemon, '_save_state') as save:
            watch_daemon.check_once()
            save.assert_called_once_with(old)
        # 已知未突破時，量比未知不妨礙解除；仍沿用價格遲滯。
        for close, should_reset in ((98, True), (99.5, False)):
            with self.subTest(close=close):
                below = {**ind, 'close': close}
                self.assertEqual(watch_daemon._eval('breakout_n_high', below, {})[0], 'wait')
                with patch.object(watch_daemon.alert_daemon, 'load_config', return_value={'watch_enabled': True}), \
                     patch.object(watch_daemon, 'load_rules', return_value={'2330': {'signals': [{'id': 'x', 'strategy': 'breakout_n_high'}]}}), \
                     patch.object(watch_daemon, '_load_state', return_value=old.copy()), \
                     patch.object(watch_daemon, '_fetch_daily', return_value=self.bars), \
                     patch.object(watch_daemon, '_ind', return_value=below), \
                     patch.object(watch_daemon, '_save_state') as save:
                    watch_daemon.check_once()
                expected = {'2330:x': {'status': None, 'last_fired_time': 100, 'fired_price': None}} if should_reset else old
                save.assert_called_once_with(expected)
        self.assertEqual(watch_daemon._eval('breakout_n_high', {**ind, 'volVs20d': 1}, {})[0], 'partial')
        self.assertEqual(watch_daemon._eval('breakout_n_high', {**ind, 'volVs20d': 2}, {})[0], 'trigger')
        # 2026-10-19 Sam 核准：突破量能改用當日量口徑，5 日／20 日均量比不再決定突破。
        self.assertEqual(watch_daemon._eval('breakout_n_high', {**ind, 'volRatio': 2, 'volVs20d': 1}, {})[0], 'partial')

    def test_已核對官方股數保留量比與來源收據(self):
        day = self.days[-1]
        official = {'status': 'selected', 'source': 'TWSE', 'unit': '股', 'asOf': day,
                    'receiptIds': ['已核對收據'], 'value': 2000}
        evidence = {'volumeConflict': True, 'receiptComplete': True, 'priceVerified': True,
                    'officialResearchVolume': official}
        with patch('daily_quality.quality_evidence', return_value={day: evidence}):
            remote = Mock()
            out = routes.load_alert_bars('2330', 'TW', remote)
        self.assertEqual(out['bars'][-1]['volume'], 2000)
        self.assertEqual(out['bars'][-1]['close'], 101)
        self.assertEqual(out['officialResearchVolumes'][day], official)
        self.assertIsNotNone(watch_daemon._ind(out['bars'], 'TW', '2330')['volRatio'])
        remote.assert_not_called()
        for change in ({'receiptComplete': False}, {'invalidReceipt': True},
                       {'invalidObservation': True}, {'priceConflict': True},
                       {'officialResearchVolume': {**official, 'status': 'unavailable'}},
                       {'officialResearchVolume': {**official, 'receiptIds': []}}):
            with self.subTest(change=change), patch('daily_quality.quality_evidence', return_value={day: {**evidence, **change}}):
                out = routes.load_alert_bars('2330', 'TW', Mock())
            self.assertIsNone(out['bars'][-1]['volume'])
            self.assertEqual(out['officialResearchVolumes'], {})

    def test_來源修訂量遮罩可用已核對官方值但價格衝突不可(self):
        day = self.days[-1]
        official = {'status': 'selected', 'source': 'TWSE', 'unit': '股', 'asOf': day,
                    'receiptIds': ['已核對修訂收據'], 'value': 2000}
        evidence = {'volumeConflict': False, 'receiptComplete': True, 'priceVerified': True,
                    'officialResearchVolume': official}
        self.ds.source_revision_status.return_value = {'count': 1}
        for price_conflict in (False, True):
            revised = [0, 100, 102, 99, 100 if price_conflict else 101, 2000]
            self.conn.execute.return_value.fetchall.return_value = [(day, json.dumps({
                'original': [0, 100, 102, 99, 101, 1000], 'revision': revised}))]
            with self.subTest(price_conflict=price_conflict), patch('daily_quality.quality_evidence', return_value={day: evidence}):
                remote = Mock()
                out = routes.load_alert_bars('2330', 'TW', remote)
            if price_conflict:
                self.assertIsNone(out['bars'][-1]['close'])
                self.assertIsNone(out['bars'][-1]['volume'])
                self.assertEqual(out['officialResearchVolumes'], {})
            else:
                self.assertEqual(out['bars'][-1]['close'], 101)
                self.assertEqual(out['bars'][-1]['volume'], 2000)
                self.assertEqual(out['officialResearchVolumes'][day], official)
                self.assertIsNotNone(watch_daemon._ind(out['bars'], 'TW', '2330')['volRatio'])
            remote.assert_not_called()

    def test_WATCH未知保留狀態自訂價位仍可使用(self):
        old = {'2330:x': {'status': 'trigger', 'last_fired_time': 100, 'fired_price': 101}}
        with patch.object(watch_daemon.alert_daemon, 'load_config', return_value={'watch_enabled': True}), \
             patch.object(watch_daemon, 'load_rules', return_value={'2330': {'signals': [{'id': 'x', 'strategy': 'sma60_pullback'}]}}), \
             patch.object(watch_daemon, '_load_state', return_value=old.copy()), \
             patch.object(watch_daemon, '_fetch_daily', return_value=self.bars), \
             patch.object(watch_daemon, '_ind', return_value={'close': None}), \
             patch.object(watch_daemon, '_save_state') as save:
            watch_daemon.check_once()
            save.assert_called_once_with(old)
        self.assertEqual(watch_daemon._eval('custom_buy', {'close': 100}, {'target': 101})[0], 'trigger')


if __name__ == '__main__':
    unittest.main()
