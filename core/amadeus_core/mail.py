"""Your mail, through the accounts connected directly with each provider (maildirect.py: IMAP to read and organize,
SMTP or Microsoft Graph to send). This is the one door the rest of Amadeus uses: it hides accounts you switched off and
adds what's built from several requests (what's new, what's unread)."""
from . import maildirect


class NotRunning(RuntimeError):
    """Mail can't be reached right now."""


def configured():
    """Mail is optional: on once at least one account is connected (Mail → + Add account)."""
    return maildirect.has_accounts()


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


def call(op, all_accounts=False, **args):
    """One mail operation (maildirect.OPS). all_accounts: also the accounts you switched off (only for the list where
    you switch them)."""
    if not configured() and op != "ping":
        raise NotRunning("No mail account is connected yet. Add one on the Mail page.")
    result = maildirect.call(op, **args)
    off = set() if all_accounts else accounts_off()
    return _hide(op, result, off) if off else result


def status():
    if not configured():
        return {"connected": False, "accounts": [], "off": []}
    try:
        return {"connected": True, "accounts": call("accounts", all_accounts=True), "off": sorted(accounts_off())}
    except Exception as e:
        return {"connected": False, "error": str(e), "accounts": []}


SKIP_USES = ("trash", "sent", "drafts", "templates", "outbox")


def new_recent(days, limit=60):
    """Mail that ARRIVED in the last `days`, read or not (you may have opened it on your phone already): the inbox
    and junk of every account, plus any folder that has unread mail (server-side filters file mail there)."""
    folders = [f for f in call("folders")
               if not any(u in SKIP_USES for u in f.get("specialUse", []))
               and (set(f.get("specialUse", [])) & {"inbox", "junk"} or (f.get("unread") or 0) > 0)]
    out = []
    for f in folders:
        for m in call("recent", folderId=f["id"], days=days, limit=limit, unreadOnly=False):
            m["folder"] = m.get("folder") or f["path"]
            m["folderId"] = m.get("folderId") or f["id"]
            out.append(m)
    out.sort(key=lambda m: m.get("date") or "", reverse=True)
    return out[:limit]


def unread_recent(days, limit=50, account_id=""):
    """Newest unread mail of the last `days` days (may be a fraction) across every folder except trash/sent/drafts.
    Returns (mails newest first, total unread count in those folders)."""
    folders = [f for f in call("folders", accountId=account_id)
               if not any(u in SKIP_USES for u in f.get("specialUse", []))]
    total = sum(f.get("unread") or 0 for f in folders)
    out = []
    for f in folders:
        if f.get("unread") == 0:
            continue
        for m in call("recent", folderId=f["id"], days=days, limit=limit, unreadOnly=True):
            m["folder"] = m.get("folder") or f["path"]
            out.append(m)
    out.sort(key=lambda m: m.get("date") or "", reverse=True)
    return out[:limit], total
