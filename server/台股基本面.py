"""台股基本面的共用來源與欄位契約；不同業別不混用財報公式。"""
from __future__ import annotations

import math
import re
from datetime import date

REVENUE_DATASETS = ('t187ap05_L', 'tpex:mopsfin_t187ap05_O')
INDUSTRIES = {'ci': '一般業', 'fh': '金控業', 'basi': '金融業',
              'ins': '保險業', 'bd': '證券期貨業', 'mim': '異業'}
INCOME_DATASETS = tuple((f't187ap06_L_{kind}', kind, '上市') for kind in INDUSTRIES) + tuple(
    (f'tpex:mopsfin_t187ap06_O_{kind}', kind, '上櫃') for kind in INDUSTRIES)


def dataset_url(dataset):
    if dataset.startswith('tpex:'):
        return 'https://www.tpex.org.tw/openapi/v1/' + dataset[5:]
    return 'https://openapi.twse.com.tw/v1/' + (dataset if '/' in dataset else 'opendata/' + dataset)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(',', '').strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def pick(row, *names):
    for name in names:
        value = number(row.get(name))
        if value is not None:
            return value
    return None


def source_date(value):
    raw = re.sub(r'[-/]', '', str(value or ''))
    try:
        if len(raw) in (7, 8) and raw.isdigit():
            year = int(raw[:-4]) + (1911 if len(raw) == 7 else 0)
            return date(year, int(raw[-4:-2]), int(raw[-2:])).isoformat()
    except ValueError:
        pass
    return None


def month_period(value):
    raw = re.sub(r'[-/]', '', str(value or ''))
    try:
        if len(raw) in (5, 6) and raw.isdigit():
            year = int(raw[:-2]) + (1911 if len(raw) == 5 else 0)
            return date(year, int(raw[-2:]), 1).strftime('%Y-%m')
    except ValueError:
        pass
    return None


def revenue_record(row, source=None, now=None):
    """金額保留官方千元單位，期別與出表日期分開，零值不當成缺值。"""
    if not row:
        return None
    period = row.get('資料年月') or row.get('RevenueMonth') or row.get('period')
    out = {
        'period': period,
        'monthRev': pick(row, 'monthRev', '營業收入-當月營收', '當月營收'),
        'yoyPct': pick(row, 'yoyPct', '營業收入-去年同月增減(%)', '營業收入-去年同月增減（％）', '去年同月增減'),
        'momPct': pick(row, 'momPct', '營業收入-上月比較增減(%)', '營業收入-上月比較增減（％）', '上月比較增減'),
        'cumRev': pick(row, 'cumRev', '累計營業收入-當月累計營收'),
        'cumYoyPct': pick(row, 'cumYoyPct', '累計營業收入-前期比較增減(%)', '累計營業收入-前期比較增減（％）'),
        'unit': '新臺幣千元', 'unitMultiplier': 1000,
        'source': source or row.get('source'),
        'sourceDate': source_date(row.get('出表日期') or row.get('Date')) or row.get('sourceDate'),
        'periodLabel': month_period(period),
    }
    if not any(out[key] is not None for key in ('monthRev', 'yoyPct', 'momPct', 'cumRev', 'cumYoyPct')):
        return None
    today = now or date.today()
    expected = date(today.year - (today.month == 1), 12 if today.month == 1 else today.month - 1, 1)
    out['expectedPeriod'] = expected.strftime('%Y-%m')
    out['priorPeriod'] = bool(out['periodLabel'] and out['periodLabel'] < out['expectedPeriod'])
    origin = out['source'] or ''
    out['sourceName'] = ('公開資訊觀測站（上櫃）' if origin == 'MOPS:otc' else
                         '公開資訊觀測站（上市）' if origin == 'MOPS:sii' else
                         '櫃買中心月營收' if origin.startswith('tpex:') else
                         '證交所月營收' if origin else '來源未附名稱')
    return out


def load_revenue(code, lookup, monthly_revenue, now=None, markets=('sii', 'otc')):
    """所有消費端沿用同一官方總表與 MOPS 逐股最近期回補。"""
    row = lookup(list(REVENUE_DATASETS), code)
    revenue = revenue_record(row, now=now)
    if revenue and revenue['monthRev'] is not None and revenue['yoyPct'] is not None:
        return revenue
    candidates = [revenue] if revenue else []
    for market in markets:
        fallback = revenue_record(monthly_revenue(market, code), 'MOPS:' + market, now)
        if fallback:
            candidates.append(fallback)
            break
    # 同一期才優先選欄位完整者，不能以舊期 YoY 覆蓋新期營收。
    return max(candidates, key=lambda item: (item['periodLabel'] or '',
               sum(item[k] is not None for k in ('monthRev', 'yoyPct', 'momPct', 'cumYoyPct'))),
               default=None)


def income_record(row, kind, source):
    if not row:
        return None
    normalized = {str(key).replace('（', '(').replace('）', ')'): value for key, value in row.items()}
    year = row.get('年度') or row.get('資料年度') or row.get('Year')
    quarter = row.get('季別') or row.get('資料季別') or row.get('Season')
    try:
        year = int(year)
        year += 1911 if year < 1911 else 0
        quarter = int(quarter)
        period = f'{year}年第{quarter}季累計' if 1 <= quarter <= 4 else None
    except (ValueError, TypeError):
        period = None
    eps = pick(normalized, '基本每股盈餘(元)', '基本每股盈餘')
    net = pick(normalized, '本期稅後淨利(淨損)', '本期淨利(淨損)', '本期淨利')
    parent = pick(normalized, '淨利(淨損)歸屬於母公司業主', '淨利(損)歸屬於母公司業主')
    sales = pick(normalized, '營業收入') if kind == 'ci' else None
    gross = pick(normalized, '營業毛利(毛損)淨額', '營業毛利(毛損)', '營業毛利')
    operating = pick(normalized, '營業利益(損失)', '營業利益')
    pct = lambda value: round(value / sales * 100, 2) if value is not None and sales and sales > 0 else None
    if all(value is None for value in (eps, net, parent, sales)):
        return None
    return {
        'period': period, 'year': year, 'quarter': quarter,
        'industry': INDUSTRIES[kind], 'industryCode': kind,
        'source': source, 'sourceDate': source_date(row.get('出表日期') or row.get('Date')),
        'sourceName': ('櫃買中心' if source.startswith('tpex:') else '證交所') + ' · ' + INDUSTRIES[kind],
        'unit': '新臺幣千元', 'unitMultiplier': 1000, 'epsUnit': '新臺幣元',
        'sales': sales, 'eps': eps, 'netIncome': net, 'parentNetIncome': parent,
        'grossMargin': pct(gross) if kind == 'ci' else None,
        'opMargin': pct(operating) if kind == 'ci' else None,
        'netMargin': pct(net) if kind == 'ci' else None,
        'marginStatus': 'available' if kind == 'ci' else 'not_applicable',
        'marginNote': None if kind == 'ci' else '此業別不套用一般業三率與評分；改列 EPS 與稅後損益。',
    }


def load_income(code, lookup):
    for dataset, kind, _board in INCOME_DATASETS:
        row = lookup([dataset], code)
        income = income_record(row, kind, dataset)
        if income:
            return income
    return None
