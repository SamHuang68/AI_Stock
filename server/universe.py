"""universe.py — 全台股 + 美股 代號↔名稱 lookup,可更新(供前端權威判市場/補名)。

市場判定本質由代號格式決定(台股=數字、美股=字母,無重疊),本表額外提供
「名稱 + 存在驗證」,且可更新讓後續新上市的股票/ETF 即時被收錄。

來源:
  TW — TWSE OpenAPI(上市個股)+ TPEx OpenAPI(上櫃)+ data/etf_catalog.json(ETF,含 00xxx)
  US — NASDAQ Trader Symbol Directory(nasdaqlisted + otherlisted,涵蓋 NYSE/AMEX/NASDAQ)
快取:data/universe.json
"""
import json
import os
import re
import sys
import time
import urllib.request

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CACHE = os.path.join(_BASE, 'data', 'universe.json')
_TW_CODE = re.compile(r'^[0-9]{4}[0-9A-Z]{0,2}$')   # 2330 / 0050 / 00631L / 020000…
_US_SYM = re.compile(r'^[A-Z][A-Z0-9.\-]{0,7}$')


def _fetch_json(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _fetch_text(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def _has_cjk(s):
    return any('一' <= ch <= '鿿' for ch in (s or ''))


def fetch_tw():
    """回傳 {code: name}(上市股 + 上櫃股 + ETF)。"""
    out = {}

    def scan(url, ckeys, nkeys):
        try:
            arr = _fetch_json(url)
        except Exception as e:
            print(f'[universe] TW scan failed {url}: {e}')
            return
        for row in arr:
            if not isinstance(row, dict):
                continue
            code = ''
            for k in ckeys:
                if row.get(k):
                    code = str(row[k]).strip()
                    break
            if not _TW_CODE.match(code):
                for v in row.values():
                    s = str(v).strip()
                    if _TW_CODE.match(s):
                        code = s
                        break
            if not _TW_CODE.match(code):
                continue
            name = ''
            for k in nkeys:
                if row.get(k):
                    name = str(row[k]).strip()
                    break
            # 中文名優先(濾掉英文重複)
            if code not in out or (_has_cjk(name) and not _has_cjk(out.get(code))):
                out[code] = name or out.get(code, '')

    scan('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', ('Code',), ('Name', '名稱', '證券名稱'))
    scan('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes',
         ('SecuritiesCompanyCode', 'Code', 'CompanyCode', '公司代號'),
         ('CompanyName', 'SecuritiesCompanyName', '公司名稱', '公司簡稱', 'Name', '名稱'))
    # ETF 目錄(權威 ETF 清單;含 00xxx/00xxxL,STOCK_DAY_ALL 不一定有)
    try:
        with open(os.path.join(_BASE, 'data', 'etf_catalog.json'), encoding='utf-8') as f:
            cat = json.load(f)
        for grp in cat.get('categories', []):
            for e in grp.get('etfs', []):
                c = str(e.get('code', '')).strip()
                if _TW_CODE.match(c):     # 台股 ETF(數字代號)
                    nm = str(e.get('name', '')).strip()
                    if nm:
                        out[c] = nm
                    else:
                        out.setdefault(c, '')
    except Exception as e:
        print(f'[universe] etf_catalog failed: {e}')
    return out


def fetch_us():
    """回傳 {symbol: name}(NASDAQ + NYSE/AMEX,含 ETF)。"""
    out = {}

    def scan(url):
        try:
            txt = _fetch_text(url)
        except Exception as e:
            print(f'[universe] US scan failed {url}: {e}')
            return
        for ln in txt.splitlines()[1:]:
            if ln.startswith('File Creation Time') or '|' not in ln:
                continue
            parts = ln.split('|')
            sym = parts[0].strip().upper()
            name = parts[1].strip() if len(parts) > 1 else ''
            if _US_SYM.match(sym):
                out[sym] = name

    scan('https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt')   # Symbol|Security Name|…
    scan('https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt')    # ACT Symbol|Security Name|…
    return out


# ── 每股四大指標(量價 / 估值 / 三率+EPS)+ 中英名 ───────────────────────
# 來源皆官方 OpenAPI;JSON key 中英混雜(TWSE 多英文、財報多中文),故一律「中英
# 雙語子字串比對 + 排除子項」(同籌碼修法),配對到才填、否則留 null(優雅降級,
# 絕不顯示錯數)。可一鍵更新讓後續新上市櫃及最新指標即時收錄。

def _row_code(row):
    """從一列(dict)抽出台股代號。"""
    for k, v in row.items():
        kl = k.lower()
        if ('代號' in k) or ('code' in kl) or ('symbol' in kl):
            s = str(v).strip()
            if _TW_CODE.match(s):
                return s
    for v in row.values():
        s = str(v).strip()
        if _TW_CODE.match(s):
            return s
    return None


def _row_num(row, subs, avoid=()):
    """抽出第一個 key 含 subs 任一、且不含 avoid 的數值欄(去千分位/%)。"""
    for k, v in row.items():
        kl = k.lower()
        if not any((s in k) or (s.lower() in kl) for s in subs):
            continue
        if any((a in k) or (a.lower() in kl) for a in avoid):
            continue
        try:
            s = str(v).replace(',', '').replace('%', '').replace(' ', '').strip()
            if s in ('', '--', '---', 'N/A', 'null', 'None'):
                return None
            return float(s)
        except Exception:
            continue
    return None


def _row_str(row, subs):
    for k, v in row.items():
        kl = k.lower()
        if any((s in k) or (s.lower() in kl) for s in subs):
            s = str(v).strip()
            if s and s not in ('--', 'N/A'):
                return s
    return None


def _slot(meta, code, board=None):
    m = meta.get(code)
    if m is None:
        m = {'en': None, 'board': board,
             'pe': None, 'pb': None, 'yield': None, 'eps': None,
             'gross': None, 'op': None, 'net': None,
             'close': None, 'chg': None, 'vol': None, 'mktcap': None}
        meta[code] = m
    if board and not m.get('board'):
        m['board'] = board
    return m


def _scan_rows(url):
    try:
        arr = _fetch_json(url)
    except Exception as e:
        print(f'[universe.meta] fetch failed {url}: {e}')
        return []
    return arr if isinstance(arr, list) else []


def fetch_tw_meta(shares_map):
    """回傳 {code: {en, board, pe,pb,yield,eps, gross,op,net, close,chg,vol,mktcap}}。
    shares_map: {code: 發行股數} 供算市值(close×shares)。"""
    meta = {}

    # 1) 量價 ── 上市 STOCK_DAY_ALL(英文 key:ClosingPrice/Change/TradeVolume)
    for row in _scan_rows('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL'):
        if not isinstance(row, dict):
            continue
        code = _row_code(row)
        if not code:
            continue
        m = _slot(meta, code, '上市')
        close = _row_num(row, ['ClosingPrice', '收盤'], avoid=['Open', 'High', 'Low', 'Previous', '開', '高', '低', '昨'])
        chg = _row_num(row, ['Change', '漲跌'], avoid=['Percent', '%', 'PreviousClose'])
        vol = _row_num(row, ['TradeVolume', '成交股數', 'Volume'], avoid=['TradeValue', 'Trans', '金額', '筆'])
        m['close'] = close if close is not None else m['close']
        if close is not None and chg is not None and (close - chg) != 0:
            m['chg'] = round(chg / (close - chg) * 100, 2)
        m['vol'] = vol if vol is not None else m['vol']

    # 1b) 量價 ── 上櫃 TPEx 主板每日收盤
    for row in _scan_rows('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes'):
        if not isinstance(row, dict):
            continue
        code = _row_code(row)
        if not code:
            continue
        m = _slot(meta, code, '上櫃')
        close = _row_num(row, ['Close', '收盤'], avoid=['Open', 'High', 'Low', 'Previous', 'Last', '開', '高', '低', '昨', '前'])
        chg = _row_num(row, ['Change', '漲跌'], avoid=['Percent', '%', 'Previous'])
        vol = _row_num(row, ['TradingShares', 'TradeVolume', '成交股數', 'Volume'], avoid=['Amount', 'Value', '金額', '筆'])
        m['close'] = close if close is not None else m['close']
        if close is not None and chg is not None and (close - chg) != 0:
            m['chg'] = round(chg / (close - chg) * 100, 2)
        m['vol'] = vol if vol is not None else m['vol']

    # 2) 估值 ── 上市 BWIBBU_ALL(本益比/殖利率/股價淨值比)
    for row in _scan_rows('https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL'):
        if not isinstance(row, dict):
            continue
        code = _row_code(row)
        if not code:
            continue
        m = _slot(meta, code, '上市')
        m['pe'] = m['pe'] if m['pe'] is not None else _row_num(row, ['PEratio', '本益比'], avoid=['PB', '淨值'])
        m['pb'] = m['pb'] if m['pb'] is not None else _row_num(row, ['PBratio', '淨值比', '股價淨值'])
        m['yield'] = m['yield'] if m['yield'] is not None else _row_num(row, ['DividendYield', '殖利率'], avoid=['Year', '年度'])

    # 2b) 估值 ── 上櫃 TPEx 本益比/殖利率/淨值比
    for row in _scan_rows('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis'):
        if not isinstance(row, dict):
            continue
        code = _row_code(row)
        if not code:
            continue
        m = _slot(meta, code, '上櫃')
        m['pe'] = m['pe'] if m['pe'] is not None else _row_num(row, ['PE', '本益比'], avoid=['PB', '淨值'])
        m['pb'] = m['pb'] if m['pb'] is not None else _row_num(row, ['PB', '淨值比', '股價淨值'])
        m['yield'] = m['yield'] if m['yield'] is not None else _row_num(row, ['Yield', '殖利率'], avoid=['Year', '年度'])

    # 3) 三率 + EPS ── 綜合損益表(僅上市 _L_ci;中文 key)
    # 註:上櫃(_O)綜合損益表 TWSE/TPEx OpenAPI 均未提供 per-company 端點(實機核
    # 對 TPEx swagger:t187ap46_O_* 為「公司治理」非財報;TWSE 僅 _L)。故上櫃三率/
    # EPS 暫留 null(量價與估值仍由 TPEx mainboard 端點正常填入)。
    for url, board in (
        ('https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci', '上市'),
    ):
        for row in _scan_rows(url):
            if not isinstance(row, dict):
                continue
            code = _row_code(row)
            if not code:
                continue
            m = _slot(meta, code, board)
            rev = _row_num(row, ['營業收入', 'Revenue'], avoid=['成本', '毛利', '率', 'Cost'])
            gp = _row_num(row, ['營業毛利', 'GrossProfit'], avoid=['率', '%'])
            oi = _row_num(row, ['營業利益', 'OperatingIncome'], avoid=['率', '%', '外'])
            ni = _row_num(row, ['本期淨利', '稅後淨利', 'NetIncome', '本期綜合損益'], avoid=['每股', '率', '%', '其他', '非控制'])
            eps = _row_num(row, ['基本每股盈餘', '每股盈餘', 'EPS'], avoid=['稀釋'])
            if eps is not None:
                m['eps'] = eps
            if rev and rev != 0:
                if gp is not None and m['gross'] is None:
                    m['gross'] = round(gp / rev * 100, 1)
                if oi is not None and m['op'] is None:
                    m['op'] = round(oi / rev * 100, 1)
                if ni is not None and m['net'] is None:
                    m['net'] = round(ni / rev * 100, 1)

    # 4) 英文名 + 發行股數 ── 公司基本資料(上市 t187ap03_L;值為英文/數字,key 中文)
    # 註:上櫃公司基本資料 OpenAPI 同樣無 per-company 端點 → 上櫃英文名暫留 null。
    for url, board in (
        ('https://openapi.twse.com.tw/v1/opendata/t187ap03_L', '上市'),
    ):
        for row in _scan_rows(url):
            if not isinstance(row, dict):
                continue
            code = _row_code(row)
            if not code:
                continue
            m = _slot(meta, code, board)
            en = _row_str(row, ['英文簡稱', '英文全名', '英文名稱', 'EnglishAbbr', 'EnglishName'])
            if en and not m.get('en'):
                m['en'] = en
            sh = _row_num(row, ['已發行普通股數', '發行股數', '普通股數'], avoid=['股本', '金額', '資本', '面額', '特別'])
            if sh and sh > 0:
                shares_map[code] = sh

    # 5) 市值 = 收盤 × 發行股數(억/兆由前端格式化)
    for code, m in meta.items():
        sh = shares_map.get(code)
        if sh and m.get('close'):
            m['mktcap'] = round(m['close'] * sh)
    return meta


def build():
    """重抓兩市場 → 寫快取 → 回傳 data。任一來源失敗不致全毀(保留另一邊)。
    新增 twmeta:每股四大指標(量價/估值/三率+EPS)+ 中英名;US 維持 {sym:name}。"""
    tw = fetch_tw()
    us = fetch_us()
    shares_map = {}
    try:
        twmeta = fetch_tw_meta(shares_map)
    except Exception as e:
        print(f'[universe] twmeta failed: {e}')
        twmeta = {}
    # 把代號庫的中文名灌進 meta(zh),並確保每個有名稱的代號都有一格
    for code, name in tw.items():
        m = _slot(twmeta, code)
        m['zh'] = name
        if not m.get('board'):
            m['board'] = 'ETF' if (code.startswith('00') and len(code) >= 5) else None
    for code, m in twmeta.items():
        m.setdefault('zh', tw.get(code, ''))
    data = {'tw': tw, 'us': us, 'twmeta': twmeta, 'updated': int(time.time()),
            'counts': {'tw': len(tw), 'us': len(us), 'twmeta': len(twmeta)}}
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f'[universe] save failed: {e}')
    return data


def load():
    """讀快取;沒有就 build()。"""
    try:
        with open(CACHE, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('tw') or data.get('us'):
            return data
    except Exception:
        pass
    return build()


if __name__ == '__main__':
    d = build()
    c = d['counts']
    print(f"universe: TW {c['tw']} 檔 · US {c['us']} 檔 · meta {c.get('twmeta', 0)} → {CACHE}")
    # 指標覆蓋率(非 null 比例),快速看資料源是否抽取成功
    meta = d.get('twmeta', {})
    flds = ['close', 'chg', 'vol', 'pe', 'pb', 'yield', 'eps', 'gross', 'op', 'net', 'mktcap', 'en']
    if meta:
        print('覆蓋率:', ', '.join(
            f"{f}={sum(1 for m in meta.values() if m.get(f) is not None)}" for f in flds))
    # 抽樣驗證:上市權值 / 上櫃 / ETF
    for s in ('2330', '6683', '0050', '2454'):
        m = meta.get(s)
        if m:
            print(f"  {s} {m.get('zh','')}/{m.get('en','')} [{m.get('board')}] "
                  f"close={m['close']} chg={m['chg']}% vol={m['vol']} | "
                  f"PE={m['pe']} PB={m['pb']} yield={m['yield']} EPS={m['eps']} | "
                  f"三率={m['gross']}/{m['op']}/{m['net']} | 市值={m['mktcap']}")
        else:
            print(f"  {s} (無 meta)")
