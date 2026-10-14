"""依明列變更選擇案例；內容與環境相同才沿用成功證據，絕不隱式全掃描。"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import time

SCHEMA = 1
LOADED_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def gate_module():
    location = Path(__file__).with_name('verification_gate.py')
    spec = importlib.util.spec_from_file_location('shared_verification_gate', location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.quotepath=false', *args], cwd=root).decode('utf-8').strip()


def relative(value):
    require(isinstance(value, str) and value and '\\' not in value, '輸入必須是明列的相對路徑。')
    path = PurePosixPath(value)
    require(not path.is_absolute() and not any(p in ('..', '.') for p in value.split('/'))
            and ':' not in value and not any(c in value for c in '*?['), '不接受根目錄、萬用字元或越界輸入。')
    return value


def resolve_input(root, name):
    path = root / relative(name)
    require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), '驗證輸入不可越界或使用連結。')
    require(path.is_file(), '驗證輸入不存在：' + name)
    return path


def case_command(root, case):
    targets = case.get('targets')
    require(isinstance(targets, list) and targets and all(isinstance(t, str) and t for t in targets), '案例必須明列測試目標。')
    kind = case.get('kind')
    if kind == 'unittest':
        for target in targets:
            require(all(p.isidentifier() for p in target.split('.')) and target != 'discover',
                    '只允許明列 unittest 模組或案例，不接受 discovery。')
            parts = target.split('.')
            while parts and not (root / ('/'.join(parts) + '.py')).is_file():
                parts.pop()
            require(parts and '/'.join(parts) + '.py' in case['inputs'], '測試模組必須列入輸入。')
        return [sys.executable, '-B', '-m', 'unittest', *targets, '-b']
    if kind == 'node':
        require(len(targets) == 1 and targets[0].endswith(('.js', '.cjs', '.mjs')),
                'Node 案例只能指定一個既有測試檔。')
        require(targets[0] in case['inputs'], 'Node 測試必須列入輸入。')
        node = shutil.which('node')
        require(node, '缺少 Node.js，未啟動驗證。')
        return [node, targets[0]]
    require(kind == 'syntax' and all(t in case['inputs'] for t in targets), '不支援的案例類型或缺少語法輸入。')
    require(all(t.endswith('.py') for t in targets), '語法檢查僅解析明列 Python 檔案。')
    return ['syntax', *targets]


def read_plan(root, plan_path, *, base_root=None, target_commit=None):
    root = Path(root).resolve()
    context = Path(base_root or root).resolve()
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    require(plan.get('schemaVersion') == SCHEMA and plan.get('scope') == 'targeted', '此入口只接受有變更依據的局部驗證計畫。')
    require(isinstance(plan.get('project'), str) and plan['project'].strip(), '必須明列穩定的專案識別。')
    require(not os.environ.get('GITHUB_REPOSITORY') or plan['project'] == os.environ['GITHUB_REPOSITORY'], '計畫專案與 GitHub 倉庫不符。')
    base = plan.get('baseCommit', '')
    require(re.fullmatch('[0-9a-f]{40}', base), '必須明列完整基底提交。')
    commit = git(context, 'rev-parse', target_commit or 'HEAD')
    subprocess.run(['git', 'merge-base', '--is-ancestor', base, commit], cwd=context, check=True, capture_output=True)
    expected_base = os.environ.get('VALIDATION_BASE')
    require(not expected_base or expected_base == base, '計畫基底與此次 PR／push 基底不同，請更新影響範圍。')
    changed = set(filter(None, git(context, 'diff', '--name-only', '--no-renames', base, commit).splitlines()))
    # 未提交候選也必須列入影響範圍；stage 的執行樹來自指定 archive。
    if target_commit is None:
        changed.update(filter(None, git(context, 'diff', '--name-only', '--no-renames', 'HEAD').splitlines()))
        changed.update(filter(None, git(context, 'ls-files', '--others', '--exclude-standard').splitlines()))
    ignored = plan.get('documentation', [])
    require(isinstance(ignored, list), '文件清單必須明列。')
    for name in ignored:
        relative(name)
        require(name.endswith('.md'),
                '只有明列文件可免執行程式測試。')
    cases = plan.get('cases')
    require(isinstance(cases, list) and cases, '必須明列案例，不能用空計畫通過。')
    covered = set(ignored)
    if Path(plan_path).resolve().is_relative_to(root):
        # 計畫本身由本函式每次重新核對，不以另一個測試形成遞迴相依。
        covered.add(Path(plan_path).resolve().relative_to(root).as_posix())
    identifiers = set()
    for case in cases:
        require(isinstance(case, dict) and isinstance(case.get('id'), str) and case['id'] not in identifiers, '案例識別不可重複。')
        identifiers.add(case['id'])
        case['_project'] = plan['project']
        require(isinstance(case.get('reason'), str) and case['reason'].strip(), '每項案例必須說明受影響契約。')
        impacts = case.get('changes')
        inputs = case.get('inputs')
        require(isinstance(impacts, list) and impacts and isinstance(inputs, list) and inputs, '案例必須明列變更與全部受測依賴。')
        for name in impacts + inputs:
            relative(name)
        deleted = case.get('deletedFiles', [])
        require(isinstance(deleted, list), '刪檔必須明列受影響消費端。')
        deleted_names = set()
        for item in deleted:
            require(isinstance(item, dict) and isinstance(item.get('reason'), str) and item['reason'].strip(), '刪檔必須說明仍須驗證的契約。')
            name, consumer = relative(item['path']), relative(item['consumer'])
            require(name in impacts and not (root / name).exists() and consumer in inputs, '刪檔映射與實際變更或受測輸入不符。')
            deleted_names.add(name)
        require(set(impacts) <= set(inputs) | deleted_names, '受影響檔案必須納入內容識別或明確刪檔映射。')
        require(set(impacts) & changed, '案例與本次變更沒有交集，禁止無關驗證：' + case['id'])
        require(type(case.get('timeoutSeconds')) is int and 0 < case['timeoutSeconds'] <= 600, '局部案例必須有不超過 600 秒的明確上限。')
        for name in inputs:
            resolve_input(root, name)
        preparation = case.get('prepare', [])
        require(isinstance(preparation, list) and set(preparation) <= {'node', 'browser', 'research'}, '不支援的環境準備項目。')
        if 'browser' in preparation:
            require({'package.json', 'package-lock.json'} <= set(inputs), '瀏覽器案例須納入套件與鎖檔。')
        if 'research' in preparation:
            require('requirements-research.txt' in inputs, '研究案例須納入依賴鎖檔。')
        command = case_command(root, case)
        absolute_inputs = [str(root / name) for name in inputs]
        absolute_changes = [str(root / name) for name in impacts]
        gate_module().validate_impact({'impact': {'changed_files': absolute_changes,
            'contracts': [case['reason']], 'cases': [{'id': case['id'], 'command': command,
            'inputs': absolute_inputs, 'changed_files': absolute_changes,
            'deleted_files': [{'path': str(root / item['path']), 'consumer': str(root / item['consumer']), 'reason': item['reason']}
                              for item in deleted]}]}}, command, absolute_inputs, root)
        covered.update(impacts)
    require(not changed - covered, '尚未對應驗證的變更，拒絕自動擴成全套：' + ', '.join(sorted(changed - covered)))
    plan['_context'] = {'baseCommit': base, 'commit': commit, 'tree': git(context, 'rev-parse', commit + '^{tree}'), 'changedFiles': sorted(changed)}
    plan.update(plan['_context'])
    return plan


def environment(root, case):
    result = {'os': platform.system(), 'machine': platform.machine(), 'python': platform.python_version(),
              'pythonExecutable': file_hash(sys.executable), 'implementation': platform.python_implementation(),
              'variables': {key: os.environ.get(key, '') for key in case.get('environmentKeys', [])}}
    if case['kind'] == 'node':
        result['node'] = subprocess.check_output([shutil.which('node'), '--version']).decode().strip()
        result['nodeExecutable'] = file_hash(shutil.which('node'))
    return result


def identity_for(root, case):
    # 提交 SHA、工作樹路徑、PR 編號不是測試輸入；不使相同內容失效。
    require(file_hash(__file__) == LOADED_SOURCE_SHA, '驗證器執行期間已變更，拒絕混用版本。')
    return {'schemaVersion': SCHEMA, 'runner': LOADED_SOURCE_SHA,
            'gate': file_hash(Path(__file__).with_name('verification_gate.py')),
            'case': case['id'], 'project': case['_project'],
            'kind': case['kind'], 'targets': case['targets'],
            'deletedFiles': sorted(item['path'] for item in case.get('deletedFiles', [])),
            'inputs': {name: file_hash(resolve_input(root, name)) for name in sorted(set(case['inputs']))},
            'environment': environment(root, case)}


def run_plan(root, plan_path, evidence_dir, *, base_root=None, target_commit=None):
    root = Path(root).resolve()
    plan = read_plan(root, plan_path, base_root=base_root, target_commit=target_commit)
    evidence = Path(evidence_dir).resolve()
    require(not evidence.is_relative_to(root), '證據應存放受測樹之外，避免變更受測輸入。')
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    for case in plan['cases']:
        identity = identity_for(root, case)
        key = digest(identity)
        receipt_path = evidence / (key + '.json')
        active = evidence / (key + '.active')
        require(not active.exists(), '已有尚未結束的相同驗證，不另啟程序。')
        prior = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.is_file() else None
        if receipt_path.exists():
            require(isinstance(prior, dict) and all(k in prior for k in ('identity', 'fingerprint', 'id', 'command', 'inputs', 'environment', 'commit', 'status', 'exitCode')),
                    '既有驗證收據格式不完整，拒絕重跑或沿用。')
            require(prior.get('identity') == identity and prior.get('fingerprint') == key, '既有驗證證據內容不符。')
            require(prior['id'] == case['id'] and prior['inputs'] == identity['inputs'] and prior['environment'] == identity['environment']
                    and isinstance(prior['command'], list) and prior['command'], '既有驗證收據案例或命令不完整。')
            require(prior.get('exitCode') == 0 and prior.get('status') == 'passed', '前次驗證失敗；先修正輸入，不原樣重跑。')
            results.append(dict(prior, decision='REUSE'))
            continue
        command = case_command(root, case)
        started = time.time()
        with active.open('x', encoding='utf-8') as handle:
            json.dump({'identity': identity, 'startedAt': started}, handle, ensure_ascii=False)
        result = {'id': case['id'], 'decision': 'EXECUTED', 'fingerprint': key, 'identity': identity,
                  'inputs': identity['inputs'], 'environment': identity['environment'], 'command': command,
                  'commit': plan['_context']['commit'], 'evidence': str(receipt_path)}
        try:
            if command[0] == 'syntax':
                for name in case['targets']:
                    ast.parse((root / name).read_text(encoding='utf-8-sig'), filename=name)
                code = 0
            else:
                with (evidence / (key + '.log')).open('wb') as output:
                    process = subprocess.Popen(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'),
                                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    active.write_text(json.dumps({'pid': process.pid, 'startedAt': started, 'identity': identity}), encoding='utf-8')
                    code = process.wait(timeout=case['timeoutSeconds'])
            require(identity_for(root, case) == identity, '驗證期間輸入改變，拒絕保存成功。')
            result.update(exitCode=code, status='passed' if code == 0 else 'failed', elapsedSeconds=round(time.time() - started, 3))
            receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            require(code == 0, '局部驗證失敗，請讀取紀錄：' + str(evidence / (key + '.log')))
        except subprocess.TimeoutExpired:
            # 保留 active 與原程序，禁止逾時後再啟一份。
            raise RuntimeError('局部驗證逾時；保留原程序及 active 紀錄，禁止盲目重跑。')
        except Exception as error:
            result.update(exitCode=1, status='failed', error=str(error), elapsedSeconds=round(time.time() - started, 3))
            receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            active.unlink(missing_ok=True)
            raise
        else:
            active.unlink()
        results.append(result)
    return {'schemaVersion': SCHEMA, 'status': 'passed', **plan['_context'], 'cases': results}


def restore_ci_receipts(evidence, artifact_name):
    """取同倉庫已完成 ci 的案例收據；成功可沿用，失敗紀錄保留以阻擋盲目重跑。"""
    repository = os.environ.get('GITHUB_REPOSITORY')
    require(repository and os.environ.get('GH_TOKEN'), '缺少 GitHub 證據讀取環境。')
    response = subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/workflows/ci.yml/runs?status=completed&per_page=20'])
    runs = json.loads(response)['workflow_runs']
    for run in runs:
        if (run.get('conclusion') not in ('success', 'failure') or run.get('event') not in ('push', 'pull_request')
                or (run.get('head_repository') or {}).get('full_name') != repository):
            continue
        listing = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/runs/{run["id"]}/artifacts']))
        if not any(a['name'] == artifact_name and not a['expired'] for a in listing['artifacts']):
            continue
        destination = evidence.parent / ('匯入-' + str(run['id']))
        subprocess.run(['gh', 'run', 'download', str(run['id']), '--repo', repository, '--name', artifact_name, '--dir', str(destination)], check=True)
        evidence.mkdir(parents=True, exist_ok=True)
        for path in destination.iterdir():
            if not re.fullmatch('[0-9a-f]{64}\\.(json|active)', path.name):
                continue
            # 不丟棄失敗／毀損／進行中紀錄來製造「沒有證據」；
            # run_plan 對命中指紋的收據做嚴格核對，只有成功可以 REUSE。
            target = evidence / path.name
            if not target.exists():
                target.write_bytes(path.read_bytes())
        # 最近一個同平台收據已包含本次之前沿用的成功案例，避免下載多份。
        break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', default='.github/驗證計畫.json')
    parser.add_argument('--evidence-dir', required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--restore-ci', metavar='ARTIFACT')
    args = parser.parse_args()
    root = Path.cwd()
    if args.check:
        plan = read_plan(root, root / args.plan)
        preparation = {item for case in plan['cases'] for item in case.get('prepare', [])}
        if any(c['kind'] == 'node' for c in plan['cases']) or 'browser' in preparation:
            preparation.add('node')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
                for name in ('node', 'browser', 'research'):
                    handle.write(name + '=' + str(name in preparation).lower() + '\n')
        print(json.dumps({'status': 'planned', **plan['_context'], 'cases': [c['id'] for c in plan['cases']]}, ensure_ascii=False))
        return
    if args.restore_ci:
        restore_ci_receipts(Path(args.evidence_dir).resolve(), args.restore_ci)
    result = run_plan(root, root / args.plan, args.evidence_dir)
    Path(args.evidence_dir, '執行收據.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'cases': [{'id': c['id'], 'decision': c['decision']} for c in result['cases']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
