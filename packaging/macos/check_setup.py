#!/usr/bin/env python3
"""On a build machine, with the installed app running: goes through the setup as the page does, with the real Ollama and a
real model. The smallest proven model, because these machines have no graphics card worth the name."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

DATA = os.path.expanduser("~/Library/Application Support/Amadeus/core")
TOKEN = open(os.path.join(DATA, "token")).read().strip()


def call(body=None):
    req = urllib.request.Request("http://127.0.0.1:8095/api/setup", json.dumps(body).encode() if body else None,
                                 {"authorization": f"Bearer {TOKEN}", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def run(action, minutes, **extra):
    print(f"--- {action}", flush=True)
    try:
        call({"action": action, **extra})
    except urllib.error.HTTPError as e:  # the page in the app's window may have started the same step
        if e.code != 400:
            raise
    end, said = time.time() + minutes * 60, ""
    while time.time() < end:
        s = call()
        job = s.get("job") or {}
        if job.get("text") != said:
            said = job.get("text")
            print(" ", said, flush=True)
        if job.get("done") and job.get("kind") == action:
            return s, job
        time.sleep(3)
    sys.exit(f"{action} took more than {minutes} minutes")


s, job = run("ollama", 8)
assert not job["error"] and s["ollama"] == "running", job
s, job = run("scan", 15)
assert not job["error"] and s["picks"], job
print("offered:", [(p["model"], p["size"], p["proven"]) for p in s["picks"]], flush=True)
assert s["picks"][0]["proven"], "a proven model comes first"
smallest = min((p for p in s["picks"] if p["proven"]), key=lambda p: p["size"])
s, job = run("begin", 25, model=smallest["model"], folder="")
print("result:", s.get("model_ready"), job["error"] or "passed", flush=True)
assert s["model_ready"], job
print(call({"action": "finish"}))
time.sleep(5)
assert not call()["needed"], "the setup is over"
print("setup finished")
