"""The guard for Claude Code work runs, written to ~/.local/share/amadeus/work-guard (read-only): a PreToolUse hook
(core/deploy/work-guard.py), deny rules and Claude Code's own sandbox. A run may write only in your projects folder and
never reads your notes, Amadeus's data, keys or mail. Written by install.sh, and again when you pick another folder."""
import json
import os
from pathlib import Path
import shlex
import stat

try:
    from . import paths
except ImportError:  # run directly by install.sh
    import paths

GUARD = paths.GUARD
TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "work-guard.py")
PRIVATE = ["~/.ssh", "~/.gnupg", "~/.aws", "~/.ollama", "~/.thunderbird", "~/Library/Thunderbird", "~/Library/Keychains", paths.CONFIG, paths.DATA,
           paths.SECRETS, paths.BACKUP, paths.GUARD, "~/.claude/.credentials.json"]


def files(projects, notes=""):
    """What goes into the guard folder: {name: (text, mode)}."""
    projects = os.path.realpath(os.path.expanduser(projects))
    notes = os.path.realpath(os.path.expanduser(notes)) if notes else ""
    guard = Path(TEMPLATE).read_text().replace('"@PROJECTS@"', json.dumps(projects))
    guard = guard.replace('"@NOTES@"', json.dumps(notes))
    deny = [f"Edit(/{GUARD}/**)"]
    if notes and os.path.isdir(notes):
        deny += [f"Edit(/{os.path.join(notes, n)}/**)" if os.path.isdir(os.path.join(notes, n)) else f"Edit(/{os.path.join(notes, n)})"
                 for n in sorted(os.listdir(notes)) if not projects.startswith(os.path.join(notes, n))]
    settings = {
        "permissions": {"deny": deny},
        "hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Read|Grep|Glob|LS",
                                  "hooks": [{"type": "command", "command": shlex.quote(os.path.join(GUARD, "work-guard.py"))}]}]},
        "sandbox": {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                    "filesystem": {"allowWrite": [projects], "allowRead": [projects],
                                   "denyRead": ([notes] if notes and not projects.startswith(notes + os.sep) else []) + PRIVATE},
                    "network": {"allowedDomains": []}}}
    return {"work-guard.py": (guard, 0o555), "settings.json": (json.dumps(settings, indent=2) + "\n", 0o444)}


def install(projects, notes=""):
    """Write the guard (only what changed). Returns the names of the files written."""
    os.makedirs(projects, exist_ok=True)
    os.makedirs(GUARD, exist_ok=True)
    os.chmod(GUARD, 0o755)
    wrote = []
    for name, (text, mode) in files(projects, notes).items():
        p = os.path.join(GUARD, name)
        if os.path.exists(p) and Path(p).read_text() == text:
            continue
        if os.path.exists(p):
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
            os.remove(p)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)
        wrote.append(name)
    old = os.path.join(GUARD, "vault-guard.py")  # the earlier name of the hook
    if os.path.exists(old):
        os.chmod(old, stat.S_IRUSR | stat.S_IWUSR)
        os.remove(old)
    os.chmod(GUARD, 0o555)
    return wrote


if __name__ == "__main__":  # install.sh: python3 workguard.py <projects> [<notes>] [--check]
    import sys
    args = [a for a in sys.argv[1:] if a != "--check"]
    if "--check" in sys.argv:
        want = files(*args)
        stale = [n for n, (t, _) in want.items() if not os.path.exists(os.path.join(GUARD, n)) or Path(os.path.join(GUARD, n)).read_text() != t]
        print("  → would write: " + ", ".join(stale) if stale else "  ✓ work-run guard up to date")
    else:
        w = install(*args)
        print("  · wrote the work-run guard: " + ", ".join(w) if w else "  ✓ work-run guard up to date")
