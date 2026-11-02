"""Phone notifications (Web Push) for Amadeus's calls. A push carries NO content: it only wakes the phone app, which
then fetches what's new from this PC over your private Tailscale connection. So Google's push service (which delivers
pushes to Android) never sees your mail, messages or calendar. Signed with this PC's own VAPID key."""
import base64
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from . import db
from .config import CFG

db.q("CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, sub TEXT, created REAL)")
KEY_FILE = os.path.join(CFG["data_dir"], "vapid.pem")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    if not os.path.exists(KEY_FILE):
        k = ec.generate_private_key(ec.SECP256R1())
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.close(fd)
    return serialization.load_pem_private_key(open(KEY_FILE, "rb").read(), None)


def public_key():
    from cryptography.hazmat.primitives import serialization
    return _b64(_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def _jwt(audience):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    head = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    body = _b64(json.dumps({"aud": audience, "exp": int(time.time()) + 12 * 3600, "sub": "mailto:amadeus@localhost.localdomain"}).encode())
    r, s = decode_dss_signature(_key().sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{body}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def subscribe(sub):
    if not str(sub.get("endpoint", "")).startswith("https://"):
        raise ValueError("bad subscription")
    db.q("INSERT INTO push_subs(endpoint,sub,created) VALUES(?,?,?) ON CONFLICT(endpoint) DO UPDATE SET sub=excluded.sub",
         (sub["endpoint"], json.dumps(sub), time.time()))


def _send_all():
    for row in db.q("SELECT endpoint FROM push_subs"):
        ep = row["endpoint"]
        u = urllib.parse.urlparse(ep)
        req = urllib.request.Request(ep, b"", method="POST", headers={
            "TTL": "600", "Urgency": "high", "Content-Length": "0",
            "Authorization": f"vapid t={_jwt(f'{u.scheme}://{u.netloc}')}, k={public_key()}"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):  # the phone unsubscribed or reinstalled the app
                db.q("DELETE FROM push_subs WHERE endpoint=?", (ep,))
            else:
                print("push failed:", e.code, flush=True)
        except Exception as e:
            print("push failed:", e, flush=True)


def notify():
    """Wake the phone app (no content). Runs in the background."""
    if db.q("SELECT 1 FROM push_subs LIMIT 1"):
        threading.Thread(target=_send_all, daemon=True).start()
