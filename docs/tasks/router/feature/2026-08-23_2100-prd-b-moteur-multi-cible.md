# PRD B — Moteur multi-cible

- **Catégorie** : feature
- **Date** : 2026-08-23
- **Auteur** : Jerome Soyer
- **ADR** : [docs/adr/0001-multi-vendor-router-monitoring.md](../../../adr/0001-multi-vendor-router-monitoring.md)
- **Version cible** : **2.4.0** (minor) — voir §3, le périmètre complet est scindé en 2.4.0 et 2.5.0
- **Branche** : `dev` → PR → `main`
- **Dépend de** : [A1 — Pilotage](2026-08-20_1618-a1-pilotage-tplink/spec.md) livré (2.1.0 + 2.1.1),
  Ntfy-first livré (2.2.0), [A2 — Exposition & Home Assistant](2026-08-20_1618-a2-exposition-ha/spec.md) livré (2.3.0)
- **Esquissé par** : A1 §9.1, A2 §4 « Out of scope »
- **Suite** : PRD B2 — scoring et alerting multi-cible (2.5.0), §14

---

## 1. Problème & objectif

Le cœur de Vigil est **mono-cible**. `watchdog.py` et `state.py` n'ont jamais été
modifiés depuis A1 — c'était l'invariant qui rendait A1 et A2 quasi sans risque.
La contrepartie est arrivée à échéance : tout ce qui a été construit depuis
(drivers, registre d'équipements, readiness, quota, devices Home Assistant)
**vit à côté du moteur, pas dedans**.

Concrètement, à la fin d'A2 :

- l'USG est surveillé par du code qui **ne passe pas** par le contrat
  `RouterDriver` posé en A1 — il n'existe pas d'`UsgDriver` ;
- le score, le circuit-breaker, les cooldowns et le backoff SSH sont des
  **champs plats** de `WatchdogState`, sans notion de « quelle cible » ;
- `RouterRole.PRIMARY` / `RouterRole.BACKUP` existent dans l'enum **mais
  n'ont aucun effet sur le moteur** : C6 (jamais de reboot automatique d'un
  secours) est tenue parce que le moteur ignore les secours, pas parce qu'il
  refuse de les rebooter ;
- la readiness d'un secours n'est calculée que **quand on la demande**, et
  n'alerte jamais d'elle-même.

**Objectif de PRD B** : faire du moteur un moteur **à cibles**, où l'USG est
une cible parmi d'autres — la seule de rôle `PRIMARY`, la seule redémarrable
automatiquement — et où le rôle d'une cible détermine **structurellement** ce
que le moteur a le droit de lui faire.

Quatre livrables, dans cet ordre de dépendance :

1. **`UsgDriver`** implémentant `RouterDriver` pour l'USG, réutilisant `usg.py`
   et `connectivity.py` sans les réécrire.
2. **Scoring et circuit-breaker paramétrés par cible** — `MonitoredTarget`
   porte score, seuil, cooldowns, backoff, compteurs journaliers.
3. **Les rôles dans le scoring** — une `BACKUP` dégradée n'entre **jamais**
   dans le score de la `PRIMARY` ; elle produit des alertes de readiness.
4. **L'alerting automatique sur la readiness des secours** — aujourd'hui
   uniquement à la demande. Un backup non testé n'est pas un backup ; un backup
   testé dont personne n'est prévenu qu'il est mort ne vaut pas mieux.

**Non-objectif, inchangé depuis A1** : le reboot automatique d'un équipement
`BACKUP`. PRD B ne relâche pas C6 — il la **durcit**, en la faisant passer d'une
garde applicative à un invariant de structure (C24).

**Ce que ce PRD n'est pas** : une extension fonctionnelle. C'est une **refonte
du cœur d'un système de production en haute disponibilité**, sur une flotte de
4 Raspberry Pi qui se mettent à jour toutes seules. La valeur utilisateur
immédiate est faible ; le risque est le plus élevé de toute la séquence. A1 §9.1
le disait déjà : *« C'est le refactor risqué […] il pourra être jugé sur ses
propres mérites — y compris la décision de ne pas le faire. »* Ce document est
écrit pour rendre cette décision possible, pas pour la présumer.

## 2. État des lieux mesuré

Relevé sur `dev` au 2026-08-23 (Vigil 2.2.0). Les chiffres ci-dessous ne sont
pas des estimations : ils cadrent la taille réelle du chantier.

| Constat | Mesure | Conséquence |
|---|---|---|
| Champs de `WatchdogState` intrinsèquement mono-cible | **19 sur ~25** | Ce n'est pas « ajouter une dimension », c'est **déplacer les trois quarts de l'état** sous une clé de cible |
| Points de couplage USG en dur dans `watchdog.py` | `from usg import reboot_usg` (l.53), `reboot_usg()` (l.476 et l.845), `check_connectivity()` (l.530), `_build_state()` (l.771 et l.1030) | Six points seulement — le couplage est **concentré**, c'est la bonne nouvelle |
| Paramétrage de la cible | Aucun. `USG_IP`, `PING_TARGETS`, `USG_SSH_KEY`… sont lus **au niveau module** par `usg.py` et `connectivity.py` | Aucune fonction du chemin SSH/ping n'accepte de paramètre de cible : c'est le vrai coût du sprint 1 |
| Trackers de latence | Singletons de module dans `connectivity.py` (`gateway_latency`, `internet_latency`) | À instancier par cible (déjà identifié en A1 §9.1) |
| Cadencement | **Aucun thread d'ordonnancement.** Tout est `cycle_count % N` dans une unique `while True` avec `time.sleep(CHECK_INTERVAL)` | La thread-safety du projet repose sur *un seul écrivain* + swap atomique. Introduire un thread par cible **détruit cet argument** (§6.1) |
| Threads existants | 2 persistants : serveur HTTP, publisher MQTT | Les deux sont **lecteurs** de l'état, jamais écrivains |
| Surface de test du cœur | `tests/test_watchdog.py` = **2 424 lignes** | C'est l'actif le plus précieux du chantier : le filet de non-régression existe déjà (§9) |

**Champs mono-cible à déplacer** : `failure_score`, `was_degraded`,
`last_reboot_time`, `grace_until`, `consecutive_reboots`, `reboots_today`,
`surveillance_only`, `consecutive_ssh_failures`, `last_ssh_attempt_time`,
`isp_outage_detected`, `outage_start_time`, `outage_reboot_count`,
`outage_reboot_helped`, `threshold_reached_time`, `gateway_ok`,
`internet_ok_count`, `internet_total`, `gateway_rtt_ms`,
`internet_avg_rtt_ms`, `latency_degraded`.

**Champs qui restent globaux** : `version`, `timestamp`, `uptime_seconds`,
`instance_priority`, `peer_*`, `isp_status_*`.

Le contrat posé en A1 est intact et suffisant en lecture :

```python
@runtime_checkable
class RouterDriver(Protocol):
    vendor: str  # "usg" | "tplink"
    def health(self) -> RouterHealth: ...
    def metrics(self) -> RouterMetrics: ...
    def readiness(self) -> RouterReadiness: ...
    def reboot(self) -> bool: ...
    def test_connection(self) -> bool: ...
```

### 2.1 La vraie surface de compatibilité n'est pas `/api/state`, c'est `from_dict`

Relevé décisif pour C22 : `peer.py` **ne lit pas des clés JSON à la carte**. Il
reconstruit un objet complet.

