# INVARIANTS — A2, exposition & Home Assistant

Contrats transverses vérifiables machine. Un sprint qui viole un invariant est
en échec, quel que soit l'état de ses propres tests.

Contexte : **4 instances** (Dijon master+slave, Nice master+slave) en
auto-update depuis `main`, et des consommateurs externes — Grafana pour les
métriques, Home Assistant pour MQTT. A2 s'adresse presque entièrement à ces
consommateurs : la plupart des invariants ci-dessous protègent **leur** contrat,
pas le nôtre.

---

## Métriques Prometheus legacy préservées (C4)

- **Owner** : `src/metrics.py`
- **Preconditions** : des dashboards Grafana et des règles d'alerte consomment
  déjà `usg_watchdog_*` **sans label**.
- **Postconditions** : ces métriques restent émises sans label, à l'identique ;
  les métriques par équipement sont **ajoutées à côté**.
- **Invariants** : ajouter un label à une métrique existante ne produit **aucune
  erreur** — les requêtes deviennent simplement vides et les alertes cessent de
  se déclencher. C'est une panne silencieuse, donc à verrouiller par test
  **métrique par métrique**, pas par une assertion globale.
- **Verify** : `python3 -m pytest tests/test_metrics.py -k "legacy_unlabeled" -q`
- **Fix** : émettre les deux familles ; ne jamais substituer.

## Le chemin de commande MQTT est gardé (C9)

- **Owner** : `src/mqtt_publisher.py`
- **Preconditions** : A2 introduit le premier `subscribe` du projet.
- **Postconditions** : l'écoute est désactivable indépendamment de la
  publication ; un message malformé est ignoré et loggé ; toute action
  destructive exige l'entité *arm* active.
- **Invariants** : quiconque peut publier sur le broker peut déclencher une
  action. C'est une surface d'attaque qui n'existait pas avant ce PRD. Sur un
  broker anonyme, l'écoute ne doit pas être activée.
- **Verify** : `python3 -m pytest tests/test_mqtt_commands.py -k "malformed or requires_arm or listen_disabled" -q`
- **Fix** : parsing strict et garde *arm* en amont du dispatch, pas dans une
  branche enfouie.

## Aucun échec silencieux côté Home Assistant (C10)

- **Owner** : `src/mqtt_publisher.py`
- **Preconditions** : un `button` HA se presse sans retour visuel natif.
- **Postconditions** : toute commande reçue produit un résultat observable dans
  l'entité de dernière action, refus compris, **avec son motif**.
- **Invariants** : sans ça, un refus est indistinguable d'un message perdu, et
  l'opérateur presse le bouton en boucle sur un équipement de production.
- **Verify** : `python3 -m pytest tests/test_mqtt_commands.py -k "last_action" -q`
- **Fix** : publier le résultat avant de retourner, y compris sur les chemins
  d'erreur.

## Identité MQTT disjointe par instance et par équipement

- **Owner** : `src/mqtt_publisher.py`
- **Preconditions** : le bugfix 1.8.1 a introduit un identifiant d'instance ;
  livré avec 1.8.2, ce préfixe est concrètement `vigil_` (device
  `vigil_{instance_id}`, `unique_id` `vigil_{instance_id}_{sensor_id}`, topic de
  discovery `.../vigil_{instance_id}/...`, `client_id` `vigil-{instance_id}` —
  `src/mqtt_publisher.py` lignes 44, 83, 92, 125).
- **Postconditions** : chaque MR110 est un device HA distinct, dont l'identité
  combine instance **et** équipement ; aucune collision entre master et slave
  d'un même site.
- **Invariants** : deux instances publiant la même identité écrasent
  mutuellement leurs entités, sans qu'aucun élément d'interface ne l'indique.
- **Verify** : `python3 -m pytest tests/test_mqtt_publisher.py -k "identity" -q`
- **Fix** : dériver toutes les identités d'un préfixe unique ; ne jamais
  réintroduire de constante en dur. Le Sprint 3 doit composer les identités
  TP-Link sur ce préfixe `vigil_` réel, pas sur `usg_watchdog` (ancien état,
  déjà remplacé).

## La sonde périodique sort par le lien 4G, et reste opt-in (C11)

- **Owner** : `src/managed_devices.py`, `src/drivers/tplink.py`
- **Preconditions** : la sonde est exécutée par SSH ponctuel sur le Pi Zero, qui
  a une interface vers le LAN **et** une vers le MR110.
- **Postconditions** : un succès exige **deux preuves concordantes** — IP
  publique observée différente de celle du site, et compteurs du MR110 en
  mouvement ; la sonde périodique est **désactivée par défaut** et s'active par
  équipement.
