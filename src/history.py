"""History -- ring buffer for time-series data points (score, latency)."""

import calendar
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime
from datetime import time as _dt_time


@dataclass(frozen=True)
class DataPoint:
    ts: float
    score: int
    gateway_rtt: float | None
    internet_rtt: float | None
    download_mbps: float | None = None


class HistoryBuffer:
    """Thread-safe ring buffer storing the last N data points."""

    def __init__(self, max_points: int = 120) -> None:
        # 120 points * 30s interval = 1 hour (was 240 = 2h, saves ~69 KB on Pi Zero)
        self._points: deque[DataPoint] = deque(maxlen=max_points)
        self._lock = threading.Lock()

    def record(
        self,
        score: int,
        gateway_rtt: float | None,
        internet_rtt: float | None,
        download_mbps: float | None = None,
    ) -> None:
        point = DataPoint(
            ts=time.time(),
            score=score,
            gateway_rtt=round(gateway_rtt, 1) if gateway_rtt is not None else None,
            internet_rtt=round(internet_rtt, 1) if internet_rtt is not None else None,
            download_mbps=round(download_mbps, 2)
            if download_mbps is not None
            else None,
        )
        with self._lock:
            self._points.append(point)

    def get_all(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "ts": p.ts,
                    "score": p.score,
                    "gw_rtt": p.gateway_rtt,
                    "inet_rtt": p.internet_rtt,
                    "dl_mbps": p.download_mbps,
                }
                for p in self._points
            ]


@dataclass(frozen=True)
class QuotaCycleState:
    """Etat persiste du cycle de facturation data d'un equipement TP-Link.

    `cycle_start` est l'epoch UTC de minuit local du jour de reset en
    cours. `accumulated_bytes` s'obtient par accumulation de deltas
    positifs (jamais par lecture directe du compteur brut -- voir
    INVARIANTS.md "Le suivi de conso survit aux remises a zero du
    compteur"). `last_raw_counter` est le dernier releve brut connu,
    utilise pour calculer le prochain delta -- `None` tant qu'aucune
    lecture n'a ete faite dans le cycle courant."""

    device_id: str
    cycle_start: float
    accumulated_bytes: int = 0
    last_raw_counter: int | None = None
    already_warned: bool = False
    last_updated: float = 0.0


def _clamp_reset_day(year: int, month: int, reset_day: int) -> int:
    """Jour de reset borne a la longueur reelle du mois (C20 -- mois
    courts : jour 31 dans un mois de 30 jours devient le dernier jour)."""
    last_day = calendar.monthrange(year, month)[1]
    return min(max(reset_day, 1), last_day)


def _cycle_boundary_for(today: date, reset_day: int) -> date:
    """Date du dernier reset <= today (C20 -- calcul sur la date
    calendaire, jamais un nombre d'heures ecoulees : un jour de
    changement d'heure fait 23 ou 25h)."""
    clamped = _clamp_reset_day(today.year, today.month, reset_day)
    if today.day >= clamped:
        return date(today.year, today.month, clamped)
    prev_month = 12 if today.month == 1 else today.month - 1
    prev_year = today.year - 1 if today.month == 1 else today.year
    clamped_prev = _clamp_reset_day(prev_year, prev_month, reset_day)
    return date(prev_year, prev_month, clamped_prev)


def _next_cycle_boundary(boundary: date, reset_day: int) -> date:
    """Date du prochain reset apres `boundary`."""
    month = 1 if boundary.month == 12 else boundary.month + 1
    year = boundary.year + 1 if boundary.month == 12 else boundary.year
    clamped = _clamp_reset_day(year, month, reset_day)
    return date(year, month, clamped)


def _local_midnight_epoch(d: date) -> float:
    """Epoch UTC correspondant a minuit heure locale de l'hote pour la
    date `d` (C20 -- fuseau local, jamais UTC)."""
    dt = datetime.combine(d, _dt_time.min)
    return time.mktime(dt.timetuple())


