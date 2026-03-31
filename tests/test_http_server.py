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


class TestControlAPI:
    @pytest.fixture(autouse=True)
    def _start_server(self):
        from http.server import HTTPServer
        from src.http_server import _make_handler_class

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

    def test_pause_command(self):
        status, body = _post(f"{self.base_url}/api/pause")
        assert status == 200
        assert body["ok"] is True
        assert body["command"] == "pause"
        assert self.holder.poll_command() == "pause"

    def test_resume_command(self):
        status, body = _post(f"{self.base_url}/api/resume")
        assert status == 200
        assert body["command"] == "resume"
        assert self.holder.poll_command() == "resume"

    def test_reboot_command(self):
        status, body = _post(f"{self.base_url}/api/reboot")
        assert status == 200
        assert body["command"] == "reboot"
        assert self.holder.poll_command() == "reboot"

    def test_multiple_commands_queued(self):
        _post(f"{self.base_url}/api/pause")
        _post(f"{self.base_url}/api/resume")
        assert self.holder.poll_command() == "pause"
        assert self.holder.poll_command() == "resume"
        assert self.holder.poll_command() is None

    def test_post_unknown_path(self):
        status, body = _post(f"{self.base_url}/api/unknown")
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
