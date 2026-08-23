"""Tests for notifier/_pushover.py -- Pushover notification channel."""

import urllib.error
from unittest import mock

import pytest

from src.notifier._types import Level, NotificationContext


# ===================================================================
# is_configured
# ===================================================================


class TestPushoverIsConfigured:
    @mock.patch("src.notifier._pushover.PUSHOVER_USER_KEY", "")
    @mock.patch("src.notifier._pushover.PUSHOVER_API_TOKEN", "")
    def test_not_configured_when_both_empty(self):
        from src.notifier._pushover import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._pushover.PUSHOVER_USER_KEY", "user123")
    @mock.patch("src.notifier._pushover.PUSHOVER_API_TOKEN", "")
    def test_not_configured_when_token_missing(self):
        from src.notifier._pushover import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._pushover.PUSHOVER_USER_KEY", "")
    @mock.patch("src.notifier._pushover.PUSHOVER_API_TOKEN", "token456")
    def test_not_configured_when_user_key_missing(self):
        from src.notifier._pushover import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._pushover.PUSHOVER_USER_KEY", "user123")
    @mock.patch("src.notifier._pushover.PUSHOVER_API_TOKEN", "token456")
    def test_configured_when_both_set(self):
        from src.notifier._pushover import is_configured

        assert is_configured() is True


# ===================================================================
# send -- helpers
# ===================================================================


def _mock_response(status: int = 200):
    resp = mock.MagicMock()
    resp.status = status
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


_BASE_PATCHES = {
    "PUSHOVER_USER_KEY": "testuser",
    "PUSHOVER_API_TOKEN": "testtoken",
    "PUSHOVER_TIMEOUT": 10,
}


def _patch_config(**overrides):
    cfg = {**_BASE_PATCHES, **overrides}
    return [mock.patch(f"src.notifier._pushover.{k}", v) for k, v in cfg.items()]


# ===================================================================
# send -- success paths
# ===================================================================


class TestPushoverSendSuccess:
    def test_send_success_returns_true(self):
        from src.notifier._pushover import send

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp):
            for p in patches:
                p.start()
            try:
                result = send("test message", Level.INFO, None, "myhost", "2026-03-31")
            finally:
                for p in patches:
                    p.stop()
        assert result is True

    def test_sends_to_pushover_api_url(self):
        from src.notifier._pushover import send

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        assert "pushover.net" in req.full_url
        assert "messages.json" in req.full_url

    def test_info_level_sends_priority_minus_one(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert fields["priority"] == "-1"

    def test_warning_level_sends_priority_zero(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("test", Level.WARNING, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert fields["priority"] == "0"

    def test_critical_level_sends_priority_one(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("test", Level.CRITICAL, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert fields["priority"] == "1"

    def test_body_contains_message_and_hostname(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("fiber down", Level.CRITICAL, None, "gw01", "2026-01-01")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert "fiber down" in fields["message"]
        assert "gw01" in fields["message"]

    def test_body_includes_context_when_provided(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        ctx = NotificationContext(score=9, threshold=10, gateway_ok=False)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("outage", Level.WARNING, ctx, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert "score=9/10" in fields["message"]
        assert "gw=KO" in fields["message"]

    def test_title_is_vigil(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert fields["title"] == "Vigil"

    def test_payload_contains_credentials(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert fields["token"] == "testtoken"
        assert fields["user"] == "testuser"

    def test_non_200_status_returns_false(self):
        from src.notifier._pushover import send

        resp = _mock_response(500)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_context_none_body_does_not_contain_none_string(self):
        from src.notifier._pushover import send
        import urllib.parse

        resp = _mock_response(200)
        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            for p in patches:
                p.start()
            try:
                send("clean message", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        req = mock_open.call_args[0][0]
        fields = dict(urllib.parse.parse_qsl(req.data.decode("utf-8")))
        assert "None" not in fields["message"]


# ===================================================================
# send -- error paths
# ===================================================================


class TestPushoverSendErrors:
    def test_returns_false_on_timeout(self):
        from src.notifier._pushover import send

        patches = _patch_config()
        with mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")
        ):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_connection_error(self):
        from src.notifier._pushover import send

        patches = _patch_config()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_http_error(self):
        from src.notifier._pushover import send

        patches = _patch_config()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(None, 400, "bad request", {}, None),
        ):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_unexpected_exception(self):
        from src.notifier._pushover import send

        patches = _patch_config()
        with mock.patch(
            "urllib.request.urlopen", side_effect=RuntimeError("unexpected")
        ):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_never_raises(self):
        from src.notifier._pushover import send

        patches = _patch_config()
        with mock.patch("urllib.request.urlopen", side_effect=Exception("boom")):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.CRITICAL, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False
