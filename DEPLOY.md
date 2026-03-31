# Guide de déploiement — USG Watchdog v1.7.0

## Prérequis

- Raspberry Pi avec Raspbian/Debian (ou tout Linux avec systemd)
- Python 3.11+
- Accès SSH au USG (clé Ed25519)
- (optionnel) rclone configuré pour backup UniFi
- (optionnel) Bot Telegram créé via @BotFather

---

## Premier déploiement (nouvelle machine)

### 1. Cloner le repo

```bash
cd /home/pi
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

**Note** : Si vous avez une clé existante, vous pouvez sauter cette étape et copier manuellement :

```bash
sudo mkdir -p /opt/usg-watchdog/.ssh
sudo cp ~/.ssh/usg_ed25519 /opt/usg-watchdog/.ssh/
sudo cp ~/.ssh/usg_ed25519.pub /opt/usg-watchdog/.ssh/
sudo cp ~/.ssh/known_hosts /opt/usg-watchdog/.ssh/
sudo chown -R root:root /opt/usg-watchdog/.ssh
sudo chmod 700 /opt/usg-watchdog/.ssh
sudo chmod 600 /opt/usg-watchdog/.ssh/usg_ed25519
```

### 3. Créer le fichier .env

```bash
sudo mkdir -p /opt/usg-watchdog
sudo nano /opt/usg-watchdog/.env
```

**Configuration minimale** :

```bash
# USG
USG_IP=192.168.1.1
USG_USER=maintenance

# Telegram (recommandé, optionnel)
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id
```

**Configuration recommandée (ajouter)** :

```bash
# DDNS Cloudflare (optionnel)
CLOUDFLARE_API_TOKEN=votre_token
CLOUDFLARE_ZONE_ID=votre_zone_id
CLOUDFLARE_RECORD_NAMES=home.example.com

# Backup UniFi (optionnel, si machine hôte UniFi)
UNIFI_BACKUP_DIR=/home/pi/docker/unifi-network-server/data/data/backup/autobackup
UNIFI_BACKUP_RCLONE_DEST=drive:Unifi
UNIFI_BACKUP_RETENTION_DAYS=30

# Autres canaux de notification (optionnel)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz

# Ntfy (optionnel, alertes self-hosted)
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=usg-watchdog

# MQTT / Home Assistant (optionnel)
MQTT_BROKER=192.168.1.50

# Dual-instance HA (optionnel, sur la 2eme machine)
INSTANCE_PRIORITY=2
PEER_IP=192.168.1.10

# API Token (protege les endpoints POST : reboot, pause, etc.)
# Generer avec : openssl rand -hex 32
API_TOKEN=coller_le_token_ici
```

**Email SMTP** (optionnel) :

```bash
SMTP_HOST=mail.example.com
SMTP_PORT=587
SMTP_FROM=watchdog@example.com
SMTP_TO=admin@example.com
SMTP_USERNAME=watchdog
SMTP_PASSWORD=password
SMTP_MIN_LEVEL=WARNING
```

**Sécuriser le fichier** :

```bash
sudo chmod 600 /opt/usg-watchdog/.env
sudo chown root:root /opt/usg-watchdog/.env
```

### 4. Vérifier la configuration (optionnel)

```bash
# Test de connectivité
sudo ./scripts/test.sh

# Test de reboot (ATTENTION: va redémarrer le USG ~30s)
sudo ./scripts/test.sh --reboot
```

### 5. Déployer

```bash
sudo ./scripts/deploy.sh
```

Ce script :
- Crée l'utilisateur système `usg-watchdog`
- Installe les fichiers dans `/opt/usg-watchdog/`
- Crée le virtualenv et installe les dépendances
- Configure le service systemd avec hardening
- Démarre le watchdog immédiatement

### 6. Vérifier le démarrage

```bash
# Status du service
sudo systemctl status usg-watchdog

# Logs en temps réel
sudo journalctl -u usg-watchdog -f

