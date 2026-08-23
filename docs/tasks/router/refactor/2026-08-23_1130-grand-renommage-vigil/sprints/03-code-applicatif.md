# Sprint 3 — Code applicatif : chemins, libellés, repli de compatibilité

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil.md` (§ 2.5, § 2.7, § 3, § 4, § 5.1, § 7 S3, § 9 AC)
- **Dépend de** : Sprint 1 (nom de dépôt), Sprint 2 (units/scripts qui consomment les mêmes chemins)
- **Taille estimée** : 75-90 min
- **Isolation** : worktree

## Objectif

Faire pointer `config.py`/`events.py`/`http_server.py`/`updater/*` sur
`/opt/vigil` + `/var/log/vigil*`, **avec un repli** sur l'ancien chemin s'il
est seul présent (invariant de sécurité pendant la migration progressive),
changer le défaut de `MQTT_TOPIC_PREFIX` en `vigil`, et mettre à jour tous les
libellés produit visibles et les User-Agents HTTP. `src/watchdog.py` garde son
nom de fichier et son nom de module (décision Q8) — seuls son docstring et ses
logs de démarrage/arrêt changent de libellé. `src/mqtt_publisher.py` n'est **pas
touché** (identité HA figée depuis 1.8.2, invariant du PRD).

## Étapes concrètes

### 1. Chemins par défaut avec repli de compatibilité (`src/config.py`)

- `:166,169,176` : `/opt/usg-watchdog/.ssh/{name,usg_ed25519,known_hosts}` →
  résolution **avec repli** : si `/opt/vigil` existe, utiliser
  `/opt/vigil/.ssh/…` ; sinon si `/opt/usg-watchdog` existe (et
  `/opt/vigil` n'existe pas), retomber sur l'ancien chemin ; sinon (aucun des
  deux, ex. environnement de dev) utiliser le nouveau chemin par défaut. Le
  nom de fichier de la clé (`usg_ed25519`) ne change **jamais** — seul le
  répertoire parent varie.
- `:433 LOG_FILE` : même logique de repli, `/var/log/vigil.log` par défaut,
  repli sur `/var/log/usg-watchdog.log` si ancien chemin seul présent.
- `:320 MQTT_TOPIC_PREFIX` : défaut `"usg-watchdog"` → `"vigil"` (pas de
  repli ici — c'est une valeur logique, pas un chemin filesystem ; les 4
  instances de production ont un préfixe explicite donc ce changement de
  défaut ne les affecte pas, cf. § 2.7 du PRD et gate
  `env-mqtt-prefix-audit`).
- Factoriser la logique de repli dans une fonction unique (ex.
  `_resolve_install_path(new_default, old_default)`) réutilisée par les 3
  points d'usage (`.ssh`, `LOG_FILE`, et le chemin `.env` de
  `http_server.py`) — éviter trois implémentations divergentes du même
  repli.

### 2. `src/events.py`

- `:46` : `/var/log/usg-watchdog-events.json` → `/var/log/vigil-events.json`,
  même logique de repli que `LOG_FILE`.

### 3. `src/http_server.py`

- `:397` : `env_path = "/opt/usg-watchdog/.env"` → repli identique
  (`/opt/vigil/.env` par défaut, repli sur `/opt/usg-watchdog/.env`).

### 4. `updater/update.py` et `updater/preflight.py`

- `:34` : déjà fait au sprint 1 (`GITHUB_REPO`).
- `:36 INSTALL_DIR` → `/opt/vigil` (pas de repli ici : l'updater tourne
  **depuis** l'installation existante, il n'a pas besoin de deviner entre deux
  racines — c'est `deploy.sh`, sprint 2, qui gère la bascule initiale).
- `:37 SERVICE_NAME` → `vigil`.
- `:422` : libellé produit dans les logs/messages de l'updater.
- `updater/preflight.py:2` : libellé produit.

### 5. Libellés visibles par l'utilisateur (cosmétique mais nom du produit)

- `src/dashboard.py:9,160` : `<title>` + `<h1>` → « Vigil ».
- `src/pwa.py:4-6` : `name`, `short_name`, `description` → « Vigil ».
- `src/report.py:85,241` : titres de rapport.
- `src/telegram_bot.py:66` : libellé produit dans les réponses du bot.
- `src/watchdog.py:3,272,961` : docstring + logs de démarrage/arrêt
  (« Vigil démarre » / « Vigil s'arrête », en français comme le reste des
  logs du projet) — **le nom du fichier et du module ne changent pas**.
- `src/notifier/__init__.py:2` : docstring.
- `src/notifier/_telegram.py`, `_discord.py`, `_slack.py`, `_ntfy.py`,
  `_pushover.py` : titre « USG Watchdog » des notifications → « Vigil ».
- `src/notifier/_email.py:30,40` : sujet + `From` fallback
  `usg-watchdog@host` → `vigil@host`.
- `src/notifier/_dispatch.py:30` : fallback de nom.

### 6. User-Agents HTTP (préfixe `vigil-*`, impact tiers nul mais cohérence)

- `src/speedtest.py:45` : `usg-watchdog-speedtest` → `vigil-speedtest`.
- `src/ddns_cloudflare.py:79` : `usg-watchdog-ddns` → `vigil-ddns`.
- `src/isp_status.py:44` : `usg-watchdog/1.0` → `vigil/1.0`.
- `updater/update.py:104,142` : `usg-watchdog-updater` → `vigil-updater`.

### 7. Tests à adapter

- `tests/test_usg.py` : chemins `/opt/…/.ssh/usg_ed25519` — **seul le
  préfixe `/opt` change** (`/opt/vigil/...` au lieu de
  `/opt/usg-watchdog/...`), le nom du fichier de clé reste `usg_ed25519`.
- `tests/test_dashboard.py`, `tests/test_pwa.py`, `tests/test_report.py` :
  assertions sur les libellés « Vigil ».
- `tests/test_pushover_notifier.py` : le test `test_title_is_usg_watchdog`
  est renommé `test_title_is_vigil` et son assertion mise à jour.
- `tests/test_watchdog.py` : assertions sur les logs de démarrage/arrêt.
- `tests/test_http_server.py` : 7 occurrences dont les assertions sur le
  chemin `.env` — adapter au nouveau défaut + repli.
- **Nouveau fichier `tests/test_path_fallback.py`** : test dédié du repli de
  compatibilité — au moins deux cas : (a) `/opt/vigil` présent → chemins
  neufs utilisés, ancien chemin ignoré même s'il existe aussi ; (b)
  `/opt/vigil` absent, `/opt/usg-watchdog` présent → repli sur l'ancien
  chemin pour `.ssh`, `LOG_FILE`, fichier d'événements et `.env`. Utiliser
  `tmp_path`/monkeypatch pour simuler la présence/absence des répertoires,
  ne jamais dépendre du filesystem réel de la machine de test.

### 8. Ne pas toucher

- `src/mqtt_publisher.py`, `tests/test_mqtt_publisher.py` : diff vide
  (invariant du PRD, déjà en `vigil_*` depuis 1.8.2).
- `src/messages.py` : les messages qui parlent du routeur USG restent
  inchangés (frontière § 3 du PRD).
- `src/usg.py` : inchangé.
- `src/metrics.py`, `tests/test_metrics.py` : sprint 4.

## Fichiers

- **files_to_create** : `tests/test_path_fallback.py`
- **files_to_modify** : `src/config.py`, `src/events.py`,
  `src/http_server.py`, `src/dashboard.py`, `src/pwa.py`, `src/report.py`,
  `src/telegram_bot.py`, `src/watchdog.py`, `src/notifier/__init__.py`,
  `src/notifier/_telegram.py`, `src/notifier/_discord.py`,
  `src/notifier/_slack.py`, `src/notifier/_ntfy.py`,
  `src/notifier/_pushover.py`, `src/notifier/_email.py`,
  `src/notifier/_dispatch.py`, `src/speedtest.py`, `src/ddns_cloudflare.py`,
  `src/isp_status.py`, `updater/update.py`, `updater/preflight.py`,
  `tests/test_usg.py`, `tests/test_dashboard.py`, `tests/test_pwa.py`,
  `tests/test_report.py`, `tests/test_pushover_notifier.py`,
  `tests/test_watchdog.py`, `tests/test_http_server.py`
- **files_read_only** : `src/usg.py`, `src/mqtt_publisher.py`,
  `tests/test_mqtt_publisher.py`, `src/messages.py`
- **forbidden** : `src/mqtt_publisher.py`, `tests/test_mqtt_publisher.py`
  (identité HA figée), `src/metrics.py`, `tests/test_metrics.py` (sprint 4)

## Critères d'acceptation

- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] `tests/test_path_fallback.py` couvre les deux cas (nouveau chemin
      présent, ancien chemin seul présent) et passe
- [ ] `grep -rIn -e 'usg-watchdog' -e 'usg_watchdog' -e 'USG Watchdog' src/
      updater/` ne renvoie que les valeurs de repli explicites (chaînes
      littérales `/opt/usg-watchdog`, `/var/log/usg-watchdog.log`,
      `/var/log/usg-watchdog-events.json` utilisées comme second argument de
      la résolution de repli) — aucun résidu de libellé produit ni de
      User-Agent
- [ ] `MQTT_TOPIC_PREFIX` défaut = `"vigil"` ; `git diff --stat -- src/mqtt_publisher.py tests/test_mqtt_publisher.py` vide
- [ ] Diff des clés `os.getenv`/`_get_env` de `src/config.py` avant/après :
      identique, hors ajouts (aucune suppression, aucun renommage)
- [ ] `src/watchdog.py` : nom de fichier inchangé ; seuls docstring et logs
      de démarrage/arrêt modifiés (`git diff` limité à ces lignes)
- [ ] `tests/test_usg.py` : seul le préfixe `/opt` change dans les chemins
      testés, `usg_ed25519` reste le nom de fichier de clé partout
- [ ] `tests/test_pushover_notifier.py::test_title_is_vigil` passe (renommé
      depuis `test_title_is_usg_watchdog`)
