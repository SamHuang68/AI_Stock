"""每日臺灣時間截止規則；不推定交易所日盤、夜盤或假日行事曆。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .state import TZ8


def deadline_status(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """計算當日截止與禁新單區間，未完成委託由執行層跨日保留。

    now 須帶時區，統一轉換為 TZ8；預設使用真實 TZ8 時鐘。
    每日截止後持續禁新單至午夜，午夜按新日期重算。
    無效設定禁止新單並回報錯誤，但不猜測強制平倉時間。
    """
    current = now if now is not None else datetime.now(TZ8)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("不留倉時鐘必須包含時區")
    current = current.astimezone(TZ8)
    config = state.get("no_overnight") or {}
    result: dict[str, Any] = {
        "enabled": bool(config.get("enabled")),
        "blocked_new": False,
        "due": False,
        "deadline": None,
        "date": current.date().isoformat(),
        "error": None,
    }
    if not result["enabled"]:
        return result
    try:
        parts = str(config.get("force_flat_time") or "13:40").split(":")
        if len(parts) != 2:
            raise ValueError("截止時間須為 HH:MM")
        hour, minute = (int(part) for part in parts)
        raw_lead = config.get("block_new_before_close_min", 15)
        lead = int(raw_lead)
        if isinstance(raw_lead, bool) or str(raw_lead).strip() != str(lead) or not 0 <= lead <= 1440:
            raise ValueError("禁新單分鐘數須為 0 至 1440 的整數")
        deadline = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (TypeError, ValueError, OverflowError):
        result.update(blocked_new=True, error="不留倉設定無效：請檢查截止時間及禁新單分鐘數")
        return result
    result.update(
        deadline=deadline,
        blocked_new=current >= deadline - timedelta(minutes=lead),
        due=current >= deadline,
    )
    return result
