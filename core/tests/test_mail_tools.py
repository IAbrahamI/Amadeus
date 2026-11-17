"""The mail tools get real mail ids, however the model names the mails (2026-11-17: a second _ids() replaced the first,
so "mark as read" and "move" got ids as text, and "id:123" or an overview number never matched)."""
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import db, tools


class MailIds(unittest.TestCase):
    def test_mark_read_and_move_get_numbers(self):
        db.set_setting("mail_overview_numbers", {"2": 1000000000042})
        calls = []
        with mock.patch.object(tools.mail, "call", side_effect=lambda op, **k: calls.append((op, k)) or
                               ([{"id": "inbox-2", "path": "/Archive"}] if op == "folders" else [])), \
                mock.patch.object(tools, "_folder_id", return_value={"id": "f1", "path": "/Archive"}):
            real, args = tools.resolve("mail_change", {"action": "mark_read", "which": ["id:1000000000007", "2"]})
            tools.BY_NAME[real]["fn"](**args)
            real, args = tools.resolve("mail_change", {"action": "move", "which": "1000000000007", "folder": "Archive"})
            tools.BY_NAME[real]["fn"](**args)
        self.assertEqual(calls[0], ("markRead", {"ids": [1000000000007, 1000000000042], "read": True}))
        self.assertEqual(calls[1], ("move", {"ids": [1000000000007], "folderId": "f1"}))


if __name__ == "__main__":
    unittest.main()
