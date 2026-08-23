"""
Configuration de Vigil.
Toutes les valeurs peuvent etre surchargees via variables d'environnement.
"""

import ipaddress
import logging
import os
import socket
from dataclasses import dataclass


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
            "Valeur invalide '%s' pour %s, utilisation du defaut %d",
            raw,
            names,
            default,
        )
        return default
    if value < minimum:
        logging.warning(
            "Valeur %d inferieure au minimum %d pour %s, utilisation de %d",
            value,
            minimum,
            names,
            minimum,
        )
        return minimum
    return value


def _resolve_install_path(new_default: str, old_default: str) -> str:
    """Resout un chemin par defaut avec repli de compatibilite pendant la
    migration progressive /opt/usg-watchdog -> /opt/vigil (PRD 2.0.0).

    Si /opt/vigil existe, utilise le nouveau chemin (meme si l'ancien
    /opt/usg-watchdog existe aussi). Si /opt/vigil est absent et
    /opt/usg-watchdog present, retombe sur l'ancien chemin -- le service
    demarre au lieu de tomber en boucle de redemarrage sur une machine
    partiellement migree. Si aucun des deux n'existe (ex. environnement de
    dev), utilise le nouveau chemin.

    Repli temporaire : retrait prevu en 2.1.0, pas dans ce PRD.
    """
    if os.path.isdir("/opt/vigil"):
        return new_default
    if os.path.isdir("/opt/usg-watchdog"):
        return old_default
    return new_default


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
SCORE_INTERNET_ALL_DOWN: int = _get_int_env(
    "SCORE_INTERNET_ALL_DOWN", default=3, minimum=1
)
SCORE_INTERNET_PARTIAL: int = _get_int_env(
    "SCORE_INTERNET_PARTIAL", default=1, minimum=0
)

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
SSH_FAILURE_BACKOFF_START: int = _get_int_env(
    "SSH_FAILURE_BACKOFF_START", default=3, minimum=1
)

# Cooldown SSH apres backoff (secondes)
# Multiplie par 2 a chaque palier (3 echecs: 300s, 6: 600s, 10: 1200s, cap 3600s)
SSH_FAILURE_COOLDOWN: int = _get_int_env(
    "SSH_FAILURE_COOLDOWN", default=300, minimum=60
)

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
# Auto-detection : ed25519 en priorite, fallback sur rsa si absent
def _detect_ssh_key() -> str:
    explicit = os.getenv("USG_SSH_KEY", "")
    if explicit:
        return explicit
    ssh_dir = _resolve_install_path("/opt/vigil/.ssh", "/opt/usg-watchdog/.ssh")
    for name in ("usg_ed25519", "usg_rsa", "id_ed25519", "id_rsa"):
        path = f"{ssh_dir}/{name}"
        if os.path.isfile(path):
            return path
    return f"{ssh_dir}/usg_ed25519"


USG_SSH_KEY: str = _detect_ssh_key()

# Fichier known_hosts pour verification de la cle hote du USG
USG_KNOWN_HOSTS: str = os.getenv(
    "USG_KNOWN_HOSTS",
    _resolve_install_path(
        "/opt/vigil/.ssh/known_hosts", "/opt/usg-watchdog/.ssh/known_hosts"
    ),
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
# NOTIFICATIONS NTFY (optionnel)
# ---------------------------------------------

# URL du serveur Ntfy (cloud: https://ntfy.sh, self-hosted: http://pi:8080)
NTFY_URL: str = os.getenv("NTFY_URL", "")
# Topic Ntfy de site (ex: vigil-dijon, vigil-nice) -- alertes de ligne
NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "")
NTFY_TIMEOUT: int = _get_int_env("NTFY_TIMEOUT", default=5, minimum=2)
NTFY_MIN_LEVEL: str = os.getenv("NTFY_MIN_LEVEL", "INFO")
# Jeton d'authentification Ntfy (Authorization: Bearer). Vide = publication
# anonyme (comportement inchange par rapport a 2.1.0 si le serveur cible
# l'autorise). Ne jamais journaliser cette valeur.
NTFY_TOKEN: str = os.getenv("NTFY_TOKEN", "")
# Topic Ntfy pour les evenements de cycle de vie (demarrage, arret,
# sauvegardes, maintenance, rapports) -- distinct du topic de site pour
# permettre de couper le bruit operationnel sans perdre les alertes de ligne.
NTFY_TOPIC_OPS: str = os.getenv("NTFY_TOPIC_OPS", "vigil-ops")

