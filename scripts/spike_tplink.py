#!/usr/bin/env python3
"""Spike de compatibilite TL-MR110 -- script jetable, hors production.

A executer manuellement **depuis un hote watchdog** (donc a travers le
chemin reseau complet : Pi Zero -> WiFi -> MR110 en mode `bridged`, ou
watchdog -> route/NAT -> Pi Zero -> WiFi -> MR110 en mode `remote`) -- c'est
le chemin reel qui doit etre valide, pas un raccourci. Voir
docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/sprints/
01-chemin-reseau-spike-contrat.md (partie B).

Deroule, dans l'ordre, en isolant chaque echec :
    1. joignabilite (ping du pont si mode remote, puis ping du MR110)
    2. acces HTTP a l'interface d'administration
    3. authentification via `tplinkrouterc6u` (import DIFFERE, jamais au
       niveau module -- voir invariant C1)
    4. inventaire des commandes de management reellement disponibles
    5. recherche d'un etat cloud/liaison dans l'API locale (best-effort)
    6. verdict FULL / DEGRADED / UNSUPPORTED, imprime en JSON

Ce script n'est PAS un module du service : c'est un outil CLI de
diagnostic. Il utilise print() (pas `logging`) et n'est pas teste
unitairement contre du vrai materiel (jetable, I/O reseau) -- voir
tests/test_spike_tplink.py pour ses seuls tests, qui portent uniquement sur
sa logique pure (parsing d'arguments, calcul du verdict).

Usage :
    export TPLINK_PASSWORD=xxx
    python3 scripts/spike_tplink.py --host 192.168.50.1 --mode bridged
    python3 scripts/spike_tplink.py --host 192.168.50.1 --mode remote \\
        --bridge-host pizero.local --json-out rapport.json

Secrets : le mot de passe se lit **uniquement** depuis la variable
d'environnement TPLINK_PASSWORD -- jamais accepte en argument de ligne de
commande (visible dans `ps`, l'historique shell, les logs systemd), jamais
journalise, jamais ecrit dans le rapport JSON.

Actions destructives ou couteuses -- JAMAIS par defaut :
    --allow-reboot   autorise reboot() (hors heures de production)
    --allow-costly   autorise les tentatives SMS/USSD (consomment du forfait)
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

# Commandes de management a inventorier -- ce que le Sprint 3 exposera a
# l'operateur si (et seulement si) le spike les voit repondre ici.
_MANAGEMENT_COMMANDS = (
    "reboot",
    "get_sms",
    "send_sms",
    "set_sms_read",
    "delete_sms",
    "send_ussd",
)

# Champs susceptibles de reveler un etat cloud/liaison de compte dans l'API
# locale -- la lib ne mappe rien de tel, mais elle ne mappe pas tout ce que
# le firmware expose. Cout nul : les reponses brutes sont deja capturees.
_CLOUD_FIELD_HINTS = ("cloud", "bind", "tplink_id", "account", "online")


def _ping(host: str, count: int = 3, timeout_s: int = 2) -> dict:
    """Ping une cible, retourne un resultat structure. Ne leve jamais."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout_s * 1000), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout_s), host]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s * count + 5,
        )
        return {"ok": proc.returncode == 0, "output": proc.stdout.strip()[-500:]}
    except Exception as e:
        return {"ok": False, "output": f"erreur ping : {e}"}


