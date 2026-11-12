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

    def test_edit_in_place_keeps_the_id_and_tries_a_new_login_first(self):
        with mock.patch.object(d, "_test"):
            acc = d.add_account("other", "b@example.invalid", "old", {"host": "imap.example.invalid", "port": 993},
                                {"host": "smtp.example.invalid", "port": 587})
        saved = d._account(acc["id"])
        self.assertEqual((saved["imap"][2], saved["smtp"][2]), ("ssl", "starttls"))  # security follows the port
        with mock.patch.object(d, "_test", side_effect=ValueError("no")), self.assertRaises(ValueError):
            d.update_account(acc["id"], password="wrong")
        self.assertEqual(d._account(acc["id"])["password"], "old")  # a failed new login changes nothing
        with mock.patch.object(d, "_test") as t:
            d.update_account(acc["id"], name="Work", imap_server={"host": "imap.example.invalid", "port": 993},
                             smtp_server={"host": "smtp.example.invalid", "port": "587"})  # only the name changed: no login
            t.assert_not_called()
            d.update_account(acc["id"], password="new", smtp_server={"host": "mail.example.invalid", "port": 465})
            t.assert_called_once()
        now = d._account(acc["id"])
        self.assertEqual((now["password"], now["smtp"], now["name"]), ("new", ["mail.example.invalid", 465, "ssl"], "Work"))
        self.assertEqual(d.op_accounts()[0]["name"], "Work")
        self.assertNotIn("new", json.dumps(d.listing()))
        with mock.patch.object(d, "_test"):  # adding the same address again keeps its id and its name
            self.assertEqual(d.add_account("other", "B@example.invalid", "x", {"host": "imap.example.invalid", "port": 993},
                                           {"host": "smtp.example.invalid", "port": 465})["id"], acc["id"])
        self.assertEqual(d._account(acc["id"])["name"], "Work")
        d.update_account(acc["id"], name="")
        self.assertEqual(d.op_accounts()[0]["name"], "B@example.invalid")  # a cleared name shows the address again
        with self.assertRaises(ValueError):
            d.update_account("d:gone", name="x")
        d.remove_account(acc["id"])

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


class MicrosoftApp(unittest.TestCase):
    def test_your_app_id_is_checked_and_kept(self):
        from amadeus_core import maildirect
        from amadeus_core.config import CFG
        with self.assertRaises(ValueError):
            maildirect.set_ms_client_id("not an id")
        maildirect.set_ms_client_id("1A2B3C4D-1234-5678-9ABC-1234567890AB")
        self.assertEqual(CFG["ms_client_id"], "1a2b3c4d-1234-5678-9abc-1234567890ab")
        self.assertEqual(maildirect.ms_client_id(), "1a2b3c4d-1234-5678-9abc-1234567890ab")
        CFG["ms_client_id"] = ""


class NoThunderbirdStart(unittest.TestCase):
    def test_amadeus_never_starts_thunderbird(self):
        from unittest import mock
        from amadeus_core import mailbridge
        with mock.patch.object(mailbridge, "_connect", side_effect=OSError), mock.patch("subprocess.Popen") as started:
            with self.assertRaises(mailbridge.NotRunning):
                mailbridge._thunderbird("folders", 5, True, {})
        started.assert_not_called()
