# USG Watchdog — CLAUDE.md

## Project Overview

USG Watchdog is an automated network monitoring and recovery system for Ubiquiti UniFi Security Gateways (USG). It continuously monitors internet connectivity via multi-target ping checks (Google DNS, Cloudflare, Quad9), applies a scoring system to detect failures, and automatically reboots the USG via SSH when connectivity problems persist. Designed for fiber installations requiring high availability, it includes exponential backoff, ISP outage detection, dual-instance peer coordination, and multi-channel notifications (Telegram, Discord, Slack).

## Architecture

**Core Components:**

- `src/watchdog.py` — Main event loop, scoring logic, reboot orchestration, circuit breaker
- `src/config.py` — Environment-based configuration (all values via env vars, no hardcoding)
- `src/state.py` — Immutable frozen dataclass (WatchdogState) for thread-safe atomic state swaps
- `src/connectivity.py` — Ping gateway + multi-target internet checks
- `src/usg.py` — SSH reboot execution via paramiko
- `src/http_server.py` — Background HTTP server (port 9000) exposing /api/state, /api/health, /dashboard, plus command queue (pause/resume/reboot)
- `src/peer.py` — Multi-instance coordination (primary/secondary with takeover delay)
- `src/events.py` — Thread-safe event history with periodic JSON persistence
- `src/notifier/` — Multi-channel dispatch (Telegram, Discord, Slack) with context-aware templating
- `src/report.py` — Daily report generation
- `src/dashboard.py` — HTML dashboard served at /

**Thread Model:**
- Main thread: watchdog loop (blocking, sleeps CHECK_INTERVAL between cycles)
- HTTP server thread: daemon background thread handling state queries and API commands

**State Management:**
- StateHolder contains mutable reference to immutable WatchdogState
- Main loop atomically swaps state reference each cycle (GIL guarantees atomic pointer assignment)
- HTTP thread reads frozen snapshot, no locks needed for state access
- Commands queued via thread-safe queue from HTTP endpoints → polled by main loop

## Key Conventions

### Configuration
- **All config via env vars** defined in `src/config.py`
- Helper functions: `_get_env()`, `_get_int_env()`
- Validation at startup (e.g., USG_IP, PEER_IP IP address validation)
- No hardcoded values except defaults in config.py

### Immutability
- WatchdogState, ConnectivityResult, Event all use `@dataclass(frozen=True)`
- State updates create new WatchdogState instances, never mutate
- StateHolder.state reference is atomically swapped, never modified in-place

### Logging & Output
- **Log messages in French** (e.g., "Reboot USG en cours", "Connexion retablie")
- No emojis in logs (they clutter log files)
- Emojis OK in notification messages to users
- All logging via `logging` module (never print)
- Log levels: INFO for status, WARNING for issues, ERROR for failures, CRITICAL for severe conditions

### Thread Safety
- Main loop's atomic state swap relies on Python GIL
- EventLog uses threading.Lock for ring buffer access
- HTTP server thread only reads frozen state (no writes)
- Commands from HTTP queued in thread-safe queue.Queue

### Notifications
- `notify(message, level, context)` never raises — failures logged
- Dispatch to all configured channels (Telegram, Discord, Slack) in parallel
- NotificationContext provides structured data for template rendering
- Return dict[str, bool] showing success per channel

## How to Run Tests

```bash
# All tests with coverage
pytest --cov=src --cov-report=term-missing

# Specific test file
pytest tests/test_watchdog.py -v

# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# Single test
pytest tests/test_watchdog.py::test_compute_cycle_delta -v
```

Test categories via `@pytest.mark`:
- `@pytest.mark.unit` — Fast, isolated unit tests
- `@pytest.mark.integration` — Tests touching I/O (network, SSH, HTTP)
- No integration tests for real SSH/reboot (stubbed via fixtures)

Coverage target: 80%+ (currently well above).

## How to Deploy

**Development:**
```bash
# Install deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run locally
python3 -m src.watchdog
```

**Production:**
```bash
# Generate/deploy SSH key (one-time setup)
sudo ./scripts/setup_ssh.sh

# Quick connectivity + SSH test
sudo ./scripts/test.sh

# Full deploy (creates service user, installs virtualenv, enables systemd)
sudo ./scripts/deploy.sh

# Post-deploy
sudo systemctl status usg-watchdog
sudo journalctl -u usg-watchdog -f
sudo tail -f /var/log/usg-watchdog.log
```

**Service Management:**
- Service: `/etc/systemd/system/usg-watchdog.service`
- Runs as: `usg-watchdog` system user
- Install dir: `/opt/usg-watchdog` (src/, venv/, .ssh/)
- Log rotation: `/etc/logrotate.d/usg-watchdog`

