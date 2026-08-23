"""Tests pour `POST /api/confirm/<action>/<jeton>` -- endpoint de
confirmation a capacite (PRD Ntfy-first, Sprint 2, coeur securite).

Couvre :
- le routage de l'endpoint dans `http_server.py` (avant `_check_auth()`,
  forme stricte a 2 segments, reponse muette D6, masquage D4, rate limiting
  D3, evenements systematiques D7) ;
- l'integration bout-en-bout avec `managed_devices.ManagedDeviceRegistry`
  (jeton valide -> reboot reellement declenche sur un driver double,
  visible dans `/api/events`) ;
- les boutons `Actions` Ntfy publies par `notifier._ntfy.send_confirm_actions`
  (gates INVARIANTS.md `no-api-token-in-notification` et
  `confirm-urls-tailscale-only`).

Design volontaire : les tests HTTP les plus critiques (succes, rejeu,
expiration, mauvaise action, annulation) utilisent un VRAI
`ManagedDeviceRegistry` branche sur un driver double (`_FakeDriver`, meme
esprit que `tests/test_managed_devices.py`) plutot qu'un registre entierement
mocke -- l'objectif du critere d'acceptation 13 est de prouver qu'un appel
HTTP declenche *reellement* `driver.reboot()`, pas seulement qu'un mock a ete
appele.
"""

import inspect
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest import mock

import pytest

from drivers._base import Readiness, RouterHealth, RouterMetrics, RouterReadiness
from src.http_server import _make_handler_class
from src.state import StateHolder


# ---------------------------------------------------------------------------
# Double de driver (meme esprit que tests/test_managed_devices.py, reduit au
# strict necessaire pour request_reboot()/confirm_reboot()).
# ---------------------------------------------------------------------------


class _FakeDriver:
    vendor = "tplink"

    def __init__(self, reboot_result: bool = True) -> None:
        self.reboot_calls = 0
        self._reboot_result = reboot_result

    def health(self) -> RouterHealth:
        return RouterHealth(
            reachable=True, internet_ok=None, rtt_ms=12.0, failed_hop=None, detail="ok"
        )

    def readiness(self) -> RouterReadiness:
        return RouterReadiness(state=Readiness.OK, reasons=())

    def metrics(self) -> RouterMetrics:
        return RouterMetrics(rx_speed_bps=0, tx_speed_bps=0, clients_total=0)

    def probe_end_to_end(self):
        raise NotImplementedError("non utilise par ces tests")

    def reboot(self) -> bool:
        self.reboot_calls += 1
        return self._reboot_result


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


def _make_real_registry(driver=None, event_log=None, ntfy_send=None):
    """Construit un VRAI ManagedDeviceRegistry (pas un mock) branche sur un
    driver double -- voir docstring du module."""
    from managed_devices import ManagedDeviceRegistry

    driver = driver or _FakeDriver()
    registry = ManagedDeviceRegistry(
        devices=[_make_config()],
        driver_factory=lambda cfg: driver,
        event_log=event_log,
        ntfy_send=ntfy_send,
    )
    return registry, driver


def _install_registry(registry):
    import managed_devices

    original = managed_devices.registry
    managed_devices.registry = registry
    return original


def _restore_registry(original):
    import managed_devices

    managed_devices.registry = original


def _make_server(holder, event_log=None):
    handler = _make_handler_class(holder, event_log)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, f"http://127.0.0.1:{port}"


def _post(url: str, timeout: int = 2) -> tuple[int, dict]:
    """POST sans aucun en-tete Authorization -- c'est justement le point de
    l'endpoint /api/confirm/*."""
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture(autouse=True)
def _reset_confirm_state():
    import confirm

    confirm._pending.clear()
    confirm._recent_success.clear()
    confirm._recent_success_logged.clear()
    yield
    confirm._pending.clear()
    confirm._recent_success.clear()
    confirm._recent_success_logged.clear()


# ---------------------------------------------------------------------------
# Fixture partagee : serveur + registre reel branche sur un driver double.
# ---------------------------------------------------------------------------


