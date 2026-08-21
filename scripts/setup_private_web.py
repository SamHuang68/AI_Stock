#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create local-only configuration and access tokens for Private Web ST."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = DATA / "private_web.json"
OWNER = DATA / "private_web_owner.token"
READER = DATA / "private_web_read.token"

DEFAULT_CONFIG = {
    "listen_host": "127.0.0.1",
    "listen_port": 18434,
    "upstream": "http://127.0.0.1:18432",
    "allowed_hosts": ["localhost", "127.0.0.1", "::1"],
    "allowed_host_suffixes": [".ts.net"],
    "max_body_bytes": 1048576,
    "read_rate_per_minute": 240,
    "write_rate_per_minute": 30,
    "upstream_timeout_seconds": 120,
    "audit_path": "logs/private_web_audit.jsonl",
    "access_request_path": "data/private_web_access_requests.json",
    "extra_read_paths": [],
    "extra_control_paths": [],
}


def _write_private(path: Path, value: str, *, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if not overwrite:
        flags |= os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return True


def setup(*, rotate: bool = False, show_tokens: bool = True) -> dict[str, str | bool]:
    DATA.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    owner_token = secrets.token_urlsafe(36)
    read_token = secrets.token_urlsafe(36)
    owner_written = _write_private(OWNER, owner_token, overwrite=rotate)
    reader_written = _write_private(READER, read_token, overwrite=rotate)

    result: dict[str, str | bool] = {
        "config": str(CONFIG),
        "owner_file": str(OWNER),
        "reader_file": str(READER),
        "owner_written": owner_written,
        "reader_written": reader_written,
    }
    if show_tokens:
        if owner_written:
            result["owner_token"] = owner_token
        if reader_written:
            result["read_token"] = read_token
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Private Web ST access")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="replace existing owner and read-only tokens",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="do not print newly generated tokens",
    )
    args = parser.parse_args()
    result = setup(rotate=args.rotate, show_tokens=not args.no_show)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["owner_written"]:
        print("Owner token already exists; use --rotate only when you intend to revoke it.")


if __name__ == "__main__":
    main()
