# -*- coding: utf-8 -*-
"""pulse_intel 單元測試 — 分數可覆核、缺資料進 pending。"""
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
        },
    )
    assert out['ok'] is True
    assert out['healthScore'] == 72
    assert out['totalScore'] is not None and 55 <= out['totalScore'] <= 90
    assert out['dataCompleteness'] == 100.0
    assert any(f['name'] == '市場廣度' for f in out['positiveFactors'])
    assert any(f['name'] == '三大法人' for f in out['positiveFactors'])
    assert any(f['name'] == '期貨未平倉量' for f in out['pendingFactors'])
    # pending 不計入正／風險分
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
        },
    )
    assert out['ok'] is True
    assert out['totalScore'] is None
    assert out['statusText'] == '資料不足'
    assert out['dataCompleteness'] == 0.0
    names = {f['name'] for f in out['pendingFactors']}
    assert '市場廣度' in names
    assert '三大法人' in names
    assert '期貨未平倉量' in names
    assert out['positiveFactors'] == []
    assert out['riskFactors'] == []


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


if __name__ == '__main__':
    test_health_and_breadth_bullish()
    test_missing_data_goes_pending_not_fake()
    test_concentration_and_divergence_risk()
    print('OK pulse_intel')
