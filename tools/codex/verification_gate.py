"""依明列計畫執行驗證；完整驗證需授權依據，相同成功輸入直接重用。"""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text(value):
    return isinstance(value, str) and bool(value.strip())


def reject_broad_targeted(command):
    """只辨識已知危險入口；不宣稱能理解任意 shell 或腳本內容。"""
    names = [Path(value).name.lower() for value in command]
    lower = [value.lower() for value in command]
    executable = names[0].removesuffix('.exe')
    require(executable not in ('cmd', 'powershell', 'pwsh', 'sh', 'bash', 'zsh'),
            'targeted 不接受 shell 包裝；請展開為各案例的直接 command。')
    require(not any(name in ('verification_gate.py', 'private_web_release.py', 'deploy.ps1', 'stage.ps1')
                    for name in names[1:]) and 'stage' not in lower,
            'targeted 不接受直接 stage、部署或巢狀 gate；請使用已核對的局部計畫並展開案例 command。')
    if executable.startswith('python'):
        require('-c' not in lower and '-' not in lower, 'targeted 不接受內嵌 Python；請使用明列於 inputs 的案例檔。')
    if executable == 'node':
        require(not any(value in ('-e', '--eval', '-p', '--print', '-') or value.startswith('--eval=')
                        for value in lower[1:]), 'targeted 不接受內嵌 Node；請展開明列案例。')
    if 'unittest' in lower:
        args = command[lower.index('unittest') + 1:]
        require('discover' not in args and not any(value in ('tests', 'tests/', 'tests\\', '.') for value in args)
                and any(not value.startswith('-') for value in args),
                'unittest discover 或未指定案例不是局部驗證。')
    if 'pytest' in lower or executable in ('pytest', 'py.test'):
        start = lower.index('pytest') + 1 if 'pytest' in lower else 1
        args = command[start:]
        options_with_values = ('-c', '--confcutdir', '--rootdir', '--ignore', '--ignore-glob',
                               '--deselect', '--override-ini', '-o', '--junitxml', '--log-file')
        selectors = any(not value.startswith('-') and (i == 0 or args[i - 1] not in options_with_values)
                        and value.split('::')[0].endswith('.py') for i, value in enumerate(args))
        selectors = selectors or any(value in ('-k', '-m') and i + 1 < len(args)
                                    and not args[i + 1].startswith('-') for i, value in enumerate(args))
        require(selectors, 'pytest 必須明列案例檔、節點或選擇條件；目錄與預設全套不屬局部驗證。')
    if executable.removesuffix('.cmd') in ('npm', 'npx', 'pnpm', 'yarn'):
        require(len(lower) > 1 and lower[1] == 'test' and '--' in lower
                and lower.index('--') + 1 < len(lower),
                '套件 wrapper 必須展開直接案例 command；npm test 至少須有 -- 後的明確 selector。')
        selected = lower[lower.index('--') + 1:]
        require(any(not value.startswith('-') and ('.test.' in value or '.spec.' in value or '::' in value)
                    for value in selected)
                or any(value in ('--testnamepattern', '-t', '--testpathpattern') and i + 1 < len(selected)
                       and not selected[i + 1].startswith('-') for i, value in enumerate(selected)),
                'npm test 只有選項並非明確案例 selector。')


