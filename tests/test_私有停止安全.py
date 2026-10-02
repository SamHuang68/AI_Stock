"""以隔離程序驗證停止器，不啟動或關閉正式服務。"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', '僅 Windows 具有 CIM 程序身分')
class PrivateStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ST停止測試 ')
        self.base = Path(self.tmp.name)
        self.owned = self.base / 'owned'
        self.production = self.base / 'production'
        self.foreign = self.base / 'foreign'
        self.processes = []
        for root in (self.owned, self.production, self.foreign):
            for folder in ('scripts', 'server', 'data'):
                (root / folder).mkdir(parents=True, exist_ok=True)
            for file in ('scripts/private_web_host.py', 'server/private_web_gateway.py', 'server/server.py'):
                (root / file).write_text('import time\ntime.sleep(90)\n', encoding='utf-8')

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
        self.tmp.cleanup()

    def spawn(self, root, script, *, relative=False):
        proc = subprocess.Popen([sys.executable, '-u', script if relative else str(root / script)],
                                cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(proc)
        return proc

    def stop(self):
        return subprocess.run(['cmd', '/d', '/c', str(ROOT / 'STOP_PRIVATE_WEB.cmd'),
                               '-InstallRoot', str(self.owned), '-ProductionRoot', str(self.production)],
                              capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)

    def test_stops_owned_host_children_and_gateway_preserves_foreign_and_dev(self):
        host_script = self.owned / 'scripts/private_web_host.py'
        host_script.write_text(
            'import pathlib,subprocess,sys,time\n'
            'root=pathlib.Path(__file__).resolve().parents[1]\n'
            'p=subprocess.Popen([sys.executable,"-u",str(root/"server/server.py")])\n'
            '(root/"data/child.pid").write_text(str(p.pid))\n'
            'time.sleep(90)\n', encoding='utf-8')
        host = self.spawn(self.owned, 'scripts/private_web_host.py')
        gateway = self.spawn(self.production, 'server/private_web_gateway.py')
        foreign = self.spawn(self.foreign, 'scripts/private_web_host.py')
        dev = self.spawn(self.owned, 'server/server.py')
        pid_file = self.owned / 'data/child.pid'
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(.05)
        self.assertTrue(pid_file.exists())
        child_pid = int(pid_file.read_text())
        try:
            result = self.stop()
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            self.assertIsNotNone(host.poll())
            self.assertIsNotNone(gateway.poll())
            self.assertIsNone(foreign.poll())
            self.assertIsNone(dev.poll())
            check = subprocess.run(['powershell', '-NoProfile', '-Command',
                                    f'if (Get-Process -Id {child_pid} -ErrorAction SilentlyContinue) {{exit 1}}'],
                                   capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 0, '隸屬已核對 host 的 backend 必須停止')
        finally:
            # 僅清理本測試親自啟動且仍隸屬同一 host 的子程序。
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {child_pid}"; '
                            f'if ($p -and $p.ParentProcessId -eq {host.pid}) {{Stop-Process -Id {child_pid} -Force}}'],
                           capture_output=True, timeout=10)

    def test_stale_pid_does_not_kill_another_python(self):
        foreign = self.spawn(self.foreign, 'scripts/private_web_host.py')
        record = self.owned / 'data/private_web_host.pid'
        record.write_text(str(foreign.pid), encoding='ascii')
        result = self.stop()
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(foreign.poll())
        self.assertEqual(record.read_text(), str(foreign.pid))

    def test_relative_identity_is_rejected_without_ending_unverified_process(self):
        host = self.spawn(self.owned, 'scripts/private_web_host.py', relative=True)
        (self.owned / 'data/private_web_host.pid').write_text(str(host.pid), encoding='ascii')
        self.assertEqual(self.stop().returncode, 1)
        self.assertIsNone(host.poll())

    def test_no_services_and_invalid_pid_are_safe(self):
        self.assertEqual(self.stop().returncode, 0)
        record = self.owned / 'data/private_web_gateway.pid'
        record.write_text('not-a-pid', encoding='ascii')
        self.assertEqual(self.stop().returncode, 1)
        self.assertTrue(record.exists())


if __name__ == '__main__':
    unittest.main()
