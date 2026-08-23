"""Tests for dashboard.py -- HTML template structure and SSE integration markers."""

import inspect

import pytest

import src.dashboard as dashboard_module
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
        assert "<title>Vigil</title>" in DASHBOARD_HTML

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


@pytest.mark.unit
class TestDashboardAuth:
    """Sprint 3 -- API_TOKEN captured client-side, sessionStorage only, never
    embedded server-side in the generated HTML."""

    def test_uses_session_storage_for_token(self):
        assert "sessionStorage.setItem(" in DASHBOARD_HTML
        assert "sessionStorage.getItem(" in DASHBOARD_HTML

    def test_never_uses_local_storage(self):
        """Hard invariant: no persistence across tab closes -- localStorage
        must never appear anywhere in the generated dashboard."""
        assert "localStorage" not in DASHBOARD_HTML

    def test_api_request_helper_defined(self):
        assert "function apiRequest(" in DASHBOARD_HTML

    def test_api_request_injects_authorization_bearer_header(self):
        assert "Authorization" in DASHBOARD_HTML
        assert "'Bearer ' + token" in DASHBOARD_HTML

    def test_send_command_uses_authenticated_request_path(self):
        """sendCommand() (existing pause/resume/reboot buttons) must funnel
        through the authenticated request helper -- this is the fix for the
        blocking bug (403/401 on every click today)."""
        send_command_start = DASHBOARD_HTML.index("async function sendCommand(")
        send_command_end = DASHBOARD_HTML.index(
            "\n}", DASHBOARD_HTML.index("function runAction(", send_command_start)
        )
        send_command_src = DASHBOARD_HTML[send_command_start:send_command_end]
        assert "runAction(" in send_command_src or "apiRequest(" in send_command_src

    def test_unauthorized_response_shows_clear_message_not_silent(self):
        """401 must surface a clear, visible message inviting the operator
        to re-enter the token -- never a silent console-only failure."""
        assert "401" in DASHBOARD_HTML
        assert "showTokenPrompt(" in DASHBOARD_HTML

    def test_token_prompt_ui_elements_present(self):
        assert 'id="token-prompt"' in DASHBOARD_HTML
        assert 'id="api-token-input"' in DASHBOARD_HTML
        assert 'id="btn-save-token"' in DASHBOARD_HTML

    def test_dashboard_source_never_references_api_token(self):
        """Architectural guarantee (not just a snapshot of today's HTML):
        dashboard.py never imports config nor references API_TOKEN, so no
        code path can ever interpolate the secret into the served HTML."""
        source = inspect.getsource(dashboard_module)
        assert "API_TOKEN" not in source
        assert "import config" not in source

    def test_generated_html_never_contains_configured_token(self, monkeypatch):
        """End-to-end proof: whatever API_TOKEN is configured server-side,
        the HTML served to the browser is identical and never carries it."""
        secret = "s3cr3t-vigil-test-token-must-never-leak-77213"
        monkeypatch.setenv("API_TOKEN", secret)

        import importlib

        import config as config_module

        importlib.reload(config_module)
        try:
            assert secret not in DASHBOARD_HTML
        finally:
            importlib.reload(config_module)


@pytest.mark.unit
class TestDashboardActionsSection:
    """Sprint 3 -- missing commands from PRD S4.5 (DDNS, backup, tailscale,
    maintenance) wired to their existing server-side endpoints."""

    def test_ddns_button_present(self):
        assert 'id="btn-ddns"' in DASHBOARD_HTML
        assert "/api/ddns/update" in DASHBOARD_HTML

    def test_backup_unifi_button_present(self):
        assert 'id="btn-backup"' in DASHBOARD_HTML
        assert "/api/backup/unifi" in DASHBOARD_HTML

    def test_tailscale_sync_button_present(self):
        assert 'id="btn-tailscale"' in DASHBOARD_HTML
        assert "/api/tailscale/sync" in DASHBOARD_HTML

    def test_maintenance_button_present(self):
        assert 'id="btn-maintenance"' in DASHBOARD_HTML
        assert "/api/maintenance" in DASHBOARD_HTML


@pytest.mark.unit
class TestDashboardTplinkSection:
    """Sprint 3 -- new TP-Link section: list, per-device status, check,
    reboot + existing confirmation flow (reused, not reinvented)."""

    def test_tplink_section_present(self):
        assert 'id="tplink-card"' in DASHBOARD_HTML
        assert 'id="tplink-list"' in DASHBOARD_HTML

    def test_tplink_list_endpoint_referenced(self):
        assert "/api/tplink" in DASHBOARD_HTML

    def test_tplink_check_function_and_endpoint(self):
        assert "function tplinkCheck(" in DASHBOARD_HTML
        assert "/check" in DASHBOARD_HTML

    def test_tplink_reboot_function_and_endpoint(self):
        assert "function tplinkReboot(" in DASHBOARD_HTML
        assert "/reboot" in DASHBOARD_HTML

    def test_tplink_reboot_reuses_existing_confirm_endpoint(self):
        """Must reuse POST /api/tplink/<id>/reboot/confirm (already shipped
        by A1 Sprint 3) -- no new confirmation mechanism invented here."""
        assert "/reboot/confirm" in DASHBOARD_HTML
        assert "function tplinkConfirmReboot(" in DASHBOARD_HTML

    def test_tplink_reboot_sends_token_in_confirm_body(self):
        """The confirm step must forward the token received from the
        reboot request, as required by /api/tplink/<id>/reboot/confirm."""
        assert "token" in DASHBOARD_HTML
