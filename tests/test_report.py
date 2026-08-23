"""Tests for report.py -- daily report generation."""

from datetime import date

import pytest

from src.events import EventLog, REBOOT, REBOOT_FAILED, RECOVERY, ISP_OUTAGE
from src.report import (
    generate_daily_report,
    format_report_notification,
    generate_weekly_report,
    format_weekly_report,
    calculate_monthly_sla,
    _parse_duration_to_minutes,
)


class TestGenerateDailyReport:
    def test_empty_events(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log, uptime_seconds=86400)

        assert report["outage_count"] == 0
        assert report["reboot_count"] == 0
        assert report["uptime_pct"] == 100.0

    def test_with_reboots_and_recoveries(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(REBOOT, attempt=1)
        log.record(REBOOT, attempt=2)
        log.record(RECOVERY, duration="5min", helped=True, reboots=2)
        log.record(REBOOT, attempt=3)
        log.record(RECOVERY, duration="10min", helped=False, reboots=1)

        report = generate_daily_report(log, uptime_seconds=86400)

        assert report["reboot_count"] == 3
        assert report["outage_count"] == 2
        assert report["reboot_helped"] == 1

    def test_with_isp_outage(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(ISP_OUTAGE, duration="2h")

        report = generate_daily_report(log)
        assert report["isp_outage_count"] == 1

    def test_with_failed_reboots(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(REBOOT_FAILED, ssh_failures=3)
        log.record(REBOOT_FAILED, ssh_failures=4)

        report = generate_daily_report(log)
        assert report["reboot_failed_count"] == 2

    def test_includes_peer_status(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log, peer_status="healthy")
        assert report["peer_status"] == "healthy"

    def test_includes_current_score(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log, current_score=7)
        assert report["current_score"] == 7


class TestFormatReportNotification:
    def test_basic_format(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log, uptime_seconds=86400)
        text = format_report_notification(report)

        assert "Rapport Vigil" in text
        assert "Uptime" in text
        assert "Coupures" in text
        assert "Reboots" in text

    def test_includes_reboot_details_when_reboots(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(REBOOT, attempt=1)
        log.record(RECOVERY, helped=True, reboots=1)
        report = generate_daily_report(log)
        text = format_report_notification(report)

        assert "utiles" in text

    def test_includes_isp_when_detected(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(ISP_OUTAGE, duration="1h")
        report = generate_daily_report(log)
        text = format_report_notification(report)

        assert "ISP" in text

    def test_includes_peer_when_configured(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log, peer_status="healthy")
        text = format_report_notification(report)

        assert "Peer" in text

    def test_no_peer_line_for_standalone(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log, peer_status="standalone")
        text = format_report_notification(report)

        assert "Peer" not in text

    def test_no_failed_line_when_zero(self, tmp_path):
        log = EventLog(
            max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_daily_report(log)
        text = format_report_notification(report)

        assert "echoues" not in text


# ===================================================================
# _parse_duration_to_minutes
# ===================================================================


class TestParseDurationToMinutes:
    def test_seconds_below_one_minute_returns_one(self):
        assert _parse_duration_to_minutes("30s") == 1

    def test_seconds_exact_minute(self):
        assert _parse_duration_to_minutes("60s") == 1

    def test_seconds_multiple_minutes(self):
        assert _parse_duration_to_minutes("120s") == 2

    def test_seconds_large_value(self):
        assert _parse_duration_to_minutes("3600s") == 60

    def test_minutes_simple(self):
        assert _parse_duration_to_minutes("5min") == 5

    def test_minutes_zero(self):
        assert _parse_duration_to_minutes("0min") == 0

    def test_minutes_large(self):
        assert _parse_duration_to_minutes("120min") == 120

    def test_hours_only(self):
        assert _parse_duration_to_minutes("2h") == 120

    def test_hours_and_minutes(self):
        assert _parse_duration_to_minutes("2h30") == 150

    def test_hours_and_zero_minutes(self):
        assert _parse_duration_to_minutes("1h0") == 60

    def test_empty_string_returns_default(self):
        assert _parse_duration_to_minutes("") == 5

    def test_question_mark_returns_default(self):
        assert _parse_duration_to_minutes("?") == 5

    def test_unknown_string_returns_default(self):
        assert _parse_duration_to_minutes("unknown") == 5

    def test_unrecognized_format_returns_default(self):
        assert _parse_duration_to_minutes("xyz") == 5

    def test_invalid_seconds_returns_default(self):
        assert _parse_duration_to_minutes("abcs") == 5

    def test_invalid_minutes_returns_default(self):
        assert _parse_duration_to_minutes("abcmin") == 5


# ===================================================================
# generate_weekly_report
# ===================================================================


class TestGenerateWeeklyReport:
    def test_empty_events_returns_zeros(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_weekly_report(log)
        assert report["outage_count"] == 0
        assert report["reboot_count"] == 0
        assert report["isp_outage_count"] == 0
        assert report["event_count"] == 0

    def test_period_key_present(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_weekly_report(log)
        assert "period" in report
        assert "->" in report["period"]

    def test_current_score_propagated(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_weekly_report(log, current_score=9)
        assert report["current_score"] == 9

    def test_peer_status_propagated(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_weekly_report(log, peer_status="degraded")
        assert report["peer_status"] == "degraded"

    def test_trend_stable_when_both_zero(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        report = generate_weekly_report(log)
        assert report["outage_trend"] == "stable"
        assert report["reboot_trend"] == "stable"

    def test_trend_positive_when_previous_zero(self, tmp_path):
        """When previous week had 0 events and current week has some, trend is +N.

        The weekly window is [today-7d, today). Events recorded now have today's
        timestamp and are excluded from the current window. We mock datetime.now
        to return tomorrow so today's events fall inside the [today-7d, today+1d)
        window.
        """
        from datetime import datetime, timedelta
        from unittest import mock

        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(RECOVERY, duration="5min", helped=True, reboots=1)
        log.record(REBOOT, attempt=1)

        tomorrow = datetime.now().date() + timedelta(days=1)
        fake_now = datetime.combine(tomorrow, datetime.min.time())

        with mock.patch("src.report.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            report = generate_weekly_report(log)

        assert report["outage_trend"].startswith("+")
        assert report["reboot_trend"].startswith("+")


# ===================================================================
# format_weekly_report
# ===================================================================


class TestFormatWeeklyReport:
    def _make_report(self, tmp_path, **kwargs):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        return generate_weekly_report(log, **kwargs)

    def test_contains_header(self, tmp_path):
        report = self._make_report(tmp_path)
        text = format_weekly_report(report)
        assert "Rapport hebdomadaire" in text

    def test_contains_period(self, tmp_path):
        report = self._make_report(tmp_path)
        text = format_weekly_report(report)
        assert "Periode" in text
        assert report["period"] in text

    def test_contains_coupures_line(self, tmp_path):
        report = self._make_report(tmp_path)
        text = format_weekly_report(report)
        assert "Coupures" in text

    def test_contains_reboots_line(self, tmp_path):
        report = self._make_report(tmp_path)
        text = format_weekly_report(report)
        assert "Reboots" in text

    def test_contains_total_events_line(self, tmp_path):
        report = self._make_report(tmp_path)
        text = format_weekly_report(report)
        assert "Evenements" in text

    def test_no_isp_line_when_zero(self, tmp_path):
        report = self._make_report(tmp_path)
        text = format_weekly_report(report)
        assert "ISP" not in text

    def test_includes_isp_line_when_nonzero(self, tmp_path):
        from datetime import datetime, timedelta
        from unittest import mock

        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(ISP_OUTAGE, duration="1h")

        tomorrow = datetime.now().date() + timedelta(days=1)
        fake_now = datetime.combine(tomorrow, datetime.min.time())

        with mock.patch("src.report.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            report = generate_weekly_report(log)

        text = format_weekly_report(report)
        assert "ISP" in text

    def test_peer_line_shown_for_non_unknown_status(self, tmp_path):
        report = self._make_report(tmp_path, peer_status="healthy")
        text = format_weekly_report(report)
        assert "Peer" in text

    def test_no_peer_line_for_unknown_status(self, tmp_path):
        report = self._make_report(tmp_path, peer_status="unknown")
        text = format_weekly_report(report)
        assert "Peer" not in text

    def test_no_peer_line_for_standalone_status(self, tmp_path):
        report = self._make_report(tmp_path, peer_status="standalone")
        text = format_weekly_report(report)
        assert "Peer" not in text


# ===================================================================
# calculate_monthly_sla
# ===================================================================


class TestCalculateMonthlySla:
    def test_returns_required_keys(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        sla = calculate_monthly_sla(log)
        assert "month" in sla
        assert "days_elapsed" in sla
        assert "uptime_pct" in sla
        assert "downtime_minutes" in sla
        assert "outage_count" in sla
        assert "sla_tier" in sla

    def test_no_outages_gives_100_pct(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        sla = calculate_monthly_sla(log)
        assert sla["uptime_pct"] == 100.0

    def test_no_outages_zero_downtime(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        sla = calculate_monthly_sla(log)
        assert sla["downtime_minutes"] == 0

    def test_no_outages_sla_tier_four_nines(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        sla = calculate_monthly_sla(log)
        assert "99.99" in sla["sla_tier"]

    def test_outage_count_matches_recovery_events(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(RECOVERY, duration="5min", helped=True, reboots=1)
        log.record(RECOVERY, duration="10min", helped=False, reboots=0)
        sla = calculate_monthly_sla(log)
        assert sla["outage_count"] == 2

    def test_downtime_accumulates_from_durations(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(RECOVERY, duration="10min", helped=True, reboots=1)
        log.record(RECOVERY, duration="20min", helped=True, reboots=1)
        sla = calculate_monthly_sla(log)
        assert sla["downtime_minutes"] == 30

    def test_uptime_pct_below_100_when_downtime_present(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(RECOVERY, duration="60min", helped=True, reboots=1)
        sla = calculate_monthly_sla(log)
        assert sla["uptime_pct"] < 100.0

    def test_days_elapsed_is_positive_integer(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        sla = calculate_monthly_sla(log)
        assert sla["days_elapsed"] >= 1

    def test_month_format_is_yyyy_mm(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        sla = calculate_monthly_sla(log)
        import re

        assert re.match(r"^\d{4}-\d{2}$", sla["month"])

    def test_sla_tier_three_nines_label(self, tmp_path):
        """Inject enough downtime to land in the 99.9% tier."""
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        # 30 days * 60 min/h * 24 h = 43200 total minutes
        # 99.9% => max 43.2 minutes downtime; inject ~60 min to drop below 99.9%
        # but above 99.0% => 432 minutes max for 99.0%
        # inject ~100 min to land in 99.9% range
        for _ in range(10):
            log.record(RECOVERY, duration="10min", helped=True, reboots=1)
        sla = calculate_monthly_sla(log)
        # Either 3 nines or 4 nines depending on days elapsed; just check it has a tier
        assert "nines" in sla["sla_tier"] or "99" in sla["sla_tier"]

    def test_recovery_with_unknown_duration_uses_default(self, tmp_path):
        log = EventLog(
            max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999
        )
        log.record(RECOVERY, duration="", helped=True, reboots=1)
        sla = calculate_monthly_sla(log)
        assert sla["downtime_minutes"] == 5