class QuotaStore:
    """Suivi persiste de la conso data par equipement, robuste aux
    remises a zero du compteur routeur et aux bascules de cycle de
    facturation (C20). Ecriture JSON atomique (.tmp + rename), meme
    pattern que EventLog dans events.py."""

    def __init__(
        self,
        persist_path: str = "/var/lib/vigil/tplink_quota.json",
    ) -> None:
        self._persist_path = persist_path
        self._lock = threading.Lock()
        self._states: dict[str, QuotaCycleState] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return
            for device_id, entry in raw.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    self._states[device_id] = QuotaCycleState(
                        device_id=device_id,
                        cycle_start=float(entry.get("cycle_start", 0.0)),
                        accumulated_bytes=int(entry.get("accumulated_bytes", 0)),
                        last_raw_counter=(
                            int(entry["last_raw_counter"])
                            if entry.get("last_raw_counter") is not None
                            else None
                        ),
                        already_warned=bool(entry.get("already_warned", False)),
                        last_updated=float(entry.get("last_updated", 0.0)),
                    )
                except (TypeError, ValueError) as e:
                    logging.warning(
                        "QuotaStore: entree illisible pour '%s' -- %s", device_id, e
                    )
        except (OSError, json.JSONDecodeError) as e:
            logging.warning("QuotaStore: lecture persistance impossible -- %s", e)

    def _persist(self) -> None:
        try:
            dirname = os.path.dirname(self._persist_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            payload = {
                device_id: {
                    "cycle_start": s.cycle_start,
                    "accumulated_bytes": s.accumulated_bytes,
                    "last_raw_counter": s.last_raw_counter,
                    "already_warned": s.already_warned,
                    "last_updated": s.last_updated,
                }
                for device_id, s in self._states.items()
            }
            tmp_path = self._persist_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, self._persist_path)
        except OSError as e:
            logging.warning("QuotaStore: persistance impossible -- %s", e)

    def record_reading(
        self,
        device_id: str,
        raw_counter: int | None,
        reset_day: int,
        now: float | None = None,
    ) -> QuotaCycleState | None:
        """Enregistre un releve de compteur brut. Retourne le nouvel
        etat, ou None si `raw_counter` est absent (champ non fourni par
        le firmware -- aucun etat invente)."""
        if raw_counter is None:
            return None
        if now is None:
            now = time.time()

        today_local = datetime.fromtimestamp(now).date()
        boundary = _cycle_boundary_for(today_local, reset_day)
        current_cycle_start = _local_midnight_epoch(boundary)

        with self._lock:
            prev = self._states.get(device_id)

            if prev is None or prev.cycle_start < current_cycle_start:
                new_state = QuotaCycleState(
                    device_id=device_id,
                    cycle_start=current_cycle_start,
                    accumulated_bytes=0,
                    last_raw_counter=raw_counter,
                    already_warned=False,
                    last_updated=now,
                )
            else:
                if prev.last_raw_counter is None:
                    delta = 0
                elif raw_counter >= prev.last_raw_counter:
                    delta = raw_counter - prev.last_raw_counter
                else:
                    # Compteur en baisse -- reset routeur non commande par
                    # QuotaStore (reboot, coupure secteur...). La conso
                    # jusqu'au reset (prev.last_raw_counter) est acquise,
                    # on y ajoute la nouvelle valeur qui represente ce qui
                    # a ete consomme depuis ce reset.
                    delta = prev.last_raw_counter + raw_counter
                    logging.info(
                        "QuotaStore '%s' : compteur en baisse (%d -> %d), "
                        "traite comme reset routeur",
                        device_id,
                        prev.last_raw_counter,
                        raw_counter,
                    )
                new_state = QuotaCycleState(
                    device_id=device_id,
                    cycle_start=prev.cycle_start,
                    accumulated_bytes=prev.accumulated_bytes + delta,
                    last_raw_counter=raw_counter,
                    already_warned=prev.already_warned,
                    last_updated=now,
                )

            self._states[device_id] = new_state
            self._persist()
            return new_state

    def mark_warned(self, device_id: str) -> None:
        with self._lock:
            state = self._states.get(device_id)
            if state is None:
                return
            self._states[device_id] = replace(state, already_warned=True)
            self._persist()

    def get_state(self, device_id: str) -> QuotaCycleState | None:
        with self._lock:
            return self._states.get(device_id)

    def next_reset_date(self, device_id: str, reset_day: int) -> str | None:
        with self._lock:
            state = self._states.get(device_id)
        if state is None:
            return None
        boundary = datetime.fromtimestamp(state.cycle_start).date()
        next_boundary = _next_cycle_boundary(boundary, reset_day)
        return next_boundary.isoformat()
