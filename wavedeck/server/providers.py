# -*- coding: utf-8 -*-
"""LLM decision providers via stdlib urllib (Ollama / OpenAI)."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .config import load_config, openai_api_key
from .cost_budget import BudgetError, CostBudget, ModelPricing, budget_day
from .decision import HeuristicProvider
from .state import DATA, now_iso

# 付費請求的每日費用帳本；所有程序必須共用同一個檔案，准入才有意義。
COST_BUDGET_PATH = DATA / "wavedeck_cost_budget.sqlite3"
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


class ProviderError(RuntimeError):
    """付費請求失敗；帶著帳本狀態與已知費用，讓退回規則引擎時不會把這筆費用當成零。"""

    def __init__(self, message: str, *, budget: dict[str, Any] | None = None,
                 cost_usd: float | None = 0.0, cloud_calls: int = 0):
        super().__init__(message)
        self.budget = budget
        self.cost_usd = cost_usd
        self.cloud_calls = cloud_calls


_LOGGED: dict[tuple[str, str], float] = {}
_LOG_LOCK = threading.Lock()
LOG_INTERVAL_SEC = 600.0


def _log_ledger_error(where: str, exc: BaseException, *, now: float | None = None) -> bool:
    """帳本讀寫失敗時留下一行限頻記錄（同一處＋同一例外型別 10 分鐘內只記一行）。

    畫面與決策只會看到「帳本無法驗證」，不會有原因；沒有這一行，損毀、鎖定、唯讀的帳本就無從診斷。
    WaveDeck 與 Stock Terminal 的 `server` 是兩個不同的套件，不能共用 server/log_once.py，所以這裡自帶最小版。"""
    kind = type(exc).__name__
    stamp = time.monotonic() if now is None else now
    with _LOG_LOCK:
        last = _LOGGED.get((where, kind))
        if last is not None and stamp - last < LOG_INTERVAL_SEC:
            return False
        _LOGGED[(where, kind)] = stamp
    print(f"[wavedeck] 費用帳本錯誤（{where}）：{kind}: {str(exc)[:200]}", file=sys.stderr, flush=True)
    return True


def _ledger(cfg: dict[str, Any]) -> CostBudget:
    budget = cfg.get("cost_budget", {})
    if not isinstance(budget, dict):
        raise BudgetError("費用上限設定格式錯誤")
    return CostBudget(COST_BUDGET_PATH, budget.get("daily_limit_usd", 5))


def budget_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """單一持久化費用來源；帳本或設定無法驗證時回報「未知且阻擋」，不冒充零費用。"""
    try:
        config = load_config() if cfg is None else cfg
        status = _ledger(config).snapshot()
    except Exception as exc:
        _log_ledger_error("狀態查詢", exc)
        return {"day": budget_day(), "timezone": "UTC+08:00", "day_basis": "request_admission",
                "limit_usd": None, "spent_usd": None, "reserved_usd": None,
                "committed_usd": None, "available_usd": None, "blocked": True,
                "pricing_configured": False, "status": "unavailable", "reason": "費用帳本或上限設定無法驗證"}
    try:
        openai = config.get("openai") or {}
        pricing = ModelPricing.from_config(openai, openai.get("model") or "gpt-4o-mini")
        status.update({"pricing_configured": True, "model": pricing.model,
                       "input_bound_tokens": pricing.context_window_tokens,
                       "max_output_tokens": pricing.max_output_tokens})
    except (BudgetError, AttributeError, TypeError):
        status.update({"pricing_configured": False, "blocked": True, "status": "unconfigured",
                       "reason": "付費模型的價目或成本限制尚未確認"})
    return status


def recorded_budget_status(cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """帳本檔存在（曾經有過付費請求）才回報狀態；從未付費過的部署回 None，也不會憑空建立帳本檔。"""
    return budget_status(cfg) if COST_BUDGET_PATH.exists() else None


def estimate_openai_usd(usage: dict[str, Any] | None, model: str = "gpt-4o-mini") -> float:
    """依設定檔中該模型的精確價目計費；沒有配置價目、或 usage 不完整時拋出 BudgetError，不猜。"""
    cfg = load_config().get("openai") or {}
    return ModelPricing.from_config(cfg, model).usage_nanos(usage) / 1_000_000_000


def _normalize(
    raw: dict[str, Any],
    event: str,
    provider: str,
    *,
    cost_usd: float | None = 0.0,
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
        # None = 費用未知（逾時、缺 usage）；不能寫成 0，否則等於宣稱這筆免費。
        "cost_usd": None if cost_usd is None else round(float(cost_usd), 6),
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
        config = load_config()
        event = str(ctx.get("event") or "TIMED_MARKET_REVIEW")
        # 第一段：送出前的全部檢查與費用預留。任何一項失敗都不會產生網路請求，也不會讀取憑證以外的東西；
        # 價目沒配置時連憑證都不讀。
        try:
            cfg = config.get("openai") or {}
            model = str(cfg.get("model") or "gpt-4o-mini")
            pricing = ModelPricing.from_config(cfg, model)
            ledger = _ledger(config)
            timeout = float(cfg.get("timeout_sec") or 45)
            payload = {
                "model": model,
                "temperature": 0.2,
                # 預留金額以這個輸出上限計算（含推理 token）；沒有它，預留就不是上限。
                "max_completion_tokens": pricing.max_output_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Return only valid JSON for WaveDeck decision."},
                    {"role": "user", "content": _prompt(ctx)},
                ],
            }
            key = openai_api_key()
            if not key:
                raise RuntimeError("缺少 OPENAI_API_KEY（環境變數或 data/wavedeck_secrets.json）")
            request_id, budget = ledger.reserve(pricing)
        except Exception as exc:
            budget = getattr(exc, "budget", None) or budget_status(config)
            raise ProviderError(f"付費請求未通過設定或費用預留檢查：{str(exc)[:200]}",
                                budget={**budget, "blocked": True}) from exc
        # 第二段：已預留。之後無論怎麼失敗，預留都不退；只有拿到完整 usage 才以實際費用結算。
        try:
            out = _http_json(
                str(cfg.get("base") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                payload,
                {"Content-Type": "application/json", "Authorization": "Bearer " + key},
                timeout,
            )
            try:
                budget = ledger.settle(request_id, pricing, out.get("usage"))
            except BudgetError as exc:
                if exc.budget:  # 供應者回報超出已配置的成本限制：帳本已標記，不能當成一般失敗吞掉
                    budget = exc.budget
                    raise
                budget = ledger.retain_unknown(request_id)
            content = (((out.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
            result = _normalize(_extract_json(str(content)), event, self.name,
                                cost_usd=budget["request_cost_usd"], cloud_calls=1)
            result["budget"] = budget
            return result
        except Exception as exc:
            try:
                budget = ledger.retain_unknown(request_id)  # 已結算的請求不受影響，仍回報其實際費用
            except Exception as ledger_exc:
                _log_ledger_error("保留預留", ledger_exc)
                budget = {**budget, "blocked": True, "status": "unavailable",
                          "reason": "帳本暫時無法讀取；預留仍保留"}
            raise ProviderError(f"付費模型請求失敗，未知費用仍保留預留額度：{type(exc).__name__}: {str(exc)[:160]}",
                                budget=budget, cost_usd=budget.get("request_cost_usd"), cloud_calls=1) from exc


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
        if isinstance(exc, ProviderError):
            # 退回規則引擎不會讓這筆付費請求變成免費：已知費用、是否真的送出、帳本狀態都原樣帶回去
            # （費用未知時 cost_usd 是 None，不是 0）。
            fb["cost_usd"] = exc.cost_usd
            fb["cloud_calls"] = exc.cloud_calls
            if isinstance(exc.budget, dict):
                fb["budget"] = exc.budget
        return fb, str(exc)
    finally:
        if need_gate:
            _llm_gate_release()
