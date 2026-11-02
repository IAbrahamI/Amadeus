#!/usr/bin/env python3
"""Amadeus icon in the system tray (taskbar). Left click: the small Amadeus window. Right click: a menu with the
dashboard, approvals (with how many are waiting) and reminders. Runs as the systemd user service amadeus-tray."""
import json
import os
import signal
import subprocess
import sys
import urllib.request

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.expanduser("~/.config/amadeus-core/config.json")
cfg = json.load(open(CFG_FILE)) if os.path.exists(CFG_FILE) else {}
DATA = cfg.get("data_dir", os.path.expanduser("~/.local/share/amadeus/core"))
BASE = f"http://127.0.0.1:{cfg.get('port', 8095)}"
POPUP = os.path.join(HERE, "popup.py")
ICON = os.path.join(os.path.dirname(HERE), "web", "logo-192.png")


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


def open_mini():
    pid = window_pid()
    if pid:
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


def pending():
    try:
        token = open(os.path.join(DATA, "token")).read().strip()
        req = urllib.request.Request(BASE + "/api/approvals?status=pending", headers={"authorization": f"Bearer {token}"})
        return len(json.load(urllib.request.urlopen(req, timeout=5)))
    except Exception:
        return None  # Amadeus Core is not running


def main():
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # windows we start are cleaned up when they close
    app = QApplication(sys.argv)
    app.setApplicationName("Amadeus")
    app.setDesktopFileName("amadeus")
    app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon(QIcon(ICON), app)

    menu = QMenu()
    talk = QAction("Talk to Amadeus", menu, triggered=open_mini)
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
    tray.activated.connect(lambda reason: open_mini() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def refresh():
        wake.blockSignals(True)  # the wake word may have been switched by voice/chat ("voice off")
        wake.setChecked(not os.path.exists(off_file))
        wake.blockSignals(False)
        n = pending()
        if n is None:
            tray.setToolTip("Amadeus is not running")
            appr.setText("Approvals")
        else:
            tray.setToolTip(f"Amadeus · {n} waiting for your approval" if n else "Amadeus")
            appr.setText(f"Approvals ({n} waiting)" if n else "Approvals")
    refresh()
    timer = QTimer(app, timeout=refresh)
    timer.start(15000)
    tray.show()
    signal.signal(signal.SIGTERM, lambda *a: app.quit())
    signal.signal(signal.SIGINT, lambda *a: app.quit())
    sys.exit(app.exec())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--open"]:  # used by the `amadeus` launcher: open (or switch) the desktop window
        open_dashboard(sys.argv[2] if len(sys.argv) > 2 else "/#home")
    else:
        main()