## Key Files & Modules

### src/watchdog.py
**Main loop handles:**
- Connectivity checks each cycle (gateway ping + internet multi-target)
- Scoring delta computation (penalties for failures, decay for recovery)
- Grace period post-reboot (ignore failures for POST_REBOOT_GRACE seconds)
- ISP outage pattern detection (gateway OK + internet KO for ISP_OUTAGE_DETECTION_DELAY → skip reboot)
- Exponential backoff cooldown (reboot N doubles cooldown, capped at MAX_REBOOT_COOLDOWN)
- SSH failure backoff (too many SSH failures → gradual retry delays)
- Max reboots/day circuit breaker (>MAX_REBOOTS_PER_DAY → surveillance_only mode)
- Peer coordination via query_peer() (defer to higher-priority peer, wait PEER_TAKEOVER_DELAY if secondary)
- Daily report generation (send at DAILY_REPORT_HOUR via notify)
- Event recording (STARTUP, REBOOT, RECOVERY, ISP_OUTAGE, ISP_RECOVERY, PEER_STANDDOWN, MAX_REBOOTS, etc.)

**Key functions:**
- `compute_cycle_delta(gateway_ok, internet_ok_count)` → int (score change per cycle)
- `compute_effective_cooldown(consecutive_reboots)` → int (exponential backoff)
- `compute_ssh_retry_delay(consecutive_ssh_failures)` → int (SSH backoff)

### src/config.py
All tuning params as module-level vars, read from env via `_get_env()` / `_get_int_env()`.

**Key categories:**
- Ping targets & timeouts (PING_TARGETS, PING_TIMEOUT)
- Scoring thresholds (REBOOT_SCORE_THRESHOLD, MAX_SCORE)
- Score deltas per issue type (SCORE_GATEWAY_DOWN, SCORE_INTERNET_ALL_DOWN, etc.)
- Score decay (SCORE_DECAY_OK, SCORE_DECAY_PARTIAL)
- Grace/cooldown (POST_REBOOT_GRACE, REBOOT_COOLDOWN, MAX_REBOOT_COOLDOWN)
- Max reboots/day (MAX_REBOOTS_PER_DAY)
- SSH backoff (SSH_FAILURE_BACKOFF_START, SSH_FAILURE_COOLDOWN, MAX_SSH_COOLDOWN)
- ISP detection (ISP_OUTAGE_DETECTION_DELAY)
- USG connection (USG_IP, USG_USER, USG_SSH_KEY, USG_KNOWN_HOSTS, USG_SSH_PASSWORD, SSH_TIMEOUT, USG_REBOOT_WAIT, USG_REBOOT_COMMAND)
- Notification channels (TELEGRAM_BOT_TOKEN/CHAT_ID/TIMEOUT/MIN_LEVEL, DISCORD_WEBHOOK_URL, SLACK_WEBHOOK_URL, etc.)
- Peer coordination (INSTANCE_PRIORITY, PEER_IP, PEER_PORT, HTTP_PORT, PEER_TAKEOVER_DELAY)
- Daily report (DAILY_REPORT_HOUR)
- Logging (LOG_LEVEL, LOG_FILE)

### src/state.py
- `WatchdogState` — Frozen dataclass capturing complete snapshot each cycle (failure_score, threshold, gateway/internet status, reboot state, peer info, etc.)
- `StateHolder` — Container with mutable `state: WatchdogState | None` reference (swapped atomically by main loop)
- Command queue for HTTP → main loop communication (pause, resume, reboot commands)

### src/connectivity.py
- `ConnectivityResult` — Frozen dataclass (gateway_ok, internet_ok_count, internet_total)
- `ping_host(host, timeout)` → bool
- `ping_gateway()` → bool (pings USG_IP)
- `check_internet()` → int (count of responding PING_TARGETS)
- `check_connectivity()` → ConnectivityResult

### src/usg.py
- `reboot_usg()` → bool (SSH to USG_IP, execute USG_REBOOT_COMMAND, return success/fail)
- Uses paramiko for SSH (key auth preferred, falls back to password)
- Respects SSH_TIMEOUT config
- Returns bool — never raises (failures logged)

### src/http_server.py
- `start_http_server(StateHolder, port, EventLog)` — starts daemon thread, returns Thread or None
- Handler endpoints:
  - `GET /` or `/dashboard` — HTML dashboard
  - `GET /health` — JSON health summary (status, score, gateway, internet, peer)
  - `GET /api/state` — Full WatchdogState JSON
  - `GET /api/events?count=50&type=reboot` — Event history (queryable)
  - `GET /api/config` — Active tuning params (no secrets)
  - `GET /api/report` — Daily report JSON
  - `POST /api/pause` → sends CMD_PAUSE to main loop
  - `POST /api/resume` → sends CMD_RESUME to main loop
  - `POST /api/reboot` → sends CMD_REBOOT to main loop

