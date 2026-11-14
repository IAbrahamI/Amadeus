"""The morning brief and evening summary are Amadeus' to change when you ask (with your OK): what goes in, when, on or
off. What you add is looked up each time the brief is written, in the background, where nothing can be changed and
nobody is called."""
import json
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import agent, db, digest, tools


class Briefs(unittest.TestCase):
    def setUp(self):
        db.set_setting("briefs", {})

    def test_change_what_goes_in_and_when(self):
        self.assertTrue(tools.BY_NAME["brief_change"]["approval"])
        summary = tools.BY_NAME["brief_change"]["summary"]({"which": "morning brief", "add": "the weather this evening in Winterthur", "hour": "8"})
        self.assertIn("add: the weather this evening in Winterthur", summary)
        self.assertIn("at 08:00", summary)
        tools.brief_change("morning", add=["the weather this evening in Winterthur"], hour=8)
        b = digest.brief_settings()["morning"]
        self.assertEqual((b["hour"], b["items"]), (8, ["the weather this evening in Winterthur"]))
        tools.brief_change("morning", add=["The weather this evening in Winterthur"])  # once is enough
        self.assertEqual(len(digest.brief_settings()["morning"]["items"]), 1)
        self.assertIn("1. the weather", tools.brief_show())
        tools.brief_change("morning", remove=["1"])
        self.assertEqual(digest.brief_settings()["morning"]["items"], [])
        with self.assertRaises(ValueError):
            tools.brief_change("morning", remove=["something never added"])
        with self.assertRaises(ValueError):
            tools.BY_NAME["brief_change"]["summary"]({"which": "noon"})
        tools.brief_change("evening", on=False)
        self.assertFalse(digest.brief_settings()["evening"]["on"])

    def test_it_comes_when_you_set_it(self):
        tools.brief_change("morning", hour=9)
        db.set_setting("morning_day", "")
        early, on_time = digest.datetime.datetime(2026, 11, 16, 8, 30), digest.datetime.datetime(2026, 11, 16, 9, 1)
        with mock.patch.object(digest, "morning_brief") as made, mock.patch.object(digest.datetime, "datetime") as dt:
            dt.now.return_value = early
            digest.check_morning()
            made.assert_not_called()
            dt.now.return_value = on_time
            digest.check_morning()
            made.assert_called_once()

    def test_additions_are_looked_up_in_the_background_without_changing_anything(self):
        tools.brief_change("morning", add=["the weather this evening in Winterthur"])

        def fake_run(cid, model, text, curate=True, **_):
            self.assertTrue(cid.startswith(agent.BACKGROUND_PREFIX))
            self.assertIn("the weather this evening in Winterthur", text)
            db.add_message(cid, "assistant", "Sunny, 7°C, low of -3°C (BBC Weather).")
        with mock.patch.object(agent, "run", side_effect=fake_run):
            out = digest._additions("morning")
        self.assertEqual(out, [{"asked": "the weather this evening in Winterthur", "found": "Sunny, 7°C, low of -3°C (BBC Weather)."}])
        self.assertEqual(digest._additions("evening"), [])

    def test_app_settings_change_only_known_values(self):
        self.assertTrue(tools.BY_NAME["app_setting_change"]["approval"])
        tools.app_setting_change("theme", "Red")
        self.assertEqual(db.get_setting("theme"), "red")
        for bad in (("theme", "green"), ("model", "x")):
            with self.assertRaises(ValueError):
                tools.app_setting_change(*bad)


class NoFakeDone(unittest.TestCase):
    def test_looking_things_up_earlier_doesnt_excuse_a_made_up_done(self):
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        db.add_message(cid, "tool", "results", {"name": "web_search"})
        db.add_message(cid, "tool", "- an event", {"name": "calendar_list"})
        self.assertFalse(agent._ever_acted(cid))
        db.add_message(cid, "approval", "Add a reminder", {"approval_id": "x", "tool": "create_reminder"})
        self.assertFalse(agent._ever_acted(cid))  # only a card: nothing has happened yet
        db.add_message(cid, "tool", "Reminder set.", {"name": "create_reminder", "approval_id": "x"})
        self.assertTrue(agent._ever_acted(cid))

    def test_only_a_change_in_this_turn_backs_a_done(self):
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        db.add_message(cid, "tool", "Reminder set.", {"name": "create_reminder"})
        db.add_message(cid, "user", "is the weather in my brief now?")
        db.add_message(cid, "tool", "Nothing added yet.", {"name": "brief_show"})
        self.assertFalse(agent._changed_this_turn(cid))  # a lookup in this turn, a change only in an earlier one
        db.add_message(cid, "tool", "Error: no such reminder", {"name": "delete_reminder"})
        self.assertFalse(agent._changed_this_turn(cid))  # a change that failed
        db.add_message(cid, "tool", "The morning brief now: on, at 07:00, with: the weather.", {"name": "brief_change"})
        self.assertTrue(agent._changed_this_turn(cid))


if __name__ == "__main__":
    unittest.main()
