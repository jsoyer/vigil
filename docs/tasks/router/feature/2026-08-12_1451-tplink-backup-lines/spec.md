> ⚠️ **SUPERSEDED le 2026-08-20** — scindé en trois livrables après quatre
> décisions (intégration Home Assistant avec bouton de reboot, bugfix MQTT
> séparé, helper de masquage de secrets) et une analyse du code qui a montré que
> trois briques supposées présentes n'existaient pas : parsing d'arguments
> Telegram, confirmation côté serveur, et chemin de commande MQTT entrant.
>
> - Pré-requis : [bugfix 1.8.1 — identité MQTT](../../bugfix/2026-08-20_1618-mqtt-instance-identity.md)
> - [A1 — Pilotage (1.9.0)](../2026-08-20_1618-a1-pilotage-tplink/spec.md)
> - [A2 — Exposition & Home Assistant (1.10.0)](../2026-08-20_1618-a2-exposition-ha/spec.md)
>
> Conservé pour l'historique : tout son contenu de fond (contraintes C1→C8,
> topologie Pi Zero/PoE, décisions verrouillées, hypothèse H1) est repris dans A1 et A2.

# PRD — Lignes de secours TP-Link MR110 — **Phase A : management & observabilité**

- **Catégorie** : feature
- **Date** : 2026-08-12
- **Auteur** : Jerome Soyer
- **ADR** : [docs/adr/0001-multi-vendor-router-monitoring.md](../../../../adr/0001-multi-vendor-router-monitoring.md) (amendé 2026-08-12)
- **Remplace** : [2026-06-26_1200-multi-vendor-tplink.md](../2026-06-26_1200-multi-vendor-tplink.md) (superseded)
- **Version cible** : 1.9.0 (minor — feature)
- **Branche** : `dev` → PR → `main`
- **Phase B** (moteur multi-cible, audit automatique) : voir §10, PRD séparé

---

## 0. Pourquoi ce PRD remplace celui du 26/06

Le PRD de juin a été écrit sur cinq hypothèses que les échanges du 2026-08-12
ont invalidées. Elles changent la sémantique, la topologie, le chemin réseau —
et l'ordre de livraison.

| Hypothèse de juin | Réalité |
|---|---|
| Les TP-Link sont des **liens principaux** à rebooter au seuil comme l'USG | Ce sont des **lignes de secours** (standby) à Dijon et Nice. **Aucun reboot automatique.** |
| **Un seul** watchdog central | **4 instances** : Dijon (master + slave), Nice (master + slave). |
| Modèle « série Archer MR », supporté par la lib | Modèle réel : **TL-MR110 indoor N300**, **absent des modèles testés** de `tplinkrouterc6u` (seul le TL-MR110-**Outdoor** v1.0 y figure). |
| Les routeurs sont **joignables sur le LAN** | **Aucun MR110 n'est sur le LAN.** Chacun est sur **son propre WiFi**, atteint via un **Pi Zero 2 W** (eth0 → LAN, wlan0 → WiFi du MR110), **pont de management uniquement** — il ne route pas le trafic de production. |
| Le besoin est l'**audit automatique** intégré au scoring | Le besoin **prioritaire** est d'avoir des **commandes de management** ; l'audit automatique vient ensuite. |

Conséquences structurantes :

1. **Le support MR110 indoor n'est pas acquis.** Spike **go/no-go bloquant**
   (Sprint 1) avant toute écriture de driver, avec plan B écrit.
2. **Il n'existe aujourd'hui aucun chemin réseau** entre les watchdogs et les
   MR110. Il faut le créer (routage + NAT sur le Pi Zero) **avant** de pouvoir
   tester quoi que ce soit. Pré-requis, pas finition.
3. **Le chemin compte trois sauts** (watchdog → Pi Zero → WiFi → MR110). Une
   sonde qui dit seulement « secours injoignable » est inutilisable : il faut
   **attribuer la panne au bon saut**.
4. **Le Pi Zero est un SPOF non surveillé**, et le lien WiFi Pi Zero ↔ MR110 est
   un point de défaillance silencieux.
5. **Découpage en deux phases** (voir §0ter) : cette phase A ne touche pas au
   cœur mono-cible.

