"""僅正規化完整驗證計畫路徑，授權與執行決策由共用 gate 負責。"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--workspace-root', required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    workspace = Path(args.workspace_root).resolve(strict=True)
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
    if plan.get('scope') != 'full':
        raise ValueError('完整入口只接受明列 full 範圍的計畫。')
    cwd = Path(plan.get('cwd', root))
    if not cwd.is_absolute():
        cwd = root / cwd
    plan['cwd'] = str(cwd.resolve(strict=True))
    executable = shutil.which(plan['command'][0])
    if executable is None:
        raise ValueError('找不到計畫指定執行檔。')
    plan['command'][0] = executable
    plan['inputs'] = [str((Path(value) if Path(value).is_absolute() else cwd / value).resolve(strict=True)) for value in plan['inputs']]
    evidence = Path(plan['evidence_dir'])
    plan['evidence_dir'] = str(evidence if evidence.is_absolute() else workspace / evidence)
    location = Path(__file__).with_name('verification_gate.py')
    spec = importlib.util.spec_from_file_location('shared_verification_gate', location)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    # 輸入 JSON 不改寫；正規化副本只留在指定證據父目錄的暫存子目錄。
    with tempfile.TemporaryDirectory(prefix='full-plan-', dir=workspace) as temporary:
        normalized = Path(temporary) / '完整計畫.json'
        normalized.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        return gate.main(normalized, workspace_root=workspace)


if __name__ == '__main__':
    raise SystemExit(main())
