# Sprint 5 — Auto-updater, documentation, release 1.9.0

- **PRD** : Lignes de secours TP-Link MR110 — phase A (management) — 2026-08-12
- **Dépend de** : Sprints 1 à 4
- **Bloque** : rien (dernier sprint de la phase A)

## Contexte (autoportant)

La phase A est fonctionnellement complète : les MR110 sont joignables via le
pont Pi Zero, pilotables (API `/api/tplink/*` + Telegram `/lte`), et visibles
(dashboard, Prometheus, quota, usage).

Il reste à **livrer sans casser la production**. La production, c'est **4
instances** — Dijon (master + slave), Nice (master + slave) — qui se mettent à
jour **toutes seules** : l'auto-updater tire les tags de `main`, valide via
`updater/preflight.py`, déploie, health-check, rollback en cas d'échec.

Deux pièges vérifiés dans le code :

- `updater/preflight.py` fait `import usg`, `import watchdog`,
  `import connectivity`. Si un de ces imports tire `tplinkrouterc6u` et que la
  lib est absente, **le preflight échoue et l'update est annulée**.
- `updater/update.py` ne fait **aucun `pip install`** — seul `deploy.sh` le fait
  à l'installation fraîche. Une nouvelle dépendance n'arrive donc **jamais**
  dans le venv par auto-update.

Ces contraintes portent les noms C1 et C2 dans le PRD.

## Objectifs

1. **C2** : l'auto-updater installe les dépendances quand elles changent.
2. Documentation, y compris le chemin réseau Pi Zero.
3. Release 1.9.0.

## Travail

### 5.1 C2 — auto-updater (bloquant)

- `updater/update.py` : détecter un changement de `requirements.txt` entre la
  release courante et la nouvelle (hash ou diff) et relancer
  `pip install -r requirements.txt` dans le venv. Idempotent, loggé, et en cas
  d'échec → **rollback**, comme n'importe quelle autre étape.
- `updater/preflight.py` : valider les nouveaux modules (`drivers`,
  `managed_devices`) **sans** tirer `tplinkrouterc6u`.
- **Ordre des opérations** : `pip install` **avant** le preflight des imports —
  sinon une instance qui a réellement des équipements TP-Link déclarés échouerait
  au preflight faute de lib.
- Vérifier que le rollback restaure aussi un état de dépendances cohérent, ou à
  défaut le documenter explicitement comme limite connue (ne pas laisser croire
  à une garantie qui n'existe pas).

### 5.2 Documentation

- `README.md` : section équipements TP-Link — déclaration `TPLINK_*`, endpoints
  `/api/tplink/*`, commandes Telegram `/lte`, seuils de readiness, configuration
  du quota, prérequis TP-Link (mot de passe local, session admin unique).
- `DEPLOY.md` :
  - **note de migration pour les 4 instances** : l'auto-update est transparente
    (aucun `TPLINK_*` déclaré = comportement 1.8 strictement inchangé) ; déclarer
    un équipement est une action **manuelle et par site** ; ordre conseillé :
    slave d'abord, master ensuite, un site avant l'autre ;
  - renvoi vers `docs/runbooks/pi-zero-mr110-access.md` pour le chemin réseau ;
  - rappel de sécurité : la route vers le MR110 est posée **sur les hôtes
    watchdog uniquement**, jamais sur l'USG ni distribuée en DHCP.
- `docs/runbooks/pi-zero-mr110-access.md` : relire et compléter avec ce qui a
  réellement été fait sur les deux sites (le runbook du Sprint 1 a pu diverger
  de la réalité une fois sur le terrain).
- `CLAUDE.md` : architecture drivers + équipements pilotables ; préciser que le
  moteur reste mono-cible en phase A.
- `docs/adr/0001-*.md` : statut → `Accepté` (phase A) une fois livré.
- `scripts/validate.sh` : vérifier l'import de la lib si au moins un équipement
  TP-Link est déclaré.

### 5.3 Release

- Bump `VERSION` → 1.9.0 ; `dev` → PR → `main` ; tag `v1.9.0`.
- Ouvrir l'issue de suivi de la **phase B** (moteur multi-cible, `UsgDriver`,
  readiness automatique, exclusivité de polling C5 complète) en référençant
  §10 du PRD.

## Tests

- **C2** : `requirements.txt` modifié → `pip install` déclenché (mocké) ;
  inchangé → **non** déclenché ; `pip install` en échec → rollback.
- Preflight vert **sans** `tplinkrouterc6u` installée.
- Preflight vert **avec** la lib installée et des équipements déclarés.
- **C1** de bout en bout : `python -c "import watchdog"` sans la lib.
- Aucun mot de passe dans `/api/config`, `/api/state`, ni dans les logs.
- Suite complète verte, coverage ≥ 80 %.

## Critères d'acceptation

- [ ] **C2** : `pip install` déclenché sur changement de `requirements.txt`,
      idempotent, rollback en cas d'échec
- [ ] `pip install` ordonné **avant** le preflight des imports
- [ ] Preflight vert avec **et** sans la lib installée
- [ ] README, DEPLOY, runbook, CLAUDE.md à jour
- [ ] Note de migration explicite pour les 4 instances
- [ ] ADR-0001 passé à `Accepté` (phase A)
- [ ] `scripts/validate.sh` vérifie la lib si un équipement est déclaré
- [ ] Aucun secret exposé par l'API ni les logs
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, VERSION = 1.9.0
- [ ] Issue de suivi phase B ouverte

## Frontières de fichiers

- **Modifier** : `updater/update.py`, `updater/preflight.py`,
  `scripts/validate.sh`, `README.md`, `DEPLOY.md`, `CLAUDE.md`, `VERSION`,
  `docs/adr/0001-multi-vendor-router-monitoring.md`,
  `docs/runbooks/pi-zero-mr110-access.md`
- **Lecture seule** : `src/` (aucun changement fonctionnel dans ce sprint)
- **Contrats partagés** : le processus d'auto-update touche les 4 instances de
  production sans intervention humaine — toute erreur ici est une panne à
  distance sur deux sites