def validate_impact(plan, command, inputs, cwd):
    impact = plan.get('impact')
    require(isinstance(impact, dict), '舊 targeted 計畫必須遷移：新增 impact.changed_files、contracts 與 cases，不接受只有 reason。')
    changed = impact.get('changed_files')
    contracts = impact.get('contracts')
    cases = impact.get('cases')
    require(isinstance(changed, list) and changed and all(text(p) and Path(p).is_absolute() for p in changed),
            'impact.changed_files 必須列變更檔案的絕對路徑；刪除檔案也須保留路徑。')
    require(isinstance(contracts, list) and contracts and all(text(v) for v in contracts), 'impact.contracts 必須列受影響契約。')
    require(isinstance(cases, list) and cases, 'impact.cases 必須列案例及其 exact command 與 inputs。')
    normalized_inputs = {str(Path(p).resolve(strict=True)) for p in inputs}
    normalized_changed = {str(Path(p).resolve()) for p in changed}
    matches = []
    for case in cases:
        require(isinstance(case, dict) and text(case.get('id')) and isinstance(case.get('command'), list)
                and case['command'] and all(text(v) for v in case['command']), '每個案例必須有 id 與完整 command。')
        case_inputs = case.get('inputs')
        require(isinstance(case_inputs, list) and case_inputs
                and all(text(p) and Path(p).is_absolute() for p in case_inputs), '每個案例必須明列 inputs 絕對路徑。')
        normalized_case_inputs = {str(Path(p).resolve(strict=True)) for p in case_inputs}
        require(normalized_case_inputs <= normalized_inputs,
                '案例 inputs 必須全部納入計畫 inputs。')
        case_changed = case.get('changed_files')
        require(isinstance(case_changed, list) and case_changed
                and all(text(p) and Path(p).is_absolute() for p in case_changed),
                '案例 changed_files 必須明列非空變更檔案絕對路徑。')
        normalized_case_changed = {str(Path(p).resolve()) for p in case_changed}
        require(normalized_case_changed <= normalized_changed,
                '案例 changed_files 必須是 impact.changed_files 的子集合。')
        deleted = case.get('deleted_files', [])
        require(isinstance(deleted, list), '案例 deleted_files 必須是明列刪檔映射的陣列。')
        mapped = set()
        for item in deleted:
            require(isinstance(item, dict) and text(item.get('path')) and Path(item['path']).is_absolute()
                    and text(item.get('consumer')) and Path(item['consumer']).is_absolute()
                    and text(item.get('reason')), '刪檔映射必須明列 path、consumer 絕對路徑及必要理由 reason。')
            deleted_path = str(Path(item['path']).resolve())
            require(deleted_path in normalized_case_changed and not Path(deleted_path).exists(),
                    '刪檔映射只接受本案例 changed_files 中確實不存在的檔案。')
            consumer = Path(item['consumer']).resolve(strict=True)
            require(consumer.is_file() and str(consumer) in normalized_case_inputs,
                    '刪檔的受影響 consumer 必須存在並納入本案例 inputs。')
            mapped.add(deleted_path)
        require(normalized_case_changed <= normalized_case_inputs | mapped,
                '變更與案例輸入沒有完整對應：存在的變更檔必須納入本案例 inputs；刪檔須有明確 consumer 映射。')
        reject_broad_targeted(case['command'])
        if case['command'] == command:
            matches.append(case)
    require(len(matches) == 1, '本次 command 必須 exact 對應 impact.cases 中唯一案例。')
    for argument in command[1:]:
        candidate = Path(argument.split('::', 1)[0])
        if not candidate.is_absolute():
            candidate = cwd / candidate
        if candidate.suffix.lower() in ('.py', '.js', '.mjs', '.cjs', '.ps1') and candidate.is_file():
            require(str(candidate.resolve()) in {str(Path(p).resolve()) for p in matches[0]['inputs']},
                    '直接指定的 runner 或測試檔必須納入匹配案例 inputs。')
    if 'unittest' in command:
        selectors = command[command.index('unittest') + 1:]
        skip_value = False
        for selector in selectors:
            if skip_value:
                skip_value = False
                continue
            if selector in ('-k', '--durations'):
                skip_value = True
                continue
            if selector.startswith('-'):
                continue
            candidate = cwd / selector
            if not candidate.is_file():
                parts = selector.split('.')
                candidate = None
                for count in range(len(parts), 0, -1):
                    path = cwd.joinpath(*parts[:count]).with_suffix('.py')
                    if path.is_file():
                        candidate = path
                        break
            require(candidate is not None and candidate.is_file(),
                    'unittest 案例必須能從 cwd 定位實際測試模組檔，請改用明確模組或檔案。')
            require(str(candidate.resolve()) in {str(Path(p).resolve()) for p in matches[0]['inputs']},
                    'unittest 命令的實際測試模組必須納入匹配案例 inputs。')
    return matches[0]['id']


