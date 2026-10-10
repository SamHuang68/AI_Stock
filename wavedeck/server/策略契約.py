"""固定策略版本與訊號收據；沿用 WaveDeck 的稽核資料庫。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from . import audit

SCHEMA = "st.strategy/v1"
ACTIONS = {"ENTER_LONG", "ENTER_SHORT", "HOLD", "REDUCE", "EXIT"}
LABELS = {"ENTER_LONG": "規則多單進場", "ENTER_SHORT": "規則空單進場", "HOLD": "規則續抱", "REDUCE": "規則減碼", "EXIT": "規則平倉"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("策略檔格式不符 st.strategy/v1")
    sid, version = manifest.get("strategy_id"), manifest.get("version")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", sid):
        raise ValueError("策略識別碼格式無效")
    if not isinstance(version, str) or not re.fullmatch(r"[a-f0-9]{64}", version):
        raise ValueError("策略版本須為完整 SHA-256")
    canonical = manifest.get("canonical_json")
    if not isinstance(canonical, str) or len(canonical) > 100_000:
        raise ValueError("策略缺少有效的雜湊原文")
    core = {key: manifest.get(key) for key in ("schema", "definition", "execution", "context")}
    try:
        same = _json(json.loads(canonical)) == _json(core)
    except (ValueError, TypeError):
        same = False
    if not same or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != version:
        raise ValueError("策略內容與版本雜湊不一致")
    definition, execution, context = (core[key] for key in ("definition", "execution", "context"))
    if not all(isinstance(item, dict) for item in (definition, execution, context)):
        raise ValueError("策略定義、執行條件與商品資訊須完整")
    if definition.get("kind") not in {"builder", "script", "external_rules"}:
        raise ValueError("不支援的策略定義種類")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,40}", str(context.get("symbol") or "")):
        raise ValueError("策略商品代碼無效")
    if not re.fullmatch(r"[1-9][0-9]{0,3}[mhdw]", str(execution.get("timeframe") or "")):
        raise ValueError("策略 K 線週期無效，例如 5m、1d")
    return json.loads(_json(manifest))


def _tables(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS strategy_versions (strategy_id TEXT NOT NULL, version TEXT NOT NULL, manifest TEXT NOT NULL, PRIMARY KEY(strategy_id,version))")
    connection.execute("CREATE TABLE IF NOT EXISTS strategy_signals (strategy_id TEXT NOT NULL, signal_id TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, PRIMARY KEY(strategy_id,signal_id))")
    connection.execute("CREATE TABLE IF NOT EXISTS strategy_bar_clock (strategy_id TEXT PRIMARY KEY, bar_epoch REAL NOT NULL)")


def register(manifest: dict) -> dict:
    verified = validate_manifest(manifest)
    with audit._lock, closing(audit._conn()) as connection:
        _tables(connection)
        row = connection.execute("SELECT manifest FROM strategy_versions WHERE strategy_id=? AND version=?", (verified["strategy_id"], verified["version"])).fetchone()
        if row:
            old = json.loads(row[0])
            if old["canonical_json"] != verified["canonical_json"]:
                raise ValueError("已保存的策略版本不可覆寫")
            return old
        connection.execute("INSERT INTO strategy_versions VALUES (?,?,?)", (verified["strategy_id"], verified["version"], _json(verified)))
        connection.commit()
    audit.write("strategy_registered", {"strategy_id": verified["strategy_id"], "version": verified["version"]})
    return verified


def get(strategy_id: str, version: str) -> dict:
    with audit._lock, closing(audit._conn()) as connection:
        _tables(connection)
        row = connection.execute("SELECT manifest FROM strategy_versions WHERE strategy_id=? AND version=?", (strategy_id, version)).fetchone()
    if not row:
        raise ValueError("尚未匯入此策略版本")
    return validate_manifest(json.loads(row[0]))


def claim(body: dict) -> dict | None:
    """原子記錄訊號；相同 ID 的內容不得更換，未完成亦不重送。"""
    digest = hashlib.sha256(_json(body).encode("utf-8")).hexdigest()
    with audit._lock, closing(audit._conn()) as connection:
        _tables(connection)
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT digest,result FROM strategy_signals WHERE strategy_id=? AND signal_id=?", (body["strategy_id"], body["signal_id"])).fetchone()
        if row:
            if row[0] != digest:
                raise ValueError("訊號識別碼重複且內容不同，已拒絕")
            return json.loads(row[1]) if row[1] else {"ok": False, "pending": True, "reason": "訊號已受理；結果待核對"}
        bar_epoch = datetime.fromisoformat(body["bar_close_time"].replace("Z", "+00:00")).timestamp()
        clock = connection.execute("SELECT bar_epoch FROM strategy_bar_clock WHERE strategy_id=?", (body["strategy_id"],)).fetchone()
        if clock and bar_epoch <= clock[0]:
            raise ValueError("訊號收 K 時間重複或落後於已受理訊號")
        connection.execute("INSERT INTO strategy_signals VALUES (?,?,?,?,?,NULL)", (body["strategy_id"], body["signal_id"], body["version"], digest, _json(body)))
        connection.execute("INSERT OR REPLACE INTO strategy_bar_clock VALUES (?,?)", (body["strategy_id"], bar_epoch))
        connection.commit()
    return None


def finish(body: dict, result: dict) -> None:
    receipt = {key: result.get(key) for key in ("ok", "blocked", "reason", "decision", "gate", "execution")}
    with audit._lock, closing(audit._conn()) as connection:
        connection.execute("UPDATE strategy_signals SET result=? WHERE strategy_id=? AND signal_id=?", (_json(receipt), body["strategy_id"], body["signal_id"]))
        connection.commit()


def decision_from_signal(body: dict, active: dict, now: datetime | None = None) -> dict:
    if body.get("strategy_id") != active.get("strategy_id") or body.get("version") != active.get("version"):
        raise ValueError("訊號策略版本與目前啟用版本不符")
    manifest = get(body["strategy_id"], body["version"])
    if body.get("symbol") != manifest["context"]["symbol"] or body.get("timeframe") != manifest["execution"]["timeframe"]:
        raise ValueError("訊號商品或 K 線週期與固定策略不符")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", str(body.get("signal_id") or "")):
        raise ValueError("訊號識別碼無效")
    action = body.get("action")
    if action not in ACTIONS:
        raise ValueError("規則訊號缺少有效的進出場動作")
    try:
        bar = datetime.fromisoformat(str(body["bar_close_time"]).replace("Z", "+00:00"))
        if bar.tzinfo is None:
            raise ValueError()
        age = ((now or datetime.now(timezone.utc)) - bar).total_seconds()
        max_age = min(3600, max(10, int(active.get("max_signal_age_sec", 300))))
        if age < -5 or age > max_age:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("訊號收 K 時間缺少時區、已過期或位於未來") from None
    price, lots = body.get("price"), body.get("lots", 1)
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("訊號價格須為有效正數")
    if isinstance(lots, bool) or not isinstance(lots, int) or not 1 <= lots <= 1000:
        raise ValueError("訊號口數須為 1 至 1000 的整數")
    return {"action": action, "action_label": LABELS[action], "confidence": None,
            "provider": "rules", "event": str(body.get("event") or "STRATEGY_SIGNAL"),
            "summary": "依固定版本接收外部規則訊號；原始條件計算由訊號來源負責。",
            "strategy_id": body["strategy_id"], "version": body["version"], "signal_id": body["signal_id"],
            "requested_lots": lots, "source_signal": json.loads(_json(body)),
            "process": {"route": "固定策略→風控→券商", "chase_risk": "low"}, "updated_at": datetime.now(timezone.utc).isoformat()}
