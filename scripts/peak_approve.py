#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record Host approval for st-peak-v0.1 FACT binding (T3).

Usage (PowerShell, from repo root):

  python scripts/peak_approve.py record `
    --evidence-hash <sha256> `
    --by "Sam" `
    --symbol 2330 `
    --as-of 2026-01-03 `
    --note "Reviewed PIT bars"

  python scripts/peak_approve.py lookup --evidence-hash <sha256>

Approvals persist under ``data/peak_approvals/`` (gitignored).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import peak_approvals as pa  # noqa: E402


def _cmd_record(args: argparse.Namespace) -> int:
    result = pa.record_approval(
        args.evidence_hash,
        approved_by=args.by,
        symbol=args.symbol,
        as_of=args.as_of,
        price_basis=args.price_basis,
        knowledge_cutoff=args.knowledge_cutoff,
        generation_id=args.generation_id,
        approval_note=args.note,
        base_dir=args.base_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_lookup(args: argparse.Namespace) -> int:
    row = pa.get_approval(args.evidence_hash, base_dir=args.base_dir)
    if not row:
        print(json.dumps({'found': False}, ensure_ascii=False))
        return 1
    print(json.dumps({'found': True, **row}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='st-peak-v0.1 Host approval binder (T3)')
    ap.add_argument('--base-dir', help='optional repo root override (tests / alternate data dir)')
    sub = ap.add_subparsers(dest='command', required=True)

    record = sub.add_parser('record', help='append Host approval for an evidenceHash')
    record.add_argument('--evidence-hash', required=True)
    record.add_argument('--by', required=True, help='Host approver id (e.g. Sam)')
    record.add_argument('--symbol')
    record.add_argument('--as-of')
    record.add_argument('--price-basis')
    record.add_argument('--knowledge-cutoff')
    record.add_argument('--generation-id')
    record.add_argument('--note')
    record.set_defaults(func=_cmd_record)

    lookup = sub.add_parser('lookup', help='fetch approval by evidenceHash')
    lookup.add_argument('--evidence-hash', required=True)
    lookup.set_defaults(func=_cmd_lookup)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == '__main__':
    raise SystemExit(main())
