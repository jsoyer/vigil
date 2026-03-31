# USG Watchdog

Daemon de surveillance de connexion internet et redémarrage automatique du routeur Ubiquiti USG, fonctionnant sur Raspberry Pi ou Linux. Conçu pour les connexions fibre instables avec détection intelligente des pannes ISP, coordination multi-instance et notifications multi-canaux.

## Vue d'ensemble

Le projet surveille deux éléments clés toutes les 30 secondes (configurable) :
- **Gateway LAN** : Le routeur USG répond-il au ping ?
- **Internet** : Trois cibles externes (Google DNS, Cloudflare, Quad9) répondent-elles ?

Un système de **scoring** avec circuit breaker décide automatiquement de redémarrer le USG, en tenant compte de la fréquence des défaillances, des pannes ISP détectées et des limites quotidiennes de redémarrage.

### Caractéristiques principales

- **Scoring intelligent** : Pas de simple seuil. Points pour gateway KO, points pour internet partiel/KO, récupération quand tout va bien
- **Circuit breaker complet** : Backoff exponentiel, limite de 10 reboots/jour, détection de panne ISP, backoff SSH
- **Notifications multi-canaux** : Telegram, Discord, Slack avec filtrage par niveau par canal
- **Haute disponibilité** : Coordination multi-instance avec failover basé sur priorité, détection de divergence
- **API HTTP** : État complet, historique d'événements, configuration, rapports
- **Dashboard LAN** : Interface web accessible sur le réseau local
- **Rapport quotidien** : Synthèse des pannes, reboots et récupérations
- **Sécurité renforcée** : SSH avec clés Ed25519, sandboxing systemd, utilisateur dédié

## Fonctionnement détaillé

### Système de scoring

Chaque cycle (par défaut 30 secondes), le score de défaillance est mis à jour selon les résultats :

| Scénario | Delta |
|----------|-------|
| Gateway OK + Internet 3/3 | -2 |
| Gateway OK + Internet 2/3 | -1 |
| Gateway OK + Internet 1/3 | +1 |
| Gateway OK + Internet 0/3 | +3 |
| Gateway KO + Internet quelconque | +4 |
| Score maximal (plafond) | 15 |
| Seuil de reboot | 10 |

Le score est borné entre 0 et 15 pour éviter l'accumulation infinie. Un score >= 10 déclenche un reboot (si les autres conditions le permettent).

### Circuit breaker

Le watchdog empêche les boucles infinites de reboots :

1. **Grace post-reboot** (6 min) : Après un reboot, les échecs sont ignorés pour laisser le USG se stabiliser
2. **Cooldown exponentiel** : Chaque reboot double le cooldown (base 15 min)
   - Reboot 1 : 15 min
   - Reboot 2 : 30 min
   - Reboot 3 : 60 min
   - Reboot 4+ : jusqu'à 4 heures max
3. **Limite quotidienne** : Max 10 reboots/jour. Au-delà, le watchdog passe en mode surveillance (alerte seulement)
4. **Backoff SSH** : Après 3 échecs SSH consécutifs, délai exponentiel avant nouvelles tentatives

### Détection de panne ISP

Pattern détecté : Gateway OK + Internet 0/3 pendant 30 minutes = probable panne ISP. Dans ce cas :
- Les reboots sont ralentis (inutiles si la panne est chez le FAI)
- Une notification d'alerte est envoyée
- Le watchdog continue la surveillance

### Coordination multi-instance

Mode optionnel pour deux instances (primary + secondary) sur le même réseau :

1. **Instance primary** (priority=1) agit en premier si seuil atteint
2. **Instance secondary** (priority=2) attend 3 min avant de prendre le relais si primary ne répond pas
3. **Divergence détectée** : Si les deux instances voient des scores très différents (écart >6), alerte pour identifier un problème local

Les deux instances se consultent via HTTP sur le port 9000 (configurable).

## Installation rapide

### Prérequis

- Raspberry Pi ou Linux (Fedora / Debian) avec systemd
- Python 3.11+
- SSH activé sur le USG (Settings > Device Authentication)
- (optionnel) Bot Telegram / Webhook Discord / Slack

### 1. Cloner le dépôt

```bash
git clone https://github.com/jsoyer/usg-watchdog.git
cd usg-watchdog
```

### 2. Configurer les variables d'environnement

