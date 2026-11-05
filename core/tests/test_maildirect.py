import json
import os
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import db, mailbridge, maildirect as d


class Routing(unittest.TestCase):
    """Each account is connected one way; a request goes to the way that has it."""

    def test_by_message_folder_and_account(self):
        ours = d.ID_BASE + 5
        self.assertEqual(mailbridge._route({"id": ours}), "direct")
        self.assertEqual(mailbridge._route({"id": 12}), "thunderbird")
        self.assertEqual(mailbridge._route({"ids": [ours, ours + 1]}), "direct")
        self.assertEqual(mailbridge._route({"folderId": "d:abc|INBOX"}), "direct")
        self.assertEqual(mailbridge._route({"accountId": "account3"}), "thunderbird")
        self.assertEqual(mailbridge._route({"replyTo": ours}), "direct")
        self.assertIsNone(mailbridge._route({"days": 2}))
        with self.assertRaises(RuntimeError):
            mailbridge._route({"ids": [ours, 12]})

    def test_thunderbird_closed_does_not_hide_direct_accounts(self):
        with mock.patch.object(mailbridge, "thunderbird_set_up", return_value=True), mock.patch.object(d, "has_accounts", return_value=True), \
                mock.patch.object(d, "call", return_value=[{"id": 1}]), mock.patch.object(mailbridge, "_thunderbird", side_effect=mailbridge.NotRunning("closed")), \
                mock.patch("builtins.print"):
            self.assertEqual(mailbridge.call("recent", days=2), [{"id": 1}])

    def test_without_direct_accounts_it_stays_thunderbird(self):
        with mock.patch.object(mailbridge, "thunderbird_set_up", return_value=True), mock.patch.object(d, "has_accounts", return_value=False), \
                mock.patch.object(mailbridge, "_thunderbird", return_value=[{"id": 2}]) as tb:
            self.assertEqual(mailbridge.call("recent", days=2), [{"id": 2}])
        tb.assert_called_once()


class Direct(unittest.TestCase):
    def test_ids_are_stable_and_ours(self):
        a = d._id("d:x", "INBOX", 7)
        self.assertGreaterEqual(a, d.ID_BASE)
        self.assertEqual(a, d._id("d:x", "INBOX", 7))
        self.assertNotEqual(a, d._id("d:x", "INBOX", 8))
        self.assertEqual(d._where(a), ("d:x", "INBOX", 7))

    def test_login_is_tried_before_saving_and_never_listed(self):
        with mock.patch.object(d, "_test", side_effect=ValueError("no")), self.assertRaises(ValueError):
            d.add_account("gmail", "a@example.invalid", "pw")
        self.assertFalse(d.has_accounts())
        with mock.patch.object(d, "_test"):
            acc = d.add_account("gmail", "a@example.invalid", "pw")
        self.assertNotIn("pw", json.dumps(d.listing()))
        self.assertEqual(oct(os.stat(d.ACCOUNTS_FILE).st_mode)[-3:], "600")
        d.remove_account(acc["id"])
        self.assertFalse(d.has_accounts())

    def test_errors_hide_the_login(self):
        self.assertNotIn("hunter2", d._clean(Exception("bad login hunter2"), {"password": "hunter2"}))

    def test_html_mail_keeps_links(self):
        text = d._html_text('<p>Hi</p><a href="https://example.invalid/ok">Confirm</a><script>x()</script>')
        self.assertIn("Confirm (https://example.invalid/ok)", text)
        self.assertNotIn("x()", text)

    def test_folder_names(self):
        self.assertEqual(d._name("Entw&APw-rfe"), "Entwürfe")

    def test_microsoft_sign_in_needs_the_state_it_started(self):
        with self.assertRaises(ValueError):
            d.ms_finish("made-up", "code")

    def test_nothing_about_providers_is_secret_to_show(self):
        self.assertNotIn("password", {k for p in d.PROVIDERS.values() for k in p})
        db.q("SELECT 1")
