"""Background jobs: due reminders (desktop notification + Reminders chat) and results coming back from work."""
import datetime
import json
import os
import subprocess
import threading
import re
import time
import urllib.request

from . import agenda, db, digest, events, learning, llm, mailwatch, quickchat, tools
from .config import CFG



def check_reminders():
    for r in db.q("SELECT * FROM reminders WHERE active=1 AND next_run IS NOT NULL AND next_run<=?", (time.time(),)):
        m = re.search(r"\s*\[mail:(\d+)\]", r["text"])  # a reminder about a mail: the call opens that mail
        events.add("reminder", r["text"].replace(m.group(0), "") if m else r["text"], ref=f"mail:{m.group(1)}" if m else "")
        nxt = tools.next_run(r["schedule"], after=time.time())
        db.q("UPDATE reminders SET next_run=?, active=? WHERE id=?", (nxt, 1 if nxt else 0, r["id"]))


IDLE_SEC = 15 * 60
PRESIDIO_STAMP = os.path.expanduser("~/.local/share/amadeus/presidio-last-used")


def idle_stop():
    """Stop Presidio (the privacy filter's helper) after 15 minutes without use."""
    now = time.time()
    try:
        idle = now - os.path.getmtime(PRESIDIO_STAMP) > IDLE_SEC
    except OSError:
        idle = True
    if idle:
        r = subprocess.run(["docker", "ps", "-q", "--filter", "name=presidio-"], capture_output=True, text=True, timeout=30)
        if r.stdout.strip():
            subprocess.run(["docker", "stop", "presidio-analyzer", "presidio-anonymizer"], capture_output=True, timeout=120)
            print("stopped idle Presidio", flush=True)


# Scheduled jobs (systemd user timers). These call you when they finish; every other job only when it fails.
JOB_CALLS = {"amadeus-leak-scan": "The nightly leak scan finished."}
_job_seen = {}


def check_jobs():
    timers = subprocess.run(["systemctl", "--user", "list-unit-files", "amadeus-*.timer", "--no-legend", "--plain"],
                            capture_output=True, text=True, timeout=20).stdout.split()
    units = [t[:-6] + ".service" for t in timers if t.endswith(".timer")]
    if not units:
        return
    out = subprocess.run(["systemctl", "--user", "show", "-p", "Id,Result,ExecMainExitTimestampMonotonic", *units],
                         capture_output=True, text=True, timeout=20).stdout
    for block in out.strip().split("\n\n"):
        f = dict(l.split("=", 1) for l in block.splitlines() if "=" in l)
        uid, ts, res = f.get("Id", ""), f.get("ExecMainExitTimestampMonotonic", "0"), f.get("Result", "")
        first = uid not in _job_seen
        if _job_seen.get(uid) == ts:
            continue
        _job_seen[uid] = ts
        if first or ts in ("", "0"):
            continue  # only runs that finish while Amadeus is running
        name = uid[:-8]
        if res != "success":
            log = subprocess.run(["journalctl", "--user", "-u", uid, "-n", "4", "-o", "cat", "--no-pager"],
                                 capture_output=True, text=True, timeout=20).stdout
            events.add("job_failed", f"{name.replace('amadeus-', '').replace('-', ' ')} failed ({res})", log)
        elif name in JOB_CALLS:
            log = subprocess.run(["journalctl", "--user", "-u", uid, "-n", "3", "-o", "cat", "--no-pager"],
                                 capture_output=True, text=True, timeout=20).stdout
            events.add("job", JOB_CALLS[name], log)


def check_calendar():
    for o in agenda.due_alerts():
        s, ad = agenda.parse(o["occ_start"], o["all_day"])
        when = "today" if ad else ("now" if s <= datetime.datetime.now() else f"at {s:%H:%M}")
        events.add("calendar", f"{o['title']} {when}" + (f" @ {o['location']}" if o.get("location") else ""), o.get("notes", ""))


