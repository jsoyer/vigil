# Workflow de développement — Vigil v2.0.0

Guide pour les non-développeurs qui demandent des changements ou des features.

## Comment ça marche

Tu communiques tes besoins en langage naturel. Claude analyse, développe, teste, valide et déploie. Aucune commande git à faire.

### Le cycle

1. **Tu demandes** : "Le watchdog plante quand le peer est offline"
2. **Claude crée une issue GitHub** automatiquement pour la traçabilité
3. **Claude développe et teste**
4. **Claude commit** avec référence à l'issue
5. **L'issue se ferme automatiquement** lors du push

Tu peux voir tout l'historique sur : https://github.com/jsoyer/vigil/issues

---

## Les 3 types de demandes

### 1. Bug fix

Exemple : "Le watchdog plante quand le peer est injoignable"

**Ce que Claude fait** :

1. Crée une issue GitHub avec label `bug`
2. Analyse le bug, écrit un test reproduisant le problème
3. Corrige le code
4. Valide (tests + couverture + imports)
5. Commit sur `main` avec `fix: ... (closes #N)`
6. Crée un tag patch (ex: `v1.0.1`)
7. Push sur GitHub → l'issue se ferme automatiquement
8. Auto-updater télécharge et déploie la version corrigée automatiquement à 3h

**Délai** : Immédiat. Droit en production.

---

### 2. Nouvelle feature

Exemple : "Ajoute le support des notifications par email"

**Ce que Claude fait** :

