"""Pytest configuration -- ensure src/ is on the import path."""

import os
import sys

TESTS_DIR = os.path.dirname(__file__)
REPO_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SRC_DIR = os.path.join(REPO_DIR, "src")

sys.path.insert(0, REPO_DIR)
sys.path.insert(0, SRC_DIR)
