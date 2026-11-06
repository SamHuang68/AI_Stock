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
    def make_link(link, target, is_dir):
        # 回傳 'symlink'／'junction'／None（這個環境建不出來）。Windows 一般使用者建不了符號連結，
        # 但目錄接合點（junction）不需要權限，realpath 同樣會解開它；檔案沒有 junction 可用。
        import subprocess
        try:
            os.symlink(target, link, target_is_directory=is_dir)
            return 'symlink'
        except (OSError, NotImplementedError):
            if is_dir and os.name == 'nt' and subprocess.run(['cmd', '/c', 'mklink', '/J', link, target],
                                                             capture_output=True).returncode == 0:
                return 'junction'
            return None
    def fake_posix_realpath(link, target):
        # 讓 os.path.realpath 照 POSIX 規則走路徑（先跟著目錄連結走、再處理 `..`），假裝 link 是指向 target 的目錄連結；
        # 不依賴作業系統能不能建立連結，也不依賴它處理 `..` 的語意。回傳還原函式。
        real = os.path.realpath
        def parts_of(path):
            drive, rest = os.path.splitdrive(path)
            return drive, [x for x in rest.replace(os.sep, '/').split('/') if x]
        target_parts = parts_of(target)[1]
        def pretend(path, *args, **kwargs):
            drive, parts = parts_of(os.fspath(path))
            walked = []
            for part in parts:
                if part == '.':
                    continue
                if part == '..':
                    if walked:
                        walked.pop()            # 在「已解開連結的前綴」上取上一層
                    continue
                walked.append(part)
                if os.path.normcase(drive + os.sep + os.sep.join(walked)) == os.path.normcase(link):
                    walked = list(target_parts)  # 走進連結：換成它指向的位置
            return drive + os.sep + os.sep.join(walked)
        os.path.realpath = pretend
        def restore():
            os.path.realpath = real
        return restore
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
        self.assertIsNone(module.current_lease())
        with tempfile.TemporaryDirectory(prefix='st-rtstore-legacy-') as tmp:
            before = sorted(os.listdir(tmp))
            # 沒有租約時連參數都不檢查：任何東西都放行，且不碰檔案系統。
            for value in (None, '', 123, object(), os.path.join(tmp, 'x', 'y.json'), '/definitely/outside'):
                self.assertIsNone(module.assert_write_allowed(value), repr(value))
            self.assertEqual(sorted(os.listdir(tmp)), before)
        self.assertIsNone(module.current_lease())

    def test_importing_the_modules_takes_no_lease_and_creates_nothing(self):
        with tempfile.TemporaryDirectory(prefix='st-rtstore-import-', ignore_cleanup_errors=True) as tmp:
            # resolve()：CI 的暫存目錄可能是 8.3 短檔名（使用者資料夾名稱被縮成 `RUNNER~1` 的形式），而子行程裡
            # daemon_lock 的 ROOT 是 Path(__file__).resolve() 的長檔名；兩邊都用 resolve 後的形式才能逐字比較。
            root = Path(tmp).resolve() / 'root'
            shutil.copytree(SERVER, root / 'server', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'data').mkdir()
            code = (f"import sys, os, json\nsys.path.insert(0, {str(root / 'server')!r})\n"
                    "import runtime_storage, atomic_store, daemon_lock, datastore\n"
                    "print('@@R@@' + json.dumps({'lease': repr(runtime_storage.current_lease()), 'data': sorted(os.listdir(sys.argv[1])),"
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
                out['lease_after_failures'] = repr(rs.current_lease())
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


class ReplacingADirectoryEntryLandsWhereTheEntryLives(unittest.TestCase):
    """`atomic_store` 在目標所在目錄建暫存檔再 `os.replace`：被取代的是目錄項目（連結本身），不是連結指向的檔案。"""

    def test_an_outside_link_pointing_inside_is_refused_without_needing_os_symlink_support(self):
        # 不依賴作業系統能不能建立符號連結：假裝 outside/link.json 是指向 root/inside.json 的連結。
        # 沒有檢查「解開後的父目錄＋檔名」時，守衛只看到終點在資料根內而放行，atomic_write 就會在資料根外建檔。
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store
                root, outside = sys.argv[1], sys.argv[2]
                inside_file = os.path.join(root, 'inside.json')
                open(inside_file, 'w', encoding='utf-8').write('{"v": 1}')
                link = os.path.join(outside, 'link.json')
                rs.bootstrap_runtime(data_root=root)
                real = os.path.realpath
                def pretend(path, *args, **kwargs):
                    if os.path.abspath(os.fspath(path)) == os.path.abspath(link):
                        return real(inside_file)
                    return real(path, *args, **kwargs)
                os.path.realpath = pretend
                try:
                    attempt('guard_via_link', lambda: rs.assert_write_allowed(link))
                    attempt('atomic_via_link', lambda: atomic_store.atomic_write_text(link, 'x'))
                finally:
                    os.path.realpath = real
                out['outside_entries'] = sorted(os.listdir(outside))
                out['inside_content'] = open(inside_file, encoding='utf-8').read()
                done()
            ''', *d.args())
            self.assertEqual(result['guard_via_link'], 'REFUSED')
            self.assertEqual(result['atomic_via_link'], 'REFUSED')
            self.assertEqual(result['outside_entries'], [], '被拒絕的寫入不能在資料根之外留下檔案')
            self.assertEqual(result['inside_content'], '{"v": 1}')

    def test_a_real_file_symlink_outside_pointing_inside_is_not_replaced(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store
                root, outside = sys.argv[1], sys.argv[2]
                inside_file = os.path.join(root, 'inside.json')
                open(inside_file, 'w', encoding='utf-8').write('{"v": 1}')
                link = os.path.join(outside, 'link.json')
                out['kind'] = make_link(link, inside_file, False) or 'UNAVAILABLE'
                if out['kind'] != 'UNAVAILABLE':
                    rs.bootstrap_runtime(data_root=root)
                    attempt('atomic_via_link', lambda: atomic_store.atomic_write_text(link, 'x'))
                    out['still_a_link'] = os.path.islink(link)
                    out['inside_content'] = open(inside_file, encoding='utf-8').read()
                done()
            ''', *d.args())
            if result['kind'] == 'UNAVAILABLE':
                self.skipTest('這個環境不能建立檔案符號連結（Windows 一般使用者沒有權限）；上一項用模擬方式涵蓋同一個判斷')
            self.assertEqual(result['atomic_via_link'], 'REFUSED')
            self.assertTrue(result['still_a_link'], '連結本身不能被取代成一般檔案')
            self.assertEqual(result['inside_content'], '{"v": 1}')


