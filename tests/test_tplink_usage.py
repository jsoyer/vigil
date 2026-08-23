"""Tests -- detection d'usage 3 etats, sonde periodique (C11), niveaux de
notification (C18) et election du poller (C12, fonctions pures de
peer.py) pour les equipements TP-Link. Sprint 1 A2.

Executor 2 completera ce fichier avec des tests d'integration
supplementaires (election a deux instances simulees via HTTP mocke,
split-brain cable, reprise apres PEER_TAKEOVER_DELAY) une fois
`managed_devices.py` et `peer.py` implementes -- ne pas s'etonner d'y
trouver des classes ajoutees apres coup."""

import sys
import os
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from drivers._base import Readiness, RouterHealth, RouterMetrics, RouterReadiness
from drivers.tplink import ProbeResult


def _make_config(index: int = 1, label: str = "mr110-test", **overrides):
    from config import TplinkDeviceConfig

    defaults = dict(
        index=index,
        label=label,
        host="192.168.10.1",
        password="s3cr3t-pwd",
        mode="bridged",
        bridge_host="",
        rsrp_min=-110,
        rsrq_min=-20,
        snr_min=-100,
    )
    defaults.update(overrides)
    return TplinkDeviceConfig(**defaults)


class _FakeDriver:
    """Double minimal de TplinkDriver -- aucun acces reseau."""

    vendor = "tplink"

    def __init__(
        self,
        health_result: RouterHealth | None = None,
        readiness_result: RouterReadiness | None = None,
        metrics_result: RouterMetrics | None = None,
        probe_results=None,
    ) -> None:
        self._health_result = health_result or RouterHealth(
            reachable=True, internet_ok=None, rtt_ms=12.0, failed_hop=None, detail=""
        )
        self._readiness_result = readiness_result or RouterReadiness(
            state=Readiness.OK, reasons=()
        )
        self._metrics_result = metrics_result or RouterMetrics(
            rsrp=-95,
            rsrq=-12,
            snr=-20,
            network_type="LTE",
            isp_name="Free",
            rx_speed_bps=0,
            tx_speed_bps=0,
            clients_total=0,
            data_used_bytes=0,
        )
        self._probe_results = list(probe_results or [ProbeResult.OK])
        self.probe_calls = 0
        self.reboot_calls = 0
        self.health_calls = 0

    def health(self) -> RouterHealth:
        self.health_calls += 1
        return self._health_result

    def readiness(self) -> RouterReadiness:
        return self._readiness_result

    def metrics(self) -> RouterMetrics:
        return self._metrics_result

    def probe_end_to_end(self) -> ProbeResult:
        idx = min(self.probe_calls, len(self._probe_results) - 1)
        result = self._probe_results[idx]
        self.probe_calls += 1
        return result

    def reboot(self) -> bool:
        self.reboot_calls += 1
        return True

    def test_connection(self) -> bool:
        return True


def _make_registry(driver=None, devices=None, **kwargs):
    from managed_devices import ManagedDeviceRegistry

    driver = driver or _FakeDriver()
    devices = devices if devices is not None else [_make_config()]
    return (
        ManagedDeviceRegistry(
            devices=devices, driver_factory=lambda cfg: driver, **kwargs
        ),
        driver,
    )


def _capture_notify():
    import managed_devices

    calls = []

    def fake_notify(text, level, ctx=None):
        calls.append({"text": text, "level": level, "ctx": ctx})
        return {}

    original = managed_devices.notify
    managed_devices.notify = fake_notify
    return calls, original


class TestUsageThreeStates:
    def test_idle_when_no_traffic_no_clients(self):
        from managed_devices import _classify_usage, USAGE_IDLE

        assert _classify_usage(0, 0, 0) == USAGE_IDLE

    def test_in_use_when_traffic_flows(self):
        from managed_devices import _classify_usage, USAGE_IN_USE

        assert _classify_usage(5_000_000, 1_000_000, 3) == USAGE_IN_USE

    def test_saturated_near_cat4_ceiling(self):
        from managed_devices import _classify_usage, USAGE_SATURATED, CAT4_DOWNLINK_BPS

        assert _classify_usage(CAT4_DOWNLINK_BPS * 0.9, 0, 1) == USAGE_SATURATED

    def test_saturated_at_max_clients(self):
        from managed_devices import _classify_usage, USAGE_SATURATED, MAX_CLIENTS

        assert _classify_usage(0, 0, MAX_CLIENTS) == USAGE_SATURATED

    def test_missing_fields_never_invent_a_state(self):
        from managed_devices import _classify_usage, USAGE_UNKNOWN

        assert _classify_usage(None, None, None) == USAGE_UNKNOWN


