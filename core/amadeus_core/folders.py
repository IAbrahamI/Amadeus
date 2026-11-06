"""Where your files live: one folder you choose (~/Amadeus unless you pick another), with Notes/ and Projects/ in it.
Notes are plain Markdown, so any app can open them. Run directly it prints the paths, for install.sh (nothing is created)."""
import json
import os
import sys

try:
    from . import paths as places
except ImportError:  # run directly by install.sh and the snapshots
    import paths as places


def paths(own, home):
    """{folder, notes, notes_root, projects} from your config. notes_root is what work runs are kept out of."""
    folder = os.path.expanduser(own.get("folder") or os.path.join(home, "Amadeus"))
    earlier = os.path.join(home, ".local", "share", "amadeus", "notes")
    if own.get("notes_dir"):
        notes = os.path.expanduser(own["notes_dir"])
        root = os.path.expanduser(own.get("notes_root") or notes)
    elif not own.get("folder") and os.path.isdir(earlier):
        notes = root = earlier
    else:
        notes = root = os.path.join(folder, "Notes")
    projects = os.path.expanduser(own.get("projects_dir") or os.path.join(folder, "Projects"))
    return {"folder": folder, "notes": notes, "notes_root": root, "projects": os.path.realpath(projects)}


if __name__ == "__main__":
    home, config = places.HOME, places.CONFIG_FILE
    with_own = {}
    if os.path.exists(config):
        with open(config) as f:
            with_own = json.load(f)
    if len(sys.argv) > 1 and sys.argv[1]:  # the folder you just chose, not saved yet
        with_own["folder"] = sys.argv[1]
    p = paths(with_own, home)
    print(p["folder"], p["notes"], p["notes_root"], p["projects"], sep="\n")
