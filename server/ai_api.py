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

_MODEL_CACHE = {'date': '', 'id': 'claude-sonnet-4-6'}
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
    model = 'claude-sonnet-4-6'
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


def anthropic_messages(api_key: str, messages: List[Dict[str, Any]],
                       max_tokens: int = 1024, *, system: Optional[str] = None,
                       model: Optional[str] = None,
                       temperature: Optional[float] = None) -> Tuple[str, Dict[str, Any]]:
    """回 (text, raw_json)。失敗 raise urllib.error.HTTPError / Exception。

    system / model / temperature 為選用（既有呼叫端不受影響）。
    """
    payload: Dict[str, Any] = {
        'model': model or resolve_model(api_key),
        'max_tokens': max_tokens,
        'messages': messages,
    }
    if system:
        payload['system'] = system
    if temperature is not None:
        payload['temperature'] = temperature
    req_body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=req_body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    text = ''.join(
        b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text'
    )
    return text.strip(), data
