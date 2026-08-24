"""Tests for src/mqtt_publisher.py"""

from unittest.mock import MagicMock, patch


import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Fake broker MQTT -- pas un broker reel, aucun reseau. Sert a verifier la
# regle MQTT "une seule connexion active par client_id" : une reconnexion
# avec un client_id deja pris evince la precedente, exactement comme un
# broker reel. Utilise pour prouver le critere d'acceptation "deux
# instances se connectent simultanement sans s'evincer" (spec
# mqtt-instance-identity), plutot que de se contenter de comparer deux
# chaines passees a un mock.
# ---------------------------------------------------------------------------


class _FakeBroker:
    """Applique la regle MQTT d'unicite de connexion par client_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, "_FakeMqttClient"] = {}
        self.eviction_count = 0

    def connect(self, client_id: str, client: "_FakeMqttClient") -> None:
        """Enregistre une connexion. Evince la precedente si le client_id
        est deja pris -- comportement d'un vrai broker MQTT."""
        with self._lock:
            previous = self._connections.get(client_id)
            if previous is not None and previous is not client:
                previous._live = False
                self.eviction_count += 1
                if previous.on_disconnect is not None:
                    previous.on_disconnect(previous, None, 7)
            self._connections[client_id] = client
            client._live = True
        if client.on_connect is not None:
            client.on_connect(client, None, None, 0)

    def live_count(self) -> int:
        with self._lock:
            return sum(1 for c in self._connections.values() if c._live)


class _FakeMqttClient:
    """Client MQTT factice -- expose uniquement ce que MqttPublisher.start()
    manipule reellement : username_pw_set, on_connect, on_disconnect,
    connect_async, loop_start, publish."""

    def __init__(
        self, broker: "_FakeBroker", client_id: str, protocol: object = None
    ) -> None:
        self._broker = broker
        self.client_id = client_id
        self.on_connect = None
        self.on_disconnect = None
        self._live = False
        self.username_pw_set = MagicMock()
        self.publish = MagicMock()
        self.loop_start = MagicMock()

    def connect_async(self, host: str, port: int, keepalive: int = 60) -> None:
        self._broker.connect(self.client_id, self)


class _FakeMqttModule:
    """Remplace paho.mqtt.client -- expose Client() et MQTTv311 comme le
    vrai module, substitue via patch('mqtt_publisher.paho_mqtt', ...)."""

    def __init__(self, broker: "_FakeBroker") -> None:
        self._broker = broker
        self.MQTTv311 = 4

    def Client(self, client_id: str, protocol: object = None) -> "_FakeMqttClient":
        return _FakeMqttClient(self._broker, client_id, protocol)


# ---------------------------------------------------------------------------
# _ha_discovery_configs
# ---------------------------------------------------------------------------