# ---------------------------------------------
# NOTIFICATIONS EMAIL SMTP (optionnel)
# ---------------------------------------------

SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = _get_int_env("SMTP_PORT", default=587, minimum=1)
SMTP_FROM: str = os.getenv("SMTP_FROM", "")
SMTP_TO: str = os.getenv("SMTP_TO", "")
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_TIMEOUT: int = _get_int_env("SMTP_TIMEOUT", default=10, minimum=2)
SMTP_MIN_LEVEL: str = os.getenv("SMTP_MIN_LEVEL", "WARNING")

# ---------------------------------------------
# ESCALADE D'ALERTES (optionnel)
# ---------------------------------------------

# Activer l'escalade (true/false)
ALERT_ESCALATION_ENABLED: bool = os.getenv(
    "ALERT_ESCALATION_ENABLED", "false"
).lower() in ("true", "1", "yes")
# Delai avant escalade (minutes)
ALERT_ESCALATION_DELAY: int = _get_int_env(
    "ALERT_ESCALATION_DELAY", default=15, minimum=5
)

# ---------------------------------------------
# API AUTHENTICATION (optionnel mais recommande)
# ---------------------------------------------

# Token d'authentification pour les endpoints POST
# Si vide, les endpoints POST sont ouverts (LAN only)
API_TOKEN: str = os.getenv("API_TOKEN", "")

# ---------------------------------------------
# CONFIRMATION A CAPACITE -- POST /api/confirm/<action>/<jeton> (Ntfy-first
# S2). Seul endpoint POST exempte de API_TOKEN (l'autorisation est le jeton
# lui-meme) -- D3 impose donc un rate limiting dedie, en memoire, par IP.
# ---------------------------------------------

# Nombre de tentatives echouees (jeton invalide/expire/action erronee)
# tolerees par IP dans la fenetre glissante avant reponse 429 + evenement
# `confirm_bruteforce`. D3 du PRD Ntfy-first exige un minimum de 10/minute.
CONFIRM_RATE_LIMIT_MAX_FAILURES: int = _get_int_env(
    "CONFIRM_RATE_LIMIT_MAX_FAILURES", default=10, minimum=1
)
# Fenetre glissante (secondes) sur laquelle les echecs sont comptes par IP.
CONFIRM_RATE_LIMIT_WINDOW: int = _get_int_env(
    "CONFIRM_RATE_LIMIT_WINDOW", default=60, minimum=1
)

# ---------------------------------------------
# IDENTITE DE L'INSTANCE
# ---------------------------------------------


def _normalize_instance_id(raw: str) -> str:
    """Normalise un identifiant d'instance pour usage MQTT / Home Assistant.

    Minuscules, tout caractere non alphanumerique ASCII devient '_' (les
    lettres accentuees, CJK, etc. sont donc aussi remplacees -- ce fichier
    est volontairement ASCII-only, et les unique_id / topics MQTT ne
    doivent contenir que des caracteres ASCII), les '_' consecutifs sont
    collapses puis retires en debut/fin. Si le resultat est vide, retombe
    sur 'vigil' pour garantir un identifiant toujours non vide.

    Limite connue et acceptee : deux hostnames qui ne different que par
    leur separateur (ex: "pi-dijon" et "pi_dijon", ou "site.master" et
    "site_master") normalisent vers le meme INSTANCE_ID. Ce n'est pas
    corrige ici -- ca demanderait un schema d'encodage reversible, pour un
    risque nul en pratique : les 4 hostnames de production (dijon/nice x
    master/slave) sont lexicalement distincts independamment du separateur.
    """
    chars = [c if c.isascii() and c.isalnum() else "_" for c in raw.lower()]
    normalized = "".join(chars)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    normalized = normalized.strip("_")
    return normalized or "vigil"


