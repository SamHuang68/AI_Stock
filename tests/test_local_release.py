"""本機發布只使用暫存 fixture；不接觸正式服務、資料或網路。"""
import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import local_release as local
import private_web_release as release


def write(path, value='資料'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def stage(source, commit):
    tree = source / 'releases' / commit[:12]
    for relative in release.REQUIRED_RELEASE_FILES:
        write(tree / relative)
    for relative in ('scripts/local_release.py', 'scripts/start_local.ps1',
                     'scripts/private_web_release.py', 'server/daemon_lock.py'):
        (tree / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, tree / relative)
    write(tree / 'data/public.csv', '公開種子')
    manifest = {'commit': commit, 'releaseId': commit[:12], 'tests': 'passed',
                'contentSha256': release._content_hashes(tree),
                'seedSha256': release._content_hashes(tree / 'data', include_runtime=True),
                'managedTopLevel': sorted(p.name for p in tree.iterdir() if p.name not in release.PRESERVE_NAMES)}
    local.write_json(tree / local.MANIFEST, manifest)
    local.write_json(source / 'current' / local.MANIFEST, manifest)
    return tree, manifest


class LocalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Windows CI 的 TEMP 可能使用 8.3 短路徑；與產品端採相同實體路徑。
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / '正式安裝'
        self.original = self.root / '原始工作樹'
        self.install = self.root / '本機安裝'
        self.commit = 'a' * 40
        self.tree, self.manifest = stage(self.source, self.commit)
        write(self.original / 'server/server.py')
        write(self.original / 'stock_terminal_v2.html', '使用者未提交的 HTML')
        write(self.original / 'data/private.json', '{"value":0}')
        with closing(sqlite3.connect(self.original / 'data/market.db')) as conn, conn:
            conn.execute('CREATE TABLE bars(symbol TEXT, close REAL, volume INTEGER)')
            conn.execute('PRAGMA user_version=3')
            conn.execute('PRAGMA application_id=42')
            conn.executemany('INSERT INTO bars VALUES(?,?,?)', [('2330', 100.5, None), ('0050', 0, 0)])
        self.config = {'originalCheckout': str(self.original), 'sourceInstallRoot': str(self.source),
                       'python': sys.executable, 'port': 18432, 'host': '127.0.0.1'}
        self.stopped = patch.object(local, 'assert_stopped')
        self.stopped.start()

    def tearDown(self):
        self.stopped.stop()
        self.tmp.cleanup()

    def install_first(self):
        return local.sync_install(self.install, release, self.config)

    def test_正式SHA選擇不使用較新的stage目錄(self):
        newer, _ = stage(self.source, 'f' * 40)
        local.write_json(self.source / 'current' / local.MANIFEST, self.manifest)
        chosen, found = local.select_stage(self.source, release)
        self.assertEqual(chosen, self.tree)
        self.assertNotEqual(chosen, newer)
        self.assertEqual(found['commit'], self.commit)

    def test_篡改略過測試與錯SHA均拒絕(self):
        for case in ('篡改', '略過測試', '錯SHA'):
            with self.subTest(case=case):
                original_manifest = dict(self.manifest)
                if case == '篡改':
                    path = self.tree / 'server/server.py'
                    old = path.read_bytes()
                    path.write_bytes(b'tampered')
                elif case == '略過測試':
                    original_manifest['tests'] = 'skipped'
                    local.write_json(self.tree / local.MANIFEST, original_manifest)
                else:
                    original_manifest['commit'] = 'b' * 40
                    local.write_json(self.tree / local.MANIFEST, original_manifest)
                with self.assertRaises((ValueError, RuntimeError)):
                    local.select_stage(self.source, release)
                if case == '篡改':
                    path.write_bytes(old)
                local.write_json(self.tree / local.MANIFEST, self.manifest)
        self.assertFalse(self.install.exists())

    def test_首次複製保留原工作樹且逐表驗證備份(self):
        before = {p.relative_to(self.original).as_posix(): local.digest(p)
                  for p in self.original.rglob('*') if p.is_file()}
        result = self.install_first()
        after = {p.relative_to(self.original).as_posix(): local.digest(p)
                 for p in self.original.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(result['changed'])
        receipt = local.read_json(Path(result['backup']) / '備份收據.json')
        self.assertEqual(receipt['status'], '已驗證')
        self.assertEqual(receipt['targetCommit'], self.commit)
        self.assertEqual(receipt['files']['market.db']['tables']['bars']['rows'], 2)
        self.assertEqual(receipt['files']['market.db']['userVersion'], 3)
        self.assertEqual(receipt['files']['market.db']['applicationId'], 42)
        with closing(sqlite3.connect(self.install / 'current/data/market.db')) as conn, conn:
            self.assertEqual(conn.execute('SELECT volume FROM bars ORDER BY symbol').fetchall(), [(0,), (None,)])
        self.assertEqual((self.install / 'current/data/private.json').read_text(), '{"value":0}')
        self.assertEqual((self.install / 'current/data/public.csv').read_text(encoding='utf-8'), '公開種子')
        self.assertTrue((self.install / 'start_local.ps1').exists())
        self.assertFalse(local.status(self.install, release)['needsSync'])
        with self.assertRaisesRegex(ValueError, '已存在'):
            self.install_first()

    def test_升版保留新增本機資料及日誌且不複製正式DB(self):
        self.install_first()
        current = self.install / 'current'
        write(current / 'data/private.json', '本機升版前資料')
        write(current / 'logs/user.log', '本機紀錄')
        write(self.source / 'current/data/private.json', '不可以使用的正式資料')
        with closing(sqlite3.connect(current / 'data/market.db')) as conn, conn:
            conn.execute("INSERT INTO bars VALUES('NEW', 9, 3)")
        _, new_manifest = stage(self.source, 'b' * 40)
        result = local.sync_install(self.install, release)
        self.assertEqual(result['commit'], new_manifest['commit'])
        self.assertEqual((current / 'data/private.json').read_text(encoding='utf-8'), '本機升版前資料')
        self.assertEqual((current / 'logs/user.log').read_text(encoding='utf-8'), '本機紀錄')
        receipt = local.read_json(Path(result['backup']) / '備份收據.json')
        self.assertEqual(receipt['commit'], self.commit)
        self.assertEqual(receipt['files']['market.db']['tables']['bars']['rows'], 3)
        self.assertFalse(local.sync_install(self.install, release)['changed'])

    def test_匯入複製失敗不建立current或修改來源(self):
        with patch.object(local.shutil, 'copytree', side_effect=OSError('fixture 複製失敗')):
            with self.assertRaises(OSError):
                self.install_first()
        self.assertFalse((self.install / 'current').exists())
        self.assertFalse((self.install / CONFIG_NAME).exists())
        self.assertTrue((self.original / 'data/market.db').exists())

    def test_初始資料複製失敗不留下半份current(self):
        real_copy = shutil.copytree
        def fail_data(source, target, *args, **kwargs):
            if Path(source).name == 'data' and Path(source).parent.name.startswith('資料備份-'):
                raise OSError('fixture 初始資料複製失敗')
            return real_copy(source, target, *args, **kwargs)
        with patch.object(local.shutil, 'copytree', side_effect=fail_data):
            with self.assertRaises(OSError):
                self.install_first()
        self.assertFalse((self.install / 'current').exists())
        self.assertFalse((self.install / CONFIG_NAME).exists())
        self.assertEqual(len(list((self.install / 'backups').glob('資料備份-*'))), 1)

    def test_升版交易失敗保留原版本及資料(self):
        self.install_first()
        current = self.install / 'current'
        before = local.digest(current / 'data/market.db')
        stage(self.source, 'c' * 40)
        with patch.object(release, '_switch_tree', side_effect=OSError('fixture 切換失敗')):
            with self.assertRaises(OSError):
                local.sync_install(self.install, release)
        self.assertEqual(local.read_json(current / local.MANIFEST)['commit'], self.commit)
        self.assertEqual(local.digest(current / 'data/market.db'), before)

    def test_備份WAL含已提交值並保留NULL與零(self):
        db = self.original / 'data/market.db'
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute("INSERT INTO bars VALUES('WAL', 12, 20)")
            conn.commit()
            backup = local.backup_data(db.parent, self.install, self.commit, '測試 WAL')
            with closing(sqlite3.connect(backup / 'data/market.db')) as copied:
                self.assertEqual(copied.execute("SELECT volume FROM bars WHERE symbol='WAL'").fetchone(), (20,))
            report = local.read_json(backup / '備份收據.json')
            self.assertIn('market.db-wal', report['sqliteSidecars'])

    def test_非DB複製內容變動中止並記錄失敗(self):
        real_copy = shutil.copy2
        def corrupt(source, target, *args, **kwargs):
            result = real_copy(source, target, *args, **kwargs)
            if Path(source).name == 'private.json':
                Path(target).write_text('不同內容', encoding='utf-8')
            return result
        with patch.object(local.shutil, 'copy2', side_effect=corrupt):
            with self.assertRaises(RuntimeError):
                local.backup_data(self.original / 'data', self.install, self.commit, '測試失敗')
        report = local.read_json(next((self.install / 'backups').glob('*/備份收據.json')))
        self.assertEqual(report['status'], '失敗')

    def test_關閉WAL後唯讀建立邊檔仍完成逐表驗證(self):
        for name in ('market.db', '歷史.bak'):
            with self.subTest(name=name):
                db = self.original / 'data' / name
                if name != 'market.db':
                    shutil.copy2(self.original / 'data/market.db', db)
                with closing(sqlite3.connect(db)) as connection:
                    connection.execute('PRAGMA journal_mode=WAL')
                self.assertFalse(Path(str(db) + '-wal').exists())
                backup = local.backup_data(db.parent, self.install, self.commit, '測試已關閉 WAL')
                report = local.read_json(backup / '備份收據.json')
                self.assertEqual(report['status'], '已驗證')
                self.assertEqual(report['files'][name]['tables']['bars']['rows'], 2)
                self.assertEqual(report['sqliteSidecarChanges']['created'],
                                 sorted([name + '-shm', name + '-wal']))
                self.assertEqual(report['sqliteSidecarChanges']['removed'], [])
                self.assertFalse((backup / 'data' / (name + '-wal')).exists())

    def test_無WAL資料庫不產生邊檔例外(self):
        backup = local.backup_data(self.original / 'data', self.install, self.commit, '測試無 WAL')
        report = local.read_json(backup / '備份收據.json')
        self.assertEqual(report['sqliteSidecars'], [])
        self.assertEqual(report['sqliteSidecarChanges'], {'created': [], 'removed': []})

    def test_WAL關閉清理邊檔仍保留已提交快照(self):
        db = self.original / 'data/market.db'
        connection = sqlite3.connect(db)
        self.addCleanup(connection.close)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute("INSERT INTO bars VALUES('WAL', 12, 20)")
        connection.commit()
        real_backup = local.sqlite_backup
        def close_after_backup(source, target):
            result = real_backup(source, target)
            connection.close()
            self.assertFalse(Path(str(db) + '-wal').exists())
            return result
        with patch.object(local, 'sqlite_backup', side_effect=close_after_backup):
            backup = local.backup_data(db.parent, self.install, self.commit, '測試 WAL 清理')
        report = local.read_json(backup / '備份收據.json')
        self.assertEqual(report['files']['market.db']['tables']['bars']['rows'], 3)
        self.assertEqual(report['status'], '已驗證')

    def test_未知邊檔新增移除與改寫均拒絕(self):
        for operation in ('新增', '移除', '改寫'):
            with self.subTest(operation=operation):
                unknown = self.original / 'data/orphan.db-wal'
                unknown.unlink(missing_ok=True)
                if operation != '新增':
                    write(unknown, '原資料')
                real_recheck = local.recheck_source
                def change_before_recheck(source, files, records):
                    if operation == '移除':
                        unknown.unlink()
                    else:
                        write(unknown, '變更後資料')
                    return real_recheck(source, files, records)
                with patch.object(local, 'recheck_source', side_effect=change_before_recheck):
                    with self.assertRaisesRegex(RuntimeError, '檔案清單改變|來源檔案已改變'):
                        local.backup_data(self.original / 'data', self.install, self.commit, operation)
                unknown.unlink(missing_ok=True)

    def test_來源再核對期間新增未知邊檔仍拒絕(self):
        real_signature = local.database_signature
        calls = 0
        def add_late(connection):
            nonlocal calls
            result = real_signature(connection)
            calls += 1
            if calls == 3:  # 備份來源、目的地、整批來源再核對。
                write(self.original / 'data/orphan.db-shm')
            return result
        with patch.object(local, 'database_signature', side_effect=add_late):
            with self.assertRaisesRegex(RuntimeError, '來源再核對期間檔案清單改變'):
                local.backup_data(self.original / 'data', self.install, self.commit, '測試延後新增')

    def test_WAL真實資料變更仍拒絕且不建立安裝(self):
        db = self.original / 'data/market.db'
        with closing(sqlite3.connect(db)) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            real_backup = local.sqlite_backup
            def change_after_backup(source, target):
                result = real_backup(source, target)
                connection.execute("UPDATE bars SET volume=999 WHERE symbol='2330'")
                connection.commit()
                return result
            with patch.object(local, 'sqlite_backup', side_effect=change_after_backup):
                with self.assertRaisesRegex(RuntimeError, '來源 SQLite 已改變'):
                    self.install_first()
        receipt = local.read_json(next((self.install / 'backups').glob('*/備份收據.json')))
        self.assertEqual(receipt['status'], '失敗')
        self.assertNotIn('sourceRecheckedAt', receipt)
        for name in ('current', local.CONFIG, local.SETUP_PENDING):
            self.assertFalse((self.install / name).exists())

    def test_SQLite備份失敗保留收據且不建立安裝(self):
        with patch.object(local, 'sqlite_backup', side_effect=sqlite3.DatabaseError('fixture 備份失敗')):
            with self.assertRaises(sqlite3.DatabaseError):
                self.install_first()
        receipt = local.read_json(next((self.install / 'backups').glob('*/備份收據.json')))
        self.assertEqual(receipt['status'], '失敗')
        self.assertIn('fixture 備份失敗', receipt['error'])
        for name in ('current', local.CONFIG, local.SETUP_PENDING):
            self.assertFalse((self.install / name).exists())

    def test_DB再核對後其他檔案核對期間新WAL寫入仍拒絕(self):
        real_digest = local.digest
        real_recheck = local.recheck_source
        connections = []
        def mutate_during_final_digest(path):
            if Path(path) == self.original / 'data/private.json':
                connection = sqlite3.connect(self.original / 'data/market.db')
                connections.append(connection)
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute("INSERT INTO bars VALUES('LATE', 12, 20)")
                connection.commit()
            return real_digest(path)
        def recheck_with_late_writer(source, files, records):
            with patch.object(local, 'digest', side_effect=mutate_during_final_digest):
                return real_recheck(source, files, records)
        try:
            with patch.object(local, 'recheck_source', side_effect=recheck_with_late_writer):
                with self.assertRaisesRegex(RuntimeError, 'SQLite 內容再核對後邊檔清單改變'):
                    local.backup_data(self.original / 'data', self.install, self.commit, '測試核對後新 WAL 寫入')
        finally:
            for connection in connections:
                connection.close()
        receipt = local.read_json(next((self.install / 'backups').glob('*/備份收據.json')))
        self.assertEqual(receipt['status'], '失敗')

    def test_promote後CONFIG寫入失敗可用相同setup修復(self):
        original_digest = local.digest(self.original / 'data/market.db')
        real_write = local.write_json
        def fail_config(path, payload):
            if Path(path).name == local.CONFIG:
                raise OSError('fixture 設定寫入失敗')
            return real_write(path, payload)
        with patch.object(local, 'write_json', side_effect=fail_config):
            with self.assertRaises(OSError):
                self.install_first()
        self.assertTrue((self.install / 'current' / local.MANIFEST).exists())
        self.assertTrue((self.install / local.SETUP_PENDING).exists())
        self.assertFalse((self.install / local.CONFIG).exists())
        with self.assertRaisesRegex(ValueError, '尚未完成'):
            local.status(self.install, release)
        before = local.digest(self.install / 'current/data/market.db')
        with patch.object(release, '_promote_release', side_effect=AssertionError('不應再次切換程式')):
            recovered = self.install_first()
        self.assertTrue(recovered['setupRecovered'])
        self.assertFalse((self.install / local.SETUP_PENDING).exists())
        self.assertEqual(local.digest(self.install / 'current/data/market.db'), before)
        self.assertEqual(local.digest(self.original / 'data/market.db'), original_digest)

    def test_bootstrap寫入失敗可修復且拒絕不同原工作樹(self):
        with patch.object(local, 'install_bootstrap', side_effect=OSError('fixture 入口寫入失敗')):
            with self.assertRaises(OSError):
                self.install_first()
        self.assertTrue((self.install / local.SETUP_PENDING).exists())
        other = self.root / '另一工作樹'
        write(other / 'server/server.py')
        with self.assertRaisesRegex(ValueError, '相同路徑'):
            local.sync_install(self.install, release, {**self.config, 'originalCheckout': str(other)})
        recovered = self.install_first()
        self.assertTrue(recovered['setupRecovered'])
        self.assertTrue((self.install / 'start_local.ps1').exists())

    def test_首次promote失敗可保留已複製資料重入(self):
        with patch.object(release, '_promote_release', side_effect=OSError('fixture 發布中斷')):
            with self.assertRaises(OSError):
                self.install_first()
        self.assertFalse((self.install / 'current' / local.MANIFEST).exists())
        self.assertTrue((self.install / local.SETUP_PENDING).exists())
        write(self.install / 'current/data/recovery.json', '修復時保留')
        recovered = self.install_first()
        self.assertEqual(recovered['commit'], self.commit)
        self.assertEqual((self.install / 'current/data/recovery.json').read_text(encoding='utf-8'), '修復時保留')

    def test_整批完成後DB再次變更必須拒絕(self):
        real_backup = local.sqlite_backup
        def changed_later(source, target):
            copied = real_backup(source, target)
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.execute("UPDATE bars SET volume=999 WHERE symbol='2330'")
            return copied
        with patch.object(local, 'sqlite_backup', side_effect=changed_later):
            with self.assertRaisesRegex(RuntimeError, '來源 SQLite 已改變'):
                local.backup_data(self.original / 'data', self.install, self.commit, '測試背景 DB 寫入')
        receipt = local.read_json(next((self.install / 'backups').glob('*/備份收據.json')))
        self.assertEqual(receipt['status'], '失敗')
        self.assertNotIn('sourceRecheckedAt', receipt)

    def test_後續檔案複製時改寫已備份檔案必須拒絕(self):
        earlier = self.original / 'data/aaa.json'
        write(earlier, '原值')
        real_copy = local.shutil.copy2
        def changed_later(source, target, *args, **kwargs):
            copied = real_copy(source, target, *args, **kwargs)
            if Path(source).name == 'private.json':
                write(earlier, '背景工作的新值')
            return copied
        with patch.object(local.shutil, 'copy2', side_effect=changed_later):
            with self.assertRaisesRegex(RuntimeError, '來源檔案已改變'):
                local.backup_data(self.original / 'data', self.install, self.commit, '測試背景檔案寫入')

    def test_遇連結目錄必須在下降列舉前拒絕(self):
        linked = self.original / 'data/junction_fixture'
        write(linked / '不可列舉.txt')
        real_link = local.is_link
        real_scan = local.os.scandir
        observed = []
        def scan(path):
            observed.append(Path(path))
            if Path(path) == linked:
                raise AssertionError('不應下降列舉 junction 內容')
            return real_scan(path)
        with patch.object(local, 'is_link', side_effect=lambda path: Path(path) == linked or real_link(path)), \
             patch.object(local.os, 'scandir', side_effect=scan):
            with self.assertRaisesRegex(ValueError, '不接受連結'):
                local.backup_data(self.original / 'data', self.install, self.commit, '測試連結')
        self.assertNotIn(linked, observed)

    def test_不同安裝目錄不得互相包含(self):
        with self.assertRaises(ValueError):
            local.validate_roots(self.original / 'nested', self.original, self.source)

    def test_本機管理程式被修改時保留變更且不更新(self):
        self.install_first()
        script = self.install / 'current/server/server.py'
        script.write_text('本機修改', encoding='utf-8')
        stage(self.source, 'd' * 40)
        with self.assertRaisesRegex(ValueError, '程式內容已變更'):
            local.status(self.install, release)
        with self.assertRaisesRegex(ValueError, '程式內容已變更'):
            local.sync_install(self.install, release)
        self.assertEqual(script.read_text(encoding='utf-8'), '本機修改')

    def test_未包含新啟動器的舊正式版在status即拒絕(self):
        self.install_first()
        tree, manifest = stage(self.source, 'e' * 40)
        (tree / 'scripts/start_local.ps1').unlink()
        del manifest['contentSha256']['scripts/start_local.ps1']
        local.write_json(tree / local.MANIFEST, manifest)
        with self.assertRaisesRegex(ValueError, '尚未包含'):
            local.status(self.install, release)

    def test_已占用埠Python入口拒絕且不終止程序(self):
        self.stopped.stop()
        with patch.object(local.socket.socket, 'bind', side_effect=OSError('fixture listener')):
            with self.assertRaisesRegex(RuntimeError, '仍有程序使用'):
                local.assert_stopped()
        self.stopped.start()

    def test_穩定Python入口可讀current的helper且不新增pyc(self):
        self.install_first()
        process = subprocess.run([sys.executable, '-B', str(self.install / 'local_release.py'),
                                  '--install-root', str(self.install), 'status'],
                                 capture_output=True, text=True, encoding='utf-8', timeout=30,
                                 env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(json.loads(process.stdout)['needsSync'])
        self.assertFalse(list((self.install / 'current').rglob('*.pyc')))


CONFIG_NAME = local.CONFIG


@unittest.skipUnless(os.name == 'nt', '此測試核對 Windows PowerShell 啟動器')
class LocalPowerShellTests(unittest.TestCase):
    def run_ps(self, script, env=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '核對.ps1'
            path.write_text(script, encoding='utf-8-sig')
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            process = subprocess.run([str(shell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(path)],
                                     capture_output=True, timeout=30, env=env)
            self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))

    def test_PID重用不同命令外部listener均拒絕(self):
        launcher = str(ROOT / 'scripts/start_local.ps1').replace("'", "''")
        self.run_ps(f"""
$ErrorActionPreference='Stop'
. '{launcher}' -FunctionsOnly
$base='C:\\測試\\current'; $python='C:\\Python\\python.exe'
$proc=[pscustomobject]@{{ProcessId=123; CreationDate=[datetime]'2026-10-03T01:00:00Z'; ExecutablePath=$python; CommandLine='"C:\\Python\\python.exe" -B -u "C:\\測試\\current\\server\\server.py"'}}
$receipt=[pscustomobject]@{{pid=123;createdAt=(Get-LocalCreation $proc);commandLine=$proc.CommandLine;baseDir=$base}}
$started=[pscustomobject]@{{Id=123;StartTime=$proc.CreationDate}}
if (-not (Test-NewLocalProcess $started $proc)) {{throw '新程序建立時間未通過'}}
$started.StartTime=$started.StartTime.AddSeconds(-1)
if (Test-NewLocalProcess $started $proc) {{throw '新程序 PID 重用未拒絕'}}
if (-not (Test-ManagedLocalIdentity $proc $receipt $base $python)) {{throw '正確身分未通過'}}
$proc.CreationDate=$proc.CreationDate.AddSeconds(1)
if (Test-ManagedLocalIdentity $proc $receipt $base $python) {{throw 'PID 重用未拒絕'}}
$proc.CreationDate=$proc.CreationDate.AddSeconds(-1)
$proc.CommandLine='python.exe -c "print(123)"'
if (Test-ManagedLocalIdentity $proc $receipt $base $python) {{throw '不同命令未拒絕'}}
$proc.CommandLine=$receipt.commandLine
$blocked=$false
try {{ Assert-LocalListeners @([pscustomobject]@{{LocalAddress='127.0.0.1';LocalPort=18432;OwningProcess=999}}) $proc $receipt $base $python }} catch {{ $blocked=$true }}
if (-not $blocked) {{throw '外部 listener 未拒絕'}}
$blocked=$false
try {{ Assert-LocalListeners @([pscustomobject]@{{LocalAddress='0.0.0.0';LocalPort=18432;OwningProcess=123}}) $proc $receipt $base $python }} catch {{ $blocked=$true }}
if (-not $blocked) {{throw '公開綁定未拒絕'}}
$health=[pscustomobject]@{{status='ok';runtimeCommit='abc';bind='127.0.0.1';port=18432;baseDir=$base;pythonExe=$python}}
if (-not (Test-LocalHealth $health $base 'abc' $python)) {{throw '健康核對錯誤'}}
if (Test-LocalHealth $health $base 'def' $python) {{throw '錯誤 SHA 未拒絕'}}
""")

    def test_登記checkout提前轉接且保留dirtyHTML(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout = root / '工作樹'
            (checkout / 'scripts').mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts/go.ps1', checkout / 'scripts/go.ps1')
            write(checkout / 'build_v2.py', 'raise RuntimeError("不應執行建置")')
            write(checkout / 'stock_terminal_v2.html', '未提交修改')
            managed = root / 'appdata/StockTerminalLocal'
            managed.mkdir(parents=True)
            local.write_json(managed / CONFIG_NAME, {'originalCheckout': str(checkout)})
            (managed / 'start_local.ps1').write_text("param([string]$InstallRoot)\n[IO.File]::WriteAllText((Join-Path $InstallRoot '轉接成功.txt'),'ok')\nexit 0\n", encoding='utf-8-sig')
            command = str(checkout / 'scripts/go.ps1').replace("'", "''")
            self.run_ps(f"& '{command}'\nexit $LASTEXITCODE", env=dict(os.environ, LOCALAPPDATA=str(root / 'appdata')))
            self.assertTrue((managed / '轉接成功.txt').is_file())
            self.assertEqual((checkout / 'stock_terminal_v2.html').read_text(encoding='utf-8'), '未提交修改')


if __name__ == '__main__':
    unittest.main()
