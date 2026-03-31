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
            score=12, threshold=10, gateway_ok=False,
            internet_ok_count=0, internet_total=3,
            reboot_count=3, duration="2h30",
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
# Telegram channel
# ===================================================================


class TestTelegram:
    @mock.patch("src.notifier._telegram.TELEGRAM_BOT_TOKEN", "")
    @mock.patch("src.notifier._telegram.TELEGRAM_CHAT_ID", "")
    def test_not_configured_when_empty(self):
        from src.notifier._telegram import is_configured
        assert is_configured() is False

    @mock.patch("src.notifier._telegram.TELEGRAM_BOT_TOKEN", "fake")
    @mock.patch("src.notifier._telegram.TELEGRAM_CHAT_ID", "123")
    def test_configured_when_set(self):
        from src.notifier._telegram import is_configured
        assert is_configured() is True

    @mock.patch("src.notifier._telegram.TELEGRAM_BOT_TOKEN", "fake")
    @mock.patch("src.notifier._telegram.TELEGRAM_CHAT_ID", "123")
    def test_sends_html_message(self):
        from src.notifier._telegram import send
        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            result = send("test msg", Level.INFO, None, "myhost", "31/03/2026 12:00:00")
        assert result is True
        req = mock_open.call_args[0][0]
        assert "fake" in req.full_url
        payload = json.loads(req.data.decode())
        assert payload["parse_mode"] == "HTML"

    @mock.patch("src.notifier._telegram.TELEGRAM_BOT_TOKEN", "fake")
    @mock.patch("src.notifier._telegram.TELEGRAM_CHAT_ID", "123")
    def test_includes_context_in_message(self):
        from src.notifier._telegram import send
        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            ctx = NotificationContext(score=12, threshold=10)
            send("test", Level.WARNING, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        payload = json.loads(req.data.decode())
        assert "score=12/10" in payload["text"]

    @mock.patch("src.notifier._telegram.TELEGRAM_BOT_TOKEN", "fake")
    @mock.patch("src.notifier._telegram.TELEGRAM_CHAT_ID", "123")
    def test_returns_false_on_timeout(self):
        from src.notifier._telegram import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            assert send("test", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._telegram.TELEGRAM_BOT_TOKEN", "fake")
    @mock.patch("src.notifier._telegram.TELEGRAM_CHAT_ID", "123")
    def test_returns_false_on_connection_error(self):
        from src.notifier._telegram import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            assert send("test", Level.INFO, None, "h", "t") is False


# ===================================================================
# Discord channel
# ===================================================================


class TestDiscord:
    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "")
    def test_not_configured_when_empty(self):
        from src.notifier._discord import is_configured
        assert is_configured() is False

    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")
    def test_sends_embed_with_color(self):
        from src.notifier._discord import send
        resp = _mock_response(204)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            result = send("test msg", Level.CRITICAL, None, "host", "ts")
        assert result is True
        req = mock_open.call_args[0][0]
        payload = json.loads(req.data.decode())
        embed = payload["embeds"][0]
        assert embed["color"] == 0xE74C3C
        assert embed["description"] == "test msg"

    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc-def")
    def test_includes_context_fields(self):
        from src.notifier._discord import send
        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            ctx = NotificationContext(score=8, threshold=10, gateway_ok=True, internet_ok_count=1, internet_total=3)
            send("msg", Level.WARNING, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        embed = json.loads(req.data.decode())["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Score" in field_names
        assert "Gateway" in field_names
        assert "Internet" in field_names

    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")
    def test_handles_rate_limit(self):
        from src.notifier._discord import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(None, 429, "rate limited", {}, None)):
            assert send("msg", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")
    def test_returns_false_on_timeout(self):
        from src.notifier._discord import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            assert send("msg", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")
    def test_returns_false_on_connection_error(self):
        from src.notifier._discord import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            assert send("msg", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._discord.DISCORD_WEBHOOK_URL", "https://evil.com/steal")
    def test_rejects_invalid_webhook_url(self):
        from src.notifier._discord import is_configured
        assert is_configured() is False


# ===================================================================
# Slack channel
# ===================================================================

_VALID_SLACK_URL = "https://hooks.slack.com/services/T0000/B0000/xxxx"


class TestSlack:
    @mock.patch("src.notifier._slack.SLACK_WEBHOOK_URL", "")
    def test_not_configured_when_empty(self):
        from src.notifier._slack import is_configured
        assert is_configured() is False

    @mock.patch("src.notifier._slack.SLACK_WEBHOOK_URL", _VALID_SLACK_URL)
    def test_sends_block_kit_message(self):
        from src.notifier._slack import send
        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            result = send("test msg", Level.WARNING, None, "host", "ts")
        assert result is True
        req = mock_open.call_args[0][0]
        payload = json.loads(req.data.decode())
        blocks = payload["blocks"]
        assert blocks[0]["type"] == "header"
        assert blocks[1]["type"] == "section"
        assert "test msg" in blocks[1]["text"]["text"]

    @mock.patch("src.notifier._slack.SLACK_WEBHOOK_URL", _VALID_SLACK_URL)
    def test_includes_context_elements(self):
        from src.notifier._slack import send
        resp = _mock_response(200)
        with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
            ctx = NotificationContext(score=12, threshold=10, reboot_count=2)
            send("msg", Level.CRITICAL, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        blocks = json.loads(req.data.decode())["blocks"]
        assert len(blocks) == 4
        ctx_block = blocks[2]
        assert ctx_block["type"] == "context"

    @mock.patch("src.notifier._slack.SLACK_WEBHOOK_URL", _VALID_SLACK_URL)
    def test_returns_false_on_timeout(self):
        from src.notifier._slack import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            assert send("msg", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._slack.SLACK_WEBHOOK_URL", _VALID_SLACK_URL)
    def test_returns_false_on_connection_error(self):
        from src.notifier._slack import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            assert send("msg", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._slack.SLACK_WEBHOOK_URL", "https://evil.com/steal")
    def test_rejects_invalid_webhook_url(self):
        from src.notifier._slack import is_configured
        assert is_configured() is False


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
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            assert send("test", Level.INFO, None, "h", "t") is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "https://ntfy.sh")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "test")
    def test_returns_false_on_connection_error(self):
        from src.notifier._ntfy import send
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
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
            ("telegram", self._make_channel(False), "INFO"),
            ("discord", self._make_channel(False), "INFO"),
            ("slack", self._make_channel(False), "INFO"),
        ]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test")
        assert results == {}

    def test_sends_to_configured_channel(self):
        tg = self._make_channel(True)
        channels = [
            ("telegram", tg, "INFO"),
            ("discord", self._make_channel(False), "INFO"),
            ("slack", self._make_channel(False), "INFO"),
        ]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test")
        assert results["telegram"] is True
        tg.send.assert_called_once()

    def test_level_filtering_skips_low_severity(self):
        tg = self._make_channel(True)
        channels = [("telegram", tg, "CRITICAL")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test", Level.INFO)
        assert results["telegram"] is False
        tg.send.assert_not_called()

    def test_level_filtering_allows_high_severity(self):
        tg = self._make_channel(True)
        channels = [("telegram", tg, "WARNING")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test", Level.CRITICAL)
        assert results["telegram"] is True
        tg.send.assert_called_once()

    def test_one_failure_doesnt_block_others(self):
        tg = self._make_channel(True)
        tg.send.side_effect = Exception("boom")
        dc = self._make_channel(True)
        channels = [("telegram", tg, "INFO"), ("discord", dc, "INFO")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test")
        assert results["telegram"] is False
        assert results["discord"] is True

    def test_multiple_channels_all_receive(self):
        tg = self._make_channel(True)
        dc = self._make_channel(True)
        sl = self._make_channel(True)
        channels = [("telegram", tg, "INFO"), ("discord", dc, "INFO"), ("slack", sl, "INFO")]
        with mock.patch("notifier._dispatch._get_channels", return_value=channels):
            results = notify("test", Level.WARNING)
        assert results == {"telegram": True, "discord": True, "slack": True}
