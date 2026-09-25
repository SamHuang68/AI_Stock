# -*- coding: utf-8 -*-
"""AI 金鑰 / 模型 / Anthropic 呼叫（從 server.py 拆出 · H2 續）"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:
    from .secret_store import load_secret, save_secret
except ImportError:
    from secret_store import load_secret, save_secret

try:
    import slog
    log = slog.get_logger('ai_api')
except Exception:
    log = None

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)

_AI_KEY_FILE = os.path.join(_BASE, 'data', 'ai_key.bin')
_AI_KEY_LEGACY_FILE = os.path.join(_BASE, 'data', 'ai_key.txt')
_ai_key_lock = threading.Lock()

# 預設 Sonnet 家族（opus 為 opt-in）；/v1/models 查不到時的後備改為當代的 Sonnet 5
DEFAULT_MODEL = 'claude-sonnet-5'
_MODEL_CACHE = {'date': '', 'id': DEFAULT_MODEL}
_OPUS_CACHE = {'date': '', 'id': ''}


def load_ai_key() -> str:
    try:
        if os.path.isfile(_AI_KEY_FILE):
            return load_secret(_AI_KEY_FILE).strip()
        if os.path.isfile(_AI_KEY_LEGACY_FILE):
            with open(_AI_KEY_LEGACY_FILE, encoding='utf-8-sig') as f:
                legacy = f.read().strip()
            save_secret(_AI_KEY_FILE, legacy)
            # Only remove legacy plaintext after the protected copy round-trips.
            if load_secret(_AI_KEY_FILE).strip() == legacy:
                os.unlink(_AI_KEY_LEGACY_FILE)
            return legacy
    except Exception as exc:
        if log:
            log.warning('AI credential unavailable: %s', type(exc).__name__)
        return ''
    return ''


def save_ai_key(k: str) -> None:
    with _ai_key_lock:
        save_secret(_AI_KEY_FILE, (k or '').strip())


def resolve_model(api_key: Optional[str]) -> str:
    from datetime import date as _d
    today = _d.today().strftime('%Y%m%d')
    if _MODEL_CACHE['date'] == today and _MODEL_CACHE['id']:
        return _MODEL_CACHE['id']
    model = DEFAULT_MODEL
    if api_key:
        try:
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/models?limit=100',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01'},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            ms = [m for m in (data.get('data') or []) if m.get('id')]
            pick = (
                next((m for m in ms if 'sonnet' in m['id'].lower()), None)
                or next((m for m in ms if 'opus' in m['id'].lower()), None)
                or (ms[0] if ms else None)
            )
            if pick:
                model = pick['id']
        except Exception as e:
            if log:
                log.warning('resolve_model: %s', e)
    _MODEL_CACHE['date'] = today
    _MODEL_CACHE['id'] = model
    return model


def resolve_model_hint(api_key: Optional[str], hint: Optional[str] = None) -> str:
    """modelHint 解析：預設 sonnet（resolve_model）；'opus' 為 opt-in（更燒額度）。

    找不到 opus 時回退 sonnet，避免打到不存在的模型 id。
    """
    from datetime import date as _d
    if str(hint or '').strip().lower() != 'opus':
        return resolve_model(api_key)
    today = _d.today().strftime('%Y%m%d')
    if _OPUS_CACHE['date'] == today and _OPUS_CACHE['id']:
        return _OPUS_CACHE['id']
    if api_key:
        try:
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/models?limit=100',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01'},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            pick = next((m for m in (data.get('data') or [])
                         if m.get('id') and 'opus' in m['id'].lower()), None)
            if pick:
                _OPUS_CACHE['date'] = today
                _OPUS_CACHE['id'] = pick['id']
                return pick['id']
        except Exception as e:
            if log:
                log.warning('resolve_model_hint(opus): %s', e)
    return resolve_model(api_key)


def _headers(api_key: str) -> Dict[str, str]:
    return {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    }


def anthropic_messages(api_key: str, messages: List[Dict[str, Any]],
                       max_tokens: int = 1024, *, system: Optional[str] = None,
                       model: Optional[str] = None,
                       temperature: Optional[float] = None,
                       output_config: Optional[Dict[str, Any]] = None,
                       cache_system: bool = False,
                       timeout: float = 60) -> Tuple[str, Dict[str, Any]]:
    """回 (text, raw_json)。失敗 raise urllib.error.HTTPError / Exception。

    system / model / temperature 為選用（既有呼叫端不受影響）。
    output_config：結構化輸出（{'format': {'type': 'json_schema', 'schema': ...}}）與 effort。
    cache_system：把 system 包成帶 cache_control 的區塊（固定前綴才會命中快取）。
    注意：Sonnet 5／Opus 4.7 以後的模型拒收非預設 temperature（400），新呼叫端不要傳。
    """
    payload = build_messages_payload(messages, max_tokens, system=system, model=model or resolve_model(api_key),
                                     temperature=temperature, output_config=output_config,
                                     cache_system=cache_system)
    data = post_messages(api_key, payload, timeout=timeout)
    return message_text(data), data


def post_messages(api_key: str, payload: Dict[str, Any], timeout: float = 60) -> Dict[str, Any]:
    """POST /v1/messages（payload 由 build_messages_payload 產生）；回傳完整 message JSON。"""
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers=_headers(api_key),
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def build_messages_payload(messages: List[Dict[str, Any]], max_tokens: int, *,
                           model: str, system: Optional[str] = None,
                           temperature: Optional[float] = None,
                           output_config: Optional[Dict[str, Any]] = None,
                           cache_system: bool = False) -> Dict[str, Any]:
    """/v1/messages 請求本體；同步呼叫與 Message Batches 共用，確保兩條路徑參數一致。"""
    payload: Dict[str, Any] = {'model': model, 'max_tokens': max_tokens, 'messages': messages}
    if system:
        payload['system'] = ([{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}]
                             if cache_system else system)
    if temperature is not None:
        payload['temperature'] = temperature
    if output_config:
        payload['output_config'] = output_config
    return payload


def message_text(data: Dict[str, Any]) -> str:
    return ''.join(
        b.get('text', '') for b in (data or {}).get('content', []) if b.get('type') == 'text'
    ).strip()


# ── Message Batches（非即時工作；費用約同步呼叫一半）─────────────────
def _json_request(api_key: str, url: str, body: Optional[Dict[str, Any]] = None,
                  method: str = 'GET', timeout: float = 60) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8') if body is not None else None,
                                 headers=_headers(api_key), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def batch_create(api_key: str, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """requests: [{'custom_id': str, 'params': <messages payload>}]；回傳 batch 物件（含 id）。"""
    return _json_request(api_key, 'https://api.anthropic.com/v1/messages/batches',
                         {'requests': requests}, method='POST')


def batch_get(api_key: str, batch_id: str) -> Dict[str, Any]:
    return _json_request(api_key, 'https://api.anthropic.com/v1/messages/batches/'
                         + urllib.request.quote(batch_id, safe=''))


def batch_results(api_key: str, batch: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """讀取已結束 batch 的 JSONL 結果 → {custom_id: result}。結果順序不固定，一律以 custom_id 對應。"""
    url = batch.get('results_url')
    if not url:
        return {}
    req = urllib.request.Request(url, headers=_headers(api_key), method='GET')
    out: Dict[str, Dict[str, Any]] = {}
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp.read().decode('utf-8', 'replace').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get('custom_id'):
                out[row['custom_id']] = row.get('result') or {}
    return out
