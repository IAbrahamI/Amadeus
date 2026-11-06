"""What differs between the systems Amadeus runs on: its services, notifications, and opening apps and pages. Everything
else in the core just calls this. Where the data lives is in paths.py."""
import glob
import os
import plistlib
import re
import subprocess
import sys
import threading
import time

MAC = sys.platform == "darwin"


def _label(service):
    """amadeus-core → com.amadeus.core, the name it has in launchd."""
    return "com.amadeus." + service.removeprefix("amadeus-")


def restart(*services):
    if MAC:
        for s in services:
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{_label(s)}"], capture_output=True, timeout=60)
    else:
        subprocess.run(["systemctl", "--user", "restart", *services], capture_output=True, timeout=60)


def install_agent(service, args, needs=None):
    """A background service on a Mac: it starts at login, and again if it stops. Replaces the one of that name."""
    label = _label(service)
    plist = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
    logs = os.path.expanduser("~/Library/Logs/Amadeus")
    os.makedirs(os.path.dirname(plist), exist_ok=True)
    os.makedirs(logs, exist_ok=True)
    with open(plist, "wb") as f:
        plistlib.dump({"Label": label, "AssociatedBundleIdentifiers": ["com.amadeus.desktop"], "ProgramArguments": list(args), "RunAtLoad": True, "KeepAlive": {"PathState": {needs or args[0]: True}}, "LimitLoadToSessionType": "Aqua",
                       "EnvironmentVariables": {"PYTHONDONTWRITEBYTECODE": "1", "PATH": os.path.expanduser("~/.local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
                       "StandardOutPath": os.path.join(logs, service + ".log"), "StandardErrorPath": os.path.join(logs, service + ".log")}, f)
    target = f"gui/{os.getuid()}"
    subprocess.run(["/bin/launchctl", "bootout", f"{target}/{label}"], capture_output=True, timeout=30)
    subprocess.run(["/bin/launchctl", "bootstrap", target, plist], capture_output=True, timeout=30, check=True)


def stop_with_app():
    """On a Mac you remove an app by dragging it to the Trash, and nothing tells its services. So they notice themselves."""
    def watch():
        while os.path.exists(sys.executable):
            time.sleep(5)
        os._exit(0)
    if MAC:
        threading.Thread(target=watch, daemon=True).start()


def open_terminal(command):
    """A command in a Terminal window you can see, on a Mac. A .command file opens there without any extra permission."""
    from . import paths
    script = os.path.join(paths.DATA, "amadeus-terminal.command")
    with open(script, "w") as f:
        f.write("#!/bin/zsh -l\n" + command + "\n")
    os.chmod(script, 0o700)
    subprocess.run(["/usr/bin/open", script], capture_output=True, timeout=20, check=True)


def notify(title, text):
    if MAC:  # through the app, so it's Amadeus' notification (one from osascript opens Script Editor when you click it)
        from . import desktop
        desktop.send({"do": "notify", "data": {"title": title, "text": text}})
    else:
        subprocess.run(["notify-send", "-a", title, title, text], timeout=10)


def launch(cmd, name="app"):
    """Start a program so that it belongs to your session, not to Amadeus: restarting Amadeus never closes it
    (Thunderbird used to die with every restart)."""
    if MAC:
        subprocess.Popen(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    from .config import desktop_env
    desktop_env()  # Amadeus may have started before the desktop: apps need its display
    unit = f"amadeus-app-{re.sub(r'[^a-z0-9]', '', name.lower())[:20]}-{int(time.time())}"
    subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={unit}", "--"] + list(cmd),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def in_background(cmd):
    """A command that may restart Amadeus itself, so it runs apart from this process."""
    if MAC:
        subprocess.Popen(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        subprocess.Popen(["systemd-run", "--user", "--collect", *cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def page_command(url, browser_cmd=None):
    """How to open a web page: in a named browser (Linux command), or the default one."""
    if MAC:
        names = {"firefox": "Firefox", "brave": "Brave Browser", "chromium": "Chromium"}
        name = names.get((browser_cmd or [""])[0])
        return ["open", "-a", name, url] if name else ["open", url]
    return (browser_cmd or ["xdg-open"]) + [url]


def mac_apps():
    """The apps in the Applications folders: {name: {name, generic, keywords}}."""
    apps = {}
    for d in ("/Applications", "/System/Applications", "/System/Applications/Utilities", os.path.expanduser("~/Applications")):
        for f in sorted(glob.glob(os.path.join(d, "*.app"))):
            n = os.path.basename(f)[:-4]
            apps[n] = {"name": n, "generic": "", "keywords": ""}
    return apps


def service_timers():
    """Whether scheduled jobs here run as systemd timers, which can be asked how they went."""
    return not MAC
