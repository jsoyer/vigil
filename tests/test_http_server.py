"""Tests for http_server.py -- background HTTP state server."""

import json
import urllib.request
import urllib.error

import pytest

from src.state import WatchdogState, StateHolder
from src.http_server import start_http_server


def _get(url: str, timeout: int = 2) -> tuple[int, dict]:
    """Helper: GET a URL and return (status_code, json_body)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post(url: str, timeout: int = 2) -> tuple[int, dict]:
    """Helper: POST to a URL and return (status_code, json_body)."""
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get_raw(url: str, timeout: int = 2) -> tuple[int, str, str]:
    """Helper: GET a URL and return (status_code, content_type, body)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            return resp.status, ct, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        ct = e.headers.get("Content-Type", "")
        return e.code, ct, e.read().decode("utf-8")


class TestHttpServer:
    @pytest.fixture(autouse=True)
    def _start_server(self):
        """Start a test server on a random port."""
        self.holder = StateHolder()
        # Use port 0 to let the OS assign a free port
        from http.server import HTTPServer
        from src.http_server import _make_handler_class
        handler = _make_handler_class(self.holder)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

        import threading
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        yield

        self.server.shutdown()

    def test_health_endpoint_starting(self):
        status, body = _get(f"{self.base_url}/health")
        assert status == 503
        assert body["status"] == "starting"

    def test_health_endpoint_healthy(self):
        self.holder.state = WatchdogState(failure_score=0)
        status, body = _get(f"{self.base_url}/health")
        assert status == 200
        assert body["status"] == "healthy"
        assert body["score"] == 0

    def test_health_endpoint_degraded(self):
        self.holder.state = WatchdogState(failure_score=5, threshold=10)
        status, body = _get(f"{self.base_url}/health")
        assert status == 200
        assert body["status"] == "degraded"

    def test_health_endpoint_critical(self):
        self.holder.state = WatchdogState(failure_score=12, threshold=10)
        status, body = _get(f"{self.base_url}/health")
        assert status == 200
        assert body["status"] == "critical"

    def test_state_not_ready(self):
        status, body = _get(f"{self.base_url}/api/state")
        assert status == 503
        assert "not ready" in body["error"]

    def test_state_returns_json(self):
        self.holder.state = WatchdogState(
            failure_score=7,
            instance_priority=2,
            gateway_ok=False,
            timestamp="2026-03-31T12:00:00",
        )
        status, body = _get(f"{self.base_url}/api/state")
        assert status == 200
        assert body["failure_score"] == 7
        assert body["instance_priority"] == 2
        assert body["gateway_ok"] is False

    def test_state_updates_on_holder_change(self):
        self.holder.state = WatchdogState(failure_score=3)
        _, body1 = _get(f"{self.base_url}/api/state")
        assert body1["failure_score"] == 3

        self.holder.state = WatchdogState(failure_score=8)
        _, body2 = _get(f"{self.base_url}/api/state")
        assert body2["failure_score"] == 8

    def test_404_on_unknown_path(self):
        status, body = _get(f"{self.base_url}/nonexistent")
        assert status == 404

    def test_dashboard_returns_html(self):
        status, ct, body = _get_raw(f"{self.base_url}/")
        assert status == 200
        assert "text/html" in ct
        assert "USG Watchdog" in body
        assert "gauge-fill" in body
        assert "/health" in body

    def test_dashboard_alt_path(self):
        status, ct, body = _get_raw(f"{self.base_url}/dashboard")
        assert status == 200
        assert "text/html" in ct

    def test_events_empty_without_log(self):
        status, body = _get(f"{self.base_url}/api/events")
        assert status == 200
        assert body == []

    def test_start_http_server_returns_thread(self):
        holder = StateHolder()
        thread = start_http_server(holder, 0)
        assert thread is not None
        assert thread.is_alive()

    def test_start_http_server_returns_none_on_port_conflict(self):
        """When the port is already in use, start_http_server returns None without raising."""
        import unittest.mock as mock

        holder = StateHolder()
        # Patch ThreadingHTTPServer (used by start_http_server since SSE feature)
        with mock.patch(
            "src.http_server.ThreadingHTTPServer",
            side_effect=OSError("address already in use"),
        ):
            result = start_http_server(holder, 9999)
        assert result is None


