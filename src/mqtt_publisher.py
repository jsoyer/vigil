"""MQTT publisher -- publish watchdog state to MQTT broker for Home Assistant.

Sprint 3 A2 ajoute trois choses au-dessus du squelette existant (connexion,
discovery, thread de publication, identite disjointe par instance -- bugfix
1.8.1) :

- des devices Home Assistant **par equipement TP-Link** (site + equipement,
  jamais par instance -- C12), publies uniquement par l'instance elue ;
- un device **USG <site>** unique pour les capteurs de ligne (gateway,
  internet, RTT), publie par l'instance elue, et des ajouts sur le device
  **watchdog** par instance (divergence, etat du peer, metriques hote C17) ;
- le premier chemin de commande **entrant** du projet (C9) : switch "armer"
  a desarmement automatique, button "reboot" refuse sans armement, sensor
  "derniere action" avec motif (C10). Toute execution passe par
  `managed_devices.registry` -- jamais un appel driver direct (C6).
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone

try:
    import paho.mqtt.client as paho_mqtt

    PAHO_AVAILABLE = True
except ImportError:
    paho_mqtt = None  # type: ignore[assignment]
    PAHO_AVAILABLE = False

import events
import managed_devices
import peer as peer_mod
from config import (
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_TOPIC_PREFIX,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_HA_DISCOVERY,
    MQTT_COMMANDS_ENABLED,
    MQTT_ARM_TIMEOUT,
    CHECK_INTERVAL,
    INSTANCE_ID,
    INSTANCE_PRIORITY,
    SITE_ID,
    PEER_IP,
    TPLINK_DEVICES,
)
from state import StateHolder

# Prefixe de discovery Home Assistant (constante -- pas de variable d'env pour
# le moment, cf. note de scope du patch mqtt-instance-identity)
HA_DISCOVERY_PREFIX: str = "homeassistant"

# ---------------------------------------------------------------------------
# C13 -- liste figee des entites par equipement TP-Link. Decidee une fois,
# jamais reconstruite depuis les donnees d'un cycle : un champ illisible
# devient "unavailable", il ne disparait jamais de cette liste.
# ---------------------------------------------------------------------------
_TPLINK_ENTITY_SPECS: tuple[dict, ...] = (
    {
        "key": "readiness",
        "platform": "sensor",
        "name": "Disponibilite",
        "device_class": "enum",
        "icon": "mdi:shield-check",
    },
    {
        "key": "secours_degrade",
        "platform": "binary_sensor",
        "name": "Secours degrade",
        "device_class": "problem",
    },
    {
        "key": "attache",
        "platform": "binary_sensor",
        "name": "Lien attache",
        "device_class": "connectivity",
    },
    {
        "key": "sonde_resultat",
        "platform": "sensor",
        "name": "Resultat de sonde",
        "device_class": "enum",
        "icon": "mdi:radar",
    },
    {
        "key": "sonde_derniere",
        "platform": "sensor",
        "name": "Derniere sonde",
        "device_class": "timestamp",
    },
    {
        "key": "rsrp",
        "platform": "sensor",
        "name": "RSRP",
        "device_class": "signal_strength",
        "state_class": "measurement",
        "unit": "dBm",
    },
    {
        "key": "rsrq",
        "platform": "sensor",
        "name": "RSRQ",
        "device_class": "signal_strength",
        "state_class": "measurement",
        "unit": "dB",
    },
    {
        "key": "snr",
        "platform": "sensor",
        "name": "SNR",
        "state_class": "measurement",
        "unit": "dB",
    },
    {
        "key": "signal_level",
        "platform": "sensor",
        "name": "Niveau de signal",
        "state_class": "measurement",
        "icon": "mdi:signal-cellular-3",
    },
    {
        "key": "network_type",
        "platform": "sensor",
        "name": "Type de reseau",
        "entity_category": "diagnostic",
    },
    {
        "key": "sim_status",
        "platform": "sensor",
        "name": "Etat SIM",
        "entity_category": "diagnostic",
    },
    {
        "key": "operateur",
        "platform": "sensor",
        "name": "Operateur",
        "entity_category": "diagnostic",
    },
    {
        "key": "conso_cycle",
        "platform": "sensor",
        "name": "Conso du cycle",
        "device_class": "data_size",
        "state_class": "total_increasing",
        "unit": "MB",
    },
    {
        "key": "quota_pct",
        "platform": "sensor",
        "name": "Pourcentage du forfait",
        "state_class": "measurement",
        "unit": "%",
    },
    {
        "key": "prochain_reset",
        "platform": "sensor",
        "name": "Prochain reset",
        "device_class": "timestamp",
    },
    {
        "key": "debit_rx",
        "platform": "sensor",
        "name": "Debit descendant",
        "device_class": "data_rate",
        "state_class": "measurement",
        "unit": "kbit/s",
    },
    {
        "key": "debit_tx",
        "platform": "sensor",
        "name": "Debit montant",
        "device_class": "data_rate",
        "state_class": "measurement",
        "unit": "kbit/s",
    },
    {
        "key": "etat_usage",
        "platform": "sensor",
        "name": "Etat d'usage",
        "device_class": "enum",
    },
    {
        "key": "saut_panne",
        "platform": "sensor",
        "name": "Saut en panne",
        "entity_category": "diagnostic",
    },
    {
        "key": "rtt_routeur",
        "platform": "sensor",
        "name": "RTT routeur",
        "state_class": "measurement",
        "unit": "ms",
        "entity_category": "diagnostic",
    },
    {
        "key": "age_donnee_peer",
        "platform": "sensor",
        "name": "Age donnee peer",
        "state_class": "measurement",
        "unit": "s",
        "entity_category": "diagnostic",
    },
)

# Entites du chemin de commande (C9/C10) -- toujours declarees (liste figee),
# meme si l'ecoute est desactivee : seule leur effet cote watchdog depend du
# flag, pas leur presence dans Home Assistant.
_TPLINK_COMMAND_SPECS: tuple[dict, ...] = (
    {"key": "arm", "platform": "switch", "name": "Armer le reboot"},
    {"key": "reboot", "platform": "button", "name": "Reboot"},
    {"key": "last_action", "platform": "sensor", "name": "Derniere action"},
)

# C15 -- capteurs de ligne USG, un seul device par site.
_USG_ENTITY_SPECS: tuple[dict, ...] = (
    {"key": "gateway", "platform": "sensor", "name": "Gateway", "device_class": "enum"},
    {
        "key": "internet",
        "platform": "sensor",
        "name": "Internet",
        "device_class": "enum",
    },
    {
        "key": "gateway_rtt",
        "platform": "sensor",
        "name": "Gateway Latency",
        "state_class": "measurement",
        "unit": "ms",
    },
    {
        "key": "internet_rtt",
        "platform": "sensor",
        "name": "Internet Latency",
        "state_class": "measurement",
        "unit": "ms",
    },
)

# C15/C17 -- ajouts sur le device watchdog par instance (divergence, etat du
# peer, metriques hote). Additifs uniquement -- les 8 capteurs historiques
# (C14) sont enrichis a part, dans `_ha_discovery_configs`.
_WATCHDOG_EXTRA_SPECS: tuple[dict, ...] = (
    {
        "key": "divergence",
        "platform": "binary_sensor",
        "name": "Divergence peer",
        "device_class": "problem",
    },
    {
        "key": "peer_state",
        "platform": "sensor",
        "name": "Etat du peer",
        "device_class": "enum",
    },
    {
        "key": "cpu_temp",
        "platform": "sensor",
        "name": "Temperature CPU",
        "device_class": "temperature",
        "state_class": "measurement",
        "unit": "°C",
        "entity_category": "diagnostic",
    },
    {
        "key": "disk_free",
        "platform": "sensor",
        "name": "Espace disque libre",
        "device_class": "data_size",
        "state_class": "measurement",
        "unit": "GB",
        "entity_category": "diagnostic",
    },
    {
        "key": "disk_used_pct",
        "platform": "sensor",
        "name": "Disque utilise",
        "state_class": "measurement",
        "unit": "%",
        "entity_category": "diagnostic",
    },
    {
        "key": "mem_available",
        "platform": "sensor",
        "name": "Memoire disponible",
        "device_class": "data_size",
        "state_class": "measurement",
        "unit": "MB",
        "entity_category": "diagnostic",
    },
    {
        "key": "load1",
        "platform": "sensor",
        "name": "Charge (1 min)",
        "state_class": "measurement",
        "entity_category": "diagnostic",
    },
)


def is_configured() -> bool:
    """Check if MQTT publishing is configured."""
    return bool(MQTT_BROKER)


# ---------------------------------------------------------------------------
# Identites de device (C12/C15) -- indexees site + equipement, jamais
# instance, pour que master et slave d'un meme site calculent la meme
# identite (seul l'elu publie effectivement dessus).
# ---------------------------------------------------------------------------


def _tplink_device_identity(site_id: str, device_id: str) -> str:
    return f"vigil_{site_id}_tplink_{device_id}"


def _usg_device_identity(site_id: str) -> str:
    return f"vigil_{site_id}_usg"


def _tplink_topic_base(prefix: str, site_id: str, device_id: str) -> str:
    return f"{prefix}/site/{site_id}/tplink/{device_id}"


def _usg_topic_base(prefix: str, site_id: str) -> str:
    return f"{prefix}/site/{site_id}/usg"


def _ha_discovery_configs(prefix: str, instance_id: str | None = None) -> list[dict]:
    """Generate Home Assistant MQTT auto-discovery payloads for the 8
    capteurs watchdog historiques. C14 : unique_id et plateforme (sensor)
    inchanges depuis 1.8.1 -- seuls device_class/state_class/unite
    s'ajoutent."""
    if instance_id is None:
        instance_id = INSTANCE_ID

    device = {
        "identifiers": [f"vigil_{instance_id}"],
        "name": f"Vigil {instance_id}",
        "model": "Vigil",
        "manufacturer": "jsoyer",
    }

    sensors = [
        (
            "score",
            "Failure Score",
            "mdi:gauge",
            None,
            f"{prefix}/score",
            {"state_class": "measurement"},
        ),
        (
            "gateway",
            "Gateway",
            "mdi:router-wireless",
            None,
            f"{prefix}/gateway",
            {"device_class": "enum"},
        ),
        (
            "internet",
            "Internet",
            "mdi:web",
            None,
            f"{prefix}/internet",
            {"device_class": "enum"},
        ),
        (
            "reboots_today",
            "Reboots Today",
            "mdi:restart",
            None,
            f"{prefix}/reboots_today",
            {"state_class": "total_increasing"},
        ),
        (
            "status",
            "Status",
            "mdi:shield-check",
            None,
            f"{prefix}/status",
            {"device_class": "enum"},
        ),
        (
            "gateway_rtt",
            "Gateway Latency",
            "mdi:timer-outline",
            "ms",
            f"{prefix}/gateway_rtt",
            {"state_class": "measurement"},
        ),
        (
            "internet_rtt",
            "Internet Latency",
            "mdi:timer-outline",
            "ms",
            f"{prefix}/internet_rtt",
            {"state_class": "measurement"},
        ),
        (
            "uptime",
            "Uptime",
            "mdi:clock-outline",
            "s",
            f"{prefix}/uptime",
            {"device_class": "duration", "state_class": "measurement"},
        ),
    ]

    configs = []
    for sensor_id, name, icon, unit, state_topic, extra in sensors:
        payload: dict = {
            "name": name,
            "unique_id": f"vigil_{instance_id}_{sensor_id}",
            "state_topic": state_topic,
            "icon": icon,
            "device": device,
        }
        if unit:
            payload["unit_of_measurement"] = unit
        payload.update(extra)
        configs.append(
            {
                "topic": f"{HA_DISCOVERY_PREFIX}/sensor/vigil_{instance_id}/{sensor_id}/config",
                "payload": payload,
            }
        )

    return configs


