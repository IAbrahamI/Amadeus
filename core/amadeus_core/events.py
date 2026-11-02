"""Things worth telling you about right away (approvals, reminders, work results, finished jobs).
Each new event makes Amadeus "call" you with a small desktop popup (desktop/popup.py), except in quiet hours:
then the call waits until the morning."""
import datetime
import os
import re
import subprocess
import sys
import threading

from . import db
from .config import CFG, NAME

db.q("""CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, ref TEXT,
        conversation_id TEXT, created REAL, seen INTEGER DEFAULT 0)""")

POPUP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "desktop", "popup.py")
PIDFILE = os.path.join(CFG["data_dir"], "popup.pid")
_lock = threading.Lock()
_children = []


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


def _popup_open():
    """True if the window is open (not a finished "zombie" process, not a reused pid)."""
    try:
        pid = int(open(PIDFILE).read())
        with open(f"/proc/{pid}/stat") as f:
            state = f.read().rsplit(")", 1)[1].split()[0]
        return state not in ("Z", "X") and "popup.py" in open(f"/proc/{pid}/cmdline").read()
    except (OSError, ValueError, IndexError):
        return False


def maybe_ring():
    """Ring if something new arrived since the last call and it is not quiet hours.
    Missed calls are not repeated; they are listed in the next call."""
    with _lock:
        if _popup_open():
            return  # an open popup polls for new events itself
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
        for p in list(_children):  # reap windows that were closed
            if p.poll() is not None:
                _children.remove(p)
        try:
            from .config import desktop_env
            desktop_env()
            p = subprocess.Popen([sys.executable, POPUP], start_new_session=True,
                                 stdout=open(os.path.join(CFG["data_dir"], "popup.log"), "a"), stderr=open(os.path.join(CFG["data_dir"], "popup.log"), "a"))
            _children.append(p)
            with open(PIDFILE, "w") as f:  # right away: the window needs a moment to start, and more events may come in meanwhile
                f.write(str(p.pid))
        except Exception as e:
            print("popup failed:", e, flush=True)
            subprocess.run(["notify-send", "-a", "Amadeus", NAME, "Something needs your attention."], timeout=10)
