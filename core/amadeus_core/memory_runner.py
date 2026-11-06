#!/usr/bin/env python3
"""Runs the memory on a Mac: its database and Hindsight, sealed off together (macmemory.py starts this under the seal). Standard
library only. If the seal doesn't hold it stops at once, and Amadeus simply has no memory until that's fixed."""
import json
import os
import signal
import socket
import subprocess
import sys
import time


def can_reach_outside():
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=3):
            return True
    except OSError:
        return False


def clear_old_database(data):
    """A database left running by a crash has to go first, or a new one can't start."""
    try:
        with open(os.path.join(data, "postmaster.pid")) as f:
            pid = int(f.readline())
        os.kill(pid, signal.SIGINT)
    except (OSError, ValueError):
        return
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)


def wait_for_port(port, seconds=60):
    for _ in range(seconds * 2):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    with open(sys.argv[1]) as f:
        cfg = json.load(f)
    sealed = "--unsealed" not in sys.argv
    if sealed and can_reach_outside():
        print("the memory isn't sealed off, so it doesn't start", flush=True)
        return 3
    clear_old_database(cfg["data"])
    env = {"PATH": "/usr/bin:/bin", "HOME": cfg["home"], "HF_HOME": os.path.join(cfg["home"], "hf"), "PYTHONPATH": cfg["ext"], "PYTHONDONTWRITEBYTECODE": "1",
           **cfg["env"], **({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"} if sealed else {})}
    database = subprocess.Popen([cfg["postgres"], "-D", cfg["data"], "-p", str(cfg["db_port"]), "-c", "listen_addresses=127.0.0.1",
                                 "-c", "unix_socket_directories=", "-c", "logging_collector=off"], env=env, stdout=sys.stdout, stderr=sys.stderr)
    children = [database]

    def stop(*_):
        for p in children:
            if p.poll() is None:
                p.send_signal(signal.SIGINT if p is database else signal.SIGTERM)
        for p in children:
            try:
                p.wait(timeout=25)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not wait_for_port(cfg["db_port"]):
        print("the memory's database didn't start", flush=True)
        stop()
    children.insert(0, subprocess.Popen([cfg["hindsight"]], env=env, stdout=sys.stdout, stderr=sys.stderr))
    while all(p.poll() is None for p in children):
        if not os.path.exists(sys.executable):  # the app was removed
            stop()
        time.sleep(3)
    stop()


if __name__ == "__main__":
    sys.exit(main())
