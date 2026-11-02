#!/usr/bin/env python3
"""PreToolUse guard for the work runs (Claude Code started by Amadeus, see core/amadeus_core/work.py).
- The vault: only Amadeus/Projects/ (one folder per project: docs, blueprints, images). Everything else in the vault,
  including the user's ToDo/Notes and Amadeus's own folder, is off-limits (read and write).
- Never this guard or its settings, Amadeus's own data, secrets, SSH keys, mail or service configs.
install.sh fills in @VAULT@. Exit 2 blocks the tool call."""
import json, os, sys

VAULT = os.path.realpath("@VAULT@")
ALLOWED = os.path.join(VAULT, "Amadeus", "Projects")
HOME = os.path.expanduser("~")
GUARD = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
SECRET_DIRS = [os.path.join(HOME, p) for p in (
    ".local/share/amadeus/core", ".local/share/amadeus/secrets", ".local/share/amadeus/backup", ".config/amadeus-core",
    ".thunderbird", ".claude/.credentials.json", ".ssh", ".gnupg", ".aws", ".ollama")]
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

def inside(path, root):
    return path == root or path.startswith(root + os.sep)

def block(msg):
    print(f"vault-guard: {msg}", file=sys.stderr); sys.exit(2)

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
if inside(real, VAULT) and not inside(real, ALLOWED):
    block(f"{real} is in the user's private vault. Work runs may only use {ALLOWED} (one folder per project). "
          "Anything else from the user comes through Amadeus.")
sys.exit(0)
