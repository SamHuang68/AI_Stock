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

    def test_wavedeck_reuses_stock_python_and_reserves_private_web_ports(self):
        launcher = (ROOT / 'wavedeck' / 'START_WAVEDECK.cmd').read_text(encoding='utf-8')
        self.assertIn(r'data\stock_python.path', launcher)
        self.assertIn('py -3 -c "import sys; print(sys.executable)"', launcher)
        self.assertIn('"%PYEXE%" run.py', launcher)
        self.assertNotIn('PYEXE=python', launcher)

        wd_server = (ROOT / 'wavedeck' / 'server' / 'server.py').read_text(encoding='utf-8')
        self.assertIn('PRIVATE_WEB_PORTS = frozenset({18434, 18435})', wd_server)
        self.assertIn('n in PRIVATE_WEB_PORTS', wd_server)
        bus = (ROOT / 'server' / 'wavedeck_bus.py').read_text(encoding='utf-8')
        self.assertIn('WD_PORTS = (18433, 18765, 28765, 38433, 8765)', bus)

        ui = (ROOT / 'src' / 'ui' / 'wavedeck_bridge_v5.js').read_text(encoding='utf-8')
        ui_candidates = ui.split('var CANDIDATES = [', 1)[1].split('];', 1)[0]
        self.assertNotIn('18434', ui_candidates)
        self.assertNotIn('18435', ui_candidates)
        self.assertIn('isReservedPrivateWebUrl(configuredBase)', ui)

        wait_ready = (ROOT / 'wavedeck' / 'wait_ready.ps1').read_text(encoding='utf-8')
        self.assertIn('$candidates = @(18433, 18765, 28765, 38433, 8765)', wait_ready)
        self.assertIn('[int]$p -notin @(18434, 18435)', wait_ready)
        self.assertIn('$ports = @(18433,18765,28765,38433,8765)', launcher)
        self.assertIn('[int]$p -notin @(18434,18435)', launcher)

        alert = (ROOT / 'server' / 'alert_daemon.py').read_text(encoding='utf-8')
        self.assertIn('ALERT_DAEMON_LOCK_PORT = 18436', alert)
        self.assertIn("s.bind(('127.0.0.1', ALERT_DAEMON_LOCK_PORT))", alert)

    def test_private_web_stop_only_terminates_verified_process_identity(self):
        script = (ROOT / 'STOP_PRIVATE_WEB.cmd').read_text(encoding='utf-8')
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
        self.assertIn('Get-CimInstance Win32_Process', script)
        self.assertIn('private_web_host.py', script)
        self.assertIn('private_web_gateway.py', script)
        self.assertNotIn('netstat -ano', script)
        self.assertIn('cmd /d /c .\\STOP_PRIVATE_WEB.cmd', ci)


if __name__ == '__main__':
    unittest.main()
