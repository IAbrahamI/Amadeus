#!/usr/bin/env python3
"""Native messaging host for the Amadeus Bridge add-on. Thunderbird starts it; it listens on a private unix socket
(~/.local/share/amadeus/core/mail.sock, mode 600) and relays each request from Amadeus Core to the add-on and back.
One request per connection: a JSON line {"op": ..., "args": {...}}, answered with one JSON line."""
import json
import os
import socket
import struct
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amadeus_core import paths  # noqa: E402
SOCK = os.path.join(paths.DATA, "mail.sock")
NEW_MAIL = os.path.join(paths.DATA, "mail-new")  # touched when Thunderbird gets new mail
_out = threading.Lock()
_waiting = {}  # request id -> [event, response]
_next = [0]


def send_native(msg):
    data = json.dumps(msg).encode()
    with _out:
        sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
        sys.stdout.buffer.flush()


def read_native():
    while True:
        head = sys.stdin.buffer.read(4)
        if len(head) < 4:
            os._exit(0)  # Thunderbird closed
        msg = json.loads(sys.stdin.buffer.read(struct.unpack("<I", head)[0]))
        if msg.get("event") == "new_mail":  # no content: Amadeus Core sees the flag and checks the new mail itself
            fd = os.open(NEW_MAIL, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, str(msg.get("count", 1)).encode())
            os.close(fd)
            continue
        slot = _waiting.get(msg.get("id"))
        if slot:
            slot[1] = msg
            slot[0].set()


def serve(conn):
    with conn:
        f = conn.makefile("rwb")
        try:
            req = json.loads(f.readline())
            _next[0] += 1
            rid = _next[0]
            slot = _waiting[rid] = [threading.Event(), None]
            send_native({"id": rid, "op": req.get("op"), "args": req.get("args") or {}})
            ok = slot[0].wait(req.get("timeout", 120))
            _waiting.pop(rid, None)
            resp = slot[1] if ok else {"ok": False, "error": "Thunderbird did not answer in time"}
        except Exception as e:
            resp = {"ok": False, "error": f"bridge error: {e}"}
        f.write((json.dumps(resp) + "\n").encode())
        f.flush()


def main():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    srv.bind(SOCK)
    os.umask(old)
    srv.listen(8)
    threading.Thread(target=read_native, daemon=True).start()
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=serve, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
