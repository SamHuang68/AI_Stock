#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_backend.py — 後端/腳本分區（藍圖 P4b）

把後端服務 .py 搬進 /server、把 .bat 搬進 /scripts，並修好所有連動路徑。
留在根目錄：build_v2.py / build_order.py / 三支 migrate/fix 工具 / 報表 .py /
            HTML / src / data / docs / logs / backups。

為什麼這樣切才安全（已逐一查證）
--------------------------------
* server.py 啟動時 os.chdir(自己的資料夾) 來服務靜態檔 → 搬到 /server 後，
  改成 chdir 到「上一層(專案根)」，靜態服務(HTML/src/data)才正確。
* server.py 的資料路徑(L33/34/37/41/44/436) 用 __file__ 目錄 → 改成「上一層」指到 /data。
* 但 server.py L657 用 __file__ 目錄找「同層的 etf_delta_tracker.py」當子程序 →
  這個「不能改」；因此 etf_delta_tracker.py 必須跟 server.py 一起搬到 /server(維持同層)。
* 各 daemon/tracker 的 _BASE/BASE/SCRIPT_DIR 只拿來找 data/、backups/、logs/(都在根) →
  一律改成「上一層」。
* .bat 全部改 cd "%~dp0" → cd "%~dp0.."(回根目錄)；對「已搬到 /server」的腳本，
  python 呼叫加上 server\ 前綴；build_v2.py / 報表 .py 仍在根，呼叫不變。
* 還原超簡單：全部檔案都被 git 追蹤，git mv 搬移 → 出事 `git reset --hard HEAD`
  + `git clean -fd server scripts` 即回到目前 commit。

用法
----
    python migrate_backend.py            # 預演：只印計畫
    python migrate_backend.py --apply    # 實際搬移 + 改路徑
執行後務必：用 .\scripts\start_terminal_v3.bat 啟動，確認頁面 + 資金流/法人榜/畫線/AI報告，
            並各跑一次 daily_chip.bat / daily_backup.bat 確認 daemon 讀寫資料正常。
