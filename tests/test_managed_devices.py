"""Tests pour src/managed_devices.py -- registre des equipements TP-Link
pilotables (A1, Sprint 3).

Driver entierement double (aucun `TplinkDriver` reel, aucun acces reseau) :
`_FakeDriver` expose la meme surface que `RouterDriver` avec des compteurs
d'appels et des retours controlables, pour verifier precisement le cache
(C5's voisin), le verrou par equipement (C5), le simple reessai sur refus de
session, et l'invariant C6 (aucune action destructive automatique / sans
confirmation).

Voir docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/
sprints/03-commandes-management.md et INVARIANTS.md du meme dossier.
"""

import sys
import os
import threading
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from drivers._base import Hop, Readiness, RouterHealth, RouterMetrics, RouterReadiness
from drivers.tplink import ProbeResult


class _FakeDriver:
    """Double de TplinkDriver -- surface RouterDriver, entierement scriptable."""

    vendor = "tplink"

    def __init__(
        self,
        label: str = "mr110-test",
        health_result: RouterHealth | None = None,
        readiness_result: RouterReadiness | None = None,
        metrics_result: RouterMetrics | None = None,
        probe_results=None,  # liste consommee dans l'ordre, dernier repete
        reboot_results=None,  # liste consommee dans l'ordre, dernier repete
    ) -> None:
        self.label = label
        self._health_result = health_result or RouterHealth(
            reachable=True, internet_ok=None, rtt_ms=12.0, failed_hop=None, detail="ok"
        )
        self._readiness_result = readiness_result or RouterReadiness(
            state=Readiness.OK, reasons=()
        )
        self._metrics_result = metrics_result or RouterMetrics(
            rsrp=-95,
            rsrq=-12,
            snr=-20,
            network_type="LTE",
            isp_name="Free",
            rx_speed_bps=0,
            tx_speed_bps=0,
            clients_total=0,
        )
        self._probe_results = list(probe_results or [ProbeResult.OK])
        self._reboot_results = list(
            reboot_results if reboot_results is not None else [True]
        )

        self.health_calls = 0
        self.readiness_calls = 0
        self.metrics_calls = 0
        self.probe_calls = 0
        self.reboot_calls = 0
        self.test_connection_calls = 0

        self._call_log: list[tuple[str, float]] = []
        self._sleep_on_call = 0.0

    def _record(self, name: str) -> None:
        if self._sleep_on_call:
            start = time.monotonic()
            time.sleep(self._sleep_on_call)
            self._call_log.append((f"{name}:start", start))
            self._call_log.append((f"{name}:end", time.monotonic()))

    def health(self) -> RouterHealth:
        self.health_calls += 1
        self._record("health")
        return self._health_result

    def readiness(self) -> RouterReadiness:
        self.readiness_calls += 1
        return self._readiness_result

    def metrics(self) -> RouterMetrics:
        self.metrics_calls += 1
        return self._metrics_result

    def probe_end_to_end(self, record: bool = True) -> ProbeResult:
        self.probe_calls += 1
        idx = min(self.probe_calls - 1, len(self._probe_results) - 1)
        return self._probe_results[idx]

    def reboot(self) -> bool:
        self.reboot_calls += 1
        self._record("reboot")
        idx = min(self.reboot_calls - 1, len(self._reboot_results) - 1)
        return self._reboot_results[idx]

    def test_connection(self) -> bool:
        self.test_connection_calls += 1
        return True


def _make_config(index: int = 1, label: str = "mr110-test"):
    from config import TplinkDeviceConfig

    return TplinkDeviceConfig(
        index=index,
        label=label,
        host="192.168.10.1",
        password="s3cr3t-pwd",
        mode="bridged",
        bridge_host="",
        rsrp_min=-110,
        rsrq_min=-20,
        snr_min=-100,
    )


def _make_registry(driver: _FakeDriver | None = None, devices=None, **kwargs):
    from managed_devices import ManagedDeviceRegistry

    driver = driver or _FakeDriver()
    devices = devices if devices is not None else [_make_config()]
    return ManagedDeviceRegistry(
        devices=devices,
        driver_factory=lambda cfg: driver,
        **kwargs,
    ), driver


# ---------------------------------------------------------------------------
# C1 -- import vendor paresseux (managed_devices ne doit jamais tirer la lib)
# ---------------------------------------------------------------------------


