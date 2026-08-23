"""Event history -- ring buffer for watchdog events with periodic disk persistence."""

import json
import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from config import _resolve_install_path


@dataclass(frozen=True)
class Event:
    """A single watchdog event."""

    ts: str
    type: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# Event type constants
STARTUP = "startup"
SHUTDOWN = "shutdown"
REBOOT = "reboot"
REBOOT_FAILED = "reboot_failed"
RECOVERY = "recovery"
ISP_OUTAGE = "isp_outage"
ISP_RECOVERY = "isp_recovery"
PEER_STANDDOWN = "peer_standdown"
MAX_REBOOTS = "max_reboots"
# A1 -- equipements TP-Link pilotables (voir src/managed_devices.py). Origine
# (api|telegram) et device_id portes dans `data`, jamais le mot de passe.
TPLINK_REBOOT = "tplink_reboot"
TPLINK_REBOOT_FAILED = "tplink_reboot_failed"


class EventLog:
    """Thread-safe ring buffer for watchdog events.

    Events are stored in a deque with a max size. Periodically persisted
    to a JSON file on disk so history survives restarts.
    """

    def __init__(
        self,
        max_events: int = 50,
        # /var/lib/vigil est cree par systemd (StateDirectory=vigil) et
        # inscriptible par le service -- l'ecriture atomique (.tmp + rename)
        # exige un REPERTOIRE inscriptible, ce que /var/log ne fournit pas
        # sous ProtectSystem=strict (cause racine du bug historique de
        # persistance des evenements).
        persist_path: str = _resolve_install_path(
            "/var/lib/vigil/events.json", "/var/log/usg-watchdog-events.json"
        ),
        persist_interval: int = 3600,
    ) -> None:
        self._events: deque[Event] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._persist_path = Path(persist_path)
        self._persist_interval = persist_interval
        self._last_persist = 0.0
        self._load_from_disk()

    def record(self, event_type: str, **data: object) -> None:
        """Record a new event. Thread-safe."""
        event = Event(
            ts=datetime.now().isoformat(timespec="seconds"),
            type=event_type,
            data={k: _serialize(v) for k, v in data.items()},
        )
        with self._lock:
            self._events.append(event)

        logging.debug("Event recorded: %s %s", event_type, data or "")
        self._maybe_persist()

    def get_all(self) -> list[dict]:
        """Return all events as a list of dicts (most recent last)."""
        with self._lock:
            return [e.to_dict() for e in self._events]

    def get_recent(self, count: int = 20) -> list[dict]:
        """Return the N most recent events."""
        with self._lock:
            items = list(self._events)
        return [e.to_dict() for e in items[-count:]]

    def get_by_type(self, event_type: str) -> list[dict]:
        """Return all events of a given type."""
        with self._lock:
            return [e.to_dict() for e in self._events if e.type == event_type]

    def count_today(self, event_type: str) -> int:
        """Count events of a given type recorded today."""
        today = datetime.now().date().isoformat()
        with self._lock:
            return sum(
                1
                for e in self._events
                if e.type == event_type and e.ts.startswith(today)
            )

    def _maybe_persist(self) -> None:
        """Persist to disk if enough time has passed since last persist."""
        now = time.time()
        if now - self._last_persist < self._persist_interval:
            return
        self._persist_to_disk()

    def persist_now(self) -> None:
        """Force immediate persistence to disk."""
        self._persist_to_disk()

    def _persist_to_disk(self) -> None:
        """Write events to JSON file."""
        try:
            data = self.get_all()
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persist_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(data, separators=(",", ":")), encoding="utf-8"
            )
            tmp_path.rename(self._persist_path)
            self._last_persist = time.time()
            logging.debug(
                "Events persisted: %d events -> %s", len(data), self._persist_path
            )
        except PermissionError:
            logging.debug("Events: impossible d'ecrire %s", self._persist_path)
        except Exception as e:
            logging.debug("Events: erreur persistence -- %s", e)

    def _load_from_disk(self) -> None:
        """Load events from JSON file if it exists."""
        try:
            if not self._persist_path.exists():
                return
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return
            for item in raw:
                if isinstance(item, dict) and "ts" in item and "type" in item:
                    event = Event(
                        ts=item["ts"],
                        type=item["type"],
                        data=item.get("data", {}),
                    )
                    self._events.append(event)
            logging.debug(
                "Events loaded: %d events from %s",
                len(self._events),
                self._persist_path,
            )
        except (json.JSONDecodeError, PermissionError) as e:
            logging.debug(
                "Events: impossible de charger %s -- %s", self._persist_path, e
            )


def _serialize(value: object) -> object:
    """Convert a value to a JSON-serializable type."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)
