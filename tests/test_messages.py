"""Tests for messages.py -- notification message clarity and completeness."""

from src.messages import (
    startup,
    shutdown,
    reboot_launching,
    recovery_with_reboot,
    recovery_no_reboot,
    isp_outage_detected,
    max_reboots_reached,
    ssh_failure,
    divergence_detected,
    api_pause,
    api_resume,
    api_reboot,
    update_available,
    update_success,
    update_failed,
    backup_ok,
    backup_failed,
    backup_stale,
    ddns_updated,
    ddns_failed,
    _dashboard_link,
    _peer_label,
)
from src.notifier._types import Level


class TestStartup:
    def test_contains_key_info(self):
        text, level, ctx = startup()
        assert "surveillance internet" in text.lower()
        assert "192.168.1.1" in text
        assert "Dashboard" in text
        assert level == Level.INFO

    def test_contains_config_values(self):
        text, _, _ = startup()
        # Should contain check interval, threshold, max reboots
        assert "30s" in text or "30" in text
        assert "10" in text  # threshold or max reboots


class TestShutdown:
    def test_manual_stop(self):
        text, level, _ = shutdown("arret manuel")
        assert "arrete" in text.lower()
        assert "arret manuel" in text
        assert level == Level.INFO

    def test_crash(self):
        text, level, _ = shutdown("crash")
        assert "crash" in text
        assert level == Level.CRITICAL

    def test_warns_no_monitoring(self):
        text, _, _ = shutdown()
        assert "surveille" in text.lower()


class TestRebootLaunching:
    def test_contains_all_details(self):
        text, level, ctx = reboot_launching(
            attempt=2,
            score=12,
            gateway_ok=True,
            inet_count=0,
            inet_total=3,
            reboots_today=2,
            peer_info={
                "status": "healthy",
                "score": 0,
                "gateway": "OK",
                "internet": "3/3",
            },
        )
        assert "redemarrage" in text.lower()
        assert "#2" in text
        assert "12" in text  # score
        assert "0/3" in text  # internet
        assert "2 min" in text  # expected downtime
        assert level == Level.CRITICAL
        assert ctx is not None
        assert ctx.score == 12

    def test_no_peer_line_standalone(self):
        text, _, _ = reboot_launching(
            attempt=1,
            score=10,
            gateway_ok=False,
            inet_count=0,
            inet_total=3,
            reboots_today=1,
            peer_info={
                "status": "standalone",
                "score": 0,
                "gateway": "",
                "internet": "",
            },
        )
        assert "Peer" not in text


class TestRecovery:
    def test_with_reboot_helped(self):
        text, level, ctx = recovery_with_reboot("5min", 2, True)
        assert "retablie" in text
        assert "5min" in text
        assert "resolu" in text.lower()
        assert level == Level.INFO

    def test_with_reboot_not_helped(self):
        text, _, _ = recovery_with_reboot("10min", 1, False)
        assert "seul" in text.lower()

    def test_no_reboot(self):
        text, _, _ = recovery_no_reboot("3min")
        assert "retablie" in text
        assert "necessaire" in text.lower()


class TestIspOutage:
    def test_explains_situation(self):
        text, level, ctx = isp_outage_detected("30min", 3)
        assert "fournisseur" in text.lower()
        assert "30min" in text
        assert "suspendus" in text
        assert "FAI" in text
        assert level == Level.WARNING


class TestMaxReboots:
    def test_explains_limit(self):
        text, level, ctx = max_reboots_reached(10)
        assert "10" in text
        assert "surveillance" in text.lower()
        assert "demain" in text
        assert "Dashboard" in text
        assert level == Level.CRITICAL


class TestSshFailure:
    def test_explains_problem_and_actions(self):
        text, level, ctx = ssh_failure(5, "5min")
        assert "SSH" in text
        assert "5" in text
        assert "5min" in text
        assert "test.sh" in text
        assert level == Level.WARNING


class TestDivergence:
    def test_local_problem(self):
        text, level, _ = divergence_detected(10, True, 0, 0, "OK", "3/3")
        assert "cette machine" in text.lower()
        assert level == Level.WARNING

    def test_peer_problem(self):
        text, _, _ = divergence_detected(0, True, 3, 10, "KO", "0/3")
        assert "peer" in text.lower()


class TestApiMessages:
    def test_pause(self):
        text, level, _ = api_pause()
        assert "surveillance" in text.lower()
        assert level == Level.WARNING

    def test_resume(self):
        text, level, _ = api_resume()
        assert "desactive" in text.lower() or "nouveau" in text.lower()
        assert level == Level.INFO

    def test_reboot(self):
        text, level, _ = api_reboot()
        assert "manuel" in text.lower()
        assert "192.168.1.1" in text
        assert level == Level.CRITICAL


