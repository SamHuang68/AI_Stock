# -*- coding: utf-8 -*-
"""README「主要 API」表必須對應 server.py 實際存在的路由（方法與路徑都要對上）。

以 AST 讀取 ``Handler.do_GET``／``do_POST`` 中與請求路徑 ``p`` 比較的字串常數，
不執行伺服器、不連網。README 新增端點而程式沒有、或程式改名而 README 沒跟上，都會失敗。
"""
import ast
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
README = os.path.join(ROOT, 'README.md')
SERVER = os.path.join(ROOT, 'server', 'server.py')

_ROW = re.compile(r'^\|\s*`(GET|POST|PUT|DELETE)\s+(/[^`\s?]*)[^`]*`\s*\|')


def readme_endpoints(text):
    """回傳 README「主要 API」段落中的 (方法, 路徑)，路徑去掉查詢字串。"""
    endpoints, inside = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            inside = line.strip() == '## 主要 API'
            continue
        if inside:
            match = _ROW.match(line)
            if match:
                endpoints.append((match.group(1), match.group(2)))
    return endpoints


def _route_constants(func):
    """收集函式內 ``p == '...'`` 與 ``p.startswith('...')`` 的字串常數。"""
    exact, prefixes = set(), set()
    for node in ast.walk(func):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == 'p':
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    exact.add(comp.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == 'startswith' and isinstance(node.func.value, ast.Name)
              and node.func.value.id == 'p'):
            for arg in node.args:
                values = arg.elts if isinstance(arg, ast.Tuple) else [arg]
                for value in values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        if value.value.endswith('?'):
                            exact.add(value.value[:-1])
                        else:
                            prefixes.add(value.value)
    return exact, prefixes


def server_routes(source):
    """回傳 {方法: (完全相符路徑集合, 前綴集合)}。"""
    tree = ast.parse(source)
    routes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ('do_GET', 'do_POST', 'do_PUT', 'do_DELETE'):
            routes[node.name[3:]] = _route_constants(node)
    return routes


def is_routed(routes, method, path):
    exact, prefixes = routes.get(method, (set(), set()))
    if path in exact:
        return True
    return any(prefix.endswith('/') and path.startswith(prefix) for prefix in prefixes)


class ReadmeApiRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(README, encoding='utf-8') as fh:
            cls.endpoints = readme_endpoints(fh.read())
        with open(SERVER, encoding='utf-8') as fh:
            cls.routes = server_routes(fh.read())

    def test_readme_table_is_parsed(self):
        self.assertGreaterEqual(len(self.endpoints), 10, 'README「主要 API」表解析不到足夠的端點')
        self.assertIn('GET', self.routes)
        self.assertIn('POST', self.routes)

    def test_every_readme_endpoint_has_a_route(self):
        missing = [f'{method} {path}' for method, path in self.endpoints
                   if not is_routed(self.routes, method, path)]
        self.assertEqual(missing, [], 'README 列出但 server.py 找不到對應路由的端點')

    def test_detects_missing_and_wrong_method(self):
        text = ('## 主要 API\n\n| 端點 | 用途 |\n|---|---|\n'
                '| `GET /health` | 版本 |\n| `GET /no-such-route-for-test` | 不存在 |\n'
                '| `POST /health` | 方法錯誤 |\n\n## 其他\n| `GET /ignored` | 不在表內 |\n')
        endpoints = readme_endpoints(text)
        self.assertEqual(endpoints, [('GET', '/health'), ('GET', '/no-such-route-for-test'), ('POST', '/health')])
        results = [is_routed(self.routes, m, p) for m, p in endpoints]
        self.assertEqual(results, [True, False, False])

    def test_query_variant_does_not_match_longer_path(self):
        routes = {'GET': ({'/pulse'}, {'/research/'})}
        self.assertTrue(is_routed(routes, 'GET', '/pulse'))
        self.assertFalse(is_routed(routes, 'GET', '/pulse/history'))
        self.assertTrue(is_routed(routes, 'GET', '/research/anything'))


if __name__ == '__main__':
    unittest.main()
