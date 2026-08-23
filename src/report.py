"""Daily report -- generate summary stats from event history."""

import logging
from datetime import datetime, date

from events import EventLog, REBOOT, REBOOT_FAILED, RECOVERY, ISP_OUTAGE


def generate_daily_report(
    event_log: EventLog,
    report_date: date | None = None,
    uptime_seconds: float = 0.0,
    current_score: int = 0,
    peer_status: str = "unknown",
) -> dict:
    """Generate a daily summary report.

    Returns a dict with all report fields, suitable for JSON and notification.
    """
    if report_date is None:
        report_date = datetime.now().date()

    date_str = report_date.isoformat()
    all_events = event_log.get_all()

    # Filter events for the report date
    day_events = [e for e in all_events if e["ts"].startswith(date_str)]

    # Count by type
    reboots = [e for e in day_events if e["type"] == REBOOT]
    reboot_failures = [e for e in day_events if e["type"] == REBOOT_FAILED]
    recoveries = [e for e in day_events if e["type"] == RECOVERY]
    isp_outages = [e for e in day_events if e["type"] == ISP_OUTAGE]

    reboot_count = len(reboots)
    reboot_failed_count = len(reboot_failures)
    recovery_count = len(recoveries)
    isp_outage_count = len(isp_outages)

    # Reboot helped ratio
    helped_count = sum(1 for r in recoveries if r.get("data", {}).get("helped") is True)

    # Outage durations from recovery events
    outage_durations: list[str] = []
    for r in recoveries:
        dur = r.get("data", {}).get("duration")
        if dur:
            outage_durations.append(str(dur))

    total_outage_str = ", ".join(outage_durations) if outage_durations else "aucune"

    # Uptime estimate (rough: based on watchdog uptime minus outage time)
    # This is approximate since we don't track exact downtime seconds in events
    uptime_hours = uptime_seconds / 3600 if uptime_seconds > 0 else 24.0
    if uptime_hours > 0 and recovery_count > 0:
        # Rough estimate: each outage is ~5 min average if no data
        estimated_downtime_h = recovery_count * 0.1  # 6 min per outage
        uptime_pct = max(
            0, min(100, ((uptime_hours - estimated_downtime_h) / uptime_hours) * 100)
        )
    else:
        uptime_pct = 100.0 if recovery_count == 0 else 99.0

    report = {
        "date": date_str,
        "uptime_pct": round(uptime_pct, 1),
        "outage_count": recovery_count,
        "outage_durations": total_outage_str,
        "reboot_count": reboot_count,
        "reboot_failed_count": reboot_failed_count,
        "reboot_helped": helped_count,
        "isp_outage_count": isp_outage_count,
        "event_count": len(day_events),
        "current_score": current_score,
        "peer_status": peer_status,
    }

    return report


def format_report_notification(report: dict) -> str:
    """Format a report dict as a human-readable notification message."""
    lines = [
        f"Rapport Vigil -- {report['date']}",
        f"  Uptime internet : ~{report['uptime_pct']}%",
        f"  Coupures : {report['outage_count']} ({report['outage_durations']})",
        f"  Reboots : {report['reboot_count']}",
    ]

    if report["reboot_count"] > 0:
        lines.append(
            f"  Reboots utiles : {report['reboot_helped']}/{report['reboot_count']}"
        )

    if report["reboot_failed_count"] > 0:
        lines.append(f"  Reboots echoues : {report['reboot_failed_count']}")

    if report["isp_outage_count"] > 0:
        lines.append(f"  Pannes ISP detectees : {report['isp_outage_count']}")

    if report["peer_status"] not in ("unknown", "standalone"):
        lines.append(f"  Peer : {report['peer_status']}")

    return "\n".join(lines)


