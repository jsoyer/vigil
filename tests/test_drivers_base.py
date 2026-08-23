"""Tests for src/drivers/_base.py -- contrat RouterDriver.

Couvre l'invariant C1 (import vendor paresseux, voir INVARIANTS.md) et le
contrat pose au Sprint 1 : enums, dataclasses frozen avec defauts
conservateurs, et conformite structurelle d'un driver factice au Protocol
`RouterDriver`.
"""

import dataclasses
import sys

import pytest

from src.drivers import (
    Hop,
    Readiness,
    RouterDriver,
    RouterHealth,
    RouterMetrics,
    RouterReadiness,
    RouterRole,
)


class TestImportVendorParesseux:
    """Invariant C1 -- import vendor paresseux."""

    def test_import_drivers_sans_lib_vendor(self):
        """`import drivers` doit reussir meme si tplinkrouterc6u n'est pas
        installe, et ne doit jamais tirer la lib au niveau module."""
        assert "tplinkrouterc6u" not in sys.modules

        import drivers  # noqa: F401

        assert "tplinkrouterc6u" not in sys.modules

    def test_import_base_directement_sans_lib_vendor(self):
        assert "tplinkrouterc6u" not in sys.modules

        from src.drivers import _base  # noqa: F401

        assert "tplinkrouterc6u" not in sys.modules


class TestEnums:
    def test_router_role_valeurs(self):
        assert RouterRole.PRIMARY.value == "primary"
        assert RouterRole.BACKUP.value == "backup"

    def test_readiness_valeurs(self):
        assert Readiness.OK.value == "ok"
        assert Readiness.DEGRADED.value == "degraded"
        assert Readiness.UNKNOWN.value == "unknown"

    def test_hop_valeurs(self):
        assert Hop.BRIDGE.value == "bridge"
        assert Hop.WIRELESS.value == "wireless"
        assert Hop.DEVICE.value == "device"
        assert Hop.ROUTE.value == "route"


class TestRouterHealthFrozen:
    def test_construction(self):
        health = RouterHealth(reachable=True, internet_ok=True, rtt_ms=12.5)
        assert health.reachable is True
        assert health.internet_ok is True
        assert health.rtt_ms == 12.5
        assert health.failed_hop is None
        assert health.detail == ""

    def test_immutable(self):
        health = RouterHealth(reachable=False, internet_ok=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            health.reachable = True  # type: ignore[misc]

    def test_failed_hop_attribuable(self):
        health = RouterHealth(
            reachable=False,
            internet_ok=False,
            failed_hop=Hop.BRIDGE,
            detail="Pi Zero injoignable",
        )
        assert health.failed_hop is Hop.BRIDGE


class TestRouterReadinessFrozen:
    def test_defaut_conservateur_unknown(self):
        """Une readiness sans argument doit etre UNKNOWN, jamais OK par defaut."""
        readiness = RouterReadiness()
        assert readiness.state is Readiness.UNKNOWN
        assert readiness.reasons == ()

    def test_immutable(self):
        readiness = RouterReadiness(state=Readiness.OK)
        with pytest.raises(dataclasses.FrozenInstanceError):
            readiness.state = Readiness.DEGRADED  # type: ignore[misc]

    def test_reasons_chiffrees(self):
        readiness = RouterReadiness(
            state=Readiness.DEGRADED,
            reasons=("rsrp=-118 < seuil -110",),
        )
        assert readiness.reasons == ("rsrp=-118 < seuil -110",)


class TestRouterMetricsFrozen:
    def test_tous_les_champs_sont_none_par_defaut(self):
        metrics = RouterMetrics()
        for field in dataclasses.fields(metrics):
            assert getattr(metrics, field.name) is None, (
                f"{field.name} devrait etre None par defaut"
            )

    def test_champs_attendus_presents(self):
        noms = {f.name for f in dataclasses.fields(RouterMetrics)}
        assert noms == {
            "cpu_usage",
            "mem_usage",
            "wan_ip",
            "clients_total",
            "network_type",
            "sim_status",
            "signal_bars",
            "rsrp",
            "rsrq",
            "snr",
            "isp_name",
            "data_used_bytes",
            "rx_speed_bps",
            "tx_speed_bps",
        }

    def test_immutable(self):
        metrics = RouterMetrics(rsrp=-95)
        with pytest.raises(dataclasses.FrozenInstanceError):
            metrics.rsrp = -80  # type: ignore[misc]


class _FakeDriver:
    """Driver factice minimal, ne parle a aucun vendor reel."""

    vendor = "fake"

    def health(self) -> RouterHealth:
        return RouterHealth(reachable=True, internet_ok=True)

    def metrics(self) -> RouterMetrics:
        return RouterMetrics()

    def readiness(self) -> RouterReadiness:
        return RouterReadiness()

    def reboot(self) -> bool:
        return False

    def test_connection(self) -> bool:
        return True


class _IncompleteDriver:
    """Ne satisfait pas le contrat -- il manque reboot() et test_connection()."""

    vendor = "incomplete"

    def health(self) -> RouterHealth:
        return RouterHealth(reachable=False, internet_ok=False)

    def metrics(self) -> RouterMetrics:
        return RouterMetrics()

    def readiness(self) -> RouterReadiness:
        return RouterReadiness()


class TestRouterDriverProtocol:
    def test_driver_factice_satisfait_le_contrat(self):
        """Structural typing : aucune heritage explicite requise."""
        driver: RouterDriver = _FakeDriver()
        assert isinstance(driver, RouterDriver)

    def test_driver_incomplet_ne_satisfait_pas_le_contrat(self):
        assert not isinstance(_IncompleteDriver(), RouterDriver)

    def test_driver_factice_ne_leve_jamais(self):
        driver = _FakeDriver()
        assert driver.health().reachable is True
        assert driver.metrics() == RouterMetrics()
        assert driver.readiness().state is Readiness.UNKNOWN
        assert driver.reboot() is False
        assert driver.test_connection() is True
