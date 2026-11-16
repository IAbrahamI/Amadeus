"""A pack: the texts a model is handed, as one JSON file, so they can be tuned, scored and kept per model.

{"model": "qwen3.5:9b",                  which model it was tuned on (texts tuned for one model don't carry over)
 "system": "...{name}...",               the rules (agent.SYSTEM)
 "pick_ask": "...", "fill_ask": "...{name}...{part}...",   the two questions of the closed-list pick
 "small_talk_hint": "...",
 "tools": {"todo_add": "description"},   tool descriptions, by tool name
 "area_words": {"mail": "regex"},        the words that put a message into an area
 "made_from": {"tools.todo_add": 123}}   written by stamp(): what the code's own text was when the pack was made

Every key is optional: what a pack leaves out stays as the code has it. Nothing here changes a model's weights.

The packs that ship are in packs/, one per model, named like the model (qwen3.5-9b.json). A turn answered by that model
uses its pack (use()); every other model gets the code's own texts. A pack is only kept there when it scored better on
the made-up cases in core/coach (see coach/tune.py). A part whose text in the code changed after the pack was written is
left out, so a pack never quietly undoes a later fix."""
import contextlib
import json
import os
import re
import threading
import zlib

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")
TEXTS = {"system": "SYSTEM", "pick_ask": "PICK_ASK", "fill_ask": "FILL_ASK", "small_talk_hint": "SMALL_TALK_HINT"}
NEEDS = {"system": ("{name}",), "fill_ask": ("{name}", "{part}")}  # what the code fills in: a text without it breaks
GROWTH = 1.15  # a pack may not be more than this much longer than the texts in the code: longer is slower on every request

_now = threading.local()  # the pack of the turn this thread is answering
_forced = None            # coaching: this pack for every model, instead of the shipped ones ({} = the code's own texts)
_loaded = {}


def _code():
    from . import agent, tools
    return agent, tools


def _area_re(words):
    return re.compile(r"\b(?:" + words + r")\b", re.I)


def file_for(model):
    """Where the pack of this model is, or None. Setup names its copy of a model after its context size
    (qwen3.5-9b-48k): that copy uses the model's pack."""
    name = re.sub(r"[^\w.-]+", "-", str(model or "").removesuffix(":latest"))
    for n in (name, re.sub(r"-\d+k$", "", name)):
        path = os.path.join(DIR, n + ".json")
        if n and os.path.isfile(path):
            return path
    return None


def _usable(pack, source=""):
    """A pack ready for use: refused as a whole when it would break something, without the parts written from a text
    the code has changed since."""
    bad = problems(pack)
    if bad:
        print(f"texts for the model not used ({source}): " + "; ".join(bad), flush=True)
        return {}
    old = stale(pack, current())
    if old:
        print(f"texts for the model ({source}): left out, the code's own text changed since: " + ", ".join(old), flush=True)
    keep = {k: pack[k] for k in TEXTS if pack.get(k) and k not in old}
    keep["tools"] = {k: v for k, v in (pack.get("tools") or {}).items() if f"tools.{k}" not in old}
    keep["area_re"] = {k: _area_re(v) for k, v in (pack.get("area_words") or {}).items() if f"area_words.{k}" not in old}
    return keep


def for_model(model):
    """The shipped pack of this model, ready for use ({} when it has none)."""
    if model not in _loaded:
        path = file_for(model)
        try:
            _loaded[model] = _usable(load(path), os.path.basename(path)) if path else {}
        except (OSError, ValueError) as e:
            print(f"texts for the model not used ({path}): {e}", flush=True)
            _loaded[model] = {}
    return _loaded[model]


@contextlib.contextmanager
def use(model):
    """While a turn is answered by this model, its texts are the ones handed out below."""
    before = getattr(_now, "pack", None)
    _now.pack = _forced if _forced is not None else for_model(model)
    try:
        yield
    finally:
        _now.pack = before


def force(pack):
    """Coaching: every turn in this process uses this pack, whatever the model ({} = the code's own texts, None = back
    to the shipped ones)."""
    global _forced
    _forced = None if pack is None else _usable(pack, "being tried")