class TestHttpServerWithEvents:
    @pytest.fixture(autouse=True)
    def _start_server(self, tmp_path):
        from http.server import HTTPServer
        from src.http_server import _make_handler_class
        from src.events import EventLog

        self.holder = StateHolder()
        self.event_log = EventLog(
            max_events=50,
            persist_path=str(tmp_path / "events.json"),
        )
        handler = _make_handler_class(self.holder, self.event_log)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

        import threading
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        yield
        self.server.shutdown()

    def test_events_returns_recorded_events(self):
        self.event_log.record("reboot", attempt=1)
        self.event_log.record("recovery", duration="5min")

        status, body = _get(f"{self.base_url}/api/events")
        assert status == 200
        assert len(body) == 2
        assert body[0]["type"] == "reboot"
        assert body[1]["type"] == "recovery"

    def test_events_filter_by_type(self):
        self.event_log.record("reboot", attempt=1)
        self.event_log.record("recovery", duration="5min")
        self.event_log.record("reboot", attempt=2)

        status, body = _get(f"{self.base_url}/api/events?type=reboot")
        assert status == 200
        assert len(body) == 2
        assert all(e["type"] == "reboot" for e in body)

    def test_events_count_param(self):
        for i in range(10):
            self.event_log.record("test", n=i)

        status, body = _get(f"{self.base_url}/api/events?count=3")
        assert status == 200
        assert len(body) == 3


_TEST_API_TOKEN = "test-secret-token"


def _post_authed(url: str, token: str, timeout: int = 2) -> tuple[int, dict]:
    """Helper: POST with Bearer token and return (status_code, json_body)."""
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class TestControlAPI:
    @pytest.fixture(autouse=True)
    def _start_server(self):
        from http.server import HTTPServer
        from src.http_server import _make_handler_class

        # Patch API_TOKEN on the exact module object used by http_server
        import src.http_server as _http_server_mod
        _config = _http_server_mod._config  # same object the handler closes over
        _original_token = _config.API_TOKEN
        _config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        handler = _make_handler_class(self.holder)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

        import threading
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        yield
        self.server.shutdown()
        _config.API_TOKEN = _original_token

    def test_pause_command(self):
        status, body = _post_authed(f"{self.base_url}/api/pause", _TEST_API_TOKEN)
        assert status == 200
        assert body["ok"] is True
        assert body["command"] == "pause"
        assert self.holder.poll_command() == "pause"

    def test_resume_command(self):
        status, body = _post_authed(f"{self.base_url}/api/resume", _TEST_API_TOKEN)
        assert status == 200
        assert body["command"] == "resume"
        assert self.holder.poll_command() == "resume"

    def test_reboot_command(self):
        status, body = _post_authed(f"{self.base_url}/api/reboot", _TEST_API_TOKEN)
        assert status == 200
        assert body["command"] == "reboot"
        assert self.holder.poll_command() == "reboot"

    def test_multiple_commands_queued(self):
        _post_authed(f"{self.base_url}/api/pause", _TEST_API_TOKEN)
        _post_authed(f"{self.base_url}/api/resume", _TEST_API_TOKEN)
        assert self.holder.poll_command() == "pause"
        assert self.holder.poll_command() == "resume"
        assert self.holder.poll_command() is None

    def test_post_unknown_path(self):
        status, body = _post_authed(f"{self.base_url}/api/unknown", _TEST_API_TOKEN)
        assert status == 404

    def test_config_endpoint(self):
        status, body = _get(f"{self.base_url}/api/config")
        assert status == 200
        assert "check_interval" in body
        assert "reboot_score_threshold" in body
        assert "ping_targets" in body
        # Verify no secrets exposed
        assert "TELEGRAM_BOT_TOKEN" not in str(body)
        assert "SSH_PASSWORD" not in str(body)
        assert "WEBHOOK_URL" not in str(body)


