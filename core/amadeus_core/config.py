"""Settings. Defaults fit a single-user desktop; override in ~/.config/amadeus-core/config.json."""
import json
import os
from pathlib import Path
import secrets

from . import folders

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".config", "amadeus-core", "config.json")

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8095,
    "data_dir": os.path.join(HOME, ".local", "share", "amadeus", "core"),
    "ollama_url": "http://127.0.0.1:11434",
    "default_model": "qwen3.5-9b-48k",
    "folder": "",                 # your folder, with Notes/ and Projects/ in it; "" = ~/Amadeus (see folders.py)
    "ms_client_id": "",           # the app's registration at Microsoft, for signing in to Outlook directly (not a secret)
    "hindsight_url": "http://127.0.0.1:8888",
    "hindsight_bank": "amadeus-private",
    "secrets_dir": os.path.join(HOME, ".local", "share", "amadeus", "secrets"),  # created by install.sh, never in git
    "hindsight_key_file": os.path.join(HOME, ".local", "share", "amadeus", "secrets", "hindsight-keys.json"),
    "hindsight_key_name": "amadeus",
    "presidio_analyzer": "http://172.30.77.10:3000/analyze",    # on the private Docker network install.sh creates
    "presidio_anonymizer": "http://172.30.77.11:3000/anonymize",
    "history_chars": 24000,
    "quiet_hours": [23, 7],
    "mail_check_minutes": 10,     # background mail watch interval
    "mail_notify": "important",   # important (call only for important mail) | all | off
    # Who the assistant is. All of it is yours to change (see docs/INSTALL.md, "Make it yours").
    "assistant_name": "Amadeus",  # shown everywhere and used as the default wake word
    "persona": "default",         # a file in data_dir/personas/ or core/personas/ (without .md); "" = no persona
    "avatar": "",                 # a sprite set in data_dir/avatar/<name>/ (<name>_<mood><1-3>.png); "" = the default icon
}


def projects_dir(cfg):
    """The folder with one subfolder per Claude Code project."""
    return os.path.realpath(cfg["projects"])


def load():
    cfg, own = dict(DEFAULTS), json.loads(Path(CONFIG_PATH).read_text()) if os.path.exists(CONFIG_PATH) else {}
    cfg.update(own)
    found = folders.paths(own, HOME)
    cfg.update(notes_dir=found["notes"], notes_root=found["notes_root"], projects=found["projects"])
    os.makedirs(cfg["notes_dir"], exist_ok=True)
    os.makedirs(cfg["data_dir"], exist_ok=True)
    os.chmod(cfg["data_dir"], 0o700)
    token_path = os.path.join(cfg["data_dir"], "token")
    if not os.path.exists(token_path):
        with open(token_path, "w") as f:
            f.write(secrets.token_urlsafe(32))
        os.chmod(token_path, 0o600)
    cfg["token"] = Path(token_path).read_text().strip()
    return cfg


# Started by systemd at boot, Amadeus doesn't get your login shell's PATH: programs installed for you alone
# (~/.local/bin, e.g. `claude` for work runs) would not be found ("No such file or directory: 'claude'").
_LOCAL_BIN = os.path.join(HOME, ".local", "bin")
if _LOCAL_BIN not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _LOCAL_BIN + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")

CFG = load()
NAME = CFG["assistant_name"]  # the assistant's name (config "assistant_name")


DESKTOP_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP",
                "XDG_SESSION_TYPE", "XDG_SESSION_DESKTOP", "KDE_FULL_SESSION", "QT_QPA_PLATFORMTHEME", "XAUTHORITY")


def desktop_env():
    """Amadeus starts at boot, before you log in, so its own environment has no display. Before opening a window or an
    app, the desktop session's variables are taken from systemd (KDE puts them there at login); without them the popup
    and opened apps fail with "Gtk couldn't be initialized". Missing variables only: nothing set is overwritten."""
    import subprocess
    import sys
    if sys.platform == "darwin":  # no such thing there: apps open through `open`
        return
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k in DESKTOP_VARS and v and not os.environ.get(k):
            os.environ[k] = v
