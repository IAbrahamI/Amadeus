"""The privacy filter for everything that leaves the PC (work runs in the cloud).

scrub(text, keep=()) -> (clean_text, findings, hold)
  1. hold=True when a canary marker or a deny-list term is in the text: it is never sent.
  2. Fixed patterns are replaced by labels: [PATH] [EMAIL] [KEY] [TOKEN] [IBAN] [URL] [IP] [PHONE].
  3. Presidio (local, in Docker) replaces names of people, places and groups: [PERSON] [LOCATION] [NRP]
     (and [ORGANIZATION] unless kept). English or German, by the text.
  4. If Presidio can't be reached, hold=True: nothing leaves unchecked.
Labels are fixed (anonymisation, not pseudonymisation): nothing is mapped back.

Secrets (~/.local/share/amadeus/secrets, created by install.sh): canaries.json (markers that must never leave)
and denylist.txt (one term per line)."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

from . import macfilter, system
from .config import CFG

PATTERNS = [
    # paths inside your notes, also with spaces in them (the general path rule below stops at a space)
    ("PATH", re.compile(r"(?:/home/[^/\s]+|~)/" + re.escape(os.path.relpath(CFG["notes_root"], os.path.expanduser("~")))
                        + r"(?:/[^\n\"'`]*?\.\w{1,5}\b|/[^\n\"'`]*)?")),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("KEY", re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp]|AKIA|AIza)[A-Za-z0-9_\-]{12,}\b")),
    ("TOKEN", re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")),
    ("URL", re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)[^\s)\]\"']*")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PATH", re.compile(r"(?:/home/[^\s\"'`)]+|~/[^\s\"'`)]+|/etc/[^\s\"'`)]+|/root/[^\s\"'`)]+)")),
    # a number at the end of a sentence ("… call 0176 1234567.") is still a phone number: only a dot followed by a
    # digit (a decimal like 0176.5) stops the match
    ("PHONE", re.compile(r"(?<![\w.\-])(?:\+\d{1,3}[\s\-]?|0)\(?\d{2,4}\)?(?:[\s\-]?\d{2,4}){2,4}(?![\w\-]|\.\d)")),
]

ANALYZER = CFG["presidio_analyzer"]
ANONYMIZER = CFG["presidio_anonymizer"]
NER_TYPES = {"PERSON", "LOCATION", "ORGANIZATION", "NRP"}
ALLOW = {"amadeus", "claude", "anthropic", "hindsight", "ollama", "qwen", "presidio", "github", "linux",
         "docker", "nas"}
DE_WORDS = {"und", "der", "die", "das", "nicht", "mit", "ist", "ein", "eine", "ich", "wir", "am", "im", "zu", "von", "für",
            "auf", "wegen", "bitte", "noch", "auch", "mein", "meine"}
STOP = {"montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag", "januar", "februar", "märz",
        "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember", "monday", "tuesday",
        "wednesday", "thursday", "friday", "saturday", "sunday", "tel", "termin", "dr", "herr", "frau"}
LAST_USED = os.path.join(os.path.dirname(CFG["secrets_dir"]), "presidio-last-used")  # Amadeus stops Presidio when idle


def _terms():
    terms = []
    try:
        with open(os.path.join(CFG["secrets_dir"], "canaries.json")) as f:
            terms += list(json.load(f).values())
    except Exception:
        terms.append("CANARY-")
    try:
        with open(os.path.join(CFG["secrets_dir"], "denylist.txt")) as f:
            terms += [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    except OSError:
        pass
    return terms


def _post(url, body):
    if system.MAC:  # no containers there: the sealed program
        return macfilter.call("analyze" if url == ANALYZER else "anonymize", body)
    r = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=30))


def _lang(text):
    words = re.findall(r"[a-zäöüß]+", text.lower())
    return "de" if sum(w in DE_WORDS for w in words) >= 2 else "en"


def _ner(text, keep=()):
    """Presidio's names, places and groups. Raises if Presidio is unreachable.
    keep: entity types to leave in place (work runs keep ORGANIZATION so brand and product names still make sense)."""
    hits = []
    tokens = [(m.start(), m.end()) for m in re.finditer(r"\[[A-Z_]+\]", text)]
    for r in _post(ANALYZER, {"text": text, "language": _lang(text), "entities": sorted(NER_TYPES - set(keep)),
                              "score_threshold": 0.5}):
        word = text[r["start"]:r["end"]].strip(" .,")
        if word.lower() in ALLOW or word.lower() in STOP or len(word) < 2:
            continue
        if any(r["start"] < e and r["end"] > s0 for s0, e in tokens):
            continue
        hits.append({"start": r["start"], "end": r["end"], "entity_type": r["entity_type"], "score": r["score"]})
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    merged = []
    for h in hits:
        if merged and h["start"] < merged[-1]["end"]:
            continue
        merged.append(h)
    return merged


def ensure_presidio():
    """Presidio runs on demand: start the containers if they are stopped (Amadeus stops them when idle).
    Either container sometimes hangs on a cold start (gunicorn without a worker): restart that one."""
    if system.MAC:
        return macfilter.start()
    os.makedirs(os.path.dirname(LAST_USED), exist_ok=True)
    Path(LAST_USED).touch()
    services = {"presidio-analyzer": ANALYZER.rsplit("/", 1)[0] + "/health",
                "presidio-anonymizer": ANONYMIZER.rsplit("/", 1)[0] + "/health"}

    def up(url):
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            return False
    if all(up(u) for u in services.values()):
        return
    subprocess.run(["docker", "start", *services], capture_output=True, timeout=60)
    for _ in range(2):
        for _ in range(25):
            if all(up(u) for u in services.values()):
                return
            time.sleep(2)
        hung = [name for name, url in services.items() if not up(url)]
        subprocess.run(["docker", "restart", *hung], capture_output=True, timeout=90)


def filter_available():
    """Without the filter there's nothing to wait for, so say so at once."""
    return macfilter.ready() if system.MAC else bool(shutil.which("docker"))


def scrub(text, keep=()):
    available = filter_available()
    try:
        if available:
            ensure_presidio()
    except Exception:
        pass  # the check below still fails closed if Presidio is unreachable
    findings, hold = [], False
    low = text.lower()
    for t in _terms():
        if t and t.lower() in low:
            hold = True
            findings.append("held-term")
    for label, rx in PATTERNS:
        text, n = rx.subn(f"[{label}]", text)
        if n:
            findings.append(f"{label}x{n}")
    if not available:
        return text, findings + ["presidio-unavailable"], True  # fail closed: hold, never send unchecked
    try:
        hits = _ner(text, keep)
    except Exception:
        return text, findings + ["presidio-unavailable"], True  # fail closed: hold, never send unchecked
    if hits:
        ops = {t: {"type": "replace", "new_value": f"[{t}]"} for t in NER_TYPES}
        text = _post(ANONYMIZER, {"text": text, "analyzer_results": hits, "anonymizers": ops})["text"]
        counts = {}
        for h in hits:
            counts[h["entity_type"]] = counts.get(h["entity_type"], 0) + 1
        findings += [f"{k}x{v}" for k, v in counts.items()]
    return text, findings, hold
