# Bugfix — Identité MQTT/Home Assistant partagée entre les instances

- **Catégorie** : bugfix
- **Date** : 2026-08-20
- **Version cible** : 1.8.1 (patch)
- **Branche** : `main` direct, sans PR (routing projet pour les bugs, cf. `CLAUDE.md`)
- **Découvert pendant** : planification du support TP-Link (2026-08-20)
- **Bloque** : PRD A2 (intégration Home Assistant) — à livrer **avant**

---

## Le bug

`src/mqtt_publisher.py` code en dur l'identité du device Home Assistant et celle
de chaque entité :

| Ligne | Valeur en dur |
|---|---|
| `:29-34` | `identifiers: ["usg_watchdog"]`, `name: "USG Watchdog"`, `model`, `manufacturer` |
| `:51` | `unique_id: f"usg_watchdog_{sensor_id}"` |
| `:59` | topic de discovery `homeassistant/sensor/usg_watchdog/{sensor_id}/config` |

Le projet supporte pourtant explicitement le multi-instance (`INSTANCE_PRIORITY`,
`PEER_IP` — `config.py:321,324`). En production, **4 instances** tournent :
Dijon (master + slave) et Nice (master + slave).

**Conséquence** : les quatre instances publient sous la même identité. Elles
écrasent mutuellement le même device HA et les mêmes 8 entités. Home Assistant
affiche donc un seul « USG Watchdog » dont les valeurs alternent entre quatre
sources, sans qu'aucun élément d'interface n'indique laquelle est affichée.

C'est un bug **existant et indépendant** du chantier TP-Link. Il est traité à
part pour ne pas mélanger un correctif de production avec une nouveauté, et
parce que le PRD A2 ajoutera des entités par équipement — ce qui aggraverait la
collision si l'identité n'est pas corrigée d'abord.

## Cause racine

L'identité MQTT a été conçue pour un déploiement mono-instance. Aucune notion
d'instance n'a été introduite lors de l'ajout de la coordination HA (`peer.py`).

## Correctif

1. **Identifiant d'instance dans `src/config.py`**
   - Nouvelle option, avec un **défaut dérivé du hostname** : un déploiement qui
     ne configure rien obtient malgré tout une identité distincte. Corriger le
     bug ne doit pas exiger d'action manuelle sur les 4 instances.
   - Normalisation : minuscules, caractères non alphanumériques → `_` (contrainte
     des `unique_id` et des topics MQTT).
