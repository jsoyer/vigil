"""Tests for connectivity.py -- ping, gateway, internet checks, latency."""

import subprocess
from unittest import mock

import pytest

from src.connectivity import (
    ping_host,
    ping_gateway,
    check_internet,
    check_connectivity,
    ConnectivityResult,
    PingResult,
    LatencyTracker,
    _parse_rtt,
)


class TestPingHost:
    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_ok_with_rtt(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="time=1.23 ms")
        result = ping_host("8.8.8.8")
        assert result.ok is True
        assert result.rtt_ms == 1.23

    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_not_ok_on_failure(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=1, stdout="")
        result = ping_host("8.8.8.8")
        assert result.ok is False
        assert result.rtt_ms is None

    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_not_ok_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ping", timeout=5)
        result = ping_host("8.8.8.8")
        assert result.ok is False

    @mock.patch("src.connectivity.subprocess.run")
    def test_returns_not_ok_on_ping_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        result = ping_host("8.8.8.8")
        assert result.ok is False

    def test_rejects_invalid_ip(self):
        result = ping_host("not-an-ip")
        assert result.ok is False

    def test_rejects_flag_input(self):
        result = ping_host("-v")
        assert result.ok is False

    @mock.patch("src.connectivity.subprocess.run")
    def test_accepts_valid_ipv6(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="time=0.5 ms")
        result = ping_host("::1")
        assert result.ok is True


class TestParseRtt:
    def test_standard_format(self):
        assert (
            _parse_rtt("64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=1.23 ms") == 1.23
        )

    def test_less_than_format(self):
        assert _parse_rtt("time<1 ms") == 1.0

    def test_no_match(self):
        assert _parse_rtt("no rtt here") is None


class TestLatencyTracker:
    def test_empty_tracker(self):
        t = LatencyTracker()
        assert t.average() is None
        assert t.max() is None
        assert t.is_degraded() is False

    def test_records_and_averages(self):
        t = LatencyTracker(window_size=3)
        t.record(10.0)
        t.record(20.0)
        t.record(30.0)
        assert t.average() == 20.0
        assert t.max() == 30.0

    def test_sliding_window(self):
        t = LatencyTracker(window_size=2)
        t.record(10.0)
        t.record(20.0)
        t.record(100.0)  # 10.0 evicted
        assert t.average() == 60.0

    def test_degradation_detection(self):
        t = LatencyTracker(window_size=3)
        t.record(300.0)
        t.record(250.0)
        t.record(280.0)
        assert t.is_degraded(threshold_ms=200.0) is True

    def test_not_degraded(self):
        t = LatencyTracker(window_size=3)
        t.record(5.0)
        t.record(10.0)
        t.record(8.0)
        assert t.is_degraded(threshold_ms=200.0) is False

    def test_to_dict(self):
        t = LatencyTracker(window_size=3)
        t.record(10.0)
        t.record(20.0)
        d = t.to_dict()
        assert d["avg_ms"] == 15.0
        assert d["max_ms"] == 20.0
        assert d["samples"] == 2
        assert d["degraded"] is False


class TestPingGateway:
    @mock.patch("src.connectivity.ping_host")
    def test_returns_ping_result(self, mock_ping):
        mock_ping.return_value = PingResult(ok=True, rtt_ms=1.5)
        result = ping_gateway()
        assert result.ok is True
        assert result.rtt_ms == 1.5

    @mock.patch("src.connectivity.ping_host")
    def test_returns_failed_result(self, mock_ping):
        mock_ping.return_value = PingResult(ok=False)
        result = ping_gateway()
        assert result.ok is False


class TestCheckInternet:
    @mock.patch("src.connectivity.ping_host")
    def test_returns_count_and_rtts(self, mock_ping):
        mock_ping.side_effect = [
            PingResult(ok=True, rtt_ms=5.0),
            PingResult(ok=False),
            PingResult(ok=True, rtt_ms=10.0),
        ]
        count, rtts = check_internet()
        assert count == 2
        assert rtts == (5.0, None, 10.0)

    @mock.patch("src.connectivity.ping_host", return_value=PingResult(ok=False))
    def test_all_fail(self, mock_ping):
        count, rtts = check_internet()
        assert count == 0

    @mock.patch("src.connectivity.PING_TARGETS", [])
    def test_empty_targets(self):
        count, rtts = check_internet()
        assert count == 0
        assert rtts == ()


class TestCheckConnectivity:
    @mock.patch("src.connectivity.check_internet", return_value=(3, (5.0, 10.0, 8.0)))
    @mock.patch(
        "src.connectivity.ping_gateway", return_value=PingResult(ok=True, rtt_ms=1.0)
    )
    def test_full_result(self, mock_gw, mock_inet):
        result = check_connectivity()
        assert result.gateway_ok is True
        assert result.internet_ok_count == 3
        assert result.gateway_rtt_ms == 1.0
        assert result.internet_avg_rtt_ms is not None
        assert abs(result.internet_avg_rtt_ms - 7.67) < 0.1

    @mock.patch("src.connectivity.check_internet", return_value=(0, (None, None, None)))
    @mock.patch("src.connectivity.ping_gateway", return_value=PingResult(ok=False))
    def test_all_down(self, mock_gw, mock_inet):
        result = check_connectivity()
        assert result.gateway_ok is False
        assert result.internet_ok_count == 0
        assert result.gateway_rtt_ms is None
        assert result.internet_avg_rtt_ms is None

    def test_result_is_immutable(self):
        r = ConnectivityResult(gateway_ok=True, internet_ok_count=2, internet_total=3)
        with pytest.raises(AttributeError):
            r.gateway_ok = False  # type: ignore[misc]
