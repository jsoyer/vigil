"""Tests for the MQTT incoming command path (src/mqtt_publisher.py).

Sprint 3 A2 -- premier `subscribe` MQTT du projet (C9). Aucun acces reseau,
aucun broker reel : le client MQTT est un objet factice minimal (seul
`publish`/`subscribe` sont exerces), et `managed_devices.registry` est
remplace par un stub controle par chaque test.

Pattern retenu -- "switch armer" + "button reboot" (C9/C10) :
- `{prefix}/site/{site}/tplink/{id}/cmd/arm` (subscribe, payload ON/OFF)
- `{prefix}/site/{site}/tplink/{id}/cmd/reboot` (subscribe, payload PRESS)
- `{prefix}/site/{site}/tplink/{id}/arm_state` (publish, retained)
- `{prefix}/site/{site}/tplink/{id}/last_action` (publish, retained, JSON)

Toute commande reelle (reboot) passe par `managed_devices.registry` --
jamais un appel direct au driver depuis ce module (C6 : meme garde que
l'API/dashboard).
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def _fixed_site_id():
    """Fixe SITE_ID pour toute la suite -- les topics de commande sont
    indexes sur le site (C12), independamment du hostname de la machine
    qui execute les tests."""
    with patch("mqtt_publisher.SITE_ID", "testsite"):
        yield


class _FakeMsg:
    """Substitut minimal de paho.mqtt.client.MQTTMessage."""

    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _FakeClient:
    """Substitut minimal du client MQTT -- seuls publish/subscribe comptent
    pour ces tests (pas de connexion reelle)."""

    def __init__(self) -> None:
        self.publish = MagicMock()
        self.subscribe = MagicMock()


def _make_publisher():
    from mqtt_publisher import MqttPublisher

    holder = MagicMock()
    holder.state = None
    publisher = MqttPublisher(holder)
    publisher._client = _FakeClient()
    return publisher


def _topic(action: str, device_id: str = "1", site: str = "testsite") -> str:
    return f"vigil/site/{site}/tplink/{device_id}/cmd/{action}"


def _last_action_payload(client) -> dict:
    """Retourne le dernier payload JSON publie sur .../last_action."""
    for call in reversed(client.publish.call_args_list):
        args = call.args
        if args and str(args[0]).endswith("/last_action"):
            return json.loads(args[1])
    raise AssertionError("aucun message last_action publie")


def _arm_state_calls(client, device_id: str = "1"):
    return [
        call
        for call in client.publish.call_args_list
        if call.args and str(call.args[0]).endswith(f"/{device_id}/arm_state")
    ]


# ---------------------------------------------------------------------------
# C9 -- ecoute desactivable, requiert un broker authentifie
# ---------------------------------------------------------------------------


class TestListenDisabled:
    def test_listen_disabled_no_subscribe_on_connect(self):
        with (
            patch("mqtt_publisher.MQTT_COMMANDS_ENABLED", False),
            patch("mqtt_publisher.MQTT_HA_DISCOVERY", False),
        ):
            publisher = _make_publisher()
            publisher._on_connect(publisher._client, None, None, 0)
        publisher._client.subscribe.assert_not_called()

    def test_listen_disabled_sensors_still_publish(self):
        """Les capteurs fonctionnent toujours quand l'ecoute est coupee."""
        state = MagicMock()
        state.failure_score = 0
        state.threshold = 10
        state.gateway_ok = True
        state.internet_ok_count = 3
        state.internet_total = 3
        state.reboots_today = 0
        state.uptime_seconds = 1.0
        state.surveillance_only = False
        state.gateway_rtt_ms = None
        state.internet_avg_rtt_ms = None
        state.to_json.return_value = "{}"

        with patch("mqtt_publisher.MQTT_COMMANDS_ENABLED", False):
            publisher = _make_publisher()
            publisher._holder.state = state
            publisher._publish_state()
        assert publisher._client.publish.called

    def test_commands_active_false_when_broker_anonymous(self):
        """C9 : meme flag active, sans MQTT_USERNAME l'ecoute reste coupee."""
        with (
            patch("mqtt_publisher.MQTT_COMMANDS_ENABLED", True),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
        ):
            publisher = _make_publisher()
            assert publisher._commands_active() is False

    def test_commands_active_true_when_enabled_and_authenticated(self):
        with (
            patch("mqtt_publisher.MQTT_COMMANDS_ENABLED", True),
            patch("mqtt_publisher.MQTT_USERNAME", "vigil"),
        ):
            publisher = _make_publisher()
            assert publisher._commands_active() is True

    def test_listen_enabled_subscribes_on_connect(self):
        with (
            patch("mqtt_publisher.MQTT_COMMANDS_ENABLED", True),
            patch("mqtt_publisher.MQTT_USERNAME", "vigil"),
            patch("mqtt_publisher.MQTT_HA_DISCOVERY", False),
            patch("managed_devices.registry.device_ids", return_value=["1"]),
        ):
            publisher = _make_publisher()
            publisher._on_connect(publisher._client, None, None, 0)
        assert publisher._client.subscribe.called


