"""What gets said when a reply is read aloud. The chat keeps the full answer; this turns it into what a person would
actually say: no Markdown, links, ids or code, times and dates the way you'd say them ("2 PM", not "14:00"), long lists
cut short, and for a long answer only the start, with a pointer to the chat. Rules only (no second model call), so
it's instant and always matches what the chat shows."""
import datetime
import re

MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
          "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
          "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]}
SAY = {"en": {"code": "The code is in the chat.", "table": "There's a table in the chat.", "more": "and {n} more, see the chat.",
              "rest": "The rest is in the chat.", "to": "to", "and": "and"},
       "de": {"code": "Den Code findest du im Chat.", "table": "Die Tabelle steht im Chat.", "more": "und {n} weitere, siehe Chat.",
              "rest": "Den Rest findest du im Chat.", "to": "bis", "and": "und"},
       "es": {"code": "El código está en el chat.", "table": "La tabla está en el chat.", "more": "y {n} más, mira el chat.",
              "rest": "El resto está en el chat.", "to": "a", "and": "y"}}
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]")


def _time(h, m, lang):
    h, m = int(h), int(m)
    if lang == "de":
        return f"{h} Uhr" + (f" {m}" if m else "")
    if lang == "es":
        return f"las {h}" + (f" y {m}" if m else "")
    ap, h12 = ("AM" if h < 12 else "PM"), (h % 12 or 12)
    if h == 12 and not m:
        return "noon"
    return f"{h12}" + (f":{m:02d}" if m else "") + f" {ap}"


def _date(y, mo, d, lang):
    try:
        x = datetime.date(int(y), int(mo), int(d))
    except ValueError:
        return f"{y}-{mo}-{d}"
    name = MONTHS[lang][x.month - 1]
    year = "" if x.year == datetime.date.today().year else f" {x.year}"
    return f"{x.day}. {name}{year}" if lang == "de" else f"{x.day} de {name}{year}" if lang == "es" else f"{name} {x.day}{year}"


def speech_text(text, lang="en", limit=600):
    lang = lang if lang in SAY else "en"
    s = SAY[lang]
    t = re.sub(r"[ \t]*\[mood:\s*\w*\]?[ \t]*", " ", str(text or ""), flags=re.I)
    t = re.sub(r"```.*?```", f" {s['code']} ", t, flags=re.S)
    t = re.sub(r"(?:^\|.*\|\s*$\n?){2,}", f"{s['table']}\n", t, flags=re.M)  # a Markdown table
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", t)  # [text](link) -> text
    t = re.sub(r"<?https?://\S+>?", "", t)
    t = re.sub(r"\[(?:id )?[0-9a-f]{8,}\]|\(id [^)]*\)", "", t)  # ids like [3f2a9c1b7e44]
    t = EMOJI.sub("", t)
    # lists: each item is a sentence; a long list is cut after four
    out, items = [], []
    def flush():
        if items:
            keep = items[:4] if len(items) > 5 else items
            out.extend(i.rstrip(".;:,") + "." for i in keep)
            if len(items) > 5:
                out.append(s["more"].format(n=len(items) - 4))
            items.clear()
    for line in t.splitlines():
        m = re.match(r"\s*(?:[-*+•]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.*)", line)
        if m:
            items.append(m.group(1).strip())
            continue
        flush()
        line = re.sub(r"^\s*#{1,6}\s*(.*)", r"\1.", line).strip()  # a heading becomes a short sentence
        if line and not re.fullmatch(r"[-*_]{3,}", line):
            out.append(line if re.search(r"[.!?:]$", line) else line + ".")  # each line ends as a sentence
    flush()
    t = " ".join(out)
    t = re.sub(r"[*_~>#|]+", "", t)
    # times and dates the way you say them
    t = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::\d\d)?(?:\s*[–-]\s*([01]?\d|2[0-3]):([0-5]\d))?\b",  # one pass, so "2 PM" isn't read again
               lambda m: _time(m[1], m[2], lang) + (f" {s['to']} {_time(m[3], m[4], lang)}" if m[3] else ""), t)
    t = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b", lambda m: _date(m[1], m[2], m[3], lang), t)
    t = t.replace("→", f" {s['to']} ").replace("&", f" {s['and']} ").replace("…", ".").replace(" · ", ", ")
    t = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", t)).strip()
    t = re.sub(r"([.!?])\.+", r"\1", t)
    if len(t) > limit:  # a long answer: the first sentences, then a pointer to the chat
        cut = t[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = (cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + ".") + " " + s["rest"]
    return t
