# Sprint 3 — Commandes de management opérateur (API + Telegram)

- **PRD** : A1 — Pilotage des lignes de secours TP-Link MR110 (2026-08-20)
- **Dépend de** : Sprints 1, 2
- **Bloque** : Sprint 4
- **Nature** : **c'est le livrable que l'utilisateur attend en premier**

## Contexte (autoportant)

`Vigil` (anciennement `usg-watchdog`, renomme en 2.0.0) tourne en **4
instances** : Dijon (master + slave), Nice (master
+ slave). Il expose une API HTTP et un **bot Telegram** en long-polling avec 8
commandes : `/status`, `/pause`, `/resume`, `/reboot`, `/ddns`, `/backup`,
`/tailscale`, `/help`.

Le Sprint 2 a livré `src/drivers/tplink.py` (`TplinkDriver`) : session gérée,
sonde étagée avec attribution de panne par saut (`Hop.BRIDGE` / `WIRELESS` /
`DEVICE` / `ROUTE`), métriques 4G, readiness, `reboot()`. **Rien n'est encore
exposé à l'opérateur.**

Ce sprint met ces capacités entre les mains de l'opérateur **sans toucher au
cœur mono-cible** : `watchdog.py` et `state.py` restent intacts. Les MR110 sont
traités comme des **équipements pilotables déclarés**, pas comme des cibles de
la boucle de surveillance.

### Deux prérequis à traiter avant les commandes elles-mêmes

L'analyse du code a montré que deux briques supposées présentes n'existent pas.
Ce sont les premières tâches du sprint, pas des détails d'implémentation.

**(P1) Le dispatcher Telegram ne parse aucun argument.**
`telegram_bot.py:48` fait `cmd = command.strip().lower().split("@")[0]`, puis
`_handle_command` (`:42-145`) enchaîne des `if/elif` sur `cmd` entier. Il n'y a
**pas de `split(" ")`** : `/status foo` n'est pas reconnu comme `/status` et
tombe dans le `else` « Commande inconnue » (`:144`). Donc `/lte reboot dijon`
serait rejeté.

**(P2) Aucune confirmation côté serveur n'existe dans le projet.**
`/reboot` (`:93-95`) enfile `CMD_REBOOT` immédiatement. Le seul précédent de
confirmation est un `confirm()` JavaScript dans le dashboard
(`dashboard.py:524-525`), purement client, sans contrepartie serveur. Et
`allowed_updates: ["message"]` (`telegram_bot.py:181`) **exclut les
`callback_query`** : les boutons inline Telegram ne remonteraient même pas.

### Convention d'exécution à respecter

Le projet distingue déjà deux familles de commandes :
- ce qui touche l'état du watchdog passe par la queue `StateHolder`
  (`http_server.py:113-119` → `state.py:106-115` → `watchdog.py:395-446`) ;
- ce qui est une **action externe** s'exécute directement dans le thread HTTP :
  `/api/ddns/update` (`:427`), `/api/backup/unifi` (`:347`),
  `/api/tailscale/sync` (`:415`).

Les commandes TP-Link relèvent du **second cas**. Deux raisons de ne pas passer
par la queue : elle ne dépile **qu'une commande par cycle** (`watchdog.py:396`),
et `CMD_REBOOT` bloque la boucle jusqu'à `USG_REBOOT_WAIT` secondes
(`:426-427`). Un reboot de MR110 ne doit pas immobiliser la surveillance USG.

## Travail

### 3.1 (P1) Parsing d'arguments dans le dispatcher Telegram

Étendre `_handle_command` (`telegram_bot.py:42-145`) pour séparer la commande de
ses arguments.

- **Contrainte absolue** : les 8 commandes existantes gardent un comportement
  **identique**, y compris leurs cas limites actuels. Test de non-régression sur
  chacune.
- Conserver `chat_id != TELEGRAM_CHAT_ID` (`:195-197`) comme seul contrôle
  d'accès — ne pas élargir la surface d'autorisation dans ce sprint.
- Ne **pas** toucher à `allowed_updates` (`:181`) : les boutons inline sont hors
  périmètre, la confirmation se fait par commande texte (voir 3.2).
- `/help` (`:131-142`) est un texte statique à synchroniser à la main.

### 3.2 (P2) Confirmation serveur des actions destructives

Pattern retenu : **action en attente, jeton court, usage unique**.

- Telegram : `/lte reboot <id>` **n'exécute pas** — il retourne un jeton et un
  rappel d'état, dont **l'avertissement si l'équipement fait passer du trafic**
  (débit rx/tx non nul, clients associés). `/lte confirm <jeton>` exécute.
