# Bugfix — Unit systemd sur layout obsolète + identité MQTT `vigil` (1.8.2)

- **Catégorie** : bugfix
- **Date** : 2026-08-23
- **Version cible** : 1.8.2 (patch)
- **Branche** : `main` direct, sans PR (routing projet pour les bugs)
- **Découvert pendant** : vérification du déploiement 1.8.1 (2026-08-22)
- **Dépend de** : 1.8.1 (identité par instance, livrée mais jamais exécutée — voir bug 1)

---

## Bug 1 — Les mises à jour sont des no-ops silencieux depuis la 1.7.6

### Constat (prouvé sur le Pi dijon-master, 2026-08-22)

- L'updater (`updater/update.py`) télécharge, valide, extrait dans
  `releases/vX.Y.Z/`, bascule le symlink `current`, redémarre le service,
  health check OK → journal « Mise a jour v1.8.0 -> v1.8.1 reussie ».
- **Mais le unit systemd** (`systemd/usg-watchdog.service:10,12`) exécute
  `WorkingDirectory=/opt/usg-watchdog/src` +
  `ExecStart=... /opt/usg-watchdog/src/watchdog.py` — le layout **à plat**
  installé par `deploy.sh:110-125`. Le symlink `current` n'est lu par personne.
- Résultat : `/health` annonce `1.7.6`, le code qui tourne n'a aucune trace
  d'`INSTANCE_ID` (`client_id` encore en dur). Toutes les « mises à jour »
  depuis le déploiement à plat sont des no-ops. Les 4 Pi sont concernés.
- Le health check de l'updater ne compare pas la version → l'échec est
  invisible depuis des mois.

### Cause racine

Deux conventions de layout coexistent : `deploy.sh` installe à plat
(`${INSTALL_DIR}/src`), l'updater installe en releases + symlink
(`releases/vX/` + `current`). Le unit systemd suit la première, l'updater
la seconde. Personne ne vérifie que la version redémarrée est celle attendue.

### Correctif

