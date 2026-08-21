# PRD A2 — Exposition des secours TP-Link & intégration Home Assistant

- **Catégorie** : feature
- **Date** : 2026-08-20
- **Auteur** : Jerome Soyer
- **ADR** : [docs/adr/0001-multi-vendor-router-monitoring.md](../../../../adr/0001-multi-vendor-router-monitoring.md)
- **Version cible** : 1.10.0 (minor)
- **Branche** : `dev` → PR → `main`
- **Dépend de** : [A1 — Pilotage](../2026-08-20_1618-a1-pilotage-tplink/spec.md) livré (1.9.0)
- **Pré-requis BLOQUANT** : bugfix [1.8.1 identité MQTT](../../bugfix/2026-08-20_1618-mqtt-instance-identity.md)
- **Suite** : PRD B — moteur multi-cible (~1.11.0)

---

## 1. Problème & objectif

A1 a rendu les MR110 **pilotables** : joignables via le pont Pi Zero, avec des
commandes API et Telegram. Mais il faut taper une commande pour savoir quoi que
ce soit. Rien n'est visible passivement, rien n'est historisé, et rien ne
remonte dans Home Assistant où le reste de l'infrastructure est déjà supervisée.

**Objectif d'A2** : rendre l'état des secours **visible sans action**, et
**actionnable depuis Home Assistant**.

Trois informations que A1 ne fournit pas et qui ne se déduisent pas d'une lecture
isolée :

- la **conso data sur le cycle de facturation** (un forfait épuisé rend le
  secours inutile, et le compteur du routeur se remet à zéro tout seul) ;
- le fait que le secours soit **en train de servir** ;
- l'**historique** du signal et de la readiness, pour distinguer une dégradation
  progressive d'un incident ponctuel.

**Non-objectif** : toujours pas de reboot automatique. A2 ajoute un chemin de
commande depuis Home Assistant, il ne change pas la règle.

## 2. Pré-requis bloquant : l'identité MQTT

`src/mqtt_publisher.py` code en dur `identifiers: ["usg_watchdog"]` (`:29-34`) et
`unique_id: f"usg_watchdog_{sensor_id}"` (`:51`). **Les 4 instances de production
écrasent donc le même device Home Assistant et les mêmes entités.**

C'est un bug **existant**, indépendant des TP-Link, traité en **1.8.1 à part**.
A2 ne peut pas démarrer avant : ajouter des entités par équipement sur une
identité déjà en collision ne ferait qu'aggraver le problème et rendrait le
résultat intestable.

## 3. Correctness Discovery

- **Audience** : l'opérateur, depuis son dashboard Home Assistant — là où le
  reste de l'infrastructure est déjà supervisée. Décision pilotée : *« mes deux
  secours sont-ils prêts, et combien de forfait reste-t-il ? »*, sans ouvrir un
  terminal.
- **Vérification** : (a) chaque MR110 apparaît comme **un device HA distinct**,
  avec ses capteurs ; (b) le bouton de reboot **refuse** de s'exécuter sans
  l'entité *arm* ; (c) un compteur de data qui se remet à zéro n'est pas compté
  comme une conso négative ; (d) les métriques `usg_watchdog_*` existantes sont
  **inchangées**.
- **Failure definition** : un secours dégradé ou un forfait épuisé passe
  inaperçu ; OU un reboot part depuis HA sans garde-fou ; OU les dashboards
  Grafana existants cassent ; OU un échec de commande est invisible côté HA.
- **Danger definition** : **le `subscribe` MQTT ouvre un chemin de commande
  entrant vers une action destructive** — quiconque peut publier sur le broker
  peut déclencher un reboot. Ajouter un label à une métrique existante casse
  silencieusement des alertes. Rebooter un secours en service coupe le site.
- **Uncertainty policy** : champ absent ⇒ capteur non publié plutôt que publié à
  zéro (un zéro se confond avec une vraie valeur). Compteur incohérent ⇒ traité
  comme reset, jamais comme conso négative. Résultat d'action inconnu ⇒ dit comme
  tel dans l'entité de dernière action.