- **Invariants** : le Pi Zero a deux pattes — `eth0` vers le LAN et la fibre,
  `wlan0` vers le MR110. Lier l'interface **ne prouve pas** le chemin emprunté.
  Une sonde qui fuit vers la fibre réussirait systématiquement, et le warning ne
  partirait **jamais** : une alerte qui ne peut pas se déclencher est pire
  qu'absente, elle rassure à tort. Et sur un lien facturé au volume, sonder sans
  qu'on l'ait demandé consomme le forfait qu'on cherche à préserver.
- **Verify** : `python3 -m pytest tests/test_tplink_usage.py -k "probe_path_proof or probe_leak or probe_opt_in" -q`
- **Fix** : exiger les deux preuves avant de conclure ; conditionner l'activation
  à une déclaration explicite par équipement.

## Un routeur = un device HA, un seul poller (C12)

- **Owner** : `src/peer.py`, `src/managed_devices.py`, `src/mqtt_publisher.py`
- **Preconditions** : master et slave d'un même site voient le même MR110, et A2
  introduit du polling **périodique**.
- **Postconditions** : une seule instance interroge un équipement à un instant
  donné ; l'autre expose l'état du peer **avec son âge**. Le device HA est indexé
  sur **site + équipement**, et seul le poller élu publie ses entités.
- **Invariants** : un routeur MR n'accepte **qu'une session d'administration** —
  deux pollers permanents se déconnecteraient mutuellement en boucle. Et un
  MR110 est un équipement physique unique : l'indexer sur l'instance produirait
  deux devices pour un routeur, tandis que publier depuis les deux instances
  réintroduirait sur le device d'équipement la collision que le bugfix 1.8.1
  corrige sur celui du watchdog. Réutiliser la priorité de `peer.py` — **ne pas**
  écrire une seconde logique de failover.
- **Verify** : `python3 -m pytest tests/test_tplink_usage.py tests/test_mqtt_commands.py -k "poller_election or single_publisher or device_identity" -q`
- **Fix** : conditionner polling **et** publication à l'élection, et dériver
  l'identité du device du couple site + équipement.

## Un seul device USG par site (C15)

- **Owner** : `src/mqtt_publisher.py`, `src/peer.py`
- **Preconditions** : master et slave d'un même site observent le même USG.
- **Postconditions** : les capteurs de **ligne** (`gateway`, `internet`, RTT)
  vivent sur un device `USG <site>` **unique**, alimenté par l'instance élue ;
  les capteurs propres au **watchdog** (`score`, `status`, `reboots_today`,
  `uptime`) restent par instance. Un `binary_sensor` divergence et un capteur
  état du peer sont exposés sur le device watchdog.
- **Invariants** : un USG est un équipement physique unique — même raisonnement
  que C12 pour le MR110. Mais la déduplication fait perdre la comparaison des
  deux vues, qui servait à repérer un désaccord entre instances : elle **doit**
  être compensée par l'exposition explicite de la divergence, sans quoi on
  supprime un signal de sécurité au nom de la cosmétique. Ne pas confondre les
  deux familles : un score qui diffère entre master et slave est **normal**, un
  état de ligne qui diffère est un **symptôme**.
- **Verify** : `python3 -m pytest tests/test_mqtt_publisher.py -k "single_usg_device or divergence_sensor" -q`
- **Fix** : router chaque capteur vers le bon device selon ce qu'il décrit, et
  conditionner la publication du device de ligne à l'élection.

## L'enrichissement des capteurs USG est additif (C14)

- **Owner** : `src/mqtt_publisher.py`
- **Preconditions** : les 8 capteurs USG existants sont déjà déployés et ont un
  historique dans Home Assistant.
- **Postconditions** : ils reçoivent `device_class`, `state_class`, unité et
  `retain` ; leur **`unique_id` et leur type d'entité restent identiques**.
- **Invariants** : un changement d'`unique_id`, ou une conversion de `sensor`
  vers `binary_sensor`, fait **recréer l'entité** par Home Assistant — l'ancienne
  devient orpheline et son historique est perdu. C'est précisément le coût qu'on
  évite en enrichissant plutôt qu'en refondant. Le seul changement d'identité
  assumé du projet est celui du bugfix 1.8.1. Un capteur dérivé souhaitable
  s'**ajoute** à côté, il ne remplace pas l'existant.
- **Verify** : `python3 -m pytest tests/test_mqtt_publisher.py -k "legacy_sensors_unique_id_stable or legacy_sensors_enriched" -q`
- **Fix** : figer `unique_id` et type dans un test de référence, et n'ajouter que
  des clés au payload de discovery.