1. **`systemd/usg-watchdog.service`**
   - `WorkingDirectory=/opt/usg-watchdog/current/src`
   - `ExecStart=/opt/usg-watchdog/venv/bin/python /opt/usg-watchdog/current/src/watchdog.py`
   - Le reste du unit (sandboxing, capabilities) inchangé. `ReadOnlyPaths=/opt/usg-watchdog`
     couvre déjà `releases/` et le symlink.
   - `watchdog.py` lit `VERSION` en relatif (`../VERSION`) → avec
     `WorkingDirectory=current/src`, il résoudra `current/VERSION` (présent dans
     chaque release extraite par l'updater). Vérifier que `deploy.sh` place bien
     `VERSION` au même endroit (voir 2).

2. **`scripts/deploy.sh`** — aligner sur le layout releases :
   - installer dans `${INSTALL_DIR}/releases/v$(cat VERSION)/` (au minimum
     `src/` + `VERSION`), puis basculer `current` **atomiquement**
     (`ln -sfn` sur un nom temporaire + `mv -T`, ou le même mécanisme que
     l'updater — regarder comment `update.py` fait le swap et faire pareil) ;
   - si un ancien layout à plat `${INSTALL_DIR}/src` existe : le **déplacer**
     en `${INSTALL_DIR}/src.flat-backup` (ne pas supprimer — c'est le
     rollback de dernier recours), avec un log explicite ;
   - conserver : venv partagé, `.env`, `.ssh`, updater, logrotate, ownership.

3. **`updater/update.py`** — le health check doit vérifier la **version** :
   - après restart, GET `/health`, comparer le champ `version` à la version
     cible de la mise à jour ;
   - mismatch → traiter comme un échec de mise à jour (même chemin que le
     health check KO : rollback + notification). C'est exactement le mode de
     défaillance qui vient de passer inaperçu ;
   - tests : cas nominal (version OK), cas mismatch (rollback déclenché).

## Bug 2 (fenêtre d'opportunité) — Identité MQTT sous le nom définitif `vigil`

Le logiciel sera renommé **Vigil** (décision utilisateur 2026-08-23). Les
`unique_id` HA sont immuables : les renommer plus tard = re-purge complète des
entités orphelines. Or **aucune instance n'a encore exécuté la 1.8.1** (bug 1)
→ les entités `usg_watchdog_{instance}_*` n'ont jamais été créées. En passant
l'identité MQTT à `vigil` maintenant, les entités naissent directement sous
leur nom définitif : une seule migration HA au lieu de deux.

### Correctif (`src/mqtt_publisher.py`)

| Élément | Avant (1.8.1) | Après (1.8.2) |
|---|---|---|
| `device.identifiers` | `usg_watchdog_{instance_id}` | `vigil_{instance_id}` |
| `device.name` | `USG Watchdog {instance_id}` | `Vigil {instance_id}` |
| `device.model` | `USG Watchdog` | `Vigil` |
| `unique_id` | `usg_watchdog_{instance_id}_{sensor_id}` | `vigil_{instance_id}_{sensor_id}` |
| Topic discovery | `homeassistant/sensor/usg_watchdog_{instance_id}/...` | `homeassistant/sensor/vigil_{instance_id}/...` |
| `client_id` MQTT | `usg-watchdog-{INSTANCE_ID}` | `vigil-{INSTANCE_ID}` |

Dans `src/config.py` : le fallback de `_normalize_instance_id()` (chaîne vide
→ `"usg_watchdog"`) devient `"vigil"`.

### Hors périmètre (inchangé, volontairement)

- `MQTT_TOPIC_PREFIX` : défaut `usg-watchdog` conservé. Le renommer fait
  partie du grand renommage (repo, service, `/opt`) — pas d'un patch.
  En production les 4 instances utilisent des prefixes explicites
  (`vigil/<site>-<role>`), le défaut ne sert à rien sur le terrain.
- Nom du service systemd, chemins `/opt/usg-watchdog`, nom du repo : idem,
  grand renommage uniquement.
- retain / availability / device_class : toujours hors périmètre (cf. tâche
  1.8.1).

## Tests

- `tests/test_mqtt_publisher.py` : adapter les attentes `usg_watchdog_*` →
  `vigil_*` (identité device, unique_id, topics, client_id). Les tests de
  disjonction, de normalisation et le faux broker (éviction) restent tels
  quels dans leur logique.
- `tests/` updater : cas version OK / version mismatch → rollback.
- `./scripts/validate.sh` vert (coverage ≥ 80 %).
- `bash -n scripts/deploy.sh` + relecture manuelle (pas de CI shell).

## Note de migration — docs/RELEASE-NOTES-1.8.2.md (OBLIGATOIRE)

1. **Sur chaque Pi, une intervention manuelle unique est requise** — l'updater
   ne peut pas réparer le unit qui l'empêche d'agir :
   ```bash
   cd <repo> && git pull
   sudo install -m 644 systemd/usg-watchdog.service /etc/systemd/system/usg-watchdog.service
   sudo systemctl daemon-reload && sudo systemctl restart usg-watchdog
   curl -s http://127.0.0.1:<port>/health   # doit annoncer la version de current/
   ```
   (ou `sudo ./scripts/deploy.sh` une fois le repo à jour, qui fait tout).
2. Les entités HA `usg_watchdog*` (anciennes, partagées) deviennent orphelines
   à la première connexion MQTT → suppression manuelle dans HA. Historique non
   transféré. Irréversible. (Reprise de la note 1.8.1 — qui n'a jamais été
   déclenchée en pratique.)
3. Les entités naissent sous l'identité `vigil_{instance}` — aucune entité
   `usg_watchdog_{instance}` (1.8.1) n'a existé, il n'y a **pas** de seconde
   purge.

## Critères d'acceptation

- [x] `systemd/usg-watchdog.service` pointe sur `current/src` (WorkingDirectory + ExecStart)
- [x] `deploy.sh` installe en `releases/vX/` + symlink `current`, migre le layout à plat en backup
- [x] L'updater échoue (rollback + alerte) si `/health` n'annonce pas la version cible après restart (tests)
- [x] Identité MQTT entièrement `vigil_*` / `vigil-{instance}` ; tests adaptés et verts
- [x] Fallback d'instance vide = `vigil`
- [x] `./scripts/validate.sh` vert, coverage ≥ 80 % (836 tests, 92 %)
- [x] `docs/RELEASE-NOTES-1.8.2.md` avec les 3 points de migration
- [x] `VERSION` = 1.8.2 (bump en commit séparé, tag manuel annoté — cf. pièges `release.sh` dans session-learnings)

## Issues

- **Résolu (2026-08-23)** — livré et déployé sur les 4 Pi (dijon-master,
  dijon-slave, nice-master/penelope, nice-slave), tous vérifiés `/health` =
  1.8.2, MQTT connecté (rc=0), discovery HA envoyée sous l'identité `vigil`.
- **Découvert au déploiement** : `paho-mqtt` absent de `requirements.txt` —
  les 4 venvs ne l'avaient pas, MQTT silencieusement désactivé (warning au
  démarrage). Corrigé : installé manuellement sur les 4 Pi (épinglé 1.6.1,
  l'API de callbacks v1 du code est incompatible paho-mqtt 2.x) + ajouté au
  `requirements.txt` en post-release (pas de nouveau tag : l'updater ne fait
  pas de pip install, seul `deploy.sh` lit requirements.txt depuis le clone).
- (ouvert) `scripts/release.sh` toujours inutilisable (double bump, `git tag -s`
  sans clé GPG) — hors périmètre ici, tag manuel comme pour 1.8.1.