# Identifiant unique de cette instance (site + role), utilise pour distinguer
# plusieurs deploiements sur le meme broker MQTT / la meme instance Home
# Assistant (ex: Dijon master, Dijon slave, Nice master, Nice slave).
# Defaut : derive du hostname, pour qu'une instance non configuree obtienne
# malgre tout une identite distincte des autres -- corriger le bug de
# collision ne doit pas exiger d'action manuelle sur chaque instance.
INSTANCE_ID: str = _normalize_instance_id(
    _get_env("INSTANCE_ID", default=socket.gethostname())
)


# Suffixes de role connus (les 4 instances de production : dijon/nice x
# master/slave). Utilise pour deriver un identifiant de SITE par defaut a
# partir de l'INSTANCE_ID -- deux instances d'un meme site (master+slave)
# doivent produire le meme SITE_ID pour partager un seul device Home
# Assistant par equipement physique (C12/C15, Sprint 3 A2).
_ROLE_SUFFIXES: tuple[str, ...] = ("_master", "_slave", "_primary", "_secondary")


def _default_site_id(instance_id: str) -> str:
    """Derive un identifiant de site depuis un INSTANCE_ID deja normalise,
    en retirant un suffixe de role connu en fin de chaine. Retombe sur
    l'INSTANCE_ID complet si aucun suffixe connu n'est trouve (deploiement
    standalone, un seul watchdog par site) -- jamais de chaine vide."""
    for suffix in _ROLE_SUFFIXES:
        if instance_id.endswith(suffix):
            stripped = instance_id[: -len(suffix)]
            if stripped:
                return stripped
    return instance_id


# Identifiant de site (regroupe les instances master/slave d'un meme site
# et l'equipement physique -- TP-Link ou USG -- qu'elles partagent). Defaut :
# INSTANCE_ID prive de son suffixe de role connu, pour qu'un deploiement
# existant (sans variable SITE_ID) obtienne malgre tout un identifiant de
# site coherent entre les deux instances d'un site, sans configuration
# manuelle (meme philosophie que INSTANCE_ID -- voir _normalize_instance_id).
SITE_ID: str = _normalize_instance_id(
    _get_env("SITE_ID", default=_default_site_id(INSTANCE_ID))
)

# ---------------------------------------------
# MQTT / HOME ASSISTANT (optionnel)
# ---------------------------------------------

# Adresse du broker MQTT (vide = desactive)
MQTT_BROKER: str = os.getenv("MQTT_BROKER", "")
MQTT_PORT: int = _get_int_env("MQTT_PORT", default=1883, minimum=1)
MQTT_TOPIC_PREFIX: str = os.getenv("MQTT_TOPIC_PREFIX", "vigil")
MQTT_USERNAME: str = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD", "")
# Envoyer les configs auto-discovery Home Assistant
MQTT_HA_DISCOVERY: bool = os.getenv("MQTT_HA_DISCOVERY", "true").lower() in (
    "true",
    "1",
    "yes",
)

# ---------------------------------------------
# MQTT -- CHEMIN DE COMMANDE ENTRANT (Sprint 3 A2, C9)
# ---------------------------------------------
#
# C9 : le `subscribe` MQTT introduit ici est la premiere surface d'attaque
# entrante du projet -- quiconque publie sur le broker peut declencher une
# action si l'ecoute est active. EXIGENCE NON VERIFIEE AU DEMARRAGE (pas de
# validation croisee bloquante ici, volontairement -- un deploiement de test
# local sur broker anonyme ne doit pas etre empeche de demarrer) : le
# broker MQTT **doit** etre authentifie (MQTT_USERNAME/MQTT_PASSWORD
# renseignes) avant d'activer MQTT_COMMANDS_ENABLED. C'est a l'operateur de
# le garantir -- voir README/DEPLOY pour la procedure. Le code cote
# publisher (mqtt_publisher.py) refuse neanmoins de s'abonner si
# MQTT_COMMANDS_ENABLED=true mais MQTT_USERNAME est vide (defense en
# profondeur, jamais une garantie a elle seule : un broker peut exiger un
# mot de passe uniquement cote serveur, invisible d'ici).