def generate_weekly_report(
    event_log: EventLog,
    uptime_seconds: float = 0.0,
    current_score: int = 0,
    peer_status: str = "unknown",
) -> dict:
    """Generate a weekly summary from the last 7 days of events."""
    from datetime import timedelta

    today = datetime.now().date()
    all_events = event_log.get_all()

    week_start = today - timedelta(days=7)
    prev_week_start = today - timedelta(days=14)

    week_events = [
        e
        for e in all_events
        if e["ts"][:10] >= week_start.isoformat() and e["ts"][:10] < today.isoformat()
    ]
    prev_events = [
        e
        for e in all_events
        if e["ts"][:10] >= prev_week_start.isoformat()
        and e["ts"][:10] < week_start.isoformat()
    ]

    def count_type(events: list[dict], t: str) -> int:
        return sum(1 for e in events if e["type"] == t)

    reboot_count = count_type(week_events, REBOOT)
    prev_reboot_count = count_type(prev_events, REBOOT)
    outage_count = count_type(week_events, RECOVERY)
    prev_outage_count = count_type(prev_events, RECOVERY)
    isp_count = count_type(week_events, ISP_OUTAGE)

    def trend(current: int, previous: int) -> str:
        if previous == 0 and current == 0:
            return "stable"
        if previous == 0:
            return f"+{current}"
        delta = current - previous
        if delta > 0:
            return f"+{delta} vs semaine precedente"
        if delta < 0:
            return f"{delta} vs semaine precedente"
        return "stable"

    return {
        "period": f"{week_start.isoformat()} -> {today.isoformat()}",
        "outage_count": outage_count,
        "outage_trend": trend(outage_count, prev_outage_count),
        "reboot_count": reboot_count,
        "reboot_trend": trend(reboot_count, prev_reboot_count),
        "isp_outage_count": isp_count,
        "event_count": len(week_events),
        "current_score": current_score,
        "peer_status": peer_status,
    }


def calculate_monthly_sla(event_log: EventLog) -> dict:
    """Calculate monthly uptime SLA from event history.

    Returns dict with uptime_pct, downtime_minutes, month.
    """
    from datetime import timedelta

    today = datetime.now().date()
    month_start = today.replace(day=1)
    month_str = today.strftime("%Y-%m")

    all_events = event_log.get_all()
    month_events = [e for e in all_events if e["ts"][:7] == month_str]

    # Count recovery events (each represents one outage)
    recoveries = [e for e in month_events if e["type"] == RECOVERY]

    # Estimate total downtime from recovery durations
    total_downtime_min = 0
    for r in recoveries:
        dur = r.get("data", {}).get("duration", "")
        total_downtime_min += _parse_duration_to_minutes(str(dur))

    days_in_month = (today - month_start).days + 1
    total_minutes = days_in_month * 24 * 60
    uptime_minutes = max(0, total_minutes - total_downtime_min)
    uptime_pct = (
        round((uptime_minutes / total_minutes) * 100, 3) if total_minutes > 0 else 100.0
    )

    # SLA tier
    if uptime_pct >= 99.99:
        tier = "99.99% (4 nines)"
    elif uptime_pct >= 99.9:
        tier = "99.9% (3 nines)"
    elif uptime_pct >= 99.0:
        tier = "99% (2 nines)"
    else:
        tier = f"< 99%"

    return {
        "month": month_str,
        "days_elapsed": days_in_month,
        "uptime_pct": uptime_pct,
        "downtime_minutes": total_downtime_min,
        "outage_count": len(recoveries),
        "sla_tier": tier,
    }


def _parse_duration_to_minutes(dur: str) -> int:
    """Parse duration strings like '5min', '2h30', '45s' to minutes."""
    if not dur or dur == "?" or dur == "unknown":
        return 5  # default estimate
    dur = dur.strip()
    if dur.endswith("s"):
        try:
            return max(1, int(dur[:-1]) // 60)
        except ValueError:
            return 5
    if dur.endswith("min"):
        try:
            return int(dur[:-3])
        except ValueError:
            return 5
    if "h" in dur:
        parts = dur.split("h")
        try:
            hours = int(parts[0])
            mins = int(parts[1]) if len(parts) > 1 and parts[1] else 0
            return hours * 60 + mins
        except ValueError:
            return 5
    return 5


def format_weekly_report(report: dict) -> str:
    """Format a weekly report as notification text."""
    lines = [
        f"Rapport hebdomadaire Vigil",
        f"Periode : {report['period']}",
        "",
        f"  Coupures : {report['outage_count']} ({report['outage_trend']})",
        f"  Reboots : {report['reboot_count']} ({report['reboot_trend']})",
    ]

    if report["isp_outage_count"] > 0:
        lines.append(f"  Pannes ISP : {report['isp_outage_count']}")

    lines.append(f"  Evenements totaux : {report['event_count']}")

    if report["peer_status"] not in ("unknown", "standalone"):
        lines.append(f"  Peer : {report['peer_status']}")

    return "\n".join(lines)