- **Risk tolerance** : zéro régression sur les métriques Grafana existantes et
  sur la surveillance USG. Métriques 4G best-effort.

## 4. Scope

### In scope
- **Quota data** : conso du cycle, %, jour de reset facturation, **détection de
  remise à zéro du compteur**, alerte au seuil.
- **Détection d'usage** du secours (H1) : inactif / en service / **saturé**.
- **Sonde périodique de bout en bout** (C11, **opt-in**) : alimente la readiness
  et déclenche le warning quand le lien cesse de porter du trafic.
- **Dashboard** : carte par équipement, badge readiness, **saut en panne**, bloc
  4G, bloc quota, bandeau d'usage.
- **Prometheus** : métriques labellisées par équipement, **C4 préservée**.
- **Home Assistant** : **un device par routeur** ; capteurs ; **chemin de commande
  entrant** (`subscribe` MQTT) ; bouton de reboot protégé par une entité *arm*.
- **C5 complète — élection du poller** entre master et slave d'un même site.
- **Mise à niveau des 8 capteurs USG existants** : `device_class`, `state_class`
  et `retain`, pour qu'ils bénéficient des mêmes statistiques long terme que les
  capteurs 4G.
- **Un seul device USG par site** : répartition des capteurs entre ce qui décrit
  **la ligne** et ce qui décrit **le watchdog qui l'observe**.
- **Métriques de la machine hôte** sur le device watchdog : température, disque,
  mémoire, charge.
- Notifications sur changement d'état (quota, usage).
- Docs + release 1.10.0.

### Out of scope
- Moteur multi-cible, `UsgDriver`, rôles dans le scoring, alerting automatique
  sur la readiness → **PRD B**. (L'exclusivité de polling, initialement prévue
  en PRD B, est **remontée dans A2** — voir C12.)
- Reboot automatique — exclu par décision.
- Les améliorations MQTT restantes, sans lien avec les TP-Link :
  `availability_topic` / LWT, et exposition du topic `{prefix}/state` déjà publié
  mais non déclaré en discovery. À traiter séparément.
  *(Le `device_class` / `state_class` / `retain` des 8 capteurs existants était
  initialement ici ; il est **remonté dans le périmètre** — décision du
  2026-08-21, voir C14.)*
- Câblage WAN2, redémarrage du Pi Zero par PoE, renommage → cf. A1 §9.

## 5. Contraintes

- **C4 — Métriques Prometheus legacy préservées (BLOQUANTE).** Les
  `usg_watchdog_*` restent émises **sans label**, à l'identique. Ajouter un label
  à une métrique existante casse silencieusement les requêtes Grafana et les
  règles d'alerte. Les métriques par équipement sont **ajoutées à côté**.
- **C1** — import paresseux de `tplinkrouterc6u` : toujours actif.
- **C12 — Un routeur = un device HA, et un seul poller par site.**

  A1 n'interrogeait les équipements **qu'à la demande** : une collision de
  session admin entre master et slave y était improbable. **A2 introduit du
  polling périodique** (quota, usage, sonde, capteurs HA) : deux instances
  interrogeant le même MR110 en continu se déconnecteraient mutuellement en
  boucle, un routeur MR n'acceptant qu'une session d'administration.
  **C5 complète est donc remontée de PRD B vers A2** — la contention était
  inévitable dès le polling périodique, indépendamment de Home Assistant.

  - **Élection du poller** : l'instance de plus haute priorité joignable
    interroge l'équipement ; l'autre lit l'état via `/api/state` du peer et
    l'expose **avec l'âge de la donnée**. Perte du peer → reprise après
    `PEER_TAKEOVER_DELAY`. Réutiliser la logique de priorité de `peer.py`, ne
    pas en écrire une seconde.
  - **Publication HA réservée au poller élu.** Le device Home Assistant est
    indexé sur **site + équipement**, jamais sur l'instance : un MR110 est un
    équipement physique unique, pas un par watchdog qui le regarde. Publier
    depuis les deux instances réintroduirait, sur le device d'équipement, la
    collision que le bugfix 1.8.1 corrige sur celui du watchdog.
  - **Split-brain** : si les deux instances se croient seules, elles pollent et
    publient toutes deux. Les valeurs concordent (même routeur), mais la
    contention de session revient. Traiter comme la divergence déjà gérée par
    `peer.py` : détecter et alerter, ne pas tenter de résoudre silencieusement.

