import unittest
from unittest import mock


class OptionalApps(unittest.TestCase):
    """Without an optional app only that part stays off, and its tools never reach the model."""

    def test_no_mail_account_no_mail_tools_and_nothing_starts(self):
        from amadeus_core import mail, tools
        with mock.patch.object(mail, "configured", return_value=False), \
                mock.patch("subprocess.run") as run, mock.patch.object(tools, "launch") as launch:
            self.assertIn("Not connected", tools.missing("mail"))
            names = {t["function"]["name"] for t in tools.schemas()}
            self.assertFalse(names & {t["name"] for t in tools.TOOLS if t["connector"] == "mail"})
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
