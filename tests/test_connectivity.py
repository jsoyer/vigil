"""Tests for connectivity.py -- ping, gateway, internet checks."""

import subprocess
from unittest import mock

import pytest

from src.connectivity import (
    ping_host,
    ping_gateway,
    check_internet,
    check_connectivity,
    ConnectivityResult,
)


class TestPingHost:
    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_true_on_success(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0)
        assert ping_host("8.8.8.8") is True

    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_false_on_failure(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=1)
        assert ping_host("8.8.8.8") is False

    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_false_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ping", timeout=5)
        assert ping_host("8.8.8.8") is False

    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_false_on_ping_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert ping_host("8.8.8.8") is False

    def test_rejects_invalid_ip_address(self):
        assert ping_host("not-an-ip") is False

    def test_rejects_flag_like_input(self):
        assert ping_host("-v") is False

    def test_accepts_valid_ipv4(self):
        with mock.patch("src.connectivity.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            assert ping_host("1.1.1.1") is True

    def test_accepts_valid_ipv6(self):
        with mock.patch("src.connectivity.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            assert ping_host("::1") is True


class TestPingGateway:
    @mock.patch("src.connectivity.ping_host", return_value=True)
    def test_returns_true_when_gateway_responds(self, mock_ping):
        assert ping_gateway() is True

    @mock.patch("src.connectivity.ping_host", return_value=False)
    def test_returns_false_when_gateway_down(self, mock_ping):
        assert ping_gateway() is False

    @mock.patch("src.connectivity.ping_host", return_value=True)
    @mock.patch("src.connectivity.USG_IP", "10.0.0.1")
    def test_pings_configured_usg_ip(self, mock_ping):
        ping_gateway()
        mock_ping.assert_called_once_with("10.0.0.1")


class TestCheckInternet:
    @mock.patch("src.connectivity.ping_host")
    def test_returns_count_of_responding_targets(self, mock_ping):
        mock_ping.side_effect = [True, False, True]
        assert check_internet() == 2

    @mock.patch("src.connectivity.ping_host", return_value=True)
    def test_all_targets_respond(self, mock_ping):
        assert check_internet() == 3

    @mock.patch("src.connectivity.ping_host", return_value=False)
    def test_no_targets_respond(self, mock_ping):
        assert check_internet() == 0

    @mock.patch("src.connectivity.PING_TARGETS", [])
    def test_returns_zero_on_empty_targets(self):
        assert check_internet() == 0

    @mock.patch("src.connectivity.ping_host")
    def test_pings_all_targets_no_shortcircuit(self, mock_ping):
        mock_ping.side_effect = [True, True, True]
        check_internet()
        assert mock_ping.call_count == 3


class TestCheckConnectivity:
    @mock.patch("src.connectivity.check_internet", return_value=3)
    @mock.patch("src.connectivity.ping_gateway", return_value=True)
    def test_returns_full_result(self, mock_gw, mock_inet):
        result = check_connectivity()
        assert result == ConnectivityResult(
            gateway_ok=True, internet_ok_count=3, internet_total=3
        )

    @mock.patch("src.connectivity.check_internet", return_value=0)
    @mock.patch("src.connectivity.ping_gateway", return_value=False)
    def test_returns_all_down(self, mock_gw, mock_inet):
        result = check_connectivity()
        assert result.gateway_ok is False
        assert result.internet_ok_count == 0

    @mock.patch("src.connectivity.check_internet", return_value=1)
    @mock.patch("src.connectivity.ping_gateway", return_value=True)
    def test_partial_internet(self, mock_gw, mock_inet):
        result = check_connectivity()
        assert result.gateway_ok is True
        assert result.internet_ok_count == 1

    def test_result_is_immutable(self):
        r = ConnectivityResult(gateway_ok=True, internet_ok_count=2, internet_total=3)
        with pytest.raises(AttributeError):
            r.gateway_ok = False  # type: ignore[misc]
