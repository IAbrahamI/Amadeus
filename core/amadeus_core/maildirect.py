"""Mail directly with the provider, without Thunderbird: IMAP to read and organize, SMTP (or Microsoft Graph for Outlook) to
send. The same operations and shapes as the Thunderbird bridge, so everything above doesn't care which way an account
is connected. Logins live only in the secrets folder (mode 600), are never returned to the page or the model, and are
sent only to that account's own server."""
import base64
import datetime
import email
import email.message
import email.policy
import email.utils
import html
import imaplib
import json
import os
import re
import smtplib
import ssl
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import db
from .config import CFG

ACCOUNTS_FILE = os.path.join(CFG["secrets_dir"], "mail-accounts.json")
ID_BASE = 1_000_000_000_000  # message ids from here on are ours; Thunderbird's are far smaller
MAX_BODY = 20000
TIMEOUT = 30
MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"
MS_IMAP = "https://outlook.office.com/IMAP.AccessAsUser.All"
MS_SEND = "https://graph.microsoft.com/Mail.Send"

# How to reach the big providers. "how" is shown when you add an account.
PROVIDERS = {
    "gmail": {"name": "Gmail", "imap": ("imap.gmail.com", 993, "ssl"), "smtp": ("smtp.gmail.com", 465, "ssl"), "auth": "password",
              "how": "Needs an app password: turn on 2-Step Verification, then create one at myaccount.google.com/apppasswords. Work accounts (Workspace) don't offer these: use Thunderbird for those.",
              "link": "https://myaccount.google.com/apppasswords", "saves_sent": True},
    "outlook": {"name": "Outlook / Hotmail", "imap": ("outlook.office365.com", 993, "ssl"), "smtp": None, "auth": "microsoft",
                "how": "Sign in with Microsoft in your browser. Your password never reaches Amadeus. Some work accounts need their admin to allow this.", "saves_sent": True},
    "yahoo": {"name": "Yahoo", "imap": ("imap.mail.yahoo.com", 993, "ssl"), "smtp": ("smtp.mail.yahoo.com", 465, "ssl"), "auth": "password",
              "how": "Needs an app password: Yahoo Account Security → Generate app password.", "link": "https://login.yahoo.com/account/security"},
    "icloud": {"name": "iCloud", "imap": ("imap.mail.me.com", 993, "ssl"), "smtp": ("smtp.mail.me.com", 587, "starttls"), "auth": "password",
               "how": "Needs an app-specific password: account.apple.com → Sign-In and Security → App-Specific Passwords.", "link": "https://account.apple.com"},
    "proton": {"name": "Proton Mail", "imap": ("127.0.0.1", 1143, "starttls"), "smtp": ("127.0.0.1", 1025, "starttls"), "auth": "password",
               "how": "Needs Proton Mail Bridge running on this PC, which Proton only offers on paid plans. Use the address and password Bridge shows, not your Proton password. Free Proton accounts can't connect any other way.",
               "link": "https://proton.me/mail/bridge", "local": True},
    "gmx": {"name": "GMX", "imap": ("imap.gmx.net", 993, "ssl"), "smtp": ("mail.gmx.net", 465, "ssl"), "auth": "password",
            "how": "Turn on POP3/IMAP access in GMX's mail settings first, then use your GMX password or an app password."},
    "webde": {"name": "WEB.DE", "imap": ("imap.web.de", 993, "ssl"), "smtp": ("smtp.web.de", 587, "starttls"), "auth": "password",
              "how": "Turn on POP3/IMAP access in WEB.DE's mail settings first, then use your password or an app password."},
    "fastmail": {"name": "Fastmail", "imap": ("imap.fastmail.com", 993, "ssl"), "smtp": ("smtp.fastmail.com", 465, "ssl"), "auth": "password",
                 "how": "Needs an app password: Settings → Privacy & Security → App passwords."},
    "zoho": {"name": "Zoho", "imap": ("imap.zoho.com", 993, "ssl"), "smtp": ("smtp.zoho.com", 465, "ssl"), "auth": "password",
             "how": "Turn on IMAP in Zoho's mail settings, and use an app password if you have 2-factor sign-in."},
    "other": {"name": "Other (IMAP)", "imap": None, "smtp": None, "auth": "password", "how": "Your provider's IMAP and SMTP servers, from its help pages."},
}
_lock = threading.RLock()
_conns = {}


