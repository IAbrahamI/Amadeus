import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from . import HOME
from amadeus_core import obsidian
from amadeus_core.config import CFG, CONFIG_PATH, DEFAULTS


class Obsidian(unittest.TestCase):
    """Obsidian is optional: to-dos and notes work without it, and connecting never overwrites anything."""

    def setUp(self):
        self.vault = tempfile.mkdtemp(dir=HOME, prefix="vault")
        os.makedirs(os.path.join(self.vault, ".obsidian"))
        self.notes = tempfile.mkdtemp(dir=HOME, prefix="notes")
        self.env = mock.patch.dict(CFG, {"vault_dir": self.notes, "projects_dir": os.path.join(HOME, "Projects")})
        self.env.start()
        self.addCleanup(self.env.stop)
        for target in ("amadeus_core.obsidian.subprocess.run", "amadeus_core.obsidian._restart", "amadeus_core.obsidian.workguard.install"):
            p = mock.patch(target, return_value=mock.Mock(returncode=0, stdout="", stderr=""))
            setattr(self, target.rsplit(".", 1)[1], p.start())
            self.addCleanup(p.stop)

    def test_works_without_a_vault(self):
        self.assertTrue(DEFAULTS["vault_dir"].endswith("amadeus/notes"))
        self.assertFalse(obsidian.status()["connected"])

    def test_connect_copies_notes_and_keeps_what_is_there(self):
        Path(os.path.join(self.notes, "ToDo.md")).write_text("mine here\n")
        Path(os.path.join(self.notes, "Notes.md")).write_text("from amadeus\n")
        os.makedirs(os.path.join(self.vault, "Amadeus"))
        Path(os.path.join(self.vault, "Amadeus", "Notes.md")).write_text("already in the vault\n")
        r = obsidian.connect(self.vault)
        self.assertEqual(r["kept"], ["Notes.md"])
        self.assertEqual(Path(os.path.join(self.vault, "Amadeus", "ToDo.md")).read_text(), "mine here\n")
        self.assertEqual(Path(os.path.join(self.vault, "Amadeus", "Notes.md")).read_text(), "already in the vault\n")
        self.assertEqual(Path(os.path.join(self.notes, "ToDo.md")).read_text(), "mine here\n")
        args, kw = self.run.call_args
        self.assertEqual(args[0][1:], ["--only", "obsidian"])
        self.assertEqual(kw["env"]["OBSIDIAN_VAULT"], os.path.realpath(self.vault))
        self.install.assert_called_once()

    def test_only_a_real_vault_inside_home(self):
        for bad in ("", "/tmp", HOME, self.notes):
            with self.assertRaises(ValueError):
                obsidian.connect(bad)

    def test_not_with_the_projects_inside_it(self):
        with mock.patch.dict(CFG, {"projects_dir": os.path.join(self.vault, "Projects")}), self.assertRaises(ValueError):
            obsidian.connect(self.vault)

    def test_disconnect_goes_back_and_leaves_the_files(self):
        os.makedirs(os.path.join(self.vault, "Amadeus"))
        Path(os.path.join(self.vault, "Amadeus", "ToDo.md")).write_text("x\n")
        with mock.patch.dict(CFG, {"vault_dir": os.path.join(self.vault, "Amadeus")}):
            self.assertTrue(obsidian.status()["connected"])
            obsidian.disconnect()
        self.assertEqual(json.loads(Path(CONFIG_PATH).read_text())["vault_dir"], DEFAULTS["vault_dir"])
        self.assertTrue(os.path.exists(os.path.join(self.vault, "Amadeus", "ToDo.md")))


class OptionalApps(unittest.TestCase):
    """Without an optional app only that part stays off, and its tools never reach the model."""

    def test_no_thunderbird_setup_no_mail_tools_and_it_never_starts(self):
        from amadeus_core import background, mailbridge, tools
        with mock.patch.object(mailbridge, "configured", return_value=False), mock.patch.object(mailbridge, "thunderbird_set_up", return_value=False), \
                mock.patch("subprocess.run") as run, mock.patch.object(tools, "launch") as launch:
            self.assertIn("Not connected", tools.missing("mail"))
            names = {t["function"]["name"] for t in tools.schemas()}
            self.assertFalse(names & {t["name"] for t in tools.TOOLS if t["connector"] == "mail"})
            background.keep_apps()
            self.assertFalse(mailbridge._start_thunderbird())
            launch.assert_not_called()
            run.assert_not_called()

    def test_no_claude_code_no_work_tools(self):
        from amadeus_core import tools, work
        with mock.patch("shutil.which", return_value=None):
            self.assertIn("Claude Code", tools.missing("work"))
            self.assertFalse({t["function"]["name"] for t in tools.schemas()} & {t["name"] for t in tools.TOOLS if t["connector"] == "work"})
            self.assertIn("isn't installed", work.start("Demo", "do it"))

    def test_no_tailscale_is_fine(self):
        from amadeus_core import playbooks
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(playbooks.phone_status(), "private")
