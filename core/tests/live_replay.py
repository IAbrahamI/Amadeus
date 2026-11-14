#!/usr/bin/env python3
"""The failures seen in real chats, replayed against the real local model, in English, German and Spanish. Each change to
what the model is handed (which tools, how much chat) is measured here: is it right, and what did it cost?

Not part of the unit tests: it needs Ollama and takes a few minutes. Made-up data only, in a throw-away home folder, so
nothing of yours is read or changed and no approval or reminder reaches you.
Run from core/:  python3 tests/live_replay.py [model] [rounds] [only-cases-containing]

Scored per case: right (the check below), a claim with no action behind it, the model calls it took (rounds), and what
it read: the size of everything sent (chars) and the tokens Ollama really had to read (the rest came from its cache)."""
import json
import os
import re
import sys
import tempfile
import time

HOME = tempfile.mkdtemp(prefix="amadeus-replay-")
REAL = os.path.expanduser("~/.config/amadeus-core/config.json")
real = json.load(open(REAL)) if os.path.exists(REAL) else {}
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amadeus_core import paths  # noqa: E402

os.makedirs(paths.CONFIG, exist_ok=True)
MODEL = sys.argv[1] if len(sys.argv) > 1 else real.get("default_model", "qwen3.5-9b-48k")
with open(paths.CONFIG_FILE, "w") as f:
    json.dump({"default_model": MODEL, "hindsight_url": "http://127.0.0.1:9", "searxng_url": "http://127.0.0.1:9",
               "folder": os.path.join(HOME, "Amadeus")}, f)
from amadeus_core import agent, db, grounding, llm, mail, tools  # noqa: E402

mail.call = lambda *a, **k: (_ for _ in ()).throw(OSError("no mail in this test"))
agent.events.maybe_ring = lambda: None
agent.events.add = lambda *a, **k: None
agent.later = lambda *a, **k: None
tools.missing = lambda connector: "" if connector != "web" else "not in this test"  # every tool but the web (no network)
tools.todo_add(["Pay the electricity bill", "Buy a birthday present for Mia"])

COST = {"calls": 0, "chars": 0, "read": 0}
_stream, _timing = llm.chat_stream, llm._timing


def counted(model, messages, tools_=None):
    COST["calls"] += 1
    COST["chars"] += len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tools_ or [], ensure_ascii=False))
    yield from _stream(model, messages, tools_)


def timing(ev):
    COST["read"] += ev.get("prompt_eval_count", 0)


llm.chat_stream, llm._timing = counted, timing

BRIEF_WRONG = [  # a day chat in which it called the brief a reminder, then claimed it added the weather
    ("user", "Can you add the weather in my town to the daily announcement you give me?"),
    ("assistant", "I'll create a daily reminder at 18:00 to check the weather. Should I?"),
    ("user", "No, not a reminder."),
    ("assistant", "I've added \"Check the weather\" to your daily morning brief reminder at 08:00."),
]
PENDING = [("user", "Put the weather in Lisbon into my morning brief."), ("assistant", ""),
           ("approval", "Change your **morning brief**:\n- add: the weather this evening in Lisbon")]


WAITING = re.compile(r"\b(?:waiting|wait for|your ok|approv\w*|wartet|freigabe|bestätig\w*|zustimm\w*|aprobaci[oó]n|espera)\b", re.I)


def say_has_facts(said):
    return bool(said) and not re.match(r"\s*(i['’]ll|i will|let me|here['’]?s|ich werde|voy a)\b", said, re.I) and \
        any(w in said.lower() for w in ("electricity", "bill", "mia", "present", "strom", "rechnung", "factura", "regalo"))


def no_claim(text):
    return not grounding.unbacked(text)


def known_args(calls):
    for name, args in calls:
        t = tools.BY_NAME.get(name.removeprefix("approved:"))
        props = set((t or {}).get("schema", {}).get("function", {}).get("parameters", {}).get("properties", {}))
        if t and set(args) - props:
            return False
    return True


def has(calls, tool, *words):
    return any(n in (tool, "approved:" + tool) and all(w in json.dumps(a, ensure_ascii=False).lower() for w in words) for n, a in calls)


def used(calls, tool):
    """Called it (or, for "approved:x", put it on a card for the user's OK)."""
    return any(n == tool for n, _ in calls) if tool.startswith("approved:") else any(n in (tool, "approved:" + tool) for n, _ in calls)


