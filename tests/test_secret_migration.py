#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from server import ai_api, alert_daemon


class SecretMigrationTests(unittest.TestCase):
    def test_legacy_ai_key_moves_out_of_plaintext(self):
        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / 'ai_key.txt'
            protected = Path(temp) / 'ai_key.bin'
            legacy.write_text('test-secret-value', encoding='utf-8')
            with mock.patch.object(ai_api, '_AI_KEY_FILE', str(protected)), \
                    mock.patch.object(ai_api, '_AI_KEY_LEGACY_FILE', str(legacy)):
                self.assertEqual(ai_api.load_ai_key(), 'test-secret-value')
            self.assertFalse(legacy.exists())
            self.assertNotEqual(protected.read_bytes(), b'test-secret-value')

    def test_alert_config_and_backup_never_contain_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'alert_config.json'
            rules = Path(temp) / 'alert_rules.json'
            secrets = Path(temp) / 'alert_secrets.bin'
            value = json.loads(json.dumps(alert_daemon._DEFAULT_CONFIG))
            value['telegram']['bot_token'] = 'telegram-secret'
            value['email']['app_password'] = 'mail-secret'
            with mock.patch.object(alert_daemon, 'CONFIG_FILE', str(config)), \
                    mock.patch.object(alert_daemon, 'RULES_FILE', str(rules)), \
                    mock.patch.object(alert_daemon, 'SECRETS_FILE', str(secrets)):
                alert_daemon.save_config(value)
                loaded = alert_daemon.load_config()
            self.assertEqual(loaded['telegram']['bot_token'], 'telegram-secret')
            self.assertEqual(loaded['email']['app_password'], 'mail-secret')
            for path in (config, Path(str(config) + '.bak')):
                text = path.read_text(encoding='utf-8')
                self.assertNotIn('telegram-secret', text)
                self.assertNotIn('mail-secret', text)


if __name__ == '__main__':
    unittest.main()
