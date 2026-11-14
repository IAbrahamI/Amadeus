"""Amadeus' own project: what it would like to do better, worked on by Claude Code, installed only with your OK.

1. Ideas: Amadeus notes what it would like to improve, each with its reason (the suggest_improvement tool, when it
   notices it couldn't do something well), and you can add your own. Nothing happens with them by itself.
2. You pick one. Claude Code then works on a copy of Amadeus' code ("Amadeus itself/code" in your projects folder,
   a git clone of the running install's last commit), never on the running install: the work guard keeps it inside
   the projects folder. What leaves the PC is shown first and goes through the privacy filter, like every work run.
3. Review: the change (a diff) and a test run Amadeus does itself on the copy, not Claude's word for it.
4. Install: only when you press it, only with the tests passing, and only onto a clean running install. The change
   is committed there under your own git name and Amadeus restarts. Discard throws the copy's change away.

Only for an install from git (./install.sh); a packaged or Mac app install updates through its releases."""
import hashlib
import os
import re
import subprocess
import threading
import time

from . import db, system, updates

PROJECT = "Amadeus itself"
KEY = "improve_ideas"
MAX_IDEAS = 60
TEST_TIMEOUT = 900
NOT_CODE = [":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc"]  # what running the code leaves behind is no change
_lock = threading.RLock()

BRIEF = """You are improving Amadeus, a private local assistant, from the inside: this project's folder holds a copy of
its code in code/ (a git clone; the running install is elsewhere and you can't reach it). Make exactly this improvement:

## {title}

Why: {why}

How to work:
- Change only files inside code/. Read code/README.md and code/docs/ARCHITECTURE.md first, then only what you need.
- Keep to the code's own style: small, clear, comments that explain why. No new dependencies unless unavoidable.
- Add or adjust tests in code/core/tests/ for what you change, and run them: cd code/core && python3 -m unittest
- Update the docs (code/docs/, code/README.md) where the behaviour a user sees changes.
- Do not commit, push or change git settings: leave your changes in the working tree. The user reviews the diff and
  installs it.
- If the improvement isn't possible or would be unsafe, change nothing and explain why.

Your final reply: in a few lines what you changed and why, which files, and the test result."""


def ideas():
    return db.get_setting(KEY, [])


def _save(items):
    db.set_setting(KEY, items[-MAX_IDEAS:])


def _idea(idea_id):
    for i in ideas():
        if i["id"] == idea_id:
            return i
    raise ValueError("That idea isn't on the list any more.")


def _update(idea_id, **fields):
    with _lock:
        items = ideas()
        for i in items:
            if i["id"] == idea_id:
                i.update(fields)
        _save(items)


def add_idea(title, why, source="amadeus"):
    """A note of what to improve. The same idea twice is kept once (its reason is added to the first)."""
    title, why = re.sub(r"\s+", " ", str(title or "")).strip()[:120], str(why or "").strip()[:1200]
    if len(title) < 4:
        raise ValueError("Say in a few words what to improve.")
    with _lock:
        items = ideas()
        same = next((i for i in items if i["title"].casefold() == title.casefold() and i["status"] in ("open", "working", "ready")), None)
        if same:
            if why and why not in same["why"]:
                same["why"] = (same["why"] + "\n" + why).strip()[:2000]
            _save(items)
            return same
        idea = {"id": db.new_id()[:12], "title": title, "why": why, "source": source, "created": time.time(), "status": "open"}
        _save(items + [idea])
        return idea


def drop_idea(idea_id):
    i = _idea(idea_id)
    if i["status"] in ("working", "ready"):
        raise ValueError("Discard its change first.")
    with _lock:
        _save([x for x in ideas() if x["id"] != idea_id])
    return {"ok": True}


