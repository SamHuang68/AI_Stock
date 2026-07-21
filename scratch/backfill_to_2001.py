#!/usr/bin/env python3
"""Backfill margin ratio history in phases toward 2001."""
import sys
sys.path.insert(0, 'server')
from datetime import date
import margin_ratio as mr

def main():
    # Phase 1: TWSE MI_INDEX era (2004-02-11 → day before existing dense 2015)
    print('PHASE1 2004-02-11 → 2014-12-31', flush=True)
    r1 = mr.backfill_history(start=date(2004, 2, 11), end=date(2014, 12, 31), resume=True)
    print('PHASE1 DONE', r1, flush=True)

    # Phase 2: pre-MI_INDEX via Yahoo closes (2001-01-05 → 2004-02-10)
    print('PHASE2 2001-01-05 → 2004-02-10 (Yahoo closes)', flush=True)
    r2 = mr.backfill_history(start=date(2001, 1, 5), end=date(2004, 2, 10), resume=True)
    print('PHASE2 DONE', r2, flush=True)

    print('META', mr.meta_summary(), flush=True)

if __name__ == '__main__':
    main()
