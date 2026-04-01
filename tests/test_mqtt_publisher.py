"""Tests for src/mqtt_publisher.py"""

import json
import threading
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# _ha_discovery_configs
# ---------------------------------------------------------------------------

class TestHaDiscoveryConfigs:
    def test_returns_eight_sensors(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        assert len(configs) == 8

    def test_each_config_has_topic_and_payload(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        for c in configs:
            assert "topic" in c
            assert "payload" in c

    def test_topics_under_homeassistant_sensor(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        for c in configs:
            assert c["topic"].startswith("homeassistant/sensor/usg_watchdog/")

    def test_payload_has_device(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        for c in configs:
            assert "device" in c["payload"]
            assert c["payload"]["device"]["name"] == "USG Watchdog"

    def test_payload_unique_ids_are_distinct(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        unique_ids = [c["payload"]["unique_id"] for c in configs]
        assert len(set(unique_ids)) == len(unique_ids)

    def test_state_topic_uses_prefix(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("my/prefix")
        for c in configs:
            assert c["payload"]["state_topic"].startswith("my/prefix/")

    def test_unit_only_on_metric_sensors(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        configs_with_units = [c for c in configs if "unit_of_measurement" in c["payload"]]
        sensor_ids = [c["payload"]["unique_id"] for c in configs_with_units]
        # gateway_rtt, internet_rtt, uptime have units
        assert any("rtt" in sid for sid in sensor_ids)
        assert any("uptime" in sid for sid in sensor_ids)

    def test_score_sensor_exists(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        ids = [c["payload"]["unique_id"] for c in configs]
        assert "usg_watchdog_score" in ids

    def test_status_sensor_exists(self):
        from mqtt_publisher import _ha_discovery_configs
        configs = _ha_discovery_configs("usg-watchdog")
        ids = [c["payload"]["unique_id"] for c in configs]
        assert "usg_watchdog_status" in ids


# ---------------------------------------------------------------------------
# MqttPublisher.__init__
# ---------------------------------------------------------------------------

class TestMqttPublisherInit:
    def test_initial_state(self):
        from mqtt_publisher import MqttPublisher
        from state import StateHolder
        holder = MagicMock(spec=StateHolder)
        pub = MqttPublisher(holder)
        assert pub._holder is holder
        assert pub._client is None
        assert pub._connected is False
        assert pub._discovery_sent is False


# ---------------------------------------------------------------------------
# MqttPublisher.start -- not configured
# ---------------------------------------------------------------------------

class TestMqttPublisherStartNotConfigured:
    def test_returns_false_when_broker_not_set(self):
        with patch("mqtt_publisher.MQTT_BROKER", ""):
            from mqtt_publisher import MqttPublisher
            holder = MagicMock()
            pub = MqttPublisher(holder)
            assert pub.start() is False

    def test_returns_false_when_paho_not_available(self):
        with patch("mqtt_publisher.MQTT_BROKER", "localhost"), \
             patch("mqtt_publisher.PAHO_AVAILABLE", False):
            from mqtt_publisher import MqttPublisher
            holder = MagicMock()
            pub = MqttPublisher(holder)
            assert pub.start() is False


# ---------------------------------------------------------------------------
# MqttPublisher.start -- configured with mock paho
# ---------------------------------------------------------------------------

class TestMqttPublisherStartConfigured:
    def _make_mock_paho(self):
        mock_paho = MagicMock()
        mock_client = MagicMock()
        mock_paho.Client.return_value = mock_client
        mock_paho.MQTTv311 = 4
        return mock_paho, mock_client

    def test_returns_true_when_configured(self):
        mock_paho, mock_client = self._make_mock_paho()
        with patch("mqtt_publisher.MQTT_BROKER", "localhost"), \
             patch("mqtt_publisher.MQTT_PORT", 1883), \
             patch("mqtt_publisher.MQTT_USERNAME", ""), \
             patch("mqtt_publisher.PAHO_AVAILABLE", True), \
             patch("mqtt_publisher.paho_mqtt", mock_paho), \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            result = pub.start()
            assert result is True
            mock_thread.start.assert_called_once()

    def test_sets_username_when_configured(self):
        mock_paho, mock_client = self._make_mock_paho()
        with patch("mqtt_publisher.MQTT_BROKER", "localhost"), \
             patch("mqtt_publisher.MQTT_PORT", 1883), \
             patch("mqtt_publisher.MQTT_USERNAME", "user"), \
             patch("mqtt_publisher.MQTT_PASSWORD", "pass"), \
             patch("mqtt_publisher.PAHO_AVAILABLE", True), \
             patch("mqtt_publisher.paho_mqtt", mock_paho), \
             patch("threading.Thread"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            pub.start()
            mock_client.username_pw_set.assert_called_once_with("user", "pass")

    def test_no_username_when_empty(self):
        mock_paho, mock_client = self._make_mock_paho()
        with patch("mqtt_publisher.MQTT_BROKER", "localhost"), \
             patch("mqtt_publisher.MQTT_PORT", 1883), \
             patch("mqtt_publisher.MQTT_USERNAME", ""), \
             patch("mqtt_publisher.PAHO_AVAILABLE", True), \
             patch("mqtt_publisher.paho_mqtt", mock_paho), \
             patch("threading.Thread"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            pub.start()
            mock_client.username_pw_set.assert_not_called()

    def test_returns_false_on_connect_exception(self):
        mock_paho, mock_client = self._make_mock_paho()
        mock_client.connect_async.side_effect = Exception("connection refused")
        with patch("mqtt_publisher.MQTT_BROKER", "localhost"), \
             patch("mqtt_publisher.MQTT_PORT", 1883), \
             patch("mqtt_publisher.MQTT_USERNAME", ""), \
             patch("mqtt_publisher.PAHO_AVAILABLE", True), \
             patch("mqtt_publisher.paho_mqtt", mock_paho):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            assert pub.start() is False


# ---------------------------------------------------------------------------
# MqttPublisher._on_connect / _on_disconnect
# ---------------------------------------------------------------------------

class TestMqttPublisherCallbacks:
    def test_on_connect_sets_connected(self):
        from mqtt_publisher import MqttPublisher
        pub = MqttPublisher(MagicMock())
        pub._on_connect(None, None, None, 0)
        assert pub._connected is True

    def test_on_disconnect_clears_connected(self):
        from mqtt_publisher import MqttPublisher
        pub = MqttPublisher(MagicMock())
        pub._connected = True
        pub._on_disconnect(None, None, 0)
        assert pub._connected is False

    def test_on_connect_sends_discovery_when_enabled(self):
        with patch("mqtt_publisher.MQTT_HA_DISCOVERY", True):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            pub._discovery_sent = False
            pub._client = MagicMock()
            with patch.object(pub, "_send_discovery") as mock_disc:
                pub._on_connect(None, None, None, 0)
                mock_disc.assert_called_once()

    def test_on_connect_skips_discovery_when_already_sent(self):
        with patch("mqtt_publisher.MQTT_HA_DISCOVERY", True):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            pub._discovery_sent = True
            pub._client = MagicMock()
            with patch.object(pub, "_send_discovery") as mock_disc:
                pub._on_connect(None, None, None, 0)
                mock_disc.assert_not_called()

    def test_on_connect_skips_discovery_when_disabled(self):
        with patch("mqtt_publisher.MQTT_HA_DISCOVERY", False):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(MagicMock())
            pub._discovery_sent = False
            pub._client = MagicMock()
            with patch.object(pub, "_send_discovery") as mock_disc:
                pub._on_connect(None, None, None, 0)
                mock_disc.assert_not_called()


# ---------------------------------------------------------------------------
# MqttPublisher._send_discovery
# ---------------------------------------------------------------------------

class TestSendDiscovery:
    def test_publishes_all_discovery_configs(self):
        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"), \
             patch("mqtt_publisher.MQTT_HA_DISCOVERY", True):
            from mqtt_publisher import MqttPublisher, _ha_discovery_configs
            pub = MqttPublisher(MagicMock())
            mock_client = MagicMock()
            pub._client = mock_client
            pub._send_discovery()
            expected_count = len(_ha_discovery_configs("usg-watchdog"))
            assert mock_client.publish.call_count == expected_count
            assert pub._discovery_sent is True

    def test_does_nothing_when_client_none(self):
        from mqtt_publisher import MqttPublisher
        pub = MqttPublisher(MagicMock())
        pub._client = None
        pub._send_discovery()
        assert pub._discovery_sent is False


# ---------------------------------------------------------------------------
# MqttPublisher._publish_state
# ---------------------------------------------------------------------------

def _make_watchdog_state(**kwargs):
    from state import WatchdogState
    defaults = dict(
        failure_score=2,
        threshold=10,
        gateway_ok=True,
        internet_ok_count=3,
        internet_total=3,
        reboots_today=0,
        uptime_seconds=3600.0,
        surveillance_only=False,
        gateway_rtt_ms=5.0,
        internet_avg_rtt_ms=12.0,
    )
    defaults.update(kwargs)
    return WatchdogState(**defaults)


class TestPublishState:
    def test_publishes_metrics(self):
        state = _make_watchdog_state()
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._connected = True
            pub._publish_state()
            assert mock_client.publish.call_count >= 5

    def test_does_nothing_when_state_none(self):
        holder = MagicMock()
        holder.state = None
        from mqtt_publisher import MqttPublisher
        pub = MqttPublisher(holder)
        mock_client = MagicMock()
        pub._client = mock_client
        pub._connected = True
        pub._publish_state()
        mock_client.publish.assert_not_called()

    def test_does_nothing_when_client_none(self):
        state = _make_watchdog_state()
        holder = MagicMock()
        holder.state = state
        from mqtt_publisher import MqttPublisher
        pub = MqttPublisher(holder)
        pub._client = None
        pub._publish_state()
        # No AttributeError -- just silently returns

    def test_publishes_status_healthy(self):
        state = _make_watchdog_state(failure_score=0)
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            published = {call[0][0]: call[0][1] for call in mock_client.publish.call_args_list}
            assert published.get("usg-watchdog/status") == "healthy"

    def test_publishes_status_critical(self):
        state = _make_watchdog_state(failure_score=10, threshold=10)
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            published = {call[0][0]: call[0][1] for call in mock_client.publish.call_args_list}
            assert published.get("usg-watchdog/status") == "critical"

    def test_publishes_status_degraded(self):
        state = _make_watchdog_state(failure_score=5, threshold=10)
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            published = {call[0][0]: call[0][1] for call in mock_client.publish.call_args_list}
            assert published.get("usg-watchdog/status") == "degraded"

    def test_publishes_status_surveillance(self):
        state = _make_watchdog_state(surveillance_only=True)
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            published = {call[0][0]: call[0][1] for call in mock_client.publish.call_args_list}
            assert published.get("usg-watchdog/status") == "surveillance"

    def test_skips_rtt_when_none(self):
        state = _make_watchdog_state(gateway_rtt_ms=None, internet_avg_rtt_ms=None)
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            topics = [call[0][0] for call in mock_client.publish.call_args_list]
            assert "usg-watchdog/gateway_rtt" not in topics
            assert "usg-watchdog/internet_rtt" not in topics

    def test_publishes_rtt_when_set(self):
        state = _make_watchdog_state(gateway_rtt_ms=7.5, internet_avg_rtt_ms=20.3)
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"):
            from mqtt_publisher import MqttPublisher
            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            published = {call[0][0]: call[0][1] for call in mock_client.publish.call_args_list}
            assert published.get("usg-watchdog/gateway_rtt") == 7.5
            assert published.get("usg-watchdog/internet_rtt") == 20.3