class _ConfirmEndpointBase:
    @pytest.fixture(autouse=True)
    def _start(self, tmp_path):
        from events import EventLog
        import managed_devices

        self.driver = _FakeDriver()
        self.event_log = EventLog(
            max_events=50, persist_path=str(tmp_path / "events.json")
        )
        self.registry, self.driver = _make_real_registry(
            driver=self.driver, event_log=self.event_log
        )
        self._original_registry = _install_registry(self.registry)
        self._original_ntfy_send = managed_devices.registry._ntfy_send

        self.holder = StateHolder()
        self.server, self.port, self.base_url = _make_server(
            self.holder, self.event_log
        )
        yield
        self.server.shutdown()
        _restore_registry(self._original_registry)


# ---------------------------------------------------------------------------
# Forme stricte du chemin -- exactement 2 segments (action, jeton)
# ---------------------------------------------------------------------------


class TestConfirmEndpointRouting(_ConfirmEndpointBase):
    def test_missing_token_returns_404(self):
        status, body = _post(f"{self.base_url}/api/confirm/tplink_reboot/")
        assert status == 404
        assert body == {"error": "unknown or expired"}

    def test_extra_segment_returns_404(self):
        status, body = _post(f"{self.base_url}/api/confirm/tplink_reboot/abc/extra")
        assert status == 404

    def test_query_string_ignored_not_used_as_authorization(self):
        """La query string ne doit jamais servir de canal d'autorisation --
        un jeton invalide dans le chemin reste refuse, meme accompagne d'une
        query string qui ressemblerait a un jeton valide."""
        req = self.registry.request_reboot("1", origin="test")
        status, body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/wrong-token"
            f"?token={req['token']}"
        )
        assert status == 404
        assert self.driver.reboot_calls == 0


# ---------------------------------------------------------------------------
# L'endpoint est exempte de _check_auth() -- aucun en-tete Authorization
# ---------------------------------------------------------------------------


class TestConfirmEndpointBypassesCheckAuth(_ConfirmEndpointBase):
    def test_no_authorization_header_still_processed(self):
        """Sans API_TOKEN configure, un endpoint normal repondrait 403 --
        celui-ci doit repondre 404 (jeton inconnu), jamais 401/403."""
        import src.http_server as _http_server_mod

        original_token = _http_server_mod._config.API_TOKEN
        _http_server_mod._config.API_TOKEN = ""
        try:
            status, _ = _post(f"{self.base_url}/api/confirm/tplink_reboot/bogus")
        finally:
            _http_server_mod._config.API_TOKEN = original_token
        assert status not in (401, 403)
        assert status == 404

    def test_valid_token_succeeds_without_any_auth_header(self):
        req = self.registry.request_reboot("1", origin="test")
        status, body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert status == 200
        assert body == {"ok": True}


# ---------------------------------------------------------------------------
# Test d'inventaire des routes -- un seul chemin POST bypass _check_auth()
# ---------------------------------------------------------------------------


class TestRouteInventoryOnlyConfirmBypassesAuth:
    def test_only_confirm_prefix_precedes_check_auth_call_in_source(self):
        """Lecture structurelle de do_POST() : un seul bloc conditionnel doit
        exister avant le premier appel a self._check_auth(), et il doit
        cibler /api/confirm/."""
        handler_cls = _make_handler_class(StateHolder())
        source = inspect.getsource(handler_cls.do_POST)
        # On coupe juste avant la ligne qui *appelle* _check_auth() (le
        # "if not self._check_auth():" lui-meme ne doit pas etre compte
        # comme un bypass -- c'est la garde normale de toutes les autres
        # routes).
        before_auth, sep, _after_auth = source.partition("if not self._check_auth()")
        assert sep, "aucun garde 'if not self._check_auth()' trouve dans do_POST"
        assert before_auth.count("if ") == 1, (
            "plus d'un bloc conditionnel bypass _check_auth() :\n" + before_auth
        )
        assert "/api/confirm/" in before_auth

    def test_all_other_post_routes_require_auth_behaviorally(self):
        """Complement comportemental : chaque route POST connue (hors
        /api/confirm/*) doit refuser une requete sans jeton (401/403)."""
        holder = StateHolder()
        handler = _make_handler_class(holder)
        server = HTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        try:
            for path in (
                "/api/pause",
                "/api/resume",
                "/api/reboot",
                "/api/ddns/update",
                "/api/tailscale/sync",
                "/api/backup/unifi",
                "/api/maintenance",
                "/api/config/reload",
                "/api/tplink/1/check",
                "/api/tplink/1/reboot",
            ):
                status, _ = _post(f"{base_url}{path}")
                assert status in (401, 403), f"{path} -> {status} (attendu 401/403)"
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Flux reussi -- declenche reellement le reboot via le driver double
# ---------------------------------------------------------------------------