class TestUsageAntiRebond:
    def test_isolated_spike_does_not_trigger_event(self):
        from managed_devices import UsageTracker

        tracker = UsageTracker(debounce_cycles=2)
        confirmed1, changed1 = tracker.update("1", 5_000_000, 0, 2)
        confirmed2, changed2 = tracker.update("1", 0, 0, 0)

        assert changed1 is False
        assert changed2 is False
        assert confirmed2 == "idle"

    def test_sustained_traffic_confirms_in_use_once(self):
        from managed_devices import UsageTracker, USAGE_IN_USE

        tracker = UsageTracker(debounce_cycles=2)
        tracker.update("1", 5_000_000, 0, 2)
        confirmed, changed = tracker.update("1", 5_000_000, 0, 2)

        assert changed is True
        assert confirmed == USAGE_IN_USE

    def test_maintaining_in_use_over_ten_cycles_notifies_once(self):
        from managed_devices import UsageTracker

        tracker = UsageTracker(debounce_cycles=2)
        change_count = 0
        for _ in range(10):
            _, changed = tracker.update("1", 5_000_000, 0, 2)
            if changed:
                change_count += 1

        assert change_count == 1

    def test_return_to_zero_confirms_idle(self):
        from managed_devices import UsageTracker, USAGE_IDLE

        tracker = UsageTracker(debounce_cycles=2)
        tracker.update("1", 5_000_000, 0, 2)
        tracker.update("1", 5_000_000, 0, 2)
        tracker.update("1", 0, 0, 0)
        confirmed, changed = tracker.update("1", 0, 0, 0)

        assert changed is True
        assert confirmed == USAGE_IDLE


class TestUsageEventsAndNotifyIntegration:
    def test_sustained_usage_emits_tplink_in_use_critical(self):
        from events import EventLog

        driver = _FakeDriver(
            metrics_result=RouterMetrics(
                rx_speed_bps=5_000_000, tx_speed_bps=0, clients_total=2
            )
        )
        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, _ = _make_registry(driver=driver, event_log=event_log)

        calls, original = _capture_notify()
        import managed_devices
        from notifier._types import Level

        try:
            registry.get_status("1", force=True)
            registry.get_status("1", force=True)
        finally:
            managed_devices.notify = original

        levels = [c["level"] for c in calls]
        assert Level.CRITICAL in levels
        types = [e["type"] for e in event_log.get_all()]
        assert "tplink_in_use" in types

    def test_saturated_emits_warning(self):
        from events import EventLog
        from managed_devices import CAT4_DOWNLINK_BPS

        driver = _FakeDriver(
            metrics_result=RouterMetrics(
                rx_speed_bps=int(CAT4_DOWNLINK_BPS * 0.9),
                tx_speed_bps=0,
                clients_total=1,
            )
        )
        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, _ = _make_registry(driver=driver, event_log=event_log)

        calls, original = _capture_notify()
        import managed_devices
        from notifier._types import Level

        try:
            registry.get_status("1", force=True)
            registry.get_status("1", force=True)
        finally:
            managed_devices.notify = original

        levels = [c["level"] for c in calls]
        assert Level.WARNING in levels
        assert Level.CRITICAL not in levels


