"""Tests for metrics.py -- Prometheus exposition format rendering."""

import managed_devices  # noqa: F401 -- used via monkeypatch in tplink test classes

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

    def test_only_up_and_notification_channels_metrics_emitted(self):
        # Depuis le Sprint 1 du PRD Ntfy-first (S6.4), le garde-fou "aucun
        # canal configure" doit etre visible sur /metrics des le demarrage,
        # avant meme le premier cycle (state=None) -- pas seulement vigil_up.
        result = render_metrics(None)
        lines = [
            line for line in result.splitlines() if line and not line.startswith("#")
        ]
        assert len(lines) == 2
        assert "vigil_up 0" in lines
        assert any(
            line.startswith("vigil_notification_channels_configured ") for line in lines
        )


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
        metric_lines = [line for line in lines if line and not line.startswith("#")]
        for metric_line in metric_lines:
            name = metric_line.split("{")[0].split(" ")[0]
            assert f"# HELP {name}" in result, f"Missing # HELP for {name}"

    def test_every_metric_has_type_line(self):
        state = _default_state()
        result = render_metrics(state)
        lines = result.splitlines()
        metric_lines = [line for line in lines if line and not line.startswith("#")]
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


# ===================================================================
# TP-Link managed devices (PRD A2 sprint 2) -- labeled metrics added
# alongside the legacy unlabeled ones. Test helpers below.
# ===================================================================


def _fake_tplink_device(**overrides) -> dict:
    """Fake device dict as returned by managed_devices.registry.list_devices()."""
    device = {
        "id": "tp1",
        "label": "Secours 4G",
        "mode": "bridged",
        "reachable": True,
        "failed_hop": None,
        "detail": "",
        "rtt_ms": 12.3,
        "readiness": "ok",
        "readiness_reasons": [],
        "network_type": "LTE",
        "sim_status": "ready",
        "signal_bars": 4,
        "rsrp": -85,
        "rsrq": -10,
        "snr": 15,
        "isp_name": "Free Mobile",
        "wan_ip": "1.2.3.4",
        "clients_total": 2,
        "rx_speed_bps": 1_000_000,
        "tx_speed_bps": 500_000,
        "data_used_bytes": 123456,
        "checked_at": 0.0,
        "from_peer": False,
        "age_seconds": None,
    }
    device.update(overrides)
    return device


def _mock_tplink_present(monkeypatch, **device_overrides) -> dict:
    """Mock managed_devices.registry so exactly one TP-Link device is
    reported, alongside a fake configured quota for it. Used by the
    legacy-metrics regression suite to prove no cross-contamination
    between the labeled TP-Link metrics and the unlabeled legacy ones."""
    device = _fake_tplink_device(**device_overrides)
    monkeypatch.setattr(managed_devices.registry, "list_devices", lambda: [device])
    monkeypatch.setattr(
        managed_devices.registry,
        "quota_status",
        lambda device_id: (
            {
                "cycle_bytes_used": 1,
                "quota_bytes": 2,
                "pct": 50.0,
                "next_reset": "2026-09-01",
            }
            if device_id == device["id"]
            else None
        ),
    )
    return device


def _assert_metric_unlabeled(result: str, name: str) -> None:
    """Assert `name` appears as a bare (label-less) metric line, and never
    as a labeled one -- proves TP-Link labels never leak onto a legacy
    metric (C4)."""
    lines = result.splitlines()
    assert any(line.startswith(f"{name} ") for line in lines), (
        f"expected unlabeled metric line for {name!r}, none found in output"
    )
    assert not any(line.startswith(f"{name}{{") for line in lines), (
        f"found unexpected labeled line for legacy metric {name!r}"
    )


_LEGACY_METRIC_NAMES = [
    "vigil_up",
    "vigil_uptime_seconds",
    "vigil_failure_score",
    "vigil_score_threshold",
    "vigil_gateway_up",
    "vigil_internet_targets_up",
    "vigil_internet_targets_total",
    "vigil_gateway_rtt_ms",
    "vigil_internet_avg_rtt_ms",
    "vigil_latency_degraded",
    "vigil_reboots_total",
    "vigil_reboots_today",
    "vigil_surveillance_mode",
    "vigil_isp_outage",
    "vigil_ssh_failures",
    "vigil_peer_up",
    "vigil_peer_score",
    "vigil_instance_priority",
    "vigil_notification_channels_configured",
]


# ===================================================================
# C4 regression suite -- every legacy metric must stay unlabeled even
# when TP-Link devices are configured and labeled metrics are emitted
# right next to them. Referenced by INVARIANTS.md.
# ===================================================================


