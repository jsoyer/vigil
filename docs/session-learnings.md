## 2026-08-23 — Renommage USG Watchdog -> Vigil (v2.0.0)

Sprint 1 du grand renommage : dépôt GitHub renommé `jsoyer/vigil` (redirection
vérifiée), documentation vivante (README, DEPLOY, WORKFLOW, CLAUDE.md,
template d'issue) mise à jour vers Vigil v2.0.0. Le routeur Ubiquiti reste
désigné USG (src/usg.py, USG_IP, etc. inchangés).

# Session Learnings — USG Watchdog

Mémoire vivante de session. Survit à `/compact`. Append-only par catégorie.

Catégories : `ENV` `LOGIC` `CONFIG` `DEPENDENCY` `SECURITY` `TEST` `DEPLOY` `PROOT` `PERFORMANCE`

---

## Active Task Queue

| Tâche | Statut | Mode |
|---|---|---|
| `docs/tasks/router/bugfix/2026-08-20_1618-mqtt-instance-identity.md` | DONE (local) — reste tag + resync `dev` au ship | Autonomous |

## Execution Mode: Autonomous

Route : tâche simple (checklist, pas de `progress.json`). Un seul agent sonnet,
pas de worktree — périmètre cohérent sur 3 fichiers (`src/config.py`,
`src/mqtt_publisher.py`, `tests/test_mqtt_publisher.py`) + `VERSION` + note de
migration.

---

## Ship Pipeline State — 1.8.3 (2026-08-23)

- **Version** : 1.8.3 (release.sh idempotent + tag annoté sans GPG + dry-run ;
  updater : pip install de requirements.txt avant bascule)
- Release faite **avec release.sh réparé** (dogfooding, dry-run puis réel) ;
  `main`, `dev`, tag `v1.8.3` poussés (commits `df77884` + `a547666`)
- **E2E RÉUSSI sur les 4 Pi** : updater déclenché manuellement, chacun a tiré
  la 1.8.3 tout seul — « Health check OK : status=healthy version=1.8.3 »
  (la vérification de version livrée en 1.8.2 a fonctionné en réel)
- MQTT reconnecté partout après restart (rc=0)

### `DEPLOY` — L'updater ne se met pas à jour lui-même (découvert 2026-08-23)

`/opt/usg-watchdog/updater/` n'est réécrit que par `deploy.sh` ; les releases
de l'updater ne contiennent que `src/` + `VERSION`. Le fix pip-install (1.8.3)
serait resté inactif sans intervention. Contourné : copie manuelle depuis les
clones git sur les 4 Pi. Dette réelle → PRD renommage ou 1.8.4.

### État suivant (2026-08-23) — plan global repris

Ordre validé par audit : ~~1.8.3~~ (fait) → **grand renommage Vigil (2.0.0,
PRD en relecture : docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil.md,
5 questions ouvertes posées à l'utilisateur)** → A1 TP-Link (1.9.0... numéro à
revoir si 2.0.0 passe avant) → A2 exposition HA. Avant A1 : re-tagger
`build-candidate/a1` et `a2` (pointent sur 54a4dcc, antérieur à tout 1.8.x).

## Ship Pipeline State — 1.8.2 (2026-08-23)

- **Version** : 1.8.2 (unit systemd → `current/src`, deploy.sh → layout releases,
  updater vérifie la version de `/health`, identité MQTT `vigil`)
- `main`, `dev`, tag annoté `v1.8.2` : poussés (commits `7634444` + `1eeba8c`)
- **FLOTTE COMPLÈTE DÉPLOYÉE (2026-08-23)** — les 4 Pi vérifiés en 1.8.2,
  healthy, layouts à plat sauvegardés en `src.flat-backup` :
  | Pi | Rôle | Login SSH |
  |---|---|---|
  | bbh-network (local) | dijon-master | — |
  | bbh-dij-guardian | dijon-slave | dietpi |
  | bbh-nce-guardian | nice-slave | dietpi |
  | penelope | nice-master | pi |
- Accès flotte : clé dédiée `~/.ssh/id_ed25519_fleet` + entrées `~/.ssh/config`
  (guardians = user `dietpi`, penelope = user `pi`), sudo NOPASSWD partout,
  repos clonés dans `~/github/usg-watchdog` sur chaque Pi
- Piège rencontré : une commande SSH avec `cd` en tête a été réécrite (hook rtk)
  et le `cd` perdu → utiliser `git -C` / variables plutôt qu'un `cd` initial
- **MQTT ACTIVÉ sur les 4 (2026-08-23)** : brokers 192.168.1.51 (HA Dijon) /
  192.168.3.51 (HA Nice), user `vigil`, INSTANCE_ID et prefixes
  `vigil/<site>-<role>` posés, les 4 loggent « MQTT connecte (rc=0) » +
  « discovery envoye »
- **Restant côté utilisateur** : purge des entités HA `usg_watchdog*`
  orphelines dans les 2 HA ; vérifier les ACL Mosquitto (écriture `vigil/#`
  ET `homeassistant/#`)

### `DEPENDENCY` — paho-mqtt absent de requirements.txt (découvert au déploiement)

MQTT ne démarrait sur aucun Pi : `paho-mqtt` n'a jamais été dans
`requirements.txt` (seul paramiko y figure), et `mqtt_publisher.py` dégrade en
silence (warning + désactivation). Corrigé : pip install sur les 4 venvs +
ajout au requirements.txt. **Épinglé `paho-mqtt==1.6.1`** : le code utilise
l'API de callbacks v1 (`Client(client_id=...)`, `on_connect` à 4 arguments),
paho-mqtt 2.x exige `CallbackAPIVersion` et casse la signature.

**Leçon** : un module optionnel qui dégrade en silence (try/except ImportError)
doit être vérifié dans les journaux après activation — le service reste
healthy alors que la fonctionnalité est morte.

## Ship Pipeline State — 1.8.1 (archivé)

- **Date** : 2026-08-21
- **Version** : 1.8.1
- **Phase atteinte** : **LIVRÉ** — `main`, `dev` et le tag `v1.8.1` poussés.
  **Post-mortem** : jamais exécutée en production (unit systemd sur layout à
  plat, cf. tâche 1.8.2) — corrigé par la 1.8.2.

| Étape | État |
|---|---|
| Gate local (`validate.sh`) | OK — 831 tests, coverage 92 % |
| Commits sur `main` | OK — `f561246`, `472aabd`, `0acefe1`, `18e0b12` |
| Tag `v1.8.1` (annoté) | OK — objet `6297504` → commit `0acefe1` |
| `dev` resynchronisé | OK — fast-forward vers `0acefe1` |
| `git push origin main` | OK — `54a4dcc..18e0b12` |
| `git push origin v1.8.1` | OK — nouveau tag |
| `git push origin dev` | OK — `82b0b4f..0acefe1` |
| Visible par l'updater | OK — l'API GitHub `/tags` liste `v1.8.1` en tête |
| Déploiement production | **EN COURS** — les 4 Pi tirent la version à leur prochain cycle d'updater |

### `ENV` — Authentification GitHub cassée (bloquant, résolu)

Le push a d'abord échoué : token `gh` expiré (HTTP 401) **et** aucun credential
helper git configuré. Les deux à la fois — d'où le diagnostic trompeur : même
après `gh auth login`, `git push` échouait encore, parce que git n'avait aucun
moyen de demander le token à `gh`.

**Résolution** : `gh auth login --web` **puis `gh auth setup-git`**. Le second est
indispensable et facile à oublier : il écrit
`credential.https://github.com.helper=!/usr/bin/gh auth git-credential`.

**Leçon** : « `gh` est authentifié » ne veut pas dire « git peut pousser ».
Vérifier les deux séparément :
```bash
gh auth status
git config --get-all credential.https://github.com.helper
```
Piège annexe : `git config --get-all <clé>` sort en **code 1** quand la clé
n'existe pas — dans un `&&`/pipeline ça se lit comme un échec de la commande
précédente. C'est ce qui a fait croire à tort que `gh auth setup-git` avait
échoué.

### `CONFIG` — `scripts/release.sh` inutilisable en l'état

Deux pièges relevés, non corrigés (hors périmètre du patch) :

1. **Double bump** : `release.sh` écrit et committe `VERSION` lui-même
   (`:72-75`). Si `VERSION` a déjà été bumpé à la main, `release.sh patch`
   produit `1.8.2`. Passer la version explicite ne sauve pas : le `git commit`
   n'aurait rien à committer et le script sort en erreur (`set -e`).
   → Laisser `release.sh` faire le bump, ne jamais toucher `VERSION` avant.
2. **`git tag -s` sans clé GPG** : aucune clé secrète n'existe sur cette
   machine, le script échouerait *après* avoir committé le bump. Les tags
   existants sont d'ailleurs hétérogènes (`v1.7.6` annoté, `v1.8.0` léger).
   → Tag créé ici manuellement en annoté (`git tag -a`), cohérent avec `v1.7.6`.

## Contexte projet utile

- `src/` est sur `sys.path` : les modules s'importent à plat
  (`from config import ...`), jamais `from src.config import ...`.
- Les constantes de `config.py` sont importées **par valeur** au chargement du
  module (`from config import MQTT_BROKER`). Conséquence pour les tests :
  patcher `config.X` n'a aucun effet, il faut patcher `mqtt_publisher.X`.
- Corollaire de design : tout défaut d'argument qui doit rester patchable doit
  être résolu **dans le corps de la fonction** (`if x is None: x = GLOBAL`) et
  non dans la signature — sinon la valeur est figée à la définition du module.
- Commentaires et logs en français, **ASCII pur** (`config.py` écrit
  « surchargees », « Priorite »). Pas d'emojis dans les logs.
- Gate qualité : `./scripts/validate.sh` (syntaxe + imports + pytest + coverage ≥ 80 %).

## Erreurs rencontrées

### `LOGIC` — Bloc dupliqué introduit par l'agent d'implémentation (2026-08-21)

`_normalize_instance_id()` + le bloc `INSTANCE_ID` ont été insérés **deux fois**
dans `src/config.py` : une fois après `_get_int_env` (l.46-74), une fois avant la
section MQTT (l.304+). La seconde définition masquait la première — comportement
correct, mais code mort et diff trompeur. Détecté à la relecture du `git diff`,
pas par les tests (les deux copies étant identiques, aucun test ne pouvait échouer).

**Correctif** : suppression de la première copie.

**Leçon** : une suite verte ne détecte pas une définition dupliquée à l'identique.
Relire le `git diff` complet avant de valider, même quand tous les tests passent.

### `CONFIG` — `scripts/validate.sh` pointait sur le mauvais venv (pré-existant)

`validate.sh:27` cherchait `${REPO_DIR}/.venv/bin/python` alors que le projet
(et `deploy.sh`) crée `venv/`. Le fallback `python3` système n'a pas `pytest`
→ la section tests échouait systématiquement hors venv activé manuellement.
Le gate qualité du projet était donc rouge pour une raison purement de chemin.

**Correctif** : boucle sur `venv/` puis `.venv/`, fallback `python3`.

**Leçon** : quand un gate qualité échoue « pour raison d'environnement »,
vérifier d'abord qu'il ne s'agit pas d'un bug du gate lui-même.

## Règles pour la prochaine itération

1. **Toujours relire `git diff` en entier** avant de déclarer une tâche finie —
   les tests ne voient ni le code mort, ni les définitions dupliquées, ni le
   bruit de reformatage.
2. Un hook de formatage repasse **tout le fichier** en style black dès qu'on
   l'édite. Sur un patch, cela gonfle le diff de lignes sans rapport. Prévoir ce
   bruit et le signaler dans le rapport plutôt que d'essayer de le défaire
   (il revient à la prochaine édition).
3. Les tests qui rechargent `config` via `importlib.reload` peuvent
   désynchroniser `config.X` de `mqtt_publisher.X` (import par valeur) pour le
   reste de la session pytest — isoler ces tests ou restaurer l'état après.
4. **Un test sur mock ne prouve pas une contrainte de protocole.** Le premier
   test « deux instances ne s'évincent pas » n'assertait que deux chaînes
   différentes passées à un `MagicMock` — il aurait passé même avec le bug.
   Pour une règle côté serveur (ici : une connexion par `client_id`), écrire un
   **faux broker qui applique la règle**, plus un **contrôle négatif** qui
   échoue quand le bug est présent. Sans le contrôle négatif, le test positif
   n'est pas crédible.
5. `patch()` n'est **pas thread-safe** : deux threads avec leur propre bloc
   `with patch(...)` sur le même attribut de module se marchent dessus au
   `__exit__` (l'un restaure pendant que l'autre lit). Patcher une seule fois
   dans le thread principal, et ne varier par thread que le strict nécessaire.

## Vérifications outillées réutilisables

- **Distinguer reformatage et vrai changement** : comparer les AST plutôt que le
  texte. `ast.dump(ast.parse(git show HEAD:f)) == ast.dump(ast.parse(open(f)))`
  → 53 fichiers prouvés « pur formatage », 3 fichiers réellement modifiés. Permet
  de rendre un patch atomique en revertant le bruit sans relire les diffs à la main.
- **Preuve d'exécution hors suite de tests** : un petit script qui lance le vrai
  code dans deux sous-processus avec des env différents (`INSTANCE_ID=...`) et
  vérifie l'intersection des identités. Indépendant des mocks — c'est ce qui
  prouve le correctif, pas la suite verte.
