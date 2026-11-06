"""The privacy filter on a Mac: Presidio in its own Python, as a program macOS seals off (no network at all, no writing, and of your
files only its own folder). On Linux the same job is done by containers on a network without internet (privacy.py).
It starts when needed and stops when idle. Whatever goes wrong here, privacy.py holds the text back."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

from . import paths

HOME = os.path.join(paths.ROOT, "filter")
PYTHON = os.path.join(HOME, "venv", "bin", "python")
READY_FILE = os.path.join(HOME, "installed")
CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAM = os.path.join(CORE, "privacy", "sealed_filter.py")
NLP = os.path.join(CORE, "privacy", "presidio", "nlp.yaml")
PACKAGES = ["presidio-analyzer", "presidio-anonymizer", "spacy"]
MODELS = ["en_core_web_lg", "de_core_news_md"]
IDLE = 15 * 60
_lock = threading.RLock()
_proc = None
_used = 0.0


def ready():
    return os.path.isfile(READY_FILE) and os.path.isfile(PYTHON)


def profile():
    """The rules macOS enforces. The last rule that matches wins."""
    home = os.path.realpath(os.path.expanduser("~"))
    own = os.path.realpath(HOME)
    return f'''(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (literal "/dev/null") (literal "/dev/dtracehelper"))
(deny file-read* (subpath "{home}"))
(allow file-read* (subpath "{own}"))
(allow file-read-metadata (subpath "{home}"))
'''


def command(args):
    rules = os.path.join(HOME, "seal.sb")
    os.makedirs(HOME, exist_ok=True)
    Path(rules).write_text(profile())
    return ["/usr/bin/sandbox-exec", "-f", rules, PYTHON, "-s", *args]


def _start():
    """Starts it and checks that it really is sealed, with a door left open here for it to try."""
    global _proc
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    probe.listen()
    probe.settimeout(0)
    try:
        p = subprocess.Popen(command([PROGRAM, NLP, str(probe.getsockname()[1])]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, env={"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~"), "PYTHONDONTWRITEBYTECODE": "1"})
        hello = json.loads(p.stdout.readline() or "{}")
        try:
            probe.accept()
            hello["sealed"] = False
        except OSError:
            pass
    finally:
        probe.close()
    if not (hello.get("ready") and hello.get("sealed")):
        p.kill()
        raise OSError("the privacy filter isn't sealed off, so it stays unused")
    _proc = p


def start():
    global _used
    with _lock:
        _used = time.time()
        if _proc is None or _proc.poll() is not None:
            _start()


def stop():
    global _proc
    with _lock:
        if _proc is not None:
            _proc.kill()
            _proc = None


def stop_when_idle():
    if _proc is not None and time.time() - _used > IDLE:
        stop()


def call(op, body, timeout=60):
    """One request. Raises if anything isn't right, and privacy.py then holds the text back."""
    global _used
    with _lock:
        start()
        timer = threading.Timer(timeout, stop)
        timer.start()
        try:
            _proc.stdin.write(json.dumps({"op": op, **body}) + "\n")
            _proc.stdin.flush()
            answer = json.loads(_proc.stdout.readline() or "{}")
        finally:
            timer.cancel()
        _used = time.time()
    if "ok" not in answer:
        raise OSError("the privacy filter didn't answer: " + str(answer.get("error", "no reply")))
    return answer["ok"]


def install(say=lambda text: None):
    """Its own Python and language models, about 1 GB. Downloads happen here, outside the seal; afterwards it never needs the network."""
    run = lambda cmd: subprocess.run(cmd, check=True, capture_output=True, timeout=3600)  # noqa: E731
    if os.path.exists(READY_FILE):
        os.remove(READY_FILE)
    say("Installing the privacy filter")
    run([sys.executable, "-m", "venv", os.path.join(HOME, "venv")])
    run([PYTHON, "-m", "pip", "install", "--quiet", *PACKAGES])
    say("Downloading its language models")
    for m in MODELS:
        run([PYTHON, "-m", "spacy", "download", m])
    say("Checking that it can't reach anything")
    stop()
    _start()
    found = call("analyze", {"text": "Anna Schmidt lives in Berlin.", "language": "en", "entities": ["PERSON", "LOCATION"], "score_threshold": 0.5})
    if not {r["entity_type"] for r in found} >= {"PERSON", "LOCATION"}:
        stop()
        raise OSError("the privacy filter didn't recognize the test sentence")
    Path(READY_FILE).write_text(time.strftime("%Y-%m-%d"))
    stop()
