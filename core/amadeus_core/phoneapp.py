"""The Android app's view of Amadeus: one small summary for its home screen, your ToDo for its Today screen, and the
live link (server-sent events) that turns its calls into phone notifications. Everything goes through your private
Tailscale connection with the phone's own key (see devices.py); nothing is sent through Google."""
import datetime
import json
import os
import time

from . import agenda, db, events, tools
from .config import CFG


def home():
    """Counts and short lines for the home screen. No mail is read here (mail counts come from the Mail screen)."""
    from . import playbooks
    approvals = db.q("SELECT id, tool, summary, created FROM approvals WHERE status='pending' ORDER BY created DESC")
    today = datetime.date.today()
    agenda_today = [{"title": o["title"], "start": o["occ_start"], "end": o["occ_end"], "all_day": bool(o["all_day"])}
                    for o in agenda.occurrences(today, today + datetime.timedelta(days=1))]
    # "chats" stays empty: messengers aren't read any more (older app versions still expect the key)
    return {"approvals": approvals, "chats": {"new": 0, "apps": []}, "today": agenda_today,
            "voice": playbooks.voice_status(), "events": len(events.unseen()), "quiet_hours": CFG.get("quiet_hours", [23, 7])}


def todo():
    """Open items on your ToDo.md (the same list Amadeus reads)."""
    _, lines = tools._lines("ToDo.md")
    return [l.strip()[6:].strip() for l in lines if l.strip().startswith("- [ ] ") and l.strip()[6:].strip()]


def todo_done(item):
    """You ticked an item off on the phone: it's removed from ToDo.md (your own action, like in any notes app)."""
    return tools.todo_done([item])


# On the phone, only these ring as a call: codes, urgent / important-person mail and chats, reminders, calendar alerts,
# the evening summary. Approvals, questions from the work team and finished jobs are a normal notification.
CALL_KINDS = {"mail_code", "mail", "message", "reminder", "calendar", "digest", "test"}


_active = {"at": 0.0}


def touch():
    """The phone app is open right now (it says so every 30 s while you use it)."""
    _active["at"] = time.time()


def in_use():
    """You're using the phone app: the PC window doesn't ring then (you see everything in the app)."""
    return time.time() - _active["at"] < 75


_pc = {"at": 0.0, "used": False}


def pc_in_use():
    """You're at the PC: your session is unlocked (KDE locks it a few minutes after you leave). Checked every 10 s."""
    if time.time() - _pc["at"] > 10:
        import subprocess
        try:
            sid = subprocess.run(["loginctl", "show-user", str(os.getuid()), "-p", "Display", "--value"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            locked = subprocess.run(["loginctl", "show-session", sid, "-p", "LockedHint", "--value"],
                                    capture_output=True, text=True, timeout=5).stdout.strip()
            _pc["used"] = bool(sid) and locked == "no"
        except Exception:
            _pc["used"] = False
        _pc["at"] = time.time()
    return _pc["used"]


def answered(by):
    """You picked up its call on one device: the other one stops ringing (the phone app and the PC window both check)."""
    db.set_setting("call_answered", {"at": time.time(), "by": by})


def call_state():
    return db.get_setting("call_answered", {"at": 0, "by": ""})


def stream(write, alive=lambda: True):
    """Live link for the phone app: each new event (the things that make it call you) is sent once per connection.
    It is where you are: while you're at the PC (session unlocked) and not in the phone app, the phone stays quiet;
    whatever is still open when you leave (the PC locks) reaches the phone then.
    In quiet hours only urgent ones (codes) go out; the rest follow in the morning, like on the PC.
    "gone" tells the phone an event was handled elsewhere; "answered" that you picked up on the PC (stop ringing).
    The app remembers which events it already showed, so a reconnect doesn't ring twice."""
    sent, last_ping, answered_at = set(), 0.0, call_state().get("at", 0)
    write("hello", {"time": time.time()})
    while alive():
        quiet = events.quiet()
        at_pc = pc_in_use() and not in_use()
        unseen = events.unseen()
        ids = {e["id"] for e in unseen}
        for e in unseen:
            if e["id"] in sent or at_pc or (quiet and e["kind"] not in events.URGENT):
                continue
            sent.add(e["id"])
            write("amadeus", {**{k: e.get(k) for k in ("id", "kind", "title", "body", "ref", "status", "created")},
                              "call": e["kind"] in CALL_KINDS})
        for eid in sent - ids:
            write("gone", {"id": eid})
        sent &= ids
        st = call_state()
        if st.get("at", 0) > answered_at:
            answered_at = st["at"]
            if st.get("by") != "phone":
                write("answered", {"by": st.get("by")})
        if time.time() - last_ping > 25:
            write(None, None)  # keep-alive comment, so Tailscale and the phone keep the connection open
            last_ping = time.time()
        time.sleep(2)


def sse(wfile):
    """A write() for stream(): returns False once the phone is gone."""
    state = {"ok": True}

    def write(kind, data):
        try:
            wfile.write((": ping\n\n" if kind is None else f"event: {kind}\ndata: {json.dumps(data)}\n\n").encode())
            wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            state["ok"] = False
    return write, lambda: state["ok"]