# ---------- the accounts ----------
def _load():
    try:
        return json.loads(Path(ACCOUNTS_FILE).read_text())
    except (OSError, ValueError):
        return []


def _save(accounts):
    os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
    fd = os.open(ACCOUNTS_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(accounts, f, indent=1)
    os.replace(ACCOUNTS_FILE + ".tmp", ACCOUNTS_FILE)


def has_accounts():
    return bool(_load())


def is_ours(account_id):
    return str(account_id or "").startswith("d:")


def listing():
    """For the page: never a password or token."""
    return [{"id": a["id"], "email": a["email"], "provider": a.get("provider", "other"),
             "providerName": PROVIDERS.get(a.get("provider"), PROVIDERS["other"])["name"]} for a in _load()]


def _account(account_id):
    for a in _load():
        if a["id"] == account_id:
            return a
    raise RuntimeError("That mail account isn't connected any more.")


def _server(value, what):
    """Host, port, security from what you typed for a custom server."""
    host, port, sec = str(value.get("host", "")).strip(), int(value.get("port") or 0), value.get("security", "ssl")
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,253}", host) or not 0 < port < 65536 or sec not in ("ssl", "starttls"):
        raise ValueError(f"The {what} server settings don't look right.")
    return (host, port, sec)


def add_account(provider, address, password, imap_server=None, smtp_server=None):
    """Tries the login before anything is saved."""
    p = PROVIDERS.get(provider)
    address = str(address or "").strip()
    if not p or p["auth"] != "password":
        raise ValueError("Pick a provider first.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+|[^\s]{1,200}", address) or not password:
        raise ValueError("Fill in the address and the password.")
    imap = p["imap"] or _server(imap_server or {}, "IMAP")
    smtp = p["smtp"] or _server(smtp_server or {}, "SMTP")
    acc = {"id": "d:" + db.new_id()[:10], "email": address, "provider": provider, "imap": list(imap), "smtp": list(smtp),
           "auth": "password", "password": password}
    _test(acc)
    with _lock:
        rest = [a for a in _load() if a["email"].lower() != address.lower()]
        _save(rest + [acc])
    return {"id": acc["id"], "email": address}


def remove_account(account_id):
    """Forgets the login. Your mail stays where it is, at your provider."""
    with _lock:
        _close(account_id)
        _save([a for a in _load() if a["id"] != account_id])
    return {"ok": True}


def _test(acc):
    try:
        conn = _open_imap(acc)
        conn.logout()
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
        raise ValueError(f"Couldn't sign in to {acc['imap'][0]}: {_clean(e, acc)}") from None
    if acc.get("auth") == "password":
        try:
            _open_smtp(acc).quit()
        except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
            raise ValueError(f"Reading works, but sending through {acc['smtp'][0]} doesn't: {_clean(e, acc)}") from None


def _clean(e, acc):
    """An error message without anything secret in it."""
    text = str(e)
    for k in ("password", "access", "refresh"):
        if acc.get(k):
            text = text.replace(acc[k], "***")
    return text[:200]


# ---------- Microsoft sign-in (browser, PKCE): your password never reaches Amadeus ----------
_pending = {}


def ms_client_id():
    return CFG.get("ms_client_id", "")


def ms_redirect():
    return f"http://localhost:{CFG['port']}/mail/oauth"


def ms_start():
    import hashlib
    import secrets
    cid = ms_client_id()
    if not cid:
        raise ValueError("Signing in with Microsoft isn't set up in this version yet.")
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    _pending[state] = {"verifier": verifier, "at": time.time()}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return MS_AUTH + "/authorize?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": ms_redirect(), "response_mode": "query", "state": state,
        "scope": f"{MS_IMAP} offline_access openid email", "extra_scope_to_consent": MS_SEND, "prompt": "select_account",
        "code_challenge": challenge, "code_challenge_method": "S256"})


