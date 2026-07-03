"""etf_report_lite.py — ETF 操盤手共識報表(純 stdlib,無 pandas/matplotlib)。

取代需重依賴(pandas/matplotlib,打包被排除)的 etf_report;dev 與打包版皆可
產出正常的 HTML + 純文字報表,絕不再寄原始 JSON。

彙總邏輯與前端「ETF 操盤手共識報表」一致:
  每股跨所有主動 ETF 統計 新增/加碼(買盤)、移除/減碼(賣盤),
  bull=(新增+加碼)×2、bear=(移除+減碼)×2、net=bull-bear。
顏色(台股慣例):買盤/潛在上漲=紅、賣盤/潛在下跌=綠。
"""
import html as _html

RED = '#ef4444'    # 台股:買盤 / 上漲
GREEN = '#22c55e'  # 台股:賣盤 / 下跌


def _agg(delta):
    agg = {}

    def g(code, name):
        k = (code or '').upper()
        if k not in agg:
            agg[k] = {'code': code, 'name': name or '', 'add': 0, 'inc': 0,
                      'rm': 0, 'dec': 0, 'wIn': 0.0, 'wOut': 0.0}
        if name and not agg[k]['name']:
            agg[k]['name'] = name
        return agg[k]

    for e in delta.get('etfs', []):
        for n in (e.get('new') or []):
            s = g(n.get('code'), n.get('name')); s['add'] += 1; s['wIn'] += (n.get('weight') or 0)
        for c in (e.get('changed') or []):
            s = g(c.get('code'), c.get('name')); d = c.get('delta') or 0
            if d >= 0:
                s['inc'] += 1; s['wIn'] += d
            else:
                s['dec'] += 1; s['wOut'] += abs(d)
        for r in (e.get('removed') or []):
            s = g(r.get('code'), r.get('name')); s['rm'] += 1; s['wOut'] += (r.get('prev_weight') or 0)

    arr = []
    for s in agg.values():
        s['bull'] = (s['add'] + s['inc']) * 2
        s['bear'] = (s['rm'] + s['dec']) * 2
        s['net'] = s['bull'] - s['bear']
        arr.append(s)
    up = sorted([s for s in arr if s['bull'] > 0], key=lambda s: (-s['bull'], -s['wIn']))
    down = sorted([s for s in arr if s['bear'] > 0], key=lambda s: (-s['bear'], -s['wOut']))
    net = sorted([s for s in arr if s['net'] != 0], key=lambda s: -s['net'])
    return up, down, net, len(delta.get('etfs', []))


def _tags(s, side):
    t = []
    if side == 'up':
        if s['add']: t.append('▲新增 %d' % s['add'])
        if s['inc']: t.append('＋加碼 %d' % s['inc'])
    else:
        if s['rm']: t.append('▼移除 %d' % s['rm'])
        if s['dec']: t.append('－減碼 %d' % s['dec'])
    return ' · '.join(t)


def _table_html(rows, side, limit):
    color = RED if side == 'up' else GREEN
    if not rows:
        return "<tr><td colspan='4' style='padding:8px;color:#999'>無</td></tr>"
    out = []
    for s in rows[:limit]:
        nm = _html.escape(s['name'] or s['code'])
        wt = s['wIn'] if side == 'up' else s['wOut']
        out.append(
            "<tr style='border-bottom:1px solid #eee'>"
            "<td style='padding:5px 8px;font-weight:700;font-family:monospace'>%s</td>"
            "<td style='padding:5px 8px'>%s</td>"
            "<td style='padding:5px 8px;color:%s;font-weight:600'>%s</td>"
            "<td style='padding:5px 8px;text-align:right;color:#888'>權重 %.2f%%</td></tr>"
            % (_html.escape(s['code']), nm, color, _html.escape(_tags(s, side)), wt))
    return ''.join(out)


def build(delta, mode='full'):
    """回傳 (subject, html, text)。mode: 'full' 多區塊 / 'lite' 加減碼 Top10。"""
    up, down, net, etf_count = _agg(delta)
    date = delta.get('date', '')
    prev = delta.get('prev_date', '')
    summ = delta.get('summary', {})
    limit = 10 if mode == 'lite' else 30
    subject = 'ETF 操盤手共識報表 · %s' % date

    def section(title, color, rows, side):
        return ("<h3 style='color:%s;margin:16px 0 4px;font-size:15px'>%s</h3>"
                "<table style='border-collapse:collapse;width:100%%;font-size:13px'>%s</table>"
                % (color, title, _table_html(rows, side, limit)))

    html_doc = (
        "<div style='font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:700px;color:#222'>"
        "<h2 style='margin:0 0 2px'>\U0001F4CB ETF 操盤手共識報表</h2>"
        "<div style='color:#888;font-size:12px;margin-bottom:6px'>%s（對比 %s） · 彙總 %d 檔主動 ETF · "
        "新增 %d / 移除 %d / 加減碼 %d</div>"
        % (date, prev, etf_count, summ.get('new', 0), summ.get('removed', 0), summ.get('changed', 0))
        + section('\U0001F4C8 潛在上漲（買盤共識）', RED, up, 'up')
        + section('\U0001F4C9 潛在下跌（賣盤共識）', GREEN, down, 'down')
        + "<div style='color:#aaa;font-size:11px;margin-top:16px'>⚠ 僅反映主動 ETF 當日持股異動,非投資建議。</div></div>")

    return subject, html_doc, build_text(delta)


def build_text(delta):
    up, down, net, etf_count = _agg(delta)
    date = delta.get('date', '')

    def line(s, side):
        if side == 'up':
            t = '新增%d/加碼%d 權重%.2f%%' % (s['add'], s['inc'], s['wIn'])
        else:
            t = '移除%d/減碼%d 權重%.2f%%' % (s['rm'], s['dec'], s['wOut'])
        return '%s %s  %s' % (s['code'], s['name'], t)

    L = ['ETF 操盤手共識報表 %s' % date, '彙總 %d 檔主動 ETF' % etf_count, '',
         '=== 潛在上漲(買盤共識) ===']
    L += [line(s, 'up') for s in up[:20]] or ['無']
    L += ['', '=== 潛在下跌(賣盤共識) ===']
    L += [line(s, 'down') for s in down[:20]] or ['無']
    L += ['', '⚠ 僅反映主動 ETF 當日持股異動,非投資建議。']
    return '\n'.join(L)
