import importlib.util
import os
import unittest

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