def _ms_token(fields):
    req = urllib.request.Request(MS_AUTH + "/token", urllib.parse.urlencode({"client_id": ms_client_id(), **fields}).encode(),
                                 {"content-type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def ms_finish(state, code):
    """Back from the browser: only with the state this PC started."""
    p = _pending.pop(state, None)
    if not p or time.time() - p["at"] > 600:
        raise ValueError("That sign-in has expired. Try again from Amadeus.")
    t = _ms_token({"grant_type": "authorization_code", "code": code, "redirect_uri": ms_redirect(), "code_verifier": p["verifier"],
                   "scope": f"{MS_IMAP} offline_access"})
    claims = json.loads(base64.urlsafe_b64decode(t["id_token"].split(".")[1] + "==")) if t.get("id_token") else {}
    address = claims.get("email") or claims.get("preferred_username") or ""
    if not address:
        raise ValueError("Microsoft didn't say which address this is.")
    acc = {"id": "d:" + db.new_id()[:10], "email": address, "provider": "outlook", "imap": list(PROVIDERS["outlook"]["imap"]), "smtp": [],
           "auth": "microsoft", "refresh": t["refresh_token"], "access": t["access_token"], "expires": time.time() + int(t.get("expires_in", 3000))}
    _test(acc)
    with _lock:
        _save([a for a in _load() if a["email"].lower() != address.lower()] + [acc])
    return {"id": acc["id"], "email": address}


def _ms_access(acc, scope=MS_IMAP):
    """A fresh token for reading (kept), or for sending (asked for when it's needed)."""
    if scope == MS_IMAP and acc.get("access") and time.time() < acc.get("expires", 0) - 120:
        return acc["access"]
    t = _ms_token({"grant_type": "refresh_token", "refresh_token": acc["refresh"], "scope": f"{scope} offline_access"})
    with _lock:
        accounts = _load()
        for a in accounts:
            if a["id"] == acc["id"]:
                a["refresh"] = t.get("refresh_token", a["refresh"])
                acc["refresh"] = a["refresh"]
                if scope == MS_IMAP:
                    a["access"], a["expires"] = t["access_token"], time.time() + int(t.get("expires_in", 3000))
                    acc["access"], acc["expires"] = a["access"], a["expires"]
        _save(accounts)
    return t["access_token"]


# ---------- connections ----------
def _context():
    return ssl.create_default_context()


def _open_imap(acc):
    host, port, sec = acc["imap"]
    local = host in ("127.0.0.1", "localhost")  # Proton Bridge: a certificate of its own, on this PC only
    ctx = _context()
    if local:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if sec == "ssl":
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=TIMEOUT)
    else:
        conn = imaplib.IMAP4(host, port, timeout=TIMEOUT)
        conn.starttls(ssl_context=ctx)
    if acc.get("auth") == "microsoft":
        token = _ms_access(acc)
        conn.authenticate("XOAUTH2", lambda _: f"user={acc['email']}\x01auth=Bearer {token}\x01\x01".encode())
    else:
        conn.login(acc["email"], acc["password"])
    conn.socket().settimeout(TIMEOUT)
    return conn


def _open_smtp(acc):
    host, port, sec = acc["smtp"]
    ctx = _context()
    if host in ("127.0.0.1", "localhost"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if sec == "ssl":
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=TIMEOUT)
    else:
        s = smtplib.SMTP(host, port, timeout=TIMEOUT)
        s.starttls(context=ctx)
    s.login(acc["email"], acc["password"])
    return s


def _close(account_id):
    conn = _conns.pop(account_id, None)
    if conn:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError, ssl.SSLError):
            pass


def _imap(acc):
    conn = _conns.get(acc["id"])
    if conn:
        try:
            conn.noop()
            return conn
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError, ssl.SSLError):
            _conns.pop(acc["id"], None)
    conn = _conns[acc["id"]] = _open_imap(acc)
    return conn


# ---------- ids: Amadeus uses whole numbers for messages, IMAP (mailbox, UID) ----------
db.q("CREATE TABLE IF NOT EXISTS mail_ids (id INTEGER PRIMARY KEY, account TEXT, folder TEXT, uid INTEGER, UNIQUE(account, folder, uid))")


