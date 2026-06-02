#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Stock Terminal v3.8 — ETF Catalog 擴充 (台股/美股分類)
# ------------------------------------------------------------
# 1. 既有條目補 market="TW"
# 2. 各分類補上主流美股 ETF (market="US", enabled=False)
#    —— 美股無 MoneyDJ 持股 delta，故不進台股追蹤，僅供分類/快速載入
# 3. 順手補幾檔常見台股 ETF
# 去重鍵 = (code, market)。會先備份 etf_catalog.json.bak。
# 用法： python expand_etf_catalog.py
# 可重複執行（idempotent）。
# ============================================================
import json, os, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(BASE, 'etf_catalog.json')

# 各分類要補的美股 ETF： 分類名稱 -> [(code, name), ...]
US_ADD = {
    '市值型大盤': [
        ('SPY', 'SPDR S&P 500'), ('VOO', 'Vanguard S&P 500'), ('IVV', 'iShares Core S&P 500'),
        ('VTI', 'Vanguard Total US Market'), ('QQQ', 'Invesco Nasdaq 100'), ('QQQM', 'Invesco Nasdaq 100 (low fee)'),
        ('DIA', 'SPDR Dow Jones'), ('IWM', 'iShares Russell 2000'), ('VT', 'Vanguard Total World'),
        ('RSP', 'Invesco S&P 500 Equal Weight'),
    ],
    '科技/半導體': [
        ('SMH', 'VanEck Semiconductor'), ('SOXX', 'iShares Semiconductor'), ('XLK', 'Tech Select Sector'),
        ('VGT', 'Vanguard Information Tech'), ('IGV', 'iShares Expanded Tech-Software'),
        ('SKYY', 'First Trust Cloud'), ('ARKK', 'ARK Innovation'), ('AIQ', 'Global X AI & Tech'),
        ('BOTZ', 'Global X Robotics & AI'),
    ],
    '高股息': [
        ('SCHD', 'Schwab US Dividend'), ('VYM', 'Vanguard High Dividend'), ('HDV', 'iShares Core High Dividend'),
        ('DGRO', 'iShares Dividend Growth'), ('JEPI', 'JPMorgan Equity Premium Income'),
        ('JEPQ', 'JPMorgan Nasdaq Equity Premium'), ('SPYD', 'SPDR S&P 500 High Dividend'),
    ],
    '槓桿/反向': [
        ('TQQQ', 'ProShares UltraPro QQQ 3x'), ('SQQQ', 'ProShares UltraPro Short QQQ -3x'),
        ('SOXL', 'Direxion Semi Bull 3x'), ('SOXS', 'Direxion Semi Bear 3x'),
        ('UPRO', 'ProShares UltraPro S&P500 3x'), ('SPXU', 'ProShares UltraPro Short S&P -3x'),
        ('TMF', 'Direxion 20Y Treasury Bull 3x'), ('TNA', 'Direxion Small Cap Bull 3x'),
        ('TSLL', 'Direxion TSLA Bull 2x'), ('NVDL', 'GraniteShares NVDA 2x'),
    ],
    '海外股票': [
        ('VEA', 'Vanguard Developed Markets'), ('VWO', 'Vanguard Emerging Markets'),
        ('EFA', 'iShares MSCI EAFE'), ('EEM', 'iShares MSCI Emerging'), ('VXUS', 'Vanguard Total Intl'),
        ('EWJ', 'iShares MSCI Japan'), ('MCHI', 'iShares MSCI China'), ('INDA', 'iShares MSCI India'),
        ('EWT', 'iShares MSCI Taiwan'),
    ],
    '債券型': [
        ('TLT', 'iShares 20+ Year Treasury'), ('IEF', 'iShares 7-10 Year Treasury'),
        ('SHY', 'iShares 1-3 Year Treasury'), ('AGG', 'iShares Core US Aggregate Bond'),
        ('BND', 'Vanguard Total Bond'), ('LQD', 'iShares Investment Grade Corp'),
        ('HYG', 'iShares High Yield Corp'), ('TIP', 'iShares TIPS'), ('BIL', 'SPDR 1-3 Month T-Bill'),
    ],
    'REITs/不動產': [
        ('VNQ', 'Vanguard Real Estate'), ('SCHH', 'Schwab US REIT'), ('IYR', 'iShares US Real Estate'),
        ('VNQI', 'Vanguard Global ex-US Real Estate'),
    ],
    '商品/原物料': [
        ('GLD', 'SPDR Gold'), ('IAU', 'iShares Gold'), ('SLV', 'iShares Silver'),
        ('USO', 'US Oil Fund'), ('DBC', 'Invesco DB Commodity'), ('PDBC', 'Invesco Optimum Yield Commodity'),
        ('URA', 'Global X Uranium'), ('LIT', 'Global X Lithium'),
    ],
    'ESG/永續': [
        ('ESGU', 'iShares ESG Aware MSCI USA'), ('ICLN', 'iShares Global Clean Energy'),
        ('TAN', 'Invesco Solar'), ('SUSA', 'iShares MSCI USA ESG'),
    ],
    '中小型/特定主題': [
        ('XLE', 'Energy Select Sector'), ('XLF', 'Financial Select Sector'), ('XLV', 'Health Care Select'),
        ('XLY', 'Consumer Discretionary Select'), ('XLP', 'Consumer Staples Select'),
        ('XLI', 'Industrial Select'), ('XLB', 'Materials Select'), ('XLU', 'Utilities Select'),
        ('XLRE', 'Real Estate Select'), ('XLC', 'Communication Services Select'),
        ('IBB', 'iShares Biotech'), ('ITA', 'iShares US Aerospace & Defense'),
        ('JETS', 'US Global Jets'), ('XBI', 'SPDR S&P Biotech'),
    ],
}

