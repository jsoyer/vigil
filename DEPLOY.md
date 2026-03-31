# Guide de deploiement -- USG Watchdog

## Prerequis

- Raspberry Pi avec Raspbian/Debian (ou tout Linux avec systemd)
- Python 3.11+
- Acces SSH au USG (cle Ed25519)
- (optionnel) rclone configure pour le backup UniFi
- (optionnel) Bot Telegram cree via @BotFather

## Premier deploiement (nouvelle machine)

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
- Genere une cle Ed25519 dans `/opt/usg-watchdog/.ssh/`
- Capture la cle hote du USG (known_hosts)
- Deploie la cle publique sur le USG
- Teste la connexion

### 3. Creer le fichier .env

```bash
sudo mkdir -p /opt/usg-watchdog
sudo nano /opt/usg-watchdog/.env
```

Contenu minimum :

```bash
# USG
USG_IP=192.168.1.1
USG_USER=maintenance

# Telegram (obtenir via @BotFather)
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id

# Protection API (generer un token aleatoire)
API_TOKEN=un_token_secret_aleatoire
```

Optionnel (ajouter selon vos besoins) :

```bash
# DDNS Cloudflare
CLOUDFLARE_API_TOKEN=votre_token
CLOUDFLARE_ZONE_ID=votre_zone_id
CLOUDFLARE_RECORD_NAMES=home.example.com

# Backup UniFi (uniquement sur la machine qui host UniFi)
UNIFI_BACKUP_DIR=/home/pi/docker/unifi-network-server/data/data/backup/autobackup
UNIFI_BACKUP_RCLONE_DEST=drive:Unifi

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy

# Ntfy (self-hosted pour alertes meme sans internet)
NTFY_URL=http://pi-ntfy:8080
NTFY_TOPIC=watchdog

# MQTT / Home Assistant
MQTT_BROKER=192.168.1.50

# Dual-instance (sur la 2eme machine uniquement)
INSTANCE_PRIORITY=2
PEER_IP=192.168.1.10
```

Securiser le fichier :

```bash
sudo chmod 600 /opt/usg-watchdog/.env
sudo chown root:root /opt/usg-watchdog/.env
```

### 4. Deployer

```bash
sudo ./scripts/deploy.sh
```

Ce script :
- Cree l'utilisateur systeme `usg-watchdog`
- Installe les fichiers dans `/opt/usg-watchdog/`
- Cree le virtualenv et installe les dependances
- Installe le service systemd
- Demarre le watchdog

### 5. Verifier

```bash
# Status du service
sudo systemctl status usg-watchdog

# Logs en temps reel
sudo journalctl -u usg-watchdog -f

# Dashboard (depuis un navigateur sur le LAN)
# http://adresse-du-pi:9000/

# Health check
curl http://localhost:9000/health

# Test rapide
sudo ./scripts/test.sh
```

### 6. Installer l'auto-updater

```bash
sudo cp systemd/usg-watchdog-updater.service /etc/systemd/system/
sudo cp systemd/usg-watchdog-updater.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable usg-watchdog-updater.timer
sudo systemctl start usg-watchdog-updater.timer
```

Verifier que le timer est actif :

```bash
sudo systemctl list-timers | grep usg-watchdog
```

Le timer verifie GitHub a 3h du matin chaque jour. Si une nouvelle version est disponible, elle est telechargee, validee, et appliquee automatiquement.

---

## Mettre a jour une installation existante

### Methode 1 : Auto-updater (recommande)

Si l'auto-updater est installe, il suffit d'attendre 3h du matin ou de forcer :

```bash
sudo systemctl start usg-watchdog-updater
```

Verifier les logs :

```bash
sudo journalctl -u usg-watchdog-updater -f
```

### Methode 2 : Mise a jour manuelle

```bash
cd /home/pi/usg-watchdog    # ou le repertoire du repo
git pull origin main
sudo ./scripts/deploy.sh
```

`deploy.sh` :
- Copie les nouveaux fichiers (atomiquement)
- Met a jour les dependances si necessaire
- Redemarre le service
- Verifie que le service est actif

### Methode 3 : Si le repo n'est pas clone sur la machine

```bash
# Telecharger la derniere version
cd /tmp
wget https://github.com/jsoyer/usg-watchdog/archive/refs/tags/v1.6.1.tar.gz
tar xzf v1.6.1.tar.gz
cd usg-watchdog-1.6.1

# Deployer
sudo ./scripts/deploy.sh
```

---

## Verifier la version en cours

```bash
# Via l'API
curl -s http://localhost:9000/health | python3 -m json.tool | grep version

# Via le fichier
cat /opt/usg-watchdog/VERSION 2>/dev/null || cat /opt/usg-watchdog/src/../VERSION 2>/dev/null
```

---

## Configuration par machine

### Machine principale (primary)

```bash
# .env minimum
USG_IP=192.168.1.1
USG_USER=maintenance
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
API_TOKEN=xxx
INSTANCE_PRIORITY=1
```

### Machine secondaire (secondary, optionnel)

```bash
# .env
USG_IP=192.168.1.1
USG_USER=maintenance
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
API_TOKEN=xxx
INSTANCE_PRIORITY=2
PEER_IP=192.168.1.10   # IP de la machine primary
```

### Machine qui host UniFi (ajouter au .env)

```bash
UNIFI_BACKUP_DIR=/home/pi/docker/unifi-network-server/data/data/backup/autobackup
UNIFI_BACKUP_RCLONE_DEST=drive:Unifi
UNIFI_BACKUP_RETENTION_DAYS=30
```

### Machine avec DDNS Cloudflare (ajouter au .env)

```bash
CLOUDFLARE_API_TOKEN=xxx
CLOUDFLARE_ZONE_ID=xxx
CLOUDFLARE_RECORD_NAMES=home.example.com,vpn.example.com
```

---

## Commandes utiles au quotidien

```bash
# Etat du service
sudo systemctl status usg-watchdog

# Logs temps reel
sudo journalctl -u usg-watchdog -f

# Redemarrer le watchdog (pas le USG)
sudo systemctl restart usg-watchdog

# Forcer une mise a jour
sudo systemctl start usg-watchdog-updater

# Forcer un check DDNS
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" http://localhost:9000/api/ddns/update

# Forcer un backup UniFi
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" http://localhost:9000/api/backup/unifi

# Pause (maintenance reseau)
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" http://localhost:9000/api/pause

# Resume
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" http://localhost:9000/api/resume

# Maintenance planifiee (2h)
curl -X POST -H "Authorization: Bearer VOTRE_TOKEN" -d '{"duration_minutes":120}' http://localhost:9000/api/maintenance

# SLA du mois
curl http://localhost:9000/api/sla

# Derniers evenements
curl http://localhost:9000/api/events?count=10
```

## Via le bot Telegram

Envoyer au bot depuis votre telephone :

```
/status   - Etat complet
/pause    - Mode surveillance
/resume   - Reprendre
/reboot   - Forcer un reboot USG
/ddns     - Forcer une MAJ DNS
/backup   - Lancer un backup UniFi
/help     - Aide
```

---

## Desinstaller

```bash
sudo ./scripts/uninstall.sh
```

Supprime le service, le timer, les fichiers. Demande confirmation pour les cles SSH et les logs.