def is_our_message(message_id):
    try:
        return int(message_id) >= ID_BASE
    except (TypeError, ValueError):
        return False


def _id(account, folder, uid):
    row = db.q("SELECT id FROM mail_ids WHERE account=? AND folder=? AND uid=?", (account, folder, uid), one=True)
    if row:
        return row["id"]
    top = db.q("SELECT MAX(id) AS m FROM mail_ids", one=True)
    new = max(int(top["m"] or 0) + 1, ID_BASE)
    db.q("INSERT INTO mail_ids(id,account,folder,uid) VALUES(?,?,?,?)", (new, account, folder, uid))
    return new


def _where(message_id):
    row = db.q("SELECT account,folder,uid FROM mail_ids WHERE id=?", (int(message_id),), one=True)
    if not row:
        raise RuntimeError("That message isn't known any more.")
    return row["account"], row["folder"], row["uid"]


def _folder_id(account, mailbox):
    return f"{account}|{mailbox}"


def _split_folder(folder_id):
    account, _, mailbox = str(folder_id).partition("|")
    return account, mailbox


def _q(mailbox):
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _select(conn, mailbox, readonly=True):
    typ, data = conn.select(_q(mailbox), readonly=readonly)
    if typ != "OK":
        raise RuntimeError(f"Couldn't open the folder {_name(mailbox)}.")
    return data


def _name(mailbox):
    """Folder names travel in a modified UTF-7."""
    def dec(m):
        s = m.group(1)
        if not s:
            return "&"
        try:
            return base64.b64decode(s.replace(",", "/") + "=" * (-len(s) % 4)).decode("utf-16-be")
        except ValueError:
            return m.group(0)
    return re.sub(r"&([^-]*)-", dec, mailbox)


# ---------- folders ----------
USES = {"\\inbox": "inbox", "\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash", "\\junk": "junk", "\\archive": "archives", "\\all": "all"}
BY_NAME = {"inbox": "inbox", "sent": "sent", "sent items": "sent", "sent mail": "sent", "gesendet": "sent", "drafts": "drafts", "entwürfe": "drafts",
           "trash": "trash", "deleted items": "trash", "deleted messages": "trash", "papierkorb": "trash", "bin": "trash", "junk": "junk", "spam": "junk",
           "junk email": "junk", "bulk mail": "junk", "archive": "archives", "archiv": "archives"}


def _list(conn):
    typ, data = conn.list()
    out = []
    for raw in data if typ == "OK" else []:
        line = raw[0].decode("utf-8", "replace") if isinstance(raw, tuple) else raw.decode("utf-8", "replace") if raw else ""
        m = re.match(r'\((.*?)\)\s+("(?:[^"\\]|\\.)*"|NIL)\s+(.*)$', line)
        if not m or "\\noselect" in m.group(1).lower():
            continue
        name = m.group(3).strip()
        name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\") if name.startswith('"') else name
        flags = m.group(1).lower().split()
        use = next((USES[f] for f in flags if f in USES), None)
        short = _name(name).rsplit(m.group(2).strip('"') or "/", 1)[-1].lower() if m.group(2) != "NIL" else _name(name).lower()
        if name.upper() == "INBOX":
            use = "inbox"
        out.append({"mailbox": name, "use": use or BY_NAME.get(short)})
    return out


def _find(conn, use):
    return next((f["mailbox"] for f in _list(conn) if f["use"] == use), None)


def op_folders(accountId="", **_):
    out = []
    for acc in _targets(accountId):
        with _lock:
            conn = _imap(acc)
            for f in _list(conn):
                unread, total = None, None
                try:
                    typ, data = conn.status(_q(f["mailbox"]), "(MESSAGES UNSEEN)")
                    if typ == "OK":
                        text = data[0].decode("utf-8", "replace")
                        total = int(re.search(r"MESSAGES (\d+)", text).group(1))
                        unread = int(re.search(r"UNSEEN (\d+)", text).group(1))
                except (imaplib.IMAP4.error, AttributeError):
                    pass
                out.append({"id": _folder_id(acc["id"], f["mailbox"]), "accountId": acc["id"], "name": _name(f["mailbox"]).split("/")[-1],
                            "path": "/" + _name(f["mailbox"]), "specialUse": [f["use"]] if f["use"] else [], "unread": unread, "total": total})
    return out


