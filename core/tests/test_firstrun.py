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

    def test_a_mac_counts_its_shared_memory(self):
        def sysctl(cmd, **_):
            return mock.Mock(stdout={"hw.memsize": str(16 * 2 ** 30), "machdep.cpu.brand_string": "Apple M1"}[cmd[-1]])
        with mock.patch.object(firstrun.pick_model.subprocess, "run", side_effect=sysctl):
            hw = firstrun.pick_model._mac_hardware()
        self.assertEqual((hw["ram_gb"], hw["gpu_gb"], hw["gpu"]), (16.0, 11.2, "Apple M1"))
        self.assertEqual(firstrun.pick_model.runs_on(6, hw), "gpu")
