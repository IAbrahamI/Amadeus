"""Local model access through Ollama (chat with tool calling, streamed)."""
import json
import os
import subprocess
import time
import urllib.request

from .config import CFG


# The model gets at most this many CPU threads (it runs on the GPU; the threads only matter for the layers that don't
# fit there). Using every core made the window and the desktop stutter while it wrote; half the cores is as fast.
THREADS = CFG.get("llm_threads") or max(2, (os.cpu_count() or 8) // 4)
KEEP = CFG.get("llm_keep_alive", "30m")  # stays loaded between questions, so it doesn't reload every few minutes
# An idle model gives the graphics card's memory back when less than this is free (MiB), so a video or a game doesn't
# stutter next to it. 0 turns it off.
GPU_FREE = CFG.get("llm_gpu_free_mib", 1024)
IDLE = 60  # seconds since the last answer before the model counts as idle
_used = 0.0


def gpu_free():
    """Free memory on the graphics card in MiB, or None when that can't be read (only NVIDIA for now)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return min(int(l) for l in out.split())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def free_gpu():
    """Background job: unload the idle models while the card's memory is nearly full. The next question reloads them.
    Ollama lets an answer still being written finish first."""
    if not GPU_FREE or time.time() - _used < IDLE:
        return
    free = gpu_free()
    if free is None or free >= GPU_FREE:
        return
    loaded = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/ps", timeout=10)).get("models", [])
    for m in loaded:
        req = urllib.request.Request(CFG["ollama_url"] + "/api/generate", json.dumps({"model": m["name"], "keep_alive": 0}).encode(),
                                     {"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        print(f"graphics memory nearly full ({free} MiB free): unloaded {m['name']}", flush=True)


def list_models():
    data = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/tags", timeout=10))
    return sorted(m["name"].removesuffix(":latest") for m in data.get("models", []))


def model_info():
    """For the model picker: each installed model with its size, parameters and context length."""
    data = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/tags", timeout=10))
    out = []
    for m in data.get("models", []):
        name, d, ctx = m["name"].removesuffix(":latest"), m.get("details") or {}, 0
        try:
            req = urllib.request.Request(CFG["ollama_url"] + "/api/show", json.dumps({"model": m["name"]}).encode(), {"content-type": "application/json"})
            show = json.load(urllib.request.urlopen(req, timeout=10))
            ctx = int(next((l.split()[-1] for l in (show.get("parameters") or "").splitlines() if l.startswith("num_ctx")), 0)) or \
                next((v for k, v in (show.get("model_info") or {}).items() if k.endswith(".context_length")), 0)
        except Exception:
            pass
        out.append({"name": name, "size": round(m.get("size", 0) / 2 ** 30, 1), "params": d.get("parameter_size", ""),
                    "quant": d.get("quantization_level", ""), "ctx": ctx})
    return sorted(out, key=lambda x: x["name"])


def _timing(ev):
    """In the log, for every answer: where the time went. Reading is what repeats if the start of the prompt changed."""
    s = lambda k: ev.get(k, 0) / 1e9  # noqa: E731
    print(f"answer: {s('total_duration'):.1f}s = load {s('load_duration'):.1f}s + read {ev.get('prompt_eval_count', 0)} tokens "
          f"{s('prompt_eval_duration'):.1f}s + write {ev.get('eval_count', 0)} tokens {s('eval_duration'):.1f}s", flush=True)


def loaded():
    """The models in memory right now."""
    return [m["name"] for m in json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/ps", timeout=10)).get("models", [])]


def warm(model, messages, tools=None):
    """Reads the prompt ahead without answering, so the next real answer can reuse it. Same request as a real one, one word long."""
    body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": KEEP,
            "options": {"temperature": 0.3, "num_thread": THREADS, "num_predict": 1}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(CFG["ollama_url"] + "/api/chat", json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        r.read()


def has_room(model):
    """Loading it wouldn't crowd the graphics card (a video or game next to it would stutter). Without a card to ask, yes."""
    free = gpu_free()
    if free is None or not GPU_FREE:
        return True
    tags = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/tags", timeout=10)).get("models", [])
    size = next((m["size"] for m in tags if m["name"].removesuffix(":latest") == model), None)
    return size is not None and free >= size / 2 ** 20 + GPU_FREE


def chat_stream(model, messages, tools=None):
    """Yields ("token", text) and finally ("done", {"content": str, "tool_calls": [...]})."""
    global _used
    _used = time.time()
    body = {"model": model, "messages": messages, "stream": True, "think": False, "keep_alive": KEEP,
            "options": {"temperature": 0.3, "num_thread": THREADS}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(CFG["ollama_url"] + "/api/chat", json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    content, calls = [], []
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            _used = time.time()
            if not line.strip():
                continue
            ev = json.loads(line)
            msg = ev.get("message", {})
            if msg.get("content"):
                content.append(msg["content"])
                yield "token", msg["content"]
            for tc in msg.get("tool_calls") or []:
                calls.append(tc["function"])
            if ev.get("done"):
                _timing(ev)
                break
    yield "done", {"content": "".join(content), "tool_calls": calls}


def complete(model, messages, as_json=False):
    """One non-streamed answer (used by background jobs). as_json asks Ollama for valid JSON."""
    global _used
    _used = time.time()
    body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": KEEP,
            "options": {"temperature": 0.1, "num_thread": THREADS}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(CFG["ollama_url"] + "/api/chat", json.dumps(body).encode(), {"content-type": "application/json"})
    answer = json.load(urllib.request.urlopen(req, timeout=600))["message"]["content"]
    _used = time.time()
    return answer
