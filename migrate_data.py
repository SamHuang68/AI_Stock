#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_data.py — 後端資料分區（藍圖 P4 的「/data」一步）

把使用者資料檔／資料夾搬進 /data，並把所有後端 .py 裡的路徑常數同步指到 /data。
server.py / daemon 仍留在根目錄（由 .bat 從根目錄啟動、彼此相對依賴，不動）。

為什麼安全
----------
* 每個資料路徑都是同一種寫法： os.path.join(<__file__ 目錄>, '<檔名>')，
  本腳本只把 ", '<檔名>')" 改成 ", 'data', '<檔名>')"，比對夠精確、不會誤中
  字典鍵('etf_history_files')或安全黑名單('/etf_history')。
* server.py 的下載黑名單用「子字串」比對（'alert_config' / '/chip_history' …），
  搬到 /data 後 '/data/chip_history' 仍含這些子字串 → 防護不變，無需改。
* 冪等：已搬過 / 已改過的自動略過，可重複執行。
* 可逆：被 git 追蹤的用 git mv；被 .gitignore 的(多數資料檔)用一般搬移，
  腳本最後會印出「反向搬回」指令以便還原；.py 改動可用 git checkout 還原。

用法
----
    python migrate_data.py            # 預演：只印計畫，不動任何東西
    python migrate_data.py --apply    # 實際搬移 + 改路徑
執行後：重新啟動 server.py，並各跑一次 daemon／tracker 確認讀寫資料正常。
"""
import os, re, sys, shutil, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
APPLY = '--apply' in sys.argv
DATA = 'data'

# 要搬進 /data 的檔案與資料夾
DATA_FILES = ['etf_catalog.json', 'ai_key.txt', 'alert_config.json', 'alert_rules.json',
              'watch_rules.json', 'watch_state.json', 'draw_store.json']
DATA_DIRS  = ['chip_history', 'etf_history']

# 在 .py 路徑常數裡，這些 token 以 ", 'token')" 形式出現 → 改成 ", 'data', 'token')"
JOIN_TOKENS = DATA_FILES + DATA_DIRS

# 會引用到上述資料的後端 .py（精準清單）
PY_TARGETS = ['server.py', 'etf_delta_tracker.py', 'chip_history_tracker.py',
              'alert_daemon.py', 'watch_daemon.py', 'expand_etf_catalog.py']

def is_tracked(rel):
    try:
        subprocess.run(['git', '-C', ROOT, 'ls-files', '--error-unmatch', rel],
                       check=True, capture_output=True)
        return True
    except Exception:
        return False

def move_path(rel):
    """回傳 (做了什麼描述, 反向指令) 或 None(略過)。"""
    src = os.path.join(ROOT, rel)
    dst_rel = DATA + '/' + rel
    dst = os.path.join(ROOT, dst_rel)
    if not os.path.exists(src):
        return None                      # 不存在 → 略過
    if os.path.exists(dst):
        return None                      # 已就位 → 冪等略過
    desc = f'{rel}  →  {dst_rel}'
    undo = f'move "{DATA}\\{rel.replace("/", os.sep)}" "{rel.replace("/", os.sep)}"'
    if APPLY:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if is_tracked(rel):
            subprocess.run(['git', '-C', ROOT, 'mv', rel, dst_rel], check=True)
        else:
            shutil.move(src, dst)
    return desc, undo

PATCHED = {}   # fname -> 改寫後的內容（dry-run 也算，供驗證用）

def patch_py(fname):
    path = os.path.join(ROOT, fname)
    if not os.path.isfile(path):
        return None
    txt = open(path, encoding='utf-8').read()
    orig = txt
    for tok in JOIN_TOKENS:
        already = f", '{DATA}', '{tok}')"
        if already in txt:
            # 該 token 已改過；仍可能有其他 token 未改 → 繼續處理其它 token
            continue
        txt = txt.replace(f", '{tok}')", f", '{DATA}', '{tok}')")
    # backup_data.py 特例：os.path.join(BASE, d) 迴圈 → 指到 data/
    if fname == 'backup_data.py':
        if "os.path.join(BASE, 'data', d)" not in txt:
            txt = txt.replace("os.path.join(BASE, d)", "os.path.join(BASE, 'data', d)")
    PATCHED[fname] = txt
    changed = (txt != orig)
    if changed and APPLY:
        open(path, 'w', encoding='utf-8').write(txt)
    return changed

def main():
    print('=' * 64)
    print('migrate_data.py — ' + ('APPLY' if APPLY else 'DRY-RUN（預演，未動任何東西）'))
    print('=' * 64)

    undo_cmds = []
    print('\n[1] 搬移資料 → /data')
    any_move = False
    for rel in DATA_FILES + DATA_DIRS:
        r = move_path(rel)
        if r:
            any_move = True
            print('   move  ' + r[0]); undo_cmds.append(r[1])
    if not any_move:
        print('   （沒有需要搬的；可能已全部就位）')

    print('\n[2] 更新後端 .py 路徑常數 → data/')
    # backup_data.py 也要處理(特例)
    for fn in PY_TARGETS + ['backup_data.py']:
        c = patch_py(fn)
        if c is None:
            print(f'   - {fn}: 找不到，略過')
        elif c:
            print(f'   ✓ {fn}: ' + ('已更新' if APPLY else '將更新'))
        else:
            print(f'   · {fn}: 無需更新（已是 data/ 或無引用）')

    print('\n[3] 驗證：掃描是否還有「根目錄」殘留引用')
    leftovers = []
    for fn in PY_TARGETS + ['backup_data.py']:
        p = os.path.join(ROOT, fn)
        if not os.path.isfile(p):
            continue
        # 用改寫後內容驗證（dry-run 也準確）
        t = PATCHED.get(fn) or open(p, encoding='utf-8').read()
        for tok in JOIN_TOKENS:
            # 仍有 ", 'tok')" 但「不是」 ", 'data', 'tok')" → 殘留
            if f", '{tok}')" in t and f", '{DATA}', '{tok}')" not in t:
                leftovers.append(f'{fn}: {tok}')
    if leftovers:
        print('   ⚠ 仍有未改到的引用（請檢查）：')
        for x in leftovers:
            print('      -', x)
    else:
        print('   ✓ 後端 .py 已無指向根目錄的資料引用' + ('' if APPLY else '（預演推算）'))

    print('\n下一步：')
    if not APPLY:
        print('   確認無誤 → python migrate_data.py --apply')
    else:
        print('   1) 重新啟動 server.py，開頁面點幾個功能（資金流/法人榜/畫線/AI報告）確認資料讀得到')
        print('   2) 手動各跑一次：python chip_history_tracker.py / alert_daemon.py / watch_daemon.py')
        print('   還原：git checkout -- ' + ' '.join(PY_TARGETS + ['backup_data.py']))
        if undo_cmds:
            print('         被忽略的資料檔搬回（Windows）：')
            for u in undo_cmds:
                print('           ' + u)
    print('=' * 64)

if __name__ == '__main__':
    main()
