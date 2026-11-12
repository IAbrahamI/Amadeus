"""Things worth telling you about right away (approvals, reminders, work results, finished jobs).
Each new event makes Amadeus "call" you through the desktop app (desktop.py), except in quiet hours: then the call
waits until the morning."""
import datetime
import time
import re
import threading

from . import db, desktop, system
from .config import CFG, NAME

db.q("""CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, ref TEXT,
        conversation_id TEXT, created REAL, seen INTEGER DEFAULT 0)""")

_lock = threading.Lock()


def _plain(text):
    return re.sub(r"[*_`>#]", "", text or "").strip()


STOP = {"your", "you", "the", "and", "for", "with", "this", "that", "read", "ready", "today", "now", "is", "my", "a", "to", "of", "at", "on", "in"}
SAME_WINDOW = 15 * 60


def _words(text):
    return {w for w in re.findall(r"[a-zäöüß]{4,}", (text or "").lower()) if w not in STOP}


def same_as_recent(kind, title):
    """The id of a call from the last 15 minutes that says the same thing, if there is one: a reminder "Read my morning brief" next
    to "Your morning brief is ready", or a reminder for an entry the calendar is already announcing."""
    mine = _words(title)
    if kind not in ("reminder", "calendar") or len(mine) < 1:
        return None
    for r in db.q("SELECT id, kind, title FROM events WHERE created>? AND kind IN ('reminder','calendar','job','digest') AND kind<>?",
                  (db.now() - SAME_WINDOW, kind)):
        theirs = _words(r["title"])
        if len(mine & theirs) >= min(2, len(mine)):
            return r["id"]
    return None


def add(kind, title, body="", ref="", cid=""):
    same = same_as_recent(kind, title)
    if same:  # one thing, one call
        print(f"{kind} joined the call that already says it", flush=True)
        return same
    eid = db.new_id()
    on_screen = kind in WORK_KINDS and _viewed(title)  # a run's result while you're looking at that project
    db.q("INSERT INTO events(id,kind,title,body,ref,conversation_id,created,seen) VALUES(?,?,?,?,?,?,?,?)",
         (eid, kind, _plain(title)[:200], _plain(body)[:1200], ref, cid, db.now(), int(on_screen)))
    if not on_screen:
        maybe_ring()
    return eid


WORK_KINDS = ("work", "job_failed")
VIEWING = {}  # project name (casefolded) -> when its page or workspace on the dashboard last said it's open
VIEW_SECONDS = 20


DASHBOARD = {"at": 0.0}  # when the dashboard last said it's on screen (every 10 s while it is)


def _viewed(title):
    """You're looking at it: that project's page, or the dashboard at all (a run's result lands in its chat or its
    project's timeline there, so you see it come in; you were just talking about it)."""
    name = str(title).split(":", 1)[0].strip().casefold()
    now = time.time()
    return now - VIEWING.get(name, 0) < VIEW_SECONDS or now - DASHBOARD["at"] < VIEW_SECONDS + 5


def dashboard_here():
    DASHBOARD["at"] = time.time()


def seen_project(name):
    """A project's page is open on the dashboard: what its runs reported is in its timeline there, so those events are
    seen, and new ones arrive seen while it stays open (otherwise the mini core called you about them as soon as you
    closed the dashboard)."""
    VIEWING[str(name).strip().casefold()] = time.time()
    rows = [r for r in db.q("SELECT id, title FROM events WHERE seen=0 AND kind IN ('work','job_failed')")
            if r["title"].casefold().startswith(str(name).casefold() + ":")]
    for r in rows:
        db.q("UPDATE events SET seen=1 WHERE id=?", (r["id"],))
    return len(rows)


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
