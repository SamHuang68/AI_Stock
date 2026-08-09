# -*- coding: utf-8 -*-
"""WaveDeck local config (no secrets in git)."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .state import DATA

CONFIG_PATH = DATA / "wavedeck_config.json"
SECRETS_PATH = DATA / "wavedeck_secrets.json"

_DEFAULT = {
    "provider": "heuristic",  # heuristic | ollama | openai
    "mode": "paper",  # paper | live
    "ollama": {
        "base": "http://127.0.0.1:11434",
        "model": "llama3.2",
        "timeout_sec": 45,
    },
    "openai": {
        "base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "timeout_sec": 45,
    },
    "broker": {
        "kind": "paper",  # paper | txt_master
        "txt_dir": "data/master",
        "target_file": "target_position.txt",
        "account_file": "account_position.txt",
        "strategy_file": "strategy_position.txt",
        "signal_file": "order_signal.txt",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def load_config() -> dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    cfg = deepcopy(_DEFAULT)
    disk = _read_json(CONFIG_PATH)
    for k, v in disk.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if not CONFIG_PATH.is_file():
        save_config(cfg)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_secrets() -> dict[str, Any]:
    """Optional local secrets file — never commit."""
    sec = _read_json(SECRETS_PATH)
    # Env wins
    if os.environ.get("OPENAI_API_KEY"):
        sec["openai_api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("WAVEDECK_SECRET"):
        sec["webhook_secret"] = os.environ["WAVEDECK_SECRET"]
    return sec


def openai_api_key() -> str:
    return str(load_secrets().get("openai_api_key") or "")


def set_provider(name: str) -> dict[str, Any]:
    want = (name or "heuristic").strip().lower()
    if want not in ("heuristic", "ollama", "openai"):
        raise ValueError("provider must be heuristic|ollama|openai")
    cfg = load_config()
    cfg["provider"] = want
    save_config(cfg)
    return cfg


def set_mode(mode: str) -> dict[str, Any]:
    want = (mode or "paper").strip().lower()
    if want not in ("paper", "live"):
        raise ValueError("mode must be paper|live")
    cfg = load_config()
    cfg["mode"] = want
    # live → 下單大師 TXT；paper → 模擬盤
    if want == "live":
        cfg.setdefault("broker", {})["kind"] = "txt_master"
    else:
        cfg.setdefault("broker", {})["kind"] = "paper"
    save_config(cfg)
    return cfg


def set_broker_kind(kind: str) -> dict[str, Any]:
    want = (kind or "paper").strip().lower()
    if want in ("txt", "master"):
        want = "txt_master"
    if want not in ("paper", "txt_master"):
        raise ValueError("broker must be paper|txt_master")
    cfg = load_config()
    cfg.setdefault("broker", {})["kind"] = want
    if want == "txt_master":
        cfg["mode"] = "live"
    else:
        cfg["mode"] = "paper"
    save_config(cfg)
    return cfg
