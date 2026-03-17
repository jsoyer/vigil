import importlib
import os
import sys
import unittest
from unittest import mock


TESTS_DIR = os.path.dirname(__file__)
REPO_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SRC_DIR = os.path.join(REPO_DIR, "src")

sys.path.insert(0, REPO_DIR)
sys.path.insert(0, SRC_DIR)


class ConfigEnvResolutionTests(unittest.TestCase):
    def _reload_config(self):
        import src.config as config

        return importlib.reload(config)

    def test_prefers_short_env_names(self):
        env = {
            "CHECK_INTERVAL": "45",
            "WATCHDOG_CHECK_INTERVAL": "90",
            "FAILURE_THRESHOLD": "4",
            "WATCHDOG_FAILURE_THRESHOLD": "8",
            "REBOOT_COOLDOWN": "700",
            "WATCHDOG_REBOOT_COOLDOWN": "900",
        }

        with mock.patch.dict(os.environ, env, clear=False):
            config = self._reload_config()

        self.assertEqual(config.CHECK_INTERVAL, 45)
        self.assertEqual(config.FAILURE_THRESHOLD, 4)
        self.assertEqual(config.REBOOT_COOLDOWN, 700)

    def test_supports_legacy_watchdog_env_names(self):
        env = {
            "CHECK_INTERVAL": "",
            "WATCHDOG_CHECK_INTERVAL": "50",
            "FAILURE_THRESHOLD": "",
            "WATCHDOG_FAILURE_THRESHOLD": "5",
            "REBOOT_COOLDOWN": "",
            "WATCHDOG_REBOOT_COOLDOWN": "800",
        }

        with mock.patch.dict(os.environ, env, clear=False):
            config = self._reload_config()

        self.assertEqual(config.CHECK_INTERVAL, 50)
        self.assertEqual(config.FAILURE_THRESHOLD, 5)
        self.assertEqual(config.REBOOT_COOLDOWN, 800)


if __name__ == "__main__":
    unittest.main()