class TestTplinkMetricsLegacyUnlabeled:
    def test_vigil_up_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        result = render_metrics(_default_state())
        _assert_metric_unlabeled(result, "vigil_up")

    def test_vigil_uptime_seconds_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(uptime_seconds=3723.5)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_uptime_seconds")

    def test_vigil_failure_score_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(failure_score=7)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_failure_score")

    def test_vigil_score_threshold_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(threshold=15)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_score_threshold")

    def test_vigil_gateway_up_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(gateway_ok=True)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_gateway_up")

    def test_vigil_internet_targets_up_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(internet_ok_count=2, internet_total=3)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_internet_targets_up")

    def test_vigil_internet_targets_total_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(internet_ok_count=2, internet_total=3)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_internet_targets_total")

    def test_vigil_gateway_rtt_ms_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(gateway_rtt_ms=12.345)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_gateway_rtt_ms")

    def test_vigil_internet_avg_rtt_ms_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(internet_avg_rtt_ms=45.678)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_internet_avg_rtt_ms")

    def test_vigil_latency_degraded_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(latency_degraded=True)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_latency_degraded")

    def test_vigil_reboots_total_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(consecutive_reboots=3)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_reboots_total")

    def test_vigil_reboots_today_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(reboots_today=2)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_reboots_today")

    def test_vigil_surveillance_mode_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(surveillance_only=True)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_surveillance_mode")

    def test_vigil_isp_outage_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(isp_outage_detected=True)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_isp_outage")

    def test_vigil_ssh_failures_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(consecutive_ssh_failures=4)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_ssh_failures")

    def test_vigil_peer_up_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(peer_status="healthy")
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_peer_up")

    def test_vigil_peer_score_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(peer_score=5)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_peer_score")

    def test_vigil_instance_priority_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        state = _default_state(instance_priority=2)
        result = render_metrics(state)
        _assert_metric_unlabeled(result, "vigil_instance_priority")

    def test_vigil_notification_channels_configured_legacy_unlabeled(self, monkeypatch):
        _mock_tplink_present(monkeypatch)
        result = render_metrics(_default_state())
        _assert_metric_unlabeled(result, "vigil_notification_channels_configured")

    def test_all_legacy_metrics_together_legacy_unlabeled(self, monkeypatch):
        # Belt-and-suspenders global check -- complements (never replaces)
        # the per-metric assertions above.
        _mock_tplink_present(monkeypatch)
        state = _default_state(
            uptime_seconds=3723.5,
            failure_score=7,
            threshold=15,
            gateway_ok=True,
            internet_ok_count=2,
            internet_total=3,
            gateway_rtt_ms=12.345,
            internet_avg_rtt_ms=45.678,
            latency_degraded=True,
            consecutive_reboots=3,
            reboots_today=2,
            surveillance_only=True,
            isp_outage_detected=True,
            consecutive_ssh_failures=4,
            peer_status="healthy",
            peer_score=5,
            instance_priority=2,
        )
        result = render_metrics(state)
        for name in _LEGACY_METRIC_NAMES:
            _assert_metric_unlabeled(result, name)


# ===================================================================
# New TP-Link labeled metrics -- correctness
# ===================================================================


