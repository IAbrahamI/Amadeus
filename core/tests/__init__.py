"""Tests for Amadeus Core. Run from core/: python -m unittest -v
They use a throw-away home folder, so they never touch your real data, and need no network, Ollama or Docker."""
import os
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="amadeus-test-")
os.environ["HOME"] = HOME  # before amadeus_core is imported: its data lives under HOME
# (Windows finds the home folder and the app data folders through these instead: also the throw-away ones)
os.environ["USERPROFILE"] = HOME
os.environ["APPDATA"] = os.path.join(HOME, "AppData", "Roaming")
os.environ["LOCALAPPDATA"] = os.path.join(HOME, "AppData", "Local")
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

from amadeus_core import meaning  # noqa: E402

meaning.installed = lambda force=False: False  # no Ollama in the unit tests: looking back uses the word search (test_meaning covers this one)

from amadeus_core import web  # noqa: E402

web.real_start, web._start = web._start, lambda: False  # never Docker from a test (a stopped search engine would be started for real); test_web covers it

from amadeus_core import system  # noqa: E402

# The tests describe Linux unless they say otherwise (they patch system.MAC / system.WIN), also when they run on
# Windows or a Mac; and a test never ends the test run the way a restart ends the core on Windows.
system.WIN = False
system.end_for_restart = lambda: None
