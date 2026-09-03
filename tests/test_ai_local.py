#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import ai_local  # noqa: E402


class FakeStreamResponse:
    def __init__(self, *items):
        self.lines = []
        for item in items:
            if item == "[DONE]":
                self.lines.append(b"data: [DONE]\n")
            else:
                self.lines.append(("data: " + json.dumps(item) + "\n").encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def __iter__(self):
        return iter(self.lines)


class AiLocalPolicyTests(unittest.TestCase):
    def test_runtime_status_is_server_side_explicit_and_load_aware(self):
        with mock.patch.object(ai_local, "_lmstudio_models", return_value=[ai_local.FAST_MODEL]), \
             mock.patch.object(ai_local, "_resolve_hermes_exe", return_value=Path("hermes.exe")):
            status = ai_local.runtime_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["execution"], "server-side-on-EVO-T1")
        self.assertFalse(status["phoneInference"])
        fast = status["modes"]["fast"]
        deep = status["modes"]["deep"]
        self.assertEqual(fast["provider"], "LM Studio")
        self.assertEqual(fast["model"], "google/gemma-4-e4b")
        self.assertEqual(fast["dataBoundary"], "local-only")
        self.assertEqual(fast["maxOutputTokens"], ai_local.FAST_MAX_TOKENS)
        self.assertGreaterEqual(fast["maxOutputTokens"], 1400)
        self.assertGreaterEqual(fast["estimateSeconds"], 300)
        self.assertIn("模型載入", fast["estimateLabel"])
        self.assertEqual(deep["providerKey"], "hermes")
        self.assertEqual(deep["model"], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(deep["dataBoundary"], "external")
        self.assertGreaterEqual(deep["estimateSeconds"], 720)
        self.assertIn("Hermes 啟動", deep["estimateLabel"])
        self.assertIn("no shell/file/browser/message tools", deep["toolPolicy"])

    def test_fast_route_ignores_browser_model_and_trace_omits_content(self):
        prompt = "PRIVATE-PROMPT-DO-NOT-LOG"
        context = "PRIVATE-CONTEXT-DO-NOT-LOG"
        output = "PRIVATE-OUTPUT-DO-NOT-LOG"
        with tempfile.TemporaryDirectory() as temp_name:
            trace_path = Path(temp_name) / "trace.jsonl"
            with mock.patch.object(ai_local, "TRACE_PATH", trace_path), \
                 mock.patch.object(ai_local, "_lmstudio_models", return_value=[ai_local.FAST_MODEL]), \
                 mock.patch.object(ai_local, "_acquire_st_slot", return_value=(True, None)), \
                 mock.patch.object(ai_local, "_release_st_slot"), \
                 mock.patch.object(ai_local, "_stream_lmstudio", return_value=iter([output])) as stream:
                result = "".join(ai_local.chat_stream(
                    prompt, context, model="browser/attempted-override", request_id="fast-test",
                ))
            self.assertEqual(result, output)
            sent_prompt = stream.call_args.args[0]
            self.assertIn(prompt, sent_prompt)
            self.assertIn(context, sent_prompt)
            trace = trace_path.read_text(encoding="utf-8")
        self.assertIn('"requestId": "fast-test"', trace)
        self.assertIn('"model": "google/gemma-4-e4b"', trace)
        self.assertIn('"inputHash"', trace)
        self.assertNotIn(prompt, trace)
        self.assertNotIn(context, trace)
        self.assertNotIn(output, trace)
        self.assertNotIn("browser/attempted-override", trace)

    def test_lmstudio_stream_uses_budget_and_never_emits_reasoning(self):
        diagnostics = {}
        response = FakeStreamResponse(
            {
                "choices": [{
                    "delta": {"reasoning_content": "PRIVATE-REASONING-DO-NOT-EMIT"},
                    "finish_reason": None,
                }],
            },
            {"choices": [{"delta": {"content": "可見正文"}, "finish_reason": None}]},
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "completion_tokens": 1174,
                    "completion_tokens_details": {"reasoning_tokens": 780},
                },
            },
            "[DONE]",
        )
        with mock.patch.object(ai_local.urllib.request, "urlopen", return_value=response) as opened:
            result = "".join(ai_local._stream_lmstudio("prompt", diagnostics=diagnostics))
        request = opened.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, "可見正文")
        self.assertNotIn("PRIVATE-REASONING", result)
        self.assertEqual(payload["max_tokens"], ai_local.FAST_MAX_TOKENS)
        self.assertEqual(payload["stream_options"], {"include_usage": True})
        self.assertEqual(diagnostics["finishReason"], "stop")
        self.assertEqual(diagnostics["completionTokens"], 1174)
        self.assertEqual(diagnostics["reasoningTokens"], 780)

    def test_reasoning_only_length_fails_and_trace_never_marks_completed(self):
        response = FakeStreamResponse(
            {
                "choices": [{
                    "delta": {"reasoning_content": "PRIVATE-REASONING-DO-NOT-LOG"},
                    "finish_reason": None,
                }],
            },
            {
                "choices": [{"delta": {}, "finish_reason": "length"}],
                "usage": {
                    "completion_tokens": ai_local.FAST_MAX_TOKENS,
                    "completion_tokens_details": {"reasoning_tokens": ai_local.FAST_MAX_TOKENS - 3},
                },
            },
            "[DONE]",
        )
        with tempfile.TemporaryDirectory() as temp_name:
            trace_path = Path(temp_name) / "trace.jsonl"
            with mock.patch.object(ai_local, "TRACE_PATH", trace_path), \
                 mock.patch.object(ai_local, "_lmstudio_models", return_value=[ai_local.FAST_MODEL]), \
                 mock.patch.object(ai_local, "_acquire_st_slot", return_value=(True, None)), \
                 mock.patch.object(ai_local, "_release_st_slot"), \
                 mock.patch.object(ai_local.urllib.request, "urlopen", return_value=response):
                with self.assertRaisesRegex(ai_local.AiRuntimeError, "尚未產生可見正文"):
                    list(ai_local.chat_stream("分析", "資料", request_id="length-test"))
            trace = trace_path.read_text(encoding="utf-8")
        events = [json.loads(line)["event"] for line in trace.splitlines()]
        self.assertIn("started", events)
        self.assertIn("failed", events)
        self.assertNotIn("completed", events)
        self.assertIn('"finishReason": "length"', trace)
        self.assertIn('"outputChars": 0', trace)
        self.assertNotIn("PRIVATE-REASONING", trace)

    def test_empty_stop_and_partial_length_are_explicit_failures(self):
        empty = FakeStreamResponse(
            {"choices": [{"delta": {}, "finish_reason": "stop"}]}, "[DONE]",
        )
        with mock.patch.object(ai_local.urllib.request, "urlopen", return_value=empty):
            with self.assertRaisesRegex(ai_local.AiRuntimeError, "未回傳可見正文"):
                list(ai_local._stream_lmstudio("prompt"))

        partial = FakeStreamResponse(
            {"choices": [{"delta": {"content": "未完成正文"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
            "[DONE]",
        )
        with mock.patch.object(ai_local.urllib.request, "urlopen", return_value=partial):
            stream = ai_local._stream_lmstudio("prompt")
            self.assertEqual(next(stream), "未完成正文")
            with self.assertRaisesRegex(ai_local.AiRuntimeError, "內容可能不完整"):
                next(stream)

    def test_fast_output_budget_invalid_env_falls_back_and_clamps(self):
        with mock.patch.dict(ai_local.os.environ, {"TEST_AI_BUDGET": "invalid"}):
            self.assertEqual(ai_local._bounded_env_int("TEST_AI_BUDGET", 2048, 1400, 4096), 2048)
        with mock.patch.dict(ai_local.os.environ, {"TEST_AI_BUDGET": "100"}):
            self.assertEqual(ai_local._bounded_env_int("TEST_AI_BUDGET", 2048, 1400, 4096), 1400)
        with mock.patch.dict(ai_local.os.environ, {"TEST_AI_BUDGET": "9000"}):
            self.assertEqual(ai_local._bounded_env_int("TEST_AI_BUDGET", 2048, 1400, 4096), 4096)

    def test_hermes_command_is_bounded_and_has_no_mutating_toolsets(self):
        command = ai_local._hermes_command(Path("C:/Hermes/hermes.exe"))
        joined = " ".join(command)
        self.assertIn("chat --query-file -", joined)
        self.assertIn("--provider nvidia", joined)
        self.assertIn("--model nvidia/nemotron-3-super-120b-a12b", joined)
        self.assertIn("--toolsets todo", joined)
        self.assertIn("--max-turns 2", joined)
        self.assertIn("--ignore-rules", joined)
        self.assertNotIn("--yolo", command)
        for forbidden in ("terminal", "file", "browser", "message", "cron"):
            self.assertNotIn(forbidden, command)

    def test_deep_route_runs_one_stdin_turn_and_returns_text(self):
        class FakeProcess:
            returncode = 0
            supplied_input = ""

            def __init__(self, argv, **kwargs):
                self.argv = argv
                self.kwargs = kwargs

            def communicate(self, input=None, timeout=None):
                type(self).supplied_input = input or ""
                self.timeout = timeout
                return "深度研究結果", ""

            def kill(self):
                return None

        metadata = {
            "available": True,
            "provider": "Hermes Agent / nvidia",
            "model": ai_local.HERMES_MODEL,
            "dataBoundary": "external",
        }
        with tempfile.TemporaryDirectory() as temp_name:
            with mock.patch.object(ai_local, "TRACE_PATH", Path(temp_name) / "trace.jsonl"), \
                 mock.patch.object(ai_local, "route_metadata", return_value=metadata), \
                 mock.patch.object(ai_local, "_resolve_hermes_exe", return_value=Path("hermes.exe")), \
                 mock.patch.object(ai_local.subprocess, "Popen", FakeProcess):
                reply = "".join(ai_local.deep_stream("分析", "市場資料", request_id="deep-test"))
        self.assertEqual(reply, "深度研究結果")
        self.assertIn("市場資料", FakeProcess.supplied_input)


if __name__ == "__main__":
    unittest.main()
