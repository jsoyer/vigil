"""
Module de controle du USG Ubiquiti via SSH.
Gere l'authentification par cle SSH et l'envoi de la commande de reboot.

Compatibilite : EdgeOS tourne sur OpenSSH 6.6.1 (vieux firmware USG).
Le client SSH moderne (OpenSSH 8+) et paramiko ont besoin d'ajustements
pour negocier les bons algorithmes avec ce vieux serveur.
"""

import logging
import socket
from typing import Optional

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore

from config import (
    USG_IP,
    USG_USER,
    USG_SSH_KEY,
    USG_SSH_PASSWORD,
    SSH_TIMEOUT,
    USG_REBOOT_COMMAND,
    USG_KNOWN_HOSTS,
)

_ALLOWED_REBOOT_COMMANDS: frozenset[str] = frozenset(
    {
        "reboot",
        "sudo reboot",
        "/sbin/reboot",
        "sudo /sbin/reboot",
    }
)

_CONNECTION_RESET_MARKERS = (
    "Connection reset",
    "EOF",
    "Socket is closed",
    "Broken pipe",
)


def _get_ssh_client() -> Optional["paramiko.SSHClient"]:
    """
    Cree et retourne un client SSH connecte au USG.

    EdgeOS (USG) tourne sur OpenSSH 6.6.1 qui ne supporte pas rsa-sha2-256/512.
    On desactive ces algos pour forcer le fallback sur ed25519 ou ssh-rsa (SHA1),
    compatibles avec le vieux serveur.

    Retourne None en cas d'echec.
    """
    if paramiko is None:
        logging.error("Le module 'paramiko' n'est pas installe (pip install paramiko)")
        return None

    client = paramiko.SSHClient()

    try:
        client.load_host_keys(USG_KNOWN_HOSTS)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    except FileNotFoundError:
        logging.warning(
            "Fichier known_hosts introuvable : %s -- "
            "connexion autorisee mais verifier avec scripts/setup_ssh.sh",
            USG_KNOWN_HOSTS,
        )
        client.set_missing_host_key_policy(paramiko.WarningPolicy())

    connect_kwargs: dict = {
        "hostname": USG_IP,
        "username": USG_USER,
        "timeout": SSH_TIMEOUT,
        "banner_timeout": SSH_TIMEOUT,
        "auth_timeout": SSH_TIMEOUT,
        "allow_agent": False,
        "look_for_keys": False,
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
    }

    if USG_SSH_KEY and USG_SSH_KEY.strip():
        connect_kwargs["key_filename"] = USG_SSH_KEY
        logging.debug("Authentification SSH par cle : %s", USG_SSH_KEY)
    elif USG_SSH_PASSWORD and USG_SSH_PASSWORD.strip():
        connect_kwargs["password"] = USG_SSH_PASSWORD
        logging.debug("Authentification SSH par mot de passe")
    else:
        logging.error(
            "Aucune methode d'authentification SSH configuree "
            "(USG_SSH_KEY ou USG_SSH_PASSWORD requis)"
        )
        return None

    try:
        client.connect(**connect_kwargs)
        logging.debug("Connexion SSH etablie -> %s@%s", USG_USER, USG_IP)
        return client
    except paramiko.AuthenticationException:
        logging.error(
            "Echec d'authentification SSH sur %s -- verifier les credentials", USG_IP
        )
    except paramiko.SSHException as e:
        logging.error("Erreur SSH %s : %s", USG_IP, e)
    except socket.timeout:
        logging.error(
            "Timeout SSH (%ds) vers %s -- USG accessible sur le reseau local ?",
            SSH_TIMEOUT,
            USG_IP,
        )
    except socket.error as e:
        logging.error("Erreur reseau vers %s : %s", USG_IP, e)
    except FileNotFoundError:
        logging.error("Cle SSH introuvable : %s", USG_SSH_KEY)
    except Exception as e:
        logging.error("Erreur inattendue SSH : %s", e, exc_info=True)

    return None


def reboot_usg() -> bool:
    """
    Envoie la commande de reboot au USG via SSH.

    Le USG coupe la connexion SSH immediatement apres l'execution
    du reboot, ce qui est un comportement normal.

    Retourne True si la commande a ete envoyee, False en cas d'erreur.
    """
    if USG_REBOOT_COMMAND not in _ALLOWED_REBOOT_COMMANDS:
        logging.error(
            "USG_REBOOT_COMMAND '%s' non autorisee -- valeurs acceptees : %s",
            USG_REBOOT_COMMAND,
            sorted(_ALLOWED_REBOOT_COMMANDS),
        )
        return False

    logging.info("Tentative de connexion SSH -> %s@%s", USG_USER, USG_IP)

    client = _get_ssh_client()
    if client is None:
        return False

    try:
        logging.info("Envoi de la commande : '%s'", USG_REBOOT_COMMAND)
        client.exec_command(USG_REBOOT_COMMAND, timeout=5)
        logging.info("Commande reboot envoyee au USG (%s)", USG_IP)
        return True

    except Exception as e:
        error_str = str(e)
        if any(marker in error_str for marker in _CONNECTION_RESET_MARKERS):
            logging.info(
                "USG a coupe la connexion SSH (reboot en cours -- comportement normal)"
            )
            return True
        logging.error("Erreur lors de l'envoi du reboot : %s", e)
        return False

    finally:
        try:
            client.close()
        except Exception:
            logging.debug("Erreur lors de la fermeture SSH (ignoree)")


def test_ssh_connection() -> bool:
    """
    Teste la connexion SSH au USG sans effectuer de reboot.

    EdgeOS utilise un shell restreint -- on considere le test reussi
    des que le handshake SSH + authentification aboutissent,
    sans executer de commande.

    Retourne True si la connexion est etablie, False sinon.
    """
    logging.info("Test de connexion SSH -> %s@%s", USG_USER, USG_IP)
    client = _get_ssh_client()

    if client is None:
        logging.error("Test SSH echoue")
        return False

    logging.info("Test SSH reussi -- handshake et authentification OK")
    try:
        client.close()
    except Exception:
        logging.debug("Erreur lors de la fermeture SSH de test (ignoree)")
    return True
