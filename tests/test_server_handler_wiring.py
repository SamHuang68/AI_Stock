"""接線檢查：server.py 內每個 `self._xxx(...)` 呼叫，都要在 `server/` 的某處有同名定義。

pyflakes 抓得到未定義的名稱，抓不到「拼錯的方法名稱」：`self._handle_foo()` 寫成 `self._handle_fo()`
只有在那條路由被打到時才會 AttributeError，而外層的寬鬆例外可能把它吞掉。這個檢查是名稱層級
（不判斷屬於哪個類別），便宜、決定性、沒有任何副作用（不啟動伺服器、不碰 data/）。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def defined_function_names(root: Path = ROOT) -> set[str]:
    names: set[str] = set()
    for path in (root / 'server').rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
        names.update(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return names


def private_self_calls(source: str) -> dict[str, list[int]]:
    calls: dict[str, list[int]] = {}
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self'
                and node.func.attr.startswith('_')):
            calls.setdefault(node.func.attr, []).append(node.lineno)
    return calls


class HandlerWiring(unittest.TestCase):
    def test_every_private_self_call_in_server_py_resolves_to_a_definition(self):
        calls = private_self_calls((ROOT / 'server' / 'server.py').read_text(encoding='utf-8'))
        defined = defined_function_names()
        missing = {name: lines[:3] for name, lines in sorted(calls.items()) if name not in defined}
        self.assertEqual(missing, {}, '以下 self._xxx() 在 server/ 內找不到定義（拼錯或漏寫？）：' + str(missing))
        self.assertGreater(len(calls), 100)          # 掃描本身有效，不是空轉

    def test_the_checker_catches_a_misspelled_handler(self):
        source = 'class H:\n    def _handle_foo(self):\n        pass\n    def do_GET(self):\n        self._handle_fo()\n        self._handle_foo()\n'
        calls = private_self_calls(source)
        defined = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
        self.assertEqual(sorted(name for name in calls if name not in defined), ['_handle_fo'])


if __name__ == '__main__':
    unittest.main()
