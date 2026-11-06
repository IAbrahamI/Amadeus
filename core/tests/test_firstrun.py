import json
import os
from pathlib import Path
import stat
import unittest
from unittest import mock

from . import HOME
from amadeus_core import firstrun, paths
from amadeus_core.config import CFG, CONFIG_PATH


class FirstStart(unittest.TestCase):
    """The Mac app has no installer: the first start sets up what install.sh would."""

    def setUp(self):
        self.addCleanup(lambda: os.path.exists(CONFIG_PATH) and os.remove(CONFIG_PATH))

    def config(self, **values):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        Path(CONFIG_PATH).write_text(json.dumps(values))

    def test_an_install_with_its_model_never_sees_it(self):
        self.config(default_model="mine")
        with mock.patch.object(firstrun, "ollama_state") as state:
            self.assertFalse(firstrun.needed())
            state.assert_not_called()

    def test_on_a_mac_without_ollama_it_starts(self):
        with mock.patch.object(firstrun, "ollama_state", return_value="missing"), mock.patch.object(firstrun.system, "MAC", True):
            self.assertTrue(firstrun.needed())

    def test_on_linux_a_stopped_ollama_is_not_a_first_start(self):
        with mock.patch.object(firstrun, "ollama_state", return_value="installed"), mock.patch.object(firstrun.system, "MAC", False):
            self.assertFalse(firstrun.needed())

    def test_an_existing_install_with_the_default_model_is_left_alone(self):
        with mock.patch.object(firstrun, "ollama_state", return_value="running"), mock.patch.object(firstrun, "_models", return_value=[CFG["default_model"]]):
            self.assertFalse(firstrun.needed())
        with mock.patch.object(firstrun, "ollama_state", return_value="running"), mock.patch.object(firstrun, "_models", return_value=[]):
            self.assertTrue(firstrun.needed())

    def test_the_folder_and_private_files(self):
        folder = os.path.join(HOME, "FirstRun")
        with mock.patch.object(firstrun.workguard, "install") as guard:
            firstrun.prepare_folder(folder)
        real = os.path.realpath(folder)
        self.assertTrue(os.path.isfile(os.path.join(real, "Notes", "README.md")))
        self.assertTrue(os.path.isdir(os.path.join(real, "Projects")))
        guard.assert_called_once_with(os.path.join(real, "Projects"), os.path.join(real, "Notes"))
        self.assertEqual(json.loads(Path(CONFIG_PATH).read_text())["folder"], real)
        keys = os.path.join(paths.SECRETS, "hindsight-keys.json")
        self.assertEqual(stat.S_IMODE(os.stat(keys).st_mode), 0o600)

    def test_only_a_folder_inside_home(self):
        for bad in ("/tmp", HOME):
            with self.assertRaises(ValueError):
                firstrun.prepare_folder(bad)

    def test_only_a_suggested_model(self):
        with self.assertRaises(ValueError):
            firstrun.act("begin", {"model": "something-else"})

    def test_the_page_gets_an_answer_on_a_mac(self):
        with mock.patch.object(firstrun, "ollama_state", return_value="missing"), mock.patch.object(firstrun.system, "MAC", True), \
                mock.patch.object(firstrun.pick_model, "hardware", return_value={"ram_gb": 16}):
            s = firstrun.status()
        self.assertTrue(s["needed"])
        self.assertEqual(s["ollama"], "missing")

    def test_it_stays_until_you_finish(self):
        self.config(default_model="mine", setup_pending=True)
        self.assertTrue(firstrun.needed())
        with mock.patch.object(firstrun.system, "restart"):
            firstrun.act("finish", {})
        self.assertFalse(firstrun.needed())

    def test_no_finishing_without_a_model(self):
        self.config(setup_pending=True)
        with self.assertRaises(ValueError):
            firstrun.act("finish", {})

    def test_a_model_for_a_newer_ollama_offers_the_update(self):
        with mock.patch.dict(firstrun._job, kind="begin", error="pull model manifest: 412: requires a newer version of Ollama", done=True), \
                mock.patch.object(firstrun, "needed", return_value=True), mock.patch.object(firstrun, "ollama_state", return_value="running"), \
                mock.patch.object(firstrun.pick_model, "hardware", return_value={}):
            self.assertTrue(firstrun.status()["too_old"])

    def test_updating_needs_the_app_in_applications(self):
        with mock.patch.object(firstrun, "OLLAMA_APPS", ("/nowhere/Ollama.app",)), self.assertRaises(ValueError):
            firstrun._update_ollama()

    def test_a_mac_notification_goes_through_the_app(self):
        from amadeus_core import desktop, system
        with mock.patch.object(system, "MAC", True), mock.patch.object(desktop, "send") as send, mock.patch("subprocess.run") as run:
            system.notify("Amadeus", "Hello")
        send.assert_called_once_with({"do": "notify", "data": {"title": "Amadeus", "text": "Hello"}})
        run.assert_not_called()

    def test_what_a_model_did_is_remembered(self):
        latest = [{"name": "bad", "versions": [("bad:8b", 6.0)]}, {"name": "new", "versions": [("new:8b", 6.0)]}]
        self.config(models_failed=["bad:8b"], models_proven=["new:8b"])
        with mock.patch.object(firstrun, "_baseline", return_value=None), mock.patch.object(firstrun.pick_model, "registry_reachable", return_value=True), \
                mock.patch.object(firstrun.pick_model, "latest_models", return_value=latest), \
                mock.patch.object(firstrun.pick_model, "hardware", return_value={"gpu_gb": 12.0, "gpu": "", "ram_gb": 16.0, "cores": 8, "disk_gb": 100.0}):
            firstrun._scan()
        got = {p["model"]: p["proven"] for p in firstrun._picks}
        firstrun._picks.clear()
        self.assertNotIn("bad:8b", got)
        self.assertTrue(got["new:8b"])
        self.assertTrue(got["qwen3.5:9b"])

    def test_ollama_installed_elsewhere_is_never_installed_again(self):
        with mock.patch.object(firstrun.system, "MAC", True), mock.patch.object(firstrun, "OLLAMA_APPS", ("/nowhere/Ollama.app",)), \
                mock.patch.object(firstrun, "_models", side_effect=OSError), mock.patch.object(firstrun.subprocess, "run", return_value=mock.Mock(returncode=0)):
            self.assertEqual(firstrun.ollama_state(), "installed")
        with mock.patch.object(firstrun, "ollama_state", return_value="installed"), mock.patch.object(firstrun, "_start_ollama") as start, \
                mock.patch.object(firstrun.urllib.request, "urlopen") as download:
            firstrun._install_ollama()
        start.assert_called_once()
        download.assert_not_called()

    def test_no_filter_means_an_answer_at_once_and_nothing_leaves(self):
        from amadeus_core import privacy
        import time
        with mock.patch.object(privacy.system, "MAC", True), mock.patch.object(privacy, "ensure_presidio") as start, mock.patch.object(privacy, "_ner") as ner:
            t = time.time()
            _, findings, hold = privacy.scrub("Hello there")
        self.assertLess(time.time() - t, 1)
        self.assertTrue(hold)
        self.assertIn("presidio-unavailable", findings)
        start.assert_not_called()
        ner.assert_not_called()

    def test_a_filter_that_can_connect_is_never_used(self):
        from amadeus_core import macfilter
        class Fake:
            stdout = mock.Mock(readline=lambda self=None: '{"ready": false, "sealed": false}')
            kill = mock.Mock()
        with mock.patch.object(macfilter.subprocess, "Popen", return_value=Fake()), mock.patch.object(macfilter, "command", return_value=["x"]), self.assertRaises(OSError):
            macfilter._start()
        self.assertIsNone(macfilter._proc)

    def test_the_seal_has_no_network_and_no_writing(self):
        from amadeus_core import macfilter
        rules = macfilter.profile()
        self.assertIn("(deny network*)", rules)
        self.assertIn("(deny file-write*)", rules)
        self.assertNotIn("allow network", rules)

    def test_the_filter_failing_holds_the_text_back(self):
        from amadeus_core import macfilter, privacy
        with mock.patch.object(privacy.system, "MAC", True), mock.patch.object(macfilter, "ready", return_value=True), \
                mock.patch.object(macfilter, "start", side_effect=OSError), mock.patch.object(macfilter, "call", side_effect=OSError):
            self.assertTrue(privacy.scrub("Anna lives in Berlin")[2])

    def test_a_failed_sign_in_is_said_plainly(self):
        from amadeus_core import work
        self.assertTrue(work.SIGNED_OUT.search("Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue."))
        self.assertFalse(work.SIGNED_OUT.search("The tests failed."))

    def test_claude_code_status(self):
        from amadeus_core import db, work
        with mock.patch.object(work, "claude_path", return_value=None):
            self.assertEqual(work.claude_status(), {"installed": False, "signed_in": False})
        with mock.patch.object(work, "claude_path", return_value="/x/claude"), mock.patch.object(work.subprocess, "run", return_value=mock.Mock(stdout='{"loggedIn": true}')):
            self.assertTrue(work.claude_status()["signed_in"])
            db.set_setting("claude_signed_out", True)
            self.assertFalse(work.claude_status()["signed_in"])
            db.set_setting("claude_signed_out", False)

    def test_a_mac_counts_its_shared_memory(self):
        def sysctl(cmd, **_):
            return mock.Mock(stdout={"hw.memsize": str(16 * 2 ** 30), "machdep.cpu.brand_string": "Apple M1"}[cmd[-1]])
        with mock.patch.object(firstrun.pick_model.subprocess, "run", side_effect=sysctl):
            hw = firstrun.pick_model._mac_hardware()
        self.assertEqual((hw["ram_gb"], hw["gpu_gb"], hw["gpu"]), (16.0, 11.2, "Apple M1"))
        self.assertEqual(firstrun.pick_model.runs_on(6, hw), "gpu")
