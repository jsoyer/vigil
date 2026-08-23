"""Contrat RouterDriver -- interface commune vendor-independante.

Aucun import de lib vendor a ce niveau (invariant C1) : ce module doit rester
importable sur les 4 instances de production meme si `tplinkrouterc6u` n'est
pas installe -- l'`ImportError` ne doit survenir qu'a l'usage effectif d'un
equipement de ce vendor, dans le corps d'une methode d'implementation
concrete (ex: `TplinkDriver`), jamais ici.

Voir docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/INVARIANTS.md
("Import vendor paresseux (C1)") et le meme dossier, sprints/01, partie D.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class RouterRole(str, Enum):
    """Role d'un equipement pilote par le watchdog."""

    PRIMARY = "primary"  # scoring + reboot automatique (USG, comportement actuel)
    BACKUP = "backup"  # management + audit, JAMAIS de reboot automatique


class Readiness(str, Enum):
    """Etat de disponibilite calcule d'un equipement."""

    OK = "ok"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"  # info indisponible -- n'est PAS un etat sain


class Hop(str, Enum):
    """Saut du chemin d'audit -- sert a attribuer une panne au bon endroit."""

    BRIDGE = "bridge"  # le Pi Zero (ou l'hote lui-meme en mode bridged, C16)
    WIRELESS = "wireless"  # le saut WiFi Pi Zero <-> MR110
    DEVICE = "device"  # le routeur lui-meme
    ROUTE = "route"  # defaut de configuration du chemin (C8), pas une panne


@dataclass(frozen=True)
class RouterHealth:
    """Resultat d'une sonde de joignabilite, avec attribution de panne.

    `failed_hop` est le champ qui rend les alertes exploitables : « secours
    injoignable » sans dire ou oblige a tout re-diagnostiquer a la main.
    """

    reachable: bool
    internet_ok: bool
    rtt_ms: float | None = None
    failed_hop: Hop | None = None  # None si tout repond
    detail: str = ""


@dataclass(frozen=True)
class RouterReadiness:
    """Etat de disponibilite calcule (seuils signal, SIM, integrite du chemin)."""

    state: Readiness = Readiness.UNKNOWN
    reasons: tuple[str, ...] = ()  # ex: ("rsrp=-118 < seuil -110",)


@dataclass(frozen=True)
class RouterMetrics:
    """Metriques d'un equipement. Tous les champs sont nullable : dependants
    du vendor et du firmware -- une valeur absente est `None`, jamais
    inventee."""

    cpu_usage: float | None = None
    mem_usage: float | None = None
    wan_ip: str | None = None
    clients_total: int | None = None
    # --- specifique 4G/LTE ---
    network_type: str | None = None
    sim_status: str | None = None
    signal_bars: int | None = None
    rsrp: int | None = None
    rsrq: int | None = None
    snr: int | None = None
    isp_name: str | None = None
    data_used_bytes: int | None = None
    rx_speed_bps: int | None = None
    tx_speed_bps: int | None = None


@runtime_checkable
class RouterDriver(Protocol):
    """Interface commune a tous les drivers vendor.

    Aucune methode ne leve jamais (invariant "Les drivers ne levent jamais",
    INVARIANTS.md) : une panne reseau, une auth refusee, un timeout ou un
    firmware inattendu se traduisent par une valeur degradee (None,
    `Readiness.UNKNOWN`, `False`), jamais par une exception qui franchit la
    frontiere du driver ni par un etat sain invente par defaut.

    `UsgDriver` n'est pas implemente en A1 (voir sprints/01, partie D) : le
    contrat est pose des maintenant pour que `TplinkDriver` ait la bonne
    forme des le depart.
    """

    vendor: str  # "usg" | "tplink"

    def health(self) -> RouterHealth:
        """Sonde de joignabilite avec attribution de panne. Ne leve jamais."""
        ...

    def metrics(self) -> RouterMetrics:
        """Metriques best-effort. Ne leve jamais -- champs a `None` si indispo."""
        ...

    def readiness(self) -> RouterReadiness:
        """Etat de disponibilite calcule. Ne leve jamais -- `UNKNOWN` si indispo."""
        ...

    def reboot(self) -> bool:
        """Redemarre l'equipement. Ne leve jamais.

        Pour un equipement `RouterRole.BACKUP`, ne doit etre invoque que par
        une commande operateur explicite et confirmee (C6) -- jamais
        automatiquement par la boucle de surveillance.
        """
        ...

    def test_connection(self) -> bool:
        """Diagnostic de connexion, sans effet de bord destructif. Ne leve jamais."""
        ...
