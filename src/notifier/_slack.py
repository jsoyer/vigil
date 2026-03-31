"""Slack notification channel via incoming webhook."""

import logging
import re

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from config import SLACK_WEBHOOK_URL, SLACK_TIMEOUT
from notifier._types import Level, NotificationContext

_SLACK_URL_RE = re.compile(r"^https://hooks\.slack\.com/services/T[\w]+/B[\w]+/[\w]+$")

_LEVEL_EMOJI: dict[Level, str] = {
    Level.INFO: ":large_blue_circle:",
    Level.WARNING: ":warning:",
    Level.CRITICAL: ":red_circle:",
}


def is_configured() -> bool:
    if not SLACK_WEBHOOK_URL:
        return False
    if not _SLACK_URL_RE.match(SLACK_WEBHOOK_URL):
        logging.warning("Slack: URL webhook invalide -- doit etre https://hooks.slack.com/services/...")
        return False
    return True


def _build_context_elements(ctx: NotificationContext) -> list[dict]:
    """Build Slack context block elements from NotificationContext."""
    elements: list[dict] = []
    if ctx.score is not None:
        elements.append({"type": "mrkdwn", "text": f"*Score:* {ctx.score}/{ctx.threshold or '?'}"})
    if ctx.gateway_ok is not None:
        elements.append({"type": "mrkdwn", "text": f"*GW:* {'OK' if ctx.gateway_ok else 'KO'}"})
    if ctx.internet_ok_count is not None:
        elements.append({"type": "mrkdwn", "text": f"*Internet:* {ctx.internet_ok_count}/{ctx.internet_total or '?'}"})
    if ctx.reboot_count is not None:
        elements.append({"type": "mrkdwn", "text": f"*Reboots:* {ctx.reboot_count}"})
    if ctx.reboots_today is not None:
        elements.append({"type": "mrkdwn", "text": f"*Reboots/jour:* {ctx.reboots_today}/{ctx.max_reboots_per_day or '?'}"})
    if ctx.duration is not None:
        elements.append({"type": "mrkdwn", "text": f"*Duree:* {ctx.duration}"})
    for k, v in ctx.extra.items():
        elements.append({"type": "mrkdwn", "text": f"*{k}:* {v}"})
    return elements


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send a Slack webhook notification. Never raises."""
    if requests is None:
        logging.warning("Module 'requests' non installe -- Slack impossible")
        return False

    emoji = _LEVEL_EMOJI.get(level, "")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} USG Watchdog"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        },
    ]

    if context is not None:
        ctx_elements = _build_context_elements(context)
        if ctx_elements:
            blocks.append({"type": "context", "elements": ctx_elements})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_{hostname} -- {timestamp}_"}],
    })

    payload = {"blocks": blocks}

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=SLACK_TIMEOUT)
        if response.status_code == 200:
            logging.debug("Slack: notification envoyee")
            return True
        response.raise_for_status()
        return True
    except requests.exceptions.Timeout:
        logging.warning("Slack: timeout")
    except requests.exceptions.ConnectionError:
        logging.warning("Slack: erreur reseau")
    except requests.exceptions.HTTPError as e:
        logging.warning("Slack: HTTP %d", e.response.status_code)
    except Exception as e:
        logging.warning("Slack: erreur -- %s", e)
    return False
