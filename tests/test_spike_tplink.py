"""Smoke tests for scripts/spike_tplink.py.

Le script est un outil de spike jetable, hors production, execute
manuellement sur le terrain a travers le chemin reseau reel (ping, HTTP,
auth TP-Link) -- voir sprints/01-chemin-reseau-spike-contrat.md, partie B.
Il n'est **pas** teste unitairement contre du vrai materiel (I/O reseau) et
est exclu de la couverture (`validate.sh` ne mesure que `--cov=src`).

Ce fichier ne fait que verifier que le script est syntaxiquement valide,
s'importe sans dependre de `tplinkrouterc6u` au niveau module, et que sa
logique pure (parsing d'arguments, calcul du verdict, serialisation) se
comporte comme documente -- sans jamais toucher au reseau ni a un
equipement reel.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "spike_tplink.py"


def _load_spike_module():
    """Charge scripts/spike_tplink.py comme module, sans l'executer (pas de
    bloc __main__), et sans que cela necessite tplinkrouterc6u installe."""
    assert "tplinkrouterc6u" not in sys.modules
    spec = importlib.util.spec_from_file_location("spike_tplink", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def spike():
    return _load_spike_module()


class TestImportSansLibVendor:
    def test_import_ne_tire_pas_tplinkrouterc6u(self, spike):
        """Le script s'importe sans la lib vendor (elle n'est utilisee que
        dans le corps de _run_tplink_probe, jamais au niveau module)."""
        assert "tplinkrouterc6u" not in sys.modules


class TestArgParser:
    def test_host_requis(self, spike):
        parser = spike.build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_defaut_mode_bridged(self, spike):
        parser = spike.build_arg_parser()
        args = parser.parse_args(["--host", "192.168.50.1"])
        assert args.mode == "bridged"
        assert args.bridge_host is None
        assert args.allow_reboot is False
        assert args.allow_costly is False

    def test_mode_remote_avec_bridge_host(self, spike):
        parser = spike.build_arg_parser()
        args = parser.parse_args(
            [
                "--host",
                "192.168.50.1",
                "--mode",
                "remote",
                "--bridge-host",
                "pizero.local",
            ]
        )
        assert args.mode == "remote"
        assert args.bridge_host == "pizero.local"

    def test_mode_invalide_rejete(self, spike):
        parser = spike.build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--host", "1.2.3.4", "--mode", "bogus"])

    def test_pas_d_argument_password(self, spike):
        """Le mot de passe ne doit JAMAIS etre acceptable en ligne de
        commande -- variable d'environnement TPLINK_PASSWORD uniquement."""
        parser = spike.build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--host", "1.2.3.4", "--password", "secret"])


class TestVerdict:
    def test_unsupported_si_authorize_absent(self, spike):
        probe = {"steps": {}}
        assert spike._verdict({}, probe) == "UNSUPPORTED"

    def test_unsupported_si_lib_absente(self, spike):
        probe = {"ok": False, "error": "tplinkrouterc6u n'est pas installe"}
        assert spike._verdict({}, probe) == "UNSUPPORTED"

    def test_degraded_si_auth_ok_mais_pas_de_commande(self, spike):
        probe = {
            "steps": {
                "authorize": True,
                "lte_status": {"rsrp": -95},
                "commands_available": {"reboot": False},
            }
        }
        assert spike._verdict({}, probe) == "DEGRADED"

    def test_degraded_si_pas_de_lte_status(self, spike):
        probe = {
            "steps": {
                "authorize": True,
                "lte_status": {},
                "commands_available": {"reboot": True},
            }
        }
        assert spike._verdict({}, probe) == "DEGRADED"

    def test_full_si_auth_lte_et_commande(self, spike):
        probe = {
            "steps": {
                "authorize": True,
                "lte_status": {"rsrp": -95},
                "commands_available": {"reboot": True, "get_sms": False},
            }
        }
        assert spike._verdict({}, probe) == "FULL"


class TestSafeAsDict:
    def test_none(self, spike):
        assert spike._safe_asdict(None) == {}

    def test_dict_passe_tel_quel(self, spike):
        assert spike._safe_asdict({"a": 1}) == {"a": 1}

    def test_objet_simple(self, spike):
        class Obj:
            def __init__(self):
                self.x = 1

        assert spike._safe_asdict(Obj()) == {"x": 1}

    def test_ne_leve_jamais(self, spike):
        assert "repr" in spike._safe_asdict(object())


class TestMainSansSecretsExposes:
    def test_erreur_claire_sans_password_env(self, spike, monkeypatch, capsys):
        monkeypatch.delenv("TPLINK_PASSWORD", raising=False)
        monkeypatch.setattr(sys, "argv", ["spike_tplink.py", "--host", "1.2.3.4"])
        rc = spike.main()
        assert rc != 0
        captured = capsys.readouterr()
        assert "TPLINK_PASSWORD" in captured.err

    def test_erreur_claire_mode_remote_sans_bridge_host(
        self, spike, monkeypatch, capsys
    ):
        monkeypatch.setenv("TPLINK_PASSWORD", "unused-in-this-test")
        monkeypatch.setattr(
            sys,
            "argv",
            ["spike_tplink.py", "--host", "1.2.3.4", "--mode", "remote"],
        )
        rc = spike.main()
        assert rc != 0
        captured = capsys.readouterr()
        assert "--bridge-host" in captured.err
