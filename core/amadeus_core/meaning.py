"""Finding earlier talk by what it means, not only by its words: "what did we say about my trip to Portugal?" finds
"I'm flying to Lisbon on Friday", in any of the user's languages.

A small embedding model in Ollama (qwen3-embedding:0.6b by default, about 640 MB, multilingual) turns each message of
yours, with the beginning of its answer, into numbers once, in the background, a moment after it's said. Looking back
then compares those numbers on this PC: milliseconds, no model call. Nothing leaves the PC.

Optional: Settings → Memory switches it on or off and sets it up. Without the model (or switched off) looking back uses
the word search in agent._look_back, as before."""
import array
import json
import math
import threading
import time
import urllib.error
import urllib.request

from .config import CFG
from . import db

MODEL = CFG.get("embed_model", "qwen3-embedding:0.6b")
KEEP = "10m"            # it stays loaded this long after use (small, but the card's memory is for the chat model)
DAYS = 30               # how far back messages get their numbers (looking back searches the last 7 days by default)
BATCH = 24
REPLY_CHARS = 600       # how much of the answer goes with your message
QUERY = "Instruct: Given something the user refers back to, retrieve the earlier chat message about it\nQuery: "
MIN_SCORE = 0.33        # below this a match is noise (measured on EN/DE/ES pairs: right ones 0.36-0.70, others under 0.33)
_lock = threading.Lock()
_state = {"at": float("-inf"), "have": False}


def enabled():
    return db.get_setting("chat_meaning", True)


def set_enabled(on):
    db.set_setting("chat_meaning", bool(on))
    return status()


def installed(force=False):
    """The model is in Ollama (asked at most once a minute)."""
    if not force and time.monotonic() - _state["at"] < 60:
        return _state["have"]
    try:
        tags = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/tags", timeout=5)).get("models", [])
        have = any(m["name"].removesuffix(":latest") == MODEL.removesuffix(":latest") for m in tags)
    except (OSError, ValueError):
        have = False
    _state.update(at=time.monotonic(), have=have)
    return have


def ready():
    return enabled() and installed()


def status():
    indexed = db.q("SELECT count(*) AS n FROM message_meaning WHERE model=?", (MODEL,), one=True)["n"]
    return {"enabled": enabled(), "installed": installed(), "model": MODEL, "indexed": indexed,
            "pulling": _pull_state.get("running", False), "error": _pull_state.get("error", "")}


def embed(texts):
    body = {"model": MODEL, "input": texts, "keep_alive": KEEP, "truncate": True}
    req = urllib.request.Request(CFG["ollama_url"] + "/api/embed", json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["embeddings"]


def _pack(vec):
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return array.array("f", (x / norm for x in vec)).tobytes()  # stored normalized: comparing is a dot product


def _unpack(blob):
    a = array.array("f")
    a.frombytes(blob)
    return a


def _units(limit):
    """Your messages of the last DAYS that have no numbers yet, each with the beginning of its answer."""
    since = time.time() - DAYS * 86400
    rows = db.q("SELECT m.id, m.conversation_id, m.content, m.created FROM messages m LEFT JOIN message_meaning v ON v.message_id=m.id "
                "AND v.model=? WHERE m.role='user' AND m.created>? AND v.message_id IS NULL AND m.content<>'' "
                "AND m.conversation_id NOT LIKE 'brief-%' ORDER BY m.id DESC LIMIT ?", (MODEL, since, limit))
    out = []
    for r in rows:
        reply = db.q("SELECT content FROM messages WHERE conversation_id=? AND id>? AND role='assistant' AND content<>'' "
                     "ORDER BY id LIMIT 1", (r["conversation_id"], r["id"]), one=True)
        out.append((r, (r["content"][:800] + ("\n" + reply["content"][:REPLY_CHARS] if reply else ""))))
    return out


def index_pending(limit=200):
    """Give the newest messages without numbers theirs (a background job; quietly does nothing when it can't)."""
    if not ready():
        return 0
    done = 0
    with _lock:
        units = _units(limit)
        for i in range(0, len(units), BATCH):
            part = units[i:i + BATCH]
            try:
                vecs = embed([t for _, t in part])
            except (OSError, ValueError, KeyError) as e:
                print("meaning: not indexed now:", str(e)[:100], flush=True)
                break
            for (r, _), v in zip(part, vecs):
                db.q("INSERT OR REPLACE INTO message_meaning(message_id,conversation_id,created,model,vec) VALUES(?,?,?,?,?)",
                     (r["id"], r["conversation_id"], r["created"], MODEL, _pack(v)))
                done += 1
    return done


def search(query, cid="", days=7, k=4, skip=()):
    """[(score, message_id)] best first: your earlier messages closest in meaning to the query. skip: message ids that
    are in front of the model already. This chat counts a little more than other chats. None: it can't search now."""
    if not ready():
        return None
    index_pending(60)  # (what was said in the last minutes, before the background job got to it)
    try:
        q = _unpack(_pack(embed([QUERY + query[:500]])[0]))
    except (OSError, ValueError, KeyError, IndexError):
        return None
    rows = db.q("SELECT message_id, conversation_id, vec FROM message_meaning WHERE model=? AND created>?", (MODEL, time.time() - days * 86400))
    scored = []
    for r in rows:
        if r["message_id"] in skip:
            continue
        v = _unpack(r["vec"])
        score = sum(a * b for a, b in zip(q, v)) + (0.03 if r["conversation_id"] == cid else 0)
        if score >= MIN_SCORE:
            scored.append((score, r["message_id"]))
    return sorted(scored, reverse=True)[:k]


# ---------- setting it up from Settings → Memory: the model through Ollama (you start it there) ----------
_pull_state = {}


def set_up():
    """Downloads the model through Ollama, in the background; Settings → Memory shows how it goes."""
    if _pull_state.get("running"):
        return status()

    def run():
        _pull_state.update(running=True, error="")
        try:
            req = urllib.request.Request(CFG["ollama_url"] + "/api/pull", json.dumps({"model": MODEL, "stream": False}).encode(),
                                         {"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=3600) as r:
                out = json.load(r)
            if out.get("status") != "success":
                raise RuntimeError(out.get("error") or "Ollama didn't finish it")
            installed(force=True)
            index_pending(2000)
        except (OSError, ValueError, RuntimeError) as e:
            _pull_state["error"] = f"That didn't work: {str(e)[:150]}"
        finally:
            _pull_state["running"] = False
    threading.Thread(target=run, daemon=True).start()
    _pull_state["running"] = True
    return status()
