import json
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import agent, db
from amadeus_core.speech import SAY_RE, SayFilter


def stream(tokens):
    f, said, text = SayFilter(), [], ""
    for t in tokens:
        s, out = f.feed(t)
        if s:
            said.append(s)
        text += out
    s, out = f.flush()
    if s:
        said.append(s)
    return said, text + out


class Say(unittest.TestCase):
    """When an answer is read aloud, the model's own spoken line goes to the voice and the full answer to the screen."""

    def test_line_split_over_tokens(self):
        self.assertEqual(stream(["<sa", "y>Three things", " tomorrow.</s", "ay>\n\n- Work", "\n- Dentist"]), (["Three things tomorrow."], "- Work\n- Dentist"))

    def test_no_line_passes_through(self):
        self.assertEqual(stream(["Hello", " there"]), ([], "Hello there"))
        self.assertEqual(stream(["<b>bold</b>"]), ([], "<b>bold</b>"))

    def test_after_the_mood_tag(self):
        self.assertEqual(stream(["[mood:", "happy] <say>Hi.</say> Hello"])[0], ["Hi."])

    def test_never_closed(self):
        self.assertEqual(stream(["<say>Only this"]), (["Only this"], ""))

    def test_stored_answer_has_no_line(self):
        self.assertEqual(SAY_RE.sub("", "<say>Short.</say>\nFull answer", count=1).strip(), "Full answer")

    def run_agent(self, reply, speak=True):
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        seen = []

        def fake(model, messages, tools=None):
            self.system = "\n".join(m["content"] for m in messages)
            for t in reply:
                yield "token", t
            yield "done", {"content": "".join(reply), "tool_calls": []}
        with mock.patch("amadeus_core.llm.chat_stream", fake):
            agent._run(cid, "m", "plan for tomorrow", lambda k, d: seen.append((k, d)), 1, False, False, speak)
        return seen, db.messages(cid)[-1]["content"]

    def test_the_voice_gets_the_line_and_the_chat_the_answer(self):
        seen, stored = self.run_agent(["<say>Three things.</say>", "\n- Work\n- Dentist\n- Gym"])
        self.assertIn(("say", "Three things."), seen)
        self.assertNotIn("<say>", "".join(d for k, d in seen if k == "token"))
        self.assertEqual(stored, "- Work\n- Dentist\n- Gym")
        self.assertIn("## Your answer will be read aloud", self.system)

    def test_only_a_line_is_the_answer_too(self):
        seen, stored = self.run_agent(["<say>Paris.</say>"])
        self.assertEqual(stored, "Paris.")
        self.assertIn(("token", "Paris."), seen)

    def test_not_asked_when_nothing_is_read_aloud(self):
        self.run_agent(["Hello"], speak=False)
        self.assertNotIn("## Your answer will be read aloud", self.system)