class TestUpdateMessages:
    def test_available(self):
        text, _, _ = update_available("1.0.0", "1.1.0")
        assert "1.0.0" in text
        assert "1.1.0" in text

    def test_success(self):
        text, _, _ = update_success("1.0.0", "1.1.0")
        assert "reussie" in text
        assert "1.1.0" in text

    def test_failed(self):
        text, _, _ = update_failed("1.1.0", "tests echoues")
        assert "echouee" in text
        assert "restauree" in text


class TestDashboardLink:
    def test_returns_http_url(self):
        link = _dashboard_link()
        assert link.startswith("http://")
        assert ":" in link

    def test_contains_port(self):
        from unittest import mock

        with mock.patch("socket.gethostname", return_value="myhost"):
            link = _dashboard_link()
        assert "myhost" in link

    def test_falls_back_on_socket_error(self):
        from unittest import mock

        with mock.patch("socket.gethostname", side_effect=OSError("fail")):
            link = _dashboard_link()
        assert "localhost" in link


class TestPeerLabel:
    def test_with_peer_ip(self):
        from unittest import mock

        with mock.patch("src.messages.PEER_IP", "10.0.0.2"):
            label = _peer_label()
        assert "10.0.0.2" in label

    def test_standalone(self):
        from unittest import mock

        with mock.patch("src.messages.PEER_IP", ""):
            label = _peer_label()
        assert "standalone" in label


class TestBackupOk:
    def test_contains_filename_and_destination(self):
        text, level, ctx = backup_ok("unifi-2026.unf", 4.2, "/mnt/backup")
        assert "unifi-2026.unf" in text
        assert "4.2" in text
        assert "/mnt/backup" in text
        assert level == Level.INFO
        assert ctx is None

    def test_default_source_is_scheduled(self):
        text, _, _ = backup_ok("unifi.unf", 1.0, "/tmp")
        assert "scheduled" in text

    def test_custom_source(self):
        text, _, _ = backup_ok("unifi.unf", 1.0, "/tmp", source="manual")
        assert "manual" in text


class TestBackupFailed:
    def test_contains_error_message(self):
        text, level, ctx = backup_failed("rclone not found")
        assert "rclone not found" in text
        assert "Echec" in text
        assert level == Level.WARNING
        assert ctx is None

    def test_contains_filename_when_provided(self):
        text, _, _ = backup_failed("disk full", filename="unifi-2026.unf")
        assert "unifi-2026.unf" in text

    def test_no_filename_when_empty(self):
        text, _, _ = backup_failed("timeout")
        assert "Fichier" not in text

    def test_contains_remediation_hints(self):
        text, _, _ = backup_failed("some error")
        assert "rclone" in text
        assert "remote" in text


class TestBackupStale:
    def test_contains_age_and_max(self):
        text, level, ctx = backup_stale("unifi-old.unf", 48, 24)
        assert "48h" in text
        assert "24h" in text
        assert "unifi-old.unf" in text
        assert level == Level.WARNING
        assert ctx is None

    def test_mentions_unifi_controller(self):
        text, _, _ = backup_stale("file.unf", 12, 6)
        assert "UniFi Controller" in text


class TestDdnsUpdated:
    def test_contains_both_ips(self):
        text, level, ctx = ddns_updated(
            "1.2.3.4", "5.6.7.8", 2, "home.example.com, vpn.example.com"
        )
        assert "1.2.3.4" in text
        assert "5.6.7.8" in text
        assert "2" in text
        assert "home.example.com" in text
        assert level == Level.INFO
        assert ctx is None

    def test_mentions_services(self):
        text, _, _ = ddns_updated("1.1.1.1", "2.2.2.2", 1, "example.com")
        assert "VPN" in text or "services" in text.lower()


class TestDdnsFailed:
    def test_contains_ip_and_errors(self):
        errors = [
            "home.example.com: record ID introuvable",
            "vpn.example.com: update echoue",
        ]
        text, level, ctx = ddns_failed("5.6.7.8", errors)
        assert "5.6.7.8" in text
        assert "home.example.com" in text
        assert "vpn.example.com" in text
        assert level == Level.WARNING
        assert ctx is None

    def test_empty_error_list(self):
        text, level, _ = ddns_failed("1.2.3.4", [])
        assert "1.2.3.4" in text
        assert level == Level.WARNING

    def test_mentions_cloudflare_token(self):
        text, _, _ = ddns_failed("1.2.3.4", ["some error"])
        assert "Cloudflare" in text

    def test_each_error_is_listed(self):
        errors = ["err-alpha", "err-beta", "err-gamma"]
        text, _, _ = ddns_failed("9.9.9.9", errors)
        for err in errors:
            assert err in text


