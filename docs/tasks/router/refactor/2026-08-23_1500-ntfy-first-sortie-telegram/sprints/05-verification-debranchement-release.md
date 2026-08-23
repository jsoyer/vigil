# Sprint 5 — Vérification réelle renforcée, puis débranchement Telegram+Pushover+Discord+Slack, release 2.2.0

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram.md` (§ 2.1, § 6.2 encart Q4, § 6.5, § 8 S5, § 9 point 2 révisé, § 10 « Débranchement », § 0bis en entier)
- **Dépend de** : Sprints 1, 2, 3, 4 (tous mergés sur `main` via `dev` → PR, `./scripts/validate.sh` vert)
- **Gate d'entrée bloquant** : `verification-reelle-avant-debranchement` de `progress.json` — **rien de la partie 2 (démantèlement) de ce sprint ne démarre avant que la partie 1 (vérification) soit constatée et journalisée**
- **Taille estimée** : 90-120 min (runbook + code), hors durée de la vérification réelle elle-même (dépend de la disponibilité de l'opérateur hors domicile)
- **Isolation** : none — ce sprint touche à la fois du code (démantèlement) et une procédure opérateur (vérification réelle, tag), comme le sprint 5 du grand renommage

## Objectif

Ce sprint a deux parties **strictement ordonnées**, jamais interchangeables :

1. **Vérification réelle renforcée** (remplace le double-run de 7 jours,
   décision Q4 du 2026-08-23 soir) — Telegram, Pushover, Discord, Slack
   **toujours actifs** pendant cette partie.
2. **Débranchement** de Telegram, Pushover, Discord et Slack (périmètre
   élargi, décision Q3), puis release `2.2.0`, **seulement après** que la
   partie 1 est journalée et satisfaisante.

## Partie 1 — Vérification réelle renforcée (avant tout code de suppression)

Checklist du PRD § 6.2 (encart daté 2026-08-23 soir), à exécuter par
l'opérateur humain sur les 4 Pi en production (code des sprints 1-4 déjà
mergé sur `main`) :

- [ ] Publication de test reçue sur **chaque topic** — `vigil-dijon`,
      `vigil-nice`, `vigil-ops` — à **chaque niveau** — INFO (`Priority: 3`),
      WARNING (`Priority: 4`), CRITICAL (`Priority: 5`) — constatée sur
      téléphone, avec la bonne priorité observée (pas juste « reçue », la
      priorité affichée doit correspondre)
- [ ] Un test end-to-end d'un bouton de confirmation **depuis le LAN** :
      déclencher une action confirmable (ex. `tplink_reboot` sur un
      équipement de test ou en environnement contrôlé), recevoir la
      notification avec boutons, taper « Confirmer », vérifier que l'action
      s'exécute et que l'événement `confirm_accepted` apparaît dans
      `/api/events`
- [ ] (Recommandé, non bloquant pour le gate) : un test du bouton
      « Annuler » et une expiration observée (jeton non pressé pendant
      600s → 404, aucune action)
- [ ] Résultat journalisé et daté dans
      `2026-08-23_1500-ntfy-first-sortie-telegram/progress.json` (gate
      `verification-reelle-avant-debranchement.satisfied = true`) **avant**
      d'ouvrir la partie 2

**Si cette checklist échoue** (notification non reçue, priorité incorrecte,
bouton de confirmation qui ne déclenche rien) : ne **pas** poursuivre vers la
partie 2. Corriger dans un sprint correctif (retour aux sprints 1/2), pas en
forçant le démantèlement.

## Partie 2 — Démantèlement (uniquement après gate satisfait)

### Contexte technique vérifié (lignes au moment de la rédaction — à
### reconfirmer par `grep -n` avant modification, elles peuvent avoir dérivé
### après les sprints 1-4)

- `src/watchdog.py` : `from telegram_bot import TelegramBot` (L76) ;
  `telegram_bot = TelegramBot(state_holder)` (L278) ;
  `tg_started = telegram_bot.start()` (L279) ; docstring et libellé de log
  mentionnant Telegram ailleurs dans le fichier.
- `src/managed_devices.py` : `_register_telegram_handlers(registry)` appelé
  depuis `bootstrap()` (L364) ; la fonction elle-même `_register_
  telegram_handlers()` avec ses 5 appels `register_lte_handler` (L367-394) ;
  `_adapt_for_telegram()` (L397-408, `import telegram_bot` en L404,
  `send=telegram_bot.send_message` en L406) ; `origin="telegram"` en dur
  (L531 dans `request_reboot`, L555 dans `confirm_reboot`) — **remplacer par
  une valeur d'origine neutre** (ex. `"dashboard"`/`"ntfy"` selon
  l'appelant réel introduit aux sprints 2-3, jamais laisser `"telegram"`
  après suppression du bot).
- `src/notifier/_dispatch.py` (fichier complet, 6 canaux enregistrés
  aujourd'hui) : retirer les entrées `("telegram", _telegram,
  TELEGRAM_MIN_LEVEL)`, `("discord", _discord, DISCORD_MIN_LEVEL)`,
  `("slack", _slack, SLACK_MIN_LEVEL)`, `("pushover", _pushover,
  PUSHOVER_MIN_LEVEL)` du tuple retourné par `_get_channels()`, et les
  imports correspondants (`_telegram, _discord, _slack, _pushover`) — ne
  garder que `_ntfy, _email`. Retirer aussi les imports
  `TELEGRAM_MIN_LEVEL, DISCORD_MIN_LEVEL, SLACK_MIN_LEVEL,
  PUSHOVER_MIN_LEVEL` du bloc `from config import (...)` en tête de
  fichier.
- `src/config.py` : `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/
  `TELEGRAM_TIMEOUT`/`TELEGRAM_MIN_LEVEL` (L220-224) ;
  `DISCORD_WEBHOOK_URL`/`DISCORD_TIMEOUT`/`DISCORD_MIN_LEVEL` (L231-233) ;
  `SLACK_WEBHOOK_URL`/`SLACK_TIMEOUT`/`SLACK_MIN_LEVEL` (L240-242) ;
  `PUSHOVER_USER_KEY`/`PUSHOVER_API_TOKEN`/`PUSHOVER_TIMEOUT`/
  `PUSHOVER_MIN_LEVEL` (L272-275) — 14 variables au total à retirer (4 +
  3 + 3 + 4). Attention : L360 `CLOUDFLARE_API_TOKEN` et L581 (commentaire
  citant `TELEGRAM_BOT_TOKEN` comme exemple de secret) sont des faux amis à
  ne **pas** toucher hors du renommage de l'exemple en commentaire.
