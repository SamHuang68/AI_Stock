# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import sector_flow  # noqa: E402


class SectorFlowTest(unittest.TestCase):
    def test_dated_twse_stock_table_normalizes_roc_date_and_signed_change(self):
        payload = {
            'stat': 'OK', 'date': '1150813',
            'tables': [{'fields': ['證券代號', '證券名稱', '成交金額', '收盤價', '漲跌(+/-)', '漲跌價差'],
                        'data': [['2330', '台積電', '12,345,678', '2,435.00', '-', '15.00']]}],
        }
        rows = sector_flow.parse_twse_daily_stock_table(payload)
        self.assertEqual(rows[0]['Date'], '20260813')
        self.assertEqual(rows[0]['TradeValue'], '12,345,678')
        self.assertEqual(rows[0]['Change'], -15.0)

    def test_official_industry_turnover_joins_index_names_without_double_counting_rollups(self):
        rows = sector_flow.attach_sector_metrics([
            {'name': '電子零組件類指數', 'changePct': 2.1},
            {'name': '電腦及週邊設備類指數', 'changePct': 1.5},
            {'name': '電子類指數', 'changePct': 1.8},
        ], industry_turnover_yi={'電子零組件業': 320, '電腦及週邊設備業': 280})
        out = sector_flow.build_sector_flow(rows, total_turnover_yi=600)
        self.assertTrue(out['flowEligible'])
        self.assertEqual(out['turnoverCoveragePct'], 100.0)
        self.assertEqual(out['turnoverScope'], 'TWSE_FOUR_DIGIT_SECURITIES_BY_INDUSTRY')
        self.assertEqual(out['rows'][0]['marketSharePct'], 53.333)
        self.assertIsNone(out['rows'][2]['marketSharePct'])

    def test_price_only_rows_are_not_mislabeled_as_fund_flow(self):
        out = sector_flow.build_sector_flow([
            {'name': '半導體', 'changePct': 2.0},
            {'name': '金融', 'changePct': -1.0},
        ], source='TWSE MI_INDEX IND')
        self.assertEqual(out['mode'], 'participation_proxy')
        self.assertFalse(out['flowEligible'])
        self.assertIsNone(out['rows'][0]['marketSharePct'])
        self.assertEqual(out['participationPct'], 50.0)

    def test_turnover_share_hhi_and_rs20(self):
        out = sector_flow.build_sector_flow([
            {'name': 'A', 'changePct': 1, 'turnoverYi': 60, 'return20Pct': 8},
            {'name': 'B', 'changePct': 2, 'turnoverYi': 40, 'return20Pct': 3},
        ], total_turnover_yi=100, benchmark_return20_pct=2)
        self.assertTrue(out['flowEligible'])
        self.assertEqual(out['top3SharePct'], 100.0)
        self.assertEqual(out['hhi'], 5200.0)
        self.assertEqual(out['rows'][0]['rs20VsBenchmarkPct'], 6.0)

    def test_partial_or_proxy_turnover_is_not_called_fund_flow(self):
        partial = sector_flow.build_sector_flow([
            {'name': 'A', 'changePct': 1, 'turnoverYi': 60},
            {'name': 'B', 'changePct': -1},
        ], total_turnover_yi=100)
        proxy = sector_flow.build_sector_flow([
            {'name': 'A', 'changePct': 1, 'turnoverYi': 100},
        ], total_turnover_yi=100, proxy_basket=True)
        self.assertEqual(partial['mode'], 'partial_turnover')
        self.assertFalse(partial['flowEligible'])
        self.assertIsNone(partial['hhi'])
        self.assertFalse(proxy['flowEligible'])


