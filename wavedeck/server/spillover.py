# -*- coding: utf-8 -*-
"""Supply-chain / sector spillover probability (mirrors WaveDeckBridge JS)."""
from __future__ import annotations

from typing import Any, Optional


def spillover_from_rotation(
    rotation_health: Optional[str],
    up_n: int = 0,
    dn_n: int = 0,
) -> float:
    rot = rotation_health or "mixed"
    total = int(up_n) + int(dn_n)
    base = 0.72 if rot == "broad" else 0.30 if rot == "narrow" else 0.50
    if total:
        breadth = up_n / total
    else:
        breadth = 0.6 if rot == "broad" else 0.35 if rot == "narrow" else 0.5
    spill = 0.55 * base + 0.45 * breadth
    if up_n > 0 and up_n <= 2:
        spill -= 0.08
    if up_n >= 5:
        spill += 0.06
    return max(0.05, min(0.95, round(spill, 2)))


def spillover_from_chain_stages(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Adjacent co-positive mom5 → diffusion; breadth + contig + inflow."""
    stages = stages or []
    with_data = [
        s
        for s in stages
        if s and int(s.get("n") or 0) > 0 and s.get("mom5") is not None
    ]
    if not with_data:
        return {
            "prob": 0.45,
            "hot_stage": None,
            "leaders": [],
            "breadth": 0.0,
            "contig": 0.0,
        }

    up = [s for s in with_data if float(s["mom5"]) > 0]
    breadth = len(up) / len(with_data)

    contig_pairs = 0
    contig_possible = 0
    for i in range(len(stages) - 1):
        a, b = stages[i], stages[i + 1]
        if not a or not b:
            continue
        if not int(a.get("n") or 0) or not int(b.get("n") or 0):
            continue
        if a.get("mom5") is None or b.get("mom5") is None:
            continue
        contig_possible += 1
        if float(a["mom5"]) > 0 and float(b["mom5"]) > 0:
            contig_pairs += 1
    contig = (contig_pairs / contig_possible) if contig_possible else 0.0

    inflow = 0
    for s in with_data:
        accel = s.get("accel")
        if accel is None and s.get("mom5") is not None and s.get("mom20") is not None:
            accel = float(s["mom5"]) - float(s["mom20"])
        if accel is not None and float(accel) > 0.05:
            inflow += 1
    inflow_ratio = inflow / len(with_data)

    def _mom_key(s: dict[str, Any]) -> float:
        v = s.get("mom20")
        if v is None:
            v = s.get("mom5")
        return float(v or 0)

    hot = sorted(with_data, key=_mom_key, reverse=True)[0]
    leaders: list[str] = []
    for L in (hot.get("leaders") or [])[:4]:
        if isinstance(L, dict):
            leaders.append(str(L.get("name") or L.get("code") or "")[:40])
        elif L:
            leaders.append(str(L)[:40])
    leaders = [x for x in leaders if x]

    prob = 0.40 * breadth + 0.35 * contig + 0.25 * min(1.0, inflow_ratio * 2)
    prob = max(0.05, min(0.95, round(prob, 2)))
    return {
        "prob": prob,
        "hot_stage": str(hot.get("stage")) if hot.get("stage") else None,
        "leaders": leaders,
        "breadth": round(breadth, 2),
        "contig": round(contig, 2),
    }


def blend_spillover(sector_prob: Optional[float], chain_prob: Optional[float]) -> Optional[float]:
    s = float(sector_prob) if sector_prob is not None else None
    c = float(chain_prob) if chain_prob is not None else None
    if s is None and c is None:
        return None
    if c is None:
        return max(0.05, min(0.95, round(s, 2)))  # type: ignore[arg-type]
    if s is None:
        return max(0.05, min(0.95, round(c, 2)))
    return max(0.05, min(0.95, round(0.60 * c + 0.40 * s, 2)))
