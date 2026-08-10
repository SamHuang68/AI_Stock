# -*- coding: utf-8 -*-
"""pulse_intel 單元測試 — 分數可覆核、缺資料進 pending、延伸因子專業口徑。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pulse_intel as pi  # noqa: E402


def test_health_and_breadth_bullish():
    out = pi.build_pulse_intel(
        health_score=72,
        pillars={
            'volumeScore': 68.0, 'turnoverYi': 10500.0,
            'instScore': 80.0, 'instNetYi': 220.0,
            'marginScore': 62.0, 'marginRatio': 172.0,
            'valuationScore': 55.0, 'medianPE': 16.5,
        },
        market_rows=[{'k': '成交金額', 'v': '10500 億', 'score': 68.0}],
        summary='大盤體質 72',
        stocks={'up': 900, 'down': 300, 'unchanged': 100, 'limitUp': 20, 'limitDown': 2,
                'advRatio': 0.75, 'net': 600},
        indices={
            't00': {'price': 23000.0, 'changePct': 1.2},
            'o00': {'price': 260.0, 'changePct': 0.8},
        },
        inst={'foreign': 1.5e10, 'trust': 3e9, 'dealer': -2e9},
        txf_night={'price': 23100.0, 'changePct': 0.9, 'ampRate': 0.8},
        sectors=[
            {'name': '半導體', 'changePct': 2.5},
            {'name': '金融', 'changePct': 1.0},
            {'name': '塑膠', 'changePct': 0.5},
            {'name': '鋼鐵', 'changePct': -0.2},
            {'name': '加權指數', 'changePct': 1.2},  # skipped
        ],
        sources_present={
            'twindex': True, 'breadth': True, 'marketflow': True, 'health': True,
            'margin': True, 'valuation': True, 'txf': True, 'sectors': True,
            'txOi': False, 'sbl': False, 'nhnl': False,
        },
    )
    assert out['ok'] is True
    assert out['healthScore'] == 72
    assert out['totalScore'] is not None and 55 <= out['totalScore'] <= 90
    # 8/11 核心+延伸有資料
    assert out['dataCompleteness'] == round(100.0 * 8 / 11, 1)
    assert any(f['name'] == '市場廣度' for f in out['positiveFactors'])
    assert any(f['name'] == '三大法人' for f in out['positiveFactors'])
    assert any(f['name'] == '類股參與度' for f in out['positiveFactors'])
    assert all(f.get('mkt') == 'TW' for f in out['positiveFactors'])
    assert any(f.get('mkt') == 'US' for f in out['pendingFactors'])
    pending_names = {f['name'] for f in out['pendingFactors']}
    assert '期貨未平倉量' in pending_names
    assert '借券賣出壓力' in pending_names
    assert '250日新高／新低家數' in pending_names
    assert all(f['score'] == 0 for f in out['pendingFactors'])


def test_missing_data_goes_pending_not_fake():
    out = pi.build_pulse_intel(
        health_score=None,
        pillars={},
        market_rows=[],
        summary=None,
        stocks=None,
        indices={},
        inst={},
        txf_night=None,
        sectors=None,
        sources_present={
            'twindex': False, 'breadth': False, 'marketflow': False, 'health': False,
            'margin': False, 'valuation': False, 'txf': False, 'sectors': False,
            'txOi': False, 'sbl': False, 'nhnl': False,
        },
    )
    assert out['ok'] is True
    assert out['totalScore'] is None
    assert out['statusText'] == '資料不足'
    assert out['dataCompleteness'] == 0.0
    names = {f['name'] for f in out['pendingFactors']}
    assert '市場廣度' in names
    assert '三大法人' in names
    assert '類股參與度' in names
    assert '估值' in names
    assert '期貨未平倉量' in names
    assert '借券賣出壓力' in names
    assert '250日新高／新低家數' in names
    assert '美股指數' in names
    assert '美股廣度' in names
    assert out['positiveFactors'] == []
    assert out['riskFactors'] == []
    # 不用假 Fear&Greed／外資借券賣超（無外資分項）
    all_names = names | {f['name'] for f in out['positiveFactors'] + out['riskFactors']}
    assert 'Fear & Greed' not in all_names
    assert '外資借券賣超' not in all_names
    assert out['datasetsTotal'] == len(pi.EXPECTED_DATASETS)


def test_concentration_and_divergence_risk():
    out = pi.build_pulse_intel(
        health_score=50,
        pillars={'volumeScore': 50.0, 'turnoverYi': 8000.0, 'instScore': 45.0, 'instNetYi': -40.0},
        market_rows=[],
        summary=None,
        stocks={'up': 400, 'down': 700, 'unchanged': 100, 'advRatio': 0.36, 'net': -300,
                'limitUp': 3, 'limitDown': 12},
        indices={'t00': {'price': 22000.0, 'changePct': 3.2}, 'o00': {'price': 250.0, 'changePct': -1.8}},
        inst={'foreign': 5e9, 'trust': 0, 'dealer': -1.2e10},
        txf_night={'price': 21800.0, 'changePct': -1.1},
        sectors=[
            {'name': '半導體', 'changePct': 6.0},
            {'name': '金融', 'changePct': 0.2},
            {'name': '塑膠', 'changePct': 0.1},
            {'name': '鋼鐵', 'changePct': -0.3},
            {'name': '航運', 'changePct': -0.5},
        ],
    )
    risk_names = {f['name'] for f in out['riskFactors']}
    assert '指數乖離風險' in risk_names
    assert '產業集中度風險' in risk_names
    assert '夜盤背離' in risk_names or '自營避險賣壓' in risk_names
    assert out['riskScore'] is not None and out['riskScore'] > 20


def test_tx_oi_long_build_is_positive():
    out = pi.build_pulse_intel(
        health_score=60, pillars={'turnoverYi': 9000.0}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        tx_oi={'oi': 120000, 'oiChgPct': 2.5, 'priceChgPct': 0.8, 'contract': '202607'},
        sources_present={'txOi': True},
    )
    pos = [f for f in out['positiveFactors'] if f['name'] == '期貨未平倉量']
    assert len(pos) == 1
    assert '多方增倉' in pos[0]['description']
    assert '期貨未平倉量' not in {f['name'] for f in out['pendingFactors']}


def test_tx_oi_short_build_is_risk():
    out = pi.build_pulse_intel(
        health_score=60, pillars={}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        tx_oi={'oi': 120000, 'oiChgPct': 2.5, 'priceChgPct': -0.9, 'contract': '202607'},
    )
    risk = [f for f in out['riskFactors'] if f['name'] == '期貨未平倉量']
    assert len(risk) == 1
    assert '空頭增倉' in risk[0]['description']


def test_sbl_heavy_is_risk():
    out = pi.build_pulse_intel(
        health_score=60, pillars={'turnoverYi': 5000.0}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        sbl={'sblSellYi': 320.0, 'marginSellYi': 40.0},
    )
    risk = [f for f in out['riskFactors'] if f['name'] == '借券賣出壓力']
    assert len(risk) == 1
    assert 'TWTASU' in risk[0]['description']


def test_nhnl_sample_discloses_coverage():
    out = pi.build_pulse_intel(
        health_score=60, pillars={}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        nhnl={'newHighs': 12, 'newLows': 2, 'sampleN': 48,
              'note': '流動性樣本 48/50 檔（非全市場）'},
    )
    pos = [f for f in out['positiveFactors'] if f['name'] == '250日新高／新低家數']
    assert len(pos) == 1
    assert '樣本' in pos[0]['description']
    assert '非全市場' in pos[0]['description']
    assert pos[0]['score'] > 0


def test_nhnl_risk_and_neutral_zero_score():
    risk_out = pi.build_pulse_intel(
        health_score=60, pillars={}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        nhnl={'newHighs': 1, 'newLows': 8, 'sampleN': 40, 'note': '樣本 40 檔（非全市場）'},
    )
    assert any(f['name'] == '250日新高／新低家數' for f in risk_out['riskFactors'])

    neu = pi.build_pulse_intel(
        health_score=60, pillars={}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        tx_oi={'oi': 100000, 'oiChgPct': 0.2, 'priceChgPct': 0.1, 'contract': '202608'},
        sbl={'sblSellYi': 150.0, 'marginSellYi': 20.0},
        nhnl={'newHighs': 3, 'newLows': 3, 'sampleN': 30, 'note': '樣本 30 檔（非全市場）'},
    )
    # 中性訊號：顯示於正面欄但 score=0，不灌水分數
    oi = [f for f in neu['positiveFactors'] if f['name'] == '期貨未平倉量'][0]
    sbl_f = [f for f in neu['positiveFactors'] if f['name'] == '借券賣出壓力'][0]
    nh = [f for f in neu['positiveFactors'] if f['name'] == '250日新高／新低家數'][0]
    assert oi['score'] == 0.0 and sbl_f['score'] == 0.0 and nh['score'] == 0.0
    assert neu['positiveFactorScore'] == 0.0


def test_tx_oi_short_covering_and_unwind():
    cover = pi.build_pulse_intel(
        health_score=60, pillars={}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        tx_oi={'oi': 90000, 'oiChgPct': -2.5, 'priceChgPct': 0.6, 'contract': '202608'},
    )
    assert any('空頭回補' in f['description'] for f in cover['positiveFactors'] if f['name'] == '期貨未平倉量')
    unwind = pi.build_pulse_intel(
        health_score=60, pillars={}, market_rows=[], summary=None,
        stocks=None, indices={}, inst={}, txf_night=None, sectors=None,
        tx_oi={'oi': 90000, 'oiChgPct': -2.5, 'priceChgPct': -0.8, 'contract': '202608'},
    )
    assert any('多頭減倉' in f['description'] for f in unwind['riskFactors'] if f['name'] == '期貨未平倉量')


def test_filter_sectors_skips_benchmarks():
    rows = pi.filter_sectors([
        {'name': '加權指數', 'changePct': 1.0},
        {'name': '半導體', 'changePct': 2.0},
        {'name': '電子工業', 'changePct': 0.5},
    ])
    assert [r['name'] for r in rows] == ['半導體']


def test_status_label_clearly_strong():
    assert pi._label_total(85) == '明顯偏強'
    assert pi._label_total(72) == '偏強'
    assert pi._label_total(50) == '中性'


def test_all_extras_raise_completeness():
    out = pi.build_pulse_intel(
        health_score=70,
        pillars={
            'volumeScore': 60.0, 'turnoverYi': 9000.0,
            'instScore': 55.0, 'instNetYi': 10.0,
            'marginScore': 55.0, 'marginRatio': 160.0,
            'valuationScore': 50.0, 'medianPE': 18.0,
        },
        market_rows=[], summary=None,
        stocks={'up': 600, 'down': 400, 'unchanged': 100, 'advRatio': 0.6, 'net': 200},
        indices={'t00': {'price': 23000.0, 'changePct': 0.5}, 'o00': {'price': 250.0, 'changePct': 0.2}},
        inst={'foreign': 1e9, 'trust': 0, 'dealer': 0},
        txf_night={'price': 23100.0, 'changePct': 0.3},
        sectors=[{'name': '半導體', 'changePct': 1.0}, {'name': '金融', 'changePct': 0.5},
                 {'name': '塑膠', 'changePct': 0.2}, {'name': '鋼鐵', 'changePct': -0.1}],
        tx_oi={'oi': 100000, 'oiChgPct': 0.5, 'priceChgPct': 0.1, 'contract': '202607'},
        sbl={'sblSellYi': 100.0, 'marginSellYi': 20.0},
        nhnl={'newHighs': 5, 'newLows': 4, 'sampleN': 40, 'note': '流動性樣本 40/50 檔（非全市場）'},
        sources_present={
            'twindex': True, 'breadth': True, 'marketflow': True, 'health': True,
            'margin': True, 'valuation': True, 'txf': True, 'sectors': True,
            'txOi': True, 'sbl': True, 'nhnl': True,
        },
    )
    assert out['dataCompleteness'] == 100.0
    pending_names = {f['name'] for f in out['pendingFactors']}
    assert '期貨未平倉量' not in pending_names
    assert '借券賣出壓力' not in pending_names
    assert '250日新高／新低家數' not in pending_names
    assert '類股參與度' not in pending_names



def test_us_market_bearish_adds_risk():
    """美股指數／廣度偏空必須進入 riskFactors，且 mkt=US。"""
    out = pi.build_pulse_intel(
        health_score=60,
        pillars={
            'volumeScore': 55.0, 'turnoverYi': 8500.0,
            'instScore': 50.0, 'instNetYi': 0.0,
            'marginScore': 55.0, 'marginRatio': 168.0,
            'valuationScore': 50.0, 'medianPE': 17.0,
        },
        market_rows=[], summary=None,
        stocks={'up': 500, 'down': 500, 'unchanged': 100, 'advRatio': 0.5, 'net': 0},
        indices={'t00': {'price': 22000.0, 'changePct': 0.1}, 'o00': {'price': 250.0, 'changePct': 0.0}},
        inst={'foreign': 0, 'trust': 0, 'dealer': 0},
        txf_night={'price': 22000.0, 'changePct': 0.0},
        sectors=[{'name': '半導體', 'changePct': 0.2}, {'name': '金融', 'changePct': 0.1},
                 {'name': '塑膠', 'changePct': 0.0}, {'name': '鋼鐵', 'changePct': -0.1}],
        sources_present={
            'twindex': True, 'breadth': True, 'marketflow': True, 'health': True,
            'margin': True, 'valuation': True, 'txf': True, 'sectors': True,
            'txOi': False, 'sbl': False, 'nhnl': False,
        },
        us_market={
            'ok': True,
            'gspcChangePct': -2.4,
            'ixicChangePct': -3.1,
            'djiChangePct': -1.8,
            'soxChangePct': -4.0,
            'vixLevel': 28.5,
            'vixChangePct': 18.0,
            'up': 8, 'down': 32, 'flat': 0,
            'advRatio': 0.20,
            'sample': 40,
            'losers': [{'sym': 'NVDA', 'changePct': -7.2}],
            'gainers': [],
        },
    )
    risk_names = {f['name'] for f in out['riskFactors']}
    assert '美股指數偏空' in risk_names
    assert 'VIX 恐慌升溫' in risk_names
    assert '美股廣度偏空' in risk_names
    us_risk = [f for f in out['riskFactors'] if f.get('mkt') == 'US']
    assert len(us_risk) >= 3
    assert all(f['score'] < 0 for f in us_risk)
    assert out['snapshot']['usMarket']['gspcChangePct'] == -2.4
    assert out['model'] == 'tw-us-pulse-intel/v1'
    # 風險分應高於僅台股中性情境
    base = pi.build_pulse_intel(
        health_score=60,
        pillars={
            'volumeScore': 55.0, 'turnoverYi': 8500.0,
            'instScore': 50.0, 'instNetYi': 0.0,
            'marginScore': 55.0, 'marginRatio': 168.0,
            'valuationScore': 50.0, 'medianPE': 17.0,
        },
        market_rows=[], summary=None,
        stocks={'up': 500, 'down': 500, 'unchanged': 100, 'advRatio': 0.5, 'net': 0},
        indices={'t00': {'price': 22000.0, 'changePct': 0.1}, 'o00': {'price': 250.0, 'changePct': 0.0}},
        inst={'foreign': 0, 'trust': 0, 'dealer': 0},
        txf_night={'price': 22000.0, 'changePct': 0.0},
        sectors=[{'name': '半導體', 'changePct': 0.2}, {'name': '金融', 'changePct': 0.1},
                 {'name': '塑膠', 'changePct': 0.0}, {'name': '鋼鐵', 'changePct': -0.1}],
        sources_present={
            'twindex': True, 'breadth': True, 'marketflow': True, 'health': True,
            'margin': True, 'valuation': True, 'txf': True, 'sectors': True,
            'txOi': False, 'sbl': False, 'nhnl': False,
        },
    )
    assert out['riskScore'] is not None and base['riskScore'] is not None
    assert out['riskScore'] > base['riskScore']


def test_us_market_bullish_positive():
    out = pi.build_pulse_intel(
        health_score=65,
        pillars={'volumeScore': 60.0, 'turnoverYi': 9000.0, 'instScore': 60.0, 'instNetYi': 50.0,
                 'marginScore': 55.0, 'marginRatio': 170.0, 'valuationScore': 50.0, 'medianPE': 17.0},
        market_rows=[], summary=None,
        stocks={'up': 700, 'down': 400, 'unchanged': 100, 'advRatio': 0.64, 'net': 300},
        indices={'t00': {'price': 23000.0, 'changePct': 0.8}, 'o00': {'price': 260.0, 'changePct': 0.5}},
        inst={'foreign': 1e9, 'trust': 0, 'dealer': 0},
        txf_night={'price': 23100.0, 'changePct': 0.5},
        sectors=[{'name': '半導體', 'changePct': 1.0}, {'name': '金融', 'changePct': 0.5},
                 {'name': '塑膠', 'changePct': 0.2}, {'name': '鋼鐵', 'changePct': -0.1}],
        us_market={
            'ok': True,
            'gspcChangePct': 1.6,
            'ixicChangePct': 2.0,
            'djiChangePct': 1.2,
            'soxChangePct': 2.5,
            'vixLevel': 13.2,
            'vixChangePct': -4.0,
            'up': 30, 'down': 10, 'flat': 0,
            'advRatio': 0.75,
            'sample': 40,
            'gainers': [{'sym': 'NVDA', 'changePct': 5.0}],
            'losers': [],
        },
    )
    pos_names = {f['name'] for f in out['positiveFactors']}
    assert '美股指數偏多' in pos_names
    assert '美股廣度' in pos_names
    assert 'VIX 低檔' in pos_names
    assert all(f.get('mkt') == 'US' for f in out['positiveFactors'] if f['name'].startswith(('美股', 'VIX')))


if __name__ == '__main__':
    test_health_and_breadth_bullish()
    test_missing_data_goes_pending_not_fake()
    test_concentration_and_divergence_risk()
    test_tx_oi_long_build_is_positive()
    test_tx_oi_short_build_is_risk()
    test_sbl_heavy_is_risk()
    test_nhnl_sample_discloses_coverage()
    test_nhnl_risk_and_neutral_zero_score()
    test_tx_oi_short_covering_and_unwind()
    test_filter_sectors_skips_benchmarks()
    test_status_label_clearly_strong()
    test_all_extras_raise_completeness()
    test_us_market_bearish_adds_risk()
    test_us_market_bullish_positive()
    print('OK pulse_intel')
