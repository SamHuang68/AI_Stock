#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely seed canonical ETF runtime history from one or more old locations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import etf_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="+", help="Source etf_history directories, newest/trusted first")
    parser.add_argument("--target", help="Optional absolute target; defaults to canonical runtime storage")
    args = parser.parse_args(argv)
    target = Path(args.target).expanduser() if args.target else None
    if target is not None and not target.is_absolute():
        parser.error("--target must be an absolute path")
    result = etf_paths.migrate_snapshots(args.sources, target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("invalid") or result.get("conflicts") or result.get("missing"):
        return 2
    return 0 if result.get("promoted") and result["status"].get("healthy") else 3


if __name__ == "__main__":
    raise SystemExit(main())