```python
def query_peer(peer_ip=PEER_IP, peer_port=PEER_PORT, retries=3, timeout=5) -> WatchdogState | None
def should_reboot(my_state: WatchdogState, gateway_ok: bool) -> tuple[bool, str]
def check_divergence(my_score: int, my_gateway_ok: bool, my_inet_count: int) -> str | None
def get_peer_info() -> dict[str, str | int]
```

`query_peer()` fait un `GET /api/state` puis un `WatchdogState.from_dict(...)`,
et **retourne `None` en cas d'échec — quelle qu'en soit la cause**. Or `None`
signifie, pour toute la suite du raisonnement, *« peer injoignable »* : la
primaire (`instance_priority == 1`) reboote alors directement, et la secondaire
prend le relais après `PEER_TAKEOVER_DELAY`.

**Conséquence** : si une 2.3.x échoue à désérialiser l'état d'une 2.4.0, elle ne
conclut pas « format inconnu », elle conclut « mon peer est mort » — et agit en
conséquence. Le chemin du double reboot ne passe donc pas par une clé manquante
mais par **une exception de désérialisation silencieusement convertie en
absence**. C'est le risque n°1 de ce PRD, et il se joue dans `from_dict`, pas
dans le sérialiseur HTTP.

Champs de `WatchdogState` effectivement consommés par `peer.py` :
`instance_priority`, `failure_score`, `surveillance_only`, `last_reboot_time`,
`timestamp`, `threshold_reached_time`, `threshold`, `gateway_ok`,
`internet_ok_count`, `internet_total`. Seuil de divergence :
`_DIVERGENCE_SCORE_GAP = 6`.

### 2.2 Le registre d'A1 est déjà multi-équipements

`managed_devices.py` expose `ManagedDeviceRegistry` (instance globale
`registry`) : `device_ids()`, `get_status(device_id, force=False)`,
`list_devices()`, `check(device_id)`, `request_reboot(device_id, origin)`,
`confirm_reboot(token, origin, expected_device_id=None)`, plus
`bootstrap(event_log)`. Cache `dict[str, tuple[float, dict]]` clé `device_id`,
TTL 60 s sur `time.monotonic()`, verrou de cache global et **un
`threading.Lock` par équipement** (`_device_locks`, créés paresseusement sous
`_registry_lock`). Confirmations déléguées à `confirm.py`
(`request_confirmation` / `validate`, jeton à usage unique, TTL court).

Autrement dit : **le `device_id` existe déjà partout du côté équipements
managés, et nulle part du côté moteur.** PRD B est exactement le travail qui
consiste à faire descendre cette notion dans `watchdog.py`, `state.py` et
`peer.py` — les trois seuls modules qui l'ignorent encore.

**Ce qui manque au contrat pour qu'un `UsgDriver` remplace les appels directs** :
rien de structurel. `RouterHealth` porte déjà `reachable`, `internet_ok`,
`rtt_ms`, `failed_hop`. Il manque en revanche, **côté moteur et non côté
contrat**, la granularité que `compute_cycle_delta(gateway_ok, internet_ok_count)`
consomme aujourd'hui : `internet_ok_count` / `internet_total` (combien de cibles
de ping sur combien) n'ont pas d'équivalent dans `RouterHealth`. Deux voies,
tranchées au Sprint 1 :

- **(a)** enrichir `RouterHealth` de deux champs optionnels
  (`probes_ok: int | None`, `probes_total: int | None`), `None` pour un driver
  qui ne fait pas de sonde multiple — additif, ne casse pas `TplinkDriver` ;
- **(b)** laisser `UsgDriver` exposer une méthode hors contrat.

**(a) est retenue par défaut** : (b) rouvrirait exactement le couplage que le
contrat existe pour fermer, et rendrait le moteur dépendant du vendor.

## 3. Découpage recommandé : deux PRD, pas un

**Recommandation explicite : scinder en B1 (2.4.0) et B2 (2.5.0).**
Ce document spécifie **B1** en entier, et cadre B2 au §14.

| | **B1 — 2.4.0** | **B2 — 2.5.0** |
|---|---|---|
| Livre | L'abstraction : `UsgDriver`, `MonitoredTarget`, état par cible, rôles comme invariant structurel, `peer.py` multi-cible | Le comportement : secours scorés en continu, alerting automatique de readiness, seuils par cible, exposition par cible |
| Cibles déclarées | **Une seule**, `PRIMARY` = l'USG | N cibles, dont des `BACKUP` |
| Critère de succès | **Rien ne change** | **Quelque chose de nouveau se produit** |
| Vérification | Comparaison d'égalité : mêmes décisions, mêmes sorties, mêmes tests | Injection : provoquer une dégradation, vérifier que l'alerte part |
| Rollback | Flag d'environnement par instance (§8) | Désactivation par cible (opt-in) |

**Pourquoi le découpage n'est pas cosmétique.** Les deux moitiés ont des
**stratégies de vérification opposées**, et les mélanger détruit les deux :

1. **L'ambiguïté du diagnostic.** Si B1 et B2 partent ensemble et qu'une
   instance de production se comporte différemment, on ne sait pas si c'est le
   refactor qui a changé une décision ou le nouveau scoring qui en prend une
   nouvelle — et on ne le sait pas **au pire moment**, pendant un incident. La
   seule chose qui rende un refactor de cœur défendable, c'est de pouvoir
   affirmer « aucune sortie n'a bougé ». Ajouter des sorties dans la même
   version rend cette affirmation invérifiable.
2. **La taille.** B1 seul consomme les 5 sprints autorisés (§10) : les rôles, le
   `peer.py` multi-version et la migration de flotte ne laissent pas de place.
   Un PRD à 8 sprints n'est pas un PRD, c'est un projet non décomposé.
3. **La décision de renoncer reste ouverte.** B1 livré, la valeur est
   *structurelle* : le mot « USG » cesse d'être un concept du moteur. B2 devient
   alors un choix, pas une conséquence. Si le parc n'évolue plus, on peut s'y
   arrêter — et A1 §9.5 y gagne aussi (le renommage devient trivial).
4. **Le précédent 2.1.1.** 1 049 tests mockés verts n'avaient pas vu le bug
   `wlan0` ; seule la vérification contre le vrai matériel l'a révélé. Chaque
   version doit donc porter **une seule question terrain**. B1 : « la
   surveillance USG est-elle identique ? ». B2 : « le secours dégradé
   alerte-t-il ? ». Deux questions dans une version, c'est une vérification
   terrain qui ne conclut sur aucune.

**Conséquence sur ce document** : à partir du §4, sauf mention explicite,
« ce PRD » désigne **B1 / 2.4.0**.

## 4. Correctness Discovery

- **Audience** : l'opérateur — mais **indirectement**. B1 ne lui livre rien
  qu'il puisse voir. Son audience réelle est *le mainteneur du moteur*, et la
  décision pilotée est : *« puis-je ajouter une cible sans réécrire la boucle,
  et puis-je le prouver ? »*. L'opérateur, lui, ne pose qu'une question :
  *« ma surveillance USG a-t-elle bougé ? »* — et la réponse attendue est non.
- **Vérification** : (a) `tests/test_watchdog.py` passe **sans qu'un seul test
  n'ait été modifié** ; (b) les clés legacy de `/api/state` sont présentes et
  identiques, assertion **par clé** ; (c) mode fantôme (§8.2) : N cycles sur les
  4 instances de production, **zéro divergence de décision** ; (d) une cible
  `BACKUP` injectée dans le chemin de décision de reboot est **refusée par
  construction**, pas par une branche.
