"""Reading-aloud voices, all local, from two engines:
- Piper: one small model per voice (about 60 MB each), many languages.
- Kokoro: one model (about 340 MB) with many natural voices, e.g. "George", the British voice OpenJarvis uses.
Settings → Voice lists a few good ones to download, and "+ Add a voice" adds any other Piper voice by name or your own
voice files. Everything is downloaded once into ~/.local/share/amadeus/voice/models/ and then works offline."""
import glob
import json
import os
import random
import re
import time
import urllib.request
import subprocess
import threading

from . import db
from .config import CFG

VOICE_DIR = os.path.expanduser("~/.local/share/amadeus/voice")
PIPER_DIR = os.path.join(VOICE_DIR, "models", "piper")
KOKORO_DIR = os.path.join(VOICE_DIR, "models", "kokoro")
KOKORO_FILES = {"kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
                "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"}
PYTHON = os.path.join(VOICE_DIR, "venv-lite", "bin", "python")

CATALOG = [
    ("en_US-lessac-medium", "Lessac", "English (US), clear and neutral"),
    ("en_GB-alan-medium", "Alan", "English (UK), calm male voice"),
    ("en_US-ryan-high", "Ryan", "English (US), male"),
    ("en_GB-jenny_dioco-medium", "Jenny", "English (UK), female"),
    ("en_GB-alba-medium", "Alba", "English (Scottish), female"),
    ("de_DE-thorsten-medium", "Thorsten", "German, male"),
    ("es_ES-davefx-medium", "Davefx", "Spanish, male"),
    ("kokoro:bm_george", "George", "English (UK), male, natural (Kokoro)"),
    ("kokoro:bm_lewis", "Lewis", "English (UK), male, natural (Kokoro)"),
    ("kokoro:bf_emma", "Emma", "English (UK), female, natural (Kokoro)"),
    ("kokoro:bf_isabella", "Isabella", "English (UK), female, natural (Kokoro)"),
    ("kokoro:af_heart", "Heart", "English (US), female, natural (Kokoro)"),
    ("kokoro:am_michael", "Michael", "English (US), male, natural (Kokoro)"),
]
_busy = set()


def _kokoro_ready():
    return all(os.path.isfile(os.path.join(KOKORO_DIR, f)) for f in KOKORO_FILES)


def installed():
    piper = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(PIPER_DIR, "*.onnx")))
    kokoro = [c[0] for c in CATALOG if c[0].startswith("kokoro:")] if _kokoro_ready() else []
    return piper + kokoro


def selected():
    """The voice id to read with: your choice, else the config's, else the first installed one."""
    have = installed()
    for v in (db.get_setting("tts_voice", ""), os.path.basename(CFG.get("tts_voice", "")).removesuffix(".onnx")):
        if v in have:
            return v
    return have[0] if have else ""


def path(voice_id=None):
    """What the voice service needs: a Piper .onnx file, or "kokoro:<voice>"."""
    v = voice_id or selected()
    return v if v.startswith("kokoro:") else (os.path.join(PIPER_DIR, v + ".onnx") if v else "")


# Short things she says, made once in the voice you picked, so they play right away: a greeting when you only say her
# name, a word when you answer a call on the mini core.
LINES = {"greet": ["Yes?", "How can I help you?", "Hello?", "Hi?"], "okay": ["Okay."], "done": ["Done."]}
LINES_DIR = os.path.join(VOICE_DIR, "lines")


def _line_file(text, voice_id):
    return os.path.join(LINES_DIR, re.sub(r"\W+", "_", voice_id), re.sub(r"\W+", "_", text).strip("_").lower() + ".wav")


def _make_line(text, voice_id):
    """The line's audio, from the voice service the first time."""
    f = _line_file(text, voice_id)
    if not os.path.exists(f):
        req = urllib.request.Request("http://127.0.0.1:8896/tts", json.dumps({"text": text, "voice": path(voice_id)}).encode(),
                                     {"authorization": f"Bearer {CFG['token']}", "content-type": "application/json"})
        data = urllib.request.urlopen(req, timeout=120).read()
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f + ".tmp", "wb") as out:
            out.write(data)
        os.replace(f + ".tmp", f)
    return open(f, "rb").read()


