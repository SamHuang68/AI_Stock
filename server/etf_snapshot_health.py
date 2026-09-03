#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate canonical ETF snapshots and optionally probe the running API."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import etf_paths


def _trace_path() -> Path:
    # A health read must not turn a genuinely missing history directory into
    # an empty one.  Only the sibling diagnostics directory is created by
    # ``_trace`` below.
    return etf_paths.resolve_history_dir(create=False).parent / "logs" / "etf_snapshot_trace.jsonl"


def _trace(event: str, correlation_id: str, **fields: object) -> None:
    path = _trace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "component": "etf_snapshot_health",
        "event": event,
        "correlationId": correlation_id,
        **fields,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    if path.stat().st_size > 256 * 1024:
        lines = path.read_text(encoding="utf-8").splitlines()[-400:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _same_path(left: object, right: object) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def probe_api(url: str, expected: dict, timeout: float = 5.0) -> dict:
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024)
            status = int(getattr(response, "status", 200))
        payload = json.loads(raw.decode("utf-8"))
        actual = payload.get("date") if isinstance(payload, dict) else None
        api_history = (
            payload.get("meta", {}).get("history", {}) if isinstance(payload, dict) else {}
        )
        mismatches = []
        if not actual or actual != expected.get("latestDate"):
            mismatches.append("date")
        if not _same_path(api_history.get("directory"), expected.get("directory")):
            mismatches.append("directory")
        if api_history.get("latestSha256") != expected.get("latestSha256"):
            mismatches.append("latestSha256")
        state = "ok" if not mismatches else "contract_mismatch"
        return {
            "state": state,
            "httpStatus": status,
            "date": actual,
            "expectedDate": expected.get("latestDate"),
            "directory": api_history.get("directory"),
            "expectedDirectory": expected.get("directory"),
            "mismatches": mismatches,
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }
    except urllib.error.HTTPError as exc:
        return {
            "state": "http_error",
            "httpStatus": exc.code,
            "date": None,
            "expectedDate": expected.get("latestDate"),
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {
            "state": "unavailable",
            "errorType": type(exc).__name__,
            "date": None,
            "expectedDate": expected.get("latestDate"),
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-url", default="http://127.0.0.1:18435/etf-delta")
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--require-api", action="store_true")
    parser.add_argument("--max-business-days", type=int, default=2)
    args = parser.parse_args(argv)

    correlation_id = "etf-health-" + uuid.uuid4().hex[:12]
    _trace("command_received", correlation_id, probeUrl=args.probe_url)
    status = etf_paths.history_status(max_business_days=max(0, args.max_business_days))
    api = None if args.skip_api else probe_api(args.probe_url, status)
    result = {
        "ok": bool(status.get("healthy")) and (
            not args.require_api or bool(api and api.get("state") == "ok")
        ),
        "correlationId": correlation_id,
        "history": status,
        "api": api,
        "trace": str(_trace_path()),
    }
    _trace(
        "terminal_success" if result["ok"] else "terminal_failure",
        correlation_id,
        historyState=status.get("state"),
        fileCount=status.get("fileCount"),
        latestDate=status.get("latestDate"),
        apiState=(api or {}).get("state") if api else "skipped",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
