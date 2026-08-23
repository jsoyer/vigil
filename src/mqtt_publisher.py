"""MQTT publisher -- publish watchdog state to MQTT broker for Home Assistant."""

import json
import logging
import threading
import time

try:
    import paho.mqtt.client as paho_mqtt

    PAHO_AVAILABLE = True
except ImportError:
    paho_mqtt = None  # type: ignore[assignment]
    PAHO_AVAILABLE = False

from config import (
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_TOPIC_PREFIX,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_HA_DISCOVERY,
    CHECK_INTERVAL,
    INSTANCE_ID,
)
from state import StateHolder

# Prefixe de discovery Home Assistant (constante -- pas de variable d'env pour
# le moment, cf. note de scope du patch mqtt-instance-identity)
HA_DISCOVERY_PREFIX: str = "homeassistant"


def is_configured() -> bool:
    """Check if MQTT publishing is configured."""
    return bool(MQTT_BROKER)


def _ha_discovery_configs(prefix: str, instance_id: str | None = None) -> list[dict]:
    """Generate Home Assistant MQTT auto-discovery payloads."""
    if instance_id is None:
        instance_id = INSTANCE_ID

    device = {
        "identifiers": [f"vigil_{instance_id}"],
        "name": f"Vigil {instance_id}",
        "model": "Vigil",
        "manufacturer": "jsoyer",
    }

    sensors = [
        ("score", "Failure Score", "mdi:gauge", None, f"{prefix}/score"),
        ("gateway", "Gateway", "mdi:router-wireless", None, f"{prefix}/gateway"),
        ("internet", "Internet", "mdi:web", None, f"{prefix}/internet"),
        (
            "reboots_today",
            "Reboots Today",
            "mdi:restart",
            None,
            f"{prefix}/reboots_today",
        ),
        ("status", "Status", "mdi:shield-check", None, f"{prefix}/status"),
        (
            "gateway_rtt",
            "Gateway Latency",
            "mdi:timer-outline",
            "ms",
            f"{prefix}/gateway_rtt",
        ),
        (
            "internet_rtt",
            "Internet Latency",
            "mdi:timer-outline",
            "ms",
            f"{prefix}/internet_rtt",
        ),
        ("uptime", "Uptime", "mdi:clock-outline", "s", f"{prefix}/uptime"),
    ]

    configs = []
    for sensor_id, name, icon, unit, state_topic in sensors:
        payload: dict = {
            "name": name,
            "unique_id": f"vigil_{instance_id}_{sensor_id}",
            "state_topic": state_topic,
            "icon": icon,
            "device": device,
        }
        if unit:
            payload["unit_of_measurement"] = unit
        configs.append(
            {
                "topic": f"{HA_DISCOVERY_PREFIX}/sensor/vigil_{instance_id}/{sensor_id}/config",
                "payload": payload,
            }
        )

    return configs


class MqttPublisher:
    """Publishes watchdog state to MQTT at regular intervals."""

    def __init__(self, holder: StateHolder) -> None:
        self._holder = holder
        self._client = None
        self._connected = False
        self._discovery_sent = False

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

    def _on_connect(
        self, client: object, userdata: object, flags: object, rc: int
    ) -> None:
        self._connected = True
        logging.info("MQTT connecte (rc=%d)", rc)
        if MQTT_HA_DISCOVERY and not self._discovery_sent:
            self._send_discovery()

    def _on_disconnect(self, client: object, userdata: object, rc: int) -> None:
        self._connected = False
        if rc != 0:
            logging.warning("MQTT deconnecte (rc=%d) -- reconnexion auto", rc)

    def _send_discovery(self) -> None:
        """Send Home Assistant auto-discovery configs."""
        if self._client is None:
            return
        for config in _ha_discovery_configs(MQTT_TOPIC_PREFIX):
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
            time.sleep(CHECK_INTERVAL)

    def _publish_state(self) -> None:
        """Publish current state values to MQTT topics."""
        state = self._holder.state
        if state is None or self._client is None:
            return

        prefix = MQTT_TOPIC_PREFIX
        try:
            # Individual topic per metric (for HA sensors)
            self._client.publish(f"{prefix}/score", state.failure_score)
            self._client.publish(
                f"{prefix}/gateway", "OK" if state.gateway_ok else "KO"
            )
            self._client.publish(
                f"{prefix}/internet",
                f"{state.internet_ok_count}/{state.internet_total}",
            )
            self._client.publish(f"{prefix}/reboots_today", state.reboots_today)
            self._client.publish(f"{prefix}/uptime", int(state.uptime_seconds))

            if state.gateway_rtt_ms is not None:
                self._client.publish(
                    f"{prefix}/gateway_rtt", round(state.gateway_rtt_ms, 1)
                )
            if state.internet_avg_rtt_ms is not None:
                self._client.publish(
                    f"{prefix}/internet_rtt", round(state.internet_avg_rtt_ms, 1)
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
            self._client.publish(f"{prefix}/status", status)

            # Full JSON state on a single topic
            self._client.publish(f"{prefix}/state", state.to_json())

        except Exception as e:
            logging.debug("MQTT publish error: %s", e)
