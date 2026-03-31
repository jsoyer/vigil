"""Notification dispatcher -- fan-out to all enabled channels."""

import functools
import logging
from datetime import datetime

from notifier._types import Level, NotificationContext, NotificationChannel

from config import (
    TELEGRAM_MIN_LEVEL, DISCORD_MIN_LEVEL, SLACK_MIN_LEVEL,
    NTFY_MIN_LEVEL, SMTP_MIN_LEVEL, PUSHOVER_MIN_LEVEL,
)


def _parse_level(raw: str) -> Level:
    """Parse a level string, defaulting to INFO on invalid input."""
    try:
        return Level[raw.upper()]
    except (KeyError, AttributeError):
        logging.warning("Niveau de notification invalide '%s' -- fallback INFO", raw)
        return Level.INFO


@functools.cache
def _get_hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "usg-watchdog"


@functools.cache
def _get_channels() -> tuple[tuple[str, NotificationChannel, str], ...]:
    """Build channel list once and cache it. Returns tuple for hashability."""
    from notifier import _telegram, _discord, _slack, _ntfy, _email, _pushover
    return (
        ("telegram", _telegram, TELEGRAM_MIN_LEVEL),
        ("discord", _discord, DISCORD_MIN_LEVEL),
        ("slack", _slack, SLACK_MIN_LEVEL),
        ("ntfy", _ntfy, NTFY_MIN_LEVEL),
        ("email", _email, SMTP_MIN_LEVEL),
        ("pushover", _pushover, PUSHOVER_MIN_LEVEL),
    )


def dispatch(
    message: str,
    level: Level,
    context: NotificationContext | None,
) -> dict[str, bool]:
    """
    Send notification to all enabled channels that accept this level.
    Never raises. Returns {channel_name: success_or_skipped}.
    """
    hostname = _get_hostname()
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    results: dict[str, bool] = {}

    for name, channel, min_level_str in _get_channels():
        if not channel.is_configured():
            continue

        min_level = _parse_level(min_level_str)
        if level < min_level:
            logging.debug("%s: niveau %s < min %s -- ignore", name, level.name, min_level.name)
            results[name] = False
            continue

        try:
            success = channel.send(message, level, context, hostname, timestamp)
            results[name] = success
        except Exception as e:
            logging.warning("%s: erreur inattendue -- %s", name, e)
            results[name] = False

    return results
