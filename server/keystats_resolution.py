#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure TWSE/TPEx key-stat symbol resolution policy."""
from __future__ import annotations


def should_retry_tw_keystats_as_otc(sym, stats):
    """Return whether a nominal .TW lookup should retry with the .TWO suffix."""
    symbol = str(sym or '').upper()
    if not symbol.endswith('.TW') or symbol.endswith('.TWO'):
        return False
    values = stats if isinstance(stats, dict) else {}
    return (
        values.get('regularMarketPrice') is None
        or (
            values.get('trailingPE') is None
            and values.get('eps') is None
            and values.get('marketCap') is None
        )
    )
