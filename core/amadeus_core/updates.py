"""Is there a newer version? Once a day it asks GitHub for the latest release and sends nothing about you; you can turn
that off (Settings → Assistant). The notes are only ever shown to you as text, never given to the model."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import db

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LATEST = "https://api.github.com/repos/IAbrahamI/Amadeus/releases/latest"
DAY = 86400


def _version_file():
    try:
        return Path(os.path.join(ROOT, "VERSION")).read_text().strip()
    except OSError:
        return ""


RUNNING = _version_file()  # what this process started with; the file changes when a package update arrives


def _parts(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def newer(a, b):
    return bool(_parts(a)) and _parts(a) > _parts(b)


def enabled():
    return db.get_setting("update_check", True)


def set_enabled(on):
    db.set_setting("update_check", on)
    if on:
        db.set_setting("update_checked", 0)
        threading.Thread(target=check, daemon=True).start()
    return status()


def check(now=None):
    """Background job: at most once a day."""
    now = now or time.time()
    if not enabled() or now - db.get_setting("update_checked", 0) < DAY:
        return
    db.set_setting("update_checked", now)
    req = urllib.request.Request(LATEST, headers={"accept": "application/vnd.github+json", "user-agent": f"Amadeus/{RUNNING}"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=15))
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 404:  # nothing released yet
            db.set_setting("update_latest", {})
        return
    except (OSError, ValueError):
        return
    db.set_setting("update_latest", {"version": str(r.get("tag_name", "")).lstrip("v")[:32], "notes": str(r.get("body") or "")[:2000]})


def status():
    latest, installed = db.get_setting("update_latest", {}) or {}, _version_file()
    return {"version": RUNNING, "installed": installed, "enabled": enabled(), "latest": latest.get("version", ""), "notes": latest.get("notes", ""),
            "available": newer(latest.get("version", ""), installed), "restart": newer(installed, RUNNING),
            "mode": "git" if os.path.isdir(os.path.join(ROOT, ".git")) else "package"}


def run():
    """Update now, for a git install: it restarts everything itself when it's done, so it runs apart from this process."""
    if status()["mode"] != "git":
        raise ValueError("Update it with your system's package manager.")
    subprocess.Popen(["systemd-run", "--user", "--collect", os.path.join(ROOT, "install.sh"), "--update", "-y"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


def restart():
    """A package update arrived: use it."""
    def later():
        time.sleep(1)
        subprocess.run(["systemctl", "--user", "restart", "amadeus-core", "amadeus-desktop"], timeout=30)
    threading.Thread(target=later, daemon=True).start()
    return {"ok": True}
