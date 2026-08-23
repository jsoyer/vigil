# Refactor — Sortie complète de Telegram, **Ntfy** canal principal (2.2.0)

- **Catégorie** : refactor
- **Date** : 2026-08-23
- **Version cible** : **2.2.0** (minor — voir § 7)
- **Branche** : `dev` → PR → `main`
- **Dépend de** : **A1 livré en 2.1.0**
  (`docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/spec.md`) — ce
  PRD supprime en partie ce que le Sprint 3 d'A1 vient de livrer (couche `/lte`
  Telegram), c'est assumé et documenté au § 2.3.
- **Précède** : **A2 (exposition Home Assistant) en 2.3.0**
  (`docs/tasks/router/feature/2026-08-20_1618-a2-exposition-ha/spec.md`, dont
  l'entête annonce encore `1.10.0` — à réaligner sur 2.3.0). A2 exposera l'état
  dans HA, ce qui **réduit d'autant le besoin de commandes conversationnelles** :
  raison de plus pour ne pas reconstruire un bot ailleurs.
- **Statut** : **rédigé — questions ouvertes du § 11 à trancher avant extraction
  des sprints.** Aucun fichier de sprint, aucun `progress.json`, aucun
  `INVARIANTS.md` n'est créé par ce document.

---

## 0bis. Décisions (2026-08-23 soir)

Réponses utilisateur aux questions ouvertes du § 12, tranchées le soir même de
la rédaction du PRD. Elles priment sur les recommandations formulées plus haut
dans le document là où elles diffèrent ; le corps du PRD **n'est pas réécrit**
— les sections concernées reçoivent des encarts datés « **Décision du
2026-08-23 (soir)** » aux endroits pertinents (§ 2.1, § 3.6, § 4.1, § 4.2.3,
§ 6.2, § 9). Sprints extraits dans
`2026-08-23_1500-ntfy-first-sortie-telegram/`.

| # | Question | Décision | Écart vs recommandation § 12 |
|---|---|---|---|
| **Q1** | Serveur Ntfy + authentification | Ni (b) ni (c) au sens strict du § 12 : le serveur retenu est le ntfy **existant** sur bbh-network (conteneur Docker `binwiederhier/ntfy`, port 7171, auth déjà active côté serveur — une publication anonyme y renvoie déjà 403). Exposition publique **déjà en place** : `https://ntfy.bbhome.wf` via tunnel Cloudflare. **Publication interne par les Pi jamais via Cloudflare** : dijon-master (colocalisé sur bbh-network) publie en local `http://127.0.0.1:7171` ; les 3 autres Pi publient sur `http://100.112.123.103:7171` (IP Tailscale de bbh-network). Abonnement téléphone via `https://ntfy.bbhome.wf`. Risque « ntfy hébergé sur un site surveillé » **explicitement assumé**, mitigé par Email + MQTT conservés (Q3) | **Écart** : le § 3.6 écartait justement l'auto-hébergement sur un site surveillé (« à écarter », seule option qualifiée de « réellement disqualifiante »). L'utilisateur assume ce risque au lieu de déployer un VPS tiers, en s'appuyant sur les deux canaux de secours |
| **Q2** | Topics | **Par site + commun** : `vigil-dijon`, `vigil-nice` (alertes de ligne par site) **+ `vigil-ops`** (cycle de vie, mises à jour, rapports) — un topic de plus que la recommandation « par site » du § 3.5 | Écart mineur : § 3.5 ne comparait que 2 topics (par site) ; l'utilisateur ajoute un troisième topic opérationnel |
| **Q3** | Canaux conservés | **Ntfy (principal) + Email + MQTT/HA.** **Pushover, Discord et Slack sont débranchés avec Telegram** — le périmètre de démantèlement (S5) s'élargit en conséquence : `notifier/_pushover.py`, `_discord.py`, `_slack.py`, leurs variables de config, leurs tests, leur documentation | **Écart majeur vs § 9 point 2 et § 12 Q3** : le PRD conservait par défaut les « 5 autres canaux » et renvoyait une éventuelle suppression de Discord/Slack/Pushover à un PRD distinct. L'utilisateur les inclut dans celui-ci |
| **Q4** | Double-run | **Aucun double-run — bascule sèche.** En compensation : une **vérification en réel renforcée** avant débranchement (S5, avant le sprint de suppression) : publication de test sur **chaque topic à chaque niveau** (INFO/WARNING/CRITICAL, priorités ntfy correspondantes), reçue et constatée, **+ un test E2E d'un bouton de confirmation depuis le LAN**, le tout **avant** la suppression du code Telegram | **Écart majeur vs § 6.2**, qui posait 7 jours de double-run comme non négociable (« l'ordre n'est pas négociable »). La durée est remplacée par une checklist de vérification réelle resserrée, mais le principe « ne jamais débrancher avant d'avoir prouvé que ça marche » est conservé |
| **Q5** | TTL de confirmation | **600 s.** `CONFIRM_TTL` — défaut porté de 120 à 600 dans `src/confirm.py` (`DEFAULT_TTL_SECONDS`, L20), pour les actions de confirmation mobiles | Repris de l'option (b) évoquée en recommandation § 12 Q5, mais retenu comme **défaut global** plutôt que « éventuellement, pour la seule action `tplink_reboot` » |
| **Q6** | Markdown dégradable | **Oui**, conforme à la recommandation § 12 Q6 (`**gras**`, listes, code court ; ni tableaux ni liens `[texte](url)`) | Conforme à la reco |
| **Q7** | Accès aux boutons de confirmation | **LAN/Tailscale uniquement**, confirmé explicitement : **aucune** route `/api/confirm/*` n'est exposée via le tunnel Cloudflare. Les URL d'action pointent exclusivement sur les adresses Tailscale des Pi. Assumé : une confirmation ne fonctionne depuis un téléphone que sur LAN ou avec Tailscale actif | Conforme au design déjà retenu au § 4.1/§ 4.2 (Tailscale y était déjà la seule option ✅) — cette décision ferme explicitement la question implicite « et si on passait par Cloudflare comme pour l'abonnement ntfy ? » par non |

**Détail opérationnel nouveau (hors Q1-Q7)** : un utilisateur/token ntfy
`vigil` doit être créé sur le serveur ntfy de bbh-network
(`docker exec ... ntfy user add …` puis droits `write` sur `vigil-*` via
`ntfy access`/`ntfy token add`). Cette étape est exécutée par
**l'orchestrateur humain**, qui dispose de `sudo` sur bbh-network — pas par un
sous-agent `sprint-executor` en worktree, à l'image du renommage du dépôt
GitHub dans le grand renommage (`sprints/01-depot-documentation.md`).
Rattachée au Sprint 1.

**Conséquence directe sur le découpage des sprints (§ 8)** : le Sprint 5,
initialement limité au débranchement de Telegram, démantèle désormais
**quatre** canaux (Telegram, Pushover, Discord, Slack), et il est précédé d'un
**gate de vérification réelle** au lieu d'un double-run de 7 jours. Voir
`2026-08-23_1500-ntfy-first-sortie-telegram/progress.json` et les 5
`sprints/NN-*.md`.

---

## 1. Contexte et décision

Vigil dispose de **7 canaux de notification** (Telegram, Discord, Slack, Ntfy,
Email SMTP, Pushover, MQTT). Dans les faits, un seul est **riche et
interactif** : Telegram. Il porte deux choses très différentes :

1. **Un canal de notification sortant** (`src/notifier/_telegram.py`, 71 lignes)
   — mise en forme HTML, contexte inline, le plus lisible des sept.
2. **Un bot interactif entrant** (`src/telegram_bot.py`, ~270 lignes) — thread
   de long-polling `getUpdates`, filtrage par `chat_id`, 8 commandes
   (`/status`, `/pause`, `/resume`, `/reboot`, `/ddns`, `/backup`,
   `/tailscale`, `/help`) plus le point d'extension `/lte` livré par le
   Sprint 3 d'A1.

**Décision utilisateur du 2026-08-23 (Option B)** : **sortie complète de
Telegram**. Les notifications basculent sur **Ntfy** comme canal principal ; les
commandes sont remplacées par des **boutons d'action Ntfy** (pour les décisions
qui arrivent avec l'alerte) et par le **dashboard + l'API HTTP** (pour tout le
reste). Cible : **2.2.0**, après la livraison d'A1 en 2.1.0.

### Pourquoi c'est plus qu'un changement de canal

Telegram et Ntfy n'ont pas la même **topologie**. C'est le point structurant de
tout ce document :

| | Telegram | Ntfy |
|---|---|---|
| Notification | Vigil → API Telegram (sortant) | Vigil → serveur ntfy (sortant) |
| Commande / réponse | téléphone → Telegram → **Vigil sort chercher** (`getUpdates`, long-polling) | téléphone → **entre directement dans Vigil** (bouton `http`) |

Autrement dit : le bot Telegram fonctionnait **sans aucun flux entrant** vers le
Raspberry Pi. Aucun port ouvert, aucun NAT, aucun VPN — le Pi allait chercher
les ordres. Un bouton d'action Ntfy fait l'inverse : c'est le **téléphone qui
doit joindre le Pi**. Et il doit le faire précisément au pire moment — pendant
un incident de ligne, quand on veut confirmer un redémarrage.

Ce PRD traite cette question de front (§ 4.1) : la réponse retenue est
**Tailscale**, déjà déployé sur la flotte (`src/tailscale_dns.py`), qui
rétablit un chemin entrant tant que le Pi conserve **n'importe quelle**
connectivité sortante (fibre, 4G de secours, DERP relay derrière CGNAT).

### Ce que la sortie de Telegram fait gagner

- **Un thread de long-polling en moins** dans le processus, avec sa boucle de
  reconnexion, son `offset` à gérer et ses erreurs réseau à absorber.
- **Un secret de moins** en production (`TELEGRAM_BOT_TOKEN` × 4 `.env`), et un
  tiers de moins qui voit passer l'état du réseau domestique.
- **Une seule surface de commande** (dashboard + API) au lieu de deux
  divergentes — aujourd'hui le bot sait faire des choses que le dashboard ne
  sait pas (§ 4.5), ce qui est une dette silencieuse.
- **Un canal riche self-hostable** : Ntfy peut tourner sur une infrastructure
  qu'on contrôle, ce que Telegram ne permet pas.

---

## 2. Inventaire — ce qui meurt, ce qui survit

### 2.1 Ce qui meurt

| Élément | Détail | Volume |
|---|---|---|
| `src/telegram_bot.py` | fichier **entier supprimé** : classe `TelegramBot(holder)`, `start()`, `_poll_loop()`, `_poll_updates()`, `is_configured()`, `_api()`, `_send()`, `send_message(chat_id, text)`, `_handle_command()`, `register_lte_handler()`, `_handle_lte()` | ~270 lignes |
| `src/notifier/_telegram.py` | canal notifier **entier supprimé** : `is_configured()`, `send(...)` | 71 lignes |
| Démarrage du bot | thread lancé depuis `src/watchdog.py` sous condition `is_configured()` | quelques lignes |
| Enregistrement du canal | entrée `telegram` dans `_get_channels()` de `src/notifier/_dispatch.py` (import différé) | 1 entrée |
| Config `src/config.py` | `TELEGRAM_BOT_TOKEN` (L220), `TELEGRAM_CHAT_ID` (L221), `TELEGRAM_TIMEOUT` (L222, def. 5), `TELEGRAM_MIN_LEVEL` (L224, def. `INFO`) | 4 variables |
| Branchement dans `src/watchdog.py` | `from telegram_bot import TelegramBot` (L76), `telegram_bot = TelegramBot(state_holder)` + `tg_started = telegram_bot.start()` (L277-279), docstring L11, libellé L927 | ~6 lignes |
| Couche `/lte` Telegram **dans `managed_devices.py`** | `_register_telegram_handlers()` (L367-394, 5 appels `register_lte_handler`), `_adapt_for_telegram()` (L397-408, `send=telegram_bot.send_message`), l'appel depuis `bootstrap()` (L357-364), et les `origin="telegram"` en dur (L531, L555) | ~45 lignes |
| Scripts | `scripts/deploy.sh:81-82` (invite de saisie des secrets), `scripts/test.sh:96-98` + `:103` (test de connectivité) | 6 occurrences |
| Tests | `tests/test_telegram_bot.py` (supprimé) ; retouches dans `tests/test_notifier.py`, `tests/test_managed_devices.py`, `tests/test_http_server.py` | 1 fichier + 3 retouches |
| `requirements.txt` | rien (aucune dépendance Telegram, cf. § 2.4) | 0 ligne |
| Documentation | `README.md` (32 occurrences), `DEPLOY.md` (13), `CLAUDE.md` (8), `WORKFLOW.md` (2) | 55 occurrences |
| `.env` de production | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` retirés des 4 Pi (§ 6.3) | 4 hôtes |

> **Décision du 2026-08-23 (soir), Q3 — périmètre élargi.** Ce tableau ne
> listait que Telegram. L'utilisateur a tranché : **Pushover, Discord et
> Slack sont débranchés dans le même PRD**, avec le même traitement que
> Telegram, listés ici pour mémoire :
>
> | Élément | Détail |
> |---|---|
> | `src/notifier/_pushover.py`, `_discord.py`, `_slack.py` | fichiers **entiers supprimés** |
> | Config `src/config.py` | `DISCORD_WEBHOOK_URL`, `DISCORD_TIMEOUT`, `DISCORD_MIN_LEVEL` ; `SLACK_WEBHOOK_URL`, `SLACK_TIMEOUT`, `SLACK_MIN_LEVEL` ; `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN`, `PUSHOVER_TIMEOUT`, `PUSHOVER_MIN_LEVEL` — 10 variables supplémentaires |
> | Enregistrement des canaux | entrées `discord`, `slack`, `pushover` de `_get_channels()` dans `src/notifier/_dispatch.py` |
> | Tests | `tests/test_pushover_notifier.py` (fichier entier supprimé) ; classes/tests Discord et Slack retirés de `tests/test_notifier.py` |
> | Documentation | occurrences `Discord`/`Slack`/`Pushover` dans `README.md`, `DEPLOY.md`, `CLAUDE.md`, `WORKFLOW.md` |
> | `.env` de production | `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN` retirés des 4 Pi s'ils y étaient présents (à vérifier — aucun des deux sites n'a confirmé les utiliser) |
>
> Rattaché au Sprint 5 (§ 8), dont le titre et les critères de vérification
> sont élargis en conséquence (§ 9 point 2, § 10 « Débranchement »).

**Ne sont pas réécrits** : les documents historiques (`docs/adr/0001-*.md`,
`docs/RELEASE-NOTES-1.8.*`, `docs/RELEASE-NOTES-2.0.0.md`,
`docs/tasks/**` y compris la spec A1 et son Sprint 3). Ils décrivent l'état du
système à une date donnée ; les réécrire falsifie la trace. Même règle qu'au
grand renommage.

### 2.2 Ce qui survit (et pourquoi)

| Élément | État | Raison |
|---|---|---|
| `src/confirm.py` | **intact**, sauf le durcissement du jeton (§ 4.2.3) | **Zéro couplage Telegram** — vérifié : aucun import, aucune mention `chat_id`, aucun formatage orienté canal. `request_confirmation(action, context, ttl) -> str`, `validate(token, action) -> dict \| None`, `purge_expired() -> int`. Jeton en mémoire, usage unique (`pop` inconditionnel), TTL 120 s (`CONFIRM_TTL`), verrou global, aucune persistance disque (volontaire). |
| `src/managed_devices.py` (581 l.) | **survit**, amputé de ~45 lignes | Restent agnostiques : `ManagedDeviceRegistry` (cache + verrou), `request_reboot()` (L278-296, crée le jeton via `confirm.request_confirmation(CONFIRM_ACTION_REBOOT, …)`), `confirm_reboot(token, origin, …)` (L298-345, consomme le jeton, exécute `driver.reboot()` avec un réessai, notifie via `notify()`, journalise dans l'`EventLog`), `_make_handle_lte_*` (qui prennent déjà un `send: Callable` **injectable**), `_status_dict`, `_traffic_warning`, `_format_*`. Déjà consommé par `/api/tplink/*`. |
| `src/alert_escalation.py` (49 l.) | **intact** | Vérifié : **zéro couplage canal**. `EscalationTracker` ne fait que du suivi temporel (§ 5). |
| `src/messages.py` (499 l.) | **survit**, templates **re-ciblés** | Les gabarits « quoi / pourquoi / quoi faire » restent la bonne abstraction. Ce qui change : le rendu HTML Telegram disparaît, un rendu texte structuré (± Markdown, § 3.4) le remplace. |
| Les 5 autres canaux | **inchangés** — Discord, Slack, Email SMTP, Pushover, MQTT | Cf. § 9 et question **Q3**. |
| `src/notifier/__init__.py` (`notify()`) | **contrat inchangé** | `notify(message, level, context)`, never raises, filtrage par `MIN_LEVEL`. Rien de ce PRD ne doit modifier cette signature. *(Note : `dispatch()` itère en réalité **séquentiellement**, pas en parallèle comme l'annonce `CLAUDE.md` — à corriger dans la doc au passage.)* |
| Endpoints `/api/tplink/*` | **inchangés** | Livrés par A1 Sprint 3, protégés par `Bearer API_TOKEN`, indépendants du canal. |

> **Décision du 2026-08-23 (soir), Q3** : la ligne « Les 5 autres canaux —
> inchangés » ci-dessus est **caduque**. Seuls **Email SMTP** et **MQTT**
> restent inchangés ; **Discord, Slack et Pushover sont débranchés** avec
> Telegram (§ 2.1, encart daté). Voir § 0bis pour le détail.

### 2.3 La couche `/lte` du Sprint 3 d'A1 : dette assumée

Le Sprint 3 d'A1 (livré, commit `29360cd`) ajoute `/lte <sous-commande>` au bot
Telegram. Ce PRD la supprime **une version plus tard**. C'est un coût réel, à
poser franchement :

- **Ce qui est perdu** : le routage `_handle_lte()`, le registre
  `register_lte_handler()`, les handlers de sous-commandes et leur formatage de
  réponse. Une **couche mince**, par construction.
- **Ce qui est conservé** : tout le travail de fond du Sprint 3 — le registre
  `managed_devices.py`, le pattern « action en attente, jeton court, usage
  unique » de `confirm.py`, et les endpoints `/api/tplink/*`. Ces trois-là ont
  été écrits **agnostiques du canal** dès le départ ; c'est exactement ce qui
  rend la sortie de Telegram peu coûteuse aujourd'hui.
- **Décision** : ne **pas** retarder A1, ne **pas** amputer son Sprint 3 par
  anticipation. Livrer 2.1.0 comme prévu, avec `/lte` fonctionnel, puis le
  retirer en 2.2.0. Le seul gaspillage est la couche d'adaptation ; l'alternative
  (bloquer A1 en attendant les boutons Ntfy) coûterait plus cher en délai qu'en
  code.

### 2.4 Dépendances : rien à retirer de `requirements.txt`

*(Correction du 2026-08-23 : la première version de cette section décrivait un
`requirements.txt` corrompu — c'était une erreur d'inventaire de l'agent
rédacteur, démentie par vérification directe et par l'historique git. État
réel et sain : `paramiko==3.5.0`, `paho-mqtt==1.6.1`,
`tplinkrouterc6u==5.31.1`, rien d'autre.)*

Le bot Telegram n'a **aucune dépendance propre** : `telegram_bot.py` et
`notifier/_telegram.py` utilisent la stdlib/`requests` déjà présents. La
sortie de Telegram ne retire donc **aucune ligne** de `requirements.txt` —
c'est une suppression de code pur, sans impact venv.

---

## 3. Ntfy enrichi comme canal principal

### 3.1 État actuel du canal (mesuré, pas supposé)

`src/notifier/_ntfy.py` (69 lignes) fait un `POST` brut sur
`{NTFY_URL}/{NTFY_TOPIC}` avec :

- `Title: Vigil` — **constant**, aucune information
- `Priority: 3 / 4 / 5` selon INFO / WARNING / CRITICAL
- `Tags: information_source / warning / rotating_light`
- `Content-Type: text/plain; charset=utf-8`
- corps texte brut : `message` + `hostname -- timestamp` + contexte inline

Configuration disponible : `NTFY_URL` (L249, défaut `""`), `NTFY_TOPIC` (L251,
défaut `""`), `NTFY_TIMEOUT` (L252, défaut 5 s), `NTFY_MIN_LEVEL` (L253, défaut
`INFO`).

**Ce qui manque, et que l'API ntfy offre déjà** : `Authorization: Bearer tk_…`,
`Actions` (jusqu'à **3 boutons** par notification), `Click` (URL ouverte au tap),
`Markdown: yes`, `Icon`, `Cache: no`, `Attach`, `Email`, `Delay`.

**Constat de sécurité immédiat** : il n'existe **aucune** variable
`NTFY_TOKEN` / `NTFY_AUTH`. Aujourd'hui, la seule protection du topic est son
nom (« secret d'obscurité »). Tant qu'on n'y publiait que du texte, c'était une
fuite d'information ; à partir du moment où on y publie des **boutons d'action**,
ça devient une surface de commande. L'authentification n'est donc plus
optionnelle — voir § 3.6 et § 4.2.

### 3.2 Niveaux Vigil → priorités ntfy

Vigil manipule aujourd'hui `Level` = INFO / WARNING / CRITICAL (aucun niveau
EMERGENCY n'existe dans `notifier/_types.py`). Ntfy offre 5 priorités.
**Recommandation : ne pas inventer un niveau EMERGENCY** — on utilise la marge
haute de ntfy pour l'escalade (§ 5), pas pour un nouveau niveau applicatif.

| `Level` Vigil | `Priority` ntfy | Tags proposés | Comportement téléphone |
|---|---|---|---|
| INFO | `3` (default) | `information_source` + tag d'instance | notification normale |
| WARNING | `4` (high) | `warning` + tag d'instance | vibration longue, en haut de la pile |
| CRITICAL | `5` (max/urgent) | `rotating_light` + tag d'instance | sonnerie insistante, contourne certains modes silencieux |
| **Escalade** (§ 5) | `5` + `Call` / email de secours | `sos` | rappel d'une CRITICAL non traitée |

Les rapports quotidiens/hebdomadaires descendent à `2` (low) — c'est de la
donnée de fond, elle ne doit pas faire vibrer un téléphone à 8 h du matin.
Cas particulier : **`Priority: 1` (min) est réservé aux événements de
recovery répétitifs** si l'on constate du bruit pendant le double-run.

### 3.3 Titre, tags et `Click`

- **`Title`** : `Vigil` seul est inutilisable avec 4 instances. Format
  proposé : `Vigil <instance> — <résumé court>`, p. ex.
  `Vigil penelope — Internet KO (score 12/15)`. C'est le titre qui s'affiche
  sur écran verrouillé ; il doit suffire à décider si on déverrouille.
- **`Tags`** : `<tag de niveau>,<instance_id>,<site>` — les tags non reconnus
  comme emoji s'affichent en libellé sous le message, ce qui donne un filtrage
  visuel gratuit entre les 4 Pi.
- **`Click`** : URL du dashboard de **l'instance émettrice**
  (`http://<nom-tailscale>:9000/dashboard`). Un tap sur la notification ouvre
  l'état **temps réel** au lieu d'un instantané figé. C'est le remplaçant
  direct de `/status` (§ 4.3).
- **`Icon`** : hors périmètre (nécessite une URL d'image publiquement
  atteignable ; le jeu n'en vaut pas la chandelle).

### 3.4 Markdown : oui, mais dégradable

`Markdown: yes` est supporté **par l'application web ntfy**, pas uniformément
par les clients mobiles. Conséquence de conception, non négociable : **le corps
du message doit rester parfaitement lisible en texte brut**. Concrètement, on
s'interdit les tableaux Markdown et les liens `[texte](url)` dans le corps ; on
autorise `**gras**`, les listes `-` et les blocs de code courts. Un test doit
vérifier qu'aucun gabarit de `messages.py` ne dépasse ce sous-ensemble.

Contrainte dure supplémentaire : **le corps d'un message ntfy.sh est plafonné à
4 096 octets**. Les rapports hebdomadaires les plus longs doivent être tronqués
proprement avec un lien `Click` vers `/api/report`.

### 3.5 Topics : par site, par instance, ou unique ?

Trois découpages possibles pour 4 instances réparties sur 2 sites :

| Option | Nb de topics | Avantage | Inconvénient |
|---|---|---|---|
| **Unique** (`vigil`) | 1 | le plus simple | impossible de couper le bruit d'un site sans se couper de l'autre |
| **Par site** (`vigil-dijon`, `vigil-nice`) | 2 | on peut mettre un site en sourdine (travaux, déménagement) ; les 2 Pi d'un site parlent du même incident au même endroit | ne distingue pas master/slave — mais les tags le font |
| **Par instance** | 4 | granularité maximale | **double notification systématique** : les 2 Pi d'un site détectent le même incident et alertent chacun sur son topic ; 4 abonnements à gérer sur chaque téléphone |

**Recommandation : par site**, avec `INSTANCE_ID` porté par les tags et par le
`Title`. C'est le seul découpage qui corresponde à une **unité de décision**
réelle (« la ligne de Nice est tombée »). Nouvelle variable :
`NTFY_TOPIC` reste, chaque `.env` reçoit sa valeur (`vigil-dijon` /
`vigil-nice`). Aucun changement de code n'est nécessaire pour cette option —
c'est de la configuration. Cf. **Q2**.

> **Note** : quel que soit le découpage, la **double notification par site
> subsiste** (master et slave alertent tous les deux). Ce n'est pas une
> régression — c'est déjà le comportement avec Telegram — et ntfy n'offre pas
> de déduplication côté serveur. Hors périmètre de ce PRD ; à traiter, si le
> bruit devient gênant, par la logique de peering (`peer.py`), pas par le canal.

### 3.6 Serveur cible et authentification

Deux décisions couplées, à trancher par l'utilisateur (**Q1**) :

**a) Où tourne le serveur ?**

- **`ntfy.sh` (cloud)** — zéro maintenance, disponibilité indépendante des deux
  sites surveillés. Limites du service gratuit : 4 096 octets par message,
  60 requêtes par visiteur (recharge 1/5 s), **250 messages/jour**, cache
  serveur de 12 h. Un compte payant permet en plus de **réserver un topic**
  (personne d'autre ne peut y publier).
- **Self-hosted sur un VPS tiers** — on garde la main sur les données, y compris
  les URL d'action (§ 4.2), et on configure `auth-default-access: deny-all`,
  `auth-users`, `auth-access` et `auth-tokens`.
- **Self-hosted sur un Pi d'un des deux sites** — ❌ **à écarter**. Héberger le
  serveur de notification derrière la ligne qu'il sert à surveiller est un point
  de défaillance unique : le jour où le site tombe, l'alerte ne part pas. C'est
  la seule option réellement disqualifiante.

**Recommandation** : `ntfy.sh` avec topic réservé + token d'accès, ou VPS tiers
si la confidentialité des messages pèse plus que la maintenance. Dans les deux
cas, **le serveur doit être hors des deux sites surveillés**.

**b) Authentification** — quel que soit le serveur retenu, ce PRD **exige**
d'ajouter :

- `NTFY_TOKEN: str` (défaut `""`) → header `Authorization: Bearer tk_…` sur
  chaque publication. Le token doit être **write-only** sur le topic
  (`auth-access: vigil-publisher:vigil-*:wo` en self-hosted).
- Le topic n'est plus « public devinable » : un tiers ne doit pouvoir ni
  **lire** les alertes (état du réseau, IP publique, contexte), ni **publier**
  de faux messages (un faux bouton d'action est un vecteur de hameçonnage
  particulièrement efficace : la notification arrive avec le bon nom, le bon
  logo, la bonne heure).
- `NTFY_URL` accepte déjà librement une URL self-hosted (aucune validation de
  domaine, commentaire L248) — rien à changer côté schéma de configuration.

> **Décision du 2026-08-23 (soir), Q1** : le serveur retenu n'est ni (b) ni
> (c) au sens strict ci-dessus — c'est le ntfy **déjà déployé** sur
> bbh-network (conteneur Docker `binwiederhier/ntfy`, port 7171,
> authentification déjà active côté serveur : publication anonyme y renvoie
> déjà 403). L'exposition publique est **déjà en place**,
> `https://ntfy.bbhome.wf` via un tunnel Cloudflare — Vigil ne la met pas en
> place, elle existe déjà pour l'abonnement téléphone. Ce que ce PRD fixe :
> **la publication interne des 4 Pi ne passe jamais par Cloudflare**.
> dijon-master (colocalisé sur bbh-network) publie en local sur
> `http://127.0.0.1:7171` ; les 3 autres Pi (dijon-slave, nice-master,
> nice-slave) publient sur `http://100.112.123.103:7171` (IP Tailscale de
> bbh-network). Le risque que le § 3.6 qualifiait de « seule option
> réellement disqualifiante » — héberger le serveur de notification sur un
> site surveillé — est ici **explicitement assumé** par l'utilisateur, pas
> écarté : bbh-network hébergeant le serveur ntfy, une panne de ce site
> précis coupe le canal de notification qu'il sert. Mitigation retenue :
> Email SMTP et MQTT restent des canaux indépendants (§ 9, Q3). Voir § 0bis.

---

## 4. Remplacement des commandes

### 4.1 Le problème de fond : rétablir un chemin entrant

Rappel du § 1 : un bouton d'action Ntfy est une requête HTTP **du téléphone vers
le Pi**. Trois chemins possibles, un seul acceptable :

| Chemin | Verdict |
|---|---|
| **IP LAN** (`http://192.168.1.x:9000/…`) | ❌ ne marche que depuis la maison. Or on confirme un reboot **quand on n'y est pas**. |
| **Redirection de port / IP publique** | ❌❌ expose le serveur HTTP de Vigil sur Internet, **en clair** (aucun TLS dans `http_server.py`), sans rate limiting, avec la quasi-totalité des GET publics sans authentification (`/api/state`, `/api/config`, `/api/events`, `/api/backup/config`…). Inacceptable. Et pendant une panne de ligne, l'IP publique est justement ce qui ne répond plus. |
| **Tailscale** (`http://<nom-magicdns>:9000/…` ou `http://100.x.y.z:9000/…`) | ✅ **retenu**. |

Pourquoi Tailscale résout le problème :

1. **Rien n'est exposé** — le port 9000 reste sur `0.0.0.0` mais n'est joignable
   que depuis le tailnet ; aucune redirection de port, aucune IP publique.
2. **Le trafic est chiffré de bout en bout** (WireGuard), ce qui compense
   l'absence de TLS dans `http_server.py`. **Aucun reverse proxy à déployer.**
3. **Ça traverse la panne** : Tailscale maintient une connexion sortante et
   sait retomber sur un relais DERP derrière du CGNAT. Tant que le Pi a *une*
   connectivité sortante — y compris via le TP-Link 4G de secours d'A1 — le
   téléphone le joint. Et si le Pi n'a plus **aucune** connectivité sortante,
   alors **la notification ntfy ne serait pas partie non plus** : il n'y a pas
   de scénario où l'on reçoit une alerte sans pouvoir répondre au bouton.
4. **Bénéfice de sécurité gratuit** : une URL d'action pointant sur `100.x.y.z`
   est **inutilisable hors du tailnet**. Même si le serveur ntfy, son
   administrateur, ou n'importe qui lisant l'historique du topic récupère
   l'URL complète, il ne peut rien en faire — l'adresse n'est routable que pour
   les membres du tailnet. C'est ce qui rend le design du § 4.2 tenable.

**Prérequis explicite** : Tailscale doit être installé et actif sur les 4 Pi
**et** sur les téléphones qui reçoivent les notifications. C'est déjà le cas des
Pi (`src/tailscale_dns.py` synchronise le DNS du tailnet) ; le téléphone est à
vérifier avant le Sprint 2.

> **Décision du 2026-08-23 (soir), Q7** : confirmée sans réserve — **LAN/
> Tailscale uniquement**. Aucune route `/api/confirm/*` n'est exposée via le
> tunnel Cloudflare qui sert par ailleurs `https://ntfy.bbhome.wf` (Q1) :
> l'abonnement au topic passe par Cloudflare, la confirmation d'action jamais.
> Toutes les URL d'action publiées dans les boutons ntfy pointent sur les
> adresses Tailscale des 4 Pi, jamais sur une IP LAN ni sur un nom public.
> Conséquence assumée : une confirmation ne fonctionne depuis un téléphone que
> sur le LAN domestique ou avec Tailscale actif sur ce téléphone — un
> réglage réseau opérateur (bascule Wi-Fi/4G, Tailscale endormi) peut donc
> faire expirer une confirmation sans recours. C'est déjà le risque n°3
> identifié au § 11 ; cette décision ne l'ajoute pas, elle en confirme
> l'acceptation.

### 4.2 Confirmations par boutons d'action — **point de sécurité central**

C'est le cœur du PRD. Le cas d'usage : Vigil détecte que la ligne fixe est
tombée, veut redémarrer le TP-Link MR110 de secours, et **demande confirmation**
parce que l'équipement fait peut-être passer du trafic (règle héritée d'A1
Sprint 3 : « `/lte reboot <id>` n'exécute pas, il retourne un jeton »). Demain,
la même mécanique servira aux commandes SMS/USSD.

#### 4.2.1 Ce qu'il ne faut surtout pas faire

Ntfy permet d'attacher des en-têtes arbitraires à un bouton :

```
Actions: http, Redémarrer, https://…/api/tplink/mr110-nice/reboot/confirm, \
         method=POST, headers.Authorization=Bearer <API_TOKEN>, body={"token":"a1b2c3d4"}
```

C'est la solution évidente. **Elle est interdite dans ce PRD.** Raisons :

1. **`API_TOKEN` n'est pas un secret de notification, c'est la clé du système.**
   Il ouvre `POST /api/reboot` (redémarrage du USG), `/api/pause` (arrêt de la
   surveillance), `/api/config/reload`, `/api/tplink/*`. Le mettre dans un
   bouton, c'est le donner en échange d'une confirmation de reboot.
2. **Le serveur ntfy voit tout.** Le header d'action fait partie du **corps du
   message**, relayé et **mis en cache 12 h** côté serveur (`ntfy.sh` par
   défaut), récupérable par tout abonné du topic et par l'opérateur du service.
3. **La rétention n'est pas maîtrisée** : historique du topic, sauvegardes du
   téléphone, application web ntfy restée ouverte sur un poste, capture
   d'écran, aperçu sur écran verrouillé.
4. **Un secret à durée de vie infinie dans un message à durée de vie infinie**
   est le pire des couples : la fuite est silencieuse et permanente. Un
   `API_TOKEN` compromis se révoque en modifiant 4 `.env` et en redémarrant
   4 services — on le saura trop tard.

**Règle absolue, à inscrire dans `INVARIANTS.md`** : *aucune notification
sortante, quel que soit le canal, ne contient `API_TOKEN` — ni dans le corps,
ni dans un en-tête d'action, ni dans une URL.* Vérifiable par un test qui
publie une notification de chaque type et grep le payload.

#### 4.2.2 Design retenu : l'URL de capacité

Le jeton de confirmation de `confirm.py` **est déjà** exactement ce qu'il faut :
court, à usage unique, à durée de vie très courte, et **lié à une action
précise**. On l'utilise comme **capacité** (capability URL) plutôt que comme
mot de passe à taper.

```
Actions: http, Confirmer le redémarrage, \
         http://vigil-nce-guardian:9000/api/confirm/tplink_reboot/<jeton>, \
         method=POST, clear=true ; \
         http, Annuler, \
         http://vigil-nce-guardian:9000/api/confirm/cancel/<jeton>, \
         method=POST, clear=true
```

Propriétés du design :

- **Aucun en-tête `Authorization`** dans le bouton. Le jeton **est** l'autorisation.
- **Nouvel endpoint `POST /api/confirm/<action>/<jeton>`**, et lui seul, est
  **exempté** de `_check_auth()`. Il ne sait faire qu'une chose : résoudre une
  confirmation **déjà en attente**, créée par Vigil lui-même. Il n'expose aucun
  état, ne prend aucun paramètre venant de l'appelant, et ne peut pas servir à
  déclencher une action qui n'a pas été proposée.
- **L'action est dans le chemin, pas dans le jeton** : on appelle
  `confirm.validate(jeton, action)`, qui **compare** `entry.action != action` et
  refuse en cas d'écart. Un jeton émis pour `tplink_reboot` ne peut donc pas
  être rejoué contre un futur `usg_reboot` ou `sms_send`. Cette propriété existe
  déjà dans `confirm.py` — il faut simplement ne pas la contourner.
- **Usage unique déjà garanti** : `validate()` fait un `pop` **inconditionnel**,
  valide ou non. Un jeton rejoué renvoie 404, y compris pour l'attaquant qui
  l'aurait vu passer.
- **TTL déjà court** : 120 s par défaut (`CONFIRM_TTL`). La fenêtre
  d'exploitation d'une URL fuitée est donc de deux minutes **et** conditionnée à
  un accès au tailnet (§ 4.1).
- **`clear=true`** retire la notification du téléphone après succès — évite le
  double-appui et le « bouton mort » qui traîne.
- **Bouton « Annuler »** explicite : `<action>` vaut `cancel`, ce qui consomme
  le jeton et **interdit** la confirmation ultérieure. Sans lui, la seule façon
  d'annuler est d'attendre 120 s.

#### 4.2.3 Durcissements obligatoires (le jeton change de métier)

`confirm.py` a été écrit pour un jeton **tapé par un humain dans un chat
authentifié** (`/lte confirm a1b2c3d4`) — d'où `secrets.token_hex(4)`, soit
**8 caractères hex = 32 bits d'entropie**. Dans un chat Telegram filtré par
`chat_id`, c'est suffisant. Dans une URL exposée à un endpoint **non
authentifié**, ça ne l'est plus : plus personne ne doit *taper* ce jeton, donc
plus rien ne justifie qu'il soit court.

| # | Durcissement | Détail |
|---|---|---|
| **D1** | **Entropie** : `secrets.token_hex(4)` → `secrets.token_urlsafe(32)` (≈256 bits) | Le jeton n'est plus saisi à la main. Aucune raison de rester à 2³². |
| **D2** | **Comparaison en temps constant** | `validate()` s'appuie sur un `dict.pop` (temps constant en pratique) mais `entry.action != action` doit passer à `hmac.compare_digest`. À faire aussi pour `_check_auth()` qui compare `API_TOKEN` avec `==` (dette existante, corrigée au passage). |
| **D3** | **Rate limiting** sur `/api/confirm/*` | Aucun rate limiting n'existe aujourd'hui dans `http_server.py`. Minimum : N tentatives échouées / minute / IP → 429 + événement `confirm_bruteforce` dans l'`EventLog`. |
| **D4** | **Pas de jeton dans les logs** | `log_message()` journalise la requête complète en `logging.debug` — donc le chemin, donc le jeton. Masquer `/api/confirm/<action>/<jeton>` → `/api/confirm/<action>/***`. |
| **D5** | **`API_TOKEN` obligatoire** | Le défaut est `""` ; `_check_auth()` est heureusement **fail-closed** (403 si vide). À renforcer : log `CRITICAL` au démarrage si `API_TOKEN` est vide alors qu'un canal avec boutons d'action est configuré. |
| **D6** | **Réponse muette** | L'endpoint répond `200 {"ok": true}` ou `404 {"error":"unknown or expired"}` — **jamais** de détail sur l'existence du jeton, l'action visée ou l'équipement. |
| **D7** | **Événement systématique** | Chaque confirmation (acceptée, refusée, expirée) génère un événement `confirm_accepted` / `confirm_rejected` dans l'`EventLog`, donc visible dans `/api/events` et le dashboard. Une confirmation qu'on n'a pas déclenchée doit se voir. |

> **Décision du 2026-08-23 (soir), Q5** : le TTL par défaut de `confirm.py`
> passe de **120 s à 600 s** — `DEFAULT_TTL_SECONDS` dans `src/confirm.py`
> (L20), et donc la valeur lue par `_get_ttl_seconds()` quand `CONFIRM_TTL`
> n'est pas positionné dans l'environnement. Recommandation (b) du § 12 Q5
> retenue, mais comme **défaut global** (toutes les actions confirmables, pas
> seulement `tplink_reboot`). Conséquence directe sur D1/D3 : la fenêtre
> d'exploitation d'un jeton fuité, déjà ramenée à « inutilisable hors
> tailnet » par le § 4.1, passe de 2 à 10 minutes — jugé acceptable
> puisqu'elle reste conditionnée à un accès Tailscale. Tous les tests et
> critères d'acceptation qui référencent « 120 s » (§ 4.2.2, § 6.2, § 10)
> s'entendent désormais avec la valeur effective de `CONFIRM_TTL`, soit 600 s
> après ce changement de défaut.

#### 4.2.4 Ce que le design ne protège pas (limites honnêtes)

- **Téléphone déverrouillé entre de mauvaises mains** : le bouton s'appuie sans
  friction. Même exposition qu'aujourd'hui avec Telegram (le chat aussi est
  ouvert). Non traité.
- **Faux message publié sur le topic** : si le topic n'est pas protégé en
  écriture, n'importe qui peut publier une notification ressemblant à Vigil,
  avec un bouton pointant où il veut. **C'est précisément pourquoi le § 3.6
  rend l'authentification ntfy obligatoire** — ce n'est pas un confort.
- **Compromission du tailnet** : hors périmètre, mais c'est bien le nouveau
  périmètre de sécurité de la surface de commande.

#### 4.2.5 Secret d'action séparé : évalué, **non retenu**

Alternative envisagée : un `NTFY_ACTION_SECRET` distinct d'`API_TOKEN`, de
portée minimale, envoyé en en-tête du bouton. **Rejeté** : ce secret vivrait
dans **chaque message** publié, donc exactement là où l'on refuse de mettre
`API_TOKEN`. Il ne protège de rien qu'un lecteur du topic ne contourne
immédiatement (il a le jeton *et* le secret). Il n'apporterait quelque chose que
si l'URL fuitait **séparément** de l'en-tête (journaux d'un proxy, historique de
navigateur) — scénario marginal une fois D4 appliqué. **Complexité opérationnelle
sans gain réel.** À reconsidérer seulement si l'on renonçait à Tailscale et que
l'endpoint devenait joignable depuis Internet — ce que le § 4.1 exclut.

### 4.3 Consultation : `Click` + dashboard, pas de bot

`/status` occupait 35 lignes de calcul de statut **inline dans le bot** (logique
dupliquée du dashboard). Son remplaçant est plus simple et strictement meilleur :

- Chaque notification porte un `Click` vers `/dashboard` de l'instance — un tap
  donne l'état **temps réel** (le dashboard rafraîchit toutes les 5 s et
  `/api/stream` diffuse déjà en SSE), là où `/status` renvoyait un instantané.
- Le dashboard est déjà une **PWA installable** (`src/pwa.py`), utilisable
  hors ligne — un raccourci sur l'écran d'accueil vaut mieux qu'une commande à
  se rappeler.
- Bénéfice collatéral : la logique de statut n'existe plus qu'à **un seul
  endroit**.

### 4.4 Faut-il un topic de commandes entrantes ? **Recommandation : non**

L'option existe : Vigil s'abonne à un topic `vigil-cmd` via
`GET /<topic>/json` (flux ndjson) ou `/ws`, et interprète les messages publiés
depuis l'application ntfy comme des commandes.

**Arguments contre (décisifs)** :

1. **On recrée exactement ce qu'on supprime** : un thread de long-polling, une
   boucle de reconnexion, un parseur de commandes, une gestion d'`offset`/de
   doublons. Le gain net de la sortie de Telegram tomberait à zéro.
2. **Un topic en écriture est une surface de commande permanente**, sans le
   filtrage `chat_id` de Telegram. Il faudrait ré-inventer l'autorisation.
3. **L'ergonomie est mauvaise** : taper `status` dans un champ de publication
   ntfy est plus lent que de toucher la notification (qui ouvre le dashboard).
4. **A2 (2.3.0) rend le besoin encore plus faible** : l'état sera dans Home
   Assistant, avec ses propres cartes et automatisations.

**Argument pour, à ne pas balayer** : c'est le **seul chemin purement sortant**,
la seule propriété que Telegram avait et que Tailscale doit remplacer.

**Position retenue** : **non**, mais avec un **plan B écrit d'avance**. Si le
double-run (§ 6.2) montre que le chemin entrant Tailscale est peu fiable en
conditions réelles (téléphone en veille, bascule Wi-Fi/4G, DERP lent), alors on
implémente un abonné ntfy **strictement limité aux confirmations** — il n'accepte
qu'un jeton `confirm.py` valide, aucune commande libre, aucun parseur. Ce n'est
pas un bot. Critère de déclenchement du plan B : **plus d'un échec de bouton
d'action sur 10 pendant la période de double-run** (§ 10).

### 4.5 Actions d'exploitation : ce que le dashboard sait déjà faire

Inventaire vérifié dans `src/http_server.py` et `src/dashboard.py` :

| Commande du bot | Endpoint API | Bouton dashboard | À faire |
|---|---|---|---|
| `/status` | `GET /api/state`, `/health`, `/api/stream` (publics) | affichage passif (cartes) | rien — cf. § 4.3 |
| `/pause` | `POST /api/pause` ✅ | bouton présent — **cassé** ⚠️ | corriger l'auth |
| `/resume` | `POST /api/resume` ✅ | bouton présent — **cassé** ⚠️ | corriger l'auth |
| `/reboot` (USG) | `POST /api/reboot` ✅ | bouton présent — **cassé** ⚠️ | corriger l'auth |
| `/ddns` | `POST /api/ddns/update` ✅ | **manquant** | ajouter |
| `/backup` | `POST /api/backup/unifi` ✅ | **manquant** | ajouter |
| `/tailscale` | `POST /api/tailscale/sync` ✅ | **manquant** | ajouter |
| `/lte …` | `GET /api/tplink`, `/api/tplink/<id>[/status]`, `POST …/check`, `…/reboot`, `…/reboot/confirm` ✅ | **manquant** (aucune section TP-Link) | ajouter |
| — | `POST /api/maintenance`, `POST /api/config/reload` ✅ | **manquant** | ajouter (optionnel) |

> **⚠️ Bug découvert pendant l'inventaire — dans le périmètre.**
> `sendCommand(cmd)` (`dashboard.py` ~L506-522) fait
> `fetch('/api/' + cmd, {method: 'POST'})` **sans en-tête `Authorization`**.
> `_check_auth()` étant fail-closed, **les trois boutons du dashboard renvoient
> 403 dès qu'`API_TOKEN` est configuré** — c'est-à-dire en production. Le
> dashboard n'a ni invite, ni champ, ni `localStorage` pour un jeton.
> Conséquence : **la « surface de commande de repli » sur laquelle repose toute
> la sortie de Telegram ne fonctionne pas aujourd'hui.** C'est un prérequis
> bloquant, pas une amélioration — traité en Sprint 3.
>
> Correction recommandée : saisie du jeton une fois, conservé en
> `sessionStorage` (pas `localStorage` : pas de persistance après fermeture),
> injecté en `Authorization: Bearer`, avec un retour d'erreur explicite en 401.

> **Note de sécurité connexe, hors périmètre mais à consigner.** La quasi-totalité
> des GET (`/api/state`, `/api/config`, `/api/events`, `/api/history`,
> `/api/sla`, `/api/backup/config`, `/metrics`) sont **publics sans
> authentification**, sur un bind `0.0.0.0` sans TLS. Seul `/api/tplink*` a été
> protégé en GET (divergence assumée et commentée, `http_server.py:567-574`).
> Ce PRD **ne referme pas** cette surface (`peer.py` et Prometheus en dépendent),
> mais elle renforce la conclusion du § 4.1 : **ce serveur ne doit jamais être
> exposé sur Internet.** À traiter dans un PRD sécurité dédié.

---

## 5. Escalade d'alertes sans Telegram

### 5.1 Bonne nouvelle : `alert_escalation.py` n'a rien à recâbler

Vérifié ligne à ligne : `src/alert_escalation.py` (49 lignes) est **totalement
agnostique du canal**. `EscalationTracker` ne fait que du suivi temporel :

- `on_critical()` (L25-29) mémorise l'horodatage du premier CRITICAL ;
- `on_recovery()` (L31-34) remet le compteur à zéro ;
- `should_escalate()` (L36-49) renvoie `True` **une seule fois**,
  `ALERT_ESCALATION_DELAY × 60` secondes après le premier CRITICAL, si
  `ALERT_ESCALATION_ENABLED`.

Aucun import de `_telegram`, aucune liste de canaux en dur, aucun ordre de
priorité. La ré-émission est faite par l'appelant (`watchdog.py`) via un simple
`notify()` : l'escalade **retombe donc naturellement sur les canaux dont le
`MIN_LEVEL` accepte CRITICAL**. Retirer Telegram du tuple `_get_channels()`
suffit — il n'y a pas de « recâblage » à faire.

Défauts pertinents : `SMTP_MIN_LEVEL` vaut `WARNING` (le seul canal qui ne
défaute pas sur `INFO`), donc **l'email reçoit déjà les escalades** dès qu'il
est configuré. `ALERT_ESCALATION_ENABLED` est `false` par défaut,
`ALERT_ESCALATION_DELAY` = 15 min (min. 5).

### 5.2 Ce qui change quand même

| Point | Aujourd'hui | En 2.2.0 |
|---|---|---|
| Canal d'escalade de fait | Telegram (le seul lu en pratique) | **Ntfy `Priority: 5`** + tag `sos` + `Click` dashboard |
| Second canal | aucun garanti | **Email SMTP**, qui passe déjà (`SMTP_MIN_LEVEL=WARNING`) — à **configurer sur les 4 Pi**, ce qui n'est peut-être pas le cas aujourd'hui (**Q3**) |
| Différenciation visuelle | aucune (même mise en forme qu'une CRITICAL normale) | l'escalade **doit** se distinguer : titre préfixé `[RELANCE]`, tag `sos`, et **pas de bouton d'action** (§ 5.3) |
| Accusé de réception | inexistant — `on_recovery()` est déclenché par la **remontée du score**, pas par une action humaine | **inchangé**, et c'est volontaire (§ 5.3) |

### 5.3 Pas d'ACK, et pas de bouton sur l'escalade

Deux tentations à écarter explicitement :

- **Ajouter un bouton « J'ai vu » (ACK)**. Il n'existe aucun mécanisme d'ACK
  aujourd'hui ; en créer un demande un état persistant, une expiration, et une
  décision sur ce que « vu » implique. Hors périmètre. Le signal d'arrêt de
  l'escalade reste le rétablissement réel du service — ce qui est plus honnête
  qu'un bouton qui fait taire l'alarme sans réparer la ligne.
- **Mettre les boutons de confirmation sur le message d'escalade**. Non : les
  jetons `confirm.py` ont un TTL de 120 s, l'escalade arrive après 15 minutes.
  Un bouton mort est pire qu'aucun bouton. L'escalade porte un `Click` vers le
  dashboard, rien d'autre.

**Recommandation complémentaire (optionnelle, à chiffrer en Sprint 4)** : ntfy
propose une action `Call` (appel téléphonique) sur les comptes payants
`ntfy.sh`. C'est le seul mécanisme qui réveille vraiment quelqu'un la nuit. À
n'activer que si l'utilisateur le demande — cf. **Q1**.

---

## 6. Migration

### 6.1 Principe : enrichir avant de débrancher

L'ordre n'est pas négociable — **on ne débranche jamais le canal qui marche
avant d'avoir prouvé que le nouveau marche** :

```
1. Ntfy enrichi (priorités, titres, tags, Click, auth)   ← Telegram toujours actif
2. Endpoint de confirmation + boutons d'action            ← Telegram toujours actif
3. Dashboard complété (auth réparée + boutons manquants)  ← Telegram toujours actif
4. DOUBLE-RUN sur les 4 Pi                                ← les deux canaux en parallèle
5. Débranchement de Telegram (code, config, doc, .env)    ← point de non-retour
```

### 6.2 Le double-run (étape 4)

**Mécanisme.** Les étapes 1-3 sont livrées sous forme de **release candidate
`2.2.0-rc1`**, déployée **manuellement** sur les 4 Pi depuis le clone git
(jamais par tag : un tag `2.2.0` serait tiré automatiquement par les updaters à
03:00, cf. la leçon du grand renommage). Le tag n'est posé qu'à l'étape 5.

**Ce que le double-run doit prouver** (pas « laisser tourner et voir ») :

- toute notification partie sur Telegram est aussi partie sur Ntfy, **avec la
  bonne priorité** ;
- au moins **un incident réel ou simulé de chaque niveau** (INFO, WARNING,
  CRITICAL) a été reçu sur téléphone, **hors du domicile** ;
- au moins **une confirmation de reboot TP-Link réelle** validée par le bouton
  d'action, **depuis l'extérieur, en 4G**, et une autre **annulée** par le
  bouton « Annuler » ;
- au moins **une expiration de jeton** observée (bouton pressé après 120 s →
  404, aucun redémarrage).

**Durée recommandée : 7 jours pleins.** Justification : c'est la seule durée qui
garantit de traverser un rapport hebdomadaire, sept rapports quotidiens et le
créneau de l'updater. Sept jours, c'est aussi assez court pour ne pas s'installer
dans un état mixte. Cf. **Q4**.

**Coût du double-run** : Ntfy est plafonné à **250 messages/jour** sur
`ntfy.sh` gratuit ; 4 instances qui doublent leurs notifications restent très
loin du plafond en régime normal, mais une tempête d'incidents peut s'en
approcher. À surveiller.

> **Décision du 2026-08-23 (soir), Q4 — remplace ce paragraphe.** Pas de
> double-run, pas de fenêtre de 7 jours, pas de `2.2.0-rc1` maintenue en
> parallèle de Telegram sur les 4 Pi : **bascule sèche**. Le plafond
> `ntfy.sh` de 250 msg/jour évoqué ci-dessus ne s'applique plus non plus
> (serveur auto-hébergé, § 3.6 Q1). En compensation, une **vérification en
> réel renforcée** est exigée avant le sprint de débranchement (S5), et
> **avant** la suppression du code Telegram — reprise du principe « ne jamais
> débrancher le canal qui marche avant d'avoir prouvé que le nouveau marche »
> du § 6.1, sans la durée de 7 jours :
>
> - publication de **test sur chaque topic** (`vigil-dijon`, `vigil-nice`,
>   `vigil-ops`) **à chaque niveau** (INFO/WARNING/CRITICAL, avec la priorité
>   ntfy correspondante — § 3.2), **reçue et constatée** sur téléphone ;
> - **un test end-to-end d'un bouton de confirmation depuis le LAN** (pas
>   nécessairement en 4G/hors domicile, contrairement à l'ancienne exigence
>   double-run ci-dessus) : publication d'une action confirmable, réception
>   du bouton, tap, vérification que l'action s'exécute et que l'événement
>   `confirm_accepted` apparaît dans `/api/events` ;
> - le tout **journalisé et daté**, avant que le sprint de démantèlement ne
>   supprime `src/telegram_bot.py`.
>
> Cette checklist devient le **gate `verification-reelle-avant-debranchement`**
> de `progress.json`, bloquant avant le Sprint 5. Elle remplace les critères
> « Double-run (S4) » du § 10 en substance (la table de critères originale
> n'est pas réécrite — voir le sprint 5 pour la liste exacte des preuves
> exigées).

### 6.3 Les `.env` des 4 Pi

| Étape | Action sur les 4 `.env` |
|---|---|
| Avant l'étape 1 | **ajouter** `NTFY_URL`, `NTFY_TOPIC` (par site, cf. **Q2**), `NTFY_TOKEN`, `NTFY_MIN_LEVEL=INFO` ; vérifier que `API_TOKEN` est **non vide** ; ajouter la variable de nom Tailscale utilisée pour `Click`/`Actions` |
| Pendant le double-run | `TELEGRAM_*` **conservées** — c'est le rollback |
| Étape 5, après validation | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_TIMEOUT`, `TELEGRAM_MIN_LEVEL` **retirées** |
| J+7 après l'étape 5 | **révoquer le bot Telegram** auprès de `@BotFather` — un token de bot qui traîne dans un historique de shell reste valable indéfiniment |

Rappel : il n'existe **aucun `.env.example`** dans le dépôt (vérifié) ; la
référence de configuration est le tableau du `README.md` (L232-235 pour Ntfy) et
`DEPLOY.md` (L84-85). Ce sont ces deux endroits qu'il faut tenir à jour.

### 6.4 Comportement si Ntfy n'est pas configuré

Aujourd'hui, un canal non configuré est **silencieusement ignoré** par
`dispatch()`. Après la sortie de Telegram, un `NTFY_URL` vide signifie
**« Vigil ne prévient plus personne »** — et personne ne s'en aperçoit, puisque
l'absence d'alerte ressemble à l'absence de problème. C'est le mode de
défaillance le plus dangereux de tout ce PRD.

Garde-fous exigés (Sprint 1) :

1. **Au démarrage** : si **aucun** canal de notification n'est configuré →
   `logging.critical` explicite + événement `no_notification_channel` dans
   l'`EventLog`.
2. **`/health` et `/api/state`** exposent un champ `notification_channels`
   (liste des canaux configurés). Un tableau de bord vide se voit.
3. **`/metrics`** expose `vigil_notification_channels_configured` — une alerte
   Prometheus `== 0` est alors triviale à écrire.
4. **Ne pas** faire échouer le démarrage : la surveillance et le reboot
   automatique doivent continuer même sans canal. Une notification muette est
   grave ; un watchdog arrêté l'est davantage.

### 6.5 Rollback

| Étape atteinte | Rollback |
|---|---|
| 1-3 (rc déployée, Telegram actif) | Rien à défaire — Telegram fonctionne toujours. Au pire, vider `NTFY_URL`. |
| 4 (double-run) | Idem : c'est l'intérêt du double-run. |
| 5 (code Telegram supprimé, tag `v2.2.0` posé) | **Redéploiement du tag `v2.1.x`** + restauration des `TELEGRAM_*` dans les `.env`. Ce n'est plus une bascule de service : c'est un retour arrière de version. |
| Après révocation du bot BotFather | Irréversible — il faut créer un nouveau bot et refaire les 4 `.env`. **Ne pas révoquer avant J+7.** |

**Points de non-retour**, à inscrire dans `docs/RELEASE-NOTES-2.2.0.md` :
suppression du code Telegram (étape 5) et révocation du bot (J+7).

---

## 7. Versionnement — **2.2.0 (minor)**

- Aucune API Python publique n'est cassée ; le contrat HTTP n'est
  qu'**étendu** (un endpoint ajouté, aucun retiré).
- Mais **4 variables d'environnement disparaissent** et un canal de
  notification est supprimé : c'est un changement de configuration visible pour
  l'exploitant, qui justifie une minor et **pas** un patch.
- Ce n'est pas une major : le grand renommage a déjà consommé ce signal en
  2.0.0, et rien ici ne change de chemin, de nom de service ni de métrique.
- **Contrainte de séquencement** : `parse_version("2.2.0") > parse_version("2.1.x")`
  → dès que le tag existe, les updaters le tirent à 03:00. D'où la règle
  **« double-run sur rc non taguée, tag en dernier »** (§ 6.2).
- A2 est réaligné sur **2.3.0** (sa spec annonce encore `1.10.0`).

---

## 8. Découpage en sprints (5 — spécifications à extraire après validation)

> Les fichiers `sprints/NN-*.md`, `progress.json` et `INVARIANTS.md` **ne sont
> pas créés par ce PRD**. Ils seront extraits après réponse aux questions du
> § 11.

| # | Titre | Objectif (1 ligne) | Vérification |
|---|---|---|---|
| **S1** | Canal Ntfy enrichi + garde-fou « aucun canal » | Titre par instance, priorités 1-5, tags, `Click` dashboard, `Markdown` dégradable, troncature à 4 096 o, nouvelle variable `NTFY_TOKEN` (`Authorization: Bearer`), et détection au démarrage de l'absence totale de canal (log CRITICAL + événement + champ `notification_channels` dans `/health`, `/api/state`, `/metrics`) | Tests unitaires sur les en-têtes produits pour chaque `Level` ; envoi réel des 3 niveaux reçu sur téléphone ; `NTFY_TOKEN` vide → publication anonyme inchangée (rétrocompatible) ; démarrage sans aucun canal → log CRITICAL + événement présents |
| **S2** | Endpoint de confirmation à capacité + boutons d'action | `POST /api/confirm/<action>/<jeton>` exempté de `_check_auth()`, durcissements **D1-D7** (§ 4.2.3), et publication des boutons `Actions` ntfy (confirmer / annuler) par `managed_devices` via une fonction `send` injectée — **sans jamais `API_TOKEN`** | Test « aucun secret dans le payload » : publier une notification de chaque type et vérifier l'absence d'`API_TOKEN` dans corps et en-têtes ; jeton rejoué → 404 ; jeton expiré (>120 s) → 404 et **aucun** reboot ; mauvaise action dans l'URL → 404 ; N échecs → 429 ; jeton absent des logs `debug` ; `secrets.token_urlsafe(32)` vérifié ; test réel bouton depuis un téléphone en 4G via Tailscale |
| **S3** | Dashboard : réparer l'auth, combler les manques | Corriger `sendCommand()` (jeton saisi une fois, `sessionStorage`, en-tête `Authorization: Bearer`, message clair en 401) puis ajouter les boutons **DDNS**, **backup UniFi**, **sync Tailscale**, **maintenance**, et une **section TP-Link** (liste, statut, check, reboot + confirmation) | Chacune des 8 commandes du bot a un équivalent cliquable ; les 3 boutons existants fonctionnent avec `API_TOKEN` configuré (aujourd'hui : 403) ; test bout-en-bout du reboot TP-Link depuis le dashboard ; aucun jeton en `localStorage` |
| **S4** | Escalade, gabarits re-ciblés et double-run | Escalade en `Priority: 5` + tag `sos` + titre `[RELANCE]` **sans bouton** ; `messages.py` purgé du HTML Telegram et conforme au sous-ensemble Markdown ; déploiement manuel de `2.2.0-rc1` sur les 4 Pi et exécution du protocole du § 6.2 | Escalade simulée → reçue en priorité 5 sur ntfy **et** par email ; aucun gabarit hors sous-ensemble Markdown (test) ; aucun message > 4 096 o (test) ; journal de double-run rempli : 3 niveaux reçus hors domicile, 1 confirmation réelle en 4G, 1 annulation, 1 expiration |
| **S5** | Débranchement de Telegram et release 2.2.0 | Supprimer `src/telegram_bot.py`, `src/notifier/_telegram.py`, l'entrée `telegram` de `_get_channels()`, les 4 `TELEGRAM_*` de `config.py`, le branchement de `watchdog.py` (L76, L277-279), la couche Telegram de `managed_devices.py` (L357-364, L367-394, L397-408, `origin=` L531/L555), `tests/test_telegram_bot.py`, les occurrences de `deploy.sh`/`test.sh` et la doc (README 32, DEPLOY 13, CLAUDE 8, WORKFLOW 2) ; nettoyer les 4 `.env` ; `VERSION`=2.2.0 ; notes de version ; tag **en dernier** | `grep -riI telegram src/ tests/ scripts/ updater/ requirements.txt` = **0** (docs historiques exclues) ; `./scripts/validate.sh` vert, coverage ≥ 80 % ; les 4 `/health` annoncent `2.2.0` ; les 4 journaux montrent une publication ntfy réussie ; `docs/RELEASE-NOTES-2.2.0.md` présent |

**Dépendances** : S1 → S2 → S3 → S4 → S5. S3 est indépendant de S2 sur le plan
des fichiers (`dashboard.py` vs `http_server.py` + `managed_devices.py`) et
pourrait être parallélisé, **mais** il partage la convention d'authentification
avec S2 : les garder séquentiels. S5 dépend de tout, et surtout du **verdict du
double-run** de S4.

> **Décision du 2026-08-23 (soir)** : le tableau S1-S5 ci-dessus décrit
> l'intention initiale, non réécrite. Les spécifications de sprint réellement
> extraites (`2026-08-23_1500-ntfy-first-sortie-telegram/sprints/`)
> l'ajustent : **S4** remplace le déploiement `2.2.0-rc1` + protocole
> double-run par la checklist de vérification réelle du § 6.2 (encart Q4) ;
> **S5** démantèle Telegram **et** Pushover, Discord, Slack (§ 2.1 encart
> Q3), et son gate d'entrée n'est plus « verdict du double-run » mais
> « vérification réelle renforcée constatée » (gate
> `verification-reelle-avant-debranchement` de `progress.json`).

---

## 9. Ce qui ne change PAS (invariants)

1. **Le contrat de `notify()`** : `notify(message, level, context)`, never
   raises, filtrage par `MIN_LEVEL` par canal. Aucune signature publique du
   paquet `notifier` n'est modifiée.
2. ~~**Les 5 autres canaux** — Discord, Slack, Email SMTP, Pushover, MQTT — sont
   **conservés tels quels**, code et configuration. Aucun n'est supprimé par ce
   PRD (à confirmer, **Q3**).~~ **Invariant révisé par la décision du
   2026-08-23 (soir), Q3** : seuls **Email SMTP** et **MQTT** sont conservés
   tels quels. **Discord, Slack et Pushover sont supprimés par ce PRD**
   (§ 2.1 encart daté, § 8 S5 élargi) — l'hypothèse « à confirmer » du Q3
   original est tranchée par la négative pour ces trois canaux. MQTT en
   particulier n'est pas un canal d'alerte mais de la télémétrie Home
   Assistant : il ne relève pas de ce document, et il est le socle d'A2 en
   2.3.0.
3. **L'identité MQTT / Home Assistant** (`unique_id`, `device.name`,
   `client_id`, topics de discovery) — figée depuis la 1.8.2, **on n'y touche
   pas**.
4. **Le contrat HTTP existant** : aucun endpoint retiré ni renommé.
   `POST /api/confirm/<action>/<jeton>` est un **ajout**. `peer.py`
   (`GET /api/state`), Prometheus et l'updater (health check) ne voient aucune
   différence.
5. **La logique métier** : scoring, circuit breaker, détection de panne ISP,
   coordination HA, DDNS, backup, speedtest. Ce PRD change **la façon de
   prévenir et de commander**, pas ce qui est surveillé ni les décisions prises.
6. **`confirm.py`** conserve son contrat (`request_confirmation`, `validate`,
   `purge_expired`), son usage unique, son absence de persistance et son TTL par
   défaut. Seules l'**entropie** du jeton et la **comparaison** changent (D1, D2).
7. **Les métriques `vigil_*` existantes** : aucune renommée ni retirée ;
   `vigil_notification_channels_configured` est un ajout.
8. **L'historique documentaire** : `docs/adr/`, `docs/RELEASE-NOTES-1.8.*` et
   `2.0.0`, `docs/tasks/**` (y compris la spec A1 et son Sprint 3) ne sont pas
   réécrits.

---

## 10. Critères d'acceptation

**Sécurité (bloquants — aucun ne peut être marqué « fait » sans preuve)**

- [ ] Test automatisé : pour **chaque** type de notification produit par
      `messages.py`, le payload complet (corps **et** en-têtes, `Actions`
      inclus) ne contient **jamais** la valeur d'`API_TOKEN`
- [ ] Le jeton de `confirm.py` fait ≥ 256 bits (`secrets.token_urlsafe(32)`) —
      vérifié par test sur la longueur et l'alphabet
- [ ] Jeton rejoué → `404` **et** aucune action exécutée (test)
- [ ] Jeton expiré (> `CONFIRM_TTL`) → `404` **et** aucune action exécutée (test)
- [ ] Jeton valide présenté sur une **autre** action dans l'URL → `404` (test)
- [ ] `hmac.compare_digest` utilisé pour la comparaison d'action **et** pour
      `_check_auth()` (`API_TOKEN`)
- [ ] Rate limiting actif sur `/api/confirm/*` : au-delà de N échecs/min/IP →
      `429` + événement `confirm_bruteforce` (test)
- [ ] Aucun jeton en clair dans les journaux, y compris en `LOG_LEVEL=DEBUG`
      (test sur `log_message`)
- [ ] `/api/confirm/*` est le **seul** endpoint POST exempté de `_check_auth()`
      (vérifié par revue + test d'inventaire des routes)
- [ ] Toutes les URL d'action publiées pointent sur un nom/adresse **Tailscale**
      — aucune IP LAN, aucune IP publique (test sur la chaîne produite)

**Fonctionnel**

- [ ] Les 3 niveaux (INFO / WARNING / CRITICAL) produisent respectivement
      `Priority: 3 / 4 / 5`, les bons tags et un `Title` contenant
      l'`INSTANCE_ID` (test)
- [ ] Rapports quotidien/hebdomadaire en `Priority: 2`, tronqués sous 4 096
      octets, avec `Click` vers le rapport complet (test)
- [ ] `NTFY_TOKEN` renseigné → en-tête `Authorization: Bearer` présent ;
      absent → publication anonyme, comportement 2.1.0 inchangé (test)
- [ ] Les 8 commandes du bot ont un équivalent : tableau du § 4.5 entièrement
      en « ✅ » (endpoint **et** bouton dashboard)
- [ ] Les 3 boutons existants du dashboard fonctionnent avec `API_TOKEN`
      configuré (régression corrigée), le jeton n'est **pas** en `localStorage`
- [ ] Démarrage sans aucun canal configuré → log `CRITICAL`, événement
      `no_notification_channel`, `notification_channels: []` dans `/health` et
      `/api/state`, `vigil_notification_channels_configured 0` dans `/metrics`,
      **et le watchdog continue de surveiller**
- [ ] Escalade : `Priority: 5`, tag `sos`, titre `[RELANCE]`, **aucun bouton
      d'action**, reçue aussi par email

**Double-run (S4) — journal de bord daté, pas une impression**

- [ ] ≥ 7 jours de fonctionnement en `2.2.0-rc1` sur les **4** Pi
- [ ] Au moins 1 notification de chaque niveau reçue **hors du domicile**
- [ ] Au moins 1 confirmation de reboot TP-Link réussie **depuis l'extérieur en
      4G** via le bouton d'action
- [ ] Au moins 1 annulation par le bouton « Annuler » et 1 expiration observée
- [ ] **Taux d'échec des boutons d'action < 1 sur 10** — au-delà, le plan B du
      § 4.4 (abonné ntfy limité aux confirmations) est déclenché **avant** S5
- [ ] Aucune notification partie sur Telegram sans équivalent Ntfy

**Débranchement (S5)**

- [ ] `grep -riI telegram src/ tests/ scripts/ updater/ requirements.txt` = 0
- [ ] `src/telegram_bot.py` et `src/notifier/_telegram.py` supprimés ; aucune
      des 4 variables `TELEGRAM_*` dans `config.py`
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] Les 4 `.env` de production sans `TELEGRAM_*` ; les 4 `/health` = `2.2.0` ;
      publication ntfy réussie visible dans les 4 journaux
- [ ] `docs/RELEASE-NOTES-2.2.0.md` : retrait du canal et du bot, variables
      supprimées, variables ajoutées (`NTFY_TOKEN`), prérequis Tailscale,
      points de non-retour, rappel « révoquer le bot BotFather à J+7 »
- [ ] `README.md`, `DEPLOY.md`, `CLAUDE.md`, `WORKFLOW.md` à jour ; docs
      historiques **non modifiées**
- [ ] `VERSION` = 2.2.0, tag `v2.2.0` poussé **après** validation des 4 Pi,
      `dev` resynchronisée

---

## 11. Risques

### Top 3

1. **Perte d'alerte silencieuse** *(probabilité moyenne, impact critique)* —
   Ntfy mal configuré, topic non souscrit sur le téléphone, application tuée par
   l'optimisation de batterie Android, jeton d'accès expiré, plafond de 250
   msg/jour atteint. Telegram était le canal fiable **de fait** ; on le remplace
   par un canal dont personne n'a encore éprouvé la fiabilité sur cette flotte.
   **Une alerte qui n'arrive pas ne se remarque pas** — c'est la définition d'une
   panne silencieuse, et un watchdog muet est pire qu'un watchdog absent (il
   inspire une confiance qu'il ne mérite plus).
   *Mitigations* : double-run de 7 jours avec preuves datées (§ 6.2) ; garde-fou
   « aucun canal configuré » (§ 6.4) ; email SMTP conservé en second canal ;
   `vigil_notification_channels_configured` en métrique.

2. **Compromission de la surface de commande** *(probabilité faible, impact
   critique)* — un `API_TOKEN` dans un bouton d'action, ou un endpoint de
   confirmation trop permissif, donne à un tiers le pouvoir de redémarrer le
   routeur, de mettre la surveillance en pause ou de recharger la configuration.
   Aggravé par le contexte existant : bind `0.0.0.0`, aucun TLS, aucun rate
   limiting, GET quasi tous publics.
   *Mitigations* : interdiction absolue d'`API_TOKEN` dans une notification
   (invariant testé) ; URL de capacité à usage unique, 120 s, liée à une action
   (§ 4.2.2) ; D1-D7 ; URL d'action **Tailscale uniquement**, donc inexploitable
   hors du tailnet même si le message fuite.

3. **Perte de la capacité d'agir à distance pendant un incident** *(probabilité
   moyenne, impact élevé)* — c'est le risque **spécifique** à ce changement, et
   le moins intuitif. Telegram commandait le Pi **sans flux entrant** ; le bouton
   Ntfy exige que le téléphone joigne le Pi, précisément quand le réseau est
   dégradé. Si Tailscale est absent du téléphone, endormi, ou lent à établir un
   relais DERP, la confirmation de reboot expire au bout de 120 s et **le
   redémarrage n'a pas lieu**.
   *Mitigations* : prérequis Tailscale vérifié **avant** S2 (Pi **et**
   téléphones) ; critère de double-run explicite (< 1 échec sur 10) ; plan B
   écrit d'avance (§ 4.4) ; comportement sûr en cas d'expiration — **aucune
   action** par défaut (cf. **Q5**).

### Autres risques

4. **Régression de confort** — passer de « `/status` en trois secondes dans un
   chat » à « ouvrir le dashboard » peut être vécu comme un recul si la PWA
   n'est pas installée sur l'écran d'accueil. *Mitigation* : `Click` sur chaque
   notification (§ 3.3) + installation de la PWA pendant le double-run.
5. **Le dashboard est aujourd'hui cassé sur l'authentification** (§ 4.5) — la
   surface de repli n'existe pas encore réellement. *Mitigation* : S3 est un
   prérequis bloquant de S5, pas une amélioration.
6. **Faux message publié sur le topic** — sans authentification en écriture,
   un tiers peut fabriquer une notification crédible avec un bouton malveillant.
   *Mitigation* : `NTFY_TOKEN` + topic à accès restreint, obligatoires (§ 3.6).
7. **Dépendance à un service tiers unique** — après la sortie de Telegram, si
   Ntfy est indisponible, il ne reste que l'email. *Mitigation* : conserver au
   moins un second canal réellement configuré (**Q3**).

---

## 12. Questions ouvertes (à trancher avant extraction des sprints)

**Q1 — Quel serveur Ntfy, et avec quelle authentification ?**
Trois options : (a) `ntfy.sh` gratuit + topic au nom imprévisible,
(b) `ntfy.sh` payant + **topic réservé** + jeton d'accès, (c) **self-hosted sur
un VPS tiers** avec `auth-default-access: deny-all`.
*Recommandation : (b) ou (c).* (a) est à écarter dès lors qu'on publie des
boutons d'action : un topic simplement « secret » est lisible et **inscriptible**
par quiconque en devine le nom. Entre (b) et (c) : (c) donne la maîtrise
complète des données (les URL de capacité ne quittent pas votre infrastructure) ;
(b) coûte moins de maintenance et débloque l'action `Call` pour l'escalade
(§ 5.3). **Dans tous les cas : jamais sur un Pi d'un des deux sites surveillés.**
Question complémentaire : as-tu déjà un serveur ntfy ou un VPS disponible ?

**Q2 — Topics : par site, par instance, ou unique ?**
*Recommandation : par site* (`vigil-dijon`, `vigil-nice`), l'`INSTANCE_ID`
étant porté par le `Title` et les tags. C'est le découpage qui correspond à une
unité de décision réelle, et il n'exige **aucun code** — seulement 4 `.env`.
Cf. § 3.5 pour la comparaison des trois options.

**Q3 — Que fait-on des 5 autres canaux (Discord, Slack, Email, Pushover, MQTT) ?**
Ce PRD les conserve **tous** par défaut. Mais après la sortie de Telegram, la
question devient concrète : lesquels sont **réellement configurés et lus** sur
les 4 Pi aujourd'hui ? Un canal configuré mais jamais consulté donne une fausse
impression de redondance.
*Recommandation :* garder **Ntfy (principal) + Email SMTP (secours réel,
`SMTP_MIN_LEVEL=WARNING`) + MQTT (télémétrie HA, socle d'A2)** et **vérifier**
si Discord, Slack et Pushover sont branchés quelque part. S'ils ne le sont pas,
leur suppression est un PRD distinct — pas celui-ci.

**Q4 — Durée du double-run et mécanisme de déploiement ?**
*Recommandation : 7 jours pleins*, sur une `2.2.0-rc1` déployée **manuellement**
depuis le clone git, **sans tag** (un tag serait tiré automatiquement par les
updaters à 03:00). Acceptes-tu ces 7 jours en état mixte, et le déploiement
manuel sur les 4 Pi ?

**Q5 — Que se passe-t-il si une confirmation n'arrive jamais ?**
Aujourd'hui : le jeton expire au bout de 120 s et **rien n'est exécuté**. C'est
le comportement sûr, et ce PRD le conserve. Mais dans le contexte d'A1, cela
signifie qu'**un TP-Link ne redémarre pas** si tu n'as pas ton téléphone sous la
main. Veux-tu (a) garder ce comportement, (b) allonger le TTL des confirmations
envoyées par notification (p. ex. 15 min, sachant que la fenêtre d'exploitation
d'un jeton fuité s'allonge d'autant), ou (c) prévoir un mode « auto-confirmation
après N minutes » pour certaines actions jugées peu risquées ?
*Recommandation : (a), plus éventuellement (b) à 600 s pour la seule action
`tplink_reboot`* — 120 s est une fenêtre très courte pour une notification
mobile qui doit d'abord réveiller le téléphone.

**Q6 — Markdown : on accepte le texte brut structuré ?**
`Markdown: yes` n'est rendu **que par l'application web** ntfy, pas
uniformément sur mobile. *Recommandation : oui, mais dégradable* — on
s'autorise `**gras**`, listes et code court, on s'interdit tableaux et liens
`[texte](url)`. Confirmes-tu ce compromis, ou préfères-tu du **texte brut
strict** (plus prévisible, moins joli) ?

**Q7 — Tailscale est-il installé sur les téléphones qui reçoivent les alertes ?**
C'est le **prérequis dur** du § 4.1 : sans lui, aucun bouton d'action ne
fonctionne hors du domicile, et le risque n°3 se réalise. À vérifier avant
d'extraire le Sprint 2. Si la réponse est non et que tu ne veux pas l'installer,
le design change complètement — il faudra alors reconsidérer le plan B du
§ 4.4 (abonné ntfy sortant) comme solution principale, et non de repli.
