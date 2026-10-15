from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _crlf(text: str) -> bytes:
    return text.replace('\r\n', '\n').replace('\n', '\r\n').encode('ascii')


STUBS = {
    'powershell': r'''@echo off
if /i "%~1"=="-NoLogo" (
  if /i not "%~2"=="-NoProfile" goto :unexpected
  if /i not "%~3"=="-NonInteractive" goto :unexpected
  if /i "%~4"=="-ExecutionPolicy" (
    if /i not "%~5"=="Bypass" goto :unexpected
    if /i not "%~6"=="-File" goto :unexpected
    if /i "%~8"=="-CheckOnly" (
      >>"%ST_TEST_FIXTURE%\calls.log" echo local-check %~nx7
      if exist "%ST_TEST_FIXTURE%\local-health.flag" exit /b 0
      exit /b 1
    )
    if /i not "%~8"=="-OpenBrowser" goto :unexpected
    >>"%ST_TEST_FIXTURE%\calls.log" echo browser-web
    if exist "%ST_TEST_FIXTURE%\web-open-fails.flag" exit /b 1
    exit /b 0
  )
  if /i not "%~4"=="-Command" goto :unexpected
  if /i "%~5"=="Start-Sleep -Seconds 3" (
    >>"%ST_TEST_FIXTURE%\calls.log" echo powershell-sleep
    exit /b 0
  )
  goto :health
)
if /i not "%~1"=="-NoProfile" goto :unexpected
if /i not "%~2"=="-Command" goto :unexpected
>>"%ST_TEST_FIXTURE%\calls.log" echo powershell-query
if exist "%ST_TEST_FIXTURE%\query-fails.flag" exit /b 2
if exist "%ST_TEST_FIXTURE%\task-running.flag" exit /b 0
exit /b 1
:health
>>"%ST_TEST_FIXTURE%\calls.log" echo powershell-health
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command ". '%ST_TEST_FIXTURE%\health-http-boundary.ps1'; %~5"
exit /b %ERRORLEVEL%
:unexpected
>>"%ST_TEST_FIXTURE%\calls.log" echo unexpected-powershell
exit /b 99
''',
    'curl': r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo curl %*
if "%~4"=="http://127.0.0.1:18432/health" (
  if exist "%ST_TEST_FIXTURE%\local-health.flag" (
    if exist "%ST_TEST_FIXTURE%\local-response.json" (
      type "%ST_TEST_FIXTURE%\local-response.json"
      exit /b 0
    )
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
  if exist "%ST_TEST_FIXTURE%\recover-on-run.flag" if not exist "%ST_TEST_FIXTURE%\gateway-live.flag" (
    >"%ST_TEST_FIXTURE%\gateway-live.flag" echo 1
    >"%ST_TEST_FIXTURE%\upstream-ready.flag" echo 1
  )
  >"%ST_TEST_FIXTURE%\task-running.flag" echo 1
  exit /b 0
)
>>"%ST_TEST_FIXTURE%\calls.log" echo unexpected-schtasks
exit /b 99
''',
    'start': r'''@echo off
if "%~2"=="http://127.0.0.1:18432/#pulse" (
  >>"%ST_TEST_FIXTURE%\calls.log" echo browser-local
  exit /b 0
)
>>"%ST_TEST_FIXTURE%\calls.log" echo start
echo %* | "%SystemRoot%\System32\findstr.exe" /c:"-NoBrowser" >nul
if errorlevel 1 >>"%ST_TEST_FIXTURE%\calls.log" echo browser-local
if exist "%ST_TEST_FIXTURE%\recover-local-on-start.flag" >"%ST_TEST_FIXTURE%\local-health.flag" echo 1
exit /b 0
''',
}


START_TIP_STUB = r'''@echo off
>>"%ST_TEST_FIXTURE%\calls.log" echo start-tip %*
if exist "%ST_TEST_FIXTURE%\tip-fails.flag" exit /b 1
if exist "%ST_TEST_FIXTURE%\recover-local-on-start.flag" >"%ST_TEST_FIXTURE%\local-health.flag" echo 1
exit /b 0
'''


_HEALTH_HTTP_BOUNDARY = r'''
function Invoke-RestMethod {
  param([string]$Uri, [int]$TimeoutSec, [string]$ErrorAction)
  if ($TimeoutSec -ne 3 -or $ErrorAction -ne 'Stop') { throw 'unexpected health request options' }
  $fixture = $env:ST_TEST_FIXTURE
  [IO.File]::AppendAllText((Join-Path $fixture 'calls.log'), ('health-http-fixture ' + $Uri + [Environment]::NewLine), [Text.Encoding]::UTF8)
  if ($Uri -eq 'http://127.0.0.1:18434/gateway/health') {
    if (-not [IO.File]::Exists((Join-Path $fixture 'gateway-live.flag'))) { throw 'offline gateway fixture' }
    $name = 'gateway-response.json'
  } else { throw 'unapproved health request' }
  $body = [IO.File]::ReadAllText((Join-Path $fixture $name), [Text.Encoding]::UTF8)
  $value = ConvertFrom-Json -InputObject $body -ErrorAction Stop
  if ($name -eq 'gateway-response.json' -and -not [IO.File]::Exists((Join-Path $fixture 'gateway-custom.flag'))) {
    $value.upstream = [IO.File]::Exists((Join-Path $fixture 'upstream-ready.flag'))
  }
  return $value
}
'''


def _instrument_external_command_tokens(raw: bytes) -> tuple[bytes, dict[str, int]]:
    """只換外部動作；健康判定保留真 PS5 程式，僅由 HTTP 函式取得固定本文。"""
    text = raw.decode('ascii')
    counts = {}
    for name in STUBS:
        token = re.escape(name) + r'(?:\.exe)?'
        if name == 'powershell':
            token = r'(?:' + token + r'|"%SystemRoot%\\System32\\WindowsPowerShell\\v1\.0\\powershell\.exe")'
        pattern = r'(?im)^([ \t]*)' + token + r'(?=[ \t])'
        replacement = r'\1call "%ST_TEST_FIXTURE%\\' + name + r'-stub.cmd"'
        text, counts[name] = re.subn(pattern, replacement, text)
    source_text = raw.decode('ascii')
    # 本機入口：無條件、恰好一次 call 同資料夾的 START_TIP.cmd -NoBrowser；冷啟動與冪等由它負責。
    if len(re.findall(r'(?im)^call "%~dp0START_TIP\.cmd" -NoBrowser\s*$', source_text)) != 1 \
            or source_text.lower().count('start_tip') != 2:
        raise AssertionError('本機入口契約已變動：必須恰有一次 call START_TIP.cmd -NoBrowser')
    health_commands = re.findall(r'-Command "([^"]*Invoke-RestMethod[^"]*)"', source_text)
    expected = {'powershell': 5, 'curl': 0, 'schtasks': 1, 'start': 1}
    if len(health_commands) != 1:
        raise AssertionError('健康查詢必須只有一個明列的閘道 JSON 邊界；本機改由受管 -CheckOnly 負責')
    for command in health_commands:
        matches = re.findall(r"Invoke-RestMethod -Uri '([^']+)' -TimeoutSec 3 -ErrorAction Stop", command)
        if len(matches) != 1 or command.count('Invoke-RestMethod') != 1:
            raise AssertionError('來源健康 HTTP 契約已變動，不執行未知外部命令')
        if re.search(r'Invoke-WebRequest|\bStart-Process\b|\bStop-Process\b|\bcurl\b|\bschtasks\b', command, re.I):
            raise AssertionError('健康判定夾帶未隔離的外部動作')
        if matches != ['http://127.0.0.1:18434/gateway/health']:
            raise AssertionError('健康查詢超出明列 URI')
    check_calls = re.findall(r'(?im)^"%SystemRoot%\\System32\\WindowsPowerShell\\v1\.0\\powershell\.exe" -NoLogo -NoProfile '
                             r'-NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\\start_local\.ps1" -CheckOnly >nul 2>nul\s*$', source_text)
    if len(check_calls) != 1:
        raise AssertionError('本機狀態必須恰有一次受管 start_local.ps1 -CheckOnly')
    if counts != expected:
        raise AssertionError(f'外部命令清單已變動，需先核對隔離完整性：{counts!r}')
    unsafe = r'(?im)^[ \t]*(?:powershell(?:\.exe)?|"[^"\r\n]*[\\/]powershell\.exe"|curl(?:\.exe)?|schtasks(?:\.exe)?|timeout(?:\.exe)?|start)(?=[ \t])'
    if re.search(unsafe, text):
        raise AssertionError('副本仍有未隔離的外部動作')
    return _crlf(text), counts


def _limit_fixture_poll_attempts(raw: bytes) -> tuple[bytes, dict[str, int]]:
    """離線案例只縮短副本的重試次數；真實健康解析、分支與 30 秒期限保留。"""
    text = raw.decode('ascii')
    budgets = {}
    for side, expected in (('web', 20),):
        pattern = rf'(?m)^if %TRIES% GEQ {expected} \(\s*$'
        text, count = re.subn(pattern, 'if %TRIES% GEQ 2 (', text)
        if count != 1:
            raise AssertionError(f'{side} 原始輪詢次數契約變動：{count}')
        budgets[side] = expected
    return _crlf(text), budgets


@unittest.skipUnless(os.name == 'nt', '此行為驗證依賴 Windows 真實 CMD 解析器')
class LauncherCmdOfflineBehaviorTests(unittest.TestCase):
    """無連線、排程操作、正式埠監聽或 GUI 的真實 CMD 行為回歸。"""

    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE_ROOT / 'START_LOCAL_AND_WEB.cmd'
        cls.raw = cls.source.read_bytes()
        actions, cls.substitution_counts = _instrument_external_command_tokens(cls.raw)
        cls.instrumented, cls.production_poll_budgets = _limit_fixture_poll_attempts(actions)
        cls.cmd = Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe'
        cls.fixture = tempfile.TemporaryDirectory(prefix='st-cmd-fixtures-')
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.run_root = Path(cls.fixture.name)

    def run_case(self, name, *, local=True, gateway=True, upstream=False,
                 running=False, recover=False, run_fails=False, recover_local=False, query_fails=False,
                 gateway_payload=None, no_browser=False, web_open_fails=False, tip_fails=False):
        case = Path(tempfile.mkdtemp(prefix='cmd-case-', dir=self.run_root))
        self.addCleanup(self.remove_case, case)
        (case / 'launcher.cmd').write_bytes(self.instrumented)
        for command, text in STUBS.items():
            (case / f'{command}-stub.cmd').write_bytes(_crlf(text))
        (case / 'health-http-boundary.ps1').write_text(_HEALTH_HTTP_BOUNDARY, encoding='utf-8')
        (case / 'START_TIP.cmd').write_bytes(_crlf(START_TIP_STUB))
        if gateway_payload is not None:
            (case / 'gateway-custom.flag').write_bytes(b'1')
        gateway_payload = {'gateway': 'private-web', 'upstream': upstream} if gateway_payload is None else gateway_payload
        for filename, payload in (('gateway-response.json', gateway_payload),):
            # 完整 HTTP 本文以位元組結束；沒有 echo 換行、合法 JSON 截斷或預先代替健康判定。
            body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            (case / filename).write_bytes(body)
        states = {
            'local-health': local,
            'gateway-live': gateway,
            'upstream-ready': upstream,
            'task-running': running,
            'recover-on-run': recover,
            'run-fails': run_fails,
            'query-fails': query_fails,
            'recover-local-on-start': recover_local,
            'web-open-fails': web_open_fails,
            'tip-fails': tip_fails,
        }
        for flag, enabled in states.items():
            if enabled:
                (case / (flag + '.flag')).write_bytes(b'1\r\n')
        env = dict(os.environ, ST_TEST_FIXTURE=str(case))
        # /s 去除外層引號後，留下有引號的完整 launcher 路徑；不啟動可見視窗。
        args = ' --no-browser' if no_browser else ''
        command_line = f'"{self.cmd}" /d /s /c ""{case / "launcher.cmd"}"{args}"'
        done = subprocess.run(command_line, cwd=case, env=env, capture_output=True,
                              timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        output = (done.stdout + done.stderr).decode('ascii', 'replace')
        calls = (case / 'calls.log').read_text(encoding='ascii').splitlines()
        self.assertFalse(any(line.startswith('unexpected-') for line in calls), calls)
        self.assertLessEqual(calls.count('powershell-health'), 8, calls)
        run_calls = [line for line in calls if line.startswith('schtasks /run ')]
        query_calls = [line for line in calls if line == 'powershell-query']
        start_calls = [line for line in calls if line.startswith('start-tip')]
        result = {'name': name, 'exitCode': done.returncode, 'hostRunCount': len(run_calls),
                  'taskQueryCount': len(query_calls), 'localStartCount': len(start_calls),
                  'browserOpenCount': calls.count('browser-local'),
                  'localCheckCount': calls.count('local-check start_local.ps1'),
                  'startTipFirst': bool(calls) and calls[0] == 'start-tip -NoBrowser',
                  'localHealthHttpCount': len([c for c in calls if '18432/health' in c]),
                  'webBrowserOpenCount': calls.count('browser-web'),
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

    def test_fixture_reduces_shell_startups_and_preserves_production_poll_budgets(self):
        self.assertEqual(self.production_poll_budgets, {'web': 20})
        self.assertEqual(self.instrumented.count(b'if %TRIES% GEQ 2 ('), 1)
        self.assertIn(b'if %TRIES% GEQ 20 (', self.raw)
        # 本機不再有啟動器自己的輪詢；就緒等待在 start_local.ps1（60 次、每次 0.5 秒）。
        self.assertNotIn(b'GEQ 40', self.raw)
        self.assertNotIn(b':wait_local', self.raw)

    def assert_health_exit_code(self, local, upstream, expected):
        code, output, result = self.run_case(
            f'local-{local}-upstream-{upstream}', local=local, upstream=upstream)
        self.assertEqual(code, expected, output)
        # 本機入口無條件呼叫一次 START_TIP.cmd（已在線時由它自行略過啟動）；啟動器自己不查本機 /health。
        self.assertEqual(result['localStartCount'], 1)
        self.assertEqual(result['startTipFirst'], True)
        self.assertEqual(result['localCheckCount'], 1)
        self.assertEqual(result['localHealthHttpCount'], 0)
        self.assertEqual(result['hostRunCount'], 0 if upstream else 1)
        self.assertEqual(result['browserOpenCount'], 1 if local else 0)
        self.assertEqual(result['webBrowserOpenCount'], 1 if upstream else 0)

    def test_no_browser_keeps_services_ready_without_opening_a_window(self):
        code, output, result = self.run_case('僅服務不開視窗', upstream=True, no_browser=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['browserOpenCount'], 0, result)
        self.assertEqual(result['webBrowserOpenCount'], 0, result)
        self.assertEqual(result['localStartCount'], 1, result)

    def test_recovered_local_opens_browser_once(self):
        code, output, result = self.run_case('本機啟動後開畫面', local=False, upstream=True, recover_local=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['localStartCount'], 1, result)
        self.assertEqual(result['browserOpenCount'], 1, result)
        self.assertEqual(result['webBrowserOpenCount'], 1, result)

    def test_cold_no_browser_suppresses_child_and_both_pages(self):
        code, output, result = self.run_case('冷啟動只啟動服務', local=False,
                                            upstream=True, recover_local=True, no_browser=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['localStartCount'], 1, result)
        self.assertEqual(result['browserOpenCount'], 0, result)
        self.assertEqual(result['webBrowserOpenCount'], 0, result)

    def test_web_url_failure_preserves_local_and_reports_web_bit(self):
        code, output, result = self.run_case('Web 網址解析失敗', upstream=True, web_open_fails=True)
        self.assertEqual(code, 2, output)
        self.assertEqual(result['browserOpenCount'], 1, result)
        self.assertEqual(result['webBrowserOpenCount'], 1, result)
        self.assertIn('[WARN]', output)

    def test_both_up_exit_zero(self):
        self.assert_health_exit_code(True, True, 0)

    def test_local_down_exit_one(self):
        self.assert_health_exit_code(False, True, 1)

    def test_web_down_exit_two(self):
        self.assert_health_exit_code(True, False, 2)

    def test_both_down_exit_three(self):
        self.assert_health_exit_code(False, False, 3)

    def test_large_valid_gateway_health_does_not_restart_running_local_or_web(self):
        # 長行溢出後 findstr 會遺失前段已找到的欄位；合法 JSON 的鍵順序不影響健康契約。
        # 以超過實機 145 KiB 的本文保留前段欄位。本機健康已改由受管腳本判定，這裡只驗閘道邊界。
        payload = {'gateway': 'private-web', 'upstream': True, 'diagnostics': 'x' * 200000}
        raw = json.dumps(payload, separators=(',', ':')).encode('ascii')
        self.assertGreater(len(raw), 200000)
        code, output, result = self.run_case('超長合法閘道 health 已在線', upstream=True,
                                           running=True, gateway_payload=payload)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['hostRunCount'], 0, result)
        self.assertEqual(result['taskQueryCount'], 0, result)
        self.assertIn('Local : UP', output)
        self.assertIn('Web   : UP', output)

    def test_large_utf8_gateway_health_does_not_restart_running_local_or_web(self):
        payload = {'gateway': 'private-web', 'upstream': True, 'diagnostics': '合成診斷' * 20000}
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.assertGreater(len(raw), 200000)
        code, output, result = self.run_case('超長 UTF-8 閘道 health 已在線', upstream=True,
                                           running=True, gateway_payload=payload)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['hostRunCount'], 0, result)
        self.assertEqual(result['taskQueryCount'], 0, result)

    def test_local_entry_failure_does_not_block_the_web_side(self):
        # START_TIP.cmd 失敗（例如版本需同步而被拒）時，網站流程仍要繼續，並如實回報本機 DOWN。
        # 網站原本也是停止的：若啟動器因本機失敗而中止，就不會啟動排程工作，這個案例才抓得到。
        code, output, result = self.run_case('本機入口失敗不擋網站', local=False, gateway=False,
                                           upstream=False, running=False, recover=True, tip_fails=True)
        self.assertEqual(code, 1, output)
        self.assertEqual(result['localStartCount'], 1, result)
        self.assertEqual(result['hostRunCount'], 1, result)
        self.assertTrue(result['upstreamReadyAfterRun'], result)
        self.assertEqual(result['browserOpenCount'], 0, result)
        self.assertEqual(result['webBrowserOpenCount'], 1, result)
        self.assertIn('Local : DOWN', output)
        self.assertIn('Web   : UP', output)

    def test_cold_start_calls_the_local_entry_before_any_web_step(self):
        code, output, result = self.run_case('冷啟動順序', local=False, upstream=True, recover_local=True)
        self.assertEqual(code, 0, output)
        self.assertTrue(result['startTipFirst'], result)
        self.assertEqual(result['localCheckCount'], 1, result)
        self.assertEqual(result['localHealthHttpCount'], 0, result)

    def test_stopped_gateway_and_backend_run_host_and_recover(self):
        code, output, result = self.run_case('兩邊停止後恢復', gateway=False,
                                           upstream=False, running=False, recover=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(result['taskQueryCount'], 1)
        self.assertEqual(result['hostRunCount'], 1)
        self.assertTrue(result['upstreamReadyAfterRun'])

    def test_orphan_gateway_task_ready_cannot_be_adopted_by_host(self):
        code, output, result = self.run_case('孤兒 gateway 保持未就緒', gateway=True,
                                           upstream=False, running=False, recover=True)
        self.assertEqual(code, 2, output)
        self.assertEqual(result['taskQueryCount'], 1)
        self.assertEqual(result['hostRunCount'], 1)
        self.assertFalse(result['upstreamReadyAfterRun'])
        self.assertIn('Web   : DOWN', output)

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


@unittest.skipUnless(os.name == 'nt', '驗證啟動器的真 PowerShell 5.1 JSON 健康判定')
class LauncherJsonHealthOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (SOURCE_ROOT / 'START_LOCAL_AND_WEB.cmd').read_bytes().decode('ascii')
        commands = re.findall(r'-Command "([^"]*Invoke-RestMethod[^"]*)"', source)
        cls.commands = {}
        for command in commands:
            if "-Uri 'http://127.0.0.1:18434/gateway/health'" in command:
                cls.commands['gateway'] = command
        if set(cls.commands) != {'gateway'} or len(commands) != 1:
            raise AssertionError('啟動器必須只有閘道一個 JSON 健康判定命令；本機由受管 -CheckOnly 負責')
        cls.engine = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'

    def query(self, side, payload):
        with tempfile.TemporaryDirectory(prefix='st-health-parser-') as temp:
            case = Path(temp)
            filename, flag = 'gateway-response.json', 'gateway-live.flag'
            (case / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            (case / flag).write_bytes(b'1')
            (case / 'gateway-custom.flag').write_bytes(b'1')
            done = subprocess.run([str(self.engine), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
                _HEALTH_HTTP_BOUNDARY + '\n' + self.commands[side]],
                env=dict(os.environ, ST_TEST_FIXTURE=str(case)), stdin=subprocess.DEVNULL,
                capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            uri = 'http://127.0.0.1:18434/gateway/health'
            self.assertEqual((case / 'calls.log').read_text(encoding='utf-8-sig').splitlines(),
                             ['health-http-fixture ' + uri])
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    def test_gateway_requires_boolean_true(self):
        for value, expected in ((True, 0), (False, 1), ('true', 1), (1, 1), (None, 1)):
            with self.subTest(upstream=value):
                code, output = self.query('gateway', {'gateway': 'private-web', 'upstream': value})
                self.assertEqual(code, expected, output)


@unittest.skipUnless(os.name == 'nt', '驗證受管本機腳本的真 PowerShell 5.1 健康判定')
class ManagedLocalHealthContractTests(unittest.TestCase):
    """本機健康判定已由 START_LOCAL_AND_WEB.cmd 的 JSON 查詢，移到 scripts/start_local.ps1 的
    Test-LocalHealth（-CheckOnly 與啟動都使用同一函式）。這裡保留原本「必須是完整字串 SHA」的保護，
    並涵蓋新增的版本、綁定、埠、目錄與 Python 核對。"""

    COMMIT = 'a' * 40

    def check(self, **overrides):
        health = {'status': 'ok', 'runtimeCommit': self.COMMIT, 'bind': '127.0.0.1', 'port': 18432,
                  'baseDir': 'C:\\測試\\current', 'pythonExe': 'C:\\Python\\python.exe'}
        health.update(overrides)
        launcher = str(SOURCE_ROOT / 'scripts/start_local.ps1').replace("'", "''")
        body = json.dumps(health, ensure_ascii=False).replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'\n"
            f". '{launcher}' -FunctionsOnly\n"
            f"$h = '{body}' | ConvertFrom-Json\n"
            "$base='C:\\測試\\current'; $python='C:\\Python\\python.exe'\n"
            f"if (Test-LocalHealth $h $base '{self.COMMIT}' $python) {{ exit 0 }} else {{ exit 1 }}\n")
        with tempfile.TemporaryDirectory(prefix='st-local-health-') as folder:
            path = Path(folder) / '核對.ps1'
            path.write_text(script, encoding='utf-8-sig')
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            done = subprocess.run([str(shell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(path)],
                                  stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    def test_complete_matching_health_is_accepted(self):
        code, output = self.check()
        self.assertEqual(code, 0, output)

    def test_runtime_commit_must_be_the_exact_installed_string(self):
        for value in ('A' * 40, self.COMMIT + '\n', self.COMMIT[:-1], 'fixture', None, 40, ['a']):
            with self.subTest(runtimeCommit=value):
                code, output = self.check(runtimeCommit=value)
                self.assertEqual(code, 1, output)

    def test_status_bind_port_and_paths_must_match(self):
        for field, value in (('status', 'degraded'), ('bind', '0.0.0.0'), ('port', 18433),
                             ('baseDir', 'C:\\其他\\current'), ('pythonExe', 'C:\\Other\\python.exe')):
            with self.subTest(**{field: value}):
                code, output = self.check(**{field: value})
                self.assertEqual(code, 1, output)

@unittest.skipUnless(os.name == 'nt', '驗證 Windows 排程查詢的 PowerShell 語意')
class ScheduledTaskQueryOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (SOURCE_ROOT / 'START_LOCAL_AND_WEB.cmd').read_bytes()
        source = raw.decode('ascii')
        pattern = r'(?im)^[ \t]*(?:powershell(?:\.exe)?|"[^"\r\n]*[\\/]powershell\.exe")[ \t]+[^\r\n]*?-Command[ \t]+"(?P<command>[^"\r\n]+)"'
        matches = [match for match in re.finditer(pattern, source)
                   if 'Get-ScheduledTask' in match.group('command')]
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

    def assert_numeric_state_display(self, state, expected, display):
        for name, engine in self.engines.items():
            with self.subTest(engine=name, state=state, display=display):
                code, output = self.query(engine, state, display)
                self.assertEqual(code, expected, output)

    def test_numeric_running_state_with_english_display(self):
        self.assert_numeric_state_display(4, 0, 'Running')

    def test_numeric_running_state_with_traditional_display(self):
        self.assert_numeric_state_display(4, 0, '執行中')

    def test_numeric_ready_state_with_english_display(self):
        self.assert_numeric_state_display(3, 1, 'Ready')

    def test_numeric_ready_state_with_traditional_display(self):
        self.assert_numeric_state_display(3, 1, '就緒')

    def test_query_failure_is_not_reported_as_running(self):
        for name, engine in self.engines.items():
            with self.subTest(engine=name):
                code, output = self.query(engine, 'throw', '合成查詢失敗')
                self.assertEqual(code, 2, output)



@unittest.skipUnless(os.name == 'nt', '驗證 Windows 原生等待在 stdin 導向時仍有效')
class LauncherNativeWaitTests(unittest.TestCase):
    def test_source_wait_command_ignores_redirected_stdin(self):
        raw = (SOURCE_ROOT / 'START_LOCAL_AND_WEB.cmd').read_bytes()
        source = raw.decode('ascii')
        # 只執行輪詢分支的等待命令，不執行啟動器。舊命令保留在允許清單以驗證失敗。
        commands = re.findall(r'(?im)^(?P<command>[^\r\n]+)\r?\n[ \t]*goto :wait[ \t]*\r?$', source)
        self.assertEqual(len(commands), 1)
        expected = r'"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 3" >nul'
        self.assertIn(commands[0], (expected, 'timeout /t 3 /nobreak >nul'))
        with tempfile.TemporaryDirectory(prefix='st-wait-command-') as temp:
            script = Path(temp) / 'wait-only.cmd'
            script.write_bytes(_crlf('@echo off\n' + commands[0] + '\nexit /b %errorlevel%\n'))
            cmd = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
            command_line = f'"{cmd}" /d /s /c ""{script}""'
            started = time.monotonic()
            done = subprocess.run(command_line, cwd=temp, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=15,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            elapsed = time.monotonic() - started
        output = (done.stdout + done.stderr).decode('utf-8', 'replace')
        self.assertEqual(done.returncode, 0, output)
        self.assertGreaterEqual(elapsed, 2.8, (elapsed, output))

if __name__ == '__main__':
    unittest.main()
