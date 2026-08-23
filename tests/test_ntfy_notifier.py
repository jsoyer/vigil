"""Tests for notifier/_ntfy.py -- Ntfy notification channel (enrichi)."""

import urllib.error
from unittest import mock

from src.notifier._types import Level, NotificationContext


# ===================================================================
# is_configured
# ===================================================================


class TestNtfyIsConfigured:
    @mock.patch("src.notifier._ntfy.NTFY_URL", "")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "")
    def test_not_configured_when_both_empty(self):
        from src.notifier._ntfy import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "http://ntfy.local:7171")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "")
    def test_not_configured_when_topic_missing(self):
        from src.notifier._ntfy import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "vigil-dijon")
    def test_not_configured_when_url_missing(self):
        from src.notifier._ntfy import is_configured

        assert is_configured() is False

    @mock.patch("src.notifier._ntfy.NTFY_URL", "http://ntfy.local:7171")
    @mock.patch("src.notifier._ntfy.NTFY_TOPIC", "vigil-dijon")
    def test_configured_when_both_set(self):
        from src.notifier._ntfy import is_configured

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
    "NTFY_URL": "http://127.0.0.1:7171",
    "NTFY_TOPIC": "vigil-dijon",
    "NTFY_TOPIC_OPS": "vigil-ops",
    "NTFY_TIMEOUT": 5,
    "NTFY_TOKEN": "",
    "HTTP_PORT": 9000,
    "INSTANCE_ID": "dijon_master",
}


def _patch_config(**overrides):
    cfg = {**_BASE_PATCHES, **overrides}
    return [mock.patch(f"src.notifier._ntfy.{k}", v) for k, v in cfg.items()]


def _send_with_patches(*args, overrides=None, **kwargs):
    from src.notifier._ntfy import send

    resp = kwargs.pop("_resp", None) or _mock_response(200)
    side_effect = kwargs.pop("_side_effect", None)
    patches = _patch_config(**(overrides or {}))
    urlopen_kwargs = (
        {"side_effect": side_effect} if side_effect else {"return_value": resp}
    )
    with mock.patch("urllib.request.urlopen", **urlopen_kwargs) as mock_open:
        for p in patches:
            p.start()
        try:
            result = send(*args, **kwargs)
        finally:
            for p in patches:
                p.stop()
    return result, mock_open


# ===================================================================
# send -- priorites par niveau
# ===================================================================


class TestNtfyPriority:
    def test_info_level_priority_3(self):
        _, mock_open = _send_with_patches("test", Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "3"

    def test_warning_level_priority_4(self):
        _, mock_open = _send_with_patches("test", Level.WARNING, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "4"

    def test_critical_level_priority_5(self):
        _, mock_open = _send_with_patches("test", Level.CRITICAL, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "5"

    def test_report_category_ops_info_priority_2(self):
        ctx = NotificationContext(category="ops")
        _, mock_open = _send_with_patches("rapport", Level.INFO, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "2"

    def test_ops_warning_keeps_level_priority(self):
        # Une alerte "ops" (ex: sauvegarde en echec) ne doit pas etre
        # noyee en priorite basse -- seule la categorie ops + INFO l'est.
        ctx = NotificationContext(category="ops")
        _, mock_open = _send_with_patches(
            "backup echoue", Level.WARNING, ctx, "host", "ts"
        )
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "4"


# ===================================================================
# send -- tags, titre
# ===================================================================


class TestNtfyTagsAndTitle:
    def test_tags_contain_level_instance_and_site(self):
        _, mock_open = _send_with_patches(
            "test",
            Level.WARNING,
            None,
            "host",
            "ts",
            overrides={"INSTANCE_ID": "dijon_master"},
        )
        req = mock_open.call_args[0][0]
        tags = req.get_header("Tags")
        assert "warning" in tags
        assert "dijon_master" in tags
        assert "dijon" in tags

    def test_tags_derive_nice_site(self):
        _, mock_open = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "host",
            "ts",
            overrides={"INSTANCE_ID": "nice_slave"},
        )
        req = mock_open.call_args[0][0]
        assert "nice" in req.get_header("Tags")

    def test_title_contains_instance_id(self):
        _, mock_open = _send_with_patches(
            "Internet KO",
            Level.CRITICAL,
            None,
            "host",
            "ts",
            overrides={"INSTANCE_ID": "nice_master"},
        )
        req = mock_open.call_args[0][0]
        assert "nice_master" in req.get_header("Title")

    def test_title_contains_first_line_of_message(self):
        _, mock_open = _send_with_patches(
            "Internet KO (score 12/15)\ndetails ici", Level.CRITICAL, None, "host", "ts"
        )
        req = mock_open.call_args[0][0]
        assert "Internet KO" in req.get_header("Title")

    def test_markdown_header_present(self):
        _, mock_open = _send_with_patches("test", Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Markdown") == "yes"

    def test_click_header_points_to_dashboard(self):
        _, mock_open = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "penelope",
            "ts",
            overrides={"HTTP_PORT": 9000},
        )
        req = mock_open.call_args[0][0]
        assert req.get_header("Click") == "http://penelope:9000/dashboard"


# ===================================================================
# send -- authentification (NTFY_TOKEN)
# ===================================================================


class TestNtfyAuth:
    def test_empty_token_no_authorization_header(self):
        _, mock_open = _send_with_patches(
            "test", Level.INFO, None, "host", "ts", overrides={"NTFY_TOKEN": ""}
        )
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") is None

    def test_token_set_adds_bearer_header(self):
        _, mock_open = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "host",
            "ts",
            overrides={"NTFY_TOKEN": "tk_secret123"},
        )
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer tk_secret123"

    def test_token_never_in_body(self):
        _, mock_open = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "host",
            "ts",
            overrides={"NTFY_TOKEN": "tk_secret123"},
        )
        req = mock_open.call_args[0][0]
        assert b"tk_secret123" not in req.data

    def test_token_never_in_url(self):
        _, mock_open = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "host",
            "ts",
            overrides={"NTFY_TOKEN": "tk_secret123"},
        )
        req = mock_open.call_args[0][0]
        assert "tk_secret123" not in req.full_url

    def test_empty_token_publication_unchanged_returns_true(self):
        result, _ = _send_with_patches(
            "test", Level.INFO, None, "host", "ts", overrides={"NTFY_TOKEN": ""}
        )
        assert result is True