- Fichiers **entiers supprimés** : `src/telegram_bot.py`,
  `src/notifier/_telegram.py`, `src/notifier/_discord.py`,
  `src/notifier/_slack.py`, `src/notifier/_pushover.py`.
- Tests : `tests/test_telegram_bot.py` (fichier entier supprimé) ;
  `tests/test_pushover_notifier.py` (357 lignes, fichier entier supprimé) ;
  dans `tests/test_notifier.py`, retirer les classes `TestTelegram` (démarre
  L92), `TestDiscord` (démarre L163), `TestSlack` (démarre L266) — vérifier
  les bornes exactes de chaque classe avant suppression (jusqu'au début de
  la classe suivante) ; retouches dans `tests/test_managed_devices.py`
  (origin="telegram" → nouvelle valeur) et `tests/test_http_server.py`.
- Scripts : `scripts/deploy.sh:81-82` (invite de saisie des secrets
  Telegram — numéros de ligne du PRD original, à reconfirmer) ;
  `scripts/test.sh:96-98` + `:103` (test de connectivité Telegram). Ajouter
  la vérification/suppression des invites Discord/Slack/Pushover si elles
  existent dans ces mêmes scripts (le PRD original ne les inventoriait pas
  car Telegram seul était dans son périmètre — `grep -n
  "discord\|slack\|pushover" scripts/deploy.sh scripts/test.sh` avant de
  conclure qu'il n'y a rien à faire).