def _check_http_admin(host: str, timeout_s: int = 5) -> dict:
    """Verifie l'accessibilite HTTP de l'interface admin du MR110."""
    import urllib.error
    import urllib.request

    url = f"http://{host}/"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return {"ok": True, "status": resp.status}
    except urllib.error.HTTPError as e:
        # Une reponse HTTP, meme 401/403, prouve que l'admin repond.
        return {"ok": True, "status": e.code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_reachability(args: argparse.Namespace) -> dict:
    """Partie 1/2 du spike : joignabilite (pont si mode remote, puis MR110)
    et acces HTTP admin."""
    result: dict = {}

    if args.mode == "remote":
        if not args.bridge_host:
            result["bridge_ping"] = {
                "ok": False,
                "output": "mode remote sans --bridge-host : etape ignoree",
            }
        else:
            print(f"[1/3] Ping du pont ({args.bridge_host})...")
            result["bridge_ping"] = _ping(args.bridge_host)
            print(f"      -> {'OK' if result['bridge_ping']['ok'] else 'ECHEC'}")
    else:
        result["bridge_ping"] = {
            "ok": True,
            "output": "mode bridged : l'hote est deja le pont",
        }

    print(f"[2/3] Ping du MR110 ({args.host})...")
    result["router_ping"] = _ping(args.host)
    print(f"      -> {'OK' if result['router_ping']['ok'] else 'ECHEC'}")

    print(f"[3/3] Acces HTTP admin ({args.host})...")
    result["http_admin"] = _check_http_admin(args.host)
    print(f"      -> {'OK' if result['http_admin']['ok'] else 'ECHEC'}")

    return result


def _safe_asdict(obj) -> dict:
    """Convertit un objet retourne par la lib (dataclass ou similaire) en
    dict serialisable JSON, sans jamais lever."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        if is_dataclass(obj):
            return asdict(obj)
    except Exception:
        pass
    try:
        return dict(vars(obj))
    except Exception:
        return {"repr": repr(obj)}


def _find_cloud_hints(*payloads: dict) -> dict:
    """Cherche, dans les reponses brutes deja capturees, des champs qui
    evoqueraient un etat cloud/liaison de compte. Une absence est un
    resultat -- elle se consigne aussi (dict vide)."""
    hits: dict = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            key_lower = str(key).lower()
            if any(hint in key_lower for hint in _CLOUD_FIELD_HINTS):
                hits[key] = value
    return hits


def _run_tplink_probe(args: argparse.Namespace, password: str) -> dict:
    """Tente l'authentification et l'inventaire via `tplinkrouterc6u`.

    Import DELIBEREMENT local a cette fonction (jamais au niveau module) :
    invariant C1 -- le script doit demarrer et afficher un message clair
    meme si la lib n'est pas installee.
    """
    try:
        from tplinkrouterc6u import TplinkRouterProvider
    except ImportError:
        print(
            "tplinkrouterc6u n'est pas installe -- "
            "pip install tplinkrouterc6u (hote watchdog uniquement, "
            "jamais sur le Pi Zero -- C7).",
            file=sys.stderr,
        )
        return {
            "ok": False,
            "error": "tplinkrouterc6u n'est pas installe",
            "steps": {},
        }

    probe: dict = {"ok": False, "steps": {}}
    client = None
    try:
        print("[spike] TplinkRouterProvider.get_client(...)")
        client = TplinkRouterProvider.get_client(f"http://{args.host}", password)
        probe["steps"]["client_class"] = type(client).__name__
        print(f"        -> classe cliente : {probe['steps']['client_class']}")

        print("[spike] authorize()...")
        client.authorize()
        probe["steps"]["authorize"] = True
        print("        -> OK")

        try:
            print("[spike] get_firmware()...")
            firmware = _safe_asdict(client.get_firmware())
            probe["steps"]["firmware"] = firmware
            print(f"        -> {firmware}")
        except Exception as e:
            probe["steps"]["firmware_error"] = str(e)
            print(f"        -> echec : {e}")

        try:
            print("[spike] get_status()...")
            status = _safe_asdict(client.get_status())
            probe["steps"]["status"] = status
        except Exception as e:
            probe["steps"]["status_error"] = str(e)
            print(f"        -> echec : {e}")

        try:
            print("[spike] get_lte_status()...")
            lte = _safe_asdict(client.get_lte_status())
            probe["steps"]["lte_status"] = lte
            print(f"        -> {lte}")
        except Exception as e:
            probe["steps"]["lte_status_error"] = str(e)
            print(f"        -> echec : {e}")

        print("[spike] inventaire des commandes de management disponibles...")
        commands = {name: hasattr(client, name) for name in _MANAGEMENT_COMMANDS}
        probe["steps"]["commands_available"] = commands
        print(f"        -> {commands}")

        cloud_hints = _find_cloud_hints(
            probe["steps"].get("status", {}),
            probe["steps"].get("lte_status", {}),
            probe["steps"].get("firmware", {}),
        )
        probe["steps"]["cloud_state_hints"] = cloud_hints
        print(
            f"[spike] indices d'etat cloud dans l'API locale : {cloud_hints or 'aucun'}"
        )

        if args.allow_reboot:
            print("[spike] --allow-reboot : appel de reboot() -- ACTION DESTRUCTIVE")
            try:
                client.reboot()
                probe["steps"]["reboot_called"] = True
            except Exception as e:
                probe["steps"]["reboot_error"] = str(e)
        else:
            probe["steps"]["reboot_called"] = False

        if args.allow_costly:
            print(
                "[spike] --allow-costly demande : SMS/USSD non automatises par "
                "ce spike -- a executer manuellement sur le terrain si besoin, "
                "jamais implicitement."
            )

        probe["ok"] = True

    except Exception as e:
        probe["error"] = str(e)
        print(f"[spike] echec : {e}", file=sys.stderr)

    finally:
        if client is not None:
            try:
                print("[spike] logout()...")
                client.logout()
                probe["steps"]["logout"] = True
                print("        -> OK")
            except Exception as e:
                probe["steps"]["logout_error"] = str(e)
                print(
                    f"        -> ECHEC logout (session potentiellement "
                    f"verrouillee sur le routeur) : {e}",
                    file=sys.stderr,
                )

    return probe


def _verdict(reachability: dict, probe: dict) -> str:
    """Calcule le verdict FULL / DEGRADED / UNSUPPORTED.

    UNSUPPORTED : auth impossible (lib absente, refusee, ou en echec).
    DEGRADED    : auth OK, mais champs LTE ou commandes partiels/absents.
    FULL        : auth OK + LTE status peuple + au moins une commande de
                  management exploitable.
    """
    if not probe.get("steps", {}).get("authorize"):
        return "UNSUPPORTED"

    has_lte = bool(probe["steps"].get("lte_status"))
    commands = probe["steps"].get("commands_available", {})
    has_command = any(commands.values())

    if has_lte and has_command:
        return "FULL"
    return "DEGRADED"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spike_tplink.py",
        description=(
            "Spike de compatibilite TL-MR110 (jetable, hors production). "
            "Mot de passe via la variable d'environnement TPLINK_PASSWORD "
            "-- jamais en argument de ligne de commande."
        ),
    )
    parser.add_argument("--host", required=True, help="IP du TL-MR110")
    parser.add_argument(
        "--bridge-host",
        default=None,
        help="IP/hostname du pont (Pi Zero), requis si --mode remote",
    )
    parser.add_argument(
        "--mode",
        choices=["bridged", "remote"],
        default="bridged",
        help=(
            "Mode d'acces (C16) : bridged = l'hote est deja sur le WiFi du "
            "MR110 (ex: Pi Zero) ; remote = pont dedie joint par le reseau"
        ),
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Chemin du fichier de sortie JSON (defaut : stdout uniquement)",
    )
    parser.add_argument(
        "--allow-reboot",
        action="store_true",
        help="Autorise l'appel a reboot() -- JAMAIS par defaut, hors heures de prod",
    )
    parser.add_argument(
        "--allow-costly",
        action="store_true",
        help="Autorise les tentatives SMS/USSD (coutent de l'argent) -- JAMAIS par defaut",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    password = os.environ.get("TPLINK_PASSWORD")
    if not password:
        print(
            "ERREUR : variable d'environnement TPLINK_PASSWORD absente. "
            "Le mot de passe n'est jamais accepte en argument de ligne de "
            "commande -- export TPLINK_PASSWORD=... avant de relancer.",
            file=sys.stderr,
        )
        return 2

    if args.mode == "remote" and not args.bridge_host:
        print(
            "ERREUR : --mode remote necessite --bridge-host (adresse du pont).",
            file=sys.stderr,
        )
        return 2

    print("=" * 70)
    print(f"Spike TL-MR110 -- mode={args.mode} host={args.host}")
    print("=" * 70)

    reachability = _check_reachability(args)
    probe = _run_tplink_probe(args, password)
    verdict = _verdict(reachability, probe)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "mode": args.mode,
        "bridge_host": args.bridge_host,
        "reachability": reachability,
        "probe": probe,
        "verdict": verdict,
    }

    output = json.dumps(report, indent=2, ensure_ascii=False, default=str)

    print()
    print("=" * 70)
    print(f"VERDICT : {verdict}")
    print("=" * 70)
    print(output)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nRapport ecrit dans {args.json_out}")

    return 0 if verdict != "UNSUPPORTED" else 1


if __name__ == "__main__":
    sys.exit(main())