Ce qui reste valide du PRD de juin : l'abstraction `RouterDriver`, et les
contraintes de compatibilité prod **C1→C4**. Elles sont reprises ici.

## 0bis. Topologie de référence (par site)

```
    ┌────────────── LAN du site ──────────────┐
    │                                          │
  [ USG ]      [ watchdog master ]  [ watchdog slave ]
 (lien principal,        │                 │
  surveillance actuelle) └────┬────────────┘
                              │  route statique : <subnet MR110> via <IP LAN Pi Zero>
                              ▼
                        [ Pi Zero 2 W ]        eth0 = LAN du site, **alimenté en PoE**
                              │                wlan0 = WiFi du MR110
                              │  IP forwarding + NAT   (pont de MANAGEMENT seul)
                              ▼
                        ((( WiFi )))           ← saut fragile, silencieux
                              │
                        [ TL-MR110 ]           équipement à piloter, 4G
```

Le Pi Zero ne porte **pas** le trafic de production : le chemin de bascule réel
du site ne passe pas par lui (voir H1, §3).

**Le Pi Zero est alimenté en PoE** — un seul câble lui apporte le réseau *et*
le courant. Trois conséquences :

- **Sa position est figée par le câblage**, pas choisie. Le saut WiFi existe
  parce que le MR110, lui, est placé selon la réception 4G. C'est la contrainte
  qui pèse sur les variantes de topologie (§10.3) : elles supposent toutes une
  adjacence Ethernet entre deux équipements dont les emplacements sont dictés
  par des impératifs différents.
- **Son alimentation dépend du switch.** Un `Hop.BRIDGE` en échec peut donc
  signifier : Pi Zero planté, **port PoE coupé**, budget PoE dépassé, ou câble.
  Ce n'est plus « le Pi Zero est mort » — le message opérateur doit rester
  prudent sur la cause.
- **En contrepartie, il devient redémarrable à distance** en coupant/rallumant
  le port PoE (cf. §10.4).

## 0quater. Caractéristiques du matériel et ce qu'elles impliquent

**TP-Link TL-MR110** — routeur 4G LTE Cat 4, WiFi N300 **2,4 GHz uniquement**,
2 antennes 4G amovibles, **2 ports LAN Ethernet**, SIM tout opérateur, jusqu'à
32 appareils.

Quatre conséquences directes sur la conception :

| Caractéristique | Conséquence |
|---|---|
| **WiFi 2,4 GHz mono-bande** | Le saut Pi Zero ↔ MR110 est sur la bande la plus encombrée, sans repli 5 GHz. C'est le maillon le plus fragile du chemin d'audit — ce qui justifie `Hop.WIRELESS` comme saut sondé à part, et le RTT comme indicateur de qualité. |
| **LTE Cat 4** (~150 Mb/s desc. / 50 montant théoriques) | Plafond modeste : les seuils de détection d'usage (§ Sprint 4) se calibrent sur cet ordre de grandeur, pas sur celui du lien principal. Un secours saturé est un état à savoir distinguer d'un secours inactif. |
| **2 ports LAN Ethernet** | Rend l'évolution WAN2 (§10.2) triviale — un câble. Ouvre aussi une **simplification immédiate** du chemin d'audit (§10.3). |
| **32 appareils max** | `clients_total` est un signal exploitable pour la détection d'usage, et une limite à connaître si le secours doit réellement servir un site. |

## 0ter. Découpage en deux phases — et pourquoi

Le besoin exprimé est d'abord **du management**. Ça tombe bien : c'est aussi le
découpage le moins risqué.

| | **Phase A — ce PRD (1.9.0)** | **Phase B — PRD suivant (1.10.0)** |
|---|---|---|
| Contenu | Chemin réseau, driver TP-Link, commandes opérateur (API + Telegram), dashboard, Prometheus, quota, usage | Moteur multi-cible, `UsgDriver`, rôles `primary`/`backup`, readiness intégrée au scoring, alerting automatique, exclusivité de polling complète |
| Touche `watchdog.py` / `state.py` | **Non** | Oui, en profondeur |
| Risque de régression USG | **Quasi nul** | Élevé — c'est le refactor du cœur |
| Valeur livrée | Piloter et voir les secours | Être alerté automatiquement |

