"""Looking things up on the web, without an account anywhere: a search engine of your own (SearXNG, in a container on
this PC, set up by install.sh) asks several public search engines and Amadeus reads the pages itself.

What leaves the PC: the search words (to those engines, with no account, cookie or history) and the request for each
page it reads (to that site). So a search never carries what's private: anything from your deny-list, a mail address,
phone number, key, IBAN or a path on this PC stops it. What comes back is untrusted: it's handed to the model as data
between markers, a page can only be an address on the public internet (never this PC or your home network), and
nothing from the web reaches long-term memory without your OK (tools.learn_from_web)."""
import html
import html.parser
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import CFG
from . import privacy

URL = CFG.get("searxng_url", "http://127.0.0.1:8894")
CHECK_SECONDS = 30
MAX_BYTES = 2_000_000      # of a page that is downloaded
MAX_TEXT = 12_000          # characters of a page handed to the model
TIMEOUT = 20
AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"  # a plain browser's, nothing about you
IN_A_SEARCH = ("EMAIL", "KEY", "TOKEN", "IBAN", "PHONE", "PATH", "URL")  # privacy.PATTERNS that stop a search
IN_AN_ADDRESS = ("EMAIL", "KEY")  # web addresses are full of long ids and paths: only what is clearly yours stops one
_state = {"at": 0.0, "ok": False}
_lock = threading.Lock()


class NotAllowed(ValueError):
    pass


# ---------- is the search engine there? ----------
def ready(force=False):
    with _lock:
        if not force and time.time() - _state["at"] < CHECK_SECONDS:
            return _state["ok"]
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "/healthz"), timeout=3) as r:
            ok = r.status == 200
    except (OSError, ValueError):
        ok = False
    with _lock:
        _state.update(at=time.time(), ok=ok)
    return ok


def missing():
    return "" if ready() else "The search engine isn't running: ./install.sh --only search (or docker start amadeus-searxng)."


# ---------- what may leave ----------
def check_outgoing(text, kinds=IN_A_SEARCH):
    """Raises NotAllowed when search words (or an address to read) carry something private."""
    low = text.lower()
    if any(t and t.lower() in low for t in privacy._terms()):
        raise NotAllowed("That contains something from your deny-list, so it isn't sent out.")
    for label, rx in privacy.PATTERNS:
        if label in kinds and rx.search(text):
            raise NotAllowed(f"That contains something private ({label.lower()}), so it isn't sent out. Try without it.")


# ---------- search ----------
def search(query, limit=6):
    """The best results across the engines: [{title, url, snippet, engines, date}]. A result several engines agree on
    comes first (SearXNG's score)."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:300]
    if len(query) < 2:
        raise ValueError("Say what to search for.")
    check_outgoing(query)
    if not ready():
        raise RuntimeError(missing())
    q = urllib.parse.urlencode({"q": query, "format": "json", "safesearch": 1})
    req = urllib.request.Request(f"{URL}/search?{q}", headers={"x-real-ip": "127.0.0.1", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.load(r)
    out, seen = [], set()
    for box in d.get("infoboxes", [])[:1]:  # an encyclopedia's summary of exactly this
        if box.get("content"):
            out.append({"title": box.get("infobox", ""), "url": box.get("id", ""), "snippet": box["content"][:700],
                        "engines": [box.get("engine", "wikipedia")], "date": ""})
            seen.add(box.get("id", ""))
    for r in sorted(d.get("results", []), key=lambda r: r.get("score", 0), reverse=True):
        url = r.get("url", "")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append({"title": (r.get("title") or "")[:200], "url": url, "snippet": (r.get("content") or "")[:400],
                    "engines": r.get("engines") or [r.get("engine", "")], "date": (r.get("publishedDate") or "")[:10]})
        if len(out) >= limit:
            break
    return out


# ---------- reading a page ----------
def _public(host):
    """Every address the name stands for is on the public internet. Returns one of them."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise NotAllowed(f"{host} can't be found.") from None
    addrs = {i[4][0] for i in infos}
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise NotAllowed("Only pages on the public internet can be read, never this PC or your home network.")
    return sorted(addrs)[0]


def _check_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise NotAllowed("Only http and https web addresses can be read.")
    if p.port not in (None, 80, 443, 8080, 8443):
        raise NotAllowed("That address uses an unusual port, so it isn't opened.")
    _public(p.hostname)
    return p


class _Checked(urllib.request.HTTPRedirectHandler):
    """Each redirect is checked like the first address, so a page can't send the request into your network."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Text(html.parser.HTMLParser):
    """The readable text of a page. Where the page marks its main part (<main>, <article>), only that is kept."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe", "template", "button"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre", "table"}
    MAIN = {"main", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.all, self.main, self.skip, self.inside, self.title, self.in_title = [], [], 0, 0, "", False

    def _add(self, text):
        self.all.append(text)
        if self.inside:
            self.main.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        if tag in self.MAIN:
            self.inside += 1
        if tag in self.BLOCK:
            self._add("\n")
        if tag in ("h1", "h2", "h3"):
            self._add("## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        if tag in self.BLOCK:
            self._add("\n")
        if tag in self.MAIN:
            self.inside = max(0, self.inside - 1)

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self._add(data)


def page_text(markup):
    """(title, readable text) of an HTML page: no scripts, menus or forms."""
    p = _Text()
    try:
        p.feed(markup)
    except Exception:
        pass  # broken HTML: what was read so far
    main = "".join(p.main)
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", main if len(main.strip()) > 500 else "".join(p.all))
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if re.search(r"\w", line)]  # no empty headings, separators or lone symbols
    text = "\n".join(lines).replace("¶", "")
    return re.sub(r"\s+", " ", p.title).strip()[:200], text


def read(url):
    """One page as text: {url, title, text, truncated}. Only public web pages, only text and HTML, no cookies kept."""
    url = str(url or "").strip()
    check_outgoing(urllib.parse.unquote(url), IN_AN_ADDRESS)
    _check_url(url)
    opener = urllib.request.build_opener(_Checked)
    req = urllib.request.Request(url, headers={"user-agent": AGENT, "accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
                                               "accept-language": "en,de;q=0.8"})
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            kind = (r.headers.get_content_type() or "").lower()
            if kind not in ("text/html", "text/plain", "application/xhtml+xml", "text/markdown"):
                raise NotAllowed(f"That's not a text page ({kind or 'unknown type'}), so it isn't read.")
            raw = r.read(MAX_BYTES + 1)
            charset = r.headers.get_content_charset() or "utf-8"
            final = r.geturl()
    except urllib.error.HTTPError as e:
        e.close()
        raise RuntimeError(f"The site answered with an error ({e.code}).") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"The page couldn't be loaded ({str(getattr(e, 'reason', e))[:80]}).") from None
    try:
        body = raw[:MAX_BYTES].decode(charset, errors="replace")
    except LookupError:
        body = raw[:MAX_BYTES].decode("utf-8", errors="replace")
    title, text = page_text(body) if kind not in ("text/plain", "text/markdown") else ("", body.strip())
    text = html.unescape(text)
    return {"url": final, "title": title, "text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT or len(raw) > MAX_BYTES}
