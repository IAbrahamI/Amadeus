"""One chat per day. Everything you say to the assistant on a day (small window, dashboard, phone app) goes into that day's chat,
so the chat list has one entry per day instead of one per small question. The small window opens empty each time (it
only shows what you say there and then); the dashboard shows the whole day.
After the day (the next time Amadeus runs on a later day), the day's chat is summarized: the summary goes into its
long-term memory (Hindsight) and a short recap of the last few days into its instructions (see recaps())."""
import datetime
import re
import threading
import time

from . import db, llm
from .config import CFG, NAME

KEEP_RECAPS = 3
_lock = threading.Lock()


def _key(day):
    return f"day_chat:{day.isoformat()}"


def current(fresh_after=None):
    """Today's chat (created on the first message of the day). fresh_after is accepted for old callers and ignored."""
    today = datetime.date.today()
    with _lock:
        cid = db.get_setting(_key(today), "")
        if cid and db.q("SELECT id FROM conversations WHERE id=?", (cid,), one=True):
            return cid
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)",
             (cid, today.strftime("%a %d %b %Y"), CFG["default_model"], db.now(), db.now()))
        db.set_setting(_key(today), cid)
    threading.Thread(target=check, daemon=True).start()  # a new day: put the earlier days away
    return cid


def new():
    """There are no extra chats any more: "new chat" is today's chat."""
    return current()


def _talk(cid):
    """What you said and what it answered (no tool results, so no mail contents)."""
    return [m for m in db.messages(cid) if m["role"] in ("user", "assistant") and m["content"].strip()]


def check():
    """Background job (and on the first chat of a day): summarize every earlier day chat that isn't summarized yet."""
    today = datetime.date.today().isoformat()
    for row in db.q("SELECT key, value FROM settings WHERE key LIKE 'day_chat:%' ORDER BY key"):
        day = row["key"][9:]
        if day >= today or db.get_setting(f"day_done:{day}", False):
            continue
        db.set_setting(f"day_done:{day}", True)  # first, so two runs never summarize the same day
        cid = db.get_setting(row["key"], "")
        if cid and _talk(cid):
            _summarize(cid, day)


def _summarize(cid, day):
    """A few lines on what the day's chat was about: into its long-term memory and into the recaps for the next days."""
    try:
        lines = [f"{'User' if m['role'] == 'user' else NAME}: {m['content'][:500]}" for m in _talk(cid)][-120:]
        text = llm.complete(CFG["default_model"], [
            {"role": "system", "content": f"Summarize this day of chats between the user and their assistant {NAME} in at most "
             "6 short bullet points: what was asked and done, what was decided, anything still open. No email or message "
             "contents, no codes, no passwords. Plain bullets only."},
            {"role": "user", "content": "\n".join(lines)}])
        text = re.sub(r"\[mood:\s*\w+\]", "", text).strip()[:1500]
    except Exception as e:
        print("day summary failed:", e, flush=True)
        db.set_setting(f"day_done:{day}", False)  # try again next time
        return
    when = datetime.date.fromisoformat(day).strftime("%a %d %b %Y")
    recs = [r for r in db.get_setting("chat_recaps", []) if r.get("cid") != cid]
    db.set_setting("chat_recaps", (recs + [{"cid": cid, "when": when, "text": text}])[-KEEP_RECAPS:])
    try:
        from . import tools
        tools.remember(f"What the user and {NAME} did on {when} (summary of that day's chat):\n{text}")
    except Exception as e:
        print("day summary not saved to memory:", e, flush=True)


def recaps():
    """For its instructions: what your last few days were about."""
    recs = db.get_setting("chat_recaps", [])
    return "\n\n".join(f"{r['when']}:\n{r['text']}" for r in recs)