class PromptOrder(unittest.TestCase):
    """What changes goes with the newest message, so the model can reuse the start of the prompt."""

    def test_the_start_of_the_prompt_stays_the_same(self):
        from amadeus_core import agent, db
        cid = "promptorder"
        db.q("INSERT OR IGNORE INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        with mock.patch("amadeus_core.agent.datetime") as clock:
            clock.date.today.return_value = __import__("datetime").date(2030, 1, 1)
            clock.timedelta = __import__("datetime").timedelta
            clock.datetime.now.return_value = __import__("datetime").datetime(2030, 1, 1, 10, 0)
            first, ctx1 = agent._system(cid), agent._context(cid, "hey")
            clock.datetime.now.return_value = __import__("datetime").datetime(2030, 1, 1, 10, 7)
            second, ctx2 = agent._system(cid), agent._context(cid, "hey")
        self.assertEqual(first, second)
        self.assertIn("Today is", first["content"])
        self.assertNotIn("10:0", first["content"])
        self.assertNotEqual(ctx1, ctx2)

    def test_the_context_goes_with_the_newest_message_only(self):
        from amadeus_core import agent, db
        cid = "promptorder2"
        db.q("INSERT OR IGNORE INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        db.add_message(cid, "user", "first")
        agent._keep_context(cid, "first")
        kept = agent._history(cid)[0]["content"]
        self.assertIn("<context>", kept)
        self.assertTrue(kept.endswith("first"))
        db.add_message(cid, "assistant", "ok")
        db.add_message(cid, "user", "second")
        agent._keep_context(cid, "second")
        history = agent._history(cid)
        self.assertEqual(history[0]["content"], "first")  # an earlier message: its words only
        self.assertIn("<context>", history[-1]["content"])
        self.assertEqual(db.messages(cid)[0]["content"], "first")  # the chat shows yours


class ShortMemory(unittest.TestCase):
    """The model reads the last few exchanges, not the whole day."""

    def chat(self, *steps, gap=0):
        from amadeus_core import db
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        for role, content, meta in steps:
            db.add_message(cid, role, content, meta)
        return cid

    def test_only_the_last_few_turns(self):
        from amadeus_core import agent
        steps = []
        for i in range(10):
            steps += [("user", f"question {i}", None), ("assistant", f"answer {i}", None)]
        h = agent._history(self.chat(*steps, ("user", "question 10", None)))
        self.assertEqual(h[0]["content"], f"question {11 - agent.RECENT_TURNS}")
        self.assertEqual(h[-1]["content"], "question 10")

    def test_old_tool_results_shrink_to_a_line_and_corrected_answers_go(self):
        from amadeus_core import agent
        cid = self.chat(("user", "what's on my calendar?", None), ("assistant", "", {"tool_calls": [{"name": "calendar_list", "arguments": {}}]}),
                        ("tool", "- Dentist 10:00\n" + "x" * 3000, {"name": "calendar_list"}), ("assistant", "You have the dentist at 10.", None),
                        ("user", "add the weather to my brief", None), ("assistant", "I've added a reminder at 08:00.", None),
                        ("user", "no, I meant the morning brief", None))
        h = agent._history(cid)
        self.assertFalse(any(m["role"] == "tool" or m.get("tool_calls") for m in h))  # an earlier turn: no tool steps
        self.assertIn("calendar_list: - Dentist 10:00", h[1]["content"])
        self.assertLess(len(h[1]["content"]), 300)
        self.assertNotIn("reminder at 08:00", json.dumps(h))  # the answer you corrected is gone
        self.assertEqual(h[-1]["content"].split("\n")[-1], "no, I meant the morning brief")

    def test_a_quiet_spell_starts_fresh(self):
        from amadeus_core import agent, db
        cid = self.chat(("user", "morning!", None), ("assistant", "Morning!", None))
        db.q("UPDATE messages SET created=created-3600 WHERE conversation_id=?", (cid,))
        db.add_message(cid, "user", "what's new?")
        self.assertEqual([m["content"] for m in agent._history(cid)], ["what's new?"])

    def test_the_current_turn_is_complete(self):
        from amadeus_core import agent
        cid = self.chat(("user", "what's on my todo?", None), ("assistant", "", {"tool_calls": [{"name": "todo_list", "arguments": {}}]}),
                        ("tool", "- milk", {"name": "todo_list"}))
        h = agent._history(cid)
        self.assertEqual([m["role"] for m in h], ["user", "assistant", "tool"])


class Overview(unittest.TestCase):
    """A long answer without its own spoken line is summed up when spoken, never cut after its first lines."""

    def test_overview_is_cleaned(self):
        from unittest import mock
        from amadeus_core import agent
        with mock.patch.object(agent.llm, "complete", return_value='<say>"I set up the backup and the report."</say> [mood: happy]'):
            self.assertEqual(agent._overview("m", [], "long answer"), "I set up the backup and the report.")
        with mock.patch.object(agent.llm, "complete", side_effect=OSError("down")):
            self.assertEqual(agent._overview("m", [], "long answer"), "")

    def test_plain_counts_only_words(self):
        from amadeus_core import speech
        self.assertEqual(speech.plain("**Hi** [docs](https://x.y)\n```py\nprint(1)\n```"), "Hi docs")


class LookBack(unittest.TestCase):
    """When you refer to earlier talk, it's found (also in other words) and handed over with its time."""

    def test_earlier_talk_comes_back_with_its_time(self):
        from unittest import mock
        from amadeus_core import agent, db
        cid = db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        db.add_message(cid, "user", "Ich fliege am Freitag nach Lissabon, Abflug 07:40.")
        db.add_message(cid, "assistant", "Notiert: Freitag 07:40 nach Lissabon.")
        db.q("UPDATE messages SET created=created-5*3600 WHERE conversation_id=?", (cid,))
        for i in range(5):
            db.add_message(cid, "user", f"small talk {i}")
            db.add_message(cid, "assistant", "ok")
        db.add_message(cid, "user", "what did we say this morning about my flight to Lisbon?")
        with mock.patch.object(agent.llm, "complete", return_value='{"english": ["flight", "Lisbon"], "german": ["Flug", "fliege", "Lissabon"], "spanish": ["vuelo"]}'):
            found = agent._look_back(cid, "what did we say this morning about my flight to Lisbon?")
        self.assertIn("07:40", found)
        self.assertIn("may have changed since", found)
        self.assertEqual(agent._look_back(cid, "add milk to my todo"), "")  # nothing points back: nothing is searched
        with mock.patch.object(agent.llm, "complete", return_value='{"english": ["zebra"]}'):
            self.assertIn("Nothing earlier", agent._look_back(cid, "what did we say earlier about zebras?"))