class TestTplinkMetricsLabeled:
    @staticmethod
    def _mock_devices(monkeypatch, devices, quota_map=None):
        quota_map = quota_map or {}
        monkeypatch.setattr(managed_devices.registry, "list_devices", lambda: devices)
        monkeypatch.setattr(
            managed_devices.registry,
            "quota_status",
            lambda device_id: quota_map.get(device_id),
        )

    def test_readiness_ok_and_degraded(self, monkeypatch):
        d1 = _fake_tplink_device(id="tp1", label="Secours 4G", readiness="ok")
        d2 = _fake_tplink_device(id="tp2", label="Secours Backup", readiness="degraded")
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_readiness{device="tp1",label="Secours 4G"} 2' in result
        assert 'vigil_tplink_readiness{device="tp2",label="Secours Backup"} 1' in result

    def test_readiness_unknown(self, monkeypatch):
        d = _fake_tplink_device(id="tp3", label="X", readiness="unknown")
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_readiness{device="tp3",label="X"} 0' in result

    def test_readiness_unrecognized_value_defaults_to_zero(self, monkeypatch):
        d = _fake_tplink_device(id="tp4", label="Y", readiness="bogus")
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_readiness{device="tp4",label="Y"} 0' in result

    def test_reachable_values(self, monkeypatch):
        d1 = _fake_tplink_device(id="tp1", label="A", reachable=True)
        d2 = _fake_tplink_device(id="tp2", label="B", reachable=False)
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_reachable{device="tp1",label="A"} 1' in result
        assert 'vigil_tplink_reachable{device="tp2",label="B"} 0' in result

    def test_signal_fields_present_when_set(self, monkeypatch):
        d = _fake_tplink_device(id="tp1", label="A", rsrp=-85, rsrq=-10, snr=15)
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_rsrp_dbm{device="tp1",label="A"} -85' in result
        assert 'vigil_tplink_rsrq_db{device="tp1",label="A"} -10' in result
        assert 'vigil_tplink_snr_db{device="tp1",label="A"} 15' in result

    def test_signal_fields_absent_when_none(self, monkeypatch):
        d = _fake_tplink_device(id="tp1", label="A", rsrp=None, rsrq=None, snr=None)
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert "vigil_tplink_rsrp_dbm" not in result
        assert "vigil_tplink_rsrq_db" not in result
        assert "vigil_tplink_snr_db" not in result

    def test_rx_tx_bps_present_and_absent(self, monkeypatch):
        d1 = _fake_tplink_device(
            id="tp1", label="A", rx_speed_bps=1_000_000, tx_speed_bps=500_000
        )
        d2 = _fake_tplink_device(
            id="tp2", label="B", rx_speed_bps=None, tx_speed_bps=None
        )
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_rx_bps{device="tp1",label="A"} 1000000' in result
        assert 'vigil_tplink_tx_bps{device="tp1",label="A"} 500000' in result
        for line in result.splitlines():
            if line.startswith("vigil_tplink_rx_bps{") or line.startswith(
                "vigil_tplink_tx_bps{"
            ):
                assert 'device="tp2"' not in line

    def test_usage_state_idle(self, monkeypatch):
        d = _fake_tplink_device(
            id="tp1", label="A", rx_speed_bps=0, tx_speed_bps=0, clients_total=0
        )
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_usage_state{device="tp1",label="A"} 0' in result

    def test_usage_state_in_use(self, monkeypatch):
        # rx_speed_bps must clear USAGE_TRAFFIC_FLOOR_BPS (100_000, bugfix
        # 2.3.1) to be real in_use traffic, not just management noise.
        d = _fake_tplink_device(
            id="tp1", label="A", rx_speed_bps=150_000, tx_speed_bps=0, clients_total=0
        )
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_usage_state{device="tp1",label="A"} 1' in result

    def test_usage_state_saturated(self, monkeypatch):
        d = _fake_tplink_device(
            id="tp1", label="A", rx_speed_bps=0, tx_speed_bps=0, clients_total=32
        )
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_usage_state{device="tp1",label="A"} 2' in result

    def test_usage_state_absent_when_all_fields_none(self, monkeypatch):
        d = _fake_tplink_device(
            id="tp1",
            label="A",
            rx_speed_bps=None,
            tx_speed_bps=None,
            clients_total=None,
        )
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert "vigil_tplink_usage_state" not in result

    def test_usage_state_idle_below_traffic_floor_with_clients(self, monkeypatch):
        """Bugfix 2.3.1 -- le guardian est lui-meme client WiFi permanent du
        MR110 (trafic de gestion residuel, quelques clients associes en
        permanence). Sous USAGE_TRAFFIC_FLOOR_BPS, meme avec des clients
        connectes, l'etat doit rester idle (jamais in_use a cause du seul
        bruit de gestion)."""
        d = _fake_tplink_device(
            id="tp1", label="A", rx_speed_bps=39, tx_speed_bps=144, clients_total=3
        )
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_usage_state{device="tp1",label="A"} 0' in result

    def test_on_backup_gauge_when_present(self, monkeypatch):
        d1 = _fake_tplink_device(id="tp1", label="A", on_backup=True)
        d2 = _fake_tplink_device(id="tp2", label="B", on_backup=False)
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_on_backup{device="tp1",label="A"} 1' in result
        assert 'vigil_tplink_on_backup{device="tp2",label="B"} 0' in result

    def test_usage_state_prefers_registry_over_instant_speeds(self, monkeypatch):
        """Un pic instantane ne doit pas ecraser l'etat confirme idle."""
        d = _fake_tplink_device(
            id="tp1",
            label="A",
            rx_speed_bps=5_000_000,
            tx_speed_bps=0,
            clients_total=2,
            usage_state="idle",
        )
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_usage_state{device="tp1",label="A"} 0' in result

    def test_failed_hop_only_for_unreachable_device(self, monkeypatch):
        d1 = _fake_tplink_device(id="tp1", label="A", reachable=True, failed_hop=None)
        d2 = _fake_tplink_device(
            id="tp2", label="B", reachable=False, failed_hop="wireless"
        )
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        assert (
            'vigil_tplink_failed_hop{device="tp2",label="B",hop="wireless"} 1' in result
        )
        for line in result.splitlines():
            if line.startswith("vigil_tplink_failed_hop{"):
                assert 'device="tp1"' not in line

    def test_hop_rtt_ms_rounded(self, monkeypatch):
        d = _fake_tplink_device(id="tp1", label="A", rtt_ms=12.345)
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_hop_rtt_ms{device="tp1",label="A"} 12.35' in result

    def test_hop_rtt_ms_absent_when_none(self, monkeypatch):
        d = _fake_tplink_device(id="tp1", label="A", rtt_ms=None)
        self._mock_devices(monkeypatch, [d])
        result = render_metrics(_default_state())
        assert "vigil_tplink_hop_rtt_ms" not in result

    def test_quota_metrics_present_when_configured(self, monkeypatch):
        d = _fake_tplink_device(id="tp1", label="A")
        self._mock_devices(
            monkeypatch,
            [d],
            quota_map={
                "tp1": {
                    "cycle_bytes_used": 500_000_000,
                    "quota_bytes": 2_000_000_000,
                    "pct": 25.0,
                    "next_reset": "2026-09-01",
                }
            },
        )
        result = render_metrics(_default_state())
        assert (
            'vigil_tplink_quota_used_bytes{device="tp1",label="A"} 500000000' in result
        )
        assert (
            'vigil_tplink_quota_bytes_total{device="tp1",label="A"} 2000000000'
            in result
        )
        assert 'vigil_tplink_quota_pct{device="tp1",label="A"} 25.0' in result
        assert (
            'vigil_tplink_quota_reset_info{device="tp1",label="A",'
            'next_reset="2026-09-01"} 1' in result
        )

    def test_quota_metrics_absent_when_not_configured(self, monkeypatch):
        d = _fake_tplink_device(id="tp1", label="A")
        self._mock_devices(monkeypatch, [d], quota_map={})
        result = render_metrics(_default_state())
        for name in (
            "vigil_tplink_quota_used_bytes",
            "vigil_tplink_quota_bytes_total",
            "vigil_tplink_quota_pct",
            "vigil_tplink_quota_reset_info",
        ):
            assert name not in result

    def test_from_peer_values(self, monkeypatch):
        d1 = _fake_tplink_device(id="tp1", label="A", from_peer=False)
        d2 = _fake_tplink_device(id="tp2", label="B", from_peer=True)
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        assert 'vigil_tplink_from_peer{device="tp1",label="A"} 0' in result
        assert 'vigil_tplink_from_peer{device="tp2",label="B"} 1' in result

    def test_data_age_seconds_only_when_set(self, monkeypatch):
        d1 = _fake_tplink_device(id="tp1", label="A", age_seconds=None)
        d2 = _fake_tplink_device(id="tp2", label="B", age_seconds=42.34)
        self._mock_devices(monkeypatch, [d1, d2])
        result = render_metrics(_default_state())
        for line in result.splitlines():
            if line.startswith("vigil_tplink_data_age_seconds{"):
                assert 'device="tp1"' not in line
        assert 'vigil_tplink_data_age_seconds{device="tp2",label="B"} 42.3' in result

    def test_every_tplink_metric_has_help_and_type_lines(self, monkeypatch):
        d = _fake_tplink_device(
            id="tp1", label="A", reachable=False, failed_hop="wireless"
        )
        self._mock_devices(
            monkeypatch,
            [d],
            quota_map={
                "tp1": {
                    "cycle_bytes_used": 1,
                    "quota_bytes": 2,
                    "pct": 50.0,
                    "next_reset": "2026-09-01",
                }
            },
        )
        result = render_metrics(_default_state())
        lines = result.splitlines()
        metric_lines = [
            line
            for line in lines
            if line
            and not line.startswith("#")
            and line.split("{")[0].split(" ")[0].startswith("vigil_tplink_")
        ]
        assert metric_lines, "expected at least one vigil_tplink_* metric line"
        for metric_line in metric_lines:
            name = metric_line.split("{")[0].split(" ")[0]
            assert f"# HELP {name}" in result, f"Missing # HELP for {name}"
            assert f"# TYPE {name} gauge" in result, f"Missing # TYPE gauge for {name}"


# ===================================================================
# TP-Link metrics -- absent when no devices configured / state is None
# ===================================================================


class TestTplinkMetricsEmptyOrAbsent:
    def test_no_tplink_lines_when_no_devices(self, monkeypatch):
        monkeypatch.setattr(managed_devices.registry, "list_devices", lambda: [])
        result = render_metrics(_default_state())
        assert not any(line.startswith("vigil_tplink_") for line in result.splitlines())

    def test_none_state_skips_tplink_metrics_entirely(self, monkeypatch):
        device = _fake_tplink_device(id="tp1", label="A")
        monkeypatch.setattr(managed_devices.registry, "list_devices", lambda: [device])
        monkeypatch.setattr(
            managed_devices.registry, "quota_status", lambda device_id: None
        )
        result = render_metrics(None)
        assert not any(line.startswith("vigil_tplink_") for line in result.splitlines())
        lines = [
            line for line in result.splitlines() if line and not line.startswith("#")
        ]
        assert len(lines) == 2
