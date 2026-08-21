# PRD A1 — Pilotage des lignes de secours TP-Link MR110

- **Catégorie** : feature
- **Date** : 2026-08-20
- **Auteur** : Jerome Soyer
- **ADR** : [docs/adr/0001-multi-vendor-router-monitoring.md](../../../../adr/0001-multi-vendor-router-monitoring.md)
- **Version cible** : 1.9.0 (minor)
- **Branche** : `dev` → PR → `main`
- **Pré-requis** : bugfix [1.8.1 identité MQTT](../../bugfix/2026-08-20_1618-mqtt-instance-identity.md) livré (bloquant pour A2, recommandé avant A1)
- **Suites** : [A2 — Exposition & Home Assistant](../2026-08-20_1618-a2-exposition-ha/spec.md) puis PRD B (§9)
- **Remplace** : `2026-08-12_1451-tplink-backup-lines/` (superseded)

---

## 1. Problème & objectif

Dijon et Nice disposent chacun d'une **ligne de secours 4G TP-Link TL-MR110**.
Ce sont aujourd'hui des angles morts complets : le watchdog ne les voit pas, et
il n'existe même pas de chemin réseau pour les interroger. Un backup non testé
n'est pas un backup — on découvre qu'il est HS (SIM expirée, plus de signal,
quota épuisé, WiFi décroché) au moment précis où on en a besoin.

**Objectif d'A1** : pouvoir **piloter** ces équipements depuis les outils
existants (API HTTP, bot Telegram), sans jamais les redémarrer automatiquement
et **sans toucher à la boucle de surveillance USG**.

**Objectif corollaire, non négociable** : quand le secours est injoignable, dire
**où** ça casse — Pi Zero, WiFi, ou MR110. Une alerte qui ne le dit pas ne fait
que déplacer le travail de diagnostic.

**Non-objectif** : faire du MR110 une cible de reboot automatique.

A1 livre le pilotage. L'exposition (dashboard, Prometheus, Home Assistant,
quota) est en A2 ; le moteur multi-cible en PRD B.

## 2. Topologie de référence (par site)

```
    ┌────────────── LAN du site ──────────────┐
    │                                          │
  [ USG ]      [ watchdog master ]  [ watchdog slave ]
 (lien principal,        │                 │
  surveillance actuelle) └────┬────────────┘
                              │  route statique : <subnet MR110> via <IP LAN Pi Zero>
                              ▼
                        [ Pi Zero 2 W ]        eth0 = LAN du site, alimenté en PoE
                              │                wlan0 = WiFi du MR110
                              │  IP forwarding + NAT   (pont de MANAGEMENT seul)
                              ▼
                        ((( WiFi 2,4 GHz )))   ← saut fragile, silencieux
                              │
                        [ TL-MR110 ]           équipement à piloter, 4G Cat 4
```

**4 instances** au total : Dijon (master + slave), Nice (master + slave), en
paires HA via `peer.py`. Chaque instance est en LAN avec ses équipements.

Le Pi Zero ne porte **pas** le trafic de production : le chemin de bascule réel
du site ne passe pas par lui (hypothèse H1, §3).

**Le mode d'accès varie selon le site et le rôle (C16).** Le schéma ci-dessus
décrit le cas **distant** : le pont est une machine dédiée, et le watchdog
l'atteint par le réseau. Mais sur certaines instances, **le watchdog tourne
lui-même sur la machine qui fait pont** — elle a alors directement une patte sur
le WiFi du MR110. Les deux cas coexistent dans le parc, et peuvent différer entre
le master et le slave d'un même site.

| | **Mode `bridged`** (le watchdog est le pont) | **Mode `remote`** (pont dédié) |
|---|---|---|
| Route + NAT | **inutiles** | requis |
| Sonde C11 | **locale**, liée à l'interface sans fil | **SSH ponctuel** sur le pont |
| `Hop.BRIDGE` | état de l'interface sans fil **locale** | joignabilité du pont |
| C7 (rien de déployé) | sans objet, l'hôte est déjà géré | applicable |