- **Failure definition** : une décision de reboot diffère de celle qu'aurait
  prise la 2.3.0 dans les mêmes conditions ; OU le failover HA se comporte
  différemment pendant la fenêtre de mise à jour mixte ; OU un test de
  non-régression a dû être « ajusté » pour passer ; OU `/api/state` perd ou
  renomme une clé.
- **Danger definition** : **le moteur acquiert le pouvoir de rebooter des
  cibles**. Un rôle mal évalué rend un MR110 redémarrable automatiquement —
  c'est-à-dire couper le site au moment où le secours sert. Second danger :
  pendant la mise à jour non atomique d'une paire HA, deux instances qui ne
  s'entendent plus sur le format de `/api/state` peuvent **rebooter toutes les
  deux** (les deux se croient seules) ou **aucune** (les deux se croient
  secondaires).
- **Uncertainty policy** : une donnée de cible absente ou périmée vaut
  `UNKNOWN`, jamais `OK` — l'âge de la donnée est un champ de premier ordre, pas
  une note de bas de page. Un peer dont le format n'est pas reconnu est traité
  comme un peer **mono-cible en 2.3.x**, jamais comme un peer absent : se croire
  seul est précisément l'erreur qui provoque le double reboot.
- **Risk tolerance** : **zéro** changement observable à périmètre constant.
  C'est le seul critère non négociable de B1. Tout le reste — élégance de
  l'abstraction, nombre de cibles supportées, propreté du modèle — est
  sacrifiable devant lui.

## 5. Scope

### 5.1 In scope (B1 / 2.4.0)

- **`UsgDriver`** implémentant `RouterDriver`, encapsulant `usg.py`
  (reboot SSH) et `connectivity.py` (ping gateway + internet), **sans les
  réécrire** — ils deviennent l'implémentation privée du driver.
- **Paramétrage par cible** de `check_connectivity()` et `reboot_usg()` :
  la configuration (IP, cibles de ping, identifiants SSH, `known_hosts`) est
  **passée**, plus lue au niveau module.
- **Suppression des trackers de latence singletons** de `connectivity.py` :
  une instance par cible, portée par la cible.
- **`MonitoredTarget`** : identité, rôle, driver, seuil, état de scoring, état
  de circuit-breaker, cooldowns, backoff. Exactement **une** cible déclarée en
  2.4.0, de rôle `PRIMARY`.
- **État par cible dans `WatchdogState`** (§6.2), avec les champs plats legacy
  conservés comme **projection** de la cible `PRIMARY`.
- **Enrichissement additif de `RouterHealth`** : `probes_ok` / `probes_total`
  (§2, voie (a)).
- **Les rôles comme invariant structurel (C24)** : le chemin de reboot
  automatique n'est **atteignable** que pour une cible `PRIMARY` ; le score de
  la `PRIMARY` n'a **aucun chemin arithmétique** vers une cible `BACKUP` (C26).
- **`peer.py` multi-cible** avec **négociation de version** (C22) : comparaison
  par cible, repli sur les champs plats face à un peer 2.3.x, divergence
  détectée par cible.
- **`/api/state` additif** (C21) : bloc `targets`, clés legacy intactes.
- **Métriques, `EventLog`, historique** : dimension de cible **ajoutée**,
  legacy sans label préservé (C4 d'A2 reste active).
- **Migration** : flag de moteur, mode fantôme, runbook de bascule de flotte
  (§8), invariants machine-vérifiables, docs, release 2.4.0.

### 5.2 Out of scope

- **Scoring continu et alerting de readiness des secours** → **B2 / 2.5.0**
  (§14). En 2.4.0 les secours restent exactement ce qu'A2 en a fait : pollés,
  exposés, jamais scorés, jamais alertants d'eux-mêmes.
- **Une seconde cadence de polling** — B1 ne crée aucun ordonnanceur (C28).
- **Une seconde cible `PRIMARY`** — hors périmètre, et probablement hors
  périmètre définitif (question ouverte Q2, §12).
- **L'élection du poller** — **livrée par A2 (C12)**. B1 la consomme, ne la
  redéfinit pas et n'en écrit pas une seconde.
- **Le tableau des niveaux de notification** — **livré par A2 (C18)**. B2 s'y
  conformera pour ses nouveaux événements ; B1 n'en crée aucun destiné à
  l'opérateur.
- **Reboot automatique d'un `BACKUP`** — exclu par décision, durci en C24.
- **Renommage, câblage WAN2, PoE** — cf. A1 §9.

### 5.3 Dépendances sur A2, à consommer sans les réécrire

PRD B **suppose A2 livré** et s'appuie sur trois de ses contrats. Aucun n'est
redéfini ici ; s'ils bougent en A2, ce document doit être relu.

| Contrat A2 | Ce que B1 en attend | Ce que B1 s'interdit |
|---|---|---|
| **C12 — élection du poller** | Une réponse fiable à « cette instance est-elle celle qui interroge l'équipement `X` ? », fondée sur la priorité de `peer.py`, avec reprise après `PEER_TAKEOVER_DELAY` | Écrire une seconde logique d'élection. B1 **lit** le verdict d'A2 ; si l'élection a besoin d'évoluer pour porter des cibles, c'est un amendement d'A2, pas un ajout de B |
| **C18 — niveaux de notification** | Le tableau événement → niveau, et le principe d'escalade conditionnelle en `CRITICAL` quand l'équipement sert | Inventer un quatrième niveau, ou noter un événement au jugé. B2 **étend le tableau**, il ne le remplace pas |
| **C5/C12 — session admin unique** | Un accès sérialisé et mis en cache aux équipements TP-Link, avec son TTL | Sonder un équipement `BACKUP` hors du chemin d'A2 (C28) |

**Point d'attention de séquencement** : A2 déclare `watchdog.py` et `state.py`
non modifiés. B1 lève cet invariant — c'est même sa définition. Il faut donc que
**A2 soit livré et stabilisé en production** avant que B1 ne soit fusionné, pas
seulement mergé sur `dev`. Deux refontes en vol sur les mêmes 4 instances qui
s'auto-mettent à jour, c'est un diagnostic impossible.

## 6. Architecture retenue

### 6.1 Où vivent les boucles de sonde — **boucle unique multiplexée**

**Décision : une seule boucle, un seul thread de décision. Pas de thread par
cible.**

- Le tour de la cible `PRIMARY` reste **synchrone et en ligne**, à la cadence
  `CHECK_INTERVAL` actuelle, à la même place dans l'ordre des étapes du cycle.
  C'est ce qui rend l'égalité de comportement démontrable plutôt que plausible.
- Les cibles `BACKUP` **ne sont jamais sondées dans le chemin critique**. Leurs
  lectures proviennent du poller d'A2 (déjà cadencé, déjà élu, déjà mis en
  cache). La boucle **lit** la dernière valeur connue **et son âge**, et n'en
  fait rien d'autre en 2.4.0.

**Pourquoi pas un thread par cible** — trois raisons, par ordre de poids :

1. **La thread-safety du projet repose sur « un seul écrivain ».** L'état est un
   `frozen dataclass` échangé atomiquement par la boucle ; les deux threads
   existants (HTTP, MQTT) sont des **lecteurs**. Un thread par cible introduit
   N écrivains, donc un besoin de verrou sur l'état, donc la fin de l'argument
   qui rend le code actuel sûr sans en avoir un. On ne paie pas ce prix pour un
   parc de 1 à 3 cibles par instance.
