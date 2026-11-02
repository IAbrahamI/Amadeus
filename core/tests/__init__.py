"""Tests for Amadeus Core. Run from core/: python -m unittest -v
They use a throw-away home folder, so they never touch your real data, and need no network, Ollama or Docker."""
import os
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="amadeus-test-")
os.environ["HOME"] = HOME  # before amadeus_core is imported: its data lives under HOME
os.makedirs(os.path.join(HOME, ".local", "share", "amadeus", "secrets"), exist_ok=True)
with open(os.path.join(HOME, ".local", "share", "amadeus", "secrets", "canaries.json"), "w") as f:
    f.write('{"vault": "CANARY-testmarker123"}')
with open(os.path.join(HOME, ".local", "share", "amadeus", "secrets", "denylist.txt"), "w") as f:
    f.write("# test\nProject Bluebird\n")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