# Health check
curl http://localhost:9000/health | python3 -m json.tool

# Dashboard web
# Ouvrir http://192.168.1.50:9000/ dans un navigateur sur le LAN
```

### 7. (Recommandé) Installer l'auto-updater

```bash
sudo systemctl enable usg-watchdog-updater.timer
sudo systemctl start usg-watchdog-updater.timer
```

Vérifier que le timer est actif :

```bash
sudo systemctl list-timers | grep usg-watchdog
```

Le timer vérifie GitHub à **3h du matin** chaque jour. Si une nouvelle version (tag vX.Y.Z) est disponible, elle est téléchargée, validée, appliquée et testée automatiquement. En cas d'échec, rollback automatique vers version précédente.

---

## Migration depuis anciens scripts

Si vous utilisiez les scripts externes (update-cloudflare-dns.sh, backup-unifi.sh, tailscale-cloudflare-dnssync), vous pouvez les désactiver :

### update-cloudflare-dns.sh

**Remplacé par** : `src/ddns_cloudflare.py` (maintenant intégré)

```bash
# Supprimer cron ou systemd timer
sudo systemctl stop update-cloudflare-dns.timer 2>/dev/null
sudo systemctl disable update-cloudflare-dns.timer 2>/dev/null
sudo rm -f /etc/systemd/system/update-cloudflare-dns.*
```

**Configuration** : Ajouter à `/opt/usg-watchdog/.env` :

```bash
CLOUDFLARE_API_TOKEN=xxx
CLOUDFLARE_ZONE_ID=xxx
CLOUDFLARE_RECORD_NAMES=home.example.com,vpn.example.com
```

### backup-unifi.sh

**Remplacé par** : `src/backup_unifi.py` (maintenant intégré)

```bash
# Supprimer cron
sudo crontab -e
# Commenter/supprimer la ligne du backup
```

**Configuration** : Ajouter à `/opt/usg-watchdog/.env` :

```bash
UNIFI_BACKUP_DIR=/path/to/unifi/backups
UNIFI_BACKUP_RCLONE_DEST=drive:Unifi
UNIFI_BACKUP_RETENTION_DAYS=30
UNIFI_BACKUP_SCHEDULE_HOUR=4
```

### tailscale-cloudflare-dnssync

**Remplacé par** : `src/tailscale_dns.py` (maintenant intégré)

```bash
# Supprimer cron ou systemd timer
sudo systemctl stop tailscale-dnssync.timer 2>/dev/null
sudo systemctl disable tailscale-dnssync.timer 2>/dev/null
```

**Configuration** : Ajouter à `/opt/usg-watchdog/.env` :

```bash
TAILSCALE_API_KEY=tskey-api-xxx
TAILSCALE_TAILNET=your-tailnet
TAILSCALE_DNS_SUBDOMAIN=ts
```

---

## Mettre à jour une installation existante

### Méthode 1 : Auto-updater (recommandé)

Si l'auto-updater est installé, il suffit d'attendre 3h du matin ou de forcer :

```bash
sudo systemctl start usg-watchdog-updater
```

Vérifier les logs :

```bash
sudo journalctl -u usg-watchdog-updater -f
```

Attendre le health check final (~30s).

### Méthode 2 : Mise à jour manuelle

```bash
cd /home/pi/usg-watchdog    # Ou le répertoire du repo
git pull origin main
sudo ./scripts/deploy.sh
```

`deploy.sh` :
- Copie les nouveaux fichiers (atomiquement)
- Met à jour les dépendances si nécessaire
- Valide la configuration
- Redémarre le service
- Vérifie que le service est actif

### Méthode 3 : Depuis une archive

```bash
cd /tmp
wget https://github.com/jsoyer/usg-watchdog/archive/refs/tags/v1.7.0.tar.gz
tar xzf v1.7.0.tar.gz
cd usg-watchdog-1.7.0

