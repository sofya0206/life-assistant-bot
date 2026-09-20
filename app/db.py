"""SQLite-хранилище. Одна таблица журнала (entries) на все виды записей —
сон, еда, тренировки, настроение и т.д. — плюс цели, прогресс по целям,
отложенные действия (ждут подтверждения кнопкой) и короткая память диалога.

Все временные метки хранятся как ISO-строки в таймзоне из настроек, поэтому
их можно сравнивать как строки прямо в SQL.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any

from .config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    raw TEXT,
    source TEXT NOT NULL DEFAULT 'tg',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts);
CREATE INDEX IF NOT EXISTS idx_entries_kind_ts ON entries(kind, ts);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    smart TEXT NOT NULL,
    deadline TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    ts TEXT NOT NULL,
    note TEXT,
    value REAL
);

CREATE TABLE IF NOT EXISTS pending (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_local() -> datetime:
    return datetime.now(settings.tz)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=settings.tz)
    return dt.astimezone(settings.tz).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=settings.tz)
    return dt.astimezone(settings.tz)


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            conn = sqlite3.connect(settings.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
            _conn = conn
        return _conn


def _run(sql: str, params: tuple = (), *, fetch: str | None = None) -> Any:
    conn = connect()
    with _lock:
        cur = conn.execute(sql, params)
        if fetch == "one":
            row = cur.fetchone()
            conn.commit()
            return row
        if fetch == "all":
            rows = cur.fetchall()
            conn.commit()
            return rows
        conn.commit()
        return cur.lastrowid


def _entry_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "kind": row["kind"],
        "data": json.loads(row["data"]),
        "raw": row["raw"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


# ── entries ──────────────────────────────────────────────────────────────


def add_entry(kind: str, data: dict, *, ts: str | datetime | None = None,
              raw: str | None = None, source: str = "tg") -> int:
    if isinstance(ts, datetime):
        ts_iso = to_iso(ts)
    else:
        parsed = parse_iso(ts) if ts else None
        ts_iso = to_iso(parsed) if parsed else to_iso(now_local())
    return _run(
        "INSERT INTO entries(ts, kind, data, raw, source, created_at) VALUES (?,?,?,?,?,?)",
        (ts_iso, kind, json.dumps(data, ensure_ascii=False), raw, source, to_iso(now_local())),
    )


def delete_entry(entry_id: int) -> None:
    _run("DELETE FROM entries WHERE id = ?", (entry_id,))


def last_entry() -> dict | None:
    row = _run("SELECT * FROM entries ORDER BY id DESC LIMIT 1", fetch="one")
    return _entry_row(row) if row else None


def entries_since(since: datetime, kind: str | None = None) -> list[dict]:
    if kind:
        rows = _run("SELECT * FROM entries WHERE ts >= ? AND kind = ? ORDER BY ts",
                    (to_iso(since), kind), fetch="all")
    else:
        rows = _run("SELECT * FROM entries WHERE ts >= ? ORDER BY ts", (to_iso(since),), fetch="all")
    return [_entry_row(r) for r in rows]


def entries_between(start: datetime, end: datetime, kind: str | None = None) -> list[dict]:
    if kind:
        rows = _run("SELECT * FROM entries WHERE ts >= ? AND ts < ? AND kind = ? ORDER BY ts",
                    (to_iso(start), to_iso(end), kind), fetch="all")
    else:
        rows = _run("SELECT * FROM entries WHERE ts >= ? AND ts < ? ORDER BY ts",
                    (to_iso(start), to_iso(end)), fetch="all")
    return [_entry_row(r) for r in rows]


# ── goals ────────────────────────────────────────────────────────────────


def add_goal(title: str, smart: dict, deadline: str | None) -> int:
    return _run(
        "INSERT INTO goals(title, smart, deadline, status, created_at) VALUES (?,?,?,?,?)",
        (title, json.dumps(smart, ensure_ascii=False), deadline, "active", to_iso(now_local())),
    )


def list_goals(status: str | None = "active") -> list[dict]:
    if status:
        rows = _run("SELECT * FROM goals WHERE status = ? ORDER BY id", (status,), fetch="all")
    else:
        rows = _run("SELECT * FROM goals ORDER BY id", fetch="all")
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "smart": json.loads(r["smart"]),
            "deadline": r["deadline"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def set_goal_status(goal_id: int, status: str) -> None:
    _run("UPDATE goals SET status = ? WHERE id = ?", (status, goal_id))


def add_goal_progress(goal_id: int, note: str | None, value: float | None = None) -> int:
    return _run(
        "INSERT INTO goal_progress(goal_id, ts, note, value) VALUES (?,?,?,?)",
        (goal_id, to_iso(now_local()), note, value),
    )


def goal_progress_since(since: datetime) -> list[dict]:
    rows = _run("SELECT * FROM goal_progress WHERE ts >= ? ORDER BY ts", (to_iso(since),), fetch="all")
    return [dict(r) for r in rows]


# ── pending actions (ждут кнопки «Применить») ────────────────────────────


def save_pending(chat_id: int, payload: dict) -> str:
    pending_id = uuid.uuid4().hex[:10]
    _run(
        "INSERT INTO pending(id, chat_id, payload, created_at) VALUES (?,?,?,?)",
        (pending_id, chat_id, json.dumps(payload, ensure_ascii=False), to_iso(now_local())),
    )
    return pending_id


def pop_pending(pending_id: str) -> dict | None:
    row = _run("SELECT payload FROM pending WHERE id = ?", (pending_id,), fetch="one")
    if not row:
        return None
    _run("DELETE FROM pending WHERE id = ?", (pending_id,))
    return json.loads(row["payload"])


# ── conversation memory ──────────────────────────────────────────────────


def add_message(chat_id: int, role: str, content: str) -> None:
    _run(
        "INSERT INTO messages(chat_id, role, content, created_at) VALUES (?,?,?,?)",
        (chat_id, role, content[:4000], to_iso(now_local())),
    )


def recent_messages(chat_id: int, limit: int = 8) -> list[dict]:
    rows = _run(
        "SELECT role, content, created_at FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit), fetch="all",
    )
    return [dict(r) for r in reversed(rows)]


# ── key/value ────────────────────────────────────────────────────────────


def get_setting(key: str, default: str | None = None) -> str | None:
    row = _run("SELECT value FROM settings WHERE key = ?", (key,), fetch="one")
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    _run("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
         (key, value))
