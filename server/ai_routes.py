# -*- coding: utf-8 -*-
"""AI HTTP handlers mixin（H2 續拆 server.py）"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error

import ai_api
from http_boundary import BodyReadError, read_json_body


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
        structured = 'text/event-stream' in (self.headers.get('Accept') or '')

        def emit(event, **fields):
            raw = json.dumps({'type': event, **fields}, ensure_ascii=False)
            self.wfile.write(('data: ' + raw + '\n\n').encode('utf-8'))
            self.wfile.flush()
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
        self.send_header('Content-Type', ('text/event-stream' if structured else 'text/plain') + '; charset=utf-8')
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
        cancelled = threading.Event()
        pending = queue.Queue(maxsize=16)

        def enqueue(kind, value=None):
            while not cancelled.is_set():
                try:
                    pending.put((kind, value), timeout=0.1)
                    return
                except queue.Full:
                    continue

        def produce():
            iterator = None
            try:
                stream = al.deep_stream if mode == 'deep' else al.chat_stream
                iterator = stream(body.get('prompt', ''), body.get('context', ''),
                                  request_id=request_id, cancel_event=cancelled)
                visible = False
                for chunk in iterator:
                    if cancelled.is_set():
                        return
                    if not isinstance(chunk, str):
                        raise al.AiRuntimeError('AI 回覆格式無效')
                    visible = visible or bool(chunk.strip())
                    enqueue('delta', chunk)
                if not visible:
                    raise al.AiRuntimeError('AI 未回傳可見正文；請重試。')
                enqueue('done')
            except Exception as exc:
                enqueue('error', exc)
            finally:
                if iterator is not None and hasattr(iterator, 'close'):
                    iterator.close()

        # 僅工作執行緒操作模型生成器；斷線時用事件通知，避免跨執行緒 close 競態。
        worker = threading.Thread(target=produce, name='st-ai-http-stream', daemon=True)
        worker.start()
        output_chars = 0
        try:
            while True:
                try:
                    kind, chunk = pending.get(timeout=1.0)
                except queue.Empty:
                    if structured:
                        # 上游尚未給正文時也能偵測使用者取消／gateway 斷線。
                        self.wfile.write(b': keep-alive\n\n')
                        self.wfile.flush()
                    continue
                if kind == 'error':
                    raise chunk
                if kind == 'done':
                    if structured:
                        emit('done')
                    break
                output_chars += len(chunk)
                if structured:
                    emit('delta', text=chunk)
                else:
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
                if structured:
                    emit('error', message=message)
                else:
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
            cancelled.set()
            # 不提前釋放模型鎖；runtime 工作真正退出時才負責釋放。
            worker.join(timeout=0.5)

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
            # 與其他 AI 端點相同拒絕行為（reader 遠端則由 private_web_gateway 擋 403）
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
