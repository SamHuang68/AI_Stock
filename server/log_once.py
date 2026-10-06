"""限頻記錄：同一個 key＋例外型別在 interval 秒內只記一行。

用在「不能讓請求失敗、但也不能悄悄吞掉錯誤」的備援路徑（共用規則 0014）。
key 加上例外型別，所以第一次出現的新型別（例如 NameError）一定會立刻記錄，
不會被先前同 key 的連線逾時蓋掉。
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_LAST: dict[tuple[str, str], float] = {}
DEFAULT_INTERVAL = 600.0


def log_once(key: str, message: str = '', *, exc: BaseException | None = None,
             interval: float = DEFAULT_INTERVAL, now: float | None = None, out=None) -> bool:
    """寫出一行並回 True；限頻內已記過則回 False。"""
    kind = type(exc).__name__ if exc is not None else ''
    stamp = time.monotonic() if now is None else now
    with _LOCK:
        last = _LAST.get((key, kind))
        if last is not None and stamp - last < interval:
            return False
        _LAST[(key, kind)] = stamp
    detail = f'{kind}: {exc}' if exc is not None else ''
    line = f'[{key}] ' + ' '.join(part for part in (message, detail) if part)
    if out is None:
        print(line, flush=True)
    else:
        print(line, file=out, flush=True)
    return True


def reset_for_tests() -> None:
    with _LOCK:
        _LAST.clear()
