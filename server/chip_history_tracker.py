#!/usr/bin/env python3
# ============================================================
# Stock Terminal v3.8 — Chip History Tracker (法人籌碼每日快照)
# ------------------------------------------------------------
# 盤後排程跑：抓 TWSE T86 (三大法人買賣超) 全市場一次，
# 把每檔的 foreign/trust/dealer/total 存到 chip_history/<date>.json。
# 累積多天後 server.py 的 _chip_streak() 就能算「外資連 N 買/賣」。
#
# 用法：
#   python chip_history_tracker.py            # 抓今天
#   python chip_history_tracker.py 20260601   # 抓指定日期 (yyyymmdd)
# 排程：沿用 install_scheduler.bat 模式，新增每交易日 17:40 觸發。
# ============================================================
import os, sys, json, urllib.request
from datetime import date

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')
YF_HEADERS = {'User-Agent': 'Mozilla/5.0'}


def fetch_t86(day):
    url = f'https://www.twse.com.tw/rwd/zh/fund/T86?date={day}&selectType=ALLBUT0999&response=json'
    req = urllib.request.Request(url, headers=YF_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def record_snapshot(code, payload, directory=CHIP_HISTORY_PATH):
    """逐檔查詢也按可證明的來源日保存，不能把休市日讀取當成新交易日。"""
    from datetime import datetime
    from atomic_store import atomic_write_json, load_json
    inst = (payload or {}).get('inst') or {}
    if inst.get('total') is None:
        return False
    # TPEx 的原回應尚未帶其自身交易日，不能借用 T86 日期寫入。
    if payload.get('_chipSource') == 'TPEx':
        return False
    raw_day = str(payload.get('date') or '')
    try:
        source_day = datetime.strptime(raw_day, '%Y%m%d').date()
    except ValueError:
        return False
    if source_day > date.today() or source_day.weekday() >= 5:
        return False
    fn = os.path.join(directory, raw_day + '.json')
    old = load_json(fn, default={}, expected_type=dict)
    values = {key: inst.get(key) for key in ('foreign', 'trust', 'dealer', 'total')}
    # 查詢缺值不得抹掉先前的完整全市場快照。
    old[code] = {**(old.get(code) or {}), **{k: v for k, v in values.items() if v is not None},
                 'sourceDate': source_day.isoformat(), 'source': 'TWSE/T86', 'unit': 'shares'}
    atomic_write_json(fn, old, backup=True, indent=None)
    return True


def parse_and_save(day):
    data = fetch_t86(day)
    if data.get('stat') not in ('OK', 'ok'):
        print(f'[chip-tracker] {day} no data (stat={data.get("stat")}) — 非交易日?')
        return 0
    from chip_api import parse_t86
    from atomic_store import atomic_write_json, load_json
    from datetime import datetime, timezone
    parsed = parse_t86(data)
    source_day = str(data.get('date') or '').replace('-', '')
    if source_day != day:
        raise ValueError('來源交易日與請求不符，拒絕寫入籌碼快照')
    datetime.strptime(source_day, '%Y%m%d')
    if not parsed:
        return 0
    if any(any(values.get(k) is None for k in ('foreign', 'trust', 'dealer', 'total'))
           for values in parsed.values()):
        raise ValueError('來源必要欄位不完整，保留既有籌碼快照')
    os.makedirs(CHIP_HISTORY_PATH, exist_ok=True)
    fn = os.path.join(CHIP_HISTORY_PATH, day + '.json')
    out = load_json(fn, default={}, expected_type=dict)
    stamp = datetime.now(timezone.utc).isoformat()
    for code, values in parsed.items():
        out[code] = {**(out.get(code) or {}), **values,
                     'sourceDate': f'{day[:4]}-{day[4:6]}-{day[6:]}',
                     'source': 'TWSE/T86', 'unit': 'shares', 'fetchedAt': stamp}
    atomic_write_json(fn, out, backup=True)
    print(f'[籌碼快照] {day}：已更新 {len(parsed)} 檔上市資料')
    try:
        from touxin_ledger import append_rows
        n_ledger = append_rows([
            {'symbol': code, 'session_date': out[code]['sourceDate'],
             'trust_net_shares': values['trust'], 'volume_shares': None,
             'source': 'chip_history/T86', 'ingested_at': stamp}
            for code, values in parsed.items()
        ], base_dir=os.path.dirname(os.path.dirname(CHIP_HISTORY_PATH)))
        if n_ledger:
            print(f'[chip-tracker] {day}: appended {n_ledger} touxin ledger rows')
    except Exception as exc:
        raise RuntimeError('籌碼快照已寫入，但投信帳本追加失敗，需重試') from exc
    return len(parsed)


if __name__ == '__main__':
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime('%Y%m%d')
    try:
        n = parse_and_save(day)
        sys.exit(0 if n else 1)
    except Exception as e:
        print(f'[chip-tracker] failed: {e}')
        sys.exit(2)
