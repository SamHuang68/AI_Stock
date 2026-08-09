# -*- coding: utf-8 -*-
"""Decision providers — heuristic (demo) + interface for Ollama/OpenAI."""
from __future__ import annotations

import random
from typing import Any, Optional, Protocol

from .state import now_iso


class DecisionProvider(Protocol):
    name: str

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ...


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


class HeuristicProvider:
    """Deterministic-ish demo brain so the console is alive without API keys.

    Respects ST macro overlay fields when present:
    st_spillover_prob / st_delever / st_hot_stage / st_score / st_rotation.
    """

    name = "heuristic"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        style = int(ctx.get("style") or 50)
        event = str(ctx.get("event") or "TIMED_MARKET_REVIEW")
        pos = int((ctx.get("positions") or {}).get("account") or 0)
        price = float(ctx.get("price") or 45020)

        spill = _f(ctx.get("st_spillover_prob"))
        delever = bool(ctx.get("st_delever"))
        hot = ctx.get("st_hot_stage")
        st_score = _f(ctx.get("st_score"))
        rotation = ctx.get("st_rotation")

        # Effective style after ST macro / spillover
        eff_style = style
        if spill is not None:
            if spill < 0.30:
                eff_style = min(eff_style, 40)
            elif spill > 0.65:
                eff_style = max(eff_style, min(65, eff_style + 5))
        if delever:
            eff_style = min(eff_style, 40)
        if st_score is not None and st_score < 35:
            eff_style = min(eff_style, 40)

        long_bias = min(0.85, 0.45 + eff_style / 200 + (0.08 if pos > 0 else 0))
        if spill is not None:
            if spill < 0.30:
                long_bias = max(0.20, long_bias * 0.85)
            elif spill > 0.65:
                long_bias = min(0.85, long_bias + 0.05)
        short_bias = max(0.15, 1.0 - long_bias)

        if pos > 0 and long_bias >= short_bias:
            if spill is not None and spill < 0.30 and short_bias > 0.40:
                action, label, conf = "REDUCE", "外溢偏低減碼", max(short_bias, 0.55)
            else:
                action, label, conf = "HOLD", "維持續抱", long_bias
        elif pos == 0 and style >= 60:
            if spill is not None and spill < 0.30:
                action, label, conf = "HOLD", "外溢偏低觀望", max(long_bias, 0.50)
            elif delever:
                action, label, conf = "HOLD", "降載觀望", max(long_bias, 0.50)
            else:
                action, label, conf = "ENTER_LONG", "偏多進場", long_bias
        elif pos > 0 and short_bias > 0.55:
            action, label, conf = "REDUCE", "減碼觀察", short_bias
        else:
            action, label, conf = "HOLD", "觀望等待", max(long_bias, short_bias)

        if spill is not None and spill < 0.30:
            chase = "high"
        elif eff_style < 45:
            chase = "low"
        elif eff_style > 70:
            chase = "high"
        else:
            chase = "medium"

        inv = round(price - (35 + (100 - eff_style) * 0.2), 0)
        bits = [
            f"事件 {event}：均線 MA20/MA60/MA150 結構仍偏多，",
            f"+DI/-DI 與 ADX 顯示趨勢未明顯轉壞。",
            f"進場風格={style}",
        ]
        if eff_style != style:
            bits.append(f"（有效 {eff_style}）")
        bits.append("；")
        if spill is not None:
            bits.append(f"供應鏈外溢={spill:.0%}；")
        if hot:
            bits.append(f"最強鏈段={hot}；")
        if rotation:
            bits.append(f"輪動={rotation}；")
        if delever:
            bits.append("ST 降載中；")
        if action == "HOLD" and pos > 0:
            bits.append("持倉續抱，嚴守失效價。")
        else:
            bits.append("依風格、外溢與閘門決定下一動。")
        summary = "".join(bits)

        watch = ["失守短線結構再評估", "收盤前不留倉時窗"]
        if hot:
            watch.insert(0, f"供應鏈最強段：{hot}")
        if spill is not None and spill < 0.35:
            watch.insert(0, "外溢偏低：慎追單一族群")

        return {
            "action": action,
            "action_label": label,
            "confidence": round(max(0.1, min(0.95, conf + random.uniform(-0.02, 0.02))), 2),
            "bias_long": round(long_bias, 2),
            "bias_short": round(short_bias, 2),
            "event": event,
            "summary": summary,
            "invalidation": {"price": inv, "side": "below"},
            "next_watch": watch[:6],
            "process": {
                "route": "heuristic→gate",
                "chase_risk": chase,
                "gate": "PENDING",
                "eff_style": eff_style,
                "st_spillover_prob": spill,
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
