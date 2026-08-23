"""Tests for metrics.py -- Prometheus exposition format rendering."""

import pytest

from src.metrics import render_metrics
from src.state import WatchdogState


# ===================================================================
# None state
# ===================================================================


class TestRenderMetricsNoneState:
    def test_returns_string(self):
        result = render_metrics(None)
        assert isinstance(result, str)

    def test_ends_with_newline(self):
        result = render_metrics(None)
        assert result.endswith("\n")

    def test_watchdog_up_is_zero(self):
        result = render_metrics(None)
        assert "vigil_up 0" in result

    def test_contains_help_line(self):
        result = render_metrics(None)
        assert "# HELP vigil_up" in result

    def test_contains_type_line(self):
        result = render_metrics(None)
        assert "# TYPE vigil_up gauge" in result

    def test_only_up_metric_emitted(self):
        result = render_metrics(None)
        lines = [l for l in result.splitlines() if l and not l.startswith("#")]
        assert len(lines) == 1
        assert lines[0] == "vigil_up 0"


# ===================================================================
# Full state -- structural checks
# ===================================================================


def _default_state(**kwargs) -> WatchdogState:
    return WatchdogState(**kwargs)


class TestRenderMetricsFullState:
    def test_returns_string(self):
        state = _default_state()
        assert isinstance(render_metrics(state), str)

    def test_ends_with_newline(self):
        state = _default_state()
        assert render_metrics(state).endswith("\n")

    def test_watchdog_up_is_one(self):
        state = _default_state()
        result = render_metrics(state)
        assert "vigil_up 1" in result

    def test_every_metric_has_help_line(self):
        state = _default_state()
        result = render_metrics(state)
        lines = result.splitlines()
        metric_lines = [l for l in lines if l and not l.startswith("#")]
        for metric_line in metric_lines:
            name = metric_line.split("{")[0].split(" ")[0]
            assert f"# HELP {name}" in result, f"Missing # HELP for {name}"

    def test_every_metric_has_type_line(self):
        state = _default_state()
        result = render_metrics(state)
        lines = result.splitlines()
        metric_lines = [l for l in lines if l and not l.startswith("#")]
        for metric_line in metric_lines:
            name = metric_line.split("{")[0].split(" ")[0]
            assert f"# TYPE {name}" in result, f"Missing # TYPE for {name}"

    def test_failure_score_emitted(self):
        state = _default_state(failure_score=7)
        result = render_metrics(state)
        assert "vigil_failure_score 7" in result

    def test_score_threshold_emitted(self):
        state = _default_state(threshold=15)
        result = render_metrics(state)
        assert "vigil_score_threshold 15" in result

    def test_gateway_up_true(self):
        state = _default_state(gateway_ok=True)
        result = render_metrics(state)
        assert "vigil_gateway_up 1" in result

    def test_gateway_up_false(self):
        state = _default_state(gateway_ok=False)
        result = render_metrics(state)
        assert "vigil_gateway_up 0" in result

    def test_internet_targets_up_count(self):
        state = _default_state(internet_ok_count=2, internet_total=3)
        result = render_metrics(state)
        assert "vigil_internet_targets_up 2" in result
        assert "vigil_internet_targets_total 3" in result

    def test_reboots_total_is_counter_type(self):
        state = _default_state(consecutive_reboots=3)
        result = render_metrics(state)
        assert "# TYPE vigil_reboots_total counter" in result
        assert "vigil_reboots_total 3" in result

    def test_reboots_today_emitted(self):
        state = _default_state(reboots_today=2)
        result = render_metrics(state)
        assert "vigil_reboots_today 2" in result

    def test_surveillance_mode_true(self):
        state = _default_state(surveillance_only=True)
        result = render_metrics(state)
        assert "vigil_surveillance_mode 1" in result

    def test_surveillance_mode_false(self):
        state = _default_state(surveillance_only=False)
        result = render_metrics(state)
        assert "vigil_surveillance_mode 0" in result

    def test_isp_outage_detected_true(self):
        state = _default_state(isp_outage_detected=True)
        result = render_metrics(state)
        assert "vigil_isp_outage 1" in result

    def test_isp_outage_detected_false(self):
        state = _default_state(isp_outage_detected=False)
        result = render_metrics(state)
        assert "vigil_isp_outage 0" in result

    def test_ssh_failures_emitted(self):
        state = _default_state(consecutive_ssh_failures=4)
        result = render_metrics(state)
        assert "vigil_ssh_failures 4" in result

    def test_instance_priority_emitted(self):
        state = _default_state(instance_priority=2)
        result = render_metrics(state)
        assert "vigil_instance_priority 2" in result

    def test_uptime_seconds_emitted(self):
        state = _default_state(uptime_seconds=3723.5)
        result = render_metrics(state)
        assert "vigil_uptime_seconds 3723" in result

    def test_latency_degraded_true(self):
        state = _default_state(latency_degraded=True)
        result = render_metrics(state)
        assert "vigil_latency_degraded 1" in result

    def test_latency_degraded_false(self):
        state = _default_state(latency_degraded=False)
        result = render_metrics(state)
        assert "vigil_latency_degraded 0" in result


