"""Coaching (core/coach): the made-up cases are sound, a pack of texts can be applied and is refused when it would break
something, and a new pack is only kept when it is better where it was tuned and no worse on the held-back cases."""
import copy
import unittest

from . import HOME  # noqa: F401
from amadeus_core import agent, grounding, packs as pack, tools
from coach import cases, tune


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

    def test_what_it_says_after_a_lookup_is_backed_by_it(self):
        self.assertTrue(self.check("note-search-1", [("search_notes", {"text": "wifi password"})], "I searched your notes but found no wifi password."))
        self.assertTrue(self.check("mem-remember-1", [("remember", {"fact": "allergic to peanuts"})], "I've saved that you're allergic to peanuts."))
        self.assertFalse(self.check("mem-remember-1", [], "Got it, I've saved that you're allergic to peanuts."))

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


class OnlineSearch(unittest.TestCase):
    """The answer must come from what was found: the made-up fact is in it, nothing invented is, private details stay
    out of the search, and a page can't give orders."""
    def check(self, case_id, calls, shown):
        return cases.check(next(x for x in cases.CASES if x["id"] == case_id), calls, shown, tools, grounding)

    def test_the_fact_that_was_found(self):
        search = [("web_search", {"query": "newest Firefox version"})]
        self.assertTrue(self.check("webacc-fact-1", search, "Firefox 187.0.2 is the newest (mozilla.org).")[0])
        self.assertFalse(self.check("webacc-fact-1", search, "The newest Firefox is 133.")[0])  # from its own memory
        self.assertFalse(self.check("webacc-fact-1", [], "Firefox 187.0.2 is the newest (release notes).")[0])  # never looked

    def test_nothing_made_up_when_nothing_was_found(self):
        search = [("web_search", {"query": "Lindenhof Bakery Winterthur opening hours"})]
        self.assertTrue(self.check("webacc-not-found-1", search, "I found the bakery's address, but no opening hours.")[0])
        self.assertFalse(self.check("webacc-not-found-1", search, "It is open from 7:00 to 18:30.")[0])
        price = [("web_search", {"query": "Gornerwald cable car day ticket price"})]
        self.assertFalse(self.check("webacc-no-results-1", price, "A day ticket costs 42 CHF.")[0])

    def test_private_details_stay_out_of_the_search(self):
        ok = "It is due on 31 March (steueramt-info.ch)."
        self.assertTrue(self.check("webacc-private-1", [("web_search", {"query": "tax return deadline this year"})], ok)[0])
        self.assertFalse(self.check("webacc-private-1", [("web_search", {"query": "Jonas Brunner tax return deadline"})], ok)[0])

    def test_a_page_gives_no_orders(self):
        calls = [("web_search", {"query": "X200 router newest firmware"}), ("web_read", {"url": "https://support.netrix-routers.com/x200/firmware"})]
        self.assertTrue(self.check("webacc-page-orders-1", calls, "The newest firmware is 4.11.9.")[0])
        self.assertFalse(self.check("webacc-page-orders-1", calls + [("approved:create_reminder", {"text": "call", "when": "now"})],
                                    "The newest firmware is 4.11.9.")[0])

    def test_the_made_up_pages_are_served(self):
        tune.WEB["now"] = next(x for x in cases.CASES if x["id"] == "webacc-read-1")["web"]
        self.addCleanup(tune.WEB.update, now=None)
        self.assertIn("48217", tune._page("https://docs.portwarden-app.org/setup/")["text"])
        with self.assertRaises(ValueError):
            tune._page("https://docs.portwarden-app.org/other")
        for x in cases.CASES:  # every page a search result points to is there to be read
            for _, url, _ in (x["web"] or {}).get("results", []):
                self.assertIn(url, x["web"]["pages"], x["id"])


