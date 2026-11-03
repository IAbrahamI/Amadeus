#!/usr/bin/env python3
"""Amadeus on the desktop: two windows in one process.
- The mini core (web/mini.html): a fully transparent, always-on-top window with only the core, bottom-right on your
  second monitor (or the only one). It speaks in bubbles and "calls" you; clicks where nothing is drawn go through
  to the desktop below. Clicking the core opens the dashboard.
- The dashboard (web/index.html): a normal window, opened from the mini core, the tray or the `amadeus` command.
On KDE Plasma a KWin script puts both in place (Wayland apps can't move themselves)."""
import json
import os
import signal
import subprocess
import sys
import time

# The page is drawn on the GPU: smooth scrolling and typing even in a big window. Drawing without it (the slow,
# CPU-only way) is only for graphics drivers where WebKit's GPU drawing crashes: "gpu_rendering": false in the config,
# or automatically after the page crashed a few times in a row (the marker file below; delete it to try the GPU again).
_cfg_file = os.path.expanduser("~/.config/amadeus-core/config.json")
_cfg = json.load(open(_cfg_file)) if os.path.exists(_cfg_file) else {}
SOFTWARE = os.path.join(_cfg.get("data_dir", os.path.expanduser("~/.local/share/amadeus/core")), "popup-software-rendering")
if _cfg.get("gpu_rendering") is False or os.path.exists(SOFTWARE):
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

cfg = _cfg
DATA = cfg.get("data_dir", os.path.expanduser("~/.local/share/amadeus/core"))
BASE = f"http://127.0.0.1:{cfg.get('port', 8095)}"
MW, MH = 300, 500  # the mini core window: the core (280 px) at the bottom, room for her speech bubbles above
CMD = os.path.join(DATA, "popup.cmd")    # target for SIGUSR2 (dashboard), written by the tray icon
MINICMD = os.path.join(DATA, "popup.mini")  # "toggle" for SIGUSR1 from the tray; otherwise SIGUSR1 = a call
HIDDEN = os.path.join(DATA, "mini-hidden")  # you closed the mini core: it only comes back for a call or the tray
ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "icon.svg")
KWIN_JS = os.path.join(DATA, "place-window.js")
KDE = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
MINI_TITLE, DASH_TITLE = "Amadeus core", "Amadeus"