# ===================================================================
# Latency RTT fields (optional -- only emitted when not None)
# ===================================================================


class TestRenderMetricsLatency:
    def test_gateway_rtt_emitted_when_set(self):
        state = _default_state(gateway_rtt_ms=12.345)
        result = render_metrics(state)
        assert "vigil_gateway_rtt_ms 12.35" in result

    def test_gateway_rtt_not_emitted_when_none(self):
        state = _default_state(gateway_rtt_ms=None)
        result = render_metrics(state)
        assert "vigil_gateway_rtt_ms" not in result

    def test_internet_avg_rtt_emitted_when_set(self):
        state = _default_state(internet_avg_rtt_ms=45.678)
        result = render_metrics(state)
        assert "vigil_internet_avg_rtt_ms 45.68" in result

    def test_internet_avg_rtt_not_emitted_when_none(self):
        state = _default_state(internet_avg_rtt_ms=None)
        result = render_metrics(state)
        assert "vigil_internet_avg_rtt_ms" not in result

    def test_rtt_rounded_to_two_decimal_places(self):
        state = _default_state(gateway_rtt_ms=1.0)
        result = render_metrics(state)
        assert "vigil_gateway_rtt_ms 1.0" in result


# ===================================================================
# Peer metrics
# ===================================================================


class TestRenderMetricsPeer:
    def test_peer_up_when_healthy(self):
        state = _default_state(peer_status="healthy")
        result = render_metrics(state)
        assert "vigil_peer_up 1" in result

    def test_peer_up_when_degraded(self):
        state = _default_state(peer_status="degraded")
        result = render_metrics(state)
        assert "vigil_peer_up 1" in result

    def test_peer_up_when_critical(self):
        state = _default_state(peer_status="critical")
        result = render_metrics(state)
        assert "vigil_peer_up 1" in result

    def test_peer_down_when_unreachable(self):
        state = _default_state(peer_status="unreachable")
        result = render_metrics(state)
        assert "vigil_peer_up 0" in result

    def test_peer_down_when_unknown(self):
        state = _default_state(peer_status="unknown")
        result = render_metrics(state)
        assert "vigil_peer_up 0" in result

    def test_peer_score_emitted(self):
        state = _default_state(peer_score=5)
        result = render_metrics(state)
        assert "vigil_peer_score 5" in result


# ===================================================================
# Prometheus format compliance
# ===================================================================


class TestPrometheusFormatCompliance:
    def test_help_lines_before_type_lines(self):
        state = _default_state()
        result = render_metrics(state)
        lines = result.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("# TYPE "):
                assert i > 0
                assert lines[i - 1].startswith("# HELP "), (
                    f"# TYPE line at {i} not preceded by # HELP: {lines[i - 1]!r}"
                )

    def test_metric_line_after_type_line(self):
        state = _default_state()
        result = render_metrics(state)
        lines = result.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("# TYPE "):
                assert i + 1 < len(lines)
                assert not lines[i + 1].startswith("#"), (
                    f"Metric value not immediately after # TYPE at {i}"
                )

    def test_no_empty_lines_in_output(self):
        state = _default_state()
        result = render_metrics(state)
        lines = result.rstrip("\n").splitlines()
        for line in lines:
            assert line != "", "Unexpected empty line in metrics output"