- **C20 — Le cycle de facturation suit le calendrier, pas un compteur d'heures.**
  Bascule à minuit **heure locale** ; jour de reset supérieur à la longueur du
  mois ⇒ dernier jour ; calcul sur la **date calendaire** (un jour de changement
  d'heure fait 23 ou 25 h) ; et si le service était arrêté au moment de la
  bascule, le démarrage suivant **clôture le cycle** au lieu de le sauter. Motif :
  un compteur de conso faux ne lève aucune erreur — il affiche un chiffre
  plausible, et c'est précisément ce que ce PRD s'efforce de rendre détectable
  partout ailleurs.

- **C19 — Les lectures TP-Link restent authentifiées.** Les endpoints
  `/api/tplink/*` livrés en A1 exigent le jeton en GET comme en POST. A2 rend
  ces mêmes données visibles dans le dashboard : elles y sont rendues **côté
  serveur**, sans que le navigateur n'appelle l'endpoint authentifié — y placer
  le jeton l'exposerait à quiconque ouvre la page.

- **C18 — Le niveau de notification est choisi, pas subi.** Les nouveaux
  événements passent par `notify()` et sont diffusés à tous les canaux
  configurés (Telegram, Discord, Slack, **ntfy**, e-mail, Pushover, MQTT), chacun
  filtrant par son `*_MIN_LEVEL`. Aucun code par canal n'est à écrire — ntfy
  mappe déjà `INFO`/`WARNING`/`CRITICAL` vers ses priorités 3/4/5 et ses tags.
  En revanche, il n'existe que **trois** niveaux et `NTFY_MIN_LEVEL` vaut `INFO`
  par défaut : un événement mal noté part directement sur le téléphone, et un
  `CRITICAL` de complaisance apprend à ignorer les alertes. Le niveau de chaque
  événement est donc fixé explicitement (tableau au Sprint 1), avec une **escalade
  conditionnelle en `CRITICAL`** quand l'équipement concerné est en cours
  d'utilisation.

- **C17 — Métriques de l'hôte, lues sans dépendance.** Tous les watchdogs
  tournent sur des Raspberry Pi (Pi Zero et Pi 4), dans des placards à plusieurs
  centaines de kilomètres. Température (throttling), espace disque et usure de
  carte SD, mémoire et charge sont les causes de panne les plus banales — et
  aujourd'hui totalement invisibles.

  - Lecture depuis `/proc`, `/sys` et `os.statvfs` : **stdlib uniquement**,
    conforme à la ligne de dépendances du projet.
  - Publiées sur le device **watchdog** (par instance) : ce sont des métriques de
    machine, pas de ligne — même critère de répartition que C15.
  - **Un Pi Zero en mode `bridged` est un point de défaillance partagé** : il
    porte une instance watchdog *et* le pont vers le MR110. Sa santé conditionne
    la surveillance du secours, ce qui rend ces métriques plus utiles là
    qu'ailleurs.
  - Champ indisponible (zone thermique absente sur une plateforme non-Pi) →
    entité `unavailable`, jamais zéro. C13 s'applique.

- **C15 — Un seul device USG par site.** Symétrique de C12 : un équipement
  physique, un device. Les capteurs se répartissent selon ce qu'ils décrivent
  réellement — la **ligne** (`gateway`, `internet`, RTT), publiée sur un device
  `USG <site>` par **l'instance élue** ; le **watchdog** (`score`, `status`,
  `reboots_today`, `uptime`), qui reste par instance, parce que ce sont bien
  quatre watchdogs distincts et que leurs valeurs divergent légitimement.

  **Ce que la déduplication fait perdre, et comment on le compense.** Aujourd'hui,
  voir deux vues de la même ligne permet de repérer un désaccord entre master et
  slave. Sous C15, seule la vue de l'instance élue est publiée. `peer.py` détecte
  déjà cette divergence sans l'exposer : ajouter un `binary_sensor` *divergence*
  (`device_class: problem`) et un capteur *état du peer* sur le device watchdog
  restitue le signal, en mieux — un désaccord devient une alerte explicite au
  lieu de deux courbes à comparer à l'œil.

  **Séquencement — pourquoi pas dans 1.8.1.** Rendre les entités de ligne
  *par site* change leur `unique_id`, donc les recrée. Le faire dans le bugfix
  serait gratuit (il recrée déjà tout), **mais des entités par site sans
  publieur unique, ce sont les deux instances qui écrivent dedans** — le bug
  corrigé, reproduit. L'élection (C12) n'arrive qu'en A2. Coût assumé : les
  4 entités de ligne sont recréées **une seconde fois** en A2. C'est le moindre
  mal — l'alternative serait de faire entrer une élection de publieur dans un
  patch, contre la séparation bug/feature du projet.

