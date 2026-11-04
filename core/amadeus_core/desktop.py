"""The desktop app (desktop-tauri/) waits here for what to show: a call or the wake word. It's a long-running request
to the local server instead of signals and pid files, so it works the same on every system."""
import threading
import time

_changed = threading.Condition()
_cmds = []
_seen = 0.0  # when the app last asked
_open = False
FRESH = 60  # seconds a command stays worth showing
WAIT = 25   # seconds a request waits before the app asks again


def send(cmd):
    with _changed:
        _cmds.append((time.time(), cmd))
        _changed.notify_all()


def wait(timeout=WAIT):
    """The commands waiting for the app, after at most `timeout` seconds."""
    global _seen
    with _changed:
        _seen = time.time()
        if not _cmds:
            _changed.wait(timeout)
        out = [c for t, c in _cmds if time.time() - t < FRESH]
        _cmds.clear()
        _seen = time.time()
    return out


def connected():
    """The app is running (it asks again right after each answer)."""
    return time.time() - _seen < WAIT + 15


def set_open(is_open):
    global _open
    _open = is_open


def window_open():
    return connected() and _open