def _watchdog_extra_discovery_configs(
    prefix: str, instance_id: str | None = None
) -> list[dict]:
    """C15/C17 -- divergence, etat du peer, metriques hote. Reste sur le
    device watchdog existant (identifiers inchanges, C14) -- purement
    additif."""
    if instance_id is None:
        instance_id = INSTANCE_ID

    device = {
        "identifiers": [f"vigil_{instance_id}"],
        "name": f"Vigil {instance_id}",
        "model": "Vigil",
        "manufacturer": "jsoyer",
    }

    configs = []
    for spec in _WATCHDOG_EXTRA_SPECS:
        topic = f"{prefix}/{instance_id}/{spec['key']}"
        payload: dict = {
            "name": spec["name"],
            "unique_id": f"vigil_{instance_id}_{spec['key']}",
            "state_topic": topic,
            "device": device,
        }
        if spec["platform"] == "sensor" and spec.get("device_class") is not None:
            payload["device_class"] = spec["device_class"]
        if spec["platform"] == "binary_sensor" and spec.get("device_class") is not None:
            payload["device_class"] = spec["device_class"]
        if "state_class" in spec:
            payload["state_class"] = spec["state_class"]
        if "unit" in spec:
            payload["unit_of_measurement"] = spec["unit"]
        if "entity_category" in spec:
            payload["entity_category"] = spec["entity_category"]
        configs.append(
            {
                "topic": (
                    f"{HA_DISCOVERY_PREFIX}/{spec['platform']}/vigil_{instance_id}/"
                    f"{spec['key']}/config"
                ),
                "payload": payload,
            }
        )
    return configs


