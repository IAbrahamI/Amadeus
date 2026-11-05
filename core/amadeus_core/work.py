"""Work in the cloud, the light way: one Claude Code run per task.

Amadeus filters the task and you approve it (tools.send_to_work / the new-project playbook); then one `claude -p` run
works in the project's folder (<your projects folder>/<Name>/, outside your vault), on your Claude subscription. No coordinator, no agents
waking each other. When it finishes the assistant tells you (a notification, and the result in the chat it came from).

Guard rails (~/.local/share/amadeus/work-guard, read-only, see workguard.py): the run may write only in your projects
folder (PreToolUse hook + Claude Code's sandbox for shell commands), and never reads your vault, Amadeus's own data,
mail, chats or keys. It can't ask you mid-run: missing facts come back as "## Questions"; your answers continue the same
session (continue_project). Every run is a normal Claude Code session, so you can also resume it yourself:
`cd "<projects folder>/<Name>" && claude --resume <session>`."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from . import db, events
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

GUARD = os.path.expanduser("~/.local/share/amadeus/work-guard")
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
    cmd = ["kitty", "--directory", path, "claude"] + (["--resume", last["session_id"]] if last else [])
    tools.launch(cmd, "claude")
    tools._to_front(["kitty"])
    return {"ok": True, "resumed": bool(last)}


def running():
    return db.q("SELECT * FROM work_jobs WHERE status='running' ORDER BY created")


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


def _run(jid, task, resume):
    j = _job(jid)
    cmd = ["claude", "-p", task, "--output-format", "json", "--model", MODEL, "--effort", EFFORT,
           "--settings", os.path.join(GUARD, "settings.json"), "--permission-mode", "acceptEdits",
           "--allowedTools", TOOLS, "--append-system-prompt", RULES]
    if resume:
        cmd += ["--resume", resume]
    env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    summary, sid, cost, ok = "", resume, None, False
    try:
        p = subprocess.run(cmd, cwd=j["folder"], capture_output=True, text=True, timeout=TIMEOUT, env=env)
        out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
        sid = out.get("session_id") or sid
        cost = out.get("total_cost_usd")
        summary = (out.get("result") or "").strip() or (p.stderr.strip()[-1500:] or "The run ended without a reply.")
        ok = p.returncode == 0 and not out.get("is_error")
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
        return {"path": rel, "text": data.decode("utf-8")}
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
def _vault():
    v = os.path.realpath(CFG["vault_dir"])
    return os.path.dirname(v) if os.path.isdir(v) else ""


def folder_info():
    root, vault = projects_dir(CFG), _vault()
    names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith(".")] if os.path.isdir(root) else []
    return {"path": root, "in_vault": bool(vault) and (root + os.sep).startswith(vault + os.sep), "projects": sorted(names, key=str.lower)}


def set_folder(path, move=False):
    """Use another folder for the projects. move=True also moves the existing ones (and their Claude Code sessions,
    so "continue" keeps working); without it they stay where they are, untouched. The guard is rewritten for it."""
    from . import workguard
    from .config import CONFIG_PATH
    new = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    vault, old, home = _vault(), projects_dir(CFG), os.path.realpath(os.path.expanduser("~"))
    if not str(path or "").strip() or new in ("/", home) or not (new + os.sep).startswith(home + os.sep):
        raise ValueError("Pick a folder inside your home folder, for example ~/Amadeus/Projects.")
    if vault and (new + os.sep).startswith(vault + os.sep):
        raise ValueError("That's inside your Obsidian vault. Projects get their own folder, so a work run never sees your notes.")
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
    CFG["projects_dir"] = new
    workguard.install(new, vault)
    return {**folder_info(), "moved": moved}
