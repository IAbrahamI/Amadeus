import json
import time
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import llm


class Reply:
    def __init__(self, data=b"{}"):
        self.data = data

    def read(self, *a):
        return self.data


class FreeGpu(unittest.TestCase):
    """An idle model gives the graphics memory back when the card is nearly full, and only then."""

    def run_job(self, free, used=0.0):
        sent = []

        def urlopen(req, timeout=0):
            if isinstance(req, str):
                return Reply(json.dumps({"models": [{"name": "m:latest"}]}).encode())
            sent.append(json.loads(req.data))
            return Reply()
        with mock.patch.object(llm, "gpu_free", return_value=free), mock.patch.object(llm, "_used", used), \
                mock.patch("urllib.request.urlopen", urlopen), mock.patch("builtins.print"):
            llm.free_gpu()
        return sent

    def test_unloads_when_nearly_full(self):
        self.assertEqual(self.run_job(449), [{"model": "m:latest", "keep_alive": 0}])

    def test_stays_loaded_with_room_to_spare(self):
        self.assertEqual(self.run_job(4000), [])

    def test_stays_loaded_right_after_an_answer(self):
        self.assertEqual(self.run_job(449, used=time.time()), [])

    def test_no_card_info_changes_nothing(self):
        self.assertEqual(self.run_job(None), [])

    def test_reads_the_card(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="8109\n")):
            self.assertEqual(llm.gpu_free(), 8109)
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertIsNone(llm.gpu_free())
