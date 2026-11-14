"""Keeps the model to what really happened and to what you really said. A small local model gets two things wrong now and then: it
answers "done" without having called a tool, and it miscalculates times ("in 5 minutes"). Neither is left to the model here: code
checks whether a tool ran, and code works out the time from your own words."""
import datetime
import re

NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
           "ein": 1, "eine": 1, "einer": 1, "einem": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "zehn": 10, "fünfzehn": 15, "zwanzig": 20, "dreißig": 30,
           "un": 1, "una": 1, "dos": 2, "tres": 3, "cinco": 5, "diez": 10, "quince": 15, "veinte": 20, "treinta": 30}
UNITS = {"minutes": r"min(?:ute[ns]?|uto?s?|s)?\b", "hours": r"(?:hours?|hrs?|h|stunden?|horas?)\b", "days": r"(?:days?|tage?n?|d[ií]as?)\b"}
IN = re.compile(r"\b(?:in|en|dentro de)\s+(?:about\s+|etwa\s+|ca\.?\s+|unos\s+|unas\s+)?(\d+|" + "|".join(NUMBERS) + r"|half an|einer halben|media)\s+(" + "|".join(UNITS.values()) + ")", re.I)
DAY_WORDS = {"today": 0, "tonight": 0, "heute": 0, "hoy": 0, "tomorrow": 1, "morgen": 1, "mañana": 1, "übermorgen": 2}
WEEKDAYS = [("monday", "mon", "montag", "lunes"), ("tuesday", "tue", "dienstag", "martes"), ("wednesday", "wed", "mittwoch", "miércoles"),
            ("thursday", "thu", "donnerstag", "jueves"), ("friday", "fri", "freitag", "viernes"), ("saturday", "sat", "samstag", "sábado"),
            ("sunday", "sun", "sonntag", "domingo")]
# a part of the day without a time: (the time used, earliest, latest the model may have meant)
PARTS = [(r"early morning|früh\b|morgens|vormittag|morning|por la mañana", (9, 6, 11)), (r"noon|midday|mittags?\b|mediodía", (12, 11, 13)),
         (r"afternoon|nachmittag|por la tarde", (15, 13, 17)), (r"evening|abends?\b|tonight|esta noche|por la noche", (19, 17, 22)), (r"\bnight\b|nachts?\b", (21, 20, 23))]
DAY = r"\b(" + "|".join(list(DAY_WORDS) + [w for names in WEEKDAYS for w in names]) + r")\b"
CLOCK = r"(?:\b(?:at|um|a las|@)\s*)?\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|uhr|h)?\b"
FORMAT = "%Y-%m-%d %H:%M"


def _clock(text):
    """An explicit time in the text: (hour, minute), or None. A bare number only counts with 'at', 'um', am/pm, 'Uhr' or minutes."""
    for m in re.finditer(CLOCK, text, re.I):
        hour, minute, mark = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        said_at = re.match(r"\s*(at|um|a las|@)", m.group(0), re.I)
        if not (said_at or m.group(2) or mark) or hour > 23 or minute > 59:
            continue
        if mark == "pm" and hour < 12:
            hour += 12
        if mark == "am" and hour == 12:
            hour = 0
        return hour, minute
    return None


