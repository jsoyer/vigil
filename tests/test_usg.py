"""Tests for usg.py -- SSH client and reboot logic."""

from unittest import mock

from src.usg import (
    _ALLOWED_REBOOT_COMMANDS,
    _get_ssh_client,
    reboot_usg,
    test_ssh_connection as usg_test_ssh_connection,
)


class TestAllowedRebootCommands:
    def test_default_command_is_allowed(self):
        assert "sudo reboot" in _ALLOWED_REBOOT_COMMANDS

    def test_rejects_arbitrary_command(self):
        assert "rm -rf /" not in _ALLOWED_REBOOT_COMMANDS

    def test_rejects_chained_commands(self):
        assert "sudo reboot; cat /etc/passwd" not in _ALLOWED_REBOOT_COMMANDS


class TestGetSshClient:
    @mock.patch("src.usg.paramiko", None)
    def test_returns_none_when_paramiko_missing(self):
        assert _get_ssh_client() is None

    @mock.patch("src.usg.paramiko")
    @mock.patch("src.usg.USG_KNOWN_HOSTS", "/nonexistent/known_hosts")
    def test_falls_back_to_warning_policy_when_known_hosts_missing(self, mock_paramiko):
        mock_client = mock.Mock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.WarningPolicy.return_value = mock.Mock()
        mock_paramiko.RejectPolicy.return_value = mock.Mock()
        mock_client.load_host_keys.side_effect = FileNotFoundError

        result = _get_ssh_client()
        # Should still connect but with WarningPolicy instead of RejectPolicy
        assert result is not None
        mock_client.set_missing_host_key_policy.assert_called_once_with(
            mock_paramiko.WarningPolicy.return_value
        )

    @mock.patch("src.usg.paramiko")
    @mock.patch("src.usg.USG_SSH_KEY", "")
    @mock.patch("src.usg.USG_SSH_PASSWORD", "")
    def test_returns_none_when_no_auth_configured(self, mock_paramiko):
        mock_client = mock.Mock()
        mock_paramiko.SSHClient.return_value = mock_client

        assert _get_ssh_client() is None

    @mock.patch("src.usg.paramiko")
    @mock.patch("src.usg.USG_SSH_KEY", "/opt/usg-watchdog/.ssh/usg_ed25519")
    def test_connects_with_key(self, mock_paramiko):
        mock_client = mock.Mock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy.return_value = mock.Mock()

        result = _get_ssh_client()

        assert result is mock_client
        mock_client.connect.assert_called_once()
        connect_kwargs = mock_client.connect.call_args[1]
        assert connect_kwargs["key_filename"] == "/opt/usg-watchdog/.ssh/usg_ed25519"

    @mock.patch("src.usg.paramiko")
    @mock.patch("src.usg.USG_SSH_KEY", "")
    @mock.patch("src.usg.USG_SSH_PASSWORD", "secret123")
    def test_connects_with_password_fallback(self, mock_paramiko):
        mock_client = mock.Mock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy.return_value = mock.Mock()

        result = _get_ssh_client()

        assert result is mock_client
        connect_kwargs = mock_client.connect.call_args[1]
        assert connect_kwargs["password"] == "secret123"


class TestRebootUsg:
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "rm -rf /")
    def test_rejects_command_not_in_allowlist(self):
        assert reboot_usg() is False

    @mock.patch("src.usg._get_ssh_client", return_value=None)
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "sudo reboot")
    def test_returns_false_when_ssh_fails(self, mock_client):
        assert reboot_usg() is False

    @mock.patch("src.usg._get_ssh_client")
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "sudo reboot")
    def test_returns_true_on_success(self, mock_get_client):
        mock_client = mock.Mock()
        mock_get_client.return_value = mock_client

        assert reboot_usg() is True
        mock_client.exec_command.assert_called_once_with("sudo reboot", timeout=5)

    @mock.patch("src.usg._get_ssh_client")
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "sudo reboot")
    def test_returns_true_on_connection_reset(self, mock_get_client):
        mock_client = mock.Mock()
        mock_client.exec_command.side_effect = Exception("Connection reset by peer")
        mock_get_client.return_value = mock_client

        assert reboot_usg() is True

    @mock.patch("src.usg._get_ssh_client")
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "sudo reboot")
    def test_returns_true_on_eof(self, mock_get_client):
        mock_client = mock.Mock()
        mock_client.exec_command.side_effect = Exception("EOF during negotiation")
        mock_get_client.return_value = mock_client

        assert reboot_usg() is True

    @mock.patch("src.usg._get_ssh_client")
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "sudo reboot")
    def test_returns_false_on_unexpected_error(self, mock_get_client):
        mock_client = mock.Mock()
        mock_client.exec_command.side_effect = Exception("Something unexpected")
        mock_get_client.return_value = mock_client

        assert reboot_usg() is False

    @mock.patch("src.usg._get_ssh_client")
    @mock.patch("src.usg.USG_REBOOT_COMMAND", "sudo reboot")
    def test_always_closes_client(self, mock_get_client):
        mock_client = mock.Mock()
        mock_client.exec_command.side_effect = Exception("Something unexpected")
        mock_get_client.return_value = mock_client

        reboot_usg()
        mock_client.close.assert_called_once()


class TestSshConnection:
    @mock.patch("src.usg._get_ssh_client", return_value=None)
    def test_returns_false_on_failure(self, mock_client):
        assert usg_test_ssh_connection() is False

    @mock.patch("src.usg._get_ssh_client")
    def test_returns_true_on_success(self, mock_get_client):
        mock_client = mock.Mock()
        mock_get_client.return_value = mock_client

        assert usg_test_ssh_connection() is True
        mock_client.close.assert_called_once()
