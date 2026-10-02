"""官方參考價比較的時間基準、證據與保守排除驗證；不連網。"""
import copy
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from 突破觀察 import build_research
from 公司行動比較 import PARSER_VERSION

YEAR = 'breakout_252'
ROUTES = {'TWT49U': 'exRight', 'TWTAUU': 'reducation', 'TWTB8U': 'change', 'TWTCAU': 'split'}


class 官方比較測試(unittest.TestCase):
    def setUp(self):
        self.rows = []
        day = date(2025, 1, 6)
        while len(self.rows) < 300:
            if day.weekday() < 5:
                self.rows.append({'date': day.isoformat(), 'open': 100, 'high': 100, 'low': 99,
                                  'close': 100, 'volume': 1000, 'source': 'TWSE', 'issues': [], 'priceBasis': 'unadjusted'})
            day += timedelta(days=1)
        self.adjustments = {'symbol': '2330', 'coverage': {'start': '2025-01-01', 'end': '2026-12-31', 'version': PARSER_VERSION,
                                        'sources': [self.receipt(route) for route in ROUTES]}, 'events': []}

    def receipt(self, route):
        return {'url': f'https://wwwc.twse.com.tw/rwd/zh/{ROUTES[route]}/{route}?startDate=20250101&endDate=20261231&response=json',
                'sourceHash': 'a' * 64, 'retrievedAt': '2026-09-22T12:00:00+08:00', 'stat': 'OK',
                'start': '2025-01-01', 'end': '2026-12-31', 'route': route}

    def event(self, index=275, before=100, after=98, *, split=False):
        day = self.rows[index]['date']
        if split:
            fields = ['恢復買賣日期', 'ETF代號', '停止買賣前收盤價格', '恢復買賣參考價', '分割(反分割)']
            values, route, kind = [day, self.adjustments['symbol'], str(before), str(after), '分割'], 'TWTCAU', 'ETF分割'
        else:
            fields = ['資料日期', '股票代號', '除權息前收盤價', '除權息參考價', '權/息']
            values, route, kind = [day, self.adjustments['symbol'], str(before), str(after), '息'], 'TWT49U', '除權息'
        receipt = self.receipt(route)
        return {'date': day, 'kind': kind, 'before': before, 'after': after, 'factor': after / before,
                'status': 'supported', 'reason': None, 'sourceHash': receipt['sourceHash'], 'sourceUrl': receipt['url'],
                'retrievedAt': receipt['retrievedAt'], 'version': PARSER_VERSION,
                'payload': {'fields': fields, 'row': values, 'request': {'start': '2025-01-01', 'end': '2026-12-31'}}}

    def apply_event(self, index=275, before=100, after=98, *, split=False):
        factor = after / before
        self.adjustments['events'].append(self.event(index, before, after, split=split))
        for row in self.rows[index:]:
            for key in ('open', 'high', 'low', 'close'):
                row[key] *= factor

    def calculate(self, *, rows=None, adjustments=True, action_days=None):
        rows = self.rows if rows is None else rows
        kwargs = {'calendar_years': {2025, 2026}, 'action_days': set(action_days or []),
                  'action_coverage': ('2025-01-01', '2026-12-31', 'TWSE')}
        if adjustments is True:
            kwargs['adjustments'] = self.adjustments
        elif adjustments is not False:
            kwargs['adjustments'] = adjustments
        return build_research(rows, **kwargs)

    def test_未提供調整時仍是原始版本且None逐值一致(self):
        self.assertEqual(self.calculate(adjustments=False), self.calculate(adjustments=None))
        result = self.calculate(adjustments=None)
        self.assertEqual(result['version'], 'breakout-observation-v1')
        self.assertNotIn('priceBasis', result)
        self.assertNotIn('comparisonEvidence', result['latest'])

    def test_每個觀察日使用自己的基準並保留原始資料(self):
        self.apply_event(after=25, split=True)
        self.rows[276].update(open=25.2, high=25.2, close=25.2)
        original = copy.deepcopy(self.rows)
        result = self.calculate(action_days={self.rows[275]['date']})
        prior, effective, after = [result['rows'][i] for i in (274, 275, 276)]
        self.assertEqual(prior['metrics']['priorHigh252'], 100)
        self.assertEqual(effective['metrics']['priorHigh252'], 25)
        self.assertEqual(effective['metrics']['rawPriorHigh252'], 100)
        self.assertFalse(effective['conditions'][YEAR])
        self.assertEqual(after['signals'], [YEAR])
        self.assertEqual(after['anchorDate'], self.rows[276]['date'])
        self.assertEqual(self.rows, original)
        self.assertEqual(self.rows[275]['close'], 25)
        self.assertEqual(self.rows[275]['volume'], 1000)
        self.assertEqual(prior, self.calculate(rows=self.rows[:275])['rows'][-1])

    def test_未來事件不影響過去條件或輸入摘要(self):
        before = self.calculate(rows=self.rows[:280])
        self.adjustments['events'].append(self.event(290, after=25, split=True))
        after = self.calculate(rows=self.rows[:280], action_days={self.rows[290]['date']})
        self.assertEqual(before, after)

    def test_涵蓋延長與窗口外事件不改摘要(self):
        before = self.calculate()['latest']['inputDigest']
        self.adjustments['coverage']['end'] = '2027-12-31'
        self.adjustments['events'].append(self.event(10))
        self.assertEqual(before, self.calculate()['latest']['inputDigest'])

    def test_頂層保留整段研究因子但早期修訂不改最新摘要(self):
        self.apply_event(index=10, after=25, split=True)
        before = self.calculate()
        event = before['adjustmentEvidence']['events'][0]
        self.assertEqual(event['date'], self.rows[10]['date'])
        self.assertEqual(event['kind'], 'ETF分割')
        self.assertTrue(event['verified'])
        self.assertEqual(before['latest']['comparisonEvidence']['events'], [])
        self.assertTrue(before['latest']['eligible'][YEAR])
        # 早期因子仍影響歷史研究與來源明細，但位於最新 254 列證據窗口之外。
        revised = self.adjustments['events'][0]
        revised.update(after=24.9, factor=.249)
        revised['payload']['row'][revised['payload']['fields'].index('恢復買賣參考價')] = '24.9'
        after = self.calculate()
        self.assertEqual(after['adjustmentEvidence']['events'][0]['after'], 24.9)
        self.assertNotEqual(before['adjustmentEvidence']['events'], after['adjustmentEvidence']['events'])
        self.assertEqual(before['latest']['inputDigest'], after['latest']['inputDigest'])

    def test_官方0050已捨入參考比值不可當作精確四分之一(self):
        # 官方 2025/06/18 原始列的兩個價格；日期另用測試時間軸，不宣稱為官方日線。
        self.adjustments['symbol'] = '0050'
        for row in self.rows:
            row.update(open=188.65, high=188.65, low=188, close=188.65)
        self.apply_event(before=188.65, after=47.16, split=True)
        result = self.calculate()
        effective = result['rows'][275]
        self.assertAlmostEqual(effective['metrics']['priorHigh252'], 47.16)
        event = result['adjustmentEvidence']['events'][0]
        self.assertTrue(event['verified'])
        self.assertNotEqual(Decimal(str(event['factor'])), Decimal('.25'))

    def test_同日多事件即使個別supported仍拒絕(self):
        self.apply_event()
        self.adjustments['events'].append(copy.deepcopy(self.adjustments['events'][0]))
        latest = self.calculate()['latest']
        self.assertFalse(any(latest['eligible'].values()))
        self.assertIn('同日多個', latest['reason'][YEAR])

    def test_原始前收不一致或因子不符官方比值拒絕(self):
        self.apply_event()
        self.rows[274]['close'] = 99.99
        result = self.calculate()
        self.assertIn('前收', result['latest']['reason'][YEAR])
        self.rows[274]['close'] = 100
        self.adjustments['events'][0]['factor'] = .9
        self.assertIn('比值', self.calculate()['latest']['reason'][YEAR])

    def test_已知事件缺因子與unsupported皆不放行(self):
        known = {self.rows[275]['date']}
        self.assertIn('缺少', self.calculate(action_days=known)['latest']['reason'][YEAR])
        self.apply_event()
        self.adjustments['events'][0].update(status='unsupported', reason='除權不支援')
        self.assertIn('除權不支援', self.calculate()['latest']['reason'][YEAR])

    def test_supported不可取代原始純息欄位證明(self):
        self.apply_event()
        self.adjustments['events'][0]['payload']['row'][-1] = '權息'
        self.assertFalse(self.calculate()['latest']['eligible'][YEAR])

    def test_缺涵蓋收據與非官方來源及價格基準都拒絕(self):
        for change in ('收據', '來源', '價格'):
            with self.subTest(種類=change):
                rows, adjustments = copy.deepcopy(self.rows), copy.deepcopy(self.adjustments)
                if change == '收據':
                    adjustments['coverage']['sources'].pop()
                elif change == '來源':
                    rows[200]['source'] = 'YAHOO'
                else:
                    rows[200].pop('priceBasis')
                result = build_research(rows, calendar_years={2025, 2026}, action_days=set(),
                                        action_coverage=('2025-01-01', '2026-12-31', 'TWSE'), adjustments=adjustments)
                self.assertFalse(result['latest']['eligible'][YEAR])

    def test_不可信網址無效數字仍可輸出完整JSON證據(self):
        self.apply_event()
        for value in (0, -1, float('nan'), float('inf'), '無效'):
            with self.subTest(數值=str(value)):
                self.adjustments['events'][0]['factor'] = value
                result = self.calculate()
                self.assertFalse(result['latest']['eligible'][YEAR])
                json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.adjustments['events'][0]['factor'] = .98
        self.adjustments['events'][0]['sourceUrl'] = 'https://twse.com.tw.example.org/rwd/zh/exRight/TWT49U'
        self.assertFalse(self.calculate()['latest']['eligible'][YEAR])

    def test_因子修訂變更摘要但窗口外證據不參與(self):
        self.apply_event()
        before = self.calculate()['latest']['inputDigest']
        event = self.adjustments['events'][0]
        event.update(after=97, factor=.97)
        event['payload']['row'][event['payload']['fields'].index('除權息參考價')] = '97'
        self.assertNotEqual(before, self.calculate()['latest']['inputDigest'])

    def test_同因子重抓只改來源時間不改經濟摘要(self):
        self.apply_event()
        before = self.calculate()['latest']['inputDigest']
        self.adjustments['events'][0]['retrievedAt'] = '2026-09-23T12:00:00+08:00'
        for source in self.adjustments['coverage']['sources']:
            source['retrievedAt'] = '2026-09-23T12:00:00+08:00'
        self.assertEqual(before, self.calculate()['latest']['inputDigest'])

    def test_其他標的事件與無對應涵蓋收據不得採用(self):
        self.apply_event()
        event = self.adjustments['events'][0]
        event['payload']['row'][1] = '0050'
        self.assertIn('標的', self.calculate()['latest']['reason'][YEAR])
        event['payload']['row'][1] = '2330'
        event['sourceHash'] = 'b' * 64
        self.assertIn('收據', self.calculate()['latest']['reason'][YEAR])

    def test_錯誤欄位與日期型別維持可輸出的拒絕結果(self):
        self.apply_event()
        original = copy.deepcopy(self.adjustments)
        changes = ('欄名型別', '查詢日期', '涵蓋日期', '網址')
        for change in changes:
            with self.subTest(錯誤=change):
                self.adjustments = copy.deepcopy(original)
                event = self.adjustments['events'][0]
                if change == '欄名型別':
                    event['payload']['fields'][0] = {}
                elif change == '查詢日期':
                    event['payload']['request']['end'] = None
                elif change == '涵蓋日期':
                    self.adjustments['coverage']['end'] = None
                else:
                    event['sourceUrl'] = 'https://['
                result = self.calculate()
                self.assertFalse(result['latest']['eligible'][YEAR])
                json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_逐年與每日增量收據合併連續涵蓋但真缺口拒絕(self):
        sources = self.adjustments['coverage']['sources']
        extended = []
        for source in sources:
            first, last = copy.deepcopy(source), copy.deepcopy(source)
            first['end'] = self.rows[298]['date']
            last['start'] = self.rows[299]['date']
            extended.extend((first, last))
        self.adjustments['coverage']['sources'] = extended
        self.assertTrue(self.calculate()['latest']['eligible'][YEAR])
        extended[1]['start'] = '2026-12-31'
        self.assertFalse(self.calculate()['latest']['eligible'][YEAR])

    def test_比較可跨事件但原始後續報酬仍排除(self):
        self.rows[260].update(open=102, high=102, close=102)
        self.apply_event(index=262)
        result = self.calculate(action_days={self.rows[262]['date']})
        self.assertTrue(result['latest']['eligible'][YEAR])
        self.assertIn(YEAR, result['rows'][260]['signals'])
        stats = next(item for item in result['stats'] if item['key'] == YEAR)
        self.assertEqual(stats['horizons']['1']['raw']['n'], 1)
        self.assertEqual(stats['horizons']['3']['raw']['n'], 0)
        self.assertIsNone(stats['horizons']['3']['raw']['mean'])

    def test_停牌缺日不壓縮且已核對前收仍不能放行缺口(self):
        self.apply_event(after=25, split=True)
        self.rows[274] = {'date': self.rows[274]['date'], 'issues': ['交易日資料缺漏'], 'priceBasis': 'unadjusted'}
        result = self.calculate()
        self.assertEqual(len(result['rows']), len(self.rows))
        self.assertFalse(result['latest']['eligible'][YEAR])
        self.assertIn('缺值', result['latest']['reason'][YEAR])
        self.assertTrue(result['adjustmentEvidence']['events'][0]['verified'])

    def test_官方因子仍無法解釋的價格斷點拒絕(self):
        self.apply_event(after=25, split=True)
        self.rows[275].update(open=50, high=50, low=49, close=50)
        latest = self.calculate()['latest']
        self.assertFalse(latest['eligible'][YEAR])
        self.assertIn('無法解釋', latest['reason'][YEAR])


if __name__ == '__main__':
    unittest.main()
