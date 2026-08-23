"""Tests for src/telegram_bot.py"""

import json
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------


class TestIsConfigured:
    def test_returns_true_when_both_set(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", "tok"),
            patch("telegram_bot.TELEGRAM_CHAT_ID", "123"),
        ):
            from telegram_bot import is_configured

            assert is_configured() is True

    def test_returns_false_when_token_missing(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", ""),
            patch("telegram_bot.TELEGRAM_CHAT_ID", "123"),
        ):
            from telegram_bot import is_configured

            assert is_configured() is False

    def test_returns_false_when_chat_id_missing(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", "tok"),
            patch("telegram_bot.TELEGRAM_CHAT_ID", ""),
        ):
            from telegram_bot import is_configured

            assert is_configured() is False

    def test_returns_false_when_both_missing(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", ""),
            patch("telegram_bot.TELEGRAM_CHAT_ID", ""),
        ):
            from telegram_bot import is_configured

            assert is_configured() is False


# ---------------------------------------------------------------------------
# _handle_command helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs):
    from state import WatchdogState

    defaults = dict(
        failure_score=3,
        threshold=10,
        gateway_ok=True,
        internet_ok_count=3,
        internet_total=3,
        reboots_today=1,
        isp_outage_detected=False,
        peer_status="healthy",
        uptime_seconds=7200.0,
        surveillance_only=False,
        gateway_rtt_ms=5.0,
        internet_avg_rtt_ms=12.5,
    )
    defaults.update(kwargs)
    return WatchdogState(**defaults)


def _make_holder(state=None):
    from state import StateHolder

    holder = MagicMock(spec=StateHolder)
    holder.state = state
    return holder


# ---------------------------------------------------------------------------
# _handle_command -- /status
# ---------------------------------------------------------------------------


class TestHandleCommandStatus:
    def setup_method(self):
        self.patcher = patch("telegram_bot._send")
        self.mock_send = self.patcher.start()

    def teardown_method(self):
        self.patcher.stop()

    def test_status_none_state(self):
        from telegram_bot import _handle_command

        holder = _make_holder(state=None)
        _handle_command("/status", "123", holder)
        self.mock_send.assert_called_once()
        assert "demarrage" in self.mock_send.call_args[0][1]

    def test_status_ok(self):
        from telegram_bot import _handle_command

        state = _make_state(failure_score=0)
        holder = _make_holder(state=state)
        _handle_command("/status", "123", holder)
        msg = self.mock_send.call_args[0][1]
        assert "OK" in msg

    def test_status_degrade(self):
        from telegram_bot import _handle_command

        state = _make_state(failure_score=5, threshold=10)
        holder = _make_holder(state=state)
        _handle_command("/status", "123", holder)
        msg = self.mock_send.call_args[0][1]
        assert "DEGRADE" in msg

    def test_status_critique(self):
        from telegram_bot import _handle_command

        state = _make_state(failure_score=10, threshold=10)
        holder = _make_holder(state=state)
        _handle_command("/status", "123", holder)
        msg = self.mock_send.call_args[0][1]
        assert "CRITIQUE" in msg

    def test_status_surveillance(self):
        from telegram_bot import _handle_command

        state = _make_state(surveillance_only=True)
        holder = _make_holder(state=state)
        _handle_command("/status", "123", holder)
        msg = self.mock_send.call_args[0][1]
        assert "SURVEILLANCE" in msg

    def test_status_without_rtt(self):
        from telegram_bot import _handle_command

        state = _make_state(gateway_rtt_ms=None, internet_avg_rtt_ms=None)
        holder = _make_holder(state=state)
        _handle_command("/status", "123", holder)
        self.mock_send.assert_called_once()

    def test_status_strips_botname(self):
        from telegram_bot import _handle_command

        state = _make_state(failure_score=0)
        holder = _make_holder(state=state)
        _handle_command("/status@mybot", "123", holder)
        msg = self.mock_send.call_args[0][1]
        assert "OK" in msg