# ---------------------------------------------------------------------------
# Parsing strict -- message malforme ignore et logge, aucune action
# ---------------------------------------------------------------------------


class TestMalformedPayload:
    def test_malformed_arm_payload_ignored(self):
        publisher = _make_publisher()
        msg = _FakeMsg(_topic("arm"), b"\xff\xfe not utf8")
        publisher._on_message(publisher._client, None, msg)
        assert publisher._is_armed("1") is False
        publisher._client.publish.assert_not_called()

    def test_arm_payload_not_on_off_ignored(self):
        publisher = _make_publisher()
        msg = _FakeMsg(_topic("arm"), b"maybe")
        publisher._on_message(publisher._client, None, msg)
        assert publisher._is_armed("1") is False

    def test_oversized_payload_ignored(self):
        publisher = _make_publisher()
        msg = _FakeMsg(_topic("arm"), b"ON" + b"x" * 100)
        publisher._on_message(publisher._client, None, msg)
        assert publisher._is_armed("1") is False

    def test_unrecognized_topic_shape_ignored(self):
        publisher = _make_publisher()
        msg = _FakeMsg("vigil/not/a/command/topic", b"ON")
        # Ne doit jamais lever -- ignore et logge.
        publisher._on_message(publisher._client, None, msg)

    def test_unknown_action_ignored(self):
        publisher = _make_publisher()
        msg = _FakeMsg(_topic("wipe"), b"PRESS")
        publisher._on_message(publisher._client, None, msg)

    def test_reboot_payload_must_be_press(self):
        publisher = _make_publisher()
        arm_msg = _FakeMsg(_topic("arm"), b"ON")
        publisher._on_message(publisher._client, None, arm_msg)
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch("managed_devices.registry.request_reboot") as request_mock,
        ):
            msg = _FakeMsg(_topic("reboot"), b"press")  # casse invalide
            publisher._on_message(publisher._client, None, msg)
            # Non execute -- payload strictement "PRESS" attendu.
            request_mock.assert_not_called()


# ---------------------------------------------------------------------------
# C10 -- aucun echec silencieux : entite "derniere action" avec motif
# ---------------------------------------------------------------------------


