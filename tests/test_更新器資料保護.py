"""在暫存本機 Git remote 驗證更新器；不觸及使用者 checkout 或網路。"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('pwsh') or shutil.which('powershell')


@unittest.skipUnless(POWERSHELL and shutil.which('git'), '需要 PowerShell 與 Git 的隔離整合環境')
class 更新器資料保護測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_COUNT='0', GIT_TERMINAL_PROMPT='0')
        template = self.root / '空範本'
        template.mkdir()
        self.env['GIT_TEMPLATE_DIR'] = str(template)
        self.remote = self.root / 'remote.git'
        self.seed = self.root / 'seed'
        self.checkout = self.root / 'checkout'
        self.seed.mkdir()
        self.git(self.root, 'init', '--bare', str(self.remote))
        self.git(self.seed, 'init', '-b', 'main')
        for key, value in [('user.name', '測試'), ('user.email', 'fixture@example.com'),
                           ('core.autocrlf', 'false')]:
            self.git(self.seed, 'config', key, value)
        (self.seed / 'scripts').mkdir()
        (self.seed / 'data').mkdir()
        shutil.copy2(ROOT / 'scripts/go.ps1', self.seed / 'scripts/go.ps1')
        (self.seed / 'TIP_BRANCH').write_text('main\n', encoding='utf-8')
        (self.seed / 'build_v2.py').write_text('# 隔離測試\n', encoding='utf-8')
        (self.seed / 'app.txt').write_text('原版', encoding='utf-8')
        (self.seed / 'data/行情.csv').write_bytes(b'original\n')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', '初始測試版本')
        self.git(self.seed, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.seed, 'push', 'origin', 'main')
        self.git(self.root, 'clone', '-b', 'main', str(self.remote), str(self.checkout))
        self.git(self.checkout, 'config', 'core.autocrlf', 'false')

    def git(self, cwd, *argv):
        return subprocess.run(['git', *argv], cwd=cwd, check=True, capture_output=True,
                              text=True, encoding='utf-8', timeout=30, env=self.env).stdout.strip()

    def incoming(self, relative, value):
        (self.seed / relative).write_text(value, encoding='utf-8')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', '遠端測試更新')
        self.git(self.seed, 'push', 'origin', 'main')

    def update(self):
        return subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive',
                               '-ExecutionPolicy', 'Bypass', '-File',
                               str(self.checkout / 'scripts/go.ps1'), '-UpdateOnly'],
                              cwd=self.checkout, capture_output=True, timeout=45,
                              env=self.env,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_行情變更可隨程式快轉且位元組及索引保留(self):
        market = self.checkout / 'data/行情.csv'
        market.write_bytes(b'local-price\r\n')
        self.git(self.checkout, 'add', 'data/行情.csv')
        staged_before = self.git(self.checkout, 'diff', '--cached', '--binary')
        stash_before = self.git(self.checkout, 'stash', 'list')
        self.incoming('app.txt', '新版')
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        self.assertEqual(market.read_bytes(), b'local-price\r\n')
        self.assertEqual(self.git(self.checkout, 'diff', '--cached', '--binary'), staged_before)
        self.assertEqual(self.git(self.checkout, 'stash', 'list'), stash_before)
        self.assertEqual((self.checkout / 'app.txt').read_text(encoding='utf-8'), '新版')

    def test_行情衝突會在變更HEAD前阻擋(self):
        market = self.checkout / 'data/行情.csv'
        market.write_bytes(b'local-price\n')
        before = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.incoming('data/行情.csv', '遠端行情')
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), before)
        self.assertEqual(market.read_bytes(), b'local-price\n')

    def test_程式變更仍阻擋且不建立暫存(self):
        (self.checkout / 'app.txt').write_text('本機未提交程式', encoding='utf-8')
        before = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.incoming('app.txt', '遠端程式')
        self.assertNotEqual(self.update().returncode, 0)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), before)
        self.assertEqual((self.checkout / 'app.txt').read_text(encoding='utf-8'), '本機未提交程式')
        self.assertEqual(self.git(self.checkout, 'stash', 'list'), '')

    def test_新增本機CSV與SQLite不因更新遺失(self):
        (self.checkout / 'data/本機.sqlite3').write_bytes(b'local-db\x00\x01')
        (self.checkout / 'data/測試backup.json').write_bytes(b'{"local":true}')
        self.incoming('app.txt', '新版')
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        self.assertEqual((self.checkout / 'data/本機.sqlite3').read_bytes(), b'local-db\x00\x01')
        self.assertEqual((self.checkout / 'data/測試backup.json').read_bytes(), b'{"local":true}')