# ---------------------------------------------------------------------------
# _handle_command -- /pause /resume /reboot
# ---------------------------------------------------------------------------


class TestHandleCommandControl:
    def setup_method(self):
        self.patcher = patch("telegram_bot._send")
        self.mock_send = self.patcher.start()

    def teardown_method(self):
        self.patcher.stop()

    def test_pause_sends_command(self):
        from telegram_bot import _handle_command
        from state import CMD_PAUSE

        holder = _make_holder()
        _handle_command("/pause", "123", holder)
        holder.send_command.assert_called_once_with(CMD_PAUSE)
        self.mock_send.assert_called_once()
        assert "surveillance" in self.mock_send.call_args[0][1].lower()

    def test_resume_sends_command(self):
        from telegram_bot import _handle_command
        from state import CMD_RESUME

        holder = _make_holder()
        _handle_command("/resume", "123", holder)
        holder.send_command.assert_called_once_with(CMD_RESUME)
        self.mock_send.assert_called_once()

    def test_reboot_sends_command(self):
        from telegram_bot import _handle_command
        from state import CMD_REBOOT

        holder = _make_holder()
        _handle_command("/reboot", "123", holder)
        holder.send_command.assert_called_once_with(CMD_REBOOT)
        self.mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_command -- /help
# ---------------------------------------------------------------------------


class TestHandleCommandHelp:
    def test_help_lists_commands(self):
        with patch("telegram_bot._send") as mock_send:
            from telegram_bot import _handle_command

            _handle_command("/help", "123", _make_holder())
            msg = mock_send.call_args[0][1]
            for cmd in [
                "/status",
                "/pause",
                "/resume",
                "/reboot",
                "/ddns",
                "/backup",
                "/help",
            ]:
                assert cmd in msg

    def test_unknown_command_suggests_help(self):
        with patch("telegram_bot._send") as mock_send:
            from telegram_bot import _handle_command

            _handle_command("/unknown", "123", _make_holder())
            msg = mock_send.call_args[0][1]
            assert "/help" in msg


# ---------------------------------------------------------------------------
# _handle_command -- /ddns
# ---------------------------------------------------------------------------