class TestImportVendorParesseux:
    def test_import_managed_devices_sans_lib_vendor(self):
        assert "tplinkrouterc6u" not in sys.modules
        import managed_devices  # noqa: F401

        assert "tplinkrouterc6u" not in sys.modules


# ---------------------------------------------------------------------------
# Aucun equipement declare -- comportement identique a la 1.8
# ---------------------------------------------------------------------------


class TestNoTplinkConfigured:
    def test_no_tplink_configured_list_devices_is_empty(self):
        registry, _ = _make_registry(devices=[])
        assert registry.list_devices() == []

    def test_no_tplink_configured_get_status_returns_none(self):
        registry, _ = _make_registry(devices=[])
        assert registry.get_status("1") is None

    def test_no_tplink_configured_check_returns_none(self):
        registry, _ = _make_registry(devices=[])
        assert registry.check("1") is None

    def test_no_tplink_configured_request_reboot_returns_none(self):
        registry, _ = _make_registry(devices=[])
        assert registry.request_reboot("1", origin="api") is None

    def test_no_tplink_configured_never_builds_a_driver(self):
        built = []

        def factory(cfg):
            built.append(cfg)
            return _FakeDriver()

        from managed_devices import ManagedDeviceRegistry

        registry = ManagedDeviceRegistry(devices=[], driver_factory=factory)
        registry.list_devices()
        registry.get_status("1")
        assert built == []


# ---------------------------------------------------------------------------
# Cache court des lectures
# ---------------------------------------------------------------------------


class TestStatusCache:
    def test_repeated_status_reads_hit_cache_once(self):
        registry, driver = _make_registry(status_cache_ttl=60.0)
        registry.get_status("1")
        registry.get_status("1")
        registry.get_status("1")
        assert driver.health_calls == 1
        assert driver.readiness_calls == 1
        assert driver.metrics_calls == 1

    def test_cache_expires_after_ttl(self):
        registry, driver = _make_registry(status_cache_ttl=0.01)
        registry.get_status("1")
        time.sleep(0.05)
        registry.get_status("1")
        assert driver.health_calls == 2

    def test_force_refresh_bypasses_cache(self):
        registry, driver = _make_registry(status_cache_ttl=60.0)
        registry.get_status("1")
        registry.get_status("1", force=True)
        assert driver.health_calls == 2

    def test_unknown_device_returns_none_without_calling_driver(self):
        registry, driver = _make_registry()
        assert registry.get_status("nope") is None
        assert driver.health_calls == 0

    def test_status_dict_never_includes_password(self):
        registry, _ = _make_registry()
        status = registry.get_status("1")
        assert "password" not in status
        for value in status.values():
            assert value != "s3cr3t-pwd"


# ---------------------------------------------------------------------------
# Verrou par equipement (C5)
# ---------------------------------------------------------------------------


class TestSessionLock:
    """C5 -- pytest -k "session_lock" (voir INVARIANTS.md)."""

    def test_session_lock_concurrent_status_reads_are_serialized(self):
        driver = _FakeDriver()
        driver._sleep_on_call = 0.05
        registry, _ = _make_registry(driver=driver, status_cache_ttl=0.0)

        def worker():
            registry.get_status("1", force=True)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Chaque appel a health() a du dormir 0.05s sous le verrou -- les
        # fenetres [start, end] ne doivent jamais se chevaucher.
        events = sorted(driver._call_log, key=lambda kv: kv[1])
        # reconstruit les paires (start, end) dans l'ordre chronologique
        pairs = []
        pending_start = None
        for name, ts in events:
            if name == "health:start":
                pending_start = ts
            elif name == "health:end" and pending_start is not None:
                pairs.append((pending_start, ts))
                pending_start = None
        assert len(pairs) == 3
        for i in range(len(pairs) - 1):
            assert pairs[i][1] <= pairs[i + 1][0] + 0.001, "sessions chevauchees"

    def test_two_concurrent_devices_do_not_block_each_other(self):
        driver_a = _FakeDriver(label="a")
        driver_b = _FakeDriver(label="b")
        driver_a._sleep_on_call = 0.05
        from managed_devices import ManagedDeviceRegistry

        registry = ManagedDeviceRegistry(
            devices=[
                _make_config(index=1, label="a"),
                _make_config(index=2, label="b"),
            ],
            driver_factory=lambda cfg: driver_a if cfg.index == 1 else driver_b,
        )

        start = time.monotonic()
        t1 = threading.Thread(target=lambda: registry.get_status("1", force=True))
        t2 = threading.Thread(target=lambda: registry.get_status("2", force=True))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        elapsed = time.monotonic() - start
        # Si les deux equipements partageaient le meme verrou, l'appel sur
        # "b" attendrait la fin du sleep de "a". Ici ils sont independants.
        assert elapsed < 0.05 + 0.03


