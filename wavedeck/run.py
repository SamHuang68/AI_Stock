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

if __name__ == "__main__":
    if sys.argv[1:] == ["--describe-runtime"]:
        import json
        from runtime_paths import describe
        print(json.dumps(describe(), ensure_ascii=False))
    else:
        from runtime_paths import BINDING, bootstrap, runtime_logs, guard_write
        if BINDING.mode != "legacy":
            _lease = bootstrap()
            if sys.argv[1:]:
                import uuid
                if len(sys.argv) != 3 or sys.argv[1] != "--launcher-log-id":
                    raise SystemExit("不支援的 WaveDeck 參數。")
                log_id = uuid.UUID(sys.argv[2]).hex
                logs = runtime_logs()
                guard_write(logs)
                logs.mkdir(parents=True, exist_ok=True)
                for stream in ("stdout", "stderr"):
                    target = logs / f"launcher-{log_id}-{stream}.log"
                    guard_write(target)
                    setattr(sys, stream, target.open("a", encoding="utf-8", buffering=1))
        from server.server import main
        main()
