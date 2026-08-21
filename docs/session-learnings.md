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
