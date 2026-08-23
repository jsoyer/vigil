# Sprint 2 — Endpoint de confirmation à capacité + boutons d'action ntfy

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram.md` (§ 4.1, § 4.2 en entier, § 8 S2, § 9 AC sécurité, § 0bis Q5/Q7)
- **Dépend de** : Sprint 1 (canal ntfy enrichi, `NotificationContext.category`)
- **Gate d'entrée** : `tailscale-telephones-verifie` de `progress.json` (vérifié par l'orchestrateur avant d'ouvrir ce sprint)
- **Taille estimée** : 90 min (le plus sensible du PRD — point de sécurité central)
- **Isolation** : worktree

## Objectif

C'est le cœur sécurité du PRD (§ 4.2). Créer `POST
/api/confirm/<action>/<jeton>`, **seul** endpoint POST exempté de
`_check_auth()`, durcir `src/confirm.py` (D1-D7, y compris le TTL 600s de la
décision Q5), et publier les boutons `Actions` ntfy (confirmer / annuler)
depuis `managed_devices.py` via une fonction `send` injectée —
**sans jamais transmettre `API_TOKEN`**.

## Contexte technique vérifié

- `src/confirm.py` (à ce jour) : `DEFAULT_TTL_SECONDS = 120.0` (L20),
  `_get_ttl_seconds()` lit `CONFIRM_TTL` sinon retombe sur ce défaut.
  `secrets.token_hex(4)` pour générer le jeton (32 bits) — à durcir en D1.
  Zéro couplage canal (déjà vérifié par le PRD § 2.2).
- `src/http_server.py` : `_check_auth()` (L107-118) compare
  `auth == f"Bearer {_config.API_TOKEN}"` avec `==` (à durcir en D2, comme le
  jeton). `do_POST()` (L120+) appelle `_check_auth()` en tout premier, avant
  tout dispatch de route — **le nouvel endpoint `/api/confirm/*` doit être
  routé avant cet appel**, pas après avec un contournement local. Routes
  POST existantes : `/api/pause`, `/api/resume`, `/api/reboot`,
  `/api/ddns/update`, `/api/tailscale/sync`, `/api/backup/unifi`,
  `/api/maintenance`, `/api/config/reload`. `log_message()` (L690-691) :
  `logging.debug("HTTP: %s", format % args)` — journalise la requête brute,
  donc le chemin complet, donc le jeton en clair aujourd'hui (à masquer, D4).
- `src/managed_devices.py` : `_register_telegram_handlers()` (L367-394),
  `_adapt_for_telegram()` (L397-408, `send=telegram_bot.send_message`),
  appel depuis `bootstrap()` (L364), `origin="telegram"` en dur en L531 et
  L555. Ces fonctions restent **intactes** dans ce sprint (invariant « 8
  commandes Telegram intactes ») — ce sprint ajoute un chemin *parallèle*
  pour ntfy, il ne modifie pas le chemin Telegram existant.
- `src/notifier/_types.py` : `NotificationContext` a reçu `category` au
  sprint 1 — pas de nouveau champ requis ici a priori, les boutons `Actions`
  sont un attribut du message ntfy, pas du contexte de niveau.

## Étapes concrètes

### 1. Durcissements D1-D7 (`src/confirm.py`)

- **D1** : `secrets.token_hex(4)` → `secrets.token_urlsafe(32)` (≈256 bits).
- **D2** : la comparaison `entry.action != action` dans `validate()` passe à
  `hmac.compare_digest`. Faire de même dans `_check_auth()` de
  `http_server.py` pour la comparaison d'`API_TOKEN` (dette existante,
  corrigée au passage, mentionnée explicitement par le PRD).
- **Q5 (TTL)** : `DEFAULT_TTL_SECONDS = 120.0` → `600.0`. Documenter le
  changement dans le docstring du module (« TTL par défaut 600s depuis la
  2.2.0, décision du 2026-08-23 »).

### 2. Nouvel endpoint `POST /api/confirm/<action>/<jeton>` (`src/http_server.py`)

- Router **avant** l'appel à `_check_auth()` dans `do_POST()` : ce chemin est
  le **seul** endpoint POST à ne pas exiger `Authorization: Bearer
  API_TOKEN` — l'autorisation, c'est le jeton lui-même (§ 4.2.2).
- **D3 (rate limiting)** : minimum N tentatives échouées / minute / IP →
  `429` + événement `confirm_bruteforce` dans l'`EventLog`. Implémenter un
  compteur en mémoire simple (dict IP → liste d'horodatages, purge
  périodique) — pas de dépendance externe, cohérent avec le style du projet
  (`confirm.py` fait déjà ça pour les jetons).
- **D4 (logs)** : dans `log_message()`, masquer
  `/api/confirm/<action>/<jeton>` → `/api/confirm/<action>/***` avant de
  journaliser.
- **D6 (réponse muette)** : `200 {"ok": true}` ou
  `404 {"error": "unknown or expired"}` — jamais de détail sur l'existence
  du jeton, l'action visée ou l'équipement.
- **D7 (événement systématique)** : chaque appel génère un événement
  `confirm_accepted` ou `confirm_rejected` dans l'`EventLog`.
- Le handler ne fait qu'une chose : `confirm.validate(jeton, action)`, puis
  s'il réussit, exécuter l'action déjà en attente (déléguer à
  `managed_devices.confirm_reboot()` existant — ne pas dupliquer sa
  logique). Il n'accepte **aucun** paramètre venant de l'appelant au-delà de
  `action` et `jeton` dans le chemin.
- **D5** : au démarrage, `logging.critical` si `API_TOKEN` est vide **et**
  qu'un canal avec boutons d'action est configuré (ntfy configuré). Peut se
  brancher sur le garde-fou du sprint 1 (§ 6.4) plutôt que dupliquer une
  vérification séparée.

### 3. Boutons `Actions` ntfy (`src/managed_devices.py`, `src/notifier/_ntfy.py`)

- Ajouter une fonction de publication des boutons, appelée depuis
  `request_reboot()` (L278-296 aujourd'hui) — **en parallèle** du chemin
  Telegram existant (`origin="telegram"` reste inchangé), pas à sa place.
  Injecter une fonction `send` (comme le fait déjà `_make_handle_lte_*` pour
  Telegram) plutôt qu'importer `_ntfy` directement dans
  `managed_devices.py` — cohérent avec le design déjà agnostique du fichier.
- Format des boutons (§ 4.2.2 du PRD, à reproduire exactement) :
  ```
  Actions: http, Confirmer le redémarrage, \
           http://<nom-tailscale-instance>:<HTTP_PORT>/api/confirm/tplink_reboot/<jeton>, \
           method=POST, clear=true ; \
           http, Annuler, \
           http://<nom-tailscale-instance>:<HTTP_PORT>/api/confirm/cancel/<jeton>, \
           method=POST, clear=true
  ```
- **Aucun en-tête `Authorization` dans le bouton.** Vérifier par test qu'un
  publish de notification avec boutons ne contient jamais `API_TOKEN` en
  clair ni encodé (gate `no-api-token-in-notification`).
- **URL Tailscale uniquement** (gate `confirm-urls-tailscale-only`,
  décision Q7) : le nom d'hôte utilisé pour l'URL d'action doit être la
  même source que celle du `Click` du sprint 1 (nom Tailscale de
  l'instance), jamais une IP LAN, jamais un nom public. Test dédié qui
  vérifie que la chaîne produite ne contient ni une IP `192.168.*`/`10.*`
  ni le domaine `ntfy.bbhome.wf`/tout domaine public.

## Ne pas toucher

- `src/telegram_bot.py`, `_register_telegram_handlers()`,
  `_adapt_for_telegram()`, `origin="telegram"` (L531, L555) : chemin
  Telegram inchangé, ce sprint ajoute un chemin parallèle.
- `src/dashboard.py` : sprint 3.

## Fichiers

- **files_to_create** : `tests/test_confirm_endpoint.py`
- **files_to_modify** : `src/confirm.py`, `src/http_server.py`,
  `src/managed_devices.py`, `src/config.py` (si une variable de rate
  limiting est ajoutée), `tests/test_confirm.py`,
  `tests/test_managed_devices.py`, `tests/test_http_server.py`
- **files_read_only** : `src/notifier/_ntfy.py`, `src/events.py`,
  `src/state.py`
- **forbidden** : `src/telegram_bot.py`, `src/dashboard.py`

## Critères d'acceptation

- [x] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [x] Test « aucun secret dans le payload » : publier une notification de
      chaque type (avec et sans boutons) et vérifier l'absence d'`API_TOKEN`
      dans corps et en-têtes
- [x] Jeton rejoué → `404`, aucune action exécutée (test)
- [x] Jeton expiré (> `CONFIRM_TTL`, soit 600s par défaut) → `404`, aucune
      action exécutée (test — utiliser un TTL court injecté dans le test,
      pas attendre 600s réelles)
- [x] Jeton valide présenté sur une autre action dans l'URL → `404` (test)
- [x] `hmac.compare_digest` utilisé pour la comparaison d'action **et** pour
      `_check_auth()` (`API_TOKEN`) — vérifié par lecture + test
- [x] Rate limiting actif : au-delà de N échecs/min/IP → `429` + événement
      `confirm_bruteforce` (test)
- [x] Aucun jeton en clair dans les journaux, y compris en
      `LOG_LEVEL=DEBUG` (test sur `log_message`)
- [x] `/api/confirm/*` est le seul endpoint POST exempté de `_check_auth()`
      (test d'inventaire des routes : parcourir `do_POST()` et vérifier
      qu'un seul chemin bypasse `_check_auth()`)
- [x] Toutes les URL d'action publiées pointent sur un nom/adresse Tailscale
      — aucune IP LAN, aucune IP publique (test sur la chaîne produite)
- [x] `secrets.token_urlsafe(32)` vérifié (longueur et alphabet du jeton)
- [x] `DEFAULT_TTL_SECONDS == 600.0` dans `src/confirm.py`
- [x] Test réel : un bouton de confirmation pressé depuis un téléphone
      (LAN suffit pour ce sprint ; le test en 4G/Tailscale externe est
      couvert par la vérification réelle du sprint 5) déclenche
      effectivement l'action et génère `confirm_accepted` dans
      `/api/events`

## Agent Notes (Sprint 2)

**Decisions prises (avec raison) :**

- **D6, code HTTP retenu** : `404 {"error": "unknown or expired"}` pour tout
  echec (jeton inconnu/expire/deja-utilise/mauvaise action), `200
  {"ok": true}` pour le succes. Le PRD (§4.2.2/D6) et les criteres
  d'acceptation de ce fichier convergent tous les deux sur `404` -- retenu
  sans ambiguite (la formulation `403` mentionnee dans une version anterieure
  de la tache orchestrateur ne correspond ni au PRD ni a ce fichier de
  sprint).
- **`confirm_bruteforce` remplace `confirm_rejected`** sur le cas rate-limite
  (pas de cumul des deux evenements pour la meme tentative) : evite de
  compter deux fois le meme echec sous deux types differents dans
  `/api/events`.
- **Handler HTTP ne re-valide jamais un jeton deja valide par
  `managed_devices.confirm_reboot()`** : pour l'action `tplink_reboot`, le
  handler delegue integralement a `registry.confirm_reboot()` (qui appelle
  `confirm.validate()` avec l'action canonique en interne) plutot que
  d'appeler `confirm.validate()` puis `confirm_reboot()` -- `confirm.validate()`
  fait un `pop` inconditionnel (usage unique), un double appel sur le meme
  jeton echouerait donc toujours au deuxieme appel, meme legitime. Pour les
  actions autres que `tplink_reboot` (dont `cancel`), le handler appelle
  `confirm.validate()` directement (aucune execution possible), ce qui
  consomme/invalide le jeton -- c'est ce qui rend le bouton "Annuler"
  efficace.
- **Rate limiting** : compteur en memoire `dict IP -> [timestamps]`, purge
  paresseuse a la lecture (pas de tache periodique dediee), ferme sur
  `_make_handler_class()` (une fenetre par serveur, pas de module-level
  partage entre instances/tests). Seuil et fenetre configurables via
  `CONFIRM_RATE_LIMIT_MAX_FAILURES`/`CONFIRM_RATE_LIMIT_WINDOW`
  (`src/config.py`), defaut 10/60s conformement a D3.
- **D5** branche dans `start_http_server()` (`src/http_server.py`), pas dans
  `watchdog.py` (INTOUCHABLE pour ce sprint, cf. commentaire existant dans
  `http_server.py` autour du wiring `managed_devices.bootstrap`).
- **Injection ntfy** : `ManagedDeviceRegistry` recoit une fonction `send`
  optionnelle (`ntfy_send`, via constructeur ou `set_ntfy_send()`), appelee
  depuis `request_reboot()` quelle que soit l'origine (telegram ou api) --
  contrairement au chemin Telegram (ou c'est le *handler* Telegram qui
  formate/envoie), la publication Ntfy doit avoir lieu automatiquement des
  qu'une confirmation est demandee. Le pont concret
  (`http_server._publish_confirm_actions`) est injecte depuis
  `start_http_server()`, `managed_devices.py` n'importe jamais `_ntfy`.
- **Source du hostname pour les URL d'action** : `socket.gethostname()`
  (nouvelle fonction `_ntfy._resolve_hostname()`), EXACTEMENT la meme source
  que le `Click` du sprint 1 (`_dispatch._get_hostname()` et
  `messages._dashboard_link()` font deja la meme chose) -- aucune nouvelle
  variable de config introduite, le sprint 1 n'en avait pas ajoute non plus
  pour `Click`.

**Assumptions (confiance) :**

- 🟢 Le nom d'hote systeme (`socket.gethostname()`) correspond au nom
  MagicDNS Tailscale en production -- deja assume par le sprint 1 pour
  `Click`, prerequis explicite du PRD (§4.1, Q7). Ce sprint ne fait que
  reutiliser la meme hypothese pour les boutons `Actions`.
- 🟡 Le bouton "Annuler" ne "reussit" jamais au sens HTTP (toujours 404, par
  design D6/reponse muette) -- son effet reel (invalidation du jeton) n'est
  visible que par l'absence de succes d'une confirmation ulterieure. Documente
  dans le code et teste, mais pourrait surprendre un futur lecteur qui
  s'attendrait a un `200` sur "Annuler".

**Issues trouvees :**

- Aucune anomalie bloquante. Le seul point de friction reel a ete la
  tension entre "handler appelle confirm.validate() puis delegue a
  confirm_reboot()" (formulation initiale de la tache) et le fait que
  confirm.validate() fait un `pop` inconditionnel -- resolu par la decision
  ci-dessus (delegation complete, sans double-validate).

**Fichiers hors perimetre necessitant une modification (aucun) :** neant --
tous les changements sont restes dans les fichiers declares
(`src/confirm.py`, `src/http_server.py`, `src/managed_devices.py`,
`src/config.py`, extension minimale de `src/notifier/_ntfy.py` explicitement
autorisee par la spec, `tests/test_confirm.py`, `tests/test_managed_devices.py`,
`tests/test_confirm_endpoint.py` nouveau). `watchdog.py`, `telegram_bot.py`,
`dashboard.py` non touches, comme exige.