def _pack():
    return getattr(_now, "pack", None) or {}


def text(key, own):
    """One of TEXTS for this turn: the pack's, else the code's own."""
    return _pack().get(key) or own


def schema(tool_schema):
    """A tool as the model is shown it: with the pack's description when it has one."""
    desc = (_pack().get("tools") or {}).get(tool_schema["function"]["name"])
    return {**tool_schema, "function": {**tool_schema["function"], "description": desc}} if desc else tool_schema


def areas(own):
    """The words of each area for this turn, in the code's order."""
    mine = _pack().get("area_re") or {}
    return {k: mine.get(k, rx) for k, rx in own.items()}


def current():
    """The code's own texts, as a pack."""
    agent, tools = _code()
    return {**{k: getattr(agent, attr) for k, attr in TEXTS.items()},
            "tools": {t["name"]: t["schema"]["function"]["description"] for t in tools.TOOLS},
            "area_words": dict(tools.AREA_WORDS)}


def _mark(text):
    return zlib.crc32(str(text).encode())


def _parts(pack):
    """What a pack replaces, as "system", "tools.todo_add", "area_words.mail"."""
    return [k for k in TEXTS if pack.get(k)] + [f"{g}.{k}" for g in ("tools", "area_words") for k in (pack.get(g) or {})]


def _text(texts, part):
    group, _, key = part.partition(".")
    return (texts.get(group) or {}).get(key) if key else texts.get(group)


def stamp(pack, base):
    """Notes what the code's own texts were when this pack was written. A pack replaces whole texts, so when the code's
    text changes later (a fix, a new tool argument), the pack would quietly undo that change: problems() refuses it then."""
    pack["made_from"] = {part: _mark(_text(base, part)) for part in _parts(pack)}
    return pack


def stale(pack, base):
    """The parts whose text in the code changed since the pack was stamped."""
    made = pack.get("made_from") or {}
    return [part for part in _parts(pack) if part in made and made[part] != _mark(_text(base, part))]


def size(pack):
    return sum(len(pack.get(k) or "") for k in TEXTS) + sum(len(v) for v in (pack.get("tools") or {}).values())


def problems(pack, base=None):
    """Why this pack can't be used ([] = it can). base: the texts it is measured against for its length."""
    _, tools = _code()
    out = []
    if not isinstance(pack, dict):
        return ["a pack is a JSON object"]
    for k in pack:
        if k not in (*TEXTS, "tools", "area_words", "model", "notes", "made_from"):
            out.append(f"unknown key {k!r}")
    for k in TEXTS:
        v = pack.get(k)
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip():
            out.append(f"{k} must be text")
            continue
        for need in NEEDS.get(k, ()):
            if need not in v:
                out.append(f"{k} lost its {need}")
        try:
            v.format(name="x", part="") if k in NEEDS else None
        except (KeyError, IndexError, ValueError) as e:
            out.append(f"{k} has a stray curly bracket ({e})")
    for name, desc in (pack.get("tools") or {}).items():
        if name not in tools.BY_NAME:
            out.append(f"no tool is called {name!r}")
        elif not isinstance(desc, str) or len(desc.strip()) < 10:
            out.append(f"the description of {name} is empty")
    for area, words in (pack.get("area_words") or {}).items():
        if area not in tools.AREA_WORDS:
            out.append(f"no area is called {area!r}")
            continue
        try:
            _area_re(words)
        except (re.error, TypeError) as e:
            out.append(f"the words of {area} are not a valid pattern ({e})")
    if base is not None and not out:
        out += [f"the code's own {part} changed since this pack was written: redo that part from the new text" for part in stale(pack, base)]
    if base is not None and not out:
        merged = {**base, **{k: pack[k] for k in TEXTS if pack.get(k)}, "tools": {**base["tools"], **(pack.get("tools") or {})}}
        if size(merged) > size(base) * GROWTH:
            out.append(f"too long: {size(merged):,} characters against {size(base):,} in the code (at most {int((GROWTH - 1) * 100)}% more)")
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(pack, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=1)
        f.write("\n")