class TestConfirmEndpointSuccessFlow(_ConfirmEndpointBase):
    def test_valid_token_executes_reboot_and_records_confirm_accepted(self):
        req = self.registry.request_reboot("1", origin="test")
        status, body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert status == 200
        assert body == {"ok": True}
        assert self.driver.reboot_calls == 1

        events = self.event_log.get_all()
        types = [e["type"] for e in events]
        assert "confirm_accepted" in types
        accepted = next(e for e in events if e["type"] == "confirm_accepted")
        assert accepted["data"]["action"] == "tplink_reboot"
        # Le jeton n'apparait JAMAIS dans les donnees de l'evenement.
        assert req["token"] not in json.dumps(accepted)

    def test_confirm_accepted_visible_via_api_events(self):
        """Critere d'acceptation 13 -- consultable via /api/events."""
        req = self.registry.request_reboot("1", origin="test")
        _post(f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}")

        with urllib.request.urlopen(f"{self.base_url}/api/events", timeout=2) as resp:
            events = json.loads(resp.read().decode("utf-8"))
        assert any(e["type"] == "confirm_accepted" for e in events)


# ---------------------------------------------------------------------------
# Rejeu -- usage unique
# ---------------------------------------------------------------------------


class TestConfirmEndpointReplay(_ConfirmEndpointBase):
    """Fenetre d'idempotence (~30s, correctif decouvert au test E2E reel du
    2026-08-23) : l'app ntfy iOS envoie ~10 POST identiques en ~20ms pour un
    seul appui de bouton. Avant le correctif, 1 requete reussissait et les 9
    autres echouaient (jeton deja consomme), declenchant quasi a coup sur le
    rate limiter D3 -- faux `confirm_bruteforce` a chaque appui legitime."""

    def test_replayed_token_within_window_returns_ok_without_reexecuting(self):
        req = self.registry.request_reboot("1", origin="test")
        first_status, first_body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        second_status, second_body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert first_status == 200
        assert first_body == {"ok": True}
        assert second_status == 200
        assert second_body == {"ok": True}
        assert self.driver.reboot_calls == 1  # une seule execution reelle

        types = [e["type"] for e in self.event_log.get_all()]
        assert types.count("confirm_accepted") == 1
        assert types.count("confirm_rejected") == 0
        assert types.count("confirm_replayed") == 1

    def test_replay_burst_of_ten_returns_ok_with_single_execution_and_no_rate_limit(
        self,
    ):
        """Reproduit le bug reel : ~10 POST identiques en rafale pour un
        seul appui. Doit produire exactement 1 execution et 10 reponses 200,
        sans compter le moindre echec du rate limiter D3."""
        req = self.registry.request_reboot("1", origin="test")
        statuses = []
        for _ in range(10):
            status, body = _post(
                f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
            )
            statuses.append((status, body))

        assert all(s == 200 and b == {"ok": True} for s, b in statuses)
        assert self.driver.reboot_calls == 1

        # Une confirmation legitime supplementaire (nouveau jeton) ne doit
        # jamais etre bloquee par le rate limiter -- preuve que la rafale de
        # rejeux n'a rien compte comme echec.
        req2 = self.registry.request_reboot("1", origin="test")
        status2, body2 = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req2['token']}"
        )
        assert status2 == 200
        assert body2 == {"ok": True}
        assert self.driver.reboot_calls == 2

    def test_replay_after_idempotency_window_expires_returns_404(self):
        """Passe la fenetre d'idempotence (~30s) sans attendre reellement :
        le jeton, deja consomme, redevient un jeton "inconnu" ordinaire --
        404, compte normalement (meme technique que TestConfirmEndpointExpired
        pour CONFIRM_TTL)."""
        import confirm

        req = self.registry.request_reboot("1", origin="test")
        first_status, _ = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert first_status == 200

        token_hash = confirm._hash_token(req["token"])
        with confirm._recent_lock:
            entry = confirm._recent_success[token_hash]
            confirm._recent_success[token_hash] = entry.__class__(
                action=entry.action, expires_at=0.0
            )

        second_status, second_body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert second_status == 404
        assert second_body == {"error": "unknown or expired"}
        assert self.driver.reboot_calls == 1  # toujours pas de deuxieme reboot

    def test_unknown_token_still_fails_and_counts_as_normal_failure(self):
        """Un jeton qui n'a jamais existe (jamais dans la fenetre
        d'idempotence) reste 404 et compte toujours comme un echec normal --
        le correctif ne doit pas affaiblir le rate limiting sur du
        bruteforce reel (voir aussi TestConfirmEndpointRateLimit)."""
        status, body = _post(f"{self.base_url}/api/confirm/tplink_reboot/never-existed")
        assert status == 404
        assert body == {"error": "unknown or expired"}

        types = [e["type"] for e in self.event_log.get_all()]
        assert types.count("confirm_rejected") == 1
        assert types.count("confirm_replayed") == 0


