"""WaveDeck 的資料根解析入口要與主站的 `server/data_paths.py` 行為一致（單一資料根階段 2b）。

WaveDeck 的 `server` 套件與主站 `server/` 同名，同一個程序只能載入其中一個，而且 `版本身分.py` 只核對
`wavedeck/` 底下的檔案，所以 WaveDeck 在自己的目錄放一份精簡入口（`wavedeck/server/data_paths.py`），不匯入主站的。
兩份各自存在，就需要有一個測試防止它們悄悄分岔：同樣的保留環境變數、同樣的拒絕條件、同樣的 legacy 路徑與訊息。

兩個模組都以檔案路徑載入（互不影響，也避開 `server` 同名衝突）。
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # dataclass 會用 sys.modules[cls.__module__] 解析型別，先登記再執行
    spec.loader.exec_module(module)
    return module


MAIN = _load('_parity_main_data_paths', ROOT / 'server' / 'data_paths.py')
WAVEDECK = _load('_parity_wavedeck_data_paths', ROOT / 'wavedeck' / 'server' / 'data_paths.py')

CODE_ROOTS = [Path('C:/x/wd'), 'rel/wd', 'dir with space/wd', 'C:/資料/程式', '', '   ', None, 123]
RELATIVES = ['', 'a.json', 'exec_md/x.json', '程式版本.json', 'a\\b', '..', 'a/../b', '/abs', 'C:x', 'a\x00b', '.', 'a/./b']
ENVIRONS = [
    {}, {'ST_DATA_ROOT': 'x'}, {'ST_RUNTIME_ROLE': 'r'}, {'ST_DATA_BINDING': 'b'}, {'ST_DATA_ROOT': '   '},
    {'ST_URL': 'http://127.0.0.1:18432'}, {'ST_UPDATE_JOBS_DB': 'x.db'},     # 與資料根無關的變數不影響結果
]


def _outcome(call):
    try:
        return ('ok', str(call()))
    except Exception as exc:                       # 比對「是否拒絕」與訊息，不比對例外類別物件（兩個模組各有一個）
        return (type(exc).__name__, str(exc))


class WaveDeckResolverParity(unittest.TestCase):
    def test_reserved_binding_environment_names_are_identical(self):
        self.assertEqual(WAVEDECK.BINDING_ENV, MAIN.BINDING_ENV)

    def test_data_root_gives_the_same_result_or_the_same_rejection(self):
        for code_root in CODE_ROOTS:
            for environ in ENVIRONS:
                with self.subTest(code_root=code_root, environ=environ):
                    self.assertEqual(
                        _outcome(lambda: WAVEDECK.data_root(code_root=code_root, environ=environ)),
                        _outcome(lambda: MAIN.data_root(code_root=code_root, environ=environ)))

    def test_data_path_gives_the_same_result_or_the_same_rejection(self):
        for code_root in CODE_ROOTS:
            for relative in RELATIVES:
                for environ in ENVIRONS:
                    with self.subTest(code_root=code_root, relative=relative, environ=environ):
                        self.assertEqual(
                            _outcome(lambda: WAVEDECK.data_path(relative, code_root=code_root, environ=environ)),
                            _outcome(lambda: MAIN.data_path(relative, code_root=code_root, environ=environ)))

    def test_the_comparison_actually_sees_both_acceptance_and_rejection(self):
        outcomes = {_outcome(lambda: WAVEDECK.data_path(r, code_root='rel/wd', environ={}))[0] for r in RELATIVES}
        self.assertIn('ok', outcomes)
        self.assertIn('BindingError', outcomes)

    def test_wavedeck_signatures_are_a_subset_of_the_main_ones(self):
        self.assertEqual(inspect.signature(WAVEDECK.data_root), inspect.signature(MAIN.data_root))
        wd, main = inspect.signature(WAVEDECK.data_path).parameters, inspect.signature(MAIN.data_path).parameters
        for name, parameter in wd.items():
            with self.subTest(parameter=name):
                self.assertIn(name, main)
                self.assertEqual((parameter.kind, parameter.default), (main[name].kind, main[name].default))

    def test_neither_resolver_touches_the_filesystem(self):
        with tempfile.TemporaryDirectory(prefix='wd-parity-') as tmp:
            code_root = Path(tmp) / 'not-created'
            for module in (MAIN, WAVEDECK):
                module.data_root(code_root=code_root, environ={})
                module.data_path('a/b.json', code_root=code_root, environ={})
            self.assertFalse(code_root.exists())

    def test_the_wavedeck_resolver_stays_self_contained(self):
        """只用標準庫：才能被發布收據完整涵蓋，也能單獨以檔案路徑載入（不依賴任何同套件模組）。"""
        tree = ast.parse((ROOT / 'wavedeck' / 'server' / 'data_paths.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, '不得使用相對匯入')
                imported.add((node.module or '').split('.')[0])
        self.assertLessEqual(imported, set(sys.stdlib_module_names), f'含非標準庫的匯入：{sorted(imported - set(sys.stdlib_module_names))}')


if __name__ == '__main__':
    unittest.main()