- **C14 — La mise à niveau des capteurs USG est strictement additive.**
  Les 8 capteurs existants reçoivent `device_class`, `state_class` et `retain`,
  mais leur **`unique_id` et leur type d'entité ne changent pas**. Motif : un
  changement d'`unique_id` — ou une conversion de `sensor` vers
  `binary_sensor` — ferait **recréer l'entité par Home Assistant**, avec perte
  de l'historique. Or c'est précisément ce qu'on cherche à éviter en enrichissant
  plutôt qu'en refondant. Le seul changement d'identité assumé du projet est
  celui du bugfix 1.8.1, et il est déjà payé.

- **C13 — La liste des entités HA est stable dans le temps.** La discovery est
  *retained* : une entité publiée puis dépubliée laisse une trace, et des
  entités qui apparaissent et disparaissent au fil des cycles rendent les
  automatisations et l'historique inutilisables. La liste se décide **une fois**,
  d'après les champs que le spike a relevés sur le firmware ; un champ
  temporairement illisible devient `unavailable`, **jamais** dépublié.
- **C11 — La sonde périodique est opt-in et sort par le lien 4G.** A1 a livré la
  sonde à la demande ; A2 la rend périodique. Deux garde-fous :
  - **opt-in par équipement**, désactivée par défaut, intervalle horaire par
    défaut (~0,7 Mo/mois). Cohérent avec le reste du plan : rien ne bouge tant
    qu'un humain n'a pas activé explicitement. Sur un lien de secours facturé au
    volume, consommer sans qu'on l'ait demandé n'est pas acceptable ;
  - la sonde **porte sa preuve de chemin** (A1) : IP publique observée différente
    de celle du site, **et** compteurs du MR110 en mouvement. Le Pi Zero étant à
    double rattachement (`eth0` vers la fibre, `wlan0` vers le MR110), lier
    l'interface ne prouve rien. Une sonde qui fuit vers la fibre réussirait
    toujours et l'alerte ne se déclencherait **jamais** — le warning serait pire
    qu'inutile, il serait rassurant à tort. Un résultat `LEAK` est remonté comme
    **défaut de configuration**, jamais comme secours sain.
- **C9 — Le chemin de commande MQTT est authentifié et gardé.** Le `subscribe`
  crée une surface d'attaque qui n'existait pas : le broker doit être
  authentifié (`MQTT_USERNAME` / `MQTT_PASSWORD` existent déjà,
  `config.py:260-261`), et toute action destructive exige l'entité *arm*.
