# Sprint 5 — Migration de la flotte et release 2.0.0 (RUNBOOK OPÉRATEUR)

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil.md` (§ 5, § 6, § 7 S5, § 8, § 9 AC flotte)
- **Dépend de** : Sprints 1, 2, 3, 4 mergés sur `main` (gate `s1-s4-merged-before-fleet`)
- **Taille estimée** : 3-4 h de fenêtre totale (4 interventions SSH de ~10 min
  chacune + 30 min d'observation entre les deux Pi d'un même site + vérifications)
- **Isolation** : aucune (`isolation: none`) — ce n'est pas un sprint de code,
  c'est une opération manuelle sur 4 machines de production hors dépôt.
  **N'est PAS délégué à un sprint-executor.** Exécuté par l'opérateur (ou
  l'orchestrateur en son nom, avec confirmation à chaque étape numérotée).

## ⚠️ Écart assumé vs PRD § 5.2 — ordre de migration

Le PRD § 5.2 recommandait un ordre **entrelacé** (slave-Dijon, slave-Nice,
master-Dijon, master-Nice) pour maximiser la redondance inter-sites pendant la
fenêtre. **Ce runbook suit un ordre site-par-site** (slave-Dijon → master-Dijon
→ slave-Nice → master-Nice), sur décision explicite du 2026-08-23. Les deux
ordres respectent l'invariant de sécurité central du PRD — **jamais les deux
membres d'une paire HA migrés simultanément, le slave toujours avant le
master** — l'ordre site-par-site termine simplement Dijon avant d'ouvrir Nice,
ce qui simplifie le suivi opérateur (un seul site « en migration » à la fois)
au prix d'une fenêtre totale légèrement plus longue avant que le second site
ne bénéficie de la redondance croisée. Si Dijon échoue et nécessite un
rollback complet, Nice n'a pas encore été touché — propriété que l'ordre
entrelacé du PRD n'offrait pas non plus (chaque site reste indépendant dans
les deux ordres).

## État de la flotte (rappel, cf. PRD § 1)

| Pi | Rôle | `INSTANCE_ID` | Login SSH | Version avant migration |
|---|---|---|---|---|
| `bbh-dij-guardian` | dijon-slave | `bbh_dij_guardian` | `dietpi` | 1.8.3 (post S1-S4) |
| `bbh-network` | dijon-master (**local**) | `bbh_network` | — (local, pas de SSH) | 1.8.3 |
| `bbh-nce-guardian` | nice-slave | `bbh_nce_guardian` | `dietpi` | 1.8.3 |
| `penelope` | nice-master | `penelope` | `pi` | 1.8.3 |

Accès flotte : clé `~/.ssh/id_ed25519_fleet` + entrées `~/.ssh/config`, sudo
NOPASSWD sur les 4 Pi. **Règle CLAUDE.md/RTK** : ne jamais préfixer une
commande SSH par `cd` (le hook rtk peut le perdre) — utiliser des chemins
absolus ou `git -C`.

## Pré-conditions bloquantes avant de commencer (gates `progress.json`)

1. **`s1-s4-merged-before-fleet`** : sprints 1-4 mergés sur `main` (via `dev`
   → PR), `./scripts/validate.sh` vert sur `main`.
2. **`env-mqtt-prefix-audit`** : sur les 4 Pi, `grep MQTT_TOPIC_PREFIX
   /opt/usg-watchdog/.env` confirme un préfixe explicite `vigil/<site>-<role>`
   (pas de dépendance au défaut qui change en 2.0.0).
3. Sauvegardes disponibles : espace disque suffisant pour les archives `tar`
   de chaque Pi (§ Procédure, étape 0).

---

## Procédure générale par Pi (détail des commandes)

Pour **chaque** Pi, dans l'ordre § Séquence ci-dessous, exécuter les 8 étapes
suivantes. `<HOST>` = alias SSH du Pi (ou exécution locale pour
`bbh-network`). `<PORT>` = valeur de `HTTP_PORT` dans le `.env` de cette
instance.

### Étape 0 — Constat initial et sauvegarde

```
ssh <HOST> systemctl is-active usg-watchdog
ssh <HOST> curl -s localhost:<PORT>/health
ssh <HOST> tar czf ~/vigil-migration-$(hostname).tgz /opt/usg-watchdog/.env /opt/usg-watchdog/.ssh
```
(Sur `bbh-network`, local, sans préfixe `ssh` : exécuter directement les mêmes
commandes.)

Vérifier que `/health` répond en 1.8.3 et `is-active` = `active` avant de
continuer. Conserver la sortie (copier-coller dans le journal de migration,
ex. une section de `docs/session-learnings.md` ou un fichier de suivi local —
ne pas l'improviser, c'est la référence en cas de rollback).

### Étape 1 — Gel de l'updater

```
ssh <HOST> sudo systemctl disable --now usg-watchdog-updater.timer
ssh <HOST> systemctl is-enabled usg-watchdog-updater.timer   # doit renvoyer "disabled"
```

### Étape 2 — Épingler les chemins courants dans `.env`

Ajouter dans `/opt/usg-watchdog/.env` (édition directe, ex. `ssh <HOST> sudo
tee -a /opt/usg-watchdog/.env`) les 3 lignes suivantes avec les valeurs
**actuelles** (avant migration) :
```
LOG_FILE=/var/log/usg-watchdog.log
USG_SSH_KEY=/opt/usg-watchdog/.ssh/usg_ed25519
USG_KNOWN_HOSTS=/opt/usg-watchdog/.ssh/known_hosts
```
Objectif : le code 2.0.0 ne peut plus se tromper de chemin même si l'ordre des
opérations dérape ensuite (le repli de compatibilité du sprint 3 devient
redondant avec ces valeurs explicites, ce qui est voulu).

### Étape 3 — Clone et remote

```
ssh <HOST> git -C ~/github/usg-watchdog remote set-url origin git@github.com:jsoyer/vigil.git
ssh <HOST> git -C ~/github/usg-watchdog fetch --tags
ssh <HOST> git -C ~/github/usg-watchdog pull origin main
ssh <HOST> mv ~/github/usg-watchdog ~/github/vigil
```
**Ne jamais préfixer par `cd`** : chaque commande ci-dessus utilise `git -C`
ou un chemin absolu, y compris depuis une session SSH.

### Étape 4 — Pré-remplissage de `/opt/vigil`

```
ssh <HOST> sudo mkdir -p /opt/vigil
ssh <HOST> sudo cp -a /opt/usg-watchdog/.env /opt/usg-watchdog/.ssh /opt/vigil/
```
**PAS** le venv (recréé par `deploy.sh`, étape 5), **PAS** `releases/` (recréé
aussi). Vérifier que `.env` copié contient bien les 3 lignes ajoutées à
l'étape 2.

### Étape 5 — Déploiement

```
ssh <HOST> sudo ~/github/vigil/scripts/deploy.sh
```
Ce script (sprint 2) : crée l'utilisateur système `vigil` (nouveau compte,
jamais `usermod -l` — décision Q1), le venv (recréé, jamais copié — vérifié à
l'étape 7), `releases/v2.0.0` + `current`, le log, le logrotate, les 4 unités
`vigil{,-updater}.{service,timer}`, `enable --now vigil`.

**L'ancien service `usg-watchdog` n'est jamais arrêté par ce script** — il
continue de tourner en parallèle jusqu'à l'étape 6.

### Étape 6 — Bascule

```
ssh <HOST> sudo systemctl disable --now usg-watchdog
```
L'unité `usg-watchdog.service` reste **présente** sur le disque, seulement
désactivée — c'est le filet de rollback.

### Étape 7 — Vérifications (TOUTES obligatoires avant le Pi suivant)

```
ssh <HOST> curl -s localhost:<PORT>/health
```
→ doit contenir `"status": "healthy"` (ou `"degraded"` avec raison
explicable, jamais une erreur de connexion) **et** `"version": "2.0.0"`.

```
ssh <HOST> journalctl -u vigil -n 80 --no-pager
```
→ doit contenir « Vigil demarre » (ou libellé équivalent posé au sprint 3),
« MQTT connecte (rc=0) », « discovery envoye » ; **aucune** ligne mentionnant
`/opt/usg-watchdog` ; aucune trace d'erreur Python (traceback).

```
ssh <HOST> ls -l /var/log/vigil.log /var/log/vigil-events.json
```
→ les deux fichiers existent, taille non nulle, propriétaire `vigil:vigil`
(ou `vigil:adm` selon le logrotate) — **c'est le test direct du fix du bug
latent `ReadWritePaths`** posé au sprint 2 : si `vigil-events.json` est absent
ou vide après un cycle de fonctionnement, le fix n'est pas effectif, ne pas
continuer.

```
ssh <HOST> curl -s localhost:<PORT>/metrics | grep -c '^vigil_'    # doit être > 0
ssh <HOST> curl -s localhost:<PORT>/metrics | grep -c '^usg_watchdog_'   # doit valoir 0 (bascule seche, decision Q2)
```

```
# Dashboard HTTP accessible :
ssh <HOST> curl -sI localhost:<PORT>/dashboard | head -1   # doit renvoyer 200
```

**Entités Home Assistant** : depuis Home Assistant (hors SSH), vérifier que le
device « Vigil {instance} » reste vert / disponible — aucune nouvelle entité
orpheline, aucune entité passée `unavailable` (les `unique_id` n'ont pas
bougé, invariant du PRD).

**Coordination peer** : depuis l'autre membre de la paire (déjà migré ou
encore en 1.8.3 selon l'ordre) :
```
curl -s <PEER_IP>:<PEER_PORT>/api/state | grep -o '"instance_id":"[^"]*"'
```
→ l'instance migrée doit apparaître comme vue par son peer, aucun événement
`divergence` ne doit être loggé côté peer dans les minutes qui suivent.

### Étape 8 — Dégel de l'updater (sous son nouveau nom)

```
ssh <HOST> sudo systemctl enable --now vigil-updater.timer
ssh <HOST> systemctl is-enabled vigil-updater.timer   # doit renvoyer "enabled"
```

**Ne réactiver que sur CE Pi, une fois ses propres vérifications validées** —
ne jamais réactiver les 4 timers en bloc à la fin (invariant
`updater-timers-frozen` de `INVARIANTS.md`).

---

## Séquence des 4 Pi (ordre décidé le 2026-08-23)

### 1. `bbh-dij-guardian` (dijon-slave) — cobaye

Exécuter les étapes 0-8 ci-dessus avec `<HOST>` = `bbh-dij-guardian`,
`<PORT>` = port HTTP de cette instance. **Pendant cette fenêtre, dijon-master
(`bbh-network`) continue de surveiller le site** — c'est pour ça qu'on
commence par le slave.

**Vérif individuelle** : les vérifications de l'étape 7 doivent toutes passer
avant de considérer ce Pi migré.

### 2. Attendre ≥ 30 min de fonctionnement sain

Observer : au moins un cycle de rapport et une remontée MQTT visibles côté
Home Assistant / dashboard, sans anomalie.

### 3. `bbh-network` (dijon-master, LOCAL)

Exécuter les étapes 0-8 **sans préfixe `ssh`** (exécution directe sur la
machine locale — c'est l'hôte qui porte cette session). Le slave dijon
(`bbh-dij-guardian`) est déjà en 2.0.0 et peut prendre le relais pendant cette
fenêtre.

**Vérif site (Dijon)** : après cette étape, vérifier que les **deux** Pi de
Dijon sont en 2.0.0, `vigil.service` actif, se voient mutuellement via
`/api/state`, aucune divergence de score anormale. C'est le point de contrôle
« site Dijon migré » avant d'ouvrir Nice.

### 4. Attendre ≥ 30 min avant d'ouvrir Nice (marge d'observation inter-site)

Pas une exigence stricte du PRD (qui ne demande le délai qu'entre les deux
membres d'un **même** site), mais une marge de prudence raisonnable avant
d'attaquer le second site du même run : confirmer que rien d'anormal
n'apparaît côté Dijon avant de reproduire l'opération à Nice.

### 5. `bbh-nce-guardian` (nice-slave)

Exécuter les étapes 0-8 avec `<HOST>` = `bbh-nce-guardian`, login `dietpi`.
**Confirme la reproductibilité sur DietPi** (environnement différent de
`bbh-network`/Raspberry Pi OS). nice-master (`penelope`) continue de
surveiller le site pendant cette fenêtre.

### 6. Attendre ≥ 30 min de fonctionnement sain (identique à l'étape 2)

### 7. `penelope` (nice-master)

Exécuter les étapes 0-8 avec `<HOST>` = `penelope`, login `pi` (dernier Pi,
environnement utilisateur différent des 3 autres — attention particulière aux
permissions lors de la création de l'utilisateur `vigil` et du `chown`).

**Vérif site (Nice)** : après cette étape, vérifier que les **deux** Pi de
Nice sont en 2.0.0, se voient mutuellement, aucune divergence.

---

## Rollback (à chaque étape, par Pi — cf. PRD § 5.3)

| Étape atteinte | Rollback |
|---|---|
| 0-4 | Rien à défaire (rien n'a été arrêté) ; `sudo rm -rf /opt/vigil` sur `<HOST>` |
| 5 (vigil démarré, ancien encore actif) | `sudo systemctl disable --now vigil` — l'ancien service n'a jamais été arrêté, aucune coupure |
| 6-7 (bascule faite, vérif KO) | `sudo systemctl disable --now vigil && sudo systemctl enable --now usg-watchdog` puis reconfirmer `curl localhost:<PORT>/health` = 1.8.3 |
| 8 (dégel fait, anomalie découverte après coup) | Idem 6-7 **+** `sudo systemctl disable --now vigil-updater.timer` |
| J+7 (après purge, § suivant) | Réinstallation depuis le tag `v1.8.3` + restauration de l'archive `~/vigil-migration-$(hostname).tgz` de l'étape 0 |

**Si un Pi échoue et qu'on rollback** : ne pas migrer les Pi suivants de la
séquence tant que la cause n'est pas comprise et corrigée (remonter en sprint
1-4 si c'est un défaut de code, pas seulement retenter sur le même Pi).

---

## Après validation des 4 Pi : release 2.0.0

Uniquement une fois **les 4 vérifications individuelles ET les 2 vérifications
de site** validées :

1. Sur le poste de dev, branche `main` à jour (les sprints 1-4 déjà mergés) :
   ```
   echo "2.0.0" > VERSION
   git add VERSION
   git commit -m "chore: bump version to 2.0.0"
   ```
2. Rédiger `docs/RELEASE-NOTES-2.0.0.md` contenant :
   - Le renommage USG Watchdog → Vigil, procédure manuelle par hôte (renvoi
     vers ce runbook).
   - **Avertissement en tête** : « Ne jamais recréer un dépôt nommé
     `jsoyer/usg-watchdog` — cela annule la redirection GitHub et casse
     instantanément tout updater non migré. »
   - **Bascule sèche des métriques (décision Q2, 2026-08-23)** : les séries
     `usg_watchdog_*` n'existent plus depuis la 2.0.0, aucune double émission,
     rupture d'historique Prometheus assumée — pas d'échéance 2.1.0 à
     mentionner puisqu'il n'y a rien à retirer plus tard.
   - Nouvel utilisateur système `vigil`, ancien `usg-watchdog` conservé
     jusqu'à J+7 (purge séparée, § suivant).
3. **Tag en dernier** :
   ```
   git tag -a v2.0.0 -m "Vigil 2.0.0 — renommage USG Watchdog, zero changement de comportement"
   git push origin main
   git push origin v2.0.0
   ```
   Ne jamais inverser cet ordre avec les migrations Pi — c'est l'invariant
   `tag-v2.0.0-posted-last`.
4. Resynchroniser `dev` :
   ```
   git checkout dev && git merge main && git push origin dev && git checkout main
   ```
5. Mettre à jour `docs/session-learnings.md` avec le résultat de la migration
   (durée réelle, écarts éventuels vs ce runbook, incidents).

---

## Opération séparée, explicitement demandée (J+7, PAS dans ce sprint)

Rappel du PRD § 5.4 — **ne pas exécuter automatiquement**, attendre une
demande explicite de l'utilisateur après la fenêtre d'observation de 7 jours :

```
# Par Pi, après dernière archive :
ssh <HOST> sudo find / -xdev -user usg-watchdog   # doit être vide avant userdel
ssh <HOST> sudo tar czf ~/usg-watchdog-final-$(hostname).tgz /var/log/usg-watchdog.log*
ssh <HOST> sudo rm -rf /opt/usg-watchdog
ssh <HOST> sudo rm -f /etc/systemd/system/usg-watchdog*.{service,timer}
ssh <HOST> sudo rm -f /etc/logrotate.d/usg-watchdog
ssh <HOST> sudo rm -f /var/log/usg-watchdog.log*
ssh <HOST> sudo userdel usg-watchdog   # en dernier, apres verification find -xdev
```

## Fichiers touchés par ce sprint (dans le dépôt)

- **files_to_create** : `docs/RELEASE-NOTES-2.0.0.md`
- **files_to_modify** : `VERSION`, `docs/session-learnings.md`
- Tout le reste de ce sprint est **hors dépôt** (SSH, systemctl, filesystem
  des 4 Pi) — pas de `files_to_modify` supplémentaire côté code, les sprints
  1-4 ont déjà livré tout le code nécessaire.

## Critères d'acceptation

- [ ] Redirection GitHub reconfirmée fonctionnelle avant la migration (test
      réel déjà fait au sprint 1, pas à refaire — juste vérifier qu'elle est
      toujours active)
- [ ] Les 4 Pi : `systemctl is-active vigil` = `active`, `is-enabled
      vigil-updater.timer` = `enabled`, `curl /health` = `2.0.0`, journal sans
      erreur, « MQTT connecte (rc=0) » présent
- [ ] Les 4 Pi : plus aucune référence à `/opt/usg-watchdog` dans le journal
      du service `vigil` ; `/opt/usg-watchdog` **toujours présent** (rollback
      disponible) et `usg-watchdog.service` désactivée mais conservée
- [ ] Coordination HA fonctionnelle après migration sur les 2 sites : chaque
      instance voit son peer, aucun événement `divergence`
- [ ] Entités Home Assistant du device « Vigil {instance} » toujours
      disponibles ×4 (aucune nouvelle entité orpheline)
- [ ] `docs/RELEASE-NOTES-2.0.0.md` présent avec les 4 points obligatoires
      (renommage, procédure manuelle, avertissement anti-recréation de dépôt,
      bascule sèche des métriques)
- [ ] `VERSION` = `2.0.0`, tag annoté `v2.0.0` poussé **après** la validation
      des 4 Pi (jamais avant), `dev` resynchronisée
- [ ] `/var/log/vigil-events.json` non vide sur les 4 Pi (vérification finale
      du fix `ReadWritePaths` en conditions réelles)
