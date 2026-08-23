"""confirm.py -- confirmation generique d'actions destructives.

Mecanisme reutilisable par l'API HTTP et le bot Telegram pour toute action qui
necessite une confirmation explicite de l'operateur avant execution (reboot
d'un equipement pilotable, SMS, USSD...). Jeton court, usage unique, TTL
court, thread-safe, sans dependance a un driver ou vendor particulier et sans
stockage disque : tout est perdu si le process redemarre, ce qui est
volontaire (une confirmation en attente ne doit pas survivre a un restart).

Le jeton n'est jamais journalise en clair : seuls l'action et le contexte
metier apparaissent dans les logs.
"""

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

DEFAULT_TTL_SECONDS = 120.0


def _get_ttl_seconds() -> float:
    """Lit CONFIRM_TTL depuis l'environnement (secondes, defaut 120)."""
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
    """Genere un jeton court (8 caracteres hexadecimaux)."""
    return secrets.token_hex(4)


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

    if entry.action != action:
        logging.warning(
            "Confirmation refusee : jeton lie a une autre action (attendu '%s')",
            entry.action,
        )
        return None

    return dict(entry.context)
