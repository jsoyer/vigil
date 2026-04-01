"""Tests for src/snmp_monitor.py"""

import subprocess
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# _snmpget
# ---------------------------------------------------------------------------

def _make_proc(returncode: int, stdout: str, stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestSnmpget:
    def test_returns_value_on_success(self):
        # split(":", 1)[1].strip() on "SNMPv2-MIB::sysUpTime.0 = Timeticks: 12345600"
        # gives ":sysUpTime.0 = Timeticks: 12345600" (first colon is the :: separator)
        proc = _make_proc(0, "SNMPv2-MIB::sysUpTime.0 = Timeticks: 12345600")
        with patch("subprocess.run", return_value=proc):
            from snmp_monitor import _snmpget
            result = _snmpget("1.3.6.1.2.1.1.3.0")
            assert result is not None
            assert "12345600" in result

    def test_returns_none_on_nonzero_returncode(self):
        proc = _make_proc(1, "", "timeout")
        with patch("subprocess.run", return_value=proc):
            from snmp_monitor import _snmpget
            assert _snmpget("1.3.6.1.2.1.1.3.0") is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="snmpget", timeout=5)):
            from snmp_monitor import _snmpget
            assert _snmpget("1.3.6.1.2.1.1.3.0") is None

    def test_returns_none_when_snmpget_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("snmpget not found")):
            from snmp_monitor import _snmpget
            assert _snmpget("1.3.6.1.2.1.1.3.0") is None

    def test_returns_none_when_output_has_no_colon(self):
        proc = _make_proc(0, "some output without colon")
        with patch("subprocess.run", return_value=proc):
            from snmp_monitor import _snmpget
            assert _snmpget("1.3.6.1.2.1.1.3.0") is None

    def test_returns_none_on_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            from snmp_monitor import _snmpget
            assert _snmpget("1.3.6.1.2.1.1.3.0") is None

    def test_passes_correct_arguments(self):
        proc = _make_proc(0, "OID = INTEGER: 42")
        with patch("subprocess.run", return_value=proc) as mock_run:
            from snmp_monitor import _snmpget
            _snmpget("1.2.3.4", host="10.0.0.1", community="mycomm", timeout=3)
            cmd = mock_run.call_args[0][0]
            assert "snmpget" in cmd
            assert "10.0.0.1" in cmd
            assert "mycomm" in cmd
            assert "1.2.3.4" in cmd

    def test_strips_value_whitespace(self):
        proc = _make_proc(0, "OID = INTEGER:   42   ")
        with patch("subprocess.run", return_value=proc):
            from snmp_monitor import _snmpget
            result = _snmpget("1.2.3.4")
            assert result == "42"


# ---------------------------------------------------------------------------
# _parse_int
# ---------------------------------------------------------------------------

class TestParseInt:
    def test_simple_integer_string(self):
        from snmp_monitor import _parse_int
        assert _parse_int("42") == 42

    def test_integer_with_units(self):
        from snmp_monitor import _parse_int
        assert _parse_int("256 kBytes") == 256

    def test_none_input(self):
        from snmp_monitor import _parse_int
        assert _parse_int(None) is None

    def test_non_numeric_string(self):
        from snmp_monitor import _parse_int
        assert _parse_int("not a number") is None

    def test_empty_string(self):
        from snmp_monitor import _parse_int
        assert _parse_int("") is None

    def test_negative_value(self):
        from snmp_monitor import _parse_int
        assert _parse_int("-5") == -5

    def test_timeticks_format(self):
        from snmp_monitor import _parse_int
        # "Timeticks: (12345600) 1:25:56.00" -- first token after split
        # _parse_int is called on already-split value by caller
        assert _parse_int("12345600") == 12345600


# ---------------------------------------------------------------------------
# read_usg_metrics
# ---------------------------------------------------------------------------

