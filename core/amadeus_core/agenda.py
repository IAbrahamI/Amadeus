"""Local calendar shared by you and Amadeus. Stored in the Amadeus database (never leaves the PC).
Times are local wall-clock time: 'YYYY-MM-DDTHH:MM', or 'YYYY-MM-DD' for all-day events.
A repeating event is one series; editing it edits the whole series. Single days of a series can be skipped (then a
separate one-off event takes that day: "only this week"), and a series can be split ("from next week on")."""
import datetime as dt

from . import db

db.q("""CREATE TABLE IF NOT EXISTS cal_events (id TEXT PRIMARY KEY, title TEXT, start TEXT, end TEXT, all_day INTEGER,
        location TEXT, notes TEXT, repeat TEXT, repeat_until TEXT, alert INTEGER, created_by TEXT, created REAL, updated REAL)""")
db.q("CREATE TABLE IF NOT EXISTS cal_alerts (key TEXT PRIMARY KEY, fired REAL)")
try:
    db.q("ALTER TABLE cal_events ADD COLUMN skip TEXT DEFAULT ''")  # dates (YYYY-MM-DD, comma separated) left out of a series
except Exception:
    pass

REPEATS = ("", "daily", "weekdays", "weekly", "monthly", "yearly")
FIELDS = ("title", "start", "end", "all_day", "location", "notes", "repeat", "repeat_until", "alert")


def parse(value, all_day=False):
    """Accepts 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DDTHH:MM'. Returns (datetime, all_day)."""
    v = (value or "").strip().replace(" ", "T")
    if len(v) == 10:
        return dt.datetime.strptime(v, "%Y-%m-%d"), True
    return dt.datetime.strptime(v[:16], "%Y-%m-%dT%H:%M"), bool(all_day)


def fmt(d, all_day):
    return d.strftime("%Y-%m-%d") if all_day else d.strftime("%Y-%m-%dT%H:%M")


def _clean(fields, old=None):
    e = dict(old or {"title": "", "end": "", "all_day": 0, "location": "", "notes": "", "repeat": "", "repeat_until": "",
                     "alert": 15})
    e.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
    if not str(e.get("title", "")).strip():
        raise ValueError("An event needs a title.")
    start, all_day = parse(e["start"], int(e.get("all_day") or 0))
    end = parse(e["end"], all_day)[0] if e.get("end") else start + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
    if end <= start:
        end = start + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
    if e.get("repeat", "") not in REPEATS:
        raise ValueError(f"repeat must be one of: {', '.join(r or 'none' for r in REPEATS)}")
    e.update(title=str(e["title"]).strip()[:200], start=fmt(start, all_day), end=fmt(end, all_day), all_day=int(all_day),
             alert=int(e["alert"]) if str(e.get("alert", "")).lstrip("-").isdigit() else -1)
    return e


def add(fields, by="you"):
    e = _clean(fields)
    e["id"] = db.new_id()
    db.q("INSERT INTO cal_events(id,title,start,end,all_day,location,notes,repeat,repeat_until,alert,created_by,created,updated)"
         " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (e["id"], e["title"], e["start"], e["end"], e["all_day"], e["location"],
                                               e["notes"], e["repeat"], e["repeat_until"], e["alert"], by, db.now(), db.now()))
    return get(e["id"])


def get(eid):
    return db.q("SELECT * FROM cal_events WHERE id=?", (eid,), one=True)


def update(eid, fields):
    old = get(eid)
    if not old:
        raise ValueError(f"No calendar event with id {eid}.")
    e = _clean(fields, old)
    db.q("UPDATE cal_events SET title=?,start=?,end=?,all_day=?,location=?,notes=?,repeat=?,repeat_until=?,alert=?,updated=? "
         "WHERE id=?", (e["title"], e["start"], e["end"], e["all_day"], e["location"], e["notes"], e["repeat"],
                        e["repeat_until"], e["alert"], db.now(), eid))
    return get(eid)


def _occurrence(e, day):
    """The start of the series occurrence on `day` (a date), or None."""
    s0, _ = parse(e["start"], e["all_day"])
    for s in _steps(e, s0):
        if s.date() > day:
            return None
        if s.date() == day:
            return s
    return None


def change_once(eid, day, fields, by="you"):
    """Only one occurrence changes: the series skips that day and a one-off event (with the changes) takes its place."""
    e = get(eid)
    if not e:
        raise ValueError(f"No calendar event with id {eid}.")
    day = parse(day, True)[0].date()
    occ = _occurrence(e, day)
    if not occ:
        raise ValueError(f"{e['title']} does not happen on {day:%a %d %b %Y}.")
    s0, ad = parse(e["start"], e["all_day"])
    length = parse(e["end"], ad)[0] - s0
    one = {"title": e["title"], "start": fmt(occ, ad), "end": fmt(occ + length, ad), "all_day": ad, "location": e["location"],
           "notes": e["notes"], "alert": e["alert"], "repeat": "", "repeat_until": ""}
    if fields.get("start") and not fields.get("end"):  # moved: keep the length
        ns, _ = parse(fields["start"], ad)
        fields = {**fields, "end": fmt(ns + length, ad)}
    one.update({k: v for k, v in fields.items() if v is not None and k not in ("repeat", "repeat_until")})
    new = add(one, by=by) if not fields.get("cancel") else None
    skip = sorted(set(filter(None, (e.get("skip") or "").split(","))) | {day.isoformat()})
    db.q("UPDATE cal_events SET skip=?, updated=? WHERE id=?", (",".join(skip), db.now(), eid))
    return get(eid), new


