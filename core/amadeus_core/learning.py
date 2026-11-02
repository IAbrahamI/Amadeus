"""The learning loop: the assistant gets better from your feedback, without retraining the model.

1. Signals. Every answer can get 👍 / 👎 (with an optional note). Approving or rejecting a proposed action, and tools
   that fail, count too.
2. Playbook. Once a day the local model reads yesterday's mistakes (👎, rejected actions, failed tools, and what you
   said next) and writes at most a few short lessons ("A weekly event on one day only: calendar_delete with date, never
   the whole series"). Each lesson keeps a helpful / harmful count from the answers it was used in; lessons that do more
   harm than good are dropped. The most relevant lessons go into the instructions for each new message.
3. Test set. Your own past requests that ended in an approved action are the test: would the model, with the new
   lessons, still choose the same tool? New lessons are kept only if that score doesn't get worse.

Everything stays local (the database and the local model). Inspired by the playbook approach (ACE) in OpenJarvis."""
import datetime
import json
import os
import random
import re
import threading
import time

from . import db, llm
from .config import CFG

db.q("""CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, message_id INTEGER, conversation_id TEXT, score INTEGER,
        note TEXT, created REAL)""")

MAX_LESSONS = 40
_lock = threading.Lock()
LAST_USED = {}  # conversation id -> ids of the lessons put into its last prompt


# ---------- the playbook ----------
def lessons():
    return db.get_setting("playbook", [])


def _save(items):
    db.set_setting("playbook", items[:MAX_LESSONS])


def _words(text):
    return set(re.findall(r"\w{3,}", (text or "").lower()))


def prompt_block(cid, user_text, k=6):
    """The lessons most relevant to this message, for the instructions (and remembered, to credit them later)."""
    items = [l for l in lessons() if l.get("harmful", 0) <= l.get("helpful", 0) + 1]
    if not items:
        LAST_USED[cid] = []
        return ""
    w = _words(user_text)
    scored = sorted(items, key=lambda l: (len(w & _words(l["text"] + " " + l.get("when", ""))), l.get("helpful", 0)),
                    reverse=True)
    picked = [l for l in scored[:k] if w & _words(l["text"] + " " + l.get("when", ""))] or scored[:2]
    LAST_USED[cid] = [l["id"] for l in picked]
    return "\n".join(f"- {l['text']}" for l in picked)


def _credit(ids, good):
    if not ids:
        return
    with _lock:
        items = lessons()
        for l in items:
            if l["id"] in ids:
                l["helpful" if good else "harmful"] = l.get("helpful" if good else "harmful", 0) + 1
        _save([l for l in items if l.get("harmful", 0) < l.get("helpful", 0) + 3])  # more harm than good: dropped


# ---------- signals ----------
def feedback(message_id, score, note=""):
    """👍 (score 1) or 👎 (score -1) on one answer, with an optional note on what was wrong."""
    m = db.q("SELECT * FROM messages WHERE id=?", (message_id,), one=True)
    if not m or m["role"] != "assistant":
        raise ValueError("Not an answer")
    score = 1 if int(score) > 0 else -1
    db.q("DELETE FROM feedback WHERE message_id=?", (message_id,))
    db.q("INSERT INTO feedback(id,message_id,conversation_id,score,note,created) VALUES(?,?,?,?,?,?)",
         (db.new_id(), message_id, m["conversation_id"], score, str(note or "")[:500], db.now()))
    _credit(json.loads(m["meta"] or "{}").get("lessons", []), score > 0)
    return {"ok": True}


def decided(cid, approved):
    """An action proposed in this chat was approved or rejected: credit the lessons it was proposed with."""
    for m in reversed(db.messages(cid)):
        if m["role"] == "assistant" and m["meta"].get("tool_calls"):
            _credit(m["meta"].get("lessons", []), approved)
            return


def scores():
    """For the dashboard: the feedback given on answers."""
    return {r["message_id"]: r["score"] for r in db.q("SELECT message_id, score FROM feedback")}


# ---------- the daily reflection ----------
def _episodes(since):
    """What went wrong (and right) since `since`: the request, what was done, the outcome, what the user said next."""
    bad, good = [], []
    for c in db.q("SELECT DISTINCT conversation_id FROM messages WHERE created>?", (since,)):
        msgs = db.messages(c["conversation_id"])
        fb = {r["message_id"]: r for r in db.q("SELECT * FROM feedback WHERE conversation_id=?", (c["conversation_id"],))}
        asked = ""
        for i, m in enumerate(msgs):
            if m["created"] < since:
                if m["role"] == "user":
                    asked = m["content"]
                continue
            if m["role"] == "user":
                asked = m["content"]
                continue
            nxt = next((x["content"] for x in msgs[i + 1:] if x["role"] == "user"), "")
            did = ", ".join(f"{t.get('name')}({json.dumps(t.get('arguments') or {}, ensure_ascii=False)[:160]})"
                            for t in m["meta"].get("tool_calls") or []) if m["role"] == "assistant" else ""
            ep = {"asked": asked[:300], "did": did or (m["content"][:200] if m["role"] == "assistant" else ""),
                  "next": nxt[:200]}
            if m["role"] == "tool" and (m["content"].startswith(("The user rejected", "Error", "Invalid request"))):
                bad.append({**ep, "did": m["meta"].get("name", ""), "outcome": m["content"][:200]})
            elif m["role"] == "assistant" and m["id"] in fb:
                f = fb[m["id"]]
                (good if f["score"] > 0 else bad).append({**ep, "outcome": "👍" if f["score"] > 0 else "👎 " + (f["note"] or "")})
    return bad[-12:], good[-6:]


