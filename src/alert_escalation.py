"""Alert escalation -- if no acknowledgement after N minutes, notify via a different channel."""

import logging
import time

from config import (
    ALERT_ESCALATION_DELAY,
    ALERT_ESCALATION_ENABLED,
)


class EscalationTracker:
    """Track unacknowledged critical alerts and escalate if needed.

    The idea: if a CRITICAL notification is sent and the score hasn't
    dropped (= no recovery) within ESCALATION_DELAY minutes, re-send
    the alert at a higher urgency so all channels (including those with
    MIN_LEVEL=CRITICAL) are notified again.
    """

    def __init__(self) -> None:
        self._critical_at: float = 0.0  # timestamp of first critical alert
        self._escalated: bool = False

    def on_critical(self) -> None:
        """Record that a critical alert was sent."""
        if self._critical_at == 0.0:
            self._critical_at = time.time()
            self._escalated = False

    def on_recovery(self) -> None:
        """Reset escalation tracking on recovery."""
        self._critical_at = 0.0
        self._escalated = False

    def should_escalate(self) -> bool:
        """Check if escalation is needed.

        Returns True once after ESCALATION_DELAY since the first critical.
        """
        if not ALERT_ESCALATION_ENABLED:
            return False
        if self._critical_at == 0.0 or self._escalated:
            return False
        elapsed = time.time() - self._critical_at
        if elapsed >= ALERT_ESCALATION_DELAY * 60:
            self._escalated = True
            return True
        return False
