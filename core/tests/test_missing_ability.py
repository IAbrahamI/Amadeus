"""When Amadeus can't do something (it says so, or keeps searching with tools that don't fit), it stops and asks once
whether the missing ability should go on its own project, instead of looking around forever or claiming it's done."""
import json
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import agent, db, selfimprove, tools


def chat(*steps):
    cid = db.new_id()
    db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
    for role, content, meta in steps:
        db.add_message(cid, role, content, meta)
    return cid


class MissingAbility(unittest.TestCase):
    def setUp(self):
        db.set_setting(selfimprove.KEY, [])

    def test_the_card_asks_first_and_approving_puts_it_on_the_list(self):
        t = tools.BY_NAME["suggest_improvement"]
        self.assertTrue(t["approval"])
        self.assertIn("I can't do this yet", t["summary"]({"title": "Change the morning brief", "why": "The user asked to add the weather."}))
        self.assertIn("Noted", t["fn"]("Change the morning brief", "The user asked to add the weather."))
        self.assertEqual(selfimprove.ideas()[-1]["title"], "Change the morning brief")

    def test_searching_in_circles_is_noticed(self):
        lookup = ("tool", "- nothing", {"name": "calendar_list"})
        self.assertFalse(agent._going_in_circles(chat(("user", "put the weather in the brief", None), lookup, lookup)))
        self.assertTrue(agent._going_in_circles(chat(("user", "put the weather in the brief", None), lookup, lookup, lookup)))
        web = ("tool", "results", {"name": "web_read"})
        self.assertFalse(agent._going_in_circles(chat(("user", "compare these shops", None), web, web, web)))  # reading several pages is normal

    def test_it_offers_once_and_never_for_what_it_doesnt_do_on_purpose(self):
        cid = chat(("user", "Put the weather into my morning brief", None), ("tool", "- nothing", {"name": "calendar_list"}))
        seen = []
        with mock.patch.object(agent.llm, "complete", return_value=json.dumps({"title": "Change the morning brief", "why": "Asked to add the weather."})), \
                mock.patch.object(agent.events, "add"):
            self.assertTrue(agent._offer_improvement(cid, "m", "Put the weather into my morning brief", lambda k, d: seen.append(k), "it said it can't"))
            self.assertFalse(agent._offer_improvement(cid, "m", "Put the weather into my morning brief", lambda k, d: seen.append(k), "again"))
            self.assertFalse(agent._offer_improvement(chat(("user", "read my WhatsApp", None)), "m", "read my WhatsApp", lambda k, d: seen.append(k), "x"))
        self.assertEqual(seen, ["approval"])
        a = db.q("SELECT tool, status FROM approvals WHERE conversation_id=?", (cid,), one=True)
        self.assertEqual((a["tool"], a["status"]), ("suggest_improvement", "pending"))

    def test_what_counts_as_cant(self):
        for said, cant in (("I need to locate your morning brief event first before I can add it. Could you tell me what it is called?", True),
                           ("I don't have a way to change that.", True), ("Ich kann das leider nicht.", True),
                           ("I couldn't find any mail from Bob.", False), ("Sunny, 7°C.", False)):
            self.assertEqual(bool(agent.CANT_RE.search(said)), cant, said)
        self.assertTrue(agent.BY_DESIGN.search("I can't read WhatsApp messages."))
        self.assertFalse(agent.BY_DESIGN.search("I can't change the display colour."))


if __name__ == "__main__":
    unittest.main()
