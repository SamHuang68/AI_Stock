from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _powershell_engines():
    return {name: path for name in ('powershell', 'pwsh') if (path := shutil.which(name))}


_FUNCTION_EXTENTS = r'''
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:ST_TEST_SOURCE, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw '來源 AST 解析失敗。' }
$functions = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
@($functions | ForEach-Object { @{ name = $_.Name; start = $_.Extent.StartOffset; end = $_.Extent.EndOffset } }) | ConvertTo-Json -Compress
'''


_FAKE_BOUNDARIES = r'''
function Write-TestTrace([string]$Line) { Add-Content -LiteralPath $env:ST_TEST_TRACE -Value $Line -Encoding ASCII }
function git {
  $global:LASTEXITCODE = 0
  $gitArgs = $args -join ' '
  if ($gitArgs -match 'status --porcelain') { Write-TestTrace 'GIT-STATUS'; return }
  if ($gitArgs -match '^fetch ') { Write-TestTrace 'GIT-FETCH'; return }
  if ($gitArgs -eq 'branch --show-current') { return 'main' }
  if ($gitArgs -match '^merge --ff-only ') {
    [IO.File]::Copy($env:ST_TEST_NEW_LAUNCHER, $PSCommandPath, $true)
    Write-TestTrace 'GIT-MERGE'
    return
  }
  if ($gitArgs -match '^rev-parse') { return ('a' * 40) }
  throw ('未預期的 Git fixture 命令：' + $gitArgs)
}
function Start-Process {
  param([string]$FilePath, [string]$WorkingDirectory, [string]$WindowStyle, [switch]$PassThru)
  Write-TestTrace 'START-FIXTURE'
  return [pscustomobject]@{ Id = 555; StartTime = [datetime]::UtcNow }
}
'''


def _instrument_go_functions(source: str, extents: list[dict]) -> str:
    """AST 邊界替換外部副作用；實際 -Pull／UpdateOnly／RebuildOnly 分支保持原樣。"""
    replacements = {
        'Resolve-StockPython': r'''function Resolve-StockPython {
  Write-TestTrace ('RESOLVER-V1|pull=' + [bool]$Pull + '|worktree=' + [bool]$Worktree + '|rebuild=' + [bool]$RebuildOnly)
  return $env:ST_TEST_PYTHON
}''',
        'Assert-TipHtml': "function Assert-TipHtml { Write-TestTrace 'HTML-FIXTURE' }",
        'Get-PortListenerPids': "function Get-PortListenerPids([int]$PortNum) { return @() }",
        'Stop-OwnedPortListeners': r'''function Stop-OwnedPortListeners([int]$PortNum, [string]$ReceiptPath, [string]$OwnerRoot) { Write-TestTrace 'STOP-FIXTURE' }''',
        'Wait-TipServer': r'''function Wait-TipServer {
  Write-TestTrace 'WAIT-FIXTURE'
  if ($env:ST_TEST_CHILD_EXIT -ne '0') { exit ([int]$env:ST_TEST_CHILD_EXIT) }
}''',
        'Assert-ListenerMatchesPin': "function Assert-ListenerMatchesPin { Write-TestTrace 'PIN-FIXTURE' }",
        'Write-DevServerReceipt': r'''function Write-DevServerReceipt {
  param([int]$PortNum, [string]$ReceiptPath, [string]$OwnerRoot, [int]$ExpectedParent, [int64]$ExpectedParentTicks, [string]$ExpectedPython, [string]$ExpectedBasePython, [string]$ExpectedLauncher)
  Write-TestTrace 'RECEIPT-FIXTURE'
}''',
        'Assert-IndexIsTip': "function Assert-IndexIsTip { Write-TestTrace 'INDEX-FIXTURE' }",
    }
    selected = [item for item in extents if item['name'] in replacements]
    if len(selected) != len(replacements):
        raise AssertionError('fixture 的函式邊界不完整，拒絕執行原始外部動作')
    # PowerShell AST 位移以 UTF-16 code unit 計算，避免非 BMP 字元導致錯位。
    utf16 = source.encode('utf-16-le')
    for item in sorted(selected, key=lambda item: item['start'], reverse=True):
        start, end = 2 * item['start'], 2 * item['end']
        utf16 = utf16[:start] + replacements[item['name']].encode('utf-16-le') + utf16[end:]
    changed = utf16.decode('utf-16-le')
    changed, count = re.subn(r'(?m)^Write-Banner\r?$',
                            lambda _: _FAKE_BOUNDARIES + '\nWrite-Banner', changed, count=1)
    if count != 1:
        raise AssertionError('找不到副作用替身注入邊界')
    return changed