2. **Le chemin d'un secours est fragile et lent.** Session admin unique (C5),
   saut WiFi, authentification HTTP, cache 60 s : un appel qui pend tient un
   verrou. Dans un thread dédié c'est un thread bloqué qu'il faut surveiller ;
   dans la boucle principale ce serait la surveillance USG qui s'arrête. Aucune
   des deux n'est acceptable — d'où la troisième voie : **ne pas sonder du tout
   dans le moteur**, et consommer les lectures d'A2.
3. **Le projet n'a aucun ordonnanceur.** Tout le cadencement périodique est
   `cycle_count % N`. Introduire un modèle de concurrence différent dans la
   version qui refond déjà le cœur, c'est empiler deux refontes.

**Corollaire, à écrire dans le code et pas seulement ici** : l'âge de la donnée
est un champ de la cible, et une donnée périmée bascule la readiness en
`UNKNOWN`. Sans ça, une boucle qui lit un cache figé rapporte indéfiniment un
secours sain — la variante « en interne » du faux OK que C11 traque sur le
réseau.

### 6.2 État par cible — **dans `WatchdogState`, avec projection legacy**

**Décision : l'état d'exécution par cible vit dans `WatchdogState`, dans un
conteneur immuable ordonné (`targets: tuple[TargetState, ...]`), et les champs
plats legacy restent présents comme projection de la cible `PRIMARY`.**

Le registre séparé a été écarté. L'arbitrage :

| Critère | État dans `WatchdogState` | Registre séparé |
|---|---|---|
| Cohérence de lecture | **Un seul swap atomique** : le thread HTTP voit toujours un instantané cohérent | Deux domaines de cohérence : l'état et le registre peuvent se contredire à l'instant de la lecture |
| Verrouillage | Aucun ajout | Un verrou de plus, lu par 3 threads |
| Diffusion | `/api/state`, `/metrics`, MQTT, dashboard, historique lisent **déjà** l'instantané | Il faut câbler le registre dans les 5 |
| Immutabilité | `tuple` de `frozen dataclass`, cohérent avec `internet_rtts: tuple[...]` | À reconstruire |
| Rétro-compatibilité | La projection legacy est **une fonction pure testable** | Deux sources pour les mêmes clés |

**Répartition des responsabilités, à énoncer noir sur blanc** — c'est la ligne
qui empêche les deux structures de dériver :

- **`managed_devices.py` = configuration et session.** *Qu'est-ce qui existe,
  comment on lui parle.* Déclaration (`TplinkDeviceConfig`), identifiants, mode
  d'accès (C16), verrou de session admin par équipement (`_device_locks`),
  cache 60 s, confirmations via `confirm.py`. Le registre **ne porte pas
  d'état de scoring**, et `ManagedDeviceRegistry` **n'est pas étendu** pour en
  porter.
- **`WatchdogState.targets` = connaissance courante.** *Ce qu'on sait
  maintenant, et depuis quand.* Score, circuit-breaker, cooldowns, dernière
  santé, readiness, âge de la donnée.

`MonitoredTarget` est l'objet **vivant** qui relie les deux : il tient le driver
et l'identité de configuration, et produit à chaque cycle un `TargetState` gelé
qui part dans l'instantané.

**La projection legacy est le mécanisme central de la rétro-compatibilité.**
Une unique fonction `_project_primary()` dérive les 20 champs plats depuis la
cible `PRIMARY`. Elle est testée champ par champ, et c'est elle qui rend C21 et
C22 mécaniquement vérifiables au lieu d'être des promesses.

### 6.3 Interaction avec l'élection du poller d'A2

Le moteur pose une question et n'en pose qu'une : **« suis-je le poller élu pour
la cible `X` ? »**.

- **Cible `PRIMARY` (USG)** : l'élection **ne s'applique pas**. Chaque instance
  ping son USG indépendamment — c'est précisément la double vue dont
  `peer.py` a besoin pour détecter une divergence, et un ping n'a aucune
  contention à éviter. Le confondre avec le cas TP-Link serait une régression du
  failover HA.
- **Cible `BACKUP`** : l'élection **s'applique intégralement**, telle qu'A2 l'a
  livrée. L'instance non élue lit l'état du peer et l'expose **avec son âge**.
- **Split-brain** : traité par A2 (détecter et alerter, ne pas résoudre
  silencieusement). B1 n'ajoute rien, mais **hérite du risque** : si les deux
  instances se croient élues, deux jeux de valeurs concurrentes arrivent dans
  `targets`. La règle retenue : la valeur locale prime dans l'instantané local,
  et le désaccord est signalé comme une divergence — jamais moyenné, jamais
  arbitré en silence.

Cette asymétrie (`PRIMARY` non élue, `BACKUP` élue) est **une propriété du
rôle**, pas une exception : elle découle directement de « qui a une session
exclusive à protéger ». Elle doit apparaître dans le code comme telle, dérivée
du rôle, et non comme un `if vendor == "tplink"`.

### 6.4 Ce que voit l'opérateur en 2.4.0

Rien de nouveau, par construction. Le dashboard, les commandes ntfy, l'API et
les entités Home Assistant rendent les mêmes informations. Le bloc `targets`
existe dans `/api/state` et dans les métriques labellisées, mais **il ne
contient qu'une cible et redit ce que les champs plats disent déjà**. C'est
voulu : c'est la définition d'une abstraction réussie.

## 7. Contraintes

La numérotation continue celle d'A1/A2 (C1→C20).

- **C21 — `/api/state` est additif, jamais restructuré (BLOQUANTE).**
  A1 §6.1 annonçait que « le risque redevient réel en PRD B » : nous y sommes.
  Les clés plates existantes restent **au premier niveau**, avec le même nom, le
  même type et la même sémantique, alimentées par la projection de la cible
  `PRIMARY` (§6.2). Le bloc `targets` s'**ajoute** à côté. Même raisonnement
  que C4 pour Prometheus, même méthode de vérification : **une assertion par clé
  legacy**, liste figée dans le test, un ajout de clé ne casse rien, une
  suppression casse immédiatement.
  Consommateurs connus : `peer.py`, le dashboard, les tests d'intégration, et
  **tout ce que l'utilisateur a pu brancher dessus sans que le dépôt le sache**.

- **C22 — Le dialogue entre peers survit à la fenêtre de mise à jour mixte
  (BLOQUANTE).** L'auto-updater tire `main` : sur une paire HA, master et slave
  **ne basculent pas ensemble**. Pendant plusieurs minutes, une 2.4.0 dialogue
  avec une 2.3.x, dans **les deux sens**.
  - **`WatchdogState.from_dict()` tolère les clés inconnues.** C'est la clause
    centrale de C22, et elle porte sur la 2.3.x **déjà déployée** : si son
    `from_dict` est strict, le bloc `targets` d'une 2.4.0 la fait échouer, et
    `query_peer()` renvoie `None` — c'est-à-dire *« peer mort »* (§2.1). À
    **vérifier sur le code de la 2.3.x en premier**, avant tout développement :
    si la tolérance n'y est pas, elle doit être livrée en **patch 2.3.x
    préalable**, déployé et stabilisé sur les 4 instances **avant** que la
    2.4.0 ne soit taguée. *C'est potentiellement un pré-requis bloquant
    hors de ce PRD — à trancher au Sprint 1.*
  - **Un échec de désérialisation n'est pas une absence de peer.** Les deux
    causes doivent être distinguées dans le code et dans les journaux. Un peer
    qui répond mais qu'on ne sait pas lire est un peer **présent** : le repli
    sûr est de **ne pas rebooter**, et d'alerter.
  - Un peer qui n'annonce pas de bloc `targets` est traité comme **mono-cible,
    `PRIMARY`**, en lisant ses champs plats. Jamais comme un peer absent :
    *se croire seul est l'erreur qui provoque le double reboot*.
  - Réciproquement, une 2.3.x lisant une 2.4.0 doit trouver **exactement** les
    10 champs qu'elle consomme (§2.1) — ce qui est la promesse C21.
  - **Testée dans les deux sens** avec des instantanés `/api/state` **capturés
    sur les instances de production en 2.3.x**, pas fabriqués à la main : un
    fixture écrit de mémoire teste ce qu'on croit produire, pas ce qu'on produit.
  - **Ordre de bascule imposé** : slaves d'abord, un site toujours couvert —
    la procédure déjà éprouvée lors du renommage 2.0.0.