L'intérêt du découpage : la phase A livre l'essentiel de la valeur **sans
toucher à la boucle de surveillance**. Les MR110 y sont des **équipements
pilotables déclarés**, pas des cibles de la boucle de scoring. Le refactor
risqué est isolé en phase B, où il pourra être jugé sur ses propres mérites — y
compris la décision de ne pas le faire.

---

## 1. Problème & objectif

Dijon et Nice disposent chacun d'une **ligne de secours 4G TP-Link MR110**.
Aujourd'hui ce sont des angles morts complets : le watchdog ne les voit pas, et
il n'existe même pas de chemin réseau pour les interroger. Un backup non testé
n'est pas un backup — on découvre qu'il est HS (SIM expirée, plus de signal,
quota épuisé, WiFi décroché) au moment précis où on en a besoin.

**Objectif de la phase A** : pouvoir **piloter** ces équipements depuis les
outils existants (API, Telegram) et **voir leur état** (dashboard, Prometheus,
quota), sans jamais les redémarrer automatiquement et sans toucher à la
surveillance USG.

**Objectif corollaire, non négociable** : quand le secours est injoignable, dire
**où** ça casse — Pi Zero, WiFi, ou MR110. Sinon l'alerte ne fait que déplacer
le travail de diagnostic.

**Non-objectif** : faire du MR110 une cible de reboot automatique.

## 2. Correctness Discovery

- **Audience** : l'opérateur (toi). Décisions pilotées : *« je veux voir/agir
  sur le secours de Dijon depuis Telegram, tout de suite »*, et *« si le lien
  principal tombe, est-ce que le secours est en état ? sinon, qu'est-ce qui
  manque — Pi Zero, WiFi, signal, SIM, quota ? »*
- **Vérification** :
  (a) sans équipement `TPLINK_*` déclaré, le comportement est strictement
      identique à la 1.8 ;
  (b) `/lte` depuis Telegram retourne l'état réel d'un MR110 de Dijon ;
  (c) chaque saut coupé (Pi Zero, WiFi, MR110) produit une cause **distincte**
      et correctement attribuée ;
  (d) `get_lte_status` mocké → RSRP/RSRQ/SNR/conso visibles dans l'API, le
      dashboard et `/metrics`.
- **Failure definition** : impossible de piloter le secours ; OU le watchdog dit
  « secours HS » sans dire où ça casse ; OU une commande reboote un équipement
  qui portait du trafic sans avertissement ; OU la surveillance USG régresse.
- **Danger definition** : reboot d'un secours **pendant** qu'il porte le trafic
  (= couper le site) ; lock de session admin ; fuite du mot de passe TP-Link ;
  épuisement du quota par le polling ; **exposition de l'interface
  d'administration du MR110 à tout le LAN** via une route trop large.
- **Uncertainty policy** : tout champ LTE absent ou illisible ⇒ `None` et
  readiness `UNKNOWN` (jamais `OK` par défaut, jamais `DEGRADED` non plus). Une
  indisponibilité non attribuable à un saut précis est rapportée comme telle,
  jamais imputée au MR110 par défaut. Un driver ne lève jamais. Une commande que
  le spike n'a pas vue répondre n'est **pas exposée**.
- **Risk tolerance** : **zéro** régression USG (priorité absolue). Métriques 4G
  best-effort. Si le MR110 indoor n'est pas pilotable par la lib, le mode
  dégradé (joignabilité + attribution de panne, sans commandes LTE) est un
  livrable acceptable.

## 3. Scope

### In scope (phase A)
- **Chemin réseau d'audit** : routage + NAT sur le Pi Zero, route statique côté
  watchdogs, runbook reproductible sur les 2 sites.
- Spike de compatibilité **TL-MR110 indoor** (go/no-go bloquant) + plan B écrit.
- Contrat `RouterDriver` + `TplinkDriver`.
- **Sonde étagée avec attribution de panne** : Pi Zero → saut WiFi → MR110 →
  défaut de route.
- **Commandes de management opérateur** : API `/api/tplink/*` + Telegram `/lte`
  (état, détail, reboot avec confirmation, SMS/USSD selon firmware).
- **Readiness** calculée et affichée (SIM, attach, seuils signal, intégrité du
  chemin) : `OK` / `DEGRADED` / `UNKNOWN`.
