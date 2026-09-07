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


def parse_and_save(day):
    data = fetch_t86(day)
    if data.get('stat') not in ('OK', 'ok'):
        print(f'[chip-tracker] {day} no data (stat={data.get("stat")}) — 非交易日?')
        return 0
    fields = data.get('fields') or []
    rows = data.get('data') or []
    idx_code = next((i for i, f in enumerate(fields) if '證券代號' in f), 0)

    def col_idx(keyword, *, exact=False, avoid=()):
        for i, f in enumerate(fields):
            fs = str(f).strip()
            if avoid and any(a in fs for a in avoid):
                continue
            if exact:
                if fs == keyword:
                    return i
            elif keyword in fs:
                return i
        return None

    i_for = col_idx('外陸資買賣超股數(不含外資自營商)', exact=True) \
        or col_idx('外陸資買賣超股數') or col_idx('外資', avoid=('外資自營商',))
    i_trust = col_idx('投信買賣超股數') or col_idx('投信')
    # 必須完全相符，否則會誤中『外資自營商買賣超股數』
    i_deal = col_idx('自營商買賣超股數', exact=True)
    i_tot = col_idx('三大法人買賣超股數', exact=True) or col_idx('三大法人買賣超股數')

    def num(row, i):
        if i is None:
            return None
        try:
            return float(str(row[i]).replace(',', '').replace(' ', ''))
        except Exception:
            return None

    out = {}
    for row in rows:
        code = str(row[idx_code]).strip()
        if not code:
            continue
        out[code] = {
            'foreign': num(row, i_for), 'trust': num(row, i_trust),
            'dealer': num(row, i_deal), 'total': num(row, i_tot),
        }
    os.makedirs(CHIP_HISTORY_PATH, exist_ok=True)
    fn = os.path.join(CHIP_HISTORY_PATH, day + '.json')
    with open(fn, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'[chip-tracker] {day}: saved {len(out)} stocks -> {fn}')
    try:
        from touxin_ledger import ingest_chip_history_file
        n_ledger = ingest_chip_history_file(fn, source='chip_history/T86')
        if n_ledger:
            print(f'[chip-tracker] {day}: appended {n_ledger} touxin ledger rows')
    except Exception as exc:
        print(f'[chip-tracker] touxin ledger append skipped: {exc}')
    return len(out)


if __name__ == '__main__':
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime('%Y%m%d')
    try:
        n = parse_and_save(day)
        sys.exit(0 if n else 1)
    except Exception as e:
        print(f'[chip-tracker] failed: {e}')
        sys.exit(2)