- **C23 — Zéro cible supplémentaire déclarée ⇒ zéro changement observable.**
  L'héritière directe de l'invariant « le cœur mono-cible n'est pas touché »
  d'A1, transposée maintenant que le cœur *est* touché. Portée : décisions de
  reboot, contenu et cadence des messages, clés et valeurs de `/api/state`,
  métriques legacy, entités Home Assistant, format des événements.
  **Vérification** : `tests/test_watchdog.py` passe **sans modification d'un
  seul test** (§9), et le mode fantôme (§8.2) ne relève aucune divergence.

- **C24 — C6 devient un invariant structurel, pas une garde applicative.**
  Jusqu'ici, C6 tenait parce que le moteur **ignorait** les secours. Le moteur
  acquiert maintenant une collection de cibles et une méthode `reboot()` sur
  chacune. La garde doit donc changer de nature : le chemin de décision de
  reboot n'est **atteignable** que depuis une cible `PRIMARY` — typage, ou
  collection distincte, **pas** un `if role == PRIMARY` au milieu d'une branche
  de 300 lignes.
  Motif : une garde par branche se contourne par un `elif` ajouté six mois plus
  tard par quelqu'un qui n'a pas lu ce document. **Test explicite** : faire
  passer une cible `BACKUP` par le chemin de décision doit être **impossible à
  écrire**, ou refusé et tracé dans l'`EventLog`.

- **C25 — Un score par cible ; le budget de reboot reste au site.**
  Le score, le circuit-breaker, les cooldowns et le backoff SSH sont **par
  cible** : ce sont des propriétés de la relation à un équipement.
  Le **plafond quotidien de reboots** reste **global à l'instance** : ce qu'il
  protège — ne pas malmener le site à répétition — est un risque de site, pas
  d'équipement. En 2.4.0 la distinction est sans effet (une seule cible
  redémarrable) ; elle est tranchée maintenant parce que **la structure de
  données se décide maintenant**. *Question ouverte Q1 (§12).*

- **C26 — La santé d'une `BACKUP` n'entre jamais dans le score d'une
  `PRIMARY`.** Séparation structurelle, pas conditionnelle : aucun chemin
  arithmétique ne relie les deux. Motif : un secours 4G dégradé est un **fait
  attendu** (couverture, quota, météo) ; le laisser peser sur le score de la
  ligne principale ferait rebooter l'USG parce que la SIM est épuisée. C'est
  l'erreur exacte que l'ADR 0001 a corrigée dans son amendement du 2026-08-12,
  quand les MR110 sont passés de « cibles » à « secours ».

- **C27 — L'âge de la donnée est un champ, et il déclasse.** Toute lecture de
  cible porte l'horodatage de son obtention. Au-delà d'un seuil, la readiness
  passe à `UNKNOWN` — jamais conservée à `OK`. Motif : le moteur ne sonde plus
  lui-même les secours (§6.1), il lit un cache. Un cache figé qui rapporte
  « sain » est un faux OK, et c'est la variante interne de ce que C11 traque
  côté réseau.

- **C28 — Aucune seconde cadence de polling.** B1 ne crée ni thread, ni timer,
  ni ordonnanceur. Les secours sont lus via le chemin d'A2 (poller élu, cache,
  verrou de session). Motif : deux cadences sur un équipement à session unique,
  c'est la contention que C5 et C12 ont coûté deux PRD à éliminer.

- **C1 — import vendor paresseux : toujours actif.** `updater/preflight.py`
  fait `import watchdog`. `watchdog.py` importe désormais des drivers : la
  chaîne d'import ne doit **jamais** tirer `tplinkrouterc6u`.
  Vérification inchangée, et devenue plus critique qu'en A1.

- **C4 — métriques Prometheus legacy préservées : toujours active.** Les
  métriques historiques restent émises **sans label de cible**. Les métriques
  par cible s'ajoutent à côté.

### 7.1 Techniques

- Immutabilité : `TargetState` en `@dataclass(frozen=True)` ; `targets` en
  `tuple`. Aucune mutation en place, y compris dans les chemins de reprise.
- `never raise` étendu au moteur : `UsgDriver` respecte l'invariant des drivers
  — un échec SSH ou un timeout produit une valeur dégradée, pas une exception
  qui remonte dans la boucle.
- Les fonctions pures existantes (`compute_cycle_delta`,
  `compute_effective_cooldown`, `compute_ssh_retry_delay`) restent **pures** et
  gardent leur signature ou n'évoluent qu'en ajoutant des paramètres à défaut.
  Ce sont elles que la suite de tests couvre le mieux : les préserver, c'est
  préserver le filet.
- Le flag de moteur (§8.1) est lu **une fois au démarrage**, jamais en cours de
  boucle : un changement de moteur en cours de vol serait la seule chose pire
  qu'un mauvais moteur.

## 8. Stratégie de migration

### 8.1 Un flag sur le chemin de décision, pas sur le modèle de données

**Décision : `VIGIL_ENGINE=driver|legacy`, défaut `driver`, qui ne commande que
la bascule du Sprint 3.**

- Le **modèle de données** (bloc `targets`, `TargetState`, projection legacy)
  part **sans condition** : il est additif et inerte. Le mettre sous flag
  obligerait dashboard, métriques, MQTT et `peer.py` à gérer **deux formes
  d'état en production** — on doublerait la surface exacte qu'on cherche à
  sécuriser.
- Le **chemin de décision** est sous flag : un unique point d'aiguillage entre
  l'ancienne boucle et la boucle à cibles.

**Pourquoi ce flag mérite son coût.** L'auto-updater tire le **dernier tag** :
revenir en arrière suppose de retirer ou dépasser `v2.4.0` sur toute la flotte
(A1 §10bis). Un `git revert` ne rétablit pas une instance à 3 h du matin ; une
variable d'environnement et un `systemctl restart`, si — **par instance**, sans
toucher aux trois autres.

**Coût assumé** : le chemin legacy reste compilé et testé pendant une version.
**Retrait programmé en 2.6.0**, inscrit dès maintenant dans le document — un
flag sans date de péremption devient une branche permanente, et deux moteurs
maintenus en parallèle, c'est le pire des deux mondes.

*Une bascule sèche sans flag reste défendable si l'on juge le coût du double
chemin supérieur au bénéfice — question ouverte Q3 (§12).*

### 8.2 Le mode fantôme : la manœuvre qui rend le refactor défendable

Avant de laisser le nouveau moteur décider, on le fait **calculer sans agir**,
en parallèle de l'ancien, sur les instances de production :