# ---------- the copy ----------
def _git(args, cwd, timeout=120, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"git {args[0]}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout


def _code():
    from . import work
    return os.path.join(work._folder(PROJECT)[1], "code")


def available():
    """"" when it can be used here, else why not."""
    from . import work
    if updates.mode() != "git":
        return "Only for an install from git (./install.sh). This one updates through its releases."
    if not work.claude_path():
        return "Needs Claude Code: Settings → Connectors → Claude Code."
    return ""


def _fresh_copy():
    """The copy at the running install's last commit, with nothing else in it. Returns that commit."""
    base = _git(["rev-parse", "HEAD"], updates.ROOT).strip()
    code = _code()
    if not os.path.isdir(os.path.join(code, ".git")):
        _git(["clone", "--quiet", "--no-hardlinks", updates.ROOT, code], os.path.dirname(code), timeout=600)
    _git(["fetch", "--quiet", updates.ROOT, "HEAD"], code, timeout=600)
    _git(["checkout", "--quiet", "--detach", base], code)
    _git(["reset", "--quiet", "--hard", base], code)
    _git(["clean", "-qfdx"], code)
    return base


def _busy():
    return next((i for i in ideas() if i["status"] in ("working", "ready")), None)


def brief(idea_id):
    i = _idea(idea_id)
    return BRIEF.format(title=i["title"], why=i["why"] or "(no reason given)")


def start(idea_id, text):
    """You picked this idea: a fresh copy, then one Claude Code run with text (the brief after the privacy filter,
    exactly what you saw)."""
    from . import work
    why = available()
    if why:
        raise ValueError(why)
    other = _busy()
    if other and other["id"] != idea_id:
        raise ValueError(f"“{other['title']}” is still {'being worked on' if other['status'] == 'working' else 'waiting for your review'}: "
                         "install or discard it first.")
    _idea(idea_id)
    base = _fresh_copy()
    _overview()
    r = work.start(PROJECT, text, work.project_chat(PROJECT))
    if isinstance(r, str):
        raise ValueError(r)
    _update(idea_id, status="working", base=base, job=r[0], started=time.time(), review=None)
    _overview()
    return {"ok": True, "project": PROJECT}


def _job_done(i):
    j = db.q("SELECT status, summary FROM work_jobs WHERE id=?", (i.get("job"),), one=True)
    return j and j["status"] != "running", j


def refresh():
    """A finished run moves its idea on to your review."""
    for i in ideas():
        if i["status"] == "working":
            done, j = _job_done(i)
            if done:
                _update(i["id"], status="ready", report=(j["summary"] or "")[:6000], run_ok=j["status"] == "done")
    return ideas()


def _diff(i):
    code = _code()
    _git(["add", "-A", "--intent-to-add", "--", ".", *NOT_CODE], code)  # new files show up in the diff too
    return _git(["diff", "--binary", i["base"], "--", ".", *NOT_CODE], code, timeout=60)


def review(idea_id):
    """The change and a test run on the copy, by Amadeus itself. Cached until the change itself changes."""
    refresh()
    i = _idea(idea_id)
    if i["status"] != "ready":
        raise ValueError("Nothing to review yet.")
    diff = _diff(i)
    stat = _git(["diff", "--stat", i["base"], "--", ".", *NOT_CODE], _code(), timeout=60).strip()
    key = hashlib.sha256(diff.encode()).hexdigest()
    if (i.get("review") or {}).get("key") == key:
        return {**i["review"], "diff": diff}
    if not diff.strip():
        r = {"key": key, "stat": "", "tests_ok": False, "tests": "No change was made."}
    else:
        env = {**{k: v for k, v in os.environ.items() if not k.startswith("AMADEUS_")}, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            p = subprocess.run(["python3", "-m", "unittest"], cwd=os.path.join(_code(), "core"), capture_output=True, text=True,
                               timeout=TEST_TIMEOUT, env=env)
            tail = (p.stderr or p.stdout).strip().splitlines()
            r = {"key": key, "stat": stat, "tests_ok": p.returncode == 0, "tests": "\n".join(tail[-25:])}
        except subprocess.TimeoutExpired:
            r = {"key": key, "stat": stat, "tests_ok": False, "tests": f"The tests didn't finish within {TEST_TIMEOUT // 60} minutes."}
    _update(idea_id, review=r)
    return {**r, "diff": diff}


def install(idea_id):
    """Your OK: the reviewed change goes into the running install as one commit under your git name, then Amadeus
    restarts. Refused if the tests failed, the change differs from what was reviewed, or the install has changes of
    its own that aren't committed (they'd be mixed in)."""
    i = _idea(idea_id)
    r = i.get("review") or {}
    diff = _diff(i) if i["status"] == "ready" else ""
    if not diff.strip() or r.get("key") != hashlib.sha256(diff.encode()).hexdigest():
        raise ValueError("Review the change first (it changed since, or there is none).")
    if not r.get("tests_ok"):
        raise ValueError("The tests didn't pass, so it isn't installed.")
    root = updates.ROOT
    if _git(["status", "--porcelain", "--untracked-files=no"], root).strip():
        raise ValueError("The running install has changes that aren't committed. Commit or put them aside first.")
    with _lock:
        p = subprocess.run(["git", "apply", "--index", "--3way", "--whitespace=nowarn", "-"], cwd=root, input=diff,
                           capture_output=True, text=True, timeout=120)
        if p.returncode:
            _git(["reset", "--quiet", "--hard", "HEAD"], root, check=False)
            raise ValueError("Amadeus changed since the copy was made and the change doesn't fit any more. Start it again.")
        msg = f"{i['title']}\n\n{i['why']}".strip()
        c = subprocess.run(["git", "commit", "--quiet", "-F", "-"], cwd=root, input=msg, capture_output=True, text=True, timeout=60)
        if c.returncode:
            _git(["reset", "--quiet", "--hard", "HEAD"], root, check=False)
            raise ValueError("Couldn't commit it: " + (c.stderr or c.stdout).strip()[:200])
        commit = _git(["rev-parse", "--short", "HEAD"], root).strip()
        _update(idea_id, status="installed", installed=time.time(), commit=commit)
    _overview()
    _restart_soon()
    return {"ok": True, "commit": commit}


def _restart_soon():
    """A moment after the answer went out, so the page hears it was installed."""
    def later():
        time.sleep(1.5)
        system.restart("amadeus-core", "amadeus-desktop")
    threading.Thread(target=later, daemon=True).start()


def discard(idea_id):
    """The copy's change is thrown away; the idea goes back on the list."""
    i = _idea(idea_id)
    if i["status"] == "working":
        raise ValueError("Claude Code is still working on it.")
    if os.path.isdir(os.path.join(_code(), ".git")) and i.get("base"):
        _git(["reset", "--quiet", "--hard", i["base"]], _code())
        _git(["clean", "-qfdx"], _code())
    _update(idea_id, status="open", review=None, job=None)
    _overview()
    return {"ok": True}


def _overview():
    """The project's Overview.md: what's on the list and where each idea is."""
    from . import work
    folder = work._folder(PROJECT)[1]
    label = {"open": "on the list", "working": "Claude Code is working on it", "ready": "waiting for your review",
             "installed": "installed"}
    lines = [f"# {PROJECT}", "", "What Amadeus would like to do better. You pick one; Claude Code works on a copy of the code in",
             "`code/`, never on the running install; you review the change and the tests, and only your OK installs it.", ""]
    for i in ideas():
        lines.append(f"- **{i['title']}** ({label.get(i['status'], i['status'])}{', commit ' + i['commit'] if i.get('commit') else ''})")
        if i["why"]:
            lines.append(f"  {i['why'].splitlines()[0][:200]}")
    with open(os.path.join(folder, "Overview.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def suggest(title, why):
    """The tool: Amadeus notes an improvement for its own project (nothing starts by itself)."""
    i = add_idea(title, why, "amadeus")
    return f"Noted for my own project: “{i['title']}”. You can pick it under Projects → {PROJECT} whenever you like."
