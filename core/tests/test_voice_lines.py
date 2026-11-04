import os
import tempfile
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import db, tools, voices


class Reply:
    def read(self):
        return b"RIFFaudio"


class VoiceLines(unittest.TestCase):
    """Short lines are made once, per voice, and then come from the file."""

    def test_made_once_then_from_the_file(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(voices, "LINES_DIR", d), \
                mock.patch.object(voices, "selected", return_value="kokoro:bm_george"), \
                mock.patch("urllib.request.urlopen", return_value=Reply()) as call:
            self.assertEqual(voices.line("done"), b"RIFFaudio")
            self.assertEqual(voices.line("done"), b"RIFFaudio")
            self.assertEqual(call.call_count, 1)
            self.assertTrue(os.path.exists(voices._line_file("Done.", "kokoro:bm_george")))

    def test_each_voice_has_its_own(self):
        self.assertNotEqual(voices._line_file("Okay.", "a"), voices._line_file("Okay.", "b"))

    def test_no_voice_no_line(self):
        with mock.patch.object(voices, "selected", return_value=""):
            self.assertIsNone(voices.line("greet"))


class ReminderApproval(unittest.TestCase):
    """Approving a removal says what's being removed, not an id."""

    def test_says_the_reminder(self):
        out = tools.create_reminder("Call the dentist", "tomorrow 09:00")
        rid = out.rsplit("[id ", 1)[1].rstrip("].")
        text = tools._delete_reminder_summary({"reminder_id": rid})
        self.assertIn("Call the dentist", text)
        self.assertNotIn(rid, text)
        db.q("DELETE FROM reminders WHERE id=?", (rid,))

    def test_gone(self):
        self.assertIn("already gone", tools._delete_reminder_summary({"reminder_id": "nope"}))
