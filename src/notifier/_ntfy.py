"""Ntfy notification channel -- supports cloud and self-hosted instances."""

import logging
import urllib.error
import urllib.request

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
        "Content-Type": "text/plain; charset=utf-8",
    }

    try:
        data = body.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=NTFY_TIMEOUT) as resp:
            status = resp.status
        if status == 200:
            logging.debug("Ntfy: notification envoyee")
            return True
        logging.warning("Ntfy: HTTP %d", status)
        return False
    except urllib.error.HTTPError as e:
        logging.warning("Ntfy: HTTP %d", e.code)
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason).lower():
            logging.warning("Ntfy: timeout")
        else:
            logging.warning("Ntfy: erreur reseau")
    except Exception as e:
        logging.warning("Ntfy: erreur -- %s", e)
    return False
