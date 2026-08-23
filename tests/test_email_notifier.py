"""Tests for notifier/_email.py -- SMTP notification channel."""

import smtplib
from unittest import mock

import pytest

from src.notifier._types import Level, NotificationContext


# ===================================================================
# is_configured
# ===================================================================


class TestEmailIsConfigured:
    @mock.patch("src.notifier._email.SMTP_HOST", "")
    @mock.patch("src.notifier._email.SMTP_TO", "")
    def test_not_configured_when_both_empty(self):
        from src.notifier._email import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._email.SMTP_HOST", "smtp.example.com")
    @mock.patch("src.notifier._email.SMTP_TO", "")
    def test_not_configured_when_to_missing(self):
        from src.notifier._email import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._email.SMTP_HOST", "")
    @mock.patch("src.notifier._email.SMTP_TO", "user@example.com")
    def test_not_configured_when_host_missing(self):
        from src.notifier._email import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._email.SMTP_HOST", "smtp.example.com")
    @mock.patch("src.notifier._email.SMTP_TO", "user@example.com")
    def test_configured_when_both_set(self):
        from src.notifier._email import is_configured

        assert is_configured() is True


# ===================================================================
# send -- helpers
# ===================================================================


def _make_smtp_mock():
    """Return a mock SMTP server instance."""
    server = mock.MagicMock()
    server.send_message.return_value = None
    server.quit.return_value = None
    return server


_BASE_PATCHES = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": 587,
    "SMTP_FROM": "watchdog@example.com",
    "SMTP_TO": "admin@example.com",
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "SMTP_TIMEOUT": 10,
}


def _patch_config(**overrides):
    """Build a list of mock.patch context managers for config values."""
    cfg = {**_BASE_PATCHES, **overrides}
    patches = [mock.patch(f"src.notifier._email.{k}", v) for k, v in cfg.items()]
    return patches


# ===================================================================
# send -- success paths
# ===================================================================


class TestEmailSendSuccess:
    def test_send_success_starttls(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config(SMTP_PORT=587)
        with mock.patch("smtplib.SMTP", return_value=smtp_instance) as mock_smtp:
            for p in patches:
                p.start()
            try:
                result = send(
                    "test message", Level.INFO, None, "myhost", "2026-03-31 12:00:00"
                )
            finally:
                for p in patches:
                    p.stop()
        assert result is True
        mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
        smtp_instance.starttls.assert_called_once()
        smtp_instance.send_message.assert_called_once()
        smtp_instance.quit.assert_called_once()

    def test_send_success_ssl_port_465(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config(SMTP_PORT=465)
        with mock.patch("smtplib.SMTP_SSL", return_value=smtp_instance) as mock_ssl:
            for p in patches:
                p.start()
            try:
                result = send("ssl test", Level.WARNING, None, "myhost", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is True
        mock_ssl.assert_called_once_with("smtp.example.com", 465, timeout=10)
        smtp_instance.starttls.assert_not_called()
        smtp_instance.send_message.assert_called_once()

    def test_send_with_authentication(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config(
            SMTP_USERNAME="user@example.com", SMTP_PASSWORD="secret"
        )
        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                result = send("auth test", Level.INFO, None, "myhost", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is True
        smtp_instance.login.assert_called_once_with("user@example.com", "secret")

    def test_send_without_authentication_skips_login(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config(SMTP_USERNAME="", SMTP_PASSWORD="")
        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("no auth", Level.INFO, None, "myhost", "ts")
            finally:
                for p in patches:
                    p.stop()
        smtp_instance.login.assert_not_called()

    def test_subject_contains_level_prefix_and_hostname(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config()
        captured_msg = {}

        def capture_send_message(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture_send_message

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("critical event", Level.CRITICAL, None, "myrouter", "ts")
            finally:
                for p in patches:
                    p.stop()

        subject = captured_msg["msg"]["Subject"]
        assert "[CRITICAL]" in subject
        assert "myrouter" in subject

    def test_subject_warning_prefix(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config()
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("warn", Level.WARNING, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()

        assert "[WARNING]" in captured_msg["msg"]["Subject"]

    def test_subject_info_prefix(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config()
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("info", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()

        assert "[INFO]" in captured_msg["msg"]["Subject"]

    def test_body_contains_message_and_hostname(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config()
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("fiber cut detected", Level.CRITICAL, None, "gw01", "2026-01-01")
            finally:
                for p in patches:
                    p.stop()

        body = captured_msg["msg"].get_payload(decode=True).decode("utf-8")
        assert "fiber cut detected" in body
        assert "gw01" in body

    def test_body_includes_context_when_provided(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config()
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture
        ctx = NotificationContext(score=8, threshold=10, gateway_ok=False)

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("outage", Level.WARNING, ctx, "host", "ts")
            finally:
                for p in patches:
                    p.stop()

        body = captured_msg["msg"].get_payload(decode=True).decode("utf-8")
        assert "score=8/10" in body
        assert "gw=KO" in body

    def test_from_address_defaults_to_hostname(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config(SMTP_FROM="")
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("test", Level.INFO, None, "router01", "ts")
            finally:
                for p in patches:
                    p.stop()

        assert "router01" in captured_msg["msg"]["From"]

    def test_from_address_uses_config_when_set(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config(SMTP_FROM="watchdog@domain.com")
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()

        assert captured_msg["msg"]["From"] == "watchdog@domain.com"

    def test_context_none_body_does_not_include_none_string(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        patches = _patch_config()
        captured_msg = {}

        def capture(msg):
            captured_msg["msg"] = msg

        smtp_instance.send_message.side_effect = capture

        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                send("hello", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()

        body = captured_msg["msg"].get_payload(decode=True).decode("utf-8")
        assert "None" not in body


# ===================================================================
# send -- error paths
# ===================================================================


class TestEmailSendErrors:
    def test_returns_false_on_auth_error(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"auth failed"
        )
        patches = _patch_config(SMTP_USERNAME="bad_user", SMTP_PASSWORD="wrong")
        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_timeout(self):
        from src.notifier._email import send

        patches = _patch_config()
        with mock.patch("smtplib.SMTP", side_effect=TimeoutError("timed out")):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_connection_error(self):
        from src.notifier._email import send

        patches = _patch_config()
        with mock.patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_smtp_exception(self):
        from src.notifier._email import send

        smtp_instance = _make_smtp_mock()
        smtp_instance.send_message.side_effect = smtplib.SMTPException("send failed")
        patches = _patch_config()
        with mock.patch("smtplib.SMTP", return_value=smtp_instance):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_returns_false_on_unexpected_exception(self):
        from src.notifier._email import send

        patches = _patch_config()
        with mock.patch("smtplib.SMTP", side_effect=RuntimeError("unexpected")):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.INFO, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False

    def test_ssl_returns_false_on_connection_error(self):
        from src.notifier._email import send

        patches = _patch_config(SMTP_PORT=465)
        with mock.patch(
            "smtplib.SMTP_SSL", side_effect=ConnectionRefusedError("ssl refused")
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
        from src.notifier._email import send

        patches = _patch_config()
        with mock.patch("smtplib.SMTP", side_effect=Exception("anything")):
            for p in patches:
                p.start()
            try:
                result = send("test", Level.CRITICAL, None, "host", "ts")
            finally:
                for p in patches:
                    p.stop()
        assert result is False
