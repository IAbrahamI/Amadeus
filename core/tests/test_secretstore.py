"""Mail logins on a Mac live in the Keychain, never in the file. Here the Keychain is a stand-in; the Mac build checks
the real one (.github/workflows/mac-app.yml)."""
import json
import unittest
from unittest import mock

from . import HOME  # noqa: F401
from amadeus_core import maildirect as d, secretstore


def _file():
    with open(d.ACCOUNTS_FILE) as f:
        return f.read()


class FakeKeychain:
    def __init__(self):
        self.items, self.locked = {}, False

    def _open(self):
        if self.locked:
            raise secretstore.Unavailable("locked")

    def put(self, name, value):
        self._open(); self.items[name] = value

    def get(self, name):
        self._open(); return self.items.get(name)

    def delete(self, name):
        self._open(); self.items.pop(name, None)


class Keychain(unittest.TestCase):
    def setUp(self):
        self.k = FakeKeychain()
        self.p = [mock.patch.object(secretstore, n, getattr(self.k, n)) for n in ("put", "get", "delete")] + \
            [mock.patch.object(secretstore, "native", return_value=True), mock.patch.object(d, "_test"), mock.patch("builtins.print")]
        for x in self.p:
            x.start()
        d._secrets.clear()

    def tearDown(self):
        for a in d._read():
            d.remove_account(a["id"])
        for x in self.p:
            x.stop()
        d._secrets.clear()

    def test_the_file_never_holds_the_login(self):
        acc = d.add_account("gmail", "k@example.invalid", "s3cret")
        self.assertNotIn("s3cret", _file())
        self.assertEqual(json.loads(self.k.items[f"mail:{acc['id']}"]), {"password": "s3cret"})
        d._secrets.clear()  # as after a restart
        self.assertEqual(d._account(acc["id"])["password"], "s3cret")
        d.remove_account(acc["id"])
        self.assertEqual(self.k.items, {})

    def test_an_older_file_moves_over(self):
        with mock.patch.object(secretstore, "native", return_value=False):
            d.add_account("gmail", "old@example.invalid", "inthefile")
        self.assertIn("inthefile", _file())
        d.to_keychain()
        self.assertNotIn("inthefile", _file())
        d._secrets.clear()
        self.assertEqual(d._load()[0]["password"], "inthefile")

    def test_a_locked_keychain_loses_nothing(self):
        acc = d.add_account("gmail", "l@example.invalid", "keepme")
        d._secrets.clear()
        self.k.locked = True
        self.assertNotIn("password", d._account(acc["id"]))
        d.update_account(acc["id"], name="Renamed")  # saving while it's locked doesn't wipe the login
        self.k.locked = False
        self.assertEqual(d._account(acc["id"])["password"], "keepme")
        self.assertEqual(d._account(acc["id"])["name"], "Renamed")


if __name__ == "__main__":
    unittest.main()
