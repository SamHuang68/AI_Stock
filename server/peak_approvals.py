#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only Host approval store for st-peak-v0.1 FACT binding (T3).

Approvals bind a computed ``evidenceHash`` to a non-null ``hostApprovalHash``.
Runtime data lives under ``data/peak_approvals/`` (gitignored). Tests may pass
``base_dir`` to isolate storage.

See ``docs/ST_PEAK_V01.md`` §6 FACT binding.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Mapping

CONTRACT_ID = 'st-peak-v0.1'

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APPROVALS_DIR = os.path.join(_BASE, 'data', 'peak_approvals')
DB_PATH = os.path.join(APPROVALS_DIR, 'peak_approvals.db')

_WRITE_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS peak_approvals(
  approval_id TEXT PRIMARY KEY,
  contract_id TEXT NOT NULL,
  evidence_hash TEXT NOT NULL,
  host_approval_hash TEXT NOT NULL UNIQUE,
  symbol TEXT,
  as_of TEXT,
  price_basis TEXT,
  knowledge_cutoff TEXT,
  generation_id TEXT,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  approval_note TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_peak_approvals_evidence
  ON peak_approvals(contract_id, evidence_hash);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _approvals_db_path(base_dir: str | os.PathLike[str] | None = None) -> str:
    if base_dir is None:
        return DB_PATH
    return os.path.join(os.fspath(base_dir), 'data', 'peak_approvals', 'peak_approvals.db')


def get_conn(base_dir: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = _approvals_db_path(base_dir)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def init_db(base_dir: str | os.PathLike[str] | None = None) -> None:
    with _WRITE_LOCK:
        with closing(get_conn(base_dir)) as conn:
            with conn:
                conn.executescript(_SCHEMA)


def compute_host_approval_hash(
    *,
    contract_id: str,
    evidence_hash: str,
    approved_by: str,
    approved_at: str,
    approval_note: str | None = None,
) -> str:
    payload = {
        'contractId': contract_id,
        'evidenceHash': evidence_hash,
        'approvedBy': approved_by,
        'approvedAt': approved_at,
        'approvalNote': approval_note or '',
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def record_approval(
    evidence_hash: str,
    *,
    approved_by: str,
    contract_id: str = CONTRACT_ID,
    symbol: str | None = None,
    as_of: str | None = None,
    price_basis: str | None = None,
    knowledge_cutoff: str | None = None,
    generation_id: str | None = None,
    approval_note: str | None = None,
    approved_at: str | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Append a Host approval for ``evidence_hash`` (idempotent on same hash)."""
    evidence = str(evidence_hash or '').strip()
    if not evidence:
        raise ValueError('evidence_hash is required')
    approver = str(approved_by or '').strip()
    if not approver:
        raise ValueError('approved_by is required')

    init_db(base_dir)
    approved_at_iso = approved_at or _utc_now_iso()
    host_hash = compute_host_approval_hash(
        contract_id=contract_id,
        evidence_hash=evidence,
        approved_by=approver,
        approved_at=approved_at_iso,
        approval_note=approval_note,
    )
    approval_id = str(uuid.uuid4())

    with _WRITE_LOCK:
        with closing(get_conn(base_dir)) as conn:
            with conn:
                existing = conn.execute(
                    '''SELECT approval_id, host_approval_hash, approved_by, approved_at, approval_note
                       FROM peak_approvals WHERE contract_id = ? AND evidence_hash = ?''',
                    (contract_id, evidence),
                ).fetchone()
                if existing:
                    return {
                        'approvalId': existing['approval_id'],
                        'contractId': contract_id,
                        'evidenceHash': evidence,
                        'hostApprovalHash': existing['host_approval_hash'],
                        'approvedBy': existing['approved_by'],
                        'approvedAt': existing['approved_at'],
                        'approvalNote': existing['approval_note'],
                        'inserted': False,
                    }
                conn.execute(
                    '''INSERT INTO peak_approvals
                       (approval_id, contract_id, evidence_hash, host_approval_hash,
                        symbol, as_of, price_basis, knowledge_cutoff, generation_id,
                        approved_by, approved_at, approval_note)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (
                        approval_id,
                        contract_id,
                        evidence,
                        host_hash,
                        symbol,
                        as_of,
                        price_basis,
                        knowledge_cutoff,
                        generation_id,
                        approver,
                        approved_at_iso,
                        approval_note,
                    ),
                )
    return {
        'approvalId': approval_id,
        'contractId': contract_id,
        'evidenceHash': evidence,
        'hostApprovalHash': host_hash,
        'approvedBy': approver,
        'approvedAt': approved_at_iso,
        'approvalNote': approval_note,
        'inserted': True,
    }


def lookup_host_approval_hash(
    evidence_hash: str,
    *,
    contract_id: str = CONTRACT_ID,
    base_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return ``hostApprovalHash`` when Host approved this evidence hash."""
    evidence = str(evidence_hash or '').strip()
    if not evidence:
        return None
    init_db(base_dir)
    with closing(get_conn(base_dir)) as conn:
        row = conn.execute(
            'SELECT host_approval_hash FROM peak_approvals WHERE contract_id = ? AND evidence_hash = ?',
            (contract_id, evidence),
        ).fetchone()
    if not row:
        return None
    return str(row['host_approval_hash'])


def get_approval(
    evidence_hash: str,
    *,
    contract_id: str = CONTRACT_ID,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    evidence = str(evidence_hash or '').strip()
    if not evidence:
        return None
    init_db(base_dir)
    with closing(get_conn(base_dir)) as conn:
        row = conn.execute(
            '''SELECT approval_id, contract_id, evidence_hash, host_approval_hash,
                      symbol, as_of, price_basis, knowledge_cutoff, generation_id,
                      approved_by, approved_at, approval_note
               FROM peak_approvals WHERE contract_id = ? AND evidence_hash = ?''',
            (contract_id, evidence),
        ).fetchone()
    if not row:
        return None
    return {
        'approvalId': row['approval_id'],
        'contractId': row['contract_id'],
        'evidenceHash': row['evidence_hash'],
        'hostApprovalHash': row['host_approval_hash'],
        'symbol': row['symbol'],
        'asOf': row['as_of'],
        'priceBasis': row['price_basis'],
        'knowledgeCutoff': row['knowledge_cutoff'],
        'generationId': row['generation_id'],
        'approvedBy': row['approved_by'],
        'approvedAt': row['approved_at'],
        'approvalNote': row['approval_note'],
    }


def bind_fixture_approval(
    evidence_hash: str,
    *,
    approved_by: str = 'fixture-host',
    base_dir: str | os.PathLike[str] | None = None,
    **kwargs: Any,
) -> str:
    """Test helper: record approval and return ``hostApprovalHash``."""
    result = record_approval(
        evidence_hash,
        approved_by=approved_by,
        base_dir=base_dir,
        **kwargs,
    )
    return str(result['hostApprovalHash'])
