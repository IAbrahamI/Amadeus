"""The optional Obsidian connector (Settings → Connectors). Without it your to-dos and notes live in Amadeus' own folder.
Connecting copies them into an Amadeus/ folder of your vault, never over anything already there, and sets up the hourly
vault snapshots (install.sh --only obsidian). Disconnecting leaves your files in the vault."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from . import workguard
from .config import CFG, CONFIG_PATH, DEFAULTS, projects_dir

HOME = os.path.expanduser("~")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARED = ("ToDo.md", "Notes.md", "_Amadeus")


def _vault_of(notes):
    """The vault a notes folder belongs to, or "" when it's Amadeus' own folder."""
    parent = os.path.dirname(os.path.realpath(notes))
    return parent if os.path.isdir(os.path.join(parent, ".obsidian")) else ""


def _suggestion():
    """The vault Obsidian itself has open, if any."""
    try:
        vaults = json.loads(Path(os.path.join(HOME, ".config", "obsidian", "obsidian.json")).read_text()).get("vaults", {})
        return next((v["path"] for v in vaults.values() if v.get("open")), next((v["path"] for v in vaults.values()), ""))
    except (OSError, ValueError, KeyError):
        return ""


def status():
    vault = _vault_of(CFG["vault_dir"])
    return {"connected": bool(vault), "vault": vault, "suggestion": "" if vault else _suggestion()}


def _config(**change):
    c = json.loads(Path(CONFIG_PATH).read_text()) if os.path.exists(CONFIG_PATH) else {}
    c.update(change)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    Path(CONFIG_PATH).write_text(json.dumps(c, indent=2))


def _restart():
    """The paths are read at start: a moment later, so this answer still reaches the page."""
    def run():
        time.sleep(1)
        subprocess.run(["systemctl", "--user", "restart", "amadeus-core"], timeout=30)
    threading.Thread(target=run, daemon=True).start()


def connect(path):
    vault = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    if not str(path or "").strip() or not (vault + os.sep).startswith(HOME + os.sep) or vault == HOME:
        raise ValueError("Pick your vault's folder, inside your home folder.")
    if not os.path.isdir(os.path.join(vault, ".obsidian")):
        raise ValueError("That isn't an Obsidian vault (it has no .obsidian folder). Open it in Obsidian once, or check the path.")
    if (projects_dir(CFG) + os.sep).startswith(vault + os.sep):
        raise ValueError("Your projects folder is inside that vault. Give the projects their own folder first, on the Projects page.")
    target, kept = os.path.join(vault, "Amadeus"), []
    os.makedirs(target, exist_ok=True)
    for name in SHARED:  # yours from Amadeus' own folder; anything already in the vault stays as it is
        src, dst = os.path.join(CFG["vault_dir"], name), os.path.join(target, name)
        if not os.path.exists(src) or os.path.realpath(src) == os.path.realpath(dst):
            continue
        if os.path.exists(dst):
            kept.append(name)
        elif os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    r = subprocess.run([os.path.join(REPO, "install.sh"), "--only", "obsidian"], cwd=REPO, capture_output=True, text=True, timeout=120,
                       stdin=subprocess.DEVNULL, env={**os.environ, "OBSIDIAN_VAULT": vault})
    if r.returncode:
        raise ValueError("The setup didn't finish: " + (r.stdout + r.stderr).strip()[-300:])
    workguard.install(projects_dir(CFG), vault)  # work runs never read it
    _restart()
    return {"ok": True, "vault": vault, "kept": kept}


def disconnect():
    """Your files stay in the vault. To-dos and notes go on in Amadeus' own folder."""
    vault = _vault_of(CFG["vault_dir"])
    if not vault:
        raise ValueError("No vault is connected.")
    _config(vault_dir=DEFAULTS["vault_dir"])
    subprocess.run(["systemctl", "--user", "disable", "--now", "amadeus-vault-snapshot.timer"], capture_output=True, timeout=30)
    env = os.path.join(REPO, "amadeus.env") if os.access(REPO, os.W_OK) else os.path.expanduser("~/.config/amadeus-core/amadeus.env")
    if os.path.exists(env):  # (or the next update connects it again)
        text = Path(env).read_text()
        Path(env).write_text(re.sub(r"^OBSIDIAN_VAULT=.*\n?", "", text, flags=re.M))
    workguard.install(projects_dir(CFG), "")
    _restart()
    return {"ok": True}
