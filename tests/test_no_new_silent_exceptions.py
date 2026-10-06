"""棘輪：`server/` 內「寬鬆例外處理又不留任何痕跡」的數量只能下降，不能增加（共用規則 0014）。

寬鬆 = `except Exception`／`except BaseException`／裸 `except`。
靜默 = 處理區塊只有 pass／continue／break／return 常數，沒有記錄、沒有 raise、沒有其他動作。

為什麼要有這個檢查：server.py 缺 `import math`，五個功能被 `except Exception: return None` 吞掉
NameError，悄悄失效約五天，沒有任何錯誤訊息（見陷阱 0019、PR #165）。

新增一個靜默處理 → 本測試失敗。請改成：縮小例外型別（例如只抓 ValueError／TypeError），或用
`log_once`（server/log_once.py）留下限頻記錄，或重新拋出。
減少了 → 本測試也會失敗，提醒你把 `tests/silent_except_baseline.json` 降到新的數字（棘輪不留餘裕，
否則之後可以「用清掉的額度」偷偷新增）。更新方式見下方 `main()`。
"""
from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name('silent_except_baseline.json')
BROAD = {'Exception', 'BaseException'}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    if isinstance(kind, ast.Name):
        return kind.id in BROAD
    if isinstance(kind, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id in BROAD for item in kind.elts)
    return False


def _is_silent(handler: ast.ExceptHandler) -> bool:
    for stmt in handler.body:
        if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
            continue
        if isinstance(stmt, ast.Return) and (stmt.value is None or isinstance(stmt.value, ast.Constant)):
            continue
        if (isinstance(stmt, ast.Return) and isinstance(stmt.value, (ast.Dict, ast.List, ast.Tuple, ast.Set))
                and not any(isinstance(n, (ast.Name, ast.Call, ast.Attribute, ast.Subscript)) for n in ast.walk(stmt.value))):
            continue                                          # return {} / [] / () 之類的空常數
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue                                          # 只有字串（註解式）
        return False
    return True


def scan(root: Path = ROOT) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted((root / 'server').rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
        lines = sorted(h.lineno for node in ast.walk(tree) if isinstance(node, ast.Try)
                       for h in node.handlers if _is_broad(h) and _is_silent(h))
        if lines:
            found[path.relative_to(root).as_posix()] = lines
    return found


class SilentExceptionRatchet(unittest.TestCase):
    def test_silent_broad_handlers_never_increase_and_the_baseline_stays_tight(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))['counts']
        current = {name: len(lines) for name, lines in scan().items()}
        problems = []
        for name in sorted(set(baseline) | set(current)):
            now, was = current.get(name, 0), baseline.get(name, 0)
            if now > was:
                problems.append(f'{name}: 靜默寬鬆例外 {was} → {now}（新增 {now - was} 個）。請縮小例外型別、'
                                f'用 log_once 記錄或重新拋出。目前所在行：{scan()[name]}')
            elif now < was:
                problems.append(f'{name}: {was} → {now}（減少了，很好）。請把 tests/silent_except_baseline.json 的'
                                f' "{name}" 降到 {now}（為 0 就移除該項），讓棘輪保持緊。')
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_the_helper_log_once_is_not_itself_silent(self):
        self.assertNotIn('server/log_once.py', scan())


def main() -> int:
    """重新產生 baseline：python tests/test_no_new_silent_exceptions.py --write"""
    if '--write' not in sys.argv:
        print(json.dumps({name: len(lines) for name, lines in scan().items()}, ensure_ascii=True, indent=2))
        return 0
    counts = {name: len(lines) for name, lines in scan().items()}
    payload = {
        'note': '寬鬆（except Exception／BaseException／裸 except）且靜默（只有 pass／continue／break／return 常數）的處理區塊數量，依檔案計。只能下降（共用規則 0014）。',
        'counts': dict(sorted(counts.items())),
    }
    BASELINE.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print('written', sum(counts.values()), 'in', len(counts), 'files')
    return 0


if __name__ == '__main__':
    if '--write' in sys.argv or '--print' in sys.argv:
        raise SystemExit(main())
    unittest.main()
