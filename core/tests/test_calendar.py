import datetime
import unittest

from . import HOME  # noqa: F401
from amadeus_core import agenda, tools


class Calendar(unittest.TestCase):
    def setUp(self):
        for e in agenda.occurrences(datetime.date(2030, 1, 1), datetime.date(2031, 1, 1)):
            agenda.delete(e["id"]) if agenda.get(e["id"]) else None

    def test_weekly_series_is_never_deleted_by_accident(self):
        w = agenda.add({"title": "Work", "start": "2030-03-04 07:00", "end": "2030-03-04 16:00", "repeat": "weekly",
                        "repeat_until": "2030-12-31"})
        with self.assertRaises(ValueError):  # no date and no whole_series: refused
            tools._delete_summary({"event_id": w["id"]})
        tools.calendar_delete(w["id"], date="2030-03-11")
        days = [o["occ_start"][:10] for o in agenda.occurrences(datetime.date(2030, 3, 1), datetime.date(2030, 3, 31))]
        self.assertIn("2030-03-04", days)
        self.assertNotIn("2030-03-11", days)
        self.assertIn("2030-03-18", days)

    def test_no_double_entries(self):
        tools.calendar_add("Dentist", "2030-05-02 10:00", "2030-05-02 11:00")
        self.assertIn("Already in the calendar", tools.calendar_add("Dentist", "2030-05-02 10:00", "2030-05-02 11:00"))

    def test_block_days_clears_everything_else(self):
        agenda.add({"title": "Gym", "start": "2030-06-03 18:00", "end": "2030-06-03 19:00", "repeat": "weekly",
                    "repeat_until": "2030-12-31"})
        agenda.add({"title": "Call", "start": "2030-06-04 10:00", "end": "2030-06-04 10:30"})
        tools.calendar_block_days("Holiday", "2030-06-03", "2030-06-05")
        left = agenda.occurrences(datetime.date(2030, 6, 3), datetime.date(2030, 6, 6))
        self.assertEqual([o["title"] for o in left], ["Holiday"])
        later = agenda.occurrences(datetime.date(2030, 6, 10), datetime.date(2030, 6, 11))
        self.assertEqual([o["title"] for o in later], ["Gym"])  # the series goes on after the blocked days


if __name__ == "__main__":
    unittest.main()