# ---------------------------------------------------------------------------
# Helpers shared by the new test classes
# ---------------------------------------------------------------------------

def _post_authed_json(
    url: str,
    token: str,
    body: bytes = b"",
    timeout: int = 2,
) -> tuple[int, dict]:
    """POST with Bearer token and optional JSON body."""
    try:
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        if body:
            req.add_header("Content-Type", "application/json")
            req.add_header("Content-Length", str(len(body)))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Fixture factory -- reused by several test classes below
# ---------------------------------------------------------------------------

def _make_server(holder, event_log=None, history=None):
    """Spin up a server on a random port; return (server, port, base_url)."""
    from http.server import HTTPServer
    from src.http_server import _make_handler_class
    import threading

    handler = _make_handler_class(holder, event_log, history)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# GET routes: manifest, service-worker, 404
# ---------------------------------------------------------------------------

class TestGetStaticRoutes:
    @pytest.fixture(autouse=True)
    def _start(self):
        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()

    def test_manifest_json_content_type(self):
        status, ct, body = _get_raw(f"{self.base_url}/manifest.json")
        assert status == 200
        assert "manifest" in ct or "json" in ct

    def test_manifest_json_body(self):
        status, ct, body = _get_raw(f"{self.base_url}/manifest.json")
        data = json.loads(body)
        assert "name" in data
        assert data["name"] == "USG Watchdog"

    def test_sw_js_content_type(self):
        status, ct, body = _get_raw(f"{self.base_url}/sw.js")
        assert status == 200
        assert "javascript" in ct

    def test_sw_js_contains_event_listener(self):
        status, ct, body = _get_raw(f"{self.base_url}/sw.js")
        assert "addEventListener" in body

    def test_unknown_path_returns_404(self):
        status, body = _get(f"{self.base_url}/totally/unknown/path")
        assert status == 404
        assert "error" in body

    def test_api_config_all_keys_present(self):
        status, body = _get(f"{self.base_url}/api/config")
        assert status == 200
        expected_keys = {
            "check_interval", "reboot_score_threshold", "max_score",
            "score_gateway_down", "score_internet_all_down", "score_internet_partial",
            "score_decay_ok", "score_decay_partial", "post_reboot_grace",
            "reboot_cooldown", "max_reboot_cooldown", "max_reboots_per_day",
            "usg_reboot_wait", "usg_ip", "instance_priority", "peer_ip", "peer_port",
            "http_port", "peer_takeover_delay", "ping_targets", "ping_timeout",
            "isp_outage_detection_delay",
        }
        for key in expected_keys:
            assert key in body, f"Missing key in /api/config: {key}"

    def test_api_config_no_secrets_exposed(self):
        status, body = _get(f"{self.base_url}/api/config")
        body_str = json.dumps(body)
        secret_keys = [
            "API_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "USG_SSH_KEY", "USG_SSH_PASSWORD",
            "CLOUDFLARE_API_TOKEN", "TAILSCALE_API_KEY",
            "MQTT_PASSWORD", "SMTP_PASSWORD",
        ]
        for key in secret_keys:
            assert key not in body_str, f"Secret key leaked in /api/config: {key}"

    def test_api_maintenance_get_no_state(self):
        status, body = _get(f"{self.base_url}/api/maintenance")
        assert status == 200
        assert "surveillance_only" in body
        assert body["surveillance_only"] is False

    def test_api_maintenance_get_with_state(self):
        from src.state import WatchdogState
        self.holder.state = WatchdogState(surveillance_only=True)
        status, body = _get(f"{self.base_url}/api/maintenance")
        assert status == 200
        assert body["surveillance_only"] is True

    def test_metrics_text_format(self):
        status, ct, body = _get_raw(f"{self.base_url}/metrics")
        assert status == 200
        assert "text/plain" in ct
        assert "usg_watchdog_up" in body

    def test_metrics_with_state(self):
        from src.state import WatchdogState
        self.holder.state = WatchdogState(failure_score=3, reboots_today=1)
        status, ct, body = _get_raw(f"{self.base_url}/metrics")
        assert status == 200
        assert "usg_watchdog_failure_score" in body
        assert "usg_watchdog_reboots_today" in body

    def test_metrics_no_state_shows_down(self):
        status, ct, body = _get_raw(f"{self.base_url}/metrics")
        assert status == 200
        assert "usg_watchdog_up 0" in body


