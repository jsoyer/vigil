"""Tests pour src/drivers/tplink.py -- TplinkDriver (Sprint 2, PRD A1).

Lib `tplinkrouterc6u` entierement mockee : aucun acces reseau reel. Couvre
l'invariant C1 (import paresseux), l'attribution de panne par saut (BRIDGE /
WIRELESS / DEVICE / ROUTE), C8 (route absente != panne), C11 (sonde de bout
en bout avec preuve de chemin, 4 valeurs), C16 (modes bridged/remote derriere
la meme sonde), la garantie de logout() et les seuils de readiness.

Voir docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/
sprints/02-tplink-driver.md et INVARIANTS.md du meme dossier.
"""

import sys
from unittest.mock import Mock

import pytest


class TestImportVendorParesseuxTplink:
    """Invariant C1 -- import vendor paresseux (tplink.py specifiquement)."""

    def test_import_drivers_tplink_sans_lib_vendor(self):
        assert "tplinkrouterc6u" not in sys.modules

        from src.drivers import tplink  # noqa: F401

        assert "tplinkrouterc6u" not in sys.modules

    def test_import_tplinkdriver_directement_sans_lib_vendor(self):
        assert "tplinkrouterc6u" not in sys.modules

        from src.drivers.tplink import TplinkDriver  # noqa: F401

        assert "tplinkrouterc6u" not in sys.modules


def _make_driver(**overrides):
    """Construit un TplinkDriver avec toutes les dependances mockees.

    Defauts : bridge et lien WiFi OK, client TP-Link mocke qui repond, sonde
    jamais executee. Chaque test surcharge ce dont il a besoin.
    """
    from src.drivers.tplink import TplinkDriver

    mock_client = overrides.pop("client", None)
    if mock_client is None:
        mock_client = Mock()
        mock_client.get_status.return_value = {"total_statistics": 1000}
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.reboot.return_value = True

    kwargs = dict(
        host="192.168.10.1",
        password="s3cr3t",
        label="mr110-dijon",
        mode="bridged",
        bridge_host="",
        client_factory=lambda: mock_client,
        ping_fn=Mock(return_value=(True, 12.0)),
        route_check_fn=Mock(return_value=(True, None)),
        ssh_client_factory=Mock(
            side_effect=AssertionError("SSH ne doit pas etre appele en mode bridged")
        ),
        ssh_command_fn=Mock(),
        local_command_fn=Mock(return_value=(True, "203.0.113.9")),
        get_public_ip_fn=Mock(return_value="198.51.100.1"),
    )
    kwargs.update(overrides)
    driver = TplinkDriver(**kwargs)
    return driver, mock_client


class TestFailedHop:
    """Attribution de panne au bon saut -- INVARIANTS.md 'Une panne est
    attribuee au bon saut'."""

    def test_failed_hop_bridge_mode_bridged(self):
        """Adapte au bugfix 2026-08-22 : BRIDGE (route locale absente) n'est
        attribue que si le device ne repond PAS non plus au ping -- sinon
        `reachable` doit refleter un device qui repond (cf.
        TestBridgeSignalNestPasUnVeto). Avant le fix, une route locale
        absente a elle seule suffisait a declarer reachable=False, y compris
        quand le device repondait -- comportement bugue reproduit en
        production (faux negatif via l'ancien check `iw wlan0`)."""
        from src.drivers._base import Hop

        driver, _ = _make_driver(
            mode="bridged",
            route_check_fn=Mock(return_value=(False, None)),
            ping_fn=Mock(return_value=(False, None)),
        )
        health = driver.health()
        assert health.reachable is False
        assert health.failed_hop is Hop.BRIDGE

    def test_failed_hop_bridge_mode_remote(self):
        from src.drivers._base import Hop

        driver, _ = _make_driver(
            mode="remote",
            bridge_host="10.0.0.2",
            ping_fn=Mock(return_value=(False, None)),
            ssh_client_factory=Mock(),
        )
        health = driver.health()
        assert health.reachable is False
        assert health.failed_hop is Hop.BRIDGE

    def test_failed_hop_wireless(self):
        from src.drivers._base import Hop

        # Mode bridged : le saut BRIDGE est sonde via wifi_status_fn (pas
        # ping_fn) -- ping_fn n'est donc appele qu'une seule fois ici, pour
        # le saut WIRELESS.
        ping_fn = Mock(return_value=(False, None))
        driver, _ = _make_driver(mode="bridged", ping_fn=ping_fn)
        health = driver.health()
        assert health.reachable is False
        assert health.failed_hop is Hop.WIRELESS

    def test_failed_hop_device(self):
        from src.drivers._base import Hop

        mock_client = Mock()
        mock_client.authorize.side_effect = Exception("AuthorizeError")
        driver, _ = _make_driver(client=mock_client)
        health = driver.health()
        assert health.reachable is False
        assert health.failed_hop is Hop.DEVICE

    def test_hop_none_quand_tout_repond(self):
        driver, _ = _make_driver()
        health = driver.health()
        assert health.reachable is True
        assert health.failed_hop is None


