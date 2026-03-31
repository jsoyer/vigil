"""Discord notification channel via webhook."""

import logging
import re

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from config import DISCORD_WEBHOOK_URL, DISCORD_TIMEOUT
from notifier._types import Level, NotificationContext

_DISCORD_URL_RE = re.compile(r"^https://discord\.com/api/webhooks/\d+/[\w-]+$")

_LEVEL_COLORS: dict[Level, int] = {
    Level.INFO: 0x3498DB,       # blue
    Level.WARNING: 0xF39C12,    # orange
    Level.CRITICAL: 0xE74C3C,   # red
}


def is_configured() -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    if not _DISCORD_URL_RE.match(DISCORD_WEBHOOK_URL):
        logging.warning("Discord: URL webhook invalide -- doit etre https://discord.com/api/webhooks/...")
        return False
    return True


def _build_fields(ctx: NotificationContext) -> list[dict]:
    """Build Discord embed fields from context."""
    fields: list[dict] = []
    if ctx.score is not None:
        fields.append({"name": "Score", "value": f"{ctx.score}/{ctx.threshold or '?'}", "inline": True})
    if ctx.gateway_ok is not None:
        fields.append({"name": "Gateway", "value": "OK" if ctx.gateway_ok else "KO", "inline": True})
    if ctx.internet_ok_count is not None:
        fields.append({"name": "Internet", "value": f"{ctx.internet_ok_count}/{ctx.internet_total or '?'}", "inline": True})
    if ctx.reboot_count is not None:
        fields.append({"name": "Reboots", "value": str(ctx.reboot_count), "inline": True})
    if ctx.reboots_today is not None:
        fields.append({"name": "Reboots/jour", "value": f"{ctx.reboots_today}/{ctx.max_reboots_per_day or '?'}", "inline": True})
    if ctx.duration is not None:
        fields.append({"name": "Duree", "value": ctx.duration, "inline": True})
    for k, v in ctx.extra.items():
        fields.append({"name": k, "value": v, "inline": True})
    return fields


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send a Discord webhook notification. Never raises."""
    if requests is None:
        logging.warning("Module 'requests' non installe -- Discord impossible")
        return False

    embed: dict = {
        "title": "USG Watchdog",
        "description": message,
        "color": _LEVEL_COLORS.get(level, 0x95A5A6),
        "footer": {"text": f"{hostname} -- {timestamp}"},
    }

    if context is not None:
        fields = _build_fields(context)
        if fields:
            embed["fields"] = fields

    payload = {"embeds": [embed]}

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=DISCORD_TIMEOUT)
        if response.status_code in (200, 204):
            logging.debug("Discord: notification envoyee")
            return True
        if response.status_code == 429:
            logging.warning("Discord: rate limited -- notification ignoree")
            return False
        response.raise_for_status()
        return True
    except requests.exceptions.Timeout:
        logging.warning("Discord: timeout")
    except requests.exceptions.ConnectionError:
        logging.warning("Discord: erreur reseau")
    except requests.exceptions.HTTPError as e:
        logging.warning("Discord: HTTP %d", e.response.status_code)
    except Exception as e:
        logging.warning("Discord: erreur -- %s", e)
    return False
