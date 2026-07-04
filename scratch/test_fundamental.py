import sys, os, urllib.request, json

# 模擬 server.py 中的相關函數與資料結構
_openapi_ds = {}

def _pick_num(row, includes, excludes=None):
    includes = [s.lower() for s in includes]
    excludes = [s.lower() for s in (excludes or [])]
    for k, v in row.items():
        if all(s in k.lower() for s in includes) and not any(e in k.lower() for e in excludes):
            try:
                return float(str(v).replace(',', '').strip())
            except Exception:
                return None
    return None

def _openapi_lookup(dataset_names, clean_code):
    import datetime
    today = datetime.date.today().strftime('%Y%m%d')
    for ds in dataset_names:
        cached = _openapi_ds.get(ds)
        if not cached or cached[0] != today:
            try:
                if ds.startswith('tpex:'):
                    url = f'https://www.tpex.org.tw/openapi/v1/{ds[5:]}'
                elif '/' in ds:
                    url = f'https://openapi.twse.com.tw/v1/{ds}'
                else:
                    url = f'https://openapi.twse.com.tw/v1/opendata/{ds}'
                print('[lookup] Fetching url:', url)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    arr = json.loads(resp.read())
                idx = {}
                for row in arr:
                    code = (row.get('公司代號') or row.get('證券代號') or
                            row.get('Code') or row.get('SecuritiesCompanyCode') or
                            row.get('股票代號') or '').strip()
                    if code:
                        idx[code] = row
                _openapi_ds[ds] = (today, idx)
                cached = _openapi_ds[ds]
            except Exception as e:
                print(f'[lookup] openapi {ds} failed: {e}')
                _openapi_ds[ds] = (today, {})
                cached = _openapi_ds[ds]
        row = cached[1].get(clean_code)
        if row:
            return row
    return None

# 測試 '6683'
clean = '6683'
rev = _openapi_lookup(['t187ap05_L', 'tpex:mopsfin_t187ap05_O'], clean)
print('rev result:', rev)
if rev:
    revenue = {
        'period':    rev.get('資料年月'),
        'monthRev':  _pick_num(rev, ['當月營收'], ['累計']),
        'yoyPct':    _pick_num(rev, ['去年同月增減']),
        'momPct':    _pick_num(rev, ['上月比較增減']),
        'cumRev':    _pick_num(rev, ['當月累計營收']),
        'cumYoyPct': _pick_num(rev, ['累計', '前期比較增減']),
    }
    print('Processed revenue:', revenue)

inc = _openapi_lookup(['t187ap06_L_ci', 'tpex:mopsfin_t187ap06_O_ci', 't187ap06_L'], clean)
print('inc result:', inc)
if inc:
    sales = _pick_num(inc, ['營業收入'], ['成本', '毛利', '費用', '外', '淨額'])
    gross = _pick_num(inc, ['營業毛利'])
    op = _pick_num(inc, ['營業利益'])
    net = _pick_num(inc, ['本期淨利']) or _pick_num(inc, ['本期綜合損益總額']) or _pick_num(inc, ['淨利', '母公司'])
    eps = _pick_num(inc, ['基本每股盈餘'])
    pct = lambda a, b: round(a / b * 100, 2) if (a is not None and b) else None
    income = {
        'period':       inc.get('資料年度') or inc.get('資料季別') or inc.get('年度'),
        'sales':        sales, 'eps': eps,
        'grossMargin':  pct(gross, sales),
        'opMargin':     pct(op, sales),
        'netMargin':    pct(net, sales),
    }
    print('Processed income:', income)