# ===================================================================
# send -- routage de topic (alert vs ops)
# ===================================================================


class TestNtfyTopicRouting:
    def test_default_no_context_uses_site_topic(self):
        _, mock_open = _send_with_patches("test", Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.full_url.endswith("/vigil-dijon")

    def test_alert_category_uses_site_topic(self):
        ctx = NotificationContext(category="alert")
        _, mock_open = _send_with_patches("test", Level.INFO, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.full_url.endswith("/vigil-dijon")

    def test_ops_category_uses_ops_topic(self):
        ctx = NotificationContext(category="ops")
        _, mock_open = _send_with_patches("test", Level.INFO, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.full_url.endswith("/vigil-ops")

    def test_ops_category_uses_configured_ops_topic_value(self):
        ctx = NotificationContext(category="ops")
        _, mock_open = _send_with_patches(
            "test",
            Level.INFO,
            ctx,
            "host",
            "ts",
            overrides={"NTFY_TOPIC_OPS": "vigil-ops-custom"},
        )
        req = mock_open.call_args[0][0]
        assert req.full_url.endswith("/vigil-ops-custom")


# ===================================================================
# send -- troncature du corps (4096 octets)
# ===================================================================


class TestNtfyBodyTruncation:
    def test_long_body_truncated_under_4096_bytes(self):
        long_message = "x" * 10000
        _, mock_open = _send_with_patches(long_message, Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert len(req.data) <= 4096

    def test_short_body_not_truncated(self):
        short_message = "Internet KO"
        _, mock_open = _send_with_patches(short_message, Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert short_message.encode("utf-8") in req.data
        assert len(req.data) <= 4096

    def test_truncated_body_ends_with_indicator(self):
        long_message = "y" * 10000
        _, mock_open = _send_with_patches(long_message, Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert b"tronque" in req.data

    def test_truncated_body_is_valid_utf8(self):
        # Message compose de caracteres multi-octets pour verifier qu'on ne
        # coupe jamais au milieu d'un caractere UTF-8.
        long_message = "e" * 4090 + "é" * 50
        _, mock_open = _send_with_patches(long_message, Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        # Ne doit pas lever UnicodeDecodeError
        req.data.decode("utf-8")
        assert len(req.data) <= 4096


# ===================================================================
# send -- corps, contexte
# ===================================================================


class TestNtfyBodyContent:
    def test_body_contains_message_and_hostname(self):
        _, mock_open = _send_with_patches(
            "fiber down", Level.CRITICAL, None, "gw01", "2026-01-01"
        )
        req = mock_open.call_args[0][0]
        body = req.data.decode("utf-8")
        assert "fiber down" in body
        assert "gw01" in body

    def test_body_includes_context_when_provided(self):
        ctx = NotificationContext(score=9, threshold=10, gateway_ok=False)
        _, mock_open = _send_with_patches("outage", Level.WARNING, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        body = req.data.decode("utf-8")
        assert "score=9/10" in body
        assert "gw=KO" in body

    def test_content_type_header_present(self):
        _, mock_open = _send_with_patches("test", Level.INFO, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert "text/plain" in req.get_header("Content-type")


# ===================================================================
# send -- jamais de lever d'exception (never raises)
# ===================================================================


class TestNtfySendErrors:
    def test_returns_false_on_timeout(self):
        result, _ = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "host",
            "ts",
            _side_effect=urllib.error.URLError("timed out"),
        )
        assert result is False

    def test_returns_false_on_http_error(self):
        result, _ = _send_with_patches(
            "test",
            Level.INFO,
            None,
            "host",
            "ts",
            _side_effect=urllib.error.HTTPError(None, 403, "forbidden", {}, None),
        )
        assert result is False

    def test_returns_false_on_non_200_status(self):
        result, _ = _send_with_patches(
            "test", Level.INFO, None, "host", "ts", _resp=_mock_response(500)
        )
        assert result is False

    def test_never_raises_on_unexpected_exception(self):
        result, _ = _send_with_patches(
            "test",
            Level.CRITICAL,
            None,
            "host",
            "ts",
            _side_effect=RuntimeError("boom"),
        )
        assert result is False


# ===================================================================
# grep de non-regression -- aucune trace des canaux debranches
# ===================================================================


def test_no_reference_to_other_channels():
    import inspect
    from src.notifier import _ntfy

    source = inspect.getsource(_ntfy)
    lowered = source.lower()
    for forbidden in ("telegram", "discord", "slack", "pushover"):
        assert forbidden not in lowered


# ===================================================================
# send -- escalade (categorie "escalation", PRD Ntfy-first S5.2/S5.3)
# ===================================================================


class TestNtfyEscalation:
    def test_escalation_priority_is_5_even_if_level_not_critical(self):
        ctx = NotificationContext(category="escalation")
        _, mock_open = _send_with_patches("test", Level.WARNING, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "5"

    def test_escalation_critical_priority_is_5(self):
        ctx = NotificationContext(category="escalation")
        _, mock_open = _send_with_patches("test", Level.CRITICAL, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Priority") == "5"

    def test_escalation_tag_sos_present_in_addition_to_usual_tags(self):
        ctx = NotificationContext(category="escalation")
        _, mock_open = _send_with_patches(
            "test",
            Level.CRITICAL,
            ctx,
            "host",
            "ts",
            overrides={"INSTANCE_ID": "dijon_master"},
        )
        req = mock_open.call_args[0][0]
        tags = req.get_header("Tags")
        assert "sos" in tags.split(",")
        assert "rotating_light" in tags
        assert "dijon_master" in tags

    def test_escalation_title_prefixed_relance(self):
        ctx = NotificationContext(category="escalation")
        _, mock_open = _send_with_patches(
            "Alerte critique non resolue", Level.CRITICAL, ctx, "host", "ts"
        )
        req = mock_open.call_args[0][0]
        assert req.get_header("Title").startswith("[RELANCE]")

    def test_escalation_never_sets_actions_header(self):
        ctx = NotificationContext(category="escalation")
        _, mock_open = _send_with_patches("test", Level.CRITICAL, ctx, "host", "ts")
        req = mock_open.call_args[0][0]
        assert req.get_header("Actions") is None

    def test_non_escalation_title_not_prefixed(self):
        ctx = NotificationContext(category="alert")
        _, mock_open = _send_with_patches(
            "Internet KO", Level.CRITICAL, ctx, "host", "ts"
        )
        req = mock_open.call_args[0][0]
        assert not req.get_header("Title").startswith("[RELANCE]")

    def test_non_escalation_no_sos_tag(self):
        _, mock_open = _send_with_patches("test", Level.CRITICAL, None, "host", "ts")
        req = mock_open.call_args[0][0]
        assert "sos" not in req.get_header("Tags").split(",")
