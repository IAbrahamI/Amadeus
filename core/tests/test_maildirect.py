import json
import os
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import db, mail, maildirect as d


class OneDoor(unittest.TestCase):
    """mail.py: every request goes to the directly connected accounts; switched-off ones stay hidden."""

    def test_without_an_account_nothing_is_tried(self):
        with mock.patch.object(d, "has_accounts", return_value=False), mock.patch.object(d, "call") as c:
            with self.assertRaises(mail.NotRunning):
                mail.call("recent", days=2)
            self.assertEqual(mail.status(), {"connected": False, "accounts": [], "off": []})
        c.assert_not_called()

    def test_switched_off_accounts_stay_hidden(self):
        rows = [{"id": 1, "accountId": "d:a"}, {"id": 2, "accountId": "d:b"}]
        with mock.patch.object(d, "has_accounts", return_value=True), mock.patch.object(d, "call", return_value=rows), \
                mock.patch.object(mail, "accounts_off", return_value={"d:b"}):
            self.assertEqual(mail.call("recent", days=2), [rows[0]])
            self.assertEqual(mail.call("recent", days=2, all_accounts=True), rows)


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


class NewMailAsItArrives(unittest.TestCase):
    """IMAP IDLE against a small stand-in server: told about new mail, renewed in time, no IDLE handled."""

    def server(self, idle=True, push=True):
        import socket
        import threading
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        self.addCleanup(srv.close)

        def run():
            c, _ = srv.accept()
            f = c.makefile("rwb")
            caps = b"IMAP4rev1 IDLE" if idle else b"IMAP4rev1"
            f.write(b"* OK [CAPABILITY " + caps + b"] ready\r\n"); f.flush()
            for line in f:
                tag, _, rest = line.decode().strip().partition(" ")
                cmd = rest.split(" ")[0].upper()
                if cmd == "CAPABILITY":
                    f.write(b"* CAPABILITY " + caps + b"\r\n")
                elif cmd == "LIST":
                    f.write(b'* LIST (\\HasNoChildren) "/" INBOX\r\n')
                elif cmd == "SELECT" or cmd == "EXAMINE":
                    f.write(b"* 3 EXISTS\r\n* 0 RECENT\r\n")
                elif cmd == "IDLE":
                    f.write(b"+ idling\r\n"); f.flush()
                    if push:
                        f.write(b"* 0 RECENT\r\n* 4 EXISTS\r\n"); f.flush()
                    f.readline()  # DONE
                elif cmd == "LOGOUT":
                    f.write(b"* BYE\r\n" + tag.encode() + b" OK done\r\n"); f.flush()
                    break
                f.write(tag.encode() + b" OK done\r\n"); f.flush()
            c.close()
        threading.Thread(target=run, daemon=True).start()
        import imaplib

        def open_(acc):
            conn = imaplib.IMAP4("127.0.0.1", srv.getsockname()[1], timeout=5)
            conn.login("x", "y")
            return conn
        return open_

    def test_told_when_mail_arrives(self):
        with mock.patch.object(d, "_open_imap", self.server()):
            self.assertTrue(d._idle_once({"email": "x"}))

    def test_renewed_when_nothing_comes(self):
        with mock.patch.object(d, "_open_imap", self.server(push=False)):
            self.assertFalse(d._idle_once({"email": "x"}, renew=0.5))

    def test_a_server_without_idle_is_left_to_the_regular_check(self):
        with mock.patch.object(d, "_open_imap", self.server(idle=False)), self.assertRaisesRegex(RuntimeError, "IDLE"):
            d._idle_once({"email": "x"})
