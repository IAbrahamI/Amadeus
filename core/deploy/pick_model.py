#!/usr/bin/env python3
"""Which local model fits this PC: looks at the hardware, measures real speed with a small model, and suggests three
(the best it can run comfortably, then two lighter ones). After you pick one it's downloaded and measured for real.
Used by install.sh; again any time with ./install.sh --benchmark. Standard library only."""
import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.request

URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
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


def hardware():
    gpu, name = 0.0, ""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
        mib, name = out.splitlines()[0].split(", ", 1)
        gpu = int(mib) / 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        for f in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"):  # AMD
            try:
                gpu = max(gpu, int(open(f).read()) / 2 ** 30)
                name = "AMD graphics card"
            except (OSError, ValueError):
                pass
    ram = 0.0
    try:
        ram = next(int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemTotal")) / 2 ** 20
    except (OSError, StopIteration, ValueError):
        pass
    return {"gpu_gb": round(gpu, 1), "gpu": name, "ram_gb": round(ram, 1), "cores": os.cpu_count() or 1,
            "disk_gb": round(shutil.disk_usage(os.path.expanduser("~")).free / 2 ** 30, 1)}


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


def baseline():
    """(tokens per second, size) from what's installed, else from a small model that's removed again afterwards."""
    have = installed()
    probe, remove = (min(have, key=have.get), False) if have else (PROBE, True)
    if remove:
        print(f"  Downloading a small test model to measure this PC ({dict((m, s) for m, s, _ in CATALOG)[PROBE]} GB, removed afterwards)...")
        if not pull(probe):
            return None
    tps, share = measure(probe)
    size = installed().get(probe, 1.0)
    print(f"  Speed test with {probe}: {tps:.0f} tokens per second, {share * 100:.0f}% on the graphics card.")
    if remove:
        subprocess.run(["ollama", "rm", probe], capture_output=True)
    return (tps, size) if tps else None


def show(picks):
    for i, m in enumerate(picks, 1):
        est = f", about {m['speed']:.0f} tokens per second" if m["speed"] else ""
        where = "on the graphics card" if m["on"] == "gpu" else "on the CPU, slower"
        print(f"  {i}. {m['model']:<14} {m['size']:>4g} GB  {m['about']} ({where}{est}){'  (recommended)' if i == 1 else ''}")


def choose(out_file, interactive):
    hw = hardware()
    print(f"  This PC: {hw['gpu'] or 'no dedicated graphics card'}" + (f" with {hw['gpu_gb']:g} GB" if hw["gpu_gb"] else "") +
          f", {hw['ram_gb']:g} GB memory, {hw['cores']} CPU threads, {hw['disk_gb']:g} GB free disk.")
    picks = suggest(hw, baseline())
    if not picks:
        print("  Not enough memory or disk for any model here.")
        return 1
    show(picks)
    while True:
        reply = input("  ? Which one? [1] ").strip() if interactive else "1"
        m = picks[int(reply) - 1 if reply in ("1", "2", "3") and int(reply) <= len(picks) else 0]
        if m["model"] not in installed() and not pull(m["model"]):
            print(f"  Couldn't download {m['model']}.")
            return 1
        tps, share = measure(m["model"])
        print(f"  {m['model']}: {tps:.0f} tokens per second, {share * 100:.0f}% on the graphics card.")
        if tps >= TOO_SLOW or not interactive or m is picks[-1]:
            break
        print("  That's slow enough to be annoying. Pick a lighter one, or the same to keep it.")
        if input(f"  ? Keep {m['model']}? [y/N] ").strip().lower().startswith("y"):
            break
        show(picks)
    ctx = context_for(hw, m["size"])
    with open(out_file, "w") as f:
        f.write(f"{m['model']}\n{variant_name(m['model'], ctx)}\n{ctx}\n")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--hardware"]:
        print(json.dumps(hardware(), indent=2))
        sys.exit(0)
    sys.exit(choose(sys.argv[1], sys.stdin.isatty() and "--auto" not in sys.argv))
