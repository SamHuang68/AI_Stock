"""以已知交易日評估個股證據品質；不抓網路、不改寫訊號。"""
from datetime import datetime

import stock_signals as ss


def assess(result, benchmark, pooled=None, now=None):
    now = now or datetime.now(ss._TZ.get(result.get('market'), ss._TZ['TW']))
    today = now.date().isoformat()
    final = (now.hour, now.minute) >= ((14, 0) if result.get('market') == 'TW' else (16, 30))
    days = sorted({b['date'] for b in benchmark if b['date'] < today or (final and b['date'] == today)})
    latest = days[-1] if days else None
    rows = []

    def row(key, label, stamp, impact, *, optional=False):
        lag = sum(d > stamp for d in days) if stamp and latest else None
        state = 'missing' if not stamp else ('stale' if lag else ('aligned' if latest else 'unknown'))
        rows.append({'id': key, 'label': label, 'asOf': stamp, 'status': state,
                     'lagSessions': lag, 'impact': impact, 'optional': optional})

    row('price', '日線', result.get('asOf'), '影響趨勢、動能、量價與風險事件')
    if result.get('market') == 'TW':
        row('chip', '籌碼', (result.get('chip') or {}).get('asOf'), '只影響法人與籌碼判讀')
        row('benchmark', '大盤情境', latest, '影響情境對照研究')
    pool_date = ((pooled or {}).get('window') or {}).get('to')
    row('statistics', '合併統計', pool_date, '影響同市場歷史對照，既有統計仍保留', optional=True)
    generated = (pooled or {}).get('generatedAt')
    try:
        stamp = datetime.fromisoformat(generated)
        age = max(0, (now - stamp).total_seconds() / 86400)
    except (ValueError, TypeError):
        age = None
    stats = rows[-1]
    stats.update({'generatedAt': generated, 'ageDays': round(age, 1) if age is not None else None})
    if age is not None and age >= 7:
        stats['status'] = 'stale'
    notes = []
    if result.get('session', {}).get('provisional'):
        notes.append('今日事件含盤中暫定值，收盤後才能確認。')
    if latest != today:
        notes.append('以本機已知交易日核對；今日是否休市或來源尚未更新，尚無完整證據。')
    if result.get('dataWarning'):
        notes.append(result['dataWarning'])
    status = 'attention' if any(r['status'] in ('missing', 'stale', 'unknown') for r in rows) else 'aligned'
    return {'status': status, 'referenceSession': latest, 'checkedAt': now.isoformat(),
            'label': '資料需留意' if status == 'attention' else '與已知交易日對齊',
            'items': rows, 'notes': notes, 'changesSignal': False}
