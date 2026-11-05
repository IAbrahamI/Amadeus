"""Things worth telling you about right away (approvals, reminders, work results, finished jobs).
Each new event makes Amadeus "call" you through the desktop app (desktop.py), except in quiet hours: then the call
waits until the morning."""
import datetime
import re
import threading

from . import db, desktop, system
from .config import CFG, NAME

db.q("""CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, ref TEXT,
        conversation_id TEXT, created REAL, seen INTEGER DEFAULT 0)""")

_lock = threading.Lock()


def _plain(text):
    return re.sub(r"[*_`>#]", "", text or "").strip()


def add(kind, title, body="", ref="", cid=""):
    eid = db.new_id()
    db.q("INSERT INTO events(id,kind,title,body,ref,conversation_id,created) VALUES(?,?,?,?,?,?,?)",
         (eid, kind, _plain(title)[:200], _plain(body)[:1200], ref, cid, db.now()))
    maybe_ring()
    return eid


def unseen():
    """Open items for the call window. Approvals already decided elsewhere (or removed) are cleared automatically."""
    out = []
    for r in db.q("SELECT * FROM events WHERE seen=0 ORDER BY created"):
        if r["kind"] == "mail_code" and db.now() - r["created"] > CODE_MINUTES * 60:
            db.q("UPDATE events SET seen=1 WHERE id=?", (r["id"],))  # codes expire; don't leave them on screen
            continue
        if r["kind"] == "approval":
            a = db.q("SELECT status FROM approvals WHERE id=?", (r["ref"],), one=True)
            if not a or a["status"] != "pending":
                db.q("UPDATE events SET seen=1 WHERE id=?", (r["id"],))
                continue
            r["status"] = "pending"
        out.append(r)
    return out


URGENT = ("mail_code",)  # these ring even in quiet hours
CODE_MINUTES = 20


def quiet(now=None):
    start, end = CFG.get("quiet_hours", [23, 7])
    h = (now or datetime.datetime.now()).hour
    return (h >= start or h < end) if start > end else (start <= h < end)


def maybe_ring():
    """Ring if something new arrived since the last call and it is not quiet hours.
    Missed calls are not repeated; they are listed in the next call."""
    with _lock:
        if desktop.window_open():
            return  # an open window polls for new events itself
        from . import phoneapp
        if phoneapp.in_use():
            return  # you're in the phone app right now: it shows this there, the PC stays quiet
        last = db.get_setting("last_ring", 0)
        fresh = db.q("SELECT kind FROM events WHERE seen=0 AND created>?", (last,))
        if not fresh or (quiet() and not any(r["kind"] in URGENT for r in fresh)):
            return
        db.set_setting("last_ring", db.now())
        try:
            from . import push
            push.notify()  # the phone app (if paired): a content-free nudge
        except Exception as e:
            print("push failed:", e, flush=True)
        if desktop.connected():
            desktop.send({"do": "call"})
            return
        try:  # the desktop app isn't running: at least a notification
            from .config import desktop_env
            desktop_env()
            system.notify(NAME, "Something needs your attention.")
        except Exception as e:
            print("notification failed:", e, flush=True)
