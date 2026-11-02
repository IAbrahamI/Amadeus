import unittest
from unittest import mock

from . import HOME  # noqa: F401  (sets up the throw-away home first)
from amadeus_core import privacy


class Patterns(unittest.TestCase):
    def label(self, text):
        for name, rx in privacy.PATTERNS:
            text = rx.sub(f"[{name}]", text)
        return text

    def test_contact_details(self):
        self.assertEqual(self.label("Write to anna@example.com or call 0176 1234567."), "Write to [EMAIL] or call [PHONE].")

    def test_keys_and_paths(self):
        out = self.label("key sk-abcdefghijklmnop1234 in /home/someone/notes.txt")
        self.assertIn("[KEY]", out)
        self.assertIn("[PATH]", out)

    def test_local_urls_and_ips(self):
        out = self.label("see http://192.168.1.20:8080/x and 10.0.0.5")
        self.assertIn("[URL]", out)
        self.assertIn("[IP]", out)

    def test_iban(self):
        self.assertIn("[IBAN]", self.label("IBAN DE89 3704 0044 0532 0130 00"))


class Scrub(unittest.TestCase):
    def test_canary_and_denylist_hold(self):
        with mock.patch.object(privacy, "ensure_presidio"), mock.patch.object(privacy, "_ner", return_value=[]):
            self.assertTrue(privacy.scrub("note: CANARY-testmarker123")[2])
            self.assertTrue(privacy.scrub("about project bluebird")[2])
            self.assertFalse(privacy.scrub("plain text")[2])

    def test_fails_closed_without_presidio(self):
        with mock.patch.object(privacy, "ensure_presidio"), mock.patch.object(privacy, "_ner", side_effect=OSError("down")):
            clean, findings, hold = privacy.scrub("Anna lives in Berlin")
        self.assertTrue(hold)
        self.assertIn("presidio-unavailable", findings)


if __name__ == "__main__":
    unittest.main()