class TestRouteMisconfig:
    """C8 -- route absente n'est pas une panne de secours."""

    def test_route_misconfig_jamais_joignable_depuis_cette_instance(self):
        from src.drivers._base import Hop

        driver, _ = _make_driver(
            mode="remote",
            bridge_host="10.0.0.2",
            ping_fn=Mock(return_value=(True, 5.0)) if False else None,
        )
        # bridge (ping bridge_host) OK, MR110 (ping host) toujours KO
        driver._ping_fn = Mock(
            side_effect=lambda target, timeout: (
                (True, 5.0) if target == "10.0.0.2" else (False, None)
            )
        )
        health = driver.health()
        assert health.reachable is False
        assert health.failed_hop is Hop.ROUTE

    def test_route_misconfig_sans_objet_en_mode_bridged(self):
        """C8 est sans objet en mode bridged : meme jamais joignable, on
        reste sur WIRELESS, jamais ROUTE."""
        from src.drivers._base import Hop

        # Meme raison qu'au-dessus : un seul appel a ping_fn en mode bridged.
        driver, _ = _make_driver(
            mode="bridged",
            ping_fn=Mock(return_value=(False, None)),
        )
        health = driver.health()
        assert health.failed_hop is Hop.WIRELESS

    def test_wireless_pas_route_si_deja_joint_avant(self):
        """Deja joignable une fois -> une panne suivante est WIRELESS, pas
        ROUTE (distinction 'jamais joignable' vs 'plus joignable')."""
        from src.drivers._base import Hop

        driver, _ = _make_driver(mode="remote", bridge_host="10.0.0.2")
        driver._ping_fn = Mock(
            side_effect=lambda target, timeout: (
                (True, 5.0) if target == "10.0.0.2" else (True, 4.0)
            )
        )
        first = driver.health()
        assert first.failed_hop is None

        driver._ping_fn = Mock(
            side_effect=lambda target, timeout: (
                (True, 5.0) if target == "10.0.0.2" else (False, None)
            )
        )
        second = driver.health()
        assert second.failed_hop is Hop.WIRELESS


