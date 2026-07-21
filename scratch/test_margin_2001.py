#!/usr/bin/env python3
import sys, time
sys.path.insert(0, 'server')
from datetime import date
import margin_ratio as mr

def run(d):
    t0 = time.time()
    r = mr.compute_ratio_for_date(d)
    print(d, r, 'sec', round(time.time() - t0, 1),
          'cache', len(mr._yahoo_series_cache), 'fail', len(mr._yahoo_fail), flush=True)
    return r

if __name__ == '__main__':
    run(date(2001, 1, 5))
    run(date(2001, 1, 8))
    run(date(2005, 1, 3))
