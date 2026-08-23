"""
Notification module -- multi-channel alerts for Vigil.
Supports Ntfy (principal, boutons d'action) and Email SMTP. MQTT/Home
Assistant est un canal de telemetrie separe (mqtt_publisher.py), pas un
canal notify(). All channels are optional.
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