# ---------------------------------------------------------------------------
# GET /api/history and /api/sla
# ---------------------------------------------------------------------------

class TestGetHistoryAndSla:
    @pytest.fixture(autouse=True)
    def _start(self, tmp_path):
        from src.events import EventLog
        from src.history import HistoryBuffer

        self.holder = StateHolder()
        self.event_log = EventLog(
            max_events=100,
            persist_path=str(tmp_path / "events.json"),
        )
        self.history = HistoryBuffer(max_points=50)
        self.server, self.port, self.base_url = _make_server(
            self.holder, self.event_log, self.history
        )
        yield
        self.server.shutdown()

    def test_history_empty(self):
        status, body = _get(f"{self.base_url}/api/history")
        assert status == 200
        assert body == []

    def test_history_with_data(self):
        self.history.record(score=5, gateway_rtt=10.0, internet_rtt=20.0)
        self.history.record(score=7, gateway_rtt=12.5, internet_rtt=None)
        status, body = _get(f"{self.base_url}/api/history")
        assert status == 200
        assert len(body) == 2
        assert body[0]["score"] == 5
        assert body[1]["score"] == 7

    def test_history_data_structure(self):
        self.history.record(score=3, gateway_rtt=8.0, internet_rtt=15.0, download_mbps=100.0)
        status, body = _get(f"{self.base_url}/api/history")
        point = body[0]
        assert "ts" in point
        assert "score" in point
        assert "gw_rtt" in point
        assert "inet_rtt" in point

    def test_sla_empty_events(self):
        status, body = _get(f"{self.base_url}/api/sla")
        assert status == 200
        assert isinstance(body, dict)

    def test_sla_with_events(self):
        self.event_log.record("reboot", attempt=1)
        status, body = _get(f"{self.base_url}/api/sla")
        assert status == 200
        assert isinstance(body, dict)

    def test_sla_without_event_log(self):
        # Server without event_log
        holder = StateHolder()
        server, _, base_url = _make_server(holder)
        try:
            status, body = _get(f"{base_url}/api/sla")
            assert status == 200
            assert body == {}
        finally:
            server.shutdown()

    def test_history_without_buffer(self):
        # Server without history buffer
        holder = StateHolder()
        server, _, base_url = _make_server(holder)
        try:
            status, body = _get(f"{base_url}/api/history")
            assert status == 200
            assert body == []
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# GET /api/report
# ---------------------------------------------------------------------------

class TestGetReport:
    @pytest.fixture(autouse=True)
    def _start(self, tmp_path):
        from src.events import EventLog
        from src.state import WatchdogState

        self.holder = StateHolder()
        self.holder.state = WatchdogState(
            failure_score=2,
            uptime_seconds=3600.0,
            peer_status="unknown",
        )
        self.event_log = EventLog(
            max_events=50,
            persist_path=str(tmp_path / "events.json"),
        )
        self.server, self.port, self.base_url = _make_server(
            self.holder, self.event_log
        )
        yield
        self.server.shutdown()

    def test_report_returns_200(self):
        status, body = _get(f"{self.base_url}/api/report")
        assert status == 200
        assert isinstance(body, dict)

    def test_report_contains_expected_keys(self):
        status, body = _get(f"{self.base_url}/api/report")
        assert "date" in body or "reboots" in body or "uptime_hours" in body

    def test_report_without_state(self):
        self.holder.state = None
        status, body = _get(f"{self.base_url}/api/report")
        assert status == 200
        assert isinstance(body, dict)


