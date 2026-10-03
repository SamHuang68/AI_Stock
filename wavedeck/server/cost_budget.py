# -*- coding: utf-8 -*-
"""依已核准價目與供應者限制，持久化控管請求准入日的費用額度。

日界線固定 UTC+08:00；跨日回應仍計入請求准入日，不等同供應者帳單日。
輸入費用採完整 context_window_tokens 預留，不估算文字或訊息框架 token。
此界限依賴配置引用的供應者強制 context window；max_completion_tokens
必須涵蓋可計費輸出（含推理 token）。來源、價目或限制未確認時不可配置啟用。
SQLite 保留未完成／未知請求；程序重啟不退款。所有程序須共用同一帳本。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any, Callable

TZ = timezone(timedelta(hours=8))
NANOS = 1_000_000_000
MAX_VALUE = Decimal("1000000")


class BudgetError(RuntimeError):
    def __init__(self, message: str, *, budget: dict[str, Any] | None = None):
        super().__init__(message)
        self.budget = budget


class BudgetExceeded(BudgetError):
    pass


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise BudgetError(f"{label}必須是有限非負數")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise BudgetError(f"{label}格式錯誤") from exc
    if not result.is_finite() or result < 0 or result > MAX_VALUE or (positive and result == 0):
        raise BudgetError(f"{label}超出允許範圍")
    # 控制最多十二位小數，讓 Decimal 的預設精度足以精確涵蓋所有乘積。
    if result.as_tuple().exponent < -12:
        raise BudgetError(f"{label}最多允許十二位小數")
    return result


def _tokens(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < int(positive) or value > 20_000_000:
        raise BudgetError(f"{label}必須是有效整數")
    return value


def _usd(nanos: int) -> float:
    return nanos / NANOS


def budget_day(now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise BudgetError("費用時鐘必須含時區")
    return stamp.astimezone(TZ).date().isoformat()


@dataclass(frozen=True)
class ModelPricing:
    model: str
    input_rate: Decimal
    output_rate: Decimal
    context_window_tokens: int
    max_output_tokens: int
    limits_source: str

    @classmethod
    def from_config(cls, cfg: dict[str, Any], model: str) -> "ModelPricing":
        entries = cfg.get("pricing")
        raw = entries.get(model) if isinstance(entries, dict) else None
        if not isinstance(model, str) or not model or len(model) > 128 or not isinstance(raw, dict):
            raise BudgetError("付費模型未配置完全相符的價目與成本限制")
        source = raw.get("limits_source")
        if not isinstance(source, str) or not source.strip() or len(source) > 1000:
            raise BudgetError("必須註明模型 context window 與輸出上限的確認來源")
        if raw.get("output_limit_parameter") != "max_completion_tokens":
            raise BudgetError("必須確認 max_completion_tokens 可限制全部可計費輸出")
        context = _tokens(raw.get("context_window_tokens"), "模型 context window", positive=True)
        output = _tokens(raw.get("max_output_tokens"), "輸出 token 上限", positive=True)
        if output > context:
            raise BudgetError("輸出 token 上限不可超過模型 context window")
        return cls(model, _decimal(raw.get("input_usd_per_million"), "輸入費率", positive=True),
                   _decimal(raw.get("output_usd_per_million"), "輸出費率", positive=True),
                   context, output, source.strip())

    def cost_nanos(self, prompt: int, completion: int) -> int:
        amount = (Decimal(prompt) * self.input_rate + Decimal(completion) * self.output_rate) * 1000
        return int(amount.to_integral_value(rounding=ROUND_CEILING))

    @property
    def reserve_nanos(self) -> int:
        return self.cost_nanos(self.context_window_tokens, self.max_output_tokens)

    def usage_nanos(self, usage: Any) -> int:
        if not isinstance(usage, dict):
            raise BudgetError("供應者未回傳完整 usage；保留預留額度")
        # Chat Completions 的原生欄位；缺少欄位不可用零或其他欄位替代。
        prompt = _tokens(usage.get("prompt_tokens"), "輸入 usage")
        completion = _tokens(usage.get("completion_tokens"), "輸出 usage")
        if "total_tokens" in usage and _tokens(usage["total_tokens"], "總 usage") != prompt + completion:
            raise BudgetError("供應者 usage 不一致；保留預留額度")
        return self.cost_nanos(prompt, completion)

    def record(self) -> str:
        return json.dumps({"model": self.model, "input_usd_per_million": str(self.input_rate),
                           "output_usd_per_million": str(self.output_rate),
                           "context_window_tokens": self.context_window_tokens,
                           "max_output_tokens": self.max_output_tokens,
                           "limits_source": self.limits_source}, ensure_ascii=False)


class CostBudget:
    """以整數奈美元保守進位；BEGIN IMMEDIATE 序列化跨程序准入。"""

    def __init__(self, path: Path, limit_usd: Any = 5, *, clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.limit_nanos = int((_decimal(limit_usd, "每日費用上限") * NANOS).to_integral_value(rounding=ROUND_FLOOR))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as con:
            con.execute("CREATE TABLE IF NOT EXISTS budget_days (day TEXT PRIMARY KEY, limit_nanos INTEGER NOT NULL)")
            con.execute("""CREATE TABLE IF NOT EXISTS budget_requests (
                id TEXT PRIMARY KEY, day TEXT NOT NULL, model TEXT NOT NULL,
                reserved_nanos INTEGER NOT NULL, spent_nanos INTEGER,
                status TEXT NOT NULL, pricing TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS budget_requests_day ON budget_requests(day)")

    @contextmanager
    def _transaction(self):
        con = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA synchronous=FULL")
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def _day(self, con: sqlite3.Connection, day: str) -> None:
        # 同日只允許收緊上限，避免不同程序的設定覆蓋造成穿透。
        con.execute("INSERT INTO budget_days(day, limit_nanos) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET limit_nanos=MIN(limit_nanos, excluded.limit_nanos)",
                    (day, self.limit_nanos))

    def _snapshot(self, con: sqlite3.Connection, day: str) -> dict[str, Any]:
        limit = con.execute("SELECT limit_nanos FROM budget_days WHERE day=?", (day,)).fetchone()[0]
        row = con.execute("""SELECT COALESCE(SUM(COALESCE(spent_nanos, 0)), 0) AS spent,
            COALESCE(SUM(CASE WHEN spent_nanos IS NULL THEN reserved_nanos ELSE 0 END), 0) AS reserved,
            COALESCE(SUM(status='unknown'), 0) AS unknown_count,
            COALESCE(SUM(status='reserved'), 0) AS pending_count
            FROM budget_requests WHERE day=?""", (day,)).fetchone()
        breach = bool(con.execute("SELECT 1 FROM budget_requests WHERE status='breached' LIMIT 1").fetchone())
        committed = row["spent"] + row["reserved"]
        return {"day": day, "timezone": "UTC+08:00", "day_basis": "request_admission",
                "limit_usd": _usd(limit), "spent_usd": _usd(row["spent"]),
                "reserved_usd": _usd(row["reserved"]), "committed_usd": _usd(committed),
                "available_usd": _usd(max(0, limit - committed)),
                "unknown_requests": row["unknown_count"], "pending_requests": row["pending_count"],
                "blocked": breach or committed >= limit, "limit_breached": breach,
                "guarantee": "configured_prices_and_provider_limits"}

    def snapshot(self, day: str | None = None) -> dict[str, Any]:
        selected = day or budget_day(self.clock())
        with self._transaction() as con:
            self._day(con, selected)
            return self._snapshot(con, selected)

    def reserve(self, pricing: ModelPricing) -> tuple[str, dict[str, Any]]:
        day = budget_day(self.clock())
        request_id = uuid.uuid4().hex
        denied = False
        with self._transaction() as con:
            self._day(con, day)
            before = self._snapshot(con, day)
            # 比較採帳本整數，避免顯示用浮點數影響精確邊界。
            available = con.execute("""SELECT d.limit_nanos - COALESCE(SUM(COALESCE(r.spent_nanos, r.reserved_nanos)), 0)
                FROM budget_days d LEFT JOIN budget_requests r ON r.day=d.day WHERE d.day=? GROUP BY d.day""", (day,)).fetchone()[0]
            if before["limit_breached"] or pricing.reserve_nanos > available:
                denied = True
                result = {**before, "blocked": True, "status": "blocked", "reason": "費用預留將超過每日上限，或價目限制已失效"}
            else:
                con.execute("INSERT INTO budget_requests VALUES (?, ?, ?, ?, NULL, 'reserved', ?)",
                            (request_id, day, pricing.model, pricing.reserve_nanos, pricing.record()))
                result = self._request_snapshot(con, request_id)
        if denied:
            raise BudgetExceeded(result["reason"], budget=result)
        return request_id, result

    def _request_snapshot(self, con: sqlite3.Connection, request_id: str) -> dict[str, Any]:
        row = con.execute("SELECT * FROM budget_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise BudgetError("費用預留紀錄不存在")
        result = self._snapshot(con, row["day"])
        result.update({"request_id": request_id, "request_status": row["status"],
                       "request_reserved_usd": _usd(row["reserved_nanos"]),
                       "request_cost_usd": None if row["spent_nanos"] is None else _usd(row["spent_nanos"]),
                       "usage_known": row["spent_nanos"] is not None, "pricing_configured": True})
        return result

    def retain_unknown(self, request_id: str) -> dict[str, Any]:
        with self._transaction() as con:
            con.execute("UPDATE budget_requests SET status='unknown' WHERE id=? AND status='reserved'", (request_id,))
            return self._request_snapshot(con, request_id)

    def settle(self, request_id: str, pricing: ModelPricing, usage: Any) -> dict[str, Any]:
        amount = pricing.usage_nanos(usage)
        # 即使費用沒有超額，token 越界也表示成本限制的前提已失效。
        limit_breach = usage["prompt_tokens"] > pricing.context_window_tokens or usage["completion_tokens"] > pricing.max_output_tokens
        with self._transaction() as con:
            row = con.execute("SELECT * FROM budget_requests WHERE id=?", (request_id,)).fetchone()
            if row is None or row["pricing"] != pricing.record():
                raise BudgetError("費用預留與價目不一致")
            if row["spent_nanos"] is not None:
                if row["spent_nanos"] != amount:
                    raise BudgetError("重複結算的 usage 不一致")
            else:
                state = "breached" if limit_breach or amount > row["reserved_nanos"] else "settled"
                con.execute("UPDATE budget_requests SET spent_nanos=?, status=? WHERE id=?", (amount, state, request_id))
            result = self._request_snapshot(con, request_id)
        if result["limit_breached"]:
            raise BudgetError("供應者回報超出已配置成本限制；停止後續付費請求", budget=result)
        return result
