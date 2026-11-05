#!/usr/bin/env python3
"""PreToolUse guard for the work runs (Claude Code started by Amadeus, see core/amadeus_core/work.py).
- Writing only inside your projects folder (one subfolder per project: docs, blueprints, images, code).
- Your notes are off-limits completely (read and write), unless an older install keeps the projects in them.
- Never this guard or its settings, Amadeus's own data, secrets, SSH keys, mail or service configs.
core/amadeus_core/workguard.py fills in @PROJECTS@ and @NOTES@. Exit 2 blocks the tool call."""
import json, os, sys

PROJECTS = os.path.realpath("@PROJECTS@")
NOTES = "@NOTES@"
NOTES = os.path.realpath(NOTES) if NOTES else ""
HOME = os.path.realpath(os.path.expanduser("~"))  # a linked home folder (always on macOS for /tmp and /var) must not slip past these
GUARD = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
SECRET_DIRS = [os.path.join(HOME, p) for p in (
    ".local/share/amadeus/core", ".local/share/amadeus/secrets", ".local/share/amadeus/backup", ".config/amadeus-core",
    "Library/Application Support/Amadeus/core", "Library/Application Support/Amadeus/secrets", "Library/Application Support/Amadeus/backup",
    "Library/Application Support/Amadeus/config", "Library/Application Support/Amadeus/work-guard", "Library/Thunderbird", "Library/Keychains",
    ".thunderbird", ".claude/.credentials.json", ".ssh", ".gnupg", ".aws", ".ollama")]
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

def inside(path, root):
    return bool(root) and (path == root or path.startswith(root + os.sep))

def block(msg):
    print(f"work-guard: {msg}", file=sys.stderr); sys.exit(2)

try:
    data = json.load(sys.stdin)
except Exception:
    block("could not read tool input; blocking to be safe")

tool = data.get("tool_name", "")
ti = data.get("tool_input") or {}
target = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
if not target:
    sys.exit(0)
real = os.path.realpath(os.path.join(data.get("cwd") or os.getcwd(), os.path.expanduser(target)))
base = os.path.basename(real)

if any(inside(real, d) for d in SECRET_DIRS) or base == ".env" or base.startswith(".env."):
    block(f"{real} holds secrets or private data and is off-limits for work runs.")
if tool in WRITE_TOOLS and (inside(real, GUARD) or real.endswith(os.path.join(".claude", "settings.json"))):
    block(f"{real} is protected configuration.")
if inside(real, NOTES) and not inside(real, PROJECTS):
    block(f"{real} is in the user's private notes. Anything from the user comes through Amadeus.")
if tool in WRITE_TOOLS and not inside(real, PROJECTS):
    block(f"Work runs may only write inside {PROJECTS} (one folder per project).")
sys.exit(0)
