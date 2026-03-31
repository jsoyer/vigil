"""Watchdog state -- immutable snapshots and command queue for HTTP coordination."""

import json
import logging
import queue
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WatchdogState:
    """Complete watchdog state snapshot, published each cycle."""

    # Scoring
    failure_score: int = 0
    threshold: int = 10
    was_degraded: bool = False

    # Reboot state
    last_reboot_time: float = 0.0
    grace_until: float = 0.0
    consecutive_reboots: int = 0
    reboots_today: int = 0
    surveillance_only: bool = False

    # SSH backoff
    consecutive_ssh_failures: int = 0
    last_ssh_attempt_time: float = 0.0

    # ISP detection
    isp_outage_detected: bool = False

    # Outage tracking
    outage_start_time: float = 0.0
    outage_reboot_count: int = 0
    outage_reboot_helped: bool = False

    # Coordination
    threshold_reached_time: float = 0.0
    instance_priority: int = 1

    # Connectivity (latest cycle)
    gateway_ok: bool = True
    internet_ok_count: int = 3
    internet_total: int = 3

    # Peer status (updated each cycle if peer configured)
    peer_status: str = "unknown"  # unknown, healthy, degraded, critical, unreachable
    peer_score: int = 0
    peer_gateway: str = ""
    peer_internet: str = ""

    # Version
    version: str = "0.0.0"

    # Metadata
    timestamp: str = ""
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "WatchdogState | None":
        """Construct from a dict. Returns None on invalid input."""
        if not isinstance(data, dict):
            return None
        try:
            # Only pass known fields, ignore extra keys
            known_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known_fields}
            return cls(**filtered)
        except (TypeError, ValueError) as e:
            logging.warning("WatchdogState.from_dict: donnees invalides -- %s", e)
            return None


class StateHolder:
    """Mutable container for the latest immutable WatchdogState snapshot.

    Thread-safe by design: the main loop swaps the reference atomically
    (Python GIL guarantees single-pointer assignment is atomic).
    The HTTP thread reads the reference and gets a complete frozen snapshot.
    """

    __slots__ = ("state", "commands")

    def __init__(self) -> None:
        self.state: WatchdogState | None = None
        self.commands: queue.Queue[str] = queue.Queue()

    def send_command(self, command: str) -> None:
        """Queue a command from the HTTP thread to the main loop."""
        self.commands.put_nowait(command)

    def poll_command(self) -> str | None:
        """Non-blocking poll for a pending command. Returns None if empty."""
        try:
            return self.commands.get_nowait()
        except queue.Empty:
            return None


# Command constants
CMD_PAUSE = "pause"
CMD_RESUME = "resume"
CMD_REBOOT = "reboot"
