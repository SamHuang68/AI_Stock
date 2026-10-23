"""Use the owning ST process for shared LLM coordination."""
from __future__ import annotations

import json
import urllib.request

from runtime_paths import BINDING, backend_url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(path: str, body: dict | None = None) -> dict:
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(backend_url() + path, data=encoded,
                                    headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=3) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise RuntimeError("ST LLM gate 回應超過大小限制。")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise RuntimeError("ST LLM gate 回應格式無效。")
    return result


def _validate_identity(value: dict) -> None:
    if (value.get("dataRootId") != BINDING.data_root_id
            or value.get("storageMode") != "external"
            or value.get("runtimeRole") != "backend"
            or value.get("storageCapability") != BINDING.capability_version):
        raise RuntimeError("ST LLM gate 後端資料根或角色不符。")


def request_gate(op: str = "status") -> dict:
    if BINDING.mode != "external" or not BINDING.data_root_id:
        raise RuntimeError("此資料模式沒有已登記的 ST LLM gate；不允許直接寫入共用鎖檔。")
    health = _request("/health")
    _validate_identity(health)
    if health.get("ok") is not True:
        raise RuntimeError("ST 後端尚未就緒。")
    if op == "status":
        value = _request("/api/llm-gate")
    elif op in {"acquire", "release"}:
        value = _request("/api/llm-gate", {"op": op, "owner": "wd", "ttl_sec": 90,
                                         "expectedDataRootId": BINDING.data_root_id})
    else:
        raise ValueError("未知 LLM gate 操作。")
    _validate_identity(value)
    if value.get("ok") is not True:
        raise RuntimeError("ST LLM gate 操作未成功。")
    if op == "acquire" and (value.get("acquired") is not True or value.get("owner") != "wd" or value.get("held") is not True):
        raise RuntimeError("ST LLM gate 未授予 WaveDeck 擁有權。")
    if op == "release" and value.get("released") is not True:
        raise RuntimeError("ST LLM gate 未確認釋放。")
    return value