# ---------------------------------------------------------------------------
# Session refusee -- un seul reessai (jamais de boucle)
# ---------------------------------------------------------------------------


class TestSingleRetryOnSessionRefusal:
    def test_check_retries_once_on_unknown_then_succeeds(self):
        driver = _FakeDriver(probe_results=[ProbeResult.UNKNOWN, ProbeResult.OK])
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        assert driver.probe_calls == 2
        assert result["result"] == "ok"

    def test_check_gives_up_after_a_single_retry(self):
        driver = _FakeDriver(
            probe_results=[ProbeResult.UNKNOWN, ProbeResult.UNKNOWN, ProbeResult.OK]
        )
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        # Jamais de boucle : au plus 2 appels, meme si le 3e aurait reussi.
        assert driver.probe_calls == 2
        assert result["result"] == "unknown"

    def test_confirm_reboot_retries_once_on_router_refusal(self):
        driver = _FakeDriver(reboot_results=[False, True])
        registry, _ = _make_registry(driver=driver)
        req = registry.request_reboot("1", origin="api")
        result = registry.confirm_reboot(req["token"], origin="api")
        assert driver.reboot_calls == 2
        assert result["ok"] is True

    def test_confirm_reboot_gives_up_after_a_single_retry(self):
        driver = _FakeDriver(reboot_results=[False, False, True])
        registry, _ = _make_registry(driver=driver)
        req = registry.request_reboot("1", origin="api")
        result = registry.confirm_reboot(req["token"], origin="api")
        assert driver.reboot_calls == 2
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Sonde a la demande -- attache vs data qui passe (C11)
# ---------------------------------------------------------------------------


