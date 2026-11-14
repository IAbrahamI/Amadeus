import importlib.util
import os
import unittest
from unittest import mock

from . import HOME  # noqa: F401

spec = importlib.util.spec_from_file_location("pick_model", os.path.join(os.path.dirname(__file__), "..", "deploy", "pick_model.py"))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)


def hw(gpu=0, ram=32, disk=200):
    return {"gpu_gb": gpu, "gpu": "", "ram_gb": ram, "cores": 16, "disk_gb": disk}


class PickModel(unittest.TestCase):
    """Three suggestions that really fit this PC, the recommended one first."""

    def names(self, *a, **k):
        return [m["model"] for m in pm.suggest(*a, **k)]

    def test_12gb_card_gets_the_tuned_model_first(self):
        self.assertEqual(self.names(hw(12)), ["qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b"])

    def test_big_card_gets_a_big_model(self):
        self.assertEqual(self.names(hw(32))[0], "qwen3.5:35b")

    def test_speed_test_can_lower_the_pick(self):
        self.assertEqual(self.names(hw(0, 64), speed=(20, 3.3))[0], "qwen3.5:4b")

    def test_always_three_when_only_the_small_ones_are_comfortable(self):
        self.assertEqual(len(self.names(hw(12), speed=(2, 6.6))), 3)
        self.assertEqual(self.names(hw(12), speed=(2, 6.6))[0], "qwen3.5:0.8b")

    def test_nothing_that_does_not_fit(self):
        self.assertEqual(self.names(hw(0, 3)), [])
        self.assertEqual(self.names(hw(32, disk=3)), [])

    def test_the_name_amadeus_has_used(self):
        self.assertEqual(pm.variant_name("qwen3.5:9b", pm.context_for(hw(12), 6.6)), "qwen3.5-9b-48k")
        self.assertLess(pm.context_for(hw(6), 3.3), 49152)

    def test_reads_the_library_pages(self):
        self.assertEqual(pm.parse_newest('<a href="/library/new-1"><a href="/library/old.2"><a href="/library/new-1">'), ["new-1", "old.2"])
        page = '''<a href="/library/m:latest">x • 6.6GB • y</a><a href="/library/m:27b">17GB</a><a href="/library/m:27b-q8_0">30GB</a>
                  <a href="/library/m:cloud">1GB</a><a href="/library/m:small">800MB</a>'''
        got = dict(pm.parse_tags("m", page))
        self.assertEqual(got["m"], 6.6)
        self.assertEqual(got["m:27b"], 17)
        self.assertNotIn("m:27b-q8_0", got)
        self.assertNotIn("m:cloud", got)
        self.assertLess(got["m:small"], 1)

    def test_proven_first_then_newest_then_lighter(self):
        latest = [{"name": "big", "versions": [("big:70b", 40.0)]}, {"name": "new", "versions": [("new:8b", 6.0), ("new:20b", 13.0)]},
                  {"name": "mini", "versions": [("mini", 2.0)]}]
        names = [m["model"] for m in pm.suggest_latest(hw(12), latest)]
        self.assertEqual(names, ["qwen3.5:9b", "new:8b", "mini"])

    def test_a_model_passes_only_by_doing_amadeus_kind_of_work(self):
        call = lambda name, args: {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}]}  # noqa: E731
        todo, brief, said = call("todo_add", {"items": ["buy milk"]}), call("brief_change", {"which": "morning", "add": ["the weather"]}), {"content": "Saved."}
        bye = {"content": "You're welcome!"}

        def ollama(answers, caps=("completion", "tools")):
            def api(path, body=None, timeout=300):
                if path == "/api/show":
                    return {"capabilities": list(caps)}
                if path == "/api/generate":
                    return {}
                a = answers.pop(0)
                if isinstance(a, Exception):
                    raise a
                return {"message": a}
            return api
        check = lambda api: mock.patch.object(pm, "_api", api)  # noqa: E731
        with check(ollama([todo, said, bye, brief, said])):
            self.assertEqual(pm.tool_check("m")[0], "ok")
        with check(ollama([{"content": "no"}, todo, said, bye, brief, said])):  # one miss isn't a verdict
            self.assertEqual(pm.tool_check("m")[0], "ok")
        with check(ollama([todo, said, bye, call("calendar_add", {"title": "weather", "start": "08:00"}), call("create_reminder", {"text": "weather", "when": "8"})])):
            self.assertEqual(pm.tool_check("m"), ("no", 'it didn\'t pick the right tool for "Please put the weather for my town into the morning brief you write me every day."'))
        with check(ollama([todo, said, call("todo_list", {}), call("todo_list", {})])):
            self.assertEqual(pm.tool_check("m"), ("no", "it used a tool where none was needed"))
        with check(ollama([], caps=("completion",))):
            self.assertEqual(pm.tool_check("m")[0], "no")
        with check(ollama([OSError("gone"), OSError("gone")])):
            self.assertEqual(pm.tool_check("m"), ("unknown", "gone"))  # says nothing about the model

    def test_no_card_and_no_speed_test_stays_small(self):
        latest = [{"name": "big", "versions": [("big:27b", 8.3)]}, {"name": "mini", "versions": [("mini", 1.1)]}]
        names = [m["model"] for m in pm.suggest_latest(hw(0, 16), latest)]
        self.assertEqual(names[0], "qwen3.5:4b")  # proven with Amadeus
        self.assertIn("mini", names)
        self.assertNotIn("big:27b", names)

    def test_offline_uses_the_built_in_list(self):
        self.assertEqual([m["model"] for m in pm.suggest_latest(hw(12), [])], ["qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b"])
