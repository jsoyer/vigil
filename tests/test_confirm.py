"""Tests for src/confirm.py"""

import hmac
import logging
import re
import threading
from unittest import mock

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# D1 : jeton `secrets.token_urlsafe(32)` -- alphabet URL-safe base64
# (A-Za-z0-9_-), longueur fixe pour 32 octets sans padding ('=').
_TOKEN_URLSAFE_32_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@pytest.fixture(autouse=True)
def _reset_confirm_state():
    """Isole chaque test : vide le registre de jetons en memoire, ainsi que
    la fenetre d'idempotence (correctif rejeu, decouvert au test E2E reel)."""
    import confirm

    confirm._pending.clear()
    confirm._recent_success.clear()
    confirm._recent_success_logged.clear()
    yield
    confirm._pending.clear()
    confirm._recent_success.clear()
    confirm._recent_success_logged.clear()


# ---------------------------------------------------------------------------
# request_confirmation
# ---------------------------------------------------------------------------


class TestRequestConfirmation:
    def test_returns_token_of_expected_length(self):
        """D1 : `secrets.token_urlsafe(32)` -- le jeton n'est plus tape a la
        main (il devient une URL de capacite), donc plus jamais court. Ancien
        test attendait 6-8 caracteres hex (`token_hex(4)`) ; mis a jour pour
        refleter le changement d'entropie (~256 bits)."""
        from confirm import request_confirmation

        token = request_confirmation("tplink_reboot", {"device_id": "dijon-1"})
        assert _TOKEN_URLSAFE_32_RE.match(token), (
            f"jeton inattendu : {token!r} (longueur {len(token)})"
        )

    def test_requires_action(self):
        from confirm import request_confirmation

        with pytest.raises(ValueError):
            request_confirmation("", {})

    def test_tokens_are_unique(self):
        from confirm import request_confirmation

        tokens = {request_confirmation("tplink_reboot") for _ in range(50)}
        assert len(tokens) == 50


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_token_returns_context(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot", {"device_id": "dijon-1"})
        context = validate(token, "tplink_reboot")
        assert context == {"device_id": "dijon-1"}

    def test_single_use_token_rejected_on_second_call(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot", {"device_id": "dijon-1"})
        assert validate(token, "tplink_reboot") is not None
        assert validate(token, "tplink_reboot") is None

    def test_unknown_token_rejected(self):
        from confirm import validate

        assert validate("deadbeef", "tplink_reboot") is None

    def test_empty_token_rejected(self):
        from confirm import validate

        assert validate("", "tplink_reboot") is None

    def test_expired_token_rejected(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot", ttl=-1)
        assert validate(token, "tplink_reboot") is None

    def test_action_mismatch_rejected(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot")
        assert validate(token, "tplink_sms_sent") is None

    def test_action_mismatch_still_consumes_token(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot")
        validate(token, "tplink_sms_sent")
        # Meme avec la bonne action, le jeton a deja ete consomme.
        assert validate(token, "tplink_reboot") is None

    def test_context_returned_is_a_copy(self):
        from confirm import request_confirmation, validate

        original_context = {"device_id": "dijon-1"}
        token = request_confirmation("tplink_reboot", original_context)
        returned = validate(token, "tplink_reboot")
        returned["device_id"] = "mutated"
        assert original_context == {"device_id": "dijon-1"}

    def test_context_defaults_to_empty_dict(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot")
        assert validate(token, "tplink_reboot") == {}


# ---------------------------------------------------------------------------
# D2 -- comparaison de l'action en temps constant (hmac.compare_digest)
# ---------------------------------------------------------------------------


class TestActionComparisonConstantTime:
    def test_validate_uses_hmac_compare_digest_for_action(self):
        """Verifie par lecture ET par test que `validate()` s'appuie sur
        `hmac.compare_digest`, pas sur `!=` -- une simple egalite de
        comportement ne suffit pas a prouver l'absence de fuite temporelle,
        donc on verifie l'appel reel a la primitive attendue."""
        from confirm import request_confirmation
        import confirm as confirm_mod

        token = request_confirmation("tplink_reboot")
        with mock.patch.object(
            confirm_mod.hmac, "compare_digest", wraps=hmac.compare_digest
        ) as spy:
            confirm_mod.validate(token, "tplink_reboot")
        spy.assert_called_once_with("tplink_reboot", "tplink_reboot")

    def test_validate_still_rejects_mismatched_action_via_compare_digest(self):
        """Non-regression : le passage a `compare_digest` ne doit jamais
        inverser la logique (un appel malheureux a
        `not hmac.compare_digest(...)` ecrit a l'envers accepterait tout)."""
        from confirm import request_confirmation
        import confirm as confirm_mod

        token = request_confirmation("tplink_reboot")
        assert confirm_mod.validate(token, "autre_action") is None

    def test_validate_accepts_matching_action_via_compare_digest(self):
        from confirm import request_confirmation
        import confirm as confirm_mod

        token = request_confirmation("tplink_reboot", {"device_id": "dijon-1"})
        assert confirm_mod.validate(token, "tplink_reboot") == {"device_id": "dijon-1"}


# ---------------------------------------------------------------------------
# D1 -- entropie du jeton (secrets.token_urlsafe(32))
# ---------------------------------------------------------------------------


class TestTokenEntropy:
    def test_token_uses_urlsafe_32_bytes(self):
        import confirm as confirm_mod

        with mock.patch.object(
            confirm_mod.secrets,
            "token_urlsafe",
            wraps=confirm_mod.secrets.token_urlsafe,
        ) as spy:
            confirm_mod._generate_token()
        spy.assert_called_once_with(32)

    def test_many_tokens_all_match_urlsafe_alphabet_and_length(self):
        from confirm import request_confirmation

        for _ in range(20):
            token = request_confirmation("tplink_reboot")
            assert _TOKEN_URLSAFE_32_RE.match(token)


# ---------------------------------------------------------------------------
# TTL configuration
# ---------------------------------------------------------------------------


class TestTtl:
    def test_default_ttl_is_600_seconds(self):
        """Q5, decision du 2026-08-23 : passage de 120s a 600s -- le jeton
        devient une URL cliquee depuis une notification mobile qui doit
        d'abord reveiller le telephone. Une regression silencieuse vers
        120.0 est un defaut de securite (voir INVARIANTS.md)."""
        import confirm

        assert confirm.DEFAULT_TTL_SECONDS == 600.0

    def test_default_ttl_used_when_env_missing(self, monkeypatch):
        import confirm

        monkeypatch.delenv("CONFIRM_TTL", raising=False)
        assert confirm._get_ttl_seconds() == confirm.DEFAULT_TTL_SECONDS
        assert confirm._get_ttl_seconds() == 600.0

    def test_env_ttl_used_when_valid(self, monkeypatch):
        import confirm

        monkeypatch.setenv("CONFIRM_TTL", "30")
        assert confirm._get_ttl_seconds() == 30.0

    def test_invalid_env_ttl_falls_back_to_default(self, monkeypatch):
        import confirm

        monkeypatch.setenv("CONFIRM_TTL", "not-a-number")
        assert confirm._get_ttl_seconds() == confirm.DEFAULT_TTL_SECONDS

    def test_non_positive_env_ttl_falls_back_to_default(self, monkeypatch):
        import confirm

        monkeypatch.setenv("CONFIRM_TTL", "0")
        assert confirm._get_ttl_seconds() == confirm.DEFAULT_TTL_SECONDS

    def test_explicit_ttl_overrides_env(self, monkeypatch):
        from confirm import request_confirmation, validate

        monkeypatch.setenv("CONFIRM_TTL", "300")
        token = request_confirmation("tplink_reboot", ttl=-1)
        # TTL explicite negatif => deja expire malgre CONFIRM_TTL=300.
        assert validate(token, "tplink_reboot") is None


# ---------------------------------------------------------------------------
# purge_expired
# ---------------------------------------------------------------------------


class TestPurgeExpired:
    def test_purge_removes_only_expired(self):
        from confirm import request_confirmation, purge_expired
        import confirm as confirm_mod

        fresh_token = request_confirmation("tplink_reboot")
        expired_token = request_confirmation("tplink_reboot", ttl=-1)
        removed = purge_expired()
        assert removed == 1
        assert expired_token not in confirm_mod._pending
        assert fresh_token in confirm_mod._pending

    def test_request_confirmation_purges_opportunistically(self):
        from confirm import request_confirmation
        import confirm as confirm_mod

        expired_token = request_confirmation("tplink_reboot", ttl=-1)
        assert expired_token in confirm_mod._pending
        request_confirmation("tplink_reboot")
        assert expired_token not in confirm_mod._pending


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_requests_produce_unique_tokens(self):
        from confirm import request_confirmation

        results = []
        lock = threading.Lock()

        def worker():
            token = request_confirmation("tplink_reboot")
            with lock:
                results.append(token)

        threads = [threading.Thread(target=worker) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 30
        assert len(set(results)) == 30

    def test_concurrent_validate_only_one_succeeds(self):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot", {"device_id": "dijon-1"})
        successes = []
        lock = threading.Lock()

        def worker():
            result = validate(token, "tplink_reboot")
            if result is not None:
                with lock:
                    successes.append(result)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1


# ---------------------------------------------------------------------------
# Le jeton n'apparait jamais dans les logs
# ---------------------------------------------------------------------------


class TestLoggingNeverExposesToken:
    def test_token_absent_from_logs_on_request(self, caplog):
        from confirm import request_confirmation

        with caplog.at_level(logging.DEBUG):
            token = request_confirmation("tplink_reboot", {"device_id": "dijon-1"})

        for record in caplog.records:
            assert token not in record.getMessage()

    def test_token_absent_from_logs_on_validate_success(self, caplog):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot")
        with caplog.at_level(logging.DEBUG):
            validate(token, "tplink_reboot")

        for record in caplog.records:
            assert token not in record.getMessage()

    def test_token_absent_from_logs_on_validate_failure(self, caplog):
        from confirm import request_confirmation, validate

        token = request_confirmation("tplink_reboot")
        validate(token, "tplink_reboot")  # consomme

        with caplog.at_level(logging.DEBUG):
            validate(token, "tplink_reboot")  # rejete : jeton deja utilise

        for record in caplog.records:
            assert token not in record.getMessage()

    def test_token_absent_from_logs_on_unknown_token(self, caplog):
        from confirm import validate

        fake_token = "deadbeef"
        with caplog.at_level(logging.DEBUG):
            validate(fake_token, "tplink_reboot")

        for record in caplog.records:
            assert fake_token not in record.getMessage()


# ---------------------------------------------------------------------------
# Fenetre d'idempotence -- correctif rejeu (decouvert au test E2E reel du
# 2026-08-23) : l'app ntfy iOS envoie ~10 POST identiques en ~20ms pour un
# seul appui de bouton. record_recent_success()/check_recent_replay()
# permettent a l'appelant (http_server.py) de reconnaitre un rejeu sans
# re-executer l'action ni compter d'echec de rate limiting.
# ---------------------------------------------------------------------------


class TestIdempotencyWindow:
    def test_unknown_token_is_not_a_replay(self):
        from confirm import check_recent_replay

        is_replay, first_replay = check_recent_replay("never-recorded", "tplink_reboot")
        assert is_replay is False
        assert first_replay is False

    def test_recorded_success_is_recognized_as_replay(self):
        from confirm import record_recent_success, check_recent_replay

        record_recent_success("tok-abc", "tplink_reboot")
        is_replay, first_replay = check_recent_replay("tok-abc", "tplink_reboot")
        assert is_replay is True
        assert first_replay is True

    def test_burst_of_ten_replays_only_first_is_flagged_first_replay(self):
        """Reproduit le bug reel : ~10 rejeux en rafale doivent tous etre
        reconnus comme des rejeux, mais un seul doit valoir `first_replay`
        (pour ne journaliser confirm_replayed qu'une fois)."""
        from confirm import record_recent_success, check_recent_replay

        record_recent_success("tok-burst", "tplink_reboot")
        results = [check_recent_replay("tok-burst", "tplink_reboot") for _ in range(10)]
        assert all(is_replay for is_replay, _ in results)
        first_replay_count = sum(1 for _, first in results if first)
        assert first_replay_count == 1
        assert results[0] == (True, True)
        assert all(r == (True, False) for r in results[1:])

    def test_wrong_action_is_not_a_replay(self):
        from confirm import record_recent_success, check_recent_replay

        record_recent_success("tok-xyz", "tplink_reboot")
        is_replay, first_replay = check_recent_replay("tok-xyz", "cancel")
        assert is_replay is False
        assert first_replay is False

    def test_replay_after_window_expiry_is_not_recognized(self):
        """Simule l'expiration de la fenetre d'idempotence (~30s) sans
        attendre reellement -- meme technique que TestPurgeExpired."""
        from confirm import record_recent_success, check_recent_replay

        record_recent_success("tok-expired", "tplink_reboot", window=-1.0)
        is_replay, first_replay = check_recent_replay("tok-expired", "tplink_reboot")
        assert is_replay is False
        assert first_replay is False

    def test_default_window_is_thirty_seconds(self):
        import confirm

        assert confirm.IDEMPOTENCY_WINDOW_SECONDS == 30.0

    def test_raw_token_never_stored_in_recent_success(self):
        """Seule l'empreinte SHA-256 du jeton est memorisee -- jamais le
        jeton en clair, meme dans cette structure en memoire de courte
        duree."""
        from confirm import record_recent_success
        import confirm as confirm_mod

        token = "super-secret-capability-token"
        record_recent_success(token, "tplink_reboot")
        assert token not in confirm_mod._recent_success
        assert all(token != h for h in confirm_mod._recent_success)

    def test_recording_never_logs_raw_token(self, caplog):
        from confirm import record_recent_success, check_recent_replay

        token = "another-secret-token"
        with caplog.at_level(logging.DEBUG):
            record_recent_success(token, "tplink_reboot")
            check_recent_replay(token, "tplink_reboot")

        for record in caplog.records:
            assert token not in record.getMessage()

    def test_empty_token_or_action_is_never_a_replay(self):
        from confirm import check_recent_replay

        assert check_recent_replay("", "tplink_reboot") == (False, False)
        assert check_recent_replay("tok", "") == (False, False)
