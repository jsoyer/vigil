import unittest
import os
import sys


TESTS_DIR = os.path.dirname(__file__)
REPO_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SRC_DIR = os.path.join(REPO_DIR, "src")

sys.path.insert(0, REPO_DIR)
sys.path.insert(0, SRC_DIR)

from src.notifier import _build_message


class NotifierFormattingTests(unittest.TestCase):
    def test_build_message_escapes_html_content(self):
        message = "Crash <boom> & retry"
        rendered = _build_message(message, "17/03/2026 10:00:00", "host<1>")

        self.assertIn("host&lt;1&gt;", rendered)
        self.assertIn("Crash &lt;boom&gt; &amp; retry", rendered)
        self.assertNotIn("host<1>", rendered)
        self.assertNotIn("Crash <boom> & retry", rendered)


if __name__ == "__main__":
    unittest.main()
