"""Client for the Thunderbird bridge (thunderbird/bridge_host.py + the Amadeus Bridge add-on).
Thunderbird keeps the accounts and logins; Amadeus only asks it for mail, drafts and (approved) sends."""
import json
import os
import socket
import subprocess
import time

from .config import CFG

SOCK = os.path.join(CFG["data_dir"], "mail.sock")


class NotRunning(RuntimeError):
    pass


def _connect(timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout + 5)
    s.connect(SOCK)
    return s


def _start_thunderbird():
    """Thunderbird was closed: start it minimized and wait for the bridge (up to ~60 s)."""
    if subprocess.run(["pgrep", "-x", "thunderbird"], capture_output=True).returncode == 0:
        # it runs: maybe it is still starting (the add-on connects a few seconds after the window); wait a bit
        for _ in range(30):
            time.sleep(1)
            try:
                _connect(5).close()
                return True
            except OSError:
                pass
        return False  # still nothing: the add-on is missing or disabled
    from .tools import launch
    launch([os.path.expanduser("~/.local/bin/amadeus-mail-start")], "thunderbird")
    for _ in range(60):
        time.sleep(1)
        try:
            _connect(5).close()
            return True
        except OSError:
            pass
    return False


def call(op, timeout=120, autostart=True, **args):
    try:
        s = _connect(timeout)
    except OSError:
        if not autostart:
            raise NotRunning("Thunderbird is not running.")
        if not _start_thunderbird():
            raise NotRunning("Thunderbird is not reachable: is the Amadeus Bridge add-on installed and enabled?")
        s = _connect(timeout)
    with s:
        f = s.makefile("rwb")
        f.write((json.dumps({"op": op, "args": args, "timeout": timeout}) + "\n").encode())
        f.flush()
        resp = json.loads(f.readline() or b'{"ok": false, "error": "no answer from Thunderbird"}')
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "mail bridge error"))
    return resp.get("result")


def status():
    try:
        return {"connected": call("ping", timeout=5) == "pong", "accounts": call("accounts", timeout=10)}
    except Exception as e:
        return {"connected": False, "error": str(e), "accounts": []}


SKIP_USES = ("trash", "sent", "drafts", "templates", "outbox")


def new_recent(days, limit=60, autostart=True):
    """Mail that ARRIVED in the last `days`, read or not (you may have opened it on your phone already): the inbox
    and junk of every account, plus any folder that has unread mail (server-side filters file mail there)."""
    folders = [f for f in call("folders", timeout=60, autostart=autostart)
               if not any(u in SKIP_USES for u in f.get("specialUse", []))
               and (set(f.get("specialUse", [])) & {"inbox", "junk"} or (f.get("unread") or 0) > 0)]
    out = []
    for f in folders:
        for m in call("recent", folderId=f["id"], days=days, limit=limit, unreadOnly=False, timeout=60, autostart=autostart):
            m["folder"] = m.get("folder") or f["path"]
            m["folderId"] = m.get("folderId") or f["id"]
            out.append(m)
    out.sort(key=lambda m: m.get("date") or "", reverse=True)
    return out[:limit]


def unread_recent(days, limit=50, account_id="", autostart=True):
    """Newest unread mail of the last `days` days (may be a fraction) across every folder except trash/sent/drafts.
    Returns (mails newest first, total unread count in those folders)."""
    folders = [f for f in call("folders", accountId=account_id, timeout=60, autostart=autostart)
               if not any(u in SKIP_USES for u in f.get("specialUse", []))]
    total = sum(f.get("unread") or 0 for f in folders)
    out = []
    for f in folders:
        if f.get("unread") == 0:
            continue
        for m in call("recent", folderId=f["id"], days=days, limit=limit, unreadOnly=True, timeout=60, autostart=autostart):
            m["folder"] = m.get("folder") or f["path"]
            out.append(m)
    out.sort(key=lambda m: m.get("date") or "", reverse=True)
    return out[:limit], total