1. Crée une issue GitHub avec label `feature`
2. Développe sur la branche `dev`
3. Écrit les tests, vérifie la couverture (80%+)
4. Valide le code
5. Crée une Pull Request sur GitHub (dev → main, liée à l'issue)
6. Te dit : "Feature prête, PR ici : [lien], issue #N. Tu veux que je merge ?"

**Tu réponds** : "Go" / "Merge" / "OK"

**Claude fait** :

1. Merge la PR → l'issue se ferme automatiquement
2. Crée un tag minor (ex: `v1.1.0`)
3. Push sur GitHub
4. Synchronise dev avec main
5. Auto-updater la déploie à 3h

**Délai** : Une PR pour que tu puisses valider avant production.

---

### 3. Correctif de sécurité (CVE)

Exemple : "paramiko a une CVE critique, met à jour"

**Ce que Claude fait** :

1. Crée une issue GitHub avec label `security`
2. Met à jour la dépendance
3. Vérifie qu'il n'y a pas de breaking change
4. Lance les tests
5. Commit sur `main` avec `security: ... (closes #N)`
6. Crée un tag patch
7. Push immédiatement → l'issue se ferme automatiquement
8. Auto-updater la déploie au prochain cycle (3h)

**Délai** : Immédiat. Droit en production.

---

## Tester une feature avant production

Exemple : "Pousse un build dev pour que je teste sur mon Pi secondaire"

Claude crée un tag dev (ex: `v1.1.0-dev.1`) et te dit comment l'installer :

```bash
# Sur le Pi secondaire, modifier .env
echo "UPDATE_CHANNEL=dev" >> /opt/vigil/.env

# Forcer la mise à jour
sudo systemctl start vigil-updater

# Logs
sudo journalctl -u vigil-updater -f
```

Après test, tu dis "OK pour merger" et c'est promu en production.

---

## Comment les mises à jour arrivent sur ta Pi

1. **Timer systemd** : `vigil-updater` se déclenche à **3h du matin**
2. **Check GitHub** : Vérifie s'il y a un nouveau tag `vX.Y.Z`
3. **Si trouvé** :
   - Télécharge la version
   - Valide (syntaxe + imports)
   - Applique atomiquement
   - Redémarre le watchdog
   - Fait un health check
   - **Si health check échoue** : Rollback automatique vers version précédente
   - **Si succès** : Notification "Mise à jour OK v1.0.0 → v1.0.1"

**Forcer une mise à jour immédiate** :

```bash
sudo systemctl start vigil-updater
```

**Vérifier la version** :

```bash
curl http://localhost:9000/health | python3 -m json.tool | grep version
```

---

## Schema des branches

```
main (production)
  |
  +-- v1.0.0  (tag)
  +-- v1.0.1  (hotfix, patch)
  |
  +-- dev (features en cours)
       |
       +-- PR "email notifications" → merge → v1.1.0
       +-- PR "SNMP support" → merge → v1.2.0
```

---

## Versioning

| Type | Bump | Exemple |
|------|------|---------|
| Bug fix | Patch | 1.0.0 → 1.0.1 |
| CVE | Patch | 1.0.1 → 1.0.2 |
| Nouvelle feature | Minor | 1.0.2 → 1.1.0 |
| Breaking change | Major | 1.1.0 → 2.0.0 |

---

## Qualité avant chaque push

Claude vérifie automatiquement :
- Tests complets (pytest)
- Couverture >= 80%
- Validation syntaxe Python
- Scan de secrets (aucun token en clair)
- Vérification des imports

Si un check échoue, le push est bloqué jusqu'à correction.

---

## Tester les notifications et confirmations

Une fois le watchdog déployé, tu peux le contrôler via le dashboard web
(`http://<pi>:9000/dashboard`) ou l'API :

```bash
# Publier un test Ntfy (vérifie l'abonnement téléphone)
curl -H "Authorization: Bearer $NTFY_TOKEN" -d "test" "$NTFY_URL/$NTFY_TOPIC"
```

Pour les actions destructives (ex. reboot TP-Link), une notification Ntfy
avec boutons « Confirmer »/« Annuler » arrive sur le téléphone -- appuyer
dessus suffit, aucune commande à taper.

---

## Commandes API pour tests

```bash
# Statut
curl http://localhost:9000/health

# Pause (pas de reboot pendant 30 min)
curl -X POST -H "Authorization: Bearer TOKEN" \
  http://localhost:9000/api/pause

# Reprendre
curl -X POST -H "Authorization: Bearer TOKEN" \
  http://localhost:9000/api/resume

# Forcer reboot
curl -X POST -H "Authorization: Bearer TOKEN" \
  http://localhost:9000/api/reboot

# Voir les événements
curl http://localhost:9000/api/events

# Voir SLA du mois
curl http://localhost:9000/api/sla | python3 -m json.tool
```

---

## Cas d'usage courant

### "Le watchdog plante en production, fixe ça aujourd'hui"

Claude :
1. Pause le service : `curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/pause`
2. Analyse le bug
3. Écrit un test
4. Corrige
5. Commit + tag patch
6. Push
7. Auto-updater la déploie à 3h (ou tu peux forcer manuellement)
8. Resume : `curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:9000/api/resume`

---

### "Ajoute le support pour un nouveau canal de notification"

Claude :
1. Crée feature branch `dev`
2. Ajoute `src/notifier/_nouveau_canal.py`
3. Update `src/notifier/_dispatch.py`
4. Ajoute config vars
5. Écrit tests
6. Crée PR
7. Te dit "PR prête, OK ?"
8. Tu dis "OK"
9. Merge → déploiement à 3h

---

### "Je veux tester une nouvelle feature avant de l'activer en production"

Claude :
1. Pousse un tag dev : `v1.1.0-dev.1`
2. Te dit comment installer avec `UPDATE_CHANNEL=dev`
3. Tu testes sur ton Pi secondaire
4. Tu dis "OK, c'est bon"
5. Claude merge vers main
6. `v1.1.0` est en production à 3h

---

## Tracabilité GitHub

Chaque changement laisse une trace sur GitHub :

1. **Issues** : Une issue par bug/feature/CVE (traçabilité)
2. **PRs** : Une PR par feature complexe (revue avant merge)
3. **Commits** : Messages explicites avec numéro issue (ferme auto)
4. **Tags** : Versions sémantiques (vX.Y.Z)

Exemple :
```bash
# Commit qui fixe le bug #42
git commit -m "fix: handle unreachable peer (closes #42)"

# Au push : issue #42 se ferme automatiquement
```

---

## FAQ

**Q: Combien de temps pour une feature ?**

A: Ça dépend. Bug simple ? Quelques heures. Feature complexe ? 1-2 jours + PR pour validation.

---

**Q: Est-ce que les mises à jour vont casser mon setup ?**

A: Non. Auto-updater valide avant de déployer. Si health check échoue, rollback auto vers version précédente.

---

**Q: Je peux tester une feature avant production ?**

A: Oui ! Claude peut créer un tag dev (`v1.1.0-dev.1`) pour tester sur une machine secondaire.

---

**Q: Comment je désactive une feature ?**

A: Via variables d'environnement. Ex: Si tu configures pas `CLOUDFLARE_API_TOKEN`, DDNS Cloudflare est désactivé.

---

**Q: Qu'est-ce qui se passe si l'auto-updater échoue ?**

A: Health check détecte le problème et rollback automatique vers version stable précédente. Notification envoyée.

---

**Q: Je peux utiliser une ancienne version ?**

A: Oui, mais pas recommandé sauf pour debug. Les versions anciennes peuvent avoir des bugs corrigés.

---

**Q: Comment je reporte un bug ?**

A: En décrivant le problème naturellement. Claude crée une issue, la reproduit, la fixe, et la ferme.

---

**Q: Est-ce qu'il y a une documentation ?**

A: Oui :
- **README.md** : Documentation complète (features, config, commandes)
- **CLAUDE.md** : Architecture (pour développeurs)
- **DEPLOY.md** : Installation + migration
- **WORKFLOW.md** : Ce fichier (pour toi)

---

## Contact et support

Aucune commande git requise. Juste parle naturellement :

- "Le watchdog ne démarre pas"
- "Ajoute un topic Ntfy supplémentaire"
- "Pourquoi mes notifications Ntfy ne marchent pas ?"
- "Je veux un rapport SLA mensuel"

Claude gère tout, crée les issues, développe, teste et déploie.

---

**Dernière mise à jour** : 2026-03-31 (v1.7.0)
