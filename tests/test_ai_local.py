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
