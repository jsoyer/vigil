# Vigil v2.0.0 — CLAUDE.md

Guide architectural et procédures développement pour Vigil.

> **Anciennement USG Watchdog.** Ce projet s'appelait *USG Watchdog* jusqu'à
> la version 1.8.3. À partir de la 2.0.0 il est renommé **Vigil** — le dépôt
> GitHub `jsoyer/usg-watchdog` a été renommé `jsoyer/vigil` (redirection
> GitHub active sur l'ancien nom). Le routeur Ubiquiti surveillé continue
> d'être désigné « USG » dans la documentation et le code (`src/usg.py`,
> `USG_IP`, etc.) — seul le nom du logiciel change. Procédure de migration
> complète : voir `docs/RELEASE-NOTES-2.0.0.md`.

## Vue d'ensemble du projet

Vigil est un système de surveillance de connexion internet et de redémarrage automatique du routeur Ubiquiti USG, fonctionnant sur Raspberry Pi ou Linux. Il combine :

- **Système de scoring** : Pénalités pour défaillances, récupération si rétablissement
- **Circuit breaker** : Backoff exponentiel, limite quotidienne, détection panne ISP
- **3 canaux de notification actifs** : Ntfy (principal, boutons d'action), Email SMTP, MQTT (télémétrie séparée)
- **Haute disponibilité** : Coordination multi-instance avec failover basé sur priorité
- **Fonctionnalités avancées** : DDNS Cloudflare, Tailscale sync, Backup UniFi, Speedtest, Prometheus metrics
- **Confirmation par capacité** : boutons d'action Ntfy + dashboard pour les décisions opérateur (reboot TP-Link, pause/resume, etc.)
- **API HTTP complète** : 15+ endpoints pour monitoring et contrôle
- **Dashboard responsive PWA** : Interface web avec support offline
- **Auto-updater** : Récupère versions depuis GitHub, valide, déploie, rollback auto

## Architecture

### Structure des fichiers

```
src/
├── watchdog.py               # Boucle principale + scoring + circuit breaker
├── config.py                 # Configuration (toutes les env vars + defaults)
├── state.py                  # WatchdogState immutable + StateHolder + queue commandes
├── connectivity.py           # check_connectivity() + ping gateway + internet
├── usg.py                    # reboot_usg() via SSH paramiko
├── drivers/                  # Contrats + implementations RouterDriver (A1, MR110 TP-Link)
│   ├── _base.py               # Contrat RouterDriver (Protocol) : Hop, Readiness, dataclasses (C1: aucun import vendor)
│   └── tplink.py               # TplinkDriver -- sonde etagee MR110, import tplinkrouterc6u paresseux (C1)
├── managed_devices.py         # Registre des equipements TP-Link pilotables (verrou session, cache, confirmation)
├── confirm.py                 # Jetons de confirmation generiques pour actions destructives (usage unique, TTL court)
├── events.py                 # EventLog ring buffer + persistence JSON
├── http_server.py            # API HTTP + endpoints JSON + dashboard
├── peer.py                   # Coordination multi-instance (failover logic)
├── dashboard.py              # HTML dashboard intégré (zéro dépendances)
├── pwa.py                    # PWA manifest.json + service worker (offline)
├── report.py                 # Rapports quotidiens/hebdomadaires
├── history.py                # Historique persisté (metriques + événements)
├── diagnostics.py            # Traceroute + SNMP monitoring
├── metrics.py                # Prometheus exposition format (/metrics)
├── ddns_cloudflare.py        # DDNS Cloudflare (remplace script shell)
├── tailscale_dns.py          # Tailscale DNS sync
├── backup_unifi.py           # Backup UniFi via rclone
├── multiwan.py               # Multi-WAN detection (failover)
├── speedtest.py              # Speedtest intégré (100KB download)
├── snmp_monitor.py           # Lecture métriques USG (CPU, mémoire)
├── mqtt_publisher.py         # MQTT / Home Assistant auto-discovery
├── alert_escalation.py       # Escalade d'alertes si pas ACK
├── messages.py               # Templates messages (tous les canaux)
├── notifier/
│   ├── __init__.py           # Public API: notify(message, level, context)
│   ├── _types.py             # Level enum + NotificationContext
│   ├── _dispatch.py          # Dispatch multi-canaux en parallèle
│   ├── _ntfy.py              # Ntfy (self-hosted possible)
│   └── _email.py             # Email SMTP (TLS)
└── __init__.py

updater/
├── update.py                 # Principal logic: download, validate, deploy, health check, rollback
└── preflight.py              # Validation syntaxe + imports

systemd/
├── vigil.service              # Unit hardening: ProtectSystem, PrivateTmp, CAP_NET_RAW, etc.
├── vigil-updater.service
├── vigil-updater.timer
└── vigil.logrotate

scripts/
├── setup_ssh.sh              # Setup SSH (Ed25519, known_hosts, test)
├── deploy.sh                 # Installation complète (user, venv, systemd)
├── test.sh                   # Tests pré-déploiement
├── uninstall.sh              # Suppression propre
├── validate.sh               # Validation pré-commit
└── release.sh                # Tagging + versioning
```

### Composants clés

#### watchdog.py

Boucle principale qui :
1. Appelle `check_connectivity()` pour statut gateway + internet
2. Calcule `compute_cycle_delta()` pour mise à jour score
3. Gère les cooldowns (reboot, SSH)
4. Détecte les pannes ISP (pattern gateway OK + internet KO prolongé)
5. Consulte le peer si HA configuré
6. Exécute reboot si seuil atteint + conditions OK
7. Enregistre événements
8. Envoie rapports quotidiens/hebdomadaires
9. Lance les tâches périodiques (DDNS, Tailscale, Backup, Speedtest)
10. Gère l'escalade d'alertes

#### config.py

Centralise TOUS les paramètres :
- Env vars via `_get_env()` et `_get_int_env()`
- Validation au startup (ex: IP addresses)
- Pas de hardcoding
- Defaults sensibles

Catégories :
- Connexion : ping targets, timeouts
- Scoring : seuils, deltas, decays
- Circuit breaker : cooldowns, grace, limites
- SSH backoff : paliers exponentiel
- ISP detection : durée pattern
- Notifications (Ntfy, SMTP)
- MQTT + Home Assistant
- DDNS Cloudflare, Tailscale, Backup UniFi
- Rapports (quotidien, hebdo)
- Coordination peer (HA)
- API + Logging

#### state.py

Immutabilité stricte :
- `WatchdogState` : @dataclass(frozen=True)
  - Snapshot complète chaque cycle (~50 champs)
  - Inclut : score, statuts, timestamps, historique cooldowns, info peer, etc.
- `StateHolder` : mutable reference à WatchdogState
  - Atomically swapped par main loop
  - Thread-safe (GIL)
  - Accessible en lecture par HTTP thread
- Command queue : pause, resume, reboot depuis endpoints POST

#### connectivity.py

Ping checks multi-threaded :
- `check_connectivity()` → ConnectivityResult
- Gateway ping + RTT
- Internet check (3 targets en parallèle)
- Latency tracking + dégradation detection

#### usg.py

SSH reboot via paramiko :
- Ed25519 key auth preferred, fallback password
- Known_hosts verification (MITM prevention)
- Timeout handling
- Never raises (failures logged)

#### http_server.py

API HTTP + dashboard :
- 15+ endpoints (GET /health, /api/state, /api/events, /api/config, /api/report, /api/sla, /api/history, /metrics, /manifest.json, /sw.js, /dashboard, POST /api/pause, /resume, /reboot, /maintenance, /ddns/update, /backup/unifi)
- Dashboard HTML responsive (zéro dépendances JS)
- Auth token optionnel (Bearer)
- Runs in daemon thread

#### peer.py

Coordination HA :
- `query_peer()` → HTTP GET /api/state
- `should_reboot()` → decision logic (primary vs secondary)
- Failover logic : secondary attend PEER_TAKEOVER_DELAY avant prendre relais
- Divergence detection : alerte si écart score > 6

#### events.py

Ring buffer thread-safe (~100 événements) :
- Event : frozen dataclass (ts, type, data)
- EventLog : thread-safe append + persistence JSON
- Types : startup, shutdown, reboot, reboot_failed, recovery, isp_outage, isp_recovery, peer_standdown, ssh_backoff, max_reboots, divergence, etc.
- Persisté à `/var/log/vigil-events.json`
- Rechargé au startup

#### notifier/

3 canaux de notification actifs :
1. Ntfy (self-hosted ou cloud, boutons d'action)
2. Email SMTP (TLS)
3. MQTT (Home Assistant + auto-discovery, télémétrie séparée -- pas un
   canal `notify()`)

Chaque canal :
- Never raises (failures logged)
- Respects MIN_LEVEL filtering
- Templated messages
- Parallel dispatch

#### dashboard.py

Interface web :
- HTML + CSS intégré (zéro dépendances)
- Responsive (mobile, tablette, desktop)
- Dark mode (GitHub style)
- Auto-refresh (5s)
- Charts (score, latency, uptime)

#### Fonctionnalités avancées

**ddns_cloudflare.py** : Sync IP publique → Cloudflare DNS
- Détecte IP change
- Update records A
- Triggerd : reboot recovery + periodic check

**tailscale_dns.py** : Sync Tailscale DNS public
- Récupère machines du tailnet
- Create DNS records
- Periodic sync (10 min)

**backup_unifi.py** : Backup UniFi via rclone
- Monitor dossier autobackup
- Upload à destination
- Retention policy
- Alerte si trop vieux

**multiwan.py** : Détection failover dual-WAN
- Query USG routing table via SSH
- Identify active WAN interface

**speedtest.py** : Test débit intégré
- Download 100KB depuis CDN
- Periodic (10 min)
- Alerte si dégradation

**snmp_monitor.py** : Lecture métriques USG
- CPU, mémoire, interfaces
- Via SNMP v2

**metrics.py** : Prometheus exposition
- Endpoint /metrics
- 15+ gauges + counters
- Grafana compatible

**alert_escalation.py** : Escalade d'alertes
- Si CRITICAL non supprimée après N min
- Re-envoi via canaux prioritaires

#### messages.py

Templates messages pour tous les canaux :
1. Quoi : qu'est-ce qui s'est passé ?
2. Pourquoi : quelle est la cause probable ?
3. Quoi faire : quelle action est attendue ?

Templates incluent contexte riche (score, latences, peer status, etc.)

## Conventions clés

### Configuration

- **TOUTES les config via env vars** dans config.py
- Helper : `_get_env()`, `_get_int_env()`
- Validation au startup
- Pas de hardcoding

### Immutabilité

- WatchdogState, ConnectivityResult, Event = @dataclass(frozen=True)
- État updates créent nouveaux objets
- StateHolder reference atomiquement swappée

### Logging

- **Messages en français**
- Pas d'emojis dans logs (sauf messages utilisateurs)
- Niveaux : DEBUG, INFO, WARNING, ERROR, CRITICAL
- Via `logging` module (jamais print)

### Thread Safety

- Main loop atomic state swap via GIL
- EventLog utilise threading.Lock
- HTTP thread lit état gelé (readonly)
- Commands queueés via thread-safe queue.Queue

### Notifications

- `notify()` never raises
- Dispatch en parallèle
- Filtrage par MIN_LEVEL par canal
- Templated messages

## Workflow de développement

### Branching

- `main` = production (auto-updater tire vX.Y.Z)
- `dev` = integration des features
- Hotfixes (bugs, CVE) → main direct

### Routing des changements

| Type | Branche | Version | PR ? |
|------|---------|---------|------|
| Bug | main | patch | Non |
| CVE | main | patch | Non |
| Feature | dev → PR → main | minor | Oui |
| Breaking | dev → PR → main | major | Oui |
| Docs | main | aucun | Non |

### Avant chaque push

```bash
./scripts/validate.sh   # Tests + coverage >= 80% + imports check
```

### Procédure bug fix / CVE

```bash
# 1. Fix + test
# 2. Commit
git add <files>
git commit -m "fix: description"
# 3. Tag + push
./scripts/release.sh patch
git push origin main
git push origin v<new_version>
# 4. Sync dev
git checkout dev && git cherry-pick <sha> && git push origin dev && git checkout main
```

### Procédure feature

```bash
# 1. Dev sur dev
git checkout dev
# ... commits ...
git push origin dev
# 2. Create PR
gh pr create --base main --head dev --title "feat: ..." --label feature
# 3. Après approbation
gh pr merge <number> --merge
# 4. Tag + push
git checkout main && git pull
./scripts/release.sh minor
git push origin main && git push origin v<new_version>
# 5. Sync dev
git checkout dev && git merge main && git push origin dev
```

### GitHub Issues (tracabilité obligatoire)

```bash
# Créer issue
gh issue create --title "fix: description" --label bug --body "Details..."

# Lier commit (ferme auto au push)
git commit -m "fix: description (closes #42)"

# Créer PR liée
gh pr create --title "feat: ..." --body "Closes #42"

# Lister issues
gh issue list
```

## Common Tasks

### Ajouter un canal de notification

1. Créer `src/notifier/_channel_name.py` :

```python
import logging
from notifier._types import Level, NotificationContext

def send_channel_name(message: str, level: Level, context: NotificationContext | None = None) -> bool:
    """Send notification. Never raise."""
    try:
        # Send logic
        return True
    except Exception as e:
        logging.error("channel_name error: %s", e)
        return False
```

2. Update `src/notifier/_dispatch.py` pour appeler votre fonction
3. Add config vars à `src/config.py` (ex: CHANNEL_WEBHOOK_URL, CHANNEL_MIN_LEVEL)
4. Check configured in _dispatch avant d'appeler

### Ajouter un endpoint API

1. Dans `src/http_server.py`, handler class method :

```python
elif self.path == "/api/new_endpoint":
    self._handle_new_endpoint()

def _handle_new_endpoint(self) -> None:
    snapshot = holder.state
    if snapshot is None:
        self._respond_json(503, {"error": "not ready"})
        return
    # Build response
    self._respond_json(200, data)
```

2. Tests : `pytest tests/test_http_server.py::test_new_endpoint -v`

### Ajouter une config var

1. Dans `src/config.py` :

```python
MY_PARAM: int = _get_int_env("MY_PARAM", default=100, minimum=10)
```

2. Importer dans watchdog.py si utilisée
3. Optionnel : exposer dans `/api/config`
4. Documenter en README

### Modifier scoring

1. Ajuster multipliers dans `src/config.py`
2. Update `compute_cycle_delta()` si logique change
3. Run tests : `pytest tests/test_watchdog.py::test_compute_cycle_delta -v`

## Running Tests

```bash
# Tous les tests avec coverage
pytest --cov=src --cov-report=term-missing --cov-fail-under=80

# Fichier spécifique
pytest tests/test_watchdog.py -v

# Unit seulement
pytest -m unit

# Integration seulement
pytest -m integration

# Test unique
pytest tests/test_watchdog.py::test_compute_cycle_delta -v
```

Marques disponibles :
- `@pytest.mark.unit` : tests rapides, isolés
- `@pytest.mark.integration` : tests I/O (network, SSH stubs)

Target : 80%+ coverage

## Déploiement

### Développement

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 -m src.watchdog
```

### Production

```bash
# Setup SSH (one-time)
sudo ./scripts/setup_ssh.sh

# Test connectivity + SSH
sudo ./scripts/test.sh

# Full deploy
sudo ./scripts/deploy.sh

# Post-deploy
sudo systemctl status vigil
sudo journalctl -u vigil -f
```

Service : `/etc/systemd/system/vigil.service`
User : `vigil` (non-root)
Install : `/opt/vigil`
Logs : `/var/log/vigil.log`
Logrotate : `/etc/logrotate.d/vigil`

## Versioning

Format : `MAJOR.MINOR.PATCH`

| Type | Bump |
|------|------|
| Bug fix | patch |
| CVE | patch |
| Feature | minor |
| Breaking | major |

Auto-updater récupère les tags depuis GitHub (v1.7.0, etc.)

## Performance Notes

- Main loop : ~100ms par cycle (30s CHECK_INTERVAL)
- HTTP server : daemon thread, non-blocking
- EventLog : ring buffer locked pendant append seulement
- State : frozen dataclass, memcpy rapide
- Notifications : dispatched in parallel threads

## Security Checklist

- [ ] SSH : Ed25519 keys, known_hosts verification, strict rejection
- [ ] Permissions : user=vigil, files 600/700
- [ ] Systemd : ProtectSystem, PrivateTmp, NoNewPrivileges, CAP_NET_RAW only
- [ ] API Token : authentification Bearer si sensible
- [ ] Secrets : JAMAIS hardcodés, env vars seulement, .env chmod 600
- [ ] Logs : pas d'info sensible en clair
- [ ] Input validation : toutes les env vars validées au startup

## File Tree Example

Après déploiement, structure `/opt/vigil/` :

```
/opt/vigil/
├── src/                     # Source code
├── venv/                    # Python virtualenv
├── .ssh/
│   ├── usg_ed25519         # Private key (600)
│   ├── usg_ed25519.pub     # Public key
│   └── known_hosts         # USG public key
├── .env                    # Config (600) — NOT in git
└── VERSION                 # Current version tag
```

## Related Files

- README.md : Documentation utilisateur (v1.7.0)
- DEPLOY.md : Installation + migration
- WORKFLOW.md : Workflow pour non-devs
- CLAUDE.md : Ce fichier (architecture + procédures dev)

---

**Last Updated** : 2026-03-31 (v1.7.0)

**Python** : 3.11+

**Key Dependencies** : paramiko (SSH), requests (HTTP), stdlib only (threading, queue, dataclass, logging)

**Test Coverage Target** : 80%+

**Code Style** : PEP 8 + black + isort + ruff