- **Quota data** : conso, %, jour de reset, détection de remise à zéro du
  compteur, alerte à seuil.
- **Détection d'usage du secours** (voir H1).
- Observabilité : dashboard, `/metrics`, notifications.
- Contraintes prod **C1→C4** + docs + release 1.9.0.

### Hypothèses explicites

- **H1 — Le chemin de bascule réel du site n'est pas observable par le
  watchdog.** Le Pi Zero étant un pont de management, on ne peut pas voir la
  bascule depuis le lien principal (l'approche « WAN2 de l'USG via
  `multiwan.py` », envisagée en juin, ne s'applique pas **tant que** le MR n'est
  pas câblé sur le WAN2 — évolution souhaitée mais non court terme, cf. §10).
  **Conception retenue** : détecter l'**usage** du secours depuis le MR110
  lui-même — débit rx/tx, clients associés, conso qui décolle. Ce signal vaut
  **quel que soit** le mécanisme de bascule, y compris manuel. C'est
  volontairement une détection *a posteriori* (« le secours sert »), pas une
  détection d'événement de bascule, et les messages doivent le dire.

### Out of scope (loggé, non traité)
- **Tout le contenu de la phase B** : moteur multi-cible, `UsgDriver`, rôles
  intégrés au scoring, alerting automatique sur readiness, exclusivité de
  polling complète entre master et slave (cf. §10).
- **Reboot automatique d'un équipement TP-Link** — exclu par décision explicite.
- **Faire du Pi Zero un routeur de production** — il reste un pont de management.
- **Câbler le MR sur le WAN2 de l'USG** — souhaité à terme, hors court terme (§10).
- Renommage du projet (cf. §9 — reporté, non urgent).
- DDNS / Tailscale / Backup UniFi pour les équipements TP-Link.
- Bascule **pilotée** par le watchdog — lecture seule uniquement.
- Supervision générale du Pi Zero en tant qu'hôte (CPU, disque, updates) : seule
  sa participation au chemin d'audit est surveillée.

## 4. Contraintes techniques

