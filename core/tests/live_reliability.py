#!/usr/bin/env python3
"""Does the assistant really do what it's asked, with the real local model? Not part of the unit tests (it needs Ollama and takes a few
minutes). It runs in a throw-away home folder, so nothing of yours is read or changed, and no approval or reminder reaches you.
Run from core/:  python3 tests/live_reliability.py [model] [rounds]"""
import datetime
import json
import os
import re
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="amadeus-live-")
REAL = os.path.expanduser("~/.config/amadeus-core/config.json")
real = json.load(open(REAL)) if os.path.exists(REAL) else {}
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amadeus_core import paths  # noqa: E402

os.makedirs(paths.CONFIG, exist_ok=True)
MODEL = sys.argv[1] if len(sys.argv) > 1 else real.get("default_model", "qwen3.5-9b-48k")
with open(paths.CONFIG_FILE, "w") as f:
    json.dump({"default_model": MODEL, "hindsight_url": "http://127.0.0.1:9", "folder": os.path.join(HOME, "Amadeus")}, f)
from amadeus_core import agent, db, mailbridge, tools  # noqa: E402


def no_mail(*a, **k):
    raise OSError("no mail in this test")


mailbridge.call = no_mail
agent.events.maybe_ring = lambda: None  # no call and no notification on your desktop from a test
tools.missing = lambda connector: ""  # every tool is offered, like on a fully set-up PC
agent.later = lambda *a, **k: None  # nothing is learned from a test
NOW = datetime.datetime.now()
CLAIM = re.compile(r"\b(i['’]ve|i have|i just|i)\s+(now |already |just )?(added|set|created|saved|scheduled|put|noted|removed)\b|^\W*(done|added|saved)\b|"
                   r"\b(is|has been|was) (set|added|created|saved|scheduled)\b|\bhabe\b.{0,60}(hinzugefügt|erstellt|gesetzt|eingetragen)", re.I | re.M)


def minutes_from_now(when):
    m = re.search(r"(\d{4}-\d{2}-\d{2})[ t](\d{1,2}):(\d{2})", when or "")
    if not m:
        return None
    dt = datetime.datetime.fromisoformat(f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)}")
    return (dt - NOW).total_seconds() / 60


CHAT = [("user", "hey, how's it going?"), ("assistant", "Good, thanks. What can I do for you?"), ("user", "tell me a fun fact about owls"),
        ("assistant", "Owls can turn their heads about 270 degrees."), ("user", "nice. what's the capital of Portugal?"), ("assistant", "Lisbon."),
        ("user", "did you add the cyberwars mail to my todo?"), ("assistant", "Yes, I added \"Write reply mail regarding Cyberwars\" to your todo."),
        ("user", "ok and how do I boil an egg?"), ("assistant", "Put it in boiling water for 7 to 9 minutes, then cool it in cold water.")]
LONG = "(after a long chat) "


def run(text):
    cid = db.new_id()
    db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", MODEL, db.now(), db.now()))
    if text.startswith(LONG):  # a chat that already holds small talk and an answer that claimed something without a tool
        text = text[len(LONG):]
        for role, content in CHAT:
            db.add_message(cid, role, content)
    shown = []
    agent.run(cid, MODEL, text, lambda kind, data: shown.append(data) if kind == "token" else None, curate=False)
    calls = [(json.loads(m["meta"] if isinstance(m["meta"], str) else json.dumps(m["meta"])).get("tool_calls") or []) for m in db.messages(cid) if m["role"] == "assistant"]
    calls = [(c["name"], c.get("arguments") or {}) for cs in calls for c in cs]
    for a in db.q("SELECT tool,args FROM approvals WHERE conversation_id=?", (cid,)):  # what you'd be asked to approve (after any correction)
        calls.append(("approved:" + a["tool"], json.loads(a["args"])))
    return calls, "".join(str(s) for s in shown)


def when_of(calls, lo, hi):
    for name, args in calls:
        if name == "approved:create_reminder":
            m = minutes_from_now(parse(args.get("when", "")))
            if m is not None and lo <= m <= hi:
                return True
    return False


def parse(when):
    try:
        return tools.parse_schedule(when)[0]
    except Exception:
        return when


