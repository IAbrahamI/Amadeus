#!/usr/bin/env python3
"""Which local model fits this PC: looks at the hardware, measures real speed with a small model, reads the newest models
that can use tools from Ollama's library, and suggests three: the newest strong one that runs comfortably here, the one
Amadeus is tuned on, and a lighter one. After you pick, it's downloaded, measured and checked that it really calls tools.
Used by install.sh; again any time with ./install.sh --benchmark. Standard library only. If the library can't be read,
the built-in list below is used."""
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import select
import sys
import termios
import tty
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
LIBRARY = "https://ollama.com"
NEWEST_PAGES = 2     # pages of 20 models each
NOT_FOR_CHAT = re.compile(r"guard|audio|-vl\b|ocr|embed|vision|code$|-code-", re.I)
NOT_A_PLAIN_TAG = re.compile(r"q\d|fp\d|bf\d|qat|mtp|instruct|cloud|-it-|text", re.I)
# Used when the library can't be read, and for the tuned suggestion.
# (Ollama name, download size in GB, what it's good for). All can call tools, which Amadeus needs. Smallest first.
CATALOG = [
    ("qwen3.5:0.8b", 1.2, "very fast, simple requests only"),
    ("qwen3.5:2b", 2.7, "fast, for simple requests and short answers"),
    ("qwen3.5:4b", 3.3, "quick everyday use"),
    ("qwen3.5:9b", 6.6, "good everyday assistant, the one Amadeus is tuned on"),
    ("qwen3.5:27b", 17, "noticeably smarter, needs a big graphics card"),
    ("qwen3.5:35b", 22, "the smartest here, needs a very big graphics card"),
]
PROBE = "qwen3.5:0.8b"  # what's downloaded to measure speed when no model is installed yet
COMFORT = 15  # words appear about as fast as you read at this many tokens per second
TOO_SLOW = 8
PROMPT = "Explain in about one hundred words how a bicycle stays upright while riding."


def model_folder():
    """Where Ollama keeps models, which is often not on the same disk as your home folder."""
    for d in (os.environ.get("OLLAMA_MODELS"), "/var/lib/ollama", "/usr/share/ollama/.ollama/models", "~/.ollama/models"):
        d = os.path.expanduser(d or "")
        if d and os.path.isdir(d):
            return d
    return os.path.expanduser("~")