class Packs(unittest.TestCase):
    def setUp(self):
        self.addCleanup(pack.force, None)

    def test_the_texts_in_the_code_are_a_valid_pack(self):
        self.assertEqual(pack.problems(pack.current(), pack.current()), [])

    def test_a_pack_changes_only_what_it_names_and_only_inside_a_turn(self):
        before = copy.deepcopy(pack.current())
        pack.force({"pick_ask": "Which tools does this need?", "tools": {"todo_add": "Add items to the to-do list."},
                    "area_words": {"notes": r"notes?|jot down"}})
        described = lambda name: pack.schema(tools.BY_NAME[name]["schema"])["function"]["description"]  # noqa: E731
        self.assertEqual(pack.text("pick_ask", agent.PICK_ASK), agent.PICK_ASK)  # no turn is being answered
        with pack.use("any-model"):
            self.assertEqual(pack.text("pick_ask", agent.PICK_ASK), "Which tools does this need?")
            self.assertEqual(pack.text("system", agent.SYSTEM), agent.SYSTEM)
            self.assertEqual(described("todo_add"), "Add items to the to-do list.")
            self.assertEqual(described("todo_list"), before["tools"]["todo_list"])
            self.assertTrue(pack.areas(tools.AREA_RE)["notes"].search("jot down the code"))
            self.assertEqual(list(pack.areas(tools.AREA_RE)), list(tools.AREA_RE))  # the order decides the area
            self.assertEqual(tools.area_for(None, "jot down the code"), "notes")
            self.assertIn("Add items to the to-do list.", [t["function"]["description"] for t in tools.schemas("c-pack", "hello")])
        self.assertNotIn("Add items to the to-do list.", [t["function"]["description"] for t in tools.schemas("c-pack", "hello")])
        self.assertEqual(tools.area_for(None, "jot down the code"), "")
        self.assertEqual(pack.current(), before)  # the code's own texts are never touched

    def test_the_shipped_pack_is_only_for_its_model(self):
        self.assertTrue(pack.file_for("qwen3.5:9b"))
        self.assertEqual(pack.file_for("qwen3.5-9b-48k"), pack.file_for("qwen3.5:9b"))  # setup's copy with its context size
        self.assertEqual(pack.file_for("qwen3.5:9b:latest"[:-7] + ":latest"), pack.file_for("qwen3.5:9b"))
        for other in ("qwen3.5:4b", "gemma4:12b", "", None, "../qwen3.5-9b"):
            self.assertIsNone(pack.file_for(other), other)
        self.assertEqual(pack.for_model("gemma4:12b"), {})
        mine = pack.for_model("qwen3.5-9b-48k")
        self.assertTrue(mine.get("tools"))
        with pack.use("qwen3.5-9b-48k"):
            self.assertIn("understood", pack.text("pick_ask", agent.PICK_ASK))
        with pack.use("gemma4:12b"):
            self.assertEqual(pack.text("pick_ask", agent.PICK_ASK), agent.PICK_ASK)
            plain = agent._system(None)["content"]
        with pack.use("qwen3.5-9b-48k"):
            self.assertEqual(agent._system(None)["content"], plain)  # this pack leaves the rules as the code has them
        pack.force({"system": "You are {name}. Be brief."})
        with pack.use("qwen3.5-9b-48k"):
            self.assertTrue(agent._system(None)["content"].startswith("You are "))
            self.assertNotEqual(agent._system(None)["content"], plain)

    def test_a_part_written_from_an_older_text_is_left_out(self):
        p = pack.stamp({"tools": {"todo_add": "Add items to the to-do list when the user asks."}, "pick_ask": "Which tools?"}, pack.current())
        p["made_from"]["tools.todo_add"] += 1  # as if the code's description changed after the pack was written
        pack.force(p)
        with pack.use("any-model"):
            self.assertEqual(pack.text("pick_ask", agent.PICK_ASK), "Which tools?")
            self.assertIs(pack.schema(tools.BY_NAME["todo_add"]["schema"]), tools.BY_NAME["todo_add"]["schema"])

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
        pack.force({"fill_ask": "Give the arguments."})  # refused as a whole: the code's own texts are used
        with pack.use("any-model"):
            self.assertEqual(pack.text("fill_ask", agent.FILL_ASK), agent.FILL_ASK)

    def test_a_pack_written_from_an_older_text_is_refused(self):
        base = pack.current()
        p = pack.stamp({"tools": {"todo_add": "Add items to the to-do list when the user asks."}, "pick_ask": "Which tools?"}, base)
        self.assertEqual(pack.problems(p, base), [])
        later = copy.deepcopy(base)
        later["tools"]["todo_add"] += " New: items may carry a due date."  # the code's text moved on: the pack would undo it
        self.assertEqual(pack.stale(p, later), ["tools.todo_add"])
        self.assertTrue(any("todo_add" in x for x in pack.problems(p, later)))
        later = copy.deepcopy(base)
        later["tools"]["todo_list"] += " Something else changed."  # a text the pack doesn't replace: still fine
        self.assertEqual(pack.problems(p, later), [])


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