class TestRebootRequiresArm:
    def test_reboot_without_arm_is_refused(self):
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch("managed_devices.registry.request_reboot") as request_mock,
        ):
            msg = _FakeMsg(_topic("reboot"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)
            request_mock.assert_not_called()

        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "refused"
        assert payload["reason"]
        assert payload["executed"] is False

    def test_reboot_refused_records_event_with_mqtt_origin(self):
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch("managed_devices.registry.record_event") as record_mock,
        ):
            msg = _FakeMsg(_topic("reboot"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)
            record_mock.assert_called_once()
            _, kwargs = record_mock.call_args
            assert kwargs.get("origin") == "mqtt"

    def test_reboot_unknown_device_refused(self):
        publisher = _make_publisher()
        with patch("managed_devices.registry.device_ids", return_value=[]):
            msg = _FakeMsg(_topic("reboot", device_id="99"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)
        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "refused"


class TestArmedReboot:
    def _arm(self, publisher, device_id="1"):
        msg = _FakeMsg(_topic("arm", device_id=device_id), b"ON")
        publisher._on_message(publisher._client, None, msg)

    def test_armed_reboot_is_executed_with_mqtt_origin(self):
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch(
                "managed_devices.registry.request_reboot",
                return_value={
                    "token": "tok123",
                    "device_id": "1",
                    "label": "mr110",
                    "warning": False,
                    "warning_reason": None,
                },
            ) as request_mock,
            patch(
                "managed_devices.registry.confirm_reboot",
                return_value={
                    "ok": True,
                    "executed": True,
                    "device_id": "1",
                    "label": "mr110",
                },
            ) as confirm_mock,
        ):
            self._arm(publisher)
            msg = _FakeMsg(_topic("reboot"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)

            request_mock.assert_called_once_with("1", origin="mqtt")
            confirm_mock.assert_called_once_with(
                "tok123", origin="mqtt", expected_device_id="1"
            )

        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "executed"
        assert payload["executed"] is True

    def test_armed_reboot_failure_reported_not_silent(self):
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch(
                "managed_devices.registry.request_reboot",
                return_value={
                    "token": "tok123",
                    "device_id": "1",
                    "label": "mr110",
                    "warning": False,
                    "warning_reason": None,
                },
            ),
            patch(
                "managed_devices.registry.confirm_reboot",
                return_value={
                    "ok": False,
                    "executed": True,
                    "error": "session occupee",
                },
            ),
        ):
            self._arm(publisher)
            msg = _FakeMsg(_topic("reboot"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)

        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "failed"
        assert payload["reason"]

    def test_arm_is_single_use_second_press_refused(self):
        """Desarmement immediat apres usage -- un double press ne reboote
        pas deux fois."""
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch(
                "managed_devices.registry.request_reboot",
                return_value={
                    "token": "tok123",
                    "device_id": "1",
                    "label": "mr110",
                    "warning": False,
                    "warning_reason": None,
                },
            ),
            patch(
                "managed_devices.registry.confirm_reboot",
                return_value={
                    "ok": True,
                    "executed": True,
                    "device_id": "1",
                    "label": "mr110",
                },
            ) as confirm_mock,
        ):
            self._arm(publisher)
            msg = _FakeMsg(_topic("reboot"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)
            publisher._on_message(publisher._client, None, msg)
            assert confirm_mock.call_count == 1

        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "refused"

    def test_in_use_device_reboot_not_blocked(self):
        """Le reboot n'est jamais bloque par l'usage en cours -- seulement
        remonte (C10, warning_reason)."""
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch(
                "managed_devices.registry.request_reboot",
                return_value={
                    "token": "tok123",
                    "device_id": "1",
                    "label": "mr110",
                    "warning": True,
                    "warning_reason": "cet equipement porte du trafic",
                },
            ),
            patch(
                "managed_devices.registry.confirm_reboot",
                return_value={
                    "ok": True,
                    "executed": True,
                    "device_id": "1",
                    "label": "mr110",
                },
            ) as confirm_mock,
        ):
            self._arm(publisher)
            msg = _FakeMsg(_topic("reboot"), b"PRESS")
            publisher._on_message(publisher._client, None, msg)
            confirm_mock.assert_called_once()

        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "executed"


# ---------------------------------------------------------------------------
# Desarmement automatique
# ---------------------------------------------------------------------------


class TestArmExpiry:
    def test_arm_expires_after_timeout(self):
        publisher = _make_publisher()
        with patch("mqtt_publisher.MQTT_ARM_TIMEOUT", 30):
            with patch("time.monotonic", return_value=1000.0):
                msg = _FakeMsg(_topic("arm"), b"ON")
                publisher._on_message(publisher._client, None, msg)
                assert publisher._is_armed("1") is True
            with patch("time.monotonic", return_value=1000.0 + 31):
                assert publisher._is_armed("1") is False

    def test_reboot_after_expiry_is_refused(self):
        publisher = _make_publisher()
        with (
            patch("mqtt_publisher.MQTT_ARM_TIMEOUT", 30),
            patch("managed_devices.registry.device_ids", return_value=["1"]),
        ):
            with patch("time.monotonic", return_value=2000.0):
                arm_msg = _FakeMsg(_topic("arm"), b"ON")
                publisher._on_message(publisher._client, None, arm_msg)
            with (
                patch("time.monotonic", return_value=2000.0 + 60),
                patch("managed_devices.registry.request_reboot") as request_mock,
            ):
                reboot_msg = _FakeMsg(_topic("reboot"), b"PRESS")
                publisher._on_message(publisher._client, None, reboot_msg)
                request_mock.assert_not_called()

        payload = _last_action_payload(publisher._client)
        assert payload["result"] == "refused"

    def test_disarm_off_clears_state(self):
        publisher = _make_publisher()
        arm_msg = _FakeMsg(_topic("arm"), b"ON")
        publisher._on_message(publisher._client, None, arm_msg)
        assert publisher._is_armed("1") is True

        disarm_msg = _FakeMsg(_topic("arm"), b"OFF")
        publisher._on_message(publisher._client, None, disarm_msg)
        assert publisher._is_armed("1") is False


# ---------------------------------------------------------------------------
# Aucune action destructive automatique (C6) -- convergence vers le registre
# ---------------------------------------------------------------------------


class TestNoAutoDestructive:
    def test_reboot_never_calls_driver_directly(self):
        """Le chemin MQTT ne fait jamais de call driver.reboot() direct --
        toujours via managed_devices.registry (meme garde que l'API)."""
        import inspect
        import mqtt_publisher

        source = inspect.getsource(mqtt_publisher)
        assert "driver.reboot" not in source
        assert ".reboot()" not in source

    def test_arm_alone_never_triggers_reboot(self):
        publisher = _make_publisher()
        with (
            patch("managed_devices.registry.request_reboot") as request_mock,
            patch("managed_devices.registry.confirm_reboot") as confirm_mock,
        ):
            msg = _FakeMsg(_topic("arm"), b"ON")
            publisher._on_message(publisher._client, None, msg)
            request_mock.assert_not_called()
            confirm_mock.assert_not_called()
