#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck entrypoint — prefer this over `python server/server.py` on Windows.

Running `server/server.py` puts `wavedeck/server/` on sys.path first and can
shadow the `server` package, causing a silent crash or hung import.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Ensure package root wins; drop accidental script-dir shadowing.
sys.path = [str(ROOT)] + [p for p in sys.path if Path(p).resolve() != (ROOT / "server").resolve()]

from server.server import main  # noqa: E402

if __name__ == "__main__":
    main()
