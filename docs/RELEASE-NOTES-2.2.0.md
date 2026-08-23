# Notes de version -- Vigil 2.2.0

PRD Ntfy-first -- Sortie de Telegram (`docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram.md`), décision Option B du 2026-08-23.

## Bascule Option B : sortie complète de Telegram

Les notifications basculent sur **Ntfy** comme canal principal. Les
commandes qui transitaient par le bot Telegram sont remplacées par des
**boutons d'action Ntfy** (pour les décisions qui arrivent avec l'alerte,
ex. confirmer/annuler un reboot TP-Link) et par le **dashboard web + l'API
HTTP** (pour tout le reste : pause/resume/reboot, DDNS, backup, sync
Tailscale, pilotage TP-Link).

Décision Q3 (2026-08-23 soir) élargit le périmètre du démantèlement à
**Pushover, Discord et Slack**, en plus de Telegram -- ces trois canaux
étaient déjà secondaires et non testés en conditions réelles récentes.

## Ce qui meurt

- **Fichiers supprimés** : `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/notifier/_discord.py`, `src/notifier/_slack.py`,
  `src/notifier/_pushover.py`, `tests/test_telegram_bot.py`,
  `tests/test_pushover_notifier.py`.
- **Le bot interactif Telegram** (long-polling, 8 commandes `/status`,
  `/pause`, `/resume`, `/reboot`, `/ddns`, `/backup`, `/tailscale`, `/help`,
  plus `/lte` livré par A1 en 2.1.0) : entièrement retiré de
  `src/watchdog.py` (import, instanciation, démarrage) et de
  `src/managed_devices.py` (`_register_telegram_handlers`,
  `_adapt_for_telegram`, tous les `_make_handle_lte_*`, l'appel depuis
  `bootstrap()`).
- **`_get_channels()`** (`src/notifier/_dispatch.py`) ne contient plus que
  2 entrées : `ntfy`, `email`. MQTT reste un canal de télémétrie séparé
  (`mqtt_publisher.py`), il n'a jamais fait partie de ce tuple.
- **14 variables de configuration retirées** de `src/config.py` :
  - Telegram (4) : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
    `TELEGRAM_TIMEOUT`, `TELEGRAM_MIN_LEVEL`
  - Discord (3) : `DISCORD_WEBHOOK_URL`, `DISCORD_TIMEOUT`,
    `DISCORD_MIN_LEVEL`
  - Slack (3) : `SLACK_WEBHOOK_URL`, `SLACK_TIMEOUT`, `SLACK_MIN_LEVEL`
  - Pushover (4) : `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN`,
    `PUSHOVER_TIMEOUT`, `PUSHOVER_MIN_LEVEL`
- **`origin="telegram"`** disparaît des events tracés (`tplink_reboot`,
  `confirm_accepted`, etc.) -- seuls `"api"` et `"ntfy"` restent des
  origines valides pour une confirmation TP-Link (boutons ntfy, dashboard,
  API directe).

**Seuls Ntfy, Email SMTP et MQTT/Home Assistant restent comme canaux actifs**
après cette version (invariant § 9 point 2 révisé du PRD).

## Configuration requise (par instance)

Chacune des 4 instances de production doit avoir dans son `.env` :

| Variable | dijon-master | autres instances |
|---|---|---|
| `NTFY_URL` | `http://127.0.0.1:7171` (colocalisé sur bbh-network) | `http://100.112.123.103:7171` (IP Tailscale de bbh-network) |
| `NTFY_TOPIC` | topic de site, ex. `vigil-dijon` / `vigil-nice` | idem, par site |
| `NTFY_TOKEN` | jeton `vigil` créé sur le serveur ntfy de bbh-network | idem |
| `NTFY_TOPIC_OPS` | `vigil-ops` (défaut) | `vigil-ops` (défaut) |