def line(kind):
    """One of the lines of a kind (a random one), or None with no voice installed."""
    v = selected()
    return _make_line(random.choice(LINES[kind]), v) if v else None


def prepare_lines():
    """In the background, so the first one plays right away too (the voice service may still be starting)."""
    def run():
        for _ in range(10):
            try:
                v = selected()
                for texts in LINES.values():
                    for text in texts:
                        v and _make_line(text, v)
                return
            except OSError:
                time.sleep(20)
    threading.Thread(target=run, daemon=True).start()


def listing():
    have = set(installed())
    known = {c[0] for c in CATALOG}
    rows = [{"id": i, "name": n, "about": a, "installed": i in have, "downloading": i in _busy} for i, n, a in CATALOG]
    rows += [{"id": i, "name": i, "about": "added by you", "installed": True, "downloading": False} for i in sorted(have - known)]
    rows += [{"id": i, "name": i, "about": "added by you", "installed": False, "downloading": True} for i in sorted(_busy - known - have)]
    return {"voices": rows, "selected": selected(), "piper": os.path.isfile(PYTHON)}


def select(voice_id):
    if voice_id not in installed():
        raise ValueError("That voice isn't downloaded yet.")
    db.set_setting("tts_voice", voice_id)
    prepare_lines()
    return listing()


def download(voice_id):
    """Fetch a voice in the background: one from the list, or any Piper voice by its name (e.g. fr_FR-siwis-medium)."""
    voice_id = str(voice_id).strip()
    if voice_id not in {c[0] for c in CATALOG} and not re.fullmatch(r"[a-z]{2}_[A-Z]{2}-[a-z0-9_]+-(x_low|low|medium|high)", voice_id):
        raise ValueError("Unknown voice. Piper voices are named like en_US-lessac-medium (see the Piper voice list).")
    if not os.path.isfile(PYTHON):
        raise ValueError("The voice service isn't set up (see docs/INSTALL.md, optional: voice).")
    if voice_id in _busy or voice_id in installed():
        return listing()
    _busy.add(voice_id)

    def run():
        try:
            if voice_id.startswith("kokoro:"):
                _get_kokoro()
            else:
                os.makedirs(PIPER_DIR, exist_ok=True)
                subprocess.run([PYTHON, "-m", "piper.download_voices", voice_id, "--data-dir", PIPER_DIR],
                               capture_output=True, timeout=900)
            if not db.get_setting("tts_voice", "") and voice_id in installed():
                db.set_setting("tts_voice", voice_id)
        finally:
            _busy.discard(voice_id)
    threading.Thread(target=run, daemon=True).start()
    return listing()


def _get_kokoro():
    """Kokoro: the engine (a pip package in the voice service's own folder) and its model, once."""
    if subprocess.run([PYTHON, "-c", "import kokoro_onnx"], capture_output=True).returncode != 0:
        subprocess.run([PYTHON, "-m", "pip", "install", "-q", "kokoro-onnx"], capture_output=True, timeout=900)
    os.makedirs(KOKORO_DIR, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        f = os.path.join(KOKORO_DIR, name)
        if not os.path.isfile(f):
            urllib.request.urlretrieve(url, f + ".part")
            os.replace(f + ".part", f)
    subprocess.run(["systemctl", "--user", "restart", "amadeus-voice"], capture_output=True, timeout=60)


def add_file(name, data):
    """"+ Add a voice" with your own files: a Piper voice is two files, <voice>.onnx and <voice>.onnx.json."""
    name = os.path.basename(str(name))
    if not re.fullmatch(r"[\w.-]+\.onnx(\.json)?", name):
        raise ValueError("A Piper voice is two files: <name>.onnx and <name>.onnx.json.")
    if len(data) > 400_000_000:
        raise ValueError("That file is too large for a voice.")
    os.makedirs(PIPER_DIR, exist_ok=True)
    with open(os.path.join(PIPER_DIR, name), "wb") as f:
        f.write(data)
    return listing()