class TestNotificationLevelsC18:
    def test_data_quota_warning_is_warning_out_of_use(self):
        from messages import data_quota_warning
        from notifier._types import Level

        _, level, _ = data_quota_warning("mr110-test", 85.0, in_use=False)
        assert level == Level.WARNING

    def test_data_quota_warning_escalates_to_critical_in_use(self):
        from messages import data_quota_warning
        from notifier._types import Level

        _, level, _ = data_quota_warning("mr110-test", 85.0, in_use=True)
        assert level == Level.CRITICAL

    def test_backup_degraded_escalates_when_in_use(self):
        from messages import backup_degraded
        from notifier._types import Level

        _, level_idle, _ = backup_degraded("mr110-test", "rsrp faible", in_use=False)
        _, level_active, _ = backup_degraded("mr110-test", "rsrp faible", in_use=True)
        assert level_idle == Level.WARNING
        assert level_active == Level.CRITICAL

    def test_tplink_link_down_escalates_when_in_use(self):
        from messages import tplink_link_down
        from notifier._types import Level

        _, level_idle, _ = tplink_link_down("mr110-test", in_use=False)
        _, level_active, _ = tplink_link_down("mr110-test", in_use=True)
        assert level_idle == Level.WARNING
        assert level_active == Level.CRITICAL

    def test_tplink_in_use_is_always_critical(self):
        from messages import tplink_in_use
        from notifier._types import Level

        _, level, _ = tplink_in_use("mr110-test")
        assert level == Level.CRITICAL

    def test_tplink_saturated_is_warning_never_critical(self):
        from messages import tplink_saturated
        from notifier._types import Level

        _, level, _ = tplink_saturated("mr110-test")
        assert level == Level.WARNING

    def test_return_to_normal_events_are_info(self):
        from messages import tplink_link_up, backup_ready, tplink_idle
        from notifier._types import Level

        assert tplink_link_up("x")[1] == Level.INFO
        assert backup_ready("x")[1] == Level.INFO
        assert tplink_idle("x")[1] == Level.INFO

    def test_probe_leak_is_warning(self):
        from messages import tplink_probe_leak
        from notifier._types import Level

        _, level, _ = tplink_probe_leak("mr110-test")
        assert level == Level.WARNING

    def test_hop_failure_is_warning(self):
        from messages import tplink_hop_failed
        from notifier._types import Level

        _, level, _ = tplink_hop_failed("mr110-test", "bridge")
        assert level == Level.WARNING

    def test_split_brain_is_warning(self):
        from messages import tplink_split_brain
        from notifier._types import Level

        _, level, _ = tplink_split_brain("mr110-test")
        assert level == Level.WARNING


class TestPeriodicProbeC11:
    def test_probe_disabled_by_default_never_calls_ssh(self):
        driver = _FakeDriver()
        registry, driver = _make_registry(
            driver=driver, devices=[_make_config(probe_enabled=False)]
        )

        registry.get_status("1", force=True)
        registry.get_status("1", force=True)

        assert driver.probe_calls == 0

    def test_attached_but_probe_fails_marks_link_down(self):
        from events import EventLog

        driver = _FakeDriver(
            readiness_result=RouterReadiness(
                state=Readiness.DEGRADED, reasons=("sonde en echec",)
            ),
            probe_results=[ProbeResult.FAIL],
        )
        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(probe_enabled=True, probe_interval=0)],
            event_log=event_log,
        )

        calls, original = _capture_notify()
        import managed_devices

        try:
            registry.get_status("1", force=True)
        finally:
            managed_devices.notify = original

        types = [e["type"] for e in event_log.get_all()]
        assert "tplink_link_down" in types

    def test_probe_unknown_never_alerts(self):
        from events import EventLog

        driver = _FakeDriver(probe_results=[ProbeResult.UNKNOWN])
        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(probe_enabled=True, probe_interval=0)],
            event_log=event_log,
        )

        calls, original = _capture_notify()
        import managed_devices

        try:
            registry.get_status("1", force=True)
        finally:
            managed_devices.notify = original

        assert len(calls) == 0

    def test_leak_never_blames_the_backup_link(self):
        from events import EventLog

        driver = _FakeDriver(probe_results=[ProbeResult.LEAK])
        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(probe_enabled=True, probe_interval=0)],
            event_log=event_log,
        )

        calls, original = _capture_notify()
        import managed_devices

        try:
            registry.get_status("1", force=True)
        finally:
            managed_devices.notify = original

        assert len(calls) == 1
        types = [e["type"] for e in event_log.get_all()]
        assert "tplink_link_down" not in types

    def test_repeated_probe_failure_over_ten_cycles_notifies_once(self):
        driver = _FakeDriver(probe_results=[ProbeResult.LEAK])
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(probe_enabled=True, probe_interval=0)],
        )

        calls, original = _capture_notify()
        import managed_devices

        try:
            for _ in range(10):
                registry.get_status("1", force=True)
        finally:
            managed_devices.notify = original

        assert len(calls) == 1

    def test_probe_failure_never_triggers_reboot(self):
        driver = _FakeDriver(probe_results=[ProbeResult.FAIL])
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(probe_enabled=True, probe_interval=0)],
        )

        registry.get_status("1", force=True)

        assert driver.reboot_calls == 0


