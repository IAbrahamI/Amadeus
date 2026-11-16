"""A pack: the texts a model is handed, as one JSON file, so a version of them can be tried, scored and kept per model.

{"model": "qwen3.5:9b",                  which model it was tuned on (texts tuned for one model don't carry over)
 "system": "...{name}...",               the rules (agent.SYSTEM)
 "pick_ask": "...", "fill_ask": "...{name}...{part}...",   the two questions of the closed-list pick
 "small_talk_hint": "...",
 "tools": {"todo_add": "description"},   tool descriptions, by tool name
 "area_words": {"mail": "regex"}}        the words that put a message into an area

Every key is optional: what a pack leaves out stays as the code has it. Nothing here changes a model's weights."""
import json
import re

from amadeus_core import agent, tools

TEXTS = {"system": "SYSTEM", "pick_ask": "PICK_ASK", "fill_ask": "FILL_ASK", "small_talk_hint": "SMALL_TALK_HINT"}
NEEDS = {"system": ("{name}",), "fill_ask": ("{name}", "{part}")}  # what the code fills in: a text without it breaks
GROWTH = 1.15  # a pack may not be more than this much longer than the texts in the code: longer is slower on every request


def current():
    """The texts as they are now (the code's own, or an applied pack's)."""
    return {**{k: getattr(agent, attr) for k, attr in TEXTS.items()},
            "tools": {t["name"]: t["schema"]["function"]["description"] for t in tools.TOOLS},
            "area_words": dict(tools.AREA_WORDS)}


def size(pack):
    return sum(len(pack.get(k) or "") for k in TEXTS) + sum(len(v) for v in (pack.get("tools") or {}).values())


def problems(pack, base=None):
    """Why this pack can't be used ([] = it can). base: the texts it is measured against for its length."""
    out = []
    if not isinstance(pack, dict):
        return ["a pack is a JSON object"]
    for k in pack:
        if k not in (*TEXTS, "tools", "area_words", "model", "notes"):
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
            re.compile(r"\b(?:" + words + r")\b", re.I)
        except (re.error, TypeError) as e:
            out.append(f"the words of {area} are not a valid pattern ({e})")
    if base is not None and not out:
        merged = {**base, **{k: pack[k] for k in TEXTS if pack.get(k)}, "tools": {**base["tools"], **(pack.get("tools") or {})}}
        if size(merged) > size(base) * GROWTH:
            out.append(f"too long: {size(merged):,} characters against {size(base):,} in the code (at most {int((GROWTH - 1) * 100)}% more)")
    return out


def apply(pack):
    """Puts a pack's texts in place (in this process only). Returns what was there, for apply() to put back."""
    bad = problems(pack)
    if bad:
        raise ValueError("; ".join(bad))
    before = current()
    for k, attr in TEXTS.items():
        if pack.get(k):
            setattr(agent, attr, pack[k])
    for name, desc in (pack.get("tools") or {}).items():
        tools.BY_NAME[name]["schema"]["function"]["description"] = desc
    for area, words in (pack.get("area_words") or {}).items():
        tools.AREA_WORDS[area] = words
        tools.AREA_RE[area] = re.compile(r"\b(?:" + words + r")\b", re.I)
    return before


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(pack, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=1)
        f.write("\n")