- Python ≥ 3.11 (projet) ∩ ≥ 3.10 (lib) → OK.
- Nouvelle dep : `tplinkrouterc6u` **pinné** (version fixée à l'issue du spike),
  tire `requests`, `pycryptodome`, `macaddress`. Installée **uniquement sur les
  hôtes watchdog**, jamais sur le Pi Zero (C7).
- `TplinkDriver` : `TplinkRouterProvider.get_client(host, password)`
  (auto-détecte CBC/GCM), `authorize()` / `logout()` en **try/finally**
  systématique, tous les appels wrappés, timeouts explicites.
- Immutabilité : `RouterHealth`, `RouterMetrics`, `RouterReadiness` frozen.
- Secrets : mot de passe TP-Link via env uniquement, `.env` 600, **jamais**
  loggé ni exposé par `/api/config`.
- `never raise` pour tout driver.
- **Budget de polling** : lectures mises en cache (défaut 60 s) et sérialisées
  par équipement. Chaque accès consomme une session admin, traverse un lien WiFi
  et un peu de data.

### 4bis. Contraintes de compatibilité PROD (auto-updater) — BLOQUANTES

L'auto-updater tire `main` automatiquement : 1.9.0 sera déployée sur **les 4
instances** sans intervention.

- **C1 — Import 100 % paresseux de `tplinkrouterc6u`.** Jamais au niveau module.
  `updater/preflight.py` fait `import usg`, `import watchdog`,
  `import connectivity` : une chaîne d'import qui tire la lib ferait échouer le
  preflight → auto-update avortée + rollback. Test : `python -c "import watchdog"`
  sans la lib.
- **C2 — L'auto-updater n'installe pas les deps.** `updater/update.py` ne fait
  aucun `pip install`. À enrichir : relancer `pip install -r requirements.txt`
  quand `requirements.txt` change, idempotent, loggé, échec → rollback. → Sprint 5.
- **C3 — Contrat `/api/state` rétro-compatible.** En phase A, `state.py` n'est
  **pas modifié**, donc C3 est satisfaite par construction. Les nouveaux
  endpoints `/api/tplink/*` s'**ajoutent**. À re-vérifier en phase B, où le
  risque redevient réel (rollout non atomique sur une paire HA).
- **C4 — Métriques Prometheus legacy préservées.** `usg_watchdog_*` sans label
  reste émis à l'identique ; les métriques labellisées sont **ajoutées**.

### 4ter. Contraintes de topologie

- **C5 — Session admin TP-Link unique.** Les routeurs MR n'acceptent qu'une
  session à la fois. En phase A le management est **à la demande** (pas de
  polling continu) : verrou local par équipement, `logout()` garanti, réessai
  unique avec message clair si la session est occupée. **L'exclusivité complète
  entre master et slave appartient à la phase B**, où le polling devient continu.
- **C6 — Aucune action destructive automatique.** Reboot, SMS et USSD ne
  proviennent que d'une commande opérateur explicite, avec confirmation pour le
  reboot, et sont tracés dans l'`EventLog` avec leur origine.
- **C7 — Chemin d'audit via le Pi Zero, sans code sur le Pi Zero.** IP
  forwarding + NAT sur le Pi Zero, route statique côté watchdogs. Conséquences :
  - aucune dépendance Python installée sur le Pi Zero, rien à y maintenir ;
  - le driver n'a **aucune connaissance** du Pi Zero : il parle à une IP, le
    routage est un détail d'infrastructure — c'est précisément ce qui rendra la
    migration vers le WAN2 (§10) sans impact sur le code ;
  - la route est posée **sur les hôtes watchdog uniquement**, pas sur l'USG ni
    en DHCP : l'admin du MR110 ne doit pas devenir joignable depuis tout le LAN.
- **C8 — Une route absente n'est pas une panne de secours.** Si la route ou le
  NAT manquent, l'instance verra le MR110 injoignable. Ce cas est rapporté comme
  **défaut de configuration du chemin d'audit** (`Hop.ROUTE`), jamais comme
  « secours HS » : sinon la première mise à jour système qui efface une route
  déclencherait une fausse alerte critique.

## 5. Critères d'acceptation (phase A)

- [ ] **Chemin réseau** : depuis un hôte watchdog de Dijon, le MR110 est
      joignable à travers le Pi Zero ; runbook rejoué avec succès sur Nice
- [ ] **C7** : rien installé sur le Pi Zero ; route posée sur les hôtes
      watchdog uniquement
- [ ] **Spike** : rapport écrit, verdict explicite (`FULL` / `DEGRADED` /
      `UNSUPPORTED`), modèle réel confirmé, **tableau des commandes disponibles**,
      version de lib retenue
- [ ] **Aucun équipement `TPLINK_*` déclaré → comportement strictement identique
      à la 1.8** (dashboard, API, metrics, boucle)
- [ ] `TplinkDriver` conforme au contrat ; aucune méthode ne lève
- [ ] **Attribution de panne** : Pi Zero / WiFi / routeur / route absente →
      quatre causes distinctes et exactes
- [ ] **C8** : route absente rapportée comme défaut de configuration
- [ ] Commandes opérateur : `GET /api/tplink`, `/api/tplink/<id>`,
      `POST …/refresh`, `POST …/reboot` (confirmation requise)
- [ ] Telegram : `/lte`, `/lte <id>`, `/lte reboot <id>`, `/help` à jour
- [ ] SMS / USSD exposés **uniquement** si le spike les a validés
- [ ] **C6** : reboot/SMS/USSD jamais automatiques, tracés avec leur origine ;
      avertissement si l'équipement porte du trafic
- [ ] Readiness `OK` / `DEGRADED` (raisons chiffrées) / `UNKNOWN` calculée et affichée
- [ ] Quota : conso, %, jour de reset, **détection de remise à zéro du compteur**
- [ ] Usage du secours détecté (débit / clients / conso) avec anti-rebond
- [ ] Dashboard : carte par équipement, badge readiness, **saut en panne**,
      bloc 4G, quota, bandeau d'usage
- [ ] **C4** : `/metrics` expose toujours les `usg_watchdog_*` sans label
- [ ] **C1** : `python -c "import watchdog"` réussit **sans** `tplinkrouterc6u`
- [ ] **C2** : l'auto-updater installe les deps quand `requirements.txt` change
- [ ] `watchdog.py` et `state.py` **non modifiés** sur toute la phase A
- [ ] Aucun secret dans l'API, le dashboard ou les logs
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] README + DEPLOY + runbook à jour

