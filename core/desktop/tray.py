#!/usr/bin/env python3
"""Amadeus icon in the system tray (taskbar): the "dot shell" in the theme's main colour, with an amber dot that
beats while something waits for you and a dimmed, slashed look when the microphone is off. Left click shows or hides
the mini core; right click has the dashboard, approvals (with how many are waiting) and reminders. At login it opens
the mini core (unless you closed it). Runs as the systemd user service amadeus-tray."""
import json
import os
import signal
import subprocess
import sys
import urllib.request

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.expanduser("~/.config/amadeus-core/config.json")
cfg = json.load(open(CFG_FILE)) if os.path.exists(CFG_FILE) else {}
DATA = cfg.get("data_dir", os.path.expanduser("~/.local/share/amadeus/core"))
BASE = f"http://127.0.0.1:{cfg.get('port', 8095)}"
POPUP = os.path.join(HERE, "popup.py")
TRAY = os.path.join(os.path.dirname(HERE), "web", "tray")  # the dot shell icons (24 x 24 SVG)
THEME = {"blue": "#5FD8FF", "purple": "#B68CFF", "red": "#FF5260"}  # the main colour of each theme (web/themes.js)


def icon(state="normal", theme="blue"):
    """The tray icon for a state (normal, call, speaking, voice-off) in the theme's colour, sharp at every size."""
    name = {"call": "amadeus-tray-call.svg", "speaking": "amadeus-tray-speaking.svg", "voice-off": "amadeus-tray-voice-off.svg"}.get(state, "amadeus-tray.svg")
    svg = open(os.path.join(TRAY, name), "rb").read().replace(b"#5FD8FF", THEME.get(theme, THEME["blue"]).encode())
    ic = QIcon()
    for px in (16, 22, 24, 32, 48, 64):
        pm = QPixmap()
        pm.loadFromData(svg.replace(b'width="24" height="24"', f'width="{px}" height="{px}"'.encode()), "SVG")
        ic.addPixmap(pm)
    return ic


def _alive(pid):
    """Running and really our window (not a finished "zombie" process or a reused pid)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            state = f.read().rsplit(")", 1)[1].split()[0]
        return state not in ("Z", "X") and "popup.py" in open(f"/proc/{pid}/cmdline").read()
    except (OSError, IndexError):
        return False


def window_pid():
    try:
        pid = int(open(os.path.join(DATA, "popup.pid")).read())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def open_mini():  # show the mini core (start it if it isn't running)
    pid = window_pid()
    if pid:
        with open(os.path.join(DATA, "popup.mini"), "w") as f:
            f.write("show")
        os.kill(pid, signal.SIGUSR1)
    else:
        subprocess.Popen([sys.executable, POPUP, "--mini"], start_new_session=True)


def toggle_mini():  # the tray click: show or hide the mini core
    pid = window_pid()
    if pid:
        with open(os.path.join(DATA, "popup.mini"), "w") as f:
            f.write("toggle")
        os.kill(pid, signal.SIGUSR1)
    else:
        subprocess.Popen([sys.executable, POPUP, "--mini"], start_new_session=True)


def open_dashboard(target="/#home"):
    pid = window_pid()
    if pid:
        with open(os.path.join(DATA, "popup.cmd"), "w") as f:
            f.write(target)
        os.kill(pid, signal.SIGUSR2)
    else:
        subprocess.Popen([sys.executable, POPUP, target], start_new_session=True)


def get(path):
    token = open(os.path.join(DATA, "token")).read().strip()
    req = urllib.request.Request(BASE + path, headers={"authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req, timeout=5))


def pending():
    try:
        return len(get("/api/approvals?status=pending"))
    except Exception:
        return None  # Amadeus Core is not running


def main():
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # windows we start are cleaned up when they close
    app = QApplication(sys.argv)
    app.setApplicationName("Amadeus")
    app.setDesktopFileName("amadeus")
    app.setQuitOnLastWindowClosed(False)
    look = {"theme": "blue", "state": "normal", "waits": False, "beat": False}
    tray = QSystemTrayIcon(icon(), app)

    menu = QMenu()
    talk = QAction("Show or hide the core", menu, triggered=toggle_mini)
    dash = QAction("Open dashboard", menu, triggered=lambda: open_dashboard("/#home"))
    appr = QAction("Approvals", menu, triggered=lambda: open_dashboard("/#approvals"))
    rem = QAction("Reminders", menu, triggered=lambda: open_dashboard("/#reminders"))
    quit_ = QAction("Hide tray icon", menu, triggered=app.quit)
    off_file = os.path.join(DATA, "wake-off")
    wake = QAction("Wake word (\"Amadeus\")", menu, checkable=True)
    wake.setChecked(not os.path.exists(off_file))

    def toggle_wake(on):
        if on:
            if os.path.exists(off_file):
                os.remove(off_file)
        else:
            open(off_file, "w").close()
    wake.toggled.connect(toggle_wake)
    for a in (talk, dash, appr, rem):
        menu.addAction(a)
    menu.addSeparator()
    menu.addAction(wake)
    menu.addSeparator()
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: toggle_mini() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def paint():  # the amber dot beats while something waits for you
        if look["state"] == "voice-off":
            st = "voice-off"
        else:
            look["beat"] = not look["beat"] if look["waits"] else False
            st = "call" if look["waits"] and look["beat"] else "normal"
        if (st, look["theme"]) != look.get("shown"):
            look["shown"] = (st, look["theme"])
            tray.setIcon(icon(st, look["theme"]))
    beat = QTimer(app, timeout=paint)
    beat.start(950)

    def refresh():
        wake.blockSignals(True)  # the wake word may have been switched by voice/chat ("voice off")
        wake.setChecked(not os.path.exists(off_file))
        wake.blockSignals(False)
        try:
            look["theme"] = get("/api/theme").get("theme", "blue")
            look["waits"] = bool(get("/api/events"))
        except Exception:
            pass
        look["state"] = "voice-off" if os.path.exists(off_file) else "normal"
        paint()
        n = pending()
        if n is None:
            tray.setToolTip("Amadeus is not running")
            appr.setText("Approvals")
        else:
            tray.setToolTip(f"Amadeus · {n} waiting for your approval" if n else "Amadeus")
            appr.setText(f"Approvals ({n} waiting)" if n else "Approvals")
    refresh()
    timer = QTimer(app, timeout=refresh)
    timer.start(5000)
    tray.show()
    if not os.path.exists(os.path.join(DATA, "mini-hidden")):  # at login: the mini core is there (unless you closed it)
        QTimer.singleShot(4000, open_mini)
    signal.signal(signal.SIGTERM, lambda *a: app.quit())
    signal.signal(signal.SIGINT, lambda *a: app.quit())
    sys.exit(app.exec())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--open"]:  # used by the `amadeus` launcher: open (or switch) the desktop window
        open_dashboard(sys.argv[2] if len(sys.argv) > 2 else "/#home")
    else:
        main()
