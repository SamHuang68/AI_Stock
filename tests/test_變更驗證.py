"""只驗證案例選擇、證據沿用與 CI 接線；使用獨立小型 Git fixture。"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('change_validation', ROOT / 'tools/codex/變更驗證.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class 變更驗證測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / '非ST專案'
        self.root.mkdir()
        self.evidence = self.base / '證據'
        self.env = patch.dict(os.environ, {'VALIDATION_BASE': '', 'GITHUB_REPOSITORY': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', '流程驗證')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(self.base / '無hook'))
        (self.root / '功能.py').write_text('VALUE = 1\n', encoding='utf-8')
        (self.root / '測試.py').write_text('import unittest\nfrom pathlib import Path\nclass T(unittest.TestCase):\n def test_one(self):\n  p=Path(__file__).parent.parent / "執行次數.txt"\n  p.write_text(str(int(p.read_text())+1) if p.exists() else "1")\n  self.assertTrue(True)\n', encoding='utf-8')
        self.git('add', '--', '功能.py', '測試.py')
        self.git('commit', '-qm', '基準')
        base_commit = self.git('rev-parse', 'HEAD')
        (self.root / '功能.py').write_text('VALUE = 2\n', encoding='utf-8')
        self.plan = {'schemaVersion': 1, 'scope': 'targeted', 'project': '流程fixture', 'baseCommit': base_commit,
                     'documentation': [], 'cases': [{'id': '指定案例', 'reason': '功能變更影響指定契約',
                     'kind': 'unittest', 'targets': ['測試.T.test_one'], 'changes': ['功能.py'],
                     'inputs': ['功能.py', '測試.py'], 'timeoutSeconds': 10}]}
        self.plan_path = self.root / '驗證計畫.json'

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL).decode('utf-8').strip()

    def save(self):
        self.plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding='utf-8')

    def run_plan(self):
        self.save()
        return engine.run_plan(self.root, self.plan_path, self.evidence)

    def test_只執行明列案例且跨提交沿用相同內容(self):
        first = self.run_plan()
        self.assertEqual(first['cases'][0]['decision'], 'EXECUTED')
        self.git('add', '--', '功能.py', '驗證計畫.json')
        self.git('commit', '-qm', '提交相同內容')
        second = self.run_plan()
        self.assertEqual(second['cases'][0]['decision'], 'REUSE')
        self.assertNotEqual(first['commit'], second['commit'])
        self.assertEqual(first['cases'][0]['fingerprint'], second['cases'][0]['fingerprint'])
        self.assertEqual((self.base / '執行次數.txt').read_text(), '1')

    def test_輸入變更使證據失效(self):
        first = self.run_plan()
        (self.root / '功能.py').write_text('VALUE = 3\n', encoding='utf-8')
        second = self.run_plan()
        self.assertEqual(second['cases'][0]['decision'], 'EXECUTED')
        self.assertNotEqual(first['cases'][0]['fingerprint'], second['cases'][0]['fingerprint'])

    def test_環境及專案識別隔離(self):
        first = self.run_plan()
        self.plan['project'] = '另一個非ST專案'
        second = self.run_plan()
        self.assertNotEqual(first['cases'][0]['fingerprint'], second['cases'][0]['fingerprint'])
        with patch.object(engine.platform, 'system', return_value='另一個作業系統'):
            self.assertEqual(self.run_plan()['cases'][0]['decision'], 'EXECUTED')

    def test_未對應變更及無關案例拒絕(self):
        (self.root / '未對應.py').write_text('x=1\n')
        with self.assertRaisesRegex(ValueError, '尚未對應'):
            self.run_plan()
        (self.root / '未對應.py').unlink()
        self.plan['cases'][0]['changes'] = ['測試.py']
        with self.assertRaisesRegex(ValueError, '沒有交集'):
            self.run_plan()
        self.assertFalse(self.evidence.exists())

    def test_拒絕discovery與越界及缺少測試輸入(self):
        original = copy.deepcopy(self.plan)
        for targets, inputs in [(['discover'], ['功能.py', '測試.py']), (['測試.T.test_one'], ['功能.py']),
                                (['測試.T.test_one'], ['功能.py', '../越界.py'])]:
            self.plan = copy.deepcopy(original)
            self.plan['cases'][0].update(targets=targets, inputs=inputs)
            with self.assertRaises(ValueError):
                self.run_plan()

    def test_空白或毀損成功收據不可重跑(self):
        result = self.run_plan()
        receipt = Path(result['cases'][0]['evidence'])
        for value in ({}, [], None, {'status': 'passed'}):
            receipt.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '格式不完整'):
                self.run_plan()

    def test_失敗及進行中證據不重跑(self):
        result = self.run_plan()
        receipt_path = Path(result['cases'][0]['evidence'])
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt.update(exitCode=1, status='failed')
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '前次驗證失敗'):
            self.run_plan()
        receipt_path.with_suffix('.active').write_text('執行中', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '尚未結束'):
            self.run_plan()

    def test_基底不符拒絕(self):
        with patch.dict(os.environ, {'VALIDATION_BASE': 'b' * 40}):
            with self.assertRaisesRegex(ValueError, '基底不同'):
                self.run_plan()

    def test_刪檔明列消費端且檔案復原時拒絕(self):
        (self.root / '功能.py').unlink()
        case = self.plan['cases'][0]
        case['inputs'] = ['測試.py']
        case['deletedFiles'] = [{'path': '功能.py', 'consumer': '測試.py', 'reason': '呼叫端維持刪檔後契約'}]
        self.assertEqual(self.run_plan()['cases'][0]['decision'], 'EXECUTED')
        (self.root / '功能.py').write_text('VALUE = 2\n')
        with self.assertRaisesRegex(ValueError, '刪檔映射'):
            self.run_plan()

    def test_CI可沿用失敗工作流中的成功案例且拒絕外部分支(self):
        runs = [
            {'id': 1, 'conclusion': 'success', 'event': 'pull_request', 'head_repository': {'full_name': '外部/專案'}},
            {'id': 2, 'conclusion': 'cancelled', 'event': 'push', 'head_repository': {'full_name': '本機/專案'}},
            {'id': 3, 'conclusion': 'failure', 'event': 'pull_request', 'head_repository': {'full_name': '本機/專案'}},
        ]
        imported = {'status': 'passed', 'exitCode': 0, 'identity': {'fixture': '既有收據'}}
        imported['fingerprint'] = engine.digest(imported['identity'])

        def download(command, **kwargs):
            self.assertEqual(command[3], '3')
            destination = Path(command[-1])
            destination.mkdir()
            (destination / (imported['fingerprint'] + '.json')).write_text(json.dumps(imported), encoding='utf-8')
            (destination / '執行收據.json').write_text('{}', encoding='utf-8')
            (destination / ('a' * 64 + '.json')).write_text(json.dumps({'status': 'failed', 'exitCode': 1}), encoding='utf-8')

        responses = [json.dumps({'workflow_runs': runs}).encode(),
                     json.dumps({'artifacts': [{'name': '平台證據', 'expired': False}]}).encode()]
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': '本機/專案', 'GH_TOKEN': '假權限'}), \
                patch.object(engine.subprocess, 'check_output', side_effect=responses) as api, \
                patch.object(engine.subprocess, 'run', side_effect=download) as download_call:
            engine.restore_ci_receipts(self.evidence, '平台證據')
        self.assertEqual(api.call_count, 2)
        self.assertEqual(download_call.call_count, 1)
        self.assertEqual([p.name for p in self.evidence.iterdir()], [imported['fingerprint'] + '.json'])

    def test_CI自動路徑只走局部計畫_完整路徑僅明確授權(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('scripts/變更驗證.py --check', ci)
        self.assertIn('--restore-ci', ci)
        self.assertNotIn('unittest discover', ci)
        self.assertNotIn('npm run test:', ci)
        for line in ('if: steps.plan.outputs.browser', 'if: steps.plan.outputs.research'):
            self.assertIn(line, ci)
        full = (ROOT / '.github/workflows/完整驗證.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', full)
        self.assertNotIn('  push:', full)
        self.assertNotIn('  pull_request:', full)
        self.assertIn('needs: authorization', full)
        self.assertIn('necessity:', full)


if __name__ == '__main__':
    unittest.main()
