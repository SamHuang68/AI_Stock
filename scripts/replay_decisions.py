#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay deterministic DecisionContext fixtures without network access."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import decision_context as dc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description='Replay Stock Terminal DecisionContext fixtures')
    ap.add_argument('--input', default=str(ROOT / 'tests' / 'fixtures' / 'decision_replay.json'))
    ap.add_argument('--output', help='optional JSON result path')
    args = ap.parse_args()
    cases = json.loads(Path(args.input).read_text(encoding='utf-8'))
    pulses = [x.get('pulse') or {} for x in cases]
    result = dc.replay(pulses)
    rows = []
    failed = 0
    for case, context in zip(cases, result['contexts']):
        actual = (context.get('regime') or {}).get('id')
        expected = case.get('expectedRegime')
        ok = expected == actual
        failed += 0 if ok else 1
        rows.append({'name': case.get('name'), 'expected': expected, 'actual': actual, 'ok': ok,
                     'confidence': (context.get('regime') or {}).get('confidence')})
        print(('[OK] ' if ok else '[FAIL] ') + f"{case.get('name')}: {actual} (expected {expected})")
    output = {'ok': failed == 0, 'rows': rows, 'transitions': result['transitions']}
    if args.output:
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