class TestHaDiscoveryConfigs:
    def test_returns_eight_sensors(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("usg-watchdog", instance_id="testhost")
        assert len(configs) == 8

    def test_each_config_has_topic_and_payload(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("usg-watchdog")
        for c in configs:
            assert "topic" in c
            assert "payload" in c

    def test_topics_under_homeassistant_sensor(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("usg-watchdog", instance_id="testhost")
        for c in configs:
            assert c["topic"].startswith("homeassistant/sensor/vigil_testhost/")

    def test_payload_has_device(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("usg-watchdog", instance_id="testhost")
        for c in configs:
            assert "device" in c["payload"]
            assert c["payload"]["device"]["name"] == "Vigil testhost"
            assert c["payload"]["device"]["identifiers"] == ["vigil_testhost"]

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
        configs_with_units = [
            c for c in configs if "unit_of_measurement" in c["payload"]
        ]
        sensor_ids = [c["payload"]["unique_id"] for c in configs_with_units]
        # gateway_rtt, internet_rtt, uptime have units
        assert any("rtt" in sid for sid in sensor_ids)
        assert any("uptime" in sid for sid in sensor_ids)

    def test_score_sensor_exists(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("usg-watchdog", instance_id="testhost")
        ids = [c["payload"]["unique_id"] for c in configs]
        assert "vigil_testhost_score" in ids

    def test_status_sensor_exists(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("usg-watchdog", instance_id="testhost")
        ids = [c["payload"]["unique_id"] for c in configs]
        assert "vigil_testhost_status" in ids


# ---------------------------------------------------------------------------
# Identite d'instance -- collision entre plusieurs instances (bugfix)
# ---------------------------------------------------------------------------


class TestInstanceIdentityDisjoint:
    """Deux instances differentes ne doivent jamais partager la meme identite."""

    def test_device_identifiers_are_disjoint(self):
        from mqtt_publisher import _ha_discovery_configs

        configs_a = _ha_discovery_configs("usg-watchdog", instance_id="dijon_master")
        configs_b = _ha_discovery_configs("usg-watchdog", instance_id="nice_master")

        identifiers_a = {
            tuple(c["payload"]["device"]["identifiers"]) for c in configs_a
        }
        identifiers_b = {
            tuple(c["payload"]["device"]["identifiers"]) for c in configs_b
        }
        assert identifiers_a.isdisjoint(identifiers_b)

    def test_unique_ids_are_disjoint(self):
        from mqtt_publisher import _ha_discovery_configs

        configs_a = _ha_discovery_configs("usg-watchdog", instance_id="dijon_master")
        configs_b = _ha_discovery_configs("usg-watchdog", instance_id="nice_master")

        unique_ids_a = {c["payload"]["unique_id"] for c in configs_a}
        unique_ids_b = {c["payload"]["unique_id"] for c in configs_b}
        assert unique_ids_a.isdisjoint(unique_ids_b)

    def test_discovery_topics_are_disjoint(self):
        from mqtt_publisher import _ha_discovery_configs

        configs_a = _ha_discovery_configs("usg-watchdog", instance_id="dijon_master")
        configs_b = _ha_discovery_configs("usg-watchdog", instance_id="nice_master")

        topics_a = {c["topic"] for c in configs_a}
        topics_b = {c["topic"] for c in configs_b}
        assert topics_a.isdisjoint(topics_b)


class TestInstanceIdDefaultAndNormalization:
    """INSTANCE_ID par defaut derive du hostname, normalise et jamais vide."""

    def test_default_derived_from_hostname_is_non_empty_and_normalized(self):
        import importlib
        import config as config_module

        env_backup = os.environ.pop("INSTANCE_ID", None)
        try:
            with patch("socket.gethostname", return_value="Pi-Dijon.local"):
                importlib.reload(config_module)
                derived = config_module.INSTANCE_ID
        finally:
            if env_backup is not None:
                os.environ["INSTANCE_ID"] = env_backup
            importlib.reload(config_module)

        assert derived != ""
        assert derived == derived.lower()
        assert all(ch.isalnum() or ch == "_" for ch in derived)
        assert derived == "pi_dijon_local"

    def test_hostname_with_dashes_and_dots_is_normalized(self):
        from config import _normalize_instance_id

        assert _normalize_instance_id("Pi-Dijon.local") == "pi_dijon_local"

    def test_hostname_with_underscore_and_space_is_normalized(self):
        from config import _normalize_instance_id

        assert _normalize_instance_id("NICE_master 01") == "nice_master_01"

    def test_empty_normalizes_to_fallback(self):
        from config import _normalize_instance_id

        assert _normalize_instance_id("") == "vigil"

    def test_only_special_chars_normalizes_to_fallback(self):
        from config import _normalize_instance_id

        assert _normalize_instance_id("---") == "vigil"

    def test_accented_hostname_normalizes_to_ascii_only(self):
        """Les lettres accentuees (non-ASCII) doivent devenir '_', pas
        passer telles quelles -- topics MQTT / unique_id HA sont ASCII."""
        from config import _normalize_instance_id

        result = _normalize_instance_id("Pi-Dîjon.local")
        assert result != ""
        assert all(ch.isascii() for ch in result)
        assert all(ch in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in result)

    def test_cjk_hostname_normalizes_to_ascii_only(self):
        """Idem pour des caracteres CJK -- aucun ne doit survivre."""
        from config import _normalize_instance_id

        result = _normalize_instance_id("住宅-pi")
        assert result != ""
        assert all(ch.isascii() for ch in result)
        assert all(ch in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in result)
        assert result == "pi"


class TestClientIdPerInstance:
    """MQTT_CLIENT_ID doit etre derive de l'instance -- sinon le broker evince
    les instances qui partagent le meme identifiant de connexion."""

    def _make_mock_paho(self):
        mock_paho = MagicMock()
        mock_client = MagicMock()
        mock_paho.Client.return_value = mock_client
        mock_paho.MQTTv311 = 4
        return mock_paho, mock_client

    def test_client_id_derived_from_instance_id(self):
        mock_paho, mock_client = self._make_mock_paho()
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho),
            patch("mqtt_publisher.INSTANCE_ID", "dijon_master"),
            patch("threading.Thread"),
        ):
            from mqtt_publisher import MqttPublisher

            pub = MqttPublisher(MagicMock())
            pub.start()
            _, kwargs = mock_paho.Client.call_args
            assert kwargs["client_id"] == "vigil-dijon_master"

    def test_two_instances_get_distinct_client_id_strings_cheap_check(self):
        """Verification bon marche que les chaines de client_id different.

        Ne prouve PAS l'absence d'eviction sur un broker -- c'est le role de
        TestTwoInstancesConnectSimultaneouslyWithoutEviction ci-dessous, qui
        utilise un broker factice appliquant la regle MQTT reelle. Ce test-ci
        reste comme garde-fou bon marche sur le format de la chaine."""

        mock_paho_a, mock_client_a = self._make_mock_paho()
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho_a),
            patch("mqtt_publisher.INSTANCE_ID", "dijon_master"),
            patch("threading.Thread"),
        ):
            from mqtt_publisher import MqttPublisher

            pub_a = MqttPublisher(MagicMock())
            result_a = pub_a.start()

        mock_paho_b, mock_client_b = self._make_mock_paho()
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho_b),
            patch("mqtt_publisher.INSTANCE_ID", "nice_master"),
            patch("threading.Thread"),
        ):
            from mqtt_publisher import MqttPublisher

            pub_b = MqttPublisher(MagicMock())
            result_b = pub_b.start()

        assert result_a is True
        assert result_b is True
        client_id_a = mock_paho_a.Client.call_args.kwargs["client_id"]
        client_id_b = mock_paho_b.Client.call_args.kwargs["client_id"]
        assert client_id_a != client_id_b
        assert client_id_a == "vigil-dijon_master"
        assert client_id_b == "vigil-nice_master"