# ---------------------------------------------------------------------------
# GET /api/backup/unifi
# ---------------------------------------------------------------------------

class TestGetBackupUnifi:
    @pytest.fixture(autouse=True)
    def _start(self):
        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()

    def test_backup_not_configured(self):
        import src.http_server as _mod
        import unittest.mock as mock

        with mock.patch("backup_unifi.is_configured", return_value=False):
            status, body = _get(f"{self.base_url}/api/backup/unifi")
        assert status == 200
        assert body["configured"] is False

    def test_backup_configured_no_latest(self):
        import unittest.mock as mock

        with mock.patch("backup_unifi.is_configured", return_value=True), \
             mock.patch("backup_unifi.find_latest_backup", return_value=None):
            status, body = _get(f"{self.base_url}/api/backup/unifi")
        assert status == 200
        assert body["configured"] is True
        assert body["latest"] is None

    def test_backup_configured_with_latest(self, tmp_path):
        import unittest.mock as mock
        from pathlib import Path

        fake_file = tmp_path / "backup_2026-03-31.unf"
        fake_file.write_bytes(b"x" * 1024 * 512)  # 0.5 MB

        with mock.patch("backup_unifi.is_configured", return_value=True), \
             mock.patch("backup_unifi.find_latest_backup", return_value=fake_file), \
             mock.patch("backup_unifi.check_backup_age", return_value=(False, 12.5)):
            status, body = _get(f"{self.base_url}/api/backup/unifi")
        assert status == 200
        assert body["configured"] is True
        assert body["latest"] == fake_file.name
        assert body["age_hours"] == 12.5
        assert body["stale"] is False


# ---------------------------------------------------------------------------
# GET /api/backup/config (export safe config)
# ---------------------------------------------------------------------------

class TestGetBackupConfig:
    @pytest.fixture(autouse=True)
    def _start(self, tmp_path):
        from src.events import EventLog
        from src.state import WatchdogState

        self.holder = StateHolder()
        self.holder.state = WatchdogState(version="1.2.3")
        self.event_log = EventLog(
            max_events=20,
            persist_path=str(tmp_path / "events.json"),
        )
        self.server, self.port, self.base_url = _make_server(
            self.holder, self.event_log
        )
        yield
        self.server.shutdown()

    def test_export_returns_200(self):
        status, body = _get(f"{self.base_url}/api/backup/config")
        assert status == 200

    def test_export_structure(self):
        status, body = _get(f"{self.base_url}/api/backup/config")
        assert "version" in body
        assert "exported_at" in body
        assert "config" in body
        assert "events" in body

    def test_export_config_contains_safe_keys(self):
        status, body = _get(f"{self.base_url}/api/backup/config")
        cfg = body["config"]
        assert "CHECK_INTERVAL" in cfg
        assert "REBOOT_SCORE_THRESHOLD" in cfg
        assert "MAX_SCORE" in cfg

    def test_export_no_secrets(self):
        status, body = _get(f"{self.base_url}/api/backup/config")
        body_str = json.dumps(body)
        secret_keys = [
            "API_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "USG_SSH_PASSWORD", "CLOUDFLARE_API_TOKEN", "TAILSCALE_API_KEY",
            "MQTT_PASSWORD", "SMTP_PASSWORD", "PUSHOVER_API_TOKEN",
            "DISCORD_WEBHOOK_URL", "SLACK_WEBHOOK_URL",
        ]
        for key in secret_keys:
            assert key not in body_str, f"Secret leaked in /api/backup/config: {key}"

    def test_export_events_included(self):
        self.event_log.record("reboot", attempt=1)
        status, body = _get(f"{self.base_url}/api/backup/config")
        assert isinstance(body["events"], list)
        assert len(body["events"]) == 1