---

## 6. Décomposition en sprints

| # | Sprint | But | Risque |
|---|---|---|---|
| 1 | Chemin réseau Pi Zero + spike MR110 + contrat `RouterDriver` | Créer l'accès, savoir si c'est faisable, poser le contrat | **Go/no-go** |
| 2 | `TplinkDriver` + sonde étagée | Piloter le routeur, attribuer les pannes | Moyen |
| 3 | **Commandes de management (API + Telegram)** | **Le livrable attendu en premier** | Moyen |
| 4 | Observabilité : dashboard, Prometheus, quota, usage | Voir sans taper une commande | Faible |
| 5 | Auto-updater, docs, release 1.9.0 | Livrer sans casser les 4 instances | Moyen |

**Gates** :
- *Dans le Sprint 1, après la partie réseau* : sans chemin joignable, le spike ne
  peut pas tourner. Ne pas enchaîner « à blanc ».
- *Après Sprint 1* : si le verdict est `UNSUPPORTED`, re-cadrer les sprints 2→5
  sur le plan B avant de continuer.

## 7. Risques & mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| **MR110 indoor non supporté par la lib** | **Critique** | Spike go/no-go Sprint 1 **avant** tout code driver + plan B écrit |
| **Aucun chemin réseau vers les MR110 aujourd'hui** | **Critique** (bloque tout) | Route + NAT sur le Pi Zero, traité en premier au Sprint 1 |
| **Reboot d'un secours qui porte du trafic = site coupé** | **Critique** | C6 : confirmation en deux temps + avertissement si débit/clients non nuls |
| **Pi Zero = SPOF non surveillé du chemin d'audit** | Élevé | Sonde étagée : le Pi Zero est un saut explicite, sa panne est nommée |
| **Lien WiFi qui décroche silencieusement** | Élevé | Saut WiFi sondé séparément (RTT + perte), qualité historisée |
| **Route absente → fausse alerte « secours HS »** | Élevé | C8 : attribution explicite au défaut de configuration |
| **Admin du MR110 exposée à tout le LAN** | Élevé | C7 : route sur les hôtes watchdog seulement, jamais sur l'USG ni en DHCP |
| Régression de la surveillance USG | Critique | Phase A ne modifie **ni** `watchdog.py` **ni** `state.py` ; vérifié par frontières de sprint |
| Preflight cassé à l'auto-update | Critique | C1 : import paresseux + test sans lib |
| Lib absente après auto-update | Élevé | C2 : `pip install` sur diff `requirements.txt` |
| Collision de session admin master/slave | Moyen (phase A) | C5 : verrou local, `logout()` garanti, réessai unique — complet en phase B |
| Grafana / alertes cassées par les labels | Moyen | C4 : métriques legacy conservées |
| Polling qui consomme le quota | Moyen | Cache 60 s, lectures à la demande, aucun trafic de test |
| Mismatch cipher CBC/GCM | Moyen | `get_client()` auto-détecte ; version validée au spike |
| Champs LTE absents (firmware) | Faible | Champs `None`, readiness `UNKNOWN`, commande non exposée si non validée |
| Fuite mot de passe TP-Link | Élevé | Env only, `.env` 600, jamais loggé, exclu de `/api/config` |
| Compteur data qui reset | Moyen | Détection de décroissance + jour de facturation configurable |
| SMS/USSD déclenchés par erreur (coût) | Moyen | Jamais implicites, jamais en réessai automatique |
| Lib GPLv3 vs distribution | Faible (perso) | Tracé dans l'ADR |

## 8. Definition of Done

Tous les AC §5 cochés, 5 sprints verts, coverage ≥ 80 %, `validate.sh` vert,
docs à jour, v1.9.0 taggée, `dev` synchronisé avec `main`, issue de phase B
ouverte — et **vérification terrain** : depuis Telegram, `/lte` retourne l'état
réel du secours de Dijon ; `/lte reboot` demande confirmation et fonctionne ; et
débrancher volontairement le WiFi du Pi Zero produit un message qui **nomme le
saut WiFi**, pas « MR110 HS ».

