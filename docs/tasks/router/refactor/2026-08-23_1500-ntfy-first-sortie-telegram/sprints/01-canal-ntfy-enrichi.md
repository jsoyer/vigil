# Sprint 1 — Canal Ntfy enrichi : priorités, tags, topics par site+ops, auth par token

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram.md` (§ 3, § 6.4, § 8 S1, § 9 AC, § 0bis Q1/Q2)
- **Dépend de** : aucun sprint de ce PRD. **Gate d'entrée** : `a1-2.1.0-livre` et `ntfy-user-token-vigil-cree` de `progress.json` (créés/vérifiés par l'orchestrateur, pas par ce sprint)
- **Taille estimée** : 75-90 min
- **Isolation** : worktree

## Objectif

Faire de `src/notifier/_ntfy.py` (69 lignes aujourd'hui) le canal de
notification riche décrit au § 3 du PRD : titre par instance, priorités 1-5,
tags de niveau + instance + site, `Click` vers le dashboard de l'instance
émettrice, `Markdown: yes` avec sous-ensemble dégradable, troncature à
4 096 octets, authentification par `NTFY_TOKEN`, et **trois topics** au lieu
d'un (décision Q2 du 2026-08-23 soir : `vigil-dijon`/`vigil-nice` pour les
alertes de ligne, `vigil-ops` pour le cycle de vie). Ajouter le garde-fou
« aucun canal configuré » (§ 6.4).

## Contexte technique vérifié

- `src/notifier/_ntfy.py` actuel : `POST` brut, `Title: Vigil` constant,
  priorités déjà correctes (3/4/5), tags `information_source` /
  `warning` / `rotating_light` (sans instance ni site), `Content-Type:
  text/plain`, pas d'auth, un seul topic (`NTFY_TOPIC`).
- `src/config.py` : `NTFY_URL` (L249), `NTFY_TOPIC` (L251), `NTFY_TIMEOUT`
  (L252), `NTFY_MIN_LEVEL` (L253). Aucune variable `NTFY_TOKEN` n'existe.
- `src/notifier/_dispatch.py` : `_get_channels()` importe
  `(_telegram, _discord, _slack, _ntfy, _email, _pushover)` et construit un
  tuple `(nom, module, min_level)` mis en cache (`@functools.cache`). Le
  contrat `notify(message, level, context)` — jamais modifié (invariant § 9
  point 1) — reste `notify(message: str, level: Level, context:
  NotificationContext | None)`.
- `NotificationContext` vit dans `src/notifier/_types.py` : c'est le seul
  endroit où l'on peut ajouter une information de routage **sans** changer
  la signature de `notify()`.

## Étapes concrètes

### 1. `NTFY_TOKEN` et authentification (`src/config.py`, `src/notifier/_ntfy.py`)

- `src/config.py` : ajouter `NTFY_TOKEN: str = os.getenv("NTFY_TOKEN", "")`
  à côté du bloc `NTFY_*` existant (après `NTFY_MIN_LEVEL`, L253).
- `src/notifier/_ntfy.py` : si `NTFY_TOKEN` est renseigné, ajouter l'en-tête
  `Authorization: Bearer {NTFY_TOKEN}`. Si vide, **aucun changement de
  comportement** vs 2.1.0 (publication anonyme) — c'est un critère
  d'acceptation testé du PRD § 10.
- Le jeton `vigil` lui-même est créé côté serveur par l'orchestrateur (gate
  `ntfy-user-token-vigil-cree`), pas par ce sprint — ce sprint ne fait que
  consommer `NTFY_TOKEN` s'il est présent.

### 2. Priorités, tags, titre (`src/notifier/_ntfy.py`)

- Conserver `_LEVEL_PRIORITY` (3/4/5) déjà correct. Ajouter `Priority: 2`
  pour les rapports quotidiens/hebdomadaires (§ 3.2) — nécessite un moyen de
  distinguer un message de rapport d'un message d'alerte (cf. étape 4,
  `NotificationContext.category`).
- `Title` : remplacer `"Vigil"` constant par `f"Vigil {instance_id} — {résumé
  court}"`. `instance_id` vient de `config.INSTANCE_ID` (déjà utilisé
  ailleurs dans le projet, cf. `mqtt_publisher.py`) ; le « résumé court » est
  la première ligne de `message` tronquée si besoin — ne pas dupliquer la
  logique de `messages.py`, juste réutiliser la première ligne fournie par
  l'appelant.
- `Tags` : remplacer la valeur simple par `f"{tag_niveau},{instance_id},
  {site}"`. `site` se déduit d'`INSTANCE_ID` ou d'une nouvelle variable
  explicite si `INSTANCE_ID` ne porte pas déjà cette information (vérifier
  dans `config.py`/`mqtt_publisher.py` comment le site est actuellement
  dérivé, ex. `bbh_dij_guardian` → `dijon`) ; réutiliser cette dérivation
  existante plutôt que d'en écrire une nouvelle.
