"""Phones paired with Amadeus. A phone reaches Amadeus only through your private Tailscale network
(https://<pc>.ts.net, via `tailscale serve`) AND with its own key, which it gets once by entering a 6-digit pairing
code shown in the dashboard. Keys are stored only as hashes and can be revoked any time."""
import hashlib
import secrets
import time

from . import db

db.q("""CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, name TEXT, key_hash TEXT, tailscale_login TEXT,
        created REAL, last_seen REAL, revoked INTEGER DEFAULT 0)""")
CODE_MINUTES = 10
MAX_TRIES = 5


def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def new_code():
    """A one-time 6-digit pairing code, shown in the dashboard (valid 10 minutes, 5 tries)."""
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.set_setting("pair_code", {"hash": _hash(code), "expires": time.time() + CODE_MINUTES * 60, "tries": 0})
    return code


def pair(code, name, tailscale_login):
    """Returns the new device key, or None. The code works once; too many wrong tries cancel it."""
    pc = db.get_setting("pair_code", {})
    if not pc or time.time() > pc.get("expires", 0) or pc.get("tries", 0) >= MAX_TRIES:
        return None
    if not secrets.compare_digest(_hash(code.strip()), pc["hash"]):
        pc["tries"] = pc.get("tries", 0) + 1
        db.set_setting("pair_code", pc)
        return None
    db.set_setting("pair_code", {})
    key = secrets.token_urlsafe(32)
    db.q("INSERT INTO devices(id,name,key_hash,tailscale_login,created,last_seen) VALUES(?,?,?,?,?,?)",
         (db.new_id(), (name or "Phone")[:60], _hash(key), tailscale_login or "", time.time(), time.time()))
    return key


def check(key, tailscale_login):
    """The device for this key (and the same Tailscale account it was paired from), or None."""
    if not key:
        return None
    d = db.q("SELECT * FROM devices WHERE key_hash=? AND revoked=0", (_hash(key),), one=True)
    if not d or (d["tailscale_login"] and d["tailscale_login"] != (tailscale_login or "")):
        return None
    if time.time() - (d["last_seen"] or 0) > 60:
        db.q("UPDATE devices SET last_seen=? WHERE id=?", (time.time(), d["id"]))
    return d


def listing():
    return db.q("SELECT id, name, tailscale_login, created, last_seen FROM devices WHERE revoked=0 ORDER BY created DESC")


def revoke(did):
    db.q("UPDATE devices SET revoked=1 WHERE id=?", (did,))