**Ce qui ne change pas** : la **preuve de chemin (C11)**. Une machine qui héberge
le watchdog *et* fait pont a elle aussi deux pattes — le risque de fuite vers la
fibre est **identique**. Le mécanisme de preuve se transpose sans modification,
ce qui est précisément l'intérêt de l'avoir fondé sur le résultat plutôt que sur
la configuration.

**Le pont est alimenté en PoE** — un seul câble lui apporte réseau et courant.
Trois conséquences :

- **sa position est figée par le câblage**, pas choisie ; le MR110, lui, est
  placé selon la réception 4G. Le pont WiFi existe très probablement parce que
  ces deux points ne coïncident pas ;
- **son alimentation dépend du switch** : un saut `BRIDGE` en échec peut
  signifier Pi Zero planté, port PoE coupé, budget PoE dépassé, ou câble. Le
  message opérateur doit rester prudent sur la cause ;
- **en contrepartie il devient redémarrable à distance** en coupant/rallumant le
  port PoE (candidat hors périmètre, §9.3).

## 3. Matériel et hypothèses

**TP-Link TL-MR110** — 4G LTE Cat 4, WiFi N300 **2,4 GHz mono-bande**, 2 antennes
4G amovibles, **2 ports LAN Ethernet**, SIM tout opérateur, 32 appareils max.

| Caractéristique | Conséquence de conception |
|---|---|
| WiFi 2,4 GHz mono-bande | Saut le plus fragile du chemin, sans repli 5 GHz → sondé à part (`Hop.WIRELESS`), RTT comme indicateur de qualité |
| LTE Cat 4 (~150/50 Mb/s théoriques) | Plafond modeste : calibre les seuils d'usage en A2, pas ceux du lien principal |
| 2 ports LAN Ethernet | Rend le câblage WAN2 trivial (§9.2) ; ouvre la variante Ethernet du saut (Sprint 1) |
| 32 appareils max | `clients_total` exploitable ; limite à connaître si le secours doit servir un site |

**Le TL-MR110 indoor n'est pas dans les modèles testés** de `tplinkrouterc6u`
(seul le TL-MR110-**Outdoor** v1.0 y figure, avec MR100 / MR105 / MR150 /
MR6400 / Archer MR200-400-550-600). Il n'existe **aucun scénario de repli
matériel** : c'est bien du MR110 (confirmé), pas un MR100 qui serait couvert.
→ **spike go/no-go bloquant** au Sprint 1.

### H1 — Le chemin de bascule n'est pas observable par le watchdog

Le Pi Zero étant un pont de management, on ne peut pas voir la bascule depuis le
lien principal (l'approche « WAN2 de l'USG via `multiwan.py` » ne s'applique pas
tant que le MR n'est pas câblé sur le WAN2 — §9.2).

**Conception retenue** (mise en œuvre en A2) : détecter l'**usage** du secours
depuis le MR110 lui-même — débit rx/tx, clients associés, conso qui décolle. Ce
signal vaut **quel que soit** le mécanisme de bascule, y compris manuel. C'est
volontairement une détection *a posteriori* (« le secours sert »), pas une
détection d'événement de bascule, et les messages doivent le dire.

## 4. Correctness Discovery

- **Audience** : l'opérateur. Décision pilotée : *« je veux voir et agir sur le
  secours de Dijon depuis Telegram, tout de suite »* — et si ça ne répond pas,
  *« qu'est-ce qui casse : Pi Zero, WiFi, ou le routeur ? »*
- **Vérification** : (a) sans `TPLINK_*` déclaré, comportement strictement
  identique à la 1.8 ; (b) `/lte` depuis Telegram retourne l'état réel d'un
  MR110 de Dijon ; (c) chaque saut coupé produit une cause **distincte** et
  correctement attribuée ; (d) un reboot exige une confirmation et est tracé.
- **Failure definition** : impossible de piloter le secours ; OU « secours HS »
  sans dire où ça casse ; OU un reboot part sans confirmation ; OU la
  surveillance USG régresse.
- **Danger definition** : reboot d'un secours **pendant** qu'il porte le trafic
  (= couper le site) ; lock de session admin ; fuite du mot de passe TP-Link ;
  exposition de l'admin du MR110 à tout le LAN via une route trop large.
- **Uncertainty policy** : champ absent ou illisible ⇒ `None` et readiness
  `UNKNOWN` — jamais `OK` par défaut, jamais `DEGRADED` non plus. Une
  indisponibilité non attribuable à un saut précis est rapportée comme telle,
  jamais imputée au MR110. Un driver ne lève jamais. **Une commande que le spike
  n'a pas vue répondre n'est pas exposée.**
- **Risk tolerance** : **zéro** régression USG. Métriques best-effort. Si le
  MR110 n'est pas pilotable par la lib, le mode dégradé (joignabilité +
  attribution de panne) est un livrable acceptable.

