"""Local model access through Ollama (chat with tool calling, streamed)."""
import json
import urllib.request

from .config import CFG


def list_models():
    data = json.load(urllib.request.urlopen(CFG["ollama_url"] + "/api/tags", timeout=10))
    return sorted(m["name"].removesuffix(":latest") for m in data.get("models", []))


def chat_stream(model, messages, tools=None):
    """Yields ("token", text) and finally ("done", {"content": str, "tool_calls": [...]})."""
    body = {"model": model, "messages": messages, "stream": True, "think": False,
            "options": {"temperature": 0.3}}
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
    body = {"model": model, "messages": messages, "stream": False, "think": False, "options": {"temperature": 0.1}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(CFG["ollama_url"] + "/api/chat", json.dumps(body).encode(), {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))["message"]["content"]
