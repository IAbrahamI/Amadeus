"""SQLite storage: conversations, messages, pending approvals, reminders, connector and skill settings."""
import atexit
import json
import os
import sqlite3
import threading
import time
import uuid

from .config import CFG

_PATH = os.path.join(CFG["data_dir"], "amadeus.db")
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, model TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, role TEXT,
  content TEXT, meta TEXT, created REAL);
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, conversation_id TEXT, tool TEXT, args TEXT,
  summary TEXT, status TEXT, result TEXT, created REAL, decided REAL);
CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY, text TEXT, schedule TEXT, next_run REAL,
  active INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def conn():
    c = sqlite3.connect(_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


_C = conn()
atexit.register(_C.close)
with _LOCK:
    _C.executescript(SCHEMA)
    for col in ("feedback TEXT", "revised INTEGER"):  # Adjust on an approval (added later; older databases get the columns here)
        try:
            _C.execute("ALTER TABLE approvals ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    _C.commit()
os.chmod(_PATH, 0o600)


def q(sql, args=(), one=False):
    with _LOCK:
        cur = _C.execute(sql, args)
        _C.commit()
        rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def new_id():
    return uuid.uuid4().hex[:12]


def now():
    return time.time()


def get_setting(key, default=None):
    r = q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    q("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, json.dumps(value)))


def add_message(cid, role, content, meta=None):
    q("INSERT INTO messages(conversation_id,role,content,meta,created) VALUES(?,?,?,?,?)",
      (cid, role, content, json.dumps(meta or {}), now()))
    q("UPDATE conversations SET updated=? WHERE id=?", (now(), cid))


def messages(cid):
    rows = q("SELECT id,role,content,meta,created FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    for r in rows:
        r["meta"] = json.loads(r["meta"] or "{}")
    return rows
