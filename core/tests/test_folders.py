import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from . import HOME
from amadeus_core import folders, notesfolder
from amadeus_core.config import CFG, CONFIG_PATH


class Places(unittest.TestCase):
    """One folder for a new install; an earlier install keeps its places without anything moving."""

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())

    def test_new_install(self):
        p = folders.paths({}, self.home)
        self.assertEqual(p["notes"], os.path.join(self.home, "Amadeus", "Notes"))
        self.assertEqual(p["notes_root"], p["notes"])
        self.assertEqual(p["projects"], os.path.join(self.home, "Amadeus", "Projects"))

    def test_the_folder_you_chose(self):
        p = folders.paths({"folder": os.path.join(self.home, "Mine")}, self.home)
        self.assertEqual(p["notes"], os.path.join(self.home, "Mine", "Notes"))
        self.assertEqual(p["projects"], os.path.join(self.home, "Mine", "Projects"))

    def test_notes_in_a_vault_only_when_you_set_that(self):
        amadeus = os.path.join(self.home, "Documents", "Obsidian Vault", "Amadeus")
        os.makedirs(amadeus)
        self.assertEqual(folders.paths({}, self.home)["notes"], os.path.join(self.home, "Amadeus", "Notes"))  # never picked up by itself
        p = folders.paths({"notes_dir": amadeus, "notes_root": os.path.dirname(amadeus), "projects_dir": os.path.join(self.home, "P")}, self.home)
        self.assertEqual(p["notes"], amadeus)
        self.assertEqual(p["notes_root"], os.path.dirname(amadeus))
        self.assertEqual(p["projects"], os.path.join(self.home, "P"))

    def test_config_from_the_connector(self):
        p = folders.paths({"vault_dir": os.path.join(self.home, "V", "Amadeus")}, self.home)
        self.assertEqual(p["notes_root"], os.path.join(self.home, "V"))
        self.assertEqual(p["projects"], os.path.join(self.home, "V", "Amadeus", "Projects"))

    def test_notes_from_before_the_folder_stay_found(self):
        earlier = os.path.join(self.home, ".local", "share", "amadeus", "notes")
        os.makedirs(earlier)
        self.assertEqual(folders.paths({}, self.home)["notes"], earlier)

    def test_a_changed_notes_folder_wins(self):
        p = folders.paths({"notes_dir": os.path.join(self.home, "N"), "vault_dir": os.path.join(self.home, "V", "A")}, self.home)
        self.assertEqual(p["notes"], os.path.join(self.home, "N"))
        self.assertEqual(p["notes_root"], os.path.join(self.home, "N"))


class Changing(unittest.TestCase):
    """Changing the folder copies your notes over and never overwrites anything."""

    def setUp(self):
        self.old = tempfile.mkdtemp(dir=HOME, prefix="notes")
        self.new = os.path.join(HOME, os.path.basename(self.old) + "-new")
        self.projects = os.path.realpath(os.path.join(HOME, "Projects"))
        env = mock.patch.dict(CFG, {"notes_dir": self.old, "notes_root": self.old, "projects": self.projects})
        env.start()
        self.addCleanup(env.stop)
        for target in ("amadeus_core.notesfolder._restart", "amadeus_core.notesfolder.workguard.install"):
            p = mock.patch(target)
            setattr(self, target.rsplit(".", 1)[1], p.start())
            self.addCleanup(p.stop)

    def test_copies_and_keeps_what_is_there(self):
        Path(self.old, "ToDo.md").write_text("mine\n")
        Path(self.old, "Notes.md").write_text("from before\n")
        os.makedirs(self.new)
        Path(self.new, "Notes.md").write_text("already there\n")
        r = notesfolder.set_notes(self.new)
        self.assertEqual(r["kept"], ["Notes.md"])
        self.assertEqual(Path(self.new, "ToDo.md").read_text(), "mine\n")
        self.assertEqual(Path(self.new, "Notes.md").read_text(), "already there\n")
        self.assertEqual(Path(self.old, "ToDo.md").read_text(), "mine\n")
        self.assertEqual(json.loads(Path(CONFIG_PATH).read_text())["notes_dir"], os.path.realpath(self.new))
        self.install.assert_called_once_with(self.projects, os.path.realpath(self.new))

    def test_only_inside_home_and_apart_from_projects(self):
        for bad in ("", "/tmp", HOME, HOME + "/Projects/Notes"):
            with self.assertRaises(ValueError):
                notesfolder.set_notes(bad)
        with mock.patch.dict(CFG, {"projects": os.path.join(self.new, "Projects")}), self.assertRaises(ValueError):
            notesfolder.set_notes(self.new)


class OwnData(unittest.TestCase):
    def test_in_the_right_place_for_this_system(self):
        from amadeus_core import paths
        import sys
        self.assertEqual(paths.CONFIG_FILE.startswith(os.path.join(HOME, "Library")), sys.platform == "darwin")
        self.assertTrue(paths.DATA.startswith(HOME))