# (name, earlier chat, the new message, spoken?, check(calls, shown text, spoken line))
CASES = [
    # 1. it follows its own earlier wrong answers
    ("1 brief, after wrong answers (en)", BRIEF_WRONG, "No! I mean the morning brief you write for me every day. Put the weather in Winterthur in it.", False,
     lambda c, t, s: has(c, "brief_change", "winterthur") and not used(c, "calendar_list") and not used(c, "create_reminder")),
    ("1 brief, after wrong answers (de)", BRIEF_WRONG, "Nein, ich meine den Morgenbericht, den du mir jeden Tag schreibst. Nimm das Wetter in Zürich dort auf.", False,
     lambda c, t, s: (has(c, "brief_change", "zürich") or has(c, "brief_change", "zurich")) and not used(c, "calendar_list") and not used(c, "create_reminder")),
    ("1 brief, after wrong answers (es)", BRIEF_WRONG, "No, me refiero al resumen de la mañana que me haces cada día. Añade el tiempo en Madrid.", False,
     lambda c, t, s: has(c, "brief_change", "madrid") and not used(c, "calendar_list") and not used(c, "create_reminder")),
    # 2. "done" without a tool
    ("2 todo after a fake done (en)", BRIEF_WRONG, "ok. add call the landlord to my todo", False, lambda c, t, s: has(c, "todo_add", "landlord")),
    ("2 todo (de)", [], "Füge \"Steuererklärung abgeben\" zu meiner Todo-Liste hinzu", False, lambda c, t, s: has(c, "todo_add", "steuer")),
    ("2 reminder (es)", [], "recuérdame mañana a las 9 llamar al médico", False, lambda c, t, s: used(c, "create_reminder")),
    # 3. a card waiting for the OK is not done
    ("3 pending card (en)", PENDING, "Is the Lisbon weather in my brief now?", False,
     lambda c, t, s: (no_claim(t) or WAITING.search(t)) and not re.search(r"\b(?:yes|it is|it's) (?:now )?(?:in|included|added)", t, re.I)),
    ("3 pending card (de)", PENDING, "Ist das Wetter jetzt im Morgenbericht?", False,
     lambda c, t, s: (no_claim(t) or WAITING.search(t)) and not re.search(r"^\W*ja\b", t, re.I | re.M)),
    # 4. a near tool as a stand-in
    ("4 phone theme (en)", [], "Make the phone app purple like the dashboard.", False, lambda c, t, s: not used(c, "approved:app_setting_change")),
    ("4 phone theme (de)", [], "Mach die Handy-App lila wie das Dashboard.", False, lambda c, t, s: not used(c, "approved:app_setting_change")),
    # 5. a tool result that contradicts the chat
    ("5 show brief after a wrong claim (en)", BRIEF_WRONG, "Show me what's in my morning brief.", False,
     lambda c, t, s: used(c, "brief_show") and not re.search(r"weather (?:is|are) (?:included|in it)|includes?[^.\n]{0,40}weather|- [^\n]*weather", t, re.I)),
    # 6. invented arguments
    ("6 block days (en)", [], "From Saturday till Tuesday I'm off, block my calendar as holidays.", False,
     lambda c, t, s: used(c, "calendar_block_days") and known_args(c)),
    ("6 calendar add (es)", [], "Añade al calendario una cena con Ana el viernes a las 20:00", False,
     lambda c, t, s: used(c, "calendar_add") and known_args(c)),
    # 7. no tool for it: say so, offer the card, never a stand-in or a fake done
    ("7 missing ability (en)", [], "Set the wake word sensitivity to high.", False,
     lambda c, t, s: no_claim(t) and not any(n.startswith("approved:") and n != "approved:suggest_improvement" for n, _ in c)),
    ("7 missing ability (de)", [], "Stell die Empfindlichkeit vom Aktivierungswort auf hoch.", False,
     lambda c, t, s: no_claim(t) and not any(n.startswith("approved:") and n != "approved:suggest_improvement" for n, _ in c)),
    # 8. the spoken line carries the facts
    ("8 spoken todo (en)", [], "What's on my todo?", True, lambda c, t, s: used(c, "todo_list") and say_has_facts(s)),
    ("8 spoken todo (de)", [], "Was steht auf meiner Todo-Liste?", True, lambda c, t, s: used(c, "todo_list") and say_has_facts(s)),
    # 9. earlier talk, outside the short window (put there by run() for "LOOKBACK" chats)
    ("9 look back (en)", "LOOKBACK", "What did we say this morning about my flight to Lisbon?", False,
     lambda c, t, s: "07:40" in t or "7:40" in t),
    ("9 look back (de)", "LOOKBACK", "Was hatten wir heute Morgen wegen meinem Flug nach Lissabon besprochen?", False,
     lambda c, t, s: "07:40" in t or "7:40" in t),
    # no tool needed
    ("0 thanks (en)", BRIEF_WRONG, "thanks, that's all", False, lambda c, t, s: not c and "haven't" not in t.lower()),
    ("0 small talk (de)", [], "Wie geht's dir heute?", False, lambda c, t, s: not c),
    ("0 general question (es)", [], "¿Cuál es la capital de Portugal?", False, lambda c, t, s: not c and "lisboa" in t.lower()),
]


