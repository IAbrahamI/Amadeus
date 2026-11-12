"""The long-term memory: which Hindsight is used, whether it answers, and that Amadeus only claims a memory it has."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from amadeus_core import agent, memory, tools


class Fake(BaseHTTPRequestHandler):
    """A Hindsight that knows one bank and one key."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.headers.get("authorization") != "Bearer right":
            self.send_response(401); self.end_headers(); return
        if not self.path.startswith("/v1/default/banks/mine/"):
            self.send_response(404); self.end_headers(); return
        data = b'{"total_nodes": 3}'
        self.send_response(200); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)


class External(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        self.tmp = tempfile.mkdtemp()
        self.p = [mock.patch.object(memory, "EXTERNAL", os.path.join(self.tmp, "ext.json")),
                  mock.patch.object(memory.paths, "SECRETS", self.tmp)]
        for x in self.p:
            x.start()
        memory._state["key"] = None

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.srv.shutdown()
        self.srv.server_close()

    def test_wrong_key_or_bank_is_not_saved(self):
        with self.assertRaisesRegex(ValueError, "key"):
            memory.use_external(self.url, "mine", "wrong")
        with self.assertRaisesRegex(ValueError, "bank"):
            memory.use_external(self.url, "other", "right")
        with self.assertRaisesRegex(ValueError, "http"):
            memory.use_external("192.168.1.2:8888", "mine", "right")
        self.assertIsNone(memory.external())

    def test_saved_privately_and_used_then_back_to_local(self):
        st = memory.use_external(self.url + "/", "mine", "right")
        self.assertEqual((st["mode"], st["ready"], st["url"]), ("external", True, self.url))
        self.assertNotIn("key", st)
        self.assertEqual(os.stat(memory.EXTERNAL).st_mode & 0o777, 0o600)
        self.assertEqual(memory.conn(), (self.url, "mine", "right"))
        self.assertEqual(memory.request("/stats", None), {"total_nodes": 3})
        self.assertEqual(memory.use_local()["mode"], "local")
        self.assertFalse(os.path.exists(memory.EXTERNAL))

    def test_leaving_the_pc_is_flagged(self):
        with mock.patch.object(memory, "external", return_value={"url": "http://192.168.1.2:8888", "bank": "b", "key": ""}), \
                mock.patch.object(memory, "check", return_value=(True, "")):
            st = memory.status()
        self.assertTrue(st["leaves_pc"] and st["plain_http"])


class HonestAboutItself(unittest.TestCase):
    def test_no_memory_is_said_and_never_promised(self):
        with mock.patch.object(memory, "check", return_value=(False, "It doesn't answer (refused).")):
            text = agent.about_me()
            self.assertIn("Long-term memory: NOT available", text)
            self.assertNotIn("long-term facts (Hindsight)", text)
            self.assertNotIn("remember", [s["function"]["name"] for s in tools.schemas()])

    def test_memory_there_is_described(self):
        with mock.patch.object(memory, "check", return_value=(True, "")):
            self.assertIn("long-term facts (Hindsight)", agent.about_me())

    def test_no_mail_account_means_no_mail_promises(self):
        with mock.patch.object(tools, "missing", side_effect=lambda c: "Not connected yet." if c == "mail" else ""):
            text = agent.about_me()
        self.assertIn("Mail: NOT available", text)
        self.assertNotIn("forward, attachments", text)


if __name__ == "__main__":
    unittest.main()
