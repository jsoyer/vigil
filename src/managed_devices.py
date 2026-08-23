"""managed_devices.py -- registre des equipements TP-Link MR110 pilotables.

Point d'entree unique des commandes operateur (API + Telegram) sur les
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

import logging
import threading
import time
from typing import Callable

import confirm
import events
import messages
from config import TPLINK_DEVICES, TplinkDeviceConfig
from drivers._base import RouterHealth, RouterMetrics, RouterReadiness
from drivers.tplink import ProbeResult, TplinkDriver
from notifier import notify

CONFIRM_ACTION_REBOOT = "tplink_reboot"
DEFAULT_STATUS_CACHE_TTL = 60.0

_HOP_LABELS = {
    "bridge": "le pont (l'hote qui porte le lien WiFi vers le MR110)",
    "wireless": "le lien WiFi entre le pont et le MR110",
    "device": "le MR110 lui-meme",
    "route": "la route/le NAT vers le MR110 (defaut de configuration, pas une panne)",
}

_READINESS_LABELS = {"ok": "OK", "degraded": "DEGRADE", "unknown": "INCONNU"}


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
    ) -> None:
        source = TPLINK_DEVICES if devices is None else devices
        self._configs: dict[str, TplinkDeviceConfig] = {str(d.index): d for d in source}
        self._driver_factory = driver_factory or _default_driver_factory
        self._status_cache_ttl = status_cache_ttl
        self._event_log = event_log

        self._registry_lock = threading.Lock()
        self._drivers: dict[str, TplinkDriver] = {}
        self._device_locks: dict[str, threading.Lock] = {}

        self._cache_lock = threading.Lock()
        self._status_cache: dict[str, tuple[float, dict]] = {}

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_log(self, event_log: object | None) -> None:
        self._event_log = event_log

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
    `set_event_log` et `register_lte_handler` sont de simples affectations.
    """
    registry.set_event_log(event_log)
    _register_telegram_handlers(registry)


def _register_telegram_handlers(target_registry: "ManagedDeviceRegistry") -> None:
    import telegram_bot

    telegram_bot.register_lte_handler(
        "", _adapt_for_telegram(_make_handle_lte_all(target_registry))
    )
    telegram_bot.register_lte_handler(
        "status", _adapt_for_telegram(_make_handle_lte_status(target_registry))
    )
    telegram_bot.register_lte_handler(
        "check", _adapt_for_telegram(_make_handle_lte_check(target_registry))
    )
    telegram_bot.register_lte_handler(
        "reboot", _adapt_for_telegram(_make_handle_lte_reboot(target_registry))
    )
    telegram_bot.register_lte_handler(
        "confirm", _adapt_for_telegram(_make_handle_lte_confirm(target_registry))
    )

    # `/lte <id>` (sans le mot-cle 'status') -- forme raccourcie explicitement
    # listee par la spec (criteres d'acceptation, 3.7). Un identifiant
    # d'equipement (index numerique de TPLINK_<n>_*) ne collisionne jamais
    # avec les mots-cles reserves ci-dessus.
    for device_id in target_registry.device_ids():
        telegram_bot.register_lte_handler(
            device_id,
            _adapt_for_telegram(_make_handle_lte_bare_id(target_registry, device_id)),
        )


def _adapt_for_telegram(handler: Callable) -> Callable[[str, str, object], None]:
    """Adapte un handler `(args, chat_id, holder, send)` a la signature
    `LteHandler` attendue par `telegram_bot.register_lte_handler`
    (`(args, chat_id, holder) -> None`), en liant `send` a
    `telegram_bot.send_message`."""

    def wrapped(args: str, chat_id: str, holder: object) -> None:
        import telegram_bot

        handler(args, chat_id, holder, send=telegram_bot.send_message)

    return wrapped


# ---------------------------------------------------------------------------
# Handlers Telegram -- formatage francais, contexte riche (style existant)
#
# Chaque `_make_handle_lte_*` prend un registre en parametre (production ou
# double de test) et renvoie une fonction `(args, chat_id, holder, send)`
# directement testable sans dependre de `telegram_bot`.
# ---------------------------------------------------------------------------


def _format_device_line(d: dict) -> str:
    if not d["reachable"]:
        hop = d.get("failed_hop")
        hop_label = (
            _HOP_LABELS.get(hop, "cause non identifiee") if hop else "cause inconnue"
        )
        detail = d.get("detail") or ""
        return f"- {d['label']} : INJOIGNABLE -- {hop_label}. {detail}".rstrip()

    state_label = _READINESS_LABELS.get(d.get("readiness"), str(d.get("readiness")))
    parts = [f"- {d['label']} : {state_label}"]
    if d.get("rsrp") is not None:
        parts.append(f"RSRP {d['rsrp']}dBm")
    if d.get("network_type"):
        parts.append(str(d["network_type"]))
    if d.get("isp_name"):
        parts.append(str(d["isp_name"]))
    line = " | ".join(parts)
    reasons = d.get("readiness_reasons") or []
    if reasons:
        line += "\n  " + " ; ".join(reasons)
    return line


