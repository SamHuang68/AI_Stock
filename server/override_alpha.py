# -*- coding: utf-8 -*-
"""Override Alpha Tracking — log ST→WD macro overlays for post-hoc review.

Lightweight SQLite under data/override_alpha.db. No pip.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DB = DATA / 'override_alpha.db'
TZ8 = timezone(timedelta(hours=8))

_lock = threading.RLock()


def _now_iso() -> str:
    return datetime.now(TZ8).strftime('%Y-%m-%d %H:%M:%S')


def _conn() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB), timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock:
        with _conn() as c:
            c.execute(
                '''CREATE TABLE IF NOT EXISTS override_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    style INTEGER,
                    delever INTEGER,
                    score REAL,
                    adv_ratio REAL,
                    spillover REAL,
                    rotation TEXT,
                    hot_stage TEXT,
                    twii REAL,
                    wd_equity REAL,
                    wd_equity_chg REAL,
                    wd_fsm TEXT,
                    wd_style INTEGER,
                    note TEXT,
                    source TEXT,
                    meta_json TEXT
                )'''
            )
            c.commit()


init_db()


def log_event(body: dict[str, Any]) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    meta = body.get('meta') if isinstance(body.get('meta'), dict) else {}
    row = {
        'ts': body.get('ts') or _now_iso(),
        'style': body.get('style'),
        'delever': 1 if body.get('delever') else 0,
        'score': body.get('score', meta.get('score')),
        'adv_ratio': body.get('advRatio', meta.get('advRatio')),
        'spillover': body.get('spillover_prob', meta.get('spillover_prob')),
        'rotation': body.get('rotation', meta.get('rotation')),
        'hot_stage': body.get('hot_stage', meta.get('hot_stage')),
        'twii': body.get('twii'),
        'wd_equity': body.get('wd_equity'),
        'wd_equity_chg': body.get('wd_equity_chg'),
        'wd_fsm': body.get('wd_fsm'),
        'wd_style': body.get('wd_style'),
        'note': str(body.get('note') or '')[:400],
        'source': str(body.get('source') or meta.get('source') or '')[:64],
        'meta_json': json.dumps(meta, ensure_ascii=False)[:2000],
    }
    with _lock:
        with _conn() as c:
            cur = c.execute(
                '''INSERT INTO override_log
                   (ts, style, delever, score, adv_ratio, spillover, rotation, hot_stage,
                    twii, wd_equity, wd_equity_chg, wd_fsm, wd_style, note, source, meta_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    row['ts'], row['style'], row['delever'], row['score'], row['adv_ratio'],
                    row['spillover'], row['rotation'], row['hot_stage'], row['twii'],
                    row['wd_equity'], row['wd_equity_chg'], row['wd_fsm'], row['wd_style'],
                    row['note'], row['source'], row['meta_json'],
                ),
            )
            c.commit()
            rid = int(cur.lastrowid)
    return {'ok': True, 'id': rid, 'ts': row['ts']}


def recent(limit: int = 40) -> list[dict[str, Any]]:
    lim = max(1, min(200, int(limit)))
    with _lock:
        with _conn() as c:
            rows = c.execute(
                'SELECT * FROM override_log ORDER BY id DESC LIMIT ?', (lim,)
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d['delever'] = bool(d.get('delever'))
        out.append(d)
    return out


def summary_for_review(limit: int = 30) -> str:
    """Plain-text pack for local LLM post-mortem."""
    items = recent(limit)
    if not items:
        return '尚無覆寫紀錄。'
    lines = ['【ST Override Alpha Log｜最近 %d 筆】' % len(items)]
    for it in reversed(items):  # chronological
        lines.append(
            '{ts} style={style} delever={delever} score={score} spill={spill} '
            'twii={twii} wd_eq={eq} chg={chg} fsm={fsm} src={src} note={note}'.format(
                ts=it.get('ts'),
                style=it.get('style'),
                delever=it.get('delever'),
                score=it.get('score'),
                spill=it.get('spillover'),
                twii=it.get('twii'),
                eq=it.get('wd_equity'),
                chg=it.get('wd_equity_chg'),
                fsm=it.get('wd_fsm'),
                src=it.get('source'),
                note=(it.get('note') or '')[:80],
            )
        )
    return '\n'.join(lines)
