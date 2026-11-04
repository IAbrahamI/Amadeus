import threading
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import desktop, events


class Desktop(unittest.TestCase):
    """The core tells the desktop app what to show through a waiting request."""

    def setUp(self):
        desktop.wait(0)

    def test_a_waiting_request_gets_the_command_right_away(self):
        got = []
        t = threading.Thread(target=lambda: got.extend(desktop.wait(5)))
        t.start()
        desktop.send({"do": "call"})
        t.join(2)
        self.assertEqual(got, [{"do": "call"}])

    def test_old_commands_are_dropped(self):
        desktop.send({"do": "call"})
        with mock.patch.object(desktop.time, "time", return_value=desktop.time.time() + desktop.FRESH + 1):
            self.assertEqual(desktop.wait(0), [])

    def test_connected_only_while_it_keeps_asking(self):
        desktop.wait(0)
        self.assertTrue(desktop.connected())
        with mock.patch.object(desktop.time, "time", return_value=desktop.time.time() + desktop.WAIT + 16):
            self.assertFalse(desktop.connected())

    def test_an_open_window_needs_the_app_running(self):
        desktop.wait(0)
        desktop.set_open(True)
        self.assertTrue(desktop.window_open())
        with mock.patch.object(desktop.time, "time", return_value=desktop.time.time() + desktop.WAIT + 16):
            self.assertFalse(desktop.window_open())
        desktop.set_open(False)

    def test_a_new_event_calls_through_the_app(self):
        desktop.wait(0)
        desktop.set_open(False)
        with mock.patch.object(events, "quiet", return_value=False), mock.patch("amadeus_core.phoneapp.in_use", return_value=False), \
                mock.patch("amadeus_core.push.notify"):
            events.add("job", "Done")
        self.assertIn({"do": "call"}, desktop.wait(0))