def run(history, text, speak):
    cid = db.new_id()
    db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", MODEL, db.now(), db.now()))
    db.set_setting("briefs", {})
    if history == "LOOKBACK":  # this morning: the flight; then a few hours of other talk
        db.add_message(cid, "user", "I'm flying to Lisbon on Friday, departure 07:40 from Zurich.")
        db.add_message(cid, "assistant", "Got it: Friday, 07:40 from Zurich to Lisbon.")
        db.q("UPDATE messages SET created=created-5*3600 WHERE conversation_id=?", (cid,))
        history = [x for i in range(5) for x in (("user", f"what's a good name for a cat, idea {i}?"), ("assistant", "Maybe Luna."))]
    for role, content in history:
        if role == "approval":
            aid = db.new_id()
            db.q("INSERT INTO approvals(id,conversation_id,tool,args,summary,status,created) VALUES(?,?,?,?,?,?,?)",
                 (aid, cid, "brief_change", json.dumps({"which": "morning", "add": ["the weather this evening in Lisbon"]}), content, "pending", db.now()))
            db.add_message(cid, "approval", content, {"approval_id": aid, "tool": "brief_change"})
        else:
            db.add_message(cid, role, content)
    before = {r["id"] for r in db.q("SELECT id FROM approvals WHERE conversation_id=?", (cid,))}
    shown, said = [], []
    agent.run(cid, MODEL, text, lambda k, d: shown.append(d) if k == "token" else said.append(d) if k == "say" else None,
              curate=False, speak=speak)
    seen = {m["id"] for m in db.messages(cid)}  # noqa: F841
    calls = [(c["name"], c.get("arguments") or {}) for m in db.messages(cid) if m["role"] == "assistant"
             for c in (m["meta"].get("tool_calls") or [])]
    calls += [("approved:" + a["tool"], json.loads(a["args"])) for a in db.q("SELECT id, tool, args FROM approvals WHERE conversation_id=?", (cid,))
              if a["id"] not in before]
    return calls, "".join(str(s) for s in shown), (said[-1] if said else "")


def main():
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    only = sys.argv[3].lower() if len(sys.argv) > 3 else ""
    right = lied = total = 0
    start = dict(COST)
    t0 = time.time()
    for name, history, text, speak, ok in CASES:
        if only and only not in name.lower():
            continue
        marks = []
        for _ in range(rounds):
            c0 = dict(COST)
            calls, shown, said = run(history, text, speak)
            good = bool(ok(calls, shown, said))
            fake = not any(n.startswith("approved:") or tools.BY_NAME.get(n, {}).get("approval") for n, _ in calls) and bool(grounding.unbacked(shown))
            right += good
            lied += fake
            total += 1
            cost = f"{COST['calls'] - c0['calls']}x {(COST['chars'] - c0['chars']) // 1000}k chars"
            marks.append(("ok" if good else "FAIL") + (" +FAKE DONE" if fake else "") + f" ({cost})")
            if not good:
                print("     ", [n for n, _ in calls][:6], "|", shown[:140].replace("\n", " "), "| said:", said[:80])
        print(f"{' / '.join(marks):60s} {name}", flush=True)
    calls = COST["calls"] - start["calls"]
    print(f"\n{MODEL}: {right}/{total} right, {lied} fake done. {calls} model calls, "
          f"{(COST['chars'] - start['chars']) // max(calls, 1):,} chars sent per call, {(COST['read'] - start['read']) // max(calls, 1):,} tokens read "
          f"per call (not from cache), {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
