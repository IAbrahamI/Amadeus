import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from . import HOME
from amadeus_core import work, workguard
from amadeus_core.config import CFG


class ProjectsFolder(unittest.TestCase):
    """Projects live in a folder you choose, apart from your notes; moving them takes their Claude Code sessions along."""

    def setUp(self):
        os.makedirs(CFG["notes_dir"], exist_ok=True)
        CFG["projects"] = os.path.join(CFG["notes_dir"], "Projects")  # an older install: the projects are among the notes
        self.addCleanup(CFG.update, projects=os.path.join(HOME, "Projects"))

    def test_move_out_of_the_notes(self):
        old = os.path.join(CFG["notes_dir"], "Projects", "Demo")
        os.makedirs(old, exist_ok=True)
        Path(os.path.join(old, "Overview.md")).write_text("# Demo\n")
        sess = os.path.join(HOME, ".claude", "projects", "".join(c if c.isalnum() else "-" for c in os.path.realpath(old)))
        os.makedirs(sess, exist_ok=True)
        self.assertTrue(work.folder_info()["in_notes"])
        new = os.path.join(HOME, "Amadeus", "Projects")
        r = work.set_folder(new, move=True)
        self.assertEqual(r["moved"], ["Demo"])
        self.assertFalse(r["in_notes"])
        self.assertTrue(os.path.isfile(os.path.join(new, "Demo", "Overview.md")))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(os.path.join(HOME, ".claude", "projects", "".join(c if c.isalnum() else "-" for c in os.path.realpath(os.path.join(new, "Demo"))))))
        self.assertTrue(os.path.isfile(os.path.join(workguard.GUARD, "settings.json")))

    def test_no_folder_inside_the_notes_or_outside_home(self):
        with self.assertRaises(ValueError):
            work.set_folder(os.path.join(CFG["notes_root"], "Work"))
        with self.assertRaises(ValueError):
            work.set_folder("/tmp")

    def test_guard_writes_only_in_projects_and_keeps_out_of_the_notes(self):
        projects = os.path.join(HOME, "P")
        notes = CFG["notes_root"]
        os.makedirs(os.path.join(HOME, "g"), exist_ok=True)
        g = os.path.join(HOME, "g", "guard.py")  # its own folder, like the real guard (it protects that folder)
        Path(g).write_text(workguard.files(projects, notes)["work-guard.py"][0])
        def allowed(tool, path):
            r = subprocess.run([sys.executable, g], input=json.dumps({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": projects}),
                               capture_output=True, text=True)
            return r.returncode == 0
        self.assertTrue(allowed("Write", os.path.join(projects, "a", "x.md")))
        self.assertFalse(allowed("Write", os.path.join(HOME, "elsewhere.md")))
        self.assertFalse(allowed("Read", os.path.join(notes, "ToDo.md")))
        self.assertFalse(allowed("Read", os.path.join(HOME, ".ssh", "id_ed25519")))

    def test_guard_holds_with_a_linked_home_folder(self):
        real = os.path.join(HOME, "real-home")
        os.makedirs(os.path.join(real, ".ssh"), exist_ok=True)
        link = os.path.join(HOME, "linked-home")
        if not os.path.islink(link):
            os.symlink(real, link)
        g = os.path.join(HOME, "g2", "guard.py")
        os.makedirs(os.path.dirname(g), exist_ok=True)
        Path(g).write_text(workguard.files(os.path.join(real, "P"), "")["work-guard.py"][0])
        r = subprocess.run([sys.executable, g], input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": os.path.join(real, ".ssh", "id_ed25519")}}),
                           capture_output=True, text=True, env={**os.environ, "HOME": link})
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