# Active l'ecoute des topics de commande (switch armer + button reboot).
# Desactivable independamment de la publication (MQTT_HA_DISCOVERY) : un
# deploiement peut vouloir les capteurs sans le chemin de commande.
MQTT_COMMANDS_ENABLED: bool = os.getenv("MQTT_COMMANDS_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)

# Delai (secondes) avant desarmement automatique de l'entite "armer le
# reboot" -- equivalent MQTT de la confirmation en deux temps (A1 utilisait
# un jeton Telegram, retire en 2.2.0). Court par defaut : le geste d'armer
# puis presser le bouton doit rester un seul enchainement operateur, pas une
# fenetre ouverte toute la journee.
MQTT_ARM_TIMEOUT: int = _get_int_env("MQTT_ARM_TIMEOUT", default=30, minimum=5)

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
CLOUDFLARE_PROXIED: bool = os.getenv("CLOUDFLARE_PROXIED", "false").lower() in (
    "true",
    "1",
    "yes",
)
# TTL en secondes (120-7200, ou 1 pour auto)
CLOUDFLARE_TTL: int = _get_int_env("CLOUDFLARE_TTL", default=120, minimum=1)
# Intervalle de check periodique DDNS (secondes, defaut 1800s = 30 min)
# Couvre le cas rare du renouvellement DHCP FAI sans coupure.
# Le check force au retablissement gere les coupures/reboots.
DDNS_CHECK_INTERVAL: int = _get_int_env("DDNS_CHECK_INTERVAL", default=1800, minimum=60)

# ---------------------------------------------
# TAILSCALE DNS SYNC (optionnel)
# ---------------------------------------------

# API key Tailscale (tskey-api-...)
TAILSCALE_API_KEY: str = os.getenv("TAILSCALE_API_KEY", "")
# Tailnet (email ou nom d'org)
TAILSCALE_TAILNET: str = os.getenv("TAILSCALE_TAILNET", "")
# Sous-domaine pour les records (ex: "ts" pour hostname.ts.bbhome.wf, vide = hostname.bbhome.wf)
TAILSCALE_DNS_SUBDOMAIN: str = os.getenv("TAILSCALE_DNS_SUBDOMAIN", "")
# Prefix/postfix pour les hostnames
TAILSCALE_DNS_PREFIX: str = os.getenv("TAILSCALE_DNS_PREFIX", "")
TAILSCALE_DNS_POSTFIX: str = os.getenv("TAILSCALE_DNS_POSTFIX", "")
# Intervalle de sync (secondes, defaut 600s = 10 min)
TAILSCALE_SYNC_INTERVAL: int = _get_int_env(
    "TAILSCALE_SYNC_INTERVAL", default=600, minimum=60
)

# ---------------------------------------------
# BACKUP UNIFI (optionnel)
# ---------------------------------------------

# Repertoire des backups auto UniFi (vide = desactive)
UNIFI_BACKUP_DIR: str = os.getenv("UNIFI_BACKUP_DIR", "")
# Destination rclone (ex: drive:Unifi, s3:bucket/prefix)
UNIFI_BACKUP_RCLONE_DEST: str = os.getenv("UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi")
# Retention en jours
UNIFI_BACKUP_RETENTION_DAYS: int = _get_int_env(
    "UNIFI_BACKUP_RETENTION_DAYS", default=30, minimum=1
)
# Heure du backup quotidien (0-23, -1=off)
UNIFI_BACKUP_SCHEDULE_HOUR: int = _get_int_env(
    "UNIFI_BACKUP_SCHEDULE_HOUR", default=4, minimum=-1
)
# Alerte si le dernier backup a plus de N heures
UNIFI_BACKUP_MAX_AGE_HOURS: int = _get_int_env(
    "UNIFI_BACKUP_MAX_AGE_HOURS", default=48, minimum=1
)

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
LOG_FILE: str = os.getenv(
    "LOG_FILE", _resolve_install_path("/var/log/vigil.log", "/var/log/usg-watchdog.log")
)


# ---------------------------------------------
# ISP STATUS PAGE (optionnel)
# ---------------------------------------------

# Activer la verification des pages statut FAI (true/false)
ISP_STATUS_ENABLED: bool = os.getenv("ISP_STATUS_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
# Intervalle de verification en cycles (defaut 20 cycles = ~10 min a 30s/cycle)
ISP_STATUS_INTERVAL_CYCLES: int = _get_int_env(
    "ISP_STATUS_INTERVAL_CYCLES", default=20, minimum=5
)
# Surcharge des URLs FAI en JSON (ex: {"Free": "https://...", "Orange": "https://..."})
ISP_STATUS_URLS: str = os.getenv("ISP_STATUS_URLS", "")
# Timeout HTTP pour chaque page (secondes)
ISP_STATUS_TIMEOUT: int = _get_int_env("ISP_STATUS_TIMEOUT", default=10, minimum=3)

# ---------------------------------------------
# TP-LINK MR110 -- lignes de secours 4G (A1, optionnel)
# ---------------------------------------------

# Equipements numerotes TPLINK_<n>_* (n = 1, 2, ... contigus). Aucune
# variable TPLINK_1_HOST declaree => aucun equipement TP-Link actif et le
# comportement du watchdog reste strictement celui de la 2.0 -- voir
# INVARIANTS.md, "Aucun equipement declare => comportement identique a la 1.8".
# Voir docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/ pour le
# contexte complet (contrat RouterDriver, TplinkDriver, C16).


@dataclass(frozen=True)
class TplinkDeviceConfig:
    """Configuration d'un equipement TP-Link MR110, une entree par index."""

    index: int
    label: str
    host: str
    password: str
    mode: str  # "bridged" | "remote" -- C16, decision du 2026-08-23
    bridge_host: str  # utilise seulement en mode "remote"
    rsrp_min: int
    rsrq_min: int
    snr_min: int
    quota_volume_mb: int | None = None
    quota_alert_pct: int = 80
    quota_reset_day: int = 1
    probe_enabled: bool = False
    probe_interval: int = 3600
    usage_traffic_floor_bps: int | None = None


def _load_tplink_devices() -> tuple[TplinkDeviceConfig, ...]:
    """Parse TPLINK_<n>_* pour n = 1, 2, ... jusqu'au premier index sans HOST.

    Numerotation strictement contigue : un trou (TPLINK_2_HOST absent alors
    que TPLINK_3_HOST existe) arrete le parsing -- ce qui suit TPLINK_3_*
    n'est pas lu. Defauts surs : mode "bridged" si absent/invalide, seuils
    de signal coherents avec le spike (voir tplink.py pour la justification
    detaillee, en particulier du SNR).
    """
    devices: list[TplinkDeviceConfig] = []
    index = 1
    while True:
        host = os.getenv(f"TPLINK_{index}_HOST", "")
        if not host:
            break

        label = _get_env(f"TPLINK_{index}_LABEL", default=f"tplink-{index}")
        password = os.getenv(f"TPLINK_{index}_PASSWORD", "")

        mode = _get_env(f"TPLINK_{index}_MODE", default="bridged").strip().lower()
        if mode not in ("bridged", "remote"):
            logging.warning(
                "TPLINK_%d_MODE invalide ('%s'), repli sur 'bridged'", index, mode
            )
            mode = "bridged"

        bridge_host = os.getenv(f"TPLINK_{index}_BRIDGE_HOST", "")

        # RSRP : coherent avec les valeurs mesurees au spike (-99 Dijon,
        # -103 Nice, service fonctionnel) -- -110 dBm = seuil LTE standard
        # "limite utilisable". Voir docs/spikes/2026-08-23-mr110-compat.md.
        rsrp_min = _get_int_env(f"TPLINK_{index}_RSRP_MIN", default=-110, minimum=-140)
        # RSRQ : marge sur les valeurs observees au spike (-14 Dijon, -18
        # Nice, toutes deux fonctionnelles).
        rsrq_min = _get_int_env(f"TPLINK_{index}_RSRQ_MIN", default=-20, minimum=-30)
        # SNR : echelle du firmware douteuse au spike (-20 Dijon, -70 Nice,
        # deux liens pourtant fonctionnels) -- seuil tres conservateur par
        # defaut pour ne jamais declencher de faux DEGRADED tant que
        # l'unite exacte n'est pas confirmee sur le terrain. Voir
        # src/drivers/tplink.py (readiness()) pour la justification complete.
        snr_min = _get_int_env(f"TPLINK_{index}_SNR_MIN", default=-100, minimum=-200)

        quota_volume_raw = os.getenv(f"TPLINK_{index}_QUOTA_VOLUME_MB", "")
        quota_volume_mb: int | None = None
        if quota_volume_raw:
            try:
                parsed = int(quota_volume_raw)
                if parsed > 0:
                    quota_volume_mb = parsed
                else:
                    logging.warning(
                        "TPLINK_%d_QUOTA_VOLUME_MB invalide (%s), quota desactive",
                        index,
                        quota_volume_raw,
                    )
            except ValueError:
                logging.warning(
                    "TPLINK_%d_QUOTA_VOLUME_MB invalide (%s), quota desactive",
                    index,
                    quota_volume_raw,
                )

        quota_alert_pct = _get_int_env(
            f"TPLINK_{index}_QUOTA_ALERT_PCT", default=80, minimum=1
        )
        quota_reset_day = _get_int_env(
            f"TPLINK_{index}_QUOTA_RESET_DAY", default=1, minimum=1
        )

        probe_enabled = _get_env(
            f"TPLINK_{index}_PROBE_ENABLED", default="false"
        ).strip().lower() in ("1", "true", "yes", "on")
        probe_interval = _get_int_env(
            f"TPLINK_{index}_PROBE_INTERVAL", default=3600, minimum=60
        )

        # Plancher de trafic "in_use" (bugfix production 2.3.0) -- surcharge
        # optionnelle en kb/s du plancher module (USAGE_TRAFFIC_FLOOR_BPS,
        # managed_devices.py). Absent => defaut module. Invalide => defaut
        # module, jamais un plancher a 0 qui reintroduirait le bug (`in_use`
        # sur le bruit de gestion).
        usage_floor_raw = os.getenv(f"TPLINK_{index}_USAGE_FLOOR_KBPS", "")
        usage_traffic_floor_bps: int | None = None
        if usage_floor_raw:
            try:
                parsed_floor = int(usage_floor_raw)
                if parsed_floor > 0:
                    usage_traffic_floor_bps = parsed_floor * 1_000
                else:
                    logging.warning(
                        "TPLINK_%d_USAGE_FLOOR_KBPS invalide (%s), "
                        "plancher par defaut conserve",
                        index,
                        usage_floor_raw,
                    )
            except ValueError:
                logging.warning(
                    "TPLINK_%d_USAGE_FLOOR_KBPS invalide (%s), "
                    "plancher par defaut conserve",
                    index,
                    usage_floor_raw,
                )

        devices.append(
            TplinkDeviceConfig(
                index=index,
                label=label,
                host=host,
                password=password,
                mode=mode,
                bridge_host=bridge_host,
                rsrp_min=rsrp_min,
                rsrq_min=rsrq_min,
                snr_min=snr_min,
                quota_volume_mb=quota_volume_mb,
                quota_alert_pct=quota_alert_pct,
                quota_reset_day=quota_reset_day,
                probe_enabled=probe_enabled,
                probe_interval=probe_interval,
                usage_traffic_floor_bps=usage_traffic_floor_bps,
            )
        )
        index += 1

    return tuple(devices)


TPLINK_DEVICES: tuple[TplinkDeviceConfig, ...] = _load_tplink_devices()

# ---------------------------------------------
# VALIDATION CROISEE
# ---------------------------------------------


# ---------------------------------------------
# MASQUAGE DE SECRETS -- helper reutilisable (A1, Sprint 3, 3.4)
# ---------------------------------------------------------------------------

# Motifs de nom de variable consideres secrets. Couvre les secrets
# existants (SMTP_PASSWORD, NTFY_TOKEN, CLOUDFLARE_API_TOKEN, API_TOKEN,
# etc.) ainsi que TPLINK_<n>_PASSWORD -- pas seulement TP-Link, tout secret
# futur suivant cette convention de nommage en beneficie automatiquement.
_SECRET_NAME_SUFFIXES = ("_PASSWORD", "_TOKEN", "_KEY", "_WEBHOOK_URL")


def redact_secrets(data: dict) -> dict:
    """Retourne une copie de `data` avec les valeurs dont le nom de cle se
    termine par un motif de secret connu (`_PASSWORD`, `_TOKEN`, `_KEY`,
    `_WEBHOOK_URL`, insensible a la casse) remplacees par un marqueur.
    N'altere jamais l'entree. Les valeurs deja vides/falsy restent telles
    quelles (rien a masquer, et ca evite de laisser croire qu'un secret est
    configure alors qu'il ne l'est pas)."""
    redacted: dict = {}
    for key, value in data.items():
        if (
            isinstance(key, str)
            and key.upper().endswith(_SECRET_NAME_SUFFIXES)
            and value
        ):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def validate() -> list[str]:
    """Valide la coherence entre les parametres. Appele au demarrage."""
    errors: list[str] = []
    if MAX_SCORE < REBOOT_SCORE_THRESHOLD:
        errors.append(
            f"MAX_SCORE ({MAX_SCORE}) < REBOOT_SCORE_THRESHOLD ({REBOOT_SCORE_THRESHOLD})"
        )
    if MAX_REBOOT_COOLDOWN < REBOOT_COOLDOWN:
        errors.append(
            f"MAX_REBOOT_COOLDOWN ({MAX_REBOOT_COOLDOWN}) < REBOOT_COOLDOWN ({REBOOT_COOLDOWN})"
        )
    if DAILY_REPORT_HOUR > 23:
        errors.append(f"DAILY_REPORT_HOUR ({DAILY_REPORT_HOUR}) > 23")
    if WEEKLY_REPORT_DAY > 6:
        errors.append(f"WEEKLY_REPORT_DAY ({WEEKLY_REPORT_DAY}) > 6")
    if LOG_LEVEL.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        errors.append(f"LOG_LEVEL invalide : '{LOG_LEVEL}'")
    for device in TPLINK_DEVICES:
        if not device.password:
            errors.append(
                f"TPLINK_{device.index}_PASSWORD absent (equipement '{device.label}')"
            )
        try:
            ipaddress.ip_address(device.host)
        except ValueError:
            errors.append(f"TPLINK_{device.index}_HOST invalide : '{device.host}'")
        if device.mode == "remote" and not device.bridge_host:
            errors.append(
                f"TPLINK_{device.index}_MODE=remote mais "
                f"TPLINK_{device.index}_BRIDGE_HOST absent"
            )
        elif device.bridge_host:
            try:
                ipaddress.ip_address(device.bridge_host)
            except ValueError:
                errors.append(
                    f"TPLINK_{device.index}_BRIDGE_HOST invalide : "
                    f"'{device.bridge_host}'"
                )
    return errors
