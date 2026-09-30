"""全檢重現：停止交易、缺日暖機、來源日期、遺漏列與中斷收據。"""
import io
import json
import math
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals as ss
import signal_stats_pool as pool
import 個股訊號研究 as research
import 個股還原研究 as adjusted
import 個股每日資料 as sources
import 台股交易參考 as reference
import datastore as ds
import chip_api as ca
import chip_history_tracker as tracker


def series(n=750):
    days, day = [], date(2026, 9, 29)
    while len(days) < n:
        if reference.session(day)['status'] != 'closed':
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return [dict(date=d, open=p, high=p * 1.01, low=p * .99, close=p, volume=1000)
            for i, d in enumerate(reversed(days)) for p in [100 + i * .02 + 10 * math.sin(i / 8)]]


class ResearchBoundaryTests(unittest.TestCase):
    def test_verified_emergency_closure_keeps_trading_sessions_continuous(self):
        closure = reference.session('2026-07-10')
        self.assertEqual(closure['status'], 'closed')
        self.assertIn('8a8216d69ef76943019f46cb86ae0110.pdf', closure['source'])
        self.assertNotEqual(closure['source'], reference.references()['calendar']['source'])
        bars = series(500)
        self.assertNotIn('2026-07-10', [b['date'] for b in bars])
        parts = reference.continuous_segments('2330', bars, [b['date'] for b in bars])
        self.assertEqual(parts, [bars])
        self.assertFalse(reference.eligible_bar('2330', '2026-07-10'))
        july9 = next(b for b in bars if b['date'] == '2026-07-09')
        with_filler = sorted(bars + [{**july9, 'date': '2026-07-10', 'volume': 0}], key=lambda b: b['date'])
        self.assertEqual(reference.continuous_segments('2330', with_filler, [b['date'] for b in bars]), [bars])

    def test_terminated_rows_cannot_enter_main_study_or_pooled_outcomes(self):
        bars = series()
        benchmark = [{**b, 'close': 100 + i} for i, b in enumerate(bars)]
        study = research.Study(benchmark)
        study.add('2867', ss.build_frame(bars))
        rows = [r for hz in study.rows.values() for values in hz.values() for r in values]
        self.assertGreater(len(rows), 20)
        self.assertTrue(all(r['endDate'] < '2026-09-01' for r in rows))
        actual = pool.compute_pooled([('2867', bars)], sessions=[b['date'] for b in bars])
        expected = pool.compute_pooled([('2867', [b for b in bars if b['date'] < '2026-09-01'])])
        self.assertEqual(actual['signals'], expected['signals'])
        self.assertLess(actual['window']['to'], '2026-09-01')

    def test_adjusted_groups_skip_tw_closure_before_source_alignment_only_for_tw(self):
        bars = series(500)
        cut = next(i for i, b in enumerate(bars) if b['date'] == '2026-07-13')
        filler = {**bars[cut - 1], 'date': '2026-07-10', 'volume': 0}
        raw = bars[:cut] + [filler] + bars[cut:]
        snap = {'symbol': '2330', 'events': {},
                'rows': [dict(date=b['date'], rawClose=b['close'], adjClose=b['close']) for b in bars]}
        sessions = [b['date'] for b in bars]
        parts = adjusted.adjusted_segments(raw, snap, sessions, market='TW')
        self.assertEqual([p['raw'] for p in parts], [bars])
        # 相同日期若屬美股正常交易日，缺少來源列仍須切段，不套台股休市。
        us = adjusted.adjusted_segments(raw, {**snap, 'symbol': 'AAPL'}, [b['date'] for b in raw], market='US')
        self.assertEqual([p['raw'] for p in us], [bars[:cut]])
        missing = {**snap, 'rows': [r for r in snap['rows'] if r['date'] != '2026-07-09']}
        tw_missing = adjusted.adjusted_segments(raw, missing, sessions, market='TW')
        self.assertEqual([p['raw'] for p in tw_missing], [bars[:cut - 1]])

    def test_gap_resets_indicators_before_events_and_matches_separate_studies(self):
        bars = series(500)
        benchmark = [{**b, 'close': 100 + i} for i, b in enumerate(bars)]
        cut = 330
        broken = bars[:cut] + bars[cut + 1:]
        actual = research.Study(benchmark)
        actual.add('2330', ss.build_frame(broken))
        expected = research.Study(benchmark)
        expected.add('2330', ss.build_frame(bars[:cut]))
        expected.add('2330', ss.build_frame(bars[cut + 1:]))
        self.assertEqual(actual.rows, expected.rows)
        self.assertGreater(sum(len(r) for hz in actual.rows.values() for r in hz.values()), 20)

    def test_shared_missing_official_session_still_breaks_segment(self):
        bars = series(500)
        missing = next(i for i, b in enumerate(bars) if b['date'] == '2026-06-18')
        broken = bars[:missing] + bars[missing + 1:]
        parts = reference.continuous_segments('2330', broken, [b['date'] for b in broken])
        self.assertEqual([len(p) for p in parts], [missing, len(bars) - missing - 1])

    def test_complete_adjusted_coverage_resets_gap_indicators_too(self):
        bars = series(500)
        broken = bars[:300] + bars[301:]
        snap = {'symbol': '2330', 'fetchedAt': '2026-09-29', 'source': '離線測試', 'events': {},
                'rows': [dict(date=b['date'], rawClose=b['close'], adjClose=b['close']) for b in broken]}
        with patch.object(adjusted, 'load_snapshot', return_value=snap):
            actual = adjusted.Sensitivity(None, [b['date'] for b in bars])
            actual.add('2330', broken, [])
            expected = adjusted.Sensitivity(None, [b['date'] for b in bars])
            expected.add('2330', bars[:300], [])
            expected.add('2330', bars[301:], [])
        self.assertEqual(actual.rows, expected.rows)


