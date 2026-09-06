# -*- coding: utf-8 -*-
"""盤後敘事日報（postmarket_report）模組測試 — 驗收 §9 對應：

1. narrative JSON schema 嚴格驗證
2. 人為改壞 quote asOf → 報告首條 risk 標「資料可能過期」
3. Decision 數字唯讀快照（不重算、欄位對齊）
4. 預設不得出現「建議買進／目標價」— system prompt 明文禁止 + guardrail 移除
5. 與 WaveDeck 同時搶 gate → 行為可預測（503 / partial），且 gate 一定釋放、
   除 reports 目錄外不寫任何狀態
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import ai_api  # noqa: E402
import llm_gate  # noqa: E402
import postmarket_report as pr  # noqa: E402


def _fresh_now() -> datetime:
    """決定性報告時點：當日 15:05 Asia/Taipei（收盤後 1.6h，未逾 6h 門檻）。"""
    return datetime.now(pr.TZ_TPE).replace(hour=15, minute=5, second=0, microsecond=0)


def _bars(days: int = 70, last_close: float = 1000.0, end: datetime | None = None):
    """(ts,o,h,l,c,v) 日K 假資料；end 預設當日 → 搭配 _fresh_now 一定新鮮。"""
    end = end or _fresh_now()
    rows = []
    for i in range(days):
        day = end - timedelta(days=days - 1 - i)
        close = last_close - (days - 1 - i) * 2.0
        rows.append((day.timestamp(), close - 5, close + 8, close - 9, close, 10_000 + i))
    return rows


def _chip():
    return {
        'symbol': '2330', 'date': datetime.now(pr.TZ_TPE).strftime('%Y%m%d'),
        'inst': {'foreign': 1_000_000, 'trust': 50_000, 'dealer': -20_000, 'total': 1_030_000},
        'margin': {'marginBalance': 30_000, 'shortBalance': 2_000,
                   'marginChange': -500, 'shortChange': 100},
    }


def _flash():
    return {'ok': True, 'items': [
        {'code': '2330', 'title': '台積電召開法說會', 'source': 'TWSE', 'time': '2026-09-05 15:00', 'url': 'x'},
        {'code': '9999', 'title': '無關訊息', 'source': 'TWSE', 'time': '2026-09-05 15:00', 'url': 'y'},
    ]}


def _decision_context():
    return {
        'ok': True, 'asOf': datetime.now(pr.TZ_TPE).isoformat(), 'market': 'TW',
        'regime': {'id': 'BROAD_RISK_ON', 'label': '全面偏多', 'score': 71.0,
                   'confidence': 0.8, 'ruleId': 'regime.broad_risk_on.v1'},
        'actionEnvelope': {'posture': 'OFFENSE'},
        'keyLevels': {'levels': {'r1': 23100, 'pivot': 22950, 's1': 22800}},
        'dataQuality': {'completeness': 90.0, 'freshness': 95.0},
    }


def _narrative_json(**overrides):
    base = {
        'conclusion': '2330 收在 1000.0，較前一日上漲 0.2%，量能持平。',
        'drivers': ['外資買超 1,000 張（chips.inst.foreign）'],
        'hypotheses': ['法說會前卡位'],
        'risks': ['量能未放大'],
        'watchTomorrow': ['能否站穩 sma20'],
        'citations': [{'type': 'quote', 'ref': 'quote.last'},
                      {'type': 'chip', 'ref': 'chips.inst.foreign'}],
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


class FakeAnthropic:
    """可注入回覆序列的 anthropic_call 替身，並記錄每次收到的 prompt。"""

    def __init__(self, replies=None, error=None):
        self.replies = list(replies or [])
        self.error = error
        self.calls = []

    def __call__(self, messages, *, system=None, model=None, max_tokens=1024):
        self.calls.append({'messages': messages, 'system': system,
                           'model': model, 'max_tokens': max_tokens})
        if self.error is not None:
            raise self.error
        text = self.replies.pop(0) if self.replies else _narrative_json()
        return text, {'model': model, 'usage': {'input_tokens': 3000, 'output_tokens': 800}}


class PostmarketBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_reports = os.environ.get('ST_REPORTS_DIR')
        os.environ['ST_REPORTS_DIR'] = str(Path(self.tmp.name) / 'reports')
        self._old_gate = llm_gate.GATE_PATH
        llm_gate.GATE_PATH = Path(self.tmp.name) / 'llm_gate.json'
        today = datetime.now().strftime('%Y%m%d')
        self._old_model_cache = dict(ai_api._MODEL_CACHE)
        ai_api._MODEL_CACHE.update({'date': today, 'id': 'claude-sonnet-4-6'})
        pr.configure(
            bars_fn=lambda code: _bars(),
            chip_fn=lambda code: _chip(),
            news_fn=_flash,
            decision_fn=_decision_context,
            universe_fn=lambda: {'tw': {'2330': '台積電'}, 'twmeta': {'2330': {'board': '上市'}}},
            sectors_fn=lambda: {'2330': '半導體業'},
        )

    def tearDown(self):
        pr.configure(bars_fn=None, chip_fn=None, news_fn=None, decision_fn=None,
                     universe_fn=None, sectors_fn=None, anthropic_fn=None)
        llm_gate.GATE_PATH = self._old_gate
        ai_api._MODEL_CACHE.update(self._old_model_cache)
        if self._old_reports is None:
            os.environ.pop('ST_REPORTS_DIR', None)
        else:
            os.environ['ST_REPORTS_DIR'] = self._old_reports
        self.tmp.cleanup()


class EvidencePackTest(PostmarketBase):
    def test_pack_contains_all_blocks_with_as_of(self):
        pack = pr.build_evidence_pack(
            '2330', include={'quotes': True, 'chips': True, 'techSummary': True,
                             'news': True, 'decisionSummary': True},
            decision=pr.decision_snapshot(_decision_context()), flash=_flash(),
            uni={'tw': {'2330': '台積電'}, 'twmeta': {'2330': {'board': '上市'}}},
            sectors={'2330': '半導體業'}, now=_fresh_now())
        self.assertEqual(pack['symbol'], '2330')
        self.assertEqual(pack['quote']['last'], 1000.0)
        self.assertEqual(pack['quote']['changePct'], 0.2)
        self.assertEqual(pack['quote']['session'], 'closed')
        self.assertIn('quote', pack['evidenceAsOf'])
        self.assertIn('chips', pack['evidenceAsOf'])
        self.assertEqual(pack['chips']['inst']['foreign'], 1_000_000)
        # techSummary 為既有 indicators 數值（精準 SMA/RSI），非 LLM 解讀
        self.assertAlmostEqual(pack['techSummary']['sma5'], 996.0, places=2)
        self.assertIsNotNone(pack['techSummary']['rsi14'])
        self.assertEqual(len(pack['news']), 1)
        self.assertEqual(pack['news'][0]['title'], '台積電召開法說會')
        self.assertEqual(pack['universeMeta']['industry'], '半導體業')
        self.assertFalse(pack['stale'])

    def test_decision_summary_is_read_only_snapshot(self):
        """驗收 §9-3：Decision 數字與報告引用一致 — 快照原封搬運既有值。"""
        ctx = _decision_context()
        snap = pr.decision_snapshot(ctx)
        self.assertEqual(snap['regime']['id'], ctx['regime']['id'])
        self.assertEqual(snap['regime']['score'], ctx['regime']['score'])
        self.assertEqual(snap['regime']['confidence'], ctx['regime']['confidence'])
        self.assertEqual(snap['levels'], {'r1': 23100, 'pivot': 22950, 's1': 22800})
        self.assertEqual(snap['posture'], 'OFFENSE')
        self.assertTrue(snap['readOnly'])
        self.assertIsNone(pr.decision_snapshot(None))

    def test_missing_data_yields_notes_not_fabrication(self):
        pr.configure(bars_fn=lambda code: [], chip_fn=lambda code: None)
        pack = pr.build_evidence_pack('9999', include={'quotes': True, 'chips': True,
                                                       'news': True}, flash=None)
        self.assertNotIn('quote', pack)
        self.assertNotIn('chips', pack)
        self.assertEqual(pack['news'], [])
        self.assertTrue(any('資料不足' in n for n in pack['notes']))

    def test_stale_quote_as_of_detected(self):
        """驗收 §9-2：人為改壞 quote asOf → 過期理由。"""
        now = _fresh_now()
        pack = pr.build_evidence_pack('2330', include={'quotes': True}, now=now)
        self.assertFalse(pack['stale'])
        pr.configure(bars_fn=lambda code: _bars(end=now - timedelta(days=3)))
        pack = pr.build_evidence_pack('2330', include={'quotes': True}, now=now)
        self.assertTrue(pack['stale'])
        self.assertTrue(any('逾 6h' in r for r in pack['staleReasons']))

    def test_intraday_session_uses_one_hour_threshold(self):
        now = datetime.now(pr.TZ_TPE)
        fresh = {'asOf': (now - timedelta(minutes=30)).isoformat(), 'session': 'regular'}
        stale = {'asOf': (now - timedelta(hours=2)).isoformat(), 'session': 'regular'}
        self.assertEqual(pr.staleness(fresh, now), [])
        self.assertTrue(any('逾 1h' in r for r in pr.staleness(stale, now)))


class AnomaliesValidationPointsTest(PostmarketBase):
    def test_pack_includes_rule_anomalies_and_validation_points(self):
        pack = pr.build_evidence_pack(
            '2330', include={'quotes': True, 'chips': True, 'techSummary': True,
                             'validationPoints': True},
            now=_fresh_now())
        self.assertIn('anomalies', pack)
        self.assertIn('validationPoints', pack)
        self.assertLessEqual(len(pack['validationPoints']), pr.MAX_VALIDATION_POINTS)
        for anomaly in pack['anomalies']:
            self.assertEqual(anomaly['epistemic'], 'FACT')
            self.assertIn('id', anomaly)
            self.assertIn('metric', anomaly)
            self.assertIn('label', anomaly)
        for vp in pack['validationPoints']:
            self.assertEqual(vp['epistemic'], 'FACT')
            self.assertIn('label', vp)
            self.assertIn('resolveSession', vp)
            self.assertIn('thresholdRef', vp)

    def test_volume_spike_anomaly_detected(self):
        bars = _bars()
        # inflate last 5 volumes
        inflated = []
        for i, row in enumerate(bars):
            if i >= len(bars) - 5:
                inflated.append((row[0], row[1], row[2], row[3], row[4], 500_000 + i))
            else:
                inflated.append(row)
        pr.configure(bars_fn=lambda code: inflated)
        pack = pr.build_evidence_pack('2330', include={'quotes': True, 'techSummary': True,
                                                       'validationPoints': True},
                                      now=_fresh_now())
        ids = {a['id'] for a in pack.get('anomalies', [])}
        self.assertIn('volume_spike', ids)

    def test_validation_points_capped_at_three(self):
        quote = {'last': 1000.0, 'asOf': _fresh_now().isoformat(), 'session': 'closed'}
        tech = {
            'close': 1000.0, 'sma20': 980.0, 'volRatio': 1.8, 'rsi14': 28.0,
            'asOf': quote['asOf'],
        }
        chips = {
            'asOf': '2026-09-05',
            'inst': {'foreign': -2_000_000},
            'margin': {'marginChange': -600},
        }
        anomalies = pr.detect_anomalies(quote, tech, chips)
        points = pr.build_validation_points(anomalies, quote, tech, chips, now=_fresh_now(),
                                            max_points=3)
        self.assertLessEqual(len(points), 3)
        self.assertTrue(all(p['epistemic'] == 'FACT' for p in points))

    def test_validation_points_disabled_via_include(self):
        pack = pr.build_evidence_pack(
            '2330', include={'quotes': True, 'techSummary': True, 'validationPoints': False},
            now=_fresh_now())
        self.assertNotIn('anomalies', pack)
        self.assertNotIn('validationPoints', pack)


class NarrativeNumericRedlineTest(PostmarketBase):
    def test_audit_flags_invented_numbers(self):
        pack = pr.build_evidence_pack(
            '2330',
            include={'quotes': True, 'techSummary': True, 'chips': True, 'validationPoints': True},
            decision=pr.decision_snapshot(_decision_context()),
            flash=_flash(),
            uni={'tw': {'2330': '台積電'}},
            now=_fresh_now(),
        )
        narrative = {
            'conclusion': '若站穩 1500 元將延續多頭。',
            'drivers': [], 'hypotheses': [], 'risks': [], 'watchTomorrow': [],
        }
        flags = pr.audit_narrative_numerics(narrative, pack)
        self.assertTrue(any('未出現的數字' in f for f in flags))

    def test_audit_allows_pack_numbers(self):
        pack = pr.build_evidence_pack(
            '2330', include={'quotes': True, 'techSummary': True, 'validationPoints': True},
            now=_fresh_now(),
        )
        last = pack['quote']['last']
        narrative = {
            'conclusion': f'收在 {last}，量能觀察中。',
            'drivers': [], 'hypotheses': [], 'risks': [], 'watchTomorrow': [],
        }
        flags = pr.audit_narrative_numerics(narrative, pack)
        self.assertEqual(flags, [])

    def test_system_prompt_mentions_validation_points(self):
        prompt = pr.system_prompt()
        self.assertIn('validationPoints', prompt)
        self.assertIn('禁止自創新閾值', prompt)


class NarrativeContractTest(unittest.TestCase):
    def test_validate_narrative_strict_schema(self):
        ok, errors = pr.validate_narrative(json.loads(_narrative_json()))
        self.assertTrue(ok, errors)
        for broken in (
            None, [], 'x',
            {'conclusion': '', 'drivers': [], 'hypotheses': [], 'risks': [], 'watchTomorrow': []},
            {'conclusion': 'ok', 'drivers': 'not-a-list', 'hypotheses': [], 'risks': [], 'watchTomorrow': []},
            {'conclusion': 'ok', 'drivers': [1], 'hypotheses': [], 'risks': [], 'watchTomorrow': []},
            {'conclusion': 'ok', 'drivers': [], 'hypotheses': [], 'risks': []},
        ):
            ok, errors = pr.validate_narrative(broken)
            self.assertFalse(ok, f'應拒絕: {broken!r}')
            self.assertTrue(errors)

    def test_parse_llm_json_tolerates_fences(self):
        raw = '```json\n' + _narrative_json() + '\n```'
        self.assertIsNotNone(pr.parse_llm_json(raw))
        self.assertIsNone(pr.parse_llm_json('沒有 JSON'))

    def test_system_prompt_forbids_trade_calls_and_recompute(self):
        """驗收 §9-4（prompt 面）：明文禁止買賣建議／目標價；Decision 唯讀。"""
        prompt = pr.system_prompt()
        for phrase in ('禁止建議買進', '禁止建議賣出', '目標價', '保證獲利',
                       '禁止自行推算', 'decisionSummary', '資料不足', '資料可能過期'):
            self.assertIn(phrase, prompt)

    def test_scrub_advice_removes_forbidden_output(self):
        """驗收 §9-4（輸出面）：模型違規輸出被 guardrail 移除。"""
        narrative = {
            'conclusion': '走勢偏多。建議買進並上看目標價 1200 元。',
            'drivers': ['外資買超', '建議加碼半導體'],
            'hypotheses': [], 'risks': ['量縮'], 'watchTomorrow': ['目標價 1200 能否達成'],
        }
        out, flags = pr.scrub_advice(narrative)
        joined = json.dumps(out, ensure_ascii=False)
        self.assertNotIn('目標價', joined)
        self.assertNotIn('建議買進', joined)
        self.assertNotIn('建議加碼', joined)
        self.assertEqual(out['drivers'], ['外資買超'])
        self.assertEqual(out['risks'], ['量縮'])
        self.assertTrue(flags)
        clean, flags = pr.scrub_advice({'conclusion': '量價齊揚。', 'drivers': [],
                                        'hypotheses': [], 'risks': [], 'watchTomorrow': []})
        self.assertEqual(clean['conclusion'], '量價齊揚。')
        self.assertFalse(flags)

    def test_apply_staleness_prepends_flag(self):
        narrative = {'conclusion': 'x', 'drivers': [], 'hypotheses': [],
                     'risks': ['既有風險'], 'watchTomorrow': []}
        out = pr.apply_staleness(narrative, ['quote asOf 逾 6h 門檻'])
        self.assertTrue(out['risks'][0].startswith('資料可能過期'))
        self.assertEqual(out['risks'][1], '既有風險')
        self.assertEqual(pr.apply_staleness(narrative, []), narrative)

    def test_estimate_cost_by_model_family(self):
        sonnet = pr.estimate_cost_usd('claude-sonnet-4-6', 1_000_000, 0)
        opus = pr.estimate_cost_usd('claude-opus-4-1', 1_000_000, 0)
        self.assertAlmostEqual(sonnet, 3.0)
        self.assertAlmostEqual(opus, 15.0)
        self.assertGreater(pr.estimate_cost_usd('unknown-model', 1000, 1000), 0)


class GenerateReportTest(PostmarketBase):
    def _generate(self, body=None, fake=None, **kwargs):
        fake = fake or FakeAnthropic()
        body = body or {'symbols': ['2330'], 'locale': 'zh-Hant-TW'}
        kwargs.setdefault('now', _fresh_now())
        result = pr.generate_report(body, api_key='sk-test',
                                    anthropic_call=fake, **kwargs)
        return result, fake

    def test_success_shape_usage_and_persistence(self):
        result, fake = self._generate()
        self.assertEqual(result['status'], 200)
        payload = result['payload']
        self.assertTrue(payload['reportId'].startswith('pmd-'))
        self.assertEqual(payload['usage']['inputTokens'], 3000)
        self.assertEqual(payload['usage']['outputTokens'], 800)
        self.assertGreater(payload['usage']['estUsd'], 0)
        sym = payload['symbols'][0]
        self.assertEqual(sym['symbol'], '2330')
        self.assertIn('quote', sym['evidenceAsOf'])
        self.assertTrue(sym['narrative']['conclusion'])
        self.assertIn('validationPoints', sym)
        self.assertLessEqual(len(sym['validationPoints']), pr.MAX_VALIDATION_POINTS)
        self.assertEqual(sym['validationPoints'][0]['epistemic'], 'FACT')
        self.assertEqual(sym['citations'][0], {'type': 'quote', 'ref': 'quote.last'})
        # 本機存檔 + 當日累計
        self.assertIn('usageToday', payload)
        saved = Path(payload['savedTo'])
        self.assertTrue(saved.is_file())
        self.assertTrue(str(saved).startswith(os.environ['ST_REPORTS_DIR']))
        again, _ = self._generate()
        self.assertEqual(again['payload']['usageToday']['runs'], 2)
        self.assertAlmostEqual(again['payload']['usageToday']['estUsd'],
                               2 * payload['usage']['estUsd'], places=6)
        # user message 只帶 EvidencePack（server 組 context，不下放 key）
        content = fake.calls[0]['messages'][0]['content']
        self.assertIn('"evidencePack"', content)
        self.assertIn('"last":1000.0', content)
        self.assertNotIn('sk-test', content)

    def test_stale_quote_flags_first_risk(self):
        """驗收 §9-2：改壞 quote asOf → narrative.risks 首條標資料可能過期。"""
        old = _fresh_now() - timedelta(days=4)
        pr.configure(bars_fn=lambda code: _bars(end=old))
        result, _ = self._generate()
        sym = result['payload']['symbols'][0]
        self.assertTrue(sym['stale'])
        self.assertTrue(sym['narrative']['risks'][0].startswith('資料可能過期'))

    def test_forbidden_model_output_scrubbed(self):
        fake = FakeAnthropic(replies=[_narrative_json(
            conclusion='強勢，建議買進，目標價 1200。',
            drivers=['外資買超', '建議加碼'],
        )])
        result, _ = self._generate(fake=fake)
        sym = result['payload']['symbols'][0]
        joined = json.dumps(sym['narrative'], ensure_ascii=False)
        self.assertNotIn('目標價', joined)
        self.assertNotIn('建議買進', joined)
        self.assertTrue(sym['guardrail'])

    def test_invented_numeric_guardrail(self):
        fake = FakeAnthropic(replies=[_narrative_json(
            conclusion='明日若突破 9999 元將延續強勢。',
        )])
        result, _ = self._generate(fake=fake)
        sym = result['payload']['symbols'][0]
        self.assertTrue(any('未出現的數字' in g for g in (sym.get('guardrail') or [])))

    def test_symbols_validation(self):
        result = pr.generate_report({'symbols': []}, api_key='sk-test',
                                    anthropic_call=FakeAnthropic())
        self.assertEqual(result['status'], 400)
        result = pr.generate_report({'symbols': ['2330'] + [f'{i:04d}' for i in range(1, 21)]},
                                    api_key='sk-test', anthropic_call=FakeAnthropic())
        self.assertEqual(result['status'], 413)

    def test_gate_held_by_wavedeck_returns_503_with_retry_after(self):
        """驗收 §9-5：WD 持有 gate → 503 + Retry-After，不打上游、不寫狀態。"""
        self.assertTrue(llm_gate.acquire('wd', ttl_sec=60))
        fake = FakeAnthropic()
        result, _ = self._generate(fake=fake)
        self.assertEqual(result['status'], 503)
        self.assertIn('Retry-After', result['headers'])
        self.assertGreaterEqual(int(result['headers']['Retry-After']), 5)
        self.assertEqual(fake.calls, [])          # 沒有任何上游呼叫
        status = llm_gate.status()
        self.assertEqual(status['owner'], 'wd')   # 沒搶走 WD 的 gate（無雙寫）
        llm_gate.release('wd')

    def test_gate_purpose_marked_and_released(self):
        result, _ = self._generate()
        self.assertEqual(result['status'], 200)
        self.assertFalse(llm_gate.status()['held'])  # 結束必釋放
        # acquire 純函式行為：purpose 落到 gate 檔
        llm_gate.acquire('st', ttl_sec=30, purpose='postmarket-daily')
        raw = json.loads(llm_gate.GATE_PATH.read_text(encoding='utf-8'))
        self.assertEqual(raw['purpose'], 'postmarket-daily')
        self.assertEqual(llm_gate.status()['purpose'], 'postmarket-daily')
        llm_gate.release('st')

    def test_mid_batch_preempt_yields_predictable_partial(self):
        class PreemptGate:
            def __init__(self):
                self.acquires = 0
            def wd_busy(self):
                return False
            def wait_or_defer(self, owner, wait_sec=2.0, ttl_sec=120, purpose=None):
                return True
            def acquire(self, owner, ttl_sec=120, purpose=None):
                self.acquires += 1
                return False  # WD 中途 preempt
            def release(self, owner):
                self.released = True
            def status(self):
                return {'held': True, 'owner': 'wd', 'remaining_sec': 10}

        gate = PreemptGate()
        result, fake = self._generate(
            body={'symbols': ['2330', '2454', '2317']}, gate=gate)
        payload = result['payload']
        self.assertEqual(result['status'], 200)
        self.assertTrue(payload['partial'])
        self.assertEqual(len(fake.calls), 1)      # 只跑了第一檔
        errors = [s.get('error') for s in payload['symbols'][1:]]
        self.assertEqual(errors, ['gate_preempted_by_wavedeck'] * 2)
        self.assertTrue(gate.released)

    def test_abort_signal_skips_remaining_symbols(self):
        cid = 'test-abort-1'
        pr.signal_abort(cid)
        result, fake = self._generate(
            body={'symbols': ['2330', '2454'], 'abortSignalClientId': cid})
        payload = result['payload']
        self.assertTrue(payload['aborted'])
        self.assertEqual(fake.calls, [])
        self.assertEqual([s['error'] for s in payload['symbols']], ['aborted', 'aborted'])
        self.assertFalse(pr.is_aborted(cid))       # 結束後清除

    def test_upstream_429_maps_to_429(self):
        err = urllib.error.HTTPError('u', 429, 'rate limited', {}, None)
        result, _ = self._generate(fake=FakeAnthropic(error=err))
        self.assertEqual(result['status'], 429)
        self.assertIn('Retry-After', result['headers'])

    def test_upstream_500_maps_to_502(self):
        err = urllib.error.HTTPError('u', 500, 'server error', {}, None)
        result, _ = self._generate(fake=FakeAnthropic(error=err))
        self.assertEqual(result['status'], 502)

    def test_invalid_model_json_reported_per_symbol(self):
        result, _ = self._generate(fake=FakeAnthropic(replies=['這不是 JSON']))
        sym = result['payload']['symbols'][0]
        self.assertNotIn('narrative', sym)
        self.assertIn('驗證失敗', sym['error'])

    def test_no_state_written_outside_reports_dir(self):
        """紅線：不 mutate ST 狀態 — 只允許 reports 目錄出現新檔。"""
        result, _ = self._generate()
        self.assertEqual(result['status'], 200)
        written = [p for p in Path(self.tmp.name).rglob('*') if p.is_file()]
        for path in written:
            ok = (str(path).startswith(os.environ['ST_REPORTS_DIR'])
                  or path.name == 'llm_gate.json')
            self.assertTrue(ok, f'不允許的寫入: {path}')

    def test_market_blurb_only_with_macro_optin(self):
        result, fake = self._generate()
        self.assertNotIn('marketBlurb', result['payload'])
        fake2 = FakeAnthropic(replies=[_narrative_json(),
                                       json.dumps({'marketBlurb': '大盤量縮整理。'},
                                                  ensure_ascii=False)])
        result, _ = self._generate(
            body={'symbols': ['2330'], 'include': {'macro': True}}, fake=fake2)
        self.assertEqual(result['payload']['marketBlurb'], '大盤量縮整理。')
        self.assertEqual(len(fake2.calls), 2)

    def test_resolve_model_hint_opus_optin_default_sonnet(self):
        today = datetime.now().strftime('%Y%m%d')
        old_opus = dict(ai_api._OPUS_CACHE)
        ai_api._OPUS_CACHE.update({'date': today, 'id': 'claude-opus-4-1'})
        try:
            self.assertEqual(ai_api.resolve_model_hint('sk-test', 'sonnet'),
                             'claude-sonnet-4-6')
            self.assertEqual(ai_api.resolve_model_hint('sk-test', None),
                             'claude-sonnet-4-6')
            self.assertEqual(ai_api.resolve_model_hint('sk-test', 'opus'),
                             'claude-opus-4-1')
        finally:
            ai_api._OPUS_CACHE.update(old_opus)


if __name__ == '__main__':
    unittest.main()