Éditer ou créer `/opt/usg-watchdog/.env` (sera chargé par systemd) :

```bash
# IP et user SSH du USG
USG_IP=192.168.1.1
USG_USER=maintenance

# Notifications (optionnel)
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHIjklmnoPQRstuvWXYz
TELEGRAM_CHAT_ID=987654321
DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Coordination multi-instance (optionnel)
INSTANCE_PRIORITY=1
PEER_IP=192.168.1.50
```

Tous les paramètres sont optionnels ; les valeurs par défaut sont conservées.

### 3. Configurer les clés SSH (une seule fois)

```bash
sudo ./scripts/setup_ssh.sh
```

Ce script :
- Génère une clé Ed25519 dans `/opt/usg-watchdog/.ssh/`
- Demande confirmation de l'empreinte du USG
- Déploie la clé publique sur le USG (via ssh-copy-id)
- Teste la connexion sans mot de passe

### 4. Déployer et démarrer

```bash
sudo ./scripts/deploy.sh
```

Le script :
- Crée l'utilisateur système `usg-watchdog`
- Installe le virtualenv et les dépendances
- Configure le service systemd
- Démarre immédiatement le watchdog

### 5. Vérifier le démarrage

```bash
sudo systemctl status usg-watchdog
sudo journalctl -u usg-watchdog -f
```

## Configuration complète

Tous les paramètres peuvent être surchargés via variables d'environnement (dans `/opt/usg-watchdog/.env` ou en ligne de commande) :

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

### Notifications Telegram

| Variable | Défaut | Description |
|----------|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | _(vide)_ | Token bot Telegram |
| `TELEGRAM_CHAT_ID` | _(vide)_ | Chat ID cible |
| `TELEGRAM_TIMEOUT` | `5` | Timeout requête (secondes) |
| `TELEGRAM_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Notifications Discord

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DISCORD_WEBHOOK_URL` | _(vide)_ | URL webhook Discord |
| `DISCORD_TIMEOUT` | `5` | Timeout requête (secondes) |
| `DISCORD_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Notifications Slack

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SLACK_WEBHOOK_URL` | _(vide)_ | URL webhook Slack |
| `SLACK_TIMEOUT` | `5` | Timeout requête (secondes) |
| `SLACK_MIN_LEVEL` | `INFO` | Niveau min : INFO, WARNING, CRITICAL |

### Coordination multi-instance

| Variable | Défaut | Description |
|----------|--------|-------------|
| `INSTANCE_PRIORITY` | `1` | Priorité (1=primary, 2+=secondary) |
| `PEER_IP` | _(vide)_ | IP du peer (vide=mode standalone) |
| `PEER_PORT` | `9000` | Port HTTP du peer |
| `HTTP_PORT` | `9000` | Port HTTP local |
| `PEER_TAKEOVER_DELAY` | `180` | Délai avant secondary prend relais (s) |

### Rapport quotidien

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DAILY_REPORT_HOUR` | `8` | Heure envoi rapport (0-23, -1=désactivé) |

### Logging

| Variable | Défaut | Description |
|----------|--------|-------------|
| `LOG_LEVEL` | `INFO` | Niveau : DEBUG, INFO, WARNING, ERROR |
| `LOG_FILE` | `/var/log/usg-watchdog.log` | Chemin fichier log |

## API HTTP

Le watchdog expose une API HTTP sur le port 9000 (configurable), accessible sur le réseau local.

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
  "peer": {
    "status": "healthy",
    "score": 0,
    "gateway": "OK",
    "internet": "3/3"
  }
}
```

Statuts possibles : `healthy`, `degraded`, `critical`, `surveillance`, `starting`

### GET /api/state

État complet (pour le peer ou monitoring).

```bash
curl http://192.168.1.50:9000/api/state
```

Retourne la snapshot immutable du watchdog (50+ champs).

### GET /api/events

Historique des événements (ring buffer ~100 events).

```bash
curl "http://192.168.1.50:9000/api/events?count=20&type=reboot"
```

Query params : `count` (défaut 50), `type` (optionnel)

Types : `startup`, `shutdown`, `reboot`, `reboot_failed`, `recovery`, `isp_outage`, `isp_recovery`, `peer_standdown`, `ssh_backoff`, `max_reboots`, `divergence`, etc.

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

