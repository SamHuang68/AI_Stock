#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded orthogonal integration score for shadow conditional research (P1).

Few rule features → score in [−2, +2].  Host-gated; walk-forward report artifact
required before any promotion beyond research surfaces.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime
from typing import Any

from chip_path_state import evaluate_chip_path_state, path_state_score
from conditional_expectation import (
    _inst3d_sign,
    collect_pit_observations,
    tech_summary_from_bars,
    _bars_upto_date,
    _session_date_from_ts,
)
from vol_regime_switch import evaluate_vol_regime_switch

MODEL_VERSION = 'st-conditional-integration/v1'
SCORE_MIN = -2.0
SCORE_MAX = 2.0
WALK_FORWARD_TRAIN_RATIO = 0.7

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WALK_FORWARD_JSON = os.path.join(_BASE, 'docs', 'research', 'conditional_integration_walkforward.json')
WALK_FORWARD_MD = os.path.join(_BASE, 'docs', 'research', 'conditional_integration_walkforward.md')


def _clamp(value: float, lo: float = SCORE_MIN, hi: float = SCORE_MAX) -> float:
    return max(lo, min(hi, value))


def _rsi_feature(rsi: float | None) -> float:
    if rsi is None or not math.isfinite(rsi):
        return 0.0
    return _clamp((float(rsi) - 50.0) / 25.0, -1.0, 1.0)


def _inst_feature(inst_key: str) -> float:
    return {'buy': 0.6, 'sell': -0.6, 'flat': 0.0}.get(inst_key, 0.0)


def _vol_feature(percentile: float | None) -> float:
    if percentile is None or not math.isfinite(percentile):
        return 0.0
    return _clamp((50.0 - float(percentile)) / 50.0, -1.0, 1.0)


def feature_vector(
    *,
    rsi14: float | None,
    inst_key: str,
    chip_state: str,
    vol_percentile: float | None,
) -> dict[str, float]:
    return {
        'rsi_centered': round(_rsi_feature(rsi14), 4),
        'inst3d': round(_inst_feature(inst_key), 4),
        'chipPath': round(path_state_score(chip_state), 4),
        'volPercentile': round(_vol_feature(vol_percentile), 4),
    }


def integrate_score(features: dict[str, float]) -> float:
    weights = {
        'rsi_centered': 0.30,
        'inst3d': 0.25,
        'chipPath': 0.25,
        'volPercentile': 0.20,
    }
    raw = sum(features.get(key, 0.0) * weight for key, weight in weights.items())
    return round(_clamp(raw * 2.0), 4)


def _observation_score(row: dict[str, Any]) -> float:
    feats = row.get('features') or {}
    vec = feature_vector(
        rsi14=feats.get('rsi14'),
        inst_key=feats.get('inst3d') or 'unknown',
        chip_state=row.get('chipState') or 'neutral',
        vol_percentile=row.get('volPercentile'),
    )
    return integrate_score(vec)


def build_walk_forward_report(
    observations: list[dict[str, Any]],
    *,
    symbol: str,
) -> dict[str, Any]:
    if len(observations) < 40:
        return {
            'symbol': symbol,
            'status': 'INSUFFICIENT_DATA',
            'observationCount': len(observations),
            'minimumObservations': 40,
            'walkForwardEvidencePresent': False,
        }
    split = int(len(observations) * WALK_FORWARD_TRAIN_RATIO)
    train = observations[:split]
    test = observations[split:]
    train_scores = [_observation_score(row) for row in train]
    test_scores = [_observation_score(row) for row in test]

    def _bucket_stats(rows: list[dict[str, Any]], scores: list[float], threshold: float) -> dict[str, Any]:
        pos = [rows[i] for i, score in enumerate(scores) if score >= threshold]
        neg = [rows[i] for i, score in enumerate(scores) if score <= -threshold]
        def _mean_return(group: list[dict[str, Any]], horizon: str = '5') -> float | None:
            vals = [
                float(row['outcomes'][horizon]['returnPct'])
                for row in group
                if horizon in row.get('outcomes', {})
            ]
            if not vals:
                return None
            return round(sum(vals) / len(vals), 4)
        return {
            'threshold': threshold,
            'positiveBucket': {'n': len(pos), 'meanReturnH5Pct': _mean_return(pos)},
            'negativeBucket': {'n': len(neg), 'meanReturnH5Pct': _mean_return(neg)},
        }

    report = {
        'symbol': symbol,
        'status': 'READY',
        'generatedAt': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
        'model': MODEL_VERSION,
        'observationCount': len(observations),
        'trainCount': len(train),
        'testCount': len(test),
        'trainScoreMean': round(sum(train_scores) / len(train_scores), 4),
        'testScoreMean': round(sum(test_scores) / len(test_scores), 4),
        'calibration': {
            'train': _bucket_stats(train, train_scores, 0.5),
            'test': _bucket_stats(test, test_scores, 0.5),
        },
        'walkForwardEvidencePresent': len(test) >= 12,
        'notes': [
            'Chronological 70/30 split — no random shuffle.',
            'Evidence is descriptive separation only; not a production Decision score.',
        ],
    }
    return report