class TestTwoInstancesConnectSimultaneouslyWithoutEviction:
    """Preuve de l'acceptance criterion spec (mqtt-instance-identity) :
    'deux instances simulees se connectent simultanement sans s'evincer'.

    Utilise _FakeBroker, qui applique la regle MQTT reelle (une connexion
    active par client_id). Demarre les deux instances depuis deux threads
    reels pour rendre "simultanement" litteral."""

    def _start_instance(
        self,
        instance_id: str,
        results: dict,
        key: str,
        instance_id_lock: threading.Lock,
    ) -> None:
        # mqtt_publisher.INSTANCE_ID est un attribut de module partage par
        # tout le process Python -- il n'existe pas de parametre par-instance
        # dans l'architecture actuelle (en production, chaque instance tourne
        # dans son propre process avec son propre INSTANCE_ID ; cette
        # contrainte ne s'y pose donc pas). Ce verrou protege uniquement la
        # fenetre ou l'attribut partage est patche, pour eviter qu'un thread
        # lise la valeur ecrite par l'autre. Il ne serialise PAS le broker :
        # c'est bien _FakeBroker.connect() (avec son propre verrou interne)
        # qui arbitre les deux connexions et qui est ce qu'on teste ici. Les
        # autres patches (MQTT_BROKER, paho_mqtt, etc.) sont appliques une
        # seule fois par le thread principal, avant le demarrage des deux
        # threads -- les appliquer par thread ici provoquerait une vraie
        # course sur __exit__ (un thread restaure la valeur d'origine
        # pendant que l'autre en depend encore).
        from mqtt_publisher import MqttPublisher

        pub = MqttPublisher(MagicMock())
        with instance_id_lock, patch("mqtt_publisher.INSTANCE_ID", instance_id):
            results[key] = pub.start()

    def test_two_distinct_instance_ids_both_stay_connected(self):
        broker = _FakeBroker()
        fake_module = _FakeMqttModule(broker)
        results: dict = {}
        instance_id_lock = threading.Lock()

        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", fake_module),
        ):
            t_a = threading.Thread(
                target=self._start_instance,
                args=("dijon_master", results, "a", instance_id_lock),
            )
            t_b = threading.Thread(
                target=self._start_instance,
                args=("nice_master", results, "b", instance_id_lock),
            )
            t_a.start()
            t_b.start()
            t_a.join(timeout=5)
            t_b.join(timeout=5)

        assert not t_a.is_alive(), "thread instance A bloque -- timeout"
        assert not t_b.is_alive(), "thread instance B bloque -- timeout"
        assert results.get("a") is True
        assert results.get("b") is True
        assert broker.eviction_count == 0
        assert broker.live_count() == 2


