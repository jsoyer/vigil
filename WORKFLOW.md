# Workflow de developpement -- USG Watchdog

## Comment ca marche

Tu parles a Claude en langage naturel. Claude developpe, teste, et deploie. Tu n'as jamais besoin de taper de commandes git.

## Tracabilite avec GitHub Issues

Chaque changement est trace dans une issue GitHub. Tu n'as rien a faire -- Claude cree et ferme les issues automatiquement.

**Exemple :**
> Toi : "Le watchdog plante quand le peer est offline"
>
> Claude :
> 1. Cree issue GitHub #4 "fix: crash quand peer offline"
> 2. Fixe le bug
> 3. Commit avec "fix: handle unreachable peer (closes #4)"
> 4. L'issue #4 se ferme automatiquement

Tu peux voir l'historique complet sur https://github.com/jsoyer/usg-watchdog/issues

## Les 3 types de demandes

### 1. Bug fix

> "Le watchdog crashe quand le peer est configure mais injoignable"

**Ce que Claude fait :**
1. Cree une issue GitHub avec le label `bug`
2. Analyse le bug, ecrit un test qui le reproduit
3. Corrige le code
4. Lance les tests + validation
5. Commit sur `main` avec `fix: ... (closes #N)`
6. Cree un tag patch (ex: `v1.0.1`)
7. Push sur GitHub -- l'issue se ferme automatiquement
8. Te dit : "Corrige, tague v1.0.1, issue #N fermee. Ta Pi se met a jour a 3h."

**Delai :** Immediat. Droit en production.

### 2. Nouvelle feature

> "Ajoute le support des notifications par email"

**Ce que Claude fait :**
1. Cree une issue GitHub avec le label `feature`
2. Developpe sur la branche `dev`
3. Ecrit les tests, verifie la couverture
4. Cree une Pull Request sur GitHub (dev -> main, liee a l'issue)
5. Te dit : "Feature prete, PR ici : [lien], issue #N. Tu veux que je merge ?"

**Tu reponds :** "Go" / "Merge" / "OK"

**Claude :**
1. Merge la PR -- l'issue se ferme automatiquement
2. Cree un tag minor (ex: `v1.1.0`)
3. Push sur GitHub
4. Synchronise dev avec main
5. Te dit : "Deploye, v1.1.0, issue #N fermee. MAJ automatique a 3h."

**Delai :** Passe par une PR pour que tu puisses valider.

### 3. Correctif de securite (CVE)

> "paramiko a une CVE critique"

**Ce que Claude fait :**
1. Cree une issue GitHub avec le label `security`
2. Met a jour la dependance
3. Verifie qu'il n'y a pas de breaking change
4. Lance les tests
5. Commit sur `main` avec `security: ... (closes #N)`
6. Cree un tag patch
7. Push immediatement -- l'issue se ferme automatiquement
8. Te dit : "Corrige, v1.0.2, issue #N fermee. Pour MAJ immediate : `sudo systemctl start usg-watchdog-updater`"

**Delai :** Immediat. Droit en production.

## Tester une feature avant la prod

> "Pousse un build dev pour que je teste sur mon Pi secondaire"

Claude cree un tag dev (ex: `v1.1.0-dev.1`) et te dit comment l'installer sur ton Pi avec `UPDATE_CHANNEL=dev`.

## Comment les mises a jour arrivent sur les Pi

1. Le timer systemd `usg-watchdog-updater` se declenche a **3h du matin**
2. Il verifie sur GitHub s'il y a un nouveau tag
3. Si oui : telecharge, valide (syntaxe + imports), applique, redemarre, health check
4. Si le health check echoue : **rollback automatique** vers la version precedente
5. Si tout va bien : notification "Mise a jour reussie v1.0.0 -> v1.0.1"

### Forcer une mise a jour immediate

```bash
sudo systemctl start usg-watchdog-updater
```

### Verifier la version en cours

```bash
curl http://localhost:9000/health | python3 -m json.tool
```

## Schema des branches

```
main (production)
  |
  +-- v1.0.0  (tag)
  +-- v1.0.1  (hotfix, directement sur main)
  |
  +-- dev (features en cours)
       |
       +-- PR "email notifications" --> merge dans main --> v1.1.0
```

## Versioning

| Type de changement | Bump | Exemple |
|---|---|---|
| Bug fix | Patch | 1.0.0 -> 1.0.1 |
| Securite/CVE | Patch | 1.0.1 -> 1.0.2 |
| Nouvelle feature | Minor | 1.0.2 -> 1.1.0 |
| Breaking change | Major | 1.1.0 -> 2.0.0 |

## Qualite

Avant chaque push, Claude lance automatiquement :
- Tests complets (pytest)
- Couverture >= 86%
- Validation syntaxe
- Scan de secrets
- Verification des imports

Si un check echoue, le push est bloque jusqu'a correction.
