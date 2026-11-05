"""Where Amadeus keeps its own data on this system. Everything else asks here: the core, the voice services, the tests.
Standard library only, because the voice services run this from their own Python environments."""
import os
import sys

HOME = os.path.expanduser("~")
if sys.platform == "darwin":
    ROOT = os.path.join(HOME, "Library", "Application Support", "Amadeus")
    CONFIG = os.path.join(ROOT, "config")
else:
    ROOT = os.path.join(HOME, ".local", "share", "amadeus")
    CONFIG = os.path.join(HOME, ".config", "amadeus-core")

CONFIG_FILE = os.path.join(CONFIG, "config.json")
DATA = os.path.join(ROOT, "core")
SECRETS = os.path.join(ROOT, "secrets")
BACKUP = os.path.join(ROOT, "backup")
GUARD = os.path.join(ROOT, "work-guard")
VOICE = os.path.join(ROOT, "voice")
