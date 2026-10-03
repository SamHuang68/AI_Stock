# -*- coding: utf-8 -*-
"""本機與雲端決策供應者；模型文字僅供文字介面顯示。"""
from __future__ import annotations

import json
import math
import urllib.request
from typing import Any

from .config import load_config, openai_api_key
from .cost_budget import BudgetError, CostBudget, ModelPricing, budget_day
from .decision import HeuristicProvider
from .state import DATA, now_iso

COST_BUDGET_PATH = DATA / "wavedeck_cost_budget.sqlite3"
ACTIONS = {"HOLD", "ENTER_LONG", "ENTER_SHORT", "EXIT", "REDUCE"}
LABELS = {"HOLD": "維持續抱", "ENTER_LONG": "偏多進場", "ENTER_SHORT": "偏空進場", "EXIT": "全部平倉", "REDUCE": "減碼觀察"}


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, budget: dict[str, Any] | None = None,
                 cost_usd: float | None = 0.0, cloud_calls: int = 0):
        super().__init__(message)
        self.budget = budget
        self.cost_usd = cost_usd
        self.cloud_calls = cloud_calls


def _ledger(cfg: dict[str, Any]) -> CostBudget:
    budget = cfg.get("cost_budget", {})
    if not isinstance(budget, dict):
        raise BudgetError("費用上限設定格式錯誤")
    return CostBudget(COST_BUDGET_PATH, budget.get("daily_limit_usd", 5))


def budget_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """提供 UI／engine 單一持久化費用來源；未知帳本不冒充零費用。"""
    try:
        config = load_config() if cfg is None else cfg
        status = _ledger(config).snapshot()
    except Exception:
        return {"day": budget_day(), "timezone": "UTC+08:00", "day_basis": "request_admission",
                "limit_usd": None, "spent_usd": None, "reserved_usd": None,
                "committed_usd": None, "available_usd": None, "blocked": True,
                "pricing_configured": False, "status": "unavailable", "reason": "費用帳本或上限設定無法驗證"}
    try:
        openai = config.get("openai") or {}
        pricing = ModelPricing.from_config(openai, openai.get("model") or "gpt-4o-mini")
        status.update({"pricing_configured": True, "model": pricing.model,
                       "input_bound_tokens": pricing.context_window_tokens, "max_output_tokens": pricing.max_output_tokens})
    except (BudgetError, AttributeError, TypeError):
        status.update({"pricing_configured": False, "blocked": True, "status": "unconfigured",
                       "reason": "付費模型的價目或成本限制尚未確認"})
    return status


def estimate_openai_usd(usage: dict[str, Any] | None, model: str = "gpt-4o-mini") -> float:
    """只接受已配置的精確模型與完整 usage；未知費用以例外表示。"""
    cfg = load_config().get("openai") or {}
    return ModelPricing.from_config(cfg, model).usage_nanos(usage) / 1_000_000_000


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"模型{label}必須是數值")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"模型{label}超出範圍") from exc
    if not math.isfinite(result):
        raise ValueError(f"模型{label}不可為非有限數值")
    return result


def _text(value: Any, maximum: int, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"模型{label}必須是文字")
    # 保留原意但移除控制字元；前端仍必須使用 textContent，不能當 HTML。
    return "".join(ch for ch in value if ch.isprintable() or ch in "\n\t").strip()[:maximum]


