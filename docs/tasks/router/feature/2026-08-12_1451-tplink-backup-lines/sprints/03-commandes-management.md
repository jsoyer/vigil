# Sprint 3 — Commandes de management opérateur (API + Telegram)

- **PRD** : Lignes de secours TP-Link MR110 — phase A (management) — 2026-08-12
- **Dépend de** : Sprints 1, 2
- **Bloque** : sprints 4, 5
- **Nature** : **c'est le livrable que l'utilisateur attend en premier**

## Contexte (autoportant)

`usg-watchdog` tourne en **4 instances** : Dijon (master + slave), Nice (master
+ slave). Il expose déjà une API HTTP (15+ endpoints, auth Bearer optionnelle),
un dashboard, et un **bot Telegram interactif** en long-polling avec les
commandes `/status`, `/pause`, `/resume`, `/reboot`, `/ddns`, `/backup`,
`/tailscale`, `/help`.

Le Sprint 2 a livré `src/drivers/tplink.py` (`TplinkDriver`) : session gérée,
sonde étagée avec attribution de panne par saut (`Hop.BRIDGE` / `WIRELESS` /
`DEVICE` / `ROUTE`), métriques 4G, readiness, `reboot()`. **Rien n'est encore
exposé à l'opérateur.**

Ce sprint met ces capacités entre les mains de l'opérateur, **sans toucher au
cœur mono-cible** (`watchdog.py`, `state.py` restent intacts). Les MR110 sont
traités ici comme des **équipements pilotables déclarés**, pas comme des cibles
de la boucle de surveillance — cette bascule appartient à la phase B.

## Objectifs

1. Déclarer les équipements TP-Link en configuration.
2. Un registre d'équipements pilotables, indépendant de la boucle de scoring.
3. Endpoints API de management.
4. Commandes Telegram, avec garde-fous sur les actions dangereuses.

## Travail

### 3.1 Configuration

Déclaration par variables d'environnement numérotées, dans le style existant de
`config.py` (`_get_env`, `_get_int_env`, validation au startup) :

```
TPLINK_0_HOST=10.x.x.1        TPLINK_0_LABEL="Secours 4G Dijon"
TPLINK_0_PASSWORD=…           TPLINK_0_BRIDGE_HOST=192.168.x.x   # IP LAN du Pi Zero
TPLINK_0_RSRP_MIN=-110        TPLINK_0_RSRQ_MIN=…   TPLINK_0_SNR_MIN=…
```

- Validation au startup : IP valides, mot de passe présent. Configuration
  invalide → refus de démarrer avec message explicite.
- `BRIDGE_HOST` alimente l'étape 1 de la sonde étagée (le Pi Zero).
- **Aucun équipement déclaré → aucun changement de comportement.** Les 4
  instances qui se mettent à jour automatiquement ne doivent rien voir changer
  tant qu'on ne les configure pas explicitement.
- `TPLINK_*_PASSWORD` exclu de `/api/config` et de tout log.

### 3.2 Registre (`src/managed_devices.py`)

Petit module qui instancie un `TplinkDriver` par équipement déclaré et sert de
point d'entrée unique aux commandes.

- **Import paresseux** (C1) : ne construire les drivers que si au moins un
  équipement est déclaré ; ne jamais tirer `tplinkrouterc6u` au chargement du
  module.
- **Cache court** des lectures (défaut proposé : 60 s) : `/status` consulté
  trois fois de suite ne doit pas ouvrir trois sessions admin sur le routeur.
- **Sérialisation des accès** : un verrou par équipement, pour qu'une commande
  concurrente n'ouvre pas une seconde session admin en parallèle. Les routeurs
  MR n'en acceptent qu'une.
- **C5 (allégé en phase A)** : le master et le slave d'un même site peuvent tous
  deux recevoir une commande. Comme le management est ici **à la demande** (pas
  du polling continu), le risque de collision est faible mais réel. Mitigation
  minimale attendue : verrou local + `logout()` garanti + réessai unique en cas
  de session refusée, avec un message clair (« session admin occupée, réessayer »).
  L'exclusivité complète entre instances appartient à la phase B.

### 3.3 Endpoints API (`src/http_server.py`)

Suivre les conventions existantes (`_respond_json`, `503` si non prêt, auth
Bearer si configurée) :

- `GET /api/tplink` — liste des équipements déclarés + dernier état connu
- `GET /api/tplink/<id>` — détail : santé, `failed_hop`, readiness + raisons,
  métriques 4G, conso
- `POST /api/tplink/<id>/reboot` — reboot, **confirmation explicite requise**
  (voir 3.5)
- `POST /api/tplink/<id>/refresh` — force une lecture, ignore le cache

Selon ce que le spike a montré disponible (§ tableau des commandes) :