## 5. Scope

### In scope
- Chemin réseau d'audit : routage + NAT sur le Pi Zero, route côté watchdogs,
  runbook reproductible sur les 2 sites.
- Spike de compatibilité TL-MR110 (go/no-go) + plan B écrit.
- Contrat `RouterDriver` + `TplinkDriver` + **sonde étagée avec attribution de
  panne**.
- Readiness calculée (SIM, attach, seuils signal, intégrité du chemin).
- **Commandes de management** : API `/api/tplink/*` + Telegram `/lte`, avec
  **confirmation serveur** pour les actions destructives.
- **Sonde de bout en bout à la demande** (`/lte check <id>`) : vérifier que le
  lien 4G **porte réellement du trafic**, et pas seulement qu'il est attaché.
- **Helper de masquage de secrets**, applicable aux 11 secrets existants.
- Contraintes prod C1→C8, updater C2, docs, release 1.9.0.

### Out of scope
- Dashboard, Prometheus, Home Assistant, quota data, détection d'usage → **A2**.
- Moteur multi-cible, `UsgDriver`, rôles dans le scoring, alerting automatique,
  exclusivité de polling complète → **PRD B** (§9.1).
- Reboot automatique d'un équipement TP-Link — exclu par décision.
- Suppression du Pi Zero du chemin — **écartée par décision** (§9.4).
- Câblage sur WAN2 — souhaité, non court terme (§9.2).
- Redémarrage du Pi Zero par le port PoE (§9.3).
- Renommage du projet (§9.5).

## 6. Contraintes

### 6.1 Compatibilité production (auto-updater) — BLOQUANTES

L'auto-updater tire `main` automatiquement : la 1.9.0 arrivera sur **les 4
instances** sans intervention.

- **C1 — Import 100 % paresseux de `tplinkrouterc6u`.** Jamais au niveau module.
  `updater/preflight.py` fait `import usg`, `import watchdog`,
  `import connectivity` : une chaîne d'import qui tire la lib ferait échouer le
  preflight → **update avortée + rollback sur les 4 instances**. Test :
  `python -c "import watchdog"` sans la lib.
- **C2 — L'auto-updater n'installe pas les deps.** `updater/update.py` ne fait
  aucun `pip install`. À enrichir : relancer `pip install -r requirements.txt`
  sur changement du fichier, idempotent, loggé, échec → rollback.
- **C3 — Contrat `/api/state` rétro-compatible.** En A1, `state.py` n'est **pas
  modifié** : C3 est satisfaite par construction. Les endpoints `/api/tplink/*`
  s'**ajoutent**. Le risque redevient réel en PRD B.
- **C4 — Métriques Prometheus legacy préservées.** A1 ne touche pas
  `metrics.py`. Contrainte active en A2.

### 6.2 Topologie

- **C5 — Session admin TP-Link unique.** Les MR n'acceptent qu'une session à la
  fois. En A1 le management est **à la demande** : verrou local par équipement,
  `logout()` garanti, réessai **unique** avec message clair si la session est
  occupée. L'exclusivité entre master et slave appartient au PRD B, où le
  polling devient continu.
- **C6 — Aucune action destructive automatique.** Reboot, SMS et USSD ne
  proviennent que d'une commande opérateur explicite, avec confirmation, et sont
  tracés dans l'`EventLog` avec leur origine.