class DotDotFollowsTheLinkNotTheText(unittest.TestCase):
    """POSIX 先跟著目錄連結走、再處理 `..`：`<連結>/../x` 落在連結指向處的上一層。字串式收縮 `..` 會看錯位置。"""

    def test_guard_verdict_agrees_with_where_the_os_really_writes(self):
        # 以作業系統實際的落點為準，不預設答案：POSIX 會落在連結指向處（資料根之外），Windows 以字串收縮 `..`
        # 而落在資料根內；守衛的判斷必須與實際落點一致。Windows 本機只能驗證後者，前者由 Linux CI 驗證。
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store
                root, outside = sys.argv[1], sys.argv[2]
                sub = os.path.join(outside, 'sub')
                os.mkdir(sub)
                link = os.path.join(root, 'link')
                out['kind'] = make_link(link, sub, True) or 'UNAVAILABLE'
                if out['kind'] != 'UNAVAILABLE':
                    # 還沒綁定：用一個探針看作業系統實際把 <連結>/../probe 放在哪。
                    open(os.path.join(link, '..', 'probe.txt'), 'w', encoding='utf-8').close()
                    out['probe_in_outside'] = os.path.exists(os.path.join(outside, 'probe.txt'))
                    out['probe_in_root'] = os.path.exists(os.path.join(root, 'probe.txt'))
                    for where in (outside, root):
                        if os.path.exists(os.path.join(where, 'probe.txt')):
                            os.remove(os.path.join(where, 'probe.txt'))
                    rs.bootstrap_runtime(data_root=root)
                    escaping = os.path.join(link, '..', 'x.json')
                    attempt('guard', lambda: rs.assert_write_allowed(escaping))
                    attempt('atomic', lambda: atomic_store.atomic_write_text(escaping, 'x'))
                    out['outside_entries'] = sorted(os.listdir(outside))
                done()
            ''', *d.args())
            if result['kind'] == 'UNAVAILABLE':
                self.skipTest('這個環境不能建立目錄符號連結或目錄接合點')
            self.assertTrue(result['probe_in_outside'] != result['probe_in_root'], '探針必須恰好落在其中一處')
            if result['probe_in_outside']:
                self.assertEqual(result['guard'], 'REFUSED', '作業系統會把它寫到資料根之外，守衛必須擋下')
                self.assertEqual(result['atomic'], 'REFUSED')
                self.assertEqual(result['outside_entries'], ['sub'], '被拒絕的寫入不能在資料根之外留下檔案')
            else:
                self.assertEqual(result['guard'], 'OK', '作業系統會把它寫在資料根之內，守衛不應該誤擋')

    def test_dotdot_after_a_directory_link_is_resolved_after_the_link_even_without_os_support(self):
        # 不依賴作業系統能不能建立連結、也不依賴它的 `..` 語意：用一個照 POSIX 規則走路徑的 realpath 替身，
        # 假裝 root/link 是指向 outside/sub 的目錄連結。先 abspath 的寫法會在替身看到路徑之前就把 `..` 收縮掉。
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store
                real = os.path.realpath
                root, outside = real(sys.argv[1]), real(sys.argv[2])
                sub = os.path.join(outside, 'sub')
                link = os.path.join(root, 'link')
                rs.bootstrap_runtime(data_root=root)
                restore = fake_posix_realpath(link, sub)
                try:
                    attempt('dotdot_after_link', lambda: rs.assert_write_allowed(os.path.join(link, '..', 'x.json')))
                    attempt('atomic_dotdot_after_link', lambda: atomic_store.atomic_write_text(os.path.join(link, '..', 'x.json'), 'x'))
                    attempt('ends_with_dotdot', lambda: rs.assert_write_allowed(os.path.join(link, '..')))
                    attempt('inside_through_link', lambda: rs.assert_write_allowed(os.path.join(link, 'x.json')))
                    attempt('plain_dotdot_inside', lambda: rs.assert_write_allowed(os.path.join(root, 'plain', '..', 'ok.json')))
                finally:
                    restore()
                out['outside_entries'] = sorted(os.listdir(outside))
                done()
            ''', *d.args())
            self.assertEqual(result['dotdot_after_link'], 'REFUSED', '<連結>/../x 實際落在連結指向處的上一層（資料根之外）')
            self.assertEqual(result['atomic_dotdot_after_link'], 'REFUSED')
            self.assertEqual(result['ends_with_dotdot'], 'REFUSED')
            self.assertEqual(result['inside_through_link'], 'REFUSED', '連結本身指向資料根之外，經由它寫入也不行')
            self.assertEqual(result['plain_dotdot_inside'], 'OK', '沒有連結的 `..` 收縮後仍在資料根內，不能誤擋')
            self.assertEqual(result['outside_entries'], [], '被拒絕的寫入不能在資料根之外留下檔案')

    def test_a_path_whose_two_readings_disagree_is_refused_and_leaves_no_trace(self):
        # 路徑有兩種讀法：作業系統的（先跟著連結走、再處理 `..`）與寫入端常用的 abspath（先收縮 `..`）。
        # root/link 指向 root/d1/d2（兩層深、仍在根內）：`root/link/../../outside/sub/x.db` 在 POSIX 實際落在 root/outside/...（根內），
        # 字串式收縮卻落在資料根旁邊的 outside/...（根外）；datastore.get_conn 的 makedirs(dirname(abspath(...))) 就是後者。
        # Windows 兩種讀法一致（都在根外），所以本機一樣會拒絕；兩種讀法真的不一致的 POSIX 由 Linux CI 驗證，本機由下一項替身涵蓋。
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store, datastore
                root, outside = sys.argv[1], sys.argv[2]
                deep = os.path.join(root, 'd1', 'd2')
                os.makedirs(deep)
                link = os.path.join(root, 'link')
                out['kind'] = make_link(link, deep, True) or 'UNAVAILABLE'
                if out['kind'] != 'UNAVAILABLE':
                    rs.bootstrap_runtime(data_root=root)
                    tricky = os.path.join(link, '..', '..', 'outside', 'sub', 'x.db')
                    attempt('guard', lambda: rs.assert_write_allowed(tricky))
                    attempt('atomic', lambda: atomic_store.atomic_write_text(tricky, 'x'))
                    attempt('init_db', lambda: datastore.init_db(tricky))
                    out['outside_entries'] = sorted(os.listdir(outside))
                    out['root_entries'] = sorted(os.listdir(root))
                done()
            ''', *d.args())
            if result['kind'] == 'UNAVAILABLE':
                self.skipTest('這個環境不能建立目錄符號連結或目錄接合點')
            self.assertEqual(result['guard'], 'REFUSED')
            self.assertEqual(result['atomic'], 'REFUSED')
            self.assertEqual(result['init_db'], 'REFUSED')
            self.assertEqual(result['outside_entries'], [], '被拒絕的寫入不能在資料根之外建立目錄或暫存檔')
            self.assertNotIn('outside', result['root_entries'], '也不能在資料根之內留下痕跡')

    def test_both_readings_of_a_path_must_stay_inside_even_without_os_support(self):
        # 同上，但不依賴作業系統能不能建立連結：用照 POSIX 規則走路徑的 realpath 替身，假裝 root/link 是指向 root/d1/d2 的目錄連結。
        # 只看作業系統讀法時（替身的結果在根內）會放行，寫入端的 abspath 卻會在資料根旁邊建立目錄。
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs, atomic_store, datastore
                real = os.path.realpath
                root, outside = real(sys.argv[1]), real(sys.argv[2])
                os.makedirs(os.path.join(root, 'd1', 'd2'))
                link = os.path.join(root, 'link')
                rs.bootstrap_runtime(data_root=root)
                restore = fake_posix_realpath(link, os.path.join(root, 'd1', 'd2'))
                try:
                    tricky = os.path.join(link, '..', '..', 'outside', 'sub', 'x.db')
                    attempt('guard', lambda: rs.assert_write_allowed(tricky))
                    attempt('atomic', lambda: atomic_store.atomic_write_text(tricky, 'x'))
                    attempt('init_db', lambda: datastore.init_db(tricky))
                    attempt('one_level_up_is_fine', lambda: rs.assert_write_allowed(os.path.join(link, '..', 'ok.json')))
                    attempt('plain_dotdot_is_fine', lambda: rs.assert_write_allowed(os.path.join(root, 'plain', '..', 'ok.json')))
                finally:
                    restore()
                out['outside_entries'] = sorted(os.listdir(outside))
                done()
            ''', *d.args())
            self.assertEqual(result['guard'], 'REFUSED', '字串式讀法落在資料根之外')
            self.assertEqual(result['atomic'], 'REFUSED')
            self.assertEqual(result['init_db'], 'REFUSED')
            self.assertEqual(result['one_level_up_is_fine'], 'OK', '兩種讀法都在資料根內，不能誤擋')
            self.assertEqual(result['plain_dotdot_is_fine'], 'OK')
            self.assertEqual(result['outside_entries'], [], '被拒絕的寫入不能在資料根之外留下目錄')


