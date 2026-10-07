from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _crlf(text: str) -> bytes:
    return text.replace('\r\n', '\n').replace('\n', '\r\n').encode('ascii')


STUBS = {
    'powershell': r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo powershell-query
if exist "%ST_TEST_FIXTURE%\query-fails.flag" exit /b 2
if exist "%ST_TEST_FIXTURE%\task-running.flag" exit /b 0
exit /b 1
''',
    'curl': r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo curl %*
if "%~4"=="http://127.0.0.1:18432/health" (
  if exist "%ST_TEST_FIXTURE%\local-health.flag" (
    echo {"runtimeCommit":"fixture"}
    exit /b 0
  )
  exit /b 7
)
if "%~4"=="http://127.0.0.1:18434/gateway/health" (
  if not exist "%ST_TEST_FIXTURE%\gateway-live.flag" exit /b 7
  if exist "%ST_TEST_FIXTURE%\upstream-ready.flag" (
    echo {"gateway":"private-web","upstream":true}
  ) else (
    echo {"gateway":"private-web","upstream":false}
  )
  exit /b 0
)
>>"%ST_TEST_FIXTURE%\calls.log" echo unexpected-curl
exit /b 99
''',
    'schtasks': r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo schtasks %*
if /i "%~1"=="/query" (
  if exist "%ST_TEST_FIXTURE%\task-running.flag" (
    echo Status: Running
  ) else (
    echo Status: Ready
  )
  exit /b 0
)
if /i "%~1"=="/run" (
  if exist "%ST_TEST_FIXTURE%\run-fails.flag" exit /b 1
  if exist "%ST_TEST_FIXTURE%\recover-on-run.flag" (
    >"%ST_TEST_FIXTURE%\gateway-live.flag" echo 1
    >"%ST_TEST_FIXTURE%\upstream-ready.flag" echo 1
  )
  >"%ST_TEST_FIXTURE%\task-running.flag" echo 1
  exit /b 0
)
>>"%ST_TEST_FIXTURE%\calls.log" echo unexpected-schtasks
exit /b 99
''',
    'timeout': r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo timeout
exit /b 0
''',
    'start': r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo start
if exist "%ST_TEST_FIXTURE%\recover-local-on-start.flag" >"%ST_TEST_FIXTURE%\local-health.flag" echo 1
exit /b 0
''',
}


def _instrument_external_command_tokens(raw: bytes) -> tuple[bytes, dict[str, int]]:
    """僅在副本換掉外部動作，原始分支、標籤、管線、findstr 與退出碼不變。"""
    text = raw.decode('ascii')
    counts = {}
    for name in STUBS:
        pattern = r'(?im)^([ \t]*)' + re.escape(name) + r'(?:\.exe)?(?=[ \t])'
        replacement = r'\1call "%ST_TEST_FIXTURE%\\' + name + r'-stub.cmd"'
        text, counts[name] = re.subn(pattern, replacement, text)
    expected = {'powershell': 1, 'curl': 3, 'schtasks': 1, 'timeout': 2, 'start': 1}
    if counts != expected:
        raise AssertionError(f'外部命令清單已變動，需先核對隔離完整性：{counts!r}')
    unsafe = r'(?im)^[ \t]*(?:powershell(?:\.exe)?|curl(?:\.exe)?|schtasks(?:\.exe)?|timeout(?:\.exe)?|start)(?=[ \t])'
    if re.search(unsafe, text):
        raise AssertionError('副本仍有未隔離的外部動作')
    return _crlf(text), counts


@unittest.skipUnless(os.name == 'nt', '此行為驗證依賴 Windows 真實 CMD 解析器')
class LauncherCmdOfflineBehaviorTests(unittest.TestCase):
    """無連線、排程操作、正式埠監聽或 GUI 的真實 CMD 行為回歸。"""

    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE_ROOT / 'START_LOCAL_AND_WEB.cmd'
        cls.raw = cls.source.read_bytes()
        cls.instrumented, cls.substitution_counts = _instrument_external_command_tokens(cls.raw)
        cls.cmd = Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe'
        cls.fixture = tempfile.TemporaryDirectory(prefix='st-cmd-fixtures-')
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.run_root = Path(cls.fixture.name)

    def run_case(self, name, *, local=True, gateway=True, upstream=False,
                 running=False, recover=False, run_fails=False, recover_local=False, query_fails=False):
        case = Path(tempfile.mkdtemp(prefix='cmd-case-', dir=self.run_root))
        self.addCleanup(self.remove_case, case)
        (case / 'launcher.cmd').write_bytes(self.instrumented)
        for command, text in STUBS.items():
            (case / f'{command}-stub.cmd').write_bytes(_crlf(text))
        states = {
            'local-health': local,
            'gateway-live': gateway,
            'upstream-ready': upstream,
            'task-running': running,
            'recover-on-run': recover,
            'run-fails': run_fails,
            'query-fails': query_fails,
            'recover-local-on-start': recover_local,
        }
        for flag, enabled in states.items():
            if enabled:
                (case / (flag + '.flag')).write_bytes(b'1\r\n')
        env = dict(os.environ, ST_TEST_FIXTURE=str(case))
        # /s 去除外層引號後，留下有引號的完整 launcher 路徑；不啟動可見視窗。
        command_line = f'"{self.cmd}" /d /s /c ""{case / "launcher.cmd"}""'
        done = subprocess.run(command_line, cwd=case, env=env, capture_output=True,
                              timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        output = (done.stdout + done.stderr).decode('ascii', 'replace')
        calls = (case / 'calls.log').read_text(encoding='ascii').splitlines()
        self.assertFalse(any(line.startswith('unexpected-') for line in calls), calls)
        run_calls = [line for line in calls if line.startswith('schtasks /run ')]
        query_calls = [line for line in calls if line == 'powershell-query']
        start_calls = [line for line in calls if line == 'start']
        result = {'name': name, 'exitCode': done.returncode, 'hostRunCount': len(run_calls),
                  'taskQueryCount': len(query_calls), 'localStartCount': len(start_calls),
                  'upstreamReadyAfterRun': (case / 'upstream-ready.flag').exists()}
        return done.returncode, output, result

    def remove_case(self, case):
        # 遞迴清理前，確認解析後的目標仍在本 harness 的 runs 目錄內。
        resolved = case.resolve()
        run_root = self.run_root.resolve()
        if resolved == run_root or not resolved.is_relative_to(run_root):
            raise AssertionError(f'拒絕清理不屬於 fixture 的路徑：{resolved}')
        shutil.rmtree(resolved)

    def test_source_is_ascii_and_preserves_crlf(self):
        self.raw.decode('ascii')
        self.assertIn(b'\r\n', self.raw)
        self.assertNotIn(b'\n', self.raw.replace(b'\r\n', b''))
        self.assertNotIn(b'\r', self.raw.replace(b'\r\n', b''))

    def test_all_four_health_exit_codes(self):
        for local, upstream, expected in ((True, True, 0), (False, True, 1),
                                          (True, False, 2), (False, False, 3)):
            with self.subTest(local=local, upstream=upstream):
                code, output, result = self.run_case(
                    f'local-{local}-upstream-{upstream}', local=local, upstream=upstream)
                self.assertEqual(code, expected, output)
                self.assertEqual(result['localStartCount'], 0 if local else 1)
                self.assertEqual(result['hostRunCount'], 0 if upstream else 1)

    def test_gateway_alive_dead_backend_runs_host_and_recovers(self):
        code, output, result = self.run_case('後端停止後恢復', gateway=True,
                                           upstream=False, running=False, recover=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['taskQueryCount'], 1)
        self.assertEqual(result['hostRunCount'], 1)
        self.assertTrue(result['upstreamReadyAfterRun'])

    def test_running_task_is_not_restarted(self):
        code, output, result = self.run_case('工作執行中不重啟', upstream=False,
                                           running=True, recover=True)
        self.assertEqual(code, 2, output)
        self.assertEqual(result['taskQueryCount'], 1)
        self.assertEqual(result['hostRunCount'], 0)
        self.assertFalse(result['upstreamReadyAfterRun'])

    def test_host_run_failure_preserves_web_down_exit_code(self):
        code, output, result = self.run_case('啟動工作失敗', gateway=True,
                                           upstream=False, run_fails=True)
        self.assertEqual(code, 2, output)
        self.assertEqual(result['hostRunCount'], 1)
        self.assertIn('[FAIL] Could not start task', output)

    def test_unknown_task_state_never_requests_a_start(self):
        code, output, result = self.run_case('排程狀態無法確認', upstream=False, query_fails=True)
        self.assertEqual(code, 2, output)
        self.assertEqual(result['hostRunCount'], 0)
        self.assertIn('No start requested', output)



_QUERY_BOUNDARY = r'''
function Get-ScheduledTask {
  param([string]$TaskName, [string]$ErrorAction)
  if ($TaskName -ne 'StockTerminal_PrivateWeb_Host') { throw '查詢了未約定的排程。' }
  if ($env:ST_TEST_TASK_STATE -eq 'throw') { throw '合成排程查詢失敗。' }
  return [pscustomobject]@{ State = [int]$env:ST_TEST_TASK_STATE; DisplayState = $env:ST_TEST_TASK_DISPLAY }
}
'''


@unittest.skipUnless(os.name == 'nt', '驗證 Windows 排程查詢的 PowerShell 語意')
class ScheduledTaskQueryOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (SOURCE_ROOT / 'START_LOCAL_AND_WEB.cmd').read_bytes()
        source = raw.decode('ascii')
        pattern = r'(?im)^[ \t]*(?:powershell(?:\.exe)?|"[^"\r\n]*[\\/]powershell\.exe")[ \t]+[^\r\n]*?-Command[ \t]+"(?P<command>[^"\r\n]+)"'
        matches = list(re.finditer(pattern, source))
        if len(matches) != 1:
            raise AssertionError('必須恰有一個可核對的 PowerShell 排程查詢邊界')
        cls.command = matches[0].group('command')
        if 'Get-ScheduledTask' not in cls.command:
            raise AssertionError('來源沒有使用已約定的排程查詢 API')
        cls.engines = {name: path for name in ('powershell', 'pwsh') if (path := shutil.which(name))}
        if 'powershell' not in cls.engines:
            raise AssertionError('必須涵蓋 CMD 實際使用的 Windows PowerShell 5.1')

    def query(self, engine, state, display):
        done = subprocess.run([engine, '-NoProfile', '-Command', _QUERY_BOUNDARY + '\n' + self.command],
                              env=dict(os.environ, ST_TEST_TASK_STATE=str(state), ST_TEST_TASK_DISPLAY=display),
                              capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    def test_numeric_state_ignores_localized_display(self):
        for name, engine in self.engines.items():
            for state, expected, displays in ((4, 0, ('Running', '執行中')), (3, 1, ('Ready', '就緒'))):
                for display in displays:
                    with self.subTest(engine=name, state=state, display=display):
                        code, output = self.query(engine, state, display)
                        self.assertEqual(code, expected, output)

    def test_query_failure_is_not_reported_as_running(self):
        for name, engine in self.engines.items():
            with self.subTest(engine=name):
                code, output = self.query(engine, 'throw', '合成查詢失敗')
                self.assertEqual(code, 2, output)

if __name__ == '__main__':
    unittest.main()
