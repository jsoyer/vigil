"""confirm.py -- confirmation generique d'actions destructives.

Mecanisme reutilisable par l'API HTTP pour toute action qui necessite une
confirmation explicite de l'operateur avant execution (reboot d'un
equipement pilotable, SMS, USSD...). Jeton long, usage unique, TTL court,
thread-safe, sans dependance a un driver ou vendor particulier et sans
stockage disque : tout est perdu si le process redemarre, ce qui est
volontaire (une confirmation en attente ne doit pas survivre a un restart).

Le jeton n'est jamais journalise en clair : seuls l'action et le contexte
metier apparaissent dans les logs.

TTL par defaut 600s depuis la 2.2.0, decision du 2026-08-23 (PRD Ntfy-first,
Q5) : historiquement tape a la main dans un chat authentifie (120s
suffisait), le jeton devient une URL de capacite cliquee depuis un bouton de
notification mobile qui doit d'abord reveiller le telephone -- 120s est jugee
trop courte. Voir aussi D1/D2 (`_generate_token`, `validate`) : le jeton n'est
plus jamais saisi a la main, d'ou le passage a une entropie ~256 bits et a une
comparaison d'action en temps constant.

Fenetre d'idempotence (`IDEMPOTENCY_WINDOW_SECONDS`, correctif decouvert au
test E2E reel du 2026-08-23) : l'application ntfy iOS envoie ~10 POST
identiques en ~20ms pour un seul appui sur un bouton d'action. Le jeton etant
a usage unique, les 9 rejeux echouaient tous (jeton deja consomme des le
premier), declenchant quasi a coup sur le rate limiter D3 de http_server.py
(`confirm_bruteforce`) a chaque appui pourtant legitime. `record_recent_success()`
et `check_recent_replay()` memorisent, pour une fenetre courte, l'empreinte
(jamais le jeton en clair) d'un jeton tout juste execute avec succes, pour que
http_server.py puisse reconnaitre un rejeu et repondre 200 sans re-executer
l'action ni compter d'echec.
"""

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

DEFAULT_TTL_SECONDS = 600.0

# Fenetre de deduplication des rejeux (~30s, cf. docstring du module). Ne
# stocke jamais le jeton en clair -- seule son empreinte SHA-256 est
# conservee (`_hash_token`), jamais journalisee.
IDEMPOTENCY_WINDOW_SECONDS = 30.0


def _get_ttl_seconds() -> float:
    """Lit CONFIRM_TTL depuis l'environnement (secondes, defaut 600)."""
    raw = os.getenv("CONFIRM_TTL", "")
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logging.warning(
            "CONFIRM_TTL invalide (%r), valeur par defaut %.0fs utilisee",
            raw,
            DEFAULT_TTL_SECONDS,
        )
        return DEFAULT_TTL_SECONDS
    if value <= 0:
        logging.warning(
            "CONFIRM_TTL doit etre strictement positif, valeur par defaut %.0fs utilisee",
            DEFAULT_TTL_SECONDS,
        )
        return DEFAULT_TTL_SECONDS
    return value


