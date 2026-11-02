#!/usr/bin/env python3
"""Amadeus desktop window. It opens small, as Amadeus' "incoming call" (web/call.html), in the bottom-right corner.
Maximize (or the Dashboard button) turns the same window into the full Amadeus app; restore goes back to the call.
Native Wayland window with normal minimize / maximize / close buttons. Staying on top and the corner position come
from a KWin window rule for the app id "amadeus-call" (desktop/install-kwin-rule.sh)."""
import json
import os
import signal
import sys
import time

os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")  # avoids blank/crashing WebKit on NVIDIA
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gio, GLib, Gtk, WebKit2  # noqa: E402

CFG_FILE = os.path.expanduser("~/.config/amadeus-core/config.json")
cfg = json.load(open(CFG_FILE)) if os.path.exists(CFG_FILE) else {}
DATA = cfg.get("data_dir", os.path.expanduser("~/.local/share/amadeus/core"))
BASE = f"http://127.0.0.1:{cfg.get('port', 8095)}"
W, H = 400, 720
CMD = os.path.join(DATA, "popup.cmd")  # target for SIGUSR2 (dashboard), written by the tray icon
ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "logo-192.png")


KWIN_JS = os.path.join(DATA, "place-window.js")


def place_window(mode):
    """Size and place the window through KWin (Wayland apps cannot move themselves):
    small = bottom-right corner, always on top; dash = centered normal window (~72% x 82% of the screen)."""
    import subprocess
    js = """for (const w of workspace.windowList()) if (w.resourceClass == "amadeus-call" && !w.fullScreen) {
      const a = workspace.clientArea(KWin.MaximizeArea, w);
      if ("%s" == "dash") {
        w.keepAbove = false;
        const W = Math.round(Math.min(1500, a.width * 0.72)), H = Math.round(Math.min(950, a.height * 0.82));
        w.frameGeometry = { x: Math.round(a.x + (a.width - W) / 2), y: Math.round(a.y + (a.height - H) / 2), width: W, height: H };
      } else {
        w.keepAbove = true;
        // KWin 6.8 rects have no right/bottom (they were NaN and the window vanished): compute them
        w.frameGeometry = { x: Math.floor(a.x + a.width - %d), y: Math.floor(a.y + a.height - %d), width: %d, height: %d };
      }
    }""" % (mode, W, H + 40, W, H + 40)
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


