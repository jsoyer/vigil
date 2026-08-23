# Sprint 3 — Home Assistant : capteurs par équipement et bouton de reboot armé

- **PRD** : A2 — Exposition & Home Assistant (2026-08-20)
- **Dépend de** : Sprints 1, 2 — **et du bugfix 1.8.1 (identité MQTT)**
- **Bloque** : Sprint 4
- **Nature** : **sprint le plus risqué du PRD** — il ouvre un chemin de commande entrant

## Contexte (autoportant)

`usg-watchdog` publie déjà vers MQTT avec auto-discovery Home Assistant, via
`src/mqtt_publisher.py` (225 lignes). L'état des lieux, relevé dans le code :

| Aspect | État actuel | Ligne |
|---|---|---|
| Sens de communication | **Lecture seule** — aucun `subscribe`, aucun `on_message`, aucun `command_topic` | — |
| Entités | 8 capteurs, source `WatchdogState` via `StateHolder` | `:50-77` (liste), `:182` (lecture `StateHolder`) |
| Discovery | `homeassistant/sensor/…/config`, `retain=True` | `:92` (topic), `:168` (`retain=True`) |
| États | publiés **sans `retain`** → `unknown` après redémarrage de HA | `:180-224` (`_publish_state`, aucun `retain=True`) |
| `device_class` / `state_class` | **absents** sur les 8 capteurs | `:50-89` |
| Identité | **corrigée par le bugfix 1.8.1** (était en dur, collision entre les 4 instances) | `:44`, `:83`, `:92`, `:125` |
| Cycle de vie | thread dédié, reconnexion automatique, publication toutes les `CHECK_INTERVAL` s | `:134-139` (thread), `:178` (intervalle) |
| Config | `MQTT_BROKER`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_HA_DISCOVERY` | `config.py:331-337` |

> **Mise à jour 2026-08-23** : toutes les lignes de ce tableau ont été
> re-vérifiées sur le code réel de la branche `dev` — les anciennes citations
> avaient dérivé depuis l'écriture du PRD (le bloc MQTT de `config.py` est
> maintenant aux lignes 331-337, pas 252-263).

Le squelette (connexion, reconnexion, discovery, thread) est solide et
**réutilisable tel quel**. Sa suite de tests est déjà exhaustive.

Ce qui manque et que ce sprint ajoute : des entités **par équipement TP-Link**,
et surtout un **chemin de commande entrant**, qui n'existe nulle part dans le
projet.

## Objectifs

1. Un device Home Assistant **par équipement TP-Link**, avec ses capteurs.
2. Un chemin de commande entrant, **gardé**.
3. Un bouton de reboot qui ne peut pas partir tout seul.

## Travail

### 3.1 Capteurs par équipement

- **Un device HA par routeur**, indexé sur **site + équipement** — **jamais** sur
  l'instance (C12). Un MR110 est un équipement physique unique, pas un par
  watchdog qui le regarde. Ce device est distinct de celui du watchdog.
- **Seul le poller élu au Sprint 1 publie** ces entités. Publier depuis les deux
  instances réintroduirait, sur le device d'équipement, exactement la collision
  que le bugfix 1.8.1 corrige sur celui du watchdog.

**Entités à publier :**

*Disponibilité du secours*

| Entité | Type | Classe | Valeurs / unité |
|---|---|---|---|
| Readiness | `sensor` | `enum` | `ok` / `degraded` / `unknown` |
| Secours dégradé | `binary_sensor` | `problem` | doublon de la readiness, pour automatiser |
| Lien attaché | `binary_sensor` | `connectivity` | ce que **le routeur déclare** |
| Résultat de sonde | `sensor` | `enum` | `ok` / `fail` / `leak` / `unknown` — ce qui est **prouvé** |
| Dernière sonde | `sensor` | `timestamp` | fraîcheur de l'information |

« Attaché » et « la data passe » sont **deux entités distinctes** : c'est tout
l'objet de C11, et les confondre annulerait le bénéfice de la sonde.

*Signal 4G* — `state_class: measurement`

| Entité | Classe | Unité |
|---|---|---|
| RSRP | `signal_strength` | dBm |
| RSRQ | `signal_strength` | dB |
| SNR | — | dB |
| Niveau de signal | — | 0-5 |
| Type de réseau / état SIM / opérateur | `enum` ou texte | `entity_category: diagnostic` |

*Forfait et trafic*

| Entité | Classe | `state_class` | Unité |
|---|---|---|---|
| Conso du cycle | `data_size` | `total_increasing` | Mo |
| % du forfait | — | `measurement` | % |
| Prochain reset | `timestamp` | — | — |
| Débits rx / tx | `data_rate` | `measurement` | kbit/s |
| État d'usage | `enum` | — | `idle` / `in_use` / `saturated` |

`total_increasing` est le bon choix : Home Assistant interprète nativement une
décroissance comme une remise à zéro, ce qui correspond au reset de facturation.

*Diagnostic du chemin* — `entity_category: diagnostic`, repliés par défaut

Saut en panne (`enum` : `bridge` / `wireless` / `device` / `route` / aucun),
RTT vers le routeur (ms, `measurement`), âge de la donnée si elle provient du
peer (C12).

**Règles transverses :**

- `device_class` et `state_class` renseignés comme ci-dessus (sans eux, pas de
  statistiques long terme côté HA), **états publiés avec `retain`** (sinon
  `unknown` après chaque redémarrage de HA).
- **C13 — la liste des entités est stable dans le temps.** La discovery est
  *retained* : des entités qui apparaissent et disparaissent au fil des cycles
  rendent automatisations et historiques inutilisables. La liste se décide **une
  fois**, d'après les champs relevés par le spike sur ce firmware. Un champ
  ensuite illisible devient **`unavailable`**, jamais dépublié — et n'est jamais
  publié à zéro, un zéro se confondant avec une vraie valeur.
### 3.1bis Répartition et mise à niveau des capteurs USG (C14, C15)

Deux problèmes à traiter ensemble sur les 8 capteurs existants.

**(a) L'USG apparaît en double par site.** Master et slave publient chacun leur
vue. Or un USG est un équipement physique unique — même raisonnement que C12
pour le MR110. Les capteurs se répartissent donc selon ce qu'ils **décrivent** :

| Device | Un par | Publié par | Capteurs |
|---|---|---|---|
| `USG <site>` | **site** | l'instance **élue** (C12) | `gateway`, `internet`, `gateway_rtt`, `internet_rtt` |
| `Watchdog <site> <rôle>` | **instance** | chaque instance | `score`, `status`, `reboots_today`, `uptime` |

Les quatre premiers décrivent la **ligne** ; les quatre suivants décrivent le
**watchdog qui l'observe** — et ceux-là divergent légitimement d'une instance à
l'autre, ce sont bien quatre watchdogs distincts.

**Métriques de l'hôte (C17)** — à ajouter sur le device watchdog, puisqu'elles
décrivent la machine et non la ligne :

| Entité | Classe | `state_class` | Unité | Source |
|---|---|---|---|---|
| Température CPU | `temperature` | `measurement` | °C | `/sys/class/thermal` |
| Espace disque libre | `data_size` | `measurement` | Go | `os.statvfs` |
| Disque utilisé | — | `measurement` | % | `os.statvfs` |
| Mémoire disponible | `data_size` | `measurement` | Mo | `/proc/meminfo` |
| Charge (1 min) | — | `measurement` | — | `/proc/loadavg` |

**Stdlib uniquement** — aucune dépendance ajoutée, conforme à la ligne du projet.
Champ indisponible (zone thermique absente sur une plateforme non-Pi) → entité
`unavailable`, **jamais zéro** (C13).

Ces métriques comptent particulièrement sur les instances **`bridged`** : un
Pi Zero y porte à la fois un watchdog et le pont vers le MR110, donc sa santé
conditionne la surveillance du secours.

**Compensation obligatoire.** Publier une seule vue de la ligne fait perdre la
possibilité de repérer un désaccord entre master et slave. `peer.py` détecte
déjà cette divergence sans l'exposer. Ajouter, sur le device watchdog :
- `binary_sensor` **divergence** (`device_class: problem`) ;
- `sensor` **état du peer** (`enum`).

Le signal est restitué, et sous une forme meilleure : une alerte explicite plutôt
que deux courbes à comparer à l'œil.

**Coût assumé** : les 4 capteurs de ligne changent d'`unique_id` (il devient
propre au site), donc Home Assistant les **recrée** — une seconde fois après
1.8.1. Ne pas chercher à l'éviter en anticipant dans le bugfix : des entités par
site **sans publieur unique** feraient écrire les deux instances dedans, soit le
bug corrigé reproduit. L'élection n'existe qu'à partir du Sprint 1 d'A2.

**(b) Les capteurs USG sont moins bien instrumentés que ceux du MR110.** Sans
correction, la ligne de secours aurait graphiques et statistiques long terme, et
pas la fibre. Incohérent pour l'opérateur.

| Capteur | Ajout |
|---|---|
| `score` | `state_class: measurement` |
| `status` | `device_class: enum` |
| `gateway` | `device_class: enum` (reste `OK`/`KO`) |
| `internet` | `device_class: enum` (reste `"{ok}/{total}"`) |
| `reboots_today` | `state_class: total_increasing` |
| `gateway_rtt` | unité `ms`, `state_class: measurement` |
| `internet_rtt` | unité `ms`, `state_class: measurement` |
| `uptime` | `device_class: duration`, unité `s`, `state_class: measurement` |

Plus **`retain` sur les états** des huit : aujourd'hui ils ne le sont pas
(`mqtt_publisher.py:180-224`, méthode `_publish_state` — vérifié 2026-08-23,
était cité `:149-172`), donc les entités passent `unknown` après chaque
redémarrage de Home Assistant.

**C14 — l'enrichissement reste additif.** Le **type d'entité** ne change pas. En
particulier, **ne pas convertir `gateway` ou `internet` en `binary_sensor`**, si
tentant que ce soit : ce serait une recréation **supplémentaire**, en plus de
celle qu'impose déjà C15 sur ces mêmes capteurs. Si un capteur numérique dérivé
est souhaitable (par exemple un compte de cibles internet joignables), c'est une
entité **nouvelle** qui s'ajoute à côté.

Pour les 4 capteurs restés sur le device watchdog, l'`unique_id` ne change pas
non plus : leur enrichissement est purement additif, sans recréation.

Ne rien changer d'autre : `availability_topic` / LWT et l'exposition du topic
`{prefix}/state` restent hors périmètre.

### 3.2 Chemin de commande entrant — la partie sensible

C'est la première fois que le projet **écoute** MQTT. Conséquence de sécurité à
traiter, pas à mentionner : quiconque peut publier sur le broker peut déclencher
une action.

- `subscribe` sur les topics de commande des équipements, `on_message` avec
  parsing strict : tout message non conforme est **ignoré et loggé**, jamais
  interprété au mieux.
- **C9** : documenter que le broker **doit** être authentifié.
  `MQTT_USERNAME` / `MQTT_PASSWORD` existent déjà (`config.py:334-335` —
  vérifié 2026-08-23, était cité `:260-261`) ; si le
  broker est anonyme, le chemin de commande ne doit pas être activé.
- Rendre l'écoute **désactivable** indépendamment de la publication : un
  déploiement peut vouloir les capteurs sans les commandes.
- Exécution **hors de la boucle principale**, comme en A1 : passer par le
  registre `managed_devices`, jamais par la queue `StateHolder` (elle ne dépile
  qu'une commande par cycle et son `CMD_REBOOT` bloque la boucle).

### 3.3 Bouton de reboot et entité *arm*

Un `button` Home Assistant se presse **en un geste, sans confirmation possible**.
Or rebooter un secours en service coupe le site. La confirmation en deux temps
d'A1 (jeton Telegram) n'a pas d'équivalent naturel dans une interface HA.

> **Mise à jour 2026-08-23** : Telegram a été retiré du code en 2.2.0. La
> confirmation en deux temps qu'A1 offrait par ce canal n'existe donc plus non
> plus — l'argument reste valable tel quel : quel que soit le canal d'A1,
> aucun ne fournissait de confirmation en deux temps nativement transposable à
> HA, d'où le pattern *arm* + `button` ci-dessous.

**Pattern retenu** — l'équivalent MQTT de la confirmation en deux temps :

- une entité **`switch` « armer le reboot »**, à **désarmement automatique** après
  un délai court ;
- une entité **`button` « reboot »** qui **refuse** de s'exécuter si l'entité
  *arm* n'est pas active ;
- une entité **`sensor` « dernière action »** portant le résultat et, en cas de
  refus, **le motif**.

**C10 — aucun échec silencieux.** Sans l'entité de dernière action, un refus est
indistinguable d'un message perdu, et l'opérateur presse le bouton en boucle.

**L'état « en service » est remonté, pas bloquant.** On reboote parfois
précisément un équipement qui dysfonctionne pendant qu'il sert. Le refuser serait
paternaliste ; le taire serait dangereux. L'information figure dans l'entité
*arm* et dans la dernière action ; la décision reste à l'opérateur.

Toute commande reçue est tracée dans l'`EventLog` avec l'origine `mqtt`,
distincte de `api`.

> **Mise à jour 2026-08-23** : cette phrase distinguait initialement l'origine
> `mqtt` de `api` **et** `telegram`. Telegram a été retiré du code en 2.2.0 —
> il ne reste que deux origines de commande possibles (`api`, `mqtt`).

## Tests

Client MQTT et driver mockés, aucun accès réseau ni broker réel.

- Deux équipements déclarés → deux devices HA **distincts**, entités disjointes.
- **C12** : le device d'un routeur est indexé sur site + équipement — **identique
  vu du master et du slave** (pas de doublon pour un routeur physique).
- **C12** : seule l'instance élue publie ; la non élue ne publie **aucune** entité
  d'équipement (assertion sur l'absence de publication).
- **C13** : la liste des entités ne varie pas d'un cycle à l'autre ; un champ
  devenu illisible passe `unavailable` et n'est **pas** dépublié.
- Champ absent → capteur **non publié** (et non publié à zéro).
- Nouvelles entités : `device_class` / `state_class` présents, états `retain`.
- **C15** : un seul device `USG <site>` par site, **identique vu du master et du
  slave** ; seule l'instance élue y publie (assertion sur l'absence de
  publication par la non élue).
- **C15** : `score`, `status`, `reboots_today`, `uptime` restent sur le device
  **par instance** et conservent leur `unique_id` (aucune recréation).
- **C15** : `binary_sensor` divergence et capteur état du peer présents sur le
  device watchdog ; un désaccord simulé lève le `binary_sensor`.
- **C14** : aucun capteur converti en `binary_sensor` ; seuls `device_class`,
  `state_class`, l'unité et `retain` s'ajoutent (assertion clé par clé sur le
  payload de discovery).
- Les états des 8 capteurs sont désormais publiés avec `retain`.
- **Bouton sans arm → refusé**, et l'entité de dernière action porte le motif.
- Arm actif → reboot exécuté, tracé avec origine `mqtt`.
- Arm se désarme seule après le délai ; bouton pressé après expiration → refusé.
- Équipement en service → l'information est présente, **le reboot n'est pas
  bloqué** pour autant.
- Message malformé sur un topic de commande → ignoré et loggé, **aucune action**.
- Écoute désactivée → aucun `subscribe`, les capteurs fonctionnent toujours.
- Aucun secret dans les payloads publiés.

## Critères d'acceptation

- [x] **C12** : un device HA **par routeur** (site + équipement), identique vu des
      deux instances ; **seul le poller élu publie** — device
      `vigil_<site>_tplink_<id>` (commit `d50e037`)
- [x] `device_class` / `state_class` conformes au tableau, `retain` sur les états
      (commit `d50e037`)
- [x] **C14** : capteurs USG enrichis, type d'entité **inchangé**, états en `retain`
      — les 8 `unique_id` historiques épinglés par test (commit `d50e037`)
- [x] **C15** : un seul device `USG <site>` par site, alimenté par l'instance élue
      (commit `d50e037`)
- [x] **C15** : capteurs propres au watchdog restés par instance, `unique_id`
      inchangé (pas de recréation pour ceux-là) — device `Watchdog <instance>`
      enrichi en place (commit `d50e037`)
- [x] **C15** : divergence et état du peer exposés sur le device watchdog
      (commit `d50e037`)
- [x] **C17** : température, disque, mémoire et charge sur le device watchdog,
      en stdlib seule ; zone thermique absente → `unavailable`, jamais zéro
      (commit `d50e037`)
- [x] **C13** : liste d'entités stable ; champ illisible → `unavailable`, jamais
      dépublié ni publié à zéro (commit `d50e037`)
- [x] Les 8 capteurs existants inchangés (commit `d50e037`)
- [x] `subscribe` + parsing strict ; message malformé ignoré et loggé —
      `tests/test_mqtt_commands.py` (458 lignes ajoutées, commit `d50e037`)
- [x] **C9** : écoute désactivable ; exigence de broker authentifié documentée
      — conditionnée à `MQTT_COMMANDS_ENABLED` + broker authentifié (commit
      `d50e037`)
- [x] **Bouton refusé sans arm** ; arm à désarmement automatique — switch
      arm avec expiration auto (commit `d50e037`)
- [x] **C10** : entité de dernière action avec résultat et motif de refus —
      button reboot refuse sans arm avec motif publié (commit `d50e037`)
- [x] État « en service » remonté, non bloquant (commit `d50e037`)
- [x] Commandes tracées avec l'origine `mqtt` — exécution via
      `managed_devices` uniquement, `EventLog` origine `mqtt` (commit
      `d50e037`)

**Preuve globale** : 50 nouveaux tests, suite complète à 1254 tests,
coverage 89 %, `./scripts/validate.sh` vert (commit `d50e037`).
- [ ] Exécution hors queue `StateHolder`
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Créer** : `tests/test_mqtt_commands.py`
- **Modifier** : `src/mqtt_publisher.py`, `src/config.py`, `src/managed_devices.py`,
  `src/events.py`, `tests/test_mqtt_publisher.py`
- **Lecture seule (ajout)** : `src/peer.py` — l'élection est livrée au Sprint 1,
  ce sprint la consomme sans la modifier
- **Lecture seule** : `src/drivers/`, `src/http_server.py`
  > **Mise à jour 2026-08-23** : `src/telegram_bot.py` retiré de cette liste —
  > le fichier n'existe plus depuis 2.2.0 (retrait de Telegram/Discord/Slack/
  > Pushover du code, bascule Ntfy-first).
- **Interdit** : `watchdog.py`, `state.py`, `peer.py`, `dashboard.py`, `metrics.py`
- **Contrats partagés** : les topics MQTT et les `unique_id` sont consommés par
  Home Assistant — les changer recrée les entités côté HA
