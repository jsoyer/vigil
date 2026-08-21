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

## Travail

### 4.1 C2 — auto-updater (bloquant)

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

- **C2** : `requirements.txt` modifié → `pip install` déclenché (mocké) ;
  inchangé → **non** déclenché ; `pip install` en échec → rollback.
- Preflight vert **sans** `tplinkrouterc6u` installée.
- Preflight vert **avec** la lib et des équipements déclarés.
- **C1** de bout en bout : `python -c "import watchdog"` sans la lib.
- Aucun mot de passe dans `/api/config`, `/api/state`, ni dans les logs.
- Suite complète verte, coverage ≥ 80 %.

## Critères d'acceptation

- [ ] **C2** : `pip install` déclenché sur changement de `requirements.txt`,
      idempotent, rollback en cas d'échec
- [ ] `pip install` ordonné **avant** le preflight des imports
- [ ] Preflight vert avec **et** sans la lib installée
- [ ] README, DEPLOY, runbook, `CLAUDE.md` à jour
- [ ] Note de migration explicite pour les 4 instances
- [ ] `API_TOKEN` documenté comme prérequis des commandes API
- [ ] Limites de gestion des secrets documentées (4 copies, clair, pas de rotation)
- [ ] `scripts/validate.sh` vérifie la lib si un équipement est déclaré
- [ ] Aucun secret exposé par l'API ni les logs
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, VERSION = 1.9.0
- [ ] Issues de suivi A2 et PRD B ouvertes

## Frontières de fichiers

- **Modifier** : `updater/update.py`, `updater/preflight.py`,
  `scripts/validate.sh`, `README.md`, `DEPLOY.md`, `CLAUDE.md`, `VERSION`,
  `docs/runbooks/pi-zero-mr110-access.md`
- **Lecture seule** : `src/` (aucun changement fonctionnel dans ce sprint)
- **Contrats partagés** : le processus d'auto-update touche les 4 instances de
  production sans intervention humaine — toute erreur ici est une panne à
  distance sur deux sites
