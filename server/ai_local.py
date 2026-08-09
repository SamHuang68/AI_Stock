#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_local.py — v4.0 本機 AI 副駕(接 LM Studio,純 stdlib)

把使用者問題 + 提供的盤面/持倉資料,丟給本機 LM Studio 的 OpenAI 相容 server 回答。
完全本機、零雲端、零 API 成本,吃 GPU(RTX 5080)。

前置(LM Studio):
  1. 安裝 LM Studio:https://lmstudio.ai
  2. 在 LM Studio 的「Discover/搜尋」下載一個模型(繁中佳,例:Qwen2.5 7B Instruct)。
  3. 到「Developer / Local Server」分頁 → 載入模型 → Start Server(預設埠 1234)。
     啟用後會在 http://localhost:1234/v1 提供 OpenAI 相容 API。
"""
import json
import os
import urllib.request
import urllib.error

# 可與 WD Ollama(:11434) 隔離：ST 預設 LM Studio :1234
LMSTUDIO_BASE = (os.environ.get('AI_LOCAL_BASE') or os.environ.get('ST_LLM_BASE')
                 or 'http://localhost:1234/v1').rstrip('/')
CHAT_URL = LMSTUDIO_BASE + '/chat/completions'
MODELS_URL = LMSTUDIO_BASE + '/models'

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


def list_models():
    """回傳 LM Studio 目前已載入/可用的模型 id 清單;server 沒開則回 None。"""
    try:
        with urllib.request.urlopen(MODELS_URL, timeout=5) as r:
            j = json.load(r)
        return [m.get('id') for m in (j.get('data') or []) if m.get('id')]
    except Exception:
        return None


def _acquire_st_slot():
    """ST 摘要讓 WD 優先；WD 佔用時短暫等待後 defer。"""
    try:
        import llm_gate as lg
        if lg.wd_busy():
            # 再等一下
            if not lg.wait_or_defer('st', wait_sec=2.0, ttl_sec=180):
                return False, '〔WD 微觀推論優先中，ST 摘要稍後再試〕'
            return True, None
        if not lg.acquire('st', ttl_sec=180):
            return False, '〔本機 LLM 忙碌，請稍後再試〕'
        return True, None
    except Exception:
        return True, None


def _release_st_slot():
    try:
        import llm_gate as lg
        lg.release('st')
    except Exception:
        pass


def chat(prompt, context='', model=None):
    """prompt:使用者問題;context:前端整理的盤面/持倉資料字串。"""
    if not prompt:
        return {'error': '問題是空的'}
    ok, defer = _acquire_st_slot()
    if not ok:
        return {'error': defer or 'LLM busy', 'deferred': True}
    try:
        if not model:                       # 沒指定就用 LM Studio 目前載入的模型
            ms = list_models()
            model = ms[0] if ms else 'local-model'
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
            return {'error': f'LM Studio HTTP {e.code}: {body[:300]}'}
        except urllib.error.URLError as e:
            return {'error': 'LM Studio 連線失敗 — 請確認已安裝 LM Studio(https://lmstudio.ai)、'
                             '在 Developer/Local Server 分頁載入模型並 Start Server。'
                             f' base={LMSTUDIO_BASE} 詳情:' + str(e)}
        except Exception as e:
            return {'error': 'AI 失敗:' + str(e)}
    finally:
        _release_st_slot()


def chat_stream(prompt, context='', model=None):
    """串流版:逐段 yield 文字(LM Studio SSE)。連線/錯誤也以文字 yield 出去。"""
    if not prompt:
        yield '⚠ 問題是空的'; return
    ok, defer = _acquire_st_slot()
    if not ok:
        yield defer or '〔本機 LLM 忙碌〕'; return
    try:
        if not model:
            ms = list_models()
            model = ms[0] if ms else 'local-model'
        sys_content = SYSTEM + (('\n\n【目前提供的資料】\n' + context) if context else
                                '\n\n(本次未附帶盤面資料,只能就一般原則回答。)')
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': sys_content},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.4,
            'stream': True,
        }
        req = urllib.request.Request(
            CHAT_URL, data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.URLError as e:
            yield '⚠ LM Studio 連線失敗(請確認已 Start Server):' + str(e); return
        except Exception as e:
            yield '⚠ AI 失敗:' + str(e); return
        try:
            for raw in resp:
                line = raw.decode('utf-8', 'replace').strip()
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
            yield '\n⚠ 串流中斷:' + str(e)
    finally:
        _release_st_slot()
