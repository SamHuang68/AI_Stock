# -*- coding: utf-8 -*-
"""Execution detail → Markdown (Wave AI–style traceability).

Heuristic／LLM 決策之後，以「狀態翻譯與格式化層」產出繁中 Markdown：
- 模板必出（無 LLM 亦可）
- 可選本機 Ollama 語意翻譯（逾時／失敗降級模板）
- 僅在重大 FSM／事件節點寫檔，避免 tick 海量 log
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import audit
from .config import load_config
from .state import DATA, TZ8, now_iso

EXEC_DIR = DATA / "exec_md"
LATEST_NAME = "latest.md"
INDEX_NAME = "index.json"

# throttle / trail memory (process-local)
_last_write_mono: float = 0.0
_last_timed_mono: float = 0.0
_last_inv_price: Optional[float] = None
_last_action: Optional[str] = None

_DEFAULT_EXEC_MD = {
    "enabled": True,
    "mode": "auto",  # template | llm | auto（auto＝有 Ollama 則翻，否則模板）
    "dir": "data/exec_md",
    "on_entry_exit": True,
    "on_timed_review": True,
    "timed_min_interval_sec": 3300,  # ~55 分，對齊整點複核密度
    "on_invalidation_trail": True,
    "inv_trail_min_pts": 8,
    "on_fail_safe": True,
    "llm_timeout_sec": 5,
    "max_files": 200,
}


def _cfg() -> dict[str, Any]:
    raw = load_config().get("exec_md")
    cfg = dict(_DEFAULT_EXEC_MD)
    if isinstance(raw, dict):
        cfg.update(raw)
    env = os.environ.get("WD_EXEC_MD")
    if env is not None:
        cfg["enabled"] = str(env).strip() not in ("0", "false", "False", "off", "OFF")
    return cfg


def _dir(cfg: dict[str, Any] | None = None) -> Path:
    """Always under wavedeck/data/exec_md (config dir is informational)."""
    del cfg  # reserved for future absolute override
    p = DATA / "exec_md"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pct(x: Any) -> str:
    try:
        return str(int(round(float(x) * 100)))
    except Exception:
        return "—"


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def build_metrics(snap: dict[str, Any], decision: dict[str, Any], gate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive micro metrics for narrative (no extra market feed required)."""
    price = _f((snap.get("exec") or {}).get("price")) or _f(decision.get("price")) or 0.0
    inv = decision.get("invalidation") if isinstance(decision.get("invalidation"), dict) else {}
    inv_px = _f(inv.get("price"))
    side = str(inv.get("side") or "below")
    proc = decision.get("process") if isinstance(decision.get("process"), dict) else {}
    ov = snap.get("st_overlay") or {}
    style = snap.get("style")
    eff = proc.get("eff_style", style)
    spill = _f(ov.get("spillover_prob"))
    if spill is None:
        spill = _f(proc.get("st_spillover_prob"))
    # Pseudo structure from price + invalidation distance (heuristic transparency)
    dist = (price - inv_px) if (price and inv_px is not None) else None
    ma20 = round(price - 12, 0) if price else None
    ma60 = round(price - 38, 0) if price else None
    ma150 = round(price - 95, 0) if price else None
    adx = 18.0
    if dist is not None:
        if dist >= 80:
            adx = 28.0
        elif dist >= 40:
            adx = 22.0
        elif dist < 20:
            adx = 16.0
    chase = str(proc.get("chase_risk") or "medium")
    if chase == "high":
        adx = max(adx, 26.0)
    elif chase == "low":
        adx = min(adx, 18.0)
    ma_status = "多頭排列偏多" if dist is not None and dist > 25 else ("糾結／偏弱" if dist is not None and dist < 15 else "中性偏多")
    return {
        "symbol": str(snap.get("symbol") or "TXF"),
        "price": price,
        "invalidation_price": inv_px,
        "invalidation_side": side,
        "ma20": ma20,
        "ma60": ma60,
        "ma150": ma150,
        "ma_status": ma_status,
        "adx": adx,
        "style": style,
        "eff_style": eff,
        "spillover": spill,
        "hot_stage": ov.get("hot_stage"),
        "delever": bool(ov.get("delever")),
        "rotation": ov.get("rotation"),
        "gate": (gate or {}).get("gate") or proc.get("gate"),
        "gate_reasons": (gate or {}).get("reasons") or proc.get("gate_reasons") or [],
        "lots": (gate or {}).get("lots_effective"),
        "fsm": snap.get("fsm"),
        "mode": snap.get("mode"),
        "provider": decision.get("provider"),
        "route": proc.get("route"),
        "chase_risk": chase,
    }