- API : `POST /api/tplink/<id>/reboot` exige une confirmation explicite dans le
  corps ; sans elle, `400` **décrivant la confirmation attendue** (une erreur qui
  n'explique pas quoi envoyer force à lire le code).
- TTL court, jeton à usage unique, invalidé après exécution ou expiration.
- Le mécanisme est **générique**, pas spécifique au reboot : SMS et USSD
  l'utiliseront aussi.

Motif : rebooter un secours **pendant qu'il porte le trafic** couperait le site.
C'est le pire scénario de la feature.

### 3.3 Configuration des équipements

Déclaration par variables d'environnement numérotées, dans le style de
`config.py` (validation au startup, refus de démarrer si incohérent) :

```
TPLINK_0_HOST=…        TPLINK_0_LABEL="Secours 4G Dijon"
TPLINK_0_PASSWORD=…    TPLINK_0_BRIDGE_HOST=…   # IP LAN du Pi Zero
TPLINK_0_RSRP_MIN=-110 TPLINK_0_RSRQ_MIN=…      TPLINK_0_SNR_MIN=…
```

- **Ce pattern numéroté n'existe nulle part dans le projet** — il est à créer.
  Les seuls précédents multi-valeurs sont `PING_TARGETS` (liste Python en dur,
  `config.py:44-48`) et `CLOUDFLARE_RECORD_NAMES` (CSV, `:274`). Concevoir
  explicitement la découverte des index et la validation.
- `BRIDGE_HOST` alimente l'étape 1 de la sonde étagée (le Pi Zero).
- **Aucun équipement déclaré → aucun changement de comportement.** Les 4
  instances reçoivent la 1.9.0 automatiquement : rien ne doit bouger tant qu'un
  humain n'a pas déclaré un équipement, site par site.

### 3.4 Masquage de secrets

Le projet n'a **aucun mécanisme de masquage** : les 11 secrets existants sont
lus en `os.getenv(X, "")` (`config.py:163-289`) et la protection repose
entièrement sur des whitelists construites à la main.

- Ajouter un **helper de redaction réutilisable**, sur motif de nom
  (`*_PASSWORD`, `*_TOKEN`, `*_KEY`, `*_WEBHOOK_URL`), appliqué aux logs.
  Bénéfice sur les 11 secrets existants, pas seulement TP-Link.
- `TPLINK_<n>_PASSWORD` doit être **absent des trois whitelists**, qui sont
  divergentes et à maintenir séparément :
  `_handle_config` (dict littéral, `http_server.py:290-311`),
  `_EXPORT_SAFE_KEYS` (`:356-366`), `_SAFE_RELOAD_KEYS` (`:384-391`).
  Test dédié sur les trois.

### 3.5 Registre `src/managed_devices.py`

Instancie un `TplinkDriver` par équipement déclaré ; point d'entrée unique des
commandes.

- **Import paresseux** (C1) : ne construire les drivers que si au moins un
  équipement est déclaré ; ne jamais tirer `tplinkrouterc6u` au chargement.
- **Cache court** des lectures (défaut 60 s) : trois `/status` d'affilée ne
  doivent pas ouvrir trois sessions admin.
- **Verrou par équipement** : les MR n'acceptent **qu'une session admin**. Deux
  commandes concurrentes se sérialisent.
- Session refusée par le routeur → message clair (« session admin occupée »),
  **un seul** réessai. Une boucle de réessai transformerait une collision en
  déni de service.

### 3.6 Endpoints API (`src/http_server.py`)

Conventions existantes (`_respond_json`, `503` si non prêt, auth Bearer) :

- `GET /api/tplink` — équipements déclarés + dernier état connu
- `GET /api/tplink/<id>` — santé, `failed_hop`, readiness + raisons, métriques 4G
- `POST /api/tplink/<id>/refresh` — force une lecture, ignore le cache
- `POST /api/tplink/<id>/check` — sonde de bout en bout (C11), non destructive
- `POST /api/tplink/<id>/reboot` — confirmation requise (3.2)
- Selon ce que le **spike** a validé : `GET`/`POST /api/tplink/<id>/sms`,
  `POST /api/tplink/<id>/ussd`

**Ne pas exposer une commande que le spike n'a pas vue répondre** : mieux vaut un
endpoint absent qu'un endpoint qui échoue silencieusement.

**C19 — authentifier aussi les GET.** Contrairement aux GET existants du projet,
`/api/tplink/*` exige le jeton Bearer **en lecture comme en écriture** : ces
réponses exposent état SIM, opérateur, IP WAN et consommation. Divergence
assumée avec `/api/state` et `/api/events`, qui restent ouverts.

- **Fail closed** : `API_TOKEN` absent ⇒ `403`, y compris en GET — même
  comportement que les POST aujourd'hui (`http_server.py:99-101`).
- **Jamais de jeton côté client** : le dashboard (A2) rendra ces données
  **côté serveur**, il n'appellera pas l'endpoint authentifié depuis le
  navigateur. Y placer le jeton l'exposerait à quiconque ouvre la page.

> **Prérequis de déploiement** : sans `API_TOKEN`, ni les commandes ni la
> lecture TP-Link ne sont accessibles par l'API. Telegram reste utilisable.
> À documenter au Sprint 4.

### 3.7 Commandes Telegram

Style des commandes existantes, français, contexte riche :

- `/lte` — tous les équipements : readiness, signal, réseau, opérateur. En cas de
  problème, **nommer le saut en panne**. « Le pont de Dijon ne répond pas » et
  « le secours est HS » sont deux messages différents. Sur `BRIDGE`, rester
  prudent : le Pi Zero est en PoE, ça peut être le Pi, son port de switch, le
  budget PoE ou le câble.
- `/lte <id>` — détail d'un équipement
- `/lte check <id>` — **sonde de bout en bout à la demande** (C11) : répond à
  « est-ce que ce secours marche vraiment, là, maintenant ? ». Distinguer
  clairement dans la réponse *attaché* (le routeur le dit) de *data qui passe*
  (la sonde le prouve) — c'est tout l'intérêt de la commande. Un résultat `LEAK`
  se dit comme un **défaut de configuration du chemin de test**, jamais comme un
  problème du secours : « impossible de tester : la sonde est sortie par la
  fibre ». Action non destructive : **pas de confirmation requise**.
- `/lte reboot <id>` → jeton ; `/lte confirm <jeton>` → exécution
- `/lte sms <id>`, `/lte ussd <id> <code>` — si validés au spike
- `/help` — mis à jour

### 3.8 Traçabilité

Toute commande est tracée dans l'`EventLog` avec son **origine** (API ou
Telegram) : `tplink_reboot`, `tplink_sms_sent`, `tplink_ussd_sent`.