def _check_shape(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("模型回傳巢狀層數過多")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("模型回傳包含非有限數值")
    if isinstance(value, dict):
        if len(value) > 64:
            raise ValueError("模型回傳欄位過多")
        for item in value.values():
            _check_shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 64:
            raise ValueError("模型回傳清單過長")
        for item in value:
            _check_shape(item, depth + 1)


def _normalize(raw: dict[str, Any], event: str, provider: str, *, cost_usd: float | None = 0.0,
               local_calls: int = 0, cloud_calls: int = 0) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("模型回傳必須是物件")
    _check_shape(raw)
    action = raw.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("模型 action 不在允許範圍")
    probabilities = {}
    for field in ("confidence", "bias_long", "bias_short"):
        value = _finite(raw.get(field), field)
        if not 0 <= value <= 1:
            raise ValueError(f"模型 {field} 必須介於零與一之間")
        probabilities[field] = round(value, 2)
    inv = raw.get("invalidation")
    if inv is None:
        inv = {}
    if not isinstance(inv, dict):
        raise ValueError("模型失效條件必須是物件或空值")
    inv_price = None if inv.get("price") is None else _finite(inv["price"], "失效價")
    if inv_price is not None and inv_price <= 0:
        raise ValueError("模型失效價必須大於零")
    side = inv.get("side")
    if side is not None and (not isinstance(side, str) or side not in {"above", "below"}):
        raise ValueError("模型失效方向不在允許範圍")
    chase = raw.get("chase_risk", "medium")
    if not isinstance(chase, str) or chase not in {"low", "medium", "high"}:
        raise ValueError("模型追價風險不在允許範圍")
    watch = raw.get("next_watch", [])
    if not isinstance(watch, list) or any(not isinstance(item, str) for item in watch):
        raise ValueError("模型觀察清單必須只含文字")
    return {"action": action, "action_label": LABELS[action], **probabilities,
            "event": _text(event, 80, "事件"), "summary": _text(raw.get("summary", ""), 800, "摘要") or "模型未提供摘要",
            "invalidation": {"price": inv_price, "side": side},
            "next_watch": [_text(item, 80, "觀察項目") for item in watch[:6]],
            "process": {"route": f"{provider}→gate", "chase_risk": chase, "gate": "PENDING"},
            "cost_usd": cost_usd, "local_calls": local_calls, "cloud_calls": cloud_calls,
            "updated_at": now_iso(), "provider": provider}


def _extract_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip() or len(text) > 32_768:
        raise ValueError("模型回傳文字為空或超出長度限制")
    def reject_constant(value):
        raise ValueError("模型 JSON 包含非有限數值")
    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("模型 JSON 包含重複欄位")
            obj[key] = value
        return obj
    obj = json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_pairs)
    if not isinstance(obj, dict):
        raise ValueError("模型 JSON 根節點必須是物件")
    _check_shape(obj)
    return obj


def _prompt(ctx: dict[str, Any]) -> str:
    return (
        "你是台指期／微觀執行風控副駕。只輸出一個 JSON 物件，不要 markdown。\n"
        "欄位：action(HOLD|ENTER_LONG|ENTER_SHORT|EXIT|REDUCE), confidence(0-1), "
        "bias_long(0-1), bias_short(0-1), summary(繁中短句), "
        "invalidation:{price,side}, next_watch:[string], chase_risk(low|medium|high)。\n"
        "只依據 context 已提供的資料；不得捏造均線、ADX 或其他技術指標。"
        "沒有可驗證失效條件時，price 與 side 回傳 null。\n"
        "若 context 含 st_spillover_prob：<0.30 宜保守／避免新多；>0.65 可略積極。"
        "st_delever=true 或 st_score<35 時禁止積極加倉。st_hot_stage 可寫進 next_watch。\n"
        f"context={json.dumps(ctx, ensure_ascii=False, allow_nan=False)}"
    )


