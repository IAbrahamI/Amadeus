import json
import os
from pathlib import Path
import stat
import time
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import work


class Workspace(unittest.TestCase):
    """The workspace view: you edit a project's files, and see what a running Claude Code does."""

    def setUp(self):
        self.name, self.folder = work._folder("Workspace test")

    def test_save_and_read_back(self):
        saved = work.save_file(self.name, "src/app.py", "print('hi')\n")
        self.assertEqual(saved["path"], os.path.join("src", "app.py"))
        got = work.project_file(self.name, "src/app.py")
        self.assertEqual(got["text"], "print('hi')\n")
        self.assertAlmostEqual(got["modified"], saved["modified"], places=3)
        self.assertIn("src/app.py", [f["path"] for f in work.changes(self.name)["files"]])

    def test_never_over_a_newer_version(self):
        first = work.save_file(self.name, "notes.md", "one")
        time.sleep(0.02)
        Path(self.folder, "notes.md").write_text("the agent was here")
        with self.assertRaises(work.Changed):
            work.save_file(self.name, "notes.md", "mine", seen=first["modified"])
        self.assertEqual(Path(self.folder, "notes.md").read_text(), "the agent was here")
        work.save_file(self.name, "notes.md", "mine", seen=None)  # you chose to overwrite
        self.assertEqual(Path(self.folder, "notes.md").read_text(), "mine")

    def test_only_inside_the_project(self):
        for bad in ("../outside.txt", ".git/config", "a/.env", "", "../Other/x.md"):
            with self.assertRaises(ValueError, msg=bad):
                work.save_file(self.name, bad, "x")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.folder), "outside.txt")))

    def test_steps_from_claude_codes_live_output(self):
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "I'll write the script."},
            {"type": "tool_use", "name": "Write", "input": {"file_path": os.path.join(self.folder, "test.py"), "content": "x"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "python3 test.py"}}]}})
        steps = work._step(self.folder, line)
        self.assertEqual([(s["text"], s["path"]) for s in steps], [("I'll write the script.", ""), ("Writing test.py", "test.py"), ("Running python3 test.py", "")])
        self.assertEqual(work._step(self.folder, "not json"), [])
        self.assertEqual(work._step(self.folder, json.dumps({"type": "result", "result": "done"})), [])

    def test_a_run_is_watched_and_its_result_read_as_before(self):
        fake = os.path.join(HOME, "fake-claude")
        target = os.path.join(self.folder, "test.py")
        Path(fake).write_text("#!/bin/sh\n" + "\n".join("echo '%s'" % json.dumps(e) for e in (
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": target}}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "Wrote test.py.", "session_id": "s1", "total_cost_usd": 0.01})) + "\n")
        os.chmod(fake, stat.S_IRWXU)
        seen = []
        real = work._step

        def spy(folder, line):
            got = real(folder, line)
            seen.extend(got)
            return got
        with mock.patch.object(work, "_step", spy):
            p = work._watched([fake], self.folder, dict(os.environ), "job1")
        self.assertEqual(p.returncode, 0)
        self.assertEqual([s["text"] for s in seen], ["Writing test.py"])
        last = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual((last["result"], last["session_id"], last["total_cost_usd"]), ("Wrote test.py.", "s1", 0.01))
        self.assertNotIn("job1", work.LIVE)  # nothing is left behind when it's over


class OwnProject(unittest.TestCase):
    """In a project's own chat, handing work to that same project runs without an approval card."""

    def test_only_the_same_project_skips_approval(self):
        from amadeus_core import agent
        cid = work.project_chat("Example")
        with mock.patch.object(agent, "_read_mail_recently", return_value=False):
            self.assertTrue(agent._own_project(cid, "continue_project", {"project": "example"}))
            self.assertTrue(agent._own_project(cid, "send_to_work", {"project": "Example"}))
            self.assertFalse(agent._own_project(cid, "send_to_work", {"project": "Other"}))
            self.assertFalse(agent._own_project(cid, "send_to_work", {}))
            self.assertFalse(agent._own_project(cid, "send_mail", {"project": "Example"}))
            self.assertFalse(agent._own_project(work.project_chat("Other") and "not-a-chat", "continue_project", {"project": "Example"}))
        with mock.patch.object(agent, "_read_mail_recently", return_value=True):  # a mail could have asked for it
            self.assertFalse(agent._own_project(cid, "continue_project", {"project": "Example"}))


class Presence(unittest.TestCase):
    """Where Claude Code is while it writes a tool call, from its partial output, like a co-author's cursor."""

    def setUp(self):
        self.name, self.folder = work._folder("Presence test")
        Path(self.folder, "f.txt").write_text("a\nb\nc\n")

    def feed(self, p, *chunks, tool="Edit"):
        p.feed({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": tool, "input": {}}}})
        for c in chunks:
            p.last = 0
            p.feed({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": c}}})
        return p.at()

    def test_partial_strings(self):
        self.assertEqual(work._partial('{"a": "x\\ny', "a"), ("x\ny", False))
        self.assertEqual(work._partial('{"a": "x\\"y"}', "a"), ('x"y', True))
        self.assertEqual(work._partial('{"a": "x\\', "a"), ("x", False))  # an escape cut in half waits
        self.assertIsNone(work._partial('{"b": "x"', "a"))

    def test_edit_shows_line_and_the_new_text(self):
        p = work.Presence(self.folder)
        path = json.dumps(os.path.join(self.folder, "f.txt"))
        at = self.feed(p, '{"file_path": ' + path, ', "old_string": "b\\nc", "new_string": "B')
        self.assertEqual((at["path"], at["kind"], at["line"]), ("f.txt", "editing", 2))
        self.assertEqual(at["text"], "a\nB\n")
        self.assertTrue(p.landed())
        self.assertIsNone(p.at()["text"])

    def test_write_cursor_moves_down_as_it_types(self):
        p = work.Presence(self.folder)
        path = json.dumps(os.path.join(self.folder, "new.py"))
        at = self.feed(p, '{"file_path": ' + path, ', "content": "one\\ntwo\\nthr', tool="Write")
        self.assertEqual((at["kind"], at["line"], at["text"]), ("writing", 3, "one\ntwo\nthr"))

    def test_outside_the_project_is_ignored(self):
        p = work.Presence(self.folder)
        self.assertIsNone(self.feed(p, '{"file_path": "/etc/passwd"}', tool="Read"))
