"""Ntfy notification channel -- supports cloud and self-hosted instances."""

import logging

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from config import NTFY_URL, NTFY_TOPIC, NTFY_TIMEOUT
from notifier._types import Level, NotificationContext, format_context_inline

_LEVEL_PRIORITY: dict[Level, int] = {
    Level.INFO: 3,       # default
    Level.WARNING: 4,    # high
    Level.CRITICAL: 5,   # urgent
}

_LEVEL_TAGS: dict[Level, str] = {
    Level.INFO: "information_source",
    Level.WARNING: "warning",
    Level.CRITICAL: "rotating_light",
}


def is_configured() -> bool:
    return bool(NTFY_URL and NTFY_TOPIC)


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send a Ntfy notification. Never raises."""
    if requests is None:
        logging.warning("Module 'requests' non installe -- Ntfy impossible")
        return False

    url = f"{NTFY_URL.rstrip('/')}/{NTFY_TOPIC}"

    body = f"{message}\n\n{hostname} -- {timestamp}"
    if context is not None:
        ctx_str = format_context_inline(context)
        if ctx_str:
            body += f"\n{ctx_str}"

    headers = {
        "Title": "USG Watchdog",
        "Priority": str(_LEVEL_PRIORITY.get(level, 3)),
        "Tags": _LEVEL_TAGS.get(level, ""),
    }

    try:
        response = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=NTFY_TIMEOUT)
        if response.status_code == 200:
            logging.debug("Ntfy: notification envoyee")
            return True
        response.raise_for_status()
        return True
    except requests.exceptions.Timeout:
        logging.warning("Ntfy: timeout")
    except requests.exceptions.ConnectionError:
        logging.warning("Ntfy: erreur reseau")
    except requests.exceptions.HTTPError as e:
        logging.warning("Ntfy: HTTP %d", e.response.status_code)
    except Exception as e:
        logging.warning("Ntfy: erreur -- %s", e)
    return False
