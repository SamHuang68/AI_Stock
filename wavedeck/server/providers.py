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


def _normalize(raw: dict[str, Any], event: str, provider: str) -> dict[str, Any]:
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
        return _normalize(raw, event, self.name)


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
        return _normalize(raw, event, self.name)


def resolve_provider(name: str | None = None):
    cfg = load_config()
    want = (name or cfg.get("provider") or "heuristic").lower()
    if want == "ollama":
        return OllamaProvider()
    if want == "openai":
        return OpenAIProvider()
    return HeuristicProvider()


def infer_with_fallback(ctx: dict[str, Any], name: str | None = None) -> tuple[dict[str, Any], str | None]:
    """Try configured provider; fall back to heuristic on error."""
    primary = resolve_provider(name)
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