def _propose(bad, good):
    from . import tools
    prompt = [{"role": "system", "content":
               "You improve a personal assistant from its own mistakes. Below are recent cases where it did something wrong "
               "(the user rejected an action, a tool failed, or the user gave a thumbs down, with what the user said next) "
               "and a few that went well. Write at most 3 SHORT general lessons that would have prevented the mistakes, "
               "as instructions to the assistant (imperative, under 30 words, name the right tool when it matters). "
               "Only lessons that generalize; nothing about one-off details, no personal data, no email contents. "
               "Use only these tool names: " + ", ".join(t["name"] for t in tools.TOOLS) + ". "
               "Reply ONLY with JSON: {\"lessons\": [{\"text\": \"...\", \"when\": \"a few trigger words\"}]}"},
              {"role": "user", "content": "MISTAKES:\n" + "\n".join(json.dumps(b, ensure_ascii=False) for b in bad) +
               "\n\nWENT WELL:\n" + ("\n".join(json.dumps(g, ensure_ascii=False) for g in good) or "-")}]
    out = json.loads(llm.complete(CFG["default_model"], prompt, as_json=True) or "{}")
    return [{"text": str(l.get("text", "")).strip()[:240], "when": str(l.get("when", "")).strip()[:120]}
            for l in out.get("lessons", []) if isinstance(l, dict) and str(l.get("text", "")).strip()][:3]


# ---------- the test set ----------
def test_cases(n=10):
    """Past requests that ended in an approved action: (what you asked, the tool that did it). Only actions that answered
    a message you wrote shortly before (not the evening filing or other proposals made by background jobs)."""
    rows = db.q("SELECT conversation_id, tool, created FROM approvals WHERE status='done' "
                "AND conversation_id NOT IN ('mail','day','reminders','week') ORDER BY created DESC LIMIT 300")
    cases = []
    for r in rows:
        ask = db.q("SELECT content, created FROM messages WHERE conversation_id=? AND role='user' AND created<=? "
                   "ORDER BY id DESC LIMIT 1", (r["conversation_id"], r["created"]), one=True)
        if ask and len(ask["content"]) > 8 and r["created"] - ask["created"] < 180:
            cases.append((ask["content"][:500], r["tool"]))
    random.Random(len(cases)).shuffle(cases)
    return cases[:n] + BASICS  # plus a few basics every assistant must keep getting right


BASICS = [tuple(c) for c in json.load(open(os.path.join(os.path.dirname(__file__), "learning_tests.json")))]


def evaluate(lesson_items, cases):
    """Share of the test requests for which the model, with these lessons, picks the tool that was approved."""
    from . import agent, tools
    if not cases:
        return 1.0
    hits = 0
    for text, want in cases:
        block = "\n".join(f"- {l['text']}" for l in lesson_items)
        sysmsg = agent.eval_system(text, block)
        got = ""
        for kind, data in llm.chat_stream(CFG["default_model"], [sysmsg, {"role": "user", "content": text}], tools.schemas()):
            if kind == "done":
                got = next((c.get("name") for c in data["tool_calls"]), "")
        hits += got == want
    return hits / len(cases)


def reflect(force=False):
    """Daily: turn yesterday's mistakes into lessons, keep them only if the test set doesn't get worse."""
    today = datetime.date.today().isoformat()
    bad, good = _episodes(time.time() - 86400)
    if not bad:
        return {"added": 0, "reason": "no mistakes"}
    new = _propose(bad, good)
    known = {l["text"].lower() for l in lessons()}
    new = [l for l in new if l["text"].lower() not in known]
    if not new:
        return {"added": 0, "reason": "nothing new"}
    cases = test_cases()
    before = evaluate(lessons(), cases)
    after = evaluate(lessons() + new, cases)
    log = {"day": today, "before": before, "after": after, "proposed": [l["text"] for l in new], "kept": after >= before}
    db.set_setting("reflect_log", (db.get_setting("reflect_log", []) + [log])[-30:])
    if after < before:
        return {"added": 0, "reason": f"test got worse ({before:.0%} → {after:.0%})"}
    with _lock:
        items = lessons()
        items += [{"id": db.new_id(), **l, "helpful": 0, "harmful": 0, "created": time.time()} for l in new]
        _save(sorted(items, key=lambda l: l.get("helpful", 0) - l.get("harmful", 0), reverse=True))
    return {"added": len(new), "score": after}


def check():
    """Background job: once a day, after `reflect_hour` (03:00 by default)."""
    if not CFG.get("learning", True) or db.get_setting("reflect_day", "") == datetime.date.today().isoformat() \
            or datetime.datetime.now().hour < CFG.get("reflect_hour", 3):
        return
    db.set_setting("reflect_day", datetime.date.today().isoformat())  # first, so the next round doesn't start it again
    threading.Thread(target=_safe_reflect, daemon=True).start()


def _safe_reflect():
    try:
        print("learning:", reflect(force=True), flush=True)
    except Exception as e:
        print("learning failed:", e, flush=True)