class Window(Gtk.Window):
    def __init__(self, token, start="call"):
        super().__init__(title="Amadeus")
        self.set_default_size(W, H)
        if os.path.exists(ICON):
            self.set_icon_from_file(ICON)
        self.full = False

        css = Gtk.CssProvider()  # a slimmer title bar than the GTK default
        css.load_from_data(b"""
            headerbar { min-height: 30px; padding: 0 4px; }
            headerbar .title { font-size: 12.5px; }
            headerbar button { min-height: 22px; min-width: 22px; padding: 2px; margin: 3px 1px; }
            headerbar button.titlebutton { min-height: 18px; min-width: 18px; padding: 1px; margin: 4px 2px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        bar = Gtk.HeaderBar(title="Amadeus", show_close_button=True)
        bar.set_decoration_layout(":minimize,maximize,close")
        self.dash = Gtk.Button()
        if os.path.exists(ICON):  # the Amadeus logo toggles between the small window and the dashboard
            from gi.repository import Gdk, GdkPixbuf
            # render at 3x from the large logo and let GTK scale down: sharp on HiDPI / fractional scaling
            src = ICON.replace("logo-192.png", "logo-512.png")
            src = src if os.path.exists(src) else ICON
            scale = 3
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, 24 * scale, 24 * scale, True)
            surface = Gdk.cairo_surface_create_from_pixbuf(pb, scale, None)
            self.dash.set_image(Gtk.Image.new_from_surface(surface))
        else:
            self.dash.set_image(Gtk.Image.new_from_icon_name("view-fullscreen-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
        self.dash.set_relief(Gtk.ReliefStyle.NONE)
        self.dash.set_tooltip_text("Show the whole dashboard")
        self.dash.connect("clicked", lambda _b: self.set_mode("small" if self.full else "dash"))
        bar.pack_start(self.dash)
        self.set_titlebar(bar)

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("amadeus")
        ucm.connect("script-message-received::amadeus", self.on_msg)
        # page errors go to the log (popup.log / the tray's journal)
        ucm.add_script(WebKit2.UserScript.new(
            "addEventListener('error',e=>console.error('JS error: '+e.message+' @'+e.lineno));"
            "addEventListener('unhandledrejection',e=>console.error('JS rejection: '+e.reason));",
            WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
        # let it speak and ring without a click first (autoplay), in this window only
        policies = WebKit2.WebsitePolicies(autoplay=WebKit2.AutoplayPolicy.ALLOW)
        self.view = WebKit2.WebView(user_content_manager=ucm, website_policies=policies)
        st = self.view.get_settings()
        st.set_enable_write_console_messages_to_stdout(True)
        st.set_user_agent_with_application_details("AmadeusDesktop", "1")  # the server only serves this window
        st.set_enable_media_stream(True)                    # microphone for push-to-talk
        st.set_media_playback_requires_user_gesture(False)  # it may speak / ring without a click first
        self.view.connect("permission-request", self.on_permission)
        self.view.connect("web-process-terminated", self.on_crash)
        self.view.connect("decide-policy", self.on_policy)
        if os.environ.get("AMADEUS_MIC_TEST"):  # diagnostics: record 2 s right after loading and log what happens
            self.view.connect("load-changed", self.on_load_test)
        self.add(self.view)
        self.connect("window-state-event", self.on_state)
        self.connect("destroy", Gtk.main_quit)
        page = "/call.html" if start == "call" else "/call.html?stay=1"
        self.view.load_uri(f"{BASE}/?token={token}&next=" + GLib.uri_escape_string(page, None, False))
        if start == "mini":  # opened by the wake word: listen once the page is there
            self.view.connect("load-changed", lambda v, ev: ev == WebKit2.LoadEvent.FINISHED and GLib.timeout_add(1200, self.check_wake))
        if start.startswith("/"):  # open straight into the dashboard, e.g. "/#approvals"
            GLib.timeout_add(300, lambda: self.set_mode("dash", start) and False)

    def show_mini(self):
        """Tray click while open: back to the small window and to the front. The wake word while the dashboard
        is open keeps the dashboard: it listens and answers right there (window.amadeusWake in app.js)."""
        if self.full and not self.wake_pending():
            self.set_mode("small")
        self.present()
        self.check_wake()
        return GLib.SOURCE_CONTINUE

    def wake_pending(self):
        try:
            return time.time() - os.path.getmtime(os.path.join(DATA, "popup.wake")) < 60
        except OSError:
            return False

    def check_wake(self):
        """The wake word was heard (flag from the server): start listening for the request."""
        flag = os.path.join(DATA, "popup.wake")
        try:
            fresh = time.time() - os.path.getmtime(flag) < 60
            data = json.load(open(flag))
            os.remove(flag)
        except (OSError, ValueError):
            return False
        if fresh:
            self.view.evaluate_javascript(f"window.amadeusWake && window.amadeusWake({json.dumps(data)})", -1, None, None, None, None, None)
        return False

    def show_dashboard(self):
        try:
            target = open(CMD).read().strip() or "/#home"
        except OSError:
            target = "/#home"
        self.set_mode("dash", target)
        self.present()
        return GLib.SOURCE_CONTINUE

    # ---- two modes: the small window in the corner, or the dashboard as a normal window (like any app) ----
    def set_mode(self, mode, target=None):
        if mode == "dash":
            if not self.full or target:
                self.view.load_uri(BASE + (target or "/#home"))
            self.full = True
        else:
            if self.is_maximized():
                self.unmaximize()
            if self.full:
                self.view.load_uri(BASE + "/call.html?stay=1")
            self.full = False
        self.dash.set_tooltip_text("Back to the small window" if self.full else "Open the dashboard")
        place_window(mode)
        return False

    def on_load_test(self, view, ev):
        if ev == WebKit2.LoadEvent.FINISHED and "call.html" in (view.get_uri() or ""):
            js = """(async () => {
              const log = (...a) => console.log("MICTEST", ...a);
              log("mediaDevices:", !!navigator.mediaDevices, "MediaRecorder:", typeof MediaRecorder, "secure:", window.isSecureContext);
              try {
                const s = await navigator.mediaDevices.getUserMedia({ audio: true });
                log("got stream, tracks:", s.getAudioTracks().map(t => t.label + "/" + t.readyState).join(", "));
                const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4", "audio/wav"];
                log("supported:", types.filter(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)).join(", ") || "none");
                const r = new MediaRecorder(s, { mimeType: "audio/webm;codecs=opus" }), parts = [];
                r.ondataavailable = e => parts.push(e.data);
                r.onerror = e => log("recorder error", e.error && e.error.message);
                r.onstop = () => { const b = new Blob(parts); log("recorded", b.size, "bytes as", r.mimeType); s.getTracks().forEach(t => t.stop()); };
                r.start(); setTimeout(() => r.stop(), 2000);
              } catch (e) { log("FAILED", e.name, e.message); }
            })();"""
            view.evaluate_javascript(js, -1, None, None, None, None, None)

    def on_crash(self, view, reason):
        """The page's process died (e.g. a missing audio plugin): reload instead of showing a blank window."""
        print("web process terminated:", reason, flush=True)
        GLib.timeout_add(500, lambda: view.reload() or False)

    def on_permission(self, _view, req):
        """Only Amadeus' own pages run in this window: allow the microphone, refuse everything else."""
        if isinstance(req, WebKit2.UserMediaPermissionRequest) and self.view.get_uri().startswith(BASE):
            req.allow()
        else:
            req.deny()
        return True

    def on_policy(self, _view, decision, kind):
        """Links to the web open in the normal browser, never inside this window."""
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

    def on_msg(self, _m, res):
        msg = res.get_js_value().to_string()
        if msg == "close" and not self.full:
            quit_now()
        elif msg.startswith("open:"):
            self.set_mode("dash", msg[5:])

    def on_state(self, _w, ev):
        """Maximizing the small window opens the dashboard; restoring keeps the dashboard as a normal window."""
        maxed = bool(ev.new_window_state & ev.new_window_state.MAXIMIZED)
        changed = bool(ev.changed_mask & ev.changed_mask.MAXIMIZED)
        if changed and maxed and not self.full:
            target, self.target = getattr(self, "target", "") or "/#home", ""
            self.view.load_uri(BASE + target)
            self.full = True
            self.dash.set_tooltip_text("Back to the small window")
        elif changed and not maxed and self.full:
            place_window("dash")