class TestSharedClientIdCausesEviction:
    """Controle negatif : sans cette preuve, le test ci-dessus ne demontre
    rien -- il doit pouvoir echouer. Deux instances qui partagent le meme
    INSTANCE_ID (simulation du comportement pre-fix, ou MQTT_CLIENT_ID etait
    en dur) doivent produire exactement une eviction sur le broker factice."""

    def _start_instance(
        self,
        results: dict,
        key: str,
        instance_id_lock: threading.Lock,
    ) -> None:
        from mqtt_publisher import MqttPublisher

        pub = MqttPublisher(MagicMock())
        # Simule le bug pre-fix : les deux instances partagent le meme
        # identifiant, comme lorsque MQTT_CLIENT_ID etait code en dur.
        with (
            instance_id_lock,
            patch("mqtt_publisher.INSTANCE_ID", "shared_instance"),
        ):
            results[key] = pub.start()

    def test_shared_client_id_evicts_previous_connection(self):
        broker = _FakeBroker()
        fake_module = _FakeMqttModule(broker)
        results: dict = {}
        instance_id_lock = threading.Lock()

        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", fake_module),
        ):
            t_a = threading.Thread(
                target=self._start_instance,
                args=(results, "a", instance_id_lock),
            )
            t_b = threading.Thread(
                target=self._start_instance,
                args=(results, "b", instance_id_lock),
            )
            t_a.start()
            t_b.start()
            t_a.join(timeout=5)
            t_b.join(timeout=5)

        assert not t_a.is_alive(), "thread instance A bloque -- timeout"
        assert not t_b.is_alive(), "thread instance B bloque -- timeout"
        assert results.get("a") is True
        assert results.get("b") is True
        assert broker.eviction_count == 1
        assert broker.live_count() == 1


