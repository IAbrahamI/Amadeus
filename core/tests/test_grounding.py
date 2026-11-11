import datetime
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import grounding as g

NOW = datetime.datetime(2026, 11, 11, 10, 30)  # a Wednesday


def at(text):
    found = g.times_in(text, NOW)
    return found[0][1].strftime("%Y-%m-%d %H:%M") if found else None


class Times(unittest.TestCase):
    """The time comes from your words, worked out by code."""

    def test_in_a_while(self):
        self.assertEqual(at("remind me in 5 minutes to check the oven"), "2026-11-11 10:35")
        self.assertEqual(at("put a reminder in one minute as a test"), "2026-11-11 10:31")
        self.assertEqual(at("set a reminder in 2 hours: call mom"), "2026-11-11 12:30")
        self.assertEqual(at("erinnere mich in 10 Minuten an die Wäsche"), "2026-11-11 10:40")
        self.assertEqual(at("in half an hour"), "2026-11-11 11:00")
        self.assertEqual(at("recuérdame en 15 minutos"), "2026-11-11 10:45")

    def test_a_day_and_a_time(self):
        self.assertEqual(at("remind me tomorrow at 9 to send the application"), "2026-11-12 09:00")
        self.assertEqual(at("today 18:00"), "2026-11-11 18:00")
        self.assertEqual(at("friday 14:30"), "2026-11-13 14:30")
        self.assertEqual(at("morgen um 8 Uhr"), "2026-11-12 08:00")
        self.assertEqual(at("at 7pm"), "2026-11-11 19:00")
        self.assertEqual(at("at 9"), "2026-11-12 09:00")  # already past today

    def test_a_part_of_the_day(self):
        self.assertEqual(g.times_in("a reminder for today evening to write back", NOW)[0][1:], (datetime.datetime(2026, 11, 11, 19, 0), "part"))
        self.assertEqual(at("tomorrow morning"), "2026-11-12 09:00")
        self.assertEqual(at("heute abend"), "2026-11-11 19:00")

    def test_nothing_to_work_out(self):
        for text in ("add buy milk to my todo", "hey how are you", "what's on my calendar tomorrow?", "I have 5 minutes"):
            self.assertEqual(g.times_in(text, NOW), [], text)

    def test_the_models_arithmetic_is_replaced_by_yours(self):
        self.assertEqual(g.correct_when("2026-11-11 11:31", "put a reminder in one minute as a test", NOW), "2026-11-11 10:31")  # an hour off
        self.assertEqual(g.correct_when("2026-11-11 10:40", "remind me in 5 minutes", NOW), "2026-11-11 10:35")
        self.assertEqual(g.correct_when("2026-11-11 10:35", "remind me in 5 minutes", NOW), "2026-11-11 10:35")
        self.assertEqual(g.correct_when("in 5 minutes", "remind me in 5 minutes", NOW), "2026-11-11 10:35")
        self.assertEqual(g.correct_when("2026-11-12 20:00", "today evening", NOW), "2026-11-11 19:00")  # wrong day
        self.assertEqual(g.correct_when("2026-11-11 18:30", "today evening", NOW), "2026-11-11 18:30")  # its own pick in the evening stays

    def test_what_you_did_not_say_is_left_alone(self):
        self.assertEqual(g.correct_when("daily 07:30", "remind me every day at 7:30", NOW), "daily 07:30")
        self.assertEqual(g.correct_when("2026-12-01 09:00", "remind me on december first at 9", NOW), "2026-12-01 09:00")
        self.assertEqual(g.correct_when("2026-11-12 09:00", "yes please", NOW), "2026-11-12 09:00")
        self.assertEqual(g.correct_when("2026-11-11 07:00", "remind me at 7pm", NOW), "2026-11-11 19:00")  # your time, its day

    def test_reminders_take_everyday_words(self):
        from amadeus_core import tools
        norm, ts = tools.parse_schedule("in 5 minutes")
        self.assertTrue(norm.startswith("once "))
        self.assertAlmostEqual(ts, (datetime.datetime.now() + datetime.timedelta(minutes=5)).timestamp(), delta=61)
        self.assertEqual(tools.parse_schedule("daily 07:00")[0], "daily 07:00")
        with self.assertRaises(ValueError):
            tools.parse_schedule("sometime")