- `GET /api/tplink/<id>/sms` — SMS reçus (utile : les opérateurs envoient les
  alertes de quota et de solde par SMS)
- `POST /api/tplink/<id>/sms` — envoi de SMS
- `POST /api/tplink/<id>/ussd` — code USSD (consultation de solde/forfait)

**Ne pas exposer une commande que le spike n'a pas vue répondre** : mieux vaut
un endpoint absent qu'un endpoint qui échoue silencieusement.

### 3.4 Commandes Telegram (`src/telegram_bot.py`)

Dans le style des commandes existantes, réponses en français, contexte riche :

- `/lte` — état de tous les équipements déclarés : readiness, signal, type de
  réseau, opérateur, conso. En cas de problème, **nommer le saut en panne**
  (« le Pi Zero de Dijon ne répond pas » ≠ « le secours est HS »).
- `/lte <id>` — détail d'un équipement
- `/lte reboot <id>` — reboot, avec confirmation (voir 3.5)
- `/lte sms <id>` — derniers SMS reçus
- `/lte ussd <id> <code>` — code USSD
- `/help` — mis à jour

### 3.5 Garde-fous sur les actions dangereuses

- **Reboot** : confirmation explicite en deux temps. Motif : si le site tourne
  **sur** son secours au moment de la commande, le reboot coupe le site. Le
  message de confirmation doit dire ce qui est sur le point d'être redémarré,
  et signaler si l'équipement est en train de faire passer du trafic
  (`rx/tx_speed` non nul, clients associés) — c'est l'information qui doit
  faire hésiter.
- **SMS / USSD** : coûtent de l'argent ou consomment du forfait. Jamais
  déclenchés implicitement, jamais en réessai automatique.
- Toute commande est **tracée dans l'`EventLog`** avec son origine (API ou
  Telegram, et l'utilisateur Telegram le cas échéant) : `tplink_reboot`,
  `tplink_sms_sent`, `tplink_ussd_sent`.
- **C6** : aucune de ces actions n'est déclenchée par un chemin automatique.
  Elles proviennent toutes d'une commande opérateur.

## Tests

`tests/test_managed_devices.py`, `tests/test_http_server.py` (ajouts),
`tests/test_telegram_bot.py` (ajouts) — driver mocké, aucun accès réseau :

- Aucun équipement déclaré → endpoints absents ou vides, commandes Telegram
  répondent proprement, **aucun changement de comportement ailleurs**.
- `GET /api/tplink/<id>` : structure complète ; **mot de passe absent** de la
  réponse comme de `/api/config`.
- Panne par saut : chaque `failed_hop` produit un message opérateur **distinct
  et explicite**, en français.
- Reboot sans confirmation → refusé ; avec confirmation → exécuté et tracé dans
  l'`EventLog` avec l'origine.
- Reboot d'un équipement qui fait passer du trafic → l'avertissement est présent
  dans le message de confirmation.
- Cache : deux lectures rapprochées → **une seule** session ouverte sur le driver.
- Verrou : deux commandes concurrentes → sérialisées, pas de double session.
- Session refusée par le routeur → message clair, un seul réessai, pas de boucle.
- SMS / USSD : jamais déclenchés sans commande explicite (assert sur le mock).
- Endpoint d'une commande absente du firmware (selon le spike) → non exposé.

## Critères d'acceptation

- [ ] Équipements déclarables par env, validés au startup
- [ ] **Aucun équipement déclaré → comportement strictement inchangé**
- [ ] `GET /api/tplink`, `GET /api/tplink/<id>`, `POST …/refresh` fonctionnels
- [ ] `POST …/reboot` exige une confirmation et trace l'événement avec l'origine
- [ ] Commandes SMS/USSD exposées **uniquement** si le spike les a validées
- [ ] Telegram : `/lte`, `/lte <id>`, `/lte reboot`, `/help` à jour
- [ ] Message opérateur **distinct par saut en panne** (Pi Zero / WiFi / routeur
      / route absente)
- [ ] Avertissement si l'on s'apprête à rebooter un équipement qui porte du trafic
- [ ] Cache + verrou : pas de sessions admin multipliées
- [ ] Aucun secret dans l'API ni dans les logs
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Créer** : `src/managed_devices.py`, `tests/test_managed_devices.py`
- **Modifier** : `src/http_server.py`, `src/telegram_bot.py`, `src/config.py`,
  `src/events.py` (nouveaux types d'événements), `src/messages.py`
- **Lecture seule** : `src/drivers/`, `docs/spikes/`
- **Interdit** : `watchdog.py`, `state.py`, `peer.py`, `connectivity.py`
- **Contrats partagés** : `/api/config` et `/api/state` ne doivent exposer aucun
  secret ; les nouveaux endpoints s'**ajoutent**, ne remplacent rien
