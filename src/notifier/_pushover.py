"""Pushover notification channel -- native iOS/Android push."""

import logging

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from config import PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN, PUSHOVER_TIMEOUT
from notifier._types import Level, NotificationContext, format_context_inline

_LEVEL_PRIORITY: dict[Level, int] = {
    Level.INFO: -1,      # lowest
    Level.WARNING: 0,    # normal
    Level.CRITICAL: 1,   # high (bypasses quiet hours)
}


def is_configured() -> bool:
    return bool(PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN)


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send a Pushover notification. Never raises."""
    if requests is None:
        logging.warning("Module 'requests' non installe -- Pushover impossible")
        return False

    body = f"{message}\n\n{hostname} -- {timestamp}"
    if context is not None:
        ctx_str = format_context_inline(context)
        if ctx_str:
            body += f"\n{ctx_str}"

    payload = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "message": body,
        "title": "USG Watchdog",
        "priority": _LEVEL_PRIORITY.get(level, 0),
    }

    try:
        response = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=PUSHOVER_TIMEOUT,
        )
        if response.status_code == 200:
            logging.debug("Pushover: notification envoyee")
            return True
        response.raise_for_status()
        return True
    except requests.exceptions.Timeout:
        logging.warning("Pushover: timeout")
    except requests.exceptions.ConnectionError:
        logging.warning("Pushover: erreur reseau")
    except Exception as e:
        logging.warning("Pushover: erreur -- %s", e)
    return False