# ---------------------------------------------------------------------------
# POST auth tests (no token, wrong token, empty token)
# ---------------------------------------------------------------------------

class TestPostAuth:
    @pytest.fixture(autouse=True)
    def _start(self):
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_post_without_auth_returns_401(self):
        status, body = _post(f"{self.base_url}/api/pause")
        assert status == 401
        assert "unauthorized" in body.get("error", "")

    def test_post_wrong_token_returns_401(self):
        status, body = _post_authed(f"{self.base_url}/api/pause", "wrong-token")
        assert status == 401
        assert "unauthorized" in body.get("error", "")

    def test_post_empty_token_in_config_returns_403(self):
        self._config.API_TOKEN = ""
        try:
            status, body = _post_authed(f"{self.base_url}/api/pause", "anything")
            assert status == 403
            assert "error" in body
        finally:
            self._config.API_TOKEN = _TEST_API_TOKEN

    def test_post_correct_token_succeeds(self):
        status, body = _post_authed(f"{self.base_url}/api/pause", _TEST_API_TOKEN)
        assert status == 200
        assert body["ok"] is True


# ---------------------------------------------------------------------------
# POST /api/maintenance
# ---------------------------------------------------------------------------

class TestPostMaintenance:
    @pytest.fixture(autouse=True)
    def _start(self):
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_maintenance_default_duration(self):
        payload = json.dumps({}).encode("utf-8")
        status, body = _post_authed_json(
            f"{self.base_url}/api/maintenance", _TEST_API_TOKEN, payload
        )
        assert status == 200
        assert body["ok"] is True
        assert body["command"] == "maintenance"
        assert body["duration_minutes"] == 60

    def test_maintenance_custom_duration(self):
        payload = json.dumps({"duration_minutes": 120}).encode("utf-8")
        status, body = _post_authed_json(
            f"{self.base_url}/api/maintenance", _TEST_API_TOKEN, payload
        )
        assert status == 200
        assert body["duration_minutes"] == 120

    def test_maintenance_clamps_to_min(self):
        payload = json.dumps({"duration_minutes": 0}).encode("utf-8")
        status, body = _post_authed_json(
            f"{self.base_url}/api/maintenance", _TEST_API_TOKEN, payload
        )
        assert status == 200
        assert body["duration_minutes"] == 1

    def test_maintenance_clamps_to_max(self):
        payload = json.dumps({"duration_minutes": 9999}).encode("utf-8")
        status, body = _post_authed_json(
            f"{self.base_url}/api/maintenance", _TEST_API_TOKEN, payload
        )
        assert status == 200
        assert body["duration_minutes"] == 1440

    def test_maintenance_invalid_json_returns_400(self):
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/maintenance",
                data=b"not-json",
                method="POST",
            )
            req.add_header("Authorization", f"Bearer {_TEST_API_TOKEN}")
            req.add_header("Content-Length", "8")
            with urllib.request.urlopen(req, timeout=2) as resp:
                status, body = resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            status = e.code
            body = json.loads(e.read())
        assert status == 400
        assert "error" in body

    def test_maintenance_queues_command(self):
        payload = json.dumps({"duration_minutes": 30}).encode("utf-8")
        _post_authed_json(
            f"{self.base_url}/api/maintenance", _TEST_API_TOKEN, payload
        )
        cmd = self.holder.poll_command()
        assert cmd == "maintenance:30"


# ---------------------------------------------------------------------------
# POST /api/config/reload
# ---------------------------------------------------------------------------