## 9. Renommage du projet — décision : reporté

`usg-watchdog` devient un nom partiellement faux dès qu'un TP-Link est piloté.
Décision retenue (confirmée le 2026-08-12) : **on ne renomme pas maintenant**,
ce n'est pas urgent.

Coût réel : unit systemd, chemin `/opt/usg-watchdog`, user système, logrotate,
chemins de logs et d'événements, tags git consommés par l'auto-updater, préfixe
des métriques Prometheus (`usg_watchdog_*`, référencé par les dashboards Grafana
existants), et une migration coordonnée des **4 instances** qui se mettent à
jour toutes seules. Ce n'est pas un `sed`.

**Ce que ce PRD fait pour préparer le terrain, sans rien renommer :**
l'abstraction `RouterDriver` retire au mot « USG » son statut de concept central
du code — il redevient un vendor parmi d'autres.

**Trigger de réouverture** : ≥ 3 vendors supportés, ou publication/distribution
du projet. Si le trigger tombe, la voie la moins risquée est un renommage **en
deux temps** : d'abord un alias (unit systemd `Alias=`, double émission des
métriques sous les deux préfixes), puis suppression de l'ancien nom une version
plus tard.

## 10. Suites prévues

### 10.1 Phase B — moteur multi-cible et audit automatique (PRD séparé, ~1.10.0)

- Extraction d'`UsgDriver` derrière le contrat `RouterDriver`.
- `MonitoredTarget` : score, circuit-breaker et cooldowns **par cible** ;
  suppression des trackers de latence singletons de `connectivity.py`.
- Rôles `primary` / `backup` intégrés au moteur, avec **C6 renforcée en
  invariant structurel** : aucun chemin automatique ne peut atteindre `reboot()`
  d'une cible `backup`.
- Alerting automatique sur la readiness (dégradé / redevenu prêt), au changement
  d'état.
- **C5 complète** : une seule instance du site interroge le MR110 ; l'autre
  republie l'état du peer avec l'âge de la donnée ; reprise après
  `PEER_TAKEOVER_DELAY`.
- **C3 redevient critique** : `state.py` est modifié et le rollout n'est pas
  atomique sur une paire HA (un master 1.10 et un slave 1.9 coexistent).

C'est le refactor risqué. Le fait que la phase A livre déjà l'essentiel de la
valeur permet de le juger sur ses propres mérites — **y compris de décider de ne
pas le faire**.

### 10.2 Câblage du MR sur le WAN2 de l'USG (souhaité, non court terme)

Objectif à terme : relier le MR au **WAN2 de l'USG** plutôt que de le laisser
isolé derrière le Pi Zero. Le MR110 disposant de **2 ports LAN Ethernet**, c'est
matériellement un câble : un port LAN du MR110 vers le WAN2 de l'USG.

**Impact sur le code : nul.** C'est précisément ce que garantit C7 — le driver
parle à une IP et ignore complètement le Pi Zero. Le jour du câblage, il suffit
de supprimer la route statique et le NAT ; le driver, les commandes, le
dashboard et les métriques continuent de fonctionner à l'identique.

**Le Pi Zero reste** (décision du 2026-08-12), y compris après ce câblage. Ce
n'est pas de la redondance inutile : une fois le MR sur le WAN2, la voie
« naturelle » pour l'atteindre passerait par l'USG — c'est-à-dire **par
l'équipement dont on surveille précisément la défaillance**. Le pont Pi Zero
reste alors un **chemin de management hors bande**, indépendant de l'USG : il
permet d'interroger et de redémarrer le secours même quand l'USG est en panne,
ce qui est exactement le moment où on en a besoin.

Ce que ce câblage **apporterait en plus** :

