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


# Seuils de classification d'usage TP-Link -- duplique volontairement
# managed_devices._classify_usage (lecture seule pour ce sprint, cf.
# INVARIANTS.md et frontieres du sprint 2 A2). A garder synchronise avec
# src/managed_devices.py si ces valeurs y changent.
_CAT4_DOWNLINK_BPS = 150_000_000
_CAT4_UPLINK_BPS = 50_000_000
_SATURATION_RATIO = 0.8
_MAX_CLIENTS = 32

_READINESS_NUMERIC = {"ok": 2, "degraded": 1, "unknown": 0}
_USAGE_NUMERIC = {"idle": 0, "in_use": 1, "saturated": 2}


def _classify_tplink_usage(rx_speed_bps, tx_speed_bps, clients_total) -> str:
    """Classifie l'usage instantane d'un equipement TP-Link depuis ses
    metriques MR110. Duplique volontairement managed_devices._classify_usage
    (lecture seule pour ce sprint) -- champs absents => "unknown", jamais un
    etat invente."""
    rx = rx_speed_bps if isinstance(rx_speed_bps, (int, float)) else None
    tx = tx_speed_bps if isinstance(tx_speed_bps, (int, float)) else None
    clients = clients_total if isinstance(clients_total, int) else None

    if rx is None and tx is None and clients is None:
        return "unknown"

    rx = rx or 0
    tx = tx or 0
    clients = clients or 0

    saturated = (
        rx >= _CAT4_DOWNLINK_BPS * _SATURATION_RATIO
        or tx >= _CAT4_UPLINK_BPS * _SATURATION_RATIO
        or clients >= _MAX_CLIENTS
    )
    if saturated:
        return "saturated"
    if rx > 0 or tx > 0 or clients > 0:
        return "in_use"
    return "idle"


def _escape_label_value(value: object) -> str:
    """Echappe une valeur de label Prometheus (backslash, guillemet, retour
    ligne) selon le format d'exposition texte."""
    text = str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_tplink_metrics(gauge) -> None:
    """Metriques labellisees par equipement TP-Link -- ajoutees a cote des
    metriques legacy sans label (C4 : jamais de label sur une metrique
    existante).

    Lecture seule sur managed_devices.py pour ce sprint (import local,
    meme convention que _configured_notification_channels_count) -- ce
    module se contente d'appeler l'API publique du registre."""
    import managed_devices

    try:
        devices = managed_devices.registry.list_devices()
    except Exception:
        # Jamais casser /metrics a cause du sous-systeme TP-Link.
        return

    for d in devices:
        device_id = d.get("id")
        if not device_id:
            continue
        device_label = d.get("label") or device_id
        labels = (
            f'device="{_escape_label_value(device_id)}",'
            f'label="{_escape_label_value(device_label)}"'
        )

        readiness = d.get("readiness")
        gauge(
            "vigil_tplink_readiness",
            "TP-Link device readiness (2=ok, 1=degraded, 0=unknown)",
            _READINESS_NUMERIC.get(readiness, 0),
            labels,
        )

        reachable = d.get("reachable")
        if reachable is not None:
            gauge(
                "vigil_tplink_reachable",
                "Whether the TP-Link device answered its last health check",
                int(bool(reachable)),
                labels,
            )

        rsrp = d.get("rsrp")
        if rsrp is not None:
            gauge("vigil_tplink_rsrp_dbm", "TP-Link RSRP in dBm", rsrp, labels)

        rsrq = d.get("rsrq")
        if rsrq is not None:
            gauge("vigil_tplink_rsrq_db", "TP-Link RSRQ in dB", rsrq, labels)

        snr = d.get("snr")
        if snr is not None:
            gauge("vigil_tplink_snr_db", "TP-Link SNR in dB", snr, labels)

        rx_speed_bps = d.get("rx_speed_bps")
        if rx_speed_bps is not None:
            gauge(
                "vigil_tplink_rx_bps",
                "TP-Link download speed in bits per second",
                rx_speed_bps,
                labels,
            )

        tx_speed_bps = d.get("tx_speed_bps")
        if tx_speed_bps is not None:
            gauge(
                "vigil_tplink_tx_bps",
                "TP-Link upload speed in bits per second",
                tx_speed_bps,
                labels,
            )

        usage = _classify_tplink_usage(
            rx_speed_bps, tx_speed_bps, d.get("clients_total")
        )
        if usage in _USAGE_NUMERIC:
            gauge(
                "vigil_tplink_usage_state",
                "TP-Link usage state (0=idle, 1=in_use, 2=saturated)",
                _USAGE_NUMERIC[usage],
                labels,
            )

        failed_hop = d.get("failed_hop")
        if reachable is False and failed_hop:
            gauge(
                "vigil_tplink_failed_hop",
                "TP-Link hop responsible for the last reachability failure"
                " (bridge/wireless/device/route)",
                1,
                labels + f',hop="{_escape_label_value(failed_hop)}"',
            )

        rtt_ms = d.get("rtt_ms")
        if rtt_ms is not None:
            gauge(
                "vigil_tplink_hop_rtt_ms",
                "RTT to the TP-Link device itself (last hop of the audit path)",
                round(rtt_ms, 2),
                labels,
            )

        quota = None
        try:
            quota = managed_devices.registry.quota_status(device_id)
        except Exception:
            quota = None
        if quota is not None:
            gauge(
                "vigil_tplink_quota_used_bytes",
                "TP-Link bytes used in the current billing cycle",
                quota.get("cycle_bytes_used"),
                labels,
            )
            gauge(
                "vigil_tplink_quota_bytes_total",
                "TP-Link billing cycle quota in bytes",
                quota.get("quota_bytes"),
                labels,
            )
            gauge(
                "vigil_tplink_quota_pct",
                "TP-Link billing cycle quota consumed, in percent",
                quota.get("pct"),
                labels,
            )
            next_reset = quota.get("next_reset")
            if next_reset:
                gauge(
                    "vigil_tplink_quota_reset_info",
                    "TP-Link next quota reset date (see next_reset label)",
                    1,
                    labels + f',next_reset="{_escape_label_value(next_reset)}"',
                )

        from_peer = bool(d.get("from_peer"))
        gauge(
            "vigil_tplink_from_peer",
            "Whether this instance's TP-Link view comes from its HA peer"
            " rather than a local poll",
            int(from_peer),
            labels,
        )
        age_seconds = d.get("age_seconds")
        if age_seconds is not None:
            gauge(
                "vigil_tplink_data_age_seconds",
                "Age in seconds of the peer-sourced TP-Link data",
                round(age_seconds, 1),
                labels,
            )


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

    # TP-Link managed devices (PRD A2 sprint 2) -- ajoutees a cote des
    # metriques legacy ci-dessus, jamais a la place (C4).
    _render_tplink_metrics(gauge)

    return "\n".join(lines) + "\n"
