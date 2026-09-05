# -*- coding: utf-8 -*-
"""ETF 個股權重變化排名的純函式契約。

本模組只比較呼叫端傳入的兩份原始 ETF 快照，不讀檔、不抓網路，也不
改變既有追蹤器。排名單位固定為 ETF 權重的「百分點」（percentage
points）；持股股數只保留為稽核欄位，絕不參與方向判定或排序。

可比較條件採保守原則：同一 ETF、相同資料來源、供應商資料日確實前進，
且兩期皆為完整覆蓋。ETF 首次出現、蒐集缺漏、前十大 fallback 或來源切換
都只會列入 ``excluded``，不會把整籃持股誤判為新增或移除。
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_VERSION = "st-etf-weight-rankings/v1"
METRIC = "weight_delta_percentage_points"
_RESERVED_ROOT_KEYS = {"date", "updated", "meta", "summary", "etfs"}
_MIN_COUNT_CONTINUITY = Decimal("0.60")
_COUNT_CONTINUITY_MIN_SIZE = 10
_REASON_LABELS = {
    "current_snapshot_missing": "當期快照缺漏",
    "previous_snapshot_missing": "前期快照缺漏，無法建立比較基準",
    "current_snapshot_empty": "當期快照沒有 ETF 資料",
    "previous_snapshot_empty": "前期快照沒有 ETF 資料",
    "previous_snapshot_invalid": "前期快照格式無效",
    "current_etf_collection_failed": "當期 ETF 蒐集失敗",
    "previous_etf_collection_failed": "前期 ETF 蒐集失敗",
    "current_etf_missing": "當期 ETF 資料缺漏",
    "previous_etf_missing": "前期 ETF 應有資料但實際缺漏",
    "no_baseline": "ETF 首次出現，尚無前期基準",
    "no_distinct_source_date_baseline": "近期待比較快照皆為相同供應商資料日",
    "out_of_scope": "ETF 已不在當期觀測範圍",
    "source_missing": "資料來源未標示",
    "source_mismatch": "前後期資料來源不同",
    "source_date_missing": "供應商資料日未標示",
    "source_date_invalid": "供應商資料日格式無效",
    "source_date_not_advanced": "供應商資料日尚未前進",
    "source_date_regressed": "供應商資料日早於前期",
    "coverage_mismatch": "前後期資料覆蓋範圍不同",
    "partial_coverage": "僅有部分持股，暫不排名",
    "coverage_unknown": "無法確認持股覆蓋範圍",
    "holdings_missing": "持股清單格式缺漏",
    "holdings_empty": "持股清單為空",
    "coverage_total_mismatch": "持股總數與清單筆數不符",
    "coverage_count_discontinuity": "前後期持股筆數落差異常",
    "holding_identity_missing": "持股代號缺漏",
    "duplicate_holding_identity": "同市場持股代號重複",
    "weight_invalid": "持股權重無效",
}


def _snapshot_date(snapshot: Mapping[str, Any] | None) -> str | None:
    if not isinstance(snapshot, Mapping):
        return None
    normalized, _ = _parse_date(snapshot.get("date"))
    return normalized


def _parse_date(value: Any) -> tuple[str | None, dt.date | None]:
    if isinstance(value, dt.datetime):
        day = value.date()
        return day.isoformat(), day
    if isinstance(value, dt.date):
        return value.isoformat(), value
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    if re.fullmatch(r"\d{8}", raw):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    else:
        raw = raw.replace("/", "-")
    try:
        day = dt.date.fromisoformat(raw[:10])
    except (TypeError, ValueError):
        return None, None
    return day.isoformat(), day


def _extract_etfs(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    nested = snapshot.get("etfs")
    if isinstance(nested, Mapping):
        for raw_code, raw_etf in nested.items():
            code = str(raw_code or "").strip().upper()
            if code and isinstance(raw_etf, Mapping):
                result[code] = raw_etf
    elif isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
        for raw_etf in nested:
            if not isinstance(raw_etf, Mapping):
                continue
            code = str(raw_etf.get("code") or raw_etf.get("etf_code") or "").strip().upper()
            if code:
                result[code] = raw_etf

    for raw_code, raw_etf in snapshot.items():
        if str(raw_code).lower() in _RESERVED_ROOT_KEYS:
            continue
        code = str(raw_code or "").strip().upper()
        if not code or code in result:
            continue
        if isinstance(raw_etf, Mapping):
            result[code] = raw_etf
    return result


def _manifest_codes(snapshot: Mapping[str, Any], key: str) -> set[str]:
    meta = snapshot.get("meta")
    if not isinstance(meta, Mapping):
        return set()
    value = meta.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return set()
    return {str(code).strip().upper() for code in value if str(code).strip()}


def _source(etf: Mapping[str, Any]) -> str:
    return str(etf.get("source") or "").strip()


def _coverage_kind(etf: Mapping[str, Any]) -> str:
    raw: Any = etf.get("coverage_kind")
    if raw is None:
        raw = etf.get("coverageKind")
    if raw is None:
        raw = etf.get("coverage")
    if isinstance(raw, Mapping):
        raw = raw.get("kind") or raw.get("scope") or raw.get("type")
    if isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
        try:
            ratio = Decimal(str(raw))
            return "full" if ratio >= Decimal("0.999") else "partial"
        except InvalidOperation:
            pass
    label = str(raw or "").strip().lower().replace("_", "-")
    if label:
        if label in {"full", "complete", "all", "全部", "完整"}:
            return "full"
        if label in {"partial", "top10", "top-10", "前十大", "部分"}:
            return "partial"
        return label

    source = _source(etf).lower().replace("_", "-")
    if source in {"moneydj-top10", "moneydj-top-10"}:
        return "partial"
    if source in {"moneydj-full", "twse"}:
        return "full"
    return "unknown"


def _holdings(etf: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    value = etf.get("holdings")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    rows = [item for item in value if isinstance(item, Mapping)]
    return rows if len(rows) == len(value) else None


def _declared_total_matches(etf: Mapping[str, Any], actual: int) -> bool:
    if "total" not in etf or etf.get("total") is None:
        return True
    try:
        declared = int(etf.get("total"))
    except (TypeError, ValueError, OverflowError):
        return False
    return declared == actual


def _normalize_identity(holding: Mapping[str, Any]) -> tuple[str, str, str] | None:
    raw_code = holding.get("code")
    if raw_code is None:
        raw_code = holding.get("symbol")
    if raw_code is None:
        raw_code = holding.get("stock_code")
    if raw_code is None:
        raw_code = holding.get("ticker")
    code = str(raw_code or "").strip().upper()
    if not code:
        return None

    market = str(holding.get("market") or "").strip().upper()
    suffix = re.fullmatch(r"(.+)\.([A-Z]{1,4})", code)
    if suffix:
        code = suffix.group(1)
        if not market:
            market = suffix.group(2)
    if not market:
        # TWSE fallback 的持股沒有 market；純數字及台股常見尾碼可安全歸 TW。
        market = "TW" if re.fullmatch(r"\d{4,6}[A-Z]?", code) else "UNKNOWN"
    return f"{code}.{market}", code, market


def _decimal_weight(holding: Mapping[str, Any]) -> Decimal | None:
    value: Any = None
    found = False
    for key in ("weight", "pct", "weight_pct"):
        if key in holding:
            value = holding.get(key)
            found = True
            break
    if not found or value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or number > 100:
        return None
    return number


def _integer_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _holding_map(
    holdings: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    result: dict[str, dict[str, Any]] = {}
    for holding in holdings:
        identity = _normalize_identity(holding)
        if identity is None:
            return None, "holding_identity_missing"
        symbol_key, code, market = identity
        if symbol_key in result:
            return None, "duplicate_holding_identity"
        weight = _decimal_weight(holding)
        if weight is None:
            return None, "weight_invalid"
        shares: Any = None
        for key in ("shares", "quantity", "volume"):
            if key in holding:
                shares = holding.get(key)
                break
        rank: Any = None
        for key in ("rank", "holding_rank"):
            if key in holding:
                rank = holding.get(key)
                break
        name = ""
        for key in ("name", "stock_name", "company_name"):
            if holding.get(key):
                name = str(holding.get(key)).strip()
                break
        result[symbol_key] = {
            "symbol_key": symbol_key,
            "code": code,
            "market": market,
            "name": name,
            "weight": weight,
            "shares": _integer_or_none(shares),
            "rank": rank,
        }
    return result, None


def _base_result(
    current_snapshot: Mapping[str, Any] | None,
    previous_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "metric": METRIC,
        "aggregation": "none_per_etf_stock_row",
        "snapshot_date": _snapshot_date(current_snapshot),
        "prev_snapshot_date": _snapshot_date(previous_snapshot),
        "source_dates": {"current": [], "previous": []},
        "status": "no_comparable_etfs",
        "comparable_etf_count": 0,
        "excluded_etf_count": 0,
        "rows": [],
        "excluded": [],
        "excluded_reasons": {},
    }


def _finish(result: dict[str, Any], current_dates: set[str], previous_dates: set[str]) -> dict[str, Any]:
    result["rows"].sort(
        key=lambda row: (
            -Decimal(str(row["delta_pp"])),
            row["etf_code"],
            row["market"],
            row["code"],
        )
    )
    for item in result["excluded"]:
        item.setdefault("reason_label", _REASON_LABELS.get(item["reason"], "無法建立可靠比較"))
    result["excluded"].sort(key=lambda item: (item["etf_code"], item["reason"]))
    result["excluded_etf_count"] = len(result["excluded"])
    result["excluded_reasons"] = dict(
        sorted(Counter(item["reason"] for item in result["excluded"]).items())
    )
    result["source_dates"] = {
        "current": sorted(current_dates),
        "previous": sorted(previous_dates),
    }
    if result["comparable_etf_count"]:
        result["status"] = "ok"
    return result


def _same_provider_date_is_safe_to_skip(
    current_etf: Mapping[str, Any],
    previous_etf: Mapping[str, Any],
) -> bool:
    """只辨識可證明為同批資料的重複快照。

    此函式刻意嚴格：若來源、完整度、持股筆數或內容結構有任一疑點，
    history 搜尋就不能略過該份快照去挑更早、看似較好的基準。
    """
    current_source = _source(current_etf)
    previous_source = _source(previous_etf)
    if not current_source or current_source.casefold() != previous_source.casefold():
        return False
    if _coverage_kind(current_etf) != "full" or _coverage_kind(previous_etf) != "full":
        return False

    _, current_day = _parse_date(current_etf.get("date"))
    _, previous_day = _parse_date(previous_etf.get("date"))
    if current_day is None or current_day != previous_day:
        return False

    current_holdings = _holdings(current_etf)
    previous_holdings = _holdings(previous_etf)
    if not current_holdings or not previous_holdings:
        return False
    if (
        not _declared_total_matches(current_etf, len(current_holdings))
        or not _declared_total_matches(previous_etf, len(previous_holdings))
    ):
        return False
    smaller = min(len(current_holdings), len(previous_holdings))
    larger = max(len(current_holdings), len(previous_holdings))
    if larger >= _COUNT_CONTINUITY_MIN_SIZE and Decimal(smaller) / Decimal(larger) < _MIN_COUNT_CONTINUITY:
        return False
    current_map, current_error = _holding_map(current_holdings)
    previous_map, previous_error = _holding_map(previous_holdings)
    return current_map is not None and previous_map is not None and not current_error and not previous_error


def build_weight_rankings(
    current_snapshot: Mapping[str, Any] | None,
    previous_snapshot: Mapping[str, Any] | None,
    *,
    allowed_codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """建立可排序的 ETF×個股權重百分點變化列。

    ``rows`` 的 ``status`` 僅有 ``increased``、``decreased``、``added``、
    ``removed``。新增／移除只有在 ETF 兩期皆通過比較閘門時才會產生。
    結果預設按 ``delta_pp`` 降冪，UI 仍可透過共用表格排序器切換順序。
    """
    current = current_snapshot if isinstance(current_snapshot, Mapping) else None
    previous = previous_snapshot if isinstance(previous_snapshot, Mapping) else None
    result = _base_result(current, previous)
    current_dates: set[str] = set()
    previous_dates: set[str] = set()

    if current is None:
        result["excluded"].append({"etf_code": "*", "reason": "current_snapshot_missing"})
        return _finish(result, current_dates, previous_dates)
    if previous is None:
        result["excluded"].append({"etf_code": "*", "reason": "previous_snapshot_missing"})
        return _finish(result, current_dates, previous_dates)

    current_etfs = _extract_etfs(current)
    previous_etfs = _extract_etfs(previous)
    if not current_etfs:
        result["excluded"].append({"etf_code": "*", "reason": "current_snapshot_empty"})
        return _finish(result, current_dates, previous_dates)
    if not previous_etfs:
        result["excluded"].append({"etf_code": "*", "reason": "previous_snapshot_empty"})
        return _finish(result, current_dates, previous_dates)

    current_expected = _manifest_codes(current, "expectedCodes")
    previous_expected = _manifest_codes(previous, "expectedCodes")
    current_failed = _manifest_codes(current, "failedCodes")
    previous_failed = _manifest_codes(previous, "failedCodes")

    comparison_codes = set(current_etfs) | set(previous_etfs)
    if allowed_codes is not None:
        normalized_allowed = {
            str(code).strip().upper() for code in allowed_codes if str(code).strip()
        }
        comparison_codes &= normalized_allowed

    for etf_code in sorted(comparison_codes):
        current_etf = current_etfs.get(etf_code)
        previous_etf = previous_etfs.get(etf_code)

        if current_etf is None:
            if etf_code in current_failed:
                reason = "current_etf_collection_failed"
            elif current_expected and etf_code not in current_expected:
                reason = "out_of_scope"
            else:
                reason = "current_etf_missing"
            result["excluded"].append({"etf_code": etf_code, "reason": reason})
            continue
        if previous_etf is None:
            if etf_code in previous_failed:
                reason = "previous_etf_collection_failed"
            elif previous_expected and etf_code in previous_expected:
                reason = "previous_etf_missing"
            else:
                # 新納入 catalog 或首次有資料皆屬無比較基準，不得把持股推零。
                reason = "no_baseline"
            result["excluded"].append({"etf_code": etf_code, "reason": reason})
            continue

        current_source = _source(current_etf)
        previous_source = _source(previous_etf)
        current_date, current_day = _parse_date(current_etf.get("date"))
        previous_date, previous_day = _parse_date(previous_etf.get("date"))
        current_coverage = _coverage_kind(current_etf)
        previous_coverage = _coverage_kind(previous_etf)
        diagnostic = {
            "etf_code": etf_code,
            "current_source": current_source or None,
            "previous_source": previous_source or None,
            "date": current_date,
            "prev_date": previous_date,
            "current_coverage": current_coverage,
            "previous_coverage": previous_coverage,
        }

        reason: str | None = None
        if not current_source or not previous_source:
            reason = "source_missing"
        elif current_source.casefold() != previous_source.casefold():
            reason = "source_mismatch"
        elif current_coverage != previous_coverage:
            reason = "coverage_mismatch"
        elif current_coverage == "partial":
            reason = "partial_coverage"
        elif current_coverage != "full":
            reason = "coverage_unknown"
        elif current_etf.get("date") in (None, "") or previous_etf.get("date") in (None, ""):
            reason = "source_date_missing"
        elif current_day is None or previous_day is None:
            reason = "source_date_invalid"
        elif current_day == previous_day:
            reason = "source_date_not_advanced"
        elif current_day < previous_day:
            reason = "source_date_regressed"

        current_holdings = _holdings(current_etf)
        previous_holdings = _holdings(previous_etf)
        if reason is None and (current_holdings is None or previous_holdings is None):
            reason = "holdings_missing"
        elif reason is None and (not current_holdings or not previous_holdings):
            reason = "holdings_empty"
        elif reason is None and (
            not _declared_total_matches(current_etf, len(current_holdings))
            or not _declared_total_matches(previous_etf, len(previous_holdings))
        ):
            reason = "coverage_total_mismatch"
        elif reason is None:
            smaller = min(len(current_holdings), len(previous_holdings))
            larger = max(len(current_holdings), len(previous_holdings))
            if larger >= _COUNT_CONTINUITY_MIN_SIZE and Decimal(smaller) / Decimal(larger) < _MIN_COUNT_CONTINUITY:
                reason = "coverage_count_discontinuity"

        if reason is not None:
            result["excluded"].append({**diagnostic, "reason": reason})
            continue

        assert current_holdings is not None and previous_holdings is not None
        current_map, current_map_error = _holding_map(current_holdings)
        previous_map, previous_map_error = _holding_map(previous_holdings)
        map_error = current_map_error or previous_map_error
        if map_error:
            result["excluded"].append({**diagnostic, "reason": map_error})
            continue
        assert current_map is not None and previous_map is not None

        result["comparable_etf_count"] += 1
        current_dates.add(current_date)
        previous_dates.add(previous_date)
        etf_name = str(current_etf.get("name") or previous_etf.get("name") or etf_code).strip()

        for symbol_key in sorted(set(current_map) | set(previous_map)):
            current_holding = current_map.get(symbol_key)
            previous_holding = previous_map.get(symbol_key)
            if current_holding is None:
                assert previous_holding is not None
                current_weight = Decimal("0")
                previous_weight = previous_holding["weight"]
                status = "removed"
                reference = previous_holding
            elif previous_holding is None:
                current_weight = current_holding["weight"]
                previous_weight = Decimal("0")
                status = "added"
                reference = current_holding
            else:
                current_weight = current_holding["weight"]
                previous_weight = previous_holding["weight"]
                delta = current_weight - previous_weight
                if delta == 0:
                    # 股數變化不是本排名的方向或納入條件。
                    continue
                status = "increased" if delta > 0 else "decreased"
                reference = current_holding

            delta = current_weight - previous_weight
            current_shares = current_holding["shares"] if current_holding else 0
            previous_shares = previous_holding["shares"] if previous_holding else 0
            shares_delta = (
                current_shares - previous_shares
                if current_shares is not None and previous_shares is not None
                else None
            )
            result["rows"].append({
                "etf_code": etf_code,
                "etf_name": etf_name,
                "code": reference["code"],
                "name": (current_holding or {}).get("name") or (previous_holding or {}).get("name") or "",
                "market": reference["market"],
                "symbol_key": symbol_key,
                "prev_weight": float(previous_weight),
                "weight": float(current_weight),
                "delta_pp": float(delta),
                "prev_date": previous_date,
                "date": current_date,
                "source": current_source,
                "status": status,
                "prev_rank": previous_holding["rank"] if previous_holding else None,
                "rank": current_holding["rank"] if current_holding else None,
                "prev_shares": previous_shares,
                "shares": current_shares,
                "shares_delta": shares_delta,
                "coverage": current_coverage,
            })

    return _finish(result, current_dates, previous_dates)


def build_weight_rankings_from_history(
    current_snapshot: Mapping[str, Any] | None,
    previous_snapshots: Iterable[Mapping[str, Any] | None],
    *,
    allowed_codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """以每檔 ETF 最近的不同供應商資料日建立排名。

    ``previous_snapshots`` 必須由新到舊排列，函式最多檢查 20 份。搜尋時
    只會跳過可完整驗證的「同 ETF、同來源、同覆蓋、同供應商資料日」
    重複快照；遇到來源切換、ETF 缺漏或結構錯誤會立即排除該 ETF，
    不會繼續往前挑選有利基準。
    """
    current = current_snapshot if isinstance(current_snapshot, Mapping) else None
    history = list(previous_snapshots or [])[:20]
    newest_valid_mapping = next((item for item in history if isinstance(item, Mapping)), None)
    result = _base_result(current, newest_valid_mapping)
    # 不存在單一共用的前期快照；每列與 baselines 都會保留實際基準。
    result["prev_snapshot_date"] = None
    result["baseline_mode"] = "per_etf_nearest_distinct_provider_date"
    result["baseline_snapshot_dates"] = []
    result["baselines"] = []
    current_dates: set[str] = set()
    previous_dates: set[str] = set()
    baseline_snapshot_dates: set[str] = set()

    if current is None:
        result["excluded"].append({"etf_code": "*", "reason": "current_snapshot_missing"})
        return _finish(result, current_dates, previous_dates)
    current_etfs = _extract_etfs(current)
    if not current_etfs:
        result["excluded"].append({"etf_code": "*", "reason": "current_snapshot_empty"})
        return _finish(result, current_dates, previous_dates)
    if not history:
        result["excluded"].append({"etf_code": "*", "reason": "previous_snapshot_missing"})
        return _finish(result, current_dates, previous_dates)

    if allowed_codes is None:
        comparison_codes = set(current_etfs)
        first = history[0]
        if isinstance(first, Mapping):
            comparison_codes |= set(_extract_etfs(first))
    else:
        comparison_codes = {
            str(code).strip().upper() for code in allowed_codes if str(code).strip()
        }

    current_expected = _manifest_codes(current, "expectedCodes")
    current_failed = _manifest_codes(current, "failedCodes")
    current_snapshot_day = _snapshot_date(current)

    for etf_code in sorted(comparison_codes):
        current_etf = current_etfs.get(etf_code)
        if current_etf is None:
            if etf_code in current_failed:
                reason = "current_etf_collection_failed"
            elif current_expected and etf_code not in current_expected:
                reason = "out_of_scope"
            else:
                reason = "current_etf_missing"
            result["excluded"].append({"etf_code": etf_code, "reason": reason})
            continue

        selected = False
        skipped_same_date = False
        for candidate_snapshot in history:
            if not isinstance(candidate_snapshot, Mapping):
                result["excluded"].append({
                    "etf_code": etf_code,
                    "reason": "previous_snapshot_invalid",
                })
                selected = True
                break

            previous_etfs = _extract_etfs(candidate_snapshot)
            previous_etf = previous_etfs.get(etf_code)
            if previous_etf is None:
                failed = _manifest_codes(candidate_snapshot, "failedCodes")
                expected = _manifest_codes(candidate_snapshot, "expectedCodes")
                if etf_code in failed:
                    reason = "previous_etf_collection_failed"
                elif expected and etf_code in expected:
                    reason = "previous_etf_missing"
                else:
                    reason = "no_baseline"
                result["excluded"].append({"etf_code": etf_code, "reason": reason})
                selected = True
                break

            if _same_provider_date_is_safe_to_skip(current_etf, previous_etf):
                skipped_same_date = True
                continue

            pair_current = {"date": current_snapshot_day, etf_code: current_etf}
            pair_previous = {
                "date": _snapshot_date(candidate_snapshot),
                etf_code: previous_etf,
            }
            pair = build_weight_rankings(
                pair_current,
                pair_previous,
                allowed_codes={etf_code},
            )
            if pair["comparable_etf_count"]:
                previous_snapshot_day = _snapshot_date(candidate_snapshot)
                for row in pair["rows"]:
                    row["snapshot_date"] = current_snapshot_day
                    row["prev_snapshot_date"] = previous_snapshot_day
                    result["rows"].append(row)
                result["comparable_etf_count"] += 1
                current_dates.update(pair["source_dates"]["current"])
                previous_dates.update(pair["source_dates"]["previous"])
                if previous_snapshot_day:
                    baseline_snapshot_dates.add(previous_snapshot_day)
                current_source_date, _ = _parse_date(current_etf.get("date"))
                previous_source_date, _ = _parse_date(previous_etf.get("date"))
                result["baselines"].append({
                    "etf_code": etf_code,
                    "snapshot_date": current_snapshot_day,
                    "prev_snapshot_date": previous_snapshot_day,
                    "date": current_source_date,
                    "prev_date": previous_source_date,
                    "source": _source(current_etf),
                })
            else:
                for item in pair["excluded"]:
                    result["excluded"].append({**item, "etf_code": etf_code})
            selected = True
            break

        if not selected:
            reason = "no_distinct_source_date_baseline" if skipped_same_date else "no_baseline"
            result["excluded"].append({"etf_code": etf_code, "reason": reason})

    result["baselines"].sort(key=lambda item: item["etf_code"])
    result["baseline_snapshot_dates"] = sorted(baseline_snapshot_dates)
    return _finish(result, current_dates, previous_dates)


__all__ = [
    "build_weight_rankings",
    "build_weight_rankings_from_history",
    "CONTRACT_VERSION",
    "METRIC",
]
