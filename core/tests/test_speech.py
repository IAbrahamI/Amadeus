import unittest

from . import HOME  # noqa: F401
from amadeus_core.speech import speech_text


class Speech(unittest.TestCase):
    """What's read aloud is what a person would say; the chat keeps the full text."""

    def test_times_dates_markdown_links(self):
        t = speech_text("**Dentist** at 14:00, the call 15:30–16:00 on 2031-11-05. See [notes](https://x.y) 🎉 [mood:happy]")
        self.assertEqual(t, "Dentist at 2 PM, the call 3:30 PM to 4 PM on November 5 2031. See notes.")

    def test_german_times(self):
        self.assertIn("14 Uhr 30", speech_text("Um 14:30.", "de"))

    def test_long_lists_and_code_stay_in_the_chat(self):
        t = speech_text("Open:\n" + "\n".join(f"- item {i}" for i in range(8)) + "\n```\ncode\n```")
        self.assertIn("and 4 more, see the chat.", t)
        self.assertIn("The code is in the chat.", t)
        self.assertNotIn("item 5", t)

    def test_a_long_answer_is_cut(self):
        t = speech_text("This is one sentence. " * 60)
        self.assertTrue(t.endswith("The rest is in the chat."))
        self.assertLess(len(t), 700)


if __name__ == "__main__":
    unittest.main()
