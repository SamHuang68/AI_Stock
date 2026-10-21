# -*- coding: utf-8 -*-
"""紙上模擬權益（審查 WD-07）。

paper 券商的每筆模擬成交記入帳本；權益＝起始資金＋已實現損益＋未實現損益（台指期大台每點 200 元，
未計手續費與期交稅）。每個交易日第一次計算時的權益記為「昨日餘額」，供每日回撤上限使用。
沒有獨立報價來源：未實現損益以最近一筆訊號價格（exec.price）計算。價格缺漏或帳本與部位不一致時，
權益回報為未知，不以推估值觸發回撤鎖。
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from typing import Any

from .state import TZ8

SOURCE = "paper_sim"
DEFAULTS = {"starting_equity": 1_000_000, "point_value": 200}
# 成交只擁有部位與損益欄位；交易日基準（day、dayStartEquity）由 refresh 維護。
FILL_KEYS = ("position", "avgPrice", "realized", "priceUnknown", "lastFillPrice")


def settings(cfg: dict[str, Any] | None) -> dict[str, float]:
    raw = dict(DEFAULTS, **((cfg or {}).get("paper_account") or {}))
    return {"starting_equity": float(raw["starting_equity"]), "point_value": float(raw["point_value"])}


def trading_day(now: datetime) -> str:
    """期交所夜盤（15:00 起）歸屬下一個交易日；以 15:00 為換日點，週末順延到週一（未含國定假日）。"""
    local = now.astimezone(TZ8)
    day = local.date() + timedelta(days=1) if local.time() >= dtime(15, 0) else local.date()
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def _price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def apply_fill(ledger: dict[str, Any] | None, target: int, price: Any, point_value: float) -> dict[str, Any]:
    """依模擬成交更新帳本：反向或歸零先平倉實現損益，縮小部位實現平掉的口數，加碼更新平均成本。"""
    ledger = dict(ledger or {})
    pos = int(ledger.get("position") or 0)
    target = int(target)
    if target == pos:
        return ledger
    fill = _price(price)
    if fill is None or (pos and ledger.get("avgPrice") is None):
        # 沒有成交價或缺平均成本時無法評價；部位照記，損益標為未知直到部位歸零。
        ledger.update(position=target, avgPrice=None, priceUnknown=bool(target))
        return ledger
    avg = float(ledger["avgPrice"]) if pos else None
    realized = float(ledger.get("realized") or 0.0)
    if pos and (target == 0 or (target > 0) != (pos > 0)):
        realized += (fill - avg) * pos * point_value
        pos, avg = 0, None
    elif pos and abs(target) < abs(pos):
        realized += (fill - avg) * (pos - target) * point_value
        pos = target
    if target != pos:
        added = target - pos
        avg = fill if not pos else (avg * abs(pos) + fill * abs(added)) / abs(target)
        pos = target
    ledger.update(position=pos, avgPrice=round(avg, 4) if pos else None, realized=round(realized, 2),
                  priceUnknown=False, lastFillPrice=fill)
    return ledger


def fill_fields(ledger: dict[str, Any] | None) -> dict[str, Any]:
    """只回傳成交擁有的欄位；RUNTIME.patch 合併字典，送單用的舊快照不會覆寫交易日基準。"""
    return {key: ledger[key] for key in FILL_KEYS if key in (ledger or {})}


def refresh(state: dict[str, Any], cfg: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """回傳要寫入 RUNTIME 的 {account, paper_ledger}。"""
    opts = settings(cfg)
    ledger = dict(state.get("paper_ledger") or {})
    position = int((state.get("positions") or {}).get("account") or 0)
    mark = _price((state.get("exec") or {}).get("price"))
    known = (not ledger.get("priceUnknown") and int(ledger.get("position") or 0) == position
             and (position == 0 or (mark is not None and ledger.get("avgPrice") is not None)))
    unrealized = ((mark - float(ledger["avgPrice"])) * position * opts["point_value"]
                  if known and position else 0.0)
    equity = round(opts["starting_equity"] + float(ledger.get("realized") or 0.0) + unrealized, 2) if known else None
    day = trading_day(now)
    if ledger.get("day") != day and equity is not None:
        ledger.update(day=day, dayStartEquity=equity)
    start = ledger.get("dayStartEquity") if ledger.get("day") == day else None
    account = {
        "source": SOURCE, "reference": False,
        "yesterday_balance": start, "equity": equity,
        "equity_change": round(equity - start, 2) if equity is not None and start is not None else None,
        "realized": ledger.get("realized") or 0.0, "unrealized": round(unrealized, 2) if known else None,
        "mark_price": mark, "starting_equity": opts["starting_equity"], "point_value": opts["point_value"],
        "equity_status": "measured" if known else ("ledger_mismatch" if int(ledger.get("position") or 0) != position
                                                    else "price_unknown"),
        "broker_api": "paper", "position_sync": "simulated",
    }
    return {"account": account, "paper_ledger": ledger}