# ---------------------------------------------------------------------------
# Expiration -- TTL court injecte, pas d'attente reelle
# ---------------------------------------------------------------------------


class TestConfirmEndpointExpired(_ConfirmEndpointBase):
    def test_expired_token_fails_and_never_reboots(self):
        import confirm

        req = self.registry.request_reboot("1", origin="test")
        # Force l'expiration sans attendre CONFIRM_TTL reel (meme technique
        # que tests/test_managed_devices.py::test_reboot_refused_with_expired_token).
        with confirm._lock:
            entry = confirm._pending[req["token"]]
            confirm._pending[req["token"]] = entry.__class__(
                action=entry.action, context=entry.context, expires_at=0.0
            )

        status, body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert status == 404
        assert body == {"error": "unknown or expired"}
        assert self.driver.reboot_calls == 0


# ---------------------------------------------------------------------------
# Mauvaise action dans l'URL
# ---------------------------------------------------------------------------


class TestConfirmEndpointWrongAction(_ConfirmEndpointBase):
    def test_valid_token_wrong_action_in_url_fails(self):
        req = self.registry.request_reboot("1", origin="test")
        status, body = _post(
            f"{self.base_url}/api/confirm/some_other_action/{req['token']}"
        )
        assert status == 404
        assert self.driver.reboot_calls == 0

    def test_token_consumed_even_when_action_is_wrong(self):
        """Meme comportement que confirm.validate() : le pop est
        inconditionnel, donc un jeton presente sur la mauvaise action est
        tout de meme brule -- la bonne action ne peut plus etre confirmee
        ensuite."""
        req = self.registry.request_reboot("1", origin="test")
        _post(f"{self.base_url}/api/confirm/some_other_action/{req['token']}")
        status, _ = _post(f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}")
        assert status == 404
        assert self.driver.reboot_calls == 0


# ---------------------------------------------------------------------------
# Bouton "Annuler" -- consomme le jeton sans jamais executer
# ---------------------------------------------------------------------------


class TestConfirmEndpointCancel(_ConfirmEndpointBase):
    def test_cancel_action_invalidates_pending_token(self):
        req = self.registry.request_reboot("1", origin="test")
        cancel_status, cancel_body = _post(
            f"{self.base_url}/api/confirm/cancel/{req['token']}"
        )
        # D6 -- reponse muette : meme forme d'echec qu'un jeton inconnu.
        assert cancel_status == 404
        assert cancel_body == {"error": "unknown or expired"}
        assert self.driver.reboot_calls == 0

        # Le jeton est bien consomme : la vraie confirmation ne marche plus.
        confirm_status, _ = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert confirm_status == 404
        assert self.driver.reboot_calls == 0


# ---------------------------------------------------------------------------
# D3 -- rate limiting par IP
# ---------------------------------------------------------------------------


