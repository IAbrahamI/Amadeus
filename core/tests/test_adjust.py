import json
import unittest
from unittest import mock

from . import HOME  # noqa: F401  (a throwaway data folder)
from amadeus_core import agent, db, llm


class Adjust(unittest.TestCase):
    """Adjust on an approval: the redraft replaces the proposal in place and still waits for approval."""

    def setUp(self):
        self.cid, self.aid = db.new_id(), db.new_id()
        db.q("INSERT INTO conversations(id,title,model,created,updated) VALUES(?,?,?,?,?)", (self.cid, "t", "m", 1, 1))
        args = {"text": "Call Anna", "when": "2099-11-05 15:00"}
        db.q("INSERT INTO approvals(id,conversation_id,tool,args,summary,status,created) VALUES(?,?,?,?,?,?,?)",
             (self.aid, self.cid, "create_reminder", json.dumps(args), "old", "pending", 1))
        db.add_message(self.cid, "approval", "old", {"approval_id": self.aid, "tool": "create_reminder"})

    def test_redraft_stays_pending_and_keeps_your_note(self):
        new = {"text": "Call Anna", "when": "2099-11-05 16:00", "extra": "dropped"}
        with mock.patch.object(llm, "complete", return_value=json.dumps(new)):
            r = agent.revise(self.aid, "make it 16:00")
        self.assertTrue(r["revised"])
        a = db.q("SELECT * FROM approvals WHERE id=?", (self.aid,), one=True)
        self.assertEqual(a["status"], "pending")
        self.assertEqual(json.loads(a["args"])["when"], "2099-11-05 16:00")
        self.assertNotIn("extra", json.loads(a["args"]))
        self.assertEqual(a["feedback"], "make it 16:00")
        msgs = db.messages(self.cid)
        self.assertEqual([m["content"] for m in msgs if m["role"] == "approval"], [a["summary"]])
        self.assertEqual(msgs[-1]["role"], "adjust")

    def test_a_bad_redraft_changes_nothing(self):
        with mock.patch.object(llm, "complete", return_value="{}"):
            self.assertIn("error", agent.revise(self.aid, "whatever"))
        self.assertEqual(db.q("SELECT summary FROM approvals WHERE id=?", (self.aid,), one=True)["summary"], "old")
        self.assertIn("error", agent.revise(self.aid, "  "))


class MailAccountsOff(unittest.TestCase):
    """An account you switched off is never read: its mail and its folders are left out, reading one of its mails fails."""

    def test_switched_off_account_is_hidden(self):
        from amadeus_core import mail
        off = {"uni"}
        mails = [{"id": 1, "accountId": "me"}, {"id": 2, "accountId": "uni"}]
        self.assertEqual(mail._hide("recent", mails, off), [mails[0]])
        self.assertEqual(mail._hide("accounts", [{"id": "me"}, {"id": "uni"}], off), [{"id": "me"}])
        with self.assertRaises(RuntimeError):
            mail._hide("read", {"id": 2, "accountId": "uni"}, off)


if __name__ == "__main__":
    unittest.main()
