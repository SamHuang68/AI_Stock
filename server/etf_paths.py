#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Canonical runtime storage and freshness helpers for ETF snapshots.

ETF history is runtime data, not release source.  Keeping it under a checked-out
or immutable release directory made the scheduler, development server and
Private Web read different timelines.  All three now resolve the same location:

1. ``ST_ETF_HISTORY_DIR`` when explicitly supplied.
2. ``%LOCALAPPDATA%\StockTerminalPrivateWeb\shared-data\etf_history`` on Windows.
3. A per-user ``~/.local/share`` equivalent on non-Windows hosts.

The helpers are dependency-free so the tracker, server, diagnostics and tests
can share one contract without importing the full HTTP server.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, Mapping


ENV_HISTORY_DIR = "ST_ETF_HISTORY_DIR"
MIN_HEALTHY_ETF_COUNT = 10
SNAPSHOT_PREFIX = "top10_active_etf_holdings_"
SNAPSHOT_GLOB = f"{SNAPSHOT_PREFIX}*.json"
_DATE_RE = re.compile(
    rf"^{re.escape(SNAPSHOT_PREFIX)}(?P<date>\d{{4}}-?\d{{2}}-?\d{{2}})\.json$"
)


def _default_local_data_root(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    local = str(env.get("LOCALAPPDATA") or "").strip()
    if local:
        return Path(local).expanduser()
    base_home = Path.home() if home is None else Path(home)
    if os.name == "nt":
        return base_home / "AppData" / "Local"
    xdg = str(env.get("XDG_DATA_HOME") or "").strip()
    return Path(xdg).expanduser() if xdg else base_home / ".local" / "share"


def resolve_history_dir(
    *,
    create: bool = False,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve the one canonical ETF snapshot directory.

    Relative overrides are rejected because scheduled tasks commonly start in
    an unrelated working directory; silently resolving one would recreate the
    original split-brain failure.
    """
    env = os.environ if environ is None else environ
    override = str(env.get(ENV_HISTORY_DIR) or "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{ENV_HISTORY_DIR} must be an absolute path: {override!r}")
    else:
        path = (
            _default_local_data_root(env, home)
            / "StockTerminalPrivateWeb"
            / "shared-data"
            / "etf_history"
        )
    path = Path(os.path.abspath(str(path)))
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_date(path: str | os.PathLike[str]) -> _dt.date | None:
    match = _DATE_RE.match(Path(path).name)
    if not match:
        return None
    raw = match.group("date").replace("-", "")
    try:
        return _dt.datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def list_snapshot_files(directory: str | os.PathLike[str] | None = None) -> list[Path]:
    root = Path(directory) if directory is not None else resolve_history_dir()
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.glob(SNAPSHOT_GLOB) if p.is_file() and snapshot_date(p)),
        key=lambda p: (snapshot_date(p), p.name),
    )


def business_day_age(latest: _dt.date, today: _dt.date | None = None) -> int:
    """Count weekdays after ``latest`` through ``today``.

    Friday remains fresh over a weekend; Monday is one business day old.  This
    deliberately does not pretend to know TWSE holidays, so the two-day gate is
    conservative without producing weekend false alarms.
    """
    current = today or _dt.date.today()
    if latest >= current:
        return 0
    age = 0
    cursor = latest + _dt.timedelta(days=1)
    while cursor <= current:
        if cursor.weekday() < 5:
            age += 1
        cursor += _dt.timedelta(days=1)
    return age


def catalog_fingerprint(codes: Iterable[str]) -> str:
    """Return the stable short fingerprint stored in snapshot manifests."""
    normalized = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
    return hashlib.sha256(("\n".join(normalized)).encode("utf-8")).hexdigest()[:16]


def snapshot_acceptance(
    check: Mapping[str, object],
    *,
    today: _dt.date | None = None,
    expected_codes: Iterable[str] | None = None,
    previous_etf_count: int = 0,
    max_business_days: int = 2,
) -> dict:
    """Apply the shared tracker/health acceptance contract to one snapshot.

    This intentionally separates the provider's disclosed date from the local
    collection date.  A snapshot with enough rows but unknown or stale source
    dates is not safe to skip, publish, or report as healthy.
    """
    current = today or _dt.date.today()
    expected = sorted({str(code).strip().upper() for code in (expected_codes or []) if str(code).strip()})
    etf_count = int(check.get("etfCount") or 0)
    minimum_count = max(
        MIN_HEALTHY_ETF_COUNT,
        math.ceil(max(0, int(previous_etf_count or 0)) * 0.60),
        math.ceil(len(expected) * 0.60) if expected else 0,
    )
    provider_dates = [item for item in (check.get("providerDates") or []) if isinstance(item, _dt.date)]
    provider_known_count = len(provider_dates)
    provider_coverage_ratio = provider_known_count / etf_count if etf_count else 0.0
    provider_ages = [business_day_age(item, current) for item in provider_dates]
    provider_fresh_count = sum(1 for age in provider_ages if age <= max_business_days)
    # Freshness is an assertion about the whole accepted snapshot, not merely
    # the subset whose provider date happened to parse.  Using the known-date
    # subset as the denominator allowed 3 fresh + 2 stale + 5 unknown ETFs to
    # pass as 60% fresh even though only 30% of the payload had fresh evidence.
    provider_fresh_ratio = provider_fresh_count / etf_count if etf_count else 0.0
    snapshot_day = check.get("snapshotDate")
    problems: list[str] = []
    state = "ok"

    if not bool(check.get("valid")):
        state = "corrupt"
        problems.append("snapshot_schema_invalid")
    elif etf_count < minimum_count:
        state = "incomplete"
        problems.append(f"etf_count_below_floor:{etf_count}<{minimum_count}")
    elif provider_coverage_ratio < 0.50:
        state = "incomplete"
        problems.append("provider_date_coverage_below_half")
    elif ((isinstance(snapshot_day, _dt.date) and snapshot_day > current) or
          any(item > current for item in provider_dates)):
        state = "future"
        problems.append("snapshot_or_provider_date_is_future")
    elif provider_fresh_ratio < 0.50:
        state = "stale"
        problems.append("majority_provider_data_is_stale")
    elif expected:
        manifest_codes = sorted({str(code).strip().upper() for code in check.get("expectedCodes") or [] if str(code).strip()})
        if manifest_codes != expected:
            state = "incomplete"
            problems.append("catalog_universe_changed")

    return {
        "accepted": state == "ok",
        "state": state,
        "problems": problems,
        "minimumEtfCount": minimum_count,
        "providerKnownCount": provider_known_count,
        "providerCoverageRatio": round(provider_coverage_ratio, 4),
        "providerFreshCount": provider_fresh_count,
        "providerFreshRatio": round(provider_fresh_ratio, 4),
    }


def history_status(
    directory: str | os.PathLike[str] | None = None,
    *,
    today: _dt.date | None = None,
    max_business_days: int = 2,
) -> dict:
    root = Path(directory) if directory is not None else resolve_history_dir()
    files = list_snapshot_files(root)
    latest_date = snapshot_date(files[-1]) if files else None
    current = today or _dt.date.today()
    age = business_day_age(latest_date, current) if latest_date else None
    latest_check = inspect_snapshot(files[-1]) if files else None
    previous_check = inspect_snapshot(files[-2]) if len(files) >= 2 else None
    latest_valid = bool(latest_check and latest_check["valid"])
    previous_valid = bool(previous_check and previous_check["valid"])
    provider_dates = list(latest_check["providerDates"]) if latest_check else []
    latest_etf_count = int((latest_check or {}).get("etfCount") or 0)
    provider_oldest = min(provider_dates) if provider_dates else None
    provider_latest = max(provider_dates) if provider_dates else None
    provider_ages = [business_day_age(item, current) for item in provider_dates]
    provider_max_age = max(provider_ages) if provider_ages else None
    provider_fresh_count = sum(1 for item in provider_ages if item <= max_business_days)
    provider_fresh_ratio = (
        provider_fresh_count / latest_etf_count if latest_etf_count else None
    )
    previous_etf_count = int((previous_check or {}).get("etfCount") or 0)
    expected_etf_count = int((latest_check or {}).get("expectedCount") or 0)
    reported_success_ratio = (latest_check or {}).get("successRatio")
    completeness_floor = max(
        MIN_HEALTHY_ETF_COUNT,
        math.ceil(previous_etf_count * 0.60) if previous_etf_count else 0,
        math.ceil(expected_etf_count * 0.60) if expected_etf_count else 0,
    )
    provider_known_count = len(provider_dates)
    provider_unknown_count = max(0, latest_etf_count - provider_known_count)
    provider_coverage_ratio = (
        provider_known_count / latest_etf_count if latest_etf_count else None
    )
    problems: list[str] = []
    if latest_check and latest_check["problems"]:
        problems.extend(f"latest:{item}" for item in latest_check["problems"])
    if previous_check and previous_check["problems"]:
        problems.extend(f"previous:{item}" for item in previous_check["problems"])

    acceptance = snapshot_acceptance(
        latest_check or {},
        today=current,
        expected_codes=(latest_check or {}).get("expectedCodes") or [],
        previous_etf_count=previous_etf_count,
        max_business_days=max_business_days,
    )

    if not files:
        state = "missing"
        problems.append("no_snapshots")
    elif len(files) < 2:
        state = "insufficient"
        problems.append("need_two_snapshots")
    elif not latest_valid or not previous_valid:
        state = "corrupt"
    elif age is not None and age > max_business_days:
        state = "stale"
        problems.append("snapshot_collection_is_stale")
    elif not acceptance["accepted"]:
        state = str(acceptance["state"])
        problems.extend(str(item) for item in acceptance["problems"])
    else:
        state = "ok"
    resolved_by = "explicit"
    if directory is None:
        resolved_by = "env" if str(os.environ.get(ENV_HISTORY_DIR) or "").strip() else "default"
    return {
        "state": state,
        "healthy": state == "ok",
        "directory": str(root),
        "resolvedBy": resolved_by,
        "fileCount": len(files),
        "latestDate": latest_date.isoformat() if latest_date else None,
        "latestSnapshotDate": latest_date.isoformat() if latest_date else None,
        "businessDayAge": age,
        "providerOldestDate": provider_oldest.isoformat() if provider_oldest else None,
        "providerLatestDate": provider_latest.isoformat() if provider_latest else None,
        "latestSourceDateMin": provider_oldest.isoformat() if provider_oldest else None,
        "latestSourceDateMax": provider_latest.isoformat() if provider_latest else None,
        "providerMaxBusinessDayAge": provider_max_age,
        "providerFreshCount": provider_fresh_count,
        "providerFreshRatio": round(provider_fresh_ratio, 4) if provider_fresh_ratio is not None else None,
        "providerKnownCount": provider_known_count,
        "providerUnknownCount": provider_unknown_count,
        "providerCoverageRatio": round(provider_coverage_ratio, 4) if provider_coverage_ratio is not None else None,
        "latestEtfCount": latest_etf_count,
        "previousEtfCount": previous_etf_count,
        "expectedEtfCount": expected_etf_count or None,
        "reportedSuccessRatio": reported_success_ratio,
        "latestHoldingRows": int((latest_check or {}).get("holdingRows") or 0),
        "latestSha256": _sha256(files[-1]) if files and latest_valid else None,
        "previousSha256": _sha256(files[-2]) if len(files) >= 2 and previous_valid else None,
        "latestReadable": latest_valid,
        "previousReadable": previous_valid,
        "acceptance": acceptance,
        "problems": problems,
        "maxBusinessDays": int(max_business_days),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_snapshot_payload(payload: object, *, expected_date: _dt.date | None) -> dict:
    """Validate an in-memory snapshot using the same contract as disk reads."""
    expected = expected_date
    result = {
        "valid": False, "providerDates": [], "problems": [],
        "etfCount": 0, "holdingRows": 0, "snapshotDate": expected,
        "expectedCodes": [], "succeededCodes": [],
    }
    if expected is None:
        result["problems"].append("invalid_expected_date")
        return result
    if not isinstance(payload, dict):
        result["problems"].append("root_not_object")
        return result
    meta = payload.get("meta")
    if meta is not None and not isinstance(meta, dict):
        result["problems"].append("manifest_not_object")
    if isinstance(meta, dict):
        required_manifest_fields = {
            "expectedCodes", "expectedCount", "succeededCodes",
            "succeededCount", "failedCodes", "successRatio",
            "catalogFingerprint",
        }
        missing_fields = sorted(required_manifest_fields - set(meta))
        if missing_fields:
            result["problems"].append(
                "manifest_missing_fields:" + ",".join(missing_fields)
            )
        for field in ("expectedCount", "succeededCount"):
            raw_count = meta.get(field)
            if (
                not isinstance(raw_count, int)
                or isinstance(raw_count, bool)
                or raw_count < 0
            ):
                result["problems"].append(f"manifest_{field}_invalid")
                result[field] = 0
            else:
                result[field] = raw_count
        for field in ("expectedCodes", "succeededCodes", "failedCodes"):
            raw_codes = meta.get(field)
            if not isinstance(raw_codes, list):
                result["problems"].append(f"manifest_{field}_not_list")
                raw_codes = []
            normalized_codes: list[str] = []
            for code in raw_codes:
                if not isinstance(code, str) or not code.strip():
                    result["problems"].append(f"manifest_{field}_invalid_code")
                    continue
                normalized_codes.append(code.strip().upper())
            if len(normalized_codes) != len(set(normalized_codes)):
                result["problems"].append(f"manifest_{field}_duplicates")
            result[field] = normalized_codes
        raw_fingerprint = meta.get("catalogFingerprint")
        if (
            not isinstance(raw_fingerprint, str)
            or not raw_fingerprint
            or raw_fingerprint != raw_fingerprint.strip()
        ):
            result["problems"].append("manifest_catalog_fingerprint_invalid")
            result["catalogFingerprint"] = ""
        else:
            result["catalogFingerprint"] = raw_fingerprint
        raw_ratio = meta.get("successRatio")
        if (
            not isinstance(raw_ratio, (int, float))
            or isinstance(raw_ratio, bool)
            or not math.isfinite(float(raw_ratio))
            or not 0.0 <= float(raw_ratio) <= 1.0
        ):
            result["problems"].append("manifest_success_ratio_invalid")
            result["successRatio"] = None
        else:
            result["successRatio"] = float(raw_ratio)
    raw_root_date = str(payload.get("date") or "").strip()
    try:
        root_date = _dt.date.fromisoformat(raw_root_date[:10])
    except ValueError:
        root_date = None
    if root_date != expected:
        result["problems"].append("filename_root_date_mismatch")
    actual_codes: list[str] = []
    for key, value in payload.items():
        if key in {"date", "updated", "meta", "summary"} or not isinstance(value, dict):
            continue
        holdings = value.get("holdings")
        if not isinstance(holdings, list) or not holdings:
            result["problems"].append(f"empty_holdings:{key}")
            continue
        result["etfCount"] += 1
        actual_codes.append(str(key).strip().upper())
        result["holdingRows"] += len(holdings)
        raw = str(value.get("date") or "").strip()
        try:
            result["providerDates"].append(_dt.date.fromisoformat(raw[:10]))
        except ValueError:
            # Provider dates are useful freshness evidence, but a single absent
            # date must not invalidate an otherwise complete ETF snapshot.
            continue
    if isinstance(meta, dict):
        expected_codes = sorted(set(result["expectedCodes"]))
        succeeded_codes = sorted(set(result["succeededCodes"]))
        failed_codes = sorted(set(result["failedCodes"]))
        actual_codes = sorted(set(actual_codes))
        if result.get("expectedCount") != len(expected_codes):
            result["problems"].append("manifest_expected_count_mismatch")
        if result.get("succeededCount") != len(succeeded_codes):
            result["problems"].append("manifest_succeeded_count_mismatch")
        if succeeded_codes != actual_codes:
            result["problems"].append("manifest_succeeded_codes_mismatch")
        if failed_codes != sorted(set(expected_codes) - set(actual_codes)):
            result["problems"].append("manifest_failed_codes_mismatch")
        if result.get("catalogFingerprint") != catalog_fingerprint(expected_codes):
            result["problems"].append("manifest_catalog_fingerprint_mismatch")
        expected_ratio = len(actual_codes) / len(expected_codes) if expected_codes else 0.0
        ratio = result.get("successRatio")
        if (
            ratio is None
            or not math.isfinite(float(ratio))
            or abs(float(ratio) - round(expected_ratio, 4)) > 0.0001
        ):
            result["problems"].append("manifest_success_ratio_mismatch")
    result["valid"] = not result["problems"]
    return result


def inspect_snapshot(path: str | os.PathLike[str]) -> dict:
    """Validate one immutable snapshot and expose provider dates for health."""
    path = Path(path)
    expected = snapshot_date(path)
    if not path.is_file() or expected is None:
        return {
            "valid": False, "providerDates": [], "problems": ["invalid_filename"],
            "etfCount": 0, "holdingRows": 0, "snapshotDate": expected,
            "expectedCodes": [], "succeededCodes": [],
        }
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "valid": False, "providerDates": [],
            "problems": [f"unreadable_json:{type(exc).__name__}"],
            "etfCount": 0, "holdingRows": 0, "snapshotDate": expected,
            "expectedCodes": [], "succeededCodes": [],
        }
    return inspect_snapshot_payload(payload, expected_date=expected)


def _valid_snapshot(path: Path) -> bool:
    return bool(inspect_snapshot(path)["valid"])


def migrate_snapshots(
    sources: Iterable[str | os.PathLike[str]],
    target: str | os.PathLike[str] | None = None,
) -> dict:
    """Copy valid, missing snapshots into canonical storage without overwrite.

    Conflicting same-date files are reported and preserved at the source.  The
    function never deletes or mutates a source snapshot and uses atomic replace
    for new target files.
    """
    destination = Path(target) if target is not None else resolve_history_dir()
    destination = Path(os.path.abspath(str(destination)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    promote_directory = not destination.exists()
    working = destination
    if promote_directory:
        working = destination.parent / f".{destination.name}.migrate-{uuid.uuid4().hex[:12]}"
        working.mkdir(parents=False, exist_ok=False)
    copied: list[str] = []
    identical: list[str] = []
    conflicts: list[str] = []
    invalid: list[str] = []
    missing: list[str] = []

    found_source = False
    found_snapshot = False
    for source in (Path(item) for item in sources):
        if not source.is_dir():
            continue
        found_source = True
        for item in list_snapshot_files(source):
            found_snapshot = True
            if not _valid_snapshot(item):
                invalid.append(str(item))
                continue
            out = working / item.name
            if out.exists():
                if _sha256(item) == _sha256(out):
                    identical.append(item.name)
                else:
                    conflicts.append(item.name)
                continue
            if not promote_directory:
                missing.append(item.name)
                continue
            fd, temp_name = tempfile.mkstemp(prefix=item.name + ".", suffix=".tmp", dir=working)
            os.close(fd)
            temp = Path(temp_name)
            try:
                shutil.copy2(item, temp)
                os.replace(temp, out)
                copied.append(item.name)
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    staged_status = history_status(working)
    if not promote_directory:
        safe_noop = bool(found_source and found_snapshot and not invalid and not conflicts and not missing)
        return {
            "target": str(destination), "copied": [], "identical": identical,
            "conflicts": conflicts, "invalid": invalid, "missing": missing,
            "status": staged_status, "promoted": safe_noop, "noop": safe_noop,
        }
    if promote_directory:
        if (not found_source or not found_snapshot or invalid or conflicts or not staged_status.get("healthy")):
            return {
                "target": str(destination), "staging": str(working),
                "copied": copied, "identical": identical, "conflicts": conflicts,
                "invalid": invalid, "missing": missing,
                "status": staged_status, "promoted": False,
            }
        os.replace(working, destination)

    return {
        "target": str(destination),
        "copied": copied,
        "identical": identical,
        "conflicts": conflicts,
        "invalid": invalid,
        "missing": missing,
        "status": history_status(destination),
        "promoted": True,
    }