class TestPostConfigReload:
    @pytest.fixture(autouse=True)
    def _start(self):
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_reload_when_env_absent(self):
        # /opt/usg-watchdog/.env won't exist in test env -- should still return ok
        status, body = _post_authed(
            f"{self.base_url}/api/config/reload", _TEST_API_TOKEN
        )
        assert status == 200
        assert body["ok"] is True
        assert isinstance(body["reloaded"], list)

    def test_reload_with_env_file(self, tmp_path):
        import unittest.mock as mock
        import importlib

        env_content = "CHECK_INTERVAL=60\nLOG_LEVEL=DEBUG\n"
        env_file = tmp_path / ".env"
        env_file.write_text(env_content)

        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=env_content)):
            status, body = _post_authed(
                f"{self.base_url}/api/config/reload", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is True


# ---------------------------------------------------------------------------
# POST /api/ddns/update
# ---------------------------------------------------------------------------

class TestPostDdnsUpdate:
    @pytest.fixture(autouse=True)
    def _start(self):
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_ddns_not_configured(self):
        import unittest.mock as mock

        with mock.patch("ddns_cloudflare.is_configured", return_value=False):
            status, body = _post_authed(
                f"{self.base_url}/api/ddns/update", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is False
        assert "not configured" in body.get("error", "").lower() or "ddns" in body.get("error", "").lower()

    def test_ddns_ip_detection_failed(self):
        import unittest.mock as mock

        with mock.patch("ddns_cloudflare.is_configured", return_value=True), \
             mock.patch("ddns_cloudflare.check_and_update", return_value=None):
            status, body = _post_authed(
                f"{self.base_url}/api/ddns/update", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is False

    def test_ddns_update_success(self):
        import unittest.mock as mock
        from src.ddns_cloudflare import DdnsResult

        fake_result = DdnsResult(
            current_ip="1.2.3.4",
            previous_ip="1.2.3.3",
            changed=True,
            records_updated=2,
            records_failed=0,
        )
        with mock.patch("ddns_cloudflare.is_configured", return_value=True), \
             mock.patch("ddns_cloudflare.check_and_update", return_value=fake_result):
            status, body = _post_authed(
                f"{self.base_url}/api/ddns/update", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is True
        assert body["current_ip"] == "1.2.3.4"
        assert body["records_updated"] == 2


# ---------------------------------------------------------------------------
# POST /api/tailscale/sync
# ---------------------------------------------------------------------------

class TestPostTailscaleSync:
    @pytest.fixture(autouse=True)
    def _start(self):
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_tailscale_not_configured(self):
        import unittest.mock as mock

        with mock.patch("tailscale_dns.is_configured", return_value=False):
            status, body = _post_authed(
                f"{self.base_url}/api/tailscale/sync", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is False
        assert "not configured" in body.get("error", "")

    def test_tailscale_sync_failed(self):
        import unittest.mock as mock

        with mock.patch("tailscale_dns.is_configured", return_value=True), \
             mock.patch("tailscale_dns.sync_tailscale_dns", return_value=None):
            status, body = _post_authed(
                f"{self.base_url}/api/tailscale/sync", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is False

    def test_tailscale_sync_success(self):
        import unittest.mock as mock
        from src.tailscale_dns import SyncResult

        fake_result = SyncResult(created=1, updated=0, deleted=0, unchanged=3, errors=0, ok=True)
        with mock.patch("tailscale_dns.is_configured", return_value=True), \
             mock.patch("tailscale_dns.sync_tailscale_dns", return_value=fake_result):
            status, body = _post_authed(
                f"{self.base_url}/api/tailscale/sync", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is True
        assert body["created"] == 1


# ---------------------------------------------------------------------------
# POST /api/backup/unifi
# ---------------------------------------------------------------------------

class TestPostBackupUnifi:
    @pytest.fixture(autouse=True)
    def _start(self):
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(self.holder)
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_backup_not_configured(self):
        import unittest.mock as mock

        with mock.patch("backup_unifi.is_configured", return_value=False):
            status, body = _post_authed(
                f"{self.base_url}/api/backup/unifi", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is False
        assert "not configured" in body.get("error", "")

    def test_backup_triggered_success(self):
        import unittest.mock as mock
        from src.backup_unifi import BackupResult

        fake_result = BackupResult(
            ok=True,
            filename="backup_2026-03-31.unf",
            size_bytes=512 * 1024,
            destination="drive:Unifi",
        )
        with mock.patch("backup_unifi.is_configured", return_value=True), \
             mock.patch("backup_unifi.run_backup", return_value=fake_result):
            status, body = _post_authed(
                f"{self.base_url}/api/backup/unifi", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is True
        assert body["filename"] == "backup_2026-03-31.unf"

    def test_backup_triggered_failure(self):
        import unittest.mock as mock
        from src.backup_unifi import BackupResult

        fake_result = BackupResult(ok=False, error="rclone not found")
        with mock.patch("backup_unifi.is_configured", return_value=True), \
             mock.patch("backup_unifi.run_backup", return_value=fake_result):
            status, body = _post_authed(
                f"{self.base_url}/api/backup/unifi", _TEST_API_TOKEN
            )
        assert status == 200
        assert body["ok"] is False


# ---------------------------------------------------------------------------
# Edge cases: exception paths, surveillance status, invalid event count param
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.fixture(autouse=True)
    def _start(self, tmp_path):
        from src.events import EventLog
        import src.http_server as _http_server_mod

        self._config = _http_server_mod._config
        self._original_token = self._config.API_TOKEN
        self._config.API_TOKEN = _TEST_API_TOKEN

        self.holder = StateHolder()
        self.event_log = EventLog(
            max_events=50,
            persist_path=str(tmp_path / "events.json"),
        )
        self.server, self.port, self.base_url = _make_server(
            self.holder, self.event_log
        )
        yield
        self.server.shutdown()
        self._config.API_TOKEN = self._original_token

    def test_health_surveillance_only_status(self):
        from src.state import WatchdogState
        self.holder.state = WatchdogState(surveillance_only=True)
        status, body = _get(f"{self.base_url}/health")
        assert status == 200
        assert body["status"] == "surveillance"

    def test_events_invalid_count_param_falls_back_to_default(self):
        for i in range(10):
            self.event_log.record("test", n=i)
        # "notanumber" triggers the ValueError branch -- should fall back to default 50
        status, body = _get(f"{self.base_url}/api/events?count=notanumber")
        assert status == 200
        assert len(body) == 10  # all 10 events returned with default count=50

    def test_get_500_on_handler_exception(self):
        import unittest.mock as mock
        import src.http_server as _mod
        # Patch render_metrics in the http_server module's own namespace so the
        # handler picks up the patched version at call time.
        with mock.patch.object(_mod, "render_metrics", side_effect=RuntimeError("boom")):
            status, ct, raw = _get_raw(f"{self.base_url}/metrics")
        assert status == 500
        body = json.loads(raw)
        assert "error" in body

    def test_post_500_on_handler_exception(self):
        import unittest.mock as mock
        # StateHolder uses __slots__ so we cannot patch the instance directly.
        # Patch the class method instead and restore it after.
        from src.state import StateHolder as _SH
        original = _SH.send_command
        try:
            _SH.send_command = lambda self, cmd: (_ for _ in ()).throw(RuntimeError("boom"))
            status, body = _post_authed(f"{self.base_url}/api/pause", _TEST_API_TOKEN)
        finally:
            _SH.send_command = original
        assert status == 500
        assert "error" in body

    def test_config_reload_exception_returns_500(self):
        import unittest.mock as mock
        import importlib as il

        with mock.patch.object(il, "reload", side_effect=RuntimeError("bad reload")):
            status, body = _post_authed(
                f"{self.base_url}/api/config/reload", _TEST_API_TOKEN
            )
        assert status == 500
        assert body["ok"] is False
