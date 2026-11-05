"""Your notes folder. Plain Markdown files: open it in Obsidian or any other app, Amadeus doesn't need to know which.
Changing it copies your to-dos and notes over, never on top of anything already there."""
import json
import os
import shutil
import threading
import time
from pathlib import Path

from . import system, workguard
from .config import CFG, CONFIG_PATH, projects_dir

HOME = os.path.realpath(os.path.expanduser("~"))
SHARED = ("ToDo.md", "Notes.md", "_Amadeus")


def status():
    return {"notes": CFG["notes_dir"], "projects": projects_dir(CFG)}


def _restart():
    """The paths are read at start: a moment later, so this answer still reaches the page."""
    def run():
        time.sleep(1)
        system.restart("amadeus-core")
    threading.Thread(target=run, daemon=True).start()


def set_notes(path):
    notes = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    if not str(path or "").strip() or not (notes + os.sep).startswith(HOME + os.sep) or notes == HOME:
        raise ValueError("Pick a folder inside your home folder.")
    projects = projects_dir(CFG)
    if (projects + os.sep).startswith(notes + os.sep):
        raise ValueError("Your projects are inside that folder. Work runs must never see your notes, so pick another one, or move the projects first on the Projects page.")
    if (notes + os.sep).startswith(projects + os.sep):
        raise ValueError("That's inside your projects folder, where work runs could read your notes. Pick another one.")
    os.makedirs(notes, exist_ok=True)
    kept = []
    for name in SHARED:
        src, dst = os.path.join(CFG["notes_dir"], name), os.path.join(notes, name)
        if not os.path.exists(src) or os.path.realpath(src) == os.path.realpath(dst):
            continue
        if os.path.exists(dst):
            kept.append(name)
        elif os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    own = json.loads(Path(CONFIG_PATH).read_text()) if os.path.exists(CONFIG_PATH) else {}
    own.update(notes_dir=notes, notes_root=notes)
    own.pop("vault_dir", None)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    Path(CONFIG_PATH).write_text(json.dumps(own, indent=2))
    workguard.install(projects, notes)  # work runs never read it
    _restart()
    return {"ok": True, "notes": notes, "kept": kept}