- La bascule devient observable côté USG, et le chemin d'audit gagne une seconde
  voie (par l'USG) en plus du pont hors bande.
- `src/multiwan.py` (détection de l'interface WAN active via la table de routage
  de l'USG, déjà présent) devient exploitable → **vraie détection d'événement de
  bascule**, à ajouter **en plus** de la détection d'usage de H1, pas à la place :
  l'une voit la bascule, l'autre voit l'utilisation réelle.
- La bascule devient automatique côté USG, ce qui change la nature du service
  rendu — et rouvrirait la question de la readiness comme critère bloquant.

*Modèle* : il s'agit du **MR-110** ici aussi (confirmé le 2026-08-12) — même
matériel que les équipements déjà en place, pas d'un modèle différent. Le gate
de compatibilité du Sprint 1 vaut donc pour cette évolution comme pour la phase
A : si le MR110 indoor n'est pas pilotable par la lib, ni l'un ni l'autre ne
l'est.

### 10.3 Fiabiliser le saut WiFi — option à évaluer au Sprint 1

> **Décision préalable (2026-08-12) : le Pi Zero 2 W est conservé.** Toute
> variante qui le supprimerait du chemin est écartée. Ce qui reste ouvert est la
> **nature du saut** entre le Pi Zero et le MR110, pas l'existence du pont.
>
> Cette décision préserve **C7** : l'interface d'administration du MR110 reste
> joignable depuis les seuls hôtes watchdog, via une route dédiée — et non
> depuis tout le LAN du site, ce qu'aurait impliqué un raccordement direct.

Le MR110 a **2 ports LAN Ethernet**. Le chemin d'audit actuel
(watchdog → Pi Zero → **WiFi 2,4 GHz** → MR110) contient donc un maillon fragile
qui n'est pas une fatalité matérielle. Deux variantes méritent d'être évaluées
sur place, avant de figer la conf réseau du Sprint 1 :

**Prérequis de la variante (a) : l'adjacence physique.** Le Pi Zero est alimenté
en PoE, donc posé là où arrive le câble ; le MR110 est posé là où passe la 4G.
Le pont WiFi existe très probablement **parce que ces deux points ne coïncident
pas**. La variante (a) n'est pas évaluable sans avoir relevé la distance réelle
entre les deux, par site — c'est la première chose à regarder, avant toute
considération technique. Si les deux équipements sont éloignés, (c) s'impose de
fait et il n'y a pas d'arbitrage à rendre.

- **(a) Pi Zero relié au MR110 par Ethernet** au lieu du WiFi. Le pont et le
  routage restent identiques ; seul le saut change de nature. Supprime le point
  de défaillance le plus probable du chemin. *Contraintes* : le Pi Zero 2 W n'a
  pas d'Ethernet natif — la liaison LAN actuelle passe déjà par un adaptateur
  USB, il en faudrait un second, donc un hub, dont l'alimentation doit tenir
  dans le budget du splitter PoE. Et il faut un câble court entre les deux
  équipements.
- **(b) MR110 raccordé directement au LAN du site** — ~~supprimerait le Pi Zero,
  le WiFi, la route et le NAT~~. **Écartée** : conserver le Pi Zero est une
  décision prise. Conservée ici pour mémoire, et parce qu'elle documente ce que
  le pont apporte en échange de sa complexité — l'isolation de l'admin du MR110
  vis-à-vis du LAN (C7).

**Ce que ça ne change pas** : le code. C7 garantit que le driver parle à une IP
sans rien savoir du chemin. Ces variantes se décident donc au Sprint 1 sur des
critères d'infrastructure, sans impact sur les sprints 2 à 5 — au-delà du fait
que certains `Hop` deviendraient sans objet, ce que la sonde étagée gère déjà
(un saut non configuré n'est pas sondé).

### 10.4 Redémarrage du Pi Zero par le port PoE — candidat, hors périmètre

Le Pi Zero étant alimenté en PoE, **couper puis rallumer son port de switch le
redémarre**. Ça transforme un « le pont de management est planté » — qui
aujourd'hui impose un déplacement sur site — en une commande à distance.

Ce serait la suite logique des commandes de management du Sprint 3 : le chemin
d'audit deviendrait réparable **de bout en bout** à distance, le Pi Zero par le
PoE et le MR110 par son API.

**Hors périmètre de la phase A**, pour deux raisons : ça sort du domaine
TP-Link (c'est une action sur le switch, via l'API du contrôleur si le switch
est managé), et ça ajoute une action destructive de plus à sécuriser. À évaluer
séparément, en vérifiant d'abord que le port du Pi Zero est bien sur un switch
pilotable — un injecteur PoE passif ne se commande pas.
