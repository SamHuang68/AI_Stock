"""固定程序啟動時的版本，避免磁碟更新後誤報已載入新版。"""
import json
import re
import subprocess
from pathlib import Path


def read_revision(root: Path) -> str | None:
    manifest = root / ".private_web_release.json"
    try:
        if manifest.exists():
            commit = json.loads(manifest.read_text(encoding="utf-8")).get("commit", "")
        elif (root / ".git").exists():
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
        else:
            return None
        return commit if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) else None
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None


RUNTIME_COMMIT = read_revision(Path(__file__).resolve().parents[1])