class TestConfirmEndpointRateLimit(_ConfirmEndpointBase):
    def test_exceeding_failure_threshold_returns_429_and_bruteforce_event(self):
        import src.http_server as _http_server_mod

        max_failures = _http_server_mod._config.CONFIRM_RATE_LIMIT_MAX_FAILURES
        assert max_failures >= 10, "D3 exige un minimum de 10 echecs/minute/IP"

        statuses = []
        for _ in range(max_failures):
            status, _ = _post(f"{self.base_url}/api/confirm/tplink_reboot/bogus")
            statuses.append(status)
        # Les max_failures premieres tentatives sont des echecs "normaux".
        assert all(s == 404 for s in statuses)

        blocked_status, blocked_body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/bogus"
        )
        assert blocked_status == 429
        assert "error" in blocked_body

        events = self.event_log.get_all()
        assert any(e["type"] == "confirm_bruteforce" for e in events)

    def test_rate_limit_does_not_block_a_valid_confirmation_from_same_ip_before_threshold(
        self,
    ):
        """Quelques echecs isoles (sous le seuil) ne doivent jamais bloquer
        une confirmation legitime qui suit."""
        for _ in range(3):
            _post(f"{self.base_url}/api/confirm/tplink_reboot/bogus")

        req = self.registry.request_reboot("1", origin="test")
        status, body = _post(
            f"{self.base_url}/api/confirm/tplink_reboot/{req['token']}"
        )
        assert status == 200
        assert body == {"ok": True}


# ---------------------------------------------------------------------------
# D4 -- jamais de jeton en clair dans les journaux
# ---------------------------------------------------------------------------


class TestConfirmEndpointLogMasking:
    def test_token_masked_even_at_debug_level(self, caplog):
        import logging

        handler_cls = _make_handler_class(StateHolder())
        instance = handler_cls.__new__(handler_cls)
        secret_token = "AbCdEf0123456789-_XyZQwErTyUiOpAsDfGhJkLzXcVbNm"

        with caplog.at_level(logging.DEBUG):
            instance.log_message(
                '"%s" %s %s',
                f"POST /api/confirm/tplink_reboot/{secret_token} HTTP/1.1",
                "200",
                "-",
            )

        full_output = "\n".join(r.getMessage() for r in caplog.records)
        assert secret_token not in full_output
        assert "/api/confirm/tplink_reboot/***" in full_output

    def test_masking_regex_does_not_touch_unrelated_paths(self, caplog):
        import logging

        handler_cls = _make_handler_class(StateHolder())
        instance = handler_cls.__new__(handler_cls)

        with caplog.at_level(logging.DEBUG):
            instance.log_message('"%s" %s %s', "GET /api/state HTTP/1.1", "200", "-")

        full_output = "\n".join(r.getMessage() for r in caplog.records)
        assert "/api/state" in full_output


# ---------------------------------------------------------------------------
# D5 -- CRITICAL au demarrage si API_TOKEN vide et Ntfy configure
# ---------------------------------------------------------------------------


class TestCheckAuthUsesConstantTimeComparison:
    """D2, second volet : `_check_auth()` doit aussi utiliser
    `hmac.compare_digest` pour comparer `API_TOKEN`, pas `==` (dette
    existante, corrigee au passage). Verifie par lecture (source) ET par
    test (spy sur l'appel reel)."""

    def test_check_auth_source_uses_hmac_compare_digest(self):
        handler_cls = _make_handler_class(StateHolder())
        source = inspect.getsource(handler_cls._check_auth)
        assert "hmac.compare_digest" in source
        assert "auth ==" not in source

    def test_check_auth_actually_calls_hmac_compare_digest(self):
        import hmac as hmac_mod
        import src.http_server as _http_server_mod

        original_token = _http_server_mod._config.API_TOKEN
        _http_server_mod._config.API_TOKEN = "test-secret-token"
        holder = StateHolder()
        handler_cls = _make_handler_class(holder)
        server = HTTPServer(("127.0.0.1", 0), handler_cls)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(
                _http_server_mod.hmac,
                "compare_digest",
                wraps=hmac_mod.compare_digest,
            ) as spy:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/pause", data=b"", method="POST"
                )
                req.add_header("Authorization", "Bearer test-secret-token")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    assert resp.status == 200
            spy.assert_called_once_with(
                "Bearer test-secret-token", "Bearer test-secret-token"
            )
        finally:
            server.shutdown()
            _http_server_mod._config.API_TOKEN = original_token


