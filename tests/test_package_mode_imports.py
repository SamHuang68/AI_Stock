"""套件模式匯入（單一資料根階段 2）：能以 ``server.<模組>`` 匯入的模組，改接 `data_paths` 後仍要能匯入。

`server/` 底下的模組有兩種載入方式：把 `server/` 放進 `sys.path` 後以頂層名稱匯入（`import ai_api`，
正式執行與多數測試），以及只把 repo 根目錄放進 `sys.path`、以套件成員匯入（`from server import ai_api`，
例如 tests/test_secret_migration.py）。後者遇到絕對的 `import data_paths` 會 ModuleNotFoundError，
所以這些模組必須用 `if __package__: from . import data_paths else: import data_paths`（datastore 本來就是這樣）。

這份名單是改接前實測「可以套件模式匯入」的模組（改接後退化的 20 個，加上本來就用雙模式匯入的
datastore）。階段 3a 再加入 atomic_store、daemon_lock、runtime_storage：它們原本沒有同層相依，
現在 atomic_store 要匯入 runtime_storage、daemon_lock 要匯入 data_paths。在暫存複本上執行，匯入的副作用不會落在 repo。
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

ROOT = Path(__file__).resolve().parents[1]

PACKAGE_MODE_MODULES = [
    'ai_api', 'ai_local', 'alert_daemon', 'atomic_store', 'daemon_lock', 'datastore', 'early_warning', 'feature_settings', 'llm_gate',
    'macro_track', 'margin_cycle', 'ohlc_ledger', 'override_alpha', 'peak_approvals', 'postmarket_report',
    'runtime_storage', 'signal_digest', 'signal_stats_pool', 'slog', 'stock_signals_routes', 'tdcc_holders', 'touxin_ledger',
    'universe', 'wavedeck_bus',
]

CHILD = r'''
import importlib, json, os, sys
root = sys.argv[1]
sys.path.insert(0, root)            # 只有 repo 根目錄；server/ 刻意不在 sys.path 上
os.chdir(root)
out = {}
for name in json.loads(sys.argv[2]):
    try:
        importlib.import_module('server.' + name)
        out[name] = 'OK'
    except BaseException as exc:
        out[name] = type(exc).__name__ + ': ' + str(exc).split(chr(10))[0][:160]
print('@@PKG@@' + json.dumps(out, ensure_ascii=False))
'''


class PackageModeImports(unittest.TestCase):
    def test_modules_that_import_as_server_members_still_do(self):
        with tempfile.TemporaryDirectory(prefix='st-pkgmode-', ignore_cleanup_errors=True) as tmp:
            root = os.path.join(tmp, 'root')
            shutil.copytree(ROOT / 'server', os.path.join(root, 'server'), ignore=shutil.ignore_patterns('__pycache__'))
            os.makedirs(os.path.join(root, 'data'))
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith('ST_') and k not in {'LLM_GATE_PATH', 'PYTHONPATH', 'PYTHONHOME'}}
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            proc = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', CHILD, root, json.dumps(PACKAGE_MODE_MODULES)],
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', env=env,
                                  cwd=tmp, timeout=240)
        line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith('@@PKG@@')), None)
        self.assertIsNotNone(line, f'子行程沒有回報結果 rc={proc.returncode}\n{proc.stderr[-1500:]}')
        result = json.loads(line[len('@@PKG@@'):])
        self.assertEqual(sorted(result), sorted(PACKAGE_MODE_MODULES))
        failures = {name: why for name, why in result.items() if why != 'OK'}
        # 缺少未安裝的第三方套件不算（那與資料路徑無關）；專案內模組（含 data_paths）匯入失敗一律算錯。
        local = {p.stem for p in (ROOT / 'server').glob('*.py')}
        real = {}
        for name, why in failures.items():
            missing = why.split("'")[1] if why.startswith('ModuleNotFoundError') and "'" in why else None
            if missing and missing not in local:
                continue
            real[name] = why
        self.assertEqual(real, {}, '以套件模式匯入失敗（多半是缺少 `if __package__` 的雙模式匯入）：\n' + json.dumps(real, ensure_ascii=False, indent=1))
        self.assertGreaterEqual(len(PACKAGE_MODE_MODULES) - len(failures), 15)

    def test_every_converted_module_that_imports_data_paths_in_package_mode_uses_the_dual_form(self):
        """靜態輔助檢查：名單內的模組都不能再有頂層的裸 ``import data_paths``。"""
        for name in PACKAGE_MODE_MODULES:
            with self.subTest(module=name):
                text = (ROOT / 'server' / f'{name}.py').read_text(encoding='utf-8')
                lines = text.splitlines()
                bare = [i for i, line in enumerate(lines) if line == 'import data_paths']
                for i in bare:
                    self.assertTrue(i > 0 and lines[i - 1].strip() == 'else:',
                                    f'{name}.py 第 {i + 1} 行是頂層的 import data_paths，套件模式會失敗')


if __name__ == '__main__':
    unittest.main()
