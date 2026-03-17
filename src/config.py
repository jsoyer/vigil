"""
Configuration du USG Watchdog.
Modifier ce fichier selon votre environnement.
"""

import os

# ─────────────────────────────────────────────
# CONNEXION — Cibles de ping
# ─────────────────────────────────────────────

# Plusieurs cibles pour éviter les faux positifs (Google DNS, Cloudflare, Quad9)
PING_TARGETS: list[str] = [
    "8.8.8.8",   # Google DNS
    "1.1.1.1",   # Cloudflare DNS
    "9.9.9.9",   # Quad9 DNS
]

# Timeout ping en secondes
PING_TIMEOUT: int = 3

# ─────────────────────────────────────────────
# LOGIQUE DE SURVEILLANCE
# ─────────────────────────────────────────────

# Délai entre chaque check (secondes)
# 30s → réactif sans être agressif
CHECK_INTERVAL: int = int(os.getenv("WATCHDOG_CHECK_INTERVAL", "30"))

# Nombre d'échecs CONSÉCUTIFS avant de rebooter
# 3 échecs × 30s = 90s de coupure confirmée avant reboot
FAILURE_THRESHOLD: int = int(os.getenv("WATCHDOG_FAILURE_THRESHOLD", "3"))

# Cooldown après un reboot (secondes)
# Évite les boucles de reboot si le problème persiste
# 600s = 10 minutes
REBOOT_COOLDOWN: int = int(os.getenv("WATCHDOG_REBOOT_COOLDOWN", "600"))

# ─────────────────────────────────────────────
# UBIQUITI USG — Connexion SSH
# ─────────────────────────────────────────────

# IP locale du USG (généralement la gateway du réseau)
USG_IP: str = os.getenv("USG_IP", "192.168.1.1")

# Username SSH du USG
# Note : sur les USG Ubiquiti, le compte SSH peut être 'maintenance', 'admin', 'ubnt' ou 'root'
# selon la version du firmware et la configuration du controller UniFi.
# Vérifier dans : UniFi Controller → Settings → System → Advanced → Device Authentication
USG_USER: str = os.getenv("USG_USER", "maintenance")

# Chemin vers la clé SSH privée dédiée (générée par scripts/setup_ssh.sh)
# La clé est générée en Ed25519 pour compatibilité avec EdgeOS (OpenSSH 6.6.1)
USG_SSH_KEY: str = os.getenv(
    "USG_SSH_KEY", "/opt/usg-watchdog/.ssh/usg_rsa"
)

# Mot de passe SSH (déconseillé — préférer la clé SSH)
# Laisser vide si vous utilisez une clé SSH
USG_SSH_PASSWORD: str = os.getenv("USG_SSH_PASSWORD", "")

# Timeout de connexion SSH (secondes)
SSH_TIMEOUT: int = int(os.getenv("SSH_TIMEOUT", "10"))

# Commande de reboot à exécuter sur le USG
# "sudo reboot" pour USG standard / "reboot" pour certains modèles
USG_REBOOT_COMMAND: str = os.getenv("USG_REBOOT_COMMAND", "sudo reboot")

# ─────────────────────────────────────────────
# NOTIFICATIONS TELEGRAM (optionnel)
# ─────────────────────────────────────────────

# Token du bot Telegram (obtenu via @BotFather)
# Laisser vide pour désactiver les notifications
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Chat ID Telegram (votre ID personnel ou un groupe)
# Récupérable via https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Timeout des requêtes Telegram (secondes)
TELEGRAM_TIMEOUT: int = int(os.getenv("TELEGRAM_TIMEOUT", "5"))

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

# Niveau de log : DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Chemin du fichier de log (doit être accessible en écriture)
LOG_FILE: str = os.getenv("LOG_FILE", "/var/log/usg-watchdog.log")