- à chaque cycle, les deux moteurs calculent score, cooldowns et **décision** ;
- seul l'ancien agit ;
- toute divergence est **journalisée avec son contexte complet** — et si elle
  porte sur une décision de reboot, notifiée.

C'est l'application au moteur du raisonnement qui a fondé C11 : **ne pas croire
une configuration, exiger une preuve issue du résultat**. Une suite de tests
verte prouve que le code fait ce que les tests décrivent ; le mode fantôme
prouve qu'il décide ce que l'ancien décidait, **sur le trafic réel des quatre
sites** — y compris dans les états que personne n'a pensé à écrire en test.
C'est exactement la classe de bug que 2.1.1 a révélée.

**Critère de sortie proposé** : ≥ 200 cycles (~100 min à `CHECK_INTERVAL` = 30 s)
sur **chacune des 4 instances**, zéro divergence de décision. À arbitrer :
couvrir au moins un incident réel serait plus probant, mais n'est pas
planifiable.

### 8.3 Migration cible par cible

Sans objet en B1 : il y a **une** cible. C'est la stratégie de **B2**, où chaque
secours devient scoré et alertant **sur activation explicite**, dans la
continuité de l'opt-in par équipement d'A2 (C11). Le principe du parc reste :
*rien ne bouge tant qu'un humain n'a pas activé explicitement*.

### 8.4 Ordre de bascule de la flotte

Repris tel quel de la migration 2.0.0, qui a fonctionné :

1. **`dijon-slave`** en cobaye, mode fantôme, 24 h d'observation ;
2. `dijon-master` ;
3. `nice-slave`, puis `nice-master`.

Un site est **toujours couvert** par au moins une instance en version connue.
Entre les deux instances d'un même site, la fenêtre est celle de C22 — elle doit
être **courte et surveillée**, et le comportement du failover y est vérifié
explicitement, pas supposé.

## 9. Critères d'acceptation

**Non-régression — le cœur du contrat**

- [ ] **C23** : `tests/test_watchdog.py` (2 424 lignes) passe **sans qu'un seul
      test n'ait été modifié**. Toute modification d'un test est un changement de
      comportement : elle doit être justifiée **ligne à ligne** dans la PR, ou
      le code est corrigé
- [ ] **C23** : idem pour `tests/test_state.py`, `tests/test_peer.py`,
      `tests/test_connectivity.py`, `tests/test_usg.py`
- [ ] **C21** : assertion **par clé legacy** de `/api/state` (liste figée) —
      présence, type et sémantique ; ajout toléré, suppression ou renommage
      bloquants
- [ ] **C21** : la projection `PRIMARY` → champs plats est testée **champ par
      champ** (20 champs)
- [ ] **C4** : `/metrics` expose toujours les métriques historiques **sans
      label de cible**, assertion par métrique legacy
- [ ] Dashboard, entités Home Assistant et messages : rendu **strictement
      inchangé** à périmètre constant
- [ ] **Mode fantôme** : ≥ 200 cycles sur **chacune des 4 instances**, **zéro
      divergence de décision** consignée avant la bascule

**Abstraction**

- [ ] `UsgDriver` conforme à `RouterDriver` ; `isinstance(drv, RouterDriver)`
      vrai ; **aucune méthode ne lève** (invariant A1)
- [ ] `check_connectivity()` et `reboot_usg()` acceptent une configuration de
      cible ; **plus aucune lecture de `config` au niveau module** dans le chemin
      SSH/ping
- [ ] Trackers de latence **instanciés par cible** ; plus aucun singleton de
      module dans `connectivity.py`
- [ ] `RouterHealth` enrichi de `probes_ok` / `probes_total` — additif,
      `TplinkDriver` inchangé et ses tests verts
- [ ] Les 6 points de couplage USG de `watchdog.py` (l.53, 476, 530, 771, 845,
      1030) passent **tous** par le driver — vérifiable par absence de
      `from usg import` et de `check_connectivity(` dans `watchdog.py`
- [ ] **C1** : `python3 -c "import watchdog"` réussit sans `tplinkrouterc6u`

**Rôles**

- [ ] **C24** : le chemin de décision de reboot est **inatteignable** pour une
      cible `BACKUP` — démontré par un test qui *tente* de l'emprunter
- [ ] **C24** : exactement **une** cible `PRIMARY` ; deux `PRIMARY` déclarées =
      refus au démarrage avec un message explicite, pas un choix arbitraire
- [ ] **C26** : aucun chemin arithmétique d'une `BACKUP` vers le score d'une
      `PRIMARY` — test d'injection : dégrader une `BACKUP` fictive à l'extrême
      laisse le score de la `PRIMARY` **rigoureusement identique**
- [ ] **C25** : score, circuit-breaker, cooldowns et backoff sont par cible ;
      le plafond quotidien de reboots reste global à l'instance

**Haute disponibilité**

- [ ] **C22** : la tolérance aux clés inconnues de `WatchdogState.from_dict` est
      **vérifiée sur le code 2.3.x réellement déployé** ; si absente, patch
      2.3.x préalable livré et stabilisé sur les 4 instances **avant** le tag
      2.4.0
- [ ] **C22** : négociation testée **dans les deux sens**, à partir
      d'instantanés `/api/state` **capturés sur la production en 2.3.x**
- [ ] **C22** : un échec de désérialisation est distingué d'un peer injoignable ;
      le repli est **ne pas rebooter** + alerter — test explicite
- [ ] **C22** : un peer sans bloc `targets` est traité comme **mono-cible
      `PRIMARY`**, jamais comme absent — test explicite sur le double reboot
- [ ] `should_reboot()`, `check_divergence()` et `get_peer_info()` produisent des
      résultats **identiques** à la 2.3.0 sur les 10 champs consommés
- [ ] Divergence détectée **par cible** ; seuil `_DIVERGENCE_SCORE_GAP = 6` et
      comportement inchangés pour la cible `PRIMARY`
- [ ] Pour la cible `PRIMARY`, l'élection du poller d'A2 **ne s'applique pas** :
      les deux instances continuent de sonder — la double vue du failover est
      préservée
- [ ] **C28** : aucun thread, timer ou ordonnanceur ajouté — vérifiable par
      comptage des threads démarrés

**Migration et livraison**

- [ ] `VIGIL_ENGINE=legacy` restaure le comportement 2.3.0 sur une instance,
      **sans redéploiement** ; retrait programmé en 2.6.0 et documenté
- [ ] **C27** : âge de la donnée exposé par cible ; au-delà du seuil, readiness
      `UNKNOWN` — jamais `OK` conservé
- [ ] Runbook de bascule de flotte écrit, ordre slaves d'abord, procédure de
      repli par instance
- [ ] `INVARIANTS.md` : entrées C21, C23, C24, C26 avec commande `Verify`
      exécutable
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, README + DEPLOY + runbook
      à jour, VERSION = 2.4.0

## 10. Sprints

| # | Sprint | But | Risque |
|---|---|---|---|
| 1 | **Vérification `from_dict` (C22)** + `UsgDriver` **non branché** + dé-globalisation de `connectivity.py` / `usg.py` | Lever le doute bloquant sur la compatibilité peer, puis poser le driver et le paramétrage par cible **sans que la boucle les utilise** | **Go/no-go** |
| 2 | `MonitoredTarget` + `targets` dans `WatchdogState` + projection legacy | Le modèle de données par cible, additif et inerte, avec C21 verrouillée par des assertions | Moyen |
| 3 | **Bascule de la boucle** sur le driver + circuit-breaker par cible + C24/C26 + mode fantôme | Le cœur du chantier — et le seul sprint qui change une décision | **Critique** |
| 4 | `peer.py` multi-cible + négociation C22 | Survivre à la fenêtre de mise à jour mixte sur une paire HA | **Élevé** |
| 5 | Invariants, docs, runbook, release 2.4.0 + vérification terrain | Livrer sur 4 instances qui se mettent à jour seules | Moyen |

