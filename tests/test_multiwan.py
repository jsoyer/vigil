"""Tests for src/multiwan.py"""

from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# WanStatus helpers
# ---------------------------------------------------------------------------


class TestWanStatus:
    def test_default_values(self):
        from multiwan import WanStatus

        w = WanStatus()
        assert w.primary_up is True
        assert w.failover_active is False
        assert w.active_interface == "unknown"
        assert w.reachable is False

    def test_to_dict(self):
        from multiwan import WanStatus

        w = WanStatus(
            primary_up=True,
            failover_active=False,
            active_interface="eth0",
            reachable=True,
        )
        d = w.to_dict()
        assert d["primary_up"] is True
        assert d["failover_active"] is False
        assert d["active_interface"] == "eth0"
        assert d["reachable"] is True

    def test_summary_unreachable(self):
        from multiwan import WanStatus

        w = WanStatus(reachable=False)
        assert "injoignable" in w.summary()

    def test_summary_primary_active(self):
        from multiwan import WanStatus

        w = WanStatus(
            primary_up=True,
            failover_active=False,
            active_interface="eth0",
            reachable=True,
        )
        s = w.summary()
        assert "eth0" in s
        assert "failover" not in s.lower()

    def test_summary_failover_active(self):
        from multiwan import WanStatus

        w = WanStatus(
            primary_up=False,
            failover_active=True,
            active_interface="eth2",
            reachable=True,
        )
        s = w.summary()
        assert "failover" in s.lower()
        assert "eth2" in s


# ---------------------------------------------------------------------------
# check_wan_status -- paramiko not available
# ---------------------------------------------------------------------------


class TestCheckWanStatusNoParamiko:
    def test_returns_unreachable_when_paramiko_none(self):
        with patch("multiwan.paramiko", None):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is False


# ---------------------------------------------------------------------------
# check_wan_status -- known_hosts missing
# ---------------------------------------------------------------------------


class TestCheckWanStatusKnownHostsMissing:
    def test_returns_unreachable_when_known_hosts_missing(self):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.side_effect = FileNotFoundError("no such file")

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is False


# ---------------------------------------------------------------------------
# check_wan_status -- SSH success, eth0 (primary)
# ---------------------------------------------------------------------------


class TestCheckWanStatusEth0:
    def _make_paramiko(self, route_output: str):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.return_value = None

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = route_output.encode("utf-8")
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())
        return mock_paramiko, mock_client

    def test_eth0_primary_active(self):
        output = (
            "default via 192.168.1.254 dev eth0 proto dhcp src 192.168.1.1 metric 100"
        )
        mock_paramiko, _ = self._make_paramiko(output)

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is True
            assert result.active_interface == "eth0"
            assert result.failover_active is False
            assert result.primary_up is True

    def test_eth2_failover_active(self):
        output = "default via 10.0.0.1 dev eth2 proto dhcp"
        mock_paramiko, _ = self._make_paramiko(output)

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is True
            assert result.active_interface == "eth2"
            assert result.failover_active is True
            assert result.primary_up is False

    def test_ppp1_failover_active(self):
        output = "default via 0.0.0.0 dev ppp1"
        mock_paramiko, _ = self._make_paramiko(output)

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.active_interface == "ppp1"
            assert result.failover_active is True

    def test_empty_output_unknown_interface(self):
        mock_paramiko, _ = self._make_paramiko("")

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is True
            assert result.active_interface == "unknown"

    def test_unknown_interface_in_output(self):
        output = "default via 10.0.0.1 dev bond0"
        mock_paramiko, _ = self._make_paramiko(output)

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            # bond0 doesn't start with eth or ppp, so interface remains "unknown"
            assert result.active_interface == "unknown"
            assert result.failover_active is False

    def test_closes_ssh_client(self):
        output = "default via 1.2.3.4 dev eth0"
        mock_paramiko, mock_client = self._make_paramiko(output)

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            check_wan_status()
            mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# check_wan_status -- connection failure
# ---------------------------------------------------------------------------


class TestCheckWanStatusConnectionFailed:
    def test_returns_unreachable_on_auth_error(self):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.return_value = None
        mock_client.connect.side_effect = Exception("Authentication failed")

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is False

    def test_returns_unreachable_on_timeout(self):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.return_value = None
        mock_client.connect.side_effect = Exception("Connection timed out")

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is False

    def test_returns_unreachable_on_host_key_mismatch(self):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.return_value = None
        mock_client.connect.side_effect = Exception("Host key mismatch")

        with patch("multiwan.paramiko", mock_paramiko):
            from multiwan import check_wan_status

            result = check_wan_status()
            assert result.reachable is False

    def test_uses_configured_ssh_params(self):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.return_value = None

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"default via 1.2.3.4 dev eth0"
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

        with (
            patch("multiwan.paramiko", mock_paramiko),
            patch("multiwan.USG_IP", "192.168.1.1"),
            patch("multiwan.USG_USER", "admin"),
            patch("multiwan.USG_SSH_KEY", "/path/to/key"),
            patch("multiwan.SSH_TIMEOUT", 15),
        ):
            from multiwan import check_wan_status

            check_wan_status()
            connect_kwargs = mock_client.connect.call_args[1]
            assert connect_kwargs["hostname"] == "192.168.1.1"
            assert connect_kwargs["username"] == "admin"
            assert connect_kwargs["key_filename"] == "/path/to/key"
            assert connect_kwargs["timeout"] == 15

    def test_no_key_when_ssh_key_empty(self):
        mock_paramiko = MagicMock()
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.RejectPolicy = MagicMock()
        mock_client.load_host_keys.return_value = None

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"default via 1.2.3.4 dev eth0"
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

        with (
            patch("multiwan.paramiko", mock_paramiko),
            patch("multiwan.USG_SSH_KEY", ""),
        ):
            from multiwan import check_wan_status

            check_wan_status()
            connect_kwargs = mock_client.connect.call_args[1]
            assert connect_kwargs["key_filename"] is None
