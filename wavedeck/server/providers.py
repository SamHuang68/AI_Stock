# -*- coding: utf-8 -*-
"""LLM decision providers via stdlib urllib (Ollama / OpenAI)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .config import load_config, openai_api_key
from .decision import HeuristicProvider
from .state import now_iso

ACTIONS = {"HOLD", "ENTER_LONG", "ENTER_SHORT", "EXIT", "REDUCE"}
LABELS = {
    "HOLD": "維持續抱",
    "ENTER_LONG": "偏多進場",
    "ENTER_SHORT": "偏空進場",
    "EXIT": "全部平倉",
    "REDUCE": "減碼觀察",
}


def _clamp01(x: Any, default: float = 0.5) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    return max(0.0, min(1.0, v))


def estimate_openai_usd(usage: dict[str, Any] | None, model: str = "gpt-4o-mini") -> float:
    """Rough USD estimate from OpenAI-style usage (gpt-4o-mini defaults)."""
    usage = usage or {}
    try:
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    except Exception:
        return 0.0
    # Default rates USD / 1M tokens (gpt-4o-mini ballpark)
    in_rate, out_rate = 0.15, 0.60
    m = (model or "").lower()
    if "gpt-4o" in m and "mini" not in m:
        in_rate, out_rate = 2.50, 10.00
    elif "gpt-3.5" in m:
        in_rate, out_rate = 0.50, 1.50
    usd = (prompt * in_rate + completion * out_rate) / 1_000_000.0
    return round(max(0.0, usd), 6)


def _normalize(
    raw: dict[str, Any],
    event: str,
    provider: str,
    *,
    cost_usd: float = 0.0,
    local_calls: int = 0,
    cloud_calls: int = 0,
) -> dict[str, Any]:
    action = str(raw.get("action") or "HOLD").upper()
    if action not in ACTIONS:
        action = "HOLD"
    conf = _clamp01(raw.get("confidence"), 0.55)
    bl = _clamp01(raw.get("bias_long"), conf if action in {"HOLD", "ENTER_LONG"} else 1 - conf)
    bs = _clamp01(raw.get("bias_short"), max(0.0, 1.0 - bl))
    inv = raw.get("invalidation") if isinstance(raw.get("invalidation"), dict) else {}
    try:
        inv_price = float(inv.get("price"))
    except Exception:
        inv_price = None
    watch = raw.get("next_watch")
    if not isinstance(watch, list):
        watch = ["結構再確認", "收盤前不留倉時窗"]
    summary = str(raw.get("summary") or "").strip() or "（模型未提供摘要）"
    return {
        "action": action,
        "action_label": LABELS.get(action, action),
        "confidence": round(conf, 2),
        "bias_long": round(bl, 2),
        "bias_short": round(bs, 2),
        "event": event,
        "summary": summary[:800],
        "invalidation": {
            "price": inv_price if inv_price is not None else 0,
            "side": str(inv.get("side") or "below"),
        },
        "next_watch": [str(x)[:80] for x in watch[:6]],
        "process": {
            "route": f"{provider}→gate",
            "chase_risk": str(raw.get("chase_risk") or "medium"),
            "gate": "PENDING",
        },
        "cost_usd": round(float(cost_usd or 0), 6),
        "local_calls": int(local_calls or 0),
        "cloud_calls": int(cloud_calls or 0),
        "updated_at": now_iso(),
        "provider": provider,
    }


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model output")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no json object in model output")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("json root not object")
    return obj


def _prompt(ctx: dict[str, Any]) -> str:
    return (
        "你是台指期／微觀執行風控副駕。只輸出一個 JSON 物件，不要 markdown。\n"
        "欄位：action(HOLD|ENTER_LONG|ENTER_SHORT|EXIT|REDUCE), confidence(0-1), "
        "bias_long(0-1), bias_short(0-1), summary(繁中短句), "
        "invalidation:{price,side}, next_watch:[string], chase_risk(low|medium|high).\n"
        "若 context 含 st_spillover_prob：<0.30 宜保守／避免新多；>0.65 可略積極。"
        "st_delever=true 或 st_score<35 時禁止積極加倉。st_hot_stage 可寫進 next_watch。\n"
        f"context={json.dumps(ctx, ensure_ascii=False)}"
    )


def _http_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


class OllamaProvider:
    name = "ollama"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cfg = load_config().get("ollama") or {}
        base = str(cfg.get("base") or "http://127.0.0.1:11434").rstrip("/")
        model = str(cfg.get("model") or "llama3.2")
        timeout = float(cfg.get("timeout_sec") or 45)
        event = str(ctx.get("event") or "TIMED_MARKET_REVIEW")
        out = _http_json(
            base + "/api/generate",
            {
                "model": model,
                "prompt": _prompt(ctx),
                "stream": False,
                "format": "json",
            },
            {"Content-Type": "application/json"},
            timeout,
        )
        raw = _extract_json(str(out.get("response") or ""))
        # Local inference: $0, count calls for shared meter
        return _normalize(raw, event, self.name, cost_usd=0.0, local_calls=1)


class OpenAIProvider:
    name = "openai"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        key = openai_api_key()
        if not key:
            raise RuntimeError("缺少 OPENAI_API_KEY（環境變數或 data/wavedeck_secrets.json）")
        cfg = load_config().get("openai") or {}
        base = str(cfg.get("base") or "https://api.openai.com/v1").rstrip("/")
        model = str(cfg.get("model") or "gpt-4o-mini")
        timeout = float(cfg.get("timeout_sec") or 45)
        event = str(ctx.get("event") or "TIMED_MARKET_REVIEW")
        out = _http_json(
            base + "/chat/completions",
            {
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Return only valid JSON for WaveDeck decision."},
                    {"role": "user", "content": _prompt(ctx)},
                ],
            },
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
            timeout,
        )
        content = (((out.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        raw = _extract_json(str(content))
        usd = estimate_openai_usd(out.get("usage") if isinstance(out.get("usage"), dict) else {}, model)
        return _normalize(raw, event, self.name, cost_usd=usd, cloud_calls=1)


def resolve_provider(name: str | None = None):
    cfg = load_config()
    want = (name or cfg.get("provider") or "heuristic").lower()
    if want == "ollama":
        return OllamaProvider()
    if want == "openai":
        return OpenAIProvider()
    return HeuristicProvider()


def _llm_gate_acquire() -> None:
    """WD = P1 on shared GPU / LM instance."""
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / "server")) if str(root / "server") not in sys.path else None
        import llm_gate as lg  # type: ignore

        lg.acquire("wd", ttl_sec=90)
    except Exception:
        pass


def _llm_gate_release() -> None:
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        if str(root / "server") not in sys.path:
            sys.path.insert(0, str(root / "server"))
        import llm_gate as lg  # type: ignore

        lg.release("wd")
    except Exception:
        pass


def infer_with_fallback(ctx: dict[str, Any], name: str | None = None) -> tuple[dict[str, Any], str | None]:
    """Try configured provider; fall back to heuristic on error."""
    primary = resolve_provider(name)
    need_gate = primary.name in {"ollama", "openai"}
    if need_gate:
        _llm_gate_acquire()
    try:
        return primary.infer(ctx), None
    except Exception as exc:
        if primary.name == "heuristic":
            raise
        fb = HeuristicProvider().infer(ctx)
        fb["process"]["route"] = f"{primary.name}-fail→heuristic→gate"
        fb["summary"] = f"〔{primary.name} 失敗：{exc}〕改用啟發式。 " + fb["summary"]
        fb["provider"] = "heuristic"
        return fb, str(exc)
    finally:
        if need_gate:
            _llm_gate_release()
