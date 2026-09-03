# -*- coding: utf-8 -*-
"""台／美股公司重大訊息彙整（供 /pulse.flash 與 /flash）

資料來源（皆為公開官方／主流金融 API，禁止 mock）：
  - 上市重訊：TWSE OpenAPI t187ap04_L
  - 上櫃重訊：TPEx OpenAPI mopsfin_t187ap04_O
  - 美股訊息：Yahoo Finance search news（大型權值／半導體籃）

回傳列欄位（前後端對齊）：
  time, ts, title, cat, code, name, mkt, url, source, clause
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as _urlquote
from xml.etree import ElementTree as ET

_UA = {
    'User-Agent': 'StockTerminal/5.0 (+local; market-flash)',
    'Accept': 'application/json,text/plain,*/*',
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
}
_YF_UA = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finance.yahoo.com/',
}

_TWSE_MAT = 'https://openapi.twse.com.tw/v1/opendata/t187ap04_L'
_TPEX_MAT = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O'

# 對台股供應鏈／權值連動高的美股籃（Yahoo 查詢用）
_US_WATCH: List[Tuple[str, str]] = [
    ('NVDA', 'Nvidia'),
    ('TSM', 'TSMC'),
    ('AAPL', 'Apple'),
    ('MSFT', 'Microsoft'),
    ('AVGO', 'Broadcom'),
    ('AMD', 'AMD'),
    ('ASML', 'ASML'),
    ('GOOGL', 'Google'),
    ('AMZN', 'Amazon'),
    ('META', 'Meta'),
    ('TSLA', 'Tesla'),
    ('INTC', 'Intel'),
    ('MU', 'Micron'),
    ('QCOM', 'Qualcomm'),
    ('ARM', 'Arm'),
]

# 重訊主旨關鍵字加權（越高越優先進快訊）
_KW_HI = (
    '併購', '合併', '分割', '減資', '增資', '私募', '庫藏', '公開收購',
    '取得或處分', '重大資產', '停工', '停業', '重整', '破產', '違約',
    '訴訟', '澄清', '財務預測', '自結', '盈餘分配', '股利', '配發',
    '營收', '財報', '財務報告', '重大訊息', '取得股權', '出售股權',
    '處分', '轉投資', '重大契約', '解除契約', '調降', '調升',
)
_KW_MID = (
    '董事會', '股東會', '資金貸與', '背書保證', '衍生性', '員工認股',
    '現金增資', '轉換公司債', '發行', '減損', '提列', '法說',
)
_KW_NOISE = (
    '更名為', '公告期間', '期刊', '接受刊登', '法人說明會召開日期',
    '延後召開', '開會通知', '議事手冊',
)

# 符合條款優先（MOPS 條款）：併購／重大資產／財報相關常見款
_CLAUSE_BOOST = {
    '第11款': 18, '第12款': 16, '第14款': 14, '第15款': 12,
    '第17款': 16, '第18款': 14, '第19款': 12, '第20款': 10,
    '第21款': 14, '第22款': 12, '第23款': 10, '第31款': 6,
    '第35款': 10, '第51款': 2,
}

_cache: Dict[str, Any] = {'ts': 0.0, 'payload': None}
_CACHE_TTL = 180.0


def _http_json(url: str, headers: Optional[dict] = None, timeout: float = 10) -> Any:
    req = urllib.request.Request(url, headers=headers or _UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8-sig', 'replace'))


def _clean_ws(s: Any) -> str:
    return re.sub(r'[\s\r\n]+', ' ', str(s or '')).strip()


def _roc_ymd_to_iso(s: Any) -> str:
    """民國 YYYYMMDD / YYYMMDD → 西元 YYYY-MM-DD；失敗回空字串。"""
    digits = re.sub(r'\D', '', str(s or ''))
    if len(digits) == 7:  # YYYMMDD
        y = int(digits[:3]) + 1911
        return f'{y:04d}-{digits[3:5]}-{digits[5:7]}'
    if len(digits) == 8:  # YYYYMMDD
        return f'{digits[:4]}-{digits[4:6]}-{digits[6:8]}'
    return ''


def _hhmmss(s: Any) -> str:
    digits = re.sub(r'\D', '', str(s or ''))
    if not digits:
        return '00:00:00'
    digits = digits.zfill(6)[-6:]
    return f'{digits[0:2]}:{digits[2:4]}:{digits[4:6]}'


def _dt_ts(date_iso: str, hhmmss: str) -> float:
    try:
        return time.mktime(time.strptime(f'{date_iso} {hhmmss}', '%Y-%m-%d %H:%M:%S'))
    except Exception:
        try:
            return time.mktime(time.strptime(date_iso, '%Y-%m-%d'))
        except Exception:
            return 0.0


def _fmt_time(ts: float, date_iso: str = '', hhmmss: str = '') -> str:
    if ts > 0:
        return time.strftime('%m-%d %H:%M', time.localtime(ts))
    if date_iso:
        return (date_iso[5:] + ' ' + (hhmmss[:5] if hhmmss else '')).strip()
    return ''


def _tw_title(row: dict) -> str:
    for k in ('主旨', '主旨 ', 'Title', 'title'):
        if k in row and row.get(k):
            return _clean_ws(row.get(k))
    return ''


def _score_tw(title: str, clause: str) -> int:
    t = title or ''
    score = 8
    for kw in _KW_NOISE:
        if kw in t:
            score -= 20
    for kw in _KW_HI:
        if kw in t:
            score += 22
    for kw in _KW_MID:
        if kw in t:
            score += 10
    score += _CLAUSE_BOOST.get(_clean_ws(clause), 0)
    # 過短／空主旨降權
    if len(t) < 6:
        score -= 15
    return score


def _parse_tw_rows(rows: List[dict], mkt_label: str, source: str, cat: str) -> List[dict]:
    out: List[dict] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        code = _clean_ws(
            r.get('公司代號') or r.get('SecuritiesCompanyCode') or r.get('Code') or ''
        )
        name = _clean_ws(
            r.get('公司名稱') or r.get('CompanyName') or r.get('Name') or ''
        )
        title = _tw_title(r)
        if not title:
            continue
        clause = _clean_ws(r.get('符合條款') or '')
        speak = r.get('發言日期') or r.get('Date') or ''
        date_iso = _roc_ymd_to_iso(speak)
        hm = _hhmmss(r.get('發言時間'))
        ts = _dt_ts(date_iso, hm)
        score = _score_tw(title, clause)
        # 標題加上公司簡稱方便閱讀（避免只顯示代號）
        disp = f'{code} {name}｜{title}' if code else title
        out.append({
            'time': _fmt_time(ts, date_iso, hm),
            'ts': ts,
            'title': disp[:160],
            'cat': cat,
            'code': code or None,
            'name': name or None,
            'mkt': 'TW',
            'url': None,
            'source': source,
            'clause': clause or None,
            'score': score,
            '_board': mkt_label,
        })
    return out


def fetch_tw_material(timeout: float = 10) -> List[dict]:
    items: List[dict] = []
    try:
        rows = _http_json(_TWSE_MAT, timeout=timeout)
        if isinstance(rows, list):
            items.extend(_parse_tw_rows(rows, '上市', 'TWSE', '台股重訊'))
    except Exception as e:
        print('[flash] twse material', type(e).__name__, e)
    try:
        rows = _http_json(_TPEX_MAT, timeout=timeout)
        if isinstance(rows, list):
            items.extend(_parse_tw_rows(rows, '上櫃', 'TPEx', '櫃買重訊'))
    except Exception as e:
        print('[flash] tpex material', type(e).__name__, e)
    return items


def _us_news_ok(sym: str, name: str, item: dict) -> bool:
    """嚴格過濾：標題必須點名代號或公司名／別名。
    Yahoo 常把 NVDA 等權值塞進 relatedTickers，不可只憑標籤收錄。"""
    title = (item.get('title') or '')
    tl = title.lower()
    sym_u = sym.upper()
    name_l = (name or '').lower()
    if sym_u.lower() in tl:
        return True
    if name_l and len(name_l) >= 3 and name_l in tl:
        return True
    aliases = {
        'GOOGL': ('alphabet', 'google'),
        'META': ('meta platforms', 'facebook'),
        'TSM': ('tsmc', 'taiwan semiconductor'),
        'AVGO': ('broadcom',),
        'ASML': ('asml',),
        'NVDA': ('nvidia',),
        'AAPL': ('apple',),
        'MSFT': ('microsoft',),
        'AMZN': ('amazon',),
        'TSLA': ('tesla',),
        'INTC': ('intel',),
        'AMD': ('advanced micro',),
        'MU': ('micron',),
        'QCOM': ('qualcomm',),
        'ARM': ('arm holdings',),
    }
    for a in aliases.get(sym_u, ()):
        if a in tl:
            return True
    return False


def fetch_us_company_news(timeout: float = 8) -> List[dict]:
    items: List[dict] = []
    now = time.time()
    cutoff = now - 72 * 3600  # 近 72 小時

    def one(sym: str, name: str) -> List[dict]:
        url = (
            'https://query1.finance.yahoo.com/v1/finance/search'
            f'?q={_urlquote(sym)}&newsCount=8&quotesCount=0'
        )
        try:
            data = _http_json(url, headers=_YF_UA, timeout=timeout)
        except Exception as e:
            print('[flash] yahoo', sym, type(e).__name__, e)
            return []
        out = []
        for n in (data.get('news') or []):
            if not isinstance(n, dict):
                continue
            if not _us_news_ok(sym, name, n):
                continue
            pts = n.get('providerPublishTime')
            try:
                ts = float(pts) if pts is not None else 0.0
            except Exception:
                ts = 0.0
            if ts and ts < cutoff:
                continue
            title = _clean_ws(n.get('title'))
            if not title:
                continue
            pub = _clean_ws(n.get('publisher') or '')
            link = n.get('link') or None
            disp = f'{sym}｜{title}' + (f'（{pub}）' if pub else '')
            out.append({
                'time': _fmt_time(ts),
                'ts': ts or now,
                'title': disp[:160],
                'cat': '美股',
                'code': sym,
                'name': name,
                'mkt': 'US',
                'url': link,
                'source': 'Yahoo',
                'clause': None,
                'score': 40 + (10 if name.lower() in title.lower() else 0),
                '_board': 'US',
            })
        return out

    with ThreadPoolExecutor(max_workers=6, thread_name_prefix='flash-us') as ex:
        futs = [ex.submit(one, s, n) for s, n in _US_WATCH]
        for fut in as_completed(futs):
            try:
                items.extend(fut.result() or [])
            except Exception as e:
                print('[flash] us fut', e)
    return items


def fetch_sec_8k_mega(timeout: float = 8) -> List[dict]:
    """SEC 當日 8-K（補充美股重大申報）；僅保留標題可辨識之大型公司。"""
    mega = {
        'NVIDIA': 'NVDA', 'APPLE': 'AAPL', 'MICROSOFT': 'MSFT', 'BROADCOM': 'AVGO',
        'ALPHABET': 'GOOGL', 'AMAZON': 'AMZN', 'META PLATFORMS': 'META',
        'TESLA': 'TSLA', 'INTEL': 'INTC', 'ADVANCED MICRO': 'AMD',
        'TAIWAN SEMICONDUCTOR': 'TSM', 'ASML': 'ASML', 'MICRON': 'MU',
        'QUALCOMM': 'QCOM', 'ARM HOLDINGS': 'ARM',
    }
    url = (
        'https://www.sec.gov/cgi-bin/browse-edgar?'
        'action=getcurrent&type=8-K&owner=include&count=40&output=atom'
    )
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'StockTerminal/5.0 (local research; flash)',
            'Accept': 'application/atom+xml,application/xml,text/xml,*/*',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        out = []
        for e in root.findall('a:entry', ns):
            title = _clean_ws(e.findtext('a:title', default='', namespaces=ns))
            updated = e.findtext('a:updated', default='', namespaces=ns) or ''
            link_el = e.find('a:link', ns)
            href = link_el.get('href') if link_el is not None else None
            tu = title.upper()
            code = None
            for name, sym in mega.items():
                if name in tu:
                    code = sym
                    break
            if not code:
                continue
            try:
                # 2026-08-07T17:30:48-04:00 → 略過時區，用前 19 字
                ts = time.mktime(time.strptime(updated[:19], '%Y-%m-%dT%H:%M:%S'))
            except Exception:
                ts = time.time()
            out.append({
                'time': _fmt_time(ts),
                'ts': ts,
                'title': f'{code}｜SEC 8-K {title[:100]}',
                'cat': '美股申報',
                'code': code,
                'name': None,
                'mkt': 'US',
                'url': href,
                'source': 'SEC',
                'clause': '8-K',
                'score': 55,
                '_board': 'US',
            })
        return out
    except Exception as e:
        print('[flash] sec 8-k', type(e).__name__, e)
        return []


def _select_tw(items: List[dict], n: int) -> List[dict]:
    """依分數＋時間排序，同公司最多 2 筆，避免單一公司洗版。"""
    items = sorted(items, key=lambda x: (x.get('score') or 0, x.get('ts') or 0), reverse=True)
    picked: List[dict] = []
    per: Dict[str, int] = {}
    for it in items:
        if (it.get('score') or 0) < 12:
            continue
        code = it.get('code') or ''
        if per.get(code, 0) >= 2:
            continue
        per[code] = per.get(code, 0) + 1
        picked.append(it)
        if len(picked) >= n:
            break
    # 若篩太嚴，放寬分數補滿
    if len(picked) < max(4, n // 2):
        for it in items:
            if it in picked:
                continue
            code = it.get('code') or ''
            if per.get(code, 0) >= 2:
                continue
            per[code] = per.get(code, 0) + 1
            picked.append(it)
            if len(picked) >= n:
                break
    return picked


def _select_us(items: List[dict], n: int) -> List[dict]:
    items = sorted(items, key=lambda x: (x.get('ts') or 0, x.get('score') or 0), reverse=True)
    picked: List[dict] = []
    seen_title = set()
    per: Dict[str, int] = {}
    for it in items:
        title_key = (it.get('title') or '')[:80]
        if title_key in seen_title:
            continue
        code = it.get('code') or ''
        if per.get(code, 0) >= 2:
            continue
        seen_title.add(title_key)
        per[code] = per.get(code, 0) + 1
        picked.append(it)
        if len(picked) >= n:
            break
    return picked


def _public_item(it: dict) -> dict:
    item = {
        'time': it.get('time') or '',
        'ts': it.get('ts') or 0,
        'title': it.get('title') or '',
        'cat': it.get('cat') or '',
        'code': it.get('code'),
        'name': it.get('name'),
        'mkt': it.get('mkt') or 'TW',
        'url': it.get('url'),
        'source': it.get('source'),
        'clause': it.get('clause'),
    }
    try:
        from news_impact import tag_item
        item['impact'] = tag_item(item)
    except Exception:
        item['impact'] = None
    return item


def build_flash(n: int = 24, force: bool = False) -> Dict[str, Any]:
    """彙整台美重大訊息。n 為回傳筆數上限。"""
    n = max(6, min(int(n or 24), 60))
    now = time.time()
    if not force and _cache.get('payload') and (now - float(_cache.get('ts') or 0)) < _CACHE_TTL:
        cached = _cache['payload']
        rows = list((cached or {}).get('items') or [])[:n]
        return {
            'ok': True,
            'cached': True,
            'updatedAt': (cached or {}).get('updatedAt'),
            'counts': (cached or {}).get('counts') or {},
            'items': rows,
        }

    tw_all: List[dict] = []
    us_all: List[dict] = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='flash') as ex:
        f_tw = ex.submit(fetch_tw_material, 10)
        f_us = ex.submit(fetch_us_company_news, 8)
        f_sec = ex.submit(fetch_sec_8k_mega, 8)
        try:
            tw_all = f_tw.result(timeout=12) or []
        except Exception as e:
            print('[flash] tw result', e)
        try:
            us_all = f_us.result(timeout=14) or []
        except Exception as e:
            print('[flash] us result', e)
        try:
            us_all.extend(f_sec.result(timeout=10) or [])
        except Exception as e:
            print('[flash] sec result', e)

    # 台股約 2/3、美股約 1/3
    n_tw = max(4, int(round(n * 0.65)))
    n_us = max(2, n - n_tw)
    tw_pick = _select_tw(tw_all, n_tw)
    us_pick = _select_us(us_all, n_us)
    merged = tw_pick + us_pick
    merged.sort(key=lambda x: x.get('ts') or 0, reverse=True)
    items = [_public_item(x) for x in merged[:n]]

    payload = {
        'ok': True,
        'cached': False,
        'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'counts': {
            'twRaw': len(tw_all),
            'usRaw': len(us_all),
            'tw': len(tw_pick),
            'us': len(us_pick),
            'out': len(items),
        },
        'items': items,
    }
    _cache['ts'] = now
    _cache['payload'] = payload
    return payload
