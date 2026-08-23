"""Tests for the /opt/usg-watchdog -> /opt/vigil install path fallback
(PRD 2.0.0, "grand renommage Vigil").

Covers `config._resolve_install_path()` directly, the module-level
constants that consume it (USG_SSH_KEY, USG_KNOWN_HOSTS, LOG_FILE), and
the `.env` reload path resolved inside `http_server.py`.

All cases mock `os.path.isdir` (and, where relevant, `os.path.isfile`) so
the outcome never depends on whether this machine actually has
/opt/vigil or /opt/usg-watchdog on disk.
"""

import importlib
from unittest import mock


def _reload_config():
    import src.config as config

    return importlib.reload(config)


def _fake_isdir(vigil_present: bool, old_present: bool):
    """Build an os.path.isdir stub that only recognizes the two install dirs."""

    def _isdir(path):
        if path == "/opt/vigil":
            return vigil_present
        if path == "/opt/usg-watchdog":
            return old_present
        return False

    return _isdir


class TestResolveInstallPathDirect:
    """Exercise config._resolve_install_path() in isolation."""

    def test_vigil_present_old_absent_uses_new_path(self):
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(True, False)):
            config = _reload_config()
            result = config._resolve_install_path(
                "/opt/vigil/.env", "/opt/usg-watchdog/.env"
            )
        assert result == "/opt/vigil/.env"

    def test_vigil_present_old_also_present_still_uses_new_path(self):
        # Both installed (mid-migration machine) -- new path wins.
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(True, True)):
            config = _reload_config()
            result = config._resolve_install_path(
                "/opt/vigil/.env", "/opt/usg-watchdog/.env"
            )
        assert result == "/opt/vigil/.env"

    def test_vigil_absent_old_present_falls_back_to_old_path(self):
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(False, True)):
            config = _reload_config()
            result = config._resolve_install_path(
                "/opt/vigil/.env", "/opt/usg-watchdog/.env"
            )
        assert result == "/opt/usg-watchdog/.env"

    def test_neither_present_uses_new_path(self):
        # Fresh dev environment -- default to the new path.
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(False, False)):
            config = _reload_config()
            result = config._resolve_install_path(
                "/opt/vigil/.env", "/opt/usg-watchdog/.env"
            )
        assert result == "/opt/vigil/.env"


class TestModuleLevelConstantsFollowFallback:
    """USG_SSH_KEY, USG_KNOWN_HOSTS and LOG_FILE are computed at import
    time from _resolve_install_path -- reload config.py under each
    filesystem scenario to confirm they pick up the right prefix while
    the SSH key filename itself never changes.
    """

    def test_vigil_present_new_defaults(self, monkeypatch):
        # USG_KNOWN_HOSTS / LOG_FILE use raw os.getenv(name, default) --
        # the default only applies when the var is ABSENT, so these must
        # be deleted (not set to "") to exercise the fallback default.
        monkeypatch.delenv("USG_SSH_KEY", raising=False)
        monkeypatch.delenv("USG_KNOWN_HOSTS", raising=False)
        monkeypatch.delenv("LOG_FILE", raising=False)
        with (
            mock.patch("os.path.isdir", side_effect=_fake_isdir(True, False)),
            mock.patch("os.path.isfile", return_value=False),
        ):
            config = _reload_config()

        assert config.USG_SSH_KEY == "/opt/vigil/.ssh/usg_ed25519"
        assert config.USG_KNOWN_HOSTS == "/opt/vigil/.ssh/known_hosts"
        assert config.LOG_FILE == "/var/log/vigil.log"

    def test_vigil_absent_old_present_old_defaults(self, monkeypatch):
        monkeypatch.delenv("USG_SSH_KEY", raising=False)
        monkeypatch.delenv("USG_KNOWN_HOSTS", raising=False)
        monkeypatch.delenv("LOG_FILE", raising=False)
        with (
            mock.patch("os.path.isdir", side_effect=_fake_isdir(False, True)),
            mock.patch("os.path.isfile", return_value=False),
        ):
            config = _reload_config()

        assert config.USG_SSH_KEY == "/opt/usg-watchdog/.ssh/usg_ed25519"
        assert config.USG_KNOWN_HOSTS == "/opt/usg-watchdog/.ssh/known_hosts"
        assert config.LOG_FILE == "/var/log/usg-watchdog.log"

    def test_ssh_key_filename_never_changes_across_scenarios(self, monkeypatch):
        # Only the /opt/... prefix moves -- the filename "usg_ed25519" is
        # a hard invariant regardless of which install path is active.
        monkeypatch.delenv("USG_SSH_KEY", raising=False)
        with (
            mock.patch("os.path.isdir", side_effect=_fake_isdir(True, False)),
            mock.patch("os.path.isfile", return_value=False),
        ):
            new_key = _reload_config().USG_SSH_KEY

        with (
            mock.patch("os.path.isdir", side_effect=_fake_isdir(False, True)),
            mock.patch("os.path.isfile", return_value=False),
        ):
            old_key = _reload_config().USG_SSH_KEY

        assert new_key.endswith("/usg_ed25519")
        assert old_key.endswith("/usg_ed25519")
        assert new_key != old_key
        assert new_key == "/opt/vigil/.ssh/usg_ed25519"
        assert old_key == "/opt/usg-watchdog/.ssh/usg_ed25519"

    def test_explicit_env_var_bypasses_fallback_entirely(self, monkeypatch):
        # An explicit USG_SSH_KEY always wins, regardless of filesystem state.
        monkeypatch.setenv("USG_SSH_KEY", "/custom/key")
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(True, True)):
            config = _reload_config()

        assert config.USG_SSH_KEY == "/custom/key"


class TestHttpServerEnvPathFallback:
    """http_server.py resolves its .env reload path inline via
    `_config._resolve_install_path(...)` (see _handle_config_reload) --
    exercise that same call with the same arguments used there.
    """

    def _resolve_env_path(self):
        import src.http_server as http_server_mod

        return http_server_mod._config._resolve_install_path(
            "/opt/vigil/.env", "/opt/usg-watchdog/.env"
        )

    def test_vigil_present_resolves_new_env_path(self):
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(True, False)):
            result = self._resolve_env_path()
        assert result == "/opt/vigil/.env"

    def test_vigil_absent_old_present_resolves_old_env_path(self):
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(False, True)):
            result = self._resolve_env_path()
        assert result == "/opt/usg-watchdog/.env"

    def test_neither_present_resolves_new_env_path(self):
        with mock.patch("os.path.isdir", side_effect=_fake_isdir(False, False)):
            result = self._resolve_env_path()
        assert result == "/opt/vigil/.env"
