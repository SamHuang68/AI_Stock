"""WaveDeck adapter for the shared Stock Terminal storage contract."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODE_ROOT = ROOT.parent
# WaveDeck's server package must stay ahead of Stock Terminal's server.py.
COMMON = str(CODE_ROOT / "server")
if COMMON not in sys.path:
    sys.path.append(COMMON)

from data_paths import binding_for, data_path, public_identity, require_runtime_paths
from runtime_storage import assert_write_allowed, bootstrap_runtime

BINDING = binding_for(code_root=CODE_ROOT)
REQUIRED_RUNTIME_PATHS = ("wavedeck/runtime_state.json", "wavedeck/wavedeck_config.json")


def runtime_data(relative: str = "") -> Path:
    if BINDING.mode == "legacy":
        return ROOT / "data" / relative
    return data_path(relative, binding=BINDING, namespace="wavedeck")


def runtime_logs() -> Path:
    return ROOT / "logs" if BINDING.mode == "legacy" else runtime_data("logs")


def guard_write(path: Path, *, must_exist: bool = False) -> None:
    assert_write_allowed(path, namespace="wavedeck", must_exist=must_exist, binding=BINDING)


def bootstrap():
    require_runtime_paths(REQUIRED_RUNTIME_PATHS, binding=BINDING)
    return bootstrap_runtime(code_root=CODE_ROOT, binding=BINDING, namespace="wavedeck")


def identity() -> dict:
    return public_identity(binding=BINDING)


def backend_url() -> str:
    if BINDING.mode == "fixture":
        return ""
    if BINDING.mode == "legacy":
        return os.environ.get("ST_URL", "http://127.0.0.1:18432").rstrip("/")
    configured = str(BINDING.backend_url or "").rstrip("/")
    override = os.environ.get("ST_URL", "").rstrip("/")
    if not configured or (override and override != configured):
        raise RuntimeError("WaveDeck 的 ST_URL 必須符合已登記的 Stock Terminal 後端。")
    return configured


def describe() -> dict:
    require_runtime_paths(REQUIRED_RUNTIME_PATHS, binding=BINDING)
    return {**identity(), "baseDir": str(ROOT), "dataDir": str(runtime_data()),
            "logDir": str(runtime_logs()), "portFile": str(runtime_data("wavedeck.port")),
            "backendUrl": backend_url() if BINDING.mode != "fixture" else None}


def registered_txt_dir(config: dict) -> Path:
    """Live TXT destinations need a separate registration before cutover."""
    chosen = str(config.get("txt_dir") or "data/master")
    path = Path(chosen)
    if BINDING.mode == "legacy":
        return path if path.is_absolute() else ROOT / path
    if BINDING.mode != "fixture":
        raise RuntimeError("外置資料模式尚未登記正式 TXT 目的地；請維持紙上模式。")
    if config.get("txt_fixture") is not True or not path.is_absolute() or not path.is_dir():
        raise RuntimeError("TXT fixture 需要明確登記既存絕對目錄及 txt_fixture=true。")
    guard_write(path)
    return path


if __name__ == "__main__":
    print(json.dumps(describe(), ensure_ascii=False))
