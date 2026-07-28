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
    import slog
    log = slog.get_logger('ai_api')
except Exception:
    log = None

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)

_AI_KEY_FILE = os.path.join(_BASE, 'data', 'ai_key.txt')
_ai_key_lock = threading.Lock()

_MODEL_CACHE = {'date': '', 'id': 'claude-sonnet-4-6'}


def load_ai_key() -> str:
    try:
        with open(_AI_KEY_FILE, encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''


def save_ai_key(k: str) -> None:
    with _ai_key_lock:
        with open(_AI_KEY_FILE, 'w', encoding='utf-8') as f:
            f.write((k or '').strip())


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


def anthropic_messages(api_key: str, messages: List[Dict[str, Any]],
                       max_tokens: int = 1024) -> Tuple[str, Dict[str, Any]]:
    """回 (text, raw_json)。失敗 raise urllib.error.HTTPError / Exception。"""
    req_body = json.dumps({
        'model': resolve_model(api_key),
        'max_tokens': max_tokens,
        'messages': messages,
    }).encode('utf-8')
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