class SourceBoundaryTests(unittest.TestCase):
    def test_t86_wrong_or_missing_date_is_unavailable_and_not_cached_as_success(self):
        payload = {'stat': 'OK', 'date': '20260924', 'fields': ['證券代號', '投信買賣超股數'],
                   'data': [['2330', '100']]}
        for source_day in ['20260924', None]:
            with patch.dict(ca._SNAP, {}, clear=True), patch.object(ca, '_fetch_json', return_value={**payload, 'date': source_day}):
                self.assertIsNone(ca.snap_t86('20260929'))
                self.assertTrue(ca._SNAP['T86:20260929']['err'])
                self.assertFalse(tracker.record_snapshot('2330', {'date': '20260929', 'inst': {'total': 1}}))
        with patch.dict(ca._SNAP, {}, clear=True), patch.object(ca, '_fetch_json', return_value=payload):
            self.assertEqual(ca.snap_t86('20260924')['2330']['trust'], 100)

    def test_missing_whole_row_retries_quotes_but_reuses_other_completed_sources(self):
        now = datetime(2026, 9, 29, 19, tzinfo=ss._TZ['TW'])
        twse = dict(Date='1150929', Code='2330', OpeningPrice='100', HighestPrice='101', LowestPrice='99', ClosingPrice='100', TradeVolume='1000')
        tpex = dict(Date='1150929', SecuritiesCompanyCode='6488', Open='100', High='101', Low='99', Close='100', TradingShares='1000')
        seen = []
        def respond(request, **kwargs):
            seen.append(request.full_url)
            rows = [twse] if 'twse' in request.full_url else [tpex]
            if 'twse' in request.full_url and len(seen) > 2:
                rows.append({**twse, 'Code': '2317'})
            if 'twse' in request.full_url:
                rows = {'stat': 'OK', 'date': '20260929', 'tables': [{
                    'fields': ['證券代號', '開盤價', '最高價', '最低價', '收盤價', '成交股數'],
                    'data': [[r[k] for k in ('Code', 'OpeningPrice', 'HighestPrice', 'LowestPrice', 'ClosingPrice', 'TradeVolume')] for r in rows]}]}
            return io.StringIO(json.dumps(rows))
        with tempfile.TemporaryDirectory() as tmp, patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                patch.object(sources, 'datetime') as clock, \
                patch.object(ds, 'list_symbols', return_value=['2330', '2317', '6488', '2867', '^TWII', '__MARGIN_RATIO__']), \
                patch.object(ds, 'merge_source_bars', return_value=dict(inserted=1, unchanged=0, conflicts=0, excluded=0)), \
                patch.object(ds, 'update', return_value=1) as benchmark, patch.object(ds, 'last_ts', return_value=int(now.timestamp())), \
                patch.object(tracker, 'parse_and_save', return_value=2) as twse_chips, \
                patch.object(tracker, 'parse_and_save_tpex', return_value=1), \
                patch.object(sources.urllib.request, 'urlopen', side_effect=respond):
            clock.now.return_value = now
            clock.fromisoformat.side_effect = datetime.fromisoformat
            first = sources.run()
            self.assertEqual(first['status'], 'partial')
            self.assertEqual(first['unconfirmedSymbols'], ['2317'])
            second = sources.run()
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(second['unconfirmedSymbols'], [])
            self.assertEqual(len(seen), 4)
            benchmark.assert_called_once()
            twse_chips.assert_called_once()

    def test_retry_interrupt_preserves_later_source_receipts(self):
        now = datetime(2026, 9, 29, 19, tzinfo=ss._TZ['TW'])
        completed = [dict(name=n, status='completed', result={'rows': 1})
                     for n in ['TPEx 日線', '大盤日線', '上市法人', '上櫃法人']]
        with tempfile.TemporaryDirectory() as tmp, patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                patch.object(sources, 'datetime') as clock, patch.object(ds, 'list_symbols', return_value=['2330']), \
                patch.object(sources.urllib.request, 'urlopen', side_effect=KeyboardInterrupt):
            path = Path(tmp) / 'stock_daily_sources.json'
            path.write_text(json.dumps(dict(runId='previous', sessionDate='2026-09-29', sources=completed)), encoding='utf-8')
            clock.now.return_value = now
            with self.assertRaises(KeyboardInterrupt):
                sources.run()
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual([r['name'] for r in saved['sources'] if r['status'] == 'completed'], [r['name'] for r in completed])
            self.assertEqual(saved['sources'][0]['status'], 'running')


if __name__ == '__main__':
    unittest.main()