class TestIsConfigured:
    def test_false_when_broker_empty(self):
        with patch("mqtt_publisher.MQTT_BROKER", ""):
            from mqtt_publisher import is_configured

            assert is_configured() is False

    def test_true_when_broker_set(self):
        with patch("mqtt_publisher.MQTT_BROKER", "localhost"):
            from mqtt_publisher import is_configured

            assert is_configured() is True


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
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.PAHO_AVAILABLE", False),
        ):
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
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            from mqtt_publisher import MqttPublisher

            pub = MqttPublisher(MagicMock())
            result = pub.start()
            assert result is True
            mock_thread.start.assert_called_once()

    def test_sets_username_when_configured(self):
        mock_paho, mock_client = self._make_mock_paho()
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", "user"),
            patch("mqtt_publisher.MQTT_PASSWORD", "pass"),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho),
            patch("threading.Thread"),
        ):
            from mqtt_publisher import MqttPublisher

            pub = MqttPublisher(MagicMock())
            pub.start()
            mock_client.username_pw_set.assert_called_once_with("user", "pass")

    def test_no_username_when_empty(self):
        mock_paho, mock_client = self._make_mock_paho()
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho),
            patch("threading.Thread"),
        ):
            from mqtt_publisher import MqttPublisher

            pub = MqttPublisher(MagicMock())
            pub.start()
            mock_client.username_pw_set.assert_not_called()

    def test_returns_false_on_connect_exception(self):
        mock_paho, mock_client = self._make_mock_paho()
        mock_client.connect_async.side_effect = Exception("connection refused")
        with (
            patch("mqtt_publisher.MQTT_BROKER", "localhost"),
            patch("mqtt_publisher.MQTT_PORT", 1883),
            patch("mqtt_publisher.MQTT_USERNAME", ""),
            patch("mqtt_publisher.PAHO_AVAILABLE", True),
            patch("mqtt_publisher.paho_mqtt", mock_paho),
        ):
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
        with (
            patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "usg-watchdog"),
            patch("mqtt_publisher.MQTT_HA_DISCOVERY", True),
        ):
            from mqtt_publisher import (
                MqttPublisher,
                SITE_ID,
                TPLINK_DEVICES,
                _ha_discovery_configs,
                _tplink_discovery_configs,
                _usg_discovery_configs,
                _watchdog_extra_discovery_configs,
            )

            pub = MqttPublisher(MagicMock())
            mock_client = MagicMock()
            pub._client = mock_client
            pub._send_discovery()
            # _send_discovery publie desormais plus que les 8 capteurs
            # historiques : les ajouts watchdog (C15/C17) et, si des
            # equipements TP-Link sont declares, un device par equipement
            # (C12/C13) plus le device USG du site (C15). Le compte
            # attendu suit la meme logique conditionnelle que
            # _send_discovery elle-meme, pour rester correct quels que
            # soient les TPLINK_* configures dans l'environnement de test.
            expected_count = len(_ha_discovery_configs("usg-watchdog")) + len(
                _watchdog_extra_discovery_configs("usg-watchdog")
            )
            for cfg in TPLINK_DEVICES:
                expected_count += len(
                    _tplink_discovery_configs(
                        "usg-watchdog", SITE_ID, str(cfg.index), cfg.label
                    )
                )
            if TPLINK_DEVICES:
                expected_count += len(_usg_discovery_configs("usg-watchdog", SITE_ID))
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
            published = {
                call[0][0]: call[0][1] for call in mock_client.publish.call_args_list
            }
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
            published = {
                call[0][0]: call[0][1] for call in mock_client.publish.call_args_list
            }
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
            published = {
                call[0][0]: call[0][1] for call in mock_client.publish.call_args_list
            }
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
            published = {
                call[0][0]: call[0][1] for call in mock_client.publish.call_args_list
            }
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
            published = {
                call[0][0]: call[0][1] for call in mock_client.publish.call_args_list
            }
            assert published.get("usg-watchdog/gateway_rtt") == 7.5
            assert published.get("usg-watchdog/internet_rtt") == 20.3


# ---------------------------------------------------------------------------
# Sprint 3 A2 -- devices par equipement TP-Link, device USG par site,
# enrichissement des 8 capteurs existants (C12/C13/C14/C15).
# ---------------------------------------------------------------------------


