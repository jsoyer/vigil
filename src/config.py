"""
Configuration du USG Watchdog.
Toutes les valeurs peuvent etre surchargees via variables d'environnement.
"""

import ipaddress
import logging
import os


def _get_env(*names: str, default: str) -> str:
    """Retourne la premiere variable d'environnement non vide."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _get_int_env(*names: str, default: int, minimum: int = 1) -> int:
    """Retourne une variable d'environnement convertie en entier avec validation."""
    raw = _get_env(*names, default=str(default))
    try:
        value = int(raw)
    except ValueError:
        logging.warning(
            "Valeur invalide '%s' pour %s, utilisation du defaut %d", raw, names, default
        )
        return default
    if value < minimum:
        logging.warning(
            "Valeur %d inferieure au minimum %d pour %s, utilisation de %d",
            value, minimum, names, minimum,
        )
        return minimum
    return value


# ---------------------------------------------
# CONNEXION -- Cibles de ping
# ---------------------------------------------

# Plusieurs cibles pour eviter les faux positifs (Google DNS, Cloudflare, Quad9)
PING_TARGETS: list[str] = [
    "8.8.8.8",  # Google DNS
    "1.1.1.1",  # Cloudflare DNS
    "9.9.9.9",  # Quad9 DNS
]

# Timeout ping en secondes
PING_TIMEOUT: int = _get_int_env("PING_TIMEOUT", default=3)

# ---------------------------------------------
# SCORING -- Logique de surveillance
# ---------------------------------------------

# Delai entre chaque check (secondes)
CHECK_INTERVAL: int = _get_int_env(
    "CHECK_INTERVAL", "WATCHDOG_CHECK_INTERVAL", default=30, minimum=5
)

# Seuil de score pour declencher un reboot
# Score monte sur probleme, descend quand tout va bien
REBOOT_SCORE_THRESHOLD: int = _get_int_env(
    "REBOOT_SCORE_THRESHOLD", default=10, minimum=3
)

# Score maximum (plafond pour eviter l'accumulation infinie)
MAX_SCORE: int = _get_int_env("MAX_SCORE", default=15, minimum=5)

# Points par type de probleme
SCORE_GATEWAY_DOWN: int = _get_int_env("SCORE_GATEWAY_DOWN", default=4, minimum=1)
SCORE_INTERNET_ALL_DOWN: int = _get_int_env("SCORE_INTERNET_ALL_DOWN", default=3, minimum=1)
SCORE_INTERNET_PARTIAL: int = _get_int_env("SCORE_INTERNET_PARTIAL", default=1, minimum=0)

# Points de recuperation (valeurs positives, appliquees en negatif)
SCORE_DECAY_OK: int = _get_int_env("SCORE_DECAY_OK", default=2, minimum=1)
SCORE_DECAY_PARTIAL: int = _get_int_env("SCORE_DECAY_PARTIAL", default=1, minimum=0)

# Grace post-reboot (secondes)
# Pendant cette periode, les echecs sont ignores pour laisser le USG se stabiliser
# 360s = 6 minutes
POST_REBOOT_GRACE: int = _get_int_env(
    "POST_REBOOT_GRACE", "WATCHDOG_POST_REBOOT_GRACE", default=360, minimum=30
)

# Cooldown apres un reboot (secondes)
# Empeche un nouveau reboot meme si le score remonte
# Sert de base pour le backoff exponentiel
# 900s = 15 minutes
REBOOT_COOLDOWN: int = _get_int_env(
    "REBOOT_COOLDOWN", "WATCHDOG_REBOOT_COOLDOWN", default=900, minimum=60
)

# Cooldown maximum apres backoff exponentiel (secondes)
# 14400s = 4 heures
MAX_REBOOT_COOLDOWN: int = _get_int_env(
    "MAX_REBOOT_COOLDOWN", default=14400, minimum=900
)

# Nombre maximum de reboots par jour
# Au-dela, le watchdog passe en mode surveillance (plus de reboot)
MAX_REBOOTS_PER_DAY: int = _get_int_env("MAX_REBOOTS_PER_DAY", default=10, minimum=1)

# ---------------------------------------------
# CIRCUIT BREAKER -- Backoff SSH
# ---------------------------------------------