**Détail des buts**

1. **Sprint 1** — **d'abord** : lire `WatchdogState.from_dict` sur la 2.3.x
   déployée et trancher C22 (tolérante ⇒ on continue ; stricte ⇒ un patch 2.3.x
   préalable devient un pré-requis bloquant de tout le PRD). **Ensuite**
   seulement : `UsgDriver` implémente le contrat en encapsulant `usg.py` et
   `connectivity.py` ; ceux-ci acceptent une configuration de cible ; les
   trackers de latence deviennent des instances ; `RouterHealth` gagne
   `probes_ok` / `probes_total`. `watchdog.py` **n'est pas touché**. La partie
   driver est donc **purement additive** : c'est ce qui la rend sûre.
2. **Sprint 2** — `MonitoredTarget` et `TargetState` ; `WatchdogState` gagne
   `targets` avec exactement une cible `PRIMARY` ; `_project_primary()` et ses
   tests champ par champ ; `/api/state` gagne son bloc ; les assertions C21
   sont écrites **avant** que quoi que ce soit ne bouge.
3. **Sprint 3** — la boucle passe par le driver et l'état par cible. C24 et C26
   sont installées comme structure. Le mode fantôme est livré **dans ce sprint**,
   pas après : c'est l'instrument qui rend la bascule vérifiable.
4. **Sprint 4** — `peer.py` compare par cible et négocie le format. Les
   instantanés figés 2.3.x servent de matériel de test.
5. **Sprint 5** — invariants machine-vérifiables, docs, runbook de flotte,
   release, puis vérification contre le vrai matériel.

**Gates**

- *Au tout début du Sprint 1, avant toute ligne de code* : verdict C22 sur le
  `from_dict` de la 2.3.x. Verdict « strict » ⇒ **arrêter et re-cadrer** : un
  patch 2.3.x doit être livré, déployé et stabilisé sur les 4 instances avant
  de reprendre. Ne pas enchaîner en espérant que la fenêtre de bascule soit
  assez courte pour que ça ne se voie pas — c'est exactement pendant cette
  fenêtre que le failover est sollicité.
- *Après Sprint 1* : `UsgDriver` doit produire, sur les mêmes entrées, un
  résultat **identique** à `check_connectivity()`. Sinon, la bascule du Sprint 3
  est déjà perdue — la corriger ici coûte une journée, plus tard elle coûte un
  incident.
- *Après Sprint 2* : les assertions C21 doivent être **rouges puis vertes** —
  écrites contre la 2.3.0, elles doivent d'abord être prouvées capables de
  détecter une régression, sinon elles ne prouvent rien.
- *Avant la fusion du Sprint 3* : critère de sortie du mode fantôme (§8.2) —
  **c'est la gate la plus importante du PRD**. Ne pas la contourner parce que la
  flotte « a l'air d'aller bien ».
- *Avant le Sprint 5* : A2 doit être **stabilisé en production**, pas seulement
  livré (§5.3).

## 11. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| **Un `from_dict` strict en 2.3.x transforme le bloc `targets` d'une 2.4.0 en « peer mort » → double reboot** | **Critique** — et **invisible** : `query_peer()` renvoie `None` sans distinguer la cause | C22 : tolérance vérifiée **sur le code 2.3.x déployé** avant tout développement ; patch 2.3.x préalable si nécessaire ; échec de parsing distingué d'une absence, repli « ne pas rebooter » |
| **Fenêtre de mise à jour mixte : le failover se décide entre deux versions qui ne lisent plus le même `/api/state`** | **Critique** — double reboot, ou aucun | C21 + C22 : clés plates intactes, négociation testée dans les deux sens sur des instantanés **capturés en production**, peer non reconnu = mono-cible et non absent ; bascule slaves d'abord |
| **Régression silencieuse du scoring** — un delta subtilement différent ne casse aucun test et ne se voit qu'au prochain incident réel | **Critique** | Tests du cœur **non modifiés** (C23) + **mode fantôme** sur les 4 instances (§8.2) + vérification terrain. Précédent 2.1.1 : 1 049 tests verts n'avaient pas vu le bug `wlan0` |
| **C6 contournée par construction** — le moteur acquiert le pouvoir de rebooter des cibles ; un rôle mal évalué redémarre un MR110 en service = site coupé | **Critique** | C24 : chemin inatteignable pour une `BACKUP`, pas un `if` dans une branche ; test qui *tente* de l'emprunter |
| **Rollback coûteux** : l'auto-updater tire le dernier tag, revenir en arrière suppose de retaguer les 4 instances | Élevé | `VIGIL_ENGINE=legacy` : repli **par instance**, immédiat, sans redéploiement (§8.1) |
| **Perte de l'argument de thread-safety** si des threads par cible sont introduits | Élevé | §6.1 : boucle unique, un seul écrivain, secours jamais sondés dans le chemin critique |
| **Cache figé lu comme un secours sain** | Élevé | C27 : l'âge déclasse en `UNKNOWN`. Variante interne du faux OK de C11 |
| **Deux refontes en vol** — B1 fusionné avant qu'A2 ne soit stabilisé en production | Élevé | §5.3 : A2 stabilisé **en production** avant fusion ; gate avant Sprint 5 |
| **Consommateur inconnu de `/api/state`** hors dépôt (script, automatisation HA, sonde externe) | Élevé | C21 additive **sans exception** — la seule défense contre un consommateur qu'on ne connaît pas est de ne rien lui retirer |
| **Split-brain hérité d'A2** : deux instances se croient élues, deux jeux de valeurs dans `targets` | Moyen | §6.3 : valeur locale prioritaire, désaccord signalé, jamais moyenné ni arbitré en silence |
| **Le flag legacy devient permanent** | Moyen | Retrait daté (2.6.0) inscrit dans le document et dans `INVARIANTS.md` |
| **Périmètre qui glisse vers B2** en cours de route (« tant qu'on y est, ajoutons l'alerting ») | Moyen | §3 : la frontière est le critère de vérification, pas une commodité d'organisation |
| **`compute_cycle_delta` élargie « pour faire propre »** | Moyen | §7.1 : les fonctions pures gardent leur signature ou n'évoluent qu'en ajoutant des paramètres à défaut — ce sont elles que la suite couvre le mieux |
| **Chaîne d'import qui tire le vendor** via les drivers désormais importés par `watchdog.py` | Moyen | C1, vérification inchangée mais plus critique qu'en A1 |
| Coverage qui chute pendant le refactor | Faible | `validate.sh` bloquant à 80 % ; les fonctions pures restent testées à l'identique |

## 11bis. Rollback par sprint

