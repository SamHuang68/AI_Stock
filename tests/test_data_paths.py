"""server/data_paths.py（單一資料根階段 2 的解析器）的單元測試。

要證明的是：解析器是純函式、legacy 路徑與原本的 os.path.join 完全相同、覆寫語意沿用既有模組、
而且任何外置資料根設定都會被拒絕而不是靜默退回 legacy。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import data_paths as dp  # noqa: E402

BASE = os.path.join(tempfile.gettempdir(), 'st-data-paths-root')   # 不必存在：解析器不碰檔案系統


class LegacyResolution(unittest.TestCase):
    def test_data_and_log_paths_equal_the_old_os_path_join(self):
        self.assertEqual(str(dp.data_root(code_root=BASE)), os.path.join(BASE, 'data'))
        self.assertEqual(str(dp.data_path(code_root=BASE)), os.path.join(BASE, 'data'))
        self.assertEqual(str(dp.data_path('a.json', code_root=BASE)), os.path.join(BASE, 'data', 'a.json'))
        self.assertEqual(str(dp.data_path('x/y/z.db', code_root=BASE)), os.path.join(BASE, 'data', 'x', 'y', 'z.db'))
        self.assertEqual(str(dp.data_path('x\\y.db', code_root=BASE)), os.path.join(BASE, 'data', 'x', 'y.db'))
        self.assertEqual(str(dp.log_path(code_root=BASE)), os.path.join(BASE, 'logs'))
        self.assertEqual(str(dp.log_path('t.jsonl', code_root=BASE)), os.path.join(BASE, 'logs', 't.jsonl'))
        self.assertEqual(str(dp.log_path('alerts', code_root=BASE)), os.path.join(BASE, 'logs', 'alerts'))

    def test_results_are_path_objects_and_binding_describes_legacy(self):
        self.assertIsInstance(dp.data_path('a', code_root=BASE), Path)
        self.assertIsInstance(dp.log_path('a', code_root=BASE), Path)
        self.assertIsInstance(dp.data_root(code_root=BASE), Path)
        binding = dp.binding_for(code_root=BASE)
        self.assertEqual(binding.mode, 'legacy')
        self.assertEqual(binding.code_root, Path(BASE))
        self.assertEqual(binding.data_root, Path(BASE) / 'data')

    def test_code_root_is_used_verbatim_not_resolved_or_made_absolute(self):
        relative = 'rel' + os.sep + 'root'
        self.assertEqual(str(dp.data_path('a', code_root=relative)), os.path.join(relative, 'data', 'a'))
        self.assertFalse(dp.data_path('a', code_root=relative).is_absolute())
        self.assertEqual(dp.data_root(code_root=Path(BASE)), dp.data_root(code_root=BASE))

    def test_invalid_code_root_is_rejected(self):
        for bad in (None, '', '   ', 5, b'bytes'):
            with self.subTest(bad=bad), self.assertRaises(dp.BindingError):
                dp.data_root(code_root=bad)

    def test_never_touches_the_filesystem(self):
        def boom(*args, **kwargs):
            raise AssertionError('data_paths 不得存取檔案系統')
        missing = os.path.join(BASE, 'does', 'not', 'exist')
        with mock.patch.object(os, 'stat', boom), mock.patch.object(os, 'lstat', boom), \
                mock.patch.object(os, 'scandir', boom), mock.patch.object(os, 'makedirs', boom), \
                mock.patch('builtins.open', boom):
            self.assertEqual(str(dp.data_path('a/b.db', code_root=missing)), os.path.join(missing, 'data', 'a', 'b.db'))
            self.assertEqual(str(dp.log_path('t', code_root=missing)), os.path.join(missing, 'logs', 't'))
        self.assertFalse(os.path.exists(missing))


class RelativePathValidation(unittest.TestCase):
    def test_traversal_absolute_and_special_forms_are_rejected(self):
        for bad in ('..', '../x', 'a/../b', 'a/./b', '/abs', 'C:/x', 'C:x', 'a:b', 'x\x00y', '\\\\server\\share', 'a/..'):
            with self.subTest(bad=bad):
                with self.assertRaises(dp.BindingError):
                    dp.data_path(bad, code_root=BASE)
                with self.assertRaises(dp.BindingError):
                    dp.log_path(bad, code_root=BASE)

    def test_nested_and_unicode_names_are_accepted(self):
        self.assertEqual(dp.data_path('個股/研究.json', code_root=BASE), Path(BASE) / 'data' / '個股' / '研究.json')
        self.assertEqual(dp.data_path('a b/c-d_e.f', code_root=BASE), Path(BASE) / 'data' / 'a b' / 'c-d_e.f')


class OverrideSemantics(unittest.TestCase):
    """沿用各模組原本的 ``Path(env or 預設)`` ／ ``db_path or env or 預設`` 語意。"""

    def test_explicit_override_wins_over_environment_and_default(self):
        env = {'LLM_GATE_PATH': 'from-env.json'}
        got = dp.data_path('llm_gate.json', code_root=BASE, override='explicit.json',
                           override_env='LLM_GATE_PATH', environ=env)
        self.assertEqual(got, Path('explicit.json'))

    def test_environment_override_is_used_when_no_explicit_value(self):
        env = {'LLM_GATE_PATH': 'from-env.json'}
        got = dp.data_path('llm_gate.json', code_root=BASE, override_env='LLM_GATE_PATH', environ=env)
        self.assertEqual(got, Path('from-env.json'))

    def test_override_is_returned_verbatim_without_expansion_or_absolutizing(self):
        for value in ('rel/x.json', '~/x.json', os.path.join(BASE, 'abs.json')):
            with self.subTest(value=value):
                got = dp.data_path('a', code_root=BASE, override=value)
                self.assertEqual(got, Path(value))
                self.assertEqual(got.is_absolute(), Path(value).is_absolute())

    def test_empty_values_fall_back_to_the_default(self):
        default = Path(BASE) / 'data' / 'llm_gate.json'
        self.assertEqual(dp.data_path('llm_gate.json', code_root=BASE, override='', environ={}), default)
        self.assertEqual(dp.data_path('llm_gate.json', code_root=BASE, override_env='LLM_GATE_PATH',
                                      environ={'LLM_GATE_PATH': ''}), default)
        self.assertEqual(dp.data_path('llm_gate.json', code_root=BASE, override_env='LLM_GATE_PATH',
                                      environ={}), default)

    def test_log_path_supports_the_same_override_rules(self):
        env = {'ST_AI_TRACE_PATH': 'trace-env.jsonl'}
        self.assertEqual(dp.log_path('t.jsonl', code_root=BASE, override_env='ST_AI_TRACE_PATH', environ=env),
                         Path('trace-env.jsonl'))
        self.assertEqual(dp.log_path('t.jsonl', code_root=BASE, override_env='ST_AI_TRACE_PATH', environ={}),
                         Path(BASE) / 'logs' / 't.jsonl')

    def test_only_registered_override_variables_are_accepted(self):
        with self.assertRaises(dp.BindingError):
            dp.data_path('a', code_root=BASE, override_env='SOME_OTHER_PATH', environ={'SOME_OTHER_PATH': 'x'})
        for name in dp.OVERRIDE_ENV:
            with self.subTest(name=name):
                self.assertEqual(dp.data_path('a', code_root=BASE, override_env=name, environ={name: 'x'}), Path('x'))

    def test_process_environment_is_read_only_when_no_mapping_is_given(self):
        with mock.patch.dict(os.environ, {'LLM_GATE_PATH': 'process-env.json'}):
            self.assertEqual(dp.data_path('llm_gate.json', code_root=BASE, override_env='LLM_GATE_PATH'),
                             Path('process-env.json'))
            self.assertEqual(dp.data_path('llm_gate.json', code_root=BASE, override_env='LLM_GATE_PATH', environ={}),
                             Path(BASE) / 'data' / 'llm_gate.json')

    def test_resolution_is_not_cached_between_calls(self):
        env = {}
        first = dp.data_path('a', code_root=BASE, override_env='ST_REPORTS_DIR', environ=env)
        env['ST_REPORTS_DIR'] = 'changed'
        self.assertNotEqual(dp.data_path('a', code_root=BASE, override_env='ST_REPORTS_DIR', environ=env), first)


class ExternalBindingIsRefused(unittest.TestCase):
    """外置資料根尚未啟用：任何綁定設定都必須拒絕，不能靜默退回 legacy 去開另一份資料。"""

    def test_each_binding_variable_is_refused_by_every_entry_point(self):
        for name in dp.BINDING_ENV:
            env = {name: 'anything'}
            for label, call in (
                ('binding_for', lambda e=env: dp.binding_for(code_root=BASE, environ=e)),
                ('data_root', lambda e=env: dp.data_root(code_root=BASE, environ=e)),
                ('data_path', lambda e=env: dp.data_path('a', code_root=BASE, environ=e)),
                ('log_path', lambda e=env: dp.log_path('a', code_root=BASE, environ=e)),
            ):
                with self.subTest(variable=name, entry=label):
                    with self.assertRaisesRegex(dp.BindingError, name):
                        call()

    def test_process_environment_is_checked_too(self):
        with mock.patch.dict(os.environ, {'ST_DATA_ROOT': os.path.join(BASE, 'external')}):
            with self.assertRaisesRegex(dp.BindingError, 'ST_DATA_ROOT'):
                dp.data_path('a', code_root=BASE)

    def test_empty_or_blank_values_count_as_not_set(self):
        for value in ('', '   ', '\t'):
            with self.subTest(value=value):
                env = {name: value for name in dp.BINDING_ENV}
                self.assertEqual(dp.data_path('a', code_root=BASE, environ=env), Path(BASE) / 'data' / 'a')

    def test_the_refusal_names_every_offending_variable(self):
        env = {'ST_DATA_ROOT': 'x', 'ST_RUNTIME_ROLE': 'backend'}
        with self.assertRaises(dp.BindingError) as ctx:
            dp.binding_for(code_root=BASE, environ=env)
        self.assertIn('ST_DATA_ROOT', str(ctx.exception))
        self.assertIn('ST_RUNTIME_ROLE', str(ctx.exception))
        self.assertNotIn('ST_DATA_BINDING', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
