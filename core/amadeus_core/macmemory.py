"""The memory on a Mac: Hindsight and its database in their own folder, as one service sealed off by macOS. They can reach only this
computer (for the model in Ollama), and write only in their own folder. On Linux the same job is done by a container (install.sh)."""
import glob
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

from . import paths, system
from .config import CFG

HOME = os.path.join(paths.ROOT, "memory")
PYTHON = os.path.join(HOME, "venv", "bin", "python")
HINDSIGHT = os.path.join(HOME, "venv", "bin", "hindsight-api")
READY_FILE = os.path.join(HOME, "installed")
RUN_FILE = os.path.join(HOME, "run.json")
PASSWORD_FILE = os.path.join(HOME, "database-password")
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_runner.py")
EXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hindsight_ext")
VERSION = "1.2.0"
DB_PORT = 8889
API_PORT = 8888
INSTANCE = "amadeus"


def ready():
    return os.path.isfile(READY_FILE) and os.path.isfile(PYTHON)


def profile():
    """The rules macOS enforces. The last rule that matches wins."""
    home = os.path.realpath(os.path.expanduser("~"))
    own = os.path.realpath(HOME)
    return f'''(version 1)
(allow default)
(deny network*)
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
(deny file-write*)
(allow file-write* (subpath "{own}") (subpath "/private/tmp") (subpath "/private/var/folders") (literal "/dev/null") (literal "/dev/dtracehelper"))
(deny file-read* (subpath "{home}"))
(allow file-read* (subpath "{own}"))
(allow file-read-metadata (subpath "{home}"))
'''


def sealed(args):
    rules = os.path.join(HOME, "seal.sb")
    Path(rules).write_text(profile())
    return ["/usr/bin/sandbox-exec", "-f", rules, *args]


def _postgres():
    found = glob.glob(os.path.join(HOME, ".pg0", "installation", "*", "bin", "postgres"))
    if not found:
        raise OSError("the memory's database isn't installed")
    return found[0]


def write_run_file():
    """What the service needs, in its own folder: under the seal it can't read anything else of yours. Written when something changed."""
    keys = json.loads(Path(CFG["hindsight_key_file"]).read_text())
    password = Path(PASSWORD_FILE).read_text().strip()
    wanted = {"home": HOME, "ext": EXT, "postgres": _postgres(), "hindsight": HINDSIGHT, "db_port": DB_PORT,
              "data": os.path.join(HOME, ".pg0", "instances", INSTANCE, "data"),
              "env": {"HINDSIGHT_API_DATABASE_URL": f"postgresql://hindsight:{password}@127.0.0.1:{DB_PORT}/hindsight",
                      "HINDSIGHT_API_TENANT_EXTENSION": "amadeus_ext.keymap:KeyMapTenantExtension",
                      "HINDSIGHT_API_TENANT_KEYS": json.dumps({v: n for n, v in keys.items()}),
                      "HINDSIGHT_API_HOST": "127.0.0.1", "HINDSIGHT_API_PORT": str(API_PORT), "HINDSIGHT_API_WORKER_ID": "amadeus-hindsight",
                      "HINDSIGHT_API_LLM_PROVIDER": "ollama", "HINDSIGHT_API_LLM_BASE_URL": CFG["ollama_url"], "HINDSIGHT_API_LLM_MODEL": CFG["default_model"],
                      "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "local"}}
    text = json.dumps(wanted, indent=1)
    if os.path.exists(RUN_FILE) and Path(RUN_FILE).read_text() == text:
        return False
    with open(os.open(RUN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(text)
    return True


def _healthy():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/health", timeout=3).close()
        return True
    except OSError:
        return False


def _wait_healthy(seconds):
    for _ in range(seconds // 2):
        if _healthy():
            return True
        time.sleep(2)
    return False


def _api(path, body):
    key = json.loads(Path(CFG["hindsight_key_file"]).read_text())[CFG["hindsight_key_name"]]
    req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/v1/default/banks/{CFG['hindsight_bank']}{path}", json.dumps(body).encode(),
                                 {"content-type": "application/json", "authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.load(r)


def check_seal():
    """It has to be cut off, or the memory stays off."""
    for code in ("import socket; socket.create_connection(('1.1.1.1', 53), timeout=4)", "import urllib.request; urllib.request.urlopen('http://example.com', timeout=6)", f"open({os.path.expanduser('~/.amadeus-seal-test')!r}, 'w')"):
        if subprocess.run(sealed([PYTHON, "-c", code]), capture_output=True, timeout=30).returncode == 0:
            raise OSError("the memory isn't sealed off, so it stays off")


def _create_database():
    if not os.path.exists(PASSWORD_FILE):
        with open(os.open(PASSWORD_FILE, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(secrets.token_urlsafe(24))
    script = ("import sys; from pg0 import Pg0; "
              f"p = Pg0(name={INSTANCE!r}, username='hindsight', password=sys.argv[1], database='hindsight', port={DB_PORT}); p.start(); p.stop()")
    subprocess.run([PYTHON, "-c", script, Path(PASSWORD_FILE).read_text().strip()], check=True, capture_output=True, timeout=600, env={"PATH": "/usr/bin:/bin", "HOME": HOME})


def install(say=lambda text: None, service=True):
    """Its own Python, database and language models. The downloads happen once here, before it's sealed off. A first start outside the seal
    fetches the models and holds no memories of yours; then a memory is saved and found again, sealed, before it counts as ready."""
    run = lambda cmd: subprocess.run(cmd, check=True, capture_output=True, timeout=3600)  # noqa: E731
    if os.path.exists(READY_FILE):
        os.remove(READY_FILE)
    os.makedirs(HOME, exist_ok=True)
    say("Installing the memory")
    run([sys.executable, "-m", "venv", os.path.join(HOME, "venv")])
    run([PYTHON, "-m", "pip", "install", "--quiet", f"hindsight-api=={VERSION}"])
    say("Setting up its database")
    _create_database()
    write_run_file()
    check_seal()
    say("Downloading what it needs to read and remember")
    first = subprocess.Popen([PYTHON, RUNNER, RUN_FILE, "--unsealed"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_healthy(900):
            raise OSError("the memory didn't start")
    finally:
        first.terminate()
        first.wait(timeout=60)
    say("Checking that it works sealed off")
    test = subprocess.Popen(sealed([PYTHON, RUNNER, RUN_FILE]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_healthy(180):
            raise OSError("the memory doesn't start sealed off, so it stays off")
        _api("/memories", {"items": [{"content": "Amadeus was set up on this computer."}]})
        found = _api("/memories/recall", {"query": "Was Amadeus set up on this computer?", "max_tokens": 300}).get("results", [])
        if not found:
            raise OSError("the memory didn't find what it just saved")
    finally:
        test.terminate()
        test.wait(timeout=60)
    Path(READY_FILE).write_text(time.strftime("%Y-%m-%d"))
    if service:
        start_service()


def start_service():
    logs = os.path.expanduser("~/Library/Logs/Amadeus")
    os.makedirs(logs, exist_ok=True)
    system.install_agent("amadeus-memory", sealed([PYTHON, RUNNER, RUN_FILE]), needs=PYTHON)


def at_start():
    """The core started: the service follows the model you use now."""
    if ready() and write_run_file():
        start_service()