def _targets(account_id):
    if account_id:
        return [_account(account_id)]
    return _load()


# ---------- messages ----------
FIELDS = "(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (DATE FROM TO CC SUBJECT MESSAGE-ID)])"


def _decode(value):
    return str(email.message_from_string(f"X: {value or ''}", policy=email.policy.default)["X"] or "").strip() if value else ""


def _addresses(value):
    return [a for a in (x.strip() for x in re.split(r",\s*(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", _decode(value))) if a]


def _iso(value, fallback=None):
    try:
        d = email.utils.parsedate_to_datetime(value)
        return d.astimezone(datetime.timezone.utc).isoformat()
    except (TypeError, ValueError, AttributeError):
        return fallback


def _fetch_headers(acc, conn, mailbox, uids):
    out = []
    if not uids:
        return out
    typ, data = conn.uid("FETCH", ",".join(str(u) for u in uids), FIELDS)
    for item in data if typ == "OK" else []:
        if not isinstance(item, tuple):
            continue
        meta = item[0].decode("utf-8", "replace")
        uid = re.search(r"UID (\d+)", meta)
        if not uid:
            continue
        flags = (re.search(r"FLAGS \((.*?)\)", meta) or [None, ""])[1].lower()
        when = re.search(r'INTERNALDATE "([^"]+)"', meta)
        h = email.message_from_bytes(item[1], policy=email.policy.compat32)
        received = None
        if when:
            try:
                received = datetime.datetime.strptime(when.group(1), "%d-%b-%Y %H:%M:%S %z").astimezone(datetime.timezone.utc).isoformat()
            except ValueError:
                pass
        out.append({"id": _id(acc["id"], mailbox, int(uid.group(1))), "messageId": (h["Message-ID"] or "").strip("<> \r\n"),
                    "date": _iso(h["Date"], received) or received, "from": _decode(h["From"]), "to": _addresses(h["To"]), "cc": _addresses(h["Cc"]),
                    "subject": _decode(h["Subject"]), "read": "\\seen" in flags, "flagged": "\\flagged" in flags,
                    "folder": "/" + _name(mailbox), "folderId": _folder_id(acc["id"], mailbox), "accountId": acc["id"]})
    return out


def _since(days):
    d = datetime.datetime.now() - datetime.timedelta(days=float(days))
    return f"{d.day:02d}-{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.month - 1]}-{d.year}"


def _search(conn, *criteria):
    typ, data = conn.uid("SEARCH", None, *criteria)
    return [int(x) for x in data[0].split()] if typ == "OK" and data and data[0] else []


def _sorted(out, limit):
    return sorted(out, key=lambda m: m.get("date") or "", reverse=True)[:limit]


def op_recent(accountId="", folderId=None, days=2, limit=30, unreadOnly=False, **_):
    out = []
    where = [_split_folder(folderId)] if folderId else [(a["id"], "INBOX") for a in _targets(accountId)]
    for account, mailbox in where:
        acc = _account(account)
        with _lock:
            conn = _imap(acc)
            _select(conn, mailbox)
            uids = _search(conn, "SINCE", _since(days), *(["UNSEEN"] if unreadOnly else []))
            out += _fetch_headers(acc, conn, mailbox, uids[-int(limit):])
    return _sorted(out, int(limit))


def op_unread(accountId="", limit=100, includeJunk=True, **_):
    out = []
    for acc in _targets(accountId):
        with _lock:
            conn = _imap(acc)
            for f in _list(conn):
                if f["use"] in ("trash", "sent", "drafts", "all") or (f["use"] == "junk" and not includeJunk):
                    continue
                _select(conn, f["mailbox"])
                out += _fetch_headers(acc, conn, f["mailbox"], _search(conn, "UNSEEN")[-int(limit):])
    return _sorted(out, int(limit))