- **C10 — Aucun échec silencieux côté HA.** Toute commande reçue produit un
  résultat observable dans une entité dédiée. Sans ça, un refus est
  indistinguable d'un message perdu.
- `watchdog.py` et `state.py` restent **non modifiés** (comme en A1) : le moteur
  reste mono-cible jusqu'au PRD B.
- Dashboard : zéro dépendance JS externe, responsive mobile-first, dark mode.

## 6. Critères d'acceptation

- [ ] **Pré-requis** : bugfix 1.8.1 livré ; deux instances publient des identités
      MQTT disjointes
- [ ] Quota : conso du cycle, %, jour de reset, **détection de remise à zéro**,
      persistant après redémarrage du service
- [ ] Usage détecté avec anti-rebond ; trois états distingués (inactif / en
      service / saturé), calibrés sur du LTE Cat 4
- [ ] **C11** : sonde périodique **opt-in**, désactivée par défaut, intervalle
      configurable ; **preuve de chemin exigée** (IP ≠ celle du site + compteurs
      en mouvement), `LEAK` remonté comme défaut de configuration
- [ ] Warning au **changement** d'état quand le lien cesse de porter du trafic,
      distinct d'un warning « routeur injoignable »
- [ ] Dashboard : carte par équipement, badge readiness, **saut en panne**, 4G,
      quota, bandeau d'usage
- [ ] Dashboard **sans** équipement déclaré : rendu strictement inchangé
- [ ] **C4** : `/metrics` expose toujours les `usg_watchdog_*` **sans label**
      (assertion explicite par métrique legacy)
- [ ] Métriques labellisées ajoutées (4G, readiness, quota, qualité du chemin)
- [ ] **C12** : un device HA **par routeur** (indexé site + équipement), publié
      par la seule instance élue ; l'autre expose l'état du peer avec son âge
- [ ] **C12** : une seule instance interroge un équipement à un instant donné ;
      reprise après `PEER_TAKEOVER_DELAY` à la perte du peer
- [ ] **C13** : liste d'entités stable ; champ illisible → `unavailable`,
      jamais dépublié
- [ ] **C14** : les capteurs USG reçoivent `device_class` / `state_class` /
      `retain`, sans changement de type d'entité
- [ ] **C15** : **un seul device `USG <site>`** par site, alimenté par l'instance
      élue ; les capteurs propres au watchdog restent par instance
- [ ] **C15** : `binary_sensor` divergence + capteur état du peer ajoutés sur le
      device watchdog, pour compenser la perte de la double vue
- [ ] **C17** : température, disque, mémoire et charge de l'hôte publiées sur le
      device watchdog, en stdlib seule ; champ indisponible → `unavailable`
- [ ] **C18** : niveaux de notification conformes au tableau du Sprint 1 ;
      escalade `CRITICAL` si l'équipement est en cours d'utilisation ; aucun
      doublon entre master et slave
- [ ] Nouvelles entités : `device_class` / `state_class` renseignés, états
      **retained**
- [ ] Bouton de reboot : **refusé sans l'entité *arm*** ; *arm* se désarme seule
- [ ] **C10** : entité de dernière action indiquant résultat et motif de refus
- [ ] État « en service » **remonté** au moment de la demande, non bloquant
- [ ] **C9** : chemin de commande documenté comme exigeant un broker authentifié
- [ ] Toute commande HA tracée dans l'`EventLog` avec l'origine `mqtt`
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, docs à jour, VERSION = 1.10.0

## 7. Sprints

| # | Sprint | But | Risque |
|---|---|---|---|
| 1 | Quota, usage, **élection du poller** | Les informations qui ne se déduisent pas d'une lecture isolée, et l'exclusivité qu'impose le polling périodique | **Élevé** |
| 2 | Dashboard + Prometheus | Voir sans taper une commande, sans casser Grafana | Moyen |
| 3 | Home Assistant : capteurs + bouton armé | Superviser et agir depuis HA | **Élevé** (chemin entrant) |
| 4 | Docs + release 1.10.0 | | Faible |