### src/peer.py
- `query_peer(peer_ip, peer_port, retries, timeout)` → WatchdogState | None (HTTP GET /api/state)
- `should_reboot(my_state, gateway_ok)` → (proceed: bool, reason: str)
  - Returns proceed decision based on peer priority, peer state, takeover delay
  - Defaults to proceed=True on errors (fail open)
- `get_peer_info()` → dict (fast single-attempt query for display)
- `check_divergence(my_score, my_gateway_ok, my_inet_count)` → str | None (divergence alert)

### src/events.py
- `Event` — Frozen dataclass (ts: ISO timestamp, type: str, data: dict)
- `EventLog` — Thread-safe ring buffer with periodic JSON persistence
  - `record(event_type, **data)` — append event (thread-safe)
  - `get_recent(count)` → list[dict]
  - `get_by_type(event_type)` → list[dict]
  - `count_today(event_type)` → int
  - Persists to /var/log/usg-watchdog-events.json every PERSIST_INTERVAL (3600s)

### src/notifier/
- `__init__.py` — public API: `notify(message, level, context)` → dict[str, bool]
- `_types.py` — `Level` (INFO, WARNING, CRITICAL), `NotificationContext` (context data)
- `_dispatch.py` — `dispatch()` → queries enabled channels, sends in parallel
- `_telegram.py` — Telegram webhook send
- `_discord.py` — Discord webhook send
- `_slack.py` — Slack webhook send

Each channel implementation never raises, returns bool success/fail.

### src/report.py
- `generate_daily_report(event_log, report_date, uptime_seconds, current_score, peer_status)` → dict
- `format_report_notification(report)` → str (human-readable summary)

Generates: event counts (reboots, failures, recoveries), uptime, peer status.

## Common Tasks

### Add a New Notification Channel

1. Create `src/notifier/_channel_name.py`:
   ```python
   import logging
   from notifier._types import Level, NotificationContext

   def send_channel_name(...) -> bool:
       """Send notification to channel. Never raise."""
       try:
           # Send logic
           return True
       except Exception as e:
           logging.error("channel_name error: %s", e)
           return False
   ```

2. Update `src/notifier/_dispatch.py` to call your function in `dispatch()`

3. Add config vars to `src/config.py` (e.g., `CHANNEL_WEBHOOK_URL`, `CHANNEL_TIMEOUT`, `CHANNEL_MIN_LEVEL`)

4. In `_dispatch.py`, check if channel is configured before calling (skip if URL is empty)

5. Test: `pytest tests/test_notifier.py -v`

### Add a New API Endpoint

1. Open `src/http_server.py`, in `do_GET()` or `do_POST()`:
   ```python
   elif self.path == "/api/new_endpoint":
       self._handle_new_endpoint()
   ```

2. Define handler:
   ```python
   def _handle_new_endpoint(self) -> None:
       snapshot = holder.state
       if snapshot is None:
           self._respond_json(503, {"error": "not ready"})
           return
       # Build response from snapshot / event_log
       self._respond_json(200, data)
   ```

3. Test: `pytest tests/test_http_server.py::test_get_new_endpoint -v`

### Add a New Config Variable

1. In `src/config.py`, define with `_get_env()` or `_get_int_env()`:
   ```python
   MY_PARAM: int = _get_int_env("MY_PARAM", default=100, minimum=10)
   ```

2. Import in `src/watchdog.py` if used in main loop logic

3. Optionally expose in `/api/config` endpoint (in `_handle_config()` in http_server.py)

4. Document in systemd service example or README

### Modify Scoring Logic

1. Adjust multipliers in `src/config.py`:
   - SCORE_GATEWAY_DOWN, SCORE_INTERNET_ALL_DOWN, SCORE_INTERNET_PARTIAL
   - SCORE_DECAY_OK, SCORE_DECAY_PARTIAL

2. Update scoring function `compute_cycle_delta()` if logic changes

3. Run `pytest tests/test_watchdog.py::test_compute_cycle_delta -v`

4. Verify main loop integration test passes: `pytest tests/test_watchdog.py -v`

### Deploy a Change

Use the workflow below. Never commit directly without running validation.

---

## Development Workflow

### Branching

- `main` = production. L'auto-updater tire les tags `vX.Y.Z` depuis cette branche.
- `dev` = integration des features. Les features atterrissent ici avant d'etre promues en prod.
- Hotfixes (bugs, CVE) vont directement sur `main`, pas besoin de passer par `dev`.

