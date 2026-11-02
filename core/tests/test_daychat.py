import datetime
import unittest

from . import HOME  # noqa: F401
from amadeus_core import db, quickchat


class DayChat(unittest.TestCase):
    def test_one_chat_per_day(self):
        a = quickchat.current()
        self.assertEqual(a, quickchat.current())
        self.assertEqual(a, quickchat.new())  # "new chat" is today's chat
        title = db.q("SELECT title FROM conversations WHERE id=?", (a,), one=True)["title"]
        self.assertEqual(title, datetime.date.today().strftime("%a %d %b %Y"))


if __name__ == "__main__":
    unittest.main()