def _generate_token() -> str:
    """Genere un jeton long (D1 : `token_urlsafe(32)`, ~256 bits d'entropie).

    Le jeton n'est plus jamais saisi a la main -- il transite exclusivement
    via une URL de capacite cliquee depuis un bouton de notification. Rien ne
    justifie plus de rester a 32 bits (`token_hex(4)`, historique du jeton
    tape a la main dans un chat authentifie)."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class _PendingConfirmation:
    action: str
    context: dict = field(default_factory=dict)
    expires_at: float = 0.0


_lock = threading.Lock()
_pending: dict[str, _PendingConfirmation] = {}


def _purge_expired_locked() -> int:
    """Supprime les jetons expires. Appelant : detient deja _lock."""
    now = time.monotonic()
    expired = [token for token, entry in _pending.items() if entry.expires_at < now]
    for token in expired:
        del _pending[token]
    return len(expired)


def purge_expired() -> int:
    """Supprime les jetons expires. Retourne le nombre de jetons supprimes."""
    with _lock:
        return _purge_expired_locked()


def request_confirmation(
    action: str,
    context: dict | None = None,
    ttl: float | None = None,
) -> str:
    """Cree une demande de confirmation pour `action` et retourne son jeton.

    `context` est une donnee metier libre (ex: device_id, avertissements) qui
    sera restituee par `validate()`. `ttl`, si fourni, remplace CONFIRM_TTL
    pour cette demande uniquement -- usage principalement reserve aux tests.
    """
    if not action:
        raise ValueError("action requise pour une demande de confirmation")

    effective_ttl = _get_ttl_seconds() if ttl is None else ttl
    expires_at = time.monotonic() + effective_ttl
    ctx = dict(context) if context else {}

    with _lock:
        _purge_expired_locked()
        token = _generate_token()
        while token in _pending:
            token = _generate_token()
        _pending[token] = _PendingConfirmation(
            action=action, context=ctx, expires_at=expires_at
        )

    logging.info(
        "Confirmation demandee pour l'action '%s' (TTL %.0fs)", action, effective_ttl
    )
    return token


def validate(token: str, action: str) -> dict | None:
    """Valide et consomme un jeton de confirmation.

    Retourne une copie du contexte associe si le jeton existe, n'est pas
    expire et correspond a `action`. Retourne None sinon. Le jeton est
    toujours retire au premier appel (usage unique), qu'il soit valide ou
    non : un jeton ne peut jamais servir a deux tentatives.
    """
    if not token or not action:
        return None

    with _lock:
        entry = _pending.pop(token, None)
        _purge_expired_locked()

    if entry is None:
        logging.warning("Confirmation refusee : jeton inconnu ou deja utilise")
        return None

    if entry.expires_at < time.monotonic():
        logging.warning(
            "Confirmation refusee : jeton expire pour l'action '%s'", entry.action
        )
        return None

    # D2 : comparaison en temps constant -- le jeton n'authentifie plus
    # seulement par sa valeur (deja `pop` en temps constant en pratique),
    # l'action attendue doit aussi etre comparee sans fuite temporelle.
    if not hmac.compare_digest(entry.action, action):
        logging.warning(
            "Confirmation refusee : jeton lie a une autre action (attendu '%s')",
            entry.action,
        )
        return None

    return dict(entry.context)


# ---------------------------------------------------------------------------
# Fenetre d'idempotence -- correctif rejeu (voir docstring du module).
#
# `validate()` ci-dessus reste inchange (contrat protege par INVARIANTS.md) :
# le pop est toujours inconditionnel, usage unique. Les deux fonctions
# ci-dessous sont additives -- elles ne remplacent rien, elles permettent a
# l'appelant (http_server.py) de reconnaitre un rejeu du MEME jeton+action
# DANS une courte fenetre suivant une execution reussie, et de repondre sans
# re-executer l'action ni compter d'echec de rate limiting.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RecentSuccess:
    action: str
    expires_at: float


_recent_lock = threading.Lock()
_recent_success: dict[str, _RecentSuccess] = {}
# Empreintes deja "vues en rejeu" -- sert uniquement a ne journaliser
# l'evenement confirm_replayed qu'une fois par jeton, pas a chacune des ~10
# requetes d'une meme rafale.
_recent_success_logged: set[str] = set()


def _hash_token(token: str) -> str:
    """Empreinte non reversible du jeton (SHA-256) -- jamais le jeton en
    clair, meme dans cette structure en memoire de courte duree."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _purge_recent_success_locked() -> None:
    """Supprime les empreintes expirees. Appelant : detient deja _recent_lock."""
    now = time.monotonic()
    expired = [h for h, entry in _recent_success.items() if entry.expires_at < now]
    for h in expired:
        del _recent_success[h]
        _recent_success_logged.discard(h)


def record_recent_success(
    token: str,
    action: str,
    window: float | None = None,
) -> None:
    """Memorise qu'une confirmation (`token`, `action`) vient d'etre executee
    avec succes, pour `window` secondes (defaut `IDEMPOTENCY_WINDOW_SECONDS`).

    Un rejeu du meme couple dans cette fenetre sera reconnu par
    `check_recent_replay()` sans que l'action soit re-executee. Ne stocke que
    l'empreinte du jeton (`_hash_token`), jamais le jeton lui-meme.
    """
    effective_window = IDEMPOTENCY_WINDOW_SECONDS if window is None else window
    token_hash = _hash_token(token)
    with _recent_lock:
        _purge_recent_success_locked()
        _recent_success[token_hash] = _RecentSuccess(
            action=action, expires_at=time.monotonic() + effective_window
        )


def check_recent_replay(token: str, action: str) -> tuple[bool, bool]:
    """Verifie si (`token`, `action`) correspond a un succes recent (fenetre
    d'idempotence).

    Retourne `(is_replay, first_replay)` :
    - `is_replay=False` : ce n'est pas un rejeu reconnu (jeton absent de la
      fenetre, fenetre expiree, ou action differente) -- l'appelant doit
      suivre le chemin normal (validate/execution, comptage rate limiter).
    - `is_replay=True` : rejeu reconnu, l'appelant doit repondre sans
      re-executer l'action ni compter d'echec. `first_replay=True`
      uniquement au tout premier rejeu detecte pour ce jeton, pour permettre
      de journaliser un evenement `confirm_replayed` une seule fois plutot
      qu'a chaque requete d'une meme rafale.
    """
    if not token or not action:
        return False, False

    token_hash = _hash_token(token)
    with _recent_lock:
        _purge_recent_success_locked()
        entry = _recent_success.get(token_hash)
        if entry is None:
            return False, False
        if entry.expires_at < time.monotonic():
            return False, False
        if not hmac.compare_digest(entry.action, action):
            return False, False
        first_replay = token_hash not in _recent_success_logged
        _recent_success_logged.add(token_hash)
        return True, first_replay
