"""Pushover notification channel -- native iOS/Android push."""

import logging
import urllib.error
import urllib.parse
import urllib.request

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
    body = f"{message}\n\n{hostname} -- {timestamp}"
    if context is not None:
        ctx_str = format_context_inline(context)
        if ctx_str:
            body += f"\n{ctx_str}"

    fields = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "message": body,
        "title": "USG Watchdog",
        "priority": str(_LEVEL_PRIORITY.get(level, 0)),
    }

    try:
        data = urllib.parse.urlencode(fields).encode("utf-8")
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=PUSHOVER_TIMEOUT) as resp:
            status = resp.status
        if status == 200:
            logging.debug("Pushover: notification envoyee")
            return True
        logging.warning("Pushover: HTTP %d", status)
        return False
    except urllib.error.HTTPError as e:
        logging.warning("Pushover: HTTP %d", e.code)
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason).lower():
            logging.warning("Pushover: timeout")
        else:
            logging.warning("Pushover: erreur reseau")
    except Exception as e:
        logging.warning("Pushover: erreur -- %s", e)
    return False
