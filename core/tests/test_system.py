import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import system


class Linux(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(system, "MAC", False)
        p.start()
        self.addCleanup(p.stop)

    def test_services_through_systemd(self):
        with mock.patch("subprocess.run") as run:
            system.restart("amadeus-core", "amadeus-desktop")
        self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "restart", "amadeus-core", "amadeus-desktop"])

    def test_pages(self):
        self.assertEqual(system.page_command("https://x.y"), ["xdg-open", "https://x.y"])
        self.assertEqual(system.page_command("https://x.y", ["firefox"]), ["firefox", "https://x.y"])


class Mac(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(system, "MAC", True)
        p.start()
        self.addCleanup(p.stop)

    def test_services_through_launchd(self):
        with mock.patch("subprocess.run") as run, mock.patch("os.getuid", return_value=501):
            system.restart("amadeus-core", "amadeus-voice")
        self.assertEqual(run.call_args_list[0][0][0], ["launchctl", "kickstart", "-k", "gui/501/com.amadeus.core"])
        self.assertEqual(run.call_args_list[1][0][0], ["launchctl", "kickstart", "-k", "gui/501/com.amadeus.voice"])

    def test_pages(self):
        self.assertEqual(system.page_command("https://x.y"), ["open", "https://x.y"])
        self.assertEqual(system.page_command("https://x.y", ["firefox"]), ["open", "-a", "Firefox", "https://x.y"])

    def test_a_notification_goes_through_the_app(self):
        from amadeus_core import desktop
        with mock.patch.object(desktop, "send") as send, mock.patch("subprocess.run") as run:
            system.notify("Amadeus", 'say "hi"')
        send.assert_called_once_with({"do": "notify", "data": {"title": "Amadeus", "text": 'say "hi"'}})
        run.assert_not_called()

    def test_no_systemd_jobs(self):
        self.assertFalse(system.service_timers())