# Nombre d'echecs SSH avant d'activer le backoff
SSH_FAILURE_BACKOFF_START: int = _get_int_env("SSH_FAILURE_BACKOFF_START", default=3, minimum=1)

# Cooldown SSH apres backoff (secondes)
# Multiplie par 2 a chaque palier (3 echecs: 300s, 6: 600s, 10: 1200s, cap 3600s)
SSH_FAILURE_COOLDOWN: int = _get_int_env("SSH_FAILURE_COOLDOWN", default=300, minimum=60)

# Cooldown SSH maximum (secondes) -- 3600s = 1 heure
MAX_SSH_COOLDOWN: int = _get_int_env("MAX_SSH_COOLDOWN", default=3600, minimum=300)

# ---------------------------------------------
# DETECTION ISP -- Pattern gateway OK + internet KO
# ---------------------------------------------

# Duree (secondes) de "gw OK + inet KO" continu avant de declarer une panne ISP probable
# 1800s = 30 minutes
ISP_OUTAGE_DETECTION_DELAY: int = _get_int_env(
    "ISP_OUTAGE_DETECTION_DELAY", default=1800, minimum=300
)

# ---------------------------------------------
# UBIQUITI USG -- Connexion SSH
# ---------------------------------------------

# IP locale du USG (gateway LAN, aussi utilisee pour le ping gateway)
USG_IP: str = os.getenv("USG_IP", "192.168.1.1")
try:
    ipaddress.ip_address(USG_IP)
except ValueError:
    raise SystemExit(f"USG_IP invalide : '{USG_IP}' -- doit etre une adresse IP")

# Username SSH du USG
USG_USER: str = os.getenv("USG_USER", "maintenance")

# Chemin vers la cle SSH privee dediee (generee par scripts/setup_ssh.sh)
USG_SSH_KEY: str = os.getenv("USG_SSH_KEY", "/opt/usg-watchdog/.ssh/usg_ed25519")

# Fichier known_hosts pour verification de la cle hote du USG
USG_KNOWN_HOSTS: str = os.getenv(
    "USG_KNOWN_HOSTS", "/opt/usg-watchdog/.ssh/known_hosts"
)

# Mot de passe SSH (deconseille -- preferer la cle SSH)
USG_SSH_PASSWORD: str = os.getenv("USG_SSH_PASSWORD", "")

# Timeout de connexion SSH (secondes)
SSH_TIMEOUT: int = _get_int_env("SSH_TIMEOUT", default=10, minimum=3)

# Temps d'attente apres envoi du reboot (secondes)
USG_REBOOT_WAIT: int = _get_int_env("USG_REBOOT_WAIT", default=60, minimum=10)

# Commande de reboot a executer sur le USG
USG_REBOOT_COMMAND: str = os.getenv("USG_REBOOT_COMMAND", "sudo reboot")

# ---------------------------------------------
# NOTIFICATIONS TELEGRAM (optionnel)
# ---------------------------------------------

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_TIMEOUT: int = _get_int_env("TELEGRAM_TIMEOUT", default=5, minimum=2)
# Niveau minimum : INFO, WARNING, CRITICAL
TELEGRAM_MIN_LEVEL: str = os.getenv("TELEGRAM_MIN_LEVEL", "INFO")

# ---------------------------------------------
# NOTIFICATIONS DISCORD (optionnel)
# ---------------------------------------------

# URL du webhook Discord (Settings > Integrations > Webhooks)
DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_TIMEOUT: int = _get_int_env("DISCORD_TIMEOUT", default=5, minimum=2)
DISCORD_MIN_LEVEL: str = os.getenv("DISCORD_MIN_LEVEL", "INFO")

# ---------------------------------------------
# NOTIFICATIONS SLACK (optionnel)
# ---------------------------------------------

# URL du webhook Slack (api.slack.com > Incoming Webhooks)
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_TIMEOUT: int = _get_int_env("SLACK_TIMEOUT", default=5, minimum=2)
SLACK_MIN_LEVEL: str = os.getenv("SLACK_MIN_LEVEL", "INFO")

# ---------------------------------------------
# NOTIFICATIONS NTFY (optionnel)
# ---------------------------------------------