# 2026-10-21 證交所 MI_INDEX type=IND 第一張表「價格指數(臺灣證券交易所)」的 56 個原始名稱（依原順序）。
TWSE_IND_NAMES_20261021 = [
    '寶島股價指數', '發行量加權股價指數', '臺灣公司治理100指數', '臺灣50指數', '臺灣50權重上限30%指數',
    '臺灣中型100指數', '臺灣資訊科技指數', '臺灣發達指數', '臺灣高股息指數', '臺灣就業99指數', '臺灣高薪100指數',
    '未含金融指數', '未含電子指數', '未含金融電子指數', '小型股300指數', '水泥窯製類指數', '塑膠化工類指數',
    '機電類指數', '水泥類指數', '食品類指數', '塑膠類指數', '紡織纖維類指數', '電機機械類指數', '電器電纜類指數',
    '化學生技醫療類指數', '化學類指數', '生技醫療類指數', '玻璃陶瓷類指數', '造紙類指數', '鋼鐵類指數',
    '橡膠類指數', '汽車類指數', '電子工業類指數', '半導體類指數', '電腦及週邊設備類指數', '光電類指數',
    '通信網路類指數', '電子零組件類指數', '電子通路類指數', '資訊服務類指數', '其他電子類指數', '建材營造類指數',
    '航運類指數', '觀光餐旅類指數', '金融保險類指數', '貿易百貨類指數', '油電燃氣類指數', '綠能環保類指數',
    '數位雲端類指數', '運動休閒類指數', '居家生活類指數', '其他類指數', '臺指日報酬兩倍指數', '臺指反向一倍指數',
    '電子類兩倍槓桿指數', '電子類反向指數',
]
# 證交所上市產業分類的 32 個單一產業。
TWSE_SINGLE_INDUSTRIES = [
    '水泥', '食品', '塑膠', '紡織纖維', '電機機械', '電器電纜', '化學', '生技醫療', '玻璃陶瓷', '造紙', '鋼鐵',
    '橡膠', '汽車', '半導體', '電腦及週邊設備', '光電', '通信網路', '電子零組件', '電子通路', '資訊服務',
    '其他電子', '建材營造', '航運', '觀光餐旅', '金融保險', '貿易百貨', '油電燃氣', '綠能環保', '數位雲端',
    '運動休閒', '居家生活', '其他',
]


class TwseIndustryIndexTest(unittest.TestCase):
    def test_official_table_keeps_exactly_the_single_industries(self):
        picked = [name[:-len('類指數')] for name in TWSE_IND_NAMES_20261021
                  if sector_flow.is_twse_industry_index(name)]
        self.assertEqual(picked, TWSE_SINGLE_INDUSTRIES)

    def test_broad_thematic_leveraged_inverse_and_composite_indices_are_not_industries(self):
        for name in ('發行量加權股價指數', '臺灣50指數', '小型股300指數', '未含金融電子指數', '臺指日報酬兩倍指數',
                     '電子類兩倍槓桿指數', '電子類反向指數', '電子工業類指數', '化學生技醫療類指數', '水泥窯製類指數',
                     '半導體', '類指數', '', None):
            self.assertFalse(sector_flow.is_twse_industry_index(name), name)
        self.assertTrue(sector_flow.is_twse_industry_index(' 半導體類指數 '))

    def test_participation_counts_only_industries_and_keeps_every_row(self):
        rows = [
            {'name': '半導體', 'changePct': 1.0, 'industry': True},
            {'name': '航運', 'changePct': -1.0, 'industry': True},
            {'name': '臺指日報酬兩倍', 'changePct': 3.0, 'industry': False},
            {'name': '發行量加權股價', 'changePct': 1.2, 'industry': False},
            {'name': '代理籃', 'changePct': 2.0},  # 沒有標記的列（Yahoo 代理籃）照舊計入
        ]
        out = sector_flow.build_sector_flow(rows)
        self.assertAlmostEqual(out['participationPct'], 66.67)
        self.assertEqual([r['name'] for r in out['rows']], [r['name'] for r in rows], '非產業列要留給類股歷史的 RS20 基準')
        self.assertEqual([r['name'] for r in sector_flow.industry_rows(out['rows'])], ['半導體', '航運', '代理籃'])

    def test_non_industry_turnover_does_not_enter_concentration(self):
        rows = [
            {'name': '半導體', 'changePct': 1.0, 'industry': True, 'turnoverYi': 300},
            {'name': '航運', 'changePct': -1.0, 'industry': True, 'turnoverYi': 100},
            {'name': '電子工業', 'changePct': 0.8, 'industry': False, 'turnoverYi': 300},
        ]
        out = sector_flow.build_sector_flow(rows, total_turnover_yi=400)
        self.assertEqual(out['top3SharePct'], 100.0)
        self.assertIsNone(out['rows'][2]['marketSharePct'])


if __name__ == '__main__':
    unittest.main()
