"""Work in the cloud, the light way: one Claude Code run per task.

Amadeus filters the task and you approve it (tools.send_to_work / the new-project playbook); then one `claude -p` run
works in the project's folder (<your projects folder>/<Name>/, outside your notes), on your Claude subscription. No coordinator, no agents
waking each other. When it finishes the assistant tells you (a notification, and the result in the chat it came from).

Guard rails (~/.local/share/amadeus/work-guard, read-only, see workguard.py): the run may write only in your projects
folder (PreToolUse hook + Claude Code's sandbox for shell commands), and never reads your notes, Amadeus's own data,
mail, chats or keys. It can't ask you mid-run: missing facts come back as "## Questions"; your answers continue the same
session (continue_project). Every run is a normal Claude Code session, so you can also resume it yourself:
`cd "<projects folder>/<Name>" && claude --resume <session>`."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time

from . import db, events, system
from . import paths
from .config import CFG, projects_dir

db.q("""CREATE TABLE IF NOT EXISTS work_jobs (id TEXT PRIMARY KEY, project TEXT, folder TEXT, session_id TEXT, status TEXT,
        created REAL, finished REAL, summary TEXT, cost REAL, conversation_id TEXT)""")

for _col in ("task",):  # added later: what was asked in each run (shown in the project's history)
    try:
        db.q(f"ALTER TABLE work_jobs ADD COLUMN {_col} TEXT")
    except Exception:
        pass
# runs still marked running belonged to an earlier start of Amadeus Core: their process is gone
db.q("UPDATE work_jobs SET status='stopped', summary=coalesce(summary, 'Stopped: Amadeus restarted while it ran.') "
     "WHERE status='running'")

GUARD = paths.GUARD
MODEL = CFG.get("work_model", "claude-sonnet-5-5")
EFFORT = CFG.get("work_effort", "medium")
TIMEOUT = CFG.get("work_timeout_min", 120) * 60
TOOLS = "Read,Edit,Write,Glob,Grep,Bash,WebSearch,WebFetch,Task"

RULES = """You work for the user, handed over by their private local assistant.
- Your working folder is this project's folder. Keep every file you create here: documents, blueprints, images, code.
  Keep an up-to-date Overview.md at the top (goal, status, what's where, open points).
- You cannot reach the user during this run. If you need a fact, a decision or an OK, do everything that doesn't depend
  on it, then end your final reply with a section "## Questions" listing exactly what you need. The answers come back
  in the next run of this same session.
- Never send, post or upload anything, never create accounts or log in anywhere, never spend money. You prepare; the
  user acts.
- Never invent facts about the user. Be economical: no long explorations, no busywork.
- Your final reply is what the user reads first: say in a few lines what you did, where the files are, and what's next."""


def _folder(project):
    name = re.sub(r"[\\/:*?\"<>|\x00]", "-", project).strip(" .-")[:80] or "Task"
    path = os.path.join(_projects_root(), name)
    os.makedirs(path, exist_ok=True)
    return name, path


def _job(jid):
    return db.q("SELECT * FROM work_jobs WHERE id=?", (jid,), one=True)


def last_session(project):
    r = db.q("SELECT * FROM work_jobs WHERE lower(project)=lower(?) AND session_id IS NOT NULL ORDER BY created DESC LIMIT 1",
             (project,), one=True)
    return r


def open_terminal(project):
    """You want to see or steer the work yourself: Claude Code opens in a terminal (kitty) in the project's folder, on its last
    run's session (all its earlier work in view), or a fresh session if it never ran. That is your own session, like
    starting `claude` there yourself."""
    from . import tools
    name, path = _project_dir(project)
    last = last_session(name)
    if system.MAC:
        system.open_terminal(f"cd {shlex.quote(path)} && " + shlex.join(["claude"] + (["--resume", last["session_id"]] if last else [])))
        return {"ok": True, "resumed": bool(last)}
    cmd = ["kitty", "--directory", path, "claude"] + (["--resume", last["session_id"]] if last else [])
    tools.launch(cmd, "claude")
    tools._to_front(["kitty"])
    return {"ok": True, "resumed": bool(last)}


def running():
    return db.q("SELECT * FROM work_jobs WHERE status='running' ORDER BY created")


SIGNED_OUT = re.compile(r"failed to authenticate|authentication_error|not logged in|please run /login|invalid api key|token has expired", re.I)
CLAUDE_INSTALLER = "https://claude.ai/install.sh"


def claude_path():
    return shutil.which("claude") or next((p for p in [os.path.expanduser("~/.local/bin/claude")] if os.path.isfile(p)), None)


def claude_status():
    """Is Claude Code here and signed in? It says so itself; the sign-in stays between you and Anthropic, Amadeus never sees it."""
    path = claude_path()
    if not path:
        return {"installed": False, "signed_in": False}
    try:
        out = json.loads(subprocess.run([path, "auth", "status", "--json"], capture_output=True, text=True, timeout=20).stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        out = {}
    return {"installed": True, "signed_in": bool(out.get("loggedIn")) and not db.get_setting("claude_signed_out", False)}


def claude_open_sign_in():
    """Opens a Terminal window where Claude Code's own installer and sign-in run, in front of you."""
    path = claude_path()
    db.set_setting("claude_signed_out", False)
    if path:
        system.open_terminal(shlex.join([path, "auth", "login"]))
    else:
        system.open_terminal(f"curl -fsSL {CLAUDE_INSTALLER} | bash && ~/.local/bin/claude auth login")


def start(project, task, cid="", resume=None):
    """Start one run in the background. Returns at once; the result arrives as a notification and in the chat."""
    if not shutil.which("claude"):
        return "Claude Code isn't installed on this PC. Install it and log in once by running claude, then ask again."
    name, folder = _folder(project)
    if any(j["project"].lower() == name.lower() for j in running()):
        return f"**{name}** is still working on the last step. I'll tell you when it's done."
    jid = db.new_id()
    db.q("INSERT INTO work_jobs(id,project,folder,session_id,status,created,conversation_id,task) VALUES(?,?,?,?,?,?,?,?)",
         (jid, name, folder, resume, "running", time.time(), cid, task[:20000]))
    threading.Thread(target=_run, args=(jid, task, resume), daemon=True).start()
    return jid, name


LIVE = {}  # job id -> what the run is doing right now, for the workspace view: [{"t", "text", "path"}]
VERBS = {"Read": "Reading", "Edit": "Editing", "MultiEdit": "Editing", "Write": "Writing", "NotebookEdit": "Editing", "Glob": "Looking for files",
         "Grep": "Searching", "Bash": "Running", "TodoWrite": "Planning", "Task": "Working on a part of it"}


def _step(folder, line):
    """One line of Claude Code's live output as steps you can read: which file it reads or changes, what it runs, what it says."""
    try:
        ev = json.loads(line)
    except ValueError:
        return []
    out = []
    for block in ((ev.get("message") or {}).get("content") or []) if ev.get("type") == "assistant" else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            given = block.get("input") or {}
            path = str(given.get("file_path") or given.get("notebook_path") or given.get("path") or "")
            rel = os.path.relpath(path, folder) if path.startswith(folder + os.sep) else ""
            what = rel or str(given.get("command") or given.get("pattern") or given.get("description") or "")[:120]
            out.append({"t": time.time(), "text": f"{VERBS.get(block.get('name'), block.get('name', 'Working'))} {what}".strip(), "path": rel})
        elif block.get("type") == "text" and (block.get("text") or "").strip():
            out.append({"t": time.time(), "text": block["text"].strip()[:300], "path": ""})
    return out


AT = {}  # job id -> where Claude Code is right now, like a co-author's cursor: see Presence.at()
KINDS = {"Read": "reading", "Edit": "editing", "MultiEdit": "editing", "Write": "writing", "NotebookEdit": "editing"}
PREVIEW_MAX = 400_000  # characters of a file shown while it's being typed (bigger files show the cursor only)


def _partial(buf, key):
    """A string value from JSON that is still arriving: (text so far, complete?). None if the key hasn't started yet."""
    m = re.search(r'"%s"\s*:\s*"' % re.escape(key), buf)
    if not m:
        return None
    out, i, n = [], m.end(), len(buf)
    while i < n:
        c = buf[i]
        if c == '"':
            return "".join(out), True
        if c == "\\":
            if i + 1 >= n:
                break  # the escape is cut in half: wait for the rest
            e = buf[i + 1]
            if e == "u":
                if i + 6 > n:
                    break
                try:
                    out.append(chr(int(buf[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(e, e))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out), False


def _number(buf, key):
    m = re.search(r'"%s"\s*:\s*(\d+)\s*[,}]' % re.escape(key), buf)
    return int(m.group(1)) if m else None


class Presence:
    """Follows Claude Code's partial output (--include-partial-messages) while a tool call is still being written, so the
    workspace can show it like a co-author in a shared document: which file, which line, and for a file being written or
    edited, the text as it appears. Nothing here changes a file; the real change lands when the tool runs."""

    def __init__(self, folder):
        self.folder, self.tool, self.buf, self.now, self.base, self.last = folder, None, "", None, None, 0.0

    def _rel(self, path):
        real = os.path.realpath(path) if path else ""
        root = os.path.realpath(self.folder)
        return os.path.relpath(real, root) if real.startswith(root + os.sep) else ""

    def feed(self, ev):
        """One line of stream-json, already parsed. Returns True when the position changed."""
        if ev.get("type") != "stream_event":
            return False
        e = ev.get("event") or {}
        t = e.get("type")
        if t == "content_block_start":
            block = e.get("content_block") or {}
            if block.get("type") == "tool_use":
                self.tool, self.buf, self.base = block.get("name"), "", None
                if self.tool in KINDS:
                    return False  # where it goes isn't known yet: the previous position stays until it is
                self.now = None  # running a command or searching: not in a file
                return True
            self.tool = None
            return False
        if t == "content_block_delta" and self.tool in KINDS:
            d = e.get("delta") or {}
            if d.get("type") != "input_json_delta":
                return False
            self.buf += d.get("partial_json") or ""
            if time.time() - self.last < 0.2:  # the workspace looks twice a second; parsing every chunk would be wasted
                return False
            self.last = time.time()
            return self._update()
        if t == "content_block_stop" and self.tool in KINDS and self.buf:
            return self._update()
        return False

    def _update(self):
        got = _partial(self.buf, "file_path") or _partial(self.buf, "notebook_path")
        if not got or not got[1]:
            return False
        rel = self._rel(got[0])
        if not rel:
            return False
        kind = KINDS[self.tool]
        if self.base is None or self.base[0] != rel:
            try:
                text = Path(self.folder, rel).read_text(errors="replace")
            except OSError:
                text = ""
            self.base = (rel, text)
        text = self.base[1]
        at = {"path": rel, "kind": kind, "line": 1, "end": 1, "text": None, "t": time.time()}
        if self.tool == "Read":
            off, lim = _number(self.buf, "offset"), _number(self.buf, "limit")
            total = max(1, len(text.splitlines()))
            at["line"] = max(1, off or 1)
            at["end"] = min(total, at["line"] + lim - 1) if lim else total
        elif self.tool == "Write":
            new = _partial(self.buf, "content")
            typed = new[0] if new else ""
            at["line"] = at["end"] = typed.count("\n") + 1
            if len(typed) <= PREVIEW_MAX:
                at["text"] = typed
        else:  # Edit / MultiEdit: where the old text is, and the new text growing in its place
            old = _partial(self.buf, "old_string")
            if old and old[1] and old[0]:
                i = text.find(old[0])
                if i >= 0:
                    first = text.count("\n", 0, i) + 1
                    new = _partial(self.buf, "new_string")
                    typed = new[0] if new else ""
                    at["line"] = first + typed.count("\n")
                    at["end"] = first + max(old[0].count("\n"), typed.count("\n"))
                    at["from"] = first
                    if new is not None and len(text) <= PREVIEW_MAX:
                        at["text"] = text[:i] + typed + text[i + len(old[0]):]
        changed = (self.now or {}).get("line") != at["line"] or (self.now or {}).get("path") != rel or at["text"] is not None
        self.now = at
        return changed

    def landed(self):
        """The tool ran (its result came back): the file on disk is the truth again, the cursor stays where it was."""
        if self.now and self.now.get("text") is not None:
            self.now = {**self.now, "text": None}
            return True
        return False

    def at(self):
        return self.now


def _watched(cmd, folder, env, jid):
    """Runs it like subprocess.run, and keeps its latest steps in LIVE while it works."""
    LIVE[jid] = []
    seen = Presence(folder)
    p = subprocess.Popen(cmd, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    lines, errors = [], []
    reader = threading.Thread(target=lambda: errors.append(p.stderr.read()), daemon=True)
    reader.start()
    timer = threading.Timer(TIMEOUT, p.kill)
    timer.start()
    try:
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "stream_event":  # the partial chunks: only for the live position, never kept
                if seen.feed(ev):
                    AT[jid] = seen.at()
                continue
            if ev.get("type") == "user" and seen.landed():
                AT[jid] = seen.at()
            lines.append(line)
            LIVE[jid] = (LIVE[jid] + _step(folder, line))[-40:]
        p.wait()
    finally:
        expired = not timer.is_alive()
        timer.cancel()
        LIVE.pop(jid, None)
        AT.pop(jid, None)
    if expired and p.returncode != 0:
        raise subprocess.TimeoutExpired(cmd, TIMEOUT)
    reader.join(timeout=5)
    return subprocess.CompletedProcess(cmd, p.returncode, "".join(lines), "".join(errors))


def changes(name):
    """For the workspace view, asked every two seconds: the files with their times, and what a running Claude Code is doing."""
    name, path = _project_dir(name)
    files = []
    for dirpath, dirs, fnames in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules")]
        for f in fnames:
            if not f.startswith("."):
                full = os.path.join(dirpath, f)
                try:
                    files.append({"path": os.path.relpath(full, path), "size": os.path.getsize(full), "modified": os.path.getmtime(full)})
                except OSError:
                    pass  # gone in this moment
    files.sort(key=lambda f: f["path"].lower())
    job = db.q("SELECT id FROM work_jobs WHERE lower(project)=lower(?) AND status='running' ORDER BY created DESC LIMIT 1", (name,), one=True)
    return {"files": files, "running": bool(job), "live": LIVE.get(job["id"], []) if job else [],
            "at": AT.get(job["id"]) if job else None}


class Changed(ValueError):
    """The file on disk is newer than the one you were editing."""


def save_file(name, rel, text, seen=None):
    """You save a file in the workspace view. Only inside this project, never a hidden file, and never over a newer version on disk
    (the agent may have changed it meanwhile) unless you say so (seen=None)."""
    name, path = _project_dir(name)
    rel = str(rel or "").strip().lstrip("/")
    full = os.path.realpath(os.path.join(path, rel))
    parts = os.path.relpath(full, path).split(os.sep)
    if not rel or not full.startswith(path + os.sep) or any(p.startswith(".") for p in parts):
        raise ValueError("That's not a file in this project.")
    if os.path.isdir(full):
        raise ValueError("That's a folder.")
    if len(text.encode()) > 2_000_000:
        raise ValueError("Too large to save here.")
    if seen is not None and os.path.exists(full) and os.path.getmtime(full) > float(seen) + 0.0005:
        raise Changed("It was changed on disk since you opened it.")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    tmp = full + ".amadeus-saving"
    Path(tmp).write_text(text)
    os.replace(tmp, full)
    return {"path": os.path.relpath(full, path), "modified": os.path.getmtime(full)}


def _json_line(line):
    try:
        o = json.loads(line)
        return o if isinstance(o, dict) else {}
    except ValueError:
        return {}


def _run(jid, task, resume):
    j = _job(jid)
    cmd = ["claude", "-p", task, "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--model", MODEL, "--effort", EFFORT,
           "--settings", os.path.join(GUARD, "settings.json"), "--permission-mode", "acceptEdits",
           "--allowedTools", TOOLS, "--append-system-prompt", RULES]
    if resume:
        cmd += ["--resume", resume]
    env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    summary, sid, cost, ok = "", resume, None, False
    try:
        p = _watched(cmd, j["folder"], env, jid)
        out = next((o for o in (_json_line(x) for x in reversed(p.stdout.strip().splitlines())) if o.get("type") == "result"), {})
        sid = out.get("session_id") or sid
        cost = out.get("total_cost_usd")
        summary = (out.get("result") or "").strip() or (p.stderr.strip()[-1500:] or "The run ended without a reply.")
        ok = p.returncode == 0 and not out.get("is_error")
        if not ok and SIGNED_OUT.search(summary):
            db.set_setting("claude_signed_out", True)
            summary = ("Claude Code needs you to sign in again, so it didn't start. Go to Settings → Connectors → Claude Code, "
                       "then say \"continue\" here. Nothing was changed.\n\n(" + summary[:300] + ")")
        elif ok:
            db.set_setting("claude_signed_out", False)
    except subprocess.TimeoutExpired:
        summary = f"The run took longer than {TIMEOUT // 60} minutes and was stopped. Say \"continue project {j['project']}\" to pick it up."
    except Exception as e:
        summary = f"The run failed: {e}"
    db.q("UPDATE work_jobs SET status=?, session_id=?, finished=?, summary=?, cost=? WHERE id=?",
         ("done" if ok else "failed", sid, time.time(), summary[:20000], cost, jid))
    head = f"{j['project']}: " + ("questions for you" if "## Questions" in summary else "done" if ok else "stopped")
    if j["conversation_id"]:
        db.add_message(j["conversation_id"], "assistant",
                       f"**{j['project']}** ({'finished' if ok else 'stopped'}):\n\n{summary}", {"mood": "normal"})
    events.add("work" if ok else "job_failed", head, summary[:600], cid=j["conversation_id"] or "")


def status():
    rows = db.q("SELECT * FROM work_jobs ORDER BY created DESC LIMIT 10")
    if not rows:
        return "No work runs yet."
    return "\n".join(f"- **{r['project']}** · {r['status']} · {time.strftime('%a %d %b %H:%M', time.localtime(r['created']))}"
                     + (f" · session `{r['session_id']}`" if r["session_id"] else "") for r in rows)


# ---------- projects (the dashboard's Projects page): one folder each in your projects folder ----------
def _projects_root():
    root = projects_dir(CFG)
    os.makedirs(root, exist_ok=True)
    return root


def _project_dir(name):
    root = os.path.realpath(_projects_root())
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root or not os.path.isdir(path):
        raise ValueError("Project not found")
    return os.path.basename(path), path


def project_chat(name, create=True):
    """Amadeus's conversation about one project (shown on its page next to the Claude Code runs)."""
    title = f"🗂️ {name}"
    c = db.q("SELECT id FROM conversations WHERE title=?", (title,), one=True)
    if c or not create:
        return c["id"] if c else None
    cid = db.new_id()
    db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)",
         (cid, title, CFG["default_model"], time.time(), time.time()))
    return cid


def project_of_chat(cid):
    c = db.q("SELECT title FROM conversations WHERE id=?", (cid,), one=True)
    return c["title"][3:] if c and c["title"].startswith("🗂️ ") else None


def _asks(summary):
    """The run ended with questions for you (a line that ends in a question mark near the end)."""
    return bool(re.search(r"\?\s*(\*+)?\s*$", summary[-800:], re.M))


def state(name, last=None):
    """needs (amber: a run asked you something), active (Claude Code is working), idle, done (you closed it)."""
    if name.lower() in {n.lower() for n in db.get_setting("projects_done", [])}:
        return "done"
    if last is None:
        last = db.q("SELECT status, created, finished, summary FROM work_jobs WHERE lower(project)=lower(?) ORDER BY created DESC LIMIT 1",
                    (name,), one=True)
    if not last:
        return "idle"
    if last["status"] == "running":
        return "active"
    if last["status"] == "done" and _asks(last.get("summary") or ""):
        cid = project_chat(name, create=False)
        later = cid and db.q("SELECT id FROM messages WHERE conversation_id=? AND role='user' AND created>?",
                             (cid, last.get("finished") or last["created"]))
        return "idle" if later else "needs"
    return "idle"


def set_done(name, done):
    name, _ = _project_dir(name)
    keep = [n for n in db.get_setting("projects_done", []) if n.lower() != name.lower()]
    db.set_setting("projects_done", keep + ([name] if done else []))
    return {"name": name, "state": state(name)}


def projects():
    out = []
    for name in sorted(os.listdir(_projects_root()), key=str.lower):
        path = os.path.join(_projects_root(), name)
        if not os.path.isdir(path) or name.startswith("."):
            continue
        last = db.q("SELECT status, created, finished, summary FROM work_jobs WHERE lower(project)=lower(?) ORDER BY created DESC LIMIT 1",
                    (name,), one=True)
        files = [f for f in os.listdir(path) if not f.startswith(".") and f != "__pycache__"]
        out.append({"name": name, "files": len(files), "status": last["status"] if last else None,
                    "last_run": last["created"] if last else None, "state": state(name, last),
                    "updated": max([os.path.getmtime(os.path.join(path, f)) for f in files] or [os.path.getmtime(path)])})
    return sorted(out, key=lambda p: p["updated"], reverse=True)


def project(name):
    name, path = _project_dir(name)
    files = []
    for dirpath, dirs, fnames in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in fnames:
            if f.startswith("."):
                continue
            full = os.path.join(dirpath, f)
            files.append({"path": os.path.relpath(full, path), "size": os.path.getsize(full), "modified": os.path.getmtime(full)})
    files.sort(key=lambda f: f["path"].lower())
    overview = ""
    if os.path.isfile(os.path.join(path, "Overview.md")):
        overview = Path(os.path.join(path, "Overview.md")).read_text(errors="replace")[:20000]
    runs = db.q("SELECT id, status, created, finished, task, summary, cost FROM work_jobs WHERE lower(project)=lower(?) "
                "ORDER BY created", (name,))
    cid = project_chat(name, create=False)
    msgs = [{"role": m["role"], "content": m["content"], "created": m["created"]}
            for m in (db.messages(cid) if cid else []) if m["role"] in ("user", "assistant") and m["content"].strip()]
    return {"name": name, "files": files, "overview": overview, "runs": runs, "chat": cid, "messages": msgs,
            "running": any(r["status"] == "running" for r in runs), "state": state(name)}


def project_file(name, rel):
    name, path = _project_dir(name)
    full = os.path.realpath(os.path.join(path, rel))
    if not full.startswith(path + os.sep) or not os.path.isfile(full):
        raise ValueError("File not found")
    if os.path.getsize(full) > 2_000_000:
        raise ValueError("Too large to show here; open it in an editor.")
    data = Path(full).read_bytes()
    try:
        return {"path": rel, "text": data.decode("utf-8"), "modified": os.path.getmtime(full)}
    except UnicodeDecodeError:
        return {"path": rel, "binary": True}


def new_project(name, goal=""):
    """Your own new project: its folder and Overview.md, nothing sent anywhere yet."""
    name = re.sub(r"[\\/:*?\"<>|\x00]", "-", name).strip(" .-")[:80]
    if not name:
        raise ValueError("Give the project a name")
    name, folder = _folder(name)
    ov = os.path.join(folder, "Overview.md")
    if not os.path.exists(ov):
        with open(ov, "w") as f:
            f.write(f"# {name}\n\n_Started {time.strftime('%d %b %Y')}_\n\n{goal.strip()}\n")
    return {"name": name}


# ---------- where the projects live (you choose it in the Projects view or with ./install.sh --setup) ----------
def _private():
    v = os.path.realpath(CFG["notes_root"])
    return v if os.path.isdir(v) else ""


def folder_info():
    root, private = projects_dir(CFG), _private()
    names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith(".")] if os.path.isdir(root) else []
    return {"path": root, "in_notes": bool(private) and (root + os.sep).startswith(private + os.sep), "projects": sorted(names, key=str.lower)}


def set_folder(path, move=False):
    """Use another folder for the projects. move=True also moves the existing ones (and their Claude Code sessions,
    so "continue" keeps working); without it they stay where they are, untouched. The guard is rewritten for it."""
    from . import workguard
    from .config import CONFIG_PATH
    new = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    private, old, home = _private(), projects_dir(CFG), os.path.realpath(os.path.expanduser("~"))
    if not str(path or "").strip() or new in ("/", home) or not (new + os.sep).startswith(home + os.sep):
        raise ValueError("Pick a folder inside your home folder, for example ~/Amadeus/Projects.")
    if private and (new + os.sep).startswith(private + os.sep):
        raise ValueError("That's inside your notes. Projects get their own folder, so a work run never sees your notes.")
    if any(f["status"] == "running" for f in running()):
        raise ValueError("A work run is still going. Change the folder when it's done.")
    os.makedirs(new, exist_ok=True)
    moved = []
    if move and new != old and os.path.isdir(old):
        clash = [n for n in folder_info()["projects"] if os.path.exists(os.path.join(new, n))]
        if clash:
            raise ValueError("The new folder already has a project named " + ", ".join(clash) + ".")
        sessions = os.path.join(home, ".claude", "projects")
        key = lambda p: re.sub(r"[^A-Za-z0-9]", "-", p)
        import shutil
        for n in folder_info()["projects"]:
            src, dst = os.path.join(old, n), os.path.join(new, n)
            shutil.move(src, dst)  # a rename on the same disk, else copy then remove
            db.q("UPDATE work_jobs SET folder=? WHERE folder=?", (dst, src))
            s_old, s_new = os.path.join(sessions, key(src)), os.path.join(sessions, key(dst))
            if os.path.isdir(s_old) and not os.path.exists(s_new):
                os.rename(s_old, s_new)
            moved.append(n)
    c = json.loads(Path(CONFIG_PATH).read_text()) if os.path.exists(CONFIG_PATH) else {}
    c["projects_dir"] = new
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(c, f, indent=2)
    CFG["projects"] = new
    workguard.install(new, private)
    return {**folder_info(), "moved": moved}
