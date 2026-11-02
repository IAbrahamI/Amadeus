import os
import unittest

from . import HOME
from amadeus_core import agent


class Skills(unittest.TestCase):
    def test_builtin_skills_load_in_the_open_format(self):
        s = agent.skills()
        self.assertIn("calendar", s)
        self.assertTrue(s["calendar"]["description"])
        self.assertIn("calendar", s["calendar"]["triggers"])
        self.assertEqual(s["mail-watch"]["mode"], "background")
        self.assertFalse(s["calendar"]["body"].startswith("---"))

    def test_a_dropped_in_skill_without_triggers_loads_by_its_name(self):
        d = os.path.join(HOME, ".local", "share", "amadeus", "core", "skills", "arxiv-search")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write("---\nname: arxiv-search\ndescription: Find papers.\n---\nSearch papers carefully.\n")
        s = agent.skills()["arxiv-search"]
        self.assertEqual(s["triggers"], ["arxiv", "search"])
        self.assertEqual(s["body"].strip(), "Search papers carefully.")


if __name__ == "__main__":
    unittest.main()