def _tplink_discovery_configs(
    prefix: str, site_id: str, device_id: str, label: str
) -> list[dict]:
    """C12/C13 -- entites d'un equipement TP-Link, indexees site +
    equipement. Liste figee : `_TPLINK_ENTITY_SPECS` + `_TPLINK_COMMAND_SPECS`
    ne varient jamais d'un cycle a l'autre."""
    identity = _tplink_device_identity(site_id, device_id)
    device = {
        "identifiers": [identity],
        "name": f"Secours 4G {label} ({site_id})",
        "model": "TP-Link MR110",
        "manufacturer": "TP-Link",
    }
    base = _tplink_topic_base(prefix, site_id, device_id)

    configs = []
    for spec in _TPLINK_ENTITY_SPECS:
        payload: dict = {
            "name": spec["name"],
            "unique_id": f"{identity}_{spec['key']}",
            "state_topic": f"{base}/{spec['key']}",
            "device": device,
        }
        if "device_class" in spec:
            payload["device_class"] = spec["device_class"]
        if "state_class" in spec:
            payload["state_class"] = spec["state_class"]
        if "unit" in spec:
            payload["unit_of_measurement"] = spec["unit"]
        if "entity_category" in spec:
            payload["entity_category"] = spec["entity_category"]
        if "icon" in spec:
            payload["icon"] = spec["icon"]
        configs.append(
            {
                "topic": (
                    f"{HA_DISCOVERY_PREFIX}/{spec['platform']}/{identity}/"
                    f"{spec['key']}/config"
                ),
                "payload": payload,
            }
        )

    # Chemin de commande (C9/C10) -- toujours declare, meme ecoute coupee.
    for spec in _TPLINK_COMMAND_SPECS:
        payload = {
            "name": spec["name"],
            "unique_id": f"{identity}_{spec['key']}",
            "device": device,
        }
        if spec["platform"] == "switch":
            payload["state_topic"] = f"{base}/arm_state"
            payload["command_topic"] = f"{base}/cmd/arm"
            payload["payload_on"] = "ON"
            payload["payload_off"] = "OFF"
        elif spec["platform"] == "button":
            payload["command_topic"] = f"{base}/cmd/reboot"
            payload["payload_press"] = "PRESS"
        elif spec["key"] == "last_action":
            payload["state_topic"] = f"{base}/last_action"
            payload["value_template"] = "{{ value_json.result }}"
            payload["json_attributes_topic"] = f"{base}/last_action"
        configs.append(
            {
                "topic": (
                    f"{HA_DISCOVERY_PREFIX}/{spec['platform']}/{identity}/"
                    f"{spec['key']}/config"
                ),
                "payload": payload,
            }
        )

    return configs


