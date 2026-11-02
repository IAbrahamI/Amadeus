"""Reading-aloud voices (Piper, local). A short list of good voices to pick from on Settings → Voice; each one is
downloaded once (about 60 MB) into ~/.local/share/amadeus/voice/models/piper/ and then works offline."""
import glob
import os
import subprocess
import threading

from . import db
from .config import CFG

VOICE_DIR = os.path.expanduser("~/.local/share/amadeus/voice")
PIPER_DIR = os.path.join(VOICE_DIR, "models", "piper")
PYTHON = os.path.join(VOICE_DIR, "venv-lite", "bin", "python")

CATALOG = [
    ("en_US-lessac-medium", "Lessac", "English (US), clear and neutral"),
    ("en_GB-alan-medium", "Jarvis-style", "English (UK), calm butler-like male voice"),
    ("en_US-ryan-high", "Ryan", "English (US), male"),
    ("en_GB-jenny_dioco-medium", "Jenny", "English (UK), female"),
    ("en_GB-alba-medium", "Alba", "English (Scottish), female"),
    ("de_DE-thorsten-medium", "Thorsten", "German, male"),
    ("es_ES-davefx-medium", "Davefx", "Spanish, male"),
]
_busy = set()


def installed():
    return sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(PIPER_DIR, "*.onnx")))


def selected():
    """The voice id to read with: your choice, else the config's, else the first installed one."""
    have = installed()
    for v in (db.get_setting("tts_voice", ""), os.path.basename(CFG.get("tts_voice", "")).removesuffix(".onnx")):
        if v in have:
            return v
    return have[0] if have else ""


def path(voice_id=None):
    v = voice_id or selected()
    return os.path.join(PIPER_DIR, v + ".onnx") if v else ""


def listing():
    have = set(installed())
    known = {c[0] for c in CATALOG}
    rows = [{"id": i, "name": n, "about": a, "installed": i in have, "downloading": i in _busy} for i, n, a in CATALOG]
    rows += [{"id": i, "name": i, "about": "added by you", "installed": True, "downloading": False} for i in sorted(have - known)]
    return {"voices": rows, "selected": selected(), "piper": os.path.isfile(PYTHON)}


def select(voice_id):
    if voice_id not in installed():
        raise ValueError("That voice isn't downloaded yet.")
    db.set_setting("tts_voice", voice_id)
    return listing()


def download(voice_id):
    """Fetch one voice from the catalog in the background (Piper's own downloader)."""
    if voice_id not in {c[0] for c in CATALOG}:
        raise ValueError("Unknown voice.")
    if not os.path.isfile(PYTHON):
        raise ValueError("The voice service isn't set up (see docs/INSTALL.md, optional: voice).")
    if voice_id in _busy or voice_id in installed():
        return listing()
    _busy.add(voice_id)

    def run():
        try:
            os.makedirs(PIPER_DIR, exist_ok=True)
            subprocess.run([PYTHON, "-m", "piper.download_voices", voice_id, "--data-dir", PIPER_DIR],
                           capture_output=True, timeout=900)
            if not db.get_setting("tts_voice", "") and voice_id in installed():
                db.set_setting("tts_voice", voice_id)
        finally:
            _busy.discard(voice_id)
    threading.Thread(target=run, daemon=True).start()
    return listing()
