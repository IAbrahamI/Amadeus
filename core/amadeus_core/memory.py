"""Where the long-term memory (Hindsight) is, and whether it answers. One place for every caller: the tools, the
recall before an answer, what Amadeus says about itself, the Connectors page.

Two ways: the Hindsight Amadeus set up on this computer (the default), or one you already run elsewhere
("Use a Hindsight you already run"). That one is saved in secrets/hindsight-external.json, readable only by you,
because its key is a password."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import CFG
from . import paths

EXTERNAL = os.path.join(paths.SECRETS, "hindsight-external.json")
CHECK_SECONDS = 30  # how long an answer to "does it answer?" is reused
_state = {"at": 0.0, "ok": False, "error": "", "key": None}
_lock = threading.Lock()


def external():
    """The Hindsight you run yourself, or None."""
    try:
        d = json.loads(Path(EXTERNAL).read_text())
        return d if d.get("url") else None
    except (OSError, ValueError):
        return None


def conn():
    """(url, bank, key) of the memory in use. key may be "" for a Hindsight without sign-in."""
    ext = external()
    if ext:
        return ext["url"].rstrip("/"), ext.get("bank") or CFG["hindsight_bank"], ext.get("key", "")
    try:
        key = json.loads(Path(CFG["hindsight_key_file"]).read_text())[CFG["hindsight_key_name"]]
    except (OSError, ValueError, KeyError):
        key = ""
    return CFG["hindsight_url"].rstrip("/"), CFG["hindsight_bank"], key


def request(path, body=None, timeout=120, where=None):
    """A call to the memory bank. body None = GET. where: (url, bank, key) to use instead of the saved one."""
    url, bank, key = where or conn()
    headers = {"authorization": f"Bearer {key}"} if key else {}
    data = None
    if body is not None:
        data, headers["content-type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(f"{url}/v1/default/banks/{urllib.parse.quote(bank, safe='')}{path}", data, headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _probe(where=None):
    """"" when the bank answers, else why not, in words."""
    try:
        request("/stats", timeout=3, where=where)
        return ""
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in (401, 403):
            return "It answers, but doesn't accept the key."
        if e.code == 404:
            return "It answers, but has no memory bank by that name."
        return f"It answers with an error ({e.code})."
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return f"It doesn't answer right now ({str(reason)[:80]})."


def check(force=False):
    """(answers, why not). Asked before every answer, so it's reused for CHECK_SECONDS; a change of setup asks again."""
    key = (conn(), _installed())
    with _lock:
        if not force and _state["key"] == key and time.time() - _state["at"] < CHECK_SECONDS:
            return _state["ok"], _state["error"]
    if not key[1]:
        from . import system
        err = "Not set up yet: “Set up the memory” above." if system.MAC else "Not set up yet: run ./install.sh --only hindsight."
    else:
        err = _probe()
    with _lock:
        _state.update(at=time.time(), ok=not err, error=err, key=key)
    return not err, err


def ready():
    return check()[0]


def _installed():
    """Amadeus' own memory exists on this computer (or you use one elsewhere)."""
    if external():
        return True
    from . import system
    if system.MAC:
        from . import macmemory
        return macmemory.ready()
    return os.path.isfile(CFG["hindsight_key_file"])


def _local_url(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def use_external(url, bank="", key=""):
    """Test first, then save. The key is kept in secrets/, never in config.json or the database."""
    url = str(url or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The address starts with http:// or https://, like http://192.168.1.20:8888.")
    where = (url, str(bank or "").strip() or CFG["hindsight_bank"], str(key or "").strip())
    err = _probe(where)
    if err:
        raise ValueError(err)
    os.makedirs(paths.SECRETS, exist_ok=True)
    tmp = EXTERNAL + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"url": where[0], "bank": where[1], "key": where[2]}, f)
    os.replace(tmp, EXTERNAL)
    check(force=True)
    return status()


def use_local():
    """Back to the memory on this computer. What's stored in the other Hindsight stays there."""
    try:
        os.remove(EXTERNAL)
    except FileNotFoundError:
        pass
    check(force=True)
    return status()


def status():
    """For the Connectors page. Never the key."""
    url, bank, _ = conn()
    ok, err = check()
    ext = external() is not None
    return {"mode": "external" if ext else "local", "url": url, "bank": bank, "ready": ok, "error": err,
            "leaves_pc": ext and not _local_url(url),
            "plain_http": ext and urllib.parse.urlsplit(url).scheme == "http" and not _local_url(url)}
