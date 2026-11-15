"""Finding earlier talk by meaning: messages get their numbers once, looking back compares them, and without the model it
quietly falls back to the word search."""
import math
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import agent, db, meaning

# a stand-in for the model: a few "meanings" as directions, so the test knows which texts belong together
TOPICS = {"flight": ("lisbon", "flying", "flug", "lissabon", "plane", "portugal", "reise"),
          "teeth": ("dentist", "teeth", "zahn"), "cat": ("cat", "katze")}


def fake_embed(texts):
    out = []
    for t in texts:
        low = t.lower().split("query:")[-1]
        v = [sum(1.0 for w in words if w in low) for words in TOPICS.values()] + [0.2]
        out.append(v)
    return out


class Meaning(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(meaning, "installed", return_value=True), mock.patch.object(meaning, "embed", side_effect=fake_embed)]
        for x in self.p:
            x.start()
        db.set_setting("chat_meaning", True)
        self.cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (self.cid, "t", "m", db.now(), db.now()))

    def tearDown(self):
        for x in self.p:
            x.stop()

    def say(self, user, answer):
        db.add_message(self.cid, "user", user)
        db.add_message(self.cid, "assistant", answer)

    def test_found_by_meaning_in_another_language(self):
        self.say("I'm flying to Lisbon on Friday, departure 07:40.", "Got it: Friday 07:40 to Lisbon.")
        self.say("What's a good name for a cat?", "Maybe Luna.")
        db.q("UPDATE messages SET created=created-3*3600 WHERE conversation_id=?", (self.cid,))
        for i in range(5):
            self.say(f"small talk {i}", "ok")
        self.assertGreaterEqual(meaning.index_pending(), 7)
        self.assertEqual(meaning.index_pending(), 0)  # each message once
        db.add_message(self.cid, "user", "Was hatten wir heute Morgen wegen meiner Reise nach Portugal besprochen?")
        found = agent._look_back(self.cid, "Was hatten wir heute Morgen wegen meiner Reise nach Portugal besprochen?")
        self.assertIn("07:40", found)
        self.assertNotIn("Luna", found)

    def test_switched_off_or_without_the_model_it_uses_the_word_search(self):
        meaning.set_enabled(False)
        self.assertFalse(meaning.ready())
        self.assertIsNone(meaning.search("anything", self.cid))
        meaning.set_enabled(True)
        with mock.patch.object(meaning, "embed", side_effect=OSError("down")):
            self.assertIsNone(meaning.search("anything", self.cid))  # can't search now: the word search takes over

    def test_numbers_are_stored_normalized(self):
        v = meaning._unpack(meaning._pack([3.0, 4.0]))
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0, places=5)
