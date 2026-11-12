"""Text normalization for speech (NVIDIA NeMo Text Processing): turns numbers, money, units, dates, ordinals and
abbreviations into words before a reply is read aloud ("$4.50" -> "four dollars fifty cents"). Runs in its own Python
environment (~/.local/share/amadeus/voice/venv-tn, set up by install.sh), because NeMo needs pynini, which needs an
older Python than the voice service. Local only (127.0.0.1:8897); bearer token = Amadeus Core's token.
POST /normalize {"text", "lang"} -> {"text"}. Amadeus Core (speech.py) falls back to its own rules when this is off.

A language is loaded only once it's asked for (each costs memory and, the first time, a minute of compiling), and the
ones used before are loaded again at start. While a language is still loading, the text comes back unchanged right
away: speech never waits for a grammar."""
import json
import os
import sys
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amadeus_core import paths  # noqa: E402
TOKEN = Path(paths.DATA, "token").read_text().strip()
CACHE = os.path.join(paths.VOICE, "models", "tn-cache")
PORT = 8897
LANGS = ("en", "de", "es")
USED = os.path.join(CACHE, "used.json")  # the languages asked for before: loaded again at start
_n, _loading, _lock = {}, set(), threading.Lock()


def _used():
    try:
        return [x for x in json.load(open(USED)) if x in LANGS]
    except (OSError, ValueError):
        return []


def _load(lang):
    try:
        from nemo_text_processing.text_normalization.normalize import Normalizer
        n = Normalizer(input_case="cased", lang=lang, cache_dir=CACHE)  # compiled once (cached on disk), then in memory
        with _lock:
            _n[lang] = n
            used = _used()
        if lang not in used:
            os.makedirs(CACHE, exist_ok=True)
            with open(USED + ".tmp", "w") as f:
                json.dump(used + [lang], f)
            os.replace(USED + ".tmp", USED)
        print("normalizer ready:", lang, flush=True)
    except Exception as e:
        print("normalizer for", lang, "failed:", e, flush=True)
    finally:
        with _lock:
            _loading.discard(lang)


def normalizer(lang):
    """The loaded normalizer, or None while it loads (the first request for a language starts loading it)."""
    with _lock:
        if lang in _n:
            return _n[lang]
        if lang not in _loading:
            _loading.add(lang)
            threading.Thread(target=_load, args=(lang,), daemon=True).start()
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.headers.get("authorization") != f"Bearer {TOKEN}" or self.path != "/normalize":
            self.send_response(403); self.end_headers(); return
        b = json.loads(self.rfile.read(int(self.headers.get("content-length", 0) or 0)) or b"{}")
        lang = b.get("lang") if b.get("lang") in LANGS else "en"
        text = str(b.get("text", ""))[:4000]
        n = normalizer(lang)
        try:
            out = n.normalize(text, verbose=False, punct_post_process=True) if n else text
        except Exception as e:  # an odd sentence: say it as it is
            print("normalize failed:", e, flush=True)
            out = text
        data = json.dumps({"text": out}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data)))
        self.end_headers(); self.wfile.write(data)


if __name__ == "__main__":
    for lang in _used() or ["en"]:  # the languages you use, ready before they're needed
        normalizer(lang)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