class TestLegacySensorsUniqueIdStable:
    """C14 -- l'unique_id des 8 capteurs existants ne bouge pas."""

    def test_legacy_sensors_unique_id_stable(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("vigil", instance_id="dijon_master")
        unique_ids = {c["payload"]["unique_id"] for c in configs}
        assert unique_ids == {
            "vigil_dijon_master_score",
            "vigil_dijon_master_gateway",
            "vigil_dijon_master_internet",
            "vigil_dijon_master_reboots_today",
            "vigil_dijon_master_status",
            "vigil_dijon_master_gateway_rtt",
            "vigil_dijon_master_internet_rtt",
            "vigil_dijon_master_uptime",
        }

    def test_legacy_sensors_stay_sensor_platform(self):
        """C14 -- jamais de conversion sensor -> binary_sensor."""
        from mqtt_publisher import _ha_discovery_configs

        configs = _ha_discovery_configs("vigil", instance_id="dijon_master")
        for c in configs:
            assert c["topic"].startswith("homeassistant/sensor/")


class TestLegacySensorsEnriched:
    """C14 -- device_class/state_class/retain s'ajoutent, additifs seulement."""

    def test_legacy_sensors_enriched(self):
        from mqtt_publisher import _ha_discovery_configs

        configs = {
            c["payload"]["unique_id"]: c["payload"]
            for c in _ha_discovery_configs("vigil", instance_id="dijon_master")
        }
        assert configs["vigil_dijon_master_score"]["state_class"] == "measurement"
        assert configs["vigil_dijon_master_status"]["device_class"] == "enum"
        assert configs["vigil_dijon_master_gateway"]["device_class"] == "enum"
        assert configs["vigil_dijon_master_internet"]["device_class"] == "enum"
        assert (
            configs["vigil_dijon_master_reboots_today"]["state_class"]
            == "total_increasing"
        )
        assert configs["vigil_dijon_master_gateway_rtt"]["unit_of_measurement"] == "ms"
        assert configs["vigil_dijon_master_gateway_rtt"]["state_class"] == "measurement"
        assert configs["vigil_dijon_master_internet_rtt"]["unit_of_measurement"] == "ms"
        assert configs["vigil_dijon_master_uptime"]["device_class"] == "duration"
        assert configs["vigil_dijon_master_uptime"]["unit_of_measurement"] == "s"

    def test_legacy_states_published_with_retain(self):
        state = _make_watchdog_state()
        holder = MagicMock()
        holder.state = state

        with patch("mqtt_publisher.MQTT_TOPIC_PREFIX", "vigil"):
            from mqtt_publisher import MqttPublisher

            pub = MqttPublisher(holder)
            mock_client = MagicMock()
            pub._client = mock_client
            pub._publish_state()
            for call in mock_client.publish.call_args_list:
                topic = call[0][0]
                if topic == "vigil/state":
                    continue  # topic JSON global, hors perimetre (spec.md 4)
                assert call.kwargs.get("retain") is True, f"{topic} sans retain"


class TestDeviceIdentitySite:
    """C12/C15 -- l'identite d'un device par equipement (ou USG) est
    indexee site + equipement, identique vue du master et du slave."""

    def test_device_identity_same_for_master_and_slave(self):
        from config import _default_site_id
        from mqtt_publisher import _tplink_device_identity

        site_master = _default_site_id("dijon_master")
        site_slave = _default_site_id("dijon_slave")
        assert site_master == site_slave == "dijon"
        assert _tplink_device_identity(site_master, "1") == _tplink_device_identity(
            site_slave, "1"
        )

    def test_usg_device_identity_same_for_master_and_slave(self):
        from config import _default_site_id
        from mqtt_publisher import _usg_device_identity

        site_master = _default_site_id("nice_master")
        site_slave = _default_site_id("nice_slave")
        assert _usg_device_identity(site_master) == _usg_device_identity(site_slave)

    def test_two_equipments_two_distinct_devices(self):
        from mqtt_publisher import _tplink_device_identity

        assert _tplink_device_identity("dijon", "1") != _tplink_device_identity(
            "dijon", "2"
        )


class TestTplinkEntitySetStable:
    """C13 -- la liste d'entites par equipement est figee, independante des
    donnees d'un cycle."""

    def test_entity_set_stable_across_calls(self):
        from mqtt_publisher import _tplink_discovery_configs

        first = _tplink_discovery_configs("vigil", "dijon", "1", "mr110")
        second = _tplink_discovery_configs("vigil", "dijon", "1", "mr110")
        keys_first = {c["payload"]["unique_id"] for c in first}
        keys_second = {c["payload"]["unique_id"] for c in second}
        assert keys_first == keys_second
        assert len(keys_first) == len(first)  # tous uniques

    def test_entity_set_includes_command_entities(self):
        from mqtt_publisher import _tplink_discovery_configs

        configs = _tplink_discovery_configs("vigil", "dijon", "1", "mr110")
        platforms = {c["topic"].split("/")[1] for c in configs}
        assert "switch" in platforms
        assert "button" in platforms


class TestUnavailableNotUnpublished:
    """C13 -- un champ illisible devient 'unavailable', jamais depublie ni
    publie a zero."""

    def test_missing_fields_yield_none_not_zero(self):
        from mqtt_publisher import _tplink_entity_value

        empty_status: dict = {}
        for spec_key in (
            "readiness",
            "secours_degrade",
            "attache",
            "sonde_resultat",
            "rsrp",
            "rtt_routeur",
            "age_donnee_peer",
        ):
            value = _tplink_entity_value(spec_key, empty_status, None)
            assert value is None, f"{spec_key} devrait etre None, pas {value!r}"

    def test_failed_hop_none_means_aucun_not_unavailable(self):
        """failed_hop=None dans un statut LU est une valeur connue ('aucun
        saut en panne'), distincte d'un champ illisible."""
        from mqtt_publisher import _tplink_entity_value

        status = {"failed_hop": None}
        assert _tplink_entity_value("saut_panne", status, None) == "aucun"

    def test_failed_hop_absent_is_unavailable(self):
        from mqtt_publisher import _tplink_entity_value

        assert _tplink_entity_value("saut_panne", {}, None) is None

    def test_usage_state_unknown_is_a_valid_value_not_none(self):
        """usage_state absent -> 'unknown' est un etat valide de l'enum
        (idle/in_use/saturated/unknown), pas un champ manquant."""
        from mqtt_publisher import _tplink_entity_value

        assert _tplink_entity_value("etat_usage", {}, None) == "unknown"

    def test_sur_secours_absent_is_unavailable(self):
        from mqtt_publisher import _tplink_entity_value

        assert _tplink_entity_value("sur_secours", {}, None) is None

    def test_sur_secours_follows_on_backup(self):
        from mqtt_publisher import _tplink_entity_value

        assert _tplink_entity_value("sur_secours", {"on_backup": True}, None) == "ON"
        assert _tplink_entity_value("sur_secours", {"on_backup": False}, None) == "OFF"


class TestSinglePublisher:
    """C12 -- seule l'instance elue publie les entites d'un equipement."""

    def test_non_elected_instance_publishes_nothing_for_device(self):
        from mqtt_publisher import MqttPublisher

        holder = MagicMock()
        holder.state = _make_watchdog_state()
        pub = MqttPublisher(holder)
        pub._client = MagicMock()

        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch(
                "managed_devices.registry.get_status",
                return_value={"id": "1", "label": "mr110", "from_peer": True},
            ),
            patch("managed_devices.registry.quota_status", return_value=None),
        ):
            pub._publish_tplink_devices()

        assert pub._client.publish.call_count == 0

    def test_elected_instance_publishes_device_entities(self):
        from mqtt_publisher import MqttPublisher

        holder = MagicMock()
        holder.state = _make_watchdog_state()
        pub = MqttPublisher(holder)
        pub._client = MagicMock()

        status = {
            "id": "1",
            "label": "mr110",
            "reachable": True,
            "readiness": "ok",
            "failed_hop": None,
        }
        with (
            patch("managed_devices.registry.device_ids", return_value=["1"]),
            patch("managed_devices.registry.get_status", return_value=status),
            patch("managed_devices.registry.quota_status", return_value=None),
        ):
            pub._publish_tplink_devices()

        assert pub._client.publish.call_count > 0


