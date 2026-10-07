#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服務啟動順序：背景程式必須在持久佇列接線之後啟動。

交易日 14:00-21:00 且每日排程已開時，每日個股留存一啟動就會把工作排進佇列；
若早於 configure_updates，舊佇列已有工作，use_durable_queue 會拒絕並使服務啟動失敗。
"""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'server', 'server.py')


class StartupOrderTests(unittest.TestCase):
    def setUp(self):
        with open(SERVER, encoding='utf-8') as handle:
            self.source = handle.read()

    def position(self, needle):
        self.assertEqual(self.source.count(needle), 1, needle)
        return self.source.index(needle)

    def test_research_daemon_starts_after_durable_queue_is_configured(self):
        configure = self.position('configure_updates(_pulse_updates)')
        self.assertGreater(self.position('_research_maintenance.start_daemon()'), configure)

    def test_options_schedule_starts_after_durable_queue_is_configured(self):
        configure = self.position('configure_updates(_pulse_updates)')
        self.assertGreater(self.position('_options_schedule.start_daemon('), configure)


if __name__ == '__main__':
    unittest.main()