- **C7 — Le pont ne devient pas un composant applicatif à maintenir.**
  En mode `remote` : IP forwarding + NAT sur le pont, route statique côté
  watchdogs, et **rien d'installé dessus** — ni dépendance, ni service, ni
  fichier du projet ; seule une commande SSH ponctuelle (sonde C11) est
  autorisée, qui ne laisse rien derrière elle.
  En mode `bridged` : la contrainte est **sans objet**, l'hôte étant déjà une
  machine gérée du parc.

  Dans les deux cas, le driver parle à une IP et **ignore comment on y arrive** —
  c'est ce qui rend la migration WAN2 sans impact sur le code, et ce qui permet
  aux deux modes de coexister sans code conditionnel dans le driver.

  La route, quand elle existe, est posée **sur les hôtes watchdog uniquement**,
  ni sur l'USG ni en DHCP : l'admin du MR110 ne doit pas devenir joignable depuis
  tout le LAN.

  **Amendement du 2026-08-20** : C7 interdisait initialement *tout* code sur le
  Pi Zero. Elle est assouplie pour autoriser une **commande SSH ponctuelle**
  (la sonde de C11) : rien n'y est **déployé**, **installé** ni à maintenir —
  aucune dépendance Python, aucun service, aucun fichier du projet. L'esprit de
  la contrainte est préservé : le Pi Zero reste un équipement d'infrastructure,
  pas un composant applicatif.

