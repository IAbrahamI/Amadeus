"""The user's profile ("bio") and the memory curator.
After each answered message the local model distills what is worth keeping (rules in the "memory-curator" skill):
lasting facts go to long-term memory (Hindsight), observations about how the user communicates are collected and
regularly merged into the profile. The profile is shown on the Memory page (you can edit it) and goes into every
conversation so Amadeus can adapt. Mail filing rules are learned from the moves you approve (never mail contents)."""
import datetime
import json
import time
import re
import os
import threading

from . import db, llm, tools
from .config import CFG

SKILL_DIRS = [os.path.join(CFG["data_dir"], "skills"), os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")]
SECTIONS = ["About you", "People", "Preferences & routines", "How you communicate", "Mail organization"]
EMPTY = "\n\n".join(f"## {s}\n" for s in SECTIONS)
MERGE_EVERY = 6  # merge collected observations into the profile after this many
_lock = threading.Lock()


def get():
    return db.get_setting("profile", EMPTY)


def put(text):
    db.set_setting("profile", text.strip()[:8000])


def _rules():
    for d in SKILL_DIRS:
        f = os.path.join(d, "memory-curator.md")
        if os.path.isfile(f):
            return open(f).read()
    return "Keep only lasting facts about the user and how they communicate. Never keep email contents."


def curate(user_text, reply, used_mail=False):
    """Runs in the background after a turn. Never raises."""
    try:
        with _lock:
            _curate(user_text, reply, used_mail)
    except Exception as e:
        print("memory curator failed:", e, flush=True)


def _curate(user_text, reply, used_mail):
    note = ("\nThis turn involved reading emails: do NOT keep anything from their contents; at most note which "
            "account/sender matters to the user.") if used_mail else ""
    prompt = [{"role": "system", "content": _rules() + note +
               "\n\nCurrent profile (already known, don't repeat):\n" + get()[:3000] +
               '\n\nReply ONLY with JSON: {"facts": ["..."], "style": ["..."]}. '
               "facts = lasting facts worth long-term memory (often none). style = observations about how the user "
               "communicates in THIS message, with the mood it suggests and how to answer (often none). Empty lists are normal."},
              {"role": "user", "content": f"USER MESSAGE:\n{user_text[:3000]}\n\nAMADEUS REPLIED:\n{reply[:1500]}"}]
    out = json.loads(llm.complete(CFG["default_model"], prompt, as_json=True) or "{}")
    facts = [f.strip() for f in out.get("facts", []) if isinstance(f, str) and 8 < len(f.strip()) < 300][:5]
    style = [f.strip() for f in out.get("style", []) if isinstance(f, str) and 8 < len(f.strip()) < 300][:3]
    for f in facts:
        tools.remember(f)
    pending = db.get_setting("profile_pending", []) + [f"[fact] {f}" for f in facts] + [f"[style] {s}" for s in style]
    db.set_setting("profile_pending", pending[-60:])
    if len(pending) >= MERGE_EVERY:
        merge()


def merge():
    """Fold collected observations into the profile (short, deduplicated, keeps what the user wrote)."""
    pending = db.get_setting("profile_pending", [])
    if not pending:
        return False
    prompt = [{"role": "system", "content":
               "You maintain a short profile of the user, in Markdown with exactly these sections: " + ", ".join(SECTIONS) +
               " (each as a '## ' heading). Merge the new observations into it: keep it concise (bullet points starting with '- ', max ~25 lines in total), merge "
               "duplicates, generalize repeated style observations into patterns (e.g. 'when excited: many exclamation "
               "marks → match the energy, keep it short'), keep everything the user wrote by hand unless contradicted, "
               "never add email contents or secrets. Reply with the full updated profile only."},
              {"role": "user", "content": "PROFILE:\n" + get() + "\n\nNEW OBSERVATIONS:\n" + "\n".join(pending)}]
    new = llm.complete(CFG["default_model"], prompt).strip()
    if new.startswith("```"):
        new = new.strip("`").split("\n", 1)[-1]
    new = "\n".join("## " + l.lstrip("# ").strip() if l.lstrip().startswith("#") else l for l in new.splitlines())
    if "## " in new and len(new) > 40:
        put(new)
        db.set_setting("profile_pending", [])
        db.set_setting("profile_updated", datetime.datetime.now().isoformat(timespec="minutes"))
        return True
    return False


# ---------- how the user asks for things (learned from requests that ended in the right action) ----------
SKIP_TOOLS = {"recall", "remember", "memory_overview"}


def learn_asking(cid):
    """After a turn where something was actually done: remember HOW the user asked and WHAT they meant, generalized
    ('says "blocker for the 7th and 8th" → one all-day event over both days'). Corrections in between (a rejected
    action, a clarification) are the most valuable: the final action is what the first wording meant. Never raises."""
    try:
        with _lock:
            _learn_asking(cid)
    except Exception as e:
        print("learning how you ask failed:", e, flush=True)


def _learn_asking(cid):
    msgs = db.messages(cid)
    start = db.get_setting(f"asking_upto:{cid}", 0)
    turn = msgs[start:]
    db.set_setting(f"asking_upto:{cid}", len(msgs))
    said = [m["content"] for m in turn if m["role"] == "user"][-3:]
    done, rejected = [], 0
    for m in turn:
        if m["role"] == "tool":
            name, text = m["meta"].get("name", ""), m["content"]
            if text.startswith("The user rejected"):
                rejected += 1
            elif name and name not in SKIP_TOOLS and not text.startswith(("Error", "Invalid request", "Unknown tool")):
                done.append(name)
    calls = [f"{c.get('name')}({json.dumps(c.get('arguments') or {}, ensure_ascii=False)[:200]})"
             for m in turn if m["role"] == "assistant" and m["meta"].get("tool_calls") for c in m["meta"]["tool_calls"]
             if c.get("name") in done]
    if not said or not done:
        return
    prompt = [{"role": "system", "content":
               "You learn how this user phrases requests to their assistant, so next time a similar wording is understood "
               "right away. From the user's words and the action that finally fulfilled them, write ONE general pattern: "
               "'say' = the user's FIRST wording, generalized: keep their characteristic words, replace one-off details with "
               "placeholders like <day>, <time>, <name>, <thing>. 'means' = how to understand that wording in general, as a "
               "short rule with the right tool (not this one case). If the first understanding was rejected, 'means' must be "
               "the CORRECT reading. Example: said 'block my afternoon on friday for gym', then corrected 'the whole "
               "afternoon, 13 to 18' -> {\"say\": \"block my afternoon on <day> for <thing>\", \"means\": \"one calendar "
               "event 13:00-18:00 on that day (afternoon = 13-18)\"}. Only reusable patterns; for trivial ones return null. "
               "No email contents, no secrets. Reply ONLY with JSON: {\"say\": \"...\", \"means\": \"...\"} or {\"say\": null}"},
              {"role": "user", "content": "USER SAID:\n" + "\n".join(f"- {s[:400]}" for s in said) +
               (f"\n\n(Before that, {rejected} proposed action(s) were REJECTED: the first understanding was wrong.)" if rejected else "") +
               "\n\nWHAT FINALLY DID IT:\n" + "\n".join(calls or done)}]
    out = json.loads(llm.complete(CFG["default_model"], prompt, as_json=True) or "{}")
    say, means = str(out.get("say") or "").strip(), str(out.get("means") or "").strip()
    if not say or not means or len(say) > 200 or len(means) > 250:
        return
    pats = db.get_setting("ask_patterns", [])
    for p in pats:  # the same wording again: count it, keep the newest meaning
        if p["say"].lower() == say.lower():
            p.update(means=means, n=p.get("n", 1) + 1, last=time.time())
            break
    else:
        pats.append({"say": say, "means": means, "n": 1, "last": time.time(), "corrected": bool(rejected)})
    db.set_setting("ask_patterns", sorted(pats, key=lambda p: (p.get("n", 1), p.get("last", 0)), reverse=True)[:80])


def asking_hints(text, k=12):
    """The learned patterns most relevant to this message (word overlap), for the system prompt."""
    pats = db.get_setting("ask_patterns", [])
    words = set(re.findall(r"\w{3,}", (text or "").lower()))
    scored = sorted(pats, key=lambda p: (len(words & set(re.findall(r"\w{3,}", p["say"].lower()))), p.get("n", 1)), reverse=True)
    return "\n".join(f'- says "{p["say"]}" → {p["means"]}' for p in scored[:k])


# ---------- mail filing rules, learned from approved moves ----------
def learn_filing(senders_to_folders):
    """senders_to_folders: [(sender address, folder path)] from a move/file the user approved."""
    rules = db.get_setting("mail_rules", {})
    for sender, folder in senders_to_folders:
        addr = (sender or "").split("<")[-1].strip(" >").lower()
        if addr and folder:
            rules[addr] = folder.strip("/")
    db.set_setting("mail_rules", dict(list(rules.items())[-300:]))


def filing_rules_text():
    rules = db.get_setting("mail_rules", {})
    return "\n".join(f"- mails from {a} → {f}" for a, f in rules.items())


def has_content():
    return any(l.strip() and not l.lstrip().startswith("#") for l in get().splitlines())