def op_search(query="", days=90, limit=20, accountId="", **_):
    text = re.sub(r"[\r\n]+", " ", str(query)).strip()
    out = []
    if not text:
        return out
    for acc in _targets(accountId):
        with _lock:
            conn = _imap(acc)
            for f in _list(conn):
                if f["use"] in ("trash", "drafts", "all"):
                    continue
                _select(conn, f["mailbox"])
                try:
                    if text.isascii():
                        uids = _search(conn, "SINCE", _since(days), "TEXT", '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"')
                    else:
                        conn.literal = text.encode()
                        typ, data = conn.uid("SEARCH", "CHARSET", "UTF-8", "SINCE", _since(days), "TEXT")
                        uids = [int(x) for x in data[0].split()] if typ == "OK" and data and data[0] else []
                except imaplib.IMAP4.error:
                    continue
                out += _fetch_headers(acc, conn, f["mailbox"], uids[-int(limit):])
    return _sorted(out, int(limit))


def op_headers(ids=(), **_):
    out = []
    for i in ids:
        try:
            account, mailbox, uid = _where(i)
            acc = _account(account)
            with _lock:
                conn = _imap(acc)
                _select(conn, mailbox)
                got = _fetch_headers(acc, conn, mailbox, [uid])
            out += got or [{"id": i, "missing": True}]
        except (RuntimeError, imaplib.IMAP4.error):
            out.append({"id": i, "missing": True})
    return out


