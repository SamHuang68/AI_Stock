#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import etf_paths  # noqa: E402


def _write_snapshot(
    root: Path,
    day: dt.date,
    *,
    etf_count: int = 2,
    provider_days: list[dt.date] | None = None,
    root_day: dt.date | None = None,
) -> Path:
    provider_days = provider_days or [day]
    payload: dict[str, object] = {"date": (root_day or day).isoformat()}
    for index in range(etf_count):
        code = f"009{index:02d}A"
        provider = provider_days[index % len(provider_days)]
        payload[code] = {
            "date": provider.isoformat(),
            "source": "fixture",
            "holdings": [{"code": "2330", "weight": 10 + index, "shares": 1000 + index}],
        }
    path = root / f"top10_active_etf_holdings_{day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _last_weekday(day: dt.date) -> dt.date:
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _previous_weekday(day: dt.date) -> dt.date:
    day -= dt.timedelta(days=1)
    return _last_weekday(day)


class EtfPathTests(unittest.TestCase):
    def test_absolute_override_and_relative_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            absolute = str(Path(temp).resolve() / "history")
            self.assertEqual(
                etf_paths.resolve_history_dir(environ={etf_paths.ENV_HISTORY_DIR: absolute}),
                Path(absolute),
            )
        with self.assertRaises(ValueError):
            etf_paths.resolve_history_dir(environ={etf_paths.ENV_HISTORY_DIR: "relative/history"})

    def test_default_is_shared_runtime_not_release_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            resolved = etf_paths.resolve_history_dir(
                environ={"LOCALAPPDATA": temp}, home=Path(temp)
            )
            self.assertEqual(
                resolved,
                Path(temp).resolve() / "StockTerminalPrivateWeb" / "shared-data" / "etf_history",
            )
            self.assertNotIn("releases", {part.lower() for part in resolved.parts})
            self.assertNotIn("current", {part.lower() for part in resolved.parts})

    def test_business_day_age_keeps_friday_fresh_over_weekend(self):
        friday = dt.date(2026, 8, 28)
        self.assertEqual(etf_paths.business_day_age(friday, dt.date(2026, 8, 29)), 0)
        self.assertEqual(etf_paths.business_day_age(friday, dt.date(2026, 8, 30)), 0)
        self.assertEqual(etf_paths.business_day_age(friday, dt.date(2026, 8, 31)), 1)

    def test_status_ok_stale_future_corrupt_and_incomplete(self):
        today = dt.date(2026, 8, 30)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_snapshot(root, dt.date(2026, 8, 27), etf_count=12)
            _write_snapshot(root, dt.date(2026, 8, 28), etf_count=12)
            status = etf_paths.history_status(root, today=today)
            self.assertEqual(status["state"], "ok")
            self.assertTrue(status["latestReadable"])
            self.assertTrue(status["previousReadable"])
            self.assertEqual(status["latestEtfCount"], 12)

            latest = root / "top10_active_etf_holdings_2026-08-28.json"
            latest.unlink()
            _write_snapshot(root, dt.date(2026, 8, 28), etf_count=5)
            self.assertEqual(etf_paths.history_status(root, today=today)["state"], "incomplete")

            latest.write_text("{broken", encoding="utf-8")
            self.assertEqual(etf_paths.history_status(root, today=today)["state"], "corrupt")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_snapshot(root, dt.date(2026, 8, 20), etf_count=12)
            _write_snapshot(root, dt.date(2026, 8, 21), etf_count=12)
            self.assertEqual(etf_paths.history_status(root, today=today)["state"], "stale")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_snapshot(root, dt.date(2026, 8, 28), etf_count=12)
            _write_snapshot(root, dt.date(2026, 8, 31), etf_count=12)
            self.assertEqual(etf_paths.history_status(root, today=today)["state"], "future")

    def test_majority_provider_freshness_not_single_old_outlier(self):
        today = dt.date(2026, 8, 30)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_snapshot(root, dt.date(2026, 8, 27), etf_count=12)
            _write_snapshot(
                root, dt.date(2026, 8, 28), etf_count=12,
                provider_days=[dt.date(2026, 8, 28), dt.date(2026, 8, 28), dt.date(2026, 8, 20)],
            )
            status = etf_paths.history_status(root, today=today)
            self.assertEqual(status["state"], "ok")
            self.assertAlmostEqual(status["providerFreshRatio"], 2 / 3, places=3)

    def test_provider_date_coverage_below_half_is_incomplete(self):
        today = dt.date(2026, 8, 31)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_snapshot(root, dt.date(2026, 8, 27), etf_count=12)
            latest = _write_snapshot(root, dt.date(2026, 8, 28), etf_count=12)
            payload = json.loads(latest.read_text(encoding="utf-8"))
            for index, key in enumerate(k for k in payload if k != "date"):
                if index >= 5:
                    payload[key]["date"] = None
            latest.write_text(json.dumps(payload), encoding="utf-8")
            status = etf_paths.history_status(root, today=today)
            self.assertEqual(status["state"], "incomplete")
            self.assertEqual(status["providerKnownCount"], 5)
            self.assertIn("provider_date_coverage_below_half", status["problems"])

    def test_manifest_must_describe_the_actual_payload(self):
        day = dt.date(2026, 8, 28)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = _write_snapshot(root, day, etf_count=12)
            payload = json.loads(path.read_text(encoding="utf-8"))
            codes = sorted(key for key in payload if key != "date")
            payload["meta"] = {
                "expectedCodes": codes,
                "expectedCount": len(codes),
                "succeededCodes": codes[:-1],
                "succeededCount": len(codes) - 1,
                "failedCodes": [codes[-1]],
                "successRatio": round((len(codes) - 1) / len(codes), 4),
                "catalogFingerprint": etf_paths.catalog_fingerprint(codes),
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            check = etf_paths.inspect_snapshot(path)
            self.assertFalse(check["valid"])
            self.assertIn("manifest_succeeded_codes_mismatch", check["problems"])

    def test_empty_or_missing_manifest_cannot_bypass_current_catalog_gate(self):
        day = dt.date(2026, 8, 28)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = _write_snapshot(root, day, etf_count=12)
            payload = json.loads(path.read_text(encoding="utf-8"))
            codes = sorted(key for key in payload if key != "date")

            # Empty arrays are real manifest values, not permission to skip
            # payload cross-validation.  This manifest says zero succeeded
            # while the body contains all 12 ETFs.
            payload["meta"] = {
                "expectedCodes": codes,
                "expectedCount": len(codes),
                "succeededCodes": [],
                "succeededCount": 0,
                "failedCodes": [],
                "successRatio": 1.0,
                "catalogFingerprint": etf_paths.catalog_fingerprint(codes),
            }
            check = etf_paths.inspect_snapshot_payload(payload, expected_date=day)
            self.assertFalse(check["valid"])
            self.assertIn("manifest_succeeded_codes_mismatch", check["problems"])

            # A present-but-empty manifest is corrupt rather than a legacy
            # snapshot.  A genuinely legacy snapshot without meta may still be
            # read by history_status, but it cannot satisfy a tracker call that
            # supplies the current catalog universe.
            payload["meta"] = {}
            check = etf_paths.inspect_snapshot_payload(payload, expected_date=day)
            self.assertFalse(check["valid"])
            self.assertTrue(any(
                problem.startswith("manifest_missing_fields:")
                for problem in check["problems"]
            ))

            payload.pop("meta")
            legacy_check = etf_paths.inspect_snapshot_payload(payload, expected_date=day)
            self.assertTrue(legacy_check["valid"])
            acceptance = etf_paths.snapshot_acceptance(
                legacy_check,
                today=day,
                expected_codes=codes,
            )
            self.assertFalse(acceptance["accepted"])
            self.assertIn("catalog_universe_changed", acceptance["problems"])

    def test_fresh_provider_evidence_is_measured_against_all_etfs(self):
        day = dt.date(2026, 8, 31)
        stale = dt.date(2026, 8, 20)
        codes = [f"009{index:02d}A" for index in range(10)]
        payload: dict[str, object] = {"date": day.isoformat()}
        for index, code in enumerate(codes):
            provider_day = day if index < 3 else stale if index < 5 else None
            payload[code] = {
                "date": provider_day.isoformat() if provider_day else None,
                "source": "fixture",
                "holdings": [{"code": "2330", "weight": 10, "shares": 1000}],
            }
        payload["meta"] = {
            "expectedCodes": codes,
            "expectedCount": len(codes),
            "succeededCodes": codes,
            "succeededCount": len(codes),
            "failedCodes": [],
            "successRatio": 1.0,
            "catalogFingerprint": etf_paths.catalog_fingerprint(codes),
        }

        check = etf_paths.inspect_snapshot_payload(payload, expected_date=day)
        self.assertTrue(check["valid"], check["problems"])
        acceptance = etf_paths.snapshot_acceptance(
            check,
            today=day,
            expected_codes=codes,
        )
        self.assertFalse(acceptance["accepted"])
        self.assertEqual(acceptance["state"], "stale")
        self.assertEqual(acceptance["providerKnownCount"], 5)
        self.assertEqual(acceptance["providerFreshCount"], 3)
        self.assertAlmostEqual(acceptance["providerCoverageRatio"], 0.5)
        self.assertAlmostEqual(acceptance["providerFreshRatio"], 0.3)
        self.assertIn("majority_provider_data_is_stale", acceptance["problems"])

    def test_manifest_scalar_fields_do_not_accept_coerced_types(self):
        day = dt.date(2026, 8, 28)
        with tempfile.TemporaryDirectory() as temp:
            path = _write_snapshot(Path(temp), day, etf_count=12)
            payload = json.loads(path.read_text(encoding="utf-8"))
            codes = sorted(key for key in payload if key != "date")
            payload["meta"] = {
                "expectedCodes": codes,
                "expectedCount": str(len(codes)),
                "succeededCodes": codes,
                "succeededCount": float(len(codes)),
                "failedCodes": [],
                "successRatio": "1.0",
                "catalogFingerprint": 123,
            }

            check = etf_paths.inspect_snapshot_payload(payload, expected_date=day)
            self.assertFalse(check["valid"])
            self.assertIn("manifest_expectedCount_invalid", check["problems"])
            self.assertIn("manifest_succeededCount_invalid", check["problems"])
            self.assertIn("manifest_success_ratio_invalid", check["problems"])
            self.assertIn("manifest_catalog_fingerprint_invalid", check["problems"])

    def test_health_read_does_not_create_history(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "missing" / "history"
            status = etf_paths.history_status(target)
            self.assertEqual(status["state"], "missing")
            self.assertFalse(target.exists())

    def test_atomic_seed_and_existing_target_is_read_only(self):
        today = dt.date.today()
        latest = _last_weekday(today)
        previous = _previous_weekday(latest)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            target = base / "shared" / "etf_history"
            first = _write_snapshot(source, previous, etf_count=12)
            second = _write_snapshot(source, latest, etf_count=12)
            source_hashes = {p.name: p.read_bytes() for p in (first, second)}

            result = etf_paths.migrate_snapshots([source], target)
            self.assertTrue(result["promoted"])
            self.assertTrue(result["status"]["healthy"])
            self.assertEqual(sorted(result["copied"]), sorted(source_hashes))
            self.assertEqual(
                {p.name: p.read_bytes() for p in target.glob("*.json")}, source_hashes
            )

            rerun = etf_paths.migrate_snapshots([source], target)
            self.assertTrue(rerun["noop"])
            self.assertEqual(rerun["copied"], [])

            second.write_text(second.read_text(encoding="utf-8") + " ", encoding="utf-8")
            before = {p.name: p.read_bytes() for p in target.glob("*.json")}
            conflict = etf_paths.migrate_snapshots([source], target)
            self.assertFalse(conflict["promoted"])
            self.assertIn(second.name, conflict["conflicts"])
            self.assertEqual({p.name: p.read_bytes() for p in target.glob("*.json")}, before)

    def test_filename_root_date_mismatch_never_promotes(self):
        today = dt.date.today()
        latest = _last_weekday(today)
        previous = _previous_weekday(latest)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            target = base / "target"
            _write_snapshot(source, previous, etf_count=12)
            _write_snapshot(source, latest, etf_count=12, root_day=previous)
            result = etf_paths.migrate_snapshots([source], target)
            self.assertFalse(result["promoted"])
            self.assertTrue(result["invalid"])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
