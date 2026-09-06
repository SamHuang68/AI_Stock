#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pulse layout diagnostics for /health (tip UX contract)."""
from __future__ import annotations

import os


def pulse_layout_probe(base_dir: str) -> dict:
    """Return tip layout markers from on-disk pulse_v5.js."""
    path = os.path.join(base_dir, 'src', 'ui', 'pulse_v5.js')
    out = {
        'pulseJsPath': path,
        'pulseJsExists': os.path.isfile(path),
        'layoutAnchor': None,
        'layoutContract': None,
        'hasFiveCol': False,
        'hasFourColPriority': False,
    }
    if not out['pulseJsExists']:
        return out
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            txt = fh.read(200000)
        if 'PULSE_LAYOUT_ANCHOR_3cab212' in txt:
            out['layoutAnchor'] = 'PULSE_LAYOUT_ANCHOR_3cab212'
        if '5col-2zone' in txt:
            out['layoutContract'] = '5col-2zone'
        out['hasFiveCol'] = 'repeat(5,minmax(0,1fr))' in txt or 'repeat(5, minmax(0, 1fr))' in txt
        out['hasFourColPriority'] = '4col-priority' in txt
    except Exception as exc:
        out['error'] = str(exc)
    return out
