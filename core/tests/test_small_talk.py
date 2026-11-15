"""Small talk gets a small answer: "how are you" doesn't pull in memories about the calendar, lessons about to-dos or the
last answer again (seen on 2026-11-15: every check-in was answered with the study blocker and the date)."""
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import agent, db, learning, tools


class SmallTalk(unittest.TestCase):
    def test_check_ins_and_greetings_are_small_talk(self):
        for t in ("Amadeus, how are you doing today?", "how are you?", "Are you OK?", "Cool, thanks.", "hey Amadeus, wie geht es dir?",
                  "qué tal", "what's up"):
            self.assertTrue(agent.small_talk(t), t)
        for t in ("how are my mails?", "what is up with my calendar tomorrow", "Why did you keep mentioning the date?",
                  "how are you going to add that event?"):
            self.assertFalse(agent.small_talk(t), t)

    def test_no_memories_or_lessons_for_small_talk(self):
        cid = "smalltalk"
        db.q("INSERT OR IGNORE INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        with mock.patch.object(tools, "recall", return_value="- User blocked the calendar for studying") as recall, \
                mock.patch.object(tools, "missing", return_value=""), \
                mock.patch.object(learning, "prompt_block", return_value="- Use todo_add only after confirming") as lessons:
            ctx = agent._context(cid, "Amadeus, how are you doing today?")
            recall.assert_not_called()
            lessons.assert_not_called()
            self.assertIn("small talk", ctx)
            self.assertNotIn("calendar for studying", ctx)
            ctx = agent._context(cid, "what did I block in my calendar this week?")
            self.assertIn("calendar for studying", ctx)
            self.assertIn("never bring it up on your own", ctx)

    def test_the_same_answer_with_a_new_first_line_is_a_repeat(self):
        cid = "smalltalk2"
        db.q("INSERT OR IGNORE INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        same = ('You have an all-day "Holidays - Blocker to study" event covering Saturday through Tuesday (November 14-17). '
                "Is there anything specific you'd like to work on tonight or plan for tomorrow?")
        db.add_message(cid, "user", "how are you doing today?")
        db.add_message(cid, "assistant", "I'm running smoothly. It's 19:17 on Sunday, November 15th. " + same)
        db.add_message(cid, "user", "Cool, thanks.")
        self.assertTrue(agent._same_as_last(cid, "I'm running smoothly and ready to help. " + same))
        self.assertFalse(agent._same_as_last(cid, "Glad to help! Enjoy your evening."))


if __name__ == "__main__":
    unittest.main()
