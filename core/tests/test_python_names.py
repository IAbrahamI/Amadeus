"""Every Python file in the repo only uses names that exist: a missing import (like `sys` in a service script) is
caught here instead of by a service that restarts forever. Uses the compiler's own symbol tables, no extra tools."""
import builtins
import os
import subprocess
import symtable
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__builtins__", "__loader__", "__package__",
                                 "__path__", "__annotations__", "__dict__", "__module__", "__qualname__", "__class__"}


def _files():
    """The repository's Python files (git's list; in a copy without git, every .py file outside hidden folders)."""
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode == 0:
        return [os.path.join(ROOT, f) for f in out.stdout.split() if os.path.exists(os.path.join(ROOT, f))]
    found = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("node_modules", "target", "__pycache__")]
        found += [os.path.join(d, f) for f in files if f.endswith(".py")]
    return found


def _missing(path):
    src = open(path, encoding="utf-8").read()
    if "import *" in src:
        return []
    top = symtable.symtable(src, path, "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    bad = []

    def walk(t):
        for s in t.get_symbols():
            used = s.is_referenced()
            global_ = s.is_global() or (t is top and not (s.is_assigned() or s.is_imported() or s.is_namespace()))
            if used and global_ and s.get_name() not in defined and s.get_name() not in BUILTINS:
                bad.append(f"{os.path.relpath(path, ROOT)}: {s.get_name()} (in {t.get_name()})")
        for c in t.get_children():
            walk(c)
    walk(top)
    return bad


class PythonNames(unittest.TestCase):
    def test_no_undefined_names(self):
        bad = [b for f in _files() for b in _missing(f)]
        self.assertEqual(bad, [], "names used but never imported or defined")


if __name__ == "__main__":
    unittest.main()