class BootstrapValidatesBeforeLocking(unittest.TestCase):
    def test_a_lock_directory_linking_outside_is_refused_before_anything_is_created(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                root, outside = sys.argv[1], sys.argv[2]
                out['kind'] = make_link(os.path.join(root, 'runtime_locks'), outside, True) or 'UNAVAILABLE'
                if out['kind'] != 'UNAVAILABLE':
                    attempt('bootstrap', lambda: rs.bootstrap_runtime(data_root=root))
                    out['outside_entries'] = sorted(os.listdir(outside))
                    out['lease'] = repr(rs.current_lease())
                done()
            ''', *d.args())
            if result['kind'] == 'UNAVAILABLE':
                self.skipTest('這個環境不能建立符號連結或目錄接合點')
            self.assertEqual(result['bootstrap'], 'REFUSED')
            self.assertEqual(result['outside_entries'], [], '先驗證再取鎖：被拒絕時資料根之外不能多出 writer.lock')
            self.assertEqual(result['lease'], 'None', '被拒絕的 bootstrap 不能讓守衛進入已綁定狀態')

    def test_a_lock_file_symlink_pointing_outside_is_refused_and_not_written_through(self):
        with Dirs() as d:
            result = run_child('''
                import runtime_storage as rs
                root, outside = sys.argv[1], sys.argv[2]
                os.makedirs(os.path.join(root, 'runtime_locks'))
                victim = os.path.join(outside, 'victim.lock')
                open(victim, 'wb').close()
                out['kind'] = make_link(os.path.join(root, 'runtime_locks', 'writer.lock'), victim, False) or 'UNAVAILABLE'
                if out['kind'] != 'UNAVAILABLE':
                    attempt('bootstrap', lambda: rs.bootstrap_runtime(data_root=root))
                    out['victim_size'] = os.path.getsize(victim)     # acquire_daemon_lock 會對空檔寫入 1 個位元組
                    out['lease'] = repr(rs.current_lease())
                done()
            ''', *d.args())
            if result['kind'] == 'UNAVAILABLE':
                self.skipTest('這個環境不能建立檔案符號連結（Windows 一般使用者沒有權限）')
            self.assertEqual(result['bootstrap'], 'REFUSED')
            self.assertEqual(result['victim_size'], 0, '不能經由連結寫進資料根之外的檔案')
            self.assertEqual(result['lease'], 'None')


class SharedRegistryAcrossImportNames(unittest.TestCase):
    """`server/` 的模組可以頂層匯入（`import runtime_storage`），也可以當套件成員匯入（`server.runtime_storage`），
    同一個程序可能兩種都有（server.py 刻意讓自己同時是模組與套件）。租約必須是程序級的，不是各份模組各一份。"""

    def test_a_lease_taken_through_one_name_binds_the_guards_of_the_other(self):
        with Dirs() as d:
            result = run_child('''
                import types
                # 與 server/server.py 相同的技巧：只有 __path__ 的假 server 套件，不必匯入整個應用程式。
                package = types.ModuleType('server')
                package.__path__ = [sys.argv[4]]
                sys.modules['server'] = package
                import server.runtime_storage as pkg_rs
                import server.atomic_store as pkg_atomic
                import runtime_storage as top_rs
                import atomic_store as top_atomic
                root, outside, evil = sys.argv[1], sys.argv[2], sys.argv[3]
                out['distinct_module_objects'] = pkg_rs is not top_rs and pkg_atomic is not top_atomic
                out['same_error_class'] = pkg_rs.StorageOwnershipError is top_rs.StorageOwnershipError
                lease = pkg_rs.bootstrap_runtime(data_root=root)
                out['top_sees_the_lease'] = top_rs.current_lease() is lease
                attempt('top_guard_outside', lambda: top_rs.assert_write_allowed(os.path.join(outside, 'x.json')))
                attempt('top_atomic_outside', lambda: top_atomic.atomic_write_text(os.path.join(outside, 'x.txt'), 'x'))
                attempt('pkg_atomic_outside', lambda: pkg_atomic.atomic_write_text(os.path.join(outside, 'y.txt'), 'y'))
                attempt('top_second_root', lambda: top_rs.bootstrap_runtime(data_root=outside))
                attempt('top_same_root', lambda: top_rs.bootstrap_runtime(data_root=root))
                top_atomic.atomic_write_text(os.path.join(root, 'ok.txt'), 'ok')
                out['inside_ok'] = open(os.path.join(root, 'ok.txt'), encoding='utf-8').read()
                out['outside_entries'] = sorted(os.listdir(outside))
                lease.close()
                attempt('top_guard_after_close', lambda: top_rs.assert_write_allowed(os.path.join(root, 'x.json')))
                done()
            ''', *d.args(), str(SERVER))
            self.assertTrue(result['distinct_module_objects'], '這個測試要有兩份模組物件才有意義')
            self.assertTrue(result['same_error_class'], '兩份模組要拋同一個例外類別，呼叫端才接得住')
            self.assertTrue(result['top_sees_the_lease'])
            self.assertEqual(result['top_guard_outside'], 'REFUSED', '經套件名稱取得的租約，頂層名稱的守衛也要看得到')
            self.assertEqual(result['top_atomic_outside'], 'REFUSED')
            self.assertEqual(result['pkg_atomic_outside'], 'REFUSED')
            self.assertEqual(result['top_second_root'], 'REFUSED', '另一種匯入名稱不能再綁定第二個資料根')
            self.assertEqual(result['top_same_root'], 'OK', '同一資料根從另一種匯入名稱重複呼叫要回傳既有租約')
            self.assertEqual(result['inside_ok'], 'ok')
            self.assertEqual(result['outside_entries'], [])
            self.assertEqual(result['top_guard_after_close'], 'REFUSED', '從一種名稱釋放租約，另一種名稱的守衛也要保持已綁定')


if __name__ == '__main__':
    unittest.main()