def has(calls, tool, *words):
    return any(n == "approved:" + tool or n == tool for n, a in calls if all(w in json.dumps(a).lower() for w in words))


tomorrow9 = (NOW.replace(hour=9, minute=0, second=0) + datetime.timedelta(days=1) - NOW).total_seconds() / 60
evening = [(NOW.replace(hour=h, minute=0) - NOW).total_seconds() / 60 for h in (17, 22)]
CASES = [
    ("add buy milk to my todo", lambda c, t: has(c, "todo_add", "milk")),
    ("put call the dentist on my todo list", lambda c, t: has(c, "todo_add", "dentist")),
    ("add eggs and bread to my todo", lambda c, t: has(c, "todo_add", "eggs", "bread")),
    ("Hey add a new Todo with reminder for today evening to write back a mail about the project", lambda c, t: has(c, "todo_add") and when_of(c, *evening)),
    ("remind me in 5 minutes to check the oven", lambda c, t: when_of(c, 4, 6.5)),
    ("set a reminder in 2 hours: call mom", lambda c, t: when_of(c, 118, 122)),
    ("put a reminder in one minute as a test", lambda c, t: when_of(c, 0.2, 2.5)),
    ("remind me tomorrow at 9 to send the application", lambda c, t: when_of(c, tomorrow9 - 1, tomorrow9 + 1)),
    ("remind me every day at 7:30 to take my vitamins", lambda c, t: has(c, "create_reminder", "daily 07:30") or has(c, "create_reminder", "daily 7:30")),
    ("erinnere mich in 10 Minuten an die Wäsche", lambda c, t: when_of(c, 9, 11.5)),
    ("note that the wifi password is on the fridge", lambda c, t: has(c, "notes_add", "fridge")),
    ("remember that my sister is called Lena", lambda c, t: has(c, "remember", "lena")),
    ("what's on my todo?", lambda c, t: has(c, "todo_list")),
    ("which reminders do I have?", lambda c, t: has(c, "list_reminders")),
    ("did you add milk to my todo earlier?", lambda c, t: has(c, "todo_list") or not CLAIM.search(t)),
    (LONG + "add call the bank to my todo", lambda c, t: has(c, "todo_add", "bank")),
    (LONG + "remind me in 3 minutes to stretch", lambda c, t: when_of(c, 2, 4.5)),
    (LONG + "did you really add that cyberwars todo?", lambda c, t: has(c, "todo_list") or not CLAIM.search(t)),
    (LONG + "thanks", lambda c, t: not c and "haven't done" not in t.lower()),
    ("do I have unread mail?", lambda c, t: has(c, "mail_unread") or has(c, "mail_overview")),
    ("create a mail folder called Invoices", lambda c, t: has(c, "mail_create_folder", "invoices") or has(c, "mail_folders") or has(c, "mail_accounts")),
    ("search my mail for the train ticket", lambda c, t: has(c, "mail_search", "ticket")),
    ("hey how are you", lambda c, t: not c and len(t) > 3 and "haven't" not in t.lower()),
    ("what can you do?", lambda c, t: not c and len(t) > 20 and "haven't done" not in t.lower()),
    ("thanks, that's all for now", lambda c, t: not c and "haven't done" not in t.lower()),
]


def main():
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    only = sys.argv[3].lower() if len(sys.argv) > 3 else ""
    passed = lied = total = 0
    for text, ok in CASES:
        if only and only not in text.lower():
            continue
        marks = []
        for _ in range(rounds):
            calls, shown = run(text)
            if only:
                print("   ", [n for n, _ in calls], "|", shown[:160].replace("\n", " "))
            good = bool(ok(calls, shown))
            false_claim = not calls and bool(CLAIM.search(shown))
            passed += good
            lied += false_claim
            total += 1
            marks.append(("ok" if good else "FAIL") + (" +FALSE CLAIM" if false_claim else ""))
            if not good:
                print("   ", [(n, a) for n, a in calls][:4], "|", shown[:110].replace("\n", " "))
        print(f"{' / '.join(marks):28s} {text[:70]}", flush=True)
    print(f"\n{MODEL}: {passed}/{total} right, {lied} said done without doing it")


if __name__ == "__main__":
    main()
