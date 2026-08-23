"""Discord notification channel via webhook."""

import json
import logging
import re
import urllib.error
import urllib.request

from config import DISCORD_WEBHOOK_URL, DISCORD_TIMEOUT
from notifier._types import Level, NotificationContext

_DISCORD_URL_RE = re.compile(r"^https://discord\.com/api/webhooks/\d+/[\w-]+$")

_LEVEL_COLORS: dict[Level, int] = {
    Level.INFO: 0x3498DB,  # blue
    Level.WARNING: 0xF39C12,  # orange
    Level.CRITICAL: 0xE74C3C,  # red
}


def is_configured() -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    if not _DISCORD_URL_RE.match(DISCORD_WEBHOOK_URL):
        logging.warning(
            "Discord: URL webhook invalide -- doit etre https://discord.com/api/webhooks/..."
        )
        return False
    return True


def _build_fields(ctx: NotificationContext) -> list[dict]:
    """Build Discord embed fields from context."""
    fields: list[dict] = []
    if ctx.score is not None:
        fields.append(
            {
                "name": "Score",
                "value": f"{ctx.score}/{ctx.threshold or '?'}",
                "inline": True,
            }
        )
    if ctx.gateway_ok is not None:
        fields.append(
            {
                "name": "Gateway",
                "value": "OK" if ctx.gateway_ok else "KO",
                "inline": True,
            }
        )
    if ctx.internet_ok_count is not None:
        fields.append(
            {
                "name": "Internet",
                "value": f"{ctx.internet_ok_count}/{ctx.internet_total or '?'}",
                "inline": True,
            }
        )
    if ctx.reboot_count is not None:
        fields.append(
            {"name": "Reboots", "value": str(ctx.reboot_count), "inline": True}
        )
    if ctx.reboots_today is not None:
        fields.append(
            {
                "name": "Reboots/jour",
                "value": f"{ctx.reboots_today}/{ctx.max_reboots_per_day or '?'}",
                "inline": True,
            }
        )
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
    embed: dict = {
        "title": "Vigil",
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
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=DISCORD_TIMEOUT) as resp:
            status = resp.status
        if status in (200, 204):
            logging.debug("Discord: notification envoyee")
            return True
        logging.warning("Discord: HTTP %d", status)
        return False
    except urllib.error.HTTPError as e:
        if e.code == 429:
            logging.warning("Discord: rate limited -- notification ignoree")
        else:
            logging.warning("Discord: HTTP %d", e.code)
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason).lower():
            logging.warning("Discord: timeout")
        else:
            logging.warning("Discord: erreur reseau")
    except Exception as e:
        logging.warning("Discord: erreur -- %s", e)
    return False
