#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Promotion gate checklist for shadow research → production Decision wiring.

Default verdict is **FAIL** until every criterion is explicitly satisfied.
This module never auto-promotes; it only evaluates a caller-supplied evidence
bundle against Host Gate requirements documented in ``docs/PROMOTION_GATE.md``.
"""
from __future__ import annotations

from typing import Any

CONTRACT_VERSION = 1
FEATURE_COUNT_CAP = 8
MIN_OOS_SAMPLE = 60
MIN_OOS_WINDOWS = 3


def _check_oos_report(bundle: dict[str, Any]) -> dict[str, Any]:
    report = bundle.get('oosReport') or {}
    windows = report.get('windows') or []
    sample = int(report.get('sampleSize') or 0)
    passed = (
        report.get('status') == 'complete'
        and len(windows) >= MIN_OOS_WINDOWS
        and sample >= MIN_OOS_SAMPLE
        and bool(report.get('reportId'))
        and bool(report.get('asOf'))
    )
    return {
        'id': 'oosReport',
        'label': 'Out-of-sample walk-forward report',
        'passed': passed,
        'required': {
            'status': 'complete',
            'minWindows': MIN_OOS_WINDOWS,
            'minSampleSize': MIN_OOS_SAMPLE,
            'reportId': True,
            'asOf': True,
        },
        'actual': {
            'status': report.get('status'),
            'windows': len(windows),
            'sampleSize': sample,
            'reportId': report.get('reportId'),
            'asOf': report.get('asOf'),
        },
    }


def _check_cost_turnover(bundle: dict[str, Any]) -> dict[str, Any]:
    notes = bundle.get('costTurnoverNotes') or {}
    passed = (
        notes.get('status') == 'documented'
        and notes.get('turnoverBps') is not None
        and notes.get('costBps') is not None
        and bool(str(notes.get('summary') or '').strip())
    )
    return {
        'id': 'costTurnoverNotes',
        'label': 'Cost and turnover notes',
        'passed': passed,
        'required': {
            'status': 'documented',
            'turnoverBps': True,
            'costBps': True,
            'summary': True,
        },
        'actual': {
            'status': notes.get('status'),
            'turnoverBps': notes.get('turnoverBps'),
            'costBps': notes.get('costBps'),
            'summary': bool(str(notes.get('summary') or '').strip()),
        },
    }


def _check_decay_monitor(bundle: dict[str, Any]) -> dict[str, Any]:
    monitor = bundle.get('decayMonitor') or {}
    passed = (
        monitor.get('status') == 'active'
        and bool(monitor.get('metric'))
        and monitor.get('lookbackDays') is not None
        and monitor.get('alertThreshold') is not None
    )
    return {
        'id': 'decayMonitor',
        'label': 'Decay / 失效 monitor',
        'passed': passed,
        'required': {
            'status': 'active',
            'metric': True,
            'lookbackDays': True,
            'alertThreshold': True,
        },
        'actual': {
            'status': monitor.get('status'),
            'metric': monitor.get('metric'),
            'lookbackDays': monitor.get('lookbackDays'),
            'alertThreshold': monitor.get('alertThreshold'),
        },
    }


def _check_feature_count_cap(bundle: dict[str, Any]) -> dict[str, Any]:
    features = bundle.get('features') or []
    count = len(features) if isinstance(features, list) else int(bundle.get('featureCount') or 0)
    passed = count > 0 and count <= FEATURE_COUNT_CAP
    return {
        'id': 'featureCountCap',
        'label': f'Feature count cap (≤{FEATURE_COUNT_CAP})',
        'passed': passed,
        'required': {'maxFeatures': FEATURE_COUNT_CAP, 'minFeatures': 1},
        'actual': {'featureCount': count, 'features': features if isinstance(features, list) else None},
    }


def evaluate(bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return promotion gate verdict. Default bundle → all checks FAIL."""
    evidence = bundle if isinstance(bundle, dict) else {}
    checks = [
        _check_oos_report(evidence),
        _check_cost_turnover(evidence),
        _check_decay_monitor(evidence),
        _check_feature_count_cap(evidence),
    ]
    passed = all(item['passed'] for item in checks)
    return {
        'contractVersion': CONTRACT_VERSION,
        'verdict': 'PASS' if passed else 'FAIL',
        'autoPromote': False,
        'policy': 'manual_host_review_required',
        'documentation': 'docs/PROMOTION_GATE.md',
        'checks': checks,
        'nonGoals': [
            'No automatic Decision envelope writes',
            'No exposure multiplier promotion',
            'No LLM Decision score ingestion',
        ],
    }


def default_fail_payload() -> dict[str, Any]:
    """Convenience payload for shadow surfaces that reference the gate."""
    return evaluate(None)