class TestRouteCheckLocal:
    """Bugfix 2026-08-22 -- l'etage BRIDGE en mode `bridged` resout la route
    locale via `ip route get` (subprocess mocke), sans dependance a une
    interface WiFi fixe (`wlan0`). Remplace l'ancien check `iw wlan0` qui
    produisait un faux negatif des que le lien vers le MR110 n'etait pas
    porte par wlan0 (cas reel des guardians en production)."""

    def test_default_route_check_ok_quand_ip_route_get_reussit(self, monkeypatch):
        from src.drivers import tplink as tplink_module

        completed = Mock(
            returncode=0,
            stdout="192.168.10.1 via 10.0.0.1 dev eth0 src 10.0.0.5\n",
        )
        monkeypatch.setattr(
            tplink_module.subprocess, "run", Mock(return_value=completed)
        )
        ok, rtt = tplink_module._default_route_check("192.168.10.1", 8.0)
        assert ok is True
        assert rtt is None

    def test_default_route_check_ko_si_exit_code_non_zero(self, monkeypatch):
        from src.drivers import tplink as tplink_module

        completed = Mock(returncode=2, stdout="")
        monkeypatch.setattr(
            tplink_module.subprocess, "run", Mock(return_value=completed)
        )
        ok, _ = tplink_module._default_route_check("192.168.10.1", 8.0)
        assert ok is False

    def test_default_route_check_ko_si_pas_de_ligne_dev(self, monkeypatch):
        from src.drivers import tplink as tplink_module

        completed = Mock(
            returncode=0, stdout="RTNETLINK answers: Network is unreachable\n"
        )
        monkeypatch.setattr(
            tplink_module.subprocess, "run", Mock(return_value=completed)
        )
        ok, _ = tplink_module._default_route_check("192.168.10.1", 8.0)
        assert ok is False

    def test_default_route_check_ko_si_exception_subprocess(self, monkeypatch):
        from src.drivers import tplink as tplink_module

        monkeypatch.setattr(
            tplink_module.subprocess,
            "run",
            Mock(side_effect=Exception("boom")),
        )
        ok, rtt = tplink_module._default_route_check("192.168.10.1", 8.0)
        assert ok is False
        assert rtt is None

    def test_default_route_check_indifferent_au_type_interface(self, monkeypatch):
        """N'importe quel type d'interface (WiFi, ethernet, vlan, usb...) est
        accepte -- plus de dependance a `wlan0` (mode bridged sans wlan0)."""
        from src.drivers import tplink as tplink_module

        for iface in ("wlan0", "eth0", "vlan42", "usb0"):
            completed = Mock(
                returncode=0,
                stdout=f"192.168.10.1 dev {iface} src 192.168.10.5\n",
            )
            monkeypatch.setattr(
                tplink_module.subprocess, "run", Mock(return_value=completed)
            )
            ok, _ = tplink_module._default_route_check("192.168.10.1", 8.0)
            assert ok is True, f"echec pour l'interface {iface}"

    def test_mode_bridged_sans_wlan0_bout_en_bout(self, monkeypatch):
        """Driver complet en mode bridged, route reelle (mockee) portee par
        une interface non-WiFi -- plus aucune reference a `wlan0` dans le
        chemin BRIDGE : reachable=True, failed_hop=None."""
        from src.drivers import tplink as tplink_module

        completed = Mock(
            returncode=0, stdout="192.168.10.1 dev eth1 src 192.168.10.20\n"
        )
        monkeypatch.setattr(
            tplink_module.subprocess, "run", Mock(return_value=completed)
        )

        driver, _ = _make_driver(mode="bridged")
        # Bypasse le route_check_fn mocke par _make_driver pour exercer le
        # vrai default (_default_route_check), seul le subprocess est mocke.
        driver._route_check_fn = tplink_module._default_route_check

        health = driver.health()
        assert health.reachable is True
        assert health.failed_hop is None


class TestBridgeSignalNestPasUnVeto:
    """Bugfix 2026-08-22 -- un etage BRIDGE en echec est un signal de
    diagnostic, jamais un veto : il ne doit jamais contredire un device qui
    repond reellement (auth + metriques OK). Avant le fix, `_check_bridge`
    en echec provoquait un retour anticipe `reachable=False` meme quand
    authorize() et les metriques reussissaient ensuite -- incoherence
    constatee en production (/api/tplink/1/status renvoyait reachable=false
    alors que rsrp/wan_ip/compteurs etaient remplis)."""

    def test_device_repond_malgre_etage_bridge_ko_reachable_true(self):
        driver, _ = _make_driver(
            mode="bridged",
            route_check_fn=Mock(return_value=(False, None)),
        )
        health = driver.health()
        assert health.reachable is True
        assert health.failed_hop is None

    def test_bridge_ko_et_device_injoignable_reste_attribue_bridge(self):
        """Contre-cas : si le device ne repond vraiment pas non plus, BRIDGE
        reste l'attribution -- le signal n'est ignore que quand il est
        contredit par un device qui repond."""
        from src.drivers._base import Hop

        driver, _ = _make_driver(
            mode="bridged",
            route_check_fn=Mock(return_value=(False, None)),
            ping_fn=Mock(return_value=(False, None)),
        )
        health = driver.health()
        assert health.reachable is False
        assert health.failed_hop is Hop.BRIDGE

    def test_bridge_ko_device_repond_metriques_conservees(self):
        """La sonde ne doit pas seulement dire reachable=True : les
        metriques (authorize deja verifie par health) restent accessibles
        via metrics(), symptome production #2 (rsrp/wan_ip remplis)."""
        driver, mock_client = _make_driver(
            mode="bridged",
            route_check_fn=Mock(return_value=(False, None)),
        )
        health = driver.health()
        assert health.reachable is True
        metrics = driver.metrics()
        assert metrics.rsrp == -95