def _usg_discovery_configs(prefix: str, site_id: str) -> list[dict]:
    """C15 -- device USG unique par site, capteurs de ligne."""
    identity = _usg_device_identity(site_id)
    device = {
        "identifiers": [identity],
        "name": f"USG {site_id}",
        "model": "UniFi Security Gateway",
        "manufacturer": "Ubiquiti",
    }
    base = _usg_topic_base(prefix, site_id)

    configs = []
    for spec in _USG_ENTITY_SPECS:
        payload: dict = {
            "name": spec["name"],
            "unique_id": f"{identity}_{spec['key']}",
            "state_topic": f"{base}/{spec['key']}",
            "device": device,
        }
        if "device_class" in spec:
            payload["device_class"] = spec["device_class"]
        if "state_class" in spec:
            payload["state_class"] = spec["state_class"]
        if "unit" in spec:
            payload["unit_of_measurement"] = spec["unit"]
        configs.append(
            {
                "topic": (
                    f"{HA_DISCOVERY_PREFIX}/{spec['platform']}/{identity}/"
                    f"{spec['key']}/config"
                ),
                "payload": payload,
            }
        )
    return configs


# ---------------------------------------------------------------------------
# Extraction de valeurs -- C13 : champ illisible -> None -> "unavailable",
# jamais depublie, jamais a zero.
# ---------------------------------------------------------------------------


def _epoch_to_iso(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OSError, OverflowError, ValueError):
        return None


def _tplink_entity_value(key: str, status: dict, quota: dict | None) -> object:
    if key == "readiness":
        return status.get("readiness")
    if key == "secours_degrade":
        readiness = status.get("readiness")
        return None if readiness is None else ("ON" if readiness != "ok" else "OFF")
    if key == "attache":
        reachable = status.get("reachable")
        return None if reachable is None else ("ON" if reachable else "OFF")
    if key == "sonde_resultat":
        return status.get("probe_result")
    if key == "sonde_derniere":
        return _epoch_to_iso(status.get("probe_result_at"))
    if key == "rsrp":
        return status.get("rsrp")
    if key == "rsrq":
        return status.get("rsrq")
    if key == "snr":
        return status.get("snr")
    if key == "signal_level":
        return status.get("signal_bars")
    if key == "network_type":
        return status.get("network_type")
    if key == "sim_status":
        return status.get("sim_status")
    if key == "operateur":
        return status.get("isp_name")
    if key == "conso_cycle":
        return (
            None if quota is None else round(quota["cycle_bytes_used"] / 1_000_000, 3)
        )
    if key == "quota_pct":
        return None if quota is None else quota["pct"]
    if key == "prochain_reset":
        return None if quota is None else quota.get("next_reset")
    if key == "debit_rx":
        v = status.get("rx_speed_bps")
        return None if v is None else round(v / 1000, 1)
    if key == "debit_tx":
        v = status.get("tx_speed_bps")
        return None if v is None else round(v / 1000, 1)
    if key == "etat_usage":
        return status.get("usage_state") or "unknown"
    if key == "saut_panne":
        if "failed_hop" not in status:
            return None
        hop = status["failed_hop"]
        return "aucun" if hop is None else hop
    if key == "rtt_routeur":
        return status.get("rtt_ms")
    if key == "age_donnee_peer":
        return status.get("age_seconds")
    return None


