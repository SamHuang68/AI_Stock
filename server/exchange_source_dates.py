"""Official exchange dates; never substitute a request/fetch date."""
from datetime import date, datetime, timedelta, timezone
import math
import re

TAIPEI = timezone(timedelta(hours=8))

def taipei_today():
    return datetime.now(TAIPEI).date()


def marketflow_cache_key(today):
    return f'marketflow:source-date-v1:{today.strftime("%Y%m%d")}'

def official_date(value):
    text = str(value or '').strip()
    match = re.fullmatch(r'(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', text)
    if match:
        year, month, day = map(int, match.groups())
        if year < 1911:
            year += 1911
    elif re.fullmatch(r'\d{8}', text):
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:])
    elif re.fullmatch(r'\d{7}', text):
        year, month, day = int(text[:3]) + 1911, int(text[3:5]), int(text[5:])
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None

def response_date(payload, requested, today):
    observed = official_date(payload.get('date'))
    return observed if observed == requested and observed <= today else None

def txf_timestamp(day, clock, now=None):
    observed = official_date(day)
    text = str(clock or '').strip()
    if re.fullmatch(r'\d{6}', text):
        text = ':'.join((text[:2], text[2:4], text[4:]))
    if observed is None or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', text):
        return None
    try:
        stamp = datetime.combine(observed, datetime.strptime(text, '%H:%M:%S').time(), TAIPEI)
    except ValueError:
        return None
    if stamp > (now or datetime.now(TAIPEI)):
        return None
    return stamp.isoformat()

def _number(value):
    try:
        value = float(str(value).replace(',', ''))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def marketflow_payload(fetch, today):
    out = {'date': today.isoformat(), 'turnover': [], 'inst': None, 'margin': None}
    try:
        data = fetch('https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=' + today.strftime('%Y%m01') + '&response=json')
        if data.get('stat') in ('OK', 'ok'):
            fields = data.get('fields') or []
            positions = {name: next((i for i, f in enumerate(fields) if label in f), default) for name, label, default in [('date','日期',0), ('amount','成交金額',1), ('index','指數',None), ('chg','漲跌點數',None)]}
            for row in data.get('data') or []:
                try:
                    observed = official_date(row[positions['date']])
                    amount = _number(row[positions['amount']])
                    if observed is None or observed > today or observed.replace(day=1) != today.replace(day=1) or amount is None:
                        continue
                    rec = {'date': str(row[positions['date']]).strip(), 'sourceDate': observed.isoformat(), 'amount': amount,
                           'source': 'TWSE FMTQIK'}
                    for name in ('index', 'chg'):
                        i = positions[name]
                        if i is not None and i < len(row):
                            value = _number(row[i])
                            if value is not None:
                                rec[name] = value
                    out['turnover'].append(rec)
                except (IndexError, TypeError):
                    continue
    except Exception:
        pass
    for back in range(7):
        requested = today - timedelta(days=back)
        try:
            data = fetch('https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=' + requested.strftime('%Y%m%d') + '&type=day&response=json')
            observed = response_date(data, requested, today)
            if data.get('stat') not in ('OK', 'ok') or observed is None:
                continue
            fields = data.get('fields') or []
            name_i = next((i for i, f in enumerate(fields) if '單位名稱' in f or '買賣別' in f), 0)
            net_i = next((i for i, f in enumerate(fields) if '買賣差' in f or '買賣超' in f), len(fields)-1)
            inst = {'foreign': None, 'trust': None, 'dealer': None, 'date': observed.strftime('%Y%m%d'),
                    'sourceDate': observed.isoformat(), 'source': 'TWSE BFI82U'}
            for row in data.get('data') or []:
                if not row or max(name_i, net_i) >= len(row):
                    continue
                name, net = str(row[name_i]), _number(row[net_i])
                if net is None:
                    continue
                kind = 'foreign' if '外' in name else 'trust' if '投信' in name else 'dealer' if '自營' in name else None
                if kind:
                    inst[kind] = (inst[kind] or 0) + net
            if any(inst[k] is not None for k in ('foreign','trust','dealer')):
                out['inst'] = inst
                break
        except Exception:
            continue
    try:
        data = fetch('https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=' + today.strftime('%Y%m%d') + '&selectType=ALL&response=json')
        observed = response_date(data, today, today)
        if data.get('stat') in ('OK', 'ok') and observed is not None:
            tables = data.get('tables') or []
            rows = tables[0].get('data') or [] if tables else []
            if rows:
                out['margin'] = {'raw': rows[:6], 'date': observed.strftime('%Y%m%d'),
                                 'sourceDate': observed.isoformat(), 'source': 'TWSE MI_MARGN'}
    except Exception:
        pass
    return out
