"""Tests for notifier package -- types, channels, dispatch."""

import json
from io import BytesIO
from unittest import mock

import pytest

from src.notifier._types import Level, NotificationContext, format_context_inline
from src.notifier import notify


# ===================================================================
# Types
# ===================================================================


class TestLevel:
    def test_ordering(self):
        assert Level.INFO < Level.WARNING < Level.CRITICAL

    def test_from_name(self):
        assert Level["INFO"] == Level.INFO
        assert Level["CRITICAL"] == Level.CRITICAL


class TestNotificationContext:
    def test_is_frozen(self):
        ctx = NotificationContext(score=5, threshold=10)
        with pytest.raises(AttributeError):
            ctx.score = 10  # type: ignore[misc]

    def test_default_values(self):
        ctx = NotificationContext()
        assert ctx.score is None
        assert ctx.gateway_ok is None
        assert ctx.extra == {}


class TestFormatContextInline:
    def test_full_context(self):
        ctx = NotificationContext(
            score=12,
            threshold=10,
            gateway_ok=False,
            internet_ok_count=0,
            internet_total=3,
            reboot_count=3,
            duration="2h30",
        )
        result = format_context_inline(ctx)
        assert "score=12/10" in result
        assert "gw=KO" in result
        assert "inet=0/3" in result
        assert "reboots=3" in result
        assert "duree=2h30" in result

    def test_empty_context(self):
        ctx = NotificationContext()
        assert format_context_inline(ctx) == ""

    def test_extra_fields(self):
        ctx = NotificationContext(extra={"ssh_echecs": "5"})
        result = format_context_inline(ctx)
        assert "ssh_echecs=5" in result

    def test_gateway_ok(self):
        ctx = NotificationContext(gateway_ok=True)
        assert "gw=OK" in format_context_inline(ctx)


# ===================================================================
# Helpers
# ===================================================================


def _mock_response(status: int = 200, body: bytes = b"{}") -> mock.MagicMock:
    """Build a mock urllib response context manager."""
    resp = mock.MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


# ===================================================================
# Ntfy channel
# ===================================================================


class TestNtfy:
    @mock.patch("src.notifier._ntfy.NTFY_URL", "")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "")
    def test_not_configured_when_empty(self):
        from src.notifier._ntfy import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "https://ntfy.sh")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "test-topic")
    def test_sends_with_priority(self):
        from src.notifier._ntfy import send

        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            result = send("test msg", Level.CRITICAL, None, "host", "ts")
        assert result is True
        req = mock_open.call_args[0][0]
        assert "ntfy.sh/test-topic" in req.full_url
        assert req.headers["Priority"] == "5"

    @mock.patch("src.notifier._ntfy.NTFY_URL", "http://pi:8080")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "watchdog")
    def test_self_hosted_url(self):
        from src.notifier._ntfy import send

        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            send("test", Level.INFO, None, "h", "t")
        req = mock_open.call_args[0][0]
        assert req.full_url == "http://pi:8080/watchdog"

    @mock.patch("src.notifier._ntfy.NTFY_URL", "https://ntfy.sh")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "test")
    def test_returns_false_on_timeout(self):
        from src.notifier._ntfy import send
        import urllib.error

        with mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")
        ):
            assert send("test", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "https://ntfy.sh")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "test")
    def test_returns_false_on_connection_error(self):
        from src.notifier._ntfy import send
        import urllib.error

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            assert send("test", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "https://ntfy.sh")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "test")
    def test_includes_context(self):
        from src.notifier._ntfy import send

        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            ctx = NotificationContext(score=12, threshold=10)
            send("test", Level.WARNING, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        body = req.data.decode()
        assert "score=12/10" in body


# ===================================================================
# Dispatch / public API
# ===================================================================


class TestDispatch:
    def _make_channel(self, configured: bool = False, send_result: bool = True):
        ch = mock.Mock()
        ch.is_configured.return_value = configured
        ch.send.return_value = send_result
        return ch

    def test_no_channels_configured(self):
        channels = [
            ("channel_a", self._make_channel(False), "INFO"),
            ("channel_b", self._make_channel(False), "INFO"),
            ("channel_c", self._make_channel(False), "INFO"),
        ]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test")
        assert results == {}

    def test_sends_to_configured_channel(self):
        ch1 = self._make_channel(True)
        channels = [
            ("channel_a", ch1, "INFO"),
            ("channel_b", self._make_channel(False), "INFO"),
            ("channel_c", self._make_channel(False), "INFO"),
        ]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test")
        assert results["channel_a"] is True
        ch1.send.assert_called_once()

    def test_level_filtering_skips_low_severity(self):
        ch1 = self._make_channel(True)
        channels = [("channel_a", ch1, "CRITICAL")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test", Level.INFO)
        assert results["channel_a"] is False
        ch1.send.assert_not_called()

    def test_level_filtering_allows_high_severity(self):
        ch1 = self._make_channel(True)
        channels = [("channel_a", ch1, "WARNING")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test", Level.CRITICAL)
        assert results["channel_a"] is True
        ch1.send.assert_called_once()

    def test_one_failure_doesnt_block_others(self):
        ch1 = self._make_channel(True)
        ch1.send.side_effect = Exception("boom")
        ch2 = self._make_channel(True)
        channels = [("channel_a", ch1, "INFO"), ("channel_b", ch2, "INFO")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test")
        assert results["channel_a"] is False
        assert results["channel_b"] is True

    def test_multiple_channels_all_receive(self):
        ch1 = self._make_channel(True)
        ch2 = self._make_channel(True)
        ch3 = self._make_channel(True)
        channels = [
            ("channel_a", ch1, "INFO"),
            ("channel_b", ch2, "INFO"),
            ("channel_c", ch3, "INFO"),
        ]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test", Level.WARNING)
        assert results == {"channel_a": True, "channel_b": True, "channel_c": True}