# ---------------------------------------------------------------------------
# Election (C12/C15) -- reutilise `peer.elect_poller`, jamais une deuxieme
# logique de failover. Pour le device USG (pas de notion "bridged"), les
# deux cotes sont passes avec `my_mode`/`peer_mode` = "usg", ce qui fait
# retomber `elect_poller` sur son repli priorite pure -- meme code que le
# TP-Link, juste une entree differente.
# ---------------------------------------------------------------------------


def _is_usg_elected(state: object) -> tuple[bool, str]:
    if not PEER_IP:
        return True, "standalone"
    peer_state = peer_mod.query_peer(retries=1, timeout=3)
    return peer_mod.elect_poller(
        my_priority=INSTANCE_PRIORITY,
        my_mode="usg",
        my_reachable=True,
        peer_reachable=peer_state is not None,
        peer_priority=peer_state.instance_priority if peer_state is not None else None,
        peer_mode="usg",
        threshold_reached_time=getattr(state, "threshold_reached_time", 0.0),
    )


def _watchdog_divergence_state(state: object) -> str:
    result = peer_mod.check_divergence(
        getattr(state, "failure_score", 0),
        getattr(state, "gateway_ok", True),
        getattr(state, "internet_ok_count", 0),
    )
    return "ON" if result is not None else "OFF"


def _watchdog_peer_state_value() -> str:
    return peer_mod.get_peer_info().get("status", "standalone")


# ---------------------------------------------------------------------------
# C17 -- metriques hote, stdlib uniquement. Champ indisponible -> None ->
# "unavailable" (jamais zero, C13).
# ---------------------------------------------------------------------------


def _read_cpu_temp_c(
    path: str = "/sys/class/thermal/thermal_zone0/temp",
) -> float | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        return round(int(raw) / 1000.0, 1)
    except (OSError, ValueError):
        return None


def _read_disk_usage(path: str = "/") -> tuple[float | None, float | None]:
    """Retourne (Go libres, % utilise)."""
    import os

    try:
        st = os.statvfs(path)
        if st.f_blocks == 0:
            return None, None
        free_bytes = st.f_bavail * st.f_frsize
        free_gb = round(free_bytes / 1_000_000_000, 2)
        pct_used = round((1 - st.f_bavail / st.f_blocks) * 100, 1)
        return free_gb, pct_used
    except OSError:
        return None, None


