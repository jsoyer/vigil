# USG Watchdog 🔌

> Surveillance de connexion fibre + reboot automatique du USG Ubiquiti via SSH

## Fonctionnement

```
[systemd] → [watchdog.py] → ping 8.8.8.8 / 1.1.1.1 / 9.9.9.9
                          ↓ (3 échecs consécutifs = 90s de coupure)
                       SSH → sudo reboot → USG redémarre
                          ↓
                    Telegram : "🔴 Connexion DOWN — Reboot en cours"
                    Telegram : "✅ Connexion rétablie"
```

**Cooldown de 10 min** après chaque reboot pour éviter les boucles infinies.

## Prérequis

- Fedora / Linux avec systemd
- Python 3.11+
- SSH activé sur le USG (UniFi Controller → Settings → Device Authentication)
- (optionnel) Bot Telegram pour les notifications

## Installation rapide

### 1. Cloner le dépôt

```bash
git clone git@github.com:VOTRE_USERNAME/usg-watchdog.git
cd usg-watchdog
```

### 2. Configurer

Éditer `src/config.py` :

```python
USG_IP   = "192.168.1.1"   # IP de votre USG
USG_USER = "admin"          # Username SSH (souvent 'admin' ou 'root')

# Telegram (optionnel)
TELEGRAM_BOT_TOKEN = "123456:ABC..."
TELEGRAM_CHAT_ID   = "123456789"
```

### 3. Setup SSH (une seule fois)

```bash
sudo ./scripts/setup_ssh.sh
```

Ce script :
- Génère une clé RSA 4096 bits dédiée dans `/opt/usg-watchdog/.ssh/`
- Déploie la clé publique sur le USG via `ssh-copy-id`
- Teste la connexion sans mot de passe

### 4. Tester la config

```bash
./scripts/test.sh
```

Test du reboot réel (⚠️ coupe le réseau ~30s) :
```bash
sudo ./scripts/test.sh --reboot
```

### 5. Déployer

```bash
sudo ./scripts/deploy.sh
```

Le service démarre immédiatement et se relance automatiquement au boot.

## Commandes utiles

```bash
# Statut du service
sudo systemctl status usg-watchdog

# Logs en temps réel
sudo journalctl -u usg-watchdog -f

# Logs fichier
sudo tail -f /var/log/usg-watchdog.log

# Redémarrer le watchdog (pas le USG)
sudo systemctl restart usg-watchdog

# Désinstaller proprement
sudo ./scripts/uninstall.sh
```

## Structure du projet

```
usg-watchdog/
├── src/
│   ├── watchdog.py      # Boucle principale + logique de seuil
│   ├── config.py        # Toute la configuration
│   ├── connectivity.py  # Ping multi-cibles
│   ├── usg.py           # Reboot SSH via paramiko
│   └── notifier.py      # Notifications Telegram
├── systemd/
│   ├── usg-watchdog.service    # Unit systemd
│   └── usg-watchdog.logrotate  # Rotation des logs
├── scripts/
│   ├── setup_ssh.sh    # Génération et déploiement de la clé SSH
│   ├── deploy.sh       # Déploiement complet
│   ├── test.sh         # Tests de validation
│   └── uninstall.sh    # Désinstallation propre
├── requirements.txt
├── .gitignore
└── README.md
```

## Configuration avancée

Toutes les valeurs de `config.py` peuvent être surchargées via variables d'environnement :

```bash
# Dans /etc/systemd/system/usg-watchdog.service
Environment="CHECK_INTERVAL=60"
Environment="FAILURE_THRESHOLD=5"
Environment="REBOOT_COOLDOWN=1200"
Environment="LOG_LEVEL=DEBUG"
```

| Variable              | Défaut                          | Description                         |
|-----------------------|---------------------------------|-------------------------------------|
| `USG_IP`              | `192.168.1.1`                   | IP locale du USG                    |
| `USG_USER`            | `admin`                         | Username SSH                        |
| `USG_SSH_KEY`         | `/opt/usg-watchdog/.ssh/usg_rsa`| Clé SSH privée                      |
| `CHECK_INTERVAL`      | `30`                            | Délai entre checks (secondes)       |
| `FAILURE_THRESHOLD`   | `3`                             | Échecs consécutifs avant reboot     |
| `REBOOT_COOLDOWN`     | `600`                           | Cooldown post-reboot (secondes)     |
| `TELEGRAM_BOT_TOKEN`  | _(vide)_                        | Token bot Telegram                  |
| `TELEGRAM_CHAT_ID`    | _(vide)_                        | Chat ID Telegram                    |
| `LOG_LEVEL`           | `INFO`                          | Niveau de log                       |

## Setup Telegram

1. Créer un bot via `@BotFather` sur Telegram → noter le token
2. Envoyer un message à votre bot
3. Récupérer votre `chat_id` :
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Renseigner `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `src/config.py`

## Sécurité

- ✅ Authentification par clé SSH uniquement (pas de mot de passe en clair)
- ✅ La clé SSH est dans `/opt/usg-watchdog/.ssh/` — **jamais dans le dépôt git**
- ✅ `.gitignore` exclut tous les fichiers sensibles
- ✅ Cooldown anti-boucle de reboot
- ✅ Ping multi-cibles pour éviter les faux positifs
