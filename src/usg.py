"""
Module de contrôle du USG Ubiquiti via SSH.
Gère l'authentification par clé SSH et l'envoi de la commande de reboot.

Compatibilité : EdgeOS tourne sur OpenSSH 6.6.1 (vieux firmware USG).
Le client SSH moderne (OpenSSH 8+) et paramiko ont besoin d'ajustements
pour négocier les bons algorithmes avec ce vieux serveur.
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
)


def _get_ssh_client() -> Optional["paramiko.SSHClient"]:
    """
    Crée et retourne un client SSH connecté au USG.

    EdgeOS (USG) tourne sur OpenSSH 6.6.1 qui ne supporte pas rsa-sha2-256/512.
    On désactive ces algos pour forcer le fallback sur ed25519 ou ssh-rsa (SHA1),
    compatibles avec le vieux serveur.

    Retourne None en cas d'échec.
    """
    if paramiko is None:
        logging.error("Le module 'paramiko' n'est pas installé (pip install paramiko)")
        return None

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {
        "hostname": USG_IP,
        "username": USG_USER,
        "timeout": SSH_TIMEOUT,
        "banner_timeout": SSH_TIMEOUT,
        "auth_timeout": SSH_TIMEOUT,
        "allow_agent": False,
        "look_for_keys": False,
        # Fix compatibilité OpenSSH 6.6.1 (EdgeOS/USG) :
        # Désactive rsa-sha2 pour permettre la négociation avec le vieux serveur.
        # Ed25519 reste prioritaire (supporté depuis OpenSSH 6.5).
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
    }

    # Priorité : clé SSH > mot de passe
    if USG_SSH_KEY and USG_SSH_KEY.strip():
        connect_kwargs["key_filename"] = USG_SSH_KEY
        logging.debug(f"Authentification SSH par clé : {USG_SSH_KEY}")
    elif USG_SSH_PASSWORD and USG_SSH_PASSWORD.strip():
        connect_kwargs["password"] = USG_SSH_PASSWORD
        logging.debug("Authentification SSH par mot de passe")
    else:
        logging.error(
            "Aucune méthode d'authentification SSH configurée "
            "(USG_SSH_KEY ou USG_SSH_PASSWORD requis)"
        )
        return None

    try:
        client.connect(**connect_kwargs)
        logging.debug(f"Connexion SSH établie → {USG_USER}@{USG_IP}")
        return client
    except paramiko.AuthenticationException:
        logging.error(
            f"Échec d'authentification SSH sur {USG_IP} "
            "— vérifier les credentials dans config.py"
        )
    except paramiko.SSHException as e:
        logging.error(f"Erreur SSH {USG_IP} : {e}")
    except socket.timeout:
        logging.error(
            f"Timeout SSH ({SSH_TIMEOUT}s) vers {USG_IP} "
            "— USG accessible sur le réseau local ?"
        )
    except socket.error as e:
        logging.error(f"Erreur réseau vers {USG_IP} : {e}")
    except FileNotFoundError:
        logging.error(f"Clé SSH introuvable : {USG_SSH_KEY}")
    except Exception as e:
        logging.error(f"Erreur inattendue SSH : {e}")

    return None


def reboot_usg() -> bool:
    """
    Envoie la commande de reboot au USG via SSH.

    Le USG coupe la connexion SSH immédiatement après l'exécution
    du reboot, ce qui est un comportement normal.

    Retourne True si la commande a été envoyée, False en cas d'erreur.
    """
    logging.info(f"Tentative de connexion SSH → {USG_USER}@{USG_IP}")

    client = _get_ssh_client()
    if client is None:
        return False

    try:
        logging.info(f"Envoi de la commande : '{USG_REBOOT_COMMAND}'")
        # Le USG va terminer la connexion dès le reboot — timeout court intentionnel
        stdin, stdout, stderr = client.exec_command(
            USG_REBOOT_COMMAND, timeout=5, get_pty=True
        )
        # On ne lit pas stdout/stderr — le device va couper avant de répondre
        logging.info(f"✅ Commande reboot envoyée au USG ({USG_IP})")
        return True

    except Exception as e:
        # Le USG peut fermer la connexion abruptement — c'est normal
        if any(x in str(e) for x in ["Connection reset", "EOF", "Socket is closed", "Broken pipe"]):
            logging.info("✅ USG a coupé la connexion SSH (reboot en cours — comportement normal)")
            return True
        logging.error(f"Erreur lors de l'envoi du reboot : {e}")
        return False

    finally:
        try:
            client.close()
        except Exception:
            pass


def test_ssh_connection() -> bool:
    """
    Teste la connexion SSH au USG sans effectuer de reboot.

    EdgeOS utilise un shell restreint — on considère le test réussi
    dès que le handshake SSH + authentification aboutissent,
    sans exécuter de commande.

    Retourne True si la connexion est établie, False sinon.
    """
    logging.info(f"Test de connexion SSH → {USG_USER}@{USG_IP}")
    client = _get_ssh_client()

    if client is None:
        logging.error("❌ Test SSH échoué")
        return False

    # Handshake + auth OK — suffisant pour valider la config
    logging.info("✅ Test SSH réussi — handshake et authentification OK")
    try:
        client.close()
    except Exception:
        pass
    return True
