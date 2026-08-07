#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_local.py — v5.0 本機 AI 副駕（預設整合 Ollama / LM Studio 本機推論服務）

將使用者問題 + 盤面/持倉資料，送至本機 Ollama / OpenAI 相容 API 進行推論。
完全本機、零雲端、零 API Key 洩漏風險，充分運用高階 GPU (RTX 5080) 與 RAM 資源。

依據資安規範：
  1. 優先使用本機端 Ollama 服務 (預設 http://localhost:11434)
  2. 推薦使用非中系開源高階模型 (如 Llama 3.3, Mistral NeMo)
"""
import json
import urllib.request
import urllib.error
from typing import Any, Dict, Generator, List, Optional

OLLAMA_BASE = 'http://localhost:11434'
LMSTUDIO_BASE = 'http://localhost:1234/v1'

# 首選本地模型端點（優先 Ollama）
CHAT_URL = LMSTUDIO_BASE + '/chat/completions'
MODELS_URL = LMSTUDIO_BASE + '/models'
OLLAMA_MODELS_URL = OLLAMA_BASE + '/api/tags'
OLLAMA_CHAT_URL = OLLAMA_BASE + '/api/chat'

SYSTEM = (
    '你是一位台股投資研究副駕,專精台股與台灣 AI 供應鏈(晶圓→封測→CPO→伺服器→散熱)。\n'
    '規則(嚴格遵守):\n'
    '1. 一律繁體中文,直白、有觀點、給可執行結論。\n'
    '2. 【資料紀律|最重要】只根據「下方提供的資料」回答。提供裡沒有的數字(股價/漲跌/'
    '法人/營收等)一律不可自行編造或臆測;沒有就明說「資料未提供」。\n'
    '3. 使用者是長線市場派,核心觀點:台灣 AI 供應鏈是結構主軸(TSMC 為核心、量能放大反映 '
    'CSP 資本支出集中台廠)。研判可納入此結構視角,但仍須以當下數據修正,並主動提示風險。\n'
    '4. 給的是研判與風險提醒,非投資建議。'
)


def list_models() -> Optional[List[str]]:
    """查詢本機 Ollama / LM Studio 已載入之可用模型清單。
    
    Returns:
        Optional[List[str]]: 模型名稱清單，若伺服器未啟用則傳回 None。
    """
    # 優先測試 Ollama 服務 API
    try:
        with urllib.request.urlopen(OLLAMA_MODELS_URL, timeout=3) as r:
            j = json.load(r)
        models = [m.get('name') for m in (j.get('models') or []) if m.get('name')]
        if models:
            return models
    except Exception:
        pass

    # 備選測試 LM Studio OpenAI 相容 API
    try:
        with urllib.request.urlopen(MODELS_URL, timeout=3) as r:
            j = json.load(r)
        return [m.get('id') for m in (j.get('data') or []) if m.get('id')]
    except Exception:
        return None


def chat(prompt: str, context: str = '', model: Optional[str] = None) -> Dict[str, Any]:
    """執行非串流本機 AI 邏輯推論。

    Args:
        prompt (str): 使用者提問或分析需求。
        context (str, optional): 盤面數據或持倉細節。 Defaults to ''.
        model (Optional[str], optional): 指定之本機 LLM 模型。 Defaults to None.

    Returns:
        Dict[str, Any]: 包含 'reply' 與 'model' 或 'error' 的字典物件。
    """
    if not prompt:
        return {'error': '問題是空的'}
    if not model:
        ms = list_models()
        model = ms[0] if ms else 'llama3.3'
    sys_content = SYSTEM + (('\n\n【目前提供的資料】\n' + context) if context else
                            '\n\n(本次未附帶盤面資料,只能就一般原則回答。)')
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': sys_content},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.4,
        'stream': False,
    }
    req = urllib.request.Request(
        CHAT_URL, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            j = json.load(r)
        choices = j.get('choices') or []
        reply = (choices[0].get('message', {}).get('content', '').strip()) if choices else ''
        return {'reply': reply, 'model': j.get('model') or model}
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')
        except Exception:
            pass
        return {'error': f'AI HTTP {e.code}: {body[:300]}'}
    except urllib.error.URLError as e:
        return {'error': f'本機 AI 服務連線失敗 — 請確認已啟動 Ollama (localhost:11434) 或 LM Studio (localhost:1234)。詳情: {e}'}
    except Exception as e:
        return {'error': f'AI 推論失敗: {e}'}


def chat_stream(prompt: str, context: str = '', model: Optional[str] = None) -> Generator[str, None, None]:
    """串流版本機推論：逐段 yield 文字（支援 Ollama 與 LM Studio SSE）。

    Args:
        prompt (str): 使用者輸入的問題或指令。
        context (str): 盤面數據或持倉脈動脈絡字串。
        model (Optional[str]): 指定之模型名稱，預設自動偵測。

    Yields:
        Generator[str, None, None]: 逐段推論結果文字塊。
    """
    if not prompt:
        yield '⚠ 問題是空的'
        return

    ms = list_models()
    if not model:
        model = ms[0] if ms else 'llama3.3'

    sys_content = SYSTEM + (('\n\n【目前提供的資料】\n' + context) if context else '\n\n(本次未附帶盤面資料,只能就一般原則回答。)')
    
    # 判斷是否為 Ollama 原生 API
    is_ollama = False
    try:
        req_check = urllib.request.Request(OLLAMA_MODELS_URL)
        with urllib.request.urlopen(req_check, timeout=2) as r:
            if r.status == 200:
                is_ollama = True
    except Exception:
        is_ollama = False

    target_url = OLLAMA_CHAT_URL if is_ollama else CHAT_URL
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': sys_content},
            {'role': 'user', 'content': prompt},
        ],
        'options': {'temperature': 0.4} if is_ollama else None,
        'temperature': 0.4 if not is_ollama else None,
        'stream': True,
    }
    # 移除 None 鍵值
    payload = {k: v for k, v in payload.items() if v is not None}

    req = urllib.request.Request(
        target_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )

    try:
        resp = urllib.request.urlopen(req, timeout=600)
    except urllib.error.URLError as e:
        yield f'⚠ 本機 AI 服務連線失敗 (請確認 Ollama localhost:11434 或 LM Studio localhost:1234 已啟動): {e}'
        return
    except Exception as e:
        yield f'⚠ AI 服務異常: {e}'
        return

    try:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            if is_ollama:
                try:
                    j = json.loads(line)
                    chunk = (j.get('message') or {}).get('content')
                    if chunk:
                        yield chunk
                    if j.get('done'):
                        break
                except Exception:
                    continue
            else:
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                try:
                    j = json.loads(data)
                    delta = ((j.get('choices') or [{}])[0].get('delta') or {}).get('content')
                    if delta:
                        yield delta
                except Exception:
                    continue
    except Exception as e:
        yield f'\n⚠ 串流中斷: {e}'
