#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modularize.py — 前端模組資料夾化（藍圖 P3）

把散在根目錄的前端 JS/CSS 依功能分類搬進 /src/<category>/，並同步更新
build_v2.py 的 V2_SCRIPTS / V2_STYLES 路徑。markdown 文件搬進 /docs。

設計重點
--------
* 安全：只動「前端檔案」。server.py / 各 daemon / *.json 資料 / *.bat 一律不動
  （它們用相對路徑互相依賴、由 .bat 從根目錄啟動，搬動會連鎖出錯）。
* server.py 用 SimpleHTTPRequestHandler 由根目錄啟動，會自動服務子資料夾，
  因此瀏覽器仍能抓到 src/core/pro_v2.js —— 不需改 server.py。
* build_v2.py 既有寫法 os.path.join(ROOT, js) 與 <script src="{js}"> 對「相對路徑」
  完全相容，故只需把清單字串改成新路徑，build 邏輯一行都不用改。
* 可逆：用 git mv 保留歷史；要還原 → `git checkout . && git clean -fd src docs`
* 冪等：重跑不會出錯，已搬過的自動略過。

用法
----
    python modularize.py            # 預演(dry-run)，只印計畫不動檔案
    python modularize.py --apply    # 實際執行
    python modularize.py --apply --no-git   # 不用 git，改用檔案搬移

