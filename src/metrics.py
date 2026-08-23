"""Prometheus metrics -- exposition format for /metrics endpoint."""

from state import WatchdogState


def _configured_notification_channels_count() -> int:
    """Nombre de canaux de notification effectivement configures.

    Duplique volontairement notifier._dispatch (read-only pour ce sprint) --
    petite fonction pure, coherente avec http_server._configured_notification_channels.
    """
    from notifier import _ntfy, _email
    import mqtt_publisher

    count = 0
    if _ntfy.is_configured():
        count += 1
    if _email.is_configured():
        count += 1
    if mqtt_publisher.is_configured():
        count += 1
    return count


def render_metrics(state: WatchdogState | None) -> str:
    """Render Prometheus exposition format text from WatchdogState.

    See: https://prometheus.io/docs/instrumenting/exposition_formats/
    """
    lines: list[str] = []

    def gauge(name: str, help_text: str, value: object, labels: str = "") -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        label_str = f"{{{labels}}}" if labels else ""
        lines.append(f"{name}{label_str} {value}")

    def counter(name: str, help_text: str, value: object) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")

    if state is None:
        gauge("vigil_up", "Whether the watchdog is running", 0)
        gauge(
            "vigil_notification_channels_configured",
            "Number of configured notification channels (ntfy/email/mqtt)",
            _configured_notification_channels_count(),
        )
        return "\n".join(lines) + "\n"

    # Watchdog status
    gauge("vigil_up", "Whether the watchdog is running", 1)
    gauge(
        "vigil_uptime_seconds",
        "Watchdog uptime in seconds",
        int(state.uptime_seconds),
    )

    # Scoring
    gauge("vigil_failure_score", "Current failure score", state.failure_score)
    gauge("vigil_score_threshold", "Score threshold for reboot", state.threshold)

    # Connectivity
    gauge(
        "vigil_gateway_up",
        "Whether the gateway responds to ping",
        int(state.gateway_ok),
    )
    gauge(
        "vigil_internet_targets_up",
        "Number of internet targets responding",
        state.internet_ok_count,
    )
    gauge(
        "vigil_internet_targets_total",
        "Total number of internet targets",
        state.internet_total,
    )

    # Latency
    if state.gateway_rtt_ms is not None:
        gauge(
            "vigil_gateway_rtt_ms",
            "Gateway ping RTT in milliseconds",
            round(state.gateway_rtt_ms, 2),
        )
    if state.internet_avg_rtt_ms is not None:
        gauge(
            "vigil_internet_avg_rtt_ms",
            "Average internet ping RTT in milliseconds",
            round(state.internet_avg_rtt_ms, 2),
        )
    gauge(
        "vigil_latency_degraded",
        "Whether latency is above degradation threshold",
        int(state.latency_degraded),
    )

    # Reboots
    counter(
        "vigil_reboots_total",
        "Total consecutive reboots without recovery",
        state.consecutive_reboots,
    )
    gauge("vigil_reboots_today", "Number of reboots today", state.reboots_today)
    gauge(
        "vigil_surveillance_mode",
        "Whether surveillance-only mode is active",
        int(state.surveillance_only),
    )

    # ISP
    gauge(
        "vigil_isp_outage",
        "Whether an ISP outage is detected",
        int(state.isp_outage_detected),
    )

    # SSH
    gauge(
        "vigil_ssh_failures",
        "Consecutive SSH failures",
        state.consecutive_ssh_failures,
    )

    # Peer
    peer_up = 1 if state.peer_status in ("healthy", "degraded", "critical") else 0
    gauge("vigil_peer_up", "Whether the peer instance is reachable", peer_up)
    gauge("vigil_peer_score", "Peer failure score", state.peer_score)

    # Instance info
    gauge(
        "vigil_instance_priority",
        "Instance priority (1=primary)",
        state.instance_priority,
    )

    # Notification channels (PRD Ntfy-first S6.4)
    gauge(
        "vigil_notification_channels_configured",
        "Number of configured notification channels (ntfy/email/mqtt)",
        _configured_notification_channels_count(),
    )

    return "\n".join(lines) + "\n"
