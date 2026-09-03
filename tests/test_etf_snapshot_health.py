#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import etf_snapshot_health  # noqa: E402


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self._body


class EtfSnapshotHealthTests(unittest.TestCase):
    def test_probe_requires_date_directory_and_hash_to_match(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = {
                "latestDate": "2026-08-28",
                "directory": str(Path(temp) / "shared-data" / "etf_history"),
                "latestSha256": "abc123",
            }
            payload = {
                "date": "2026-08-28",
                "meta": {"history": dict(expected)},
            }
            with mock.patch.object(
                etf_snapshot_health.urllib.request,
                "urlopen",
                return_value=_Response(payload),
            ):
                result = etf_snapshot_health.probe_api(
                    "http://127.0.0.1:18435/etf-delta", expected
                )
            self.assertEqual(result["state"], "ok")
            self.assertEqual(result["mismatches"], [])

    def test_same_date_from_another_history_is_a_contract_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = {
                "latestDate": "2026-08-28",
                "directory": str(Path(temp) / "canonical"),
                "latestSha256": "canonical-hash",
            }
            payload = {
                "date": "2026-08-28",
                "meta": {
                    "history": {
                        "latestDate": "2026-08-28",
                        "directory": str(Path(temp) / "old-release"),
                        "latestSha256": "old-hash",
                    }
                },
            }
            with mock.patch.object(
                etf_snapshot_health.urllib.request,
                "urlopen",
                return_value=_Response(payload),
            ):
                result = etf_snapshot_health.probe_api("http://unit.test/etf-delta", expected)
            self.assertEqual(result["state"], "contract_mismatch")
            self.assertEqual(set(result["mismatches"]), {"directory", "latestSha256"})


if __name__ == "__main__":
    unittest.main()