# ===================================================================
# Alert escalation (Sprint 4, PRD Ntfy-first S5)
# ===================================================================


class TestAlertEscalation:
    def test_is_critical_and_escalation_category(self):
        from src.messages import alert_escalation

        text, level, ctx = alert_escalation(15, 12, 15)
        assert level == Level.CRITICAL
        assert ctx is not None
        assert ctx.category == "escalation"

    def test_contains_delay_and_score(self):
        from src.messages import alert_escalation

        text, _, _ = alert_escalation(15, 12, 15)
        assert "15" in text
        assert "12/15" in text

    def test_mentions_escalade_or_critique(self):
        from src.messages import alert_escalation

        text, _, _ = alert_escalation(20, 5, 10)
        assert "scalade" in text.lower() or "critique" in text.lower()

    def test_explains_no_ack_possible(self):
        """S5.3 : pas d'ACK possible sur l'escalade -- le message doit
        expliciter que le seul signal d'arret est le retablissement reel."""
        from src.messages import alert_escalation

        text, _, _ = alert_escalation(15, 12, 15)
        assert "retablissement" in text.lower() or "retabli" in text.lower()

    def test_context_carries_score_and_threshold(self):
        from src.messages import alert_escalation

        _, _, ctx = alert_escalation(15, 8, 15)
        assert ctx.score == 8
        assert ctx.threshold == 15

    def test_under_4096_bytes(self):
        from src.messages import alert_escalation

        text, _, _ = alert_escalation(15, 12, 15)
        assert len(text.encode("utf-8")) <= 4096


# ===================================================================
# Markdown degradable (Q6, PRD Ntfy-first S3.4)
# ===================================================================


class TestMarkdownDegradable:
    """Sous-ensemble autorise : **gras**, listes `-`, blocs de code courts.
    Interdits : tableaux Markdown (|---|) et liens [texte](url) -- le corps
    doit rester lisible en texte brut sur mobile."""

    def _all_template_texts(self):
        from src import messages as m

        peer_info = {
            "status": "healthy",
            "score": 0,
            "gateway": "OK",
            "internet": "3/3",
        }
        return [
            m.startup()[0],
            m.shutdown("arret manuel")[0],
            m.shutdown("crash")[0],
            m.reboot_launching(1, 12, True, 0, 3, 2, peer_info)[0],
            m.reboot_launching(1, 12, True, 0, 3, 2, peer_info, "diagnostic")[0],
            m.recovery_with_reboot("5min", 2, True)[0],
            m.recovery_no_reboot("3min")[0],
            m.isp_outage_detected("30min", 3)[0],
            m.max_reboots_reached(10)[0],
            m.ssh_failure(5, "5min")[0],
            m.divergence_detected(10, True, 0, 0, "OK", "3/3")[0],
            m.api_pause()[0],
            m.api_resume()[0],
            m.api_reboot()[0],
            m.update_available("1.0.0", "1.1.0")[0],
            m.update_success("1.0.0", "1.1.0")[0],
            m.update_failed("1.1.0", "tests echoues")[0],
            m.tplink_reboot("secours-1", "auto")[0],
            m.tplink_reboot_failed("secours-1", "auto")[0],
            m.backup_ok("unifi.unf", 1.0, "/tmp")[0],
            m.backup_failed("erreur")[0],
            m.backup_stale("unifi.unf", 48, 24)[0],
            m.ddns_updated("1.2.3.4", "5.6.7.8", 1, "example.com")[0],
            m.ddns_failed("1.2.3.4", ["erreur"])[0],
            m.alert_escalation(15, 12, 15)[0],
        ]

    def test_no_markdown_table_pattern(self):
        for text in self._all_template_texts():
            assert "|---" not in text and "---|" not in text, (
                f"tableau Markdown detecte : {text!r}"
            )

    def test_no_markdown_link_pattern(self):
        import re

        link_re = re.compile(r"\[.+?\]\(.+?\)")
        for text in self._all_template_texts():
            assert not link_re.search(text), f"lien Markdown detecte : {text!r}"

    def test_no_template_exceeds_4096_bytes_raw(self):
        """Garde-fou : la troncature vit dans _ntfy.py, mais un gabarit
        "nu" ne doit jamais depasser la limite au point de perdre une
        information critique avant meme d'atteindre _truncate_body()."""
        for text in self._all_template_texts():
            assert len(text.encode("utf-8")) <= 4096

    def test_no_leftover_telegram_html_in_source(self):
        """S2 de ce sprint : purger tout rendu HTML oriente Telegram."""
        import inspect
        from src import messages as m

        source = inspect.getsource(m)
        for tag in ("<b>", "</b>", "<i>", "</i>", "<code>", "</code>", "<pre>"):
            assert tag not in source
