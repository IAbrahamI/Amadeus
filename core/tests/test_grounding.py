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

    def test_reports_about_information_are_not_claims(self):
        # read back from a web page: when the information changed, not something Amadeus did
        for text in ("Sunny, 7°C. The forecast was updated at 11:25 today (BBC Weather).", "The record was set in 2019.",
                     "The page is updated daily."):
            self.assertIsNone(g.unbacked(text), text)

    def test_promises_and_made_up_lists(self):
        self.assertEqual(g.unbacked("Got it. Let's set a reminder for tomorrow evening."), "promise")
        self.assertEqual(g.unbacked("I'll add that to your todo right away."), "promise")
        self.assertEqual(g.unbacked("I have no active reminders."), "fact")
        self.assertEqual(g.unbacked("I'm blocking your calendar from Saturday to Tuesday with an all-day entry."), "promise")
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

    def test_an_invented_argument_is_left_out_before_you_approve(self):
        import json
        call = [{"name": "calendar_block_days", "arguments": {"title": "Holidays", "start_date": "2099-11-14", "end_date": "2099-11-17", "all_day": "True"}}]
        cid, shown, asked, db = self.run_with([("", call)], "block saturday to tuesday as holidays")
        args = json.loads(db.q("SELECT args FROM approvals WHERE conversation_id=?", (cid,))[0]["args"])
        self.assertNotIn("all_day", args)
        self.assertEqual(args["title"], "Holidays")

    def test_done_after_a_failed_action_is_not_passed_on(self):
        from amadeus_core import agent, db
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        db.add_message(cid, "user", "block the weekend")
        db.add_message(cid, "assistant", "", {"tool_calls": [{"name": "calendar_block_days", "arguments": {}}]})
        db.add_message(cid, "tool", "Error: something broke", {"name": "calendar_block_days"})
        seen = []

        def model(model, messages, tools=None):
            yield "token", "Done - your calendar is now blocked."
            yield "done", {"content": "Done - your calendar is now blocked.", "tool_calls": []}
        with mock.patch("amadeus_core.agent.llm.chat_stream", model):
            agent.run(cid, "m", None, lambda kind, data: seen.append((kind, data)), curate=False)
        said = db.messages(cid)[-1]["content"]
        self.assertIn("didn't work", said)
        self.assertIn("something broke", said)
        self.assertNotIn("now blocked", said)
        self.assertNotIn("now blocked", "".join(str(d) for k, d in seen if k == "token"))

    def test_a_reminders_time_is_yours(self):
        call = [{"name": "create_reminder", "arguments": {"text": "test", "when": "2099-01-01 11:00"}}]
        cid, shown, asked, db = self.run_with([("", call)], "put a reminder in one minute as a test")
        import json
        when = json.loads(db.q("SELECT args FROM approvals WHERE conversation_id=?", (cid,))[0]["args"])["when"]
        want = datetime.datetime.now() + datetime.timedelta(minutes=1)
        self.assertLess(abs((datetime.datetime.strptime(when, "%Y-%m-%d %H:%M") - want).total_seconds()), 61)


