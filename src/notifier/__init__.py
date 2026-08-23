"""
Notification module -- multi-channel alerts for Vigil.
Supports Telegram, Discord, and Slack. All channels are optional.
"""

from notifier._types import Level, NotificationContext
from notifier._dispatch import dispatch

__all__ = ["notify", "Level", "NotificationContext"]


def notify(
    message: str,
    level: Level = Level.INFO,
    context: NotificationContext | None = None,
) -> dict[str, bool]:
    """
    Send a notification to all configured channels.
    Never raises -- failures are logged.
    """
    return dispatch(message, level, context)