# 順手補的台股 ETF（market="TW"）：分類 -> [(code, name)]
TW_ADD = {
    '市值型大盤': [('00905', 'FT臺灣Smart'), ('00921', '兆豐龍頭等權重'), ('006208', '富邦台50')],
    '高股息': [('00919', '群益台灣精選高息'), ('00929', '復華台灣科技優息'), ('00940', '元大台灣價值高息'),
               ('00939', '統一台灣高息動能'), ('00943', '兆豐電子高息等權'), ('00713', '元大台灣高息低波')],
    '科技/半導體': [('00891', '中信關鍵半導體'), ('00892', '富邦台灣半導體'), ('00904', '新光臺灣半導體30'),
                    ('00913', '兆豐台灣晶圓製造')],
    '債券型': [('00679B', '元大美債20年'), ('00772B', '中信高評級公司債'), ('00937B', '群益ESG投等債20+')],
    '主動式 ETF': [('00982A', '主動統一台股增長'), ('00983A', '主動野村臺灣優選'), ('00985A', '主動群益台灣強棒')],
}


def norm(s):
    return (s or '').strip().upper()


def main():
    with open(CAT, encoding='utf-8') as f:
        cat = json.load(f)
    shutil.copyfile(CAT, CAT + '.bak')

    cats = cat.get('categories', [])
    by_name = {c.get('name'): c for c in cats}

    # 1) 既有條目補 market="TW"
    tw_tagged = 0
    for c in cats:
        for e in c.get('etfs', []):
            if not e.get('market'):
                e['market'] = 'TW'
                tw_tagged += 1

    def existing_keys(c):
        return {(norm(e.get('code')), e.get('market', 'TW')) for e in c.get('etfs', [])}

    def add_entries(cat_name, items, market, enabled):
        c = by_name.get(cat_name)
        if not c:
            c = {'name': cat_name, 'etfs': []}
            cats.append(c)
            by_name[cat_name] = c
        keys = existing_keys(c)
        added = 0
        for code, name in items:
            k = (norm(code), market)
            if k in keys:
                continue
            c['etfs'].append({'code': code, 'name': name, 'market': market, 'enabled': enabled})
            keys.add(k)
            added += 1
        return added

    us_added = sum(add_entries(n, items, 'US', False) for n, items in US_ADD.items())
    tw_added = sum(add_entries(n, items, 'TW', False) for n, items in TW_ADD.items())

    cat['version'] = 'v3.8'
    cat['note'] = (cat.get('note', '') + ' | v3.8: market split TW/US; US ETFs enabled=False (no MoneyDJ delta).').strip(' |')

    with open(CAT, 'w', encoding='utf-8') as f:
        json.dump(cat, f, ensure_ascii=False, indent=2)

    print(f'TW tagged on existing : {tw_tagged}')
    print(f'US ETFs added         : {us_added}')
    print(f'TW ETFs added         : {tw_added}')
    tot = sum(len(c.get('etfs', [])) for c in cats)
    print(f'Total entries now     : {tot}')
    print('Backup: etf_catalog.json.bak  | restart server to reload.')


if __name__ == '__main__':
    main()
