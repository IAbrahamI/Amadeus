"""The first start of an app that came without an installer (the Mac app): gets Ollama, sets up your folder, and picks
and downloads a model. Uses the same hardware check, speed test and model suggestions as install.sh (pick_model.py)."""
import importlib.util
import json
import os
from pathlib import Path
import secrets as tokens
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

from . import db, folders, paths, system, workguard
from .config import CFG, CONFIG_PATH

DEPLOY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy")
_spec = importlib.util.spec_from_file_location("pick_model", os.path.join(DEPLOY, "pick_model.py"))
pick_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pick_model)

OLLAMA_ZIP = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_APPS = ("/Applications/Ollama.app", os.path.expanduser("~/Applications/Ollama.app"))
_lock = threading.Lock()
_job = {"kind": "", "text": "", "pct": None, "error": "", "done": False}
_picks = []
_rejected = {}  # the model that just didn't pass, so you can remove its download
_failed = set()
_shown = {"yes": False}  # the setup really appeared in the dashboard (the build checks this)


def _own():
    return json.loads(Path(CONFIG_PATH).read_text()) if os.path.exists(CONFIG_PATH) else {}


def _api(path, body=None, method=None, timeout=10):
    req = urllib.request.Request(CFG["ollama_url"] + path, json.dumps(body).encode() if body is not None else None,
                                 {"content-type": "application/json"}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def _models():
    with _api("/api/tags") as r:
        return [m["name"].removesuffix(":latest") for m in json.load(r).get("models", [])]


def ollama_state():
    try:
        _models()
        return "running"
    except (OSError, ValueError):
        return "installed" if system.MAC and any(os.path.isdir(a) for a in OLLAMA_APPS) or shutil.which("ollama") else "missing"


def needed():
    """Only where nothing has chosen a model yet; an install that has its model never sees this."""
    own = _own()
    if own.get("setup_pending"):
        return True
    if own.get("default_model"):
        return False
    state = ollama_state()
    if state != "running":
        return system.MAC  # (on Linux the install handles Ollama; it may just be stopped for a moment)
    return CFG["default_model"] not in _models()


def status():
    if not needed() and (not _job["kind"] or _job["done"]):
        return {"needed": False, "job": dict(_job), "shown": _shown["yes"], "can_install": system.MAC, "voice_ready": voice_ready()}
    return {"needed": True, "rejected": dict(_rejected), "voice_ready": voice_ready(), "shown": _shown["yes"], "too_old": _job["kind"] == "begin" and "newer version of Ollama" in _job["error"], "model_ready": bool(_own().get("default_model")), "ollama": ollama_state(), "can_install": system.MAC,
            "folder": folders.paths(_own(), os.path.expanduser("~"))["folder"], "picks": _picks, "job": dict(_job),
            "hardware": pick_model.hardware()}


def _say(text, pct=None):
    _job.update(text=text, pct=pct)


def _run(kind, work):
    if not _lock.acquire(blocking=False):
        raise ValueError("Still busy with the last step.")
    _job.update(kind=kind, text="", pct=None, error="", done=False)

    def go():
        try:
            work()
            _job["done"] = True
        except KeyError:
            _job.update(error="Ollama gave an answer I didn't expect. Try again, and if it stays like this, update Ollama.", done=True)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            _job.update(error=str(e) or "That didn't work.", done=True)
        finally:
            _lock.release()
    threading.Thread(target=go, daemon=True).start()


def _start_ollama():
    if system.MAC:
        app = next((a for a in OLLAMA_APPS if os.path.isdir(a)), None)
        if app:
            subprocess.run(["/usr/bin/open", "-g", app], capture_output=True, timeout=20)
    for _ in range(45):
        if ollama_state() == "running":
            return
        time.sleep(1)
    raise ValueError("Ollama didn't start. Open it once from your Applications folder, then try again.")


def _quit_ollama():
    subprocess.run(["/usr/bin/osascript", "-e", 'quit app "Ollama"'], capture_output=True, timeout=30)
    for _ in range(15):
        if ollama_state() != "running":
            return
        time.sleep(1)
    raise ValueError("Ollama didn't close. Quit it from its menu bar icon, then try again.")


def _update_ollama():
    """A model needs a newer Ollama: you asked for this with the button."""
    if not any(os.path.isdir(a) for a in OLLAMA_APPS):
        raise ValueError("This Ollama wasn't installed as an app in Applications. Update it the way you installed it, then try again.")
    _install_ollama(update=True)


def _install_ollama(update=False):
    """Ollama's own signed app, only accepted if macOS confirms that signature."""
    if not update and ollama_state() == "installed":
        _say("Starting Ollama")
        return _start_ollama()
    with tempfile.TemporaryDirectory(prefix="amadeus-ollama-") as tmp:
        zipped = os.path.join(tmp, "Ollama.zip")
        with urllib.request.urlopen(urllib.request.Request(OLLAMA_ZIP, headers={"user-agent": "Amadeus"}), timeout=60) as r, open(zipped, "wb") as f:
            total, got = int(r.headers.get("content-length") or 0), 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                _say("Downloading Ollama", got * 100 // total if total else None)
        _say("Checking Ollama's signature")
        subprocess.run(["/usr/bin/ditto", "-x", "-k", zipped, tmp], check=True, capture_output=True, timeout=300)
        app = os.path.join(tmp, "Ollama.app")
        if subprocess.run(["/usr/sbin/spctl", "--assess", "--type", "execute", app], capture_output=True, timeout=120).returncode:
            raise ValueError("macOS couldn't confirm that download is really Ollama, so I didn't install it. You can get it from ollama.com.")
        if update:
            _say("Closing the old Ollama")
            _quit_ollama()
        for target in OLLAMA_APPS:
            if update and not os.path.isdir(target):
                continue
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                old = os.path.join(tmp, "old-Ollama.app")
                if update:
                    shutil.move(target, old)  # (dropped with the temporary folder, once the new one is in place)
                try:
                    shutil.move(app, target)
                except OSError:
                    if update:
                        shutil.move(old, target)
                    raise
                break
            except OSError:
                continue
        else:
            raise ValueError("Couldn't put Ollama in your Applications folder.")
    _say("Starting Ollama")
    _start_ollama()


def _pull(model, label):
    with _api("/api/pull", {"model": model, "stream": True}, timeout=120) as r:
        for line in r:
            s = json.loads(line)
            if s.get("error"):
                raise ValueError(s["error"])
            _say(label, s["completed"] * 100 // s["total"] if s.get("total") and s.get("completed") else None)


def _baseline():
    """The speed test: on a model you already have, else on a small one that's removed again."""
    have = pick_model.installed()
    probe, remove = (min(have, key=have.get), False) if have else (pick_model.PROBE, True)
    if remove:
        _pull(probe, "Getting a small test model to measure this Mac")
    _say("Measuring speed")
    tps, _share = pick_model.measure(probe)
    size = pick_model.installed().get(probe, 1.0)
    if remove:
        _api("/api/delete", {"model": probe}, method="DELETE").close()
    return (tps, size) if tps else None


def _scan():
    if not pick_model.registry_reachable():
        raise ValueError("Can't reach Ollama's model library. Check your internet connection and try again.")
    speed = _baseline()
    _say("Reading the newest models")
    latest = [m for m in pick_model.latest_models() if m["name"] not in _failed]
    found = pick_model.suggest_latest(pick_model.hardware(), latest, speed)
    if not found:
        raise ValueError("There isn't enough memory or disk space for any model here.")
    _picks[:] = [{"model": m["model"], "size": m["size"], "about": m["about"], "speed": round(m["speed"] * 0.75) if m.get("speed") else None} for m in found]


VOICE_PACKAGES = ["faster-whisper", "soundfile", "vosk", "sounddevice", "piper-tts"]
WAKE_MODEL = "vosk-model-small-en-us-0.15"
WHISPER = "Systran/faster-whisper-small"
FIRST_VOICE = "en_US-lessac-medium"
_VOICE_PYTHON = os.path.join(paths.VOICE, "venv-lite", "bin", "python")


def voice_ready():
    return os.path.isfile(_VOICE_PYTHON) and os.path.isdir(os.path.join(paths.VOICE, "models", WAKE_MODEL))


def _voice(service=True):
    """Speech recognition, the wake word and a first voice for reading aloud. Everything then runs on this computer."""
    run = lambda cmd, **kw: subprocess.run(cmd, check=True, capture_output=True, timeout=3600, **kw)  # noqa: E731
    models = os.path.join(paths.VOICE, "models")
    os.makedirs(models, exist_ok=True)
    try:
        _say("Installing speech recognition")
        run([sys.executable, "-m", "venv", os.path.join(paths.VOICE, "venv-lite")])
        run([_VOICE_PYTHON, "-m", "pip", "install", "--quiet", *VOICE_PACKAGES])
        _say("Downloading the speech model")
        run([_VOICE_PYTHON, "-c", f"from huggingface_hub import snapshot_download as d; d({WHISPER!r})"],
            env={**os.environ, "HF_HOME": os.path.join(models, "hf")})
        _say("Downloading a voice")
        piper = os.path.join(models, "piper")
        os.makedirs(piper, exist_ok=True)
        run([_VOICE_PYTHON, "-m", "piper.download_voices", FIRST_VOICE, "--data-dir", piper])
        if not os.path.isdir(os.path.join(models, WAKE_MODEL)):
            _say("Downloading the wake word model")
            with tempfile.TemporaryDirectory(prefix="amadeus-wake-") as tmp:
                zipped = os.path.join(tmp, "wake.zip")
                with urllib.request.urlopen(f"https://alphacephei.com/vosk/models/{WAKE_MODEL}.zip", timeout=120) as r, open(zipped, "wb") as f:
                    shutil.copyfileobj(r, f)
                zipfile.ZipFile(zipped).extractall(models)
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b"").decode(errors="replace").strip().splitlines()[-1:]
        raise ValueError("Setting up voice didn't work: " + (tail[0] if tail else "see the log")) from e
    db.set_setting("tts_voice", FIRST_VOICE)
    if service:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system.install_agent("amadeus-voice", [_VOICE_PYTHON, "-W", "ignore", os.path.join(here, "voice", "voice_server.py")])
    _say("Ready")


def prepare_folder(folder):
    """Your folder, the guard for work runs and the private files install.sh would have made."""
    folder = os.path.realpath(os.path.expanduser(str(folder or "").strip() or "~/Amadeus"))
    home = os.path.realpath(os.path.expanduser("~"))
    if not (folder + os.sep).startswith(home + os.sep) or folder == home:
        raise ValueError("Pick a folder inside your home folder.")
    own = _own()
    own.update(folder=folder, setup_pending=True)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    Path(CONFIG_PATH).write_text(json.dumps(own, indent=2))
    where = folders.paths(own, home)
    os.makedirs(os.path.join(where["notes"], "_Amadeus"), exist_ok=True)
    os.makedirs(where["projects"], exist_ok=True)
    readme = os.path.join(where["notes"], "README.md")
    if not os.path.exists(readme):
        shutil.copy2(os.path.join(DEPLOY, "notes", "README.md"), readme)
    workguard.install(where["projects"], where["notes_root"])
    os.makedirs(paths.SECRETS, mode=0o700, exist_ok=True)
    for name, text in (("hindsight-keys.json", json.dumps({"amadeus": tokens.token_urlsafe(32)})),
                       ("canaries.json", json.dumps({"vault": "CANARY-" + tokens.token_hex(8)})),
                       ("denylist.txt", "# One word or phrase per line that must never leave this computer (names, addresses, projects).\n")):
        f = os.path.join(paths.SECRETS, name)
        if not os.path.exists(f):
            with open(os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
                out.write(text + "\n")


def _begin(model, size):
    _say("Getting " + model)
    _rejected.clear()
    fresh = model not in pick_model.installed()
    if fresh:
        _pull(model, "Downloading " + model)
    _say("Checking that it can work with Amadeus")
    verdict, why = pick_model.tool_check(model)
    if verdict == "unknown":
        raise ValueError(f"I couldn't test {model}: {why}. Try again.")
    if verdict == "no":
        _picks[:] = [p for p in _picks if p["model"] != model]
        _rejected.update(model=model, size=size, downloaded=fresh)
        raise ValueError(f"{model} can't work with Amadeus: {why}. It needs tools for nearly everything, so please pick another one.")
    ctx = pick_model.context_for(pick_model.hardware(), size)
    variant = pick_model.variant_name(model, ctx)
    _api("/api/create", {"model": variant, "from": model, "parameters": {"num_ctx": ctx}, "stream": False}, timeout=300).close()
    own = _own()
    own["default_model"] = variant
    Path(CONFIG_PATH).write_text(json.dumps(own, indent=2))
    CFG["default_model"] = variant
    db.set_setting("chat_model", variant)
    _say("Ready")


def finish():
    own = _own()
    own.pop("setup_pending", None)
    Path(CONFIG_PATH).write_text(json.dumps(own, indent=2))
    threading.Thread(target=lambda: (time.sleep(1), system.restart("amadeus-core")), daemon=True).start()  # your folder is read at start


def act(action, b):
    if action == "shown":
        _shown["yes"] = True
    elif action == "finish":
        if not _own().get("default_model"):
            raise ValueError("Pick a model first.")
        finish()
    elif action == "ollama":
        _run("ollama", _install_ollama if system.MAC else _start_ollama)
    elif action == "remove_model":
        if not _rejected.get("downloaded"):
            raise ValueError("Nothing to remove.")
        _failed.add(_rejected["model"].split(":")[0])
        _api("/api/delete", {"model": _rejected["model"]}, method="DELETE").close()
        _rejected.clear()
    elif action == "voice":
        _run("voice", _voice)
    elif action == "update_ollama":
        _run("ollama", _update_ollama)
    elif action == "scan":
        _run("scan", _scan)
    elif action == "begin":
        pick = next((p for p in _picks if p["model"] == b.get("model")), None)
        if not pick:
            raise ValueError("Pick one of the suggested models.")
        prepare_folder(b.get("folder"))
        _run("begin", lambda: _begin(pick["model"], pick["size"]))
    else:
        raise ValueError("Unknown step.")
    return {"ok": True}
