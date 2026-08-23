# Sprint 4 — Auto-updater, documentation, release 1.9.0

- **PRD** : A1 — Pilotage des lignes de secours TP-Link MR110 (2026-08-20)
- **Dépend de** : Sprints 1, 2, 3
- **Bloque** : rien (dernier sprint d'A1)

## Contexte (autoportant)

A1 est fonctionnellement complet : les MR110 sont joignables via le pont Pi Zero,
et pilotables depuis l'API (`/api/tplink/*`) et Telegram (`/lte`).

Il reste à **livrer sans casser la production**. La production, c'est **4
instances** — Dijon (master + slave), Nice (master + slave) — qui se mettent à
jour **toutes seules** : l'auto-updater tire les tags de `main`, valide via
`updater/preflight.py`, déploie, health-check, rollback en cas d'échec.

Deux pièges vérifiés dans le code :

- `updater/preflight.py` fait `import usg`, `import watchdog`,
  `import connectivity`. Si un de ces imports tire `tplinkrouterc6u` et que la
  lib est absente, **le preflight échoue et l'update est annulée**.
- `updater/update.py` ne fait **aucun `pip install`** — seul `deploy.sh` le fait
  à l'installation fraîche. Une nouvelle dépendance n'arrive donc **jamais** dans
  le venv par auto-update.

Ces contraintes portent les noms C1 et C2 dans le PRD.

> **Mise à jour 2026-08-23** : le `pip install` de l'updater (C2) est **déjà
> livré**, en 1.8.3 — voir `updater/update.py::install_requirements` et les
> tests dans `tests/test_update.py`. Ce sprint ne l'implémente plus : il se
> réduit à **vérifier** ce comportement existant avec les nouvelles
> dépendances TP-Link (`tplinkrouterc6u`, `requirements.txt` modifié par le
> Sprint 2). Le reste (4.1 ci-dessous) documente le besoin d'origine, conservé
> pour mémoire et pour l'ordre des opérations avec le preflight.

## Travail

### 4.1 C2 — auto-updater (déjà livré en 1.8.3, à vérifier avec TP-Link)

- `updater/update.py` : détecter un changement de `requirements.txt` entre la
  release courante et la nouvelle (hash ou diff) et relancer
  `pip install -r requirements.txt` dans le venv. Idempotent, loggé, échec →
  **rollback**, comme toute autre étape.
- `updater/preflight.py` : valider les nouveaux modules (`drivers`,
  `managed_devices`) **sans** tirer `tplinkrouterc6u`.
- **Ordre des opérations** : `pip install` **avant** le preflight des imports —
  sinon une instance ayant réellement des équipements déclarés échouerait au
  preflight faute de lib.
- Vérifier que le rollback restaure un état de dépendances cohérent ; sinon le
  **documenter explicitement comme limite connue**. Ne pas laisser croire à une
  garantie qui n'existe pas.

### 4.2 Documentation

- `README.md` : section équipements TP-Link — déclaration `TPLINK_*`, endpoints
  `/api/tplink/*`, commandes Telegram `/lte` et le **mécanisme de confirmation**
  (jeton), seuils de readiness, prérequis TP-Link (mot de passe local, session
  admin unique).
- `DEPLOY.md` :
  - **note de migration pour les 4 instances** : l'auto-update est transparente
    (aucun `TPLINK_*` = comportement 1.8 strictement inchangé) ; déclarer un
    équipement est une action **manuelle et par site** ; ordre conseillé : slave
    d'abord, master ensuite, un site avant l'autre ;
  - **`API_TOKEN` est un prérequis** : sans lui, tous les POST répondent `403`
    (`http_server.py:99-101`) **et les GET `/api/tplink/* aussi** (C19) — donc ni
    commande ni lecture TP-Link par l'API. Telegram reste utilisable ;
  - renvoi vers `docs/runbooks/pi-zero-mr110-access.md` ;
  - rappel de sécurité : la route vers le MR110 est posée **sur les hôtes
    watchdog uniquement**, jamais sur l'USG ni en DHCP ;
  - rappel : le mot de passe TP-Link existe en **4 copies** (master + slave × 2
    sites), en clair (la lib n'accepte pas de hash sur les MR), sans rotation
    outillée. Limite assumée, à documenter plutôt qu'à masquer.
- `docs/runbooks/pi-zero-mr110-access.md` : compléter avec ce qui a réellement
  été fait sur les deux sites, **y compris la variante de saut retenue par site**
  (WiFi ou Ethernet). Le runbook du Sprint 1 a pu diverger une fois sur le terrain.
- `CLAUDE.md` : architecture drivers + équipements pilotables ; préciser que le
  moteur reste mono-cible en A1.
- `scripts/validate.sh` : vérifier l'import de la lib si au moins un équipement
  est déclaré.

### 4.3 Release

- Bump `VERSION` → 1.9.0 ; `dev` → PR → `main` ; tag `v1.9.0`.
- Ouvrir les issues de suivi : **A2** (exposition & Home Assistant) et **PRD B**
  (moteur multi-cible), en référençant §9 du PRD A1.

## Tests

> **Mise à jour 2026-08-23** : la première ligne (**C2**) est déjà couverte par
> `tests/test_update.py` (livré 1.8.3). Ne pas la ré-écrire — l'exécuter avec
> `requirements.txt` modifié par les dépendances TP-Link du Sprint 2 et
> confirmer que le comportement tient.

- **C2** : `requirements.txt` modifié → `pip install` déclenché (mocké) ;
  inchangé → **non** déclenché ; `pip install` en échec → rollback.
- Preflight vert **sans** `tplinkrouterc6u` installée.
- Preflight vert **avec** la lib et des équipements déclarés.
- **C1** de bout en bout : `python -c "import watchdog"` sans la lib.
- Aucun mot de passe dans `/api/config`, `/api/state`, ni dans les logs.
- Suite complète verte, coverage ≥ 80 %.

## Critères d'acceptation

> **Mise à jour 2026-08-23** : le critère **C2** ci-dessous est déjà satisfait
> par la livraison 1.8.3 (`updater/update.py::install_requirements` +
> `tests/test_update.py`). À ré-ouvrir seulement pour vérification avec les
> dépendances TP-Link, pas pour implémentation.

- [x] **C2** : `pip install` déclenché sur changement de `requirements.txt`,
      idempotent, rollback en cas d'échec — **déjà livré en 1.8.3, à vérifier
      avec les dépendances TP-Link**
- [x] `pip install` ordonné **avant** le preflight des imports
- [x] Preflight vert avec **et** sans la lib installée
- [x] README, DEPLOY, `CLAUDE.md` à jour (runbook non touché -- hors périmètre
      de ce sprint réduit 2026-08-23, cf. encart en tête de fichier)
- [x] Note de migration explicite pour les 4 instances
- [x] `API_TOKEN` documenté comme prérequis des commandes API
- [x] Limites de gestion des secrets documentées (4 copies, clair, pas de rotation)
- [x] `scripts/validate.sh` vérifie l'import de `drivers`/`managed_devices`
      (vérification inconditionnelle -- ces modules doivent s'importer que la
      lib TP-Link soit installée ou non, invariant C1)
- [ ] Aucun secret exposé par l'API ni les logs -- non re-vérifié dans ce
      sprint réduit ; couvert par les tests `test_managed_devices.py`
      (`secret_not_exposed`) livrés au Sprint 3
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 % -- VERSION **non modifiée**
      dans ce sprint réduit (bump + tag délégués à l'orchestrateur, cf.
      consignes 2026-08-23)
- [ ] Issues de suivi A2 et PRD B ouvertes -- hors périmètre de ce sprint
      réduit, à la charge de l'orchestrateur/release

## Mise à jour 2026-08-23 -- exécution du sprint réduit

Vérification C2 (lecture de `updater/update.py::main`) : l'ordre des appels
est `install_requirements(staged)` (avant bascule) puis `apply_update(...)`
(bascule du symlink `current`) puis `restart_service()`. `install_requirements`
échoue → `return 1` immédiat, aucune bascule, aucun restart : une instance
avec équipement déclaré ne démarre jamais sans `tplinkrouterc6u`. Confirmé
sans modification de code.

`updater/preflight.py::check_imports()` importe désormais aussi `drivers` et
`managed_devices`, en plus des modules existants. Test ajouté dans
`tests/test_preflight.py` (`test_drivers_and_managed_devices_importable`).
Vérifié statiquement (grep) que `tplinkrouterc6u` n'est importé qu'à
l'intérieur de `TplinkDriver._import_tplinkrouterc6u()`, jamais au niveau
module (invariant C1).

## Frontières de fichiers

- **Modifier** : `updater/update.py`, `updater/preflight.py`,
  `scripts/validate.sh`, `README.md`, `DEPLOY.md`, `CLAUDE.md`, `VERSION`,
  `docs/runbooks/pi-zero-mr110-access.md`
- **Lecture seule** : `src/` (aucun changement fonctionnel dans ce sprint)
- **Contrats partagés** : le processus d'auto-update touche les 4 instances de
  production sans intervention humaine — toute erreur ici est une panne à
  distance sur deux sites
