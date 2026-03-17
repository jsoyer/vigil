#!/usr/bin/env python3
"""
USG Watchdog — Surveillance de connexion fibre + reboot automatique USG Ubiquiti
"""

import time
import logging
import logging.handlers
import sys
from datetime import datetime

from config import (
    CHECK_INTERVAL,
    FAILURE_THRESHOLD,
    REBOOT_COOLDOWN,
    LOG_FILE,
    LOG_LEVEL,
)
from connectivity import check_connectivity
from usg import reboot_usg
from notifier import send_notification


def setup_logging():
    """Configure le logging vers fichier + console avec rotation."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Handler fichier avec rotation (10 MB max, 5 fichiers)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except PermissionError:
        logging.warning(f"Impossible d'écrire dans {LOG_FILE} — logs console uniquement")


def main():
    setup_logging()

    failure_count = 0
    last_reboot_time = 0.0
    was_down = False

    logging.info("=" * 60)
    logging.info("🚀 USG Watchdog démarré")
    logging.info(f"   Check toutes les {CHECK_INTERVAL}s")
    logging.info(f"   Seuil de reboot : {FAILURE_THRESHOLD} échecs consécutifs")
    logging.info(f"   Cooldown post-reboot : {REBOOT_COOLDOWN}s")
    logging.info("=" * 60)

    send_notification("🚀 USG Watchdog démarré")

    while True:
        is_up = check_connectivity()

        if is_up:
            if was_down:
                down_duration = failure_count * CHECK_INTERVAL
                msg = f"✅ Connexion rétablie après {down_duration}s de coupure"
                logging.info(msg)
                send_notification(msg)
                was_down = False

            if failure_count > 0:
                logging.debug(f"Remise à zéro du compteur (était à {failure_count})")
            failure_count = 0

        else:
            failure_count += 1
            was_down = True
            logging.warning(
                f"⚠️  Connexion DOWN — Échec {failure_count}/{FAILURE_THRESHOLD} "
                f"({failure_count * CHECK_INTERVAL}s de coupure)"
            )

            if failure_count >= FAILURE_THRESHOLD:
                now = time.time()
                elapsed_since_reboot = now - last_reboot_time

                if elapsed_since_reboot < REBOOT_COOLDOWN:
                    remaining = int(REBOOT_COOLDOWN - elapsed_since_reboot)
                    logging.info(
                        f"⏳ Cooldown actif — prochain reboot possible dans {remaining}s"
                    )
                else:
                    down_duration = failure_count * CHECK_INTERVAL
                    logging.warning(
                        f"🔴 Seuil atteint ({down_duration}s de coupure) — Lancement du reboot USG"
                    )
                    send_notification(
                        f"🔴 Connexion DOWN depuis {down_duration}s\n"
                        f"🔄 Reboot USG en cours..."
                    )

                    success = reboot_usg()

                    if success:
                        last_reboot_time = now
                        failure_count = 0
                        reboot_time_str = datetime.now().strftime("%H:%M:%S")
                        logging.info(
                            f"✅ Reboot USG envoyé à {reboot_time_str} — "
                            f"Cooldown de {REBOOT_COOLDOWN}s activé"
                        )
                        # Attendre que le USG redémarre avant de reprendre les checks
                        logging.info("⏳ Pause de 60s — attente du redémarrage USG...")
                        time.sleep(60)
                    else:
                        send_notification(
                            "❌ Reboot SSH a échoué !\n"
                            "Vérifier les logs pour plus de détails."
                        )
                        logging.error("❌ Reboot SSH échoué — retry au prochain cycle")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("🛑 USG Watchdog arrêté manuellement")
        send_notification("🛑 USG Watchdog arrêté")
        sys.exit(0)
    except Exception as e:
        logging.critical(f"💥 Erreur fatale : {e}", exc_info=True)
        send_notification(f"💥 USG Watchdog crashé : {e}")
        sys.exit(1)