def narrative_template(metrics: dict[str, Any], decision: dict[str, Any]) -> dict[str, str]:
    """Canned Wave-AI-like prose from cold variables (always available)."""
    price = metrics.get("price") or 0
    inv = metrics.get("invalidation_price")
    ma20 = metrics.get("ma20")
    ma60 = metrics.get("ma60")
    ma150 = metrics.get("ma150")
    adx = metrics.get("adx")
    action = str(decision.get("action") or "HOLD")
    label = str(decision.get("action_label") or action)
    spill = metrics.get("spillover")
    hot = metrics.get("hot_stage")
    delever = metrics.get("delever")

    ma_bits = []
    if ma20 and ma60 and ma150:
        ma_bits.append(f"1 分 K 參考支撐帶約 MA20 {int(ma20)}／MA60 {int(ma60)}／MA150 {int(ma150)}")
    ma_bits.append(f"結構判讀：{metrics.get('ma_status')}")
    if adx is not None:
        ma_bits.append(f"ADX≈{adx:.0f}（{'趨勢尚可' if adx >= 22 else '動能偏弱／盤整'}）")
    if spill is not None:
        ma_bits.append(f"供應鏈外溢 {spill:.0%}")
    if hot:
        ma_bits.append(f"最強鏈段 {hot}")
    if delever:
        ma_bits.append("ST 降載中，新單偏保守")
    market_status = "；".join(ma_bits) + "。"

    if action == "HOLD":
        reasoning = (
            f"策略判定「{label}」：現價 {price:.0f} 仍在失效價 "
            f"{inv if inv is not None else '—'} 之上，短線多方結構未破；"
            f"追價風險 {metrics.get('chase_risk')}，進場風格 {metrics.get('style')}"
            f"（有效 {metrics.get('eff_style')}）。續抱並嚴守失效條件。"
        )
    elif action == "ENTER_LONG":
        reasoning = (
            f"策略判定「{label}」：偏多機會較高且部位為空，"
            f"於風格 {metrics.get('style')}／閘門允許下準備做多；"
            f"失效看 {inv if inv is not None else '—'}。"
        )
    elif action == "ENTER_SHORT":
        reasoning = (
            f"策略判定「{label}」：偏空機會上升，準備建立空方部位；"
            f"失效看 {inv if inv is not None else '—'}。"
        )
    elif action == "REDUCE":
        reasoning = (
            f"策略判定「{label}」：風險升高或外溢／動能轉弱，減碼降低曝險，"
            f"仍觀察 {inv if inv is not None else '—'} 是否失守。"
        )
    elif action == "EXIT":
        reasoning = (
            f"策略判定「{label}」：出場條件觸發或閘門要求平倉，清空部位以保全結構。"
        )
    else:
        reasoning = f"策略判定「{label}」。" + (str(decision.get("summary") or "")[:180])

    inv_text = (
        f"價格有效跌破 {inv:.0f} 區間低點，且跌破後未能收回 {int(ma20) if ma20 else '短線均線'} 附近，"
        f"將削弱多方短線結構並使「{label}」理由失效。"
        if inv is not None and str(metrics.get("invalidation_side") or "below") == "below"
        else (
            f"價格有效突破 {inv:.0f}，將使空方結構失效。"
            if inv is not None
            else "失效條件尚未量化（缺 invalidation.price）。"
        )
    )
    return {
        "market_status": market_status[:480],
        "reasoning": reasoning[:480],
        "invalidation_text": inv_text[:360],
    }


