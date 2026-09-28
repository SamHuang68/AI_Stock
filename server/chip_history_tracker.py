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
import time
from datetime import date
from pathlib import Path

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')
YF_HEADERS = {'User-Agent': 'Mozilla/5.0'}


def _merge_snapshot(filename, additions):
    """以共用跨程序鎖保護完整讀改寫，避免批次與單檔查詢互相覆蓋。"""
    from atomic_store import atomic_write_json, load_json
    from daemon_lock import acquire_daemon_lock, release_daemon_lock
    target = Path(filename)
    deadline = time.monotonic() + 20
    handle = None
    while handle is None:
        handle = acquire_daemon_lock('chip-' + target.stem, lock_dir=target.parent / 'locks')
        if handle is None:
            if time.monotonic() >= deadline:
                raise TimeoutError('籌碼快照正由其他工作更新，保留原資料並稍後重試')
            time.sleep(.05)
    try:
        old = load_json(target, default={}, expected_type=dict)
        for code, values in additions.items():
            old[code] = {**(old.get(code) or {}), **values}
        atomic_write_json(target, old, backup=True)
        return old
    finally:
        release_daemon_lock(handle)


def fetch_t86(day):
    url = f'https://www.twse.com.tw/rwd/zh/fund/T86?date={day}&selectType=ALLBUT0999&response=json'
    req = urllib.request.Request(url, headers=YF_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def record_snapshot(code, payload, directory=CHIP_HISTORY_PATH):
    """逐檔查詢也按可證明的來源日保存，不能把休市日讀取當成新交易日。"""
    from datetime import datetime
    inst = (payload or {}).get('inst') or {}
    if inst.get('total') is None:
        return False
    # TPEx 必須帶經解析器核對的自身交易日，不能借用 T86 日期。
    if payload.get('_chipSource') == 'TPEx' and payload.get('_verifiedChipDate') != payload.get('date'):
        return False
    raw_day = str(payload.get('date') or '')
    try:
        source_day = datetime.strptime(raw_day, '%Y%m%d').date()
    except ValueError:
        return False
    if source_day > date.today() or source_day.weekday() >= 5:
        return False
    fn = os.path.join(directory, raw_day + '.json')
    values = {key: inst.get(key) for key in ('foreign', 'trust', 'dealer', 'total')}
    # 查詢缺值不得抹掉先前的完整全市場快照。
    _merge_snapshot(fn, {code: {**{k: v for k, v in values.items() if v is not None},
                 'sourceDate': source_day.isoformat(),
                 'source': 'TPEx/3insti' if payload.get('_chipSource') == 'TPEx' else 'TWSE/T86', 'unit': 'shares'}})
    return True


def parse_and_save(day, *, directory=None):
    data = fetch_t86(day)
    if data.get('stat') not in ('OK', 'ok'):
        print(f'[chip-tracker] {day} no data (stat={data.get("stat")}) — 非交易日?')
        return 0
    from chip_api import parse_t86
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
    directory = directory or CHIP_HISTORY_PATH
    os.makedirs(directory, exist_ok=True)
    fn = os.path.join(directory, day + '.json')
    stamp = datetime.now(timezone.utc).isoformat()
    out = _merge_snapshot(fn, {code: {**values,
                     'sourceDate': f'{day[:4]}-{day[4:6]}-{day[6:]}',
                     'source': 'TWSE/T86', 'unit': 'shares', 'fetchedAt': stamp}
                     for code, values in parsed.items()})
    print(f'[籌碼快照] {day}：已更新 {len(parsed)} 檔上市資料')
    try:
        from touxin_ledger import append_rows
        n_ledger = append_rows([
            {'symbol': code, 'session_date': out[code]['sourceDate'],
             'trust_net_shares': values['trust'], 'volume_shares': None,
             'source': 'chip_history/T86', 'ingested_at': stamp}
            for code, values in parsed.items()
        ], base_dir=os.path.dirname(os.path.dirname(directory)))
        if n_ledger:
            print(f'[chip-tracker] {day}: appended {n_ledger} touxin ledger rows')
    except Exception as exc:
        raise RuntimeError('籌碼快照已寫入，但投信帳本追加失敗，需重試') from exc
    return len(parsed)


def parse_and_save_tpex(day, *, directory=None):
    """與單檔畫面共用解析器；每日一次完整上櫃快照，日期不符時不寫入。"""
    from chip_api import parse_tpex_inst
    from datetime import datetime, timezone
    url = 'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading'
    with urllib.request.urlopen(urllib.request.Request(url, headers=YF_HEADERS), timeout=20) as response:
        parsed = parse_tpex_inst(json.load(response), day)
    if not parsed:
        return 0
    directory = directory or CHIP_HISTORY_PATH
    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, day + '.json')
    stamp = datetime.now(timezone.utc).isoformat()
    _merge_snapshot(filename, {code: {**values, 'sourceDate': f'{day[:4]}-{day[4:6]}-{day[6:]}',
                     'source': 'TPEx/3insti', 'unit': 'shares', 'fetchedAt': stamp}
                     for code, values in parsed.items()})
    from touxin_ledger import append_rows
    append_rows([{'symbol': code, 'session_date': f'{day[:4]}-{day[4:6]}-{day[6:]}',
                  'trust_net_shares': values['trust'], 'volume_shares': None,
                  'source': 'chip_history/TPEx', 'ingested_at': stamp}
                 for code, values in parsed.items()], base_dir=os.path.dirname(os.path.dirname(directory)))
    return len(parsed)


if __name__ == '__main__':
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime('%Y%m%d')
    try:
        n = parse_and_save(day)
        sys.exit(0 if n else 1)
    except Exception as e:
        print(f'[chip-tracker] failed: {e}')
        sys.exit(2)
