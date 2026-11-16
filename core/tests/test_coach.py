"""Coaching (core/coach): the made-up cases are sound, a pack of texts can be applied and is refused when it would break
something, and a new pack is only kept when it is better where it was tuned and no worse on the held-back cases."""
import copy
import unittest

from . import HOME  # noqa: F401
from amadeus_core import agent, grounding, tools
from coach import cases, pack, tune


class Cases(unittest.TestCase):
    def test_the_cases_and_packs_are_sound(self):
        self.assertEqual(tune.check(), [])

    def test_three_languages_and_enough_cases_that_need_no_tool(self):
        self.assertGreaterEqual(len(cases.CASES), 150)
        for lang in ("en", "de", "es"):
            self.assertGreaterEqual(sum(x["lang"] == lang for x in cases.CASES), 25, lang)
        quiet = sum(x["want"] in ("none", "cant") for x in cases.CASES)
        self.assertGreaterEqual(quiet / len(cases.CASES), 0.2)  # tuned only on "call a tool", a model calls tools everywhere

    def test_the_split_stays_the_same(self):
        self.assertEqual({x["id"] for x in cases.split("train")} | {x["id"] for x in cases.split("held")}, {x["id"] for x in cases.CASES})
        self.assertEqual([x["id"] for x in cases.split("held")], [x["id"] for x in cases.split("held")])

    def case(self, case_id):
        return next(x for x in cases.CASES if x["id"] == case_id)

    def check(self, case_id, calls, shown="Here you go."):
        return cases.check(self.case(case_id), calls, shown, tools, grounding)[0]

    def test_right_and_wrong_answers(self):
        self.assertTrue(self.check("todo-add-1", [("approved:todo_add", {"items": ["Renew my passport"]})]))
        self.assertFalse(self.check("todo-add-1", [("approved:notes_add", {"text": "renew my passport"})]))
        self.assertFalse(self.check("todo-add-1", [("approved:todo_add", {"items": ["Buy milk"]})]))  # not what was asked
        self.assertFalse(self.check("todo-add-1", [("approved:todo_add", {"items": ["Renew my passport"], "due": "friday"})]))  # made-up field
        self.assertFalse(self.check("todo-add-1", [], "I've added it to your todo list."))  # said, not done

    def test_no_tool_and_cant(self):
        self.assertTrue(self.check("none-1", [], "Good morning!"))
        self.assertFalse(self.check("none-1", [("calendar_list", {"start_date": "2026-11-16"})], "Good morning!"))
        self.assertTrue(self.check("cant-1", [("approved:suggest_improvement", {"title": "volume", "why": "asked"})], "I can't do that yet."))
        self.assertFalse(self.check("cant-1", [("approved:app_setting_change", {"name": "volume", "value": "80"})], "Waiting for your OK."))

    def test_all_of_several_and_any_mail_tool(self):
        both = [("approved:todo_add", {"items": ["buy milk"]}), ("approved:create_reminder", {"text": "buy milk", "when": "6 pm"})]
        self.assertTrue(self.check("rem-and-todo-1", both))
        self.assertFalse(self.check("rem-and-todo-1", both[:1]))
        self.assertTrue(self.check("mail-look-1", [("mail_look", {"what": "unread"})]))
        self.assertTrue(self.check("mail-look-1", [("mail_unread", {})]))
        self.assertFalse(self.check("todo-about-mail-1", [("mail_look", {"what": "search", "query": "Tom"}),
                                                          ("approved:todo_add", {"items": ["Reply to Tom's email"]})]))


class Packs(unittest.TestCase):
    def setUp(self):
        self.before = copy.deepcopy(pack.current())
        self.addCleanup(pack.apply, self.before)

    def test_the_texts_in_the_code_are_a_valid_pack(self):
        self.assertEqual(pack.problems(pack.current(), pack.current()), [])

    def test_a_pack_changes_only_what_it_names(self):
        pack.apply({"pick_ask": "Which tools does this need?", "tools": {"todo_add": "Add items to the to-do list."},
                    "area_words": {"notes": r"notes?|jot down"}})
        self.assertEqual(agent.PICK_ASK, "Which tools does this need?")
        self.assertEqual(tools.BY_NAME["todo_add"]["schema"]["function"]["description"], "Add items to the to-do list.")
        self.assertTrue(tools.AREA_RE["notes"].search("jot down the code"))
        self.assertEqual(agent.SYSTEM, self.before["system"])
        self.assertEqual(tools.BY_NAME["todo_list"]["schema"]["function"]["description"], self.before["tools"]["todo_list"])

    def test_a_pack_that_would_break_something_is_refused(self):
        base = pack.current()
        for bad in ({"system": "You are an assistant."},                 # the name is filled in by the code
                    {"fill_ask": "Give the arguments."},
                    {"system": base["system"] + " {oops}"},
                    {"tools": {"todo_ad": "Add items to the to-do list."}},
                    {"tools": {"todo_add": ""}},
                    {"area_words": {"notes": "notes?|("}},
                    {"area_words": {"shopping": "buy"}},
                    {"temperature": 0},
                    {"system": base["system"] + "\n- " + "Always think twice. " * 400}):  # far too long
            self.assertTrue(pack.problems(bad, base), bad)
        with self.assertRaises(ValueError):
            pack.apply({"fill_ask": "Give the arguments."})


class Verdict(unittest.TestCase):
    def result(self, train, held, fake=0, chars=9000):
        rows = {f"t{i}": {"right": 2 if i < train else 0, "of": 2, "held": False, "fake": fake if i == 0 else 0} for i in range(10)}
        rows.update({f"h{i}": {"right": 2 if i < held else 0, "of": 2, "held": True, "fake": 0} for i in range(5)})
        return {"cases": rows, "chars_per_call": chars}

    def test_kept_only_when_better_and_no_worse_elsewhere(self):
        a = self.result(6, 3)
        self.assertTrue(tune.verdict(a, self.result(8, 3))[0])
        self.assertFalse(tune.verdict(a, self.result(6, 3))[0])            # the same
        self.assertFalse(tune.verdict(a, self.result(9, 2))[0])            # learned the test: worse on what it never saw
        self.assertFalse(tune.verdict(a, self.result(8, 3, fake=1))[0])    # more made-up "done"
        self.assertFalse(tune.verdict(a, self.result(8, 3, chars=11000))[0])  # every request much bigger
        self.assertTrue(tune.verdict(a, self.result(8, 4, chars=9500))[0])


if __name__ == "__main__":
    unittest.main()