class TestHandleCommandDdns:
    def test_ddns_not_configured(self):
        with patch("telegram_bot._send") as mock_send:
            with patch.dict(
                "sys.modules",
                {
                    "ddns_cloudflare": MagicMock(
                        is_configured=MagicMock(return_value=False),
                        check_and_update=MagicMock(),
                    )
                },
            ):
                from telegram_bot import _handle_command

                _handle_command("/ddns", "123", _make_holder())
                assert "non configure" in mock_send.call_args[0][1]

    def test_ddns_ip_unchanged(self):
        result = MagicMock()
        result.changed = False
        result.current_ip = "1.2.3.4"
        ddns_mod = MagicMock(
            is_configured=MagicMock(return_value=True),
            check_and_update=MagicMock(return_value=result),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"ddns_cloudflare": ddns_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/ddns", "123", _make_holder())
            assert "1.2.3.4" in mock_send.call_args[0][1]
            assert "inchangee" in mock_send.call_args[0][1]

    def test_ddns_ip_changed(self):
        result = MagicMock()
        result.changed = True
        result.previous_ip = "1.1.1.1"
        result.current_ip = "2.2.2.2"
        ddns_mod = MagicMock(
            is_configured=MagicMock(return_value=True),
            check_and_update=MagicMock(return_value=result),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"ddns_cloudflare": ddns_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/ddns", "123", _make_holder())
            msg = mock_send.call_args[0][1]
            assert "1.1.1.1" in msg
            assert "2.2.2.2" in msg

    def test_ddns_returns_none(self):
        ddns_mod = MagicMock(
            is_configured=MagicMock(return_value=True),
            check_and_update=MagicMock(return_value=None),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"ddns_cloudflare": ddns_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/ddns", "123", _make_holder())
            assert "Impossible" in mock_send.call_args[0][1]


# ---------------------------------------------------------------------------
# _handle_command -- /backup
# ---------------------------------------------------------------------------


class TestHandleCommandBackup:
    def test_backup_not_configured(self):
        backup_mod = MagicMock(
            is_configured=MagicMock(return_value=False),
            run_backup=MagicMock(),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"backup_unifi": backup_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/backup", "123", _make_holder())
            assert "non configure" in mock_send.call_args[0][1]

    def test_backup_runs_and_sends_summary(self):
        bresult = MagicMock()
        bresult.summary.return_value = "Backup OK : file.unf (2.5 MB) -> drive:Unifi"
        backup_mod = MagicMock(
            is_configured=MagicMock(return_value=True),
            run_backup=MagicMock(return_value=bresult),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"backup_unifi": backup_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/backup", "123", _make_holder())
            calls = [c[0][1] for c in mock_send.call_args_list]
            assert any("Backup OK" in c for c in calls)


# ---------------------------------------------------------------------------
# _handle_command -- /tailscale
# ---------------------------------------------------------------------------


class TestHandleCommandTailscale:
    def test_tailscale_not_configured(self):
        ts_mod = MagicMock(
            is_configured=MagicMock(return_value=False),
            sync_tailscale_dns=MagicMock(),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"tailscale_dns": ts_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/tailscale", "123", _make_holder())
            assert "non configure" in mock_send.call_args[0][1]

    def test_tailscale_sync_none(self):
        ts_mod = MagicMock(
            is_configured=MagicMock(return_value=True),
            sync_tailscale_dns=MagicMock(return_value=None),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"tailscale_dns": ts_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/tailscale", "123", _make_holder())
            calls = [c[0][1] for c in mock_send.call_args_list]
            assert any("echouee" in c for c in calls)

    def test_tailscale_sync_success(self):
        ts_result = MagicMock()
        ts_result.summary.return_value = "Tailscale DNS sync : 2 crees"
        ts_mod = MagicMock(
            is_configured=MagicMock(return_value=True),
            sync_tailscale_dns=MagicMock(return_value=ts_result),
        )
        with (
            patch("telegram_bot._send") as mock_send,
            patch.dict("sys.modules", {"tailscale_dns": ts_mod}),
        ):
            from telegram_bot import _handle_command

            _handle_command("/tailscale", "123", _make_holder())
            calls = [c[0][1] for c in mock_send.call_args_list]
            assert any("2 crees" in c for c in calls)


# ---------------------------------------------------------------------------
# _check_auth via TelegramBot._poll_updates
# ---------------------------------------------------------------------------


class TestCheckAuth:
    """Verify the bot ignores messages from unauthorized chat IDs."""

    def _make_update(self, chat_id: str, text: str, update_id: int = 1) -> dict:
        return {
            "update_id": update_id,
            "message": {
                "text": text,
                "chat": {"id": int(chat_id)},
            },
        }

    def test_authorized_chat_dispatches_command(self):
        from telegram_bot import TelegramBot

        holder = _make_holder(state=_make_state())

        update = self._make_update("999", "/help")
        api_response = {"ok": True, "result": [update]}

        with (
            patch("telegram_bot.TELEGRAM_CHAT_ID", "999"),
            patch("telegram_bot._api", return_value=api_response),
            patch("telegram_bot._handle_command") as mock_handle,
        ):
            bot = TelegramBot(holder)
            bot._poll_updates()
            mock_handle.assert_called_once_with("/help", "999", holder)

    def test_unauthorized_chat_ignored(self):
        from telegram_bot import TelegramBot

        holder = _make_holder(state=_make_state())

        update = self._make_update("888", "/reboot")
        api_response = {"ok": True, "result": [update]}

        with (
            patch("telegram_bot.TELEGRAM_CHAT_ID", "999"),
            patch("telegram_bot._api", return_value=api_response),
            patch("telegram_bot._handle_command") as mock_handle,
        ):
            bot = TelegramBot(holder)
            bot._poll_updates()
            mock_handle.assert_not_called()

    def test_poll_updates_no_result(self):
        from telegram_bot import TelegramBot

        holder = _make_holder()

        with (
            patch("telegram_bot._api", return_value=None),
            patch("time.sleep") as mock_sleep,
        ):
            bot = TelegramBot(holder)
            bot._poll_updates()
            mock_sleep.assert_called_once_with(5)

    def test_poll_updates_not_ok(self):
        from telegram_bot import TelegramBot

        holder = _make_holder()

        with (
            patch("telegram_bot._api", return_value={"ok": False}),
            patch("time.sleep") as mock_sleep,
        ):
            bot = TelegramBot(holder)
            bot._poll_updates()
            mock_sleep.assert_called_once_with(5)

    def test_poll_updates_increments_offset(self):
        from telegram_bot import TelegramBot

        holder = _make_holder(state=_make_state())

        update = self._make_update("999", "/help", update_id=42)
        api_response = {"ok": True, "result": [update]}

        with (
            patch("telegram_bot.TELEGRAM_CHAT_ID", "999"),
            patch("telegram_bot._api", return_value=api_response),
            patch("telegram_bot._handle_command"),
        ):
            bot = TelegramBot(holder)
            assert bot._offset == 0
            bot._poll_updates()
            assert bot._offset == 43

    def test_poll_updates_skips_non_commands(self):
        from telegram_bot import TelegramBot

        holder = _make_holder(state=_make_state())

        update = self._make_update("999", "hello world")
        api_response = {"ok": True, "result": [update]}

        with (
            patch("telegram_bot.TELEGRAM_CHAT_ID", "999"),
            patch("telegram_bot._api", return_value=api_response),
            patch("telegram_bot._handle_command") as mock_handle,
        ):
            bot = TelegramBot(holder)
            bot._poll_updates()
            mock_handle.assert_not_called()


# ---------------------------------------------------------------------------
# TelegramBot.start
# ---------------------------------------------------------------------------


class TestTelegramBotStart:
    def test_start_returns_false_when_not_configured(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", ""),
            patch("telegram_bot.TELEGRAM_CHAT_ID", ""),
        ):
            from telegram_bot import TelegramBot

            bot = TelegramBot(_make_holder())
            assert bot.start() is False

    def test_start_returns_true_and_spawns_thread(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", "tok"),
            patch("telegram_bot.TELEGRAM_CHAT_ID", "123"),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            from telegram_bot import TelegramBot

            bot = TelegramBot(_make_holder())
            result = bot.start()
            assert result is True
            mock_thread.start.assert_called_once()


# ---------------------------------------------------------------------------
# _api function
# ---------------------------------------------------------------------------


class TestApiFunction:
    def test_api_returns_parsed_json(self):
        response_data = {"ok": True, "result": []}
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")

        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", "mytoken"),
            patch("urllib.request.urlopen", return_value=mock_response),
        ):
            from telegram_bot import _api

            result = _api("getUpdates")
            assert result == response_data

    def test_api_returns_none_on_error(self):
        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", "mytoken"),
            patch("urllib.request.urlopen", side_effect=Exception("timeout")),
        ):
            from telegram_bot import _api

            result = _api("getUpdates")
            assert result is None

    def test_api_with_params_posts_json(self):
        response_data = {"ok": True}
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")

        with (
            patch("telegram_bot.TELEGRAM_BOT_TOKEN", "tok"),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_open,
        ):
            from telegram_bot import _api

            _api("sendMessage", {"chat_id": "1", "text": "hi"})
            req = mock_open.call_args[0][0]
            assert req.data is not None
