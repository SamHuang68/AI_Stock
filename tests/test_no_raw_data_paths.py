"""棘輪：`server/` 與 `wavedeck/server/` 內「自己組 data／logs 路徑」的位置只能減少，不能增加（單一資料根階段 2、2b）。

所有執行期資料與日誌路徑都要經過 `server/data_paths.py`（`data_path`／`data_root`／`log_path`），
否則日後切換到單一資料根時，這個模組會悄悄繼續寫回舊位置。
WaveDeck（`wavedeck/server/`）的 `server` 套件與主站同名，走它自己的 `wavedeck/server/data_paths.py`（階段 2b）。

偵測兩種寫法（AST，不看註解與字串內容）：
  * ``os.path.join(<根>, 'data'|'logs'[, …])``
  * ``<根> / 'data'|'logs'``（pathlib）

新增一處 → 本測試失敗：請改用 `data_paths`。
減少了 → 本測試也會失敗，提醒你把 `tests/raw_data_paths_baseline.json` 降到新的數字（棘輪不留餘裕）。
目前留下的項目都有明確理由與歸屬階段，見 baseline 檔的 reasons。
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name('raw_data_paths_baseline.json')
SCAN_DIRS = ('server', 'wavedeck/server')
EXEMPT = {'server/data_paths.py', 'wavedeck/server/data_paths.py'}
SEGMENTS = {'data', 'logs'}


def _is_runtime_dir_literal(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.replace('\\', '/').split('/')[0] in SEGMENTS)


def scan(root: Path = ROOT) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(p for directory in SCAN_DIRS for p in (root / directory).rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
        lines = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'join'
                    and any(_is_runtime_dir_literal(arg) for arg in node.args[1:])):
                lines.append(node.lineno)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _is_runtime_dir_literal(node.right):
                lines.append(node.lineno)
        if lines:
            found[relative] = sorted(lines)
    return found


class RawDataPathRatchet(unittest.TestCase):
    def test_raw_runtime_paths_never_increase_and_the_baseline_stays_tight(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))['counts']
        current = scan()
        problems = []
        for name in sorted(set(baseline) | set(current)):
            now, was = len(current.get(name, [])), baseline.get(name, 0)
            if now > was:
                problems.append(f'{name}: 自己組 data／logs 路徑 {was} → {now}（新增 {now - was} 處，行 {current[name]}）。'
                                f'請改用該區的 data_paths（server/data_paths.py 或 wavedeck/server/data_paths.py）。')
            elif now < was:
                problems.append(f'{name}: {was} → {now}（減少了，很好）。請把 tests/raw_data_paths_baseline.json 的'
                                f' "{name}" 降到 {now}（為 0 就移除該項與其 reasons），讓棘輪保持緊。')
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_baseline_entries_each_carry_a_reason(self):
        data = json.loads(BASELINE.read_text(encoding='utf-8'))
        self.assertEqual(sorted(data['counts']), sorted(data['reasons']))
        for name, reason in data['reasons'].items():
            self.assertTrue(reason.strip(), name)

    def test_the_scanner_recognises_both_spellings_and_ignores_unrelated_code(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / 'server'
            server.mkdir()
            (server / 'a.py').write_text(
                "import os\nfrom pathlib import Path\n"
                "A = os.path.join(base, 'data', 'x.db')\n"          # 第 3 行
                "B = os.path.join(base, 'logs')\n"                   # 第 4 行
                "C = Path(base) / 'data' / 'y.json'\n"               # 第 5 行（內層 / 'data' 算，外層 / 'y.json' 不算）
                "D = os.path.join(base, 'data/sub', 'z')\n"          # 第 6 行
                "E = os.path.join('data', name)\n"                   # 不算：第一個參數是封存內名稱
                "F = {'data': 1}\nG = row.get('data')\nH = base / 'database'\n", encoding='utf-8')
            (server / 'data_paths.py').write_text("X = Path(a) / 'data'\n", encoding='utf-8')   # 解析器本身免檢
            wd = Path(tmp) / 'wavedeck' / 'server'
            wd.mkdir(parents=True)
            (wd / 'b.py').write_text("Y = ROOT / 'data'\n", encoding='utf-8')               # WaveDeck 也要掃（第 1 行）
            (wd / 'data_paths.py').write_text("Z = Path(a) / 'data'\n", encoding='utf-8')   # WaveDeck 解析器免檢
            hits = scan(Path(tmp))
        self.assertEqual(hits, {'server/a.py': [3, 4, 5, 6], 'wavedeck/server/b.py': [1]})


if __name__ == '__main__':
    unittest.main()