**Jamais via Cloudflare** : la publication interne (Vigil → serveur ntfy) ne
passe jamais par `https://ntfy.bbhome.wf` (tunnel Cloudflare, réservé à
l'abonnement téléphone). Publier via le tunnel exposerait `NTFY_TOKEN` et le
contenu des alertes en dehors du LAN/Tailscale (décision Q1 du PRD).

## Boutons de confirmation : LAN/Tailscale uniquement

Décision Q7 : `POST /api/confirm/*` n'est **jamais** exposé via le tunnel
Cloudflare. Toutes les URL d'action publiées dans les boutons `Actions` ntfy
utilisent une adresse Tailscale des 4 Pi (`100.x.y.z` ou nom MagicDNS),
jamais une IP LAN ni une IP publique. Une confirmation ne fonctionne donc
depuis un téléphone que sur LAN ou avec Tailscale actif.

## `CONFIRM_TTL` : 120s -> 600s

Décision Q5 : le jeton de confirmation, historiquement tapé à la main dans
un chat authentifié (120s suffisait), devient une URL de capacité cliquée
depuis une notification mobile qui doit d'abord réveiller le téléphone --
`DEFAULT_TTL_SECONDS` dans `src/confirm.py` passe de `120.0` à `600.0`.

## Correctif d'idempotence (découvert au test E2E réel)

L'application ntfy iOS envoie environ 10 requêtes `POST` identiques en
~20ms pour un seul appui sur un bouton d'action. Avec le jeton à usage
unique historique, cela produisait 1 succès et 9 « échecs » (jeton déjà
consommé), déclenchant quasi systématiquement le rate limiter D3
(`10/60s`) et un faux événement `confirm_bruteforce` à chaque appui pourtant
légitime.

**Correctif** (`src/confirm.py` + `src/http_server.py`) : une fenêtre
d'idempotence de ~30s (`IDEMPOTENCY_WINDOW_SECONDS`) mémorise en mémoire,
de façon thread-safe, l'empreinte SHA-256 (jamais le jeton en clair) de
chaque jeton consommé avec succès. Un rejeu du **même** jeton+action dans
cette fenêtre renvoie `200 {"ok": true}` sans ré-exécuter l'action, sans
compter comme un échec du rate limiter, et sans événement
`confirm_rejected` (un événement `confirm_replayed` est journalisé une
seule fois, au premier rejeu détecté). Un jeton inconnu, expiré, ou associé
à une autre action continue de suivre le chemin normal (`404`, compte
comme échec).

Tests : `tests/test_confirm.py::TestIdempotencyWindow` (unitaires) et
`tests/test_confirm_endpoint.py::TestConfirmEndpointReplay` (bout-en-bout,
rafale de 10 requêtes identiques = 1 exécution + 10 réponses `200` + zéro
comptage rate limiter ; rejeu après expiration de la fenêtre = `404` ;
jeton inconnu inchangé).

## Vérification réelle renforcée (avant démantèlement)

Décision Q4 (bascule sèche, sans double-run de 7 jours) : remplacée par une
checklist resserrée, exécutée par l'opérateur sur les 4 Pi de production
avant toute suppression de code (sprints 1-4 déjà mergés) --

- Publication de test reçue sur **chaque topic** (`vigil-dijon`,
  `vigil-nice`, `vigil-ops`) à **chaque niveau** (INFO/WARNING/CRITICAL,
  priorités ntfy 3/4/5) -- salve 5/5 reçue sur téléphone, priorité affichée
  conforme.
- Test end-to-end d'un bouton de confirmation depuis le LAN : action
  exécutée, événement `confirm_accepted` visible dans `/api/events` --
  bouton E2E prouvé.

Journalisée le **2026-08-23** ; gate `verification-reelle-avant-debranchement`
de `progress.json` satisfait avant l'ouverture de la partie démantèlement de
ce sprint (voir
`docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram/progress.json`).

## Points de non-retour

- **Suppression du code** de cette version : irréversible sans revert Git --
  les 4 canaux débranchés ne peuvent plus être réactivés sans restaurer les
  fichiers supprimés et republier une version.
- **Révocation du bot Telegram auprès de `@BotFather`** : geste opérateur
  distinct de ce tag, volontairement différé à **J+7** après le déploiement
  de 2.2.0 sur les 4 instances -- le temps de confirmer qu'aucun besoin de
  rollback vers Telegram ne se présente. À exécuter manuellement, hors dépôt.
- Le **tag `v2.2.0`** n'est poussé qu'après validation `/health` = `2.2.0`
  sur les 4 Pi et confirmation que les canaux de secours (Email, MQTT)
  fonctionnent réellement sur les 4 instances (voir INVARIANTS.md du
  sprint).

## Périmètre exclu de cette version

- Pas de nouveau canal de notification.
- Pas de changement du protocole MQTT/Home Assistant (canal de télémétrie
  inchangé).
- La révocation effective du bot Telegram auprès de `@BotFather` (geste
  opérateur J+7, voir ci-dessus) n'est pas automatisée par cette version.
