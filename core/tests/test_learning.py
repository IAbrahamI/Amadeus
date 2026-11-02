import unittest

from . import HOME  # noqa: F401
from amadeus_core import db, learning


class Learning(unittest.TestCase):
    def setUp(self):
        learning._save([{"id": "a", "text": "For one day of a weekly event use calendar_delete with date.",
                         "when": "delete weekly day", "helpful": 0, "harmful": 0}])

    def test_relevant_lessons_go_into_the_prompt(self):
        block = learning.prompt_block("c1", "please delete the weekly gym on monday")
        self.assertIn("calendar_delete", block)
        self.assertEqual(learning.LAST_USED["c1"], ["a"])

    def test_feedback_credits_and_drops_harmful_lessons(self):
        cid = "conv-test"
        db.q("INSERT OR IGNORE INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)",
             (cid, "t", "m", db.now(), db.now()))
        db.add_message(cid, "assistant", "answer", {"lessons": ["a"]})
        mid = db.q("SELECT max(id) m FROM messages", one=True)["m"]
        learning.feedback(mid, 1)
        self.assertEqual(learning.lessons()[0]["helpful"], 1)
        for _ in range(4):
            learning._credit(["a"], False)
        self.assertEqual(learning.lessons(), [])  # more harm than good: dropped

    def test_basic_test_cases_are_always_there(self):
        self.assertTrue(all(len(c) == 2 for c in learning.BASICS))
        self.assertGreaterEqual(len(learning.test_cases()), len(learning.BASICS))


if __name__ == "__main__":
    unittest.main()
