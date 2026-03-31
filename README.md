# USG Watchdog v1.7.0

Daemon de surveillance de connexion internet et redémarrage automatique du routeur Ubiquiti USG, fonctionnant sur Raspberry Pi ou Linux. Conçu pour les connexions fibre instables avec détection intelligente des pannes ISP, coordination multi-instance et notifications multi-canaux (7 canaux supportés).

**Version de production : v1.7.0**

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Installation rapide](#installation-rapide)
- [Configuration complète](#configuration-complète)
- [Système de scoring](#système-de-scoring)
- [Circuit breaker](#circuit-breaker)
- [7 Canaux de notification](#7-canaux-de-notification)
- [Commandes Telegram Bot](#commandes-telegram-bot)
- [API HTTP complète](#api-http-complète)
- [Dashboard PWA](#dashboard-pwa)
- [Fonctionnalités avancées](#fonctionnalités-avancées)
- [Coordination haute disponibilité](#coordination-haute-disponibilité)
- [Dépannage](#dépannage)

---

## Vue d'ensemble

Le projet surveille deux éléments clés toutes les 30 secondes (configurable) :

- **Gateway LAN** : Le routeur USG répond-il au ping ?
- **Internet** : Trois cibles externes (Google DNS, Cloudflare, Quad9) répondent-elles ?

Un système de **scoring** avec circuit breaker décide automatiquement de redémarrer le USG, en tenant compte de la fréquence des défaillances, des pannes ISP détectées et des limites quotidiennes de redémarrage.

### Caractéristiques principales de v1.7.0

- **Scoring intelligent** : Pas de simple seuil. Points pour gateway KO, points pour internet partiel/KO, récupération quand tout va bien
- **Circuit breaker complet** : Backoff exponentiel, limite de 10 reboots/jour, détection de panne ISP, backoff SSH
- **7 Canaux de notification** : Telegram, Discord, Slack, Ntfy, Email SMTP, Pushover, MQTT/Home Assistant
- **Telegram Bot interactif** : Commandes /status, /pause, /resume, /reboot, /ddns, /backup, /tailscale, /help
- **Haute disponibilité** : Coordination multi-instance avec failover basé sur priorité, détection de divergence
- **API HTTP complète** : État complet, historique d'événements, configuration, rapports, maintenance
- **Dashboard responsive + PWA** : Interface web avec support offline, compatible mobile/tablette/desktop
- **Rapports quotidiens et hebdomadaires** : Synthèse des pannes, reboots et métriques SLA
- **Uptime SLA** : Calcul mensuel avec visualisation des coupures
- **DDNS Cloudflare** : Synchronisation automatique IP publique → DNS (remplace script shell externe)
- **Tailscale DNS Sync** : Intégration avec Tailscale DNS public
- **Backup UniFi automatisé** : Upload via rclone vers stockage remote (Google Drive, S3, etc.)
- **Monitoring multi-WAN** : Détection failover dual-WAN
- **Speedtest intégré** : Tests de débit périodiques (100KB) pour détection dégradation
- **Mesure de latence** : RTT gateway + internet, alerte si dégradation
- **Diagnostics traceroute** : Traceroute vers cibles ping sur demande Telegram
- **SNMP monitoring** : Lecture des métriques USG (CPU, mémoire, interfaces)
- **Métrique Prometheus** : Endpoint /metrics pour Grafana + dashboards prêts
- **Escalade d'alertes** : Re-envoi automatique via canaux prioritaires si pas d'ACK
- **Maintenance programmée** : Mode pause avec durée, accessible via API ou Telegram
- **Auto-updater** : Récupère les versions depuis GitHub, valide, déploie, rollback auto
- **Historique d'événements** : Ring buffer persisté (~100 événements) + export JSON

---

## Installation rapide

### Prérequis

- Raspberry Pi ou Linux (Fedora / Debian) avec systemd
- Python 3.11+
- SSH activé sur le USG (Settings > Device Authentication)
- (optionnel) Bot Telegram / Webhooks Discord/Slack / Compte Cloudflare

### 1. Cloner le dépôt

```bash
git clone https://github.com/jsoyer/usg-watchdog.git
cd usg-watchdog
```

### 2. Configurer SSH vers le USG

```bash
sudo ./scripts/setup_ssh.sh
```

Ce script :
- Génère une clé Ed25519 dans `/opt/usg-watchdog/.ssh/`
- Capture la clé hôte du USG (known_hosts)
- Déploie la clé publique sur le USG
- Teste la connexion sans mot de passe

### 3. Créer le fichier .env

```bash
sudo mkdir -p /opt/usg-watchdog
sudo nano /opt/usg-watchdog/.env
```

Configuration minimale :

```bash
# USG
USG_IP=192.168.1.1
USG_USER=maintenance

# Telegram (optionnel mais recommandé)
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHIjklmnoPQRstuvWXYz
TELEGRAM_CHAT_ID=987654321
```

Sécuriser le fichier :

```bash
sudo chmod 600 /opt/usg-watchdog/.env
```

### 4. Déployer

```bash
sudo ./scripts/deploy.sh
```

Ce script :
- Crée l'utilisateur système `usg-watchdog`
- Installe les fichiers et dépendances Python
- Configure le service systemd
- Démarre le watchdog

### 5. Vérifier

```bash
# Status du service
sudo systemctl status usg-watchdog

# Logs en temps réel
sudo journalctl -u usg-watchdog -f

# Health check
curl http://localhost:9000/health | python3 -m json.tool

# Dashboard
# Ouvrir http://192.168.1.50:9000/ dans un navigateur sur le LAN
```

### 6. (Recommandé) Installer l'auto-updater

```bash
sudo systemctl enable usg-watchdog-updater.timer
sudo systemctl start usg-watchdog-updater.timer
```

Le timer vérifie GitHub à 3h du matin chaque jour. Voir `DEPLOY.md` pour plus de détails.

---

## Configuration complète

Tous les paramètres peuvent être surchargés via variables d'environnement dans `/opt/usg-watchdog/.env` :

### Connexion et ping

| Variable | Défaut | Description |
|----------|--------|-------------|
| `USG_IP` | `192.168.1.1` | IP du routeur USG (gateway LAN) |
| `USG_USER` | `maintenance` | User SSH du USG |
| `USG_SSH_KEY` | `/opt/usg-watchdog/.ssh/usg_ed25519` | Chemin clé SSH privée |
| `USG_KNOWN_HOSTS` | `/opt/usg-watchdog/.ssh/known_hosts` | Fichier known_hosts |
| `PING_TIMEOUT` | `3` | Timeout ping en secondes |
| `SSH_TIMEOUT` | `10` | Timeout connexion SSH en secondes |

### Scoring et seuils

| Variable | Défaut | Description |
|----------|--------|-------------|
| `CHECK_INTERVAL` | `30` | Délai entre checks en secondes |
| `REBOOT_SCORE_THRESHOLD` | `10` | Score qui déclenche reboot |
| `MAX_SCORE` | `15` | Plafond du score |
| `SCORE_GATEWAY_DOWN` | `4` | Points si gateway KO |
| `SCORE_INTERNET_ALL_DOWN` | `3` | Points si internet 0/3 |
| `SCORE_INTERNET_PARTIAL` | `1` | Points si internet 1/3 |
| `SCORE_DECAY_OK` | `2` | Points récupérés si tout OK |
| `SCORE_DECAY_PARTIAL` | `1` | Points récupérés si 1/3 internet |

### Circuit breaker et reboots

| Variable | Défaut | Description |
|----------|--------|-------------|
| `POST_REBOOT_GRACE` | `360` | Durée grace post-reboot (secondes) |
| `REBOOT_COOLDOWN` | `900` | Base cooldown (15 min) |
| `MAX_REBOOT_COOLDOWN` | `14400` | Cooldown max après backoff (4 h) |
| `MAX_REBOOTS_PER_DAY` | `10` | Limite reboots/jour avant surveillance |
| `SSH_FAILURE_BACKOFF_START` | `3` | Échecs SSH avant backoff |
| `SSH_FAILURE_COOLDOWN` | `300` | Base cooldown SSH (5 min) |
| `MAX_SSH_COOLDOWN` | `3600` | Cooldown SSH max (1 h) |
| `ISP_OUTAGE_DETECTION_DELAY` | `1800` | Durée avant détection panne ISP (30 min) |
| `USG_REBOOT_WAIT` | `60` | Attente après envoi reboot (s) |

### Telegram (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | _(vide)_ | Token bot Telegram |
| `TELEGRAM_CHAT_ID` | _(vide)_ | Chat ID cible |
| `TELEGRAM_TIMEOUT` | `5` | Timeout requête (secondes) |
| `TELEGRAM_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Discord (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DISCORD_WEBHOOK_URL` | _(vide)_ | URL webhook Discord |
| `DISCORD_TIMEOUT` | `5` | Timeout requête (secondes) |
| `DISCORD_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Slack (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SLACK_WEBHOOK_URL` | _(vide)_ | URL webhook Slack |
| `SLACK_TIMEOUT` | `5` | Timeout requête (secondes) |
| `SLACK_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Ntfy (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `NTFY_URL` | _(vide)_ | URL serveur Ntfy (https://ntfy.sh ou self-hosted) |
| `NTFY_TOPIC` | _(vide)_ | Topic Ntfy |
| `NTFY_TIMEOUT` | `5` | Timeout requête (secondes) |
| `NTFY_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Email SMTP (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SMTP_HOST` | _(vide)_ | Serveur SMTP |
| `SMTP_PORT` | `587` | Port SMTP (TLS) |
| `SMTP_FROM` | _(vide)_ | Adresse e-mail source |
| `SMTP_TO` | _(vide)_ | Adresse e-mail destination |
| `SMTP_USERNAME` | _(vide)_ | Username SMTP |
| `SMTP_PASSWORD` | _(vide)_ | Password SMTP |
| `SMTP_TIMEOUT` | `10` | Timeout requête (secondes) |
| `SMTP_MIN_LEVEL` | `WARNING` | Niveau min : INFO, WARNING, CRITICAL |

### Pushover (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `PUSHOVER_USER_KEY` | _(vide)_ | User key Pushover |
| `PUSHOVER_API_TOKEN` | _(vide)_ | API token Pushover |
| `PUSHOVER_TIMEOUT` | `5` | Timeout requête (secondes) |
| `PUSHOVER_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### MQTT / Home Assistant (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `MQTT_BROKER` | _(vide)_ | Adresse broker MQTT (vide = désactivé) |
| `MQTT_PORT` | `1883` | Port MQTT |
| `MQTT_TOPIC_PREFIX` | `usg-watchdog` | Préfixe topics MQTT |
| `MQTT_USERNAME` | _(vide)_ | Username MQTT |
| `MQTT_PASSWORD` | _(vide)_ | Password MQTT |
| `MQTT_HA_DISCOVERY` | `true` | Envoyer configs auto-discovery Home Assistant |

### Escalade d'alertes (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `ALERT_ESCALATION_ENABLED` | `false` | Activer l'escalade |
| `ALERT_ESCALATION_DELAY` | `15` | Délai avant escalade (minutes) |

### DDNS Cloudflare (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `CLOUDFLARE_API_TOKEN` | _(vide)_ | Token API Cloudflare (Zone edit) |
| `CLOUDFLARE_ZONE_ID` | _(vide)_ | Zone ID Cloudflare |
| `CLOUDFLARE_RECORD_NAMES` | _(vide)_ | Records A à mettre à jour (virgules) |
| `CLOUDFLARE_PROXIED` | `false` | Utiliser proxy Cloudflare |
| `CLOUDFLARE_TTL` | `120` | TTL en secondes (120-7200, ou 1 = auto) |
| `DDNS_CHECK_INTERVAL` | `1800` | Interval check périodique DDNS (30 min) |

### Tailscale DNS Sync (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `TAILSCALE_API_KEY` | _(vide)_ | API key Tailscale (tskey-api-...) |
| `TAILSCALE_TAILNET` | _(vide)_ | Tailnet (email ou nom org) |
| `TAILSCALE_DNS_SUBDOMAIN` | _(vide)_ | Sous-domaine pour records (ex: ts) |
| `TAILSCALE_DNS_PREFIX` | _(vide)_ | Prefix pour hostnames |
| `TAILSCALE_DNS_POSTFIX` | _(vide)_ | Postfix pour hostnames |
| `TAILSCALE_SYNC_INTERVAL` | `600` | Interval sync (10 min) |

### Backup UniFi (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `UNIFI_BACKUP_DIR` | _(vide)_ | Repertoire backups auto UniFi (vide = désactivé) |
| `UNIFI_BACKUP_RCLONE_DEST` | `drive:Unifi` | Destination rclone (ex: drive:Unifi, s3:bucket) |
| `UNIFI_BACKUP_RETENTION_DAYS` | `30` | Retention en jours |
| `UNIFI_BACKUP_SCHEDULE_HOUR` | `4` | Heure backup quotidien (0-23, -1 = off) |
| `UNIFI_BACKUP_MAX_AGE_HOURS` | `48` | Alerte si dernier backup > N heures |

### Rapports quotidiens et hebdomadaires

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DAILY_REPORT_HOUR` | `8` | Heure rapport quotidien (0-23, -1 = off) |
| `WEEKLY_REPORT_DAY` | `0` | Jour rapport hebdomadaire (0=lun, 6=dim, -1 = off) |

### Coordination haute disponibilité

| Variable | Défaut | Description |
|----------|--------|-------------|
| `INSTANCE_PRIORITY` | `1` | Priorité (1 = primary, 2+ = secondary) |
| `PEER_IP` | _(vide)_ | IP du peer (vide = mode standalone) |
| `PEER_PORT` | `9000` | Port HTTP du peer |
| `HTTP_PORT` | `9000` | Port HTTP local |
| `PEER_TAKEOVER_DELAY` | `180` | Délai avant secondary prend relais (s) |

### API et authentification

| Variable | Défaut | Description |
|----------|--------|-------------|
| `API_TOKEN` | _(vide)_ | Token d'auth pour endpoints POST (vide = LAN only) |

### Logging

| Variable | Défaut | Description |
|----------|--------|-------------|
| `LOG_LEVEL` | `INFO` | Niveau : DEBUG, INFO, WARNING, ERROR |
| `LOG_FILE` | `/var/log/usg-watchdog.log` | Chemin fichier log |

---

## Système de scoring

Chaque cycle (par défaut 30 secondes), le score de défaillance est mis à jour selon les résultats :

| Scénario | Delta |
|----------|-------|
| Gateway OK + Internet 3/3 | -2 |
| Gateway OK + Internet 2/3 | -1 |
| Gateway OK + Internet 1/3 | +1 |
| Gateway OK + Internet 0/3 | +3 |
| Gateway KO + Internet quelconque | +4 |
| Score maximal (plafond) | 15 |
| **Seuil de reboot** | **10** |

Le score est borné entre 0 et 15. Un score >= 10 déclenche un reboot (si les conditions le permettent).

### Récupération et stabilisation

Quand la connexion se rétablit :
- Si tout OK (3/3) : perte de 2 points par cycle
- Si dégradé (2/3) : perte de 1 point par cycle
- Permet une récupération progressive

---

## Circuit breaker

Système multi-niveaux pour prévenir les boucles infinies de reboots :

### 1. Grace post-reboot (6 min)

Après un reboot, les échecs sont ignorés pendant 360s pour laisser le USG se stabiliser.

### 2. Cooldown exponentiel

Chaque reboot double le cooldown (base 15 min) :
- Reboot 1 : 15 min
- Reboot 2 : 30 min
- Reboot 3 : 60 min
- Reboot 4+ : jusqu'à 4 heures (MAX_REBOOT_COOLDOWN)

### 3. Limite quotidienne

Max 10 reboots/jour. Au-delà, le watchdog passe en mode **surveillance** :
- Plus de reboot automatique
- Alerte seulement
- Permet une intervention manuelle

### 4. Backoff SSH

Après 3 échecs SSH consécutifs, délai exponentiel avant nouvelles tentatives :
- 3 échecs : 5 min
- 6 échecs : 10 min
- 10 échecs : 20 min (capped à 1 heure)

### 5. Détection de panne ISP

Pattern détecté : Gateway OK + Internet 0/3 pendant 30 minutes = panne ISP probable.

Dans ce cas :
- Les reboots sont ralentis (inutiles si panne chez FAI)
- Une notification d'alerte est envoyée
- Le watchdog continue la surveillance
- Récupération auto au retablissement

---

## 7 Canaux de notification

Le watchdog supporte 7 canaux de notification, chacun filtrable par niveau :

### 1. Telegram

Requiert : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

**Avantages** : Push sur mobile, bot interactif avec commandes

```bash
# Exemple config
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHIjklmnoPQRstuvWXYz
TELEGRAM_CHAT_ID=987654321
TELEGRAM_MIN_LEVEL=INFO
```

### 2. Discord

Requiert : `DISCORD_WEBHOOK_URL`

**Avantages** : Webhooks simples, rich formatting, threading

```bash
DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/xxx/yyy
DISCORD_MIN_LEVEL=INFO
```

### 3. Slack

Requiert : `SLACK_WEBHOOK_URL`

**Avantages** : Rich messages, statuses, thread support

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
SLACK_MIN_LEVEL=WARNING
```

### 4. Ntfy

Requiert : `NTFY_URL`, `NTFY_TOPIC`

**Avantages** : Self-hosted possible, pas d'abonnement, alertes même sans internet (local)

```bash
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=usg-watchdog
NTFY_MIN_LEVEL=INFO
```

### 5. Email SMTP

Requiert : `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_TO`, `SMTP_USERNAME`, `SMTP_PASSWORD`

**Avantages** : Traces écrites, audit compliance, pas de dépendance cloud

```bash
SMTP_HOST=mail.example.com
SMTP_PORT=587
SMTP_FROM=watchdog@example.com
SMTP_TO=admin@example.com
SMTP_USERNAME=watchdog
SMTP_PASSWORD=password
SMTP_MIN_LEVEL=WARNING
```

### 6. Pushover

Requiert : `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN`

**Avantages** : Notifications mobiles riches, escalade priorités

```bash
PUSHOVER_USER_KEY=user_key_xxx
PUSHOVER_API_TOKEN=token_xxx
PUSHOVER_MIN_LEVEL=INFO
```

### 7. MQTT / Home Assistant

Requiert : `MQTT_BROKER`

**Avantages** : Intégration domotique complète, auto-discovery Home Assistant

```bash
MQTT_BROKER=192.168.1.50
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=usg-watchdog
MQTT_HA_DISCOVERY=true
```

### Filtrage par niveau

Chaque canal supporte un niveau minimum de notification :

- `INFO` : Toutes les notifications (defaut)
- `WARNING` : Seulement avertissements et critiques
- `CRITICAL` : Seulement incidents critiques

Exemple : Telegram en INFO (notifications détaillées), Email en WARNING (important seulement)

```bash
TELEGRAM_MIN_LEVEL=INFO
DISCORD_MIN_LEVEL=WARNING
SMTP_MIN_LEVEL=CRITICAL
```

---

## Commandes Telegram Bot

Si `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` sont configurés, le watchdog expose un bot interactif.

Envoyer ces commandes au bot depuis votre téléphone :

### `/status`

Affiche l'état complet du watchdog :
- Score / seuil
- Gateway et internet
- Latences RTT
- Reboots aujourd'hui
- Statut ISP
- Statut peer (si HA activé)

### `/pause [minutes]`

Passer en mode surveillance (pas de reboot automatique, alerte seulement).

Optionnel : durée en minutes. Sans paramètre, pause infinie.

```
/pause 60    # Pause 1 heure
/pause       # Pause infinie (jusqu'à /resume)
```

### `/resume`

Reprendre les reboots automatiques après une pause.

### `/reboot`

Déclencher un reboot immédiatement (ignore les cooldowns et grace periods).

**Utile** : Tests, maintenance, urgence.

### `/ddns`

Forcer une vérification et mise à jour DDNS Cloudflare.

(Uniquement si `CLOUDFLARE_API_TOKEN` configuré)

### `/backup`

Lancer manuellement un backup UniFi vers rclone.

(Uniquement si `UNIFI_BACKUP_DIR` configuré)

### `/tailscale`

Forcer une synchronisation Tailscale DNS.

(Uniquement si `TAILSCALE_API_KEY` configuré)

### `/help`

Affiche l'aide des commandes disponibles.

---

## API HTTP complète

Le watchdog expose une API HTTP sur le port 9000 (configurable) :

### GET /health

État synthétique du watchdog.

```bash
curl http://192.168.1.50:9000/health
```

Réponse :

```json
{
  "status": "healthy",
  "score": 0,
  "threshold": 10,
  "gateway": "OK",
  "internet": "3/3",
  "instance_priority": 1,
  "consecutive_reboots": 0,
  "reboots_today": 0,
  "isp_outage": false,
  "uptime": 86400,
  "latency_gateway_ms": 5.2,
  "latency_internet_ms": 18.5,
  "peer": {
    "status": "healthy",
    "score": 0,
    "gateway": "OK",
    "internet": "3/3"
  },
  "version": "1.7.0"
}
```

Statuts possibles : `healthy`, `degraded`, `critical`, `surveillance`, `starting`

### GET /api/state

État complet (pour le peer ou monitoring externe).

```bash
curl http://192.168.1.50:9000/api/state
```

Retourne la snapshot immutable du watchdog (~50 champs) : scores, statuts, timestamps, historique cooldowns, etc.

### GET /api/events

Historique des événements (queryable).

```bash
# 50 derniers événements
curl http://192.168.1.50:9000/api/events

# Filtrer par type
curl "http://192.168.1.50:9000/api/events?type=reboot"

# Limiter le count
curl "http://192.168.1.50:9000/api/events?count=10"
```

Types possibles : `startup`, `shutdown`, `reboot`, `reboot_failed`, `recovery`, `isp_outage`, `isp_recovery`, `peer_standdown`, `ssh_backoff`, `max_reboots`, `divergence`, etc.

### GET /api/config

Configuration active (paramètres publics, jamais les secrets).

```bash
curl http://192.168.1.50:9000/api/config
```

### GET /api/report

Rapport quotidien.

```bash
curl http://192.168.1.50:9000/api/report
```

Retourne : reboots, pannes, récupérations, uptime d'aujourd'hui.

### GET /api/sla

Calcul SLA mensuel (uptime, outages, MTTR).

```bash
curl http://192.168.1.50:9000/api/sla
```

### GET /api/history

Historique persisté des événements et métriques.

```bash
curl http://192.168.1.50:9000/api/history | jq .
```

### GET /metrics

Métriques Prometheus au format standard.

```bash
curl http://192.168.1.50:9000/metrics
```

Utilisable directement avec Grafana.

### GET /api/backup/config

Export de la configuration complète (format JSON).

```bash
curl http://192.168.1.50:9000/api/backup/config > watchdog-config.json
```

### GET /api/maintenance

État du mode maintenance actuel.

```bash
curl http://192.168.1.50:9000/api/maintenance
```

### GET /manifest.json

Web App manifest (pour PWA).

```bash
curl http://192.168.1.50:9000/manifest.json
```

### GET /sw.js

Service Worker (pour support offline PWA).

```bash
curl http://192.168.1.50:9000/sw.js
```

### POST /api/pause

Passer en mode surveillance (pas de reboot, alerte seulement).

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://192.168.1.50:9000/api/pause
```

### POST /api/resume

Reprendre les reboots normaux.

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://192.168.1.50:9000/api/resume
```

### POST /api/reboot

Déclencher un reboot immédiatement (ignore les cooldowns).

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://192.168.1.50:9000/api/reboot
```

### POST /api/maintenance

Activer le mode maintenance pour une durée.

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"duration_minutes": 120}' \
  http://192.168.1.50:9000/api/maintenance
```

### POST /api/ddns/update

Forcer une vérification DDNS Cloudflare.

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://192.168.1.50:9000/api/ddns/update
```

### POST /api/backup/unifi

Lancer un backup UniFi immédiatement.

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://192.168.1.50:9000/api/backup/unifi
```

### Authentification API

Si `API_TOKEN` est configuré, tous les endpoints POST requièrent :

```bash
Authorization: Bearer YOUR_TOKEN
```

Si vide, les endpoints POST sont accessibles depuis le LAN (aucune vérification).

---

## Dashboard PWA

Le dashboard HTML intégré est accessible sur :

```
http://192.168.1.50:9000/
http://192.168.1.50:9000/dashboard
```

### Fonctionnalités

- **Responsive** : Adapté mobile / tablette / desktop
- **Dark mode** : Style GitHub compatible
- **Auto-refresh** : Requête /health toutes les 5 secondes
- **PWA** : Installable sur Android/iOS, support offline
- **Zéro dépendances** : Aucun framework JS externe (vanilla)

### Affichage

- **Statut** : Indicateur de couleur (vert=healthy, orange=degraded, rouge=critical, violet=surveillance)
- **Score** : Valeur actuelle et barre de progression vers le seuil
- **Connectivité** : Gateway OK/KO, internet X/3, uptime
- **Latences** : RTT gateway et internet, alerte si dégradation
- **Reboots** : Tentatives aujourd'hui vs limite quotidienne
- **Peer** : Statut du secondary (si HA configuré)
- **Événements** : 20 derniers événements avec timestamps
- **ISP** : Alerte si panne ISP détectée
- **Maintenance** : Boutons pause/resume/reboot (authentification requise si `API_TOKEN`)

---

## Fonctionnalités avancées

### DDNS Cloudflare

Synchronise automatiquement votre IP publique vers les records Cloudflare.

Remplace le script externe `update-cloudflare-dns.sh`.

Déclenche : au redémarrage + au retablissement après coupure + check périodique (30 min).

Configuration :

```bash
CLOUDFLARE_API_TOKEN=xxx          # Token (Zone edit)
CLOUDFLARE_ZONE_ID=xxx           # Zone ID
CLOUDFLARE_RECORD_NAMES=home.example.com,vpn.example.com
CLOUDFLARE_PROXIED=false         # Proxy Cloudflare
CLOUDFLARE_TTL=120               # TTL secondes
DDNS_CHECK_INTERVAL=1800         # Check periodiqu (30 min)
```

### Tailscale DNS Sync

Synchronise les enregistrements Tailscale DNS avec les machines du réseau.

Remplace le script externe `tailscale-cloudflare-dnssync`.

Configuration :

```bash
TAILSCALE_API_KEY=tskey-api-xxx
TAILSCALE_TAILNET=your-tailnet
TAILSCALE_DNS_SUBDOMAIN=ts        # Optionnel
TAILSCALE_SYNC_INTERVAL=600       # Check toutes les 10 min
```

### Backup UniFi automatisé

Télécharge automatiquement les backups UniFi via rclone.

Remplace le script externe `backup-unifi.sh`.

Configuration :

```bash
UNIFI_BACKUP_DIR=/path/to/unifi/backups
UNIFI_BACKUP_RCLONE_DEST=drive:Unifi    # Google Drive, S3, etc.
UNIFI_BACKUP_RETENTION_DAYS=30
UNIFI_BACKUP_SCHEDULE_HOUR=4             # 4h du matin
UNIFI_BACKUP_MAX_AGE_HOURS=48            # Alerte si > 48h
```

**Note** : Configurer rclone au préalable avec `rclone config`.

### Monitoring multi-WAN

Détecte si une failover de WAN double-WAN est active sur le USG.

Utile pour identifier les problèmes de WAN secondaire.

### Speedtest intégré

Tests de débit périodiques (100KB) pour détection dégradation.

Télécharge depuis Cloudflare CDN toutes les 10 minutes.

Alerte si débit < seuil configuré.

### Mesure de latence

RTT (Round Trip Time) gateway + internet avec alerte si dégradation.

Utile pour détecter les lenteurs réseau avant coupure.

### Diagnostics traceroute

Traceroute vers cibles ping sur demande Telegram (commande `/status`).

Utile pour identifier le point de rupture en cas de problème.

### SNMP monitoring

Lecture des métriques USG (CPU, mémoire, interfaces) via SNMP.

Affiché dans le dashboard et les rapports.

### Métriques Prometheus

Endpoint `/metrics` au format Prometheus standard.

Dashboard Grafana prêt à importer.

Métriques disponibles :
- `usg_watchdog_failure_score` - Score de défaillance
- `usg_watchdog_gateway_up` - Gateway OK (0/1)
- `usg_watchdog_internet_targets_up` - Cibles internet répondant
- `usg_watchdog_gateway_rtt_ms` - Latence gateway
- `usg_watchdog_internet_avg_rtt_ms` - Latence internet moyenne
- `usg_watchdog_reboots_total` - Total reboots
- `usg_watchdog_latency_degraded` - Alerte dégradation latence

### Escalade d'alertes

Si une alerte critique n'est pas supprimée après N minutes, ré-envoie via les canaux prioritaires.

Configuration :

```bash
ALERT_ESCALATION_ENABLED=true
ALERT_ESCALATION_DELAY=15          # Délai escalade (minutes)
```

### Maintenance programmée

Mode pause avec durée automatique.

Utile pour maintenance réseau planifiée.

```bash
curl -X POST -H "Authorization: Bearer TOKEN" \
  -d '{"duration_minutes": 120}' \
  http://localhost:9000/api/maintenance
```

---

## Coordination haute disponibilité

Mode optionnel pour deux instances (primary + secondary) sur le même réseau.

### Configuration

**Instance 1 (Primary) :**

```bash
INSTANCE_PRIORITY=1
PEER_IP=192.168.1.51
HTTP_PORT=9000
```

**Instance 2 (Secondary) :**

```bash
INSTANCE_PRIORITY=2
PEER_IP=192.168.1.50
HTTP_PORT=9000
```

### Comportement

1. **Primary surveille** : Décide de redémarrer si seuil atteint
2. **Primary notifie** : Secondary est au courant avant chaque reboot
3. **Secondary attend** : 3 min avant de prendre le relais si primary devient injoignable
4. **Divergence détectée** : Si les deux instances voient des états très différents (score > 6), alerte pour identifier un problème local

### Consultation du peer

```bash
# Voir l'état du secondary depuis le primary
curl http://192.168.1.51:9000/api/state
```

---

## Rapports quotidiens et hebdomadaires

Envoyés automatiquement aux canaux configurés.

### Rapport quotidien

Envoyé à `DAILY_REPORT_HOUR` (défaut 8h).

Contenu :
- Uptime du jour
- Nombre et durée des pannes
- Reboots réussis / échoués
- Pannes ISP détectées
- Statut du peer

Exemple :

```
2024-01-15 -- Rapport quotidien
Uptime : 99.2%
Pannes : 2 (16m20s, 8m)
Reboots : 3 réussis, 0 échoués
Pannes ISP : 0 détectées
Peer : healthy
```

### Rapport hebdomadaire

Envoyé tous les `WEEKLY_REPORT_DAY` (défaut lundi).

Cumul de la semaine : uptime, incidents, reboots, état pair.

### SLA mensuel

Endpoint `/api/sla` retourne :
- Uptime % du mois
- Total outages et durée
- MTTR (Mean Time To Recovery)
- Nombre de reboots

---

## Structure du projet

```
usg-watchdog/
├── src/
│   ├── watchdog.py               # Boucle principale + scoring + circuit breaker
│   ├── config.py                 # Configuration (env vars)
│   ├── connectivity.py           # Ping gateway + internet
│   ├── usg.py                    # Reboot SSH paramiko
│   ├── state.py                  # Snapshots immuables + queue commandes
│   ├── events.py                 # Ring buffer events + persistence
│   ├── http_server.py            # API HTTP + endpoints
│   ├── peer.py                   # Coordination multi-instance
│   ├── dashboard.py              # Dashboard HTML intégré
│   ├── pwa.py                    # PWA manifest + service worker
│   ├── report.py                 # Rapports quotidiens/hebdomadaires
│   ├── history.py                # Historique persisté
│   ├── diagnostics.py            # Traceroute + SNMP
│   ├── metrics.py                # Prometheus /metrics
│   ├── ddns_cloudflare.py        # DDNS Cloudflare
│   ├── tailscale_dns.py          # Tailscale DNS sync
│   ├── backup_unifi.py           # Backup UniFi via rclone
│   ├── multiwan.py               # Multi-WAN detection
│   ├── speedtest.py              # Speedtest intégré
│   ├── snmp_monitor.py           # SNMP monitoring
│   ├── mqtt_publisher.py         # MQTT / Home Assistant
│   ├── alert_escalation.py       # Escalade d'alertes
│   ├── telegram_bot.py           # Telegram bot interactif
│   ├── messages.py               # Templates messages
│   ├── notifier/
│   │   ├── __init__.py
│   │   ├── _types.py             # Level, NotificationContext
│   │   ├── _dispatch.py          # Dispatch multi-canaux
│   │   ├── _telegram.py          # Telegram
│   │   ├── _discord.py           # Discord
│   │   ├── _slack.py             # Slack
│   │   ├── _ntfy.py              # Ntfy
│   │   ├── _email.py             # Email SMTP
│   │   └── _pushover.py          # Pushover
│   └── __init__.py
├── updater/
│   ├── update.py                 # Auto-updater principal
│   └── preflight.py              # Validation avant deployment
├── systemd/
│   ├── usg-watchdog.service      # Unit systemd (sandboxing)
│   ├── usg-watchdog.logrotate    # Rotation logs
│   ├── usg-watchdog-updater.service
│   └── usg-watchdog-updater.timer
├── scripts/
│   ├── setup_ssh.sh              # Setup SSH Ed25519
│   ├── deploy.sh                 # Installation complète
│   ├── test.sh                   # Tests pré-déploiement
│   ├── uninstall.sh              # Suppression propre
│   ├── validate.sh               # Validation pré-commit
│   └── release.sh                # Tagging + versioning
├── tests/
│   ├── test_watchdog.py
│   ├── test_connectivity.py
│   ├── test_notifier.py
│   ├── test_http_server.py
│   └── ...
├── requirements.txt              # Dépendances Python
├── .gitignore                    # Exclut .env, SSH, logs
├── README.md                     # Ce fichier
├── CLAUDE.md                     # Architecture (développeurs)
├── DEPLOY.md                     # Guide déploiement
├── WORKFLOW.md                   # Workflow développement
└── VERSION                       # Fichier version
```

---

## Dépannage

### SSH échoue avec "Connection refused"

1. Vérifier SSH activé sur USG : Settings > Device Authentication
2. Tester manuellement : `ssh -i /opt/usg-watchdog/.ssh/usg_ed25519 maintenance@192.168.1.1`
3. Relancer setup : `sudo ./scripts/setup_ssh.sh`
4. Vérifier clé publique sur USG : `cat ~/.ssh/authorized_keys`

### "Peer unreachable" en permanent

1. Vérifier que secondary tourne : `sudo systemctl status usg-watchdog` sur l'autre machine
2. Vérifier PEER_IP / HTTP_PORT correct dans `/opt/usg-watchdog/.env`
3. Tester ping : `ping 192.168.1.51`
4. Consulter logs de secondary : `sudo journalctl -u usg-watchdog -f`
5. Vérifier firewall entre les machines

### Reboots très fréquents

Vérifier :
- Score anormalement haut (dans logs)
- Pattern ISP non détecté (gateway OK, internet KO prolongé)
- Cooldown peut-être trop bas : augmenter `REBOOT_COOLDOWN`
- Mode surveillance activé ? (Max reboots/jour dépassé) - voir logs

### Logs vides ou pas de notifications

1. Vérifier niveau log : `cat /var/log/usg-watchdog.log`
2. Augmenter verbosité : `echo "LOG_LEVEL=DEBUG" >> /opt/usg-watchdog/.env && sudo systemctl restart usg-watchdog`
3. Pour Telegram : tester token/chat_id avec curl
4. HTTP port disponible ? `sudo netstat -tlnp | grep 9000`
5. Vérifier permissions fichier log : `sudo ls -l /var/log/usg-watchdog.log`

### "Divergence detectee" entre instances

Signifie que local et peer voient des états très différents (écart score > 6).

Solutions :
- Vérifier connectivité réseau entre les deux machines
- Vérifier que les deux surveillent la même gateway
- Vérifier ping targets identiques sur les deux machines
- Consulter les logs des deux instances en parallèle

### Dashboard lent ou injoignable

1. Vérifier port : `curl -v http://192.168.1.50:9000/health`
2. Vérifier pare-feu : `sudo iptables -L -n | grep 9000`
3. Vérifier que watchdog tourne : `sudo systemctl status usg-watchdog`
4. Vérifier CPU/mémoire : `free -h && uptime`
5. Vérifier logs du serveur HTTP : `sudo journalctl -u usg-watchdog -f`

### Notifications non reçues

Telegram :
- Vérifier token : `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Vérifier chat_id : envoyer "/start" au bot, vérifier id dans logs
- Vérifier niveau : `TELEGRAM_MIN_LEVEL`

Discord :
- Tester webhook : `curl -X POST <WEBHOOK_URL> -d '{"content":"test"}'`
- Vérifier formatting

Slack :
- Tester webhook : `curl -X POST <WEBHOOK_URL> -d '{"text":"test"}'`

Email :
- Tester SMTP : `python3 -c "import smtplib; smtplib.SMTP('host', 587).login('user', 'pass')"`
- Vérifier TLS : port 587 ou 465
- Vérifier credentials dans .env

### DDNS ne se met pas à jour

1. Vérifier configuration : `curl http://localhost:9000/api/config | grep CLOUDFLARE`
2. Tester manuellement : `curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/ddns/update`
3. Vérifier logs : `sudo journalctl -u usg-watchdog -f | grep -i ddns`
4. Vérifier token Cloudflare : permissions "Zone.DNS edit"
5. Vérifier que record A existe

### Backup UniFi ne fonctionne pas

1. Vérifier rclone config : `rclone config`
2. Tester destination : `rclone ls <destination>`
3. Vérifier dossier source existe : `ls -la /path/to/unifi/backups`
4. Tester manuellement : `curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/backup/unifi`
5. Vérifier espace disque : `df -h`

---

## Commandes utiles

```bash
# Statut du service
sudo systemctl status usg-watchdog

# Logs temps réel
sudo journalctl -u usg-watchdog -f

# Logs complets
sudo tail -f /var/log/usg-watchdog.log

# Événements historiques
curl http://localhost:9000/api/events | python3 -m json.tool

# Redémarrer le watchdog (pas le USG)
sudo systemctl restart usg-watchdog

# Mode surveillance (pas de reboot)
curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/pause

# Reprendre les reboots
curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/resume

# Forcer un reboot USG
curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/reboot

# Voir l'uptime SLA du mois
curl http://localhost:9000/api/sla | python3 -m json.tool

# Export config
curl http://localhost:9000/api/backup/config > watchdog-backup.json

# Métriques Prometheus
curl http://localhost:9000/metrics

# Mode debug
echo "LOG_LEVEL=DEBUG" >> /opt/usg-watchdog/.env
sudo systemctl restart usg-watchdog
```

---

## Auto-updater

Le watchdog inclut un système d'auto-mise-à-jour.

Installation :

```bash
sudo systemctl enable usg-watchdog-updater.timer
sudo systemctl start usg-watchdog-updater.timer
```

Le timer se déclenche à **3h du matin** chaque jour.

Processus :
1. Vérifie GitHub pour un nouveau tag `vX.Y.Z`
2. Si trouvé, télécharge et valide (syntaxe + imports)
3. Applique atomiquement
4. Redémarre le watchdog
5. Fait un health check (200 OK)
6. Si echec : rollback automatique vers version précédente
7. Notifie du résultat

Forcer une mise à jour immédiate :

```bash
sudo systemctl start usg-watchdog-updater
```

Vérifier la version :

```bash
curl http://localhost:9000/health | python3 -m json.tool | grep version
```

---

## Sécurité

### Authentification SSH

- **Clés Ed25519 uniquement** : Compatible EdgeOS 6.6.1 (USG vieux firmware)
- **Known_hosts** : Vérification de la clé hôte du USG (MITM prevention)
- **Rejet strict** : `RejectPolicy` si la clé change (détecte intrusion)

### Permissions

- **Utilisateur dédié** : `usg-watchdog` (non-root, nologin)
- **Virtualenv isolé** : `/opt/usg-watchdog/venv`
- **SSH dir 700** : Clés privées accessibles uniquement au watchdog
- **Log file 640** : Logs lisibles par adm seulement

### Sandboxing systemd

- **ProtectSystem=strict** : Système de fichiers read-only
- **PrivateTmp=yes** : Temp dir dédié
- **NoNewPrivileges=yes** : Aucune escalade de privilèges
- **RestrictNamespaces=yes** : Namespaces limités
- **RestrictAddressFamilies** : TCP/UDP seulement
- **DevicePolicy=closed** : Aucun accès aux devices
- **CAP_NET_RAW** : Seule capacité (pour ping)

### Gestion des secrets

- Aucun token/mot de passe hardcodé
- Variables d'environnement dans `/opt/usg-watchdog/.env` (chmod 600)
- Fichier ignoré par git
- Jamais de logs d'authentification en clair

### API Token

Si `API_TOKEN` configuré, tous les endpoints POST requièrent l'authentification :

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" http://localhost:9000/api/pause
```

Générer un token aléatoire :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Licence

MIT - voir LICENSE

---

## Support et contribution

Pour remonter un bug ou une idée :

1. Créer une issue GitHub : https://github.com/jsoyer/usg-watchdog/issues
2. Fournir : configuration, logs, étapes de reproduction
3. Pour les contributions : fork, feature branch, tests, PR

---

**Dernière mise à jour** : 2026-03-31 (v1.7.0)

**Python** : 3.11+

**Dépendances principales** : paramiko (SSH), requests (HTTP), stdlib only (threading, queue, dataclass)