- **C11 — La sonde doit sortir par le lien 4G, et le prouver.** L'état
  `internet_ok` ne peut pas se contenter de `connect_status` / `network_type` :
  ces champs sont **auto-reportés par le routeur**, et un MR110 peut être
  attaché au réseau tout en n'ayant plus de data (forfait épuisé, APN cassé,
  blocage opérateur). Une sonde active de bout en bout est donc nécessaire.

  Elle est exécutée par **SSH ponctuel sur le Pi Zero**, seul point du chemin
  situé derrière le MR110.

  **Le problème du double rattachement.** Le Pi Zero a deux pattes : `eth0` vers
  le LAN du site (donc vers la fibre) et `wlan0` vers le MR110. Lier la requête
  à `wlan0` **ne prouve pas** qu'elle est sortie par là : l'option peut ne pas
  être honorée par l'outil, une règle de routage peut avoir changé, le DNS peut
  sortir par l'autre patte. Une sonde qui fuit vers la fibre **réussit** — et
  signale un secours sain quoi qu'il arrive.

  **La sonde doit donc porter sa propre preuve de chemin**, et non se fier à sa
  configuration. Deux preuves indépendantes, exigées ensemble :

  1. **L'IP publique observée diffère de celle du site.** La sonde renvoie l'IP
     publique vue depuis le Pi Zero ; le watchdog la compare à l'IP publique du
     site, obtenue par `get_public_ip()` (`src/ddns_cloudflare.py:72`, déjà
     présent et doté d'endpoints de repli). **Identiques ⇒ la sonde est sortie
     par la fibre**, le résultat est invalide. Le CGNAT de l'opérateur mobile ne
     gêne pas : on cherche une *différence*, pas une correspondance avec le
     `wan_ipv4_addr` du routeur.
  2. **Les compteurs de trafic du MR110 ont bougé.** Relevé avant/après via
     `total_statistics`. S'ils sont figés, la requête n'a pas traversé le
     routeur, quelle que soit l'IP renvoyée.

  Prises isolément, chacune est contournable ; ensemble, elles rendent une fuite
  détectable au lieu de silencieuse.

  **Propriété utile** : le faux OK n'est possible que si la fibre est **up** —
  c'est-à-dire exactement quand la référence est disponible pour le détecter.
  Fibre down, une fuite échoue au lieu de mentir. Le cas dangereux est celui où
  l'on a les moyens de le voir. Conserver malgré tout la dernière IP publique
  connue du site en repli.

  Coût : une requête légère (~1 Ko). En périodique horaire (A2, opt-in) :
  de l'ordre de 0,7 Mo/mois — négligeable devant n'importe quel forfait.
- **C19 — Les lectures TP-Link sont authentifiées.** Les endpoints
  `/api/tplink/*`, y compris en **GET**, exigent le jeton Bearer. C'est une
  **divergence assumée** avec les GET existants du projet (`/api/state`,
  `/api/events`), qui sont ouverts : ces nouvelles réponses exposent état SIM,
  opérateur, IP WAN et consommation, ce qui n'est pas du même ordre que le score
  du watchdog.
  - **Fail closed** : `API_TOKEN` non configuré ⇒ ces endpoints répondent `403`,
    comme les POST aujourd'hui (`http_server.py:99-101`). Déclarer un équipement
    sans configurer `API_TOKEN` prive donc d'accès API — Telegram reste
    utilisable. À documenter comme prérequis, pas à découvrir en production.
  - **Le jeton ne doit jamais se retrouver côté client.** Le dashboard rend les
    données TP-Link **côté serveur** (comme le reste de `dashboard.py`) et
    n'appelle pas l'endpoint authentifié depuis le navigateur : y placer le jeton
    l'exposerait à quiconque ouvre la page.

- **C16 — Le mode d'accès est une propriété de la cible, pas du projet.**
  Chaque équipement déclare comment on l'atteint (`bridged` ou `remote`), et
  **deux instances d'un même site peuvent différer**. Conséquences :
  - la sonde s'exécute **en local** ou **par SSH** selon le mode, mais **exige la
    même preuve de chemin** (C11) dans les deux cas ;
  - `Hop.BRIDGE` se sonde différemment — état de l'interface sans fil locale en
    `bridged`, joignabilité du pont en `remote` — mais garde le même sens pour
    l'opérateur : *le premier maillon est en cause* ;
  - `Hop.ROUTE` (C8) est **sans objet en mode `bridged`** : il n'y a ni route ni
    NAT à omettre.

  **À trancher au Sprint 1, par site et par instance** : faut-il configurer le
  chemin `remote` **en repli** sur l'instance `bridged`, et inversement ? Sans
  cela, la surveillance du secours disparaît avec l'instance qui porte le pont —
  ce qui est faible pour un dispositif dont le rôle est justement de survivre aux
  pannes. Hypothèse retenue par défaut : **oui, configurer le repli**, à
  confirmer lors du relevé terrain.

- **C8 — Une route absente n'est pas une panne de secours.** Route ou NAT
  manquants → `Hop.ROUTE`, défaut de configuration du chemin d'audit. Sinon la
  première mise à jour système qui efface une route lève une fausse alerte
  critique sur un secours sain.

### 6.3 Techniques

- Python ≥ 3.11 (projet) ∩ ≥ 3.10 (lib).
- `tplinkrouterc6u` **pinné** à la version validée au spike ; installée sur les
  hôtes watchdog uniquement, **jamais sur le Pi Zero** (C7).
- `authorize()` / `logout()` en **try/finally** systématique ; timeouts explicites
  sur tous les appels (le chemin traverse un lien WiFi).
- Immutabilité : `RouterHealth`, `RouterMetrics`, `RouterReadiness` frozen.
- `never raise` pour tout driver.
- Lectures mises en cache (défaut 60 s) et sérialisées par équipement.
- **`API_TOKEN` non configuré ⇒ tous les POST répondent 403**
  (`http_server.py:99-101`). Prérequis de déploiement à documenter.

## 7. Critères d'acceptation

- [ ] Depuis un hôte watchdog de Dijon : Pi Zero, MR110 et son admin joignables
- [ ] **C7** : rien installé sur le Pi Zero ; route sur les hôtes watchdog seulement
- [ ] Runbook réseau écrit et **rejoué avec succès sur Nice**
- [ ] Spike : verdict explicite, révision matérielle et firmware relevés par site,
      **tableau des commandes réellement disponibles**, version de lib retenue
- [ ] **Aucun `TPLINK_*` déclaré → comportement strictement identique à la 1.8**
- [ ] `TplinkDriver` conforme au contrat ; **aucune méthode ne lève**
- [ ] **Attribution de panne** : `BRIDGE` / `WIRELESS` / `DEVICE` / `ROUTE`,
      quatre causes distinctes et exactes
- [ ] **C8** : route absente rapportée comme défaut de configuration
- [ ] API : `GET /api/tplink`, `/api/tplink/<id>`, `POST …/refresh`, `POST …/reboot`
- [ ] **C19** : les GET `/api/tplink/*` exigent le jeton ; `403` si `API_TOKEN`
      absent ; aucun jeton dans le rendu du dashboard
- [ ] Telegram : `/lte`, `/lte <id>`, `/lte reboot <id>`, `/lte confirm <jeton>`, `/help`
- [ ] **Les 8 commandes Telegram existantes sont inchangées** (non-régression)
- [ ] **C6** : reboot jamais automatique ; confirmation exigée ; tracé avec origine ;
      avertissement si l'équipement porte du trafic
- [ ] SMS / USSD exposés **uniquement** si le spike les a validés
- [ ] Readiness `OK` / `DEGRADED` (raisons chiffrées) / `UNKNOWN`
- [ ] `/lte check <id>` : sonde de bout en bout, résultat explicite
- [ ] **C11** : la sonde **prouve son chemin** — IP publique observée différente
      de celle du site **et** compteurs du MR110 qui bougent ; une sortie par la
      fibre est détectée et rapportée comme défaut de configuration
- [ ] Un lien attaché sans data est détecté `DEGRADED`, pas `OK`
- [ ] Accès SSH au pont configuré et documenté (clé, `known_hosts`) — sites
      en mode `remote`
- [ ] **C16** : mode `bridged` / `remote` déclaré par équipement ; les deux
      chemins de sonde fonctionnent et **exigent la même preuve de chemin**
- [ ] **C16** : mode relevé et consigné **par site et par instance** ; décision
      prise sur la configuration d'un chemin de repli
- [ ] Helper de masquage appliqué aux logs ; mot de passe TP-Link absent des
      **trois** whitelists de config
- [ ] **C1** : `python -c "import watchdog"` réussit sans `tplinkrouterc6u`
- [ ] **C2** : l'auto-updater installe les deps quand `requirements.txt` change
- [ ] `watchdog.py` et `state.py` **non modifiés** sur tout A1
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, README + DEPLOY + runbook à jour

## 8. Sprints

| # | Sprint | But | Risque |
|---|---|---|---|
| 1 | Chemin réseau Pi Zero + spike MR110 + contrat `RouterDriver` | Créer l'accès, savoir si c'est faisable, poser le contrat | **Go/no-go** |
| 2 | `TplinkDriver` + sonde étagée | Piloter le routeur, attribuer les pannes | Moyen |
| 3 | Commandes de management (API + Telegram) + masquage | **Le livrable attendu** | Moyen |
| 4 | Updater C2, docs, release 1.9.0 | Livrer sans casser les 4 instances | Moyen |

**Gates** :
- *Dans le Sprint 1, après la partie réseau* : sans chemin joignable, le spike ne
  peut pas tourner. Ne pas enchaîner « à blanc ».
- *Après Sprint 1* : verdict `UNSUPPORTED` → re-cadrer les sprints 2 à 4 sur le
  plan B avant de continuer.

## 9. Décisions, suites et sujets écartés

### 9.1 PRD B — moteur multi-cible (~1.11.0)

`UsgDriver` derrière le contrat ; `MonitoredTarget` (score, circuit-breaker,
cooldowns par cible) ; suppression des trackers de latence singletons de
`connectivity.py` ; rôles `primary` / `backup` intégrés au moteur avec C6
renforcée en invariant structurel ; alerting automatique sur la readiness ;
**C3 redevient critique** (`state.py` modifié, rollout non atomique sur une
paire HA).

> **Note du 2026-08-21** : l'exclusivité de polling (C5 complète) était
> initialement prévue ici. Elle est **remontée dans A2** : le polling périodique
> qu'A2 introduit rend la contention de session admin certaine, alors qu'A1
> reste à la demande. Voir C12 dans le PRD A2.

C'est le refactor risqué. A1 et A2 livrant l'essentiel de la valeur, il pourra
être jugé sur ses propres mérites — **y compris la décision de ne pas le faire**.

### 9.2 Câblage du MR110 sur le WAN2 de l'USG (souhaité, non court terme)

Le MR110 ayant 2 ports LAN, c'est matériellement un câble.
**Impact sur le code : nul** — c'est ce que garantit C7. Le jour du câblage, on
supprime la route et le NAT ; driver, commandes et métriques continuent.

**Le Pi Zero reste**, y compris après ce câblage : la voie « naturelle » pour
atteindre le MR passerait alors par l'USG, c'est-à-dire **par l'équipement dont
on surveille la défaillance**. Le pont demeure un **chemin de management hors
bande**, qui permet d'interroger et de redémarrer le secours *pendant* une panne
de l'USG — le moment exact où on en a besoin.

Apports du câblage : deux points de défaillance en moins sur le chemin, et
`src/multiwan.py` (déjà présent) devient exploitable pour une **vraie détection
d'événement de bascule**, à ajouter **en plus** de la détection d'usage de H1.

### 9.3 Redémarrage du Pi Zero par le port PoE — candidat, hors périmètre

Couper puis rallumer le port de switch redémarre le Pi Zero, transformant un
déplacement sur site en commande à distance. Combiné au reboot du MR110 par son
API, le chemin d'audit deviendrait réparable **de bout en bout**.

Hors périmètre : c'est une action sur le switch (API du contrôleur), pas sur du
TP-Link, et une action destructive de plus à sécuriser. Vérifier d'abord que le
port est sur un switch pilotable — un injecteur PoE passif ne se commande pas.

### 9.4 Suppression du Pi Zero — écartée

Raccorder le MR110 directement au LAN (IP statique, DHCP désactivé) supprimerait
le pont, le WiFi, la route et le NAT. **Écarté par décision (2026-08-12).**
Conservé ici pour mémoire, et parce que ça documente ce que le pont apporte en
échange de sa complexité : l'isolation de l'admin du MR110 vis-à-vis du LAN (C7),
et le chemin hors bande de §9.2.

Reste ouverte et tranchée au Sprint 1, site par site : la **nature du saut**
Pi Zero ↔ MR110 (WiFi actuel, ou Ethernet si les équipements sont adjacents).

### 9.5 Renommage du projet — reporté

`usg-watchdog` devient un nom partiellement faux dès qu'un TP-Link est piloté.
**On ne renomme pas maintenant** (confirmé le 2026-08-12).

Coût réel : unit systemd, `/opt/usg-watchdog`, user système, logrotate, chemins
de logs et d'événements, tags git consommés par l'auto-updater, préfixe des
métriques Prometheus consommé par Grafana, et une migration coordonnée des 4
instances qui se mettent à jour toutes seules. Ce n'est pas un `sed`.

Ce que A1 prépare sans rien renommer : l'abstraction `RouterDriver` retire au mot
« USG » son statut de concept central du code — il redevient un vendor parmi
d'autres.

**Trigger de réouverture** : ≥ 3 vendors, ou distribution publique. Voie la moins
risquée : renommage **en deux temps** (alias systemd + double émission des
métriques, puis suppression une version plus tard).

## 10. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| **MR110 indoor non supporté par la lib** | **Critique** | Spike go/no-go Sprint 1 avant tout code driver + plan B écrit |
| **Aucun chemin réseau aujourd'hui** | **Critique** (bloque tout) | Route + NAT, traité en premier au Sprint 1 |
| **Reboot d'un secours en service = site coupé** | **Critique** | C6 : confirmation serveur + avertissement si débit/clients non nuls |
| Preflight cassé à l'auto-update | **Critique** | C1 : import paresseux, testé sans la lib |
| Régression de la surveillance USG | Critique | A1 ne modifie ni `watchdog.py` ni `state.py` (invariant + frontières de sprint) |
| Lib absente après auto-update | Élevé | C2 |
| **Dépendance qui ne s'installe pas sur les hôtes `bridged`** | Élevé | Pi Zero **2 W** confirmés (ARMv8, pas ARMv6) ; installation réelle validée au Sprint 1, car C2 relance `pip install` à chaque auto-update |
| **Pi Zero = SPOF du chemin d'audit** | Élevé | Saut explicite ; cause PoE/switch/câble non tranchée dans le message |
| Lien WiFi qui décroche silencieusement | Élevé | Saut sondé séparément (RTT + perte) |
| Route absente → fausse alerte « secours HS » | Élevé | C8 |
| Admin du MR110 exposée à tout le LAN | Élevé | C7 : route sur les hôtes watchdog seulement |
| **Données SIM / opérateur / IP lisibles sans authentification** | Élevé | C19 : GET `/api/tplink/*` authentifiés, fail closed, jeton jamais côté client |
| Fuite du mot de passe TP-Link | Élevé | Env only, `.env` 600, helper de masquage, absent des 3 whitelists |
| **Sonde qui fuit par la fibre → faux OK permanent** | **Critique** | C11 : double preuve de chemin (IP publique ≠ celle du site + compteurs du routeur qui bougent). Le Pi Zero étant à double rattachement, le binding d'interface seul ne prouve rien |
| **Lien attaché mais sans data (forfait épuisé, APN)** | **Critique** | C11 : sonde active ; `connect_status` seul ne suffit pas |
| Accès SSH au pont à gérer (sites `remote`) | Moyen | Réutiliser le pattern de `scripts/setup_ssh.sh` (clé Ed25519, `known_hosts`) |
| **Topologie mixte traitée comme uniforme** | Élevé | C16 : mode déclaré par équipement ; relevé par site **et par instance** au Sprint 1 |
| **Surveillance du secours perdue avec l'instance qui porte le pont** | Moyen | C16 : configurer le chemin de repli sur l'autre instance |
| **Régression des 8 commandes Telegram existantes** | Élevé | Le parsing d'arguments est un prérequis : test de non-régression par commande |
| Collision de session admin master/slave | Moyen | C5 : verrou local, `logout()` garanti, réessai unique |
| Mismatch cipher CBC/GCM | Moyen | `get_client()` auto-détecte ; version validée au spike |
| SMS/USSD déclenchés par erreur (coût) | Moyen | Jamais implicites, jamais en réessai automatique |
| Champs LTE absents (firmware) | Faible | `None`, readiness `UNKNOWN`, commande non exposée si non validée |

## 10bis. Rollback par sprint

Le projet dispose d'un protocole global (`CLAUDE.md`) ; ce PRD précise ce qui
lui est propre.

| Sprint | Rollback | Point d'attention |
|---|---|---|
| 1 | Revert de la branche **+** procédure d'annulation réseau du runbook | **Mixte** : du code *et* de la configuration hors dépôt. Le runbook doit contenir la méthode d'annulation de la route, du NAT et de l'accès SSH — c'est un critère d'acceptation, pas une option |
| 2, 3 | Revert de la branche | Sans équipement déclaré, le code est inerte : un revert suffit |
| 4 | Revert **+** retag | L'auto-updater tire le **dernier tag** : revenir en arrière suppose de retirer ou dépasser `v1.9.0`, sinon les 4 instances retirent la version fautive |

**Règle générale** : ne jamais fusionner un sprint à moitié. L'isolation en
worktree rend le revert propre tant que rien n'est mergé — c'est le moment le
moins cher pour renoncer.

**Ce qui n'est pas réversible** : le bugfix 1.8.1 recrée les entités Home
Assistant. Revenir sur le code **ne les restaure pas** — les anciennes restent
orphelines et leur historique est perdu. C'est la seule étape irréversible de
la séquence, et elle arrive en premier.

## 11. Definition of Done

Tous les AC §7 cochés, 4 sprints verts, coverage ≥ 80 %, `validate.sh` vert,
docs à jour, v1.9.0 taggée, `dev` synchronisé — et **vérification terrain** :
depuis Telegram, `/lte` retourne l'état réel du secours de Dijon ; `/lte reboot`
exige une confirmation et fonctionne ; débrancher volontairement le WiFi du
Pi Zero produit un message qui **nomme le saut**, pas « MR110 HS ».