def _mac_hardware():
    """Apple Silicon: one memory for everything. About 70% of it can hold a model while the desktop keeps working."""
    def read(key):
        return subprocess.run(["/usr/sbin/sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
    ram = int(read("hw.memsize") or 0) / 2 ** 30
    return {"gpu_gb": round(ram * 0.7, 1), "gpu": read("machdep.cpu.brand_string") or "Apple Silicon", "ram_gb": round(ram, 1), "cores": os.cpu_count() or 1,
            "disk_gb": round(shutil.disk_usage(model_folder()).free / 2 ** 30, 1)}


def hardware():
    if sys.platform == "darwin":
        return _mac_hardware()
    gpu, name = 0.0, ""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
        mib, name = out.splitlines()[0].split(", ", 1)
        gpu = int(mib) / 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        for f in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"):  # AMD
            try:
                gpu = max(gpu, int(Path(f).read_text()) / 2 ** 30)
                name = "AMD graphics card"
            except (OSError, ValueError):
                pass
    ram = 0.0
    try:
        ram = next(int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal")) / 2 ** 20
    except (OSError, StopIteration, ValueError):
        pass
    return {"gpu_gb": round(gpu, 1), "gpu": name, "ram_gb": round(ram, 1), "cores": os.cpu_count() or 1,
            "disk_gb": round(shutil.disk_usage(model_folder()).free / 2 ** 30, 1)}


def runs_on(size, hw):
    """Where a model of this download size fits with room to spare for the desktop: "gpu", "cpu" or None."""
    if hw["gpu_gb"] >= size * 1.25 + 1.5:
        return "gpu"
    return "cpu" if hw["ram_gb"] >= size * 1.25 + 4 else None


def estimate(size, speed):
    """Tokens per second for a model of this size, from one measurement: speed is (tokens per second, measured size)."""
    return speed[0] * speed[1] / size if speed else None


def suggest(hw, speed=None):
    """Three models, recommended first: the biggest that fits and stays comfortable, then the next smaller ones."""
    fit = [dict(model=m, size=s, about=a, on=runs_on(s, hw), speed=estimate(s, speed)) for m, s, a in CATALOG
           if runs_on(s, hw) and hw["disk_gb"] >= s + 2]
    if any(m["on"] == "gpu" for m in fit):  # with a graphics card, only what fits on it: on the CPU it's far slower
        fit = [m for m in fit if m["on"] == "gpu"]
    elif not speed:  # no card and nothing measured: stay small
        fit = [m for m in fit if m["size"] <= 4] or fit[:1]
    if not fit:
        return []
    good = [i for i, m in enumerate(fit) if m["speed"] is None or m["speed"] >= COMFORT]
    best = good[-1] if good else 0
    picks = fit[max(0, best - 2):best + 1][::-1]
    return picks + fit[best + 1:best + 1 + 3 - len(picks)]


def parse_newest(page):
    """Model names from a page of Ollama's search, newest first."""
    return list(dict.fromkeys(re.findall(r'href="/library/([a-z0-9.\-]+)"', page)))


def parse_tags(model, page):
    """The plain downloadable versions of a model from its tags page: [(name:tag, size in GB)]."""
    out = {}
    for m in re.finditer(r'/library/' + re.escape(model) + r':([a-z0-9.\-_]+)"[\s\S]{0,700}?([0-9.]+) ?(GB|MB)\b', page):
        tag, size = m.group(1), float(m.group(2)) / (1 if m.group(3) == "GB" else 1024)
        if not NOT_A_PLAIN_TAG.search(tag):
            out.setdefault(f"{model}:{tag}".removesuffix(":latest"), size)
    return list(out.items())


def _fetch(url):
    req = urllib.request.Request(url, headers={"user-agent": "Amadeus installer", "HX-Request": "true"})
    return urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "replace")


def latest_models():
    """Newest models that can use tools, newest first: [{name, versions: [(name:tag, GB)]}], or [] if offline."""
    try:
        names = []
        for p in range(1, NEWEST_PAGES + 1):
            names += parse_newest(_fetch(f"{LIBRARY}/search?c=tools&o=newest&page={p}"))
    except OSError:
        return []
    names = [n for n in dict.fromkeys(names) if not NOT_FOR_CHAT.search(n)]

    def read(name):
        try:
            return {"name": name, "versions": parse_tags(name, _fetch(f"{LIBRARY}/library/{name}/tags"))}
        except OSError:
            return {"name": name, "versions": []}
    with ThreadPoolExecutor(8) as pool:
        return [m for m in pool.map(read, names) if m["versions"]]


def suggest_latest(hw, latest, speed=None):
    """Three different models, recommended first: the newest strong one that runs comfortably here, the one Amadeus is
    tuned on, and a lighter one. Falls back on the built-in list for whatever the library doesn't give."""
    tuned = suggest(hw, speed)
    if not latest:
        return tuned
    # no graphics card and nothing measured: stay small, the same as the built-in list
    usable = lambda s: runs_on(s, hw) == "gpu" or (not hw["gpu_gb"] and runs_on(s, hw) and (speed or s <= 4))  # noqa: E731
    fits = []  # per model the biggest version that fits and stays comfortable, newest model first
    for rank, m in enumerate(latest):
        ok = [(n, s) for n, s in m["versions"] if usable(s) and hw["disk_gb"] >= s + 2 and (estimate(s, speed) or COMFORT) >= COMFORT]
        if ok:
            name, size = max(ok, key=lambda v: v[1])
            fits.append(dict(model=name, size=size, about="one of the newest, not yet tried with Amadeus", on=runs_on(size, hw),
                             speed=estimate(size, speed), rank=rank))
    if not fits:
        return tuned
    best = max(fits[:12], key=lambda m: m["size"])  # the strongest among the newest
    picks = [best]
    for t in tuned:  # the tuned family, if it's a different model
        if t["model"].split(":")[0] != best["model"].split(":")[0]:
            picks.append(t)
            break
    light = [m for m in fits if m["size"] <= best["size"] * 0.6 and m["model"].split(":")[0] not in {p["model"].split(":")[0] for p in picks}]
    if light:
        picks.append(light[0])
    for t in tuned[1:] + fits:
        if len(picks) >= 3:
            break
        if t["model"] not in {p["model"] for p in picks}:
            picks.append(t)
    return picks[:3]


def calls_tools(model):
    """It really uses a tool when asked to: Amadeus can't work without that."""
    tool = {"type": "function", "function": {"name": "get_time", "description": "The current time in a city.", "parameters": {
        "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}
    try:
        r = _api("/api/chat", {"model": model, "stream": False, "think": False, "keep_alive": 0, "tools": [tool], "options": {"temperature": 0},
                               "messages": [{"role": "user", "content": "What time is it in Paris? Use the tool."}]})
        return any(c["function"]["name"] == "get_time" for c in r["message"].get("tool_calls") or [])
    except (OSError, ValueError, KeyError):
        return False


def context_for(hw, size):
    """How much conversation it holds: more where there's room on the graphics card."""
    room = hw["gpu_gb"] - (size * 1.25 + 1.5)
    return 49152 if room >= 1.5 else 24576 if room >= 0.5 else 12288


def variant_name(model, ctx):
    return f"{model.replace(':', '-')}-{ctx // 1024}k"


def _api(path, body=None, timeout=300):
    req = urllib.request.Request(URL + path, json.dumps(body).encode() if body is not None else None, {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def installed():
    return {m["name"].removesuffix(":latest"): m["size"] / 2 ** 30 for m in _api("/api/tags").get("models", []) if "embed" not in m["name"]}


def measure(model):
    """Real speed: tokens per second, and how much of the model is on the graphics card (0 to 1)."""
    r = _api("/api/generate", {"model": model, "prompt": PROMPT, "stream": False, "think": False, "keep_alive": "1m",
                               "options": {"num_predict": 120, "temperature": 0}})
    tps = r["eval_count"] / (r["eval_duration"] / 1e9) if r.get("eval_duration") else 0.0
    share = next((m["size_vram"] / m["size"] for m in _api("/api/ps").get("models", []) if m["name"].removesuffix(":latest") == model and m.get("size")), 0.0)
    _api("/api/generate", {"model": model, "keep_alive": 0})  # give the memory back
    return tps, share


def pull(model):
    return subprocess.run(["ollama", "pull", model]).returncode == 0


class NoDownloads(Exception):
    """Models can't be downloaded from here."""


def registry_reachable():
    try:
        urllib.request.urlopen(urllib.request.Request("https://registry.ollama.ai/v2/", headers={"user-agent": "Amadeus installer"}), timeout=15).close()
    except urllib.error.HTTPError:  # it answered
        return True
    except OSError:
        return False
    return True


def baseline():
    """(tokens per second, size) from what's installed, else from a small model that's removed again afterwards."""
    have = installed()
    probe, remove = (min(have, key=have.get), False) if have else (PROBE, True)
    if remove:
        print(f"  {DIM}· Downloading a small test model to measure this PC ({dict((m, s) for m, s, _ in CATALOG)[PROBE]} GB, removed afterwards){OFF}")
        if not pull(probe):
            return None
    tps, share = measure(probe)
    size = installed().get(probe, 1.0)
    print(f"  {OK}✓{OFF} Speed test: {tps:.0f} tokens per second, {share * 100:.0f}% on the graphics card")
    if remove:
        subprocess.run(["ollama", "rm", probe], capture_output=True)
    return (tps, size) if tps else None


FANCY = sys.stdout.isatty() and sys.stdin.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM", "dumb") != "dumb"
OK, BAD, HEAD, BOLD, DIM, PICK, OFF = ("\033[38;5;78m", "\033[38;5;203m", "\033[38;5;80m", "\033[1m", "\033[2m", "\033[1;38;5;16;48;5;80m", "\033[0m") if FANCY else ("",) * 7


def describe(m, recommended):
    est = f", about {m['speed']:.0f} tokens/s" if m["speed"] else ""
    where = "graphics card" if m["on"] == "gpu" else "CPU, slower"
    return f"{m['model']:<18} {m['size']:>5.1f} GB", f"{m['about']} ({where}{est})" + ("  recommended" if recommended else "")


def _key():
    """One key: up, down, enter, a digit or None."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        c = os.read(fd, 1)
        if c == b"\x1b":
            r, _, _ = select.select([fd], [], [], 0.05)
            seq = os.read(fd, 2) if r else b""
            return {b"[A": "up", b"OA": "up", b"[B": "down", b"OB": "down"}.get(seq)
        if c == b"\x03":
            raise KeyboardInterrupt
        if c == b"\x04":
            raise EOFError
        return {b"\r": "enter", b"\n": "enter", b"k": "up", b"j": "down"}.get(c, c.decode("ascii", "ignore"))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def menu(picks, question="Which model?"):
    """Choose with the arrow keys or a number, Enter takes it. Without a real terminal: type a number."""
    rows = [describe(m, i == 0) for i, m in enumerate(picks)]
    if not FANCY:
        for i, (left, right) in enumerate(rows, 1):
            print(f"  {i}. {left}  {right}")
        reply = input(f"  ? {question} [1] ").strip()
        return picks[int(reply) - 1] if reply.isdigit() and 1 <= int(reply) <= len(picks) else picks[0]
    sel, drawn = 0, False
    print(f"  {HEAD}?{OFF} {BOLD}{question}{OFF}  {DIM}↑ ↓ or a number, Enter to choose{OFF}")
    while True:
        if drawn:
            sys.stdout.write(f"\033[{len(rows) * 2}A")
        for i, (left, right) in enumerate(rows):
            mark = f"  {PICK} {left} {OFF}" if i == sel else f"   {left} "
            sys.stdout.write(f"\r{mark}\033[K\n\r      {DIM}{right}{OFF}\033[K\n")
        sys.stdout.flush()
        drawn = True
        k = _key()
        if k == "up":
            sel = (sel - 1) % len(rows)
        elif k == "down":
            sel = (sel + 1) % len(rows)
        elif k == "enter":
            break
        elif k and k.isdigit() and 1 <= int(k) <= len(rows):
            sel = int(k) - 1
    sys.stdout.write(f"\033[{len(rows) * 2 + 1}A\033[J")
    print(f"  {HEAD}?{OFF} {question}  {HEAD}{picks[sel]['model']}{OFF}")
    return picks[sel]


def show(picks):
    for i, m in enumerate(picks):
        left, right = describe(m, i == 0)
        print(f"  {i + 1}. {left}  {right}")


def choose(out_file, interactive):
    hw = hardware()
    print(f"  {OK}✓{OFF} This PC: {hw['gpu'] or 'no dedicated graphics card'}" + (f" with {hw['gpu_gb']:g} GB" if hw["gpu_gb"] else "") +
          f", {hw['ram_gb']:g} GB memory, {hw['cores']} CPU threads, {hw['disk_gb']:g} GB free where models go.")
    if not installed() and not registry_reachable():
        print(f"  {BAD}{BOLD}✗ Can't reach registry.ollama.ai, where models are downloaded from. Check this PC's internet and DNS.{OFF}")
        return 3
    speed = baseline()
    print(f"  {DIM}· Reading the newest models from Ollama's library{OFF}")
    latest = latest_models()
    if not latest:
        print(f"  {DIM}· Couldn't read the library: using the built-in list{OFF}")
    picks = suggest_latest(hw, latest, speed)
    if not picks:
        print(f"  {BAD}{BOLD}✗ Not enough memory or disk for any model here.{OFF}")
        return 1
    if not interactive:
        show(picks)
    next_pick = None
    while True:
        m = next_pick or (menu(picks) if interactive else picks[0])
        next_pick = None
        if not interactive:  # nobody to ask: the safest, the one Amadeus is tuned on
            m = next((p for p in picks if p["model"].startswith("qwen3.5")), m)
        if m["model"] not in installed() and not pull(m["model"]):
            print(f"  {BAD}{BOLD}✗ Couldn't download {m['model']}.{OFF}")
            return 3
        tps, share = measure(m["model"])
        tools_ok = calls_tools(m["model"])
        print(f"  {OK if tools_ok else BAD}{'✓' if tools_ok else '✗'}{OFF} {m['model']}: {tps:.0f} tokens per second, {share * 100:.0f}% on the graphics card, tools {'work' if tools_ok else 'did NOT work'}")
        if not tools_ok:
            rest = [p for p in picks if p is not m]
            if not rest:
                print(f"  {BAD}{BOLD}✗ It can't use tools, so Amadeus couldn't work with it.{OFF}")
                return 1
            print("  Amadeus needs tools for nearly everything, so this one won't do. Pick another.")
            picks = rest
            continue
        if tps >= TOO_SLOW or not interactive or m is picks[-1]:
            break
        print("  That's slow enough to be annoying. Pick a lighter one, or the same to keep it.")
        chosen = menu(picks, "Which one now?")
        if chosen is m:
            break
        next_pick = chosen
    ctx = context_for(hw, m["size"])
    with open(out_file, "w") as f:
        f.write(f"{m['model']}\n{variant_name(m['model'], ctx)}\n{ctx}\n")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--hardware"]:
        print(json.dumps(hardware(), indent=2))
        sys.exit(0)
    if sys.argv[1:2] == ["--suggest"]:  # only look: no download, no changes
        show(suggest_latest(hardware(), latest_models()))
        sys.exit(0)
    sys.exit(choose(sys.argv[1], sys.stdin.isatty() and "--auto" not in sys.argv))
