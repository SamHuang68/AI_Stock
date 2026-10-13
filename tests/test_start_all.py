from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', '使用 Windows 真實 CMD 驗證批次串接')
class StartAllTests(unittest.TestCase):
    def test_all_exit_bits_and_no_browser_argument_are_preserved(self):
        cmd = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
        raw = (ROOT / 'START_ALL.cmd').read_bytes()
        raw.decode('ascii')
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        with tempfile.TemporaryDirectory(prefix='st-all-cmd-') as temp:
            case = Path(temp)
            (case / 'START_ALL.cmd').write_bytes(raw)
            for filename, label, variable in (
                ('START_LOCAL_AND_WEB.cmd', 'stock', 'ST_FIXTURE_RC'),
                ('START_WAVEDECK.cmd', 'wave', 'WD_FIXTURE_RC'),
            ):
                body = f'@echo off\r\n>>"%~dp0calls.log" echo {label} %*\r\nexit /b %{variable}%\r\n'
                (case / filename).write_bytes(body.encode('ascii'))
            for stock in range(4):
                for wave in (0, 1):
                    with self.subTest(stock=stock, wave=wave):
                        (case / 'calls.log').unlink(missing_ok=True)
                        command = f'"{cmd}" /d /s /c ""{case / "START_ALL.cmd"}" --no-browser"'
                        result = subprocess.run(command, cwd=case,
                            env=dict(os.environ, ST_FIXTURE_RC=str(stock), WD_FIXTURE_RC=str(wave)),
                            capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                        self.assertEqual(result.returncode, stock | (4 if wave else 0), result.stderr)
                        self.assertEqual((case / 'calls.log').read_text().splitlines(),
                                         ['stock --no-browser', 'wave --no-browser'])

    def test_root_wavedeck_wrapper_preserves_failure_and_arguments(self):
        cmd = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
        with tempfile.TemporaryDirectory(prefix='wd-root-cmd-') as temp:
            case = Path(temp)
            (case / 'START_WAVEDECK.cmd').write_bytes((ROOT / 'START_WAVEDECK.cmd').read_bytes())
            (case / 'wavedeck').mkdir()
            (case / 'wavedeck/run.py').touch()
            (case / 'wavedeck/START_WAVEDECK.cmd').write_bytes(
                b'@echo off\r\n>"%~dp0args.log" echo %*\r\nexit /b 1\r\n')
            result = subprocess.run(f'"{cmd}" /d /s /c ""{case / "START_WAVEDECK.cmd"}" --no-browser"',
                cwd=case, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual((case / 'wavedeck/args.log').read_text().strip(), '--no-browser')


class WaveDeckHealthIdentityTests(unittest.TestCase):
    def test_real_health_handler_reports_home_and_actual_bound_port(self):
        # 完整模組在獨立 Python 載入；HTTP socket 用動態 loopback 埠，不啟動任何背景 worker。
        code = r'''
import json, os, sys, threading, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from server.server import Handler, ROOT
with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/health', timeout=3) as response:
            body = json.load(response)
        assert body['ok'] is True
        assert body['service'] == 'WaveDeck'
        assert Path(body['baseDir']).resolve() == ROOT.resolve()
        assert body['pythonExe'] == sys.executable
        assert body['pid'] == os.getpid()
        assert body['port'] == server.server_port
        print(json.dumps({'portMatched': True, 'homeMatched': True}))
    finally:
        server.shutdown()
        thread.join(timeout=3)
        assert not thread.is_alive()
'''
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code],
            cwd=ROOT / 'wavedeck', env=dict(os.environ, WAVEDECK_PORT='18433'),
            capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'portMatched': True, 'homeMatched': True})


if __name__ == '__main__':
    unittest.main()
