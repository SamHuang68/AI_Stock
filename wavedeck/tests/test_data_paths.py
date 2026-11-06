# -*- coding: utf-8 -*-
"""WaveDeck 資料根解析入口（單一資料根階段 2b）：解析器本身，以及 legacy 路徑與改接前逐字相同的契約。

契約測試在暫存複本上以 ``python -I -X utf8`` 開乾淨子行程匯入 ``server.server``，期望值是這裡獨立寫死的
路徑表（用 ``os.path.join`` 組，不經過 ``data_paths``），所以解析器算錯、或有人把某個模組改接錯，都會對不上。
暫存複本的資料目錄是空的，不會碰到真實的 ``wavedeck/data`` 與執行中服務的實例鎖。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import data_paths  # noqa: E402
from server.data_paths import BINDING_ENV, BindingError  # noqa: E402


class DataPathsUnitTests(unittest.TestCase):
    def test_legacy_data_root_is_code_root_slash_data(self):
        self.assertEqual(data_paths.data_root(code_root=ROOT, environ={}), ROOT / 'data')
        self.assertEqual(data_paths.data_root(code_root=str(ROOT), environ={}), ROOT / 'data')

    def test_data_path_joins_below_the_data_root(self):
        self.assertEqual(data_paths.data_path('wavedeck.port', code_root=ROOT, environ={}), ROOT / 'data' / 'wavedeck.port')
        self.assertEqual(data_paths.data_path('exec_md/x.json', code_root=ROOT, environ={}), ROOT / 'data' / 'exec_md' / 'x.json')
        self.assertEqual(data_paths.data_path('', code_root=ROOT, environ={}), ROOT / 'data')

    def test_code_root_is_used_verbatim(self):
        # 不 abspath、不 resolve：相對路徑原樣保留，才會與既有的 ROOT / "data" 逐字相同。
        self.assertEqual(data_paths.data_root(code_root='rel/wd', environ={}), Path('rel/wd') / 'data')
        self.assertFalse(data_paths.data_root(code_root='rel/wd', environ={}).is_absolute())

    def test_unsafe_relative_paths_are_rejected(self):
        for bad in ('..', 'a/../b', '/abs', 'C:x', 'a\x00b', '.', 'a/./b', '..\\x'):
            with self.subTest(relative=bad):
                with self.assertRaises(BindingError):
                    data_paths.data_path(bad, code_root=ROOT, environ={})

    def test_empty_or_non_path_code_root_is_rejected(self):
        for bad in ('', '   ', None, 123):
            with self.subTest(code_root=bad):
                with self.assertRaises(BindingError):
                    data_paths.data_root(code_root=bad, environ={})

    def test_any_external_binding_setting_fails_closed(self):
        for name in BINDING_ENV:
            with self.subTest(name=name):
                with self.assertRaises(BindingError) as caught:
                    data_paths.data_root(code_root=ROOT, environ={name: 'x'})
                self.assertIn(name, str(caught.exception))
        self.assertEqual(data_paths.data_root(code_root=ROOT, environ={'ST_DATA_ROOT': '   '}), ROOT / 'data')

    def test_environment_is_read_when_no_mapping_is_passed(self):
        with mock.patch.dict(os.environ, {'ST_DATA_BINDING': 'external'}):
            with self.assertRaises(BindingError):
                data_paths.data_root(code_root=ROOT)
            self.assertEqual(data_paths.data_root(code_root=ROOT, environ={}), ROOT / 'data')

    def test_resolving_never_touches_the_filesystem(self):
        with tempfile.TemporaryDirectory(prefix='wd-dp-') as tmp:
            code_root = Path(tmp) / 'not-created'
            data_paths.data_root(code_root=code_root, environ={})
            data_paths.data_path('a/b.json', code_root=code_root, environ={})
            self.assertFalse(code_root.exists())


CHILD = r'''
import importlib, json, os, socket, sys
from pathlib import Path
from unittest import mock

root = sys.argv[1]
sys.path.insert(0, root)
os.chdir(root)


def forbidden(*args, **kwargs):
    raise AssertionError('匯入期間不得監聽或連線')


out = {'values': {}, 'modules': []}
try:
    with mock.patch.object(socket.socket, 'connect', forbidden), mock.patch.object(socket.socket, 'bind', forbidden):
        module = importlib.import_module('server.server')
        for name in ('server.state', 'server.config', 'server.audit', 'server.exec_md', 'server.providers'):
            importlib.import_module(name)
        out['values'] = {
            'server.state.DATA': str(sys.modules['server.state'].DATA),
            'server.state.STATE_PATH': str(sys.modules['server.state'].STATE_PATH),
            'server.config.DATA': str(sys.modules['server.config'].DATA),
            'server.config.CONFIG_PATH': str(sys.modules['server.config'].CONFIG_PATH),
            'server.config.SECRETS_PATH': str(sys.modules['server.config'].SECRETS_PATH),
            'server.audit.DATA': str(sys.modules['server.audit'].DATA),
            'server.exec_md.DATA': str(sys.modules['server.exec_md'].DATA),
            'server.exec_md.EXEC_DIR': str(sys.modules['server.exec_md'].EXEC_DIR),
            'server.providers.DATA': str(sys.modules['server.providers'].DATA),
            'server.providers.COST_BUDGET_PATH': str(sys.modules['server.providers'].COST_BUDGET_PATH),
            'server.server.PORT_FILE': str(module.PORT_FILE),
            'server.server._INSTANCE_LOCK': str(module._INSTANCE_LOCK.name),
        }
        module._write_port_file(12345)
        out['port_file_text'] = Path(module.PORT_FILE).read_text(encoding='utf-8')
        sys.modules['server.audit'].write('contract_probe', {'k': 1})
        sys.modules['server.state'].RUNTIME.save()
        sys.modules['server.config'].load_config()
        out['data_files'] = sorted(p.relative_to(Path(root) / 'data').as_posix() for p in (Path(root) / 'data').rglob('*') if p.is_file())
except BaseException as exc:
    out['error'] = type(exc).__name__ + ': ' + str(exc).split(chr(10))[0][:200]
out['modules'] = sorted(n for n in ('server.state', 'server.audit', 'server.config') if n in sys.modules)
out['top_level'] = sorted(p.name for p in Path(root).iterdir())
sys.stdout.write('@@WDDP@@' + json.dumps(out, sort_keys=True) + chr(10))
sys.stdout.flush()
os._exit(0)
'''


class LegacyContractTests(unittest.TestCase):
    def _run(self, extra_env=None):
        tmp = tempfile.TemporaryDirectory(prefix='wd-contract-', ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / 'wd'
        shutil.copytree(ROOT / 'server', root / 'server', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(ROOT / 'VERSION', root / 'VERSION')
        (root / 'data').mkdir()
        child = Path(tmp.name) / 'child.py'
        child.write_text(CHILD, encoding='utf-8')
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('ST_', 'WD_', 'WAVEDECK_')) and k not in {'PYTHONPATH', 'PYTHONHOME', 'OPENAI_API_KEY'}}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.update(extra_env or {})
        proc = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(child), str(root)], capture_output=True,
                              text=True, encoding='utf-8', errors='replace', env=env, cwd=tmp.name, timeout=120)
        line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith('@@WDDP@@')), None)
        self.assertIsNotNone(line, f'子行程沒有回報結果 rc={proc.returncode}\n{proc.stderr[-1500:]}')
        return root, json.loads(line[len('@@WDDP@@'):])

    def test_every_wavedeck_path_matches_the_pre_change_layout(self):
        root, out = self._run()
        self.assertNotIn('error', out, out.get('error'))
        resolved = str(root.resolve())
        j = lambda *parts: os.path.join(resolved, *parts)      # 獨立於 data_paths 的期望值
        contract = {
            'server.state.DATA': j('data'),
            'server.state.STATE_PATH': j('data', 'runtime_state.json'),
            'server.config.DATA': j('data'),
            'server.config.CONFIG_PATH': j('data', 'wavedeck_config.json'),
            'server.config.SECRETS_PATH': j('data', 'wavedeck_secrets.json'),
            'server.audit.DATA': j('data'),
            'server.exec_md.DATA': j('data'),
            'server.exec_md.EXEC_DIR': j('data', 'exec_md'),
            'server.providers.DATA': j('data'),
            'server.providers.COST_BUDGET_PATH': j('data', 'wavedeck_cost_budget.sqlite3'),
            'server.server.PORT_FILE': j('data', 'wavedeck.port'),
            'server.server._INSTANCE_LOCK': j('data', 'wavedeck.instance.lock'),
        }
        self.assertEqual(out['values'], contract)
        self.assertEqual(out['port_file_text'], '12345')

    def test_files_land_only_under_data(self):
        _, out = self._run()
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['data_files'], ['runtime_state.json', 'wavedeck.instance.lock', 'wavedeck.port',
                                             'wavedeck_audit.db', 'wavedeck_config.json'])
        self.assertEqual(out['top_level'], ['VERSION', 'data', 'server'])

    def test_external_binding_setting_stops_startup_before_any_state_is_touched(self):
        root, out = self._run({'ST_DATA_ROOT': 'elsewhere'})
        self.assertTrue(out.get('error', '').startswith('BindingError'), out)
        self.assertEqual(out['modules'], [], '失敗前不得已初始化狀態、稽核或設定')
        self.assertEqual(out['top_level'], ['VERSION', 'data', 'server'])
        self.assertEqual(list((root / 'data').iterdir()) if (root / 'data').exists() else [], [],
                         '拒絕啟動前不得寫入任何資料或建立實例鎖')


if __name__ == '__main__':
    unittest.main()
