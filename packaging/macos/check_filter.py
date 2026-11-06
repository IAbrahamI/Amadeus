#!/usr/bin/env python3
"""On a build machine: installs the Mac privacy filter and proves it's sealed. Each check also runs without the seal, where it must
work: otherwise a failure in the seal would prove nothing."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.getcwd())
from amadeus_core import macfilter, privacy, system  # noqa: E402

assert system.MAC
home = os.path.expanduser("~")
os.makedirs(os.path.join(home, ".ssh"), exist_ok=True)
secret = os.path.join(home, ".ssh", "id_test")
open(secret, "w").write("secret")
macfilter.os.makedirs(macfilter.HOME, exist_ok=True)

t = time.time()
macfilter.install(print)
print(f"installed in {time.time() - t:.0f}s")

ATTEMPTS = {
    "the internet by address": "import socket; socket.create_connection(('1.1.1.1', 53), timeout=4)",
    "the internet by name": "import urllib.request; urllib.request.urlopen('http://example.com', timeout=6)",
    "name lookup": "import socket; socket.getaddrinfo('example.com', 443)",
    "reading your files": f"open({secret!r}).read()",
    "writing a file at home": f"open({os.path.join(home, 'written')!r}, 'w').write('x')",
    "writing a temporary file": "open('/tmp/amadeus-filter-written', 'w').write('x')",
}
failed = False
for name, code in ATTEMPTS.items():
    free = subprocess.run([macfilter.PYTHON, "-c", code], capture_output=True, timeout=30).returncode == 0
    sealed = subprocess.run(macfilter.command(["-c", code]), capture_output=True, timeout=30).returncode == 0
    ok = free and not sealed
    failed |= not ok
    print(f"{'ok ' if ok else 'BAD'} {name}: without the seal {'works' if free else 'FAILS'}, sealed {'WORKS' if sealed else 'blocked'}")
assert not failed, "the seal doesn't hold"

t = time.time()
macfilter.start()
print(f"start and load: {time.time() - t:.1f}s")
text = "Please write to Anna Schmidt in Berlin about the invoice."
t = time.time()
clean, findings, hold = privacy.scrub(text)
print(f"first check: {time.time() - t:.2f}s")
t = time.time()
privacy.scrub("Anna Schmidt lebt in Berlin und das ist nicht neu.")
print(f"second check: {time.time() - t:.2f}s")
print(findings, hold)
assert "Anna" not in clean and "Berlin" not in clean and not hold, clean
macfilter.stop()
print("filter works, sealed")