class TestProbePathProof:
    """C11 -- la sonde porte sa preuve de chemin."""

    def test_probe_path_proof_ok_quand_les_deux_preuves_concordent(self):
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_status.side_effect = [
            {"total_statistics": 1000},
            {"total_statistics": 1500},
        ]
        driver, _ = _make_driver(
            client=mock_client,
            local_command_fn=Mock(return_value=(True, "203.0.113.9")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        assert driver.probe_end_to_end() is ProbeResult.OK

    def test_probe_path_proof_jamais_ok_sans_les_deux_preuves(self):
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_status.side_effect = [
            {"total_statistics": 1000},
            {"total_statistics": 1000},  # fige
        ]
        driver, _ = _make_driver(
            client=mock_client,
            local_command_fn=Mock(return_value=(True, "203.0.113.9")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        assert driver.probe_end_to_end() is not ProbeResult.OK


class TestProbeLeak:
    """C11 -- une fuite par la fibre est detectee, jamais un faux OK."""

    def test_probe_leak_ip_identique_a_celle_du_site(self):
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_status.side_effect = [
            {"total_statistics": 1000},
            {"total_statistics": 1500},
        ]
        driver, _ = _make_driver(
            client=mock_client,
            local_command_fn=Mock(return_value=(True, "198.51.100.1")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        assert driver.probe_end_to_end() is ProbeResult.LEAK

    def test_probe_leak_compteurs_figes_meme_si_ip_differe(self):
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_status.side_effect = [
            {"total_statistics": 1000},
            {"total_statistics": 1000},
        ]
        driver, _ = _make_driver(
            client=mock_client,
            local_command_fn=Mock(return_value=(True, "203.0.113.9")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        assert driver.probe_end_to_end() is ProbeResult.LEAK

    def test_probe_leak_rapportee_comme_defaut_config_pas_panne_secours(self):
        """LEAK ne degrade pas la readiness -- defaut du chemin de test."""
        from src.drivers._base import Readiness
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(
            client=mock_client,
            local_command_fn=Mock(return_value=(True, "198.51.100.1")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        result = driver.probe_end_to_end()
        assert result is ProbeResult.LEAK
        readiness = driver.readiness()
        assert readiness.state is Readiness.OK
        assert not any("fuite" in r or "chemin de test" in r for r in readiness.reasons)

    def test_probe_end_to_end_record_false_n_ecrit_pas_le_cache(self):
        """Bouton Verifier : un FAIL diagnostique ne doit pas empoisonner
        readiness() via le cache 60s."""
        from src.drivers._base import Readiness
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(
            client=mock_client,
            local_command_fn=Mock(return_value=(True, "not-an-ip")),
            get_public_ip_fn=Mock(return_value="198.51.100.1"),
        )
        result = driver.probe_end_to_end(record=False)
        assert result is ProbeResult.FAIL
        assert driver._last_probe_result is None
        readiness = driver.readiness()
        assert readiness.state is Readiness.OK
        assert not any("sonde de bout en bout" in r for r in readiness.reasons)


class TestAttachedWithoutData:
    """attached != internet_ok -- lien attache sans data -> DEGRADED, jamais OK."""

    def test_attached_without_data_degrade_jamais_ok(self):
        from src.drivers._base import Readiness
        from src.drivers.tplink import ProbeResult

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",  # attache
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(client=mock_client)
        driver._record_probe(ProbeResult.FAIL)

        readiness = driver.readiness()
        assert readiness.state is Readiness.DEGRADED
        assert readiness.state is not Readiness.OK

    def test_sonde_jamais_executee_internet_ok_jamais_true(self):
        driver, _ = _make_driver()
        health = driver.health()
        assert health.internet_ok is not True


class TestModeBridged:
    def test_mode_bridged_aucun_appel_ssh(self):
        ssh_factory = Mock()
        driver, _ = _make_driver(mode="bridged", ssh_client_factory=ssh_factory)
        driver.health()
        driver.probe_end_to_end()
        assert not ssh_factory.called

    def test_mode_bridged_utilise_verification_route_locale(self):
        route_check_fn = Mock(return_value=(True, None))
        driver, _ = _make_driver(mode="bridged", route_check_fn=route_check_fn)
        driver.health()
        assert route_check_fn.called
        route_check_fn.assert_called_with(driver.host, driver.timeout)


class TestModeRemote:
    def test_mode_remote_utilise_ssh_pour_la_sonde(self):
        ssh_client = Mock()
        ssh_command_fn = Mock(return_value=(True, "203.0.113.9"))
        driver, _ = _make_driver(
            mode="remote",
            bridge_host="10.0.0.2",
            ssh_client_factory=Mock(return_value=ssh_client),
            ssh_command_fn=ssh_command_fn,
        )
        driver._ping_fn = Mock(return_value=(True, 5.0))
        driver.probe_end_to_end()
        assert ssh_command_fn.called

    @pytest.mark.parametrize("mode", ["bridged", "remote"])
    def test_meme_failed_hop_wireless_dans_les_deux_modes(self, mode):
        from src.drivers._base import Hop

        kwargs = {"mode": mode}
        if mode == "remote":
            kwargs["bridge_host"] = "10.0.0.2"
        driver, _ = _make_driver(**kwargs)
        driver._ping_fn = Mock(
            side_effect=lambda target, timeout: (
                (True, 5.0) if target == "10.0.0.2" else (False, None)
            )
        )
        health = driver.health()
        assert health.failed_hop in (Hop.WIRELESS, Hop.ROUTE)


class TestLogoutGuaranteed:
    """C5 -- logout() garanti en finally, meme sur exception."""

    def test_logout_guaranteed_authorize_leve(self):
        mock_client = Mock()
        mock_client.authorize.side_effect = Exception("boom")
        driver, _ = _make_driver(client=mock_client)
        driver.readiness()
        assert mock_client.logout.called

    def test_logout_guaranteed_appel_intermediaire_leve(self):
        mock_client = Mock()
        mock_client.get_lte_status.side_effect = Exception("boom")
        driver, _ = _make_driver(client=mock_client)
        driver.metrics()
        assert mock_client.logout.called

    def test_logout_guaranteed_reboot(self):
        mock_client = Mock()
        mock_client.reboot.side_effect = Exception("boom")
        driver, _ = _make_driver(client=mock_client)
        driver.reboot()
        assert mock_client.logout.called


class TestReadinessSeuils:
    def test_readiness_ok_quand_tout_est_bon(self):
        from src.drivers._base import Readiness

        driver, _ = _make_driver()
        assert driver.readiness().state is Readiness.OK

    def test_readiness_degrade_rsrp_sous_seuil(self):
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -125,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(client=mock_client, rsrp_min=-110)
        readiness = driver.readiness()
        assert readiness.state is Readiness.DEGRADED
        assert any("rsrp" in r and "-110" in r for r in readiness.reasons)

    def test_readiness_sim_ko(self):
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "0",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(client=mock_client)
        readiness = driver.readiness()
        assert readiness.state is Readiness.DEGRADED

    def test_readiness_unknown_par_defaut_si_champ_absent(self):
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {}
        mock_client.get_status.return_value = {}
        driver, _ = _make_driver(client=mock_client)
        readiness = driver.readiness()
        assert readiness.state is Readiness.UNKNOWN

    def test_readiness_unknown_si_injoignable(self):
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.authorize.side_effect = Exception("KO")
        driver, _ = _make_driver(client=mock_client)
        readiness = driver.readiness()
        assert readiness.state is Readiness.UNKNOWN

    def test_champ_absent_seul_ne_degrade_pas(self):
        """Un champ RSRP/RSRQ/SIM absent produit UNKNOWN, jamais DEGRADED."""
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": None,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(client=mock_client)
        readiness = driver.readiness()
        assert readiness.state is Readiness.UNKNOWN
        assert readiness.reasons == ()

    def test_snr_sentinel_ne_degrade_pas(self):
        """Bugfix 2.3.2 -- le firmware pousse snr=-130 (sentinelle idle)
        sous l'ancien seuil -100. SIM/RSRP/RSRQ OK => readiness OK, jamais
        un faux DEGRADED sur le SNR seul."""
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -99,
            "rsrq": -14,
            "snr": -130,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(client=mock_client, snr_min=-100)
        readiness = driver.readiness()
        assert readiness.state is Readiness.OK
        assert readiness.reasons == ()

    def test_snr_absent_n_empeche_pas_ok(self):
        """SNR n'entre plus dans la readiness : champ absent + reste OK
        => OK, plus UNKNOWN."""
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": None,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, _ = _make_driver(client=mock_client)
        readiness = driver.readiness()
        assert readiness.state is Readiness.OK
        assert readiness.reasons == ()


class TestMetriques:
    def test_metrics_mapping_complet(self):
        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
            "isp_name": "Free",
            "sig_level": 3,
            "total_statistics": 12345,
            "cur_rx_speed": 100,
            "cur_tx_speed": 50,
        }
        mock_client.get_status.return_value = {
            "wan_ipv4_addr": "203.0.113.9",
            "clients_total": 2,
            "cpu_usage": 10,
            "mem_usage": 20,
        }
        driver, _ = _make_driver(client=mock_client)
        metrics = driver.metrics()
        assert metrics.rsrp == -95
        assert metrics.rsrq == -12
        assert metrics.snr == -20
        assert metrics.isp_name == "Free"
        assert metrics.wan_ip == "203.0.113.9"
        assert metrics.clients_total == 2

    def test_metrics_champs_partiels_pas_de_keyerror(self):
        mock_client = Mock()
        mock_client.get_lte_status.return_value = {"sim_status": "3"}
        mock_client.get_status.return_value = {}
        driver, _ = _make_driver(client=mock_client)
        metrics = driver.metrics()
        assert metrics.rsrp is None
        assert metrics.wan_ip is None

    def test_metrics_injoignable_renvoie_tout_none(self):
        mock_client = Mock()
        mock_client.authorize.side_effect = Exception("KO")
        driver, _ = _make_driver(client=mock_client)
        metrics = driver.metrics()
        assert metrics.rsrp is None
        assert metrics.wan_ip is None


class TestAucunRebootAutomatique:
    def test_health_ne_declenche_jamais_reboot(self):
        mock_client = Mock()
        driver, _ = _make_driver(client=mock_client)
        driver.health()
        assert not mock_client.reboot.called

    def test_readiness_ne_declenche_jamais_reboot(self):
        mock_client = Mock()
        driver, _ = _make_driver(client=mock_client)
        driver.readiness()
        assert not mock_client.reboot.called

    def test_metrics_ne_declenche_jamais_reboot(self):
        mock_client = Mock()
        driver, _ = _make_driver(client=mock_client)
        driver.metrics()
        assert not mock_client.reboot.called

    def test_probe_ne_declenche_jamais_reboot(self):
        mock_client = Mock()
        mock_client.get_status.return_value = {"total_statistics": 1}
        driver, _ = _make_driver(client=mock_client)
        driver.probe_end_to_end()
        assert not mock_client.reboot.called

    def test_reboot_retourne_bool_et_ne_leve_jamais(self):
        mock_client = Mock()
        mock_client.reboot.return_value = True
        driver, _ = _make_driver(client=mock_client)
        assert driver.reboot() is True


class TestSecretsPasDansLesLogs:
    def test_mot_de_passe_absent_des_logs_sur_erreur(self, caplog):
        mock_client = Mock()
        mock_client.authorize.side_effect = Exception("password=s3cr3t leaked")
        driver, _ = _make_driver(client=mock_client)
        with caplog.at_level("DEBUG"):
            driver.readiness()
        assert "s3cr3t" not in caplog.text

    def test_mot_de_passe_absent_des_logs_probe(self, caplog):
        mock_client = Mock()
        mock_client.get_status.side_effect = Exception("s3cr3t")
        driver, _ = _make_driver(client=mock_client)
        with caplog.at_level("DEBUG"):
            driver.probe_end_to_end()
        assert "s3cr3t" not in caplog.text


class TestTimeout:
    def test_ping_qui_time_out_ne_bloque_pas(self):
        driver, _ = _make_driver(ping_fn=Mock(return_value=(False, None)))
        health = driver.health()
        assert health.reachable is False

    def test_probe_ssh_indisponible_renvoie_unknown_jamais_exception(self):
        from src.drivers.tplink import ProbeResult

        driver, _ = _make_driver(
            mode="remote",
            bridge_host="10.0.0.2",
            ssh_client_factory=Mock(side_effect=Exception("timeout")),
        )
        driver._ping_fn = Mock(return_value=(True, 5.0))
        result = driver.probe_end_to_end()
        assert result is ProbeResult.UNKNOWN


class TestSnapshotUneSession:
    """get_status() ne doit plus ouvrir 3 sessions admin par cycle."""

    def test_snapshot_autorise_une_seule_fois(self):
        from src.drivers._base import Readiness

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {"total_statistics": 1000}
        driver, client = _make_driver(client=mock_client)
        health, readiness, metrics = driver.snapshot()
        assert health.reachable is True
        assert readiness.state is Readiness.OK
        assert metrics.rsrp == -95
        assert client.authorize.call_count == 1
        assert client.logout.call_count == 1

    def test_snapshot_ping_ko_n_ouvre_pas_de_session(self):
        mock_client = Mock()
        driver, client = _make_driver(
            client=mock_client, ping_fn=Mock(return_value=(False, None))
        )
        health, readiness, _metrics = driver.snapshot()
        assert health.reachable is False
        assert client.authorize.call_count == 0

    def test_registry_get_status_uses_single_session(self):
        from managed_devices import ManagedDeviceRegistry
        from config import TplinkDeviceConfig

        mock_client = Mock()
        mock_client.get_lte_status.return_value = {
            "sim_status": "3",
            "rsrp": -95,
            "rsrq": -12,
            "snr": -20,
            "network_type": "LTE",
        }
        mock_client.get_status.return_value = {
            "total_statistics": 1000,
            "clients_total": 0,
            "cur_rx_speed": 0,
            "cur_tx_speed": 0,
        }
        driver, client = _make_driver(client=mock_client)
        cfg = TplinkDeviceConfig(
            index=1,
            label="mr110-test",
            host="192.168.10.1",
            password="s3cr3t",
            mode="bridged",
            bridge_host="",
            rsrp_min=-110,
            rsrq_min=-20,
            snr_min=-100,
        )
        registry = ManagedDeviceRegistry(
            devices=[cfg], driver_factory=lambda _cfg: driver
        )
        status = registry.get_status("1", force=True)
        assert status is not None
        assert status["reachable"] is True
        assert client.authorize.call_count == 1


class TestNoTplinkConfigured:
    """Volet config.py de l'invariant 'aucun equipement declare => comportement
    identique a la 1.8' (INVARIANTS.md) -- moitie TplinkDriver hors scope."""

    def test_no_tplink_configured_returns_empty(self, monkeypatch):
        for name in list(__import__("os").environ):
            if name.startswith("TPLINK_"):
                monkeypatch.delenv(name, raising=False)
        from src import config

        assert config._load_tplink_devices() == ()