class TestApiTokenMissingCriticalGuard:
    def test_critical_logged_when_api_token_empty_and_ntfy_configured(self, caplog):
        import logging
        import src.http_server as _http_server_mod

        original_token = _http_server_mod._config.API_TOKEN
        _http_server_mod._config.API_TOKEN = ""
        holder = StateHolder()
        try:
            with (
                mock.patch("notifier._ntfy.is_configured", return_value=True),
                caplog.at_level(logging.CRITICAL),
            ):
                thread = _http_server_mod.start_http_server(holder, 0)
            assert thread is not None
        finally:
            _http_server_mod._config.API_TOKEN = original_token

        assert any(
            "API_TOKEN" in r.getMessage() and r.levelname == "CRITICAL"
            for r in caplog.records
        )

    def test_no_critical_when_api_token_set(self, caplog):
        import logging
        import src.http_server as _http_server_mod

        original_token = _http_server_mod._config.API_TOKEN
        _http_server_mod._config.API_TOKEN = "some-token"
        holder = StateHolder()
        try:
            with (
                mock.patch("notifier._ntfy.is_configured", return_value=True),
                caplog.at_level(logging.CRITICAL),
            ):
                _http_server_mod.start_http_server(holder, 0)
        finally:
            _http_server_mod._config.API_TOKEN = original_token

        assert not any(r.levelname == "CRITICAL" for r in caplog.records)


# ---------------------------------------------------------------------------
# notifier._ntfy.send_confirm_actions -- gates INVARIANTS.md
# ---------------------------------------------------------------------------


def _mock_response(status: int = 200):
    resp = mock.MagicMock()
    resp.status = status
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


_BASE_NTFY_PATCHES = {
    "NTFY_URL": "http://127.0.0.1:7171",
    "NTFY_TOPIC": "vigil-dijon",
    "NTFY_TOPIC_OPS": "vigil-ops",
    "NTFY_TIMEOUT": 5,
    "NTFY_TOKEN": "",
    "HTTP_PORT": 9000,
    "INSTANCE_ID": "nice_master",
}


def _patch_ntfy_config(**overrides):
    cfg = {**_BASE_NTFY_PATCHES, **overrides}
    return [mock.patch(f"src.notifier._ntfy.{k}", v) for k, v in cfg.items()]


def _call_send_confirm_actions(overrides=None, **kwargs):
    from src.notifier._ntfy import send_confirm_actions

    resp = _mock_response(200)
    patches = _patch_ntfy_config(**(overrides or {}))
    with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
        for p in patches:
            p.start()
        try:
            defaults = dict(
                label="mr110-nice",
                warning=False,
                warning_reason=None,
                action="tplink_reboot",
                token="fake-capability-token-value",
            )
            defaults.update(kwargs)
            result = send_confirm_actions(**defaults)
        finally:
            for p in patches:
                p.stop()
    return result, mock_open


