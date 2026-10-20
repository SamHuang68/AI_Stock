"""審查 AL-01：推播全部通道失敗時進待送匣重試，記錄失敗原因（不含權杖），並回報送達狀態。不連網。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import alert_daemon  # noqa: E402

TOKEN = '123456:SECRET-TOKEN'
CFG = {'telegram': {'enabled': True, 'bot_token': TOKEN, 'chat_id': '1'},
       'email': {'enabled': False}, 'webhook': {'enabled': False}}
FAIL = (False, {'telegram': f'<urlopen error https://api.telegram.org/bot{TOKEN}/sendMessage timed out>',
                'email': 'email disabled/unconfigured', 'webhook': 'webhook disabled/unconfigured'})
OK = (True, {'telegram': 'ok', 'email': 'email disabled/unconfigured', 'webhook': 'webhook disabled/unconfigured'})
NONE = (False, {'telegram': 'telegram disabled/unconfigured', 'email': 'email disabled/unconfigured',
                'webhook': 'webhook disabled/unconfigured'})


class AlertDeliveryOutboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, value in (('OUTBOX_FILE', str(root / 'alert_outbox.json')), ('LOG_DIR', str(root / 'logs'))):
            patcher = mock.patch.object(alert_daemon, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        saved = dict(alert_daemon._state)
        self.addCleanup(lambda: (alert_daemon._state.clear(), alert_daemon._state.update(saved)))
        alert_daemon._state.update(fired=[], deliveries=[])
        self.logs = root / 'logs'

    def log_text(self):
        return ''.join(p.read_text(encoding='utf-8') for p in self.logs.glob('*.log'))

    def test_all_channels_failing_queues_and_logs_without_token(self):
        with mock.patch.object(alert_daemon, 'notify', return_value=FAIL):
            out = alert_daemon.deliver(CFG, '測試警報', source='price', now=1000.0)
        self.assertEqual(out['status'], 'queued')
        self.assertEqual(alert_daemon.outbox_pending(), 1)
        log = self.log_text()
        self.assertIn('送出失敗（price，第 1 次）', log)
        self.assertIn('timed out', log)
        self.assertNotIn(TOKEN, log)
        self.assertEqual(alert_daemon._state['deliveries'][-1]['status'], 'queued')

    def test_retry_waits_gap_then_sends_and_clears(self):
        with mock.patch.object(alert_daemon, 'notify', return_value=FAIL):
            alert_daemon.deliver(CFG, '測試警報', now=1000.0)
        with mock.patch.object(alert_daemon, 'notify', return_value=OK) as notify:
            self.assertEqual(alert_daemon.retry_outbox(CFG, now=1030.0)['pending'], 1)
            notify.assert_not_called()
            out = alert_daemon.retry_outbox(CFG, now=1061.0)
        notify.assert_called_once()
        self.assertEqual(out['sent'], 1)
        self.assertEqual(alert_daemon.outbox_pending(), 0)
        self.assertEqual(alert_daemon._state['deliveries'][-1]['status'], 'sent')
        self.assertEqual(alert_daemon._state['deliveries'][-1]['attempts'], 2)

    def test_gives_up_after_max_attempts(self):
        with mock.patch.object(alert_daemon, 'notify', return_value=FAIL):
            alert_daemon.deliver(CFG, '測試警報', now=1000.0)
            now = 1000.0
            for _ in range(alert_daemon.OUTBOX_MAX_ATTEMPTS - 1):
                now += alert_daemon.OUTBOX_RETRY_GAP_SECONDS + 1
                alert_daemon.retry_outbox(CFG, now=now)
        self.assertEqual(alert_daemon.outbox_pending(), 0)
        self.assertEqual(alert_daemon._state['deliveries'][-1]['status'], 'failed')
        self.assertEqual(alert_daemon._state['deliveries'][-1]['attempts'], alert_daemon.OUTBOX_MAX_ATTEMPTS)
        self.assertIn('放棄送出', self.log_text())

    def test_stale_item_dropped_without_sending(self):
        with mock.patch.object(alert_daemon, 'notify', return_value=FAIL):
            alert_daemon.deliver(CFG, '舊警報', now=1000.0)
        with mock.patch.object(alert_daemon, 'notify', return_value=OK) as notify:
            alert_daemon.retry_outbox(CFG, now=1000.0 + alert_daemon.OUTBOX_MAX_AGE_SECONDS + 1)
        notify.assert_not_called()
        self.assertEqual(alert_daemon.outbox_pending(), 0)
        self.assertEqual(alert_daemon._state['deliveries'][-1]['status'], 'failed')

    def test_no_configured_channel_is_not_queued(self):
        with mock.patch.object(alert_daemon, 'notify', return_value=NONE):
            out = alert_daemon.deliver(CFG, '測試警報', now=1000.0)
        self.assertEqual(out['status'], 'no_channel')
        self.assertEqual(alert_daemon.outbox_pending(), 0)

    def test_pass_stops_at_first_still_failing_item(self):
        with mock.patch.object(alert_daemon, 'notify', return_value=FAIL):
            alert_daemon.deliver(CFG, '一', now=1000.0)
            alert_daemon.deliver(CFG, '二', now=1000.0)
        with mock.patch.object(alert_daemon, 'notify', return_value=FAIL) as notify:
            alert_daemon.retry_outbox(CFG, now=1061.0)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(alert_daemon.outbox_pending(), 2)

    def test_composite_rule_records_delivery_status(self):
        rule = {'sym': '2330', 'type': 'composite', 'combine': 'AND', '_last_fired': False,
                'conditions': [{'left': 'close', 'op': 'gt', 'right': '100'}]}
        with mock.patch.object(alert_daemon, '_fetch_daily_candles', return_value=[{'close': 1}]), \
                mock.patch.object(alert_daemon, '_calc_ind', return_value={'close': 120}), \
                mock.patch.object(alert_daemon, 'notify', return_value=FAIL):
            self.assertTrue(alert_daemon._check_composite(rule, CFG))
        self.assertEqual(alert_daemon._state['fired'][-1]['delivery'], 'queued')
        self.assertEqual(alert_daemon.outbox_pending(), 1)


if __name__ == '__main__':
    unittest.main()
