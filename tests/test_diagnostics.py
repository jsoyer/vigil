"""Tests for diagnostics.py -- traceroute parsing and execution."""

from unittest import mock

import pytest

from src.diagnostics import run_traceroute, _parse_traceroute, TracerouteResult


SAMPLE_TRACEROUTE_FULL = """\
traceroute to 8.8.8.8 (8.8.8.8), 20 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.100 ms  1.050 ms
 2  10.0.0.1  5.678 ms  5.500 ms  5.400 ms
 3  172.16.0.1  10.123 ms  10.200 ms  10.100 ms
 4  8.8.8.8  15.456 ms  15.300 ms  15.200 ms
"""

SAMPLE_TRACEROUTE_BREAK = """\
traceroute to 8.8.8.8 (8.8.8.8), 20 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.100 ms  1.050 ms
 2  10.0.0.1  5.678 ms  5.500 ms  5.400 ms
 3  * * *
 4  * * *
 5  * * *
"""

SAMPLE_TRACEROUTE_NO_RESPONSE = """\
traceroute to 8.8.8.8 (8.8.8.8), 20 hops max, 60 byte packets
 1  * * *
 2  * * *
 3  * * *
"""

SAMPLE_TRACEROUTE_ISP_BREAK = """\
traceroute to 8.8.8.8 (8.8.8.8), 20 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.100 ms  1.050 ms
 2  10.0.0.1  5.678 ms  5.500 ms  5.400 ms
 3  172.16.0.1  10.123 ms  10.200 ms  10.100 ms
 4  80.10.234.56  12.345 ms  12.200 ms  12.100 ms
 5  * * *
 6  * * *
"""


class TestParseTraceroute:
    def test_full_success(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_FULL)
        assert result.reached_target is True
        assert result.total_hops == 4
        assert result.last_responsive_hop == 4
        assert "aucune coupure" in result.break_point
        assert len(result.hops) == 4
        assert result.hops[0].host == "192.168.1.1"
        assert result.hops[0].rtt_ms is not None

    def test_break_at_hop_3(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_BREAK)
        assert result.reached_target is False
        assert result.last_responsive_hop == 2
        assert "local" in result.break_point or "USG" in result.break_point

    def test_no_response_at_all(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_NO_RESPONSE)
        assert result.reached_target is False
        assert result.last_responsive_hop == 0
        assert "premier hop" in result.break_point

    def test_isp_break(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_ISP_BREAK)
        assert result.reached_target is False
        assert result.last_responsive_hop == 4
        assert "FAI" in result.break_point or "NRO" in result.break_point

    def test_summary_success(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_FULL)
        assert "OK" in result.summary()
        assert "8.8.8.8" in result.summary()

    def test_summary_break(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_BREAK)
        assert "Coupure" in result.summary()

    def test_to_dict(self):
        result = _parse_traceroute("8.8.8.8", SAMPLE_TRACEROUTE_FULL)
        d = result.to_dict()
        assert d["target"] == "8.8.8.8"
        assert d["reached_target"] is True
        assert len(d["hops"]) == 4
        assert d["hops"][0]["host"] == "192.168.1.1"


class TestRunTraceroute:
    @mock.patch("src.diagnostics.subprocess.run")
    def test_returns_result_on_success(self, mock_run):
        mock_run.return_value = mock.Mock(stdout=SAMPLE_TRACEROUTE_FULL)
        result = run_traceroute()
        assert result is not None
        assert result.reached_target is True

    @mock.patch("src.diagnostics.subprocess.run")
    def test_returns_none_on_timeout(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="traceroute", timeout=15)
        assert run_traceroute() is None

    @mock.patch("src.diagnostics.subprocess.run")
    def test_returns_none_on_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert run_traceroute() is None

    @mock.patch("src.diagnostics.subprocess.run")
    def test_uses_correct_args(self, mock_run):
        mock_run.return_value = mock.Mock(stdout=SAMPLE_TRACEROUTE_FULL)
        run_traceroute(target="1.1.1.1", max_hops=15, timeout=10)
        args = mock_run.call_args[0][0]
        assert "traceroute" in args
        assert "1.1.1.1" in args
        assert "15" in args