| Sprint | Rollback | Point d'attention |
|---|---|---|
| 1 | Revert de la branche | Purement additif, non branché : un revert suffit |
| 2 | Revert de la branche | Additif, mais `/api/state` a déjà changé de forme sur `dev` — vérifier qu'aucun test d'intégration ne s'est mis à dépendre du bloc `targets` |
| 3 | `VIGIL_ENGINE=legacy` **d'abord**, revert ensuite | **Le seul sprint dont le rollback doit fonctionner sans redéploiement.** Le flag est le rollback ; le revert est le nettoyage. Ne jamais fusionner ce sprint sans avoir prouvé le repli sur une instance réelle |
| 4 | Revert de la branche | `peer.py` porte le failover HA : après revert, **re-vérifier le failover d'origine** — même précaution qu'au Sprint 1 d'A2 |
| 5 | Revert **+ retag** | L'auto-updater tire le dernier tag : revenir en arrière suppose de retirer ou dépasser `v2.4.0`, sinon les 4 instances retirent la version fautive |

**Ce qui n'est pas réversible** : rien, si C21 est tenue. C'est la propriété la
plus utile de cette contrainte — un `/api/state` strictement additif rend
l'ensemble du chantier réversible, alors que la moindre clé renommée le rendrait
irréversible pour tout consommateur hors dépôt. **C21 n'est pas une commodité de
compatibilité : c'est la condition du rollback.**

## 12. Questions ouvertes

- **Q1 — Plafond de reboots quotidien : par cible ou global au site ?**
  C25 tranche par défaut pour **global à l'instance** (ce qu'il protège est un
  risque de site). Sans effet en 2.4.0, mais **la structure de données se décide
  maintenant**. Confirmez-vous ?
- **Q2 — Une seconde cible `PRIMARY` est-elle un objectif à terme ?**
  Ce document pose « exactement une `PRIMARY` » en invariant vérifié au
  démarrage (C24). Si deux lignes principales sont envisagées un jour
  (second site, seconde fibre), il faut le savoir **maintenant** : cela change
  l'arbitrage entre cibles et la logique de `peer.py`. Hypothèse retenue :
  **une seule `PRIMARY` par instance, définitivement**.
- **Q3 — Flag legacy ou bascule sèche ?** §8.1 recommande le flag, retiré en
  2.6.0. La bascule sèche reste défendable (moins de code, rollback par retag
  uniquement). Le flag coûte un chemin doublé pendant une version ; la bascule
  sèche coûte une flotte à retaguer, la nuit, en cas de problème.
- **Q4 — Fenêtre de mise à jour mixte : négocier ou geler ?**
  (a) négociation automatique (C22, recommandée) ; (b) passer le slave en
  surveillance seule pendant la bascule et réactiver après. (b) est plus simple
  et supprime le risque de double reboot, mais **laisse le site sans failover**
  pendant la fenêtre. Recommandation : (a), avec (b) en procédure de secours
  écrite dans le runbook.
- **Q5 — `check_connectivity()` reste-t-elle une fonction publique ?**
  Elle est directement couverte par `tests/test_connectivity.py`. L'absorber
  entièrement dans `UsgDriver` est plus propre ; la conserver comme fonction
  paramétrée que le driver appelle préserve la suite de tests telle quelle.
  Recommandation : **la conserver**, paramétrée — préserver le filet prime sur
  l'élégance dans ce chantier précis.
- **Q5bis — L'identité d'une cible.** Le registre d'A1 utilise des `device_id`
  de chaînes (`TPLINK_<n>_*`). La cible `PRIMARY` a besoin du sien. Faut-il un
  identifiant explicite et configurable, ou un `"usg"` implicite ? Cet
  identifiant apparaîtra dans `/api/state`, les métriques labellisées, les
  événements et Home Assistant — **le changer plus tard coûte des entités
  recréées** (leçon C14/C15 d'A2). Recommandation : `"usg"` figé, non
  configurable, documenté comme réservé.
- **Q6 (B2) — Un secours dégradé alerte-t-il une fois, ou périodiquement ?**
  C18 (A2) dit « au changement d'état ». Mais un secours mort depuis trois
  semaines qui n'a alerté qu'une fois, c'est exactement l'angle mort qu'A1
  ouvrait son PRD en dénonçant. Proposition : alerte au changement d'état
  **plus** un rappel dans le rapport hebdomadaire existant.
- **Q7 — Numérotation des versions.** Le PRD A2 porte encore « 1.10.0 » et
  A1 §9.1 « ~1.11.0 », antérieurs au renommage 2.0.0. Ce document retient
  **A2 = 2.3.0, B1 = 2.4.0, B2 = 2.5.0**. À confirmer, et les deux PRD
  antérieurs mériteraient une note de mise à jour.
- **Q8 — Dérive documentaire à corriger.** A1 et A2 décrivent des commandes
  **Telegram** (`/lte`, `/status`…) alors que 2.2.0 a sorti Telegram au profit
  de ntfy + e-mail. Aucun impact sur B1 (qui n'ajoute aucune commande), mais les
  critères d'acceptation d'A2 devront être relus avant son démarrage.

## 13. Definition of Done

Tous les AC §9 cochés, 5 sprints verts, coverage ≥ 80 %, `validate.sh` vert,
docs et runbook à jour, `v2.4.0` taggée en dernier, `dev` synchronisé.

Et **vérification terrain**, qui pour ce PRD ne consiste pas à voir une
fonctionnalité nouvelle mais à **ne rien voir** :

- les 4 instances tournent en 2.4.0, moteur à cibles, depuis 48 h ;
- le mode fantôme n'a relevé **aucune divergence de décision** avant la bascule ;
- `/api/state` d'une 2.4.0 est consommé sans erreur par une 2.3.x, **et
  l'inverse** — vérifié en réel pendant la fenêtre de bascule d'un site, pas
  seulement en test ;
- un `VIGIL_ENGINE=legacy` sur une instance la ramène au comportement 2.3.0, et
  le retrait du flag la ramène au nouveau moteur — **essayé pour de vrai**, une
  fois, sur `dijon-slave` ;
- une coupure volontaire de l'USG de Dijon produit **exactement** la même
  séquence de score, de messages et de décision qu'en 2.3.0.

## 14. Suite — PRD B2, scoring et alerting multi-cible (2.5.0)

À spécifier après livraison de B1. Périmètre pressenti, **non engageant** :

- **Cibles `BACKUP` scorées en continu**, sur les lectures du poller élu d'A2,
  avec seuils propres au rôle — un secours 4G n'a pas les seuils d'une fibre.
- **Alerting automatique de readiness** : notification au **changement d'état**
  (C18), anti-rebond, escalade en `CRITICAL` quand la `PRIMARY` est elle-même en
  panne — c'est le seul moment où un secours dégradé est une urgence. Émis par
  la **seule instance élue** (C12), pour éviter le doublon master/slave.
- **Rappel périodique** d'un secours durablement dégradé (Q6).
- **Activation par cible** (opt-in), dans la continuité d'A2.
- **Exposition par cible** : dashboard, Prometheus labellisé, entités Home
  Assistant de readiness.

**Ce que B2 n'apportera pas non plus** : le reboot automatique d'un `BACKUP`.
C6 et C24 restent valides indéfiniment.

**Et la décision de ne pas faire B1 reste ouverte.** A1 et A2 ont livré
l'essentiel de la valeur opérationnelle. Si le parc n'évolue plus — deux sites,
une fibre et un secours 4G chacun — le moteur mono-cible actuel, entouré des
drivers et du registre, **fait le travail**. B1 n'achète pas une fonction : il
achète la capacité d'en ajouter une sans réécrire la boucle, et l'assurance que
le rôle d'un équipement détermine structurellement ce qu'on a le droit de lui
faire. C'est un vrai bénéfice, et il a un vrai prix. Ce document est écrit pour
que les deux soient visibles avant de s'engager.
