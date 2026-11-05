import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import db, updates

ROOT = updates.ROOT


class Updates(unittest.TestCase):
    def setUp(self):
        db.set_setting("update_check", True)
        db.set_setting("update_checked", 0)
        db.set_setting("update_latest", {})

    def fake(self, tag="v9.9.9", body="notes"):
        return io.BytesIO(json.dumps({"tag_name": tag, "body": body}).encode())

    def test_newer_compares_numbers(self):
        self.assertTrue(updates.newer("0.10.0", "0.9.0"))
        self.assertFalse(updates.newer("0.9.0", "0.9.0"))
        self.assertFalse(updates.newer("", "0.9.0"))

    def test_finds_a_newer_release_once_a_day(self):
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: self.fake()) as get:
            updates.check(now=1000000)
            updates.check(now=1000100)
        self.assertEqual(get.call_count, 1)
        s = updates.status()
        self.assertTrue(s["available"])
        self.assertEqual(s["latest"], "9.9.9")

    def test_off_means_no_request_at_all(self):
        db.set_setting("update_check", False)
        with mock.patch("urllib.request.urlopen") as get:
            updates.check(now=1000000)
        get.assert_not_called()

    def test_sends_nothing_about_you(self):
        with mock.patch("urllib.request.urlopen", return_value=self.fake()) as get:
            updates.check(now=1000000)
        req = get.call_args[0][0]
        self.assertIsNone(req.data)
        self.assertEqual(req.full_url, updates.LATEST)
        self.assertEqual(set(k.lower() for k in req.headers), {"accept", "user-agent"})

    def test_no_release_yet_and_offline_are_quiet(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 404, "no", None, None)):
            updates.check(now=1000000)
        self.assertFalse(updates.status()["available"])
        db.set_setting("update_checked", 0)
        with mock.patch("urllib.request.urlopen", side_effect=OSError):
            updates.check(now=1000000)
        self.assertFalse(updates.status()["available"])

    def test_one_version_everywhere(self):
        v = open(os.path.join(ROOT, "VERSION")).read().strip()
        self.assertIn(f'version = "{v}"', open(os.path.join(ROOT, "core/desktop-tauri/Cargo.toml")).read())
        self.assertEqual(json.load(open(os.path.join(ROOT, "core/desktop-tauri/tauri.conf.json")))["version"], v)