class TestNtfyNoSecretInPayload:
    """Gate INVARIANTS.md `no-api-token-in-notification` -- API_TOKEN n'est
    JAMAIS un secret de notification (c'est la cle du systeme). On verifie
    a la fois le message simple (`send`, sans boutons) et le message avec
    boutons (`send_confirm_actions`)."""

    _FAKE_API_TOKEN = "SUPER-SECRET-API-TOKEN-DO-NOT-LEAK-9f8e7d6c"

    def test_send_confirm_actions_never_contains_api_token(self):
        with mock.patch("src.config.API_TOKEN", self._FAKE_API_TOKEN):
            _, mock_open = _call_send_confirm_actions()
        req = mock_open.call_args[0][0]
        assert self._FAKE_API_TOKEN not in req.data.decode("utf-8")
        assert self._FAKE_API_TOKEN not in json.dumps(dict(req.header_items()))
        assert req.get_header("Authorization") is None  # NTFY_TOKEN vide ici

    def test_send_confirm_actions_no_authorization_header_in_actions_string(self):
        """Regle absolue PRD S4.2.1 : jamais `headers.Authorization=` dans le
        bouton Actions lui-meme."""
        _, mock_open = _call_send_confirm_actions()
        req = mock_open.call_args[0][0]
        actions_header = req.get_header("Actions")
        assert "Authorization" not in actions_header
        assert "headers." not in actions_header

    def test_plain_send_never_contains_api_token(self):
        from src.notifier._ntfy import send
        from src.notifier._types import Level

        with mock.patch("src.config.API_TOKEN", self._FAKE_API_TOKEN):
            patches = _patch_ntfy_config()
            resp = _mock_response(200)
            with mock.patch("urllib.request.urlopen", return_value=resp) as mock_open:
                for p in patches:
                    p.start()
                try:
                    send("test message", Level.INFO, None, "vigil-nice-guardian", "now")
                finally:
                    for p in patches:
                        p.stop()
        req = mock_open.call_args[0][0]
        assert self._FAKE_API_TOKEN not in req.data.decode("utf-8")
        assert self._FAKE_API_TOKEN not in json.dumps(dict(req.header_items()))


class TestConfirmActionsTailscaleOnly:
    """Gate INVARIANTS.md `confirm-urls-tailscale-only` -- toutes les URL
    d'action pointent sur le hostname de l'instance (source unique, meme que
    le `Click` des messages normaux), jamais une IP LAN codee en dur ni un
    domaine public codes en dur dans le code source."""

    _LAN_IP_RE = re.compile(r"\b(192\.168\.|10\.\d+\.\d+\.\d+)\b")

    def test_action_urls_use_the_injected_hostname_not_a_hardcoded_ip(self):
        with mock.patch(
            "src.notifier._ntfy._resolve_hostname",
            return_value="vigil-nice-guardian",
        ):
            _, mock_open = _call_send_confirm_actions()
        req = mock_open.call_args[0][0]
        actions_header = req.get_header("Actions")
        assert "vigil-nice-guardian:9000/api/confirm/tplink_reboot/" in actions_header
        assert "vigil-nice-guardian:9000/api/confirm/cancel/" in actions_header
        assert not self._LAN_IP_RE.search(actions_header)
        assert "ntfy.bbhome.wf" not in actions_header

    def test_action_urls_never_contain_lan_ip_when_hostname_is_tailscale_ip(self):
        with mock.patch(
            "src.notifier._ntfy._resolve_hostname",
            return_value="100.112.123.55",
        ):
            _, mock_open = _call_send_confirm_actions()
        req = mock_open.call_args[0][0]
        actions_header = req.get_header("Actions")
        assert "100.112.123.55:9000" in actions_header
        assert not self._LAN_IP_RE.search(actions_header)

    def test_no_hardcoded_lan_or_public_url_in_managed_devices_or_http_server_source(
        self,
    ):
        """Miroir du grep automatisable suggere par INVARIANTS.md (gate
        `/api/confirm/* n'est jamais expose via Cloudflare`) : aucune URL
        `http://` codee en dur avec une IP LAN ou un domaine public dans les
        deux fichiers qui construisent/routent les demandes de confirmation."""
        import os

        src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
        for filename in ("managed_devices.py", "http_server.py"):
            path = os.path.join(src_dir, filename)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            for line in content.splitlines():
                if "http://" not in line:
                    continue
                allowed = ("100.", "tailscale", "localhost", "127.0.0.1", "{hostname}")
                assert any(token in line for token in allowed), (
                    f"URL http:// suspecte dans {filename}: {line.strip()}"
                )


# ---------------------------------------------------------------------------
# CONFIRM_RATE_LIMIT_* -- variables de configuration (config.py)
# ---------------------------------------------------------------------------


class TestConfirmRateLimitConfigDefaults:
    def test_default_max_failures_is_at_least_ten(self):
        import config

        assert config.CONFIRM_RATE_LIMIT_MAX_FAILURES >= 10

    def test_default_window_is_positive(self):
        import config

        assert config.CONFIRM_RATE_LIMIT_WINDOW > 0