**Niveaux de notification.** Ces événements passent par `notify()` et sont
diffusés à tous les canaux configurés (Telegram, Discord, Slack, ntfy, e-mail,
Pushover, MQTT), chacun filtrant par son `*_MIN_LEVEL` — aucun code par canal à
écrire. Commande **réussie** → `INFO` : l'opérateur vient de la lancer, il n'a
pas besoin d'être réveillé. Commande **en échec** → `WARNING` : il croit avoir
agi alors que non. Ne pas mettre de `CRITICAL` ici ; A2 les réserve aux
situations où le secours est réellement compromis.
**C6** : aucune de ces actions n'est atteignable par un chemin automatique.

## Tests

Driver mocké, aucun accès réseau.

- **(P1) Non-régression Telegram** : les 8 commandes existantes se comportent à
  l'identique après l'ajout du parsing d'arguments — un test par commande.
- **(P2) Confirmation** : reboot sans jeton → refusé ; jeton expiré → refusé ;
  jeton réutilisé → refusé ; jeton valide → exécuté et tracé avec l'origine.
- Équipement en cours d'usage → l'avertissement figure dans la réponse de
  demande de confirmation.
- Aucun équipement déclaré → endpoints vides, commandes Telegram répondent
  proprement, **aucun changement ailleurs**.
- Panne par saut : chaque `failed_hop` produit un message opérateur **distinct**,
  en français.
- Cache : deux lectures rapprochées → **une seule** session ouverte.
- Verrou : deux commandes concurrentes → sérialisées, pas de double session.
- Session refusée → message clair, **un seul** réessai, pas de boucle.
- SMS / USSD jamais déclenchés sans commande explicite (assert sur le mock).
- **Secrets** : `TPLINK_<n>_PASSWORD` absent de `/api/config`, de l'export et du
  reload (les 3 whitelists) ; helper de masquage appliqué (capture de logs).

## Critères d'acceptation

- [ ] **(P1)** Parsing d'arguments ajouté ; **les 8 commandes existantes
      inchangées**, prouvé par un test chacune
- [ ] **(P2)** Confirmation serveur générique (jeton court, usage unique)
- [ ] Reboot : refusé sans confirmation ; exécuté et tracé avec origine sinon
- [ ] Avertissement si l'équipement porte du trafic au moment de la demande
- [ ] Équipements déclarables (pattern numéroté créé), validés au startup
- [ ] **Aucun équipement déclaré → comportement strictement identique à la 1.8**
- [ ] Endpoints `/api/tplink/*` fonctionnels ; SMS/USSD exposés **uniquement**
      si validés au spike
- [ ] **C19** : GET `/api/tplink/*` authentifiés ; `403` sans `API_TOKEN` ;
      testé en lecture comme en écriture
- [ ] Telegram : `/lte`, `/lte <id>`, `/lte check`, `/lte reboot`, `/lte confirm`, `/help`
- [ ] `/lte check` distingue explicitement *attaché* de *data qui passe*
- [ ] `/lte check` n'exige **pas** de confirmation (action non destructive)
- [ ] Message opérateur **distinct par saut**, prudent sur la cause d'un `BRIDGE`
- [ ] Cache + verrou : pas de sessions admin multipliées
- [ ] Helper de masquage en place ; secret absent des **3** whitelists
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Créer** : `src/managed_devices.py`, `tests/test_managed_devices.py`
- **Modifier** : `src/http_server.py`, `src/telegram_bot.py`, `src/config.py`,
  `src/events.py`, `src/messages.py`
- **Lecture seule** : `src/drivers/`, `docs/spikes/`
- **Interdit** : `watchdog.py`, `state.py`, `peer.py`, `connectivity.py`,
  `dashboard.py`, `metrics.py`, `mqtt_publisher.py` (A2)
- **Contrats partagés** : les 3 whitelists de config — toute option nouvelle se
  déclare aux 3 endroits, et aucun secret n'y entre
