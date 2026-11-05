"""Client for the Thunderbird bridge (thunderbird/bridge_host.py + the Amadeus Bridge add-on).
Thunderbird keeps the accounts and logins; Amadeus only asks it for mail, drafts and (approved) sends."""
import json
import os
import socket
import subprocess
import time

from .config import CFG
from . import maildirect

SOCK = os.path.join(CFG["data_dir"], "mail.sock")


class NotRunning(RuntimeError):
    pass


def _connect(timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout + 5)
    s.connect(SOCK)
    return s


def thunderbird_set_up():
    """Only with the bridge set up (./install.sh --setup) does anything here touch Thunderbird."""
    return os.path.exists(os.path.expanduser("~/.thunderbird/native-messaging-hosts/amadeus_bridge.json"))


def configured():
    """Mail is optional, and connected through Thunderbird, directly, or some accounts each way."""
    return thunderbird_set_up() or maildirect.has_accounts()


def _start_thunderbird():
    """Thunderbird was closed: start it minimized and wait for the bridge (up to ~60 s)."""
    if not thunderbird_set_up():
        return False
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


def accounts_off():
    """Accounts you switched off in Mail (+ Add account): Amadeus doesn't read them, anywhere."""
    from . import db
    return set(db.get_setting("mail_accounts_off", []))


def _hide(op, res, off):
    if op == "read" and isinstance(res, dict) and res.get("accountId") in off:
        raise RuntimeError("Reading this mail account is switched off (Mail → + Add account).")
    if isinstance(res, list):
        return [x for x in res if not (isinstance(x, dict) and (x.get("accountId") in off or (op == "accounts" and x.get("id") in off)))]
    return res


def _thunderbird(op, timeout, autostart, args):
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


def _route(args):
    """direct / thunderbird: where the message, folder or account in this request lives. None: it isn't about one."""
    ids = args.get("ids") or ([args["id"]] if args.get("id") is not None else [])
    if ids:
        ours = [maildirect.is_our_message(i) for i in ids]
        if all(ours):
            return "direct"
        if not any(ours):
            return "thunderbird"
        raise RuntimeError("These messages are in differently connected accounts: change them one account at a time.")
    if args.get("replyTo") is not None:
        return "direct" if maildirect.is_our_message(args["replyTo"]) else "thunderbird"
    for key in ("folderId", "parentId", "accountId"):
        if args.get(key):
            return "direct" if maildirect.is_ours(args[key]) else "thunderbird"
    return None


def call(op, timeout=120, autostart=True, all_accounts=False, **args):
    """all_accounts: also the accounts you switched off (only for the list where you switch them). Each account is
    connected either through Thunderbird or directly (maildirect.py); a request goes to the one that has it."""
    route = _route(args)
    both = thunderbird_set_up() and maildirect.has_accounts()
    if route is None and op in ("draft", "send"):  # no account named: the first one
        route = "direct" if maildirect.has_accounts() else "thunderbird"
    if route is None and not both:
        route = "direct" if maildirect.has_accounts() else "thunderbird"
    if route == "direct":
        result = maildirect.call(op, **args)
    elif route == "thunderbird":
        result = _thunderbird(op, timeout, autostart, args)
    else:  # about everything: both ways together. Thunderbird being closed doesn't hide the direct accounts.
        result = maildirect.call(op, **args)
        if op != "ping" and isinstance(result, list):
            try:
                result = _thunderbird(op, timeout, autostart, args) + result
            except (NotRunning, RuntimeError, OSError) as e:
                print("mail: only the direct accounts:", str(e)[:120], flush=True)
    off = set() if all_accounts else accounts_off()
    return _hide(op, result, off) if off else result


def status():
    try:
        if maildirect.has_accounts():
            return {"connected": True, "accounts": call("accounts", timeout=10, all_accounts=True), "off": sorted(accounts_off())}
        return {"connected": call("ping", timeout=5) == "pong", "accounts": call("accounts", timeout=10, all_accounts=True),
                "off": sorted(accounts_off())}
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
