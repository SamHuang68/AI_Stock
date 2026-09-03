#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherSafetyTests(unittest.TestCase):
    def test_canonical_windows_launcher_never_discards_work(self):
        script = (ROOT / 'scripts' / 'go.ps1').read_text(encoding='utf-8')
        lowered = script.lower()
        for destructive in ('reset --hard', 'checkout -f', 'git stash', 'clean -fd'):
            self.assertNotIn(destructive, lowered)
        self.assertIn('git status --porcelain', script)
        self.assertIn('git merge --ff-only', script)
        self.assertIn('Resolve-StockPython', script)

    def test_batch_files_are_ascii_shims_and_only_stop_the_owned_port(self):
        go = (ROOT / 'scripts' / 'go.bat').read_bytes()
        start = (ROOT / 'START_TIP.cmd').read_bytes()
        go.decode('ascii')
        start.decode('ascii')
        go_text = go.decode('ascii').lower()
        start_text = start.decode('ascii').lower()
        self.assertIn('go.ps1', go_text)
        self.assertNotRegex(go_text, r'(?m)^\s*git\s+')
        self.assertIn(':18432', start_text)
        self.assertNotIn('taskkill /im python', start_text)

    def test_etf_scheduler_uses_pinned_python_shared_history_and_health_gate(self):
        wrapper = (ROOT / 'scripts' / 'daily_etf.bat').read_bytes()
        wrapper_text = wrapper.decode('ascii').lower()
        script = (ROOT / 'scripts' / 'daily_etf.ps1').read_text(encoding='utf-8')
        installer = (ROOT / 'scripts' / 'install_scheduler.bat').read_text(encoding='ascii')
        self.assertNotIn(b'\x00', wrapper)
        self.assertIn('%~dp0daily_etf.ps1', wrapper_text)
        self.assertIn('%*', wrapper_text)
        self.assertIn('Resolve-StockPython', script)
        self.assertIn('stock_python.path', script)
        self.assertIn('ST_ETF_HISTORY_DIR', script)
        self.assertIn(r'shared-data\etf_history', script)
        self.assertIn('etf_snapshot_health.py', script)
        self.assertIn('exit $TrackerRc', script)
        self.assertIn('exit $HealthRc', script)
        self.assertIn('-WorkingDirectory', installer)
        self.assertIn('-RequireApi', installer)
        self.assertIn('http://127.0.0.1:18435/etf-delta', installer)
        self.assertIn('New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 7pm', installer)


if __name__ == '__main__':
    unittest.main()
