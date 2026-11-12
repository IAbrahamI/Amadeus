"""Amadeus' own project, end to end on a throw-away git repository standing in for the running install: the idea,
a fresh copy, a change made there (standing in for Claude Code), the review with a real test run, the install as one
commit, and every refusal on the way."""
import os
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import db, selfimprove as si, updates, work


def _read(path):
    with open(path) as f:
        return f.read()


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


class OwnProject(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amadeus-root-")
        os.makedirs(os.path.join(self.root, "core", "tests"))
        with open(os.path.join(self.root, "core", "calc.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        with open(os.path.join(self.root, "core", "tests", "__init__.py"), "w") as f:
            f.write("")
        with open(os.path.join(self.root, "core", "tests", "test_calc.py"), "w") as f:
            f.write(textwrap.dedent("""
                import unittest
                from calc import add
                class T(unittest.TestCase):
                    def test_add(self):
                        self.assertEqual(add(2, 3), 5)
            """))
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "start")
        self.p = [mock.patch.object(updates, "ROOT", self.root), mock.patch.object(si.updates, "mode", return_value="git"),
                  mock.patch.object(work, "claude_path", return_value="/bin/true"),
                  mock.patch.object(work, "start", return_value=("job1", si.PROJECT)),
                  mock.patch.object(si, "_restart_soon"), mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                                                                                       "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid"})]
        for x in self.p:
            x.start()
        db.set_setting(si.KEY, [])

    def tearDown(self):
        for x in self.p:
            x.stop()

    def _finish_run(self, code_change):
        code = si._code()
        with open(os.path.join(code, "core", "calc.py"), "w") as f:
            f.write(code_change)
        db.q("INSERT OR REPLACE INTO work_jobs(id,project,folder,status,created,summary) VALUES(?,?,?,?,?,?)",
             ("job1", si.PROJECT, os.path.dirname(code), "done", 0, "Changed calc.py"))

    def test_idea_to_install(self):
        i = si.add_idea("Subtract too", "It can only add", "you")
        self.assertEqual(si.add_idea("subtract TOO", "asked again")["id"], i["id"])  # one idea, both reasons
        self.assertIn("It can only add", si.brief(i["id"]))
        si.start(i["id"], "brief")
        self.assertEqual(si._idea(i["id"])["status"], "working")
        other = si.add_idea("Something else", "")
        with self.assertRaisesRegex(ValueError, "install or discard"):
            si.start(other["id"], "brief")  # one at a time
        self._finish_run("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        si.refresh()
        r = si.review(i["id"])
        self.assertTrue(r["tests_ok"], r["tests"])
        self.assertIn("def sub", r["diff"])
        out = si.install(i["id"])
        self.assertTrue(out["ok"])
        self.assertIn("def sub", _read(os.path.join(self.root, "core", "calc.py")))
        self.assertIn("Subtract too", git(self.root, "log", "-1", "--format=%s"))
        self.assertEqual(si._idea(i["id"])["status"], "installed")
        si._restart_soon.assert_called_once()

    def test_failing_tests_or_a_changed_install_refuse(self):
        i = si.add_idea("Break it", "")
        si.start(i["id"], "brief")
        self._finish_run("def add(a, b):\n    return a - b\n")
        r = si.review(i["id"])
        self.assertFalse(r["tests_ok"])
        with self.assertRaisesRegex(ValueError, "tests"):
            si.install(i["id"])
        si.discard(i["id"])
        self.assertEqual(si._idea(i["id"])["status"], "open")
        self.assertNotIn("a - b", _read(os.path.join(si._code(), "core", "calc.py")))
        # a change made after the review isn't installed unseen
        si.start(i["id"], "brief")
        self._finish_run("def add(a, b):\n    return b + a\n")
        si.review(i["id"])
        with open(os.path.join(si._code(), "core", "calc.py"), "a") as f:
            f.write("# later\n")
        with self.assertRaisesRegex(ValueError, "Review"):
            si.install(i["id"])
        # your own uncommitted work in the running install is never mixed in
        si.review(i["id"])
        with open(os.path.join(self.root, "core", "calc.py"), "a") as f:
            f.write("# mine\n")
        with self.assertRaisesRegex(ValueError, "aren't committed"):
            si.install(i["id"])

    def test_not_for_a_packaged_install(self):
        with mock.patch.object(si.updates, "mode", return_value="package"):
            self.assertIn("git", si.available())
            with self.assertRaises(ValueError):
                si.start(si.add_idea("Anything here", "")["id"], "brief")

    def test_the_tool_only_notes_it(self):
        self.assertIn("Noted", si.suggest("Read scanned PDFs", "The user sent a scan and I couldn't read it"))
        work.start.assert_not_called()
        self.assertEqual(si.ideas()[-1]["source"], "amadeus")


if __name__ == "__main__":
    unittest.main()