sudo ./scripts/deploy.sh
```

---

## Vérifier la version

```bash
# Via l'API
curl -s http://localhost:9000/health | python3 -m json.tool | grep version

# Via le fichier
cat /opt/usg-watchdog/VERSION
```

---

## Configuration par machine

### Machine principale (Primary)

```bash
# /opt/usg-watchdog/.env
USG_IP=192.168.1.1
USG_USER=maintenance
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
API_TOKEN=xxx
INSTANCE_PRIORITY=1
```

### Machine secondaire (Secondary, optionnel pour HA)

```bash
# /opt/usg-watchdog/.env
USG_IP=192.168.1.1
USG_USER=maintenance
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
API_TOKEN=xxx
INSTANCE_PRIORITY=2
PEER_IP=192.168.1.10   # IP de la machine primary
HTTP_PORT=9000
```

### Machine qui héberge UniFi

Ajouter au .env :

```bash
UNIFI_BACKUP_DIR=/path/to/unifi/backups
UNIFI_BACKUP_RCLONE_DEST=drive:Unifi
UNIFI_BACKUP_RETENTION_DAYS=30
UNIFI_BACKUP_SCHEDULE_HOUR=4
UNIFI_BACKUP_MAX_AGE_HOURS=48
```

**Note** : Configurer rclone au préalable :

```bash
rclone config
# Ajouter une destination (ex: Google Drive comme "drive")
# Puis utiliser UNIFI_BACKUP_RCLONE_DEST=drive:Unifi
```

### Machine avec DDNS Cloudflare

Ajouter au .env :

```bash
CLOUDFLARE_API_TOKEN=xxx         # Token (Zone edit)
CLOUDFLARE_ZONE_ID=xxx           # Zone ID
CLOUDFLARE_RECORD_NAMES=home.example.com,vpn.example.com
CLOUDFLARE_PROXIED=false         # true/false
CLOUDFLARE_TTL=120               # TTL secondes
DDNS_CHECK_INTERVAL=1800         # Check periodiqu (30 min)
```

### Machine avec Tailscale DNS Sync

Ajouter au .env :

```bash
TAILSCALE_API_KEY=tskey-api-xxx
TAILSCALE_TAILNET=your-tailnet@gmail.com
TAILSCALE_DNS_SUBDOMAIN=ts       # Optionnel
TAILSCALE_SYNC_INTERVAL=600      # Check toutes les 10 min
```

---

## Commandes utiles

```bash
# Statut du service
sudo systemctl status usg-watchdog

# Logs temps réel
sudo journalctl -u usg-watchdog -f

# Redémarrer le watchdog (pas le USG)
sudo systemctl restart usg-watchdog

# Forcer une mise à jour
sudo systemctl start usg-watchdog-updater

# Forcer une pause (maintenance réseau)
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" \
  http://localhost:9000/api/pause

# Reprendre
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" \
  http://localhost:9000/api/resume

# Forcer un reboot USG
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" \
  http://localhost:9000/api/reboot

# Forcer une vérification DDNS
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" \
  http://localhost:9000/api/ddns/update

# Forcer un backup UniFi
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" \
  http://localhost:9000/api/backup/unifi

# Voir l'uptime SLA du mois
curl http://localhost:9000/api/sla | python3 -m json.tool

# Voir les événements récents
curl http://localhost:9000/api/events?count=10 | python3 -m json.tool