# Apps Amadeus needs running in the background: (how to see it runs, how to start it hidden)
KEEP_APPS = {
    "thunderbird": (["pgrep", "-x", "thunderbird"], [os.path.expanduser("~/.local/bin/amadeus-mail-start")]),
}
_apps = {}


def keep_apps():
    """Thunderbird must run for Amadeus to see mail: if it was closed, start it again hidden after a minute (so a quick restart by you isn't interrupted). After Thunderbird comes back,
    check the mail that came in meanwhile."""
    import shutil
    from . import mailbridge
    if not mailbridge.configured():
        return
    now = time.time()
    for name in CFG.get("keep_running", ["thunderbird"]):
        if name not in KEEP_APPS or not shutil.which(name if name != "thunderbird" else "thunderbird"):
            continue
        check, start = KEEP_APPS[name]
        st = _apps.setdefault(name, {"missing_since": 0, "restarted": 0})
        if subprocess.run(check, capture_output=True).returncode == 0:
            st["missing_since"] = 0
            if name == "thunderbird" and st["restarted"] and now - st["restarted"] > 60:
                st["restarted"] = 0
                threading.Thread(target=mailwatch.check, kwargs={"force": True}, daemon=True).start()
            continue
        if not st["missing_since"]:
            st["missing_since"] = now
            continue
        if now - st["missing_since"] < 60:
            continue
        print(f"{name} was closed: starting it again in the background", flush=True)
        try:
            tools.launch(start, name)
        except Exception as e:
            print(f"could not start {name}:", e, flush=True)
        st["missing_since"], st["restarted"] = 0, now


def clean_reports():
    """The leak-scan log keeps the last `leak_scan_days` (30) nights. Runs once a day."""
    today = datetime.date.today().isoformat()
    if db.get_setting("reports_cleaned", "") == today:
        return
    db.set_setting("reports_cleaned", today)
    base = os.path.join(CFG["data_dir"], "reports")
    log = os.path.join(base, "logs", "leak-scan.md")
    if os.path.exists(log):
        lines = open(log).read().splitlines()
        entries = [i for i, l in enumerate(lines) if l.startswith("- 20")]
        keep = CFG.get("leak_scan_days", 30)
        if len(entries) > keep:
            with open(log, "w") as f:
                f.write("\n".join(lines[entries[-keep]:]) + "\n")


WEEK_CID = "week"


def check_week_ahead():
    """Sunday evening: Amadeus prepares the week-ahead overview (skill "week-ahead") and calls you with it."""
    now = datetime.datetime.now()
    if now.weekday() != 6 or now.hour < CFG.get("week_ahead_hour", 19) or db.get_setting("week_ahead_last", "") == now.date().isoformat():
        return
    db.set_setting("week_ahead_last", now.date().isoformat())
    if "week-ahead" in db.get_setting("skills_off", []):
        return
    threading.Thread(target=_week_ahead, daemon=True).start()


def _week_ahead():
    from . import agent
    if not db.q("SELECT id FROM conversations WHERE id=?", (WEEK_CID,), one=True):
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)",
             (WEEK_CID, "📅 Week ahead", CFG["default_model"], db.now(), db.now()))
    from . import playbooks
    try:
        last = playbooks.week_ahead(WEEK_CID)
    except Exception as e:
        events.add("job_failed", "week ahead failed", str(e))
        return
    db.add_message(WEEK_CID, "assistant", last, {"mood": "normal"})
    events.add("job", "Your week ahead is ready.", last[:600], cid=WEEK_CID)


def loop():
    while True:
        for job in (check_reminders, check_calendar, keep_apps, mailwatch.check, check_jobs,
                    check_week_ahead, digest.check_morning, digest.check, quickchat.check, learning.check, clean_reports, events.maybe_ring, idle_stop, llm.free_gpu):
            try:
                job()
            except Exception as e:
                print("background error:", job.__name__, e, flush=True)
        time.sleep(30)


def start():
    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=mailwatch.watch, daemon=True).start()
