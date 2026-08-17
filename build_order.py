#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_order.py — 模組載入順序的「相依宣告 + 自動排序」（藍圖 P5）

把原本散在 build_v2.py 註解裡的「須在 X 後」變成可執行的相依表，
由穩定拓樸排序自動產生正確順序，取代人工維護順序。

安全保證
--------
* 穩定排序：當目前順序「已滿足」所有相依時，輸出與輸入「完全相同」。
* 以「檔名(basename)」比對。
* build_v2.py 以 try/except 接入：本檔若缺檔或出錯，自動退回原順序。

用法：被 build_v2.py import；或直接 `python build_order.py` 跑 self-test。
"""
import os

# 相依宣告：key 必須排在 value(們) 之後。
DEPS = {
    'table_sort_v5.js':     ['colors_v3.js'],
    'volume_profile_v3.js': ['pro_v2.js'],
    'alert_push_v3.js':     ['alert_v3.js'],
    'backtest_ui_v3.js':    ['backtest_v3.js'],
    'strategy_builder_v3.js': ['backtest_v3.js'],
    'strategy_script_v3.js':  ['strategy_builder_v3.js'],
    'wizard_v3.js':         ['strategy_builder_v3.js', 'backtest_v3.js', 'drawtools_v3.js'],
    'portfolio_v3.js':      ['supplychain_v3.js'],
    'chainmom_v3.js':       ['supplychain_v3.js'],
    'polish_v3.js':         ['chart_registry_v3.js', 'colors_v3.js'],
    'market_score_bar_v3.js': ['toast_v3.js', 'fundamental_v3.js'],
    'market_chart_v3.js':   ['toolbar_v3.js', 'polish_v3.js', 'drawtools_v3.js', 'market_score_bar_v3.js'],
    # Viz 共用視覺：所有消費面板須在 viz_v5 之後
    'viz_v5.js':            ['colors_v3.js'],
    'chip_v3.js':           ['viz_v5.js'],
    'instrank_v3.js':       ['viz_v5.js'],
    'marketflow_v3.js':     ['viz_v5.js'],
    'pulse_v5.js':          ['viz_v5.js'],
    'decision_data_v5.js':  ['market_data_v5.js'],
    'market_data_v5.js':    ['app_kernel_v5.js'],
    'decision_v5.js':       ['viz_v5.js', 'decision_data_v5.js', 'shell_v5.js'],
    'hub_v5.js':            ['viz_v5.js'],
    'breadth_v5.js':        ['viz_v5.js'],
    'afterhours_v5.js':     ['viz_v5.js'],
    'scan_v5.js':           ['viz_v5.js'],
    'news_v5.js':           ['viz_v5.js'],
    'book_v5.js':           ['viz_v5.js'],
    'heat_v5.js':           ['viz_v5.js'],
    'chart_visual_v5.js':   ['colors_v3.js', 'visual_system_v5.js'],
    'realtime_v3.js':       ['intraday_volume_v3.js'],
}
# 必須永遠排在最後的（market_chart 蓋過 K 線；score_bar 次末；toolbar 再前）
LAST = ['toolbar_v3.js', 'market_score_bar_v3.js', 'market_chart_v3.js']

def order_scripts(scripts):
    """穩定拓樸排序：盡量保持原順序，只在違反相依時把節點往後挪。"""
    base = [os.path.basename(s) for s in scripts]
    by_base = {os.path.basename(s): s for s in scripts}
    present = set(base)
    deps = {b: [d for d in DEPS.get(b, []) if d in present] for b in base}
    others = [b for b in base if b not in LAST]
    for b in base:
        if b in LAST:
            deps[b] = list(set(deps.get(b, []) + others))

    result, placed = [], set()
    remaining = list(base)
    guard = 0
    while remaining:
        guard += 1
        if guard > len(base) * len(base) + 10:
            result.extend(remaining); break
        for i, b in enumerate(remaining):
            if all(d in placed for d in deps[b]):
                result.append(b); placed.add(b)
                remaining.pop(i)
                break
        else:
            result.extend(remaining); break
    return [by_base[b] for b in result]


# ── 與 build_v2.py V2_SCRIPTS（經 order_scripts 後）對齊的基準清單 ──────────
_CURRENT = [
    'colors_v3.js', 'app_kernel_v5.js', 'market_data_v5.js', 'decision_data_v5.js', 'table_sort_v5.js', 'viz_v5.js', 'market_v3.js', 'fields_v3.js', 'chart_registry_v3.js',
    'share_v3.js', 'datasources_v3.js', 'etf_flow_tip_v3.js',
    'position_v2.js', 'watch_v2.js', 'info_v2.js', 'pro_v2.js', 'volume_profile_v3.js',
    'pattern_v3.js', 'live_v2.js', 'chip_v3.js', 'fundamental_v3.js', 'screener_v3.js',
    'ai_report_v3.js', 'polish_v3.js', 'wl_live_v3.js', 'plan_history_v3.js',
    'plan_position_v3.js', 'plan_v3.js', 'pdf_import_v3.js', 'pdf_export_v3.js', 'peg_v3.js',
    'alert_v3.js', 'alert_push_v3.js', 'backtest_v3.js', 'backtest_ui_v3.js', 'enhance_v3.js',
    'aftermarket_v3.js', 'overnight_v3.js', 'supplychain_v3.js', 'portfolio_v3.js',
    'chainmom_v3.js', 'valuation_v3.js', 'marketflow_v3.js', 'instrank_v3.js',
    'calendar_v3.js', 'multichart_v3.js', 'spread_v3.js', 'hotkeys_v3.js',
    'strategy_builder_v3.js', 'strategy_script_v3.js', 'drawtools_v3.js',
    'screener3_v3.js', 'etf_v3.js', 'stockfut_v3.js', 'indices_v3.js', 'datahealth_v3.js',
    'toast_v3.js', 'settle_v3.js', 'cmdpalette_v3.js', 'dragwin_v3.js', 'liverefresh_v3.js',
    'namesearch_v3.js', 'intraday_volume_v3.js', 'realtime_v3.js', 'focus_v3.js', 'copilot_v3.js',
    'wizard_v3.js', 'shell_v5.js', 'hub_v5.js', 'pulse_v5.js', 'decision_v5.js', 'heat_v5.js', 'book_v5.js',
    'scan_v5.js', 'breadth_v5.js', 'afterhours_v5.js', 'news_v5.js',
    'visual_system_v5.js', 'chart_visual_v5.js',
    'toolbar_v3.js', 'market_score_bar_v3.js', 'market_chart_v3.js',
]

def _selftest():
    out = order_scripts(_CURRENT)
    assert out == _CURRENT, 'order changed!\n' + '\n'.join(
        f'{i}: {a} != {b}' for i, (a, b) in enumerate(zip(out, _CURRENT)) if a != b)
    bad = _CURRENT[:]
    i_b = bad.index('strategy_builder_v3.js'); i_s = bad.index('strategy_script_v3.js')
    bad[i_b], bad[i_s] = bad[i_s], bad[i_b]
    fixed = order_scripts(bad)
    assert fixed.index('strategy_script_v3.js') > fixed.index('strategy_builder_v3.js'), 'dep not enforced'
    assert fixed[-1] == 'market_chart_v3.js', 'market_chart not last'
    assert fixed.index('toolbar_v3.js') < fixed.index('market_chart_v3.js')
    assert fixed.index('chart_registry_v3.js') < fixed.index('polish_v3.js')
    assert fixed.index('market_score_bar_v3.js') < fixed.index('market_chart_v3.js')
    print('build_order self-test PASSED：目前順序零變動，且相依/最後位置可強制修正。')

if __name__ == '__main__':
    _selftest()
