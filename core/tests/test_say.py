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
            self.system = messages[0]["content"]
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