class TestPollerElectionC12PureFunction:
    """Fonction pure de peer.py -- aucune dependance reseau."""

    def test_bridged_reachable_wins_even_with_lower_ha_priority(self):
        from peer import elect_poller

        elected, reason = elect_poller(
            my_priority=2,
            my_mode="bridged",
            my_reachable=True,
            peer_reachable=True,
            peer_priority=1,
            peer_mode="remote",
            threshold_reached_time=0.0,
        )
        assert elected is True

    def test_remote_defers_to_reachable_bridged_peer(self):
        from peer import elect_poller

        elected, reason = elect_poller(
            my_priority=1,
            my_mode="remote",
            my_reachable=True,
            peer_reachable=True,
            peer_priority=2,
            peer_mode="bridged",
            threshold_reached_time=0.0,
        )
        assert elected is False

    def test_bridged_unreachable_lets_remote_take_over_after_delay(self):
        from peer import elect_poller
        from config import PEER_TAKEOVER_DELAY

        now = 10_000.0
        elected, reason = elect_poller(
            my_priority=2,
            my_mode="remote",
            my_reachable=True,
            peer_reachable=False,
            peer_priority=1,
            peer_mode=None,
            threshold_reached_time=now - PEER_TAKEOVER_DELAY - 1,
            now=now,
        )
        assert elected is True

    def test_bridged_unreachable_remote_waits_before_delay_elapsed(self):
        from peer import elect_poller

        now = 10_000.0
        elected, reason = elect_poller(
            my_priority=2,
            my_mode="remote",
            my_reachable=True,
            peer_reachable=False,
            peer_priority=1,
            peer_mode=None,
            threshold_reached_time=now - 5,
            now=now,
        )
        assert elected is False

    def test_remote_without_configured_path_never_falsely_elected(self):
        from peer import elect_poller
        from config import PEER_TAKEOVER_DELAY

        now = 10_000.0
        elected, reason = elect_poller(
            my_priority=1,
            my_mode="remote",
            my_reachable=False,
            peer_reachable=False,
            peer_priority=2,
            peer_mode=None,
            threshold_reached_time=now - PEER_TAKEOVER_DELAY - 100,
            now=now,
        )
        assert elected is False

    def test_no_bridged_instance_falls_back_to_ha_priority(self):
        from peer import elect_poller

        elected_high, _ = elect_poller(
            my_priority=1,
            my_mode="remote",
            my_reachable=True,
            peer_reachable=True,
            peer_priority=2,
            peer_mode="remote",
            threshold_reached_time=0.0,
        )
        elected_low, _ = elect_poller(
            my_priority=2,
            my_mode="remote",
            my_reachable=True,
            peer_reachable=True,
            peer_priority=1,
            peer_mode="remote",
            threshold_reached_time=0.0,
        )
        assert elected_high is True
        assert elected_low is False


class TestSplitBrainC12(object):
    def test_split_brain_detected_when_peer_fresh_after_takeover(self):
        from peer import detect_split_brain
        from state import WatchdogState
        import datetime as _dt

        now = time.time()
        peer_state = WatchdogState(
            timestamp=_dt.datetime.fromtimestamp(now - 5).isoformat()
        )

        assert detect_split_brain(peer_state, took_over=True, now=now) is True

    def test_no_split_brain_when_no_takeover(self):
        from peer import detect_split_brain
        from state import WatchdogState
        import datetime as _dt

        now = time.time()
        peer_state = WatchdogState(
            timestamp=_dt.datetime.fromtimestamp(now - 5).isoformat()
        )

        assert detect_split_brain(peer_state, took_over=False, now=now) is False

    def test_no_split_brain_when_peer_state_stale(self):
        from peer import detect_split_brain
        from state import WatchdogState
        import datetime as _dt

        now = time.time()
        peer_state = WatchdogState(
            timestamp=_dt.datetime.fromtimestamp(now - 10_000).isoformat()
        )

        assert detect_split_brain(peer_state, took_over=True, now=now) is False


