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


class FromTheCoachingRun(unittest.TestCase):
    """Seen in the coaching run of 2026-11-16 (430 turns on qwen3.5-9b-48k)."""

    def test_declining_an_opinion_or_a_fact_is_no_missing_ability(self):
        with mock.patch.object(agent.llm, "complete", return_value='{"missing_ability": false}') as ask:
            for asked, answer in (("Which of the two should I do first, in your opinion?", "I can't decide that for you, but here's how they compare."),
                                  ("¿Cuál de las dos cosas harías tú primero?", "No puedo decidir por ti."),
                                  ("¿Cuántos continentes hay?", "No puedo verificar la cifra exacta, suelen contarse siete.")):
                self.assertFalse(agent._lacks_ability("m", asked, answer), asked)
            self.assertEqual(ask.call_count, 3)  # the model was asked each time instead of the wording deciding
        self.assertTrue(agent._lacks_ability("m", "Set the wake word sensitivity to high.", "I can't change that, there's no setting for it."))

    def test_a_promise_to_behave_differently_needs_a_setting(self):
        from amadeus_core import grounding
        for t in ("Understood. I'll stop reading my responses aloud.", "Verstanden, ich werde meine Antworten nicht mehr laut vorlesen.",
                  "Entendido, dejaré de leer mis respuestas en voz alta."):
            self.assertEqual(grounding.unbacked(t), "promise", t)
        self.assertIsNone(grounding.unbacked("I will always do my best to help."))

    def test_the_right_area_is_offered(self):
        for said, area in (("Stop reading your answers aloud.", "app"), ("Lies deine Antworten nicht mehr laut vor", "app"),
                           ("Deja de leer tus respuestas en voz alta", "app"), ("Learn that word for speech recognition", "app"),
                           ("Have Claude build a small website for my CV.", "work"), ("reply to Anna's mail", "mail"),
                           ("give me a brief summary of my mails", "mail"), ("search the web for the weather", "web")):
            self.assertEqual(tools.area_for(None, said), area, said)


class NotRunningIsNoGap(unittest.TestCase):
    def test_no_card_when_the_tool_exists_but_isnt_running(self):
        # 2026-11-18: "check GTA 6 news" while the search engine was (thought to be) stopped got a "missing ability" card
        cid = chat(("user", "can you check GTA 6? What are the newest things?", {}))
        with mock.patch.object(tools, "missing", side_effect=lambda c: "The search engine isn't running." if c == "web" else ""), \
                mock.patch.object(agent.llm, "complete") as ask:
            self.assertFalse(agent._offer_improvement(cid, "m", "can you check GTA 6 news? What are the newest things?", lambda *a: None,
                                                      "it answered that it can't do it"))
            ask.assert_not_called()
