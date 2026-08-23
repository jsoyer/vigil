# Vigil v2.0.0

Daemon de surveillance de connexion internet et redémarrage automatique du routeur Ubiquiti USG, fonctionnant sur Raspberry Pi ou Linux. Conçu pour les connexions fibre instables avec détection intelligente des pannes ISP, coordination multi-instance et notifications multi-canaux (Ntfy, Email SMTP, MQTT/Home Assistant).

**Version de production : v2.0.0**

> **Anciennement USG Watchdog.** Ce projet s'appelait *USG Watchdog* jusqu'à
> la version 1.8.3. À partir de la 2.0.0 il est renommé **Vigil** — le dépôt
> GitHub `jsoyer/usg-watchdog` a été renommé `jsoyer/vigil` (une redirection
> GitHub reste active sur l'ancien nom). Le routeur Ubiquiti surveillé
> continue d'être désigné "USG" dans la documentation et le code
> (`src/usg.py`, `USG_IP`, etc.) — seul le nom du logiciel change.
> Procédure de migration complète : voir `docs/RELEASE-NOTES-2.0.0.md`
> (ce fichier sera ajouté lors de la finalisation de la version 2.0.0).

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Installation rapide](#installation-rapide)
- [Configuration complète](#configuration-complète)
- [Système de scoring](#système-de-scoring)
- [Circuit breaker](#circuit-breaker)
- [Canaux de notification](#canaux-de-notification)
- [Contrôle à distance (Dashboard + boutons Ntfy)](#contrôle-à-distance-dashboard--boutons-ntfy)
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
- **Canaux de notification** : Ntfy (principal, boutons d'action), Email SMTP, MQTT/Home Assistant
- **Boutons d'action Ntfy + Dashboard** : confirmer/annuler une action directement depuis la notification ou le dashboard web
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
- **Diagnostics traceroute** : Traceroute vers cibles ping, lancé automatiquement au premier seuil de défaillance atteint
- **SNMP monitoring** : Lecture des métriques USG (CPU, mémoire, interfaces)
- **Métrique Prometheus** : Endpoint /metrics pour Grafana + dashboards prêts
- **Escalade d'alertes** : Re-envoi automatique via canaux prioritaires si pas d'ACK
- **Maintenance programmée** : Mode pause avec durée, accessible via API ou dashboard
- **Auto-updater** : Récupère les versions depuis GitHub, valide, déploie, rollback auto
- **Historique d'événements** : Ring buffer persisté (~100 événements) + export JSON

---

## Installation rapide

### Prérequis

- Raspberry Pi ou Linux (Fedora / Debian) avec systemd
- Python 3.11+
- SSH activé sur le USG (Settings > Device Authentication)
- (optionnel) Serveur Ntfy joignable (LAN/Tailscale) / Compte Cloudflare

### 1. Cloner le dépôt

```bash
git clone https://github.com/jsoyer/vigil.git
cd vigil
```

### 2. Configurer SSH vers le USG

```bash
sudo ./scripts/setup_ssh.sh
```

Ce script :
- Génère une clé Ed25519 dans `/opt/vigil/.ssh/`
- Capture la clé hôte du USG (known_hosts)
- Déploie la clé publique sur le USG
- Teste la connexion sans mot de passe

### 3. Créer le fichier .env

```bash
sudo mkdir -p /opt/vigil
sudo nano /opt/vigil/.env
```

Configuration minimale :

```bash
# USG
USG_IP=192.168.1.1
USG_USER=ubnt

# Ntfy (optionnel mais recommandé)
NTFY_URL=http://127.0.0.1:7171
NTFY_TOPIC=vigil-dijon
NTFY_TOKEN=tk_xxxxxxxxxxxxxxxxx
```

Sécuriser le fichier :

```bash
sudo chmod 600 /opt/vigil/.env
```

### 4. Déployer

```bash
sudo ./scripts/deploy.sh
```

Ce script :
- Crée l'utilisateur système `vigil`
- Installe les fichiers et dépendances Python
- Configure le service systemd
- Démarre le watchdog

### 5. Vérifier

```bash
# Status du service
sudo systemctl status vigil

# Logs en temps réel
sudo journalctl -u vigil -f

# Health check
curl http://localhost:9000/health | python3 -m json.tool

# Dashboard
# Ouvrir http://192.168.1.50:9000/ dans un navigateur sur le LAN
```

### 6. (Recommandé) Installer l'auto-updater

```bash
sudo systemctl enable vigil-updater.timer
sudo systemctl start vigil-updater.timer
```

Le timer vérifie GitHub à 3h du matin chaque jour. Voir `DEPLOY.md` pour plus de détails.

---

## Configuration complète

Tous les paramètres peuvent être surchargés via variables d'environnement dans `/opt/vigil/.env` :

### Connexion et ping

| Variable | Défaut | Description |
|----------|--------|-------------|
| `USG_IP` | `192.168.1.1` | IP du routeur USG (gateway LAN) |
| `USG_USER` | `ubnt` | User SSH du USG |
| `USG_SSH_KEY` | `/opt/vigil/.ssh/usg_ed25519` | Chemin clé SSH privée |
| `USG_KNOWN_HOSTS` | `/opt/vigil/.ssh/known_hosts` | Fichier known_hosts |
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

### Ntfy (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `NTFY_URL` | _(vide)_ | URL serveur Ntfy (https://ntfy.sh ou self-hosted) |
| `NTFY_TOPIC` | _(vide)_ | Topic Ntfy de site (alertes de ligne, ex: vigil-dijon) |
| `NTFY_TOPIC_OPS` | `vigil-ops` | Topic Ntfy pour le cycle de vie (demarrage, sauvegardes, rapports) |
| `NTFY_TIMEOUT` | `5` | Timeout requête (secondes) |
| `NTFY_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |
| `NTFY_TOKEN` | _(vide)_ | Jeton d'authentification (`Authorization: Bearer`). Vide = publication anonyme |

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

### MQTT / Home Assistant (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `MQTT_BROKER` | _(vide)_ | Adresse broker MQTT (vide = désactivé) |
| `MQTT_PORT` | `1883` | Port MQTT |
| `MQTT_TOPIC_PREFIX` | `vigil` | Préfixe topics MQTT |
| `MQTT_USERNAME` | _(vide)_ | Username MQTT |
| `MQTT_PASSWORD` | _(vide)_ | Password MQTT |
| `MQTT_HA_DISCOVERY` | `true` | Envoyer configs auto-discovery Home Assistant |
| `SITE_ID` | _(dérivé de `INSTANCE_ID`)_ | Identifiant de site (Dijon/Nice) — regroupe les devices HA « par site » (USG, TP-Link) |
| `MQTT_COMMANDS_ENABLED` | `false` | Active l'écoute des commandes MQTT entrantes (switch arm + button reboot) — **broker authentifié obligatoire**, voir avertissement dans la section « Home Assistant : entités par équipement » |
| `MQTT_ARM_TIMEOUT` | `30` | Durée en secondes avant désarmement automatique du bouton reboot (minimum 5) |

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
| `LOG_FILE` | `/var/log/vigil.log` | Chemin fichier log |

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

## Canaux de notification

Le watchdog supporte 3 canaux de notification actifs (Ntfy, Email SMTP,
MQTT/Home Assistant), chacun filtrable par niveau :

### 1. Ntfy

Requiert : `NTFY_URL`, `NTFY_TOPIC`

**Avantages** : Self-hosted possible, pas d'abonnement, alertes même sans internet (local)

```bash
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=vigil
NTFY_MIN_LEVEL=INFO
```

Sur un serveur Ntfy protégé par authentification, ajouter `NTFY_TOKEN` (jeton
`Authorization: Bearer`, jamais journalisé) et éventuellement `NTFY_TOPIC_OPS`
pour séparer les alertes de ligne des événements de cycle de vie
(démarrage, sauvegardes, rapports) :

```bash
NTFY_TOKEN=tk_xxxxxxxxxxxxxxxxx
NTFY_TOPIC_OPS=vigil-ops
```

### 2. Email SMTP

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

### 3. MQTT / Home Assistant

Requiert : `MQTT_BROKER`

**Avantages** : Intégration domotique complète, auto-discovery Home Assistant

```bash
MQTT_BROKER=192.168.1.50
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=vigil
MQTT_HA_DISCOVERY=true
```

### Filtrage par niveau

Chaque canal supporte un niveau minimum de notification :

- `INFO` : Toutes les notifications (defaut)
- `WARNING` : Seulement avertissements et critiques
- `CRITICAL` : Seulement incidents critiques

Exemple : Ntfy en INFO (notifications détaillées), Email en WARNING (important seulement)

```bash
NTFY_MIN_LEVEL=INFO
SMTP_MIN_LEVEL=CRITICAL
```

---

## Contrôle à distance (Dashboard + boutons Ntfy)

Les commandes historiquement envoyées à un bot interactif sont remplacées
par le dashboard web (authentification par jeton `API_TOKEN`, voir
[Dashboard PWA](#dashboard-pwa)) et par les boutons d'action publiés dans
les notifications Ntfy pour les décisions qui arrivent avec l'alerte
(confirmer/annuler un reboot TP-Link, voir
[Lignes de secours TP-Link (4G)](#lignes-de-secours-tp-link-4g)).

| Ancienne commande du bot | Équivalent 2.2.0 |
|---|---|
| État complet du watchdog | Dashboard (page d'accueil) ou `GET /api/state` |
| Pause (durée optionnelle) | Bouton Pause du dashboard ou `POST /api/pause` |
| Reprendre les reboots | Bouton Reprendre du dashboard ou `POST /api/resume` |
| Forcer un reboot | Bouton Reboot du dashboard ou `POST /api/reboot` |
| Vérification DDNS | Bouton DDNS du dashboard ou `POST /api/ddns/update` |
| Backup UniFi | Bouton Backup du dashboard ou `POST /api/backup/unifi` |
| Sync Tailscale DNS | Bouton Tailscale du dashboard ou `POST /api/tailscale/sync` |
| Pilotage TP-Link (4G) | Section TP-Link du dashboard ou `/api/tplink/*` |

Toutes ces actions POST exigent `API_TOKEN` (en-tête `Authorization: Bearer`),
saisi une fois dans le dashboard et conservé en `sessionStorage` (jamais
`localStorage`). Seul `POST /api/confirm/<action>/<jeton>` (boutons Ntfy) en
est exempté : le jeton de capacité **est** l'autorisation.

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

Traceroute lancé automatiquement au premier seuil de défaillance atteint, journalisé dans les événements (`traceroute`).

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

**Nouveau en 2.3.0** : 16 séries `vigil_tplink_*` labellisées `device`/`label`
(signal 4G, quota, débit, usage, readiness...) pour chaque équipement TP-Link
déclaré. **Purement additif** : les métriques `usg_watchdog_*` ci-dessus
restent émises **sans label**, à l'identique — vos dashboards Grafana et
règles d'alerte existants n'ont rien à changer.

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

### Lignes de secours TP-Link (4G)

Pilotage optionnel d'un ou plusieurs routeurs 4G TP-Link (MR110 validé,
`tplinkrouterc6u`) utilisés comme secours. **Aucun équipement déclaré =
comportement strictement identique aux versions précédentes** : aucun driver
n'est instancié, aucune dépendance TP-Link n'est sollicitée.

**Déclaration** (par instance, numérotation `TPLINK_<n>_*` contiguë à partir
de 1 — exemple pour un guardian avec le MR110 en accès direct) :

```bash
# /opt/vigil/.env
TPLINK_1_HOST=192.168.10.1
TPLINK_1_PASSWORD=motdepasse_local_du_mr110
TPLINK_1_LABEL=mr110-dijon
TPLINK_1_MODE=bridged            # bridged: cet hôte a un lien direct au MR110
                                  # remote : le MR110 est joint via un pont SSH
                                  #          (TPLINK_1_BRIDGE_HOST requis)
TPLINK_1_RSRP_MIN=-110           # dBm, défaut -110
TPLINK_1_RSRQ_MIN=-20            # dB, défaut -20
TPLINK_1_SNR_MIN=-100            # unité firmware, défaut -100 -- voir
                                  # docs/spikes/2026-08-23-mr110-compat.md
```

**Dashboard** : section TP-Link dédiée (liste, statut, sonde, reboot +
confirmation) -- voir [Dashboard PWA](#dashboard-pwa).

**Endpoints API** (`/api/tplink/*`) :

- `GET /api/tplink` -- équipements déclarés + dernier état connu
- `GET /api/tplink/<id>` -- santé, saut en panne, readiness, métriques 4G
- `POST /api/tplink/<id>/refresh` -- force une lecture, ignore le cache
- `POST /api/tplink/<id>/check` -- sonde de bout en bout, non destructive
- `POST /api/tplink/<id>/reboot` -- demande de redémarrage, renvoie un jeton
- `POST /api/tplink/<id>/reboot/confirm` -- confirme et exécute

**`API_TOKEN` est obligatoire dès qu'un équipement est déclaré** : sans lui,
les `GET /api/tplink/*` répondent aussi `403`, pas seulement les `POST` --
divergence volontaire avec le reste de l'API (ces réponses exposent état SIM,
opérateur, IP WAN et consommation).

**Périmètre A1** : management manuel uniquement (état, sonde à la demande,
reboot confirmé). Pas de bascule automatique du trafic vers le secours, pas
de commandes SMS/USSD en A1. Voir « Home Assistant : entités par équipement » ci-dessous pour l'exposition Home Assistant et le chemin de commande MQTT.

### Home Assistant : entités par équipement

A2 publie l'intégration Home Assistant complète depuis les mêmes 4 instances,
avec auto-discovery MQTT retenue (`retain`). Trois familles de devices,
strictement séparées :

- **`vigil_<site>_tplink_<id>`** — un device par équipement TP-Link déclaré
  (21 entités) : disponibilité, indicateurs 4G (RSRP, RSRQ, SNR, type réseau,
  opérateur, état SIM), conso/quota/pourcentage/date de reset, débits,
  état d'usage, résultat de sonde, diagnostic. Publié uniquement par
  l'instance élue (poller, voir « Coordination haute disponibilité ») —
  jamais par les deux instances d'un même site à la fois.
- **`USG <site>`** — un device par site (pas par instance) pour les 4
  capteurs de **ligne** USG (`gateway`, `internet`, RTT gateway, RTT
  internet), alimenté par l'instance élue. Cette déduplication a un coût :
  la comparaison des deux vues master/slave, qui servait à repérer un
  désaccord, disparaît du device de ligne. Elle est compensée par un
  `binary_sensor` de divergence exposé sur le device watchdog (voir
  ci-dessous) — un état de ligne qui diffère entre instances est un
  symptôme, pas un affichage redondant.
- **`Watchdog <instance>`** — un device par instance (Dijon-master,
  Dijon-slave, Nice-master, Nice-slave) pour les capteurs propres au
  watchdog : les 8 historiques (`score`, `gateway`, `internet`,
  `reboots_today`, `status`, RTT gateway/internet, `uptime` — enrichis en
  `device_class`/`state_class` mais **`unique_id` et type d'entité
  inchangés**, aucune recréation), plus 7 nouveaux : divergence, état du
  peer (avec âge), et les métriques hôte (température CPU, disque libre,
  disque utilisé %, mémoire disponible, charge — stdlib seule, sans
  dépendance).

**Le bouton armé** : `switch` *Armer le reboot* + `button` *Reboot* +
`sensor` *Dernière action*, sur le device de l'équipement TP-Link. Le
reboot est **refusé** tant que le switch arm n'est pas actif — l'appuyer
sans armer au préalable est un no-op **volontaire**, pas un bug : le
capteur *Dernière action* publie systématiquement un résultat (`ok` ou
`refused`) avec son **motif**, y compris sur un refus, pour qu'un opérateur
ne presse jamais le bouton en boucle sans retour. Le switch arm se
désarme automatiquement après `MQTT_ARM_TIMEOUT` secondes (défaut 30 s)
s'il n'est pas utilisé.

**Variables** :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SITE_ID` | dérivé de `INSTANCE_ID` | Regroupe les devices « par site » (USG, TP-Link) — dérivé en retirant les suffixes `_master`/`_slave`/`_primary`/`_secondary` |
| `MQTT_COMMANDS_ENABLED` | `false` | Active l'écoute des commandes entrantes (switch arm + button reboot) |
| `MQTT_ARM_TIMEOUT` | `30` (min 5) | Secondes avant désarmement automatique |

> **Avertissement de sécurité (C9)** : activer `MQTT_COMMANDS_ENABLED` ouvre
> une voie de commande entrante capable de déclencher un reboot — la
> deuxième voie de commande entrante du projet, après l'API HTTP.
> Quiconque peut publier sur le broker peut déclencher une action.
> **N'activez `MQTT_COMMANDS_ENABLED` que sur un broker authentifié**
> (`MQTT_USERNAME`/`MQTT_PASSWORD` configurés) — sur un broker anonyme,
> laissez l'écoute désactivée.

> **Recommandation opérateur** : n'activez `MQTT_COMMANDS_ENABLED` que sur
> **une seule instance par site** — le **guardian** (l'instance qui porte
> le lien direct vers le MR110, voir « Lignes de secours TP-Link »
> ci-dessus). Armer les deux instances d'un même site multiplie
> inutilement la surface de commande sans bénéfice fonctionnel.

**Quota data** (exemple, forfait 110 Go / mois avec reset le 27 du mois) :

```bash
TPLINK_1_QUOTA_VOLUME_MB=110000
TPLINK_1_QUOTA_ALERT_PCT=80          # défaut 80
TPLINK_1_QUOTA_RESET_DAY=27          # défaut 1
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
vigil/
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
│   ├── confirm.py                # Confirmation à capacité (boutons Ntfy)
│   ├── messages.py               # Templates messages
│   ├── notifier/
│   │   ├── __init__.py
│   │   ├── _types.py             # Level, NotificationContext
│   │   ├── _dispatch.py          # Dispatch multi-canaux
│   │   ├── _ntfy.py              # Ntfy
│   │   └── _email.py             # Email SMTP
│   └── __init__.py
├── updater/
│   ├── update.py                 # Auto-updater principal
│   └── preflight.py              # Validation avant deployment
├── systemd/
│   ├── vigil.service      # Unit systemd (sandboxing)
│   ├── vigil.logrotate    # Rotation logs
│   ├── vigil-updater.service
│   └── vigil-updater.timer
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
2. Tester manuellement : `ssh -i /opt/vigil/.ssh/usg_ed25519 maintenance@192.168.1.1`
3. Relancer setup : `sudo ./scripts/setup_ssh.sh`
4. Vérifier clé publique sur USG : `cat ~/.ssh/authorized_keys`

### "Peer unreachable" en permanent

1. Vérifier que secondary tourne : `sudo systemctl status vigil` sur l'autre machine
2. Vérifier PEER_IP / HTTP_PORT correct dans `/opt/vigil/.env`
3. Tester ping : `ping 192.168.1.51`
4. Consulter logs de secondary : `sudo journalctl -u vigil -f`
5. Vérifier firewall entre les machines

### Reboots très fréquents

Vérifier :
- Score anormalement haut (dans logs)
- Pattern ISP non détecté (gateway OK, internet KO prolongé)
- Cooldown peut-être trop bas : augmenter `REBOOT_COOLDOWN`
- Mode surveillance activé ? (Max reboots/jour dépassé) - voir logs

### Logs vides ou pas de notifications

1. Vérifier niveau log : `cat /var/log/vigil.log`
2. Augmenter verbosité : `echo "LOG_LEVEL=DEBUG" >> /opt/vigil/.env && sudo systemctl restart vigil`
3. Pour Ntfy : tester avec `curl -H "Authorization: Bearer $NTFY_TOKEN" -d "test" $NTFY_URL/$NTFY_TOPIC`
4. HTTP port disponible ? `sudo netstat -tlnp | grep 9000`
5. Vérifier permissions fichier log : `sudo ls -l /var/log/vigil.log`

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
3. Vérifier que watchdog tourne : `sudo systemctl status vigil`
4. Vérifier CPU/mémoire : `free -h && uptime`
5. Vérifier logs du serveur HTTP : `sudo journalctl -u vigil -f`

### Notifications non reçues

Ntfy :
- Tester publication : `curl -H "Authorization: Bearer $NTFY_TOKEN" -d "test" $NTFY_URL/$NTFY_TOPIC`
- Vérifier `NTFY_MIN_LEVEL`
- Vérifier que le serveur est joignable en LAN/Tailscale (jamais via
  Cloudflare pour la publication interne, voir INVARIANTS.md)

Email :
- Tester SMTP : `python3 -c "import smtplib; smtplib.SMTP('host', 587).login('user', 'pass')"`
- Vérifier TLS : port 587 ou 465
- Vérifier credentials dans .env

### DDNS ne se met pas à jour

1. Vérifier configuration : `curl http://localhost:9000/api/config | grep CLOUDFLARE`
2. Tester manuellement : `curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/ddns/update`
3. Vérifier logs : `sudo journalctl -u vigil -f | grep -i ddns`
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
sudo systemctl status vigil

# Logs temps réel
sudo journalctl -u vigil -f

# Logs complets
sudo tail -f /var/log/vigil.log

# Événements historiques
curl http://localhost:9000/api/events | python3 -m json.tool

# Redémarrer le watchdog (pas le USG)
sudo systemctl restart vigil

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
echo "LOG_LEVEL=DEBUG" >> /opt/vigil/.env
sudo systemctl restart vigil
```

---

## Auto-updater

Le watchdog inclut un système d'auto-mise-à-jour.

Installation :

```bash
sudo systemctl enable vigil-updater.timer
sudo systemctl start vigil-updater.timer
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
sudo systemctl start vigil-updater
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

- **Utilisateur dédié** : `vigil` (non-root, nologin)
- **Virtualenv isolé** : `/opt/vigil/venv`
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
- Variables d'environnement dans `/opt/vigil/.env` (chmod 600)
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

1. Créer une issue GitHub : https://github.com/jsoyer/vigil/issues
2. Fournir : configuration, logs, étapes de reproduction
3. Pour les contributions : fork, feature branch, tests, PR

---

**Dernière mise à jour** : 2026-03-31 (v1.7.0)

**Python** : 3.11+

**Dépendances principales** : paramiko (SSH), requests (HTTP), stdlib only (threading, queue, dataclass)
