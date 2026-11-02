#!/usr/bin/env python3
"""Amadeus voice service: everything on the CPU, so the GPU stays free for the language model.
Runs in its own small venv: ~/.local/share/amadeus/voice/venv-lite (no PyTorch).
  POST /stt   body: recorded audio (webm/ogg/wav)   -> {"text", "language"}    Whisper small (faster-whisper, int8)
Local only (127.0.0.1); bearer token = Amadeus Core's token. Replies are text; the only sounds are the voice
clips (served by Amadeus Core), so there is no text-to-speech here anymore."""
import io
import json
import os
import subprocess
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
VOICE = os.path.join(HOME, ".local/share/amadeus/voice")
MODELS = os.path.join(VOICE, "models")
CFG_FILE = os.path.join(HOME, ".config/amadeus-core/config.json")
WORDS_FILE = os.path.join(HOME, ".local/share/amadeus/core/stt-words.json")  # words the assistant added when you asked
os.environ.setdefault("HF_HOME", os.path.join(MODELS, "hf"))  # Whisper small lives in this cache
os.environ.setdefault("HF_HUB_OFFLINE", "1")                   # never download at runtime
TOKEN = open(os.path.join(HOME, ".local/share/amadeus/core/token")).read().strip()
PORT = 8896
LANGS = {"en", "de", "es"}

_lock = threading.Lock()
_m = {}


def _cfg():
    try:
        return json.load(open(CFG_FILE))
    except Exception:
        return {}




def _whisper():
    if "stt" not in _m:
        from faster_whisper import WhisperModel
        _m["stt"] = WhisperModel("Systran/faster-whisper-small", device="cpu", compute_type="int8", cpu_threads=8)
    return _m["stt"]



# Vocabulary hints per language: Whisper leans towards words it has just "heard", so typical commands go here
# ("mark this mail as read", not "male as red"). Extra words of your own: "stt_words" in config.json.
PROMPTS = {
    "en": "Amadeus, mark this mail as read. Move these mails to the folder. Show my unread mails in the inbox. "
          "Reply to the email. Remind me tomorrow. Add it to my calendar. Thunderbird, Claude, Obsidian.",
    "de": "Amadeus, markiere diese Mail als gelesen. Verschieb die Mails in den Ordner. Zeig meine ungelesenen Mails im "
          "Posteingang. Antworte auf die Mail. Erinnere mich morgen. Trag den Termin in den Kalender ein. Rechnung.",
    "es": "Amadeus, marca este correo como leído. Mueve los correos a la carpeta. Muéstrame los correos no leídos. "
          "Responde al correo. Recuérdame mañana. Añádelo a mi calendario.",
}


def _prompt(lang):
    try:
        words = json.load(open(WORDS_FILE))
    except Exception:
        words = []
    extra = " ".join(x for x in [_cfg().get("stt_words", ""), ", ".join(words)] if x)
    return (PROMPTS.get(lang, PROMPTS["en"]) + (" " + extra if extra else ""))[:800]


def stt(audio, ctype=""):
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "quiet", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
                         input=audio, capture_output=True).stdout
    x = np.frombuffer(pcm, dtype=np.float32).copy()
    dur = x.size / 16000
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if x.size < 4000:  # under a quarter second
        print(f"stt: {ctype} {len(audio)} B, {dur:.2f}s: too short", flush=True)
        return {"text": "", "language": "en"}
    if 0 < peak < 0.5:  # quiet microphone: bring the level up (the model works best around -20 dBFS)
        x *= min(0.9 / peak, 0.1 / max(rms, 1e-4), 30.0)
    model = _whisper()
    forced = _cfg().get("stt_language", "")  # e.g. "en"; empty = choose between English, German and Spanish
    if forced:
        lang, lp = forced, 1.0
    else:
        _, _, probs = model.detect_language(x)
        p = {l: pr for l, pr in probs if l in LANGS}
        lang = max(p, key=p.get) if p else "en"
        lp = p.get(lang, 0.0)
    segs, info = model.transcribe(x, language=lang, beam_size=5, vad_filter=True,
                                  vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 600},
                                  initial_prompt=_prompt(lang), condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segs).strip()
    print(f"stt: {ctype} {len(audio)} B, {dur:.1f}s, rms {20 * np.log10(max(rms, 1e-6)):.0f} dBFS, peak {peak:.2f}, "
          f"lang {lang} ({lp:.2f}), {len(text.split())} words", flush=True)
    return {"text": text, "language": lang}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "loaded": sorted(_m)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.headers.get("authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"error": "unauthorized"})
        body = self.rfile.read(int(self.headers.get("content-length", 0) or 0))
        try:
            if self.path == "/stt":
                return self._send(200, stt(body, self.headers.get("content-type", "")))
            self._send(404, {"error": "not found"})
        except Exception as e:
            print("voice error:", repr(e), flush=True)
            self._send(500, {"error": str(e)})


if __name__ == "__main__":
    def warm():  # load everything in the background so the first answer is quick
        try:
            _whisper()
            print("voice ready", flush=True)
        except Exception as e:
            print("warm-up failed:", e, flush=True)
    threading.Thread(target=warm, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