def main(plan_path, workspace_root=None):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    require(plan.get('scope') in ('targeted', 'full'), '必須明列 targeted 或 full 範圍。')
    require(text(plan.get('reason')), '必須說明本次驗證與變更／失敗的關係。')
    command = plan.get('command')
    require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command), 'command 必須是非空參數陣列。')
    require(Path(command[0]).is_absolute() and Path(command[0]).is_file(), '執行檔必須是已存在的絕對路徑。')
    cwd = Path(plan['cwd']).resolve(strict=True)
    require(cwd.is_dir(), '工作目錄不存在。')
    inputs = plan.get('inputs')
    require(isinstance(inputs, list) and inputs and all(isinstance(x, str) and Path(x).is_absolute() for x in inputs), '必須明列完整受影響輸入、測試與設定檔的絕對路徑。')
    require(text(plan.get('environment')), '必須記錄 Python／Node／作業系統等相關環境識別。')
    require(text(plan.get('artifact')), '必須明列提交或實際候選產物識別。')
    require(text(plan.get('verification_id')), '必須明列穩定的 verification_id；不得隨提交 SHA 改名。')
    policy = plan.get('reuse_policy', 'success')
    require(policy in ('success', 'never'), 'reuse_policy 只接受 success 或 never。')
    mode = plan.get('mode', 'static')
    require(mode in ('static', 'live'), 'mode 只接受 static 或 live。')
    fresh = policy == 'never' or mode == 'live'
    if plan['scope'] == 'targeted':
        case_id = validate_impact(plan, command, inputs, cwd)
    else:
        case_id = None
        require(text(plan.get('full_necessity')), '完整驗證須說明 full_necessity：為何局部案例不足及其必要範圍。')
        consent = plan.get('full_consent', {})
        require(isinstance(consent, dict) and consent.get('explicit') is True
                and text(consent.get('user_quote')) and text(consent.get('source')),
                '完整驗證缺少 Sam 的明確授權原文與來源；命令未啟動。CI 環境變數不能代替授權。')
    require(type(plan.get('expected_seconds')) in (int, float) and plan['expected_seconds'] > 0, '必須估計耗時。')
    require(type(plan.get('timeout_seconds')) in (int, float) and plan['timeout_seconds'] >= plan['expected_seconds'], '必須設定不小於預估耗時的觀察上限。')
    root = Path(workspace_root or r'C:\Users\Sam\AI-Workspace').resolve(strict=True)
    output = Path(plan['evidence_dir']).resolve()
    require(output.is_relative_to(root) and output != root, '證據目錄必須位於 AI-Workspace 的子目錄。')
    fingerprints = {str(Path(p).resolve(strict=True)): sha(p) for p in sorted(set(inputs))}
    identity = {'command': command, 'cwd': str(cwd), 'inputs': fingerprints,
                'environment': plan['environment'], 'verification_id': plan['verification_id'],
                'runtime': {'python': sys.version, 'implementation': platform.python_implementation(),
                            'os': platform.platform(), 'machine': platform.machine(),
                            'gate_python': str(Path(sys.executable).resolve())},
                'case_id': case_id, 'executable': sha(command[0]), 'scope': plan['scope'], 'gate': sha(__file__)}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    latest = output / (key + '.latest.json')
    active = output / (key + '.active.json')
    require(not active.exists(), '同版本有未結束或尚未核對的執行紀錄；禁止重跑。')
    prior = json.loads(latest.read_text(encoding='utf-8')) if latest.is_file() else None
    rerun = plan.get('rerun')
    if prior:
        require(prior.get('identity') == identity, '既有收據與本次輸入不符。')
    if prior and prior.get('exit_code') == 0 and not rerun and not fresh:
        print(json.dumps({'decision': 'REUSE', 'message': '相同輸入及環境已通過，本次沒有執行命令。',
                          'artifact': plan['artifact'], 'verified_artifact': prior.get('artifact'), 'receipt': str(latest)}, ensure_ascii=False))
        return 0
    require(not prior or prior.get('exit_code') == 0 or rerun, '前次同版本失敗；須先讀失敗紀錄並提供新的重跑依據。')
    used = prior.get('used_evidence', []) if prior else []
    if rerun:
        require(isinstance(rerun, dict) and text(rerun.get('reason')) and text(rerun.get('evidence'))
                and Path(rerun['evidence']).is_absolute() and Path(rerun['evidence']).is_file(),
                '同版本重跑必須提供新的失敗或未解疑慮說明及證據檔絕對路徑。')
        evidence_hash = sha(rerun['evidence'])
        require(evidence_hash not in used, '相同的重跑證據已使用；禁止無新證據重複執行。')
        used = [*used, evidence_hash]
    output.mkdir(parents=True, exist_ok=True)
    with active.open('x', encoding='utf-8') as lock:
        lock.write(json.dumps({'identity': identity, 'started_at': time.time()}))
    if latest.is_file():
        current = json.loads(latest.read_text(encoding='utf-8'))
        if current != prior:
            active.unlink()
            raise ValueError('取得執行鎖前收據已更新，請重新判讀，不重複啟動。')
    run = output / ('run-' + time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    run.mkdir()
    record = {'identity': identity, 'reason': plan['reason'], 'expected_seconds': plan['expected_seconds'],
              'artifact': plan['artifact'], 'impact': plan.get('impact'), 'full_necessity': plan.get('full_necessity'),
              'reuse_policy': policy, 'mode': mode,
              'full_consent': plan.get('full_consent'), 'rerun': rerun, 'used_evidence': used,
              'run': str(run), 'started_at': time.time()}
    (run / 'started.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    with (run / 'stdout.log').open('wb') as stdout, (run / 'stderr.log').open('wb') as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            record['pid'] = process.pid
            (run / 'started.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            active.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            code = process.wait(timeout=plan['timeout_seconds'])
        except subprocess.TimeoutExpired:
            code = 124
            record['still_running'] = True
            record['message'] = '觀察逾時；保留程序與紀錄，不重跑、不按埠停止程序，也不記錄成功。'
        except OSError as error:
            code = 125
            record['message'] = '程序啟動失敗：' + str(error)
    record.update(exit_code=code, elapsed_seconds=round(time.time() - record['started_at'], 3))
    if code == 0:
        try:
            unchanged = (all(sha(p) == h for p, h in fingerprints.items())
                         and sha(command[0]) == identity['executable'] and sha(__file__) == identity['gate'])
        except OSError:
            unchanged = False
        if not unchanged:
            code = 1
            record.update(exit_code=code, message='執行期間輸入改變；未保存為相同版本成功收據。')
    (run / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    latest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    if not record.get('still_running'):
        active.unlink()
    print(json.dumps({'decision': 'EXECUTED', 'exit_code': code, 'evidence': str(run)}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2, '用法：python verification_gate.py <plan.json>')
        sys.exit(main(sys.argv[1]))
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({'decision': 'DENY', 'message': str(error)}, ensure_ascii=False))
        sys.exit(2)
