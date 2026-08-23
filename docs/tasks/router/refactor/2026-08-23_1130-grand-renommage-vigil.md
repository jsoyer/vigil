# Refactor — Grand renommage « USG Watchdog » → **Vigil** (2.0.0)

- **Catégorie** : refactor
- **Date** : 2026-08-23
- **Version cible** : **2.0.0** (major — voir § Versionnement)
- **Branche** : `dev` → PR → `main` (routing projet : breaking = PR obligatoire)
- **Dépend de** : 1.8.2 (layout `releases/` + `current`, identité MQTT `vigil`
  déjà livrée sur les 4 Pi) et, fortement recommandé, 1.8.3
  (`docs/tasks/router/infrastructure/2026-08-23_1100-release-updater-debts.md` :
  `release.sh` utilisable + `pip install` dans l'updater)
- **Statut** : **Décisions tranchées (2026-08-23) — voir § 0bis. Sprints
  extraits dans `2026-08-23_1130-grand-renommage-vigil/`. Exécution immédiate.**

---

## 0bis. Décisions (2026-08-23)

Réponses utilisateur aux questions ouvertes du § 10, tranchées le jour même de
la rédaction du PRD. Elles priment sur les recommandations formulées plus haut
dans le document là où elles diffèrent ; le corps du PRD n'est pas réécrit,
seule la section métriques (§ 2.6) reçoit un encart daté (bascule sèche).

| # | Question | Décision | Écart vs recommandation § 10 |
|---|---|---|---|
| **Q1** | Utilisateur système | **Oui**, renommé `usg-watchdog` → `vigil`. Nouvel utilisateur **créé** par `deploy.sh` (jamais `usermod -l`). Ancien utilisateur supprimé **en fin de migration** (J+7, après vérification `find -xdev -user usg-watchdog`) | Conforme à la reco |
| **Q2** | Métriques Prometheus | **Bascule sèche** : `vigil_*` seul dès la 2.0.0, **pas de double émission**. Rupture d'historique Prometheus assumée. Aucune règle d'alerte Prometheus/Alertmanager hors dépôt à inventorier (confirmé : aucune n'existe) | **Écart** : le PRD recommandait la double émission (§ 2.6, § Q2). L'utilisateur tranche pour la simplicité — voir encart § 2.6 |
| **Q3** | Nom du dépôt | `jsoyer/vigil` confirmé | Conforme à la reco |
| **Q4** | Chemin d'installation | `/opt/vigil` confirmé | Conforme à la reco |
| **Q5** | Alias systemd de l'ancien nom | **Non** — pas d'`Alias=usg-watchdog.service` | Conforme à la reco |
| **Q6** | Créneau | **Immédiat** : exécution dès que les specs de sprint sont prêtes, flotte migrée dans la même fenêtre (pas d'état mixte > 24 h) | Reco suivie (« ne pas laisser la flotte en état mixte ») |
| **Q7** | 1.8.3 avant migration | 1.8.3 déjà livrée (`release.sh` idempotent + `pip install` de l'updater) — prérequis satisfait | Conforme à la reco |
| **Q8** | Renommer `src/watchdog.py` | **Non** — le module garde son nom (chien de garde, pas l'ancien nom produit) | Conforme à la reco |

**Conséquence directe sur le découpage des sprints (§ 7)** : le Sprint 4
(métriques) est **simplifié** — renommage direct des 19 séries `usg_watchdog_*`
→ `vigil_*` et du dashboard Grafana, sans code de double émission ni logique de
dépréciation. Voir l'encart daté en § 2.6 et le détail dans
`2026-08-23_1130-grand-renommage-vigil/sprints/04-metriques-prometheus-grafana.md`.

---

## 1. Contexte et décision

Le logiciel change de nom : **USG Watchdog** devient **Vigil** (décision
utilisateur du 2026-08-23). Le matériel surveillé, lui, reste un USG Ubiquiti
(et bientôt des TP-Link 4G, cf. ADR-0001) : **le renommage concerne le produit,
pas la cible**.

Une partie du travail est déjà faite : la **1.8.2 a posé l'identité MQTT /
Home Assistant définitive** (`device.name` = « Vigil {instance} », `unique_id`
`vigil_*`, `client_id` `vigil-{instance}`, topics de discovery
`homeassistant/sensor/vigil_{instance}/…`), et les 4 `.env` de production
portent déjà des `MQTT_TOPIC_PREFIX` explicites `vigil/<site>-<role>`. Les
`unique_id` HA étant immuables, cette partie **ne doit plus être touchée** : la
purge des entités orphelines a déjà été payée une fois.

Reste ce qui n'a pas pu passer dans un patch : le **nom du dépôt**, le **nom du
service systemd**, l'**arborescence `/opt`**, les **logs**, l'**utilisateur
système**, les **métriques Prometheus**, le **défaut** de `MQTT_TOPIC_PREFIX`
et toute la **documentation vivante**.

### État de la flotte (point de départ)

| Pi | Rôle | `INSTANCE_ID` | Login SSH | Version |
|---|---|---|---|---|
| bbh-network (local) | dijon-master | `bbh_network` | — (local) | 1.8.2 |
| bbh-dij-guardian | dijon-slave | `bbh_dij_guardian` | `dietpi` | 1.8.2 |
| penelope | nice-master | `penelope` | `pi` | 1.8.2 |
| bbh-nce-guardian | nice-slave | `bbh_nce_guardian` | `dietpi` | 1.8.2 |

Commun aux 4 : `/opt/usg-watchdog/{releases/vX.Y.Z, current -> releases/vX.Y.Z,
venv, .env, .ssh, updater}`, service `usg-watchdog.service`, timer
`usg-watchdog-updater.timer` (03:00 ± 10 min) qui interroge
`https://api.github.com/repos/jsoyer/usg-watchdog/tags`, log
`/var/log/usg-watchdog.log` + logrotate, utilisateur système `usg-watchdog`,
clone git dans `~/github/usg-watchdog`. Accès flotte : clé
`~/.ssh/id_ed25519_fleet` + entrées `~/.ssh/config`, sudo NOPASSWD partout.

---

## 2. Périmètre exact du renommage (inventaire)

Mesure de départ : **431 occurrences** de `usg-watchdog` / `usg_watchdog` /
`USG Watchdog` dans **68 fichiers** (hors `.git`, `venv`, caches).

### 2.1 Dépôt GitHub et clones

| Élément | Avant | Après |
|---|---|---|
| Dépôt | `jsoyer/usg-watchdog` | `jsoyer/vigil` |
| `updater/update.py:34` | `UPDATER_GITHUB_REPO` défaut `jsoyer/usg-watchdog` | `jsoyer/vigil` |
| URLs docs | `github.com/jsoyer/usg-watchdog{,/issues}` (`README.md:72,1315`, `WORKFLOW.md:17`) | idem `vigil` |
| Clones sur les 4 Pi | `~/github/usg-watchdog` (remote `origin`) | `~/github/vigil` + `git remote set-url` |

**Point clé de sûreté** : GitHub met en place une **redirection permanente** de
l'ancien `owner/name` vers le nouveau, y compris pour l'API REST et les
tarballs. `urllib.request` (utilisé par `update.py:99,138`) suit les 301/302 par
défaut → **un updater non migré continue de trouver les releases**. C'est le
filet qui rend la migration progressive possible ; il doit être **prouvé par un
test réel** (sprint 1), pas supposé.

### 2.2 Unités systemd (renommage de fichiers + contenu)

| Fichier actuel | Fichier cible | Contenu à changer |
|---|---|---|
| `systemd/usg-watchdog.service` | `systemd/vigil.service` | `Description`, `User`/`Group` (→ `vigil`, cf. Q1), `WorkingDirectory=/opt/vigil/current/src`, `ExecStart=/opt/vigil/venv/bin/python /opt/vigil/current/src/watchdog.py`, `EnvironmentFile=-/opt/vigil/.env`, `SyslogIdentifier=vigil`, `ReadOnlyPaths=/opt/vigil`, `ReadWritePaths=/var/log/vigil.log` |
| `systemd/usg-watchdog-updater.service` | `systemd/vigil-updater.service` | `Description`, `After=… vigil.service`, `WorkingDirectory`, `ExecStart`, `EnvironmentFile`, `SyslogIdentifier=vigil-updater` |
| `systemd/usg-watchdog-updater.timer` | `systemd/vigil-updater.timer` | `Description` |
| `systemd/usg-watchdog.logrotate` | `systemd/vigil.logrotate` | chemin `/var/log/vigil.log`, `create 0640 vigil adm`, `systemctl kill -s HUP vigil.service` |

**Bug latent à corriger au passage** (découvert pendant l'inventaire) :
`events.py:46` persiste dans `/var/log/usg-watchdog-events.json`, mais le unit
n'autorise en écriture que `/var/log/usg-watchdog.log` sous
`ProtectSystem=strict` → la persistance des événements échoue probablement en
silence depuis toujours. Le renommage touche ce chemin de toute façon :
ajouter `/var/log/vigil-events.json` aux `ReadWritePaths` et vérifier que le
fichier est bien écrit après un redémarrage (petit fix clair et dans le
périmètre — cf. règle « erreur trouvée = corrigée si simple »).

### 2.3 Système de fichiers et utilisateur

| Élément | Avant | Après |
|---|---|---|
| Racine d'installation | `/opt/usg-watchdog` | `/opt/vigil` |
| Log principal | `/var/log/usg-watchdog.log` | `/var/log/vigil.log` |
| Log événements | `/var/log/usg-watchdog-events.json` | `/var/log/vigil-events.json` |
| Logrotate installé | `/etc/logrotate.d/usg-watchdog` | `/etc/logrotate.d/vigil` |
| Utilisateur/groupe système | `usg-watchdog` | `vigil` (**cf. Q1**) |
| Units installées | `/etc/systemd/system/usg-watchdog{,-updater}.{service,timer}` | `vigil{,-updater}.{service,timer}` |
| Clé SSH vers le routeur | `/opt/usg-watchdog/.ssh/usg_ed25519` | `/opt/vigil/.ssh/usg_ed25519` (**nom du fichier inchangé** : il désigne le USG) |

### 2.4 Scripts (7 fichiers)

| Fichier | Points touchés |
|---|---|
| `scripts/deploy.sh` | `:10 INSTALL_DIR`, `:11 SERVICE_NAME`, `:12 SERVICE_USER`, `:173-178` (log), `:182` (logrotate), `:188-196` (noms des units), `:206-207` (timer), `:233-235` (messages) |
| `scripts/uninstall.sh` | `:8-10` (service/user/dir), `:71-73` (logs) — plus : **doit savoir désinstaller l'ancien nom** |
| `scripts/setup_ssh.sh` | `:15 SSH_DIR`, `:18 KEY_COMMENT`, `:52` (bannière) |
| `scripts/test.sh` | `:10 INSTALL_DIR`, `:28 ENV_FILE`, `:44`, `:102` (bannières/messages) |
| `scripts/validate.sh` | `:22` (bannière) — `:62 import usg` **reste** |
| `scripts/release.sh` | `:3` (commentaire) |
| `scripts/lib/logging.sh` | `:3` (commentaire) |

### 2.5 Code source (`src/`, 20 fichiers) et `updater/` (2 fichiers)

**Chemins par défaut** (les seuls à impact opérationnel réel) :

| Emplacement | Avant | Après |
|---|---|---|
| `src/config.py:166,169,176` | `/opt/usg-watchdog/.ssh/{name,usg_ed25519,known_hosts}` | `/opt/vigil/.ssh/…` |
| `src/config.py:433` | `LOG_FILE=/var/log/usg-watchdog.log` | `/var/log/vigil.log` |
| `src/config.py:320` | `MQTT_TOPIC_PREFIX=usg-watchdog` | `vigil` (cf. § 2.7) |
| `src/events.py:46` | `/var/log/usg-watchdog-events.json` | `/var/log/vigil-events.json` |
| `src/http_server.py:397` | `env_path = "/opt/usg-watchdog/.env"` | `/opt/vigil/.env` |
| `updater/update.py:34,36,37` | `GITHUB_REPO`, `INSTALL_DIR`, `SERVICE_NAME` | `jsoyer/vigil`, `/opt/vigil`, `vigil` |

**Libellés visibles par l'utilisateur** (cosmétique, mais c'est le nom du
produit) : `src/dashboard.py:9,160` (`<title>` + `<h1>`), `src/pwa.py:4-6`
(`name`, `short_name`, `description`), `src/report.py:85,241` (titres de
rapport), `src/telegram_bot.py:66`, `src/watchdog.py:3,272,961` (docstring +
logs de démarrage/arrêt), `src/notifier/__init__.py:2`,
`src/notifier/_{telegram,discord,slack,ntfy,pushover}.py` (titre
« USG Watchdog » des notifications), `src/notifier/_email.py:30,40` (sujet +
`From` fallback `usg-watchdog@host` → `vigil@host`),
`src/notifier/_dispatch.py:30` (fallback de nom), `updater/update.py:422`,
`updater/preflight.py:2`.

**User-Agents HTTP** : `src/speedtest.py:45` (`usg-watchdog-speedtest`),
`src/ddns_cloudflare.py:79` (`usg-watchdog-ddns`), `src/isp_status.py:44`
(`usg-watchdog/1.0`), `updater/update.py:104,142` (`usg-watchdog-updater`) →
préfixe `vigil-*`. Aucun tiers ne filtre sur ces valeurs (Cloudflare, CDN,
statuts opérateurs) : impact nul, mais à changer par cohérence.

### 2.6 Métriques Prometheus et Grafana

`src/metrics.py` expose **19 séries préfixées `usg_watchdog_`** (`_up`,
`_uptime_seconds`, `_failure_score`, `_score_threshold`, `_gateway_up`,
`_internet_targets_{up,total}`, `_gateway_rtt_ms`, `_internet_avg_rtt_ms`,
`_latency_degraded`, `_reboots_total`, `_reboots_today`, `_surveillance_mode`,
`_isp_outage`, `_ssh_failures`, `_peer_{up,score}`, `_instance_priority`).
`grafana/dashboard.json` en référence 8, et `tests/test_metrics.py` contient 34
occurrences.

C'est le seul poste où le renommage **détruit de la donnée historique** :
changer le nom d'une série coupe la continuité dans Prometheus (l'ancienne
série s'arrête, la nouvelle démarre à zéro) et casse toute alerte/dashboard
écrit contre l'ancien nom. **Recommandation : double émission transitoire** —
`vigil_*` (canonique) + `usg_watchdog_*` (déprécié, marqué en commentaire
`# DEPRECATED — retrait en 2.1.0`) pendant une version mineure, le temps de
migrer dashboards et alertes. Coût : ~20 lignes et un test. Cf. **Q2**.

> **Encart 2026-08-23 — décision Q2 : bascule sèche.** L'utilisateur tranche
> pour la **bascule sèche** plutôt que la double émission recommandée
> ci-dessus : `vigil_*` seul dès la 2.0.0, aucune série `usg_watchdog_*`
> conservée. Confirmé : aucune règle d'alerte Prometheus/Alertmanager hors
> dépôt ne dépend des séries actuelles — la question complémentaire du § Q2
> est donc close sans inventaire. Conséquence : le Sprint 4 se réduit à un
> **renommage direct** des 19 séries dans `src/metrics.py` et
> `grafana/dashboard.json` (retrait du préfixe `usg_watchdog_`, pose du
> préfixe `vigil_`), sans logique de double émission, sans commentaire
> `DEPRECATED`, sans échéance 2.1.0 à tenir. Le risque n°3 du § 8 (« perte de
> continuité Prometheus / alertes muettes ») est **assumé**, pas mitigé : la
> rupture d'historique et le silence d'alerte le temps de migrer un dashboard
> externe sont le prix accepté de la simplicité. À documenter explicitement
> dans `docs/RELEASE-NOTES-2.0.0.md`.

### 2.7 `MQTT_TOPIC_PREFIX`

Défaut `usg-watchdog` → `vigil` (`src/config.py:320`). **Impact production
nul** : les 4 instances ont un prefix explicite `vigil/<site>-<role>` dans leur
`.env`. Le risque ne concerne qu'un éventuel déploiement tiers qui aurait laissé
le défaut : ses topics d'état changeraient de racine et ses entités HA
tomberaient en `unavailable` jusqu'à la prochaine discovery. À signaler dans les
notes de version comme **breaking** (une des justifications du major).
Vérification préalable obligatoire : `grep MQTT_TOPIC_PREFIX /opt/*/.env` sur
les 4 Pi avant migration.

### 2.8 Documentation

**Vivante — à renommer** (6 fichiers) : `README.md` (54 occurrences, titre
`# USG Watchdog v1.7.0` à réaligner sur 2.0.0), `DEPLOY.md` (45), `WORKFLOW.md`
(7), `CLAUDE.md` (18, y compris l'arbre des fichiers et les procédures),
`.github/ISSUE_TEMPLATE/bug_report.md` (2), `grafana/dashboard.json` (12).
Ajouter dans README/DEPLOY un encadré « Anciennement USG Watchdog — procédure de
migration 1.8.x → 2.0.0 ».

**Historique — à NE PAS réécrire** (20 fichiers) : `docs/adr/0001-*.md`,
`docs/RELEASE-NOTES-1.8.{1,2}.md`, `docs/tasks/**`. Ces documents décrivent
l'état du système à une date donnée ; les réécrire falsifie la trace. Seul
`docs/session-learnings.md` reçoit une ligne d'entête indiquant le renommage.

### 2.9 Tests (9 fichiers)

`tests/test_metrics.py` (34), `tests/test_http_server.py` (7, dont les
assertions `usg_watchdog_up` et le chemin `.env`), `tests/test_dashboard.py`,
`tests/test_pwa.py`, `tests/test_report.py`, `tests/test_pushover_notifier.py`
(nom de test `test_title_is_usg_watchdog`), `tests/test_watchdog.py` (logs de
démarrage/arrêt), `tests/test_usg.py` (chemins `/opt/…/.ssh/usg_ed25519` —
**seul le préfixe `/opt` change**), `tests/test_mqtt_publisher.py` (déjà en
`vigil_*`, **ne pas toucher**).

---

## 3. Frontière : ce qui reste « USG »

Règle : **tout ce qui désigne le routeur Ubiquiti reste `usg`. Tout ce qui
désigne le logiciel devient `vigil`.**

Restent inchangés, volontairement :

- `src/usg.py`, `tests/test_usg.py`, `reboot_usg()`, `test_ssh_connection()` —
  c'est le pilote du USG. (L'ADR-0001 prévoit à terme un
  `src/drivers/ubiquiti.py` ; ce PRD ne préempte pas ce découpage.)
- Variables d'environnement `USG_IP`, `USG_USER`, `USG_SSH_KEY`,
  `USG_SSH_PASSWORD`, `USG_KNOWN_HOSTS`, `USG_REBOOT_COMMAND`,
  `USG_REBOOT_WAIT` — renommer casserait les 4 `.env` de production pour un
  gain nul, et elles désignent bien la cible.
- Les messages parlant du routeur : `src/messages.py:48,85,163,213,219,293`
  (« Gateway USG », « redémarrage du routeur USG (…) »).
- Le nom de fichier de la clé SSH `usg_ed25519` et son `known_hosts`.
- `UNIFI_BACKUP_DIR`, `UNIFI_BACKUP_RCLONE_DEST` (produit Ubiquiti).
- La `Description` du unit reste explicite sur la cible :
  `Description=Vigil -- surveillance de connexion et reboot automatique du routeur USG Ubiquiti`.

### Cas limites tranchés

| Élément | Décision | Raison |
|---|---|---|
| `src/watchdog.py` (nom de module + `ExecStart`) | **reste** | Le module s'appelle `watchdog` parce que c'est un chien de garde, pas à cause de l'ancien nom produit. Le renommer coûte imports, tests, unit, mémoire musculaire, pour zéro bénéfice. |
| `usg_watchdog_*` (métriques) | **devient `vigil_*`** (double émission) | Le préfixe nomme le logiciel exportateur. |
| `usg-watchdog@$(hostname)` (commentaire de clé SSH) | **devient `vigil@…`** | Identifie la machine émettrice, pas la cible. |
| `NTFY_TOPIC=usg-watchdog` (exemples doc, `README.md:446`) | exemple → `vigil` | Valeur d'exemple seulement ; en prod le topic est configuré. |
| `.env` de production | **aucune variable renommée** | Un renommage de clé `.env` = 4 interventions manuelles supplémentaires et un risque de silence (valeur ignorée). |

---

## 4. Ce qui ne doit PAS changer (invariants du renommage)

1. **Identité MQTT / Home Assistant** : `device.identifiers` `vigil_{instance}`,
   `device.name` « Vigil {instance} », `unique_id` `vigil_{instance}_{sensor}`,
   `client_id` `vigil-{instance}`, topics de discovery
   `homeassistant/sensor/vigil_{instance}/…`. **Déjà corrects depuis la 1.8.2.**
   Toute retouche = seconde purge d'entités orphelines et perte d'historique HA.
2. **Contrat HTTP** : `HTTP_PORT`, `/health`, `/api/*`, `/metrics`,
   `/manifest.json`, `/sw.js`, `/dashboard`. Le peering HA
   (`peer.py` → `GET /api/state`), l'updater (health check) et Prometheus en
   dépendent. Aucun chemin, aucun champ retiré ni renommé.
3. **Coordination de flotte** : `PEER_IP`, `PEER_PORT`, `INSTANCE_ID`,
   `INSTANCE_PRIORITY` inchangés ; les 4 `INSTANCE_ID` de production restent
   `bbh_network`, `bbh_dij_guardian`, `penelope`, `bbh_nce_guardian`.
4. **Toutes les variables d'environnement existantes** (aucune suppression,
   aucun renommage) — les `.env` de production doivent rester valides tels quels
   après migration, à l'exception des chemins qu'on y **ajoutera** volontairement
   (cf. § 5.1).
5. **Historique git** : aucun `filter-branch`, aucun réécriture, les tags
   `v1.x.y` restent tels quels et continuent de pointer sur du code
   « USG Watchdog ».
6. **La logique métier** : scoring, circuit breaker, ISP detection, escalade,
   DDNS, backup. Ce PRD est un renommage — **zéro changement de comportement**
   en dehors des chemins et des noms. Toute tentation de « pendant qu'on y
   est » est hors périmètre (sauf le `ReadWritePaths` du § 2.2, qui est un bug
   sur un chemin que l'on renomme de toute façon).

---

## 5. Stratégie de migration de la flotte

Objectif : **aucune fenêtre sans surveillance sur un site**, et un rollback
possible à chaque étape.

### 5.1 Principes

- **Copier, pas déplacer.** `/opt/usg-watchdog` reste en place et bootable
  jusqu'à la validation finale (J+7). Le rollback est alors
  `systemctl disable --now vigil && systemctl enable --now usg-watchdog`.
- **Le venv n'est pas relogeable.** `cp -a`/`mv` d'un virtualenv laisse des
  shebangs et un `pyvenv.cfg` pointant sur `/opt/usg-watchdog/venv` → paramiko
  ou paho-mqtt peuvent casser en silence. Le venv de `/opt/vigil` est
  **recréé** par `deploy.sh` (`python3 -m venv` + `pip install -r
  requirements.txt`, qui contient désormais `paho-mqtt==1.6.1`). Vérification
  obligatoire après démarrage : ligne « MQTT connecte (rc=0) » dans le journal.
- **`.env` et `.ssh` sont copiés avant `deploy.sh`** (sinon `deploy.sh` bascule
  en mode interactif et régénère une clé).
- **Épingler les chemins dans `.env` avant toute bascule** : ajouter
  explicitement `LOG_FILE=`, `USG_SSH_KEY=`, `USG_KNOWN_HOSTS=` avec les
  valeurs **courantes**. Coût : 3 lignes. Bénéfice : le code 2.0.0 ne peut plus
  se tromper de chemin si l'ordre des opérations dérape, et l'on découple le
  changement de défauts du changement d'arborescence.
- **Geler l'updater pendant la fenêtre** : `systemctl disable --now
  usg-watchdog-updater.timer` sur les 4 Pi **avant** de commencer, réactivé
  sous son nouveau nom une fois l'instance validée.
- **Tag en dernier.** La migration se fait depuis le clone git (branche
  `main` fraîchement mergée, `VERSION`=2.0.0), le tag `v2.0.0` n'est poussé
  qu'**après** les 4 Pi migrés. Tant qu'il n'existe pas, aucun updater ne peut
  tirer la 2.0.0.
- **Filet de sécurité dans le code** : résolution de chemin avec repli — si
  `/opt/vigil` n'existe pas et que `/opt/usg-watchdog` existe, les défauts
  retombent sur l'ancien chemin (log, `.ssh`, `.env`, events). Ainsi, même si
  une 2.0.0 atterrissait par accident sur une installation non migrée, le
  service démarre au lieu de tomber en boucle de redémarrage. Repli à retirer
  en 2.1.0.

### 5.2 Ordre des Pi

Jamais les deux membres d'une paire HA en même temps ; on commence par les
secondaires, dont l'indisponibilité est couverte par le primaire :

1. **bbh-dij-guardian** (dijon-slave) — cobaye ; dijon-master surveille.
2. **bbh-nce-guardian** (nice-slave) — confirme la reproductibilité (DietPi).
3. **bbh-network** (dijon-master, local) — le slave Dijon est déjà en 2.0.0 et
   peut prendre le relais.
4. **penelope** (nice-master, user `pi`) — dernier, environnement différent.

Attendre **au moins 30 min de fonctionnement sain** entre deux Pi d'un même
site (un cycle de rapport + une remontée MQTT).

### 5.3 Procédure par Pi (runbook, ~10 min, arrêt de service ~2 min)

```
0. Constat initial : systemctl is-active usg-watchdog ; curl -s :PORT/health
   (version 1.8.2) ; sauvegarde : tar czf ~/vigil-migration-$(hostname).tgz \
   /opt/usg-watchdog/.env /opt/usg-watchdog/.ssh
1. Gel : systemctl disable --now usg-watchdog-updater.timer
2. .env : ajouter LOG_FILE / USG_SSH_KEY / USG_KNOWN_HOSTS explicites (anciens chemins)
3. Clone : git -C ~/github/usg-watchdog remote set-url origin <nouvelle URL>
   ; git -C ~/github/usg-watchdog pull ; puis mv du répertoire en ~/github/vigil
   (attention : ne jamais préfixer une commande SSH par `cd` — le hook rtk peut
   le perdre ; utiliser git -C ou des chemins absolus)
4. Pré-remplissage : mkdir -p /opt/vigil && cp -a /opt/usg-watchdog/.env
   /opt/usg-watchdog/.ssh /opt/vigil/   (PAS le venv, PAS releases/)
5. Déploiement : sudo ~/github/vigil/scripts/deploy.sh
   → crée l'utilisateur vigil, le venv, releases/v2.0.0 + current, le log,
     le logrotate, les units vigil{,-updater}, enable + start
6. Bascule : systemctl disable --now usg-watchdog   (unit conservée, non supprimée)
7. Vérification (toutes obligatoires avant de passer au Pi suivant) :
   - curl -s :PORT/health → status healthy/degraded ET version 2.0.0
   - journalctl -u vigil -n 50 : « Vigil demarre », « MQTT connecte (rc=0) »,
     « discovery envoye », aucune trace de /opt/usg-watchdog
   - ls -l /var/log/vigil.log /var/log/vigil-events.json (créés, non vides)
   - curl -s :PORT/metrics | grep -c '^vigil_' (>0) ; grep -c '^usg_watchdog_'
     doit valoir 0 (bascule sèche, décision 2026-08-23 Q2 — pas de double
     émission)
   - dashboard HTTP accessible, entités HA du device « Vigil {instance} »
     toujours vertes (les unique_id n'ont pas bougé)
   - depuis le peer : curl :PEER/api/state → l'instance migrée est vue
8. Dégel : systemctl enable --now vigil-updater.timer
```

**Rollback (à chaque étape)** :

| Étape atteinte | Rollback |
|---|---|
| 1-4 | Rien à défaire (rien n'a été arrêté), `rm -rf /opt/vigil` |
| 5 (vigil démarré, ancien encore actif) | `systemctl disable --now vigil` — l'ancien service n'a jamais été arrêté |
| 6-7 (bascule faite, vérif KO) | `systemctl disable --now vigil && systemctl enable --now usg-watchdog` puis `curl /health` = 1.8.2 |
| 8 (dégel) | idem 6-7 + `systemctl disable --now vigil-updater.timer` |
| J+7 (après purge) | Réinstallation depuis le tag `v1.8.2` + restauration du tar de l'étape 0 |

### 5.4 Après migration (J+7, opération séparée et explicitement demandée)

- `rm -rf /opt/usg-watchdog` (après une dernière archive), suppression des units
  `usg-watchdog*` de `/etc/systemd/system`, de `/etc/logrotate.d/usg-watchdog`,
  archivage puis suppression de `/var/log/usg-watchdog.log*`.
- `userdel usg-watchdog` **en dernier**, après avoir vérifié qu'aucun fichier
  ne lui appartient encore (`find / -xdev -user usg-watchdog`) — sinon on crée
  des UID orphelins.
- Retrait des métriques dépréciées : **pas ici**, en 2.1.0, une fois les
  dashboards et alertes migrés.

---

## 6. Versionnement — recommandation : **2.0.0 (major)**

Justification :

1. **Contrat d'exploitation cassé** : le nom du service, le chemin
   d'installation, le chemin des logs, le nom des métriques et le défaut de
   `MQTT_TOPIC_PREFIX` changent. Tout script, alerte, dashboard, playbook ou
   habitude externe qui s'appuie sur `systemctl … usg-watchdog`,
   `/var/log/usg-watchdog.log` ou `usg_watchdog_*` casse. C'est la définition
   d'un breaking change, même si aucune API Python ne bouge.
2. **La mise à jour ne peut pas être automatique** : comme la 1.8.2, elle exige
   une intervention manuelle par hôte. Un numéro majeur est le seul signal assez
   fort pour que « ne pas laisser l'updater faire » soit évident.
3. **Lisibilité de l'histoire** : v1.x = USG Watchdog, v2.x = Vigil. La
   frontière de version documente le renommage à elle seule.
4. Contre-argument honnête : sémantiquement, un renommage n'ajoute aucune
   fonctionnalité, et `2.0.0` peut donner l'impression d'une refonte. Il est
   levé par des notes de version explicites (« 2.0.0 = renommage, zéro
   changement de comportement »).

Conséquence opérationnelle : `parse_version("2.0.0") > parse_version("1.8.2")`
→ les updaters non migrés **tireront** la 2.0.0 dès que le tag existe. D'où la
règle « tag en dernier » + gel des timers + repli de chemins (§ 5.1).

---

## 7. Découpage en sprints (5 — spécifications à extraire après validation)

> Les fichiers `sprints/NN-*.md`, `progress.json` et `INVARIANTS.md` **ne sont
> pas créés par ce PRD**. Ils seront extraits après validation utilisateur.

| # | Titre | Objectif (1 ligne) | Vérification |
|---|---|---|---|
| **S1** | Dépôt, redirection et documentation vivante | Renommer `jsoyer/usg-watchdog` → `jsoyer/vigil`, prouver la redirection API/tarball, mettre à jour README/DEPLOY/WORKFLOW/CLAUDE.md/templates + `UPDATER_GITHUB_REPO` par défaut, sans toucher aux docs historiques | `curl -sIL https://api.github.com/repos/jsoyer/usg-watchdog/tags` renvoie 200 après redirection ; téléchargement d'un tarball par l'ancien nom réussi ; `grep -rn 'usg-watchdog' README.md DEPLOY.md WORKFLOW.md CLAUDE.md` ne renvoie que des mentions historiques assumées |
| **S2** | Unités systemd, scripts et arborescence `/opt/vigil` | Renommer les 4 units + les 7 scripts (`INSTALL_DIR`, `SERVICE_NAME`, `SERVICE_USER`, logs, logrotate), ajouter `ReadWritePaths` pour le fichier d'événements, rendre `uninstall.sh` capable de nettoyer l'ancien nom | `bash -n` sur les 7 scripts ; `systemd-analyze verify systemd/vigil*.service` ; déploiement réel sur le Pi cobaye (dijon-slave) suivi de `/health` OK |
| **S3** | Code applicatif : chemins, libellés, repli de compatibilité | `config.py`/`events.py`/`http_server.py`/`updater` sur `/opt/vigil` + `/var/log/vigil*` avec **repli** sur l'ancien chemin s'il existe seul, `MQTT_TOPIC_PREFIX` défaut `vigil`, tous les libellés produit et User-Agents ; tests adaptés | `./scripts/validate.sh` vert, coverage ≥ 80 % ; test dédié du repli (ancien chemin présent / absent) ; aucun `usg_watchdog`/`USG Watchdog` résiduel dans `src/` hors frontière § 3 |
| **S4** | Métriques Prometheus et Grafana | ~~Préfixe canonique `vigil_*` + double émission `usg_watchdog_*` dépréciée~~ → **bascule sèche (décision 2026-08-23, Q2)** : préfixe `vigil_*` seul, aucune double émission ; dashboard Grafana migré sur `vigil_*`, doc des métriques mise à jour | `/metrics` contient les 19 séries `vigil_*` et **aucune** série `usg_watchdog_*` ; `tests/test_metrics.py` couvre uniquement la famille `vigil_*` ; `grep -c usg_watchdog grafana/dashboard.json` = 0 |
| **S5** | Migration de la flotte et release 2.0.0 | Exécuter le runbook § 5.3 sur les 4 Pi dans l'ordre slave→master, puis `VERSION`=2.0.0, notes de version avec la procédure de migration, tag `v2.0.0` **en dernier**, timers réactivés | Les 4 `/health` annoncent `2.0.0` sous `vigil.service` ; `systemctl is-enabled vigil-updater.timer` = enabled ×4 ; MQTT connecté ×4 ; entités HA toujours vertes ; `docs/RELEASE-NOTES-2.0.0.md` présent |

Dépendances : S1 → S2 → S3 → S4 → S5 (S5 dépend de tout). S2 et S3 pourraient
être menés en parallèle sur des fichiers disjoints, mais partagent la
convention de chemins : **les garder séquentiels**.

---

## 8. Risques et points de non-retour

### Risques (par gravité)

1. **L'updater déploie la 2.0.0 sur un Pi non migré à 03:00** (probabilité
   moyenne, impact critique) : code aux chemins `/opt/vigil` sous un unit qui
   pointe encore sur `/opt/usg-watchdog`, log non ouvrable sous
   `ProtectSystem=strict` → boucle de redémarrage, surveillance perdue pendant
   la nuit, sur potentiellement plusieurs Pi à la fois.
   *Mitigations cumulées* : tag poussé en dernier, timers gelés pendant toute
   la fenêtre, repli de chemins dans le code, chemins épinglés dans `.env`.
2. **Virtualenv copié au lieu d'être recréé** (probabilité moyenne, impact
   élevé) : shebangs et `pyvenv.cfg` pointant sur l'ancien chemin ; `paho-mqtt`
   dégrade **en silence** (le service reste « healthy » sans MQTT — précédent
   avéré en 1.8.2).
   *Mitigation* : venv recréé par `deploy.sh`, vérification explicite de la
   ligne « MQTT connecte (rc=0) » dans le runbook.
3. **Perte de continuité Prometheus / alertes muettes** (probabilité élevée si
   bascule sèche, impact moyen) : séries `usg_watchdog_*` figées, dashboards et
   règles d'alerte silencieux — une alerte qui ne se déclenche plus ne se
   remarque pas.
   *Mitigation initialement recommandée* : double émission pendant 2.0.x,
   retrait planifié en 2.1.0.
   *Décision 2026-08-23 (Q2)* : risque **assumé**, pas mitigé — bascule sèche,
   aucune double émission. Confirmé sans règle d'alerte hors dépôt à migrer.
4. **Suppression prématurée de `/opt/usg-watchdog` ou du user système** : le
   rollback devient une réinstallation complète ; fichiers en UID orphelin.
   *Mitigation* : purge à J+7 seulement, sur demande explicite.
5. **Entités Home Assistant** : aucune raison de bouger (les `unique_id` sont
   déjà `vigil_*`), **sauf** si une instance utilisait le défaut de
   `MQTT_TOPIC_PREFIX`. *Mitigation* : vérifier les 4 `.env` avant migration.
6. **Clone/remote git désynchronisé sur un Pi** : `git pull` échoue au pire
   moment. *Mitigation* : `git remote set-url` fait à l'étape 3, avant tout
   arrêt de service ; GitHub redirige aussi les remotes git.

### Points de non-retour

- **Ne jamais recréer un dépôt nommé `jsoyer/usg-watchdog`** après le
  renommage : cela **annule la redirection GitHub** et casse instantanément
  tout updater non migré. À inscrire en tête des notes de version.
- **Purge de `/opt/usg-watchdog`, des units et du user** : au-delà, le rollback
  n'est plus une bascule de service mais une réinstallation.
- **Retrait des métriques dépréciées** (2.1.0) : irréversible pour les
  dashboards non migrés.
- **Suppression du log historique `/var/log/usg-watchdog.log*`** : à archiver
  avant, jamais à supprimer pendant la fenêtre de migration.

---

## 9. Critères d'acceptation

Périmètre code (S1-S4) :

- [ ] `grep -rIn -e 'usg-watchdog' -e 'usg_watchdog' -e 'USG Watchdog' src/ updater/ scripts/ systemd/ tests/` ne renvoie **que** des occurrences listées comme volontaires au § 3 (frontière USG) ou comme dépréciation métrique assumée
- [ ] Les 4 units s'appellent `systemd/vigil{,-updater}.{service,timer,logrotate}` et `systemd-analyze verify` passe
- [ ] `systemd/vigil.service` liste `/var/log/vigil.log` **et** `/var/log/vigil-events.json` en `ReadWritePaths`, et le fichier d'événements est effectivement écrit après un redémarrage sur le Pi cobaye
- [ ] `updater/update.py` : `GITHUB_REPO=jsoyer/vigil`, `INSTALL_DIR=/opt/vigil`, `SERVICE_NAME=vigil`
- [ ] Repli de compatibilité testé : avec `/opt/vigil` absent et `/opt/usg-watchdog` présent, les chemins par défaut retombent sur l'ancien emplacement (test unitaire)
- [ ] `/metrics` expose les 19 séries `vigil_*` ; **bascule sèche (décision 2026-08-23, Q2)** : aucune série `usg_watchdog_*` résiduelle ; `grafana/dashboard.json` n'utilise plus que `vigil_*`
- [ ] `MQTT_TOPIC_PREFIX` défaut = `vigil` ; **aucune** modification de `src/mqtt_publisher.py` (identité HA figée depuis 1.8.2) — vérifié par `git diff --stat`
- [ ] Aucune variable d'environnement existante renommée ni supprimée (diff de la liste des clés `os.getenv`/`_get_env` avant/après = identique, hors ajouts)
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] `README.md`, `DEPLOY.md`, `WORKFLOW.md`, `CLAUDE.md` à jour, avec encadré de migration 1.8.x → 2.0.0 ; docs historiques (`docs/adr/`, `docs/RELEASE-NOTES-1.8.*`, `docs/tasks/**`) **non modifiées**

Périmètre flotte (S5) :

- [ ] Redirection GitHub prouvée : un updater configuré sur l'ancien nom télécharge et valide un tarball du nouveau dépôt (test réel, pas supposé)
- [ ] Les 4 Pi : `systemctl is-active vigil` = active, `is-enabled vigil-updater.timer` = enabled, `curl /health` = `2.0.0`, journal sans erreur, « MQTT connecte (rc=0) » présent
- [ ] Les 4 Pi : plus aucune référence à `/opt/usg-watchdog` dans le journal du service ; `/opt/usg-watchdog` **toujours présent** (rollback disponible) et `usg-watchdog.service` désactivée mais conservée
- [ ] Coordination HA fonctionnelle après migration : chaque instance voit son peer (`/api/state`), aucun événement `divergence` déclenché par la migration
- [ ] Entités Home Assistant du device « Vigil {instance} » toujours disponibles (aucune nouvelle entité orpheline créée)
- [ ] `docs/RELEASE-NOTES-2.0.0.md` : renommage, procédure manuelle par hôte, avertissement « ne jamais recréer l'ancien dépôt », dépréciation des métriques avec échéance 2.1.0
- [ ] `VERSION` = 2.0.0, tag annoté `v2.0.0` poussé **après** la migration des 4 Pi, `dev` resynchronisée

---

## 10. Questions ouvertes (à trancher avant extraction des sprints)

> **Tranchées le 2026-08-23** — voir § 0bis pour les réponses et les écarts
> vs les recommandations ci-dessous (notamment Q2 : bascule sèche, pas de
> double émission).

**Q1 — Renommer l'utilisateur système `usg-watchdog` → `vigil` ?**
Recommandation : **oui**, via création d'un nouvel utilisateur par `deploy.sh`
(et non `usermod -l`, qui touche un compte en cours d'utilisation). Coût réel :
un `chown -R` déjà présent dans `deploy.sh:169`, plus la reprise du
propriétaire du fichier de log et de `.ssh`. Risque résiduel : des fichiers
oubliés en UID orphelin si l'ancien compte est supprimé trop tôt — d'où la
suppression à J+7 avec `find -user`. Alternative si tu préfères zéro risque :
garder `usg-watchdog` comme nom d'utilisateur, au prix d'une incohérence
visible dans `ps`, `ls -l` et le logrotate.

**Q2 — Métriques Prometheus : double émission, bascule sèche, ou statu quo ?**
Recommandation : **double émission** pendant 2.0.x, retrait en 2.1.0. Une
bascule sèche coupe l'historique et rend muettes les alertes existantes sans
signal ; le statu quo (`usg_watchdog_*` conservé) laisse le nom mort visible à
vie dans Grafana. Question complémentaire : **existe-t-il aujourd'hui des
règles d'alerte Prometheus/Alertmanager hors dépôt** basées sur ces séries ? Si
oui, il faut les inventorier avant S4.

**Q3 — Nom exact du dépôt : `jsoyer/vigil` confirmé ?**
Pas de conflit de namespace (dépôt personnel), mais `vigil` est un nom très
générique sur GitHub. Alternatives si tu veux quelque chose de plus
identifiable : `jsoyer/vigil-watchdog`, `jsoyer/vigil-net`. Ce choix conditionne
`UPDATER_GITHUB_REPO`, les URLs de doc et les remotes des 4 clones.

**Q4 — Chemin d'installation : `/opt/vigil` confirmé ?**
Recommandation : `/opt/vigil` (court, cohérent avec le service `vigil.service`
et le log `/var/log/vigil.log`).

**Q5 — Faut-il conserver un alias systemd pour l'ancien nom ?**
Recommandation : **non**. Un `Alias=usg-watchdog.service` entretient l'ambiguïté
et complique le rollback (deux units revendiquant le même alias). Les anciennes
units restent simplement présentes et désactivées pendant la fenêtre de
rollback.

**Q6 — Fenêtre d'intervention.**
La migration demande 4 interventions SSH, avec **~2 min de service arrêté par
Pi** (couvert par le peer du même site) et une fenêtre totale de quelques heures
pendant laquelle les updaters sont gelés. Quand veux-tu la programmer, et
acceptes-tu de gérer les 4 Pi dans la même session (recommandé : ne pas laisser
la flotte dans un état mixte plus de 24 h) ?

**Q7 — La 1.8.3 (dettes `release.sh` + `pip install` de l'updater) passe-t-elle
avant ?**
Recommandation : **oui**. S5 crée un tag et compte sur un déploiement propre ;
un `release.sh` inutilisable et un updater incapable d'installer les
dépendances sont exactement les deux outils dont la 2.0.0 a besoin.

**Q8 — Renommer `src/watchdog.py` en `src/vigil.py` ?**
Recommandation : **non** (cf. § 3, cas limites). À confirmer, car c'est le seul
endroit où l'ancien vocabulaire reste visible dans `ExecStart`.
