# -*- coding: utf-8 -*-
"""AI HTTP handlers mixin（H2 續拆 server.py）"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import ai_api
from http_boundary import BodyReadError, read_body, read_json_body


class AiRoutesMixin:
    def _handle_ai_key_status(self):
        self._ok(json.dumps({'set': bool(ai_api.load_ai_key())}).encode())

    def _handle_ai_key_set(self):
        try:
            body = read_json_body(self, max_bytes=16 * 1024)
        except BodyReadError as e:
            self._err(str(e), e.status); return
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
            raw = read_body(self, max_bytes=2 * 1024 * 1024) or b'{}'
        except BodyReadError as e:
            self._err(str(e), e.status); return
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

    def _stream_ai_runtime(self, mode: str):
        try:
            body = read_json_body(self, max_bytes=256 * 1024)
        except BodyReadError as e:
            self._err(str(e), e.status); return
        # ai_local 由 server 主模組注入到 mixin 可用名稱
        al = getattr(self, '_ai_local_mod', None)
        try:
            import ai_local as al_mod
            al = al_mod
        except Exception:
            pass
        if not al:
            self._err('ai_local 模組未載入', 500); return
        request_id = self._ensure_trace_id()
        try:
            metadata = al.route_metadata(mode, probe=(mode == 'fast'))
        except Exception as exc:
            self._err('AI runtime 狀態讀取失敗: ' + type(exc).__name__, 503); return
        if not metadata.get('available'):
            self._err(str(metadata.get('reason') or 'AI runtime 未就緒'), 503); return
        try:
            al.trace_event(
                'http_request_received', request_id=request_id, mode=mode,
                provider=metadata.get('provider'), model=metadata.get('model'),
                dataBoundary=metadata.get('dataBoundary'), phase='request-received',
                inputChars=len(str(body.get('prompt') or '')) + len(str(body.get('context') or '')),
            )
        except Exception:
            pass
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('X-ST-AI-Request-ID', request_id)
        self.send_header('X-ST-AI-Mode', str(metadata.get('mode') or mode))
        self.send_header('X-ST-AI-Host', str(metadata.get('host') or 'EVO-T1'))
        self.send_header('X-ST-AI-Provider', str(metadata.get('provider') or 'unknown'))
        self.send_header('X-ST-AI-Model', str(metadata.get('model') or 'unknown'))
        self.send_header('X-ST-AI-Data-Boundary', str(metadata.get('dataBoundary') or 'unknown'))
        self.send_header('X-ST-AI-Estimate-Seconds', str(int(metadata.get('estimateSeconds') or 0)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            import wavedeck_bus as wdb
            wdb.record_st_local(1)
        except Exception:
            pass
        started = time.monotonic()
        iterator = None
        output_chars = 0
        try:
            if mode == 'deep':
                iterator = al.deep_stream(
                    body.get('prompt', ''), body.get('context', ''), request_id=request_id,
                )
            else:
                iterator = al.chat_stream(
                    body.get('prompt', ''), body.get('context', ''), request_id=request_id,
                )
            for chunk in iterator:
                output_chars += len(chunk)
                self.wfile.write(chunk.encode('utf-8'))
                self.wfile.flush()
            al.trace_event(
                'http_stream_completed', request_id=request_id, mode=mode,
                provider=metadata.get('provider'), model=metadata.get('model'),
                dataBoundary=metadata.get('dataBoundary'), phase='response-complete',
                elapsedMs=round((time.monotonic() - started) * 1000), outputChars=output_chars,
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as exc:
            al.trace_event(
                'client_disconnected', request_id=request_id, mode=mode,
                provider=metadata.get('provider'), model=metadata.get('model'),
                dataBoundary=metadata.get('dataBoundary'), phase='response-stream',
                elapsedMs=round((time.monotonic() - started) * 1000), errorType=type(exc).__name__,
            )
        except Exception as exc:
            message = str(exc) if isinstance(exc, getattr(al, 'AiRuntimeError', RuntimeError)) else type(exc).__name__
            try:
                self.wfile.write(('\n⚠ ' + message).encode('utf-8'))
                self.wfile.flush()
            except (OSError, ValueError):
                pass
            al.trace_event(
                'http_stream_failed', request_id=request_id, mode=mode,
                provider=metadata.get('provider'), model=metadata.get('model'),
                dataBoundary=metadata.get('dataBoundary'), phase='response-stream',
                elapsedMs=round((time.monotonic() - started) * 1000), errorType=type(exc).__name__,
            )
        finally:
            if iterator is not None and hasattr(iterator, 'close'):
                try:
                    iterator.close()
                except Exception:
                    pass

    def _handle_ai_local(self):
        self._stream_ai_runtime('fast')

    def _handle_ai_deep(self):
        self._stream_ai_runtime('deep')

    def _handle_ai_local_status(self):
        try:
            import ai_local as al
            payload = al.runtime_status()
        except Exception as exc:
            payload = {'ok': False, 'error': 'AI runtime status: ' + type(exc).__name__, 'modes': {}}
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

    def _handle_ai_report(self):
        try:
            body = read_json_body(self, max_bytes=512 * 1024)
        except BodyReadError as e:
            self._err(str(e), e.status); return
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
            try:
                import wavedeck_bus as wdb
                wdb.record_st_cloud(usd=0.04, calls=1)
            except Exception:
                pass
            self._ok(json.dumps({'ok': True, 'report': text, 'model': data.get('model')}).encode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', 'replace')
            self._err(f'Anthropic API HTTP {e.code}: {err_body[:500]}', 502)
        except Exception as e:
            self._err('AI report failed: ' + str(e), 500)

    # ── 盤後敘事日報（postmarket-daily）────────────────────────────────
    # 紅線見 docs/POSTMARKET_DAILY.md：雲端 Claude only、不 fallback 本機 deep、
    # 不 mutate ST 狀態、DecisionContext 只當唯讀證據。

    def _send_ai_json(self, status, payload, headers=None):
        """帶 X-ST-AI-Request-ID（與 /ai/local 對齊）與額外 header 的 JSON 回覆。"""
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(int(status))
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-ST-AI-Request-ID', self._ensure_trace_id())
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def _handle_ai_postmarket_daily(self):
        key = ai_api.load_ai_key()
        if not key:
            # 與 /ai-proxy 相同拒絕行為（reader 遠端則由 private_web_gateway 擋 403）
            self._err('AI key not set on server', 400); return
        try:
            body = read_json_body(self, max_bytes=64 * 1024)
        except BodyReadError as e:
            self._err(str(e), e.status); return
        self._ensure_trace_id()
        try:
            import postmarket_report as pr
            result = pr.generate_report(body, api_key=key)
        except Exception as e:
            self._err('postmarket-daily failed: ' + type(e).__name__, 500); return
        self._send_ai_json(result['status'], result['payload'], result.get('headers'))

    def _handle_ai_postmarket_abort(self):
        try:
            body = read_json_body(self, max_bytes=4 * 1024)
        except BodyReadError as e:
            self._err(str(e), e.status); return
        cid = str(body.get('abortSignalClientId') or body.get('clientId') or '').strip()
        if not cid:
            self._err('abortSignalClientId required', 400); return
        try:
            import postmarket_report as pr
            pr.signal_abort(cid)
        except Exception as e:
            self._err('postmarket abort failed: ' + type(e).__name__, 500); return
        self._send_ai_json(200, {'ok': True, 'aborted': cid})

    def _handle_ai_postmarket_latest(self):
        try:
            import postmarket_report as pr
            day = pr.load_latest_report()
        except Exception as e:
            self._err('postmarket latest failed: ' + type(e).__name__, 500); return
        if not day:
            self._ok(json.dumps({'ok': False, 'reason': 'no_report'}).encode()); return
        self._ok(json.dumps(day, ensure_ascii=False).encode())

    def _handle_ai_note(self):
        try:
            body = read_json_body(self, max_bytes=64 * 1024)
        except BodyReadError as e:
            self._err(str(e), e.status); return
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
            try:
                import wavedeck_bus as wdb
                wdb.record_st_cloud(usd=0.02, calls=1)
            except Exception:
                pass
            self._ok(json.dumps({'ok': True, 'text': text}, ensure_ascii=False).encode())
        except urllib.error.HTTPError as e:
            self._err(f'Anthropic HTTP {e.code}: ' + e.read().decode('utf-8', 'replace')[:300], 502)
        except Exception as e:
            self._err('ai-note failed: ' + str(e), 500)
