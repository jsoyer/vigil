"""Tests for dashboard.py -- HTML template structure and SSE integration markers."""

import pytest

from src.dashboard import DASHBOARD_HTML


@pytest.mark.unit
class TestDashboardHtml:
    """Verify the dashboard HTML contains expected structural elements."""

    def test_is_nonempty_string(self):
        assert isinstance(DASHBOARD_HTML, str)
        assert len(DASHBOARD_HTML) > 1000

    def test_has_doctype(self):
        assert DASHBOARD_HTML.startswith("<!DOCTYPE html>")

    def test_has_title(self):
        assert "<title>USG Watchdog</title>" in DASHBOARD_HTML

    def test_has_manifest_link(self):
        assert 'href="/manifest.json"' in DASHBOARD_HTML

    def test_has_service_worker_registration(self):
        assert "serviceWorker" in DASHBOARD_HTML

    def test_has_score_gauge_element(self):
        assert 'id="gauge-fill"' in DASHBOARD_HTML

    def test_has_status_badge_element(self):
        assert 'id="status-badge"' in DASHBOARD_HTML

    def test_has_events_list_element(self):
        assert 'id="events-list"' in DASHBOARD_HTML

    def test_has_pause_button(self):
        assert 'id="btn-pause"' in DASHBOARD_HTML

    def test_has_resume_button(self):
        assert 'id="btn-resume"' in DASHBOARD_HTML

    def test_has_reboot_button(self):
        assert 'id="btn-reboot"' in DASHBOARD_HTML

    def test_has_chart_score_svg(self):
        assert 'id="chart-score"' in DASHBOARD_HTML

    def test_has_chart_latency_svg(self):
        assert 'id="chart-latency"' in DASHBOARD_HTML

    def test_health_endpoint_referenced(self):
        assert "/health" in DASHBOARD_HTML

    def test_api_events_endpoint_referenced(self):
        assert "/api/events" in DASHBOARD_HTML

    def test_api_history_endpoint_referenced(self):
        assert "/api/history" in DASHBOARD_HTML


@pytest.mark.unit
class TestDashboardSseIntegration:
    """Verify SSE-specific elements and fallback logic are present."""

    def test_sse_stream_endpoint_referenced(self):
        """Dashboard must connect to the /api/stream SSE endpoint."""
        assert "/api/stream" in DASHBOARD_HTML

    def test_event_source_api_used(self):
        """Dashboard must use the browser EventSource API."""
        assert "EventSource" in DASHBOARD_HTML

    def test_sse_onerror_fallback_defined(self):
        """Dashboard must define an onerror handler for SSE fallback."""
        assert "onerror" in DASHBOARD_HTML

    def test_polling_fallback_present(self):
        """Dashboard must fall back to polling when SSE is unavailable."""
        assert "setInterval" in DASHBOARD_HTML

    def test_connection_indicator_element_present(self):
        """Dashboard must show a connection status badge (LIVE / POLLING)."""
        assert 'id="conn-badge"' in DASHBOARD_HTML

    def test_live_badge_text_present(self):
        """Dashboard must show 'LIVE' text in connection indicator."""
        assert "LIVE" in DASHBOARD_HTML

    def test_polling_badge_text_present(self):
        """Dashboard must show 'POLLING' text in connection indicator."""
        assert "POLLING" in DASHBOARD_HTML

    def test_conn_live_css_class_defined(self):
        """CSS class .conn-live must be defined for the LIVE indicator."""
        assert "conn-live" in DASHBOARD_HTML

    def test_conn_polling_css_class_defined(self):
        """CSS class .conn-polling must be defined for the POLLING indicator."""
        assert "conn-polling" in DASHBOARD_HTML

    def test_update_dashboard_function_defined(self):
        """updateDashboard() must be extracted as a standalone function."""
        assert "function updateDashboard(" in DASHBOARD_HTML

    def test_refresh_function_calls_update_dashboard(self):
        """refresh() must delegate DOM updates to updateDashboard()."""
        assert "updateDashboard(" in DASHBOARD_HTML

    def test_charts_poll_interval_at_least_60s(self):
        """Chart refresh interval should be >= 60000ms (not 30s)."""
        # Ensure we have refreshCharts on a timer -- value must be >= 60000
        import re

        matches = re.findall(r"setInterval\(refreshCharts,\s*(\d+)\)", DASHBOARD_HTML)
        assert matches, "setInterval(refreshCharts, ...) not found"
        interval_ms = int(matches[0])
        assert interval_ms >= 60000, (
            f"Chart refresh interval is {interval_ms}ms, expected >= 60000ms"
        )

    def test_sse_reconnect_timeout_defined(self):
        """Dashboard must schedule SSE reconnection after errors."""
        assert "setTimeout" in DASHBOARD_HTML