class Lean(unittest.TestCase):
    """Only what a message needs is sent to the model and looked up."""

    def chat(self):
        from amadeus_core import db
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        return cid

    def test_a_small_base_set_plus_one_area(self):
        from amadeus_core import db, tools
        cid = self.chat()
        names = lambda said="": {t["function"]["name"] for t in tools.schemas(cid, said)}  # noqa: E731
        with mock.patch.object(tools, "missing", return_value=""):
            everything = {t["function"]["name"] for t in tools.schemas()}
            db.add_message(cid, "user", "add milk to my todo")
            base = names("add milk to my todo")
            self.assertEqual(base, set(tools.BASE))
            self.assertLess(len(base), 15)
            self.assertNotIn("more_tools", everything)  # background jobs and tests see every tool, never the area picker
            for said, area in (("move those mails to the invoices folder", "mail"), ("put the weather into my morning brief", "app"),
                               ("verschieb den Termin auf Freitag", "calendar"), ("busca el tiempo en Madrid", "web"),
                               ("what do you know about me?", "memory")):
                db.add_message(cid, "user", said)
                self.assertEqual(names(said), set(tools.BASE) | set(tools.AREAS[area]), said)
            db.add_message(cid, "user", "yes, do it")
            self.assertEqual(names("yes, do it"), set(tools.BASE) | set(tools.AREAS["memory"]))  # a short follow-up keeps the area
            db.add_message(cid, "user", "how many days until christmas from today do you think?")
            self.assertEqual(names("how many days until christmas from today do you think?"), set(tools.BASE))

    def test_asking_for_an_area_brings_it_for_the_rest_of_the_turn(self):
        from amadeus_core import db, tools
        cid = self.chat()
        db.add_message(cid, "user", "is anything new for me?")
        with mock.patch.object(tools, "missing", return_value=""), mock.patch.object(tools, "CURRENT_CID", cid):
            self.assertNotIn("mail_unread", {t["function"]["name"] for t in tools.schemas(cid, "is anything new for me?")})
            self.assertIn("ready", tools.more_tools("mail"))
            self.assertIn("mail_unread", {t["function"]["name"] for t in tools.schemas(cid, "is anything new for me?")})
            with self.assertRaises(ValueError):
                tools.more_tools("games")

    def test_no_memory_lookup_for_small_talk_and_plain_commands(self):
        from amadeus_core import agent
        for text in ("hey", "thanks a lot!", "ok", "add buy milk to my todo", "remind me in 5 minutes to stretch"):
            self.assertFalse(agent._worth_recalling(text), text)
        for text in ("what did I tell you about my sister?", "when is my next exam again?"):
            self.assertTrue(agent._worth_recalling(text), text)

    def test_learning_waits_until_you_are_quiet(self):
        from amadeus_core import agent
        done = []
        with mock.patch.object(agent, "QUIET", 0.2), mock.patch.object(agent, "warm_up"), mock.patch.object(agent.llm, "loaded", return_value=[]):
            agent._active = __import__("time").time()
            agent.RUNNING.add("x")
            agent.later(done.append, 1)
            agent.later(done.append, 1)  # the same job twice is one job
            __import__("time").sleep(1.3)
            self.assertEqual(done, [])  # you're in the middle of something
            agent.RUNNING.discard("x")
            __import__("time").sleep(1.6)
        self.assertEqual(done, [1])

    def test_no_thread_count_unless_you_set_one(self):
        from amadeus_core import llm
        from amadeus_core.config import CFG
        self.assertEqual(llm.THREAD_OPTION, {"num_thread": llm.THREADS} if CFG.get("llm_threads") else {})


class OneCall(unittest.TestCase):
    """The same thing isn't announced twice."""

    def test_a_reminder_for_what_is_already_announced_joins_it(self):
        from amadeus_core import events
        with mock.patch.object(events, "maybe_ring"):
            brief = events.add("job", "Your morning brief is ready.", ref="day")
            self.assertEqual(events.add("reminder", "Read my morning brief"), brief)
            other = events.add("reminder", "Call the dentist")
            self.assertNotEqual(other, brief)
            work = events.add("calendar", "Team meeting at 10:00")
            self.assertEqual(events.add("reminder", "Team meeting"), work)

    def test_reminders_you_add_and_remove_yourself(self):
        from amadeus_core import db, tools
        r = tools.create_reminder("Water the plants", "in 10 minutes")
        rid = r.split("[id ")[1].rstrip("]")
        self.assertTrue(db.q("SELECT active FROM reminders WHERE id=?", (rid,), one=True)["active"])
        tools.delete_reminder(rid)
        self.assertFalse(db.q("SELECT active FROM reminders WHERE id=?", (rid,), one=True)["active"])


class PickFromAList(unittest.TestCase):
    """The tool is picked from a closed list first, then its arguments against that tool's schema only."""

    def test_pick_then_fill(self):
        from amadeus_core import agent
        offered = [{"type": "function", "function": {"name": "todo_add", "parameters": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}}},
                   {"type": "function", "function": {"name": "todo_list", "parameters": {"type": "object", "properties": {}}}}]
        asked = []

        def fake(model, messages, schema, tools=None):
            asked.append(schema)
            return {"tool": "todo_add"} if "tool" in schema["properties"] else {"items": ["milk"]}
        with mock.patch.object(agent.llm, "structured", side_effect=fake):
            self.assertEqual(agent._pick_tool("m", [], offered), {"name": "todo_add", "arguments": {"items": ["milk"]}})
        self.assertEqual(asked[0]["properties"]["tool"]["enum"], ["todo_add", "todo_list", "none"])  # only these, or none
        self.assertEqual(asked[1]["required"], ["items"])  # that tool's own fields
        with mock.patch.object(agent.llm, "structured", return_value={"tool": "none"}):
            self.assertIsNone(agent._pick_tool("m", [], offered))  # none: it answers the normal way
        with mock.patch.object(agent.llm, "structured", side_effect=OSError("down")), mock.patch("builtins.print"):
            self.assertIsNone(agent._pick_tool("m", [], offered))
        with mock.patch.object(agent.llm, "structured", return_value={"tool": "todo_list"}) as s:
            self.assertEqual(agent._pick_tool("m", [], offered), {"name": "todo_list", "arguments": {}})
            self.assertEqual(s.call_count, 1)  # no fields to fill: no second step
