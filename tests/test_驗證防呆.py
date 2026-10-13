"""驗證防呆的局部流程案例；所有產物均在暫存目錄。"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

入口 = Path(__file__).resolve().parents[1] / 'tools' / 'codex' / 'verification_gate.py'
規格 = importlib.util.spec_from_file_location('scoped_verification_gate', 入口)
gate = importlib.util.module_from_spec(規格)
規格.loader.exec_module(gate)


class 驗證防呆測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / '案例.py'
        self.counter = self.root / '次數.txt'
        self.runner.write_text(
            'from pathlib import Path\nimport sys\n'
            'p = Path(sys.argv[1])\n'
            'p.write_text(str(int(p.read_text()) + 1) if p.exists() else "1")\n'
            'if "漂移" in sys.argv: Path(__file__).write_text("# 輸入已改變\\n", encoding="utf-8")\n'
            'sys.exit(3 if "失敗" in sys.argv else 0)\n', encoding='utf-8')
        command = [sys.executable, '-B', str(self.runner), str(self.counter)]
        self.plan = {
            'scope': 'targeted', 'reason': '確認局部防呆契約', 'verification_id': '假案例',
            'artifact': '候選甲', 'cwd': str(self.root), 'command': command,
            'inputs': [str(self.runner)], 'environment': sys.version,
            'impact': {'changed_files': [str(self.runner)], 'contracts': ['僅執行明列案例'],
                       'cases': [{'id': '案例甲', 'command': command.copy(), 'inputs': [str(self.runner)],
                                  'changed_files': [str(self.runner)]}]},
            'expected_seconds': 0.01, 'timeout_seconds': 5,
            'evidence_dir': str(self.root / '證據'),
        }

    def invoke(self):
        path = self.root / '計畫.json'
        path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = gate.main(path, workspace_root=self.root)
        return code, json.loads(output.getvalue())

    def argument(self, value):
        self.plan['command'].append(value)
        self.plan['impact']['cases'][0]['command'].append(value)

    def test_無關候選變更重用成功(self):
        self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        self.plan['artifact'] = '候選乙'
        result = self.invoke()[1]
        self.assertEqual(result['decision'], 'REUSE')
        self.assertEqual(result['verified_artifact'], '候選甲')
        self.assertEqual(self.counter.read_text(), '1')

    def test_輸入或環境變更重新執行(self):
        self.invoke()
        self.runner.write_text(self.runner.read_text(encoding='utf-8') + '# 新變更\n', encoding='utf-8')
        self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        self.plan['environment'] += '環境乙'
        self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        self.assertEqual(self.counter.read_text(), '3')

    def test_即時檢查不重用(self):
        self.invoke()
        self.plan['reuse_policy'] = 'never'
        self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        self.plan['reuse_policy'] = 'success'
        self.plan['mode'] = 'live'
        self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        self.assertEqual(self.counter.read_text(), '3')

    def test_舊局部計畫拒絕遷移(self):
        del self.plan['impact']
        with self.assertRaisesRegex(ValueError, '遷移'):
            self.invoke()
        self.assertFalse(self.counter.exists())

    def test_命令未對應案例拒絕(self):
        self.plan['command'].append('未列案例')
        with self.assertRaisesRegex(ValueError, 'exact'):
            self.invoke()

    def test_案例依賴未納入輸入拒絕(self):
        extra = self.root / '設定.json'
        extra.write_text('{}')
        self.plan['impact']['cases'][0]['inputs'].append(str(extra))
        with self.assertRaisesRegex(ValueError, '全部納入'):
            self.invoke()

    def test_全套與已知包裝拒絕(self):
        commands = [
            ['python', '-m', 'unittest', 'discover'], ['python', '-m', 'unittest'],
            ['python', '-m', 'pytest'], ['pytest', 'tests'],
            ['pytest', '--ignore=案例.py'], ['pytest', '-c', '設定.py'],
            ['npm', 'test'], ['npm', 'test', '--', '--runInBand'],
            ['npm', 'run', 'test:all'], ['pwsh', '-File', '案例.ps1'],
            ['python', '-c', 'pass'], ['python', 'private_web_release.py', 'stage'],
            ['node', '-e', 'process.exit(0)'],
            ['python', 'verification_gate.py', '計畫.json'],
        ]
        for command in commands:
            with self.subTest(command=command), self.assertRaises(ValueError):
                gate.reject_broad_targeted(command)

    def test_明列案例允許(self):
        for command in (['python', '-m', 'unittest', 'tests.test_驗證防呆'],
                        ['python', '-m', 'pytest', 'tests/test_驗證防呆.py'],
                        ['npm', 'test', '--', '案例.test.js']):
            gate.reject_broad_targeted(command)

    def test_完整計畫必須有必要性及授權(self):
        self.plan['scope'] = 'full'
        self.plan['full_consent'] = {'explicit': True, 'user_quote': '測試夾具授權', 'source': '單元案例'}
        with self.assertRaisesRegex(ValueError, 'full_necessity'):
            self.invoke()
        self.plan['full_necessity'] = '夾具只執行秒級假 runner，以確認完整計畫欄位。'
        self.assertEqual(self.invoke()[0], 0)
        del self.plan['full_consent']
        with self.assertRaisesRegex(ValueError, '明確授權'):
            self.invoke()

    def test_失敗須新證據且不可重複(self):
        self.argument('失敗')
        self.assertEqual(self.invoke()[0], 3)
        with self.assertRaisesRegex(ValueError, '前次同版本失敗'):
            self.invoke()
        evidence = self.root / '新證據.txt'
        evidence.write_text('新的疑慮', encoding='utf-8')
        self.plan['rerun'] = {'reason': '新失敗證據', 'evidence': str(evidence)}
        self.assertEqual(self.invoke()[0], 3)
        with self.assertRaisesRegex(ValueError, '已使用'):
            self.invoke()

    def test_成功重跑須新證據(self):
        self.invoke()
        evidence = self.root / '新證據.txt'
        evidence.write_text('新的疑慮', encoding='utf-8')
        self.plan['rerun'] = {'reason': '具體未解疑慮', 'evidence': str(evidence)}
        self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        with self.assertRaisesRegex(ValueError, '已使用'):
            self.invoke()

    def test_執行期間輸入漂移不能成功(self):
        self.argument('漂移')
        self.assertEqual(self.invoke()[0], 1)
        receipt = next((self.root / '證據').glob('*.latest.json'))
        self.assertIn('輸入改變', json.loads(receipt.read_text(encoding='utf-8'))['message'])

    def test_逾時保留鎖不另啟程序(self):
        with patch.object(gate.subprocess, 'Popen') as start:
            start.return_value.pid = 123
            start.return_value.wait.side_effect = subprocess.TimeoutExpired(self.plan['command'], 5)
            self.assertEqual(self.invoke()[0], 124)
            with self.assertRaisesRegex(ValueError, '未結束'):
                self.invoke()
            self.assertEqual(start.call_count, 1)
        self.assertEqual(len(list((self.root / '證據').glob('*.active.json'))), 1)

    def test_執行檔與入口雜湊進入識別(self):
        self.invoke()
        receipt = next((self.root / '證據').glob('*.latest.json'))
        identity = json.loads(receipt.read_text(encoding='utf-8'))['identity']
        self.assertEqual(identity['executable'], gate.sha(sys.executable))
        self.assertEqual(identity['gate'], gate.sha(入口))
        self.assertNotIn('artifact', identity)

    def test_兩個非股票專案共用帳本也不混用(self):
        original = copy.deepcopy(self.plan)
        for name in ('筆記專案', '圖片專案'):
            project = self.root / name
            project.mkdir()
            self.plan = copy.deepcopy(original)
            self.plan['cwd'] = str(project)
            self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
            self.assertEqual(self.invoke()[1]['decision'], 'REUSE')
        self.assertEqual(self.counter.read_text(), '2')
        self.assertEqual(len(list((self.root / '證據').glob('*.latest.json'))), 2)

    def test_無關案例不能冒充變更驗證(self):
        changed = self.root / '真正變更.py'
        changed.write_text('# 真正受影響來源', encoding='utf-8')
        self.plan['impact']['changed_files'] = [str(changed)]
        self.plan['impact']['cases'][0]['changed_files'] = [str(changed)]
        with self.assertRaisesRegex(ValueError, '沒有完整對應'):
            self.invoke()
        self.assertFalse(self.counter.exists())

    def test_案例變更必須是整體變更子集合(self):
        self.plan['impact']['cases'][0]['changed_files'] = [str(self.root / '無關.py')]
        with self.assertRaisesRegex(ValueError, '子集合'):
            self.invoke()

    def test_刪檔必須映射受影響檔案與理由(self):
        deleted = str(self.root / '已刪除.py')
        self.plan['impact']['changed_files'] = [deleted]
        case = self.plan['impact']['cases'][0]
        case['changed_files'] = [deleted]
        with self.assertRaisesRegex(ValueError, '沒有完整對應'):
            self.invoke()
        case['deleted_files'] = [{'path': deleted, 'consumer': str(self.runner),
                                 'reason': '刪除舊來源後由此案例確認呼叫者正常處理。'}]
        self.assertEqual(self.invoke()[0], 0)

    def test_命令指定測試檔必須納入案例輸入(self):
        folder = self.root / 'tests'
        folder.mkdir()
        module = folder / 'test_範例.py'
        module.write_text('# 局部測試模組', encoding='utf-8')
        for args in (['-m', 'unittest', 'tests.test_範例.案例.test_指定'],
                     ['-m', 'pytest', 'tests/test_範例.py::test_指定']):
            with self.subTest(command=args):
                command = [sys.executable, *args]
                self.plan['command'] = command
                self.plan['impact']['cases'][0]['command'] = command.copy()
                with self.assertRaisesRegex(ValueError, '測試模組|測試檔'):
                    self.invoke()
        self.assertFalse(self.counter.exists())

    def test_實際環境指紋不依賴計畫文字(self):
        self.invoke()
        with patch.object(gate.platform, 'platform', return_value='不同作業系統'):
            self.assertEqual(self.invoke()[1]['decision'], 'EXECUTED')
        self.assertEqual(self.counter.read_text(), '2')


if __name__ == '__main__':
    unittest.main()