class TestSingleUsgDevice:
    """C15 -- un seul device USG par site, alimente par l'instance elue."""

    def test_single_usg_device_identity_per_site(self):
        from mqtt_publisher import _usg_discovery_configs

        configs = _usg_discovery_configs("vigil", "dijon")
        identifiers = {tuple(c["payload"]["device"]["identifiers"]) for c in configs}
        assert identifiers == {("vigil_dijon_usg",)}

    def test_usg_line_sensors_stay_sensor_not_binary(self):
        """C14 -- meme raisonnement applique aux 4 capteurs de ligne
        recrees : gateway/internet restent des sensor."""
        from mqtt_publisher import _usg_discovery_configs

        configs = _usg_discovery_configs("vigil", "dijon")
        for c in configs:
            assert c["topic"].split("/")[1] == "sensor"

    def test_non_elected_instance_does_not_publish_usg(self):
        from mqtt_publisher import MqttPublisher

        holder = MagicMock()
        holder.state = _make_watchdog_state()
        pub = MqttPublisher(holder)
        pub._client = MagicMock()

        with (
            patch("mqtt_publisher.TPLINK_DEVICES", (object(),)),
            patch(
                "mqtt_publisher._is_usg_elected",
                return_value=(False, "peer a priorite"),
            ),
        ):
            pub._publish_usg_device()

        pub._client.publish.assert_not_called()

    def test_elected_instance_publishes_usg(self):
        from mqtt_publisher import MqttPublisher

        holder = MagicMock()
        holder.state = _make_watchdog_state()
        pub = MqttPublisher(holder)
        pub._client = MagicMock()

        with (
            patch("mqtt_publisher.TPLINK_DEVICES", (object(),)),
            patch("mqtt_publisher._is_usg_elected", return_value=(True, "standalone")),
        ):
            pub._publish_usg_device()

        assert pub._client.publish.call_count > 0


