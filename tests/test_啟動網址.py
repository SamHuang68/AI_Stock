from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', '使用真實 PowerShell 5.1 驗證網址開啟邊界')
class PrivateWebBrowserTests(unittest.TestCase):
    def test_依Serve路由開啟一次且解析失敗不開頁(self):
        source = ROOT / 'scripts/inspect_tailscale_private_web.ps1'
        raw = source.read_text(encoding='utf-8-sig')
        executable = "$tailscale = 'C:\\Program Files\\Tailscale\\tailscale.exe'"
        self.assertEqual(raw.count(executable), 1)
        engine = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        good = {'TCP': {'443': {'HTTPS': True}}, 'Web': {
            'stock.fixture.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:18434'}}}}}
        cases = [
            ('正常開頁', good, '-OpenBrowser', 0, ['https://stock.fixture.ts.net/#pulse']),
            ('僅解析不開頁', good, '-ResolveUrl', 0, []),
            ('路由缺失', {}, '-OpenBrowser', 1, []),
            ('指向其他服務', {'TCP': good['TCP'], 'Web': {
                'stock.fixture.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:18432'}}}}}, '-OpenBrowser', 1, []),
            ('非HTTPS', {'TCP': {'443': {'HTTPS': False}}, 'Web': good['Web']}, '-OpenBrowser', 1, []),
            ('多個路由不猜測', {'TCP': good['TCP'], 'Web': dict(good['Web'], **{
                'other.fixture.ts.net:443': good['Web']['stock.fixture.ts.net:443']})}, '-OpenBrowser', 1, []),
        ]
        with tempfile.TemporaryDirectory(prefix='st-web-url-') as temporary:
            case = Path(temporary)
            stub = case / 'tailscale.cmd'
            stub.write_bytes(b'@echo off\r\nif not "%*"=="serve status --json" exit /b 9\r\ntype "%~dp0serve.json"\r\nexit /b 0\r\n')
            candidate = case / source.name
            candidate.write_text(raw.replace(executable, "$tailscale = '" + str(stub).replace("'", "''") + "'"), encoding='utf-8-sig')
            launch_log = case / 'opened.txt'
            harness = case / '邊界.ps1'
            harness.write_text(
                "param([string]$Mode)\n"
                "function Start-Process { param([string]$FilePath)\n"
                "[IO.File]::AppendAllText((Join-Path $PSScriptRoot 'opened.txt'), $FilePath + [Environment]::NewLine) }\n"
                "$options = @{OpenBrowser=($Mode -eq '-OpenBrowser');ResolveUrl=($Mode -eq '-ResolveUrl')}\n"
                "& (Join-Path $PSScriptRoot 'inspect_tailscale_private_web.ps1') @options\nexit $LASTEXITCODE\n",
                encoding='utf-8-sig')
            for name, config, mode, expected, opened in cases:
                with self.subTest(name=name):
                    launch_log.unlink(missing_ok=True)
                    (case / 'serve.json').write_text(json.dumps(config), encoding='ascii')
                    result = subprocess.run([str(engine), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(harness), '-Mode', mode], capture_output=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode, expected, (result.stdout + result.stderr).decode('utf-8', 'replace'))
                    self.assertEqual(launch_log.read_text().splitlines() if launch_log.exists() else [], opened)
                    if mode == '-ResolveUrl':
                        self.assertIn(b'https://stock.fixture.ts.net/#pulse', result.stdout)


if __name__ == '__main__':
    unittest.main()