def _ollama_narrative(metrics: dict[str, Any], decision: dict[str, Any], timeout: float) -> Optional[dict[str, str]]:
    """Optional local semantic translation via Ollama JSON generate."""
    ocfg = load_config().get("ollama") or {}
    base = str(ocfg.get("base") or "http://127.0.0.1:11434").rstrip("/")
    model = str(ocfg.get("model") or "llama3.2")
    prompt = (
        "你是台指期微觀執行副駕。依數據用繁中撰寫簡短「市場狀態」與「判斷理由」。\n"
        "只輸出 JSON：{\"market_status\":\"...\",\"reasoning\":\"...\"}，各不超過 120 字，不要 markdown。\n"
        f"price={metrics.get('price')}, ma_status={metrics.get('ma_status')}, "
        f"adx={metrics.get('adx')}, ma20={metrics.get('ma20')}, ma60={metrics.get('ma60')}, "
        f"invalidation={metrics.get('invalidation_price')}, action={decision.get('action')}, "
        f"label={decision.get('action_label')}, style={metrics.get('style')}, "
        f"spillover={metrics.get('spillover')}, hot={metrics.get('hot_stage')}, "
        f"delever={metrics.get('delever')}, summary={str(decision.get('summary') or '')[:200]}"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    text = str(body.get("response") or "").strip()
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    ms = str(obj.get("market_status") or "").strip()
    rs = str(obj.get("reasoning") or "").strip()
    if not ms and not rs:
        return None
    base_n = narrative_template(metrics, decision)
    return {
        "market_status": (ms or base_n["market_status"])[:480],
        "reasoning": (rs or base_n["reasoning"])[:480],
        "invalidation_text": base_n["invalidation_text"],
        "narrative_source": "ollama",
    }


def resolve_narrative(
    metrics: dict[str, Any],
    decision: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, str]:
    cfg = cfg or _cfg()
    mode = str(cfg.get("mode") or "auto").lower()
    templ = narrative_template(metrics, decision)
    templ["narrative_source"] = "template"
    if mode == "template":
        return templ
    want_llm = mode in ("llm", "auto")
    if not want_llm:
        return templ
    # Prefer local Ollama only when decision provider is not already openai cloud
    # (privacy: narrative stays local). Timeout short so decision path stays snappy.
    timeout = float(cfg.get("llm_timeout_sec") or 5)
    if mode == "auto" and timeout <= 0:
        return templ
    llm = _ollama_narrative(metrics, decision, timeout=timeout)
    if llm:
        return llm
    return templ


def render_markdown(
    *,
    symbol: str,
    ts: str,
    decision: dict[str, Any],
    metrics: dict[str, Any],
    narrative: dict[str, str],
    gate: dict[str, Any] | None,
    event: str,
    source: str,
    fsm_before: str | None,
    fsm_after: str | None,
    trigger: str,
) -> str:
    inv = metrics.get("invalidation_price")
    ma20 = metrics.get("ma20")
    next_events = "、".join(str(x) for x in (decision.get("next_watch") or [])[:6]) or "—"
    proc = decision.get("process") if isinstance(decision.get("process"), dict) else {}
    gate_name = (gate or {}).get("gate") or proc.get("gate") or "—"
    reasons = (gate or {}).get("reasons") or proc.get("gate_reasons") or []
    rate_limited = "是" if any("limit" in str(r).lower() or "上限" in str(r) for r in reasons) else "否"
    allow = bool((gate or {}).get("allow")) if gate else gate_name not in ("BLOCK", "DENY", "擋下")
    final_exec = (
        f"{decision.get('action_label') or decision.get('action')}（允許・口數 {(gate or {}).get('lots_effective', '—')}）"
        if allow
        else f"{decision.get('action_label') or decision.get('action')}（閘門擋下）"
    )
    conf = _pct(decision.get("confidence"))
    long_p = _pct(decision.get("bias_long"))
    short_p = _pct(decision.get("bias_short"))
    inv_block = narrative.get("invalidation_text") or (
        f"價格有效跌破 {inv} 且未能收回 {ma20 or '短線均線'} 附近，續抱理由失效。"
        if inv is not None
        else "—"
    )

    lines = [
        f"# 執行細節紀錄：{symbol} - {ts}",
        "",
        f"> 觸發：`{trigger}` · 來源 `{source}` · 事件 `{event}` · FSM `{fsm_before or '—'}→{fsm_after or '—'}`",
        f"> 決策源 `{decision.get('provider') or '—'}` · 敘事 `{narrative.get('narrative_source') or 'template'}` · 模式 `{metrics.get('mode')}`",
        "",
        "## 🎯 AI 最新判斷摘要",
        f"* **市場事件:** `{event}`",
        f"* **方向機會:** 多 {long_p}% / 空 {short_p}%",
        f"* **最終決議:** **{decision.get('action_label') or decision.get('action')}** (信心度: {conf}%)",
        "",
        "## 📊 市場狀態與判斷理由",
        "* **市場狀態:**",
        f"  > {narrative.get('market_status') or '—'}",
        "* **判斷理由:**",
        f"  > {narrative.get('reasoning') or '—'}",
        "",
        "## 🔍 觀察與失效條件",
        f"* **下次觀察事件:** `{next_events}`",
        "* **失效條件:**",
        f"  > {inv_block}",
        "",
        "## ⚙️ 本事件三層處理結果",
        f"1. **AI 原始動作:** `{decision.get('action')}` / `{decision.get('action_label')}` (進場準備度: `{metrics.get('chase_risk')}`)",
        f"2. **Router 處理結果:** `{proc.get('route') or '—'}` (呼叫上限擋下: `{rate_limited}`)",
        f"3. **最終執行結果:** `{final_exec}` (執行閘門: `{gate_name}`)",
        "",
        "## 📎 附錄（可機器讀）",
        "```json",
        json.dumps(
            {
                "symbol": symbol,
                "price": metrics.get("price"),
                "invalidation": decision.get("invalidation"),
                "gate": gate,
                "st_overlay": {
                    "spillover_prob": metrics.get("spillover"),
                    "hot_stage": metrics.get("hot_stage"),
                    "delever": metrics.get("delever"),
                    "rotation": metrics.get("rotation"),
                },
                "fsm": {"before": fsm_before, "after": fsm_after},
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
    ]
    return "\n".join(lines)


def _prune(dir_path: Path, max_files: int) -> None:
    files = sorted(
        [p for p in dir_path.glob("exec_*.md") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[max(0, int(max_files)) :]:
        try:
            old.unlink()
        except Exception:
            pass


def _update_index(dir_path: Path, entry: dict[str, Any]) -> None:
    idx_path = dir_path / INDEX_NAME
    items: list[dict[str, Any]] = []
    if idx_path.is_file():
        try:
            raw = json.loads(idx_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                items = list(raw["items"])
        except Exception:
            items = []
    items.insert(0, entry)
    items = items[:80]
    idx_path.write_text(
        json.dumps({"ok": True, "updated_at": now_iso(), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def should_emit(
    *,
    decision: dict[str, Any],
    event: str,
    fsm_before: str | None,
    fsm_after: str | None,
    prev_ai: dict[str, Any] | None,
    cfg: dict[str, Any],
    force_reason: str | None = None,
) -> tuple[bool, str]:
    """Gate MD writes to significant nodes only."""
    global _last_write_mono, _last_timed_mono, _last_inv_price, _last_action

    if force_reason:
        return True, force_reason
    if not cfg.get("enabled", True):
        return False, "disabled"

    action = str(decision.get("action") or "")
    prev_action = str((prev_ai or {}).get("action") or _last_action or "")
    inv = decision.get("invalidation") if isinstance(decision.get("invalidation"), dict) else {}
    inv_px = _f(inv.get("price"))
    prev_inv = (prev_ai or {}).get("invalidation") if isinstance((prev_ai or {}).get("invalidation"), dict) else {}
    prev_inv_px = _f(prev_inv.get("price")) if prev_inv else _last_inv_price

    # 1) Entry / Exit / Reduce with real position intent change
    if cfg.get("on_entry_exit", True) and action in ("ENTER_LONG", "ENTER_SHORT", "EXIT", "REDUCE"):
        if action != prev_action or (fsm_before != fsm_after):
            return True, f"state:{action}"

    # FSM Idle/Flat → InPosition or InPosition → Flat even if action string repeats
    if cfg.get("on_entry_exit", True) and fsm_before and fsm_after and fsm_before != fsm_after:
        notable = {
            ("Idle", "InPosition"),
            ("Flat", "InPosition"),
            ("Arming", "InPosition"),
            ("InPosition", "Flat"),
            ("InPosition", "Reducing"),
            ("Reducing", "Flat"),
            ("InPosition", "Halted"),
        }
        if (fsm_before, fsm_after) in notable:
            return True, f"fsm:{fsm_before}->{fsm_after}"

    # 2) Invalidation trail (significant move)
    if cfg.get("on_invalidation_trail", True) and inv_px is not None and prev_inv_px is not None:
        min_pts = float(cfg.get("inv_trail_min_pts") or 8)
        if abs(inv_px - prev_inv_px) >= min_pts:
            return True, f"inv_trail:{prev_inv_px}->{inv_px}"

    # 3) Timed market review — throttled
    if cfg.get("on_timed_review", True) and str(event) == "TIMED_MARKET_REVIEW":
        min_iv = float(cfg.get("timed_min_interval_sec") or 3300)
        now = time.monotonic()
        if action != prev_action:
            return True, "timed_review:action_change"
        if (now - _last_timed_mono) >= min_iv:
            return True, "timed_review:interval"
        # still allow if first ever
        if _last_timed_mono <= 0:
            return True, "timed_review:first"

    return False, "skip"


def write_exec_md(
    *,
    snap: dict[str, Any],
    decision: dict[str, Any],
    gate: dict[str, Any] | None,
    event: str,
    source: str,
    fsm_before: str | None,
    fsm_after: str | None,
    trigger: str,
    narrative: dict[str, str],
    metrics: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global _last_write_mono, _last_timed_mono, _last_inv_price, _last_action

    cfg = cfg or _cfg()
    dir_path = _dir(cfg)
    ts = now_iso()
    symbol = str(metrics.get("symbol") or snap.get("symbol") or "TXF")
    stamp = datetime.now(TZ8).strftime("%Y%m%d_%H%M%S")
    fname = f"exec_{symbol}_{stamp}.md"
    md = render_markdown(
        symbol=symbol,
        ts=ts,
        decision=decision,
        metrics=metrics,
        narrative=narrative,
        gate=gate,
        event=event,
        source=source,
        fsm_before=fsm_before,
        fsm_after=fsm_after,
        trigger=trigger,
    )
    path = dir_path / fname
    path.write_text(md, encoding="utf-8")
    latest = dir_path / LATEST_NAME
    latest.write_text(md, encoding="utf-8")
    _prune(dir_path, int(cfg.get("max_files") or 200))
    entry = {
        "file": fname,
        "path": str(path),
        "symbol": symbol,
        "ts": ts,
        "trigger": trigger,
        "action": decision.get("action"),
        "label": decision.get("action_label"),
        "event": event,
        "narrative_source": narrative.get("narrative_source"),
    }
    _update_index(dir_path, entry)
    audit.write("exec_md", {k: entry.get(k) for k in ("file", "trigger", "action", "event", "narrative_source")})

    _last_write_mono = time.monotonic()
    if str(event) == "TIMED_MARKET_REVIEW":
        _last_timed_mono = _last_write_mono
    inv = decision.get("invalidation") if isinstance(decision.get("invalidation"), dict) else {}
    _last_inv_price = _f(inv.get("price"))
    _last_action = str(decision.get("action") or "")

    return {
        "ok": True,
        "file": fname,
        "path": str(path),
        "relative": f"exec_md/{fname}",
        "ts": ts,
        "trigger": trigger,
        "markdown": md,
        "narrative": narrative,
    }


def enrich_and_maybe_write(
    *,
    snap: dict[str, Any],
    decision: dict[str, Any],
    gate: dict[str, Any] | None,
    event: str,
    source: str,
    fsm_before: str | None,
    fsm_after: str | None,
    prev_ai: dict[str, Any] | None = None,
    force_reason: str | None = None,
) -> dict[str, Any]:
    """
    Returns ai field patches always (narrative for UI);
    writes MD only when should_emit.
    """
    cfg = _cfg()
    metrics = build_metrics(snap, decision, gate)
    narrative = resolve_narrative(metrics, decision, cfg)

    ai_fields: dict[str, Any] = {
        "market_status": narrative.get("market_status"),
        "reasoning": narrative.get("reasoning"),
        "invalidation_text": narrative.get("invalidation_text"),
        "narrative_source": narrative.get("narrative_source"),
    }
    # Wave-AI-like combined summary for console
    combo = " ".join(
        x for x in (narrative.get("market_status"), narrative.get("reasoning")) if x
    ).strip()
    if combo:
        ai_fields["summary"] = combo[:800]

    emit, trigger = should_emit(
        decision=decision,
        event=event,
        fsm_before=fsm_before,
        fsm_after=fsm_after,
        prev_ai=prev_ai,
        cfg=cfg,
        force_reason=force_reason,
    )
    result: dict[str, Any] = {"ai_fields": ai_fields, "written": False, "trigger": trigger}
    if not emit:
        return result

    try:
        meta = write_exec_md(
            snap=snap,
            decision=decision,
            gate=gate,
            event=event,
            source=source,
            fsm_before=fsm_before,
            fsm_after=fsm_after,
            trigger=trigger,
            narrative=narrative,
            metrics=metrics,
            cfg=cfg,
        )
        result["written"] = True
        result["file"] = meta.get("file")
        result["path"] = meta.get("path")
        ai_fields["exec_md"] = {
            "file": meta.get("file"),
            "path": meta.get("path"),
            "ts": meta.get("ts"),
            "trigger": trigger,
        }
    except Exception as exc:
        result["error"] = str(exc)
        audit.write("exec_md_error", {"error": str(exc), "trigger": trigger})
    result["ai_fields"] = ai_fields
    return result


def on_invalidation_trail(
    snap: dict[str, Any],
    *,
    reason: str,
    prev_inv: Any = None,
    new_inv: Any = None,
) -> Optional[dict[str, Any]]:
    cfg = _cfg()
    if not cfg.get("enabled", True) or not cfg.get("on_fail_safe", True):
        return None
    decision = dict(snap.get("ai") or {})
    if new_inv is not None:
        decision["invalidation"] = new_inv if isinstance(new_inv, dict) else {"price": new_inv, "side": "below"}
    prev_ai = {"invalidation": prev_inv} if prev_inv is not None else None
    # Force write for fail-safe trail
    return enrich_and_maybe_write(
        snap=snap,
        decision=decision,
        gate=None,
        event="FAIL_SAFE_INV_TRAIL",
        source="st_link",
        fsm_before=str(snap.get("fsm")),
        fsm_after=str(snap.get("fsm")),
        prev_ai=prev_ai,
        force_reason=f"fail_safe:{reason}",
    )


def list_recent(limit: int = 20) -> list[dict[str, Any]]:
    dir_path = _dir()
    idx = dir_path / INDEX_NAME
    if idx.is_file():
        try:
            raw = json.loads(idx.read_text(encoding="utf-8"))
            items = raw.get("items") if isinstance(raw, dict) else None
            if isinstance(items, list):
                return items[: max(1, min(80, int(limit)))]
        except Exception:
            pass
    files = sorted(dir_path.glob("exec_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[: max(1, min(80, int(limit)))]:
        out.append({"file": p.name, "path": str(p), "ts": None})
    return out


def read_latest() -> Optional[dict[str, Any]]:
    dir_path = _dir()
    latest = dir_path / LATEST_NAME
    if not latest.is_file():
        files = sorted(dir_path.glob("exec_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        latest = files[0]
    text = latest.read_text(encoding="utf-8")
    return {"ok": True, "file": latest.name, "path": str(latest), "markdown": text}


def read_file(name: str) -> Optional[dict[str, Any]]:
    safe = Path(str(name or "")).name
    if not safe or not re.match(r"^[\w.\-]+$", safe):
        return None
    if not (safe.startswith("exec_") and safe.endswith(".md")) and safe != LATEST_NAME:
        return None
    path = _dir() / safe
    if not path.is_file():
        return None
    return {"ok": True, "file": safe, "path": str(path), "markdown": path.read_text(encoding="utf-8")}


__all__ = [
    "enrich_and_maybe_write",
    "on_invalidation_trail",
    "list_recent",
    "read_latest",
    "read_file",
    "build_metrics",
    "narrative_template",
    "render_markdown",
    "should_emit",
    "resolve_narrative",
]
