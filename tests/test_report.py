"""Tests for report.py -- daily report generation."""

from datetime import date

import pytest

from src.events import EventLog, REBOOT, REBOOT_FAILED, RECOVERY, ISP_OUTAGE
from src.report import generate_daily_report, format_report_notification


class TestGenerateDailyReport:
    def test_empty_events(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log, uptime_seconds=86400)

        assert report["outage_count"] == 0
        assert report["reboot_count"] == 0
        assert report["uptime_pct"] == 100.0

    def test_with_reboots_and_recoveries(self, tmp_path):
        log = EventLog(max_events=50, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
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
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record(ISP_OUTAGE, duration="2h")

        report = generate_daily_report(log)
        assert report["isp_outage_count"] == 1

    def test_with_failed_reboots(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record(REBOOT_FAILED, ssh_failures=3)
        log.record(REBOOT_FAILED, ssh_failures=4)

        report = generate_daily_report(log)
        assert report["reboot_failed_count"] == 2

    def test_includes_peer_status(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log, peer_status="healthy")
        assert report["peer_status"] == "healthy"

    def test_includes_current_score(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log, current_score=7)
        assert report["current_score"] == 7


class TestFormatReportNotification:
    def test_basic_format(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log, uptime_seconds=86400)
        text = format_report_notification(report)

        assert "Rapport USG Watchdog" in text
        assert "Uptime" in text
        assert "Coupures" in text
        assert "Reboots" in text

    def test_includes_reboot_details_when_reboots(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record(REBOOT, attempt=1)
        log.record(RECOVERY, helped=True, reboots=1)
        report = generate_daily_report(log)
        text = format_report_notification(report)

        assert "utiles" in text

    def test_includes_isp_when_detected(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record(ISP_OUTAGE, duration="1h")
        report = generate_daily_report(log)
        text = format_report_notification(report)

        assert "ISP" in text

    def test_includes_peer_when_configured(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log, peer_status="healthy")
        text = format_report_notification(report)

        assert "Peer" in text

    def test_no_peer_line_for_standalone(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log, peer_status="standalone")
        text = format_report_notification(report)

        assert "Peer" not in text

    def test_no_failed_line_when_zero(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        report = generate_daily_report(log)
        text = format_report_notification(report)

        assert "echoues" not in text