def times_in(text, now=None):
    """The times you named in your own words, worked out: [(your words, datetime, kind)]. kind: "exact", "part" ('this evening', no time) or "clock" (a time, no day)."""
    now = now or datetime.datetime.now()
    low, found = (text or "").lower(), []
    for m in IN.finditer(low):
        word = m.group(1)
        n = 0.5 if word in ("half an", "einer halben", "media") else float(NUMBERS.get(word, word))
        unit = next(u for u, rx in UNITS.items() if re.fullmatch(rx, m.group(2), re.I))
        found.append((m.group(0), now + datetime.timedelta(**{unit: n}), "exact"))
    if found:
        return found
    day = re.search(DAY, low)
    part = next(((m.group(0), hours) for rx, hours in PARTS for m in [re.search(rx, low)] if m), None)
    if not day and not part and not _clock(low):
        return []
    word = day.group(1) if day else ""
    if word in DAY_WORDS:
        date = now.date() + datetime.timedelta(days=DAY_WORDS[word])
    elif word:
        wd = next(i for i, names in enumerate(WEEKDAYS) if word in names)
        date = now.date() + datetime.timedelta(days=(wd - now.weekday() - 1) % 7 + 1)
    else:
        date = now.date()
    rest = low.replace(word, " ", 1) if word else low
    clock = _clock(rest)
    said = " ".join(x for x in (word, part[0] if part and not clock else "") if x)
    if clock:
        hour, minute = clock
        if part and hour < 12 and part[1][0] >= 15 and not re.search(r"\b(am|uhr)\b", rest):  # "at 7 this evening"
            hour += 12
        at = datetime.datetime.combine(date, datetime.time(hour, minute))
        if not word and at < now:  # "at 9" when it's already later: tomorrow
            at += datetime.timedelta(days=1)
        return [(f"{said} {hour:02d}:{minute:02d}".strip(), at, "exact" if word else "clock")]  # only a time: the day may be one this doesn't know
    if not part:
        return []  # only a day, no time: nothing to work out
    at = datetime.datetime.combine(date, datetime.time(part[1][0], 0))
    if not day and at < now and "tonight" not in low:
        return []
    return [(said, at, "part")]


def resolve_when(when, now=None):
    """What the model passed as a reminder's time, if it's in everyday words: 'YYYY-MM-DD HH:MM', or None."""
    found = times_in(when, now)
    return found[0][1].strftime(FORMAT) if len(found) == 1 else None


def correct_when(when, said, now=None):
    """The model's time for a reminder, checked against what you said. Returns the time to use: yours where it's unambiguous."""
    now = now or datetime.datetime.now()
    found = times_in(said, now)
    if len(found) != 1 or re.match(r"\s*(daily|weekdays|weekly)\b", when or "", re.I) or re.search(r"\b(every|each|daily|jeden|täglich|cada|todos los)\b", said or "", re.I):
        return when
    _, mine, kind = found[0]
    m = re.fullmatch(r"\s*(\d{4}-\d{2}-\d{2})[ tT](\d{1,2}):(\d{2})\s*", when or "")
    theirs = datetime.datetime.fromisoformat(f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)}") if m else None
    if kind == "clock":  # you gave the time; the day is the model's, unless it gave none
        if not theirs:
            return mine.strftime(FORMAT)
        return when if (theirs.hour, theirs.minute) == (mine.hour, mine.minute) else theirs.replace(hour=mine.hour, minute=mine.minute).strftime(FORMAT)
    if kind == "exact":
        return when if theirs and abs((theirs - mine).total_seconds()) <= 90 else mine.strftime(FORMAT)
    window = next(hours for rx, hours in PARTS if hours[0] == mine.hour)
    if theirs and theirs.date() == mine.date() and window[1] <= theirs.hour <= window[2]:
        return when  # "this evening" and the model picked a time in the evening: fine
    return mine.strftime(FORMAT)


def hint(said, now=None):
    """For the model: the times in your message, already worked out."""
    found = times_in(said, now)
    return "Times in this message, already worked out (use exactly these, never calculate): " + "; ".join(
        f'"{words}" = {at.strftime(FORMAT)}' for words, at, _ in found) if found else ""


DID = (r"added|set|created|saved|scheduled|put|noted|marked|moved|removed|deleted|sent|drafted|updated|cancell?ed|written|wrote|filed|stored|"
       r"reminded|booked|logged|recorded")
