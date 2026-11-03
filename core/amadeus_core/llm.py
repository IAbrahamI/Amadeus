"""Local model access through Ollama (chat with tool calling, streamed)."""
import json
import os
import urllib.request

from .config import CFG


# The model gets at most this many CPU threads (it runs on the GPU; the threads only matter for the layers that don't
# fit there). Using every core made the window and the desktop stutter while it wrote; half the cores is as fast.
THREADS = CFG.get("llm_threads") or max(2, (os.cpu_count() or 8) // 4)
KEEP = CFG.get("llm_keep_alive", "30m")  # stays loaded between questions, so it doesn't reload every few minutes


def list_models():
    data = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/tags", timeout=10))
    return sorted(m["name"].removesuffix(":latest") for m in data.get("models", []))


def chat_stream(model, messages, tools=None):
    """Yields ("token", text) and finally ("done", {"content": str, "tool_calls": [...]})."""
    body = {"model": model, "messages": messages, "stream": True, "think": False, "keep_alive": KEEP,
            "options": {"temperature": 0.3, "num_thread": THREADS}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(CFG["ollama_url"] + "/api/chat", json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    content, calls = [], []
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
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
                break
    yield "done", {"content": "".join(content), "tool_calls": calls}


def complete(model, messages, as_json=False):
    """One non-streamed answer (used by background jobs). as_json asks Ollama for valid JSON."""
    body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": KEEP,
            "options": {"temperature": 0.1, "num_thread": THREADS}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(CFG["ollama_url"] + "/api/chat", json.dumps(body).encode(), {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))["message"]["content"]