def write_walk_forward_artifacts(report: dict[str, Any]) -> tuple[str, str]:
    os.makedirs(os.path.dirname(WALK_FORWARD_JSON), exist_ok=True)
    with open(WALK_FORWARD_JSON, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    lines = [
        '# Conditional Integration Score — Walk-Forward Report',
        '',
        f"- Symbol: `{report.get('symbol', '—')}`",
        f"- Status: `{report.get('status', '—')}`",
        f"- Observations: {report.get('observationCount', 0)} "
        f"(train {report.get('trainCount', 0)} / test {report.get('testCount', 0)})",
        f"- Walk-forward evidence present: `{report.get('walkForwardEvidencePresent', False)}`",
        '',
        '## Calibration (H=5 mean return by score bucket)',
        '',
    ]
    cal = report.get('calibration') or {}
    for split in ('train', 'test'):
        block = cal.get(split) or {}
        lines.append(f"### {split.title()}")
        for side in ('positiveBucket', 'negativeBucket'):
            bucket = block.get(side) or {}
            lines.append(
                f"- {side}: n={bucket.get('n', 0)}, "
                f"meanReturnH5Pct={bucket.get('meanReturnH5Pct')}"
            )
        lines.append('')
    lines.append('> Shadow research only. Default OFF. Does not write Decision envelope.')
    with open(WALK_FORWARD_MD, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    return WALK_FORWARD_JSON, WALK_FORWARD_MD


def walk_forward_evidence_present(symbol: str | None = None) -> bool:
    if not os.path.isfile(WALK_FORWARD_JSON):
        return False
    try:
        with open(WALK_FORWARD_JSON, encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    if not payload.get('walkForwardEvidencePresent'):
        return False
    if symbol and str(payload.get('symbol') or '').upper() != str(symbol).upper():
        return False
    return True


def evaluate_integration_score(
    symbol: str,
    *,
    bars: list,
    chip_inst_by_date: dict[str, float] | None = None,
    as_of_date: date | None = None,
    write_report: bool = False,
) -> dict[str, Any]:
    code = str(symbol or '').strip().upper()
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if not rows:
        return {
            'model': MODEL_VERSION,
            'epistemic': 'CONDITIONAL',
            'shadowOnly': True,
            'actionAuthority': 'none',
            'decisionUse': 'research_only',
            'enabled': False,
            'symbol': code,
            'status': 'INSUFFICIENT_DATA',
            'score': None,
        }
    if as_of_date is None:
        as_of_date = _session_date_from_ts(rows[-1][0])

    pit_bars = _bars_upto_date(rows, as_of_date)
    tech = tech_summary_from_bars(pit_bars)
    _, inst_key = _inst3d_sign(chip_inst_by_date or {}, as_of_date)
    chip = evaluate_chip_path_state(
        code,
        bars=rows,
        chip_inst_by_date=chip_inst_by_date,
        as_of_date=as_of_date,
    )
    vol = evaluate_vol_regime_switch(code, bars=rows, as_of_date=as_of_date)
    vec = feature_vector(
        rsi14=(tech or {}).get('rsi14'),
        inst_key=inst_key,
        chip_state=chip.get('state') or 'neutral',
        vol_percentile=(vol.get('percentile') if isinstance(vol.get('percentile'), (int, float)) else None),
    )
    score = integrate_score(vec)

    observations = collect_pit_observations(code, rows, chip_inst_by_date=chip_inst_by_date)
    enriched = []
    for row in observations:
        session = date.fromisoformat(row['sessionDate'])
        chip_row = evaluate_chip_path_state(
            code, bars=rows, chip_inst_by_date=chip_inst_by_date, as_of_date=session,
        )
        vol_row = evaluate_vol_regime_switch(code, bars=rows, as_of_date=session)
        enriched.append({
            **row,
            'chipState': chip_row.get('state'),
            'volPercentile': vol_row.get('percentile'),
        })
    report = build_walk_forward_report(enriched, symbol=code)
    artifact_paths = None
    if write_report and report.get('status') == 'READY':
        artifact_paths = write_walk_forward_artifacts(report)

    evidence = walk_forward_evidence_present(code)
    return {
        'model': MODEL_VERSION,
        'epistemic': 'CONDITIONAL',
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'enabled': evidence,
        'symbol': code,
        'asOfDate': as_of_date.isoformat(),
        'status': 'READY',
        'score': score if evidence else None,
        'scoreRange': [SCORE_MIN, SCORE_MAX],
        'features': vec,
        'featureWeights': {
            'rsi_centered': 0.30,
            'inst3d': 0.25,
            'chipPath': 0.25,
            'volPercentile': 0.20,
        },
        'walkForward': report,
        'walkForwardEvidencePresent': evidence,
        'artifactPaths': artifact_paths,
        'notes': [
            '集成分數預設 withheld；需 shadowConditionalIntegrationScore + walk-forward 證據。',
            '不得寫入 Decision 曝險或 LLM 信心分數。',
        ],
    }
