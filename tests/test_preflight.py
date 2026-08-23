"""Tests pour updater/preflight.py -- verifications de pre-demarrage.

Suite creee lors du grand renommage Vigil (le fichier n'avait aucun test).
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))

import preflight


class TestCheckPythonVersion:
    def test_current_interpreter_passes(self):
        # La suite tourne sur Python >= 3.11 (prerequis projet).
        assert preflight.check_python_version() is True

    def test_old_python_fails(self):
        with patch.object(preflight.sys, "version_info", (3, 9, 0)):
            assert preflight.check_python_version() is False


class TestCheckImports:
    def test_core_modules_importable(self):
        # Depuis le repo, le repli src/ (pas de current/) doit suffire.
        assert preflight.check_imports() is True

    def test_drivers_and_managed_devices_importable(self):
        # A1 -- preflight.check_imports() ajoute desormais drivers/ et
        # managed_devices.py aux modules verifies au demarrage du service.
        # Invariant C1 : les deux doivent s'importer sans tplinkrouterc6u
        # installee (aucun equipement TP-Link n'a besoin d'etre declare).
        src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
        sys.path.insert(0, src_dir)
        import drivers  # noqa: F401
        import managed_devices  # noqa: F401

        assert preflight.check_imports() is True


class TestCheckPort:
    def test_free_port_returns_true(self):
        # Port arbitraire tres probablement libre ; la fonction ne doit
        # jamais etre fatale de toute facon.
        assert preflight.check_port(port=64999) is True

    def test_never_raises_on_socket_error(self):
        with patch.object(preflight.socket, "socket", side_effect=OSError("boom")):
            assert preflight.check_port(port=9000) is True


class TestMain:
    def test_main_returns_zero_when_all_ok(self):
        assert preflight.main() == 0