# Export configuration
curl http://localhost:9000/api/backup/config > watchdog-config.json
```

---

## Via le bot Telegram

Envoyer ces commandes au bot depuis votre téléphone :

```
/status          Etat complet du watchdog
/pause [min]     Mode surveillance (optionnel: durée en minutes)
/resume          Reprendre les reboots
/reboot          Forcer un reboot USG
/ddns            Forcer une vérification DDNS
/backup          Lancer un backup UniFi
/tailscale       Forcer un sync Tailscale
/help            Aide des commandes
```

---

## Variables d'environnement obligatoires

| Variable | Exemple | Description |
|----------|---------|-------------|
| `USG_IP` | `192.168.1.1` | IP locale du routeur USG |
| `USG_USER` | `maintenance` | Username SSH du USG |

Toutes les autres sont optionnelles avec defaults sensibles.

---

## Variables d'environnement importantes

| Variable | Défaut | Description |
|----------|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | _(vide)_ | Token bot Telegram pour notifications |
| `TELEGRAM_CHAT_ID` | _(vide)_ | Chat ID destination Telegram |
| `API_TOKEN` | _(vide)_ | Token d'auth pour endpoints POST (vide = LAN only) |
| `CLOUDFLARE_API_TOKEN` | _(vide)_ | Token API Cloudflare pour DDNS |
| `CLOUDFLARE_ZONE_ID` | _(vide)_ | Zone ID Cloudflare |
| `CLOUDFLARE_RECORD_NAMES` | _(vide)_ | Records A à mettre à jour (virgules) |
| `INSTANCE_PRIORITY` | `1` | 1=primary, 2+=secondary (HA) |
| `PEER_IP` | _(vide)_ | IP du peer (vide = standalone) |

Voir README.md pour la liste complète (~50 variables).

---

## Désinstaller

```bash
sudo ./scripts/uninstall.sh
```

Ce script :
- Arrête le service
- Désactive les timers
- Supprime les fichiers
- Demande confirmation pour clés SSH et logs

---

## Dépannage

### Service ne démarre pas

```bash
# Vérifier les erreurs
sudo journalctl -u usg-watchdog -n 50

# Vérifier la config
sudo cat /opt/usg-watchdog/.env

# Tester manually
sudo -u usg-watchdog python3 -m src.watchdog
```

### SSH échoue

```bash
# Tester manuellement
ssh -i /opt/usg-watchdog/.ssh/usg_ed25519 maintenance@192.168.1.1

# Vérifier clé sur USG
# SSH sur USG, puis : cat ~/.ssh/authorized_keys

# Relancer setup
sudo ./scripts/setup_ssh.sh
```

### Notifications ne fonctionnent pas

**Telegram** :
```bash
# Tester token
curl https://api.telegram.org/bot<TOKEN>/getMe

# Vérifier chat_id
# Envoyer "/start" au bot et vérifier logs
```

**Discord/Slack** :
```bash
# Tester webhook
curl -X POST <WEBHOOK_URL> -d '{"content":"test"}' -H "Content-Type: application/json"
```

### DDNS ne met pas à jour

```bash
# Tester manuellement
curl -X POST -H "Authorization: Bearer TOKEN" \
  http://localhost:9000/api/ddns/update

# Vérifier logs
sudo journalctl -u usg-watchdog -f | grep -i ddns

# Vérifier token Cloudflare (permissions Zone.DNS edit)
```

### Backup UniFi échoue

```bash
# Vérifier rclone
rclone ls <destination>

# Vérifier dossier source
ls -la /path/to/unifi/backups

# Tester manuellement
curl -X POST -H "Authorization: Bearer TOKEN" \
  http://localhost:9000/api/backup/unifi

# Vérifier espace disque
df -h
```

---

## Performance et ressources

**Utilisation CPU** : ~2-5% en veille (Raspberry Pi 4)
**Utilisation RAM** : ~40-50 MB
**Disque** : ~50 MB pour l'installation
**Bande passante** : Minimal (~1 KB/cycle de 30s)

---

## Support

Pour des questions ou bugs :

1. Consulter README.md (documentation complète)
2. Vérifier les logs : `sudo journalctl -u usg-watchdog -f`
3. Consulter WORKFLOW.md (pour commandes de base)
4. Créer une issue GitHub : https://github.com/jsoyer/usg-watchdog/issues

---

**Dernière mise à jour** : 2026-03-31 (v1.7.0)

**Version cible** : Python 3.11+

**Auto-updater** : Récupère les tags depuis GitHub, valide, déploie, rollback auto
