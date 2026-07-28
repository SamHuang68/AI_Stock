# -*- coding: utf-8 -*-
"""
輕量觀測性（H4）— 標準庫 logging，寫 stderr + data/logs/server.log
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_CONFIGURED = False
_LOG = logging.getLogger('stock_terminal')


def setup(level: str = 'INFO') -> logging.Logger:
    global _CONFIGURED
    if _CONFIGURED:
        return _LOG
    _LOG.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s',
                            datefmt='%H:%M:%S')
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    _LOG.addHandler(sh)
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(os.path.dirname(base), 'data', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, 'server.log'), encoding='utf-8')
        fh.setFormatter(fmt)
        _LOG.addHandler(fh)
    except Exception as e:
        _LOG.warning('file log unavailable: %s', e)
    _CONFIGURED = True
    return _LOG


def get_logger(name: Optional[str] = None) -> logging.Logger:
    if not _CONFIGURED:
        setup()
    return logging.getLogger(name or 'stock_terminal')
