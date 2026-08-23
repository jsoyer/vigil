# Infrastructure — release.sh inutilisable + updater sans pip install (1.8.3)

- **Catégorie** : infrastructure (dettes relevées pendant 1.8.1/1.8.2)
- **Date** : 2026-08-23
- **Version cible** : 1.8.3 (patch)
- **Branche** : `main` direct, sans PR

## Dette 1 — `scripts/release.sh` inutilisable en l'état

Constaté pendant les livraisons 1.8.1 et 1.8.2 (tags créés manuellement) :

1. **Double bump** : le script écrit et committe `VERSION` lui-même. Si
   `VERSION` a déjà été bumpé à la main, `release.sh patch` produit une
   version de trop ; passer la version explicite fait échouer le script
   (`git commit` sans rien à committer, sous `set -e`).
2. **`git tag -s` sans clé GPG** : aucune clé secrète sur les machines du
   projet — le script échouerait *après* avoir committé le bump. Les tags
   existants sont d'ailleurs annotés (`git tag -a`), pas signés.

### Correctif

- Si `VERSION` est déjà à la version cible : ne pas re-committer, continuer
  vers le tag (idempotence). Sinon bump + commit comme aujourd'hui.
- Tag **annoté** (`git tag -a`) par défaut ; `-s` uniquement si
  `git config user.signingkey` est configuré.
- Si le tag existe déjà : erreur claire, ne rien casser.
- `bash -n` + un dry-run testable (`RELEASE_DRY_RUN=1` ou équivalent) pour
  vérifier le comportement sans committer.

## Dette 2 — L'updater ne fait pas de `pip install`

Constaté à l'activation MQTT : une release qui ajoute une dépendance
(`paho-mqtt`…) est déployée par l'updater **sans** installation des
dépendances — le venv est partagé et seul `deploy.sh` lit
`requirements.txt`. La 1.9.0 (TP-Link) est directement concernée.

### Correctif (`updater/update.py`)

- Après validation de la release stagée et **avant** la bascule du symlink :
  si la release contient `requirements.txt`, exécuter
  `<venv>/bin/pip install -r <staged>/requirements.txt` (timeout généreux,
  sortie loggée).
- Échec du pip install = échec de la mise à jour **avant** bascule : pas de
  swap, pas de restart, notification — l'instance continue sur la version
  courante (pas besoin de rollback puisque rien n'a basculé).
- Tests ciblés de la nouvelle fonction (subprocess mocké) : succès, échec,
  release sans requirements.txt (no-op).

## Hors périmètre

- Renommage Vigil (PRD séparé), PRD A2.
- Pas de changement du unit systemd ni de deploy.sh (livrés en 1.8.2).

## Critères d'acceptation

- [ ] `release.sh` idempotent sur `VERSION` déjà bumpé ; tag annoté sans GPG ;
      erreur claire si tag existant
- [ ] L'updater installe `requirements.txt` de la release stagée avant la
      bascule ; échec = abandon propre sans bascule (tests)
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] `VERSION` = 1.8.3, tag annoté, `dev` resynchronisé
- [ ] Vérification E2E réelle : déclenchement manuel de l'updater sur un Pi,
      qui doit tirer la 1.8.3, la valider, basculer, redémarrer et annoncer
      `1.8.3` dans `/health`
