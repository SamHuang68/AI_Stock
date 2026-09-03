# -*- coding: utf-8 -*-
"""chip_api 欄位對齊：自營商不可誤中外資自營商；融資/融券讀重複『今日餘額』。"""
import os
import sys
import inspect
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import chip_api as ca  # noqa: E402


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    module = sys.modules[__name__]
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if name.startswith('test_'):
            suite.addTest(unittest.FunctionTestCase(fn, description=name))
    return suite


# 與 TWSE T86 現行 fields 對齊（含外資自營商欄）
T86_FIELDS = [
    '證券代號', '證券名稱',
    '外陸資買進股數(不含外資自營商)',
    '外陸資賣出股數(不含外資自營商)',
    '外陸資買賣超股數(不含外資自營商)',
    '外資自營商買進股數',
    '外資自營商賣出股數',
    '外資自營商買賣超股數',
    '投信買進股數', '投信賣出股數', '投信買賣超股數',
    '自營商買賣超股數',
    '自營商買進股數(自行買賣)', '自營商賣出股數(自行買賣)', '自營商買賣超股數(自行買賣)',
    '自營商買進股數(避險)', '自營商賣出股數(避險)', '自營商買賣超股數(避險)',
    '三大法人買賣超股數',
]

# MI_MARGN 個股表：欄名重複（融資組 → 融券組）
MARGN_FIELDS = [
    '代號', '名稱',
    '買進', '賣出', '現金償還', '前日餘額', '今日餘額', '次一營業日限額',
    '買進', '賣出', '現券償還', '前日餘額', '今日餘額', '次一營業日限額',
    '資券互抵', '註記',
]


def test_col_prefers_exact_dealer_over_foreign_dealer():
    row = ['2330', '台積電'] + ['0'] * 17
    row[7] = '0'            # 外資自營商買賣超股數
    row[11] = '1,242,950'   # 自營商買賣超股數
    assert ca._col(T86_FIELDS, row, '自營商買賣超股數') == 1242950.0


def test_t86_dealer_excludes_foreign_dealer_prefix():
    row = ['2330', '台積電'] + ['0'] * 17
    row[4] = '641,660'
    row[7] = '0'
    row[10] = '61,000'
    row[11] = '1,242,950'
    row[14] = '912,715'
    row[17] = '330,235'
    row[18] = '1,945,610'
    assert ca._t86_dealer(T86_FIELDS, row) == 1242950.0


def test_t86_dealer_fallback_sum_self_and_hedge():
    """合計欄缺值時，自行買賣 + 避險。"""
    fields = list(T86_FIELDS)
    # 把合計欄改名，迫使走 fallback
    fields[11] = '自營商（缺）'
    row = ['2330', '台積電'] + ['0'] * 17
    row[14] = '100'
    row[17] = '50'
    assert ca._t86_dealer(fields, row) == 150.0


def test_margn_pair_first_second_today_balance():
    row = [
        '2330', '台積電',
        '262', '513', '41', '29,949', '29,657', '6,483,092',
        '8', '3', '0', '38', '33', '6,483,092',
        '0', '',
    ]
    mb, sb = ca._margn_pair(MARGN_FIELDS, row, '今日餘額')
    assert mb == 29657.0
    assert sb == 33.0


def test_snap_margn_parses_lots_to_shares():
    """模擬 MI_MARGN JSON：今日餘額(張) → API 股。"""
    ca._SNAP.clear()
    payload = {
        'stat': 'OK',
        'tables': [
            {
                'title': '信用交易統計',
                'fields': ['項目', '買進', '賣出', '現金(券)償還', '前日餘額', '今日餘額'],
                'data': [['融資', '1', '1', '0', '1', '1']],
            },
            {
                'title': '融資融券彙總 (全部)',
                'fields': MARGN_FIELDS,
                'data': [[
                    '2330', '台積電',
                    '262', '513', '41', '29,949', '29,657', '6,483,092',
                    '8', '3', '0', '38', '33', '6,483,092',
                    '0', '',
                ]],
            },
        ],
    }

    def fake_fetch(url, timeout=8):
        return payload

    old = ca._fetch_json
    ca._fetch_json = fake_fetch
    try:
        by = ca.snap_margn('20260807')
        assert by is not None
        assert '2330' in by
        assert by['2330']['marginBalance'] == 29657.0 * 1000
        assert by['2330']['shortBalance'] == 33.0 * 1000
        # 融資買進−賣出 = 262−513 = −251 張 → 股
        assert by['2330']['marginChange'] == -251.0 * 1000
        assert by['2330']['shortChange'] == (8 - 3) * 1000
    finally:
        ca._fetch_json = old
        ca._SNAP.clear()


def test_snap_t86_dealer_not_zero_when_foreign_dealer_zero():
    ca._SNAP.clear()
    row = ['2330', '台積電'] + ['0'] * 17
    row[4] = '641,660'
    row[7] = '0'
    row[10] = '61,000'
    row[11] = '1,242,950'
    row[18] = '1,945,610'
    payload = {'stat': 'OK', 'fields': T86_FIELDS, 'data': [row]}

    def fake_fetch(url, timeout=8):
        return payload

    old = ca._fetch_json
    ca._fetch_json = fake_fetch
    try:
        by = ca.snap_t86('20260807')
        assert by['2330']['dealer'] == 1242950.0
        assert by['2330']['foreign'] == 641660.0
        assert by['2330']['trust'] == 61000.0
    finally:
        ca._fetch_json = old
        ca._SNAP.clear()
