"""Telegram notification channel via Bot API."""

import html
import json
import logging
import urllib.error
import urllib.request

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TIMEOUT
from notifier._types import Level, NotificationContext, format_context_inline

_LEVEL_ICONS: dict[Level, str] = {
    Level.INFO: "i",
    Level.WARNING: "!",
    Level.CRITICAL: "X",
}


def is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send a Telegram notification. Never raises."""
    icon = _LEVEL_ICONS.get(level, "")
    escaped_msg = html.escape(message)
    escaped_host = html.escape(hostname)

    body = f"<b>{icon} Vigil</b>\n<i>{escaped_host} -- {timestamp}</i>\n\n{escaped_msg}"

    if context is not None:
        ctx_str = format_context_inline(context)
        if ctx_str:
            body += f"\n\n<code>{html.escape(ctx_str)}</code>"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": body,
        "parse_mode": "HTML",
        "disable_notification": False,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT) as resp:
            resp.read()
        logging.debug("Telegram: notification envoyee")
        return True
    except urllib.error.HTTPError as e:
        logging.warning("Telegram: HTTP %d", e.code)
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower():
            logging.warning("Telegram: timeout")
        else:
            logging.warning("Telegram: erreur reseau (normal si connexion DOWN)")
    except Exception:
        logging.warning(
            "Telegram: erreur inattendue (details masques pour proteger le token)"
        )
    return False
