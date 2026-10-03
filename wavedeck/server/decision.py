# -*- coding: utf-8 -*-
"""Decision providers — heuristic (demo) + interface for Ollama/OpenAI."""
from __future__ import annotations

from typing import Any, Optional, Protocol

from .data_contract import finite_number
from .state import now_iso


class DecisionProvider(Protocol):
    name: str

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ...


def _f(v: Any) -> Optional[float]:
    return finite_number(v)


class HeuristicProvider:
    """確定性的紙上規則演練；分數不代表經驗證的信心度或勝率。"""

    name = "heuristic"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        style = int(ctx.get("style") or 50)
        event = str(ctx.get("event") or "TIMED_MARKET_REVIEW")
        pos = int((ctx.get("positions") or {}).get("account") or 0)

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

        raw_inv = ctx.get("decision_invalidation") or ctx.get("st_decision_invalidation") or ctx.get("invalidation") or {}
        raw_inv = raw_inv if isinstance(raw_inv, dict) else {}
        inv = finite_number(raw_inv.get("price"))
        side = raw_inv.get("side")
        if inv is None or inv <= 0 or side not in {"below", "above"}:
            inv, side = None, None
        bits = [
            f"紙上規則演練（非勝率）：事件 {event}；",
            "未驗證均線與 ADX，不據此判斷趨勢；",
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
            bits.append("紙上持倉維持；" + ("依已提供失效條件觀察。" if inv is not None else "失效價未知，等待來源條件。"))
        else:
            bits.append("依風格、外溢與閘門決定下一動。")
        summary = "".join(bits)

        watch = ["確認來源行情與失效條件", "收盤前不留倉時窗"]
        if hot:
            watch.insert(0, f"供應鏈最強段：{hot}")
        if spill is not None and spill < 0.35:
            watch.insert(0, "外溢偏低：慎追單一族群")

        return {
            "action": action,
            "action_label": label,
            "confidence": None,
            "demo": True,
            "rule_score": round(conf, 2),
            "bias_long": None,
            "bias_short": None,
            "event": event,
            "summary": summary,
            "invalidation": {"price": inv, "side": side},
            "next_watch": watch[:6],
            "process": {
                "route": "heuristic→gate",
                "chase_risk": chase,
                "gate": "PENDING",
                "eff_style": eff_style,
                "st_spillover_prob": spill,
            },
            "cost_usd": 0.0,
            "local_calls": 0,
            "cloud_calls": 0,
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