def _html_text(text):
    """HTML mail as readable text that keeps links, so verification and sign-in links stay usable."""
    text = re.sub(r"<(style|script)\b.*?</\1>", "", text, flags=re.S | re.I)

    def link(m):
        url, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        return label if re.match(r"(mailto:|#)", url, re.I) else (f"{label} ({url})" if label and label != url else url)
    text = re.sub(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", link, text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _body(msg):
    plain, rich = "", ""
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        try:
            if kind == "text/plain" and not plain:
                plain = part.get_content()
            elif kind == "text/html" and not rich:
                rich = part.get_content()
        except (LookupError, ValueError, KeyError):
            pass
    # plain text if there is one; but if it has no links while the HTML part does, the HTML (links kept)
    if plain and (re.search(r"https?://", plain) or not rich):
        return plain
    return _html_text(rich) if rich else plain


def _attachments(msg):
    out = []
    for n, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        name = part.get_filename()
        if part.get_content_disposition() == "attachment" or name:
            payload = part.get_payload(decode=True) or b""
            out.append({"name": name or f"attachment-{n}", "size": len(payload), "contentType": part.get_content_type(), "part": str(n)})
    return out


def _raw(message_id):
    account, mailbox, uid = _where(message_id)
    acc = _account(account)
    with _lock:
        conn = _imap(acc)
        _select(conn, mailbox)
        typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        raw = next((x[1] for x in data if isinstance(x, tuple)), None) if typ == "OK" else None
        head = _fetch_headers(acc, conn, mailbox, [uid])
    if raw is None or not head:
        raise RuntimeError("That message isn't there any more.")
    return head[0], email.message_from_bytes(raw, policy=email.policy.default), acc


def op_read(id=None, **_):
    head, msg, _acc = _raw(id)
    body = _body(msg)
    return {**head, "body": body[:MAX_BODY], "truncated": len(body) > MAX_BODY,
            "attachments": [{k: a[k] for k in ("name", "size", "contentType")} for a in _attachments(msg)]}


def op_attachments(id=None, **_):
    return _attachments(_raw(id)[1])


def op_attachment(id=None, part=None, **_):
    msg = _raw(id)[1]
    for n, p in enumerate(msg.walk()):
        if str(n) == str(part):
            data = p.get_payload(decode=True) or b""
            if len(data) > 25 * 1024 * 1024:
                raise RuntimeError("attachment larger than 25 MB")
            return {"name": p.get_filename() or f"attachment-{n}", "size": len(data), "contentType": p.get_content_type(), "data": base64.b64encode(data).decode()}
    raise RuntimeError("That attachment isn't there.")


# ---------- changing things: one account at a time, per folder ----------
def _by_folder(ids):
    groups = {}
    for i in ids:
        account, mailbox, uid = _where(i)
        groups.setdefault((account, mailbox), []).append(uid)
    return groups


def _store(ids, op, flags):
    for (account, mailbox), uids in _by_folder(ids).items():
        with _lock:
            conn = _imap(_account(account))
            _select(conn, mailbox, readonly=False)
            conn.uid("STORE", ",".join(map(str, uids)), op, flags)


def op_markRead(ids=(), read=True, **_):
    _store(ids, "+FLAGS" if read else "-FLAGS", "(\\Seen)")
    return {"updated": len(ids)}


def op_flag(ids=(), flagged=True, **_):
    _store(ids, "+FLAGS" if flagged else "-FLAGS", "(\\Flagged)")
    return {"updated": len(ids)}


def _move_uids(conn, uids, target):
    """MOVE if the server has it, else copy and remove from here. The copy comes first, so nothing can get lost."""
    joined = ",".join(map(str, uids))
    if "MOVE" in conn.capabilities:
        typ, data = conn.uid("MOVE", joined, _q(target))
        if typ != "OK":
            raise RuntimeError(f"Couldn't move it: {data}")
        return
    typ, data = conn.uid("COPY", joined, _q(target))
    if typ != "OK":
        raise RuntimeError(f"Couldn't move it: {data}")
    conn.uid("STORE", joined, "+FLAGS", "(\\Deleted)")
    conn.expunge()


def op_move(ids=(), folderId=None, **_):
    target_account, target = _split_folder(folderId)
    for (account, mailbox), uids in _by_folder(ids).items():
        if account != target_account:
            raise RuntimeError("Mail can only be moved within one account.")
        with _lock:
            conn = _imap(_account(account))
            _select(conn, mailbox, readonly=False)
            _move_uids(conn, uids, target)
    return {"moved": len(ids)}


def _to_special(ids, use, missing):
    for (account, mailbox), uids in _by_folder(ids).items():
        with _lock:
            conn = _imap(_account(account))
            target = _find(conn, use)
            if not target:
                raise RuntimeError(missing)
            if target != mailbox:
                _select(conn, mailbox, readonly=False)
                _move_uids(conn, uids, target)


def op_trash(ids=(), **_):  # into the trash only, never deleted for good
    _to_special(ids, "trash", "This account has no trash folder, so nothing was removed.")
    return {"trashed": len(ids)}


def op_junk(ids=(), junk=True, **_):
    if junk:
        _to_special(ids, "junk", "This account has no spam folder.")
    else:
        _to_special(ids, "inbox", "This account has no inbox.")
    return {"updated": len(ids)}


def op_createFolder(parentId=None, name="", **_):
    account, parent = _split_folder(parentId)
    mailbox = f"{parent}/{name}" if parent else name
    with _lock:
        conn = _imap(_account(account))
        typ, data = conn.create(_q(mailbox))
        if typ != "OK":
            raise RuntimeError(f"Couldn't create the folder: {data}")
    return {"id": _folder_id(account, mailbox), "path": "/" + mailbox, "name": name}


def op_contacts(query="", limit=10, **_):
    """There's no address book here: names and addresses from your recent mail."""
    seen, out = set(), []
    for m in op_search(query=query, days=365, limit=50):
        for who in [m.get("from", "")] + m.get("to", []):
            name, addr = email.utils.parseaddr(who)
            if addr and addr.lower() not in seen and str(query).lower() in who.lower():
                seen.add(addr.lower())
                out.append({"name": name, "emails": [addr]})
    return out[:int(limit)]


# ---------- writing and sending ----------
def _default_account(account_id):
    accounts = _targets(account_id)
    if not accounts:
        raise RuntimeError("No mail account is connected.")
    return accounts[0]


def _compose(acc, to, cc, subject, body, replyTo):
    msg = email.message.EmailMessage()
    msg["From"] = acc["email"]
    if replyTo:
        head, orig, _a = _raw(replyTo)
        to = to or orig["Reply-To"] or orig["From"]
        if not subject:
            old = head.get("subject", "")
            subject = old if old.lower().startswith("re:") else f"Re: {old}"
        if orig["Message-ID"]:
            msg["In-Reply-To"] = orig["Message-ID"]
            msg["References"] = f"{orig['References'] or ''} {orig['Message-ID']}".strip()
    for key, value in (("To", to), ("Cc", cc)):
        if value:
            msg[key] = ", ".join(value) if isinstance(value, (list, tuple)) else value
    msg["Subject"] = subject or ""
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=acc["email"].rpartition("@")[2] or "localhost")
    msg.set_content(body or "")
    return msg


