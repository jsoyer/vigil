"""
Module de notification Telegram.
Envoie des alertes lors des événements clés (coupure, reboot, rétablissement).
"""

import logging
import html
from datetime import datetime
from typing import Optional

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None  # type: ignore[assignment]
    REQUESTS_AVAILABLE = False

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_TIMEOUT,
)

_HOSTNAME: Optional[str] = None


def _get_hostname() -> str:
    """Retourne le hostname de la machine pour identifier la source."""
    global _HOSTNAME
    if _HOSTNAME is None:
        try:
            import socket

            _HOSTNAME = socket.gethostname()
        except Exception:
            _HOSTNAME = "usg-watchdog"
    return _HOSTNAME


def _is_configured() -> bool:
    """Vérifie que Telegram est configuré."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _build_message(message: str, timestamp: str, hostname: str) -> str:
    """Construit un message Telegram compatible avec le mode HTML."""
    escaped_hostname = html.escape(hostname)
    escaped_message = html.escape(message)
    return (
        f"<b>📡 USG Watchdog</b>\n"
        f"<i>{escaped_hostname} — {timestamp}</i>\n\n"
        f"{escaped_message}"
    )


def send_notification(message: str) -> bool:
    """
    Envoie un message Telegram.

    Ne lève jamais d'exception — les erreurs de notification ne doivent
    pas interrompre le watchdog principal.

    Retourne True si envoyé avec succès, False sinon.
    """
    if not _is_configured():
        logging.debug("Telegram non configuré — notification ignorée")
        return False

    if not REQUESTS_AVAILABLE:
        logging.warning(
            "Module 'requests' non installé — notification Telegram impossible"
        )
        return False

    if requests is None:
        logging.warning(
            "Module 'requests' indisponible — notification Telegram impossible"
        )
        return False

    requests_module = requests

    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    full_message = _build_message(message, timestamp, _get_hostname())

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": full_message,
        "parse_mode": "HTML",
        "disable_notification": False,
    }

    try:
        response = requests_module.post(url, json=payload, timeout=TELEGRAM_TIMEOUT)
        response.raise_for_status()
        logging.debug("📬 Notification Telegram envoyée")
        return True
    except requests_module.exceptions.Timeout:
        logging.warning("Timeout envoi Telegram — notification ignorée")
    except requests_module.exceptions.ConnectionError:
        logging.warning("Erreur réseau Telegram (normal si connexion DOWN)")
    except requests_module.exceptions.HTTPError as e:
        logging.warning(
            f"Erreur HTTP Telegram : {e.response.status_code} — {e.response.text}"
        )
    except Exception as e:
        logging.warning(f"Erreur notification Telegram : {e}")

    return False
