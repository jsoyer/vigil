"""Tests for config.py -- environment variable resolution and validation."""

import importlib
import os
from unittest import mock


def _reload_config():
    import src.config as config

    return importlib.reload(config)


class TestGetEnv:
    def test_prefers_short_env_names(self):
        env = {
            "CHECK_INTERVAL": "45",
            "WATCHDOG_CHECK_INTERVAL": "90",
            "REBOOT_COOLDOWN": "700",
            "WATCHDOG_REBOOT_COOLDOWN": "900",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = _reload_config()

        assert config.CHECK_INTERVAL == 45
        assert config.REBOOT_COOLDOWN == 700

    def test_supports_legacy_watchdog_env_names(self):
        env = {
            "CHECK_INTERVAL": "",
            "WATCHDOG_CHECK_INTERVAL": "50",
            "REBOOT_COOLDOWN": "",
            "WATCHDOG_REBOOT_COOLDOWN": "800",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = _reload_config()

        assert config.CHECK_INTERVAL == 50
        assert config.REBOOT_COOLDOWN == 800

    def test_uses_defaults_when_no_env(self):
        env = {
            "CHECK_INTERVAL": "",
            "WATCHDOG_CHECK_INTERVAL": "",
            "REBOOT_COOLDOWN": "",
            "WATCHDOG_REBOOT_COOLDOWN": "",
            "REBOOT_SCORE_THRESHOLD": "",
            "MAX_SCORE": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = _reload_config()

        assert config.CHECK_INTERVAL == 30
        assert config.REBOOT_COOLDOWN == 900
        assert config.REBOOT_SCORE_THRESHOLD == 10
        assert config.MAX_SCORE == 15
        assert config.POST_REBOOT_GRACE == 360


class TestGetIntEnvValidation:
    def test_invalid_integer_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {"CHECK_INTERVAL": "abc"}, clear=False):
            config = _reload_config()
        assert config.CHECK_INTERVAL == 30

    def test_zero_value_clamped_to_minimum(self):
        with mock.patch.dict(os.environ, {"CHECK_INTERVAL": "0"}, clear=False):
            config = _reload_config()
        assert config.CHECK_INTERVAL >= 5

    def test_negative_value_clamped_to_minimum(self):
        with mock.patch.dict(os.environ, {"REBOOT_SCORE_THRESHOLD": "-1"}, clear=False):
            config = _reload_config()
        assert config.REBOOT_SCORE_THRESHOLD >= 3

    def test_reboot_cooldown_minimum_enforced(self):
        with mock.patch.dict(os.environ, {"REBOOT_COOLDOWN": "10"}, clear=False):
            config = _reload_config()
        assert config.REBOOT_COOLDOWN >= 60


class TestScoringDefaults:
    def test_scoring_point_defaults(self):
        env = {
            "SCORE_GATEWAY_DOWN": "",
            "SCORE_INTERNET_ALL_DOWN": "",
            "SCORE_INTERNET_PARTIAL": "",
            "SCORE_DECAY_OK": "",
            "SCORE_DECAY_PARTIAL": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = _reload_config()

        assert config.SCORE_GATEWAY_DOWN == 4
        assert config.SCORE_INTERNET_ALL_DOWN == 3
        assert config.SCORE_INTERNET_PARTIAL == 1
        assert config.SCORE_DECAY_OK == 2
        assert config.SCORE_DECAY_PARTIAL == 1