class TestCheckEndToEnd:
    def test_check_ok_reports_attached_and_data_confirmed(self):
        driver = _FakeDriver(
            health_result=RouterHealth(
                reachable=True, internet_ok=None, rtt_ms=10, failed_hop=None
            ),
            probe_results=[ProbeResult.OK],
        )
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        assert result["attached"] is True
        assert result["data_confirmed"] is True
        assert result["result"] == "ok"

    def test_check_fail_reports_attached_but_no_data(self):
        driver = _FakeDriver(probe_results=[ProbeResult.FAIL, ProbeResult.FAIL])
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        assert result["attached"] is True
        assert result["data_confirmed"] is False
        assert result["result"] == "fail"

    def test_check_leak_never_blames_the_backup_link(self):
        driver = _FakeDriver(probe_results=[ProbeResult.LEAK, ProbeResult.LEAK])
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        assert result["result"] == "leak"
        assert result["data_confirmed"] is False

    def test_check_unreachable_device_reports_not_attached(self):
        driver = _FakeDriver(
            health_result=RouterHealth(
                reachable=False,
                internet_ok=None,
                rtt_ms=None,
                failed_hop=Hop.WIRELESS,
                detail="MR110 injoignable",
            ),
            probe_results=[ProbeResult.UNKNOWN, ProbeResult.UNKNOWN],
        )
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        assert result["attached"] is False

    def test_check_does_not_record_probe_on_real_driver(self):
        """Bouton Verifier : FAIL/LEAK ne doit pas ecrire le cache readiness."""
        from unittest.mock import Mock

        from drivers.tplink import TplinkDriver

        mock_client = Mock()
        mock_client.get_status.return_value = {"total_statistics": 1000}
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
        }
        driver = TplinkDriver(
            host="192.168.10.1",
            password="s3cr3t",
            label="mr110-test",
            client_factory=lambda: mock_client,
            ping_fn=Mock(return_value=(True, 10.0)),
            route_check_fn=Mock(return_value=(True, None)),
            local_command_fn=Mock(return_value=(True, "not-an-ip")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        registry, _ = _make_registry(driver=driver)
        result = registry.check("1")
        assert result["result"] == "fail"
        assert driver._last_probe_result is None


# ---------------------------------------------------------------------------
# C6 -- aucune action destructive automatique / sans confirmation
# ---------------------------------------------------------------------------


class TestNoAutoDestructive:
    """C6 -- pytest -k "no_auto_destructive" (voir INVARIANTS.md)."""

    def test_no_auto_destructive_request_reboot_never_calls_driver_reboot(self):
        registry, driver = _make_registry()
        registry.request_reboot("1", origin="api")
        assert driver.reboot_calls == 0

    def test_no_auto_destructive_check_never_calls_driver_reboot(self):
        registry, driver = _make_registry()
        registry.check("1")
        assert driver.reboot_calls == 0

    def test_no_auto_destructive_get_status_never_calls_driver_reboot(self):
        registry, driver = _make_registry()
        registry.get_status("1")
        assert driver.reboot_calls == 0

    def test_no_auto_destructive_constructing_registry_never_calls_driver_reboot(self):
        registry, driver = _make_registry()
        assert driver.reboot_calls == 0


class TestRequiresConfirmation:
    """C6 -- pytest -k "requires_confirmation" (voir INVARIANTS.md)."""

    def test_requires_confirmation_reboot_refused_without_token(self):
        registry, driver = _make_registry()
        result = registry.confirm_reboot("does-not-exist", origin="api")
        assert result["ok"] is False
        assert result["executed"] is False
        assert driver.reboot_calls == 0

    def test_reboot_refused_with_expired_token(self):
        registry, driver = _make_registry()
        req = registry.request_reboot("1", origin="api")
        import confirm

        with confirm._lock:
            entry = confirm._pending[req["token"]]
            confirm._pending[req["token"]] = entry.__class__(
                action=entry.action, context=entry.context, expires_at=0.0
            )
        result = registry.confirm_reboot(req["token"], origin="api")
        assert result["ok"] is False
        assert driver.reboot_calls == 0

    def test_reboot_refused_when_token_reused(self):
        registry, driver = _make_registry()
        req = registry.request_reboot("1", origin="api")
        first = registry.confirm_reboot(req["token"], origin="api")
        second = registry.confirm_reboot(req["token"], origin="api")
        assert first["ok"] is True
        assert second["ok"] is False
        assert second["executed"] is False
        assert driver.reboot_calls == 1

    def test_reboot_executed_and_traced_with_origin_on_valid_token(self):
        from events import EventLog

        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, driver = _make_registry(event_log=event_log)
        req = registry.request_reboot("1", origin="api")
        result = registry.confirm_reboot(req["token"], origin="api")
        assert result["ok"] is True
        assert driver.reboot_calls == 1
        events_recorded = event_log.get_all()
        assert len(events_recorded) == 1
        assert events_recorded[0]["type"] == "tplink_reboot"
        assert events_recorded[0]["data"]["origin"] == "api"

    def test_reboot_failure_traced_as_warning_never_critical(self):
        from events import EventLog
        from notifier._types import Level

        event_log = EventLog(max_events=10, persist_path="/dev/null")
        driver = _FakeDriver(reboot_results=[False, False])
        registry, _ = _make_registry(driver=driver, event_log=event_log)
        req = registry.request_reboot("1", origin="api")

        captured = {}

        def fake_notify(text, level, ctx=None):
            captured["level"] = level
            return {}

        import managed_devices

        original_notify = managed_devices.notify
        managed_devices.notify = fake_notify
        try:
            result = registry.confirm_reboot(req["token"], origin="api")
        finally:
            managed_devices.notify = original_notify

        assert result["ok"] is False
        assert captured["level"] == Level.WARNING
        assert captured["level"] != Level.CRITICAL
        events_recorded = event_log.get_all()
        assert events_recorded[0]["type"] == "tplink_reboot_failed"


# ---------------------------------------------------------------------------
# Avertissement trafic
# ---------------------------------------------------------------------------


class TestTrafficWarning:
    def test_warning_present_when_traffic_flowing(self):
        driver = _FakeDriver(
            metrics_result=RouterMetrics(
                rx_speed_bps=5000, tx_speed_bps=100, clients_total=2
            )
        )
        registry, _ = _make_registry(driver=driver)
        req = registry.request_reboot("1", origin="api")
        assert req["warning"] is True
        assert req["warning_reason"]

    def test_no_warning_when_idle(self):
        driver = _FakeDriver(
            metrics_result=RouterMetrics(
                rx_speed_bps=0, tx_speed_bps=0, clients_total=0
            )
        )
        registry, _ = _make_registry(driver=driver)
        req = registry.request_reboot("1", origin="api")
        assert req["warning"] is False


# ---------------------------------------------------------------------------
# Ntfy-first S2 -- boutons Actions publies EN PLUS du dict retourne par
# request_reboot() (chemin API/dashboard existant), via une fonction `send`
# injectee (jamais d'import direct de _ntfy dans ce module).
# ---------------------------------------------------------------------------


class TestNtfySendInjection:
    def test_request_reboot_calls_injected_ntfy_send_with_expected_args(self):
        calls = []

        def fake_ntfy_send(label, warning, warning_reason, action, token):
            calls.append((label, warning, warning_reason, action, token))
            return True

        registry, _ = _make_registry(ntfy_send=fake_ntfy_send)
        result = registry.request_reboot("1", origin="api")

        assert len(calls) == 1
        label, warning, warning_reason, action, token = calls[0]
        assert label == "mr110-test"
        assert warning is False
        assert action == "tplink_reboot"
        assert token == result["token"]

    def test_request_reboot_never_fails_when_no_ntfy_send_injected(self):
        """Par defaut (tests, Ntfy non configure) : no-op silencieux."""
        registry, _ = _make_registry()
        result = registry.request_reboot("1", origin="api")
        assert result["token"]

    def test_request_reboot_survives_ntfy_send_exception(self):
        """Une erreur de publication Ntfy ne doit jamais empecher l'emission
        du jeton -- le chemin API/dashboard JSON doit rester utilisable."""

        def failing_ntfy_send(*args, **kwargs):
            raise RuntimeError("ntfy down")

        registry, _ = _make_registry(ntfy_send=failing_ntfy_send)
        result = registry.request_reboot("1", origin="api")
        assert result["token"]

    def test_set_ntfy_send_is_idempotent_like_set_event_log(self):
        import managed_devices

        def fake_send(*args, **kwargs):
            return True

        managed_devices.registry.set_ntfy_send(fake_send)
        assert managed_devices.registry._ntfy_send is fake_send
        managed_devices.registry.set_ntfy_send(None)
        assert managed_devices.registry._ntfy_send is None

    def test_origin_agnostic_path_unaffected_by_ntfy_injection(self):
        """Invariant du sprint : le dict retourne par request_reboot()
        (chemin API/dashboard) reste identique, que ntfy_send soit injecte
        ou non, quelle que soit l'origine de l'appel."""
        calls = []

        def fake_ntfy_send(*args, **kwargs):
            calls.append(args)
            return True

        registry, _ = _make_registry(ntfy_send=fake_ntfy_send)
        result = registry.request_reboot("1", origin="api")
        assert set(result.keys()) == {
            "token",
            "device_id",
            "label",
            "warning",
            "warning_reason",
        }
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Logout garanti -- delegue au driver (deja garanti par _with_session, teste
# ici pour la couverture de l'invariant du cote registre)
# ---------------------------------------------------------------------------


class TestRebootConfirmLogoutGuaranteedDelegatesToDriver:
    def test_reboot_confirm_does_not_bypass_driver_session_handling(self):
        """managed_devices n'ouvre jamais de session lui-meme : il delegue
        entierement a driver.reboot(), qui garantit logout() en interne
        (voir tests/test_drivers_tplink.py, deja couvert au Sprint 2)."""
        registry, driver = _make_registry()
        req = registry.request_reboot("1", origin="api")
        registry.confirm_reboot(req["token"], origin="api")
        assert driver.reboot_calls >= 1
        # Aucune methode de session bas niveau (authorize/logout) n'existe
        # sur le registre -- seule l'API haut niveau du driver est utilisee.
        assert not hasattr(registry, "authorize")
        assert not hasattr(registry, "logout")


# ---------------------------------------------------------------------------
# Bootstrap -- point d'entree production (event_log)
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_bootstrap_sets_event_log_on_default_registry(self):
        import managed_devices

        fake_log = object()
        managed_devices.bootstrap(fake_log)
        assert managed_devices.registry._event_log is fake_log
        managed_devices.bootstrap(None)


# ---------------------------------------------------------------------------
# messages.py -- notify() tuples pour tplink_reboot / tplink_reboot_failed
# ---------------------------------------------------------------------------


class TestMessagesTplinkReboot:
    def test_tplink_reboot_is_info_never_critical(self):
        from messages import tplink_reboot
        from notifier._types import Level

        text, level, ctx = tplink_reboot("mr110-dijon", "api")
        assert level == Level.INFO
        assert "mr110-dijon" in text

    def test_tplink_reboot_failed_is_warning_never_critical(self):
        from messages import tplink_reboot_failed
        from notifier._types import Level

        text, level, ctx = tplink_reboot_failed("mr110-dijon", "api")
        assert level == Level.WARNING
        assert level != Level.CRITICAL


# ---------------------------------------------------------------------------
# events.py -- constantes de traçabilite
# ---------------------------------------------------------------------------


class TestEventsConstants:
    def test_tplink_reboot_constants_exist(self):
        from events import TPLINK_REBOOT, TPLINK_REBOOT_FAILED

        assert TPLINK_REBOOT == "tplink_reboot"
        assert TPLINK_REBOOT_FAILED == "tplink_reboot_failed"


# ---------------------------------------------------------------------------
# config.py -- helper de masquage des secrets
# ---------------------------------------------------------------------------


class TestRedactSecrets:
    def test_redacts_password_token_key_webhook(self):
        from config import redact_secrets

        data = {
            "TPLINK_1_PASSWORD": "hunter2",
            "NTFY_TOKEN": "abc123",
            "CLOUDFLARE_API_TOKEN": "xyz",
            "SOME_WEBHOOK_URL": "https://example.com/secret",
            "SOME_KEY": "k",
            "CHECK_INTERVAL": 30,
        }
        redacted = redact_secrets(data)
        assert redacted["TPLINK_1_PASSWORD"] != "hunter2"
        assert redacted["NTFY_TOKEN"] != "abc123"
        assert redacted["CLOUDFLARE_API_TOKEN"] != "xyz"
        assert redacted["SOME_WEBHOOK_URL"] != "https://example.com/secret"
        assert redacted["SOME_KEY"] != "k"
        assert redacted["CHECK_INTERVAL"] == 30

    def test_does_not_mutate_input(self):
        from config import redact_secrets

        data = {"TPLINK_1_PASSWORD": "hunter2"}
        redact_secrets(data)
        assert data["TPLINK_1_PASSWORD"] == "hunter2"

    def test_empty_secret_value_stays_falsy(self):
        from config import redact_secrets

        data = {"TPLINK_1_PASSWORD": ""}
        redacted = redact_secrets(data)
        assert not redacted["TPLINK_1_PASSWORD"]


# ---------------------------------------------------------------------------
# Secrets jamais exposes -- pytest -k "secret_not_exposed" (voir INVARIANTS.md)
# Couvre les 3 whitelists divergentes de http_server.py (_handle_config,
# _EXPORT_SAFE_KEYS, _SAFE_RELOAD_KEYS) ET les reponses /api/tplink/*.
# ---------------------------------------------------------------------------


class TestSecretNotExposed:
    def test_secret_not_exposed_in_export_and_reload_whitelists(self):
        import http_server
        from state import StateHolder

        handler_class = http_server._make_handler_class(StateHolder())
        assert not any("TPLINK" in key for key in handler_class._EXPORT_SAFE_KEYS)
        assert not any("TPLINK" in key for key in handler_class._SAFE_RELOAD_KEYS)

    def test_secret_not_exposed_in_config_endpoint_response(self):
        import json as _json
        import threading as _threading
        import urllib.request as _ur
        from http.server import HTTPServer

        import http_server
        from state import StateHolder

        holder = StateHolder()
        handler_class = http_server._make_handler_class(holder)
        server = HTTPServer(("127.0.0.1", 0), handler_class)
        port = server.server_address[1]
        thread = _threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with _ur.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as resp:
                body_text = resp.read().decode("utf-8")
        finally:
            server.shutdown()
        assert "TPLINK" not in body_text
        assert _json.loads(
            body_text
        )  # reponse bien formee malgre l'assertion ci-dessus

    def test_secret_not_exposed_in_tplink_status_response(self):
        import json as _json

        registry, _ = _make_registry()
        status = registry.get_status("1")
        assert "password" not in status
        assert "s3cr3t-pwd" not in _json.dumps(status)

    def test_secret_not_exposed_in_tplink_list_response(self):
        import json as _json

        registry, _ = _make_registry()
        devices = registry.list_devices()
        assert "s3cr3t-pwd" not in _json.dumps(devices)