- `Click` : `f"http://{tailscale_hostname}:{HTTP_PORT}/dashboard"`. Le nom
  Tailscale de l'instance émettrice doit être lisible depuis la config
  existante (cf. `src/tailscale_dns.py` / variable déjà utilisée pour
  identifier l'hôte) — ne pas introduire une nouvelle variable si une
  existe déjà pour cet usage.

### 3. Markdown dégradable et troncature (`src/notifier/_ntfy.py`, `src/messages.py` si nécessaire)

- Ajouter l'en-tête `Markdown: yes`.
- Le corps ne doit jamais dépasser **4 096 octets** (limite dure ntfy.sh —
  toujours respectée même en self-hosted par cohérence, cf. § 3.4). Tronquer
  proprement, avec indication explicite (« … [tronqué, voir `Click`] ») plutôt
  qu'une coupure brutale au milieu d'un mot.
- Ce sprint **ne réécrit pas** `messages.py` (c'est le sprint 4, § 3.4/§ 8
  S4) — se contenter, ici, de garantir que `_ntfy.send()` tronque tout corps
  reçu avant publication, quel que soit son origine.

### 4. Topics par site + ops (décision Q2) : `NotificationContext.category`

- `src/config.py` : garder `NTFY_TOPIC` comme topic **de site**
  (`vigil-dijon` / `vigil-nice`, valeur par `.env`, § 3.5 inchangé sur ce
  point). Ajouter `NTFY_TOPIC_OPS: str = os.getenv("NTFY_TOPIC_OPS",
  "vigil-ops")`.
- `src/notifier/_types.py` : ajouter un champ optionnel à
  `NotificationContext` (dataclass déjà immuable, `frozen=True` a priori —
  vérifier) : `category: str = "alert"`. Valeurs attendues : `"alert"`
  (défaut, alertes de ligne → `NTFY_TOPIC`) et `"ops"` (cycle de vie,
  mises à jour, rapports → `NTFY_TOPIC_OPS`). **Champ additionnel avec
  valeur par défaut** : ne casse aucun appelant existant de `notify()`, ne
  change pas la signature de `notify()` elle-même (invariant § 9 point 1).
- `src/notifier/_ntfy.py` : choisir le topic à publier selon
  `context.category if context else "alert"`.
- Les appelants actuels (`watchdog.py`, `report.py`, l'updater le cas
  échéant) qui publient des événements de cycle de vie ou des rapports
  doivent passer `context=NotificationContext(..., category="ops")` — ne
  changer que les appels concernés, pas tous les appels à `notify()`.
  Identifier ces appelants par `grep -rn "notify(" src/report.py
  src/watchdog.py updater/` avant de modifier.

### 5. Garde-fou « aucun canal configuré » (§ 6.4)

- Au démarrage (`src/watchdog.py`) : si **aucun** canal de notification
  n'est configuré (`is_configured()` faux pour ntfy, email **et** mqtt —
  vérifier que MQTT compte bien comme canal de secours ou s'il faut se
  limiter aux canaux d'alerte), `logging.critical` explicite + événement
  `no_notification_channel` dans l'`EventLog`.
- `src/http_server.py` : exposer un champ `notification_channels` (liste des
  canaux configurés) dans les réponses `/health` et `/api/state`.
- `src/metrics.py` : ajouter la gauge
  `vigil_notification_channels_configured` (nombre de canaux configurés).
- Ne **jamais** faire échouer le démarrage si aucun canal n'est configuré —
  la surveillance continue (§ 6.4 point 4).

### 6. Documentation

- `README.md` (tableau L232-235 pour Ntfy, référence de configuration citée
  au § 6.3 du PRD) : documenter `NTFY_TOKEN`, `NTFY_TOPIC_OPS`.
- `DEPLOY.md` (L84-85) : idem, + rappel que la publication se fait en
  interne sur l'IP Tailscale/loopback de bbh-network (jamais via
  `https://ntfy.bbhome.wf`, décision Q1) — ne pas documenter l'URL
  Cloudflare comme cible de publication.

## Ne pas toucher

- `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/notifier/_discord.py`, `src/notifier/_slack.py`,
  `src/notifier/_pushover.py` : intacts jusqu'au sprint 5 (invariant
  « 8 commandes Telegram intactes »).
- `src/confirm.py` : sprint 2.
- `src/dashboard.py` : sprint 3.

## Fichiers

- **files_to_create** : `tests/test_ntfy_notifier.py`
- **files_to_modify** : `src/notifier/_ntfy.py`, `src/config.py`,
  `src/watchdog.py`, `src/http_server.py`, `src/metrics.py`, `README.md`,
  `DEPLOY.md`
- **files_read_only** : `src/notifier/_types.py`, `src/notifier/_dispatch.py`,
  `src/notifier/__init__.py`, `src/events.py`
- **forbidden** : `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/notifier/_discord.py`, `src/notifier/_slack.py`,
  `src/notifier/_pushover.py`

## Critères d'acceptation

- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] Tests unitaires : en-têtes produits pour chaque `Level` (`Priority`
      3/4/5, `Tags` avec niveau+instance+site, `Title` contenant
      `INSTANCE_ID`) ; rapport → `Priority: 2`
- [ ] `NTFY_TOKEN` vide → publication anonyme inchangée (comportement 2.1.0,
      régression testée) ; renseigné → en-tête `Authorization: Bearer`
      présent (test)
- [ ] Topic de site (`NTFY_TOPIC`) utilisé pour `category="alert"` (défaut) ;
      `NTFY_TOPIC_OPS` utilisé pour `category="ops"` (test)
- [ ] Aucun corps de notification > 4 096 octets (test avec un message long
      généré artificiellement)
- [ ] `Markdown: yes` présent dans les en-têtes
- [ ] Démarrage sans aucun canal configuré → log `CRITICAL`, événement
      `no_notification_channel`, `notification_channels: []` dans `/health`
      et `/api/state`, `vigil_notification_channels_configured 0` dans
      `/metrics` ; le watchdog continue de surveiller (test d'intégration)
- [ ] Envoi réel des 3 niveaux (INFO/WARNING/CRITICAL) reçu sur téléphone via
      le serveur ntfy de bbh-network, publié en interne (loopback ou
      Tailscale, jamais Cloudflare) — consigné dans le journal de
      vérification (utile en avance du sprint 5, pas bloquant pour ce
      sprint)
- [ ] `grep -rn "telegram\|discord\|slack\|pushover" src/notifier/_ntfy.py` = 0