Retourne : reboots, pannes, récupérations d'aujourd'hui.

### POST /api/pause

Passer en mode surveillance (pas de reboot, alerte seulement).

```bash
curl -X POST http://192.168.1.50:9000/api/pause
```

### POST /api/resume

Reprendre les reboots normaux.

```bash
curl -X POST http://192.168.1.50:9000/api/resume
```

### POST /api/reboot

Déclencher un reboot immédiatement (ignore les cooldowns).

```bash
curl -X POST http://192.168.1.50:9000/api/reboot
```

### GET / ou /dashboard

Interface web HTML (responsive, dark mode, zéro dépendances externes).

```
http://192.168.1.50:9000/dashboard
```

Affiche : statut en direct, score/seuil, gateway/internet, reboots du jour, 20 derniers événements, trace peer.

## Configuration multi-instance

### Scénario : Primary + Secondary avec failover

**Instance 1 (Primary):**
```bash
# /opt/usg-watchdog/.env sur instance 1
INSTANCE_PRIORITY=1
PEER_IP=192.168.1.51
HTTP_PORT=9000
```

**Instance 2 (Secondary):**
```bash
# /opt/usg-watchdog/.env sur instance 2
INSTANCE_PRIORITY=2
PEER_IP=192.168.1.50
HTTP_PORT=9000
```

**Comportement :**
1. Primary surveille, décide de redémarrer si seuil atteint
2. Primary notifie le secondary avant chaque reboot
3. Si primary devient injoignable (network/crash), secondary attend 3 min puis prend le relais
4. Si divergence détectée (scores très différents), les deux envoient une alerte

### Consultation du peer

```bash
# From primary, voir l'état du secondary
curl http://192.168.1.51:9000/api/state
```

## Dashboard

Le dashboard HTML intégré affiche :

- **Statut** : indicateur de couleur (healthy = vert, degraded = orange, critical = rouge, surveillance = violet)
- **Score** : valeur actuelle et barre de progression vers le seuil
- **Connectivité** : gateway OK/KO, internet X/3, uptime
- **Reboots** : tentatives aujourd'hui vs limite quotidienne
- **Peer** : statut du secondary (standalone si pas configuré)
- **Événements** : 20 derniers événements avec timestamps et contexte
- **ISP** : alerte si panne ISP détectée

Accessible sur : `http://192.168.1.50:9000/` ou `http://192.168.1.50:9000/dashboard`

Design :
- Responsive (adapté mobile / tablette / desktop)
- Dark mode (GitHub style)
- Auto-refresh (requête /health toutes les 5 secondes)
- Zéro dépendances JavaScript externes

## Commandes utiles

```bash
# Statut du service
sudo systemctl status usg-watchdog

# Logs en temps réel
sudo journalctl -u usg-watchdog -f

# Logs fichier
sudo tail -f /var/log/usg-watchdog.log

# Événements historiques
sudo tail -f /var/log/usg-watchdog-events.json

# Redémarrer le watchdog (pas le USG)
sudo systemctl restart usg-watchdog

# Activer mode surveillance (API)
curl -X POST http://192.168.1.50:9000/api/pause

# Reprendre les reboots (API)
curl -X POST http://192.168.1.50:9000/api/resume

# Déclencher reboot manuel (API)
curl -X POST http://192.168.1.50:9000/api/reboot

# Voir les logs au démarrage
sudo systemctl start usg-watchdog && sudo journalctl -u usg-watchdog -f
```

## Sécurité

### Authentification SSH

- **Clés Ed25519 uniquement** : Compatible EdgeOS 6.6.1 (USG vieux firmware)
- **Known_hosts** : Vérification de la clé hôte du USG (MITM prevention)
- **Rejet strict** : `RejectPolicy` si la clé change (détecte intrusion)
- **Algorithmes négociés** : Désactif rsa-sha2-* pour forcer ed25519 avec vieux OpenSSH

### Permissions

- **Utilisateur dédié** : `usg-watchdog` (non-root, nologin)
- **Virtualenv isolé** : `/opt/usg-watchdog/venv` (dépendances locales)
- **SSH dir 700** : Clés privées accessibles uniquement au watchdog
- **Log file 640** : Logs lisibles par adm seulement

### Sandboxing systemd

