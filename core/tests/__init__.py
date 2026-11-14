"""Tests for Amadeus Core. Run from core/: python -m unittest -v
They use a throw-away home folder, so they never touch your real data, and need no network, Ollama or Docker."""
import os
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="amadeus-test-")
os.environ["HOME"] = HOME  # before amadeus_core is imported: its data lives under HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amadeus_core import paths  # noqa: E402

os.makedirs(paths.SECRETS, exist_ok=True)
with open(os.path.join(paths.SECRETS, "canaries.json"), "w") as f:
    f.write('{"marker": "CANARY-testmarker123"}')
with open(os.path.join(paths.SECRETS, "denylist.txt"), "w") as f:
    f.write("# test\nProject Bluebird\n")

from amadeus_core import agent  # noqa: E402

agent.TWO_STEP = False  # the unit tests script the model's answers; the closed-list pick has its own tests (PickFromAList)

from amadeus_core import secretstore  # noqa: E402

# never the real Keychain from a test: on a Mac it can wait for a "may Python use your Keychain?" answer forever
# (the Mac build checks the real one in .github/workflows/mac-app.yml; test_secretstore uses a stand-in)
secretstore.native = lambda: False
