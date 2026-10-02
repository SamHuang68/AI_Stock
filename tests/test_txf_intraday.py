"""分鐘標的、盤別、來源時間、缺值及日線隔離契約。"""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import txf_intraday as minute


def fixture():
    return json.loads(Path(__file__).with_name('fixtures').joinpath('txf_minute.json').read_text(encoding='utf-8'))['chart']


def html(chart):
    return '<script>root.App.main = '+json.dumps({'context':{'dispatcher':{'stores':{'MarketChartStore':{'libra':{'OTHER':{'timestamp':[123]},'WTX&':chart}}}}}})+';</script>'


class MinuteTests(unittest.TestCase):
    def setUp(self):
        self.chart=fixture(); self.now=self.chart['meta']['regularMarketTime']+60

    def test_recorded_source_selects_named_symbol_and_omits_future_placeholders(self):
        out=minute.parse_html(html(self.chart),now=self.now)
        self.assertEqual(len(out['candles']),4)
        self.assertEqual(out['candles'][0]['open'],48671)
        self.assertEqual(out['candles'][-1]['close'],49185)
        self.assertTrue(all(b['time']<=out['sourceTimestamp'] for b in out['candles']))
        self.assertEqual(out['previousClose'],48669)
        self.assertEqual(out['exchangeTimezone'],'Asia/Taipei')

    def test_identity_timezone_interval_and_session_are_required(self):
        for changes in ({'symbol':'^TWII'},{'exchange':'NYQ'},{'exchangeTimezoneName':'America/New_York'},
                        {'dataGranularity':'1d'},{'sourceTradingPeriods':[]},{'regularMarketTime':self.now+600}):
            chart=copy.deepcopy(self.chart); chart['meta'].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError): minute.parse_html(html(chart),now=self.now)

    def test_wrong_array_length_duplicate_time_and_outside_session_fail(self):
        for mode in ('length','duplicate','session'):
            chart=copy.deepcopy(self.chart)
            if mode=='length':chart['indicators']['quote'][0]['close'].pop()
            elif mode=='duplicate':chart['timestamp'][1]=chart['timestamp'][0]
            else:chart['timestamp'][0]=chart['meta']['sourceTradingPeriods'][0][0]['start']-60
            with self.subTest(mode=mode),self.assertRaises(ValueError):minute.parse_html(html(chart),now=self.now)

    def test_null_prices_are_excluded_unknown_volume_is_not_zero(self):
        q=self.chart['indicators']['quote'][0]; q['open'][0]=None;q['volume'][1]=None
        out=minute.parse_html(html(self.chart),now=self.now)
        self.assertEqual(len(out['candles']),3)
        self.assertIsNone(out['candles'][0]['volume'])
        self.assertEqual(out['missing'],{'invalidPriceBars':1,'unknownVolumeBars':1})

    def test_missing_previous_close_is_not_fabricated(self):
        del self.chart['meta']['chartPreviousClose']
        self.assertIsNone(minute.parse_html(html(self.chart),now=self.now)['previousClose'])

    def test_undefined_in_page_object_is_not_executed_or_replaced_inside_string(self):
        text=html(self.chart).replace('"context":','"unused":undefined,"literal":"undefined","context":',1)
        self.assertTrue(minute.parse_html(text,now=self.now)['ok'])

    def test_cache_is_read_only_copy_and_failures_do_not_return_daily_fallback(self):
        with patch.object(minute,'_cached',None),patch('datastore.upsert_bars') as daily_write:
            result=minute.get(fetch=lambda:html(self.chart),now=self.now)
            result['candles'].clear()
            cached=minute.get(fetch=lambda:self.fail('快取不應連外'),now=self.now+1)
            self.assertEqual(len(cached['candles']),4);self.assertTrue(cached['cached'])
            failed=minute.get(fetch=lambda:'invalid',now=self.now+61)
            self.assertFalse(failed['ok']);self.assertEqual(failed['candles'],[])
            daily_write.assert_not_called()


if __name__=='__main__':unittest.main()