### Routing des changements

| Type | Branche cible | Version bump | PR requise ? |
|------|---------------|-------------|-------------|
| Bug fix | `main` | patch | Non |
| CVE/securite | `main` | patch | Non |
| Feature | `dev` -> PR -> `main` | minor | Oui |
| Breaking change | `dev` -> PR -> `main` | major | Oui |
| Documentation | `main` | aucun | Non |

### GitHub Issues -- Tracabilite obligatoire

**Toujours creer une issue GitHub avant de commencer a travailler.** C'est le point de reference pour l'utilisateur.

#### Quand creer une issue

| Situation | Label | Action |
|-----------|-------|--------|
| Utilisateur signale un bug | `bug` | Creer issue, fixer, fermer avec le commit |
| Audit detecte des problemes | `bug` ou `security` | 1 issue par probleme |
| Nouvelle feature demandee | `feature` | Issue comme spec, PR liee |
| CVE detectee | `security` | Issue, fix immediat, fermeture |
| Probleme detecte mais pas urgent | `bug` | Issue ouverte, priorisee plus tard |
| Amelioration identifiee (non demandee) | `feature` | Issue ouverte, proposee a l'utilisateur |

#### Commandes

```bash
# Creer une issue
gh issue create --title "fix: description" --label bug --body "Details..."

# Lier un commit a une issue (fermeture automatique au push)
git commit -m "fix: description du probleme (closes #42)"

# Lier une PR a une issue
gh pr create --title "feat: ..." --body "Closes #42"

# Fermer manuellement avec commentaire
gh issue close 42 --comment "Resolu dans v1.0.1"

# Lister les issues ouvertes
gh issue list
```

#### Regles

- Le mot-cle `closes #N` dans un commit ou une PR ferme l'issue automatiquement au merge/push.
- Pour les bugs : creer l'issue d'abord, meme si le fix est trivial. Ca laisse une trace.
- Pour les features : l'issue sert de spec. La PR la reference.
- Pour les audits : creer les issues en batch, traiter par priorite.
- Ne jamais creer d'issue pour du travail interne (refactor pur, mise a jour docs) sauf si l'utilisateur l'a demande.

### Avant chaque push

Lancer `./scripts/validate.sh` ou les commandes equivalentes :

```bash
pytest --cov=src --cov-fail-under=80 -q
python3 -m py_compile src/*.py
PYTHONPATH=src python3 -c "import watchdog; import config"
```

### Procedure bug fix / CVE (main direct)

```bash
# 1. Fix + test
# 2. Commit
git add <files>
git commit -m "fix: description du probleme"
# 3. Tag + push
./scripts/release.sh patch
git push origin main
git push origin v<new_version>
# 4. Sync dev
git checkout dev && git cherry-pick <sha> && git push origin dev && git checkout main
```

### Procedure feature (dev -> PR -> main)

```bash
# 1. Developper sur dev
git checkout dev
# ... commits ...
git push origin dev
# 2. Creer la PR
gh pr create --base main --head dev --title "feat: ..." --label feature
# 3. Apres approbation utilisateur
gh pr merge <number> --merge
# 4. Tag + push
git checkout main && git pull
./scripts/release.sh minor
git push origin main && git push origin v<new_version>
# 5. Sync dev
git checkout dev && git merge main && git push origin dev
```

### Apres hotfix sur main

Toujours cherry-pick sur `dev` pour garder les branches synchronisees.

### Apres merge feature dans main

Toujours fast-forward `dev` sur `main` : `git checkout dev && git merge main && git push origin dev`

### Tags dev (pre-release)

Pour tester une feature sur un Pi avec `UPDATE_CHANNEL=dev` :

```bash
git tag -s "v1.1.0-dev.1" -m "Dev build: description"
git push origin "v1.1.0-dev.1"
```

Les tags dev ne modifient pas le fichier VERSION.

### Messages de commit

Convention : `<type>: <description>`

Types : `feat`, `fix`, `security`, `refactor`, `docs`, `test`, `chore`, `perf`

### Notifications enrichies

Tous les messages de notification passent par `src/messages.py`. Chaque message doit repondre a 3 questions :
1. **Quoi** : qu'est-ce qui s'est passe ?
2. **Pourquoi** : quelle est la cause probable ?
3. **Quoi faire** : quelle action est attendue de l'utilisateur ?

---

**Last Updated:** 2026-03-31
**Python:** 3.11+
**Key Dependencies:** paramiko (SSH), requests (HTTP), stdlib only (threading, queue, dataclass)
