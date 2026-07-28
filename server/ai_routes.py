# -*- coding: utf-8 -*-
"""AI HTTP handlers mixin（H2 續拆 server.py）"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import ai_api


class AiRoutesMixin:
    def _handle_ai_key_status(self):
        self._ok(json.dumps({'set': bool(ai_api.load_ai_key())}).encode())

    def _handle_ai_key_set(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(n) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        if body.get('clear'):
            ai_api.save_ai_key('')
            self._ok(b'{"ok":true,"cleared":true}'); return
        k = (body.get('key') or '').strip()
        if not k.startswith('sk-'):
            self._err('invalid key (need sk-...)', 400); return
        ai_api.save_ai_key(k)
        self._ok(b'{"ok":true}')

    def _handle_ai_model(self):
        self._ok(json.dumps({'model': ai_api.resolve_model(ai_api.load_ai_key())}).encode())

    def _handle_ai_proxy(self):
        key = ai_api.load_ai_key()
        if not key:
            self._err('AI key not set on server', 400); return
        try:
            n = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(n) or b'{}'
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        try:
            up = urllib.request.Request(
                'https://api.anthropic.com/v1/messages', data=raw,
                headers={
                    'Content-Type': 'application/json', 'x-api-key': key,
                    'anthropic-version': '2023-06-01',
                }, method='POST',
            )
            resp = urllib.request.urlopen(up, timeout=180)
        except urllib.error.HTTPError as e:
            self._err('Anthropic %d: %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]), 502); return
        except Exception as e:
            self._err('ai-proxy failed: ' + str(e), 502); return
        try:
            self.send_response(200)
            self.send_header('Content-Type', resp.headers.get('Content-Type', 'text/event-stream'))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            while True:
                chunk = resp.read(2048)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception:
            pass

    def _handle_ai_local(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        # ai_local 由 server 主模組注入到 mixin 可用名稱
        al = getattr(self, '_ai_local_mod', None)
        try:
            import ai_local as al_mod
            al = al_mod
        except Exception:
            pass
        if not al:
            self._err('ai_local 模組未載入', 500); return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            for chunk in al.chat_stream(body.get('prompt', ''), body.get('context', ''), body.get('model')):
                self.wfile.write(chunk.encode('utf-8'))
                self.wfile.flush()
        except Exception:
            pass

    def _handle_ai_local_status(self):
        try:
            import ai_local as al
            models = al.list_models()
        except Exception:
            models = None
        self._ok(json.dumps({'ok': models is not None, 'models': models or []}, ensure_ascii=False).encode())

    def _handle_ai_report(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        api_key = body.get('apiKey', '').strip() or ai_api.load_ai_key()
        if not api_key:
            self._err('apiKey required (use sk-ant-...)', 400); return
        positions = body.get('positions') or {}
        watches = body.get('watches') or {}
        market = body.get('marketSym') or '^TWII'
        pos_lines = []
        for code, p in positions.items():
            pos_lines.append(
                f"  - {code}: 進場 {p.get('entry')}、{p.get('shares')} 股、"
                f"停利 {p.get('target') or '無'}、停損 {p.get('stop') or '無'}、現價 {p.get('lastPrice') or '?'}"
            )
        watch_lines = []
        for code, w in watches.items():
            sigs = w.get('signals', []) if isinstance(w, dict) else []
            triggered = [s for s in sigs if s.get('lastEval', {}).get('status') == 'trigger']
            watch_lines.append(f"  - {code}: {len(sigs)} 訊號、{len(triggered)} 觸發")
        prompt = (
            f'你是專業台股研究分析師。請為這個人撰寫今日盤前簡報。\n\n'
            f'# 持倉清單\n' + ('\n'.join(pos_lines) if pos_lines else '  (無)') + '\n\n'
            f'# 觀察清單\n' + ('\n'.join(watch_lines) if watch_lines else '  (無)') + '\n\n'
            f'請輸出 Markdown 格式報告，含：\n'
            f'1. 📊 大盤總結（基於昨日 {market} 表現）\n'
            f'2. 💼 持倉檢視（每檔含表現、注意事項、行動建議）\n'
            f'3. 👁 觀察清單重點（觸發訊號分析）\n'
            f'4. 🎯 今日 3 大重點\n\n'
            f'語言：繁體中文、口語化、有觀點。長度約 500~800 字。\n\n'
            f'【重要】股票一律以「代號」為準（上面清單給的就是正確代號）。'
            f'提到公司名稱時務必與代號正確對應；若你不百分之百確定某代號對應的公司名稱，'
            f'就只用代號稱呼，嚴禁臆測或填入可能錯誤的名稱（例如不可把 2408 寫成旺宏）。'
        )
        try:
            text, data = ai_api.anthropic_messages(
                api_key, [{'role': 'user', 'content': prompt}], max_tokens=2048,
            )
            self._ok(json.dumps({'ok': True, 'report': text, 'model': data.get('model')}).encode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', 'replace')
            self._err(f'Anthropic API HTTP {e.code}: {err_body[:500]}', 502)
        except Exception as e:
            self._err('AI report failed: ' + str(e), 500)

    def _handle_ai_note(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        api_key = (body.get('apiKey') or '').strip() or ai_api.load_ai_key()
        prompt = (body.get('prompt') or '').strip()
        if not api_key:
            self._err('apiKey required', 400); return
        if not prompt:
            self._err('prompt required', 400); return
        mt = int(body.get('max_tokens') or 500)
        try:
            text, _ = ai_api.anthropic_messages(
                api_key, [{'role': 'user', 'content': prompt}],
                max_tokens=max(64, min(1500, mt)),
            )
            self._ok(json.dumps({'ok': True, 'text': text}, ensure_ascii=False).encode())
        except urllib.error.HTTPError as e:
            self._err(f'Anthropic HTTP {e.code}: ' + e.read().decode('utf-8', 'replace')[:300], 502)
        except Exception as e:
            self._err('ai-note failed: ' + str(e), 500)
