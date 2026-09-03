#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 實機驗證 Stock Terminal、WaveDeck、雙向 bridge 與 SSE。"""
from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {url} 回傳 HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, body: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"POST {url} 回傳 HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def bridge_payload(overlay: dict[str, Any], marker: str | None = None) -> dict[str, Any]:
    note = marker if marker is not None else str(overlay.get("note") or "")
    return {
        "style": overlay.get("aggressiveness"),
        "delever": bool(overlay.get("delever")),
        "note": note,
        "meta": {
            "source": "實機煙霧驗證" if marker is not None else overlay.get("source"),
            "score": overlay.get("score"),
            "advRatio": overlay.get("advRatio"),
            "rotation": overlay.get("rotation"),
            "spillover_prob": overlay.get("spillover_prob"),
            "leaders": overlay.get("leaders") or [],
            "hot_stage": overlay.get("hot_stage"),
            "chain_breadth": overlay.get("chain_breadth"),
            "chain_contig": overlay.get("chain_contig"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=32.0, help="SSE 持續觀測秒數")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "logs" / "實機煙霧驗證.json",
        help="驗證收據輸出路徑",
    )
    args = parser.parse_args()

    port_file = ROOT / "wavedeck" / "data" / "wavedeck.port"
    wd_port = int(port_file.read_text(encoding="utf-8").strip())
    st_base = "http://127.0.0.1:18432"
    wd_base = f"http://127.0.0.1:{wd_port}"
    started = time.time()
    marker = f"實機煙霧驗證-{int(started * 1000)}"

    st_health = get_json(st_base + "/health")
    wd_health = get_json(wd_base + "/health")
    wd_state = get_json(wd_base + "/api/state").get("state") or {}
    original_overlay = dict(wd_state.get("st_overlay") or {})
    initial_bus = get_json(st_base + "/bridge/wavedeck")

    if not st_health.get("tipUx"):
        raise RuntimeError("Stock Terminal /health 未回報 tipUx=true")
    if not wd_health.get("ok") or wd_health.get("service") != "WaveDeck":
        raise RuntimeError("WaveDeck /health 未回報可用")
    if not initial_bus.get("ok"):
        raise RuntimeError("Stock Terminal WaveDeck bridge 初始快照不可用")

    connected = threading.Event()
    full_sync = threading.Event()
    bridge_event = threading.Event()
    stop = threading.Event()
    sse_result: dict[str, Any] = {
        "http_status": None,
        "content_type": None,
        "events": [],
        "keepalives": 0,
        "deadline_reached": False,
        "error": None,
    }

    def consume_sse() -> None:
        request = urllib.request.Request(
            st_base + "/bridge/wavedeck/stream",
            headers={
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
                "Origin": wd_base,
            },
        )
        event_name = "message"
        data_lines: list[str] = []
        deadline = time.monotonic() + max(5.0, args.duration)
        try:
            with urllib.request.urlopen(request, timeout=20.0) as response:
                sse_result["http_status"] = response.status
                sse_result["content_type"] = response.headers.get("Content-Type")
                connected.set()
                while not stop.is_set() and time.monotonic() < deadline:
                    raw = response.readline()
                    if not raw:
                        raise RuntimeError("SSE 連線在觀測期限前關閉")
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith(":"):
                        sse_result["keepalives"] += 1
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip() or "message"
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                        continue
                    if line or not data_lines:
                        continue
                    payload = json.loads("\n".join(data_lines))
                    data_lines.clear()
                    received = {
                        "event": event_name,
                        "event_type": payload.get("event_type"),
                        "push_reason": payload.get("push_reason"),
                        "timestamp": payload.get("timestamp"),
                    }
                    sse_result["events"].append(received)
                    if event_name == "FULL_SYNC" and payload.get("event_type") == "FULL_SYNC":
                        full_sync.set()
                    if (
                        event_name == "POSITION_STATE_CHANGE"
                        and payload.get("event_type") == "POSITION_STATE_CHANGE"
                        and payload.get("push_reason") == "st_bridge"
                    ):
                        bridge_event.set()
                    event_name = "message"
                if not stop.is_set() and time.monotonic() >= deadline:
                    sse_result["deadline_reached"] = True
        except Exception as exc:  # pragma: no cover - 僅在實機服務下觸發
            sse_result["error"] = f"{type(exc).__name__}: {exc}"
            connected.set()

    thread = threading.Thread(target=consume_sse, name="tip-wavedeck-sse-smoke", daemon=True)
    thread.start()

    restored = False
    try:
        if not connected.wait(5.0):
            raise RuntimeError("SSE 在 5 秒內未建立連線")
        if sse_result["error"]:
            raise RuntimeError(str(sse_result["error"]))
        if not full_sync.wait(5.0):
            raise RuntimeError("SSE 在 5 秒內未收到 FULL_SYNC")

        bridge_response = post_json(wd_base + "/bridge/st", bridge_payload(original_overlay, marker))
        if not bridge_response.get("ok"):
            raise RuntimeError("ST→WD bridge 寫入未成功")
        if not bridge_event.wait(5.0):
            raise RuntimeError("WD→ST 後未在 SSE 收到 POSITION_STATE_CHANGE")

        deadline = time.monotonic() + 5.0
        marker_seen = False
        bus_after: dict[str, Any] = {}
        while time.monotonic() < deadline:
            bus_after = get_json(st_base + "/bridge/wavedeck")
            note = str(((bus_after.get("report") or {}).get("st_overlay") or {}).get("note") or "")
            if note == marker:
                marker_seen = True
                break
            time.sleep(0.2)
        if not marker_seen:
            raise RuntimeError("ST bridge 快照未收到本次 WaveDeck 回推標記")

        post_json(wd_base + "/bridge/st", bridge_payload(original_overlay))
        restored = True

        remaining = max(0.0, args.duration - (time.time() - started))
        stop.wait(remaining)
        if sse_result["error"]:
            raise RuntimeError(str(sse_result["error"]))
        if not thread.is_alive() and not sse_result["deadline_reached"]:
            raise RuntimeError("SSE 連線未維持到觀測期限")
        sse_result["stable_for_duration"] = True

        final_wd = get_json(wd_base + "/health")
        final_bus = get_json(st_base + "/bridge/wavedeck")
        event_types = [event.get("event_type") for event in sse_result["events"]]
        if event_types.count("POSITION_STATE_CHANGE") < 1:
            raise RuntimeError("SSE 觀測期間沒有 POSITION_STATE_CHANGE")
        if not final_wd.get("ok") or (final_wd.get("st_link") or {}).get("status") != "ok":
            raise RuntimeError("觀測結束時 WaveDeck 或 ST 心跳不是正常狀態")
        if not final_bus.get("fresh"):
            raise RuntimeError("觀測結束時 Stock Terminal bridge 快照已過期")

        receipt = {
            "通過": True,
            "觀測時間": time.strftime("%Y-%m-%d %H:%M:%S"),
            "觀測秒數": round(time.time() - started, 1),
            "Stock Terminal": {
                "網址": st_base,
                "版本": st_health.get("version"),
                "TIP 介面": st_health.get("tipUx"),
            },
            "WaveDeck": {
                "網址": wd_base,
                "版本": wd_health.get("version"),
                "實際埠檔": str(port_file),
                "ST 連線": final_wd.get("st_link"),
            },
            "Bridge": {
                "驗證標記": marker,
                "已收到標記": marker_seen,
                "已還原覆寫": restored,
                "資料新鮮": final_bus.get("fresh"),
                "資料年齡秒數": final_bus.get("age_sec"),
            },
            "SSE": {
                "HTTP 狀態": sse_result["http_status"],
                "內容類型": sse_result["content_type"],
                "事件": sse_result["events"],
                "Keepalive 次數": sse_result["keepalives"],
                "抵達觀測期限": sse_result["deadline_reached"],
                "全程穩定": sse_result["stable_for_duration"],
                "錯誤": sse_result["error"],
            },
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        print(f"\n驗證收據：{args.evidence}")
        return 0
    finally:
        if not restored:
            try:
                post_json(wd_base + "/bridge/st", bridge_payload(original_overlay))
            except Exception:
                pass
        stop.set()


if __name__ == "__main__":
    raise SystemExit(main())