2. **`src/mqtt_publisher.py`**
   - `:29-34` — `identifiers` et `name` dérivés de l'identifiant d'instance.
   - `:51` — `unique_id` préfixé de même.
   - `:59` — topic de discovery idem ; sortir `homeassistant/` dans une constante
     de module (préparation d'une éventuelle option `MQTT_DISCOVERY_PREFIX`, non
     ajoutée ici — hors périmètre d'un patch).
3. **`MQTT_CLIENT_ID` par instance — second volet du même bug.** L'identifiant
   client MQTT est lui aussi en dur (`mqtt_publisher.py:88`). Or un broker
   n'accepte **qu'une connexion par `client_id`** : quatre instances partageant
   le même identifiant se déconnectent mutuellement en boucle, chacune évinçant
   la précédente. Le symptôme — des entités qui se figent et repartent sans
   raison — se confond avec celui de la collision d'entités, ce qui l'a rendu
   invisible jusqu'ici.
   Dériver le `client_id` du même identifiant d'instance : c'est la même famille
   de défaut, dans le même fichier, et le corriger séparément demanderait un
   second patch pour un gain nul.
4. **Cohérence** : ajouter `is_configured()` à `mqtt_publisher`, aligné sur
   `telegram_bot.is_configured()` (`telegram_bot.py:18-19`),
   `ddns_cloudflare.is_configured()` (`:38`) et `backup_unifi.is_configured()`.
   Incohérence relevée pendant l'analyse ; correctif trivial et au même endroit.

## Ce que ce patch ne fait PAS, volontairement

**Il ne crée pas de device `USG <site>` unique.** Décidé le 2026-08-21 (C15 du
PRD A2) : les capteurs de ligne (`gateway`, `internet`, RTT) doivent à terme
vivre sur un device unique par site, et non être dupliqués par instance.

Ce serait tentant de le faire ici — le patch recrée déjà les entités, ce serait
« gratuit ». **Mais des entités par site sans publieur unique feraient écrire les
deux instances dedans**, c'est-à-dire exactement le bug qu'on corrige, déplacé.
L'élection du publieur (C12) n'arrive qu'au Sprint 1 d'A2.

Conséquence assumée : les 4 capteurs de ligne seront recréés **une seconde fois**
en A2. L'alternative — faire entrer une élection de publieur dans un patch —
violerait la séparation bug/feature du projet pour un gain cosmétique.

Ce patch se limite donc à donner **une identité distincte à chaque instance**.

## Hors périmètre (loggé, non traité)

Relevés pendant l'analyse, à traiter ailleurs — ce sont des **améliorations**,
pas des bugs, et un patch ne doit pas les embarquer :

- absence de `device_class` / `state_class` sur les 8 capteurs (pas de
  statistiques long terme côté HA) ;
- états publiés **sans `retain`** (`:149-172`) → entités `unknown` après un
  redémarrage de HA, jusqu'au cycle suivant ;
- pas d'`availability_topic` / LWT ;
- topic `{prefix}/state` (`:172`) qui publie déjà l'état complet sans être
  déclaré en discovery ;
*(`MQTT_CLIENT_ID` figurait ici comme « à vérifier » ; il est **entré dans le
périmètre** — voir le point 3 ci-dessus.)*

### ⚠️ Prérequis de déploiement relevé pendant l'implémentation (2026-08-21)

`MQTT_TOPIC_PREFIX` reste une **valeur unique partagée** (`config.py:320`,
défaut `usg-watchdog`). Les *state topics* (`{prefix}/score`, `{prefix}/gateway`,
…) ne sont donc **pas** couverts par ce patch : ils sont dérivés du préfixe, pas
de l'`INSTANCE_ID`.

Conséquence concrète : après ce patch, les 4 instances ont bien des devices, des
`unique_id`, des topics de discovery et des `client_id` **disjoints** — plus
d'écrasement d'entités, plus d'éviction sur le broker. Mais si les 4 gardent le
préfixe par défaut, leurs 8 entités pointent toutes vers **les mêmes** state
topics : Home Assistant affichera 4 devices distincts affichant des valeurs
**identiques** (dernier publieur gagnant).

**Il faut donc définir `MQTT_TOPIC_PREFIX` par instance au déploiement**
(ex : `usg-watchdog/dijon-master`), sinon le correctif est incomplet en pratique.

Non traité ici volontairement : changer le défaut de `MQTT_TOPIC_PREFIX` (par
exemple le dériver d'`INSTANCE_ID`) déplacerait les topics de tous les
déploiements existants, y compris mono-instance, et casserait les automatisations
et dashboards HA qui les référencent. C'est une décision de rupture, pas un
patch — à trancher séparément.

## Tests

`tests/test_mqtt_publisher.py` (la suite existante est déjà exhaustive) :

- deux instances simulées avec des identifiants différents → `identifiers`,
  `unique_id` et topics de discovery **disjoints** ;
- aucune configuration d'identifiant → défaut dérivé du hostname, non vide,
  normalisé ;
- caractères spéciaux dans le hostname → normalisation correcte ;
- non-régression : la structure du payload de discovery est inchangée par
  ailleurs (seules les valeurs d'identité bougent).

## Note de migration — OBLIGATOIRE dans les notes de version

Changer les `unique_id` fait que **Home Assistant recrée les entités**. Les
anciennes deviennent orphelines et doivent être supprimées à la main. Les
historiques rattachés aux anciennes entités ne suivent pas.

C'est un coût unique et assumé : il n'existe pas de moyen de renommer un
`unique_id` sans que HA considère qu'il s'agit d'une nouvelle entité. Le
signaler explicitement — le découvrir après coup serait bien pire.

## Rollback — une étape irréversible

Le revert du code restaure le comportement, **mais ne défait pas la recréation
des entités Home Assistant**. Les anciennes restent orphelines et leur
historique est perdu quoi qu'il arrive.

C'est la seule étape irréversible de toute la séquence, et elle arrive en
premier. En conséquence : livrer ce patch quand on est décidé à aller au bout,
pas « pour voir ».

## Critères d'acceptation

- [x] Deux instances publient des identités MQTT disjointes (test)
- [x] Sans configuration, l'identifiant est dérivé du hostname et normalisé
- [x] `mqtt_publisher.is_configured()` existe, aligné sur les autres modules
- [x] Suite `tests/test_mqtt_publisher.py` verte, coverage ≥ 80 %
- [x] `./scripts/validate.sh` vert
- [x] Note de migration rédigée dans les notes de version
- [x] `MQTT_CLIENT_ID` dérivé de l'identifiant d'instance ; deux instances
      simulées se connectent **simultanément** sans s'évincer
- [x] `VERSION` = 1.8.1, taggée, `dev` resynchronisé

## Issues

- **Résolu (2026-08-21)** — livré : `VERSION` = 1.8.1, tag annoté `v1.8.1`
  (`0acefe1`), `main` et `dev` poussés. Tous les critères sont satisfaits.
- Le tag a été créé **manuellement** et non via `./scripts/release.sh` :
  le script committe `VERSION` lui-même (double bump si le fichier est déjà
  à jour) et utilise `git tag -s` alors qu'aucune clé GPG n'existe sur la
  machine — il aurait échoué *après* avoir committé le bump. Tag annoté,
  cohérent avec `v1.7.6`. À corriger séparément.
- `dev` a été **mergé** (fast-forward) plutôt que cherry-pické : `dev` était
  en retard du commit de docs, le cherry-pick conflictait sur ce fichier de
  tâche inexistant sur `dev`.
