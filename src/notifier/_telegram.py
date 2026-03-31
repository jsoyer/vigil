"""Telegram notification channel via Bot API."""

import html
import logging

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TIMEOUT
from notifier._types import Level, NotificationContext, format_context_inline

_LEVEL_ICONS: dict[Level, str] = {
    Level.INFO: "ℹ️",
    Level.WARNING: "⚠️",
    Level.CRITICAL: "🔴",
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
    if requests is None:
        logging.warning("Module 'requests' non installe -- Telegram impossible")
        return False

    icon = _LEVEL_ICONS.get(level, "")
    escaped_msg = html.escape(message)
    escaped_host = html.escape(hostname)

    body = f"<b>{icon} USG Watchdog</b>\n<i>{escaped_host} -- {timestamp}</i>\n\n{escaped_msg}"

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
        response = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT)
        response.raise_for_status()
        logging.debug("Telegram: notification envoyee")
        return True
    except requests.exceptions.Timeout:
        logging.warning("Telegram: timeout")
    except requests.exceptions.ConnectionError:
        logging.warning("Telegram: erreur reseau (normal si connexion DOWN)")
    except requests.exceptions.HTTPError as e:
        logging.warning("Telegram: HTTP %d", e.response.status_code)
    except Exception:
        logging.warning("Telegram: erreur inattendue (details masques pour proteger le token)")
    return False
