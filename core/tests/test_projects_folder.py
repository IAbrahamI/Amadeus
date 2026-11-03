import json
import os
import subprocess
import sys
import unittest

from . import HOME
from amadeus_core import work, workguard
from amadeus_core.config import CFG


class ProjectsFolder(unittest.TestCase):
    """Projects live in a folder you choose, outside the vault; moving them takes their Claude Code sessions along."""

    def setUp(self):
        os.makedirs(CFG["vault_dir"], exist_ok=True)
        CFG["projects_dir"] = ""  # an older install: the projects are in the vault

    def test_move_out_of_the_vault(self):
        old = os.path.join(CFG["vault_dir"], "Projects", "Demo")
        os.makedirs(old, exist_ok=True)
        open(os.path.join(old, "Overview.md"), "w").write("# Demo\n")
        sess = os.path.join(HOME, ".claude", "projects", "".join(c if c.isalnum() else "-" for c in os.path.realpath(old)))
        os.makedirs(sess, exist_ok=True)
        self.assertTrue(work.folder_info()["in_vault"])
        new = os.path.join(HOME, "Amadeus", "Projects")
        r = work.set_folder(new, move=True)
        self.assertEqual(r["moved"], ["Demo"])
        self.assertFalse(r["in_vault"])
        self.assertTrue(os.path.isfile(os.path.join(new, "Demo", "Overview.md")))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(os.path.join(HOME, ".claude", "projects", "".join(c if c.isalnum() else "-" for c in os.path.realpath(os.path.join(new, "Demo"))))))
        self.assertTrue(os.path.isfile(os.path.join(workguard.GUARD, "settings.json")))

    def test_no_folder_inside_the_vault_or_outside_home(self):
        with self.assertRaises(ValueError):
            work.set_folder(os.path.join(os.path.dirname(CFG["vault_dir"]), "Work"))
        with self.assertRaises(ValueError):
            work.set_folder("/tmp")

    def test_guard_writes_only_in_projects_and_keeps_out_of_the_vault(self):
        projects = os.path.join(HOME, "P")
        vault = os.path.dirname(CFG["vault_dir"])
        os.makedirs(os.path.join(HOME, "g"), exist_ok=True)
        g = os.path.join(HOME, "g", "guard.py")  # its own folder, like the real guard (it protects that folder)
        open(g, "w").write(workguard.files(projects, vault)["work-guard.py"][0])
        def allowed(tool, path):
            r = subprocess.run([sys.executable, g], input=json.dumps({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": projects}),
                               capture_output=True, text=True)
            return r.returncode == 0
        self.assertTrue(allowed("Write", os.path.join(projects, "a", "x.md")))
        self.assertFalse(allowed("Write", os.path.join(HOME, "elsewhere.md")))
        self.assertFalse(allowed("Read", os.path.join(vault, "Amadeus", "ToDo.md")))
        self.assertFalse(allowed("Read", os.path.join(HOME, ".ssh", "id_ed25519")))


if __name__ == "__main__":
    unittest.main()
