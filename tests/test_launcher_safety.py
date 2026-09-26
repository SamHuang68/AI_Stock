#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
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

    def test_stop_private_web_stops_isolated_host_from_any_folder(self):
        text = (ROOT / 'STOP_PRIVATE_WEB.cmd').read_bytes().decode('ascii')
        low = text.lower()
        # The promoted copy's supervisor restarts gateway/backend unless it is stopped
        # first; run from the dev folder the script must still find its pid file.
        self.assertIn(r'%localappdata%\stockterminalprivateweb\current', low)
        self.assertIn('*private_web_host.py*', low)
        host = low.index('private_web_host.pid')
        self.assertLess(host, low.index('*private_web_host.py*'))
        self.assertLess(low.index('*private_web_host.py*'), low.index('private_web_gateway.pid'))
        self.assertLess(low.index('private_web_gateway.pid'), low.index('for %%p in'))
        # Only the private ports are swept; development ST :18432 is never killed.
        self.assertEqual(set(re.findall(r'for %%p in \(([^)]*)\)', low)), {'18434 18435'})
        code = '\n'.join(l for l in low.splitlines() if not l.strip().startswith('rem '))
        self.assertNotIn('taskkill /im', code)
        self.assertNotIn('server.py', code)
        # A stale pid file (e.g. after a reboot) must not kill an unrelated process.
        self.assertEqual(low.count('tasklist /fi "pid eq !st_web_pid!"'), 2)
        self.assertEqual(low.count('if /i "%%i"=="python.exe" taskkill /pid !st_web_pid!'), 2)
        # The promoted copy is exported with LF endings, where cmd label lookup is
        # unreliable, and !vars! are not expanded inside pipes: no labels, no piped pids.
        self.assertNotRegex(code, r'(?m)^\s*:|\bcall :|\bgoto ')
        self.assertNotRegex(code, r'!st_web_pid![^\n]*\|')
        self.assertIn('still listening', low)
        self.assertIn('exit /b 1', low)

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
