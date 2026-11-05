"""Text normalization for speech (NVIDIA NeMo Text Processing): turns numbers, money, units, dates, ordinals and
abbreviations into words before a reply is read aloud ("$4.50" -> "four dollars fifty cents"). Runs in its own Python
environment (~/.local/share/amadeus/voice/venv-tn, set up by install.sh), because NeMo needs pynini, which needs an
older Python than the voice service. Local only (127.0.0.1:8897); bearer token = Amadeus Core's token.
POST /normalize {"text", "lang"} -> {"text"}. Amadeus Core (speech.py) falls back to its own rules when this is off."""
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amadeus_core import paths  # noqa: E402
TOKEN = Path(paths.DATA, "token").read_text().strip()
CACHE = os.path.join(paths.VOICE, "models", "tn-cache")
PORT = 8897
LANGS = ("en", "de", "es")
_n, _lock = {}, threading.Lock()


def normalizer(lang):
    with _lock:  # the grammars are compiled once (cached on disk), then kept in memory
        if lang not in _n:
            from nemo_text_processing.text_normalization.normalize import Normalizer
            _n[lang] = Normalizer(input_case="cased", lang=lang, cache_dir=CACHE)
        return _n[lang]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.headers.get("authorization") != f"Bearer {TOKEN}" or self.path != "/normalize":
            self.send_response(403); self.end_headers(); return
        b = json.loads(self.rfile.read(int(self.headers.get("content-length", 0) or 0)) or b"{}")
        lang = b.get("lang") if b.get("lang") in LANGS else "en"
        text = str(b.get("text", ""))[:4000]
        try:
            out = normalizer(lang).normalize(text, verbose=False, punct_post_process=True)
        except Exception as e:  # an odd sentence: say it as it is
            print("normalize failed:", e, flush=True)
            out = text
        data = json.dumps({"text": out}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data)))
        self.end_headers(); self.wfile.write(data)


if __name__ == "__main__":
    # load the grammars right away (the first time they are compiled and cached, which takes a minute per language)
    threading.Thread(target=lambda: [normalizer(lang) for lang in LANGS], daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
