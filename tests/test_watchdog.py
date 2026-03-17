import os
import sys
import unittest
from unittest import mock


TESTS_DIR = os.path.dirname(__file__)
REPO_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SRC_DIR = os.path.join(REPO_DIR, "src")

sys.path.insert(0, REPO_DIR)
sys.path.insert(0, SRC_DIR)

from src import watchdog


class WatchdogOutageDurationTests(unittest.TestCase):
    def test_uses_failure_count_when_outage_start_is_unknown(self):
        duration = watchdog._get_outage_duration_seconds(None, 3)

        self.assertEqual(duration, 3 * watchdog.CHECK_INTERVAL)

    def test_keeps_real_elapsed_outage_after_reboot_reset(self):
        with mock.patch("src.watchdog.time.time", return_value=130.0):
            duration = watchdog._get_outage_duration_seconds(100.0, 0)

        self.assertEqual(duration, 30)

    def test_never_reports_less_than_failure_based_duration(self):
        with mock.patch("src.watchdog.time.time", return_value=105.0):
            duration = watchdog._get_outage_duration_seconds(100.0, 2)

        self.assertEqual(duration, 2 * watchdog.CHECK_INTERVAL)


if __name__ == "__main__":
    unittest.main()
