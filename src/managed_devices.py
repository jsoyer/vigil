"""managed_devices.py -- registre des equipements TP-Link MR110 pilotables.

Point d'entree unique des commandes operateur (API + dashboard + boutons
d'action Ntfy) sur les
equipements declares via `TPLINK_<n>_*` (voir config.py). Ce module ne
construit un `TplinkDriver` que pour un equipement effectivement declare
(invariant C1 -- import vendor paresseux : `drivers/tplink.py` n'importe
`tplinkrouterc6u` que dans le corps de `_default_client_factory`, jamais au
niveau module ; ce fichier ne fait qu'instancier `TplinkDriver`, jamais la lib
vendor elle-meme).

Trois garanties portees ici, au-dela de ce que le driver garantit deja :
- **Cache court** (`status_cache_ttl`, defaut 60s) : plusieurs lectures
  rapprochees d'un meme equipement ne rouvrent pas de session admin.
- **Verrou par equipement** (C5) : les MR110 n'acceptent qu'une session admin
  a la fois -- les commandes concurrentes sur le meme equipement se
  serialisent. Deux equipements differents ne se bloquent jamais entre eux.
- **Un seul reessai** sur refus de session cote routeur (jamais de boucle) :
  applique a `check()` (ProbeResult.UNKNOWN) et a `confirm_reboot()`
  (`driver.reboot()` renvoie False).

C6 (aucune action destructive automatique) est garanti par construction :
`reboot()` du driver n'est jamais appele ailleurs que dans `confirm_reboot()`,
qui exige un jeton valide obtenu via `confirm.py` (usage unique, TTL court).
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

import confirm
import events
import history
import messages
import peer as peer_mod
from config import (
    API_TOKEN,
    CHECK_INTERVAL,
    INSTANCE_PRIORITY,
    PEER_IP,
    PEER_PORT,
    TPLINK_DEVICES,
    TplinkDeviceConfig,
)
from drivers._base import RouterHealth, RouterMetrics, RouterReadiness
from drivers.tplink import ProbeResult, TplinkDriver
from notifier import notify

CONFIRM_ACTION_REBOOT = "tplink_reboot"
DEFAULT_STATUS_CACHE_TTL = 60.0

# --- Detection d'usage (1.2, Sprint 1 A2) -- calibre LTE Cat 4 ---
CAT4_DOWNLINK_BPS = 150_000_000  # theorique descendant (~150 Mb/s)
CAT4_UPLINK_BPS = 50_000_000  # theorique montant (~50 Mb/s)
SATURATION_RATIO = 0.8  # "proche du plafond" -- 80% du theorique
MAX_CLIENTS = 32  # plafond materiel MR110
USAGE_DEBOUNCE_CYCLES = 2  # anti-rebond -- pic isole ignore

USAGE_IDLE = "idle"
USAGE_IN_USE = "in_use"
USAGE_SATURATED = "saturated"
USAGE_UNKNOWN = "unknown"

# Store de quota partage par le module -- persistance JSON (history.py),
# un seul fichier pour tous les equipements.
_quota_store = history.QuotaStore()


def _default_driver_factory(cfg: TplinkDeviceConfig) -> TplinkDriver:
    return TplinkDriver(
        host=cfg.host,
        password=cfg.password,
        label=cfg.label,
        mode=cfg.mode,
        bridge_host=cfg.bridge_host,
        rsrp_min=cfg.rsrp_min,
        rsrq_min=cfg.rsrq_min,
        snr_min=cfg.snr_min,
    )


def _status_dict(
    device_id: str,
    cfg: TplinkDeviceConfig,
    health: RouterHealth,
    readiness: RouterReadiness,
    metrics: RouterMetrics,
) -> dict:
    return {
        "id": device_id,
        "label": cfg.label,
        "mode": cfg.mode,
        "reachable": health.reachable,
        "failed_hop": health.failed_hop.value if health.failed_hop else None,
        "detail": health.detail,
        "rtt_ms": health.rtt_ms,
        "readiness": readiness.state.value,
        "readiness_reasons": list(readiness.reasons),
        "network_type": metrics.network_type,
        "sim_status": metrics.sim_status,
        "signal_bars": metrics.signal_bars,
        "rsrp": metrics.rsrp,
        "rsrq": metrics.rsrq,
        "snr": metrics.snr,
        "isp_name": metrics.isp_name,
        "wan_ip": metrics.wan_ip,
        "clients_total": metrics.clients_total,
        "rx_speed_bps": metrics.rx_speed_bps,
        "tx_speed_bps": metrics.tx_speed_bps,
        "data_used_bytes": metrics.data_used_bytes,
        "checked_at": time.time(),
    }


def _check_dict(
    device_id: str, cfg: TplinkDeviceConfig, health: RouterHealth, result: ProbeResult
) -> dict:
    return {
        "id": device_id,
        "label": cfg.label,
        "attached": health.reachable,
        "result": result.value,
        "data_confirmed": result is ProbeResult.OK,
    }


def _traffic_warning(status: dict) -> tuple[bool, str | None]:
    """Avertit si l'equipement semble porter du trafic actuellement.

    Best-effort : champs absents (`None`) => pas d'avertissement (jamais de
    faux positif faute de donnee, mais jamais non plus un faux negatif
    invente -- si le champ est present et non nul, c'est signale)."""
    rx = status.get("rx_speed_bps")
    tx = status.get("tx_speed_bps")
    clients = status.get("clients_total")
    reasons: list[str] = []
    if isinstance(rx, (int, float)) and rx > 0:
        reasons.append(f"debit descendant {rx} bps")
    if isinstance(tx, (int, float)) and tx > 0:
        reasons.append(f"debit montant {tx} bps")
    if isinstance(clients, int) and clients > 0:
        reasons.append(f"{clients} client(s) associe(s)")
    if reasons:
        return True, (
            "cet equipement semble porter du trafic actuellement ("
            + ", ".join(reasons)
            + ") -- un reboot va couper ce trafic."
        )
    return False, None