- `requirements.txt` : **rien à retirer** — contenu confirmé
  (`paramiko==3.5.0`, `paho-mqtt==1.6.1`, `tplinkrouterc6u==5.31.1`), aucune
  dépendance Telegram/Discord/Slack/Pushover propre (tous utilisaient
  `requests`/stdlib déjà présents pour d'autres raisons). Vérifier que
  `requests` n'est utilisé par **aucun** autre module avant de conclure
  qu'il ne faut rien retirer non plus côté `requests` (a priori si, gardé
  par d'autres canaux).
- Documentation, occurrences mesurées avant ce sprint (recompter après —
  ces chiffres datent d'avant le sprint 5, ils doivent tomber à 0 sauf
  historique) :

  | Fichier | telegram | pushover | discord | slack |
  |---|---|---|---|---|
  | README.md | 32 | 12 | 13 | 12 |
  | DEPLOY.md | 15 | 0 | 2 | 2 |
  | CLAUDE.md | 8 | 4 | 4 | 4 |
  | WORKFLOW.md | 2 | 0 | 1 | 4 |

### Étapes concrètes (partie 2)

1. Supprimer les 5 fichiers listés ci-dessus (`telegram_bot.py`,
   `_telegram.py`, `_discord.py`, `_slack.py`, `_pushover.py`).
2. Nettoyer `src/watchdog.py` (import + instanciation + démarrage du bot,
   docstring, libellés de log).
3. Nettoyer `src/managed_devices.py` (`_register_telegram_handlers`,
   `_adapt_for_telegram`, l'appel depuis `bootstrap()`, les deux
   `origin="telegram"`).
4. Nettoyer `src/notifier/_dispatch.py` (imports + tuple `_get_channels()`).
5. Retirer les 14 variables de `src/config.py` (Telegram, Discord, Slack,
   Pushover).
6. Supprimer `tests/test_telegram_bot.py`, `tests/test_pushover_notifier.py`
   ; retirer les classes `TestTelegram`/`TestDiscord`/`TestSlack` de
   `tests/test_notifier.py` ; adapter `tests/test_managed_devices.py` et
   `tests/test_http_server.py`.
7. Nettoyer `scripts/deploy.sh`, `scripts/test.sh` (invites/tests des 4
   canaux).
8. Mettre à jour `README.md`, `DEPLOY.md`, `CLAUDE.md`, `WORKFLOW.md` — les
   4 comptes du tableau ci-dessus doivent tomber à 0 (documents historiques
   `docs/adr/`, `docs/RELEASE-NOTES-1.8.*`/`2.0.0`, `docs/tasks/**` **non
   réécrits**, invariant du § 2.1).
9. Nettoyer les 4 `.env` de production : retirer `TELEGRAM_*`,
   `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, `PUSHOVER_USER_KEY`,
   `PUSHOVER_API_TOKEN` s'ils y sont présents.
10. `VERSION` = `2.2.0`.
11. Créer `docs/RELEASE-NOTES-2.2.0.md` : retrait des 4 canaux et du bot,
    variables supprimées (14, listées ci-dessus), variables ajoutées
    (`NTFY_TOKEN`, `NTFY_TOPIC_OPS`), prérequis Tailscale (téléphones),
    points de non-retour (suppression du code + révocation du bot
    BotFather), rappel explicite « révoquer le bot Telegram auprès de
    `@BotFather` à J+7 » (le PRD § 6.3 le pose comme irréversible et
    distinct du tag).
12. **Tag `v2.2.0` en dernier**, seulement après validation `/health` =
    `2.2.0` sur les 4 Pi et après confirmation que les canaux de secours
    (Email, MQTT) fonctionnent réellement sur les 4 instances.

## Fichiers

- **files_to_create** : `docs/RELEASE-NOTES-2.2.0.md`
- **files_to_delete** : `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/notifier/_discord.py`, `src/notifier/_slack.py`,
  `src/notifier/_pushover.py`, `tests/test_telegram_bot.py`,
  `tests/test_pushover_notifier.py`
- **files_to_modify** : `VERSION`, `src/config.py`, `src/watchdog.py`,
  `src/managed_devices.py`, `src/notifier/_dispatch.py`, `README.md`,
  `DEPLOY.md`, `CLAUDE.md`, `WORKFLOW.md`, `scripts/deploy.sh`,
  `scripts/test.sh`, `tests/test_notifier.py`,
  `tests/test_managed_devices.py`, `tests/test_http_server.py`,
  `docs/session-learnings.md`
- **files_read_only** : `docs/adr/`, `docs/RELEASE-NOTES-1.8.*.md`,
  `docs/RELEASE-NOTES-2.0.0.md`, `docs/tasks/**` (y compris ce PRD
  lui-même — encarts datés seulement, jamais réécrit)

## Critères d'acceptation

**Vérification réelle (bloquant avant toute suppression de code)**

- [ ] Checklist de la Partie 1 entièrement cochée et journalée (date +
      preuve : capture d'écran ou description de chaque notification reçue,
      événement `confirm_accepted` visible dans `/api/events`)
- [ ] Gate `verification-reelle-avant-debranchement` de `progress.json`
      passé à `satisfied: true`

**Débranchement**

- [x] `grep -riI "telegram\|pushover\|discord\|slack" src/ tests/ scripts/ updater/ requirements.txt` = **0** (docs historiques exclues) -- une exception documentee : `tests/test_ntfy_notifier.py::test_no_reference_to_other_channels` (sprint 1, hors perimetre S5) liste ces mots en dur pour PROUVER leur absence dans `_ntfy.py`, faux positif attendu du grep litteral (voir `docs/session-learnings.md`, entree du 2026-08-23 soir).
- [x] Les 5 fichiers de canal/bot supprimés ; aucune des 14 variables
      `TELEGRAM_*`/`DISCORD_*`/`SLACK_*`/`PUSHOVER_*` dans `config.py`
- [x] `./scripts/validate.sh` vert, coverage ≥ 80 % (voir preuve d'execution consignee par l'orchestrateur)
- [ ] Les 4 `.env` de production sans `TELEGRAM_*`, `DISCORD_WEBHOOK_URL`,
      `SLACK_WEBHOOK_URL`, `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN`
- [ ] Les 4 `/health` annoncent `2.2.0` ; publication ntfy réussie visible
      dans les 4 journaux
- [x] `docs/RELEASE-NOTES-2.2.0.md` présent et complet (variables retirées,
      variables ajoutées, prérequis Tailscale, points de non-retour, rappel
      révocation BotFather à J+7)
- [x] `README.md`, `DEPLOY.md`, `CLAUDE.md`, `WORKFLOW.md` à jour (0
      occurrence des 4 canaux débranchés hors documents historiques exclus)
- [ ] `VERSION` = `2.2.0`, tag `v2.2.0` poussé **après** validation des 4
      Pi, `dev` resynchronisée avec `main`
- [x] Seuls **Ntfy**, **Email SMTP** et **MQTT** restent comme canaux de
      notification actifs (`_get_channels()` de `_dispatch.py` ne contient
      plus que 2 entrées : `ntfy`, `email` — MQTT n'est pas dans ce tuple,
      c'est un canal de télémétrie séparé, invariant § 9 point 2)