- **ProtectSystem=strict** : Système de fichiers read-only (sauf logs)
- **PrivateTmp=yes** : Temp dir dédié
- **NoNewPrivileges=yes** : Aucune escalade de privilèges possible
- **RestrictNamespaces=yes** : Namespaces limités
- **RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX** : Seulement TCP/UDP et Unix sockets
- **DevicePolicy=closed** : Aucun accès aux devices
- **CAP_NET_RAW** : Seule capacité (pour ping)

### Gestion des secrets

- Aucun token/mot de passe hardcodé
- Variables d'environnement dans `/opt/usg-watchdog/.env` (chmod 600)
- Fichier ignoré par git (dans `.gitignore`)
- Jamais de logs d'authentification en clair

### Architecture d'événements

- Ring buffer en mémoire (~100 événements)
- Persistance JSON sur disque (/var/log/usg-watchdog-events.json)
- Thread-safe (locks)
- Survit aux redémarrages du watchdog (chargement au startup)

## Structure du projet

```
usg-watchdog/
├── src/
│   ├── watchdog.py       # Boucle principale + scoring + circuit breaker
│   ├── config.py         # Toute la configuration (env vars)
│   ├── connectivity.py   # Ping gateway + internet
│   ├── usg.py            # Reboot SSH paramiko
│   ├── notifier.py       # Notifications (Telegram/Discord/Slack)
│   ├── state.py          # Snapshots immuables + queue commandes
│   ├── http_server.py    # API HTTP + endpoint health/state/events
│   ├── peer.py           # Coordination multi-instance
│   ├── events.py         # Ring buffer events + persistence
│   ├── dashboard.py      # Dashboard HTML intégré
│   ├── report.py         # Rapport quotidien
│   └── __init__.py       # Package marker
├── systemd/
│   ├── usg-watchdog.service    # Unit systemd (sandboxing, hardening)
│   └── usg-watchdog.logrotate  # Rotation logs
├── scripts/
│   ├── setup_ssh.sh      # Clé Ed25519 + known_hosts + test
│   ├── deploy.sh         # Installation complète + systemd
│   ├── test.sh           # Tests pré-déploiement
│   ├── uninstall.sh      # Suppression propre
│   └── lib/
│       └── logging.sh     # Utilitaires shell
├── requirements.txt      # Dépendances Python
├── .gitignore            # Exclut .env, clés SSH, logs
└── README.md             # Ce fichier
```

### Fichiers clés

| Fichier | Rôle |
|---------|------|
| `watchdog.py` | Boucle principale avec scoring, circuit breaker, détection ISP |
| `config.py` | Centralise tous les paramètres (env var overridables) |
| `connectivity.py` | Ping gateway + internet (3 cibles) |
| `usg.py` | SSH Paramiko, Ed25519, négociation algos EdgeOS |
| `peer.py` | Requêtes HTTP vers secondary, failover logic |
| `http_server.py` | API HTTP multi-endpoints, dashboard HTML |
| `events.py` | Ring buffer thread-safe, persistence JSON |
| `notifier.py` | Envoi messages Telegram/Discord/Slack |

## Dépendances

```
paramiko>=2.12      # SSH
requests>=2.28      # HTTP client (notifications)
```

Installées automatiquement par `scripts/deploy.sh`.

## Dépannage

### SSH échoue avec "Connection refused"

1. Vérifier SSH activé sur USG : Settings > Device Authentication
2. Tester manuellement : `ssh -i /opt/usg-watchdog/.ssh/usg_ed25519 maintenance@192.168.1.1`
3. Relancer setup : `sudo ./scripts/setup_ssh.sh`

### "Peer unreachable" en permanent

1. Vérifier que secondary tourne : `sudo systemctl status usg-watchdog` sur l'autre machine
2. Vérifier PEER_IP / HTTP_PORT correct dans `/opt/usg-watchdog/.env`
3. Tester ping : `ping 192.168.1.51`
4. Consulter logs de secondary : `sudo journalctl -u usg-watchdog -f`

### Reboots très fréquents

Vérifier :
- Score anormalement haut (gateway.log.warning)
- Pattern ISP non détecté (gateway OK, internet KO prolongé)
- Cooldown peut-être trop bas : augmenter `REBOOT_COOLDOWN`
- Mode surveillance activé ? (Max reboots/jour dépassé)

### Logs vides ou pas de notifications