def _http_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, allow_nan=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(1_048_577)
    if len(body) > 1_048_576:
        raise ValueError("供應者回應超出長度限制")
    result = json.loads(body.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("供應者回應必須是物件")
    return result


class OllamaProvider:
    name = "ollama"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cfg = load_config().get("ollama") or {}
        out = _http_json(str(cfg.get("base") or "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                         {"model": str(cfg.get("model") or "llama3.2"), "prompt": _prompt(ctx), "stream": False, "format": "json"},
                         {"Content-Type": "application/json"}, float(cfg.get("timeout_sec") or 45))
        return _normalize(_extract_json(out.get("response")), str(ctx.get("event") or "TIMED_MARKET_REVIEW"), self.name, local_calls=1)


class OpenAIProvider:
    name = "openai"

    def infer(self, ctx: dict[str, Any]) -> dict[str, Any]:
        config = load_config()
        try:
            cfg = config.get("openai") or {}
            model = cfg.get("model") or "gpt-4o-mini"
            pricing = ModelPricing.from_config(cfg, model)
            ledger = _ledger(config)
            timeout = _finite(cfg.get("timeout_sec", 45), "請求逾時")
            if timeout <= 0 or timeout > 300:
                raise ValueError("請求逾時設定超出範圍")
            payload = {"model": model, "temperature": 0.2,
                       "max_completion_tokens": pricing.max_output_tokens,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": "只回傳有效的 WaveDeck 決策 JSON。"},
                                    {"role": "user", "content": _prompt(ctx)}]}
            key = openai_api_key()
            if not key:
                raise ValueError("缺少付費模型憑證")
            request_id, budget = ledger.reserve(pricing)
        except Exception as exc:
            budget = getattr(exc, "budget", None) or budget_status(config)
            budget = {**budget, "blocked": True}
            raise ProviderError("付費請求未通過設定或費用預留檢查", budget=budget) from exc
        try:
            out = _http_json(str(cfg.get("base") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                             payload, {"Content-Type": "application/json", "Authorization": "Bearer " + key}, timeout)
            try:
                budget = ledger.settle(request_id, pricing, out.get("usage"))
            except BudgetError as exc:
                if exc.budget:
                    budget = exc.budget
                    raise
                budget = ledger.retain_unknown(request_id)
            choices = out.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("供應者回應缺少決策選項")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("供應者回應缺少決策內容")
            result = _normalize(_extract_json(message.get("content")), str(ctx.get("event") or "TIMED_MARKET_REVIEW"),
                                self.name, cost_usd=budget["request_cost_usd"], cloud_calls=1)
            result["budget"] = budget
            return result
        except Exception as exc:
            try:
                budget = ledger.retain_unknown(request_id)
            except Exception:
                budget = {**budget, "blocked": True, "status": "unavailable", "reason": "帳本暫時無法讀取；預留仍保留"}
            raise ProviderError("付費模型請求或回傳驗證失敗；未知費用仍保留預留額度", budget=budget,
                                cost_usd=budget.get("request_cost_usd"), cloud_calls=1) from exc


def resolve_provider(name: str | None = None):
    cfg = load_config()
    want = (name or cfg.get("provider") or "heuristic").lower()
    if want == "ollama":
        return OllamaProvider()
    if want == "openai":
        return OpenAIProvider()
    return HeuristicProvider()


def _llm_gate_acquire() -> None:
    """沿用既有共用推論閘門。"""
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        if str(root / "server") not in sys.path:
            sys.path.insert(0, str(root / "server"))
        import llm_gate as lg
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
        import llm_gate as lg
        lg.release("wd")
    except Exception:
        pass


def infer_with_fallback(ctx: dict[str, Any], name: str | None = None) -> tuple[dict[str, Any], str | None]:
    """模型失敗時維持觀望，保留費用證據；不補造行情或技術指標。"""
    primary = resolve_provider(name)
    need_gate = primary.name in {"ollama", "openai"}
    if need_gate:
        _llm_gate_acquire()
    try:
        return primary.infer(ctx), None
    except Exception as exc:
        if primary.name == "heuristic":
            raise
        reason = str(exc) if isinstance(exc, ProviderError) else "模型請求或回傳驗證失敗"
        fb = _normalize({"action": "HOLD", "confidence": 0.0, "bias_long": 0.0, "bias_short": 0.0,
                         "summary": reason + "；未取得可驗證決策，維持觀望。", "next_watch": [], "chase_risk": "high"},
                        str(ctx.get("event") or "TIMED_MARKET_REVIEW"), "heuristic",
                        cost_usd=getattr(exc, "cost_usd", None if primary.name == "openai" else 0.0),
                        cloud_calls=getattr(exc, "cloud_calls", 0))
        fb["process"]["route"] = f"{primary.name}-fail→heuristic→gate"
        fb["provider_error"] = True
        if isinstance(getattr(exc, "budget", None), dict):
            fb["budget"] = exc.budget
        return fb, reason
    finally:
        if need_gate:
            _llm_gate_release()