## La liste des entités HA est stable (C13)

- **Owner** : `src/mqtt_publisher.py`
- **Preconditions** : la discovery Home Assistant est publiée en `retain`.
- **Postconditions** : la liste des entités est décidée **une fois**, d'après les
  champs relevés par le spike ; un champ ensuite illisible passe `unavailable`.
- **Invariants** : des entités qui apparaissent et disparaissent au fil des
  cycles laissent des traces retenues, cassent les automatisations et trouent
  les historiques. Un champ absent n'est **jamais** publié à zéro : un zéro se
  confond avec une vraie valeur, et c'est la même famille d'erreur que le faux
  `OK` corrigé en C11.
- **Verify** : `python3 -m pytest tests/test_mqtt_publisher.py -k "entity_set_stable or unavailable_not_unpublished" -q`
- **Fix** : figer la liste à la construction du publisher ; publier
  `unavailable` au lieu de dépublier.

## Le cœur mono-cible n'est toujours pas touché

- **Owner** : `src/watchdog.py`, `src/state.py`
- **Preconditions** : A2 expose et commande des équipements, sans les intégrer à
  la boucle de surveillance.
- **Postconditions** : boucle de scoring, circuit-breaker et format de
  `WatchdogState` inchangés depuis la 1.8.
- **Invariants** : c'est ce qui maintient le risque de régression USG au plus
  bas jusqu'au PRD B, où le refactor sera jugé sur ses propres mérites.
- **Verify** : `git diff --quiet $(git describe --tags --abbrev=0 --match 'v1.8*') -- src/watchdog.py src/state.py`
- **Fix** : sortir le changement d'A2 et le remonter.

## Aucune action destructive automatique (C6, maintenu)

- **Owner** : `src/mqtt_publisher.py`, `src/managed_devices.py`
- **Preconditions** : A2 ajoute une **deuxième** voie de commande (après
  l'API).
  > **Mise à jour 2026-08-23** : cet invariant disait initialement « troisième
  > voie de commande (après l'API et Telegram) ». C'est faux depuis 2.2.0 :
  > Telegram (comme Discord, Slack et Pushover) a été **retiré du code**
  > (bascule Ntfy-first), et `src/telegram_bot.py` n'existe plus. MQTT devient
  > donc la **deuxième** voie de commande entrante du projet, pas la
  > troisième. Conservé pour mémoire, ne reflète plus l'état actuel.
- **Postconditions** : le reboot reste déclenché uniquement par une action
  opérateur explicite et gardée, tracée dans l'`EventLog` avec l'origine `mqtt`.
- **Invariants** : rebooter un secours **pendant qu'il porte le trafic**
  couperait le site. Ajouter une voie de commande ne doit pas ajouter une voie
  de contournement.
- **Verify** : `python3 -m pytest tests/test_mqtt_commands.py -k "no_auto_destructive" -q`
- **Fix** : faire converger toutes les voies vers la même garde dans le registre.

## Le suivi de conso survit aux remises à zéro du compteur

- **Owner** : `src/managed_devices.py`, `src/history.py`
- **Preconditions** : le compteur du routeur repart de zéro à un reboot, et selon
  le firmware.
- **Postconditions** : la conso du cycle s'accumule par **deltas positifs** ;
  une décroissance du compteur est traitée comme un reset.
- **Invariants** : A1 rend le reboot possible à la demande — le cas « compteur
  remis à zéro » n'est pas une hypothèse d'école, c'est une conséquence directe
  d'une commande que l'opérateur va utiliser. Une soustraction naïve produirait
  une conso négative ou un compteur figé.
- **Verify** : `python3 -m pytest tests/test_tplink_quota.py -k "counter_reset" -q`
- **Fix** : accumuler, ne jamais soustraire deux relevés bruts.

## Rendu inchangé sans équipement déclaré

- **Owner** : `src/dashboard.py`, `src/metrics.py`, `src/mqtt_publisher.py`
- **Preconditions** : un déploiement existant n'a aucune variable `TPLINK_*`.
- **Postconditions** : dashboard, `/metrics` et entités HA strictement
  identiques à avant.
- **Invariants** : les 4 instances reçoivent la 2.3.0 automatiquement. Rien ne
  doit bouger tant qu'un humain n'a pas déclaré un équipement, site par site.
- **Verify** : `python3 -m pytest tests/ -k "no_tplink_configured" -q`
- **Fix** : conditionner strictement tout rendu et toute publication à la
  déclaration.