def change_from(eid, day, fields, by="you"):
    """From `day` on the series changes: the old series ends the day before, a new one starts with the changes."""
    e = get(eid)
    if not e:
        raise ValueError(f"No calendar event with id {eid}.")
    day = parse(day, True)[0].date()
    occ = _occurrence(e, day)
    if not occ:
        raise ValueError(f"{e['title']} does not happen on {day:%a %d %b %Y}; pick a day it happens on.")
    s0, ad = parse(e["start"], e["all_day"])
    length = parse(e["end"], ad)[0] - s0
    nxt = {"title": e["title"], "start": fmt(occ, ad), "end": fmt(occ + length, ad), "all_day": ad, "location": e["location"],
           "notes": e["notes"], "alert": e["alert"], "repeat": e["repeat"], "repeat_until": e["repeat_until"]}
    if fields.get("start") and not fields.get("end"):
        ns, _ = parse(fields["start"], ad)
        fields = {**fields, "end": fmt(ns + length, ad)}
    nxt.update({k: v for k, v in fields.items() if v is not None})
    new = add(nxt, by=by)
    if occ.date() == s0.date():
        delete(eid)
    else:
        db.q("UPDATE cal_events SET repeat_until=?, updated=? WHERE id=?", ((day - dt.timedelta(days=1)).isoformat(), db.now(), eid))
    return get(eid), new


def delete(eid):
    old = get(eid)
    if not old:
        raise ValueError(f"No calendar event with id {eid}.")
    db.q("DELETE FROM cal_events WHERE id=?", (eid,))
    return old


def _nth(first, rep, i):
    """The i-th start of a series (None when that month has no such day, e.g. the 31st)."""
    if i == 0 or rep in ("", None):
        return first
    if rep in ("daily", "weekdays"):
        return first + dt.timedelta(days=i)
    if rep == "weekly":
        return first + dt.timedelta(weeks=i)
    y, m = divmod(first.month - 1 + (i if rep == "monthly" else 12 * i), 12)
    try:
        return first.replace(year=first.year + y, month=m + 1)
    except ValueError:
        return None


def _steps(e, first):
    """Start times of a series, from its first start onwards (endless for repeats; callers stop)."""
    rep = e["repeat"] or ""
    until = dt.datetime.strptime(e["repeat_until"], "%Y-%m-%d") + dt.timedelta(days=1) if e.get("repeat_until") else None
    i = 0
    while True:
        cur = _nth(first, rep, i)
        i += 1
        if cur is not None:
            if until and cur >= until:
                return
            if rep != "weekdays" or cur.weekday() < 5:
                yield cur
        if not rep:
            return


def occurrences(frm, to):
    """All event occurrences overlapping [frm, to) (dates or datetimes), sorted by start."""
    frm = frm if isinstance(frm, dt.datetime) else dt.datetime.combine(frm, dt.time())
    to = to if isinstance(to, dt.datetime) else dt.datetime.combine(to, dt.time())
    out = []
    for e in db.q("SELECT * FROM cal_events"):
        s0, all_day = parse(e["start"], e["all_day"])
        length = parse(e["end"], all_day)[0] - s0
        skip = set(filter(None, (e.get("skip") or "").split(",")))
        for s in _steps(e, s0):
            if s >= to:
                break
            if s + length > frm and s.strftime("%Y-%m-%d") not in skip:
                out.append({**e, "occ_start": fmt(s, all_day), "occ_end": fmt(s + length, all_day)})
    return sorted(out, key=lambda o: (o["occ_start"][:10], not o["all_day"], o["occ_start"]))


def overlaps(start, end, all_day=False, skip_id=None):
    s, ad = parse(start, all_day)
    e = parse(end, ad)[0] if end else s + dt.timedelta(hours=1)
    if ad:
        return []
    return [o for o in occurrences(s, e) if not o["all_day"] and o["id"] != skip_id]


def describe(o):
    """One line for chat and approvals, e.g. 'Fri 10 Oct 14:00–15:00 Dentist @ Main St (weekly, alert 15 min)'."""
    s, ad = parse(o.get("occ_start") or o["start"], o["all_day"])
    en = parse(o.get("occ_end") or o["end"], ad)[0]
    last = en - dt.timedelta(days=1)
    if ad and last.date() > s.date():  # several days
        when = f"{s:%a %d %b} – {last:%a %d %b %Y} (all day, {(en - s).days} days)"
    elif not ad and en.date() > s.date():
        when = f"{s:%a %d %b %H:%M} – {en:%a %d %b %Y %H:%M}"
    else:
        when = s.strftime("%a %d %b %Y") + (" (all day)" if ad else f" {s:%H:%M}–{en:%H:%M}")
    extra = [x for x in (o.get("repeat") and f"repeats {o['repeat']}",
                         o.get("alert", -1) >= 0 and (f"alert {o['alert']} min before" if o["alert"] else "alert at start"))
             if x]
    return f"{when} **{o['title']}**" + (f" @ {o['location']}" if o.get("location") else "") + \
        (f" ({', '.join(extra)})" if extra else "")


def due_alerts(now=None):
    """Occurrences whose alert time has come and that have not alerted yet (looks 1 day ahead)."""
    now = now or dt.datetime.now()
    due = []
    for o in occurrences(now - dt.timedelta(hours=1), now + dt.timedelta(days=1, hours=1)):
        if o["alert"] < 0:
            continue
        s, ad = parse(o["occ_start"], o["all_day"])
        at = (s.replace(hour=8) if ad else s) - dt.timedelta(minutes=o["alert"])  # all-day: alert relative to 08:00
        key = f"{o['id']}@{o['occ_start']}"
        if at <= now < s + dt.timedelta(minutes=30) and not db.q("SELECT key FROM cal_alerts WHERE key=?", (key,), one=True):
            db.q("INSERT INTO cal_alerts(key,fired) VALUES(?,?)", (key, db.now()))
            due.append(o)
    return due
