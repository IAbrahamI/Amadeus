"""HTTP server: web UI + JSON API + streamed chat (server-sent events). Local only, token protected."""
import datetime
import html
import http.cookies
import json
import mimetypes
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import agenda, agent, background, db, desktop, devices, events, llm, mailbridge, phoneapp, profile, system, tools
from .config import CFG

DESKTOP_UA = "AmadeusDesktop/1"
RELOGIN = """<!doctype html><meta charset=utf-8><title>Amadeus</title>
<body style="margin:0;height:100vh;display:grid;place-items:center;background:#05101A;color:#D4E6F2;font:15px system-ui,sans-serif"><p id=t>Signing in…</p>
<script>window.amadeusBridge.postMessage("relogin");
setTimeout(() => { t.textContent = "Amadeus couldn't sign this window in. Please quit it from the menu bar icon and open it again."; }, 8000);</script>"""
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
WEB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


def _tailscale_host():
    """This PC's private HTTPS name in your Tailscale network (e.g. pc.tailXXXX.ts.net), or ''."""
    import subprocess
    try:
        out = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5).stdout)
        return (out.get("Self") or {}).get("DNSName", "").rstrip(".")
    except Exception:
        return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # ---------- helpers ----------
    def _desktop(self):
        """Amadeus runs only in its desktop app (desktop-tauri/), which identifies itself in the user agent."""
        return DESKTOP_UA in self.headers.get("user-agent", "")

    def _tailnet(self):
        """Requests from your phone come through `tailscale serve`, which adds the Tailscale user (only your own devices)."""
        return self.headers.get("tailscale-user-login", "")

    def _device(self):
        """The paired phone making this request (its own key cookie, through your Tailscale network), or None."""
        c = http.cookies.SimpleCookie(self.headers.get("cookie", ""))
        if not self._tailnet() or c.get("amadeus_dev") is None:
            return None
        return devices.check(c["amadeus_dev"].value, self._tailnet())

    def _phone(self):
        return self._device() is not None

    def _authed(self):
        c = http.cookies.SimpleCookie(self.headers.get("cookie", ""))
        return (c.get("amadeus") and c["amadeus"].value == CFG["token"] and self._desktop() and not self._tailnet()) or \
            (self.headers.get("authorization") == f"Bearer {CFG['token']}" and not self._tailnet()) or self._phone()

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _mail_signed_in(self, qs):
        """Only takes a sign-in this PC started (its one-time state), so no cookie is needed here."""
        from . import maildirect
        try:
            if qs.get("error"):
                raise ValueError(qs.get("error_description", qs["error"])[0][:300])
            text = f"Connected {maildirect.ms_finish(qs.get('state', [''])[0], qs.get('code', [''])[0])['email']}. You can close this tab."
        except (ValueError, OSError, KeyError) as e:
            text = f"That didn't work: {e}"
        data = f"<!doctype html><meta charset=utf-8><title>Amadeus</title><p>{html.escape(text)}</p>".encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("content-length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _static(self, path):
        f = os.path.realpath(os.path.join(WEB, path.lstrip("/") or "index.html"))
        if not f.startswith(os.path.realpath(WEB)) or not os.path.isfile(f):
            f = os.path.join(WEB, "index.html")
        data = Path(f).read_bytes()
        self.send_response(200)
        self.send_header("content-type", mimetypes.guess_type(f)[0] or "application/octet-stream")
        if f.endswith((".html", ".js", ".css")):  # checked every time, so an update shows without clearing a cache
            self.send_header("cache-control", "no-cache")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- routes ----------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/mail/oauth" and not self._tailnet():  # back from signing in at Microsoft, in your normal browser
            return self._mail_signed_in(qs)
        if self._tailnet():  # from your phone, through Tailscale
            if u.path in ("/pair", "/pair.html"):
                return self._static("/pair.html")
            if u.path == "/amadeus.apk" and CFG.get("serve_apk", False):  # the Android app for installing on your phone;
                # off unless "serve_apk": true in the config (only needed while you install or update the app)
                f = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                 "android", "app", "build", "outputs", "apk", "release", "app-release.apk")
                if not os.path.isfile(f):
                    return self._json({"error": "The app isn't built yet."}, 404)
                data = Path(f).read_bytes()
                self.send_response(200)
                self.send_header("content-type", "application/vnd.android.package-archive")
                self.send_header("content-disposition", 'attachment; filename="Amadeus.apk"')
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not self._phone():
                if u.path.endswith((".js", ".css", ".png", ".svg", ".webmanifest")) and not u.path.startswith("/avatar/"):
                    return self._static(u.path)
                if u.path.startswith("/api/"):
                    return self._json({"error": "This phone is not paired."}, 401)
                self.send_response(302)
                self.send_header("location", "/pair")
                self.end_headers()
                return
            if u.path in ("/", "/m"):
                return self._static("/call.html")
        elif not self._desktop() and (u.path in ("/", "/index.html", "/call.html", "/mini.html", "/bubble.html") or "token" in qs):
            return self._json({"error": "Amadeus only opens in its desktop window: use the tray icon or the Amadeus app."}, 403)
        if qs.get("token", [""])[0] == CFG["token"]:
            # the page goes on by itself, not with a redirect: a window that came from the app's starting screen would
            # otherwise arrive from another site, and the browser leaves out this cookie then
            nxt = qs.get("next", ["/"])[0]
            target = json.dumps(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/").replace("<", "\\u003c")
            page = f"<!doctype html><meta charset=utf-8><body style='background:#05101A'><script>location.replace({target})</script>".encode()
            self.send_response(200)
            self.send_header("set-cookie", f"amadeus={CFG['token']}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000")
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if u.path.startswith("/avatar/"):
            if not self._authed():
                return self._json({"error": "unauthorized"}, 401)
            base = os.path.realpath(os.path.join(CFG["data_dir"], "avatar"))
            f = os.path.realpath(os.path.join(base, u.path[len("/avatar/"):]))
            if f.startswith(base + os.sep) and not os.path.isfile(f):  # a mood or frame you didn't add: the calm one
                calm = os.path.join(os.path.dirname(f), os.path.basename(os.path.dirname(f)) + "_normal1.png")
                f = calm if os.path.isfile(calm) else f
            if not f.startswith(base + os.sep) or not os.path.isfile(f):
                return self._json({"error": "not found"}, 404)
            data = Path(f).read_bytes()
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("cache-control", "private, max-age=86400")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if not u.path.startswith("/api/"):
            if not self._authed() and u.path in ("/", "/index.html"):
                if self._desktop():  # the app's own window, without a valid sign-in: it signs in again
                    page = RELOGIN.encode()
                    self.send_response(200)
                    self.send_header("content-type", "text/html; charset=utf-8")
                    self.send_header("cache-control", "no-store")
                    self.send_header("content-length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                    return
                return self._json({"error": "Open Amadeus with the 'amadeus' command (it signs you in)."}, 401)
            return self._static(u.path)
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        p = u.path
        if p == "/api/avatar":  # an animated sprite set if you added one (config "avatar"), else the default icon
            name = os.path.basename(CFG.get("avatar") or "")
            d = os.path.join(CFG["data_dir"], "avatar", name)
            return self._json({"available": bool(name) and os.path.isdir(d) and bool(os.listdir(d)), "set": name})
        if p == "/api/learning":  # what it learned from your feedback (Settings → Memory)
            from . import learning
            return self._json({"lessons": learning.lessons(), "log": db.get_setting("reflect_log", [])[-10:],
                               "feedback": learning.scores()})
        if p == "/api/assistant":  # Settings → Assistant: name, personality, avatar
            from . import assistant
            return self._json(assistant.get())
        if p == "/api/voice/voices":  # reading-aloud voices (Settings → Voice)
            from . import voices
            return self._json(voices.listing())
        if p == "/api/desktop/wait":  # the desktop app waits here for what to show (a call, the wake word)
            if self._tailnet():
                return self._json({"error": "Only on the PC."}, 403)
            return self._json({"cmds": desktop.wait()})
        if p == "/api/identity":  # the assistant's name and look, for the window and the phone app
            return self._json({"name": CFG["assistant_name"], "avatar": os.path.basename(CFG.get("avatar") or ""), "theme": db.get_setting("theme", "blue")})
        m = re.fullmatch(r"/api/voice/line/(\w+)", p)
        if m:  # a short line she says (voices.py); nothing while the mini core's voice is off
            from . import voices
            data = voices.line(m.group(1)) if m.group(1) in voices.LINES and db.get_setting("speak_mini", "always") != "off" else None
            self.send_response(200 if data else 204)
            self.send_header("content-type", "audio/wav")
            self.send_header("content-length", str(len(data or b"")))
            self.end_headers()
            self.wfile.write(data or b"")
            return
        if p == "/api/voice/replies":  # read replies aloud: "voice" (when you talked), "always" or "off"; the mini core has its own
            from . import voices
            mini = qs.get("for", [""])[0] == "mini"
            return self._json({"mode": db.get_setting("speak_mini" if mini else "speak_replies", "always" if mini else "voice"), "voice": voices.selected()})
        if p == "/api/theme":  # the dashboard's main colour (Settings): blue (default), purple or red
            return self._json({"theme": db.get_setting("theme", "blue")})
        if p == "/api/setup":  # the first start of the Mac app
            from . import firstrun
            return self._json(firstrun.status())
        if p == "/api/models":
            try:
                return self._json({"models": llm.list_models(), "info": llm.model_info(), "default": CFG["default_model"],
                                   "chat": db.get_setting("chat_model", "") or CFG["default_model"]})
            except OSError:  # Ollama isn't running
                return self._json({"offline": True, "models": [], "info": [], "default": CFG["default_model"], "chat": ""})
        if p == "/api/conversations":
            return self._json(db.q("SELECT * FROM conversations ORDER BY updated DESC"))
        m = re.fullmatch(r"/api/conversations/(\w+)", p)
        if m:
            conv = db.q("SELECT * FROM conversations WHERE id=?", (m.group(1),), one=True)
            if not conv:
                return self._json({"error": "not found"}, 404)
            msgs = db.messages(m.group(1))
            for x in msgs:
                if x["role"] == "approval":
                    a = db.q("SELECT status,result,args FROM approvals WHERE id=?", (x["meta"]["approval_id"],), one=True)
                    x["meta"].update(a or {})
            return self._json({"conversation": conv, "messages": msgs, "busy": m.group(1) in agent.RUNNING})
        if p == "/api/approvals":
            status = qs.get("status", ["pending"])[0]
            rows = db.q("SELECT a.*, c.title AS conversation_title FROM approvals a LEFT JOIN conversations c "
                        "ON c.id=a.conversation_id " + ("" if status == "all" else "WHERE a.status=? ") +
                        "ORDER BY a.created DESC LIMIT 200", () if status == "all" else (status,))
            return self._json(rows)
        if p == "/api/mail/direct":  # Mail → + Add account: the providers, and what's connected this way
            from . import mailbridge, maildirect
            return self._json({"providers": {k: {"name": v["name"], "how": v["how"], "link": v.get("link", ""), "auth": v["auth"], "manual": not v["imap"]}
                                             for k, v in maildirect.PROVIDERS.items()},
                               "accounts": maildirect.listing(), "microsoft": bool(maildirect.ms_client_id()), "thunderbird": mailbridge.thunderbird_set_up()})
        if p == "/api/update":  # a new version? (Settings → Assistant, the top bar and the tray)
            from . import updates
            return self._json(updates.status())
        if p == "/api/folder":  # Settings → Connectors: where your notes and projects are
            from . import notesfolder
            return self._json(notesfolder.status())
        if p == "/api/connectors":
            from . import mcp
            on = tools.enabled_connectors()
            own = [{"id": c["id"], "description": f"Your connector (MCP): {c['command']}", "enabled": on.get(c["id"], True),
                    "tools": c["tools"], "approval_tools": c["tools"], "own": True, "name": c["name"]} for c in mcp.listing()]
            return self._json([{"id": k, "description": v, "enabled": on.get(k, True), "missing": tools.missing(k),
                                "tools": [t["name"] for t in tools.TOOLS if t["connector"] == k],
                                "approval_tools": [t["name"] for t in tools.TOOLS if t["connector"] == k and t["approval"]]}
                               for k, v in tools.CONNECTORS.items()] + own)
        if p == "/api/skills":
            off = set(db.get_setting("skills_off", []))
            return self._json([{"name": s["name"], "description": s["description"], "mode": s["mode"], "triggers": s["triggers"],
                                "active": s["mode"] == "background" or s["name"] not in off, "own": agent.own_skill(s["name"])}
                               for s in agent.skills().values()])
        if p == "/api/reminders":
            return self._json(db.q("SELECT * FROM reminders WHERE active=1 ORDER BY next_run"))
        if p == "/api/devices/qr":  # QR code for pairing: the address, plus the one-time code when the dashboard just made one
            import subprocess
            if self._tailnet():
                return self._json({"error": "Show the pairing QR code on the PC."}, 403)
            host = _tailscale_host()
            if not host:
                return self._json({"error": "Tailscale is not running"}, 404)
            code = qs.get("code", [""])[0]
            url = f"https://{host}/pair" + (f"#code={code}" if re.fullmatch(r"\d{6}", code) else "")
            svg = subprocess.run(["qrencode", "-t", "SVG", "-m", "1", "-o", "-", url], capture_output=True, timeout=10).stdout
            self.send_response(200)
            self.send_header("content-type", "image/svg+xml")
            self.send_header("content-length", str(len(svg)))
            self.end_headers()
            self.wfile.write(svg)
            return
        if p == "/api/push/key":
            from . import push
            return self._json({"key": push.public_key()})
        if p == "/api/devices":
            from . import playbooks
            return self._json({"devices": devices.listing(), "host": _tailscale_host(), "phone": self._phone(),
                               "mode": playbooks.phone_status()})
        if p == "/api/playbooks":
            from . import playbooks
            return self._json(playbooks.listing())
        if p == "/api/events":
            return self._json(events.unseen())
        if p == "/api/ringable":  # the mini core: may it ring now (quiet hours, you're on the phone), and what always rings
            return self._json({"quiet": events.quiet(), "phone": phoneapp.in_use(), "urgent": list(events.URGENT)})
        if p == "/api/app/home":  # the Android app's home screen
            return self._json(phoneapp.home())
        if p == "/api/projects":  # the Projects page: one folder each in your projects folder
            from . import work
            return self._json(work.projects())
        if p == "/api/projects/folder":  # where the projects live, and whether that's (still) among your notes
            from . import work
            return self._json(work.folder_info())
        m = re.fullmatch(r"/api/projects/([^/]+)(/file)?", p)
        if m:
            from . import work
            name = urllib.parse.unquote(m.group(1))
            try:
                return self._json(work.project_file(name, qs.get("path", [""])[0]) if m.group(2) else work.project(name))
            except ValueError as e:
                return self._json({"error": str(e)}, 404)
        if p == "/api/todo":
            return self._json({"items": phoneapp.todo()})
        if p == "/api/day":  # "Your day" on the dashboard (click the clock): today's morning brief and evening summary
            from . import digest
            return self._json({"date": datetime.date.today().isoformat(), "reports": digest.reports()})
        if p == "/api/quickchat":  # today's chat (one per day): small window, dashboard and phone app
            from . import quickchat
            return self._json({"id": quickchat.current()})
        if p == "/api/call":  # was the current call answered somewhere (PC window or phone)?
            return self._json(phoneapp.call_state())
        if p == "/api/stream":  # the Android app's live link: calls as phone notifications
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            self.close_connection = True
            return phoneapp.stream(*phoneapp.sse(self.wfile))
        if p == "/api/profile":
            return self._json({"profile": profile.get(), "pending": len(db.get_setting("profile_pending", [])),
                               "updated": db.get_setting("profile_updated", ""), "rules": db.get_setting("mail_rules", {}),
                               "vip": db.get_setting("mail_vip", []), "asking": db.get_setting("ask_patterns", [])})
        if p == "/api/core":  # the HUD core: memory counts per kind and topic sizes (no memory text)
            try:
                return self._json(tools.core_stats())
            except Exception as e:
                return self._json({"error": str(e)}, 502)
        if p == "/api/memory":
            try:
                return self._json({"text": tools.memory_overview(300)})
            except Exception as e:
                return self._json({"error": str(e)}, 502)
        if p.startswith("/api/mail/"):
            return self._mail(p, qs)
        if p == "/api/calendar":
            import datetime as _dt
            frm = _dt.date.fromisoformat(qs.get("from", [_dt.date.today().isoformat()])[0])
            to = _dt.date.fromisoformat(qs.get("to", [(frm + _dt.timedelta(days=42)).isoformat()])[0])
            return self._json(agenda.occurrences(frm, to))
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/pair":  # a phone (through Tailscale) enters the code shown in the dashboard
            if not self._tailnet():
                return self._json({"error": "Pairing works only from a device in your Tailscale network."}, 403)
            b = self._body()
            key = devices.pair(str(b.get("code", "")), str(b.get("name", "Phone")), self._tailnet())
            if not key:
                return self._json({"error": "That code is wrong or expired. Make a new one in the dashboard (Settings → Phone)."}, 403)
            data = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("set-cookie", f"amadeus_dev={key}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000")
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        if p == "/api/voice/voices/upload":  # "+ Add a voice" with your own files (raw body, file name in the query)
            from . import voices
            n = int(self.headers.get("content-length", 0) or 0)
            try:
                return self._json(voices.add_file(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("name", [""])[0],
                                                  self.rfile.read(n)))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/voice/tts":  # {"text"} -> spoken audio with the voice picked in Settings → Voice
            from . import voices
            n = int(self.headers.get("content-length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            text = str(body.get("text", ""))[:4000]
            if body.get("speech"):  # a reply read aloud: what a person would say, not the chat text (speech.py)
                from .speech import speech_text
                v = voices.selected()
                text = speech_text(text, "en" if v.startswith("kokoro:") else v[:2], int(body.get("limit") or 600))
            return self._voice("/tts", json.dumps({"text": text, "voice": voices.path()}).encode())
        if p == "/api/voice/stt":  # raw audio, passed through to the voice service
            return self._voice(p[len("/api/voice"):])
        b = self._body()
        if p == "/api/push/subscribe":  # the phone app wants Amadeus's calls as notifications
            from . import push
            try:
                push.subscribe(self._body())
                return self._json({"ok": True})
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        m = re.fullmatch(r"/api/phone/(private|visible)", p)
        if m:  # dashboard buttons for private / visible mode; the phone app can only go private (it can't reach a private PC)
            if self._tailnet() and m.group(1) != "private":
                return self._json({"error": "Switch this on the PC."}, 403)
            from . import playbooks
            return self._json({"text": (playbooks.private_mode if m.group(1) == "private" else playbooks.visible_mode)(None),
                               "mode": playbooks.phone_status()})
        if p == "/api/devices/code":  # dashboard: a new pairing code
            if self._tailnet():
                return self._json({"error": "Make pairing codes on the PC."}, 403)
            host = _tailscale_host()
            return self._json({"code": devices.new_code(), "url": f"https://{host}/pair" if host else "", "minutes": devices.CODE_MINUTES})
        m = re.fullmatch(r"/api/devices/(\w+)/revoke", p)
        if m:
            devices.revoke(m.group(1))
            return self._json({"ok": True})
        if p == "/api/unpair":  # the phone app removes itself ("Unpair this phone")
            d = self._device()
            if not d:
                return self._json({"error": "Only a paired phone can unpair itself."}, 400)
            devices.revoke(d["id"])
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/voice/(on|off)", p)
        if m:  # voice input (the wake word listener) on or off, e.g. from the phone app
            from . import playbooks
            text = (playbooks.voice_on if m.group(1) == "on" else playbooks.voice_off)(None)
            return self._json({"voice": playbooks.voice_status(), "text": text})
        m = re.fullmatch(r"/api/messages/(\d+)/feedback", p)
        if m:  # 👍 / 👎 on an answer
            from . import learning
            try:
                return self._json(learning.feedback(int(m.group(1)), b.get("score", 0), b.get("note", "")))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        m = re.fullmatch(r"/api/assistant(/reset|/upload)?", p)
        if m:  # save who the assistant is (then Amadeus restarts itself), the defaults, or your own avatar images
            from . import assistant
            try:
                if m.group(1) == "/reset":
                    return self._json(assistant.reset())
                if m.group(1) == "/upload":
                    return self._json(assistant.upload(b.get("files", []), b.get("set", "custom")))
                return self._json(assistant.save(b))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        m = re.fullmatch(r"/api/voice/voices/(select|download)", p)
        if m:
            from . import voices
            try:
                return self._json(getattr(voices, m.group(1))(str(b.get("id", ""))))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/learning/run":  # learn from the last day's feedback now, instead of waiting for the night
            from . import learning
            return self._json(learning.reflect(force=True) or {})
        if p == "/api/learning/forget":  # remove one lesson
            from . import learning
            learning._save([l for l in learning.lessons() if l["id"] != b.get("id")])
            return self._json({"lessons": learning.lessons()})
        if p == "/api/day/now":  # "Summarize so far" in "Your day": today's mail and chats until now
            from . import digest
            return self._json({"reports": digest.now_summary()})
        if p == "/api/quickchat/new":  # older callers (phone app): there is one chat per day, so this is today's
            from . import quickchat
            return self._json({"id": quickchat.new()})
        if p == "/api/app/active":  # the phone app is open (sent every 30 s while you use it)
            phoneapp.touch()
            return self._json({"ok": True})
        if p == "/api/call/answered":  # picked up on this device: the other one stops ringing
            phoneapp.answered("phone" if self._tailnet() else "pc")
            return self._json({"ok": True})
        if p == "/api/projects":  # you start a project yourself (folder + Overview.md; nothing leaves the PC)
            from . import work
            try:
                return self._json(work.new_project(str(b.get("name", "")), str(b.get("goal", ""))[:4000]))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/projects/folder":  # you pick the folder for the projects (and whether to move the existing ones)
            from . import work
            try:
                return self._json(work.set_folder(b.get("path", ""), bool(b.get("move"))))
            except (ValueError, OSError) as e:
                return self._json({"error": str(e)}, 400)
        m = re.fullmatch(r"/api/projects/([^/]+)/state", p)
        if m:  # you mark a project done (or open it again)
            from . import work
            try:
                return self._json(work.set_done(urllib.parse.unquote(m.group(1)), bool(b.get("done"))))
            except ValueError as e:
                return self._json({"error": str(e)}, 404)
        if p == "/api/mail/accounts":  # which mail accounts Amadeus may read (switched off = never read, anywhere)
            off = set(db.get_setting("mail_accounts_off", []))
            aid = str(b.get("id", ""))[:80]
            (off.discard if b.get("read", True) else off.add)(aid)
            db.set_setting("mail_accounts_off", sorted(off))
            return self._json({"off": sorted(off)})
        if p in ("/api/mail/direct/add", "/api/mail/direct/remove", "/api/mail/direct/microsoft"):
            from . import maildirect
            if self._tailnet():
                return self._json({"error": "Only on the PC."}, 403)
            try:
                if p.endswith("/add"):
                    return self._json(maildirect.add_account(b.get("provider"), b.get("email"), b.get("password"), b.get("imap"), b.get("smtp")))
                if p.endswith("/remove"):
                    return self._json(maildirect.remove_account(str(b.get("id", ""))))
                return self._json({"url": maildirect.ms_start()})
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/mail/thunderbird":  # open Thunderbird (to add an account there: sign-in stays in Thunderbird)
            from .tools import _to_front, launch
            launch(["thunderbird"], "thunderbird")
            _to_front(["thunderbird"])
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/projects/([^/]+)/terminal", p)
        if m:  # "Open in Claude Code": a terminal with Claude Code in the project's folder (your own session)
            from . import work
            try:
                return self._json(work.open_terminal(urllib.parse.unquote(m.group(1))))
            except ValueError as e:
                return self._json({"error": str(e)}, 404)
        m = re.fullmatch(r"/api/projects/([^/]+)/(chat|claude)", p)
        if m:
            from . import work
            try:
                name, _ = work._project_dir(urllib.parse.unquote(m.group(1)))
            except ValueError as e:
                return self._json({"error": str(e)}, 404)
            if m.group(2) == "chat":  # Amadeus's conversation about this project
                return self._json({"id": work.project_chat(name)})
            # straight to Claude Code: you see the filtered text first, then confirm it (your own action, like an approval)
            clean, findings, hold = tools.send_to_work_preview(str(b.get("text", ""))[:20000])
            if hold:
                return self._json({"error": "Not sendable: it contains something from your deny-list or a canary marker."}, 400)
            if not b.get("confirm"):
                return self._json({"preview": clean, "findings": findings})
            if clean != b.get("preview"):
                return self._json({"error": "The text changed; check the preview again."}, 409)
            last = work.last_session(name)
            r = work.start(name, clean, work.project_chat(name), resume=last["session_id"] if last else None)
            return self._json({"error": r} if isinstance(r, str) else {"ok": True, "resumed": bool(last)})
        if p == "/api/todo/add":  # you added an item on the ToDo page (your own action, like in any notes app)
            items = [str(i).strip()[:300] for i in b.get("items", []) if str(i).strip()][:20]
            return self._json({"text": tools.todo_add(items) if items else "", "items": phoneapp.todo()})
        if p == "/api/todo/done":  # you ticked an item off in the phone app
            return self._json({"text": phoneapp.todo_done(str(b.get("item", ""))[:300]), "items": phoneapp.todo()})
        if p == "/api/conversations":
            cid = db.new_id()
            db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)",
                 (cid, b.get("title") or "New chat", b.get("model") or CFG["default_model"], db.now(), db.now()))
            return self._json({"id": cid})
        m = re.fullmatch(r"/api/conversations/(\w+)/messages", p)
        if m:
            return self._chat(m.group(1), b)
        if p == "/api/setup":
            from . import firstrun
            if self._tailnet():
                return self._json({"error": "Only on this computer."}, 403)
            try:
                return self._json(firstrun.act(b.get("action", ""), b))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/models":  # the model picker: the model for today's chat and the next ones (memory jobs keep theirs)
            from . import quickchat
            m = str(b.get("model", ""))
            if m not in llm.list_models():
                return self._json({"error": "That model isn't installed in Ollama."}, 400)
            db.set_setting("chat_model", m)
            db.q("UPDATE conversations SET model=? WHERE id=?", (m, quickchat.current()))
            return self._json({"chat": m})
        if p == "/api/voice/replies":
            m, key = str(b.get("mode", "")), "speak_mini" if b.get("for") == "mini" else "speak_replies"
            db.set_setting(key, m if m in ("voice", "always", "off") else "voice")
            return self._json({"mode": db.get_setting(key)})
        if p == "/api/theme":
            t = str(b.get("theme", ""))
            db.set_setting("theme", t if t in ("blue", "purple", "red") else "blue")
            return self._json({"theme": db.get_setting("theme")})
        m = re.fullmatch(r"/api/approvals/(\w+)/revise", p)
        if m:  # Adjust: what should be different; the redraft waits for your approval again
            return self._json(agent.revise(m.group(1), b.get("note", "")))
        m = re.fullmatch(r"/api/approvals/(\w+)/(approve|reject)", p)
        if m:
            if self._tailnet():  # decided on the phone: the PC window stops ringing for it
                phoneapp.touch()
                phoneapp.answered("phone")
            return self._json(agent.decide(m.group(1), m.group(2) == "approve"))
        if p == "/api/voice/stt":
            return self._voice(p[len("/api/voice"):])
        if p in ("/api/mail/markread", "/api/mail/move"):  # your own actions in the Mail page (no approval needed)
            try:
                ids = [int(i) for i in b.get("ids", [])]
                if p.endswith("markread"):
                    return self._json(mailbridge.call("markRead", ids=ids, read=bool(b.get("read", True))))
                return self._json(mailbridge.call("move", ids=ids, folderId=b["folderId"]))
            except Exception as e:
                return self._json({"error": str(e)}, 502)
        if p == "/api/profile":
            profile.put(b.get("profile", ""))
            return self._json({"ok": True})
        if p == "/api/asking/remove":  # forget one learned "how you ask" pattern (Memory page)
            pats = [x for x in db.get_setting("ask_patterns", []) if x.get("say") != b.get("say")]
            db.set_setting("ask_patterns", pats)
            return self._json({"asking": pats})
        if p == "/api/wake":  # the wake word was heard: small window to the front, listening
            stage = b.get("stage", "listening") if b.get("stage") in ("listening", "text", "cancel") else "listening"
            desktop.send({"do": "wake", "data": {"stage": stage, "word": re.sub(r"[^a-z]", "", str(b.get("word", "")).lower())[:20],
                                                 "text": str(b.get("text", ""))[:2000], "quiet": bool(b.get("quiet"))}})
            return self._json({"ok": True})
        if p == "/api/desktop/state":  # the desktop app: whether a window is open
            if self._tailnet():
                return self._json({"error": "Only on the PC."}, 403)
            desktop.set_open(bool(b.get("open")))
            return self._json({"ok": True})
        if p == "/api/mail/vip":  # senders whose mail always calls you (your own list, set in the Memory page)
            vip = [v.strip()[:120] for v in b.get("vip", []) if isinstance(v, str) and v.strip()][:200]
            db.set_setting("mail_vip", list(dict.fromkeys(vip)))
            return self._json({"vip": db.get_setting("mail_vip", [])})
        if p == "/api/profile/merge":
            return self._json({"merged": profile.merge(), "profile": profile.get()})
        if p == "/api/calendar":
            try:
                return self._json(agenda.add(b, by="you"))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        m = re.fullmatch(r"/api/events/(\w+)/seen", p)
        if m:
            db.q("UPDATE events SET seen=1 WHERE id=?" if m.group(1) != "all" else "UPDATE events SET seen=1 WHERE seen=0",
                 (m.group(1),) if m.group(1) != "all" else ())
            return self._json({"ok": True})
        if p in ("/api/update/run", "/api/update/setting", "/api/update/restart"):
            from . import updates
            if self._tailnet():
                return self._json({"error": "Only on the PC."}, 403)
            try:
                return self._json(updates.run() if p.endswith("/run") else updates.restart() if p.endswith("/restart") else updates.set_enabled(bool(b.get("on"))))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/folder":
            from . import notesfolder
            if self._tailnet():
                return self._json({"error": "Only on the PC."}, 403)
            try:
                return self._json(notesfolder.set_notes(b.get("notes", "")))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/connectors/add":  # your own connector: an MCP server (a local command)
            from . import mcp
            try:
                return self._json(mcp.add(b.get("name", ""), b.get("command", ""), b.get("env") or {}))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/connectors/remove":
            from . import mcp
            return self._json(mcp.remove(b.get("name", "")))
        if p == "/api/connectors":
            on = tools.enabled_connectors()
            on[b["id"]] = bool(b["enabled"])
            db.set_setting("connectors", on)
            return self._json(on)
        if p in ("/api/skills/add", "/api/skills/remove"):  # your own skills
            try:
                if p.endswith("add"):
                    return self._json({"name": agent.skill_add(b.get("name", ""), b.get("description", ""), b.get("triggers", ""),
                                                               b.get("body", ""), b.get("file", ""))})
                return self._json({"ok": agent.skill_remove(b.get("name", ""))})
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p in ("/api/playbooks/add", "/api/playbooks/remove"):  # your own playbooks
            from . import playbooks
            try:
                return self._json(playbooks.own_add(b.get("title", ""), b.get("triggers", ""), b.get("steps", ""))
                                  if p.endswith("add") else playbooks.own_remove(b.get("id", "")))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/skills":
            off = set(db.get_setting("skills_off", []))
            (off.discard if b["active"] else off.add)(b["name"])
            db.set_setting("skills_off", sorted(off))
            return self._json(sorted(off))
        return self._json({"error": "not found"}, 404)

    def do_PATCH(self):
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        m = re.fullmatch(r"/api/calendar/(\w+)", urllib.parse.urlparse(self.path).path)
        if m:
            try:
                return self._json(agenda.update(m.group(1), self._body()))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        m = re.fullmatch(r"/api/conversations/(\w+)", urllib.parse.urlparse(self.path).path)
        if not m:
            return self._json({"error": "not found"}, 404)
        b = self._body()
        for k in ("title", "model"):
            if k in b:
                db.q(f"UPDATE conversations SET {k}=? WHERE id=?", (b[k], m.group(1)))
        return self._json({"ok": True})

    def do_DELETE(self):
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        m = re.fullmatch(r"/api/calendar/(\w+)", urllib.parse.urlparse(self.path).path)
        if m:
            try:
                return self._json(agenda.delete(m.group(1)))
            except ValueError as e:
                return self._json({"error": str(e)}, 404)
        m = re.fullmatch(r"/api/conversations/(\w+)", urllib.parse.urlparse(self.path).path)
        if not m:
            return self._json({"error": "not found"}, 404)
        cid = m.group(1)
        for t in ("messages", "approvals"):
            db.q(f"DELETE FROM {t} WHERE conversation_id=?", (cid,))
        db.q("DELETE FROM conversations WHERE id=?", (cid,))
        return self._json({"ok": True})

    # ---------- voice (proxy to the local voice service on 127.0.0.1:8896) ----------
    def _voice(self, path, body=None):
        if body is None:
            n = int(self.headers.get("content-length", 0) or 0)
            body = self.rfile.read(n) if n else b""
        req = urllib.request.Request(f"http://127.0.0.1:8896{path}", body, {
            "authorization": f"Bearer {CFG['token']}", "content-type": self.headers.get("content-type", "application/octet-stream")})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data, ctype = r.read(), r.headers.get("content-type", "application/json")
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except urllib.error.HTTPError as e:  # pass the voice service's own message on (e.g. "no voice installed")
            try:
                msg = json.load(e).get("error", str(e))
            except ValueError:
                msg = str(e)
            return self._json({"error": msg}, e.code)
        except Exception as e:
            return self._json({"error": f"voice service: {e}"}, 502)

    # ---------- mail (read-only views; writing goes through Amadeus with approval) ----------
    def _mail(self, p, qs):
        arg = lambda k, d="": qs.get(k, [d])[0]
        try:
            if p == "/api/mail/status":
                return self._json({**mailbridge.status(), "setup": mailbridge.configured()})
            if p == "/api/mail/recent":
                return self._json(mailbridge.call("recent", accountId=arg("account"), folderId=arg("folder") or None,
                                                  days=min(365, int(arg("days", "7"))), limit=min(500, int(arg("limit", "80")))))
            if p == "/api/mail/unread":
                return self._json(mailbridge.call("unread", accountId=arg("account"), limit=100))
            if p == "/api/mail/folders":
                return self._json(mailbridge.call("folders", accountId=arg("account"), timeout=60))
            if p == "/api/mail/search":
                return self._json(mailbridge.call("search", query=arg("q"), days=int(arg("days", "365")), limit=50,
                                                  accountId=arg("account")))
            m = re.fullmatch(r"/api/mail/message/(\d+)", p)
            if m:
                return self._json(mailbridge.call("read", id=int(m.group(1))))
        except mailbridge.NotRunning as e:
            return self._json({"error": str(e), "offline": True}, 503)
        except Exception as e:
            return self._json({"error": str(e)}, 502)
        return self._json({"error": "not found"}, 404)

    # ---------- streamed chat ----------
    def _chat(self, cid, b):
        conv = db.q("SELECT * FROM conversations WHERE id=?", (cid,), one=True)
        if not conv:
            return self._json({"error": "not found"}, 404)
        model = b.get("model") or conv["model"] or CFG["default_model"]
        if model != conv["model"]:
            db.q("UPDATE conversations SET model=? WHERE id=?", (model, cid))
        if conv["title"] == "New chat" and b.get("text"):
            db.q("UPDATE conversations SET title=? WHERE id=?", (b["text"][:48], cid))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()

        def emit(kind, data):
            try:
                self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        try:
            agent.run(cid, model, b.get("text", ""), emit, voice=bool(b.get("voice")), speak=bool(b.get("speak")))
        except Exception as e:
            db.add_message(cid, "assistant", f"Error: {e}")
            emit("error", {"message": str(e)})


def main():
    from . import voices, work  # noqa: F401  (work makes its tables, which the background jobs read)
    system.stop_with_app()
    background.start()
    voices.prepare_lines()
    srv = ThreadingHTTPServer((CFG["host"], CFG["port"]), Handler)
    print(f"Amadeus Core on http://{CFG['host']}:{CFG['port']}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