def _running_window(pidfile):
    """pid of another Amadeus window that is still running, else None."""
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
    """Close the window and end the process right away. A normal Gtk quit can hang while WebKit shuts down: the window
    is then gone but the process lives on, so the next "Amadeus" or call is sent to an invisible window."""
    pidfile = os.path.join(DATA, "popup.pid")
    try:
        if open(pidfile).read().strip() == str(os.getpid()):  # only our own (a newer window may have taken over)
            os.remove(pidfile)
    except OSError:
        pass
    sys.stdout.flush()
    os._exit(0)


def main():
    """popup.py            ring (used for events; closes itself when there is nothing to show)
       popup.py --mini     open the small Amadeus window without ringing
       popup.py /#path     open the dashboard at a page, e.g. /#approvals
    A running window reacts to SIGUSR1 (come to front) and SIGUSR2 (dashboard at the page in popup.cmd)."""
    GLib.set_prgname("amadeus-call")  # Wayland app id, matched by the KWin rule
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    start = "mini" if arg == "--mini" else arg if arg.startswith("/") else "call"
    pidfile = os.path.join(DATA, "popup.pid")
    other = _running_window(pidfile)
    if other and start == "call":  # a window is already open: it shows the new events itself
        os.kill(other, signal.SIGUSR1)
        return
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))
    try:
        win = Window(open(os.path.join(DATA, "token")).read().strip(), start)
        try:
            from gi.repository import GLibUnix
            add = GLibUnix.signal_add
        except ImportError:
            add = GLib.unix_signal_add
        add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, win.show_mini)
        add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, win.show_dashboard)
        for sig in (signal.SIGTERM, signal.SIGINT):  # quit cleanly so the pid file is removed
            add(GLib.PRIORITY_DEFAULT, sig, lambda: quit_now() or GLib.SOURCE_REMOVE)
        win.show_all()
        win.present()
        Gtk.main()
    finally:
        try:
            os.remove(pidfile)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