def _classify_usage(
    rx_speed_bps: object, tx_speed_bps: object, clients_total: object
) -> str:
    """Classifie l'usage instantane depuis les metriques MR110. Champs
    absents (`None`) => `unknown`, jamais un etat invente."""
    rx = rx_speed_bps if isinstance(rx_speed_bps, (int, float)) else None
    tx = tx_speed_bps if isinstance(tx_speed_bps, (int, float)) else None
    clients = clients_total if isinstance(clients_total, int) else None

    if rx is None and tx is None and clients is None:
        return USAGE_UNKNOWN

    rx = rx or 0
    tx = tx or 0
    clients = clients or 0

    saturated = (
        rx >= CAT4_DOWNLINK_BPS * SATURATION_RATIO
        or tx >= CAT4_UPLINK_BPS * SATURATION_RATIO
        or clients >= MAX_CLIENTS
    )
    if saturated:
        return USAGE_SATURATED
    if rx > 0 or tx > 0 or clients > 0:
        return USAGE_IN_USE
    return USAGE_IDLE


class UsageTracker:
    """Anti-rebond (1.2) : un etat n'est confirme -- et notifie -- qu'apres
    `debounce_cycles` releves consecutifs concordants. Un pic isole de
    trafic de management ne declenche donc jamais d'alerte."""

    def __init__(self, debounce_cycles: int = USAGE_DEBOUNCE_CYCLES) -> None:
        self._debounce_cycles = debounce_cycles
        self._confirmed: dict[str, str] = {}
        self._pending: dict[str, tuple[str, int]] = {}

    def update(
        self,
        device_id: str,
        rx_speed_bps: object,
        tx_speed_bps: object,
        clients_total: object,
    ) -> tuple[str, bool]:
        """Retourne (etat_confirme, changed). `changed` est True seulement
        au moment ou l'etat confirme bascule reellement."""
        raw = _classify_usage(rx_speed_bps, tx_speed_bps, clients_total)
        confirmed = self._confirmed.get(device_id, USAGE_IDLE)

        if raw == USAGE_UNKNOWN:
            return confirmed, False

        if raw == confirmed:
            self._pending.pop(device_id, None)
            return confirmed, False

        cand, count = self._pending.get(device_id, (None, 0))
        if cand == raw:
            count += 1
        else:
            cand, count = raw, 1

        if count >= self._debounce_cycles:
            self._confirmed[device_id] = raw
            self._pending.pop(device_id, None)
            return raw, True

        self._pending[device_id] = (cand, count)
        return confirmed, False

    def confirmed_state(self, device_id: str) -> str | None:
        """Etat d'usage confirme (idle/in_use/saturated), pour exposition
        Home Assistant (Sprint 3 A2). None tant qu'aucun releve n'a ete
        confirme -- jamais un etat invente (C13)."""
        return self._confirmed.get(device_id)