class TestDivergenceSensor:
    """C15 -- binary_sensor divergence, compense la perte de la double vue."""

    def test_divergence_sensor_on_when_diverging(self):
        from mqtt_publisher import _watchdog_divergence_state

        state = _make_watchdog_state()
        with patch("peer.check_divergence", return_value="Divergence detectee\n..."):
            assert _watchdog_divergence_state(state) == "ON"

    def test_divergence_sensor_off_when_agreeing(self):
        from mqtt_publisher import _watchdog_divergence_state

        state = _make_watchdog_state()
        with patch("peer.check_divergence", return_value=None):
            assert _watchdog_divergence_state(state) == "OFF"

    def test_watchdog_extra_discovery_includes_divergence_and_peer_state(self):
        from mqtt_publisher import _watchdog_extra_discovery_configs

        configs = _watchdog_extra_discovery_configs("vigil", instance_id="dijon_master")
        keys = {c["payload"]["unique_id"] for c in configs}
        assert "vigil_dijon_master_divergence" in keys
        assert "vigil_dijon_master_peer_state" in keys

    def test_watchdog_extra_stays_on_existing_device(self):
        """Les nouvelles entites restent sur le device watchdog existant
        (identifiers inchanges) -- purement additif (C15)."""
        from mqtt_publisher import _watchdog_extra_discovery_configs

        configs = _watchdog_extra_discovery_configs("vigil", instance_id="dijon_master")
        for c in configs:
            assert c["payload"]["device"]["identifiers"] == ["vigil_dijon_master"]


class TestHostMetricsC17:
    """C17 -- metriques hote stdlib, jamais zero si indisponible."""

    def test_cpu_temp_missing_file_returns_none(self):
        from mqtt_publisher import _read_cpu_temp_c

        assert _read_cpu_temp_c(path="/nonexistent/thermal_zone_xyz") is None

    def test_cpu_temp_parses_millidegrees(self, tmp_path):
        from mqtt_publisher import _read_cpu_temp_c

        f = tmp_path / "temp"
        f.write_text("45000")
        assert _read_cpu_temp_c(path=str(f)) == 45.0

    def test_mem_available_missing_file_returns_none(self):
        from mqtt_publisher import _read_mem_available_mb

        assert _read_mem_available_mb(path="/nonexistent/meminfo_xyz") is None

    def test_load1_returns_a_float(self):
        from mqtt_publisher import _read_load1

        value = _read_load1()
        assert value is None or isinstance(value, float)