class TestReadUsgMetrics:
    def test_unreachable_when_uptime_fails(self):
        with patch("snmp_monitor._snmpget", return_value=None):
            from snmp_monitor import read_usg_metrics
            metrics = read_usg_metrics()
            assert metrics.reachable is False
            assert metrics.cpu_percent is None
            assert metrics.memory_percent is None

    def test_reachable_with_all_metrics(self):
        snmp_responses = {
            "1.3.6.1.2.1.1.3.0": "100000",       # uptime ticks = 1000s
            "1.3.6.1.4.1.2021.11.9.0": "35",       # cpu
            "1.3.6.1.4.1.2021.4.5.0": "512000",    # mem total
            "1.3.6.1.4.1.2021.4.6.0": "256000",    # mem avail
        }

        def mock_snmpget(oid, *args, **kwargs):
            return snmp_responses.get(oid)

        with patch("snmp_monitor._snmpget", side_effect=mock_snmpget):
            from snmp_monitor import read_usg_metrics
            metrics = read_usg_metrics()
            assert metrics.reachable is True
            assert metrics.uptime_seconds == 1000
            assert metrics.cpu_percent == 35.0
            assert metrics.memory_percent == 50.0

    def test_cpu_none_when_cpu_snmp_fails(self):
        snmp_responses = {
            "1.3.6.1.2.1.1.3.0": "100000",
            "1.3.6.1.4.1.2021.11.9.0": None,
            "1.3.6.1.4.1.2021.4.5.0": "512000",
            "1.3.6.1.4.1.2021.4.6.0": "256000",
        }

        def mock_snmpget(oid, *args, **kwargs):
            return snmp_responses.get(oid)

        with patch("snmp_monitor._snmpget", side_effect=mock_snmpget):
            from snmp_monitor import read_usg_metrics
            metrics = read_usg_metrics()
            assert metrics.cpu_percent is None
            assert metrics.reachable is True

    def test_memory_none_when_mem_snmp_fails(self):
        snmp_responses = {
            "1.3.6.1.2.1.1.3.0": "100000",
            "1.3.6.1.4.1.2021.11.9.0": "25",
            "1.3.6.1.4.1.2021.4.5.0": None,
            "1.3.6.1.4.1.2021.4.6.0": None,
        }

        def mock_snmpget(oid, *args, **kwargs):
            return snmp_responses.get(oid)

        with patch("snmp_monitor._snmpget", side_effect=mock_snmpget):
            from snmp_monitor import read_usg_metrics
            metrics = read_usg_metrics()
            assert metrics.memory_percent is None
            assert metrics.reachable is True

    def test_memory_percent_calculation(self):
        snmp_responses = {
            "1.3.6.1.2.1.1.3.0": "36000",          # 360 seconds
            "1.3.6.1.4.1.2021.11.9.0": "10",
            "1.3.6.1.4.1.2021.4.5.0": "1000000",    # 1000000 kB total
            "1.3.6.1.4.1.2021.4.6.0": "250000",     # 250000 kB avail = 75% used
        }

        def mock_snmpget(oid, *args, **kwargs):
            return snmp_responses.get(oid)

        with patch("snmp_monitor._snmpget", side_effect=mock_snmpget):
            from snmp_monitor import read_usg_metrics
            metrics = read_usg_metrics()
            assert metrics.memory_percent == 75.0

    def test_uptime_ticks_conversion(self):
        snmp_responses = {
            "1.3.6.1.2.1.1.3.0": "360000",     # 3600s = 1 hour
            "1.3.6.1.4.1.2021.11.9.0": None,
            "1.3.6.1.4.1.2021.4.5.0": None,
            "1.3.6.1.4.1.2021.4.6.0": None,
        }

        def mock_snmpget(oid, *args, **kwargs):
            return snmp_responses.get(oid)

        with patch("snmp_monitor._snmpget", side_effect=mock_snmpget):
            from snmp_monitor import read_usg_metrics
            metrics = read_usg_metrics()
            assert metrics.uptime_seconds == 3600


# ---------------------------------------------------------------------------
# UsgMetrics.is_stressed
# ---------------------------------------------------------------------------

class TestIsStressed:
    def test_not_stressed_normal_values(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=50.0, memory_percent=60.0, reachable=True)
        assert m.is_stressed() is False

    def test_stressed_high_cpu(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=95.0, memory_percent=50.0, reachable=True)
        assert m.is_stressed() is True

    def test_stressed_high_memory(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=50.0, memory_percent=95.0, reachable=True)
        assert m.is_stressed() is True

    def test_not_stressed_when_both_none(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=None, memory_percent=None, reachable=False)
        assert m.is_stressed() is False

    def test_stressed_exactly_at_threshold(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=90.0, memory_percent=90.0, reachable=True)
        # threshold is > 90.0, so exactly 90 is NOT stressed
        assert m.is_stressed() is False

    def test_stressed_custom_threshold(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=80.0, memory_percent=50.0, reachable=True)
        assert m.is_stressed(cpu_threshold=70.0) is True

    def test_to_dict_all_fields(self):
        from snmp_monitor import UsgMetrics
        m = UsgMetrics(cpu_percent=30.0, memory_percent=50.0, uptime_seconds=3600, reachable=True)
        d = m.to_dict()
        assert d["cpu_percent"] == 30.0
        assert d["memory_percent"] == 50.0
        assert d["uptime_seconds"] == 3600
        assert d["reachable"] is True
