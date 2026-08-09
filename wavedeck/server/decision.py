# -*- coding: utf-8 -*-
"""Decision providers — heuristic (demo) + interface for Ollama/OpenAI."""
from __future__ import annotations

import random
from typing import Any, Protocol

from .state import now_iso


class DecisionProvider(Protocol):
    name: str

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ...


class HeuristicProvider:
    """Deterministic-ish demo brain so the console is alive without API keys."""

    name = "heuristic"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        style = int(ctx.get("style") or 50)
        event = str(ctx.get("event") or "TIMED_MARKET_REVIEW")
        pos = int((ctx.get("positions") or {}).get("account") or 0)
        price = float(ctx.get("price") or 45020)
        # Style nudges confidence / bias
        long_bias = min(0.85, 0.45 + style / 200 + (0.08 if pos > 0 else 0))
        short_bias = max(0.15, 1.0 - long_bias)
        if pos > 0 and long_bias >= short_bias:
            action, label, conf = "HOLD", "維持續抱", long_bias
        elif pos == 0 and style >= 60:
            action, label, conf = "ENTER_LONG", "偏多進場", long_bias
        elif pos > 0 and short_bias > 0.55:
            action, label, conf = "REDUCE", "減碼觀察", short_bias
        else:
            action, label, conf = "HOLD", "觀望等待", max(long_bias, short_bias)

        inv = round(price - (35 + (100 - style) * 0.2), 0)
        summary = (
            f"事件 {event}：均線 MA20/MA60/MA150 結構仍偏多，"
            f"+DI/-DI 與 ADX 顯示趨勢未明顯轉壞。"
            f"進場風格={style}；"
            + (
                "持倉續抱，嚴守失效價。"
                if action == "HOLD" and pos > 0
                else "依風格與閘門決定下一動。"
            )
        )
        return {
            "action": action,
            "action_label": label,
            "confidence": round(conf + random.uniform(-0.02, 0.02), 2),
            "bias_long": round(long_bias, 2),
            "bias_short": round(short_bias, 2),
            "event": event,
            "summary": summary,
            "invalidation": {"price": inv, "side": "below"},
            "next_watch": ["失守短線結構再評估", "收盤前不留倉時窗"],
            "process": {
                "route": "heuristic→gate",
                "chase_risk": "low" if style < 45 else ("high" if style > 70 else "medium"),
                "gate": "PENDING",
            },
            "updated_at": now_iso(),
            "provider": self.name,
        }


PROVIDERS: dict[str, DecisionProvider] = {
    "heuristic": HeuristicProvider(),
}


def get_provider(name: str | None = None) -> DecisionProvider:
    """Resolve heuristic / ollama / openai (see providers.py)."""
    from .providers import resolve_provider

    return resolve_provider(name)