## 8. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| **Chemin de commande MQTT entrant vers une action destructive** | **Critique** | C9 : broker authentifié + entité *arm* obligatoire à désarmement automatique |
| **Label ajouté à une métrique existante** | **Critique** (casse silencieuse) | C4 : legacy sans label conservé, assertion par métrique |
| Reboot depuis HA d'un secours en service | Élevé | État remonté dans l'entité *arm* et la dernière action ; décision laissée à l'opérateur |
| Échec de commande invisible dans HA | Élevé | C10 : entité de dernière action avec motif |
| Identité MQTT en collision | Élevé | Pré-requis bloquant : bugfix 1.8.1 |
| **Master et slave pollent le même routeur en continu** | **Élevé** | C12 : élection du poller. Le polling périodique d'A2 rend la contention de session certaine, là où A1 restait à la demande |
| **Deux devices HA pour un routeur physique** | Moyen | C12 : device indexé sur site + équipement, publication réservée au poller élu |
| Entités HA qui apparaissent et disparaissent | Moyen | C13 : liste figée d'après le spike ; `unavailable` plutôt que dépublication |
| Compteur data qui se remet à zéro | Moyen | Accumulation de deltas positifs, jamais de soustraction naïve |
| Faux positif d'usage sur un pic de management | Moyen | Anti-rebond + seuils calibrés Cat 4 |
| **Alertes mal calibrées → notifications ignorées** | Moyen | C18 : niveau fixé par événement, escalade conditionnelle, notification au changement d'état seulement |
| **Sonde périodique qui fuit par la fibre** | **Critique** | C11 : double preuve de chemin. Sur un hôte à deux pattes, le binding d'interface ne garantit rien — sans preuve, l'alerte ne part jamais |
| Sonde périodique activée sans le vouloir → conso du forfait | Moyen | C11 : opt-in par équipement, désactivée par défaut |
| Entités HA `unknown` après redémarrage de HA | Faible | `retain` sur les états, nouvelles **et** existantes (C14) |
| **Enrichissement qui recrée les entités USG** | Élevé | C14 : type d'entité figé ; jamais de `sensor` → `binary_sensor` |
| **Perte de la détection de désaccord master/slave** | Moyen | C15 : `binary_sensor` divergence explicite, plus lisible que deux courbes à comparer |
| Seconde recréation des 4 entités de ligne | Faible | C15 : assumée et documentée ; l'éviter imposerait une élection dans un patch |
| Régression de la surveillance USG | Critique | `watchdog.py` / `state.py` non modifiés (invariant + frontières) |

## 8bis. Rollback par sprint

| Sprint | Rollback | Point d'attention |
|---|---|---|
| 1 | Revert de la branche | L'élection touche `peer.py` : vérifier après revert que le failover HA d'origine fonctionne toujours |
| 2 | Revert de la branche | Aucune donnée persistée n'est perdue |
| 3 | Revert **+ nettoyage MQTT** | La discovery est publiée en `retain` : un revert du code **ne retire pas** les entités du broker. Il faut publier des messages de discovery vides sur les topics concernés, sinon Home Assistant garde des entités fantômes |
| 4 | Revert **+ retag** | L'auto-updater tire le dernier tag |

**Le sprint 3 est le seul dont le rollback demande une action hors dépôt.**
C'est la contrepartie du `retain` : il rend les entités robustes aux
redémarrages, et durables au-delà du code qui les a créées.

## 9. Definition of Done

Tous les AC §6 cochés, 4 sprints verts, coverage ≥ 80 %, `validate.sh` vert,
docs à jour, v1.10.0 taggée — et **vérification terrain** : dans Home Assistant,
les deux MR110 apparaissent comme deux devices distincts avec leur readiness et
leur signal réels ; presser le bouton de reboot **sans armer** ne fait rien et
l'entité de dernière action explique pourquoi ; armer puis presser redémarre
l'équipement et le trace.