class Backed(unittest.TestCase):
    """Saying it's done counts only if a tool ran."""

    def test_claims(self):
        for text in ("I've added \"Write reply mail\" to your todo.", "Done! Reminder set for 23:53.", "Yes, I added it.", "Your reminder has been set.",
                     "Ich habe den Termin eingetragen.", "Added.", "The item is now saved on your list."):
            self.assertEqual(g.unbacked(text), "claim", text)

    def test_promises_and_made_up_lists(self):
        self.assertEqual(g.unbacked("Got it. Let's set a reminder for tomorrow evening."), "promise")
        self.assertEqual(g.unbacked("I'll add that to your todo right away."), "promise")
        self.assertEqual(g.unbacked("I have no active reminders."), "fact")
        self.assertEqual(g.unbacked("You have no open to-dos."), "fact")

    def test_ordinary_answers_pass(self):
        for text in ("Hey! How can I help you today?", "What day and time would you like the reminder?", "I can set reminders, manage your calendar and read mail.",
                     "I'll add it. What time should the reminder be?", "I haven't added anything yet.", "I can't make phone calls.",
                     "You could say \"I added it\" to mark it."):
            self.assertIsNone(g.unbacked(text), text)


class Turn(unittest.TestCase):
    """The whole turn, with a model that says done without doing it."""

    def run_with(self, replies, text="add buy milk to my todo"):
        from amadeus_core import agent, db
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        seen, asked = [], []

        def model(model, messages, tools=None):
            asked.append(messages)
            content, calls = replies[min(len(asked), len(replies)) - 1]
            for word in content.split(" "):
                yield "token", word + " "
            yield "done", {"content": content, "tool_calls": calls}
        with mock.patch("amadeus_core.agent.llm.chat_stream", model), mock.patch("amadeus_core.agent.events.add"):
            agent.run(cid, "m", text, lambda kind, data: seen.append((kind, data)), curate=False)
        shown = "".join(d for k, d in seen if k == "token")
        return cid, shown, asked, db

    def test_done_without_a_tool_never_reaches_you_and_it_gets_done(self):
        call = [{"name": "todo_add", "arguments": {"items": ["buy milk"]}}]
        cid, shown, asked, db = self.run_with([("I've added buy milk to your todo.", []), ("", call)])
        self.assertNotIn("added", shown)
        self.assertEqual(len(asked), 2)
        self.assertIn("called no tool", asked[1][-1]["content"])
        self.assertEqual([a["tool"] for a in db.q("SELECT tool FROM approvals WHERE conversation_id=?", (cid,))], ["todo_add"])
        self.assertFalse(any("called no tool" in m["content"] for m in db.messages(cid)))  # the note to the model isn't part of the chat

    def test_if_it_still_does_nothing_you_are_told_the_truth(self):
        cid, shown, asked, db = self.run_with([("Done, I've added it.", [])])
        self.assertEqual(len(asked), 2)
        self.assertIn("haven't done that", shown)
        self.assertNotIn("I've added", shown)
        self.assertIn("haven't done that", db.messages(cid)[-1]["content"])

    def test_an_ordinary_answer_is_not_touched(self):
        cid, shown, asked, db = self.run_with([("Hey! How can I help you today?", [])], "hey")
        self.assertEqual(len(asked), 1)
        self.assertEqual(shown.strip(), "Hey! How can I help you today?")

    def test_after_the_tool_ran_done_is_true(self):
        from amadeus_core import agent, db
        cid, shown, asked, _ = self.run_with([("", [{"name": "todo_list", "arguments": {}}]), ("Done, here is your list: nothing open.", [])], "what's on my todo?")
        self.assertEqual(len(asked), 2)
        self.assertIn("here is your list", shown)

    def test_a_reminders_time_is_yours(self):
        call = [{"name": "create_reminder", "arguments": {"text": "test", "when": "2099-01-01 11:00"}}]
        cid, shown, asked, db = self.run_with([("", call)], "put a reminder in one minute as a test")
        import json
        when = json.loads(db.q("SELECT args FROM approvals WHERE conversation_id=?", (cid,))[0]["args"])["when"]
        want = datetime.datetime.now() + datetime.timedelta(minutes=1)
        self.assertLess(abs((datetime.datetime.strptime(when, "%Y-%m-%d %H:%M") - want).total_seconds()), 61)
