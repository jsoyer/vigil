# Infrastructure — micro-dettes post-renommage (2.0.1)

- **Catégorie** : infrastructure
- **Date** : 2026-08-23
- **Version cible** : 2.0.1 (patch)
- **Branche** : `main` direct, sans PR (routing projet)
- **Origine** : dettes loggées pendant les livraisons 1.8.3 et 2.0.0

## Dette 1 — L'updater ne met pas à jour sa propre copie

`/opt/vigil/updater/` n'est réécrit que par `deploy.sh` ; l'updater qui tourne
(via le timer) ne se rafraîchit jamais lui-même. Une amélioration de l'updater
livrée par release resterait inactive jusqu'au prochain passage manuel.

### Correctif (`updater/update.py`)

Après la bascule du symlink `current` (et avant le restart du service) : si la
release stagée contient un dossier `updater/`, copier ses `*.py` vers
`INSTALL_DIR/updater/` (écrasement du script en cours d'exécution : sans effet
sur le process courant sous Linux, le prochain run du timer utilisera la
nouvelle version). Logguer la mise à jour. Échec de cette copie = WARNING, pas
un échec de la mise à jour (le cœur — code applicatif — est déjà basculé).

Tests : release avec `updater/` (copie faite), sans (no-op), erreur de copie
(warning, retour succès quand même).

## Dette 2 — `DeprecationWarning` Python 3.14 sur `tar.extract`

Le journal updater montre : « Python 3.14 will, by default, filter extracted
tar archives... Use the filter argument ». L'extraction a déjà une protection
path-traversal maison, mais autant adopter le mécanisme standard.

### Correctif (`updater/update.py`, extract_tarball)

Passer `filter="data"` à `tar.extract(...)`. Compatibilité : le paramètre
existe depuis Python 3.12 (backporté 3.11.4+) — le projet exige 3.11+, donc
protéger par try/except TypeError avec repli sur l'appel actuel (et garder la
protection maison dans les deux cas). Test : l'extraction fonctionne toujours
(suite updater existante), pas de warning sur les versions récentes.

## Dette 3 — Défaut `USG_IP` site-local dans `setup_ssh.sh`

nice-slave portait une modif locale de clone (défaut `192.168.3.1`) — mise en
stash pendant la migration. Cause : `setup_ssh.sh` code en dur le défaut
`192.168.1.1`, faux pour le site de Nice.

### Correctif (`scripts/setup_ssh.sh`)

Avant d'appliquer le défaut, lire `USG_IP` depuis `/opt/vigil/.env` (puis
`/opt/usg-watchdog/.env` en repli) s'il n'est pas déjà dans l'environnement.
Priorité : env explicite > .env > défaut 192.168.1.1. `bash -n` + relecture.
Après livraison : supprimer le stash `site-local` sur nice-slave (il devient
sans objet).

## Critères d'acceptation

- [ ] L'updater copie `updater/*.py` de la release vers sa propre copie après
      bascule (tests : présent/absent/échec-warning)
- [ ] `tar.extract` utilise `filter="data"` avec repli compatible 3.11
- [ ] `setup_ssh.sh` résout `USG_IP` depuis le `.env` avant le défaut
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] `VERSION` = 2.0.1 via `release.sh`, tag poussé
- [ ] E2E : les 4 updaters `vigil` tirent la 2.0.1 automatiquement
      (déclenchement manuel), `/health` = 2.0.1 partout, et la copie
      `/opt/vigil/updater/` est rafraîchie par l'update lui-même (dette 1
      vérifiée en réel)