def _make_handle_lte_all(target_registry: ManagedDeviceRegistry) -> Callable:
    def handler(args: str, chat_id: str, holder: object, send: Callable) -> None:
        devices = target_registry.list_devices()
        if not devices:
            send(chat_id, "Aucun equipement TP-Link declare.")
            return
        lines = ["<b>Lignes de secours 4G</b>", ""]
        lines.extend(_format_device_line(d) for d in devices)
        send(chat_id, "\n".join(lines))

    return handler


def _make_handle_lte_status(target_registry: ManagedDeviceRegistry) -> Callable:
    def handler(args: str, chat_id: str, holder: object, send: Callable) -> None:
        device_id = args.strip()
        status = target_registry.get_status(device_id) if device_id else None
        if status is None:
            send(chat_id, f"Equipement TP-Link inconnu : '{device_id}'.")
            return
        send(chat_id, _format_device_line(status))

    return handler


def _make_handle_lte_bare_id(
    target_registry: ManagedDeviceRegistry, device_id: str
) -> Callable:
    """`/lte <id>` -- raccourci vers le detail d'un equipement, sans le
    mot-cle 'status'. `device_id` est fige par closure a l'enregistrement
    (voir `_register_telegram_handlers`) : l'id fait partie de la
    sous-commande elle-meme, pas des arguments restants."""
    status_handler = _make_handle_lte_status(target_registry)

    def handler(args: str, chat_id: str, holder: object, send: Callable) -> None:
        status_handler(device_id, chat_id, holder, send=send)

    return handler


def _format_check_result(result: dict) -> str:
    lines = [f"<b>Sonde bout-en-bout -- {result['label']}</b>", ""]
    lines.append(
        f"Attache au reseau 4G (declare par le routeur) : "
        f"{'OUI' if result['attached'] else 'NON'}"
    )
    outcome = result["result"]
    if outcome == "ok":
        lines.append(
            "Data confirmee : OUI -- le lien porte reellement du trafic "
            "(IP publique differente du site + compteurs en mouvement)."
        )
    elif outcome == "fail":
        lines.append(
            "Data confirmee : NON -- rien n'est passe sur le lien "
            "(attache mais pas de trafic ; forfait/APN a verifier)."
        )
    elif outcome == "leak":
        lines.append(
            "Data confirmee : NON -- impossible de conclure, la sonde est "
            "ressortie par la fibre (defaut de configuration du chemin de "
            "test, pas un probleme du secours)."
        )
    else:
        lines.append(
            "Data confirmee : INCONNU -- le pont ou la commande de sonde "
            "est injoignable, reessayez plus tard."
        )
    return "\n".join(lines)


def _make_handle_lte_check(target_registry: ManagedDeviceRegistry) -> Callable:
    def handler(args: str, chat_id: str, holder: object, send: Callable) -> None:
        device_id = args.strip()
        result = target_registry.check(device_id) if device_id else None
        if result is None:
            send(chat_id, f"Equipement TP-Link inconnu : '{device_id}'.")
            return
        send(chat_id, _format_check_result(result))

    return handler


def _make_handle_lte_reboot(target_registry: ManagedDeviceRegistry) -> Callable:
    def handler(args: str, chat_id: str, holder: object, send: Callable) -> None:
        device_id = args.strip()
        result = (
            target_registry.request_reboot(device_id, origin="telegram")
            if device_id
            else None
        )
        if result is None:
            send(chat_id, f"Equipement TP-Link inconnu : '{device_id}'.")
            return
        lines = [f"Reboot demande pour {result['label']}.", ""]
        if result["warning"]:
            lines.append(f"ATTENTION : {result['warning_reason']}")
            lines.append("")
        lines.append(f"Pour confirmer : /lte confirm {result['token']}")
        lines.append("Jeton a usage unique, expire rapidement.")
        send(chat_id, "\n".join(lines))

    return handler


def _make_handle_lte_confirm(target_registry: ManagedDeviceRegistry) -> Callable:
    def handler(args: str, chat_id: str, holder: object, send: Callable) -> None:
        token = args.strip()
        if not token:
            send(chat_id, "Jeton manquant. Usage : /lte confirm <jeton>")
            return
        result = target_registry.confirm_reboot(token, origin="telegram")
        if not result.get("executed"):
            send(
                chat_id,
                f"Confirmation refusee : {result.get('error', 'jeton invalide')}",
            )
            return
        if result.get("ok"):
            send(chat_id, f"Reboot de {result['label']} lance avec succes.")
        else:
            label = result.get("label", "l'equipement")
            send(
                chat_id,
                f"Echec du reboot de {label}. Verifiez manuellement sur place.",
            )

    return handler


# Handlers par defaut (production), lies au registre par defaut. Redefinis
# dynamiquement par `_register_telegram_handlers` a chaque `bootstrap()` --
# conserves ici pour compatibilite/introspection directe si besoin.
_handle_lte_all = _make_handle_lte_all(registry)
_handle_lte_status = _make_handle_lte_status(registry)
_handle_lte_check = _make_handle_lte_check(registry)
_handle_lte_reboot = _make_handle_lte_reboot(registry)
_handle_lte_confirm = _make_handle_lte_confirm(registry)
