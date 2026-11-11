"""The dashboard's scripts share one global scope: a name declared twice silently replaces the first (that once stopped
the core from moving when the window was resized, because the workspace declared its own place())."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
TOP = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^(?:const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)


def scripts(page):
    return [WEB / s.lstrip("/") for s in re.findall(r'<script src="([^"]+\.js)"', (WEB / page).read_text())]


class OneScope(unittest.TestCase):
    def test_no_name_is_declared_twice(self):
        for page in ("index.html", "mini.html"):
            seen = {}
            for f in scripts(page):
                if not f.exists():
                    continue
                for m in TOP.finditer(f.read_text()):
                    name = m.group(1) or m.group(2)
                    with self.subTest(page=page, name=name):
                        self.assertNotIn(name, seen, f"{name} is declared in both {seen.get(name)} and {f.name}")
                    seen[name] = f.name


if __name__ == "__main__":
    unittest.main()
