"""Settings → Assistant: who your assistant is. Its name, its personality (a persona file) and its look (an avatar
sprite set, or the default agent icon). Changes go into ~/.config/amadeus-core/config.json (and your own persona and
avatar files into the data folder), then Amadeus restarts itself so everything uses them. Nothing here is in git."""
import base64
import glob
import json
import os
import re
import subprocess
import threading

from .config import CFG, CONFIG_PATH

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSONA_DIRS = [os.path.join(CFG["data_dir"], "personas"), os.path.join(CORE, "personas")]
AVATARS = os.path.join(CFG["data_dir"], "avatar")
MOODS = ("normal", "happy", "sided_thinking", "sided_surprised", "sided_worried", "sad", "annoyed", "blush", "winking")
DEFAULTS = {"assistant_name": "Amadeus", "persona": "default", "avatar": ""}


def _read_config():
    try:
        return json.load(open(CONFIG_PATH))
    except (OSError, ValueError):
        return {}


def _persona_file(name):
    for d in PERSONA_DIRS:
        f = os.path.join(d, os.path.basename(name) + ".md")
        if os.path.isfile(f):
            return f
    return ""


def personas():
    return sorted({os.path.basename(f)[:-3] for d in PERSONA_DIRS for f in glob.glob(os.path.join(d, "*.md"))})


def avatar_sets():
    """Sprite sets you added: folders in the data folder's avatar/ with at least one image."""
    return sorted(d for d in os.listdir(AVATARS) if glob.glob(os.path.join(AVATARS, d, "*.png"))) \
        if os.path.isdir(AVATARS) else []


def get():
    c = _read_config()
    persona = c.get("persona", CFG.get("persona", "default"))
    f = _persona_file(persona) if persona else ""
    return {"name": c.get("assistant_name", CFG["assistant_name"]), "persona": persona, "personas": personas(),
            "persona_text": open(f).read() if f else "", "persona_is_yours": f.startswith(PERSONA_DIRS[0]),
            "avatar": c.get("avatar", CFG.get("avatar", "")), "avatars": avatar_sets()}


def _restart():
    """Amadeus reads its settings at start: restart it (and the wake word, which listens for the name) a moment later,
    so this request still gets its answer."""
    def later():
        import time
        time.sleep(1.0)
        subprocess.run(["systemctl", "--user", "restart", "amadeus-wake"], capture_output=True, timeout=30)
        subprocess.run(["systemctl", "--user", "restart", "amadeus-core"], capture_output=True, timeout=30)
    threading.Thread(target=later, daemon=True).start()


def save(fields):
    """Save the name, the persona (by name, or your own text) and the avatar set ("" = the default agent)."""
    c = _read_config()
    if "name" in fields:
        name = re.sub(r"\s+", " ", str(fields["name"])).strip()[:40]
        if not name:
            raise ValueError("The assistant needs a name.")
        c["assistant_name"] = name
    if "persona_text" in fields:  # your own personality: kept as personas/custom.md in the data folder
        os.makedirs(PERSONA_DIRS[0], exist_ok=True)
        with open(os.path.join(PERSONA_DIRS[0], "custom.md"), "w") as f:
            f.write(str(fields["persona_text"])[:8000])
        c["persona"] = "custom"
    elif "persona" in fields:
        p = os.path.basename(str(fields["persona"]))
        if p and p not in personas():
            raise ValueError("Unknown persona.")
        c["persona"] = p
    if "avatar" in fields:
        a = os.path.basename(str(fields["avatar"] or ""))
        if a and a not in avatar_sets():
            raise ValueError("Unknown avatar.")
        c["avatar"] = a
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(c, f, indent=2)
    _restart()
    return {"ok": True, "restarting": True}


def reset():
    """The default assistant: name Amadeus, the friendly default persona, the default agent icon. Your own persona and
    avatar files are kept (you can switch back to them)."""
    c = _read_config()
    c.update({"assistant_name": DEFAULTS["assistant_name"], "persona": DEFAULTS["persona"], "avatar": DEFAULTS["avatar"]})
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(c, f, indent=2)
    _restart()
    return {"ok": True, "restarting": True}


def upload(files, set_name="custom"):
    """Your own avatar images (PNG). One image: it is used for every mood. Images named like happy1.png or
    custom_happy1.png fill those moods (frames 1-3 make the mouth move while it talks)."""
    set_name = re.sub(r"[^a-z0-9_-]", "", str(set_name).lower())[:30] or "custom"
    d = os.path.join(AVATARS, set_name)
    os.makedirs(d, exist_ok=True)
    saved = []
    for i, f in enumerate(files[:40]):
        data = base64.b64decode(str(f.get("data", "")).split(",")[-1])
        if not data.startswith(b"\x89PNG"):
            raise ValueError(f"{f.get('name', 'file')} is not a PNG image.")
        if len(data) > 8_000_000:
            raise ValueError(f"{f.get('name', 'file')} is larger than 8 MB.")
        stem = os.path.splitext(os.path.basename(str(f.get("name", ""))))[0].lower().removeprefix(set_name + "_")
        m = re.fullmatch(r"(%s)([123])" % "|".join(MOODS), stem)
        target = f"{set_name}_{m.group(1)}{m.group(2)}.png" if m else (f"{set_name}_normal1.png" if i == 0 else None)
        if target:
            with open(os.path.join(d, target), "wb") as out:
                out.write(data)
            saved.append(target)
    return {"saved": saved, "set": set_name, "avatars": avatar_sets()}
