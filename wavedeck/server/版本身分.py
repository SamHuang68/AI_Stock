"""啟動時核對發布收據；健康端點只回報已核對的程式版本。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def read_release_identity(root: Path) -> dict:
    receipt = root / "data" / "程式版本.json"
    if not receipt.is_file():
        return {"runtimeCommit": None, "releaseVerified": False, "releaseError": "尚未建立發布收據"}
    try:
        raw = json.loads(receipt.read_text(encoding="utf-8"))
        commit, files = raw["commit"], raw["files"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit) or not isinstance(files, dict):
            raise ValueError("發布收據格式無效")
        required = {"VERSION", "run.py", "web/index.html", "web/js/deck.js", "web/css/deck.css"}
        required.update(path.relative_to(root).as_posix() for path in (root / "server").rglob("*.py"))
        if not required.issubset(files):
            raise ValueError("發布收據缺少必要程式檔案")
        for relative, expected in files.items():
            path = (root / relative).resolve()
            path.relative_to(root.resolve())
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("程式檔案與發布收據不符")
        return {"runtimeCommit": commit, "releaseVerified": True, "releaseError": None}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {"runtimeCommit": None, "releaseVerified": False, "releaseError": str(exc)}