# URL du serveur Ntfy (cloud: https://ntfy.sh, self-hosted: http://pi:8080)
NTFY_URL: str = os.getenv("NTFY_URL", "")
# Topic Ntfy (ex: usg-watchdog)
NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "")
NTFY_TIMEOUT: int = _get_int_env("NTFY_TIMEOUT", default=5, minimum=2)
NTFY_MIN_LEVEL: str = os.getenv("NTFY_MIN_LEVEL", "INFO")

# ---------------------------------------------
# MQTT / HOME ASSISTANT (optionnel)
# ---------------------------------------------

# Adresse du broker MQTT (vide = desactive)
MQTT_BROKER: str = os.getenv("MQTT_BROKER", "")
MQTT_PORT: int = _get_int_env("MQTT_PORT", default=1883, minimum=1)
MQTT_TOPIC_PREFIX: str = os.getenv("MQTT_TOPIC_PREFIX", "usg-watchdog")
MQTT_USERNAME: str = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD", "")
# Envoyer les configs auto-discovery Home Assistant
MQTT_HA_DISCOVERY: bool = os.getenv("MQTT_HA_DISCOVERY", "true").lower() in ("true", "1", "yes")

# ---------------------------------------------
# DDNS CLOUDFLARE (optionnel)
# ---------------------------------------------

# Token API Cloudflare (Zone DNS edit)
CLOUDFLARE_API_TOKEN: str = os.getenv("CLOUDFLARE_API_TOKEN", "")
# Zone ID (visible sur la page overview du domaine dans Cloudflare)
CLOUDFLARE_ZONE_ID: str = os.getenv("CLOUDFLARE_ZONE_ID", "")
# Records A a mettre a jour (separes par des virgules)
CLOUDFLARE_RECORD_NAMES: str = os.getenv("CLOUDFLARE_RECORD_NAMES", "")
# Utiliser le proxy Cloudflare (true/false)
CLOUDFLARE_PROXIED: bool = os.getenv("CLOUDFLARE_PROXIED", "false").lower() in ("true", "1", "yes")
# TTL en secondes (120-7200, ou 1 pour auto)
CLOUDFLARE_TTL: int = _get_int_env("CLOUDFLARE_TTL", default=120, minimum=1)
# Intervalle de check periodique DDNS (secondes, defaut 1800s = 30 min)
# Couvre le cas rare du renouvellement DHCP FAI sans coupure.
# Le check force au retablissement gere les coupures/reboots.
DDNS_CHECK_INTERVAL: int = _get_int_env("DDNS_CHECK_INTERVAL", default=1800, minimum=60)

# ---------------------------------------------
# COORDINATION PEER (optionnel)
# ---------------------------------------------

# Priorite de l'instance (1 = primary, 2 = secondary)
# Le primary agit en premier, le secondary prend le relais si le primary est KO
INSTANCE_PRIORITY: int = _get_int_env("INSTANCE_PRIORITY", default=1, minimum=1)

# IP de l'autre instance (vide = mode standalone, pas de coordination)
PEER_IP: str = os.getenv("PEER_IP", "")
if PEER_IP:
    try:
        ipaddress.ip_address(PEER_IP)
    except ValueError:
        raise SystemExit(f"PEER_IP invalide : '{PEER_IP}' -- doit etre une adresse IP")

# Port HTTP du peer et de cette instance
PEER_PORT: int = _get_int_env("PEER_PORT", default=9000, minimum=1024)
HTTP_PORT: int = _get_int_env("HTTP_PORT", default=9000, minimum=1024)

# Delai avant que le secondary prenne le relais (secondes)
# Doit etre >= SSH_TIMEOUT + USG_REBOOT_WAIT + marge
# 180s = 3 minutes
PEER_TAKEOVER_DELAY: int = _get_int_env("PEER_TAKEOVER_DELAY", default=180, minimum=60)

# ---------------------------------------------
# RAPPORT QUOTIDIEN
# ---------------------------------------------

# Heure d'envoi du rapport quotidien (0-23, defaut 8h)
# Mettre -1 pour desactiver
DAILY_REPORT_HOUR: int = _get_int_env("DAILY_REPORT_HOUR", default=8, minimum=-1)

# Jour d'envoi du rapport hebdomadaire (0=lundi, 6=dimanche, -1=desactive)
WEEKLY_REPORT_DAY: int = _get_int_env("WEEKLY_REPORT_DAY", default=0, minimum=-1)

# ---------------------------------------------
# LOGGING
# ---------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", "/var/log/usg-watchdog.log")
