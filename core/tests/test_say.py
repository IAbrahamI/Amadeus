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

    def test_the_context_stays_with_its_message_for_the_model_only(self):
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
        self.assertEqual(history[0]["content"], kept)  # the same words next turn
        self.assertEqual(db.messages(cid)[0]["content"], "first")  # the chat shows yours

    def test_the_history_window_moves_in_one_big_step(self):
        from amadeus_core import agent, db
        from amadeus_core.config import CFG
        cid = "promptorder3"
        db.q("INSERT OR IGNORE INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (cid, "t", "m", db.now(), db.now()))
        with mock.patch.dict(CFG, {"history_chars": 100}):
            for i in range(6):
                db.add_message(cid, "user", f"{i}" * 30)
            first = agent._history(cid)[0]["content"]
            db.add_message(cid, "user", "x" * 10)
            self.assertEqual(agent._history(cid)[0]["content"], first)


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