class TestPollerElectionC12Integration:
    """Deux instances simulees via un peer HTTP mocke -- `PEER_IP`,
    `peer_mod.query_peer` et `_peer_device_status` sont patches, jamais un
    vrai socket ouvert (meme convention que tests/test_peer.py)."""

    def test_elected_instance_actually_queries_the_driver(self):
        from state import WatchdogState

        peer_payload = {
            "id": "1",
            "label": "mr110-test",
            "reachable": True,
            "mode": "remote",
            "checked_at": time.time(),
        }
        driver = _FakeDriver()
        registry, driver = _make_registry(
            driver=driver, devices=[_make_config(mode="remote")]
        )

        peer_state = WatchdogState(instance_priority=2)
        with (
            mock.patch("managed_devices.PEER_IP", "100.64.1.2"),
            mock.patch("managed_devices.INSTANCE_PRIORITY", 1),
            mock.patch.object(
                type(registry), "_peer_device_status", return_value=peer_payload
            ),
            mock.patch("peer.query_peer", return_value=peer_state),
        ):
            status = registry.get_status("1", force=True)

        assert driver.health_calls == 1
        assert status.get("from_peer") is not True

    def test_non_elected_instance_exposes_from_peer_with_age(self):
        peer_payload = {
            "id": "1",
            "label": "mr110-test",
            "reachable": True,
            "mode": "remote",
            "checked_at": time.time() - 12,
        }
        driver = _FakeDriver()
        registry, driver = _make_registry(
            driver=driver, devices=[_make_config(mode="remote")]
        )

        from state import WatchdogState

        peer_state = WatchdogState(instance_priority=1)
        with (
            mock.patch("managed_devices.PEER_IP", "100.64.1.2"),
            mock.patch("managed_devices.INSTANCE_PRIORITY", 2),
            mock.patch.object(
                type(registry),
                "_peer_device_status",
                return_value=peer_payload,
            ),
            mock.patch("peer.query_peer", return_value=peer_state),
        ):
            status = registry.get_status("1", force=True)

        assert driver.health_calls == 0
        assert status["from_peer"] is True
        assert status["age_seconds"] is not None
        assert status["age_seconds"] > 0

    def test_takeover_resumes_after_peer_takeover_delay(self):
        from config import PEER_TAKEOVER_DELAY

        driver = _FakeDriver()
        registry, driver = _make_registry(
            driver=driver, devices=[_make_config(mode="remote")]
        )
        cfg = registry._configs["1"]

        with (
            mock.patch("managed_devices.PEER_IP", "100.64.1.2"),
            mock.patch("managed_devices.INSTANCE_PRIORITY", 2),
            mock.patch("peer.query_peer", return_value=None),
        ):
            registry._last_reachable["1"] = True

            start = 100_000.0
            elected_immediately, _ = registry._is_elected("1", cfg, now=start)
            assert elected_immediately is False

            still_waiting, _ = registry._is_elected(
                "1", cfg, now=start + PEER_TAKEOVER_DELAY - 1
            )
            assert still_waiting is False

            elected_after_delay, reason = registry._is_elected(
                "1", cfg, now=start + PEER_TAKEOVER_DELAY + 1
            )
            assert elected_after_delay is True
            assert "takeover" in reason

    def test_split_brain_notified_when_peer_fresh_after_takeover(self):
        """Scenario reel (pas un appel isole) : (a) le peer est injoignable
        depuis plus de PEER_TAKEOVER_DELAY -- ce qui fait _peer_unreachable_since
        > 0 et elected=True via la branche takeover d'elect_poller ; (b) au
        cycle suivant le peer redevient joignable et rapporte un
        WatchdogState frais (< CHECK_INTERVAL*3) -- c'est ce second appel qui
        doit signaler le split-brain (C12).

        Bug corrige : `_is_elected` capture desormais `was_unreachable_since`
        AVANT que ce meme appel ne remette `_peer_unreachable_since` a zero
        via `_track_peer_unreachable` (qui renvoie 0.0 des que le peer est de
        nouveau joignable POUR CET APPEL). Le garde split-brain n'exige plus
        `"takeover" in reason` -- condition auparavant inatteignable, puisque
        le peer ne peut pas etre a la fois injoignable pour
        `threshold_reached_time > 0` et joignable pour `peer_ws is not None`
        dans le meme appel. `was_unreachable_since > 0` (capture pre-clear)
        suffit desormais a cibler precisement le seul appel de transition, et
        la notification split-brain (b) se declenche bien."""
        from events import EventLog
        from state import WatchdogState
        from config import PEER_TAKEOVER_DELAY
        import datetime as _dt

        driver = _FakeDriver()
        event_log = EventLog(max_events=10, persist_path="/dev/null")
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(mode="remote")],
            event_log=event_log,
        )
        cfg = registry._configs["1"]

        start = 200_000.0
        calls, original = _capture_notify()
        import managed_devices

        try:
            with (
                mock.patch("managed_devices.PEER_IP", "100.64.1.2"),
                mock.patch("managed_devices.INSTANCE_PRIORITY", 1),
                mock.patch("peer.query_peer", return_value=None),
            ):
                registry._last_reachable["1"] = True
                # (a) peer injoignable depuis plus que PEER_TAKEOVER_DELAY --
                # deux appels reels (pas d'ecriture directe de l'etat interne)
                # pour reproduire un cycle qui a d'abord constate la coupure
                # puis, plus tard, franchi le delai de reprise.
                not_yet_elected, _ = registry._is_elected("1", cfg, now=start)
                assert not_yet_elected is False
                took_over, takeover_reason = registry._is_elected(
                    "1", cfg, now=start + PEER_TAKEOVER_DELAY + 1
                )
                assert took_over is True
                assert "takeover" in takeover_reason

            # (b) le peer redevient joignable au cycle suivant, avec un
            # WatchdogState frais (< CHECK_INTERVAL*3).
            now_recovered = start + PEER_TAKEOVER_DELAY + 2
            fresh_peer_state = WatchdogState(
                instance_priority=2,
                timestamp=_dt.datetime.fromtimestamp(now_recovered - 5).isoformat(),
            )
            peer_payload = {
                "id": "1",
                "label": "mr110-test",
                "reachable": True,
                "mode": "remote",
                "checked_at": now_recovered,
            }
            with (
                mock.patch("managed_devices.PEER_IP", "100.64.1.2"),
                mock.patch("managed_devices.INSTANCE_PRIORITY", 1),
                mock.patch.object(
                    type(registry), "_peer_device_status", return_value=peer_payload
                ),
                mock.patch("peer.query_peer", return_value=fresh_peer_state),
            ):
                elected, _ = registry._is_elected("1", cfg, now=now_recovered)
        finally:
            managed_devices.notify = original

        assert elected is True
        types = [e["type"] for e in event_log.get_all()]
        assert "tplink_split_brain" in types
        assert len(calls) == 1

    def test_no_split_brain_over_dozens_of_healthy_cycles(self):
        """Non-regression du bug corrige (C12) : une election normale et
        saine -- peer TOUJOURS joignable, jamais marque injoignable -- ne
        doit JAMAIS declencher tplink_split_brain, meme sur des dizaines de
        cycles consecutifs. C'est exactement le faux-positif qui se
        declenchait a chaque election avant le correctif (condition trop
        laxiste `elected and peer_ws is not None`)."""
        from events import EventLog
        from state import WatchdogState

        driver = _FakeDriver()
        event_log = EventLog(max_events=200, persist_path="/dev/null")
        registry, driver = _make_registry(
            driver=driver,
            devices=[_make_config(mode="remote")],
            event_log=event_log,
        )
        cfg = registry._configs["1"]

        start = 300_000.0
        peer_state = WatchdogState(instance_priority=2)
        peer_payload = {
            "id": "1",
            "label": "mr110-test",
            "reachable": True,
            "mode": "remote",
            "checked_at": start,
        }

        calls, original = _capture_notify()
        import managed_devices

        try:
            with (
                mock.patch("managed_devices.PEER_IP", "100.64.1.2"),
                mock.patch("managed_devices.INSTANCE_PRIORITY", 1),
                mock.patch.object(
                    type(registry), "_peer_device_status", return_value=peer_payload
                ),
                mock.patch("peer.query_peer", return_value=peer_state),
            ):
                registry._last_reachable["1"] = True
                for cycle in range(50):
                    elected, reason = registry._is_elected(
                        "1", cfg, now=start + cycle * 30
                    )
                    assert elected is True
                    assert "takeover" not in reason
        finally:
            managed_devices.notify = original

        types = [e["type"] for e in event_log.get_all()]
        assert "tplink_split_brain" not in types
        assert len(calls) == 0
