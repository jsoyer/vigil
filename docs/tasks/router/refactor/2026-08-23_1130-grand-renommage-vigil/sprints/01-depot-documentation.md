# Sprint 1 — Dépôt GitHub, redirection et documentation vivante

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil.md` (§ 2.1, § 2.8, § 7 S1)
- **Dépend de** : rien (premier sprint)
- **Taille estimée** : 45-60 min
- **Isolation** : worktree, MAIS la partie « renommage GitHub » n'est PAS exécutée par le sous-agent (voir § Répartition ci-dessous)

## Objectif

Renommer le dépôt `jsoyer/usg-watchdog` en `jsoyer/vigil`, prouver que la
redirection GitHub (API REST + tarballs) fonctionne réellement, et mettre à
jour la documentation vivante (README, DEPLOY, WORKFLOW, CLAUDE.md, template
d'issue) ainsi que le défaut `UPDATER_GITHUB_REPO`. Les documents historiques
(`docs/adr/`, `docs/RELEASE-NOTES-1.8.*.md`, `docs/tasks/**`) ne sont **pas**
touchés — ils décrivent l'état du système à une date donnée.

## Répartition orchestrateur / sous-agent (important)

**Le renommage GitHub (`gh repo rename usg-watchdog vigil`) est fait par
l'orchestrateur, jamais par le sprint-executor.** Raisons : c'est une opération
sur l'identité du dépôt partagé par les 4 instances de production (les 4
`origin` pointent dessus), elle n'est pas confinée à un worktree, et elle doit
être suivie immédiatement d'une vérification de redirection réelle avant que
quoi que ce soit d'autre ne s'appuie dessus.

Séquence :

1. **Orchestrateur** exécute `gh repo rename vigil --repo jsoyer/usg-watchdog`
   (ou depuis l'UI GitHub), puis vérifie la redirection (§ Étapes, point 1).
2. **Sous-agent** (sprint-executor, worktree) prépare tout le contenu textuel :
   documentation, défaut `UPDATER_GITHUB_REPO` dans `updater/update.py`. Le
   sous-agent n'a pas besoin d'attendre le renommage effectif pour préparer ces
   fichiers — les URLs cibles sont connues à l'avance (`jsoyer/vigil`).
3. **Orchestrateur** merge une fois le renommage confirmé ET le contenu du
   sous-agent revu.

## Étapes concrètes

1. **Preuve de redirection (orchestrateur, avant tout le reste)** :
   ```
   gh repo rename vigil --repo jsoyer/usg-watchdog
   curl -sIL https://api.github.com/repos/jsoyer/usg-watchdog/tags   # doit suivre 301/302 -> jsoyer/vigil, code final 200
   curl -sL -o /tmp/test-tarball.tgz https://api.github.com/repos/jsoyer/usg-watchdog/tarball/v1.8.3
   tar tzf /tmp/test-tarball.tgz | head -3   # doit lister des fichiers, pas une erreur JSON
   ```
   Documenter le résultat (sortie des commandes) dans le message de commit ou
   dans `docs/session-learnings.md` (point 5 ci-dessous) — c'est un test réel
   exigé par le PRD (§ 2.1), pas une supposition.

2. **`updater/update.py`** (sous-agent) :
   - Ligne `GITHUB_REPO = os.getenv("UPDATER_GITHUB_REPO", "jsoyer/usg-watchdog")`
     → `"jsoyer/vigil"`.
   - Ne pas toucher `INSTALL_DIR`/`SERVICE_NAME` ici (sprint 2).

3. **README.md** (54 occurrences recensées au 2026-08-23) :
   - Titre `# USG Watchdog v1.7.0` → `# Vigil v2.0.0`.
   - Toutes les URLs `github.com/jsoyer/usg-watchdog{,/issues}` → `jsoyer/vigil`.
   - Exemple `NTFY_TOPIC=usg-watchdog` (ligne ~446) → `vigil` (valeur
     d'exemple seulement, cf. PRD § 3 cas limites).
   - Ajouter un encadré « Anciennement USG Watchdog — migration 1.8.x → 2.0.0 »
     expliquant le renommage, sans détailler le runbook opérateur (renvoyer
     vers `docs/RELEASE-NOTES-2.0.0.md`, produit au sprint 5).

4. **DEPLOY.md** (45 occurrences), **WORKFLOW.md** (7 occurrences) : même
   traitement — noms de service, chemins `/opt/vigil`, URLs de dépôt.

5. **CLAUDE.md** (18 occurrences, y compris l'arbre de fichiers et les
   procédures) :
   - Titre `# USG Watchdog v1.7.0 — CLAUDE.md` → `# Vigil v2.0.0 — CLAUDE.md`.
   - Toute mention de `/opt/usg-watchdog`, `usg-watchdog.service`, du dépôt.
   - **Ne pas** toucher aux sections décrivant `src/usg.py`, `USG_IP`, etc. —
     elles restent USG par construction (frontière § 3 du PRD).

6. **`.github/ISSUE_TEMPLATE/bug_report.md`** (2 occurrences) : nom du projet
   dans le template.

7. **`docs/session-learnings.md`** : ajouter une ligne d'en-tête signalant le
   renommage (ex. `## 2026-08-23 — Renommage USG Watchdog -> Vigil (v2.0.0)`),
   sans réécrire le reste du fichier — c'est la seule doc historique qui reçoit
   une note, comme prévu au PRD § 2.8.

## Fichiers

- **files_to_modify** : `README.md`, `DEPLOY.md`, `WORKFLOW.md`, `CLAUDE.md`,
  `.github/ISSUE_TEMPLATE/bug_report.md`, `updater/update.py`,
  `docs/session-learnings.md`
- **files_read_only** : `docs/adr/`, `docs/RELEASE-NOTES-1.8.1.md`,
  `docs/RELEASE-NOTES-1.8.2.md`, `docs/tasks/**`
- **forbidden** : `src/` (aucun chemin de code ne bouge dans ce sprint — c'est
  le sprint 3), `systemd/` (sprint 2)

## Critères d'acceptation

- [ ] Redirection GitHub prouvée par un test réel : `curl -sIL
      https://api.github.com/repos/jsoyer/usg-watchdog/tags` renvoie 200 après
      redirection ; téléchargement d'un tarball par l'ancien nom réussi
      (commandes et sortie consignées)
- [ ] `updater/update.py` : `GITHUB_REPO` défaut = `"jsoyer/vigil"`
- [ ] `grep -rn 'usg-watchdog' README.md DEPLOY.md WORKFLOW.md CLAUDE.md` ne
      renvoie plus aucune occurrence (toutes remplacées ou déplacées dans
      l'encadré de migration qui, lui, mentionne l'ancien nom volontairement —
      relire le contexte de chaque hit restant pour confirmer qu'il s'agit bien
      de l'encadré de migration, pas d'un oubli)
- [ ] `grep -c 'usg-watchdog\|usg_watchdog' .github/ISSUE_TEMPLATE/bug_report.md`
      = 0
- [ ] `docs/adr/`, `docs/RELEASE-NOTES-1.8.1.md`, `docs/RELEASE-NOTES-1.8.2.md`,
      `docs/tasks/**` : diff vide (`git diff --stat -- docs/adr docs/RELEASE-NOTES-1.8.1.md docs/RELEASE-NOTES-1.8.2.md docs/tasks` ne liste que ce PRD lui-même, aucun fichier historique modifié)
- [ ] `docs/session-learnings.md` reçoit une ligne d'en-tête datée, reste
      autrement inchangé
- [ ] README.md contient un encadré « Anciennement USG Watchdog » avec le
      renvoi vers la procédure de migration
