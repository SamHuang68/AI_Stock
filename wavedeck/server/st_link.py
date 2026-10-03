# -*- coding: utf-8 -*-
"""ST heartbeat + graceful degradation (fail-safe) for WaveDeck.

Root causes addressed:
1. Fail-safe used to set style=35 once → later style drift to 60 while banner stayed.
   → Sticky enforce every tick + /api/style clamp.
2. Overlay stale when ST browser tab stopped pushing → WD now PULLS macro from ST
   before fail-safe (retry), and ST bridge heartbeat republishes last payload.
3. Fail-safe banner was appended into ai.summary every tick → UI wash/duplication.
   → Reason lives on st_link / st_overlay only; summary is scrubbed clean.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

from . import audit
from .data_contract import assess_quote, finite_number, parse_as_of
from .risk import daily_dd_ratio, MAX_DAILY_DD, WARN_DAILY_DD
from .state import RUNTIME, now_iso
from .st_push import push_async

ST_URL = os.environ.get("ST_URL", "http://127.0.0.1:18432").rstrip("/")
PING_SEC = float(os.environ.get("WD_ST_HEARTBEAT_SEC", "5"))
# Soft age: attempt WD←ST pull before hard fail-safe
OVERLAY_PULL_SEC = float(os.environ.get("WD_ST_OVERLAY_PULL_SEC", "45"))
# Overlay older than this without bridge update → fail-safe
OVERLAY_STALE_SEC = float(os.environ.get("WD_ST_OVERLAY_STALE_SEC", "90"))
# Consecutive ping failures before fail-safe
FAIL_AFTER = int(os.environ.get("WD_ST_FAIL_AFTER", "2"))
FAIL_SAFE_STYLE = int(os.environ.get("WD_FAIL_SAFE_STYLE", "35"))
# When daily DD breaches, also flatten TXT (default: pause new only)
DD_FLATTEN = os.environ.get("WD_DD_FLATTEN", "0").lower() in ("1", "true", "yes")

_FS_BANNER_RE = re.compile(
    r"〔Fail-safe：[^\]]*〕(?:\s*風格→保守、降載、收緊失效。?)*\s*",
    re.UNICODE,
)
_FS_CLAUSE_RE = re.compile(r"(?:風格→保守、降載、收緊失效。?\s*)+", re.UNICODE)

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_fail_count = 0
_lock = threading.Lock()
_last_pull_at = 0.0
_dd_locked = False


def _default_link() -> dict[str, Any]:
    return {
        "status": "unknown",  # ok | warn | down
        "last_ok_at": None,
        "last_ping_at": None,
        "fail_count": 0,
        "overlay_at": None,
        "overlay_as_of": None,
        "overlay_epoch": None,
        "fail_safe": False,
        "fail_safe_reason": "",
        "fail_safe_kind": "",  # stale_overlay | heartbeat
        "last_pull_at": None,
        "pull_ok": None,
        "st_port": ST_URL,
    }


def _kind_of(reason: str) -> str:
    r = str(reason or "")
    if "心跳" in r or "斷線" in r:
        return "heartbeat"
    if "過期" in r or "覆寫" in r:
        return "stale_overlay"
    return "other"


def scrub_fail_safe_summary(text: str | None) -> str:
    """Remove stacked Fail-safe banners from AI summary body."""
    t = str(text or "")
    t = _FS_BANNER_RE.sub("", t)
    t = _FS_CLAUSE_RE.sub("", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def touch_overlay(as_of: Any = None) -> None:
    """保留接收時間；只有新鮮且含時區的來源時間能解除 fail-safe。"""
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    stamp = parse_as_of(as_of)
    link["overlay_at"] = now_iso()
    link["overlay_as_of"] = stamp.isoformat() if stamp is not None else None
    link["overlay_epoch"] = stamp.timestamp() if stamp is not None else None
    age = _overlay_age_sec(link)
    if age is None or age > OVERLAY_STALE_SEC:
        reason = "宏觀覆寫來源時間未知或在未來" if age is None else f"宏觀覆寫過期 {int(age)}s"
        RUNTIME.patch(st_link=link)
        enforce_fail_safe(reason, tighten=False)
        return
    link["status"] = "ok"
    link["fail_safe"] = False
    link["fail_safe_reason"] = ""
    link["fail_safe_kind"] = ""
    ov = dict(RUNTIME.snapshot().get("st_overlay") or {})
    ai = dict(RUNTIME.snapshot().get("ai") or {})
    cleaned = scrub_fail_safe_summary(ai.get("summary"))
    patch: dict[str, Any] = {"st_link": link, "lights": {"st_bridge": "ok"}}
    if ov.get("fail_safe"):
        ov["fail_safe"] = False
        ov["fail_safe_reason"] = None
        patch["st_overlay"] = ov
    dd = daily_dd_ratio(RUNTIME.snapshot())
    risk_lamp = "warn" if dd is None or dd >= WARN_DAILY_DD else "ok"
    if dd is not None and dd >= MAX_DAILY_DD:
        risk_lamp = "bad"
    patch["lights"] = {"st_bridge": "ok", "risk_watchdog": risk_lamp}
    if cleaned != str(ai.get("summary") or ""):
        ai["summary"] = cleaned
        patch["ai"] = ai
    RUNTIME.patch(**patch)


def _ping_st() -> bool:
    try:
        req = urllib.request.Request(ST_URL + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            raw = resp.read().decode("utf-8", "replace")
        j = json.loads(raw)
        return bool(j.get("status") == "ok" or j.get("ok") is True)
    except Exception:
        return False


def _get_json(path: str, timeout: float = 2.5) -> Optional[dict[str, Any]]:
    try:
        req = urllib.request.Request(ST_URL + path, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        j = json.loads(raw)
        return j if isinstance(j, dict) else None
    except Exception:
        return None


def _style_from_score(score: Any, adv: Any) -> int:
    try:
        s = float(score)
    except Exception:
        s = 50.0
    if s >= 70:
        hint = 65
    elif s >= 55:
        hint = 55
    elif s >= 45:
        hint = 50
    elif s >= 30:
        hint = 40
    else:
        hint = 35
    try:
        a = float(adv) if adv is not None else None
    except Exception:
        a = None
    if a is not None:
        if a < 0.35:
            hint = min(hint, 40)
        if a > 0.65:
            hint = max(hint, 55)
    return max(20, min(90, int(round(hint))))


def pull_st_macro(*, force: bool = False) -> bool:
    """WD←ST pull: fundamental + breadth → POST-equivalent overlay (clears fail-safe)."""
    global _last_pull_at
    now = time.time()
    if not force and (now - _last_pull_at) < 12.0:
        return False
    _last_pull_at = now
    fund = _get_json("/fundamental/" + urllib.parse.quote("^TWII", safe=""))
    br = _get_json("/breadth")
    if not fund and not br:
        link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
        link["pull_ok"] = False
        link["last_pull_at"] = now_iso()
        RUNTIME.patch(st_link=link)
        return False
    fund = fund or {}
    br = br or {}
    score = fund.get("score")
    if score is None:
        score = br.get("score")
    adv = (br.get("stocks") or {}).get("advRatio")
    if score is None and adv is None:
        link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
        link["pull_ok"] = False
        link["last_pull_at"] = now_iso()
        RUNTIME.patch(st_link=link)
        return False
    style = _style_from_score(score, adv)
    try:
        delever = score is not None and float(score) < 35
    except Exception:
        delever = False
    note = (
        f"WD 拉取 ST · 體質 {round(float(score)) if score is not None else '—'}"
        f" · 風格 {style}"
        + (" · 降載" if delever else "")
    )
    from .engine import apply_st_bridge

    apply_st_bridge(
        {
            "style": style,
            "delever": delever,
            "note": note,
            "meta": {
                "score": score,
                "advRatio": adv,
                "label": fund.get("label") or br.get("label"),
                "source": "wd-st-pull",
            },
        }
    )
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    link["pull_ok"] = True
    link["last_pull_at"] = now_iso()
    RUNTIME.patch(st_link=link)
    audit.write("st_pull", {"style": style, "score": score, "advRatio": adv})
    return True


def _overlay_age_sec(link: dict[str, Any]) -> Optional[float]:
    ep = finite_number(link.get("overlay_epoch"))
    if ep is None:
        return None
    age = time.time() - ep
    return age if age >= 0 else None


def _tighten_invalidation(ai: dict[str, Any], price: float) -> dict[str, Any]:
    inv = dict(ai.get("invalidation") or {})
    side = str(inv.get("side") or "below")
    inv_price = finite_number(inv.get("price"))
    if price > 0 and inv_price is not None and inv_price > 0:
        if side == "below" and inv_price < price:
            inv["price"] = round(inv_price + (price - inv_price) * 0.40, 0)
        elif side == "above" and inv_price > price:
            inv["price"] = round(inv_price - (inv_price - price) * 0.40, 0)
    ai["invalidation"] = inv
    return ai


def _write_inv_txt(ai: dict[str, Any], symbol: str = "TXF") -> None:
    """Soft-sync invalidation for 下單大師 side-file (non-fatal)."""
    try:
        from .broker import write_invalidation_txt

        inv = ai.get("invalidation") if isinstance(ai.get("invalidation"), dict) else {}
        if inv.get("price") is not None:
            write_invalidation_txt(
                float(inv["price"]),
                str(inv.get("side") or "below"),
                symbol=symbol,
            )
    except Exception:
        pass


def enforce_fail_safe(reason: str | None = None, *, tighten: bool = False) -> dict[str, Any]:
    """Keep fail-safe sticky: style cap + delever + warn lamps (every tick)."""
    st = RUNTIME.snapshot()
    link = dict(st.get("st_link") or _default_link())
    ov = dict(st.get("st_overlay") or {})
    reason = str(reason or link.get("fail_safe_reason") or ov.get("fail_safe_reason") or "Fail-safe")
    kind = _kind_of(reason)
    ai = dict(st.get("ai") or {})
    quote = assess_quote(st.get("quote"), st.get("symbol"), now=time.time(), mode=str(st.get("mode") or "unknown"))
    price = quote["price"] if quote["entry_allowed"] else None
    if tighten and price is not None:
        ai = _tighten_invalidation(ai, price)
    # Never stack banners into summary — badge UI reads fail_safe_reason
    ai["summary"] = scrub_fail_safe_summary(ai.get("summary"))

    link.update(
        {
            "status": "down" if kind == "heartbeat" else "warn",
            "fail_safe": True,
            "fail_safe_reason": reason,
            "fail_safe_kind": kind,
        }
    )
    ov.update(
        {
            "aggressiveness": FAIL_SAFE_STYLE,
            "delever": True,
            "note": f"Fail-safe · {reason}",
            "fail_safe": True,
            "fail_safe_reason": reason,
        }
    )
    try:
        cur_style = int(st.get("style") or 50)
    except Exception:
        cur_style = 50
    style = min(cur_style, FAIL_SAFE_STYLE)

    snap = RUNTIME.patch(
        style=style,
        ai=ai,
        st_overlay=ov,
        st_link=link,
        lights={"st_bridge": "warn" if kind != "heartbeat" else "bad", "risk_watchdog": "warn"},
    )
    if st.get("mode") == "live" and not ai.get("demo"):
        _write_inv_txt(ai, str(st.get("symbol") or "TXF"))
    return snap


def apply_fail_safe(reason: str) -> dict[str, Any]:
    """Enter or refresh fail-safe (tighten invalidation on first entry / kind change)."""
    st = RUNTIME.snapshot()
    link = dict(st.get("st_link") or _default_link())
    kind = _kind_of(reason)
    already = bool(link.get("fail_safe") or (st.get("st_overlay") or {}).get("fail_safe"))
    same_kind = str(link.get("fail_safe_kind") or "") == kind
    prev_inv = None
    try:
        prev_inv = dict(((st.get("ai") or {}).get("invalidation") or {}))
    except Exception:
        prev_inv = None
    do_tighten = not already or not same_kind
    snap = enforce_fail_safe(reason, tighten=do_tighten)
    if not already:
        audit.write("fail_safe", {"reason": reason, "kind": kind})
        push_async(snap, reason="fail_safe", force=True)
    elif not same_kind:
        audit.write("fail_safe", {"reason": reason, "kind": kind, "upgrade": True})
        push_async(snap, reason="fail_safe", force=True)
    # Fail-safe 收緊失效價 → 寫執行細節 MD（盤後可溯源）
    if do_tighten:
        try:
            from . import exec_md

            new_inv = ((snap.get("ai") or {}).get("invalidation") or {})
            md_meta = exec_md.on_invalidation_trail(
                snap, reason=reason, prev_inv=prev_inv, new_inv=new_inv
            )
            fields = (md_meta or {}).get("ai_fields") or {}
            if fields:
                ai2 = dict(snap.get("ai") or {})
                ai2.update(fields)
                snap = RUNTIME.patch(ai=ai2)
        except Exception:
            pass
    return snap


def _enforce_daily_dd() -> None:
    """Hard stop when session equity drawdown ≥ MAX_DAILY_DD (default 5%)."""
    global _dd_locked
    st = RUNTIME.snapshot()
    ratio = daily_dd_ratio(st)
    acct = dict(st.get("account") or {})
    acct["daily_dd_pct"] = round(ratio * 100, 2) if ratio is not None else None
    acct["daily_dd_limit_pct"] = round(MAX_DAILY_DD * 100, 2)
    lights: dict[str, Any] = {}
    if ratio is None:
        RUNTIME.patch(account=acct, lights={"risk_watchdog": "warn"})
        return
    if ratio >= WARN_DAILY_DD and ratio < MAX_DAILY_DD:
        lights["risk_watchdog"] = "warn"
        RUNTIME.patch(account=acct, lights=lights)
        return
    if ratio < MAX_DAILY_DD:
        if _dd_locked and not st.get("kill_switch"):
            _dd_locked = False
        RUNTIME.patch(account=acct)
        return

    lights["risk_watchdog"] = "bad"
    RUNTIME.patch(account=acct, lights=lights)
    if st.get("kill_switch") and _dd_locked:
        return
    RUNTIME.set_kill(True)
    _dd_locked = True
    audit.write(
        "daily_dd_lock",
        {
            "ratio": ratio,
            "limit": MAX_DAILY_DD,
            "yesterday": acct.get("yesterday_balance"),
            "equity": acct.get("equity"),
            "flatten": DD_FLATTEN,
        },
    )
    if DD_FLATTEN:
        try:
            from .broker import panic_flatten

            flat = panic_flatten(RUNTIME.snapshot())
            RUNTIME.patch(
                positions=flat.get("positions"),
                exec=flat.get("exec"),
            )
            RUNTIME.set_kill(True)
        except Exception:
            pass
    push_async(RUNTIME.snapshot(), reason="daily_dd_lock", force=True)


def _tick() -> None:
    global _fail_count
    ok = _ping_st()
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    link["last_ping_at"] = now_iso()
    with _lock:
        if ok:
            _fail_count = 0
            link["fail_count"] = 0
            link["last_ok_at"] = now_iso()
            if not link.get("fail_safe"):
                link["status"] = "ok"
            lamp = "warn" if link.get("fail_safe") else "ok"
            RUNTIME.patch(st_link=link, lights={"st_bridge": lamp})
        else:
            _fail_count += 1
            link["fail_count"] = _fail_count
            link["status"] = "down" if _fail_count >= FAIL_AFTER else "warn"
            RUNTIME.patch(
                st_link=link,
                lights={"st_bridge": "warn" if _fail_count < FAIL_AFTER else "bad"},
            )

    try:
        _enforce_daily_dd()
    except Exception:
        pass

    # 由服務端心跳維持 WD→ST 快照新鮮度，不依賴 WaveDeck 網頁是否位於前景。
    # force=True 讓相同狀態也能重新發布；否則 st_push 的簽章去重會略過心跳。
    if ok:
        push_async(RUNTIME.snapshot(), reason="heartbeat", force=True)

    if not ok and _fail_count >= FAIL_AFTER:
        apply_fail_safe("ST 心跳中斷")
        return

    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    age = _overlay_age_sec(link)
    # Soft retry: ST alive but overlay aging / missing → pull macro
    need_pull = ok and (
        age is None or age >= OVERLAY_PULL_SEC or bool(link.get("fail_safe"))
    )
    if need_pull:
        pull_st_macro(force=bool(link.get("fail_safe") and (age is None or age >= OVERLAY_PULL_SEC)))

    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    age = _overlay_age_sec(link)
    if age is None:
        apply_fail_safe("宏觀覆寫來源時間未知或在未來")
        return
    if age > OVERLAY_STALE_SEC:
        apply_fail_safe(f"宏觀覆寫過期 {int(age)}s")
        return

    if fail_safe_active():
        enforce_fail_safe(tighten=False)


def _loop() -> None:
    if not RUNTIME.snapshot().get("st_link"):
        RUNTIME.patch(st_link=_default_link())
    while not _stop.wait(PING_SEC):
        try:
            _tick()
        except Exception as exc:
            try:
                import sys

                sys.stderr.write(f"[wavedeck] st_link tick: {exc}\n")
            except Exception:
                pass


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="wd-st-heartbeat", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def snapshot_link() -> dict[str, Any]:
    return dict(RUNTIME.snapshot().get("st_link") or _default_link())


def fail_safe_active(state: dict[str, Any] | None = None) -> bool:
    st = state or RUNTIME.snapshot()
    return bool((st.get("st_link") or {}).get("fail_safe") or (st.get("st_overlay") or {}).get("fail_safe"))