def _read_mem_available_mb(path: str = "/proc/meminfo") -> float | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return round(int(parts[1]) / 1000.0, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def _read_load1() -> float | None:
    import os

    try:
        return round(os.getloadavg()[0], 2)
    except OSError:
        return None


class MqttPublisher:
    """Publishes watchdog state to MQTT at regular intervals, and (Sprint 3
    A2, optionnel -- C9) ecoute un chemin de commande garde."""

    def __init__(self, holder: StateHolder) -> None:
        self._holder = holder
        self._client = None
        self._connected = False
        self._discovery_sent = False
        # device_id -> horodatage d'expiration (time.monotonic()). Presence
        # = arme. Purge paresseuse dans `_is_armed`.
        self._armed: dict[str, float] = {}

    def start(self) -> bool:
        """Connect to MQTT broker and start publishing in a background thread.

        Returns True if MQTT is configured, False otherwise. Never raises.
        """
        if not MQTT_BROKER:
            return False

        if not PAHO_AVAILABLE:
            logging.warning(
                "Module 'paho-mqtt' non installe -- MQTT desactive (pip install paho-mqtt)"
            )
            return False

        try:
            self._client = paho_mqtt.Client(
                client_id=f"vigil-{INSTANCE_ID}", protocol=paho_mqtt.MQTTv311
            )
            if MQTT_USERNAME:
                self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            if self._commands_active():
                self._client.on_message = self._on_message
            self._client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self._client.loop_start()

            thread = threading.Thread(
                target=self._publish_loop,
                name="mqtt-publisher",
                daemon=True,
            )
            thread.start()
            logging.info("MQTT publisher demarre -> %s:%d", MQTT_BROKER, MQTT_PORT)
            return True

        except Exception as e:
            logging.warning("MQTT: erreur connexion -- %s", e)
            return False

    # ------------------------------------------------------------------
    # C9 -- l'ecoute exige le flag ET un broker authentifie
    # ------------------------------------------------------------------

    def _commands_active(self) -> bool:
        if not MQTT_COMMANDS_ENABLED:
            return False
        if not MQTT_USERNAME:
            logging.warning(
                "MQTT: MQTT_COMMANDS_ENABLED=true mais MQTT_USERNAME absent -- "
                "ecoute des commandes refusee (C9 : le broker doit etre authentifie)"
            )
            return False
        return True

    def _on_connect(
        self, client: object, userdata: object, flags: object, rc: int
    ) -> None:
        self._connected = True
        logging.info("MQTT connecte (rc=%d)", rc)
        if MQTT_HA_DISCOVERY and not self._discovery_sent:
            self._send_discovery()
        if self._commands_active():
            self._subscribe_commands()

    def _on_disconnect(self, client: object, userdata: object, rc: int) -> None:
        self._connected = False
        if rc != 0:
            logging.warning("MQTT deconnecte (rc=%d) -- reconnexion auto", rc)

    def _subscribe_commands(self) -> None:
        if self._client is None:
            return
        for device_id in managed_devices.registry.device_ids():
            base = _tplink_topic_base(MQTT_TOPIC_PREFIX, SITE_ID, device_id)
            self._client.subscribe(f"{base}/cmd/arm")
            self._client.subscribe(f"{base}/cmd/reboot")
        logging.info("MQTT: abonnement au chemin de commande actif")

    def _send_discovery(self) -> None:
        """Send Home Assistant auto-discovery configs -- 8 capteurs
        historiques (C14), ajouts watchdog (C15/C17), un device par
        equipement TP-Link declare (C12/C13) et le device USG du site
        (C15). La discovery est envoyee par toutes les instances pour les
        8 capteurs et les ajouts watchdog (chacune son device par
        instance) ; pour les devices site (TP-Link, USG), la declaration
        de structure est inoffensive meme depuis une instance non elue --
        seule la PUBLICATION D'ETAT est reservee a l'elu (C12/C15)."""
        if self._client is None:
            return
        for config in _ha_discovery_configs(MQTT_TOPIC_PREFIX):
            self._client.publish(
                config["topic"],
                json.dumps(config["payload"]),
                retain=True,
            )
        for config in _watchdog_extra_discovery_configs(MQTT_TOPIC_PREFIX):
            self._client.publish(
                config["topic"],
                json.dumps(config["payload"]),
                retain=True,
            )
        for cfg in TPLINK_DEVICES:
            device_id = str(cfg.index)
            for config in _tplink_discovery_configs(
                MQTT_TOPIC_PREFIX, SITE_ID, device_id, cfg.label
            ):
                self._client.publish(
                    config["topic"],
                    json.dumps(config["payload"]),
                    retain=True,
                )
        if TPLINK_DEVICES:
            for config in _usg_discovery_configs(MQTT_TOPIC_PREFIX, SITE_ID):
                self._client.publish(
                    config["topic"],
                    json.dumps(config["payload"]),
                    retain=True,
                )
        self._discovery_sent = True
        logging.info("MQTT: Home Assistant discovery envoye")

    def _publish_loop(self) -> None:
        """Publish state every CHECK_INTERVAL."""
        while True:
            if self._connected and self._client is not None:
                self._publish_state()
                self._publish_tplink_devices()
                self._publish_usg_device()
                self._publish_watchdog_extras()
                self._refresh_arm_states()
            time.sleep(CHECK_INTERVAL)

    def _publish_state(self) -> None:
        """Publish current state values to MQTT topics (8 capteurs
        historiques, C14 : etats desormais retained)."""
        state = self._holder.state
        if state is None or self._client is None:
            return

        prefix = MQTT_TOPIC_PREFIX
        try:
            self._client.publish(f"{prefix}/score", state.failure_score, retain=True)
            self._client.publish(
                f"{prefix}/gateway",
                "OK" if state.gateway_ok else "KO",
                retain=True,
            )
            self._client.publish(
                f"{prefix}/internet",
                f"{state.internet_ok_count}/{state.internet_total}",
                retain=True,
            )
            self._client.publish(
                f"{prefix}/reboots_today", state.reboots_today, retain=True
            )
            self._client.publish(
                f"{prefix}/uptime", int(state.uptime_seconds), retain=True
            )

            if state.gateway_rtt_ms is not None:
                self._client.publish(
                    f"{prefix}/gateway_rtt",
                    round(state.gateway_rtt_ms, 1),
                    retain=True,
                )
            if state.internet_avg_rtt_ms is not None:
                self._client.publish(
                    f"{prefix}/internet_rtt",
                    round(state.internet_avg_rtt_ms, 1),
                    retain=True,
                )

            # Status
            if state.surveillance_only:
                status = "surveillance"
            elif state.failure_score >= state.threshold:
                status = "critical"
            elif state.failure_score > 0:
                status = "degraded"
            else:
                status = "healthy"
            self._client.publish(f"{prefix}/status", status, retain=True)

            # Full JSON state on a single topic
            self._client.publish(f"{prefix}/state", state.to_json())

        except Exception as e:
            logging.debug("MQTT publish error: %s", e)

    def _publish_tplink_devices(self) -> None:
        """C12 : seule l'instance elue publie les entites d'un equipement
        donne (verifie via `status["from_peer"]`, deja calcule par
        `managed_devices.registry.get_status`, qui reutilise
        `peer.elect_poller` -- aucune deuxieme logique d'election ici)."""
        if self._client is None:
            return
        try:
            for device_id in managed_devices.registry.device_ids():
                status = managed_devices.registry.get_status(device_id)
                if status is None or status.get("from_peer"):
                    continue
                quota = managed_devices.registry.quota_status(device_id)
                base = _tplink_topic_base(MQTT_TOPIC_PREFIX, SITE_ID, device_id)
                for spec in _TPLINK_ENTITY_SPECS:
                    value = _tplink_entity_value(spec["key"], status, quota)
                    payload = "unavailable" if value is None else value
                    self._client.publish(f"{base}/{spec['key']}", payload, retain=True)
        except Exception as e:
            logging.debug("MQTT publish tplink error: %s", e)

    def _refresh_arm_states(self) -> None:
        """Republie l'etat d'armement de chaque equipement deja arme au
        moins une fois par cette instance -- independant de l'election
        (C12 ne gouverne que les capteurs de donnees, pas le suivi local
        d'un armement recu par CETTE instance). Necessaire pour que le
        desarmement automatique (delai ecoule) se reflete sur le broker
        meme sans nouveau message entrant."""
        if self._client is None:
            return
        for device_id in list(self._armed.keys()):
            self._publish_arm_state(device_id)

    def _publish_usg_device(self) -> None:
        """C15 : device USG unique par site, alimente par l'instance elue."""
        if self._client is None or not TPLINK_DEVICES:
            return
        state = self._holder.state
        if state is None:
            return
        try:
            elected, _reason = _is_usg_elected(state)
            if not elected:
                return
            base = _usg_topic_base(MQTT_TOPIC_PREFIX, SITE_ID)
            self._client.publish(
                f"{base}/gateway", "OK" if state.gateway_ok else "KO", retain=True
            )
            self._client.publish(
                f"{base}/internet",
                f"{state.internet_ok_count}/{state.internet_total}",
                retain=True,
            )
            if state.gateway_rtt_ms is not None:
                self._client.publish(
                    f"{base}/gateway_rtt", round(state.gateway_rtt_ms, 1), retain=True
                )
            if state.internet_avg_rtt_ms is not None:
                self._client.publish(
                    f"{base}/internet_rtt",
                    round(state.internet_avg_rtt_ms, 1),
                    retain=True,
                )
        except Exception as e:
            logging.debug("MQTT publish usg error: %s", e)

    def _publish_watchdog_extras(self) -> None:
        """C15/C17 -- divergence, etat du peer, metriques hote. Publie par
        chaque instance sur son propre device (pas d'election -- ce sont
        des valeurs par instance, C15)."""
        if self._client is None:
            return
        state = self._holder.state
        if state is None:
            return
        try:
            topic_base = f"{MQTT_TOPIC_PREFIX}/{INSTANCE_ID}"
            self._client.publish(
                f"{topic_base}/divergence",
                _watchdog_divergence_state(state),
                retain=True,
            )
            self._client.publish(
                f"{topic_base}/peer_state", _watchdog_peer_state_value(), retain=True
            )

            temp = _read_cpu_temp_c()
            self._client.publish(
                f"{topic_base}/cpu_temp",
                "unavailable" if temp is None else temp,
                retain=True,
            )
            free_gb, pct_used = _read_disk_usage()
            self._client.publish(
                f"{topic_base}/disk_free",
                "unavailable" if free_gb is None else free_gb,
                retain=True,
            )
            self._client.publish(
                f"{topic_base}/disk_used_pct",
                "unavailable" if pct_used is None else pct_used,
                retain=True,
            )
            mem = _read_mem_available_mb()
            self._client.publish(
                f"{topic_base}/mem_available",
                "unavailable" if mem is None else mem,
                retain=True,
            )
            load1 = _read_load1()
            self._client.publish(
                f"{topic_base}/load1",
                "unavailable" if load1 is None else load1,
                retain=True,
            )
        except Exception as e:
            logging.debug("MQTT publish watchdog extras error: %s", e)

    # ------------------------------------------------------------------
    # Chemin de commande entrant (C9/C10) -- premier `subscribe` du projet.
    # Parsing strict : tout message non conforme est ignore et logge,
    # jamais interprete au mieux. Toute execution passe par
    # `managed_devices.registry` (C6 -- meme garde que l'API/dashboard).
    # ------------------------------------------------------------------

    def _decode_payload(self, payload: object) -> str | None:
        try:
            text = payload.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            return None
        if not text or len(text) > 64:
            return None
        return text

    def _on_message(self, client: object, userdata: object, msg: object) -> None:
        try:
            topic = str(getattr(msg, "topic", ""))
            parts = topic.split("/")
            # {prefix}/site/{site_id}/tplink/{device_id}/cmd/{action}
            if (
                len(parts) != 7
                or parts[1] != "site"
                or parts[3] != "tplink"
                or parts[5] != "cmd"
            ):
                logging.warning("MQTT commande: topic non reconnu -- %s", topic)
                return
            device_id = parts[4]
            action = parts[6]
            payload = getattr(msg, "payload", b"")
            if action == "arm":
                self._handle_arm(device_id, payload)
            elif action == "reboot":
                self._handle_reboot(device_id, payload)
            else:
                logging.warning("MQTT commande: action inconnue -- %s", topic)
        except Exception as e:
            logging.warning("MQTT commande: erreur de traitement -- %s", e)

    def _handle_arm(self, device_id: str, payload: object) -> None:
        text = self._decode_payload(payload)
        if text not in ("ON", "OFF"):
            logging.warning("MQTT arm: payload invalide pour '%s' -- ignore", device_id)
            return
        if text == "ON":
            self._armed[device_id] = time.monotonic() + MQTT_ARM_TIMEOUT
        else:
            self._armed.pop(device_id, None)
        self._publish_arm_state(device_id)

    def _is_armed(self, device_id: str) -> bool:
        expiry = self._armed.get(device_id)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            self._armed.pop(device_id, None)
            return False
        return True

    def _publish_arm_state(self, device_id: str) -> None:
        if self._client is None:
            return
        base = _tplink_topic_base(MQTT_TOPIC_PREFIX, SITE_ID, device_id)
        state = "ON" if self._is_armed(device_id) else "OFF"
        self._client.publish(f"{base}/arm_state", state, retain=True)

    def _handle_reboot(self, device_id: str, payload: object) -> None:
        text = self._decode_payload(payload)
        if text != "PRESS":
            logging.warning(
                "MQTT reboot: payload invalide pour '%s' -- ignore", device_id
            )
            return

        if device_id not in managed_devices.registry.device_ids():
            logging.warning("MQTT reboot: equipement inconnu -- %s", device_id)
            self._refuse_reboot(device_id, "equipement inconnu")
            return

        if not self._is_armed(device_id):
            self._refuse_reboot(device_id, "non arme ou armement expire")
            return

        # Usage unique : desarme immediatement, avant l'action -- un
        # double press ne declenche jamais deux reboots.
        self._armed.pop(device_id, None)
        self._publish_arm_state(device_id)

        result = managed_devices.registry.request_reboot(device_id, origin="mqtt")
        if result is None:
            self._refuse_reboot(device_id, "equipement inconnu")
            return

        outcome = managed_devices.registry.confirm_reboot(
            result["token"], origin="mqtt", expected_device_id=device_id
        )
        self._publish_reboot_outcome(device_id, result, outcome)

    def _refuse_reboot(self, device_id: str, reason: str) -> None:
        managed_devices.registry.record_event(
            events.MQTT_COMMAND_REFUSED,
            device_id=device_id,
            reason=reason,
            origin="mqtt",
        )
        self._publish_last_action(device_id, result="refused", reason=reason)

    def _publish_reboot_outcome(
        self, device_id: str, request: dict, outcome: dict
    ) -> None:
        if outcome.get("executed") and outcome.get("ok"):
            self._publish_last_action(
                device_id,
                result="executed",
                reason=request.get("warning_reason"),
            )
        else:
            self._publish_last_action(
                device_id,
                result="failed",
                reason=outcome.get("error", "echec du reboot"),
            )

    def _publish_last_action(
        self, device_id: str, result: str, reason: str | None
    ) -> None:
        if self._client is None:
            return
        base = _tplink_topic_base(MQTT_TOPIC_PREFIX, SITE_ID, device_id)
        payload = json.dumps(
            {
                "result": result,
                "reason": reason,
                "executed": result in ("executed", "failed"),
                "device_id": device_id,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        self._client.publish(f"{base}/last_action", payload, retain=True)
