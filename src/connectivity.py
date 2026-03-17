"""
Module de vérification de la connexion internet.
Utilise ping multi-cibles pour éviter les faux positifs.
"""

import subprocess
import logging
from config import PING_TARGETS, PING_TIMEOUT


def ping_host(host: str, timeout: int = PING_TIMEOUT) -> bool:
    """
    Ping un host unique.
    Retourne True si le host répond, False sinon.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logging.debug(f"Ping timeout → {host}")
        return False
    except FileNotFoundError:
        logging.error("Commande 'ping' introuvable — vérifier l'installation")
        return False
    except Exception as e:
        logging.debug(f"Erreur ping {host} : {e}")
        return False


def check_connectivity() -> bool:
    """
    Vérifie la connexion internet en pingant plusieurs cibles.

    Stratégie : connexion considérée UP si AU MOINS 1 cible répond.
    Cela évite un reboot si c'est un serveur DNS externe qui est down,
    plutôt que notre connexion fibre.

    Retourne True si internet est UP, False si DOWN.
    """
    if not PING_TARGETS:
        logging.error("PING_TARGETS est vide — impossible de vérifier la connexion")
        return True  # On assume UP pour ne pas rebooter par erreur de config

    results = {}
    for host in PING_TARGETS:
        up = ping_host(host)
        results[host] = up
        if up:
            logging.debug(f"✓ {host} répond")
        else:
            logging.debug(f"✗ {host} ne répond pas")

    reachable = sum(1 for v in results.values() if v)
    total = len(PING_TARGETS)

    if reachable == 0:
        logging.debug(f"Connexion DOWN — 0/{total} cibles accessibles")
        return False
    elif reachable < total:
        logging.debug(
            f"Connexion partielle — {reachable}/{total} cibles accessibles (considérée UP)"
        )
        return True
    else:
        logging.debug(f"Connexion UP — {reachable}/{total} cibles accessibles")
        return True