def second_screen():
    """The monitor for the mini core: the one KScreen ranks second, else the only one (config "mini_screen": a name)."""
    if cfg.get("mini_screen"):
        return cfg["mini_screen"]
    try:
        out = subprocess.run(["kscreen-doctor", "-o"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    import re
    out, name, best = re.sub(r"\x1b\[[0-9;]*m", "", out), "", {}
    for line in out.splitlines():
        m = re.match(r"Output:\s+\d+\s+(\S+)", line)
        if m:
            name = m.group(1)
        m = re.search(r"priority (\d+)", line)
        if m and name:
            best[int(m.group(1))] = name
    return best.get(2) or best.get(1, "")


def kwin(js):
    """Run a short KWin script (KDE Plasma): place, keep above, hide from the taskbar."""
    with open(KWIN_JS, "w") as f:
        f.write(js)
    name = "amadeus-place-%d" % os.getpid()
    cmd = (f"qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript {name} >/dev/null 2>&1; "
           f"id=$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript '{KWIN_JS}' {name}) && "
           f"qdbus6 org.kde.KWin /Scripting/Script$id org.kde.kwin.Script.run >/dev/null; sleep 1; "
           f"qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript {name} >/dev/null 2>&1")
    try:
        subprocess.Popen(["sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def place_mini(win):
    if not KDE:  # other desktops: keep above everywhere, the corner only on X11
        win.set_keep_above(True)
        mon = Gdk.Display.get_default().get_primary_monitor()
        if mon:
            a = mon.get_workarea()
            win.move(a.x + a.width - MW - 16, a.y + a.height - MH - 16)
        return
    kwin("""const want = %s;
    for (const w of workspace.windowList()) if (w.resourceClass == "amadeus-call" && w.caption == "%s") {
      const scr = workspace.screens.find((s) => s.name == want) || w.output;
      const a = workspace.clientArea(KWin.MaximizeArea, scr, workspace.currentDesktop);
      w.keepAbove = true; w.skipTaskbar = true; w.skipSwitcher = true; w.skipPager = true;
      w.frameGeometry = { x: Math.floor(a.x + a.width - %d - 16), y: Math.floor(a.y + a.height - %d - 8), width: %d, height: %d };
    }""" % (json.dumps(second_screen()), MINI_TITLE, MW, MH, MW, MH))


def place_dash(win):
    if not KDE:
        mon = Gdk.Display.get_default().get_primary_monitor()
        a = mon.get_workarea() if mon else None
        w, h = (int(min(1500, a.width * .72)), int(min(950, a.height * .82))) if a else (1200, 800)
        win.resize(w, h)
        if a:
            win.move(a.x + (a.width - w) // 2, a.y + (a.height - h) // 2)
        return
    kwin("""for (const w of workspace.windowList()) if (w.resourceClass == "amadeus-call" && w.caption == "%s") {
      w.keepAbove = false; w.skipTaskbar = false;
      const a = workspace.clientArea(KWin.MaximizeArea, workspace.activeScreen, workspace.currentDesktop);
      const W = Math.round(Math.min(1500, a.width * 0.72)), H = Math.round(Math.min(950, a.height * 0.82));
      w.frameGeometry = { x: Math.round(a.x + (a.width - W) / 2), y: Math.round(a.y + (a.height - H) / 2), width: W, height: H };
    }""" % DASH_TITLE)


def make_view(on_msg, transparent=False):
    """A WebView for Amadeus' own pages: messages from the page, microphone allowed, links open in the browser."""
    ucm = WebKit2.UserContentManager()
    ucm.register_script_message_handler("amadeus")
    ucm.connect("script-message-received::amadeus", lambda _m, res: on_msg(res.get_js_value().to_string()))
    ucm.add_script(WebKit2.UserScript.new(  # page errors go to the log (popup.log / the tray's journal)
        "addEventListener('error',e=>console.error('JS error: '+e.message+' @'+e.lineno));"
        "addEventListener('unhandledrejection',e=>console.error('JS rejection: '+e.reason));",
        WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
    # it may speak and ring without a click first (autoplay), in these windows only
    view = WebKit2.WebView(user_content_manager=ucm, website_policies=WebKit2.WebsitePolicies(autoplay=WebKit2.AutoplayPolicy.ALLOW))
    st = view.get_settings()
    st.set_enable_write_console_messages_to_stdout(True)
    st.set_user_agent_with_application_details("AmadeusDesktop", "1")  # the server only serves these windows
    st.set_enable_media_stream(True)
    st.set_media_playback_requires_user_gesture(False)
    if transparent:
        view.set_background_color(Gdk.RGBA(0, 0, 0, 0))
    view.connect("permission-request", _permission)
    view.connect("decide-policy", _policy)
    view.connect("web-process-terminated", _crash)
    return view


def _permission(view, req):
    """Only Amadeus' own pages run here: allow the microphone, refuse everything else."""
    if isinstance(req, WebKit2.UserMediaPermissionRequest) and (view.get_uri() or "").startswith(BASE):
        req.allow()
    else:
        req.deny()
    return True


def _policy(_view, decision, kind):
    """Links to the web open in the normal browser, never inside these windows."""
    if kind not in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
        return False
    uri = decision.get_navigation_action().get_request().get_uri()
    if uri.startswith(("http://", "https://")) and not uri.startswith(BASE):
        decision.ignore()
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as e:
            print("could not open link:", e, flush=True)
        return True
    return False


_crashes = []


def _crash(view, reason):
    """The page's process died (e.g. a missing audio plugin): reload instead of showing a blank window; after a few
    crashes in a row with GPU drawing, restart with software drawing."""
    print("web process terminated:", reason, flush=True)
    now = time.time()
    _crashes[:] = [t for t in _crashes if now - t < 120] + [now]
    if len(_crashes) >= 3 and not os.environ.get("WEBKIT_DISABLE_DMABUF_RENDERER"):
        print("the page keeps crashing with GPU drawing: switching to software drawing", flush=True)
        open(SOFTWARE, "w").close()
        os.execv(sys.executable, [sys.executable] + sys.argv)
    GLib.timeout_add(500, lambda: view.reload() or False)


class Mini(Gtk.Window):
    """The mini core: transparent, no frame, always on top, bottom-right on the second monitor."""
    def __init__(self, app):
        super().__init__(title=MINI_TITLE)
        self.app = app
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_default_size(MW, MH)
        visual = self.get_screen().get_rgba_visual()  # see-through where nothing is drawn
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        css = Gtk.CssProvider()
        css.load_from_data(b"window.amadeus-mini, window.amadeus-mini * { background: transparent; }")
        self.get_style_context().add_class("amadeus-mini")
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.view = make_view(self.on_msg, transparent=True)
        self.add(self.view)
        self.connect("delete-event", lambda *_: (self.app.hide_mini(user=True), True)[1])
        self.call = False

    def load(self, call=False):
        self.call = call
        self.view.load_uri(BASE + "/mini.html" + ("?call=1" if call else ""))

    def on_msg(self, msg):
        if msg.startswith("dash:"):
            self.app.show_dash(msg[5:] or "/#home")
        elif msg == "close":  # the close button: you closed it
            self.app.hide_mini(user=True)
        elif msg == "hide":  # a call is over: back to how it was
            self.app.hide_mini(user=False)
        elif msg.startswith("shape:"):
            self.set_shape(json.loads(msg[6:]))

    def set_shape(self, rects):
        """Clicks only where something is drawn (the core, the bubbles); everywhere else they reach the desktop."""
        import cairo
        try:
            region = cairo.Region([cairo.RectangleInt(max(0, x), max(0, y), max(1, w), max(1, h)) for x, y, w, h in rects])
            self.input_shape_combine_region(region)
        except Exception as e:
            print("input shape:", e, flush=True)


class Dash(Gtk.Window):
    """The dashboard: a normal window with a slim title bar."""
    def __init__(self, app):
        super().__init__(title=DASH_TITLE)
        self.app = app
        self.set_default_size(1200, 800)
        if os.path.exists(ICON):
            try:
                self.set_icon_from_file(ICON)
            except GLib.Error:
                pass
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            headerbar { min-height: 30px; padding: 0 4px; }
            headerbar .title { font-size: 12.5px; }
            headerbar button.titlebutton { min-height: 18px; min-width: 18px; padding: 1px; margin: 4px 2px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        bar = Gtk.HeaderBar(title=DASH_TITLE, show_close_button=True)
        bar.set_decoration_layout(":minimize,maximize,close")
        self.set_titlebar(bar)
        self.view = make_view(self.on_msg)
        self.add(self.view)
        self.connect("delete-event", lambda *_: (self.app.close_dash(), True)[1])

    def on_msg(self, msg):
        if msg.startswith("open:"):
            self.view.load_uri(BASE + msg[5:])


class App:
    def __init__(self, token):
        self.token, self.mini, self.dash = token, None, None
        self.mini_visible = False

    def login(self, view, page):  # the first page of the process signs the windows in (cookie), then goes on
        view.load_uri(f"{BASE}/?token={self.token}&next=" + GLib.uri_escape_string(page, None, False))

    # ---- the mini core ----
    def show_mini(self, call=False):
        first = self.mini is None
        if first:
            self.mini = Mini(self)
        if first or not self.mini_visible:  # (hidden, it's blank: it loads again)
            self.mini.call = call
            if first and not self.dash:
                self.login(self.mini.view, "/mini.html" + ("?call=1" if call else ""))
            else:
                self.mini.load(call)
        if not call:
            try:
                os.remove(HIDDEN)
            except OSError:
                pass
        self.mini.show_all()
        self.mini.present()
        self.mini_visible = True
        place_mini(self.mini)
        if call and not first:
            self.mini.view.evaluate_javascript("window.amadeusShown && window.amadeusShown('call')", -1, None, None, None, None, None)

    def hide_mini(self, user):
        if not self.mini:
            return
        if user:
            open(HIDDEN, "w").close()
        self.mini.hide()
        self.mini_visible = False
        self.mini.view.load_uri("about:blank")  # nothing runs while it's hidden
        self.quit_if_idle()

    def toggle_mini(self):
        if self.mini_visible:
            self.hide_mini(user=True)
        else:
            self.show_mini()

    # ---- the dashboard ----
    def show_dash(self, target="/#home"):
        if not self.dash:
            self.dash = Dash(self)
            if self.mini is None:
                self.login(self.dash.view, target)
            else:
                self.dash.view.load_uri(BASE + target)
            self.dash.show_all()
            place_dash(self.dash)
        else:
            self.dash.view.load_uri(BASE + target)
            self.dash.show_all()
        self.dash.present()

    def close_dash(self):
        if self.dash:
            self.dash.destroy()
            self.dash = None
        self.quit_if_idle()

    def quit_if_idle(self):
        if not self.mini_visible and not self.dash:
            quit_now()

    # ---- signals from the tray, the server and the wake word ----
    def on_usr1(self):
        """The tray ("toggle" in popup.mini), the wake word (popup.wake) or a new call."""
        try:
            fresh = time.time() - os.path.getmtime(MINICMD) < 10
            cmd = open(MINICMD).read().strip() if fresh else ""
            os.remove(MINICMD)
        except OSError:
            cmd = ""
        if cmd == "toggle":
            self.toggle_mini()
        elif cmd == "show":
            self.show_mini()
        elif not self.check_wake():
            self.show_mini(call=not self.mini_visible)
            if self.mini_visible and self.mini:
                self.mini.view.evaluate_javascript("window.amadeusShown && window.amadeusShown('call')", -1, None, None, None, None, None)
        return GLib.SOURCE_CONTINUE

    def on_usr2(self):
        try:
            target = open(CMD).read().strip() or "/#home"
        except OSError:
            target = "/#home"
        self.show_dash(target)
        return GLib.SOURCE_CONTINUE

    def check_wake(self):
        """The wake word was heard (flag from the server): the dashboard listens if it's in front, else the mini core."""
        flag = os.path.join(DATA, "popup.wake")
        try:
            fresh = time.time() - os.path.getmtime(flag) < 60
            data = json.load(open(flag))
            os.remove(flag)
        except (OSError, ValueError):
            return False
        if not fresh:
            return False
        if self.dash and self.dash.is_active():
            view = self.dash.view
        else:
            if not self.mini_visible:
                self.show_mini()
                GLib.timeout_add(1500, lambda: self._wake(self.mini.view, data) or False)
                return True
            view = self.mini.view
        self._wake(view, data)
        return True

    def _wake(self, view, data):
        view.evaluate_javascript(f"window.amadeusWake && window.amadeusWake({json.dumps(data)})", -1, None, None, None, None, None)


def _running_window(pidfile):
    """pid of another Amadeus window process that is still running, else None."""
    try:
        pid = int(open(pidfile).read())
        if pid == os.getpid():
            return None
        with open(f"/proc/{pid}/stat") as f:
            if f.read().rsplit(")", 1)[1].split()[0] in ("Z", "X"):
                return None
        return pid if "popup.py" in open(f"/proc/{pid}/cmdline").read() else None
    except (OSError, ValueError, IndexError):
        return None


def quit_now():
    """End the process right away. A normal Gtk quit can hang while WebKit shuts down: the windows are then gone but
    the process lives on, so the next call or `amadeus` is sent to an invisible window."""
    pidfile = os.path.join(DATA, "popup.pid")
    try:
        if open(pidfile).read().strip() == str(os.getpid()):  # only our own (a newer process may have taken over)
            os.remove(pidfile)
    except OSError:
        pass
    sys.stdout.flush()
    os._exit(0)


def main():
    """popup.py            a call (from the server's events): the mini core shows up, rings, and goes again
       popup.py --mini     the mini core (the tray, the wake word, at login)
       popup.py /#path     the dashboard at a page, e.g. /#approvals
    A running process reacts to SIGUSR1 (popup.mini: "toggle" / "show", else a call or the wake word) and SIGUSR2
    (the dashboard at the page in popup.cmd)."""
    GLib.set_prgname("amadeus-call")  # Wayland app id, matched by the KWin rule and scripts
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    start = "mini" if arg == "--mini" else arg if arg.startswith("/") else "call"
    pidfile = os.path.join(DATA, "popup.pid")
    other = _running_window(pidfile)
    if other:  # already running: hand it over
        if start.startswith("/"):
            open(CMD, "w").write(start)
            os.kill(other, signal.SIGUSR2)
        else:
            if start == "mini":
                open(MINICMD, "w").write("show")
            os.kill(other, signal.SIGUSR1)
        return
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))
    try:
        app = App(open(os.path.join(DATA, "token")).read().strip())
        try:
            from gi.repository import GLibUnix
            add = GLibUnix.signal_add
        except ImportError:
            add = GLib.unix_signal_add
        add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, app.on_usr1)
        add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, app.on_usr2)
        for sig in (signal.SIGTERM, signal.SIGINT):  # quit cleanly so the pid file is removed
            add(GLib.PRIORITY_DEFAULT, sig, lambda: quit_now() or GLib.SOURCE_REMOVE)
        if start.startswith("/"):
            app.show_dash(start)
            if not os.path.exists(HIDDEN):
                GLib.timeout_add(1500, lambda: app.show_mini() or False)
        elif start == "mini":
            app.show_mini()
            GLib.timeout_add(1500, lambda: app.check_wake() and False)
        else:
            app.show_mini(call=True)
        Gtk.main()
    finally:
        try:
            os.remove(pidfile)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