@unittest.skipIf(not _powershell_engines(), '找不到 PowerShell')
class PullUpdateOfflineBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROOT / 'scripts' / 'go.ps1'
        cls.original = cls.source.read_bytes().decode('utf-8-sig')
        engine = next(iter(_powershell_engines().values()))
        done = subprocess.run([engine, '-NoProfile', '-Command', _FUNCTION_EXTENTS],
                              env=dict(os.environ, ST_TEST_SOURCE=str(cls.source)),
                              capture_output=True, timeout=30)
        if done.returncode:
            raise AssertionError(done.stderr.decode('utf-8', 'replace'))
        cls.extents = json.loads(done.stdout.decode('utf-8-sig'))
        cls.old_source = _instrument_go_functions(cls.original, cls.extents)
        cls.new_source = cls.old_source.replace('RESOLVER-V1|', 'RESOLVER-V2|')
        cls.fixture = tempfile.TemporaryDirectory(prefix='st-pull-fixtures-')
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.run_root = Path(cls.fixture.name)

    def run_go(self, engine_name, engine, flags, child_exit=0):
        case = Path(tempfile.mkdtemp(prefix='pull-case-', dir=self.run_root))
        self.addCleanup(self.remove_case, case)
        repo = case / 'repo'
        (repo / 'scripts').mkdir(parents=True)
        launcher = repo / 'scripts' / 'go.ps1'
        incoming = case / 'new-go.ps1'
        launcher.write_text(self.old_source, encoding='utf-8-sig', newline='')
        incoming.write_text(self.new_source, encoding='utf-8-sig', newline='')
        (repo / 'TIP_BRANCH').write_text('main', encoding='ascii')
        (repo / 'build_v2.py').write_text(
            "import os,pathlib\n"
            "with pathlib.Path(os.environ['ST_TEST_TRACE']).open('a',encoding='ascii') as f: f.write('BUILD-FIXTURE\\n')\n",
            encoding='ascii')
        trace_path = case / 'calls.log'
        env = dict(os.environ, LOCALAPPDATA=str(case / 'localappdata'),
                   ST_TEST_NEW_LAUNCHER=str(incoming), ST_TEST_TRACE=str(trace_path),
                   ST_TEST_PYTHON=sys.executable, ST_TEST_CHILD_EXIT=str(child_exit),
                   PYTHONDONTWRITEBYTECODE='1')
        args = [engine, '-NoProfile']
        if os.name == 'nt':
            args += ['-ExecutionPolicy', 'Bypass']
        args += ['-File', str(launcher), *flags]
        done = subprocess.run(args, cwd=repo, env=env, capture_output=True, timeout=30)
        output = (done.stdout + done.stderr).decode('utf-8', 'replace')
        trace = trace_path.read_text(encoding='ascii').splitlines() if trace_path.exists() else []
        return done.returncode, output, trace

    def remove_case(self, case):
        resolved = case.resolve()
        run_root = self.run_root.resolve()
        if resolved == run_root or not resolved.is_relative_to(run_root):
            raise AssertionError(f'拒絕清理不屬於 fixture 的路徑：{resolved}')
        shutil.rmtree(resolved)

    def assert_single_update(self, trace):
        self.assertEqual(trace.count('GIT-FETCH'), 1, trace)
        self.assertEqual(trace.count('GIT-MERGE'), 1, trace)
        self.assertFalse(any(line.startswith('RESOLVER-V1|') for line in trace), trace)

    def test_pull_reenters_updated_resolver_and_fetches_once(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, output, trace = self.run_go(name, engine, ['-Pull'])
                self.assertEqual(code, 0, output)
                self.assert_single_update(trace)
                self.assertEqual(trace.count('RESOLVER-V2|pull=False|worktree=True|rebuild=False'), 1, trace)
                self.assertEqual(trace.count('BUILD-FIXTURE'), 1, trace)
                self.assertEqual(trace.count('START-FIXTURE'), 2, trace)

    def test_update_only_never_resolves_builds_or_launches(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, output, trace = self.run_go(name, engine, ['-UpdateOnly'])
                self.assertEqual(code, 0, output)
                self.assert_single_update(trace)
                for prefix in ('RESOLVER-', 'BUILD-', 'STOP-', 'START-'):
                    self.assertFalse(any(line.startswith(prefix) for line in trace), trace)

    def test_pull_preserves_rebuild_only_without_launch(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, output, trace = self.run_go(name, engine, ['-Pull', '-RebuildOnly'])
                self.assertEqual(code, 0, output)
                self.assert_single_update(trace)
                self.assertEqual(trace.count('RESOLVER-V2|pull=False|worktree=True|rebuild=True'), 1, trace)
                self.assertEqual(trace.count('BUILD-FIXTURE'), 1, trace)
                self.assertNotIn('STOP-FIXTURE', trace)
                self.assertNotIn('START-FIXTURE', trace)

    def test_pull_returns_reentered_script_exit_code(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, output, trace = self.run_go(name, engine, ['-Pull'], child_exit=23)
                self.assertEqual(code, 23, output)
                self.assert_single_update(trace)
                self.assertEqual(trace.count('WAIT-FIXTURE'), 1, trace)
                self.assertEqual(trace.count('START-FIXTURE'), 1, trace)



def _launcher_ast_guard_engines():
    return {name: path for name in ('powershell', 'pwsh') if (path := shutil.which(name))}


@unittest.skipIf(not _launcher_ast_guard_engines(), '找不到 PowerShell')
class LauncherAstGuardOfflineTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'scripts' / 'go.ps1').read_bytes().decode('utf-8-sig').replace('\r\n', '\n')
        start = self.source.index('function Assert-LauncherBehavior')
        end = self.source.index('\nfunction ', start + 10)
        self.guard = self.source[start:end]
        self.temp = tempfile.TemporaryDirectory(prefix='st-launcher-ast-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.driver = self.folder / 'driver.ps1'
        self.driver.write_text(self.guard + "\nAssert-LauncherBehavior -Path $env:ST_TEST_CANDIDATE\nWrite-Host 'AST-GUARD-OK'\n", encoding='utf-8-sig')

    def check_source(self, engine, source):
        candidate = self.folder / 'candidate.ps1'
        candidate.write_text(source, encoding='utf-8-sig')
        args = [engine, '-NoProfile']
        if os.name == 'nt':
            args += ['-ExecutionPolicy', 'Bypass']
        args += ['-File', str(self.driver)]
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        done = subprocess.run(args, env=dict(os.environ, ST_TEST_CANDIDATE=str(candidate)),
                              capture_output=True, timeout=15, **kwargs)
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    def test_current_owned_guard_is_accepted_and_comments_are_ignored(self):
        candidate = self.source + '\n# Stop-PortListeners 及 Stop-Process 僅為歷史說明。\n# Start-Process sample -RedirectStandardOutput sample.log\n'
        for name, engine in _launcher_ast_guard_engines().items():
            with self.subTest(engine=name):
                code, output = self.check_source(engine, candidate)
                self.assertEqual(code, 0, output)
                self.assertIn('AST-GUARD-OK', output)

    def test_legacy_port_killing_function_and_caller_are_rejected(self):
        start = self.source.index('function Stop-OwnedPortListeners')
        end = self.source.index('\nfunction ', start + 10)
        old = '''function Stop-PortListeners([int]$PortNum) {
  foreach ($procId in @(Get-PortListenerPids $PortNum)) {
    Stop-Process -Id $procId -Force
  }
}'''
        candidate = (self.source[:start] + old + self.source[end:]).replace('Stop-OwnedPortListeners -PortNum', 'Stop-PortListeners -PortNum')
        for name, engine in _launcher_ast_guard_engines().items():
            with self.subTest(engine=name):
                code, output = self.check_source(engine, candidate)
                self.assertNotEqual(code, 0, output)
                self.assertNotIn('AST-GUARD-OK', output)

    def test_unowned_stop_process_outside_receipt_guard_is_rejected(self):
        # candidate 只被 AST 讀取，絕不執行這個合成 Stop-Process。
        candidate = self.source + '\nif ($env:ST_TEST_SYNTHETIC_STOP) { Stop-Process -Id 999999 -Force }\n'
        for name, engine in _launcher_ast_guard_engines().items():
            with self.subTest(engine=name):
                code, output = self.check_source(engine, candidate)
                self.assertNotEqual(code, 0, output)
                self.assertNotIn('AST-GUARD-OK', output)

    def test_taskkill_commands_are_rejected(self):
        for command in ('taskkill', 'taskkill.exe'):
            candidate = self.source + '\nif ($env:ST_TEST_SYNTHETIC_STOP) { ' + command + ' /PID 999999 /F }\n'
            for name, engine in _launcher_ast_guard_engines().items():
                with self.subTest(engine=name, command=command):
                    code, output = self.check_source(engine, candidate)
                    self.assertNotEqual(code, 0, output)
                    self.assertNotIn('AST-GUARD-OK', output)

if __name__ == '__main__':
    unittest.main()
