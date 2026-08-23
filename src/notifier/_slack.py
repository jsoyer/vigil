"""Slack notification channel via incoming webhook."""

import json
import logging
import re
import urllib.error
import urllib.request

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
        logging.warning(
            "Slack: URL webhook invalide -- doit etre https://hooks.slack.com/services/..."
        )
        return False
    return True


def _build_context_elements(ctx: NotificationContext) -> list[dict]:
    """Build Slack context block elements from NotificationContext."""
    elements: list[dict] = []
    if ctx.score is not None:
        elements.append(
            {"type": "mrkdwn", "text": f"*Score:* {ctx.score}/{ctx.threshold or '?'}"}
        )
    if ctx.gateway_ok is not None:
        elements.append(
            {"type": "mrkdwn", "text": f"*GW:* {'OK' if ctx.gateway_ok else 'KO'}"}
        )
    if ctx.internet_ok_count is not None:
        elements.append(
            {
                "type": "mrkdwn",
                "text": f"*Internet:* {ctx.internet_ok_count}/{ctx.internet_total or '?'}",
            }
        )
    if ctx.reboot_count is not None:
        elements.append({"type": "mrkdwn", "text": f"*Reboots:* {ctx.reboot_count}"})
    if ctx.reboots_today is not None:
        elements.append(
            {
                "type": "mrkdwn",
                "text": f"*Reboots/jour:* {ctx.reboots_today}/{ctx.max_reboots_per_day or '?'}",
            }
        )
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
    emoji = _LEVEL_EMOJI.get(level, "")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} Vigil"},
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

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{hostname} -- {timestamp}_"}],
        }
    )

    payload = {"blocks": blocks}

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=SLACK_TIMEOUT) as resp:
            status = resp.status
        if status == 200:
            logging.debug("Slack: notification envoyee")
            return True
        logging.warning("Slack: HTTP %d", status)
        return False
    except urllib.error.HTTPError as e:
        logging.warning("Slack: HTTP %d", e.code)
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason).lower():
            logging.warning("Slack: timeout")
        else:
            logging.warning("Slack: erreur reseau")
    except Exception as e:
        logging.warning("Slack: erreur -- %s", e)
    return False