class ManagedDeviceRegistry:
    """Registre des equipements TP-Link declares -- un `TplinkDriver` par
    equipement, construit paresseusement au premier acces.

    `devices` et `driver_factory` sont injectables pour les tests (aucun
    acces reseau). En production, la valeur par defaut lit `TPLINK_DEVICES`
    (config.py) et construit de vrais `TplinkDriver`.
    """

    def __init__(
        self,
        devices: list[TplinkDeviceConfig]
        | tuple[TplinkDeviceConfig, ...]
        | None = None,
        driver_factory: Callable[[TplinkDeviceConfig], TplinkDriver] | None = None,
        status_cache_ttl: float = DEFAULT_STATUS_CACHE_TTL,
        event_log: object | None = None,
        ntfy_send: Callable | None = None,
        quota_store: object | None = None,
    ) -> None:
        source = TPLINK_DEVICES if devices is None else devices
        self._configs: dict[str, TplinkDeviceConfig] = {str(d.index): d for d in source}
        self._driver_factory = driver_factory or _default_driver_factory
        self._status_cache_ttl = status_cache_ttl
        self._event_log = event_log
        # Ntfy-first S2 : fonction `send` injectee pour publier les boutons
        # Actions (confirmer/annuler) sur une demande de reboot. La
        # publication doit avoir lieu quel que soit l'origine de la demande
        # (dashboard OU api), jamais conditionnee a un handler specifique.
        # `None` par defaut = no-op (tests, Ntfy non configure).
        self._ntfy_send = ntfy_send

        self._registry_lock = threading.Lock()
        self._drivers: dict[str, TplinkDriver] = {}
        self._device_locks: dict[str, threading.Lock] = {}

        self._cache_lock = threading.Lock()
        self._status_cache: dict[str, tuple[float, dict]] = {}

        # A2 Sprint 1 -- quota, usage, sonde, election (C12/C18/C20/C11).
        # `quota_store` injectable pour les tests (fichier temporaire) ;
        # partage le module-level `_quota_store` par defaut en production.
        self._quota_store = quota_store if quota_store is not None else _quota_store
        self._usage_tracker = UsageTracker(debounce_cycles=USAGE_DEBOUNCE_CYCLES)
        self._readiness_state: dict[str, str] = {}
        self._hop_state: dict[str, str | None] = {}
        self._link_state: dict[str, str] = {}
        self._leak_warned: dict[str, bool] = {}
        self._last_probe_at: dict[str, float] = {}
        self._last_reachable: dict[str, bool] = {}
        self._peer_unreachable_since: dict[str, float] = {}
        self._split_brain_warned: dict[str, bool] = {}
        self._polling_thread: threading.Thread | None = None
        # Sprint 3 A2 -- dernier resultat de sonde bout-en-bout confirme
        # (ProbeResult.value : "ok"/"fail"/"leak"), et son horodatage, pour
        # exposition Home Assistant (C13 -- jamais invente, absent tant
        # qu'aucune sonde n'a confirme un resultat).
        self._last_probe_result: dict[str, str] = {}
        self._last_probe_result_at: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_log(self, event_log: object | None) -> None:
        self._event_log = event_log

    def set_ntfy_send(self, ntfy_send: Callable | None) -> None:
        """Injecte la fonction de publication des boutons Ntfy (voir
        `__init__`). Idempotent, comme `set_event_log`."""
        self._ntfy_send = ntfy_send

    def record_event(self, event_type: str, **data: object) -> None:
        """Enregistre un evenement via l'event_log de bootstrap, si defini
        (Sprint 3 A2 -- permet au chemin de commande MQTT de tracer ses
        refus/actions sans dupliquer le wiring de l'event_log). No-op si
        `bootstrap()` n'a pas ete appele (ex. tests)."""
        if self._event_log is not None:
            self._event_log.record(event_type, **data)

    def device_ids(self) -> list[str]:
        return list(self._configs.keys())

    def _get_driver(self, device_id: str) -> TplinkDriver | None:
        cfg = self._configs.get(device_id)
        if cfg is None:
            return None
        with self._registry_lock:
            driver = self._drivers.get(device_id)
            if driver is None:
                driver = self._driver_factory(cfg)
                self._drivers[device_id] = driver
            return driver

    def _get_device_lock(self, device_id: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._device_locks.get(device_id)
            if lock is None:
                lock = threading.Lock()
                self._device_locks[device_id] = lock
            return lock

    # ------------------------------------------------------------------
    # Lecture -- cache court + verrou par equipement (C5)
    # ------------------------------------------------------------------

    def _cached_status(self, device_id: str) -> dict | None:
        with self._cache_lock:
            entry = self._status_cache.get(device_id)
        if entry is None:
            return None
        fetched_at, status = entry
        if time.monotonic() - fetched_at > self._status_cache_ttl:
            return None
        return status

    def get_status(self, device_id: str, force: bool = False) -> dict | None:
        cfg = self._configs.get(device_id)
        if cfg is None:
            return None

        if not force:
            cached = self._cached_status(device_id)
            if cached is not None:
                return cached

        elected, election_reason = self._is_elected(device_id, cfg)
        if not elected:
            return self._exposed_peer_status(device_id, cfg, election_reason)

        driver = self._get_driver(device_id)
        lock = self._get_device_lock(device_id)
        with lock:
            if not force:
                # Une autre thread a peut-etre deja rafraichi pendant qu'on
                # attendait le verrou -- evite une session admin de plus.
                cached = self._cached_status(device_id)
                if cached is not None:
                    return cached

            health = driver.health()
            readiness = driver.readiness()
            metrics = driver.metrics()
            status = _status_dict(device_id, cfg, health, readiness, metrics)

            self._last_reachable[device_id] = health.reachable

            now = time.time()
            in_use = self._update_usage(device_id, cfg, status)
            self._update_quota(device_id, cfg, status, in_use)
            self._update_readiness_notify(device_id, cfg, readiness, in_use)
            self._update_hop_notify(device_id, cfg, health)
            self._check_probe(device_id, cfg, driver, in_use, now)

            # Sprint 3 A2 -- champs additionnels pour exposition Home
            # Assistant (C13) : jamais invente, absent/None si jamais
            # confirme. Ajoutes ici (et non dans `_status_dict`, fonction
            # pure independante de l'etat du registre) pour que
            # `_exposed_peer_status` les propage automatiquement -- ils
            # transitent par le meme JSON que le reste du statut, via
            # l'endpoint `/api/tplink/<id>` existant.
            status["usage_state"] = self._usage_tracker.confirmed_state(device_id)
            status["in_use"] = in_use
            status["probe_result"] = self._last_probe_result.get(device_id)
            status["probe_result_at"] = self._last_probe_result_at.get(device_id)

            with self._cache_lock:
                self._status_cache[device_id] = (time.monotonic(), status)
            return status

    def list_devices(self) -> list[dict]:
        result = []
        for device_id in self._configs:
            status = self.get_status(device_id)
            if status is not None:
                result.append(status)
        return result

    # ------------------------------------------------------------------
    # Sonde a la demande -- non destructive, pas de confirmation (C11)
    # ------------------------------------------------------------------

    def check(self, device_id: str) -> dict | None:
        cfg = self._configs.get(device_id)
        if cfg is None:
            return None

        driver = self._get_driver(device_id)
        lock = self._get_device_lock(device_id)
        with lock:
            health = driver.health()
            result = driver.probe_end_to_end()
            if result is ProbeResult.UNKNOWN:
                logging.warning(
                    "TPLINK '%s' : sonde bout-en-bout indisponible, un seul reessai",
                    cfg.label,
                )
                result = driver.probe_end_to_end()

        # La lecture du statut n'invalide pas le cache de check() -- la
        # sonde peut avoir fait bouger les compteurs de trafic.
        with self._cache_lock:
            self._status_cache.pop(device_id, None)

        return _check_dict(device_id, cfg, health, result)

    # ------------------------------------------------------------------
    # Election du poller (C12) -- reutilise la priorite de peer.py
    # ------------------------------------------------------------------

    def _peer_device_status(self, device_id: str, timeout: float = 5.0) -> dict | None:
        """Interroge le statut TP-Link du peer via son API HTTP existante
        (`/api/tplink/{device_id}`, livree en A1) -- jamais une deuxieme
        logique de failover, juste une lecture a distance du meme format
        que `get_status()` local. Jamais d'exception levee."""
        if not PEER_IP:
            return None
        # PEER_IP est une adresse tailscale (coordination HA -- meme usage que
        # query_peer() dans peer.py), jamais une IP LAN ou un domaine public.
        url = f"http://{PEER_IP}:{PEER_PORT}/api/tplink/{device_id}"  # tailscale
        headers = {"Accept": "application/json"}
        if API_TOKEN:
            headers["Authorization"] = f"Bearer {API_TOKEN}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("id") == device_id:
                return data
        except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError) as e:
            logging.debug("Peer TP-Link '%s' -- %s", device_id, e)
        return None

    def _track_peer_unreachable(
        self, device_id: str, peer_reachable: bool, now: float
    ) -> float:
        if peer_reachable:
            self._peer_unreachable_since.pop(device_id, None)
            self._split_brain_warned.pop(device_id, None)
            return 0.0
        since = self._peer_unreachable_since.get(device_id)
        if since is None:
            since = now
            self._peer_unreachable_since[device_id] = since
        return since

    def _is_elected(
        self, device_id: str, cfg: TplinkDeviceConfig, now: float | None = None
    ) -> tuple[bool, str]:
        if now is None:
            now = time.time()
        if not PEER_IP:
            return True, "standalone"

        my_reachable = self._last_reachable.get(device_id, True)

        peer_ws = peer_mod.query_peer(retries=1, timeout=3)
        peer_state_reachable = peer_ws is not None

        peer_device = (
            self._peer_device_status(device_id) if peer_state_reachable else None
        )
        peer_device_reachable = bool(peer_device) and bool(peer_device.get("reachable"))
        peer_mode = peer_device.get("mode") if peer_device else None
        peer_priority = peer_ws.instance_priority if peer_ws is not None else None

        # Capture avant clear : `_track_peer_unreachable` remet a zero des
        # que le peer redevient joignable, donc `since` (utilise pour
        # l'election elle-meme) ne suffit pas a savoir si on VENAIT de
        # considerer le peer injoignable -- necessaire pour ne declencher
        # le split-brain que sur une reprise apres coupure, jamais sur une
        # election normale (bridged ou priorite) avec peer deja joignable.
        was_unreachable_since = self._peer_unreachable_since.get(device_id, 0.0)
        since = self._track_peer_unreachable(device_id, peer_state_reachable, now)

        elected, reason = peer_mod.elect_poller(
            my_priority=INSTANCE_PRIORITY,
            my_mode=cfg.mode,
            my_reachable=my_reachable,
            peer_reachable=peer_device_reachable if peer_state_reachable else False,
            peer_priority=peer_priority,
            peer_mode=peer_mode,
            threshold_reached_time=since,
            now=now,
        )

        # Split-brain (C12) : uniquement si je venais de considerer le peer
        # injoignable (was_unreachable_since > 0, capture AVANT que ce
        # meme appel ne remette le compteur a zero) et qu'il repond a
        # nouveau maintenant, avec un etat recent -- signature d'une
        # partition reseau plutot qu'une vraie panne (voir detect_split_
        # brain). Ne pas exiger "takeover" dans `reason` : au moment ou le
        # peer redevient joignable, elect_poller retombe deja sur ses
        # branches normales (bridged/priorite) -- exiger "takeover" ici
        # rendrait la condition inatteignable (le peer ne peut pas etre a
        # la fois injoignable pour threshold_reached_time>0 et joignable
        # pour peer_ws is not None dans le meme appel). Jamais declenche
        # sur une election ordinaire avec peer deja joignable depuis
        # longtemps, puisque `was_unreachable_since` reste alors a 0.
        if elected and peer_ws is not None and was_unreachable_since > 0:
            if peer_mod.detect_split_brain(peer_ws, took_over=True, now=now):
                self._notify_split_brain(device_id, cfg)

        return elected, reason

    def _exposed_peer_status(
        self, device_id: str, cfg: TplinkDeviceConfig, election_reason: str
    ) -> dict:
        peer_data = self._peer_device_status(device_id)
        if peer_data is not None:
            exposed = dict(peer_data)
            fetched_at = peer_data.get("checked_at")
            exposed["from_peer"] = True
            exposed["age_seconds"] = (
                round(time.time() - fetched_at, 1)
                if isinstance(fetched_at, (int, float))
                else None
            )
            exposed["poller_election_reason"] = election_reason
            return exposed
        return {
            "id": device_id,
            "label": cfg.label,
            "from_peer": True,
            "age_seconds": None,
            "reachable": None,
            "readiness": "unknown",
            "poller_election_reason": election_reason,
        }

    def _notify_split_brain(self, device_id: str, cfg: TplinkDeviceConfig) -> None:
        if self._split_brain_warned.get(device_id):
            return
        self._split_brain_warned[device_id] = True
        text, level, ctx = messages.tplink_split_brain(cfg.label)
        notify(text, level, ctx)
        if self._event_log is not None:
            self._event_log.record(
                events.TPLINK_SPLIT_BRAIN, device_id=device_id, label=cfg.label
            )

    # ------------------------------------------------------------------
    # Quota data (C20) -- accumulation de deltas positifs, persistee
    # ------------------------------------------------------------------

    def _update_quota(
        self, device_id: str, cfg: TplinkDeviceConfig, status: dict, in_use: bool
    ) -> None:
        if cfg.quota_volume_mb is None:
            return
        raw_counter = status.get("data_used_bytes")
        state = self._quota_store.record_reading(
            device_id, raw_counter, cfg.quota_reset_day
        )
        if state is None:
            return
        quota_bytes = cfg.quota_volume_mb * 1_000_000
        if quota_bytes <= 0:
            return
        pct = state.accumulated_bytes / quota_bytes * 100
        if pct >= cfg.quota_alert_pct and not state.already_warned:
            self._quota_store.mark_warned(device_id)
            text, level, ctx = messages.data_quota_warning(cfg.label, pct, in_use)
            notify(text, level, ctx)
            if self._event_log is not None:
                self._event_log.record(
                    events.DATA_QUOTA_WARNING,
                    device_id=device_id,
                    label=cfg.label,
                    pct=round(pct, 1),
                    in_use=in_use,
                )

    def quota_status(self, device_id: str) -> dict | None:
        """Etat de quota courant pour affichage (dashboard/HA, sprints 2/3)."""
        cfg = self._configs.get(device_id)
        if cfg is None or cfg.quota_volume_mb is None:
            return None
        state = self._quota_store.get_state(device_id)
        if state is None:
            return None
        quota_bytes = cfg.quota_volume_mb * 1_000_000
        pct = (state.accumulated_bytes / quota_bytes * 100) if quota_bytes else 0.0
        return {
            "cycle_bytes_used": state.accumulated_bytes,
            "quota_bytes": quota_bytes,
            "pct": round(pct, 1),
            "next_reset": self._quota_store.next_reset_date(
                device_id, cfg.quota_reset_day
            ),
        }

    # ------------------------------------------------------------------
    # Detection d'usage (1.2) -- notifie au changement d'etat seulement
    # ------------------------------------------------------------------

    def _update_usage(
        self, device_id: str, cfg: TplinkDeviceConfig, status: dict
    ) -> bool:
        """Retourne `in_use` (bool) pour l'escalade des autres notifs (C18)."""
        confirmed, changed = self._usage_tracker.update(
            device_id,
            status.get("rx_speed_bps"),
            status.get("tx_speed_bps"),
            status.get("clients_total"),
        )
        if changed:
            if confirmed == USAGE_IN_USE:
                text, level, ctx = messages.tplink_in_use(cfg.label)
                event_type = events.TPLINK_IN_USE
            elif confirmed == USAGE_SATURATED:
                text, level, ctx = messages.tplink_saturated(cfg.label)
                event_type = events.TPLINK_SATURATED
            else:
                text, level, ctx = messages.tplink_idle(cfg.label)
                event_type = events.TPLINK_IDLE
            notify(text, level, ctx)
            if self._event_log is not None:
                self._event_log.record(event_type, device_id=device_id, label=cfg.label)
        return confirmed in (USAGE_IN_USE, USAGE_SATURATED)

    # ------------------------------------------------------------------
    # Readiness et chemin d'audit -- notification au changement d'etat
    # ------------------------------------------------------------------

    def _update_readiness_notify(
        self,
        device_id: str,
        cfg: TplinkDeviceConfig,
        readiness: RouterReadiness,
        in_use: bool,
    ) -> None:
        prev = self._readiness_state.get(device_id)
        current = readiness.state.value
        if current == prev:
            return
        self._readiness_state[device_id] = current
        if current == "degraded":
            reason = (
                "; ".join(readiness.reasons) if readiness.reasons else "raison inconnue"
            )
            text, level, ctx = messages.backup_degraded(cfg.label, reason, in_use)
            notify(text, level, ctx)
            if self._event_log is not None:
                self._event_log.record(
                    events.BACKUP_DEGRADED,
                    device_id=device_id,
                    label=cfg.label,
                    reason=reason,
                    in_use=in_use,
                )
        elif current == "ok" and prev is not None:
            text, level, ctx = messages.backup_ready(cfg.label)
            notify(text, level, ctx)
            if self._event_log is not None:
                self._event_log.record(
                    events.BACKUP_READY, device_id=device_id, label=cfg.label
                )

    def _update_hop_notify(
        self, device_id: str, cfg: TplinkDeviceConfig, health: RouterHealth
    ) -> None:
        prev = self._hop_state.get(device_id)
        current = health.failed_hop.value if health.failed_hop else None
        if current == prev:
            return
        self._hop_state[device_id] = current
        if current in ("bridge", "route"):
            text, level, ctx = messages.tplink_hop_failed(cfg.label, current)
            notify(text, level, ctx)
            if self._event_log is not None:
                self._event_log.record(
                    events.TPLINK_HOP_FAILED,
                    device_id=device_id,
                    label=cfg.label,
                    hop=current,
                )

    # ------------------------------------------------------------------
    # Sonde periodique bout-en-bout (C11) -- opt-in, jamais de reboot (C6)
    # ------------------------------------------------------------------

    def _check_probe(
        self,
        device_id: str,
        cfg: TplinkDeviceConfig,
        driver: TplinkDriver,
        in_use: bool,
        now: float,
    ) -> None:
        if not cfg.probe_enabled:
            return
        last = self._last_probe_at.get(device_id, 0.0)
        if now - last < cfg.probe_interval:
            return
        self._last_probe_at[device_id] = now
        result = driver.probe_end_to_end()

        if result is ProbeResult.UNKNOWN:
            return

        # Sprint 3 A2 -- dernier resultat confirme, expose via get_status()
        # (C13 : jamais "unknown" invente ici, seuls ok/fail/leak arrivent
        # a ce point).
        self._last_probe_result[device_id] = result.value
        self._last_probe_result_at[device_id] = now

        if result is ProbeResult.LEAK:
            if not self._leak_warned.get(device_id, False):
                text, level, ctx = messages.tplink_probe_leak(cfg.label)
                notify(text, level, ctx)
                if self._event_log is not None:
                    self._event_log.record(
                        events.TPLINK_PROBE_LEAK, device_id=device_id, label=cfg.label
                    )
                self._leak_warned[device_id] = True
            return
        self._leak_warned[device_id] = False

        new_link = "up" if result is ProbeResult.OK else "down"
        prev_link = self._link_state.get(device_id)
        if new_link != prev_link:
            self._link_state[device_id] = new_link
            if new_link == "down":
                text, level, ctx = messages.tplink_link_down(cfg.label, in_use)
                event_type = events.TPLINK_LINK_DOWN
            else:
                text, level, ctx = messages.tplink_link_up(cfg.label)
                event_type = events.TPLINK_LINK_UP
            notify(text, level, ctx)
            if self._event_log is not None:
                self._event_log.record(event_type, device_id=device_id, label=cfg.label)

    # ------------------------------------------------------------------
    # Sondage periodique de fond (C12) -- idempotent, thread daemon
    # ------------------------------------------------------------------

    def start_periodic_polling(self, interval: float | None = None) -> None:
        """Demarre le sondage periodique (quota/usage/sonde/election) en
        tache de fond. Idempotent -- un second appel est un no-op."""
        if self._polling_thread is not None:
            return
        poll_interval = interval or CHECK_INTERVAL

        def _loop() -> None:
            while True:
                for dev_id in list(self._configs.keys()):
                    try:
                        self.get_status(dev_id, force=True)
                    except Exception as e:
                        logging.warning("Sondage periodique '%s' -- %s", dev_id, e)
                time.sleep(poll_interval)

        self._polling_thread = threading.Thread(target=_loop, daemon=True)
        self._polling_thread.start()

    # ------------------------------------------------------------------
    # Actions destructives (C6) -- toujours confirmees, jamais automatiques
    # ------------------------------------------------------------------

    def request_reboot(self, device_id: str, origin: str) -> dict | None:
        cfg = self._configs.get(device_id)
        if cfg is None:
            return None

        status = self.get_status(device_id) or {}
        warning, warning_reason = _traffic_warning(status)

        token = confirm.request_confirmation(
            CONFIRM_ACTION_REBOOT,
            context={"device_id": device_id, "requested_by": origin},
        )

        # Ntfy-first S2 : boutons Actions (confirmer/annuler) publies EN
        # PLUS du dict retourne par cette methode (chemin API/dashboard
        # inchange), jamais a sa place. Quelle que soit l'origine de la
        # demande (dashboard ou api), la confirmation devient joignable par
        # bouton. Jamais bloquant : une erreur de publication ne doit jamais
        # empecher l'emission du jeton (le chemin API/dashboard reste
        # utilisable).
        if self._ntfy_send is not None:
            try:
                self._ntfy_send(
                    cfg.label, warning, warning_reason, CONFIRM_ACTION_REBOOT, token
                )
            except Exception as e:
                logging.warning(
                    "Ntfy: echec publication des boutons de confirmation "
                    "pour '%s' -- %s",
                    cfg.label,
                    e,
                )

        return {
            "token": token,
            "device_id": device_id,
            "label": cfg.label,
            "warning": warning,
            "warning_reason": warning_reason,
        }

    def confirm_reboot(
        self, token: str, origin: str, expected_device_id: str | None = None
    ) -> dict:
        ctx = confirm.validate(token, CONFIRM_ACTION_REBOOT)
        if ctx is None:
            return {
                "ok": False,
                "executed": False,
                "error": "jeton invalide, expire ou deja utilise",
            }

        device_id = ctx.get("device_id", "")
        if expected_device_id is not None and device_id != expected_device_id:
            return {
                "ok": False,
                "executed": False,
                "error": "jeton ne correspond pas a cet equipement",
            }

        cfg = self._configs.get(device_id)
        driver = self._get_driver(device_id)
        if cfg is None or driver is None:
            return {"ok": False, "executed": False, "error": "equipement inconnu"}

        lock = self._get_device_lock(device_id)
        with lock:
            ok = driver.reboot()
            if not ok:
                logging.warning(
                    "TPLINK '%s' : reboot refuse (session admin probablement occupee), "
                    "un seul reessai",
                    cfg.label,
                )
                ok = driver.reboot()
            with self._cache_lock:
                self._status_cache.pop(device_id, None)

        text_fn = messages.tplink_reboot if ok else messages.tplink_reboot_failed
        text, level, notif_ctx = text_fn(cfg.label, origin)
        notify(text, level, notif_ctx)

        if self._event_log is not None:
            event_type = events.TPLINK_REBOOT if ok else events.TPLINK_REBOOT_FAILED
            self._event_log.record(
                event_type, device_id=device_id, label=cfg.label, origin=origin
            )

        return {"ok": ok, "executed": True, "device_id": device_id, "label": cfg.label}


# ---------------------------------------------------------------------------
# Instance par defaut (production) -- construite sans jamais instancier de
# driver (C1) : `_configs` est un simple dict, `_drivers` reste vide tant
# qu'aucune methode n'est appelee sur un equipement declare.
# ---------------------------------------------------------------------------

registry = ManagedDeviceRegistry()


def bootstrap(event_log: object | None) -> None:
    """Point d'entree production, appele par `http_server.start_http_server`.

    Idempotent : peut etre appele plusieurs fois sans effet de bord --
    `set_event_log` est une simple affectation et `start_periodic_polling`
    ne demarre le thread de fond qu'une seule fois. Depuis le
    debranchement du bot interactif historique (Ntfy-first S5), il n'y a
    plus de handlers a enregistrer ici : le pilotage TP-Link passe par le
    dashboard et l'API HTTP (`/api/tplink/*`, `/api/confirm/*`).

    A2 Sprint 1 : demarre aussi le sondage periodique (quota, usage,
    sonde, election C12) en tache de fond.
    """
    registry.set_event_log(event_log)
    registry.start_periodic_polling()
