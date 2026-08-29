#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EVO-T1 AI runtime policy for Stock Terminal.

The browser never selects an endpoint or arbitrary model. Stock Terminal owns
two explicit server-side routes: ``fast`` uses a small local model; ``deep``
uses one bounded Hermes Agent advisory invocation. Model output cannot mutate
Stock Terminal state. Traces never store prompts, context, keys or output.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


ROOT = Path(__file__).resolve().parents[1]
HOST_LABEL = (os.environ.get("ST_AI_HOST_LABEL") or "EVO-T1").strip()[:48]
TRACE_PATH = Path(os.environ.get("ST_AI_TRACE_PATH") or str(ROOT / "logs" / "ai_runtime_trace.jsonl"))


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read one integer setting without allowing import-time configuration failure."""
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))

OLLAMA_BASE = (os.environ.get("ST_OLLAMA_BASE") or "http://127.0.0.1:11434").rstrip("/")
LMSTUDIO_BASE = (
    os.environ.get("AI_LOCAL_BASE")
    or os.environ.get("ST_LLM_BASE")
    or "http://127.0.0.1:1234/v1"
).rstrip("/")
OLLAMA_MODELS_URL = OLLAMA_BASE + "/api/tags"
OLLAMA_CHAT_URL = OLLAMA_BASE + "/api/chat"
LMSTUDIO_MODELS_URL = LMSTUDIO_BASE + "/models"
LMSTUDIO_CHAT_URL = LMSTUDIO_BASE + "/chat/completions"

FAST_PROVIDER = (os.environ.get("ST_AI_FAST_PROVIDER") or "lmstudio").strip().lower()
if FAST_PROVIDER not in {"lmstudio", "ollama"}:
    FAST_PROVIDER = "lmstudio"
FAST_MODEL = (
    os.environ.get("ST_AI_FAST_MODEL")
    or ("google/gemma-4-e4b" if FAST_PROVIDER == "lmstudio" else "gemma2:latest")
).strip()
FAST_MAX_TOKENS = _bounded_env_int("ST_AI_FAST_MAX_TOKENS", 2048, 1400, 4096)

HERMES_PROVIDER = (os.environ.get("ST_AI_HERMES_PROVIDER") or "nvidia").strip()
HERMES_MODEL = (
    os.environ.get("ST_AI_HERMES_MODEL")
    or "nvidia/nemotron-3-super-120b-a12b"
).strip()

# Deliberately conservative user guidance, not an SLA. It includes cold model
# load, context prefill, reasoning and response transfer.
FAST_ESTIMATE_SECONDS = max(180, int(os.environ.get("ST_AI_FAST_ESTIMATE_SECONDS") or 300))
DEEP_ESTIMATE_SECONDS = max(360, int(os.environ.get("ST_AI_DEEP_ESTIMATE_SECONDS") or 720))
FAST_SOCKET_TIMEOUT = max(FAST_ESTIMATE_SECONDS + 120, 600)
DEEP_PROCESS_TIMEOUT = max(DEEP_ESTIMATE_SECONDS + 180, 900)

SYSTEM = (
    "你是一位台股投資研究副駕，專精台股與台灣 AI 供應鏈。\n"
    "規則：\n"
    "1. 一律繁體中文，直白、有觀點，但不得下達交易指令。\n"
    "2. 只能使用 Stock Terminal 提供的資料；沒有的數字必須明說資料未提供。\n"
    "3. 先陳述證據，再說最強反方、風險與失效條件。\n"
    "4. 模型輸出只供研究，不得修改市場資料、持倉或系統狀態。\n"
    "5. 結尾加上「⚠ 非投資建議」。"
)

_TRACE_LOCK = threading.Lock()


class AiRuntimeError(RuntimeError):
    """A bounded, user-readable AI runtime failure."""


class AiCompletionError(AiRuntimeError):
    """The model transport completed without one trustworthy visible answer."""


def _trace(event: str, *, request_id: str, mode: str, **details: object) -> None:
    """Persist sanitized execution evidence without prompts or output."""
    allowed: dict[str, object] = {}
    for key, value in details.items():
        if key in {
            "provider", "model", "dataBoundary", "phase", "errorType",
            "elapsedMs", "inputChars", "inputHash", "outputChars", "exitCode",
            "maxTokens", "finishReason", "completionTokens", "reasoningTokens",
        }:
            allowed[key] = value
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "component": "st_ai_runtime",
        "event": str(event)[:64],
        "requestId": str(request_id)[:64],
        "mode": str(mode)[:16],
        **allowed,
    }
    try:
        path = TRACE_PATH if TRACE_PATH.is_absolute() else ROOT / TRACE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def trace_event(event: str, *, request_id: str, mode: str, **details: object) -> None:
    _trace(event, request_id=request_id, mode=mode, **details)


def _fetch_json(url: str, timeout: float = 3.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload if isinstance(payload, dict) else {}


def _lmstudio_models() -> list[str]:
    payload = _fetch_json(LMSTUDIO_MODELS_URL)
    return [
        str(item.get("id")) for item in (payload.get("data") or [])
        if isinstance(item, dict) and item.get("id")
    ]


def _ollama_models() -> list[str]:
    payload = _fetch_json(OLLAMA_MODELS_URL)
    return [
        str(item.get("name")) for item in (payload.get("models") or [])
        if isinstance(item, dict) and item.get("name")
    ]


def _resolve_hermes_exe() -> Optional[Path]:
    configured = (os.environ.get("ST_HERMES_EXE") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    discovered = shutil.which("hermes")
    if discovered:
        candidates.append(Path(discovered))
    local_app_data = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidates.extend([
            Path(local_app_data) / "hermes" / "hermes-agent" / "bin" / "hermes.exe",
            Path(local_app_data) / "hermes" / "hermes-agent" / "venv" / "Scripts" / "hermes.exe",
        ])
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


def _estimate_label(seconds: int) -> str:
    minutes = max(1, (seconds + 59) // 60)
    return f"請預留約 {minutes} 分鐘（含模型載入、上下文預填與推理）"


def route_metadata(mode: str, *, probe: bool = True) -> dict[str, Any]:
    mode = "deep" if str(mode).lower() == "deep" else "fast"
    if mode == "deep":
        executable = _resolve_hermes_exe()
        return {
            "mode": "deep",
            "available": bool(executable and HERMES_PROVIDER and HERMES_MODEL),
            "host": HOST_LABEL,
            "provider": "Hermes Agent / " + HERMES_PROVIDER,
            "providerKey": "hermes",
            "model": HERMES_MODEL,
            "dataBoundary": "external" if HERMES_PROVIDER != "custom" else "configured-provider",
            "toolPolicy": "todo-only; no shell/file/browser/message tools",
            "estimateSeconds": DEEP_ESTIMATE_SECONDS,
            "estimateLabel": (
                f"請預留約 {max(1, (DEEP_ESTIMATE_SECONDS + 59) // 60)} 分鐘"
                "（含 Hermes 啟動、供應商連線、上下文預填與深度推理）"
            ),
            "phases": ["Hermes 啟動", "模型連線/載入", "上下文預填", "深度推理"],
            "reason": "" if executable else "Hermes CLI 未安裝或無法定位",
        }

    provider_label = "LM Studio" if FAST_PROVIDER == "lmstudio" else "Ollama"
    available = True
    reason = ""
    if probe:
        try:
            models = _lmstudio_models() if FAST_PROVIDER == "lmstudio" else _ollama_models()
            available = FAST_MODEL in models
            if not available:
                reason = f"指定模型 {FAST_MODEL} 尚未可用"
        except Exception as exc:
            available = False
            reason = f"{provider_label} 未連線（{type(exc).__name__}）"
    return {
        "mode": "fast",
        "available": available,
        "host": HOST_LABEL,
        "provider": provider_label,
        "providerKey": FAST_PROVIDER,
        "model": FAST_MODEL,
        "dataBoundary": "local-only",
        "toolPolicy": "no tools; advisory text only",
        "estimateSeconds": FAST_ESTIMATE_SECONDS,
        "estimateLabel": _estimate_label(FAST_ESTIMATE_SECONDS),
        "maxOutputTokens": FAST_MAX_TOKENS,
        "phases": ["模型冷啟動", "上下文預填", "快速推理"],
        "reason": reason,
    }


def runtime_status() -> dict[str, Any]:
    fast = route_metadata("fast", probe=True)
    deep = route_metadata("deep", probe=False)
    return {
        "ok": bool(fast.get("available") or deep.get("available")),
        "host": HOST_LABEL,
        "execution": "server-side-on-EVO-T1",
        "phoneInference": False,
        "modes": {"fast": fast, "deep": deep},
    }


def list_models() -> Optional[List[str]]:
    """Compatibility surface: expose only the selected fast model."""
    metadata = route_metadata("fast", probe=True)
    return [str(metadata["model"])] if metadata.get("available") else None


def _acquire_st_slot() -> tuple[bool, Optional[str]]:
    try:
        import llm_gate as gate
        if gate.wd_busy():
            if not gate.wait_or_defer("st", wait_sec=2.0, ttl_sec=FAST_ESTIMATE_SECONDS + 180):
                return False, "WD 微觀推論優先中，請稍後再試"
            return True, None
        if not gate.acquire("st", ttl_sec=FAST_ESTIMATE_SECONDS + 180):
            return False, "EVO-T1 本機模型忙碌，請稍後再試"
        return True, None
    except Exception:
        return True, None


def _release_st_slot() -> None:
    try:
        import llm_gate as gate
        gate.release("st")
    except Exception:
        pass


def _full_prompt(prompt: str, context: str) -> tuple[str, str]:
    prompt = str(prompt or "").strip()[:16_000]
    context = str(context or "").strip()[:180_000]
    if not prompt:
        raise AiRuntimeError("分析問題是空的")
    supplied = context or "（本次未附帶市場資料，只能回答一般原則。）"
    full = SYSTEM + "\n\n【Stock Terminal 提供的資料】\n" + supplied + "\n\n【分析任務】\n" + prompt
    return full, hashlib.sha256(full.encode("utf-8")).hexdigest()


def _stream_lmstudio(
    full_prompt: str,
    *,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Generator[str, None, None]:
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update({"maxTokens": FAST_MAX_TOKENS, "outputChars": 0})
    payload = {
        "model": FAST_MODEL,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.3,
        "max_tokens": FAST_MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        LMSTUDIO_CHAT_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    with urllib.request.urlopen(request, timeout=FAST_SOCKET_TIMEOUT) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                item = json.loads(data)
                choices = item.get("choices") or []
                choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    normalized = str(finish_reason).strip().lower()
                    diagnostics["finishReason"] = (
                        normalized if normalized in {
                            "stop", "length", "content_filter", "tool_calls", "function_call",
                        } else "other"
                    )
                usage = item.get("usage") or {}
                if isinstance(usage, dict):
                    completion_tokens = usage.get("completion_tokens")
                    if isinstance(completion_tokens, (int, float)) and completion_tokens >= 0:
                        diagnostics["completionTokens"] = int(completion_tokens)
                    details = usage.get("completion_tokens_details") or {}
                    reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
                    if isinstance(reasoning_tokens, (int, float)) and reasoning_tokens >= 0:
                        diagnostics["reasoningTokens"] = int(reasoning_tokens)
                # Deliberately ignore reasoning/reasoning_content/analysis. Only
                # model-visible answer text may cross the runtime boundary.
                delta = choice.get("delta") or {}
                content = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(content, str) and content:
                    diagnostics["outputChars"] = int(diagnostics.get("outputChars") or 0) + len(content)
                    yield content
            except (TypeError, ValueError):
                continue
    output_chars = int(diagnostics.get("outputChars") or 0)
    finish_reason = diagnostics.get("finishReason")
    if output_chars <= 0 and finish_reason == "length":
        raise AiCompletionError(
            f"本機模型已用完 {FAST_MAX_TOKENS} 個輸出 token，但尚未產生可見正文；請重試。"
        )
    if output_chars <= 0:
        raise AiCompletionError("本機模型完成推理，但未回傳可見正文；請重試。")
    if finish_reason == "length":
        raise AiCompletionError("本機模型回覆達輸出上限，內容可能不完整；請重試。")


def _stream_ollama(full_prompt: str) -> Generator[str, None, None]:
    payload = {
        "model": FAST_MODEL,
        "messages": [{"role": "user", "content": full_prompt}],
        "options": {"temperature": 0.3, "num_predict": FAST_MAX_TOKENS},
        "stream": True,
    }
    request = urllib.request.Request(
        OLLAMA_CHAT_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=FAST_SOCKET_TIMEOUT) as response:
        for raw in response:
            try:
                item = json.loads(raw.decode("utf-8", "replace"))
            except (TypeError, ValueError):
                continue
            chunk = (item.get("message") or {}).get("content")
            if chunk:
                yield str(chunk)
            if item.get("done"):
                break


def chat_stream(
    prompt: str,
    context: str = "",
    model: Optional[str] = None,
    *,
    request_id: Optional[str] = None,
) -> Generator[str, None, None]:
    """Stream the fixed fast-local route; caller model overrides are ignored."""
    del model
    request_id = request_id or uuid.uuid4().hex
    metadata = route_metadata("fast", probe=True)
    if not metadata.get("available"):
        raise AiRuntimeError(str(metadata.get("reason") or "快速本機模型未就緒"))
    full_prompt, digest = _full_prompt(prompt, context)
    ok, defer = _acquire_st_slot()
    if not ok:
        raise AiRuntimeError(defer or "本機模型忙碌")
    started = time.monotonic()
    output_chars = 0
    diagnostics: Dict[str, Any] = {"maxTokens": FAST_MAX_TOKENS}
    _trace(
        "started", request_id=request_id, mode="fast",
        provider=metadata["provider"], model=metadata["model"],
        dataBoundary=metadata["dataBoundary"], phase="model-load-prefill-inference",
        inputChars=len(full_prompt), inputHash=digest, maxTokens=FAST_MAX_TOKENS,
    )
    try:
        iterator = (
            _stream_lmstudio(full_prompt, diagnostics=diagnostics)
            if FAST_PROVIDER == "lmstudio" else _stream_ollama(full_prompt)
        )
        for chunk in iterator:
            output_chars += len(chunk)
            yield chunk
        if output_chars <= 0:
            raise AiCompletionError("本機模型完成推理，但未回傳可見正文；請重試。")
        _trace(
            "completed", request_id=request_id, mode="fast",
            provider=metadata["provider"], model=metadata["model"],
            dataBoundary=metadata["dataBoundary"], phase="complete",
            elapsedMs=round((time.monotonic() - started) * 1000), outputChars=output_chars,
            maxTokens=diagnostics.get("maxTokens"),
            finishReason=diagnostics.get("finishReason"),
            completionTokens=diagnostics.get("completionTokens"),
            reasoningTokens=diagnostics.get("reasoningTokens"),
        )
    except Exception as exc:
        _trace(
            "failed", request_id=request_id, mode="fast",
            provider=metadata["provider"], model=metadata["model"],
            dataBoundary=metadata["dataBoundary"], phase=(
                "completion-validation" if isinstance(exc, AiCompletionError) else "runtime"
            ),
            elapsedMs=round((time.monotonic() - started) * 1000), errorType=type(exc).__name__,
            outputChars=output_chars, maxTokens=diagnostics.get("maxTokens"),
            finishReason=diagnostics.get("finishReason"),
            completionTokens=diagnostics.get("completionTokens"),
            reasoningTokens=diagnostics.get("reasoningTokens"),
        )
        if isinstance(exc, AiRuntimeError):
            raise
        raise AiRuntimeError(f"{metadata['provider']} 快速摘要失敗：{type(exc).__name__}") from exc
    finally:
        _release_st_slot()


def _hermes_command(executable: Path) -> list[str]:
    return [
        str(executable), "chat", "--query-file", "-",
        "--provider", HERMES_PROVIDER, "--model", HERMES_MODEL,
        "--toolsets", "todo", "--reasoning", "high", "--max-turns", "2",
        "--ignore-rules", "--source", "tool", "-Q",
    ]


def deep_stream(
    prompt: str,
    context: str = "",
    *,
    request_id: Optional[str] = None,
) -> Generator[str, None, None]:
    """Run one bounded Hermes advisory turn and yield its final text."""
    request_id = request_id or uuid.uuid4().hex
    metadata = route_metadata("deep", probe=False)
    executable = _resolve_hermes_exe()
    if not metadata.get("available") or executable is None:
        raise AiRuntimeError(str(metadata.get("reason") or "Hermes Agent 未就緒"))
    full_prompt, digest = _full_prompt(prompt, context)
    started = time.monotonic()
    _trace(
        "started", request_id=request_id, mode="deep",
        provider=metadata["provider"], model=metadata["model"],
        dataBoundary=metadata["dataBoundary"], phase="hermes-start-provider-prefill-reasoning",
        inputChars=len(full_prompt), inputHash=digest,
    )
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            _hermes_command(executable), cwd=ROOT, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, stderr = process.communicate(input=full_prompt, timeout=DEEP_PROCESS_TIMEOUT)
        reply = str(stdout or "").strip()
        if process.returncode != 0:
            lines = str(stderr or "").strip().splitlines()
            suffix = lines[-1][:180] if lines else f"exit {process.returncode}"
            raise AiRuntimeError("Hermes 深度分析失敗：" + suffix)
        if not reply:
            raise AiRuntimeError("Hermes 未回傳分析內容")
        yield reply
        _trace(
            "completed", request_id=request_id, mode="deep",
            provider=metadata["provider"], model=metadata["model"],
            dataBoundary=metadata["dataBoundary"], phase="complete",
            elapsedMs=round((time.monotonic() - started) * 1000),
            outputChars=len(reply), exitCode=process.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            process.kill()
            process.communicate()
        _trace(
            "timeout", request_id=request_id, mode="deep",
            provider=metadata["provider"], model=metadata["model"],
            dataBoundary=metadata["dataBoundary"], phase="runtime",
            elapsedMs=round((time.monotonic() - started) * 1000), errorType=type(exc).__name__,
        )
        raise AiRuntimeError("Hermes 超過保守等待上限，已安全停止；市場資料不受影響") from exc
    except Exception as exc:
        _trace(
            "failed", request_id=request_id, mode="deep",
            provider=metadata["provider"], model=metadata["model"],
            dataBoundary=metadata["dataBoundary"], phase="runtime",
            elapsedMs=round((time.monotonic() - started) * 1000), errorType=type(exc).__name__,
        )
        if isinstance(exc, AiRuntimeError):
            raise
        raise AiRuntimeError(f"Hermes 深度分析失敗：{type(exc).__name__}") from exc


def chat(prompt: str, context: str = "", model: Optional[str] = None) -> Dict[str, Any]:
    """Compatibility non-streaming wrapper for the fixed fast route."""
    del model
    request_id = uuid.uuid4().hex
    try:
        reply = "".join(chat_stream(prompt, context, request_id=request_id))
        return {
            "reply": reply, "model": FAST_MODEL,
            "provider": "LM Studio" if FAST_PROVIDER == "lmstudio" else "Ollama",
            "requestId": request_id,
        }
    except AiRuntimeError as exc:
        return {"error": str(exc), "requestId": request_id}
