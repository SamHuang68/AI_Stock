"""寫入租約與寫入守衛（單一資料根階段 3a）。

兩半：
1. **legacy 是 no-op**：沒有租約時，守衛不讀、不寫、不檢查參數；匯入相關模組不會取得租約或建立檔案。
2. **已綁定時真的會擋**：租約是程序級全域狀態，所以每個情境都在子行程裡跑（不污染其他測試）；
   跨程序互斥用真的第二個程序驗證，不是模擬。

守衛接在 `atomic_store`（寫入與損毀復原）和 `datastore`（init_db／upsert_bars／merge_source_bars）。
守衛必須早於建立任何目錄或檔案：被拒絕的寫入不能留下痕跡。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'server'
MARK = '@@R@@'
BOOT = f"import sys, os, json\nsys.path.insert(0, {str(SERVER)!r})\n"
HELPERS = textwrap.dedent('''
    out = {}
    def attempt(label, fn):
        try:
            fn()
            out[label] = 'OK'
        except Exception as exc:                       # noqa: BLE001 - 把例外型別回報給測試判斷
            out[label] = 'REFUSED' if type(exc).__name__ == 'StorageOwnershipError' else type(exc).__name__ + ': ' + str(exc)[:200]
    def done():
        print('@@R@@' + json.dumps(out, ensure_ascii=False))
''')


def run_child(body: str, *args: str, timeout: int = 90):
    code = BOOT + HELPERS + textwrap.dedent(body)
    proc = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-c', code, *args], capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=timeout, cwd=tempfile.gettempdir())
    line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith(MARK)), None)
    if line is None:
        raise AssertionError(f'子行程沒有回報結果 rc={proc.returncode}\nstdout={proc.stdout[-800:]}\nstderr={proc.stderr[-1500:]}')
    return json.loads(line[len(MARK):])


class Dirs:
    """root（資料根）、outside（資料根之外）、evil（名字以資料根開頭的兄弟目錄）。"""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='st-rtstore-', ignore_cleanup_errors=True)
        base = Path(self._tmp.name)
        self.root, self.outside = base / 'root', base / 'outside'
        self.evil = base / 'root-evil'
        for d in (self.root, self.outside, self.evil):
            d.mkdir()
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def args(self):
        return str(self.root), str(self.outside), str(self.evil)


class LegacyIsNoop(unittest.TestCase):
    def test_guard_does_nothing_without_a_lease(self):
        spec = importlib.util.spec_from_file_location('runtime_storage_legacy_probe', SERVER / 'runtime_storage.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIsNone(module._lease)
        with tempfile.TemporaryDirectory(prefix='st-rtstore-legacy-') as tmp:
            before = sorted(os.listdir(tmp))
            # 沒有租約時連參數都不檢查：任何東西都放行，且不碰檔案系統。
            for value in (None, '', 123, object(), os.path.join(tmp, 'x', 'y.json'), '/definitely/outside'):
                self.assertIsNone(module.assert_write_allowed(value), repr(value))
            self.assertEqual(sorted(os.listdir(tmp)), before)
        self.assertIsNone(module._lease)

    def test_importing_the_modules_takes_no_lease_and_creates_nothing(self):
        with tempfile.TemporaryDirectory(prefix='st-rtstore-import-', ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / 'root'
            shutil.copytree(SERVER, root / 'server', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'data').mkdir()
            code = (f"import sys, os, json\nsys.path.insert(0, {str(root / 'server')!r})\n"
                    "import runtime_storage, atomic_store, daemon_lock, datastore\n"
                    "print('@@R@@' + json.dumps({'lease': repr(runtime_storage._lease), 'data': sorted(os.listdir(sys.argv[1])),"
                    " 'lockdir': str(daemon_lock.DEFAULT_LOCK_DIR)}))\n")
            proc = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-c', code, str(root / 'data')],
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90, cwd=tmp)
            line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith(MARK)), None)
            self.assertIsNotNone(line, proc.stderr[-1500:])
            result = json.loads(line[len(MARK):])
            self.assertEqual(result['lease'], 'None')
            self.assertEqual(result['data'], [], '匯入模組不應在 data/ 建立任何東西（含 runtime_locks）')
            self.assertEqual(Path(result['lockdir']), root / 'data' / 'runtime_locks')


class Bootstrap(unittest.TestCase):
    def test_root_must_be_absolute_and_exist_and_is_not_created(self):
        with Dirs() as d:
            missing = str(d.root / 'not-there')
            result = run_child('''
                import runtime_storage as rs
                root = sys.argv[1]
                # 讓這個相對路徑「確實存在」：單靠「資料根必須存在」的檢查擋不住它，只有「必須是絕對路徑」的檢查擋得住。
                os.chdir(os.path.dirname(root))
                attempt('relative_existing', lambda: rs.bootstrap_runtime(data_root=os.path.basename(root)))
                attempt('missing', lambda: rs.bootstrap_runtime(data_root=sys.argv[2]))
                out['missing_created'] = os.path.exists(sys.argv[2])
                out['lockdir_created'] = os.path.exists(os.path.join(root, 'runtime_locks'))
                out['lease_after_failures'] = repr(rs._lease)
                done()
            ''', str(d.root), missing)
            self.assertEqual(result['relative_existing'], 'REFUSED', '相對路徑即使存在也必須拒絕')
            self.assertEqual(result['missing'], 'REFUSED')
            self.assertFalse(result['missing_created'], '拒絕自動建立空的資料根')
            self.assertFalse(result['lockdir_created'], '被拒絕的 bootstrap 不能留下 runtime_locks')
            self.assertEqual(result['lease_after_failures'], 'None', '失敗的 bootstrap 不能讓守衛進入已綁定狀態')

    def test_bootstrap_writes_only_the_lease_file(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                rs.bootstrap_runtime(data_root=sys.argv[1])
                out['top'] = sorted(os.listdir(sys.argv[1]))
                out['locks'] = sorted(os.listdir(os.path.join(sys.argv[1], 'runtime_locks')))
                done()
            ''', *d.args())
            self.assertEqual(result['top'], ['runtime_locks'])
            self.assertEqual(result['locks'], ['writer.lock'])

    def test_same_root_is_idempotent_and_a_second_root_is_refused(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                first = rs.bootstrap_runtime(data_root=sys.argv[1])
                out['same'] = rs.bootstrap_runtime(data_root=sys.argv[1]) is first
                attempt('other_root', lambda: rs.bootstrap_runtime(data_root=sys.argv[2]))
                done()
            ''', *d.args())
            self.assertTrue(result['same'])
            self.assertEqual(result['other_root'], 'REFUSED', '一個程序只能綁定一個資料根')

    def test_a_second_process_cannot_take_the_lease_until_the_first_exits(self):
        with Dirs() as d:
            holder_code = BOOT + textwrap.dedent('''
                import runtime_storage as rs
                rs.bootstrap_runtime(data_root=sys.argv[1])
                print('READY', flush=True)
                sys.stdin.readline()
            ''')
            holder = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', '-B', '-c', holder_code, str(d.root)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8', errors='replace', cwd=tempfile.gettempdir())
            watchdog = threading.Timer(60, holder.kill)
            watchdog.start()
            try:
                self.assertEqual(holder.stdout.readline().strip(), 'READY', holder.stderr.read() if holder.poll() is not None else '')
                contender = run_child('''
                    import runtime_storage as rs
                    attempt('contend', lambda: rs.bootstrap_runtime(data_root=sys.argv[1]))
                    done()
                ''', str(d.root))
                self.assertEqual(contender['contend'], 'REFUSED', '租約被另一個程序持有時必須拒絕，不等待')
                holder.stdin.write('\n')
                holder.stdin.flush()
                holder.wait(timeout=30)
                after = run_child('''
                    import runtime_storage as rs
                    attempt('take', lambda: rs.bootstrap_runtime(data_root=sys.argv[1]))
                    done()
                ''', str(d.root))
                self.assertEqual(after['take'], 'OK', '持有者結束後租約必須可再取得')
            finally:
                watchdog.cancel()
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=10)
                for stream in (holder.stdin, holder.stdout, holder.stderr):
                    try:
                        stream.close()
                    except OSError:
                        pass


class GuardWhenBound(unittest.TestCase):
    def test_inside_allowed_outside_refused_and_refusal_leaves_no_trace(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store
                root, outside, evil = sys.argv[1], sys.argv[2], sys.argv[3]
                rs.bootstrap_runtime(data_root=root)
                attempt('inside_guard', lambda: rs.assert_write_allowed(os.path.join(root, 'a', 'x.json')))
                attempt('outside_guard', lambda: rs.assert_write_allowed(os.path.join(outside, 'x.json')))
                attempt('prefix_sibling', lambda: rs.assert_write_allowed(os.path.join(evil, 'x.json')))
                attempt('lease_file', lambda: rs.assert_write_allowed(os.path.join(root, 'runtime_locks', 'writer.lock')))
                attempt('atomic_inside', lambda: atomic_store.atomic_write_json(os.path.join(root, 'sub', 'x.json'), {'a': 1}))
                attempt('atomic_outside', lambda: atomic_store.atomic_write_json(os.path.join(outside, 'newdir', 'x.json'), {'a': 1}))
                attempt('atomic_evil', lambda: atomic_store.atomic_write_text(os.path.join(evil, 'newdir', 'x.txt'), 'x'))
                out['outside_has_newdir'] = os.path.exists(os.path.join(outside, 'newdir'))
                out['evil_has_newdir'] = os.path.exists(os.path.join(evil, 'newdir'))
                out['inside_content'] = json.load(open(os.path.join(root, 'sub', 'x.json'), encoding='utf-8'))
                if os.name == 'nt':
                    attempt('inside_other_case', lambda: rs.assert_write_allowed(os.path.join(root.upper(), 'a', 'x.json')))
                done()
            ''', *d.args())
            self.assertEqual(result['inside_guard'], 'OK')
            self.assertEqual(result['outside_guard'], 'REFUSED')
            self.assertEqual(result['prefix_sibling'], 'REFUSED', '名字以資料根開頭的兄弟目錄不是資料根之內')
            self.assertEqual(result['lease_file'], 'REFUSED', '租約檔由 bootstrap 管理')
            self.assertEqual(result['atomic_inside'], 'OK')
            self.assertEqual(result['atomic_outside'], 'REFUSED')
            self.assertEqual(result['atomic_evil'], 'REFUSED')
            self.assertFalse(result['outside_has_newdir'], '守衛必須早於建立目錄：被拒絕的寫入不能留下痕跡')
            self.assertFalse(result['evil_has_newdir'])
            self.assertEqual(result['inside_content'], {'a': 1})
            if os.name == 'nt':
                self.assertEqual(result['inside_other_case'], 'OK', 'Windows 路徑大小寫不分')

    def test_a_closed_lease_stays_bound_and_refuses_everything(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                lease = rs.bootstrap_runtime(data_root=sys.argv[1])
                lease.close()
                attempt('write_after_close', lambda: rs.assert_write_allowed(os.path.join(sys.argv[1], 'x.json')))
                attempt('rebind_same_root', lambda: rs.bootstrap_runtime(data_root=sys.argv[1]))
                done()
            ''', *d.args())
            self.assertEqual(result['write_after_close'], 'REFUSED', '釋放租約後不能退回 legacy 的放行')
            self.assertEqual(result['rebind_same_root'], 'REFUSED')

    def test_a_forked_child_does_not_inherit_the_lease(self):
        # Windows 沒有 fork：以「租約登記的 pid 不是目前程序」模擬（守衛判斷的就是這個條件）。
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                lease = rs.bootstrap_runtime(data_root=sys.argv[1])
                lease.pid += 1
                attempt('foreign_pid', lambda: rs.assert_write_allowed(os.path.join(sys.argv[1], 'x.json')))
                lease.pid -= 1
                done()
            ''', *d.args())
            self.assertEqual(result['foreign_pid'], 'REFUSED')

    def test_a_symlink_inside_the_root_cannot_escape_it(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                root, outside = sys.argv[1], sys.argv[2]
                rs.bootstrap_runtime(data_root=root)
                import subprocess
                link = os.path.join(root, 'link')
                try:
                    os.symlink(outside, link, target_is_directory=True)
                    out['kind'] = 'symlink'
                except (OSError, NotImplementedError):
                    # Windows 一般使用者不能建符號連結，但可以建目錄接合點（junction），realpath 同樣會解開它。
                    made = os.name == 'nt' and subprocess.run(['cmd', '/c', 'mklink', '/J', link, outside],
                                                              capture_output=True).returncode == 0
                    out['kind'] = 'junction' if made else 'UNAVAILABLE'
                if out['kind'] != 'UNAVAILABLE':
                    attempt('via_link', lambda: rs.assert_write_allowed(os.path.join(link, 'x.json')))
                done()
            ''', *d.args())
            if result['kind'] == 'UNAVAILABLE':
                self.skipTest('這個環境不能建立符號連結或目錄接合點')
            self.assertEqual(result['via_link'], 'REFUSED', f"經由 {result['kind']} 逃出資料根必須被擋")

    def test_load_json_repair_is_a_guarded_write(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store
                root, outside = sys.argv[1], sys.argv[2]
                def seed(folder):
                    primary = os.path.join(folder, 'c.json')
                    open(primary, 'w', encoding='utf-8').write('{broken')
                    open(primary + '.bak', 'w', encoding='utf-8').write(json.dumps({'ok': 1}))
                    return primary
                outside_file, inside_file = seed(outside), seed(root)
                rs.bootstrap_runtime(data_root=root)
                attempt('repair_outside', lambda: atomic_store.load_json(outside_file, default=None))
                out['outside_untouched'] = open(outside_file, encoding='utf-8').read() == '{broken'
                out['outside_no_quarantine'] = not any('.corrupt-' in n for n in os.listdir(outside))
                out['inside_value'] = atomic_store.load_json(inside_file, default=None)
                out['inside_quarantined'] = any('.corrupt-' in n for n in os.listdir(root))
                done()
            ''', *d.args())
            self.assertEqual(result['repair_outside'], 'REFUSED', '資料根之外的損毀復原會改名並重寫檔案，必須被擋')
            self.assertTrue(result['outside_untouched'])
            self.assertTrue(result['outside_no_quarantine'])
            self.assertEqual(result['inside_value'], {'ok': 1}, '資料根之內的復原照常運作')
            self.assertTrue(result['inside_quarantined'])

    def test_datastore_write_entry_points_are_guarded(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, datastore
                root, outside = sys.argv[1], sys.argv[2]
                rs.bootstrap_runtime(data_root=root)
                outside_db = os.path.join(outside, 'sub', 'market.db')
                attempt('init_outside', lambda: datastore.init_db(outside_db))
                attempt('upsert_outside', lambda: datastore.upsert_bars('2330', 'TW', [], source='Yahoo Finance', path=outside_db))
                datastore.DB_PATH = outside_db
                attempt('merge_outside', lambda: datastore.merge_source_bars('2330', 'TW', [], 'Yahoo Finance'))
                out['outside_has_sub'] = os.path.exists(os.path.join(outside, 'sub'))
                inside_db = os.path.join(root, 'market.db')
                attempt('init_inside', lambda: datastore.init_db(inside_db))
                out['inside_db_exists'] = os.path.isfile(inside_db)
                done()
            ''', *d.args())
            self.assertEqual(result['init_outside'], 'REFUSED')
            self.assertEqual(result['upsert_outside'], 'REFUSED')
            self.assertEqual(result['merge_outside'], 'REFUSED')
            self.assertFalse(result['outside_has_sub'], '守衛必須早於 get_conn 建立資料夾')
            self.assertEqual(result['init_inside'], 'OK')
            self.assertTrue(result['inside_db_exists'])


if __name__ == '__main__':
    unittest.main()
