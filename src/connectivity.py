"""
Module de verification de la connexion internet et du gateway LAN.
Ping gateway USG + multi-cibles internet pour scoring precis.
"""

import ipaddress
import subprocess
import logging
from dataclasses import dataclass

from config import PING_TARGETS, PING_TIMEOUT, USG_IP


@dataclass(frozen=True)
class ConnectivityResult:
    """Resultat d'un cycle de verification."""
    gateway_ok: bool
    internet_ok_count: int
    internet_total: int


def ping_host(host: str, timeout: int = PING_TIMEOUT) -> bool:
    """
    Ping un host unique.
    Retourne True si le host repond, False sinon.
    """
    try:
        ipaddress.ip_address(host)
    except ValueError:
        logging.error("Cible de ping invalide (doit etre une adresse IP) : %s", host)
        return False

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logging.debug("Ping timeout -> %s", host)
        return False
    except FileNotFoundError:
        logging.error("Commande 'ping' introuvable -- verifier l'installation")
        return False
    except Exception as e:
        logging.debug("Erreur ping %s : %s", host, e)
        return False


def ping_gateway() -> bool:
    """Ping le gateway USG sur le LAN."""
    ok = ping_host(USG_IP)
    if ok:
        logging.debug("Gateway %s repond", USG_IP)
    else:
        logging.debug("Gateway %s ne repond pas", USG_IP)
    return ok


def check_internet() -> int:
    """
    Ping les cibles internet et retourne le nombre de reponses.
    Short-circuit impossible ici : on a besoin du count exact pour le scoring.
    """
    if not PING_TARGETS:
        logging.error("PING_TARGETS est vide -- impossible de verifier la connexion")
        return 0

    ok_count = 0
    for host in PING_TARGETS:
        if ping_host(host):
            ok_count += 1
            logging.debug("Internet %s repond", host)
        else:
            logging.debug("Internet %s ne repond pas", host)

    return ok_count


def check_connectivity() -> ConnectivityResult:
    """
    Effectue un cycle complet de verification :
    1. Ping du gateway USG (LAN)
    2. Ping des cibles internet

    Retourne un ConnectivityResult avec le detail.
    """
    gateway_ok = ping_gateway()
    internet_ok_count = check_internet()

    return ConnectivityResult(
        gateway_ok=gateway_ok,
        internet_ok_count=internet_ok_count,
        internet_total=len(PING_TARGETS),
    )