def _append(acc, msg, use, flags):
    with _lock:
        conn = _imap(acc)
        target = _find(conn, use)
        if not target:
            raise RuntimeError(f"This account has no {use} folder.")
        typ, data = conn.append(_q(target), flags, imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        if typ != "OK":
            raise RuntimeError(f"Couldn't save it: {data}")


def _deliver(acc, msg):
    if acc.get("auth") == "microsoft":
        token = _ms_access(acc, MS_SEND)
        req = urllib.request.Request("https://graph.microsoft.com/v1.0/me/sendMail", base64.b64encode(msg.as_bytes()),
                                     {"authorization": f"Bearer {token}", "content-type": "text/plain"})
        urllib.request.urlopen(req, timeout=TIMEOUT).close()
        return
    with _open_smtp(acc) as s:
        s.send_message(msg)
    if not PROVIDERS.get(acc.get("provider"), {}).get("saves_sent"):
        try:  # most servers don't keep a copy of what's sent through SMTP
            _append(acc, msg, "sent", "(\\Seen)")
        except (RuntimeError, imaplib.IMAP4.error, OSError):
            pass


def op_draft(accountId="", to=None, cc=None, subject="", body="", replyTo=None, **_):
    acc = _default_account(accountId)
    msg = _compose(acc, to, cc, subject, body, replyTo)
    _append(acc, msg, "drafts", "(\\Draft \\Seen)")
    return {"saved": True, "messageId": msg["Message-ID"].strip("<>")}


def op_send(accountId="", to=None, cc=None, subject="", body="", replyTo=None, **_):
    acc = _default_account(accountId)
    msg = _compose(acc, to, cc, subject, body, replyTo)
    _deliver(acc, msg)
    return {"sent": True, "messageId": msg["Message-ID"].strip("<>")}


def op_forward(id=None, to=None, body="", accountId="", **_):
    head, orig, source = _raw(id)
    acc = _account(accountId) if accountId else source
    text = f"{body or ''}\n\n-------- Forwarded message --------\nFrom: {head.get('from', '')}\nDate: {head.get('date', '')}\nSubject: {head.get('subject', '')}\n\n{_body(orig)}"
    old = head.get("subject", "")
    msg = _compose(acc, to, None, old if old.lower().startswith("fwd:") else f"Fwd: {old}", text.strip(), None)
    for part in orig.walk():
        if not part.is_multipart() and part.get_content_disposition() == "attachment":
            maintype, _, subtype = part.get_content_type().partition("/")
            msg.add_attachment(part.get_payload(decode=True) or b"", maintype=maintype, subtype=subtype or "octet-stream", filename=part.get_filename())
    _deliver(acc, msg)
    return {"sent": True, "messageId": msg["Message-ID"].strip("<>")}


def op_accounts(**_):
    return [{"id": a["id"], "name": a["email"], "type": "imap", "identities": [{"id": a["id"], "email": a["email"], "name": ""}]} for a in _load()]


def op_ping(**_):
    return "pong"


OPS = {k[3:]: v for k, v in list(globals().items()) if k.startswith("op_")}


def call(op, **args):
    fn = OPS.get(op)
    if not fn:
        raise RuntimeError(f"unknown operation {op}")
    try:
        return fn(**args)
    except (imaplib.IMAP4.error, imaplib.IMAP4.abort, ssl.SSLError, OSError, smtplib.SMTPException) as e:
        with _lock:  # the next try starts with a fresh connection
            for a in list(_conns):
                _conns.pop(a, None)
        raise RuntimeError(f"The mail server didn't answer properly: {str(e)[:200]}") from None