CLAIM = re.compile(
    r"\b(?:i['’]ve|i have|i just|i)\s+(?:now\s+|already\s+|just\s+|successfully\s+)?(?:" + DID + r")\b|"
    r"^\W*(?:done|added|saved|noted|all set|reminder set|erledigt|fertig|hecho|listo)\b|"
    # passive: "it's been added". Not a report about information ("the forecast was updated at 11:25", "recorded in
    # 2019"): that says nothing about what Amadeus did
    r"\b(?:is|are|has been|have been|was|were|is now|are now)\s+(?:now\s+|successfully\s+)?(?:" + DID + r")\b"
    r"(?!\s+(?:at\s+\d|on\s+(?:\d|mon|tue|wed|thu|fri|sat|sun)|in\s+\d{4}|every|daily|hourly|weekly|yesterday|last\s|\d))|"
    r"\b(?:ich habe|habe ich|ich hab)\b.{0,70}\b(?:hinzugefügt|erstellt|gespeichert|eingetragen|gesetzt|notiert|verschoben|gelöscht|gesendet|markiert|angelegt)\b|"
    r"\b(?:wurde|wurden|ist|sind)\b.{0,40}\b(?:hinzugefügt|erstellt|gespeichert|eingetragen|gesetzt|angelegt)\b|"
    r"\b(?:he|ya he)\s+(?:añadido|agregado|creado|guardado|programado|anotado|movido|eliminado|enviado|marcado)\b", re.I | re.M)
PROMISE = re.compile(
    r"\b(?:i['’]ll|i will|i am going to|i['’]m going to|let me|let['’]s)\s+(?:now\s+|go ahead and\s+)?(?:add|set|create|save|schedule|put|note|remind|mark|move|remove|delete|send|draft)\b|"
    r"\b(?:adding|setting|creating|saving|scheduling)\b.{0,40}\b(?:reminder|to-?do|note|event|appointment)\b|"
    r"\bi['’]?\s?a?m\s+(?:now\s+)?(?:adding|setting|creating|saving|scheduling|blocking|putting|removing|moving|booking|marking|sending|deleting|updating)\b|"
    r"\bich (?:werde|setze|erstelle|trage|füge)\b.{0,60}\b(?:erinner|hinzu|ein\b|eintrag|notiz|termin)", re.I)
FACT = re.compile(r"\b(?:you have|there are|i have|du hast|es gibt)\s+(?:no|keine)\s+(?:active\s+|open\s+|aktiven\s+|offenen\s+|unread\s+|new\s+)?(?:reminders?|to-?dos?|erinnerungen|events|appointments|termine|mails?|emails?)\b", re.I)


def unbacked(reply):
    """What kind of thing the reply says that only a tool can make true: "claim" (it's done), "promise" (it will be, with no question
    back to you), "fact" (what your list holds), or None. Only meaningful when no tool ran in this turn."""
    text = re.sub(r"`[^`]*`|\"[^\"]*\"|“[^”]*”", " ", reply or "")
    if CLAIM.search(text):
        return "claim"
    if FACT.search(text):
        return "fact"
    if PROMISE.search(text) and "?" not in text:
        return "promise"
    return None


def fit_args(fn, args):
    """Only the arguments the tool has: a model sometimes invents one ("all_day"), and the whole action then fails after you approved it.
    Returns (arguments, the names left out)."""
    import inspect
    try:
        known = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return args, []
    if any(p.kind == p.VAR_KEYWORD for p in known.values()):
        return args, []
    extra = [k for k in args if k not in known]
    return {k: v for k, v in args.items() if k in known}, extra


def failure(result):
    """The reason, if a tool's result says it failed."""
    m = re.match(r"\s*(?:Error:|FAILED[^:]*:|Invalid request:)\s*(.*)", result or "", re.S)
    return m.group(1).strip()[:300] if m else ""


FAILED_NUDGE = ("(From the system, not the user.) The action FAILED, nothing was changed: {why}. Don't say it's done. If you can fix what was wrong, "
                "call the tool again now with correct arguments; otherwise tell the user plainly that it didn't work and why.")
NUDGE = ("(From the system, not the user.) You answered as if it had happened, but you called no tool, so nothing has happened and you looked "
         "nothing up. Now call the tool or tools the user's last message needs. If no tool fits, or you first need to ask something, say plainly "
         "that it is not done yet. Never say it's done, added, set or saved unless a tool ran.")
HONEST = "I haven't done that yet: I didn't manage to start the right action for it. Please tell me again what to do, as exactly as you can."