執行後務必：  python build_v2.py   重新打包，再開頁面確認工具列與各功能正常。
"""
import os, re, sys, shutil, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
APPLY  = '--apply'  in sys.argv
USE_GIT = '--no-git' not in sys.argv

# ── 分類設定（基底檔名 → src 子資料夾）──────────────────────────────────────
CATEGORY = {
    # 核心：報價/自選/部位/即時
    'core': ['position_v2.js', 'watch_v2.js', 'info_v2.js', 'pro_v2.js', 'live_v2.js',
             'realtime_v3.js', 'liverefresh_v3.js', 'wl_live_v3.js', 'wlgroup_v3.js',
             'namesearch_v3.js', 'indices_v3.js', 'etf_v3.js', 'etf_v2.js', 'peg_v3.js'],
    # 圖表：量價/多圖/畫線/型態
    'chart': ['volume_profile_v3.js', 'multichart_v3.js', 'spread_v3.js', 'drawtools_v3.js',
              'overnight_v3.js', 'aftermarket_v3.js', 'heatmap_v3.js', 'pattern_v2.js',
              'pattern_v3.js', 'hotkeys_v3.js'],
    # 選股/策略/回測
    'screener': ['screener_v3.js', 'screener3_v3.js', 'strategy_builder_v3.js',
                 'strategy_script_v3.js', 'backtest_v3.js', 'backtest_ui_v3.js',
                 'wizard_v3.js', 'macro_v3.js'],
    # 籌碼基本面/計畫
    'fundamental': ['fundamental_v3.js', 'valuation_v3.js', 'marketflow_v3.js', 'instrank_v3.js',
                    'supplychain_v3.js', 'stockfut_v3.js', 'chip_v3.js',
                    'plan_v3.js', 'plan_history_v3.js', 'plan_position_v3.js'],
    # 快訊/通知/行事曆/資料源
    'alert': ['toast_v3.js', 'alert_v3.js', 'alert_push_v3.js', 'calendar_v3.js',
              'datahealth_v3.js', 'settle_v3.js'],
    # AI / 指令 / 焦點
    'ai': ['ai_report_v3.js', 'cmdpalette_v3.js', 'focus_v3.js'],
    # 介面外觀 / 匯出 / 工具列
    'ui': ['toolbar_v3.js', 'dragwin_v3.js', 'polish_v3.js', 'enhance_v3.js',
           'pdf_import_v3.js', 'pdf_export_v3.js', 'mobile_v2.css'],
}
# 反查：basename → 'src/<cat>'
DEST = {}
for cat, files in CATEGORY.items():
    for fn in files:
        DEST[fn] = 'src/' + cat

DOCS_GLOB_EXT = '.md'   # markdown → docs/

moves = []   # (src_rel, dst_rel)

def plan_moves():
    # 1) 前端 js/css → src/<cat>/
    for fn, dst_dir in DEST.items():
        src_path = os.path.join(ROOT, fn)
        if not os.path.isfile(src_path):
            continue   # 檔案不存在(或已搬走) → 略過,冪等
        dst_rel = dst_dir + '/' + fn
        if os.path.isfile(os.path.join(ROOT, dst_rel)):
            continue   # 已就位
        moves.append((fn, dst_rel))
    # 2) *.md → docs/
    for fn in sorted(os.listdir(ROOT)):
        if fn.lower().endswith(DOCS_GLOB_EXT) and os.path.isfile(os.path.join(ROOT, fn)):
            dst_rel = 'docs/' + fn
            if not os.path.isfile(os.path.join(ROOT, dst_rel)):
                moves.append((fn, dst_rel))

def git_ok():
    if not USE_GIT:
        return False
    try:
        subprocess.run(['git', '-C', ROOT, 'rev-parse', '--is-inside-work-tree'],
                       check=True, capture_output=True)
        return True
    except Exception:
        return False

def do_move(src_rel, dst_rel, use_git):
    dst_abs = os.path.join(ROOT, dst_rel)
    os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
    if use_git:
        try:
            subprocess.run(['git', '-C', ROOT, 'mv', src_rel, dst_rel],
                           check=True, capture_output=True)
            return
        except Exception:
            pass   # git mv 失敗(未追蹤/邊界情況) → 退回一般檔案搬移,保證搬得動
    shutil.move(os.path.join(ROOT, src_rel), dst_abs)

def patch_build():
    """把 build_v2.py 的 V2_SCRIPTS / V2_STYLES 清單字串改成新相對路徑。
       只在清單區塊內取代，避免誤改註解或其他程式碼。build 邏輯不動。"""
    bp = os.path.join(ROOT, 'build_v2.py')
    if not os.path.isfile(bp):
        print('  ! 找不到 build_v2.py，略過清單更新')
        return
    txt = open(bp, encoding='utf-8').read()
    orig = txt

    def patch_block(text, var):
        m = re.search(var + r'\s*=\s*\[(.*?)\]', text, re.S)
        if not m:
            return text
        block = m.group(1)
        new_block = block
        for fn, dst_dir in DEST.items():
            new_path = dst_dir + '/' + fn
            # 'fn'  或  "fn"  → 'new_path'（已是新路徑則不動）
            for q in ("'", '"'):
                new_block = new_block.replace(q + fn + q, q + new_path + q)
        return text[:m.start(1)] + new_block + text[m.end(1):]

    txt = patch_block(txt, 'V2_SCRIPTS')
    txt = patch_block(txt, 'V2_STYLES')
    if txt != orig and APPLY:
        open(bp, 'w', encoding='utf-8').write(txt)
    return txt != orig

def verify(build_txt):
    """確認 build_v2.py 清單裡每個檔案都能在磁碟上找到（搬移後）。"""
    bp = os.path.join(ROOT, 'build_v2.py')
    txt = build_txt if (build_txt and APPLY) else open(bp, encoding='utf-8').read()
    entries = re.findall(r"['\"]([\w./-]+\.(?:js|css))['\"]", txt)
    missing = []
    for e in entries:
        base = os.path.basename(e)
        # 預期搬移後的位置
        dst = (DEST[base] + '/' + base) if base in DEST else e
        # 找得到即可：搬移後在 dst；預演時仍在根目錄(base) 或原路徑(e)
        ok = (os.path.isfile(os.path.join(ROOT, dst))
              or os.path.isfile(os.path.join(ROOT, base))
              or os.path.isfile(os.path.join(ROOT, e)))
        if not ok:
            missing.append(dst)
    return entries, missing

def main():
    plan_moves()
    use_git = git_ok()
    mode = 'APPLY' if APPLY else 'DRY-RUN（預演，未動任何檔案）'
    print('=' * 64)
    print(f'modularize.py — {mode}   (git={"on" if use_git else "off"})')
    print('=' * 64)
    if not moves:
        print('沒有需要搬移的檔案（可能已全部就位）。')
    for s, d in moves:
        print(f'  move  {s:32s} → {d}')
        if APPLY:
            try:
                do_move(s, d, use_git)
            except Exception as ex:
                print(f'    ! 搬移失敗: {ex}')

    changed = patch_build()
    print(f'\nbuild_v2.py 清單路徑更新: {"已更新" if (changed and APPLY) else ("將更新" if changed else "無需更新")}')

    entries, missing = verify(None if not APPLY else open(os.path.join(ROOT,"build_v2.py"),encoding="utf-8").read())
    print(f'\n驗證：build 清單共 {len(entries)} 個前端檔')
    if missing:
        print('  ✗ 以下檔案在預期位置找不到（請檢查）：')
        for m in missing:
            print('     -', m)
    else:
        print('  ✓ 全部檔案都能在預期位置找到' + ('' if APPLY else '（預演結果；--apply 後才會真的成立）'))

    print('\n下一步：')
    if not APPLY:
        print('  1) 確認上面計畫無誤 → 執行：  python modularize.py --apply')
    else:
        print('  1) 重新打包：  python build_v2.py')
        print('  2) 開頁面確認工具列與各功能正常')
        print('  還原（如有問題）：  git checkout . && git clean -fd src docs')
    print('=' * 64)

if __name__ == '__main__':
    main()
