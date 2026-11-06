"""SQLite 寫入守衛棘輪（單一資料根階段 3a）。

`server/` 裡直接 `sqlite3.connect(...)` 且不是唯讀 URI（`mode=ro`）的位置，必須先呼叫
`runtime_storage.assert_write_allowed(路徑)`——同一個函式（含外層函式）裡、**在這次連線之前**。
目前大多數位置還沒接，現況登記在 `tests/sqlite_write_guard_baseline.json`，只能降不能升：

- 新增的 `sqlite3.connect` 若沒先過守衛，這個測試失敗（請改走已接守衛的入口，或在連線前呼叫守衛）。
- 某個檔案接上守衛後，把基準降到實際數字（這個測試會要求，免得基準虛高、之後又悄悄退化）。

掃描是保守的：用變數傳進去的 URI（看不出是不是 `mode=ro`）一律當成可寫；外層函式要自己呼叫守衛，
巢狀函式裡的守衛不替外層背書（看不出它有沒有被呼叫），外層的守衛則涵蓋它裡面的連線。
這只證明「語法上、連線之前有呼叫守衛」（不看分支與路徑是否真的會走到），不證明路徑引數正確；
守衛本身的行為由 tests/test_runtime_storage.py 驗證。
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIR = 'server'
BASELINE = ROOT / 'tests' / 'sqlite_write_guard_baseline.json'
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _is_sqlite_connect(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'connect'
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'sqlite3')


def _is_guard_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == 'assert_write_allowed') or \
           (isinstance(func, ast.Name) and func.id == 'assert_write_allowed')


def _is_read_only(call: ast.Call, source: str) -> bool:
    args = list(call.args[:1]) + [kw.value for kw in call.keywords if kw.arg == 'database']
    return bool(args) and 'mode=ro' in (ast.get_source_segment(source, args[0]) or '')


def _own_scope_nodes(function: ast.AST):
    """函式自己這一層的節點：不走進巢狀函式／lambda 的內容。

    巢狀函式有沒有被呼叫、什麼時候被呼叫，從語法上看不出來，所以它裡面的守衛不能替外層的連線背書
    （例如外層定義了一個含守衛的 `check()` 卻沒有呼叫它，再直接連線）。
    """
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, FUNCTIONS):
            stack.extend(ast.iter_child_nodes(node))


def unguarded_write_connects(source: str) -> int:
    """這份原始碼裡，沒有先過守衛的可寫 `sqlite3.connect` 數量。"""
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    total = 0
    for call in (n for n in ast.walk(tree) if _is_sqlite_connect(n)):
        if _is_read_only(call, source):
            continue
        position = (call.lineno, call.col_offset)
        guarded, node = False, parents.get(call)
        while node is not None and not guarded:
            if isinstance(node, FUNCTIONS):
                guarded = any(_is_guard_call(g) and (g.lineno, g.col_offset) < position for g in _own_scope_nodes(node))
            node = parents.get(node)
        total += 0 if guarded else 1
    return total


def scan_tree(root: Path = ROOT) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted((root / SCAN_DIR).glob('*.py')):
        count = unguarded_write_connects(path.read_text(encoding='utf-8'))
        if count:
            counts[f'{SCAN_DIR}/{path.name}'] = count
    return counts


class SqliteWriteGuardRatchet(unittest.TestCase):
    def test_unguarded_sqlite_writes_only_decrease(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))['counts']
        current = scan_tree()
        grew = {f: (baseline.get(f, 0), n) for f, n in current.items() if n > baseline.get(f, 0)}
        self.assertFalse(grew, '新增了沒先過守衛的 sqlite3.connect（檔案：基準→現在）：'
                               f'{grew}\n請改走已接守衛的入口（datastore.init_db／upsert_bars／merge_source_bars），'
                               '或在連線之前呼叫 runtime_storage.assert_write_allowed(路徑)。')
        shrank = {f: (n, current.get(f, 0)) for f, n in baseline.items() if current.get(f, 0) < n}
        self.assertFalse(shrank, f'已有位置接上守衛，請把 tests/sqlite_write_guard_baseline.json 降到實際數字（檔案：基準→現在）：{shrank}')

    def test_baseline_only_names_existing_files(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))['counts']
        missing = [f for f in baseline if not (ROOT / f).is_file()]
        self.assertFalse(missing, f'基準登記了不存在的檔案：{missing}')


class ScannerClassification(unittest.TestCase):
    """掃描器本身的判定（用合成的原始碼，不依賴 repo 現況）。"""

    def count(self, body: str) -> int:
        return unguarded_write_connects('import sqlite3\nimport runtime_storage\n' + body)

    def test_plain_connect_counts(self):
        self.assertEqual(self.count("def f(p):\n    return sqlite3.connect(p)\n"), 1)

    def test_connect_inside_with_closing_counts(self):
        self.assertEqual(self.count("from contextlib import closing\ndef f(p):\n    with closing(sqlite3.connect(p)) as c, c:\n        pass\n"), 1)

    def test_read_only_uri_is_not_counted(self):
        self.assertEqual(self.count("def f(p):\n    return sqlite3.connect(p + '?mode=ro', uri=True)\n"), 0)

    def test_variable_uri_is_treated_as_writable(self):
        self.assertEqual(self.count("def f(uri):\n    return sqlite3.connect(uri, uri=True)\n"), 1)

    def test_guard_before_connect_in_same_function(self):
        self.assertEqual(self.count("def f(p):\n    runtime_storage.assert_write_allowed(p)\n    return sqlite3.connect(p)\n"), 0)

    def test_guard_after_connect_does_not_count_as_a_guard(self):
        self.assertEqual(self.count("def f(p):\n    c = sqlite3.connect(p)\n    runtime_storage.assert_write_allowed(p)\n    return c\n"), 1)

    def test_guard_in_outer_function_covers_a_nested_helper(self):
        self.assertEqual(self.count("def f(p):\n    runtime_storage.assert_write_allowed(p)\n    def g():\n        return sqlite3.connect(p)\n    return g()\n"), 0)

    def test_guard_in_an_uncalled_nested_helper_does_not_cover_the_outer_connection(self):
        self.assertEqual(self.count(
            "def f(p):\n    def check():\n        runtime_storage.assert_write_allowed(p)\n    return sqlite3.connect(p)\n"), 1)

    def test_guard_and_connect_both_inside_a_nested_helper_count_as_guarded(self):
        self.assertEqual(self.count(
            "def f(p):\n    def g():\n        runtime_storage.assert_write_allowed(p)\n        return sqlite3.connect(p)\n    return g()\n"), 0)

    def test_guard_inside_a_lambda_does_not_cover(self):
        self.assertEqual(self.count(
            "def f(p):\n    check = lambda: runtime_storage.assert_write_allowed(p)\n    return sqlite3.connect(p)\n"), 1)

    def test_guard_in_a_different_function_does_not_cover(self):
        self.assertEqual(self.count("def a(p):\n    runtime_storage.assert_write_allowed(p)\ndef b(p):\n    return sqlite3.connect(p)\n"), 1)

    def test_module_level_connect_counts(self):
        self.assertEqual(self.count("c = sqlite3.connect('x.db')\n"), 1)

    def test_bare_name_guard_call_is_recognised(self):
        self.assertEqual(unguarded_write_connects(
            'import sqlite3\nfrom runtime_storage import assert_write_allowed\n'
            'def f(p):\n    assert_write_allowed(p)\n    return sqlite3.connect(p)\n'), 0)


if __name__ == '__main__':
    unittest.main()