1. Vérifier niveau log : `cat /var/log/usg-watchdog.log`
2. Pour Telegram : tester token/chat_id avec `curl`
3. HTTP port disponible ? `sudo netstat -tlnp | grep 9000`

### "Divergence detectee" entre instances

Cela signifie local et peer voient des états très différents (écart score >6).
Solutions :
- Vérifier connectivité réseau entre les deux machines
- Vérifier que les deux surveillent la même gateway
- Vérifier `PING_TARGETS` identique sur les deux

## Rapport quotidien

Un rapport automatique est envoyé chaque jour à 8h (configurable avec `DAILY_REPORT_HOUR`).

Contenu :
- Nombre de reboots / échecs reboots
- Nombre de pannes (recovery events)
- Durations des pannes
- Nombre de pannes ISP détectées
- Uptime estimée
- Statut du peer

Exemple :
```
2024-01-15 -- Rapport quotidien
Uptime : 99.2%
Pannes : 2 (16m20s, 8m)
Reboots : 3 reussis, 0 echoues
Reboots a aide : 2/2
Pannes ISP : 0 detectees
Peer : healthy
```

## Tests

Avant déploiement, tester la configuration :

```bash
# Tests basiques
./scripts/test.sh

# Test connexion SSH réelle
./scripts/test.sh --reboot
```

Cela coupe effectivement le réseau ~30s pendant le reboot du USG. Utile pour valider le setup complet.

## Logs

### Console et fichier

- Console : STDOUT via systemd
- Fichier : `/var/log/usg-watchdog.log` (rotaté automatiquement)
- Événements : `/var/log/usg-watchdog-events.json` (ring buffer persisted)

### Rotation

Fichier `/etc/logrotate.d/usg-watchdog` gère :
- Max 10 MB par fichier
- 5 fichiers d'archives
- Compression gzip

### Niveaux

- `DEBUG` : Pings détaillés, état du peer
- `INFO` : Checks normaux, scoring
- `WARNING` : Seuil atteint, ISP pattern, SSH backoff
- `ERROR` : Authentification SSH, réseau, commandes
- `CRITICAL` : Crash, shutdown

## Contribution

Pour améliorer le watchdog :

1. Fork et créer une branche feature
2. Respecter les conventions commit (feat:, fix:, etc.)
3. Tester avant PR
4. Documenter les nouveaux paramètres

## Licence

MIT - voir LICENSE

## Troubleshooting avancé

### Forcer un reboot via API

```bash
curl -X POST http://localhost:9000/api/reboot
```

Cela déclenche immédiatement, en ignorant cooldown et grace period. Enregistré en événement `api_reboot`.

### Désactiver les reboots temporairement

```bash
curl -X POST http://localhost:9000/api/pause
```

Mode surveillance : alerte seulement, pas de reboot (utilisé auto si max_reboots/jour atteint).

### Consulter historique événements

```bash
# JSON complet
curl http://localhost:9000/api/events | jq .

# Filtrer par type
curl "http://localhost:9000/api/events?type=reboot"

# Derniers 10 événements
curl "http://localhost:9000/api/events?count=10"
```

### Analyser la divergence peer

Si les deux instances ne s'accordent pas sur la connectivité :

```bash
# Instance 1
curl http://192.168.1.50:9000/api/state | jq '.failure_score, .gateway_ok, .internet_ok_count'

# Instance 2
curl http://192.168.1.51:9000/api/state | jq '.failure_score, .gateway_ok, .internet_ok_count'
```

Si score > 6, vérifier :
- Cibles ping identiques
- Localisation des instances
- Câblage réseau local

### Mode debug

Augmenter le niveau log :

```bash
# Temporaire (session courante)
sudo systemctl stop usg-watchdog
sudo LOG_LEVEL=DEBUG /opt/usg-watchdog/venv/bin/python /opt/usg-watchdog/src/watchdog.py

# Permanent
echo "LOG_LEVEL=DEBUG" >> /opt/usg-watchdog/.env
sudo systemctl restart usg-watchdog
```

Affiche chaque ping, chaque tentative SSH, chaque query peer.

## Conclusion

USG Watchdog offre une surveillance robuste et automatisée de la connectivité internet, adaptée à l'écosystème Ubiquiti USG et aux connexions instables. Le système de scoring, le circuit breaker et la coordination multi-instance assurent une gestion intelligente sans boucles infinies de reboots.