"""
import os, re, sys, shutil, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
APPLY = '--apply' in sys.argv

# 搬進 /server 的後端 .py（server.py 與它 spawn 的 etf_delta_tracker 必須同層）
SERVER_PY = ['server.py', 'alert_daemon.py', 'watch_daemon.py', 'chip_history_tracker.py',
             'etf_delta_tracker.py', 'backup_data.py', 'expand_etf_catalog.py']
MOVED = set(SERVER_PY)

OLD_BASE = "os.path.dirname(os.path.abspath(__file__))"
NEW_BASE = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"

def git_ok():
    try:
        subprocess.run(['git', '-C', ROOT, 'rev-parse', '--is-inside-work-tree'],
                       check=True, capture_output=True); return True
    except Exception:
        return False

def do_move(rel, dst_rel, use_git):
    dst = os.path.join(ROOT, dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if use_git:
        try:
            subprocess.run(['git', '-C', ROOT, 'mv', rel, dst_rel],
                           check=True, capture_output=True); return
        except Exception:
            pass
    shutil.move(os.path.join(ROOT, rel), dst)

def patch_server(txt):
    # 資料路徑(後面接 , 'data') → 指到上一層；保留 L657 的同層用法(它後面不接 'data')
    txt = txt.replace(f"{OLD_BASE}, 'data'", f"{NEW_BASE}, 'data'")
    # 靜態服務 chdir → 上一層(專案根)
    txt = txt.replace(f"os.chdir({OLD_BASE})", f"os.chdir({NEW_BASE})")
    return txt

def patch_daemon(txt):
    # 這些檔的 base 只有一處、且都指向專案根資產 → 整支提升一層(有防重複保護)
    if NEW_BASE in txt:
        return txt                      # 已改過
    return txt.replace(OLD_BASE, NEW_BASE)

def patch_bat(txt):
    txt = txt.replace('cd /d "%~dp0"', 'cd /d "%~dp0.."')
    for name in MOVED:
        # python <name>  →  python server\<name>（涵蓋 cmd /c "python <name>" 形式）
        if f"python server\\{name}" in txt:
            continue                    # 已改過
        txt = txt.replace(f"python {name}", f"python server\\{name}")
    return txt

def main():
    use_git = git_ok()
    print('=' * 64)
    print('migrate_backend.py — ' + ('APPLY' if APPLY else 'DRY-RUN（預演）') +
          f'   (git={"on" if use_git else "off"})')
    print('=' * 64)

    bats = sorted(f for f in os.listdir(ROOT) if f.lower().endswith('.bat'))

    print('\n[1] 搬移後端 .py → /server')
    for fn in SERVER_PY:
        if not os.path.isfile(os.path.join(ROOT, fn)):
            print(f'   - {fn}: 不在根目錄，略過'); continue
        print(f'   move  {fn}  →  server/{fn}')
        if APPLY: do_move(fn, f'server/{fn}', use_git)

    print('\n[2] 搬移 .bat → /scripts')
    for fn in bats:
        print(f'   move  {fn}  →  scripts/{fn}')
        if APPLY: do_move(fn, f'scripts/{fn}', use_git)

    print('\n[3] 改路徑')
    # server.py + daemons：改檔內 base/chdir（檔案已在 server/）
    for fn in SERVER_PY:
        p = os.path.join(ROOT, 'server', fn) if APPLY else os.path.join(ROOT, fn)
        if not os.path.isfile(p):
            print(f'   - {fn}: 找不到，略過'); continue
        t = open(p, encoding='utf-8').read()
        t2 = patch_server(t) if fn == 'server.py' else patch_daemon(t)
        print(f'   {"✓" if t2 != t else "·"} {fn}: ' + ('改路徑' if t2 != t else '無需改'))
        if APPLY and t2 != t: open(p, 'w', encoding='utf-8').write(t2)
    # .bat：cd 回根 + server\ 前綴
    for fn in bats:
        p = os.path.join(ROOT, 'scripts', fn) if APPLY else os.path.join(ROOT, fn)
        if not os.path.isfile(p): continue
        t = open(p, encoding='utf-8', errors='replace').read()
        t2 = patch_bat(t)
        if APPLY and t2 != t: open(p, 'w', encoding='utf-8', errors='replace').write(t2)

    print('\n[4] 驗證')
    warn = []
    if APPLY:
        for fn in SERVER_PY:
            if not os.path.isfile(os.path.join(ROOT, 'server', fn)): warn.append('缺 server/' + fn)
        sp = os.path.join(ROOT, 'server', 'server.py')
        if os.path.isfile(sp):
            st = open(sp, encoding='utf-8').read()
            if f"os.chdir({NEW_BASE})" not in st: warn.append('server.py chdir 未提升一層')
            if f"{OLD_BASE}, 'data'" in st: warn.append('server.py 仍有未提升的 data 路徑')
        # build_dist.bat 會因檔案搬移而打包失敗(僅影響「製作發佈包」，非日常)
        if os.path.isfile(os.path.join(ROOT, 'scripts', 'build_dist.bat')):
            warn.append('提醒：build_dist.bat 的 FILES 清單仍用舊路徑，若要做發佈包需另外更新(非日常功能)')
    if warn:
        print('   ⚠ ' + '\n   ⚠ '.join(warn))
    else:
        print('   ✓ ' + ('檢查通過' if APPLY else '預演完成，--apply 後會實際驗證'))

    print('\n下一步：')
    if not APPLY:
        print('   確認無誤 → python migrate_backend.py --apply')
    else:
        print('   1) 啟動： .\\scripts\\start_terminal_v3.bat  → 開頁面點 資金流/法人榜/畫線/AI報告')
        print('   2) 排程： .\\scripts\\daily_chip.bat 與 .\\scripts\\daily_backup.bat 各跑一次確認 daemon 正常')
        print('   3) 若用 Windows 排程器，請重跑 scripts\\install_*.bat 以更新工作路徑')
        print('   還原： git reset --hard HEAD  然後  git clean -fd server scripts')
    print('=' * 64)

if __name__ == '__main__':
    main()
