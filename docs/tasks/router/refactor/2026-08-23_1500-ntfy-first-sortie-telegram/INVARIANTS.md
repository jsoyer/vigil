# INVARIANTS — Ntfy-first, sortie de Telegram (2.2.0)

Contrats transverses vérifiables machine. Un sprint qui viole un invariant est
en échec, quel que soit l'état de ses propres tests. Contexte : **4 instances
de production**, un point de non-retour au sprint 5 (suppression de code +
tag `v2.2.0`), et une surface de commande qui devient joignable par un bouton
d'action *entrant* pour la première fois du projet — la plupart de ces
invariants existent pour éviter qu'un secret système (`API_TOKEN`) ou qu'un
jeton de confirmation ne fuite via un canal de notification à durée de vie
longue (cf. PRD § 4.2.1).

---

## Aucun `API_TOKEN` dans une notification, quel que soit le canal

- **Owner** : `src/notifier/_ntfy.py`, `src/managed_devices.py`
- **Preconditions** : `API_TOKEN` ouvre `POST /api/reboot`, `/api/pause`,
  `/api/config/reload`, `/api/tplink/*` — ce n'est pas un secret de
  notification, c'est la clé du système (PRD § 4.2.1).
- **Postconditions** : aucun payload de notification (corps **et** en-têtes,
  `Actions` ntfy inclus) ne contient jamais la valeur d'`API_TOKEN`, dans
  aucun des sprints 1 à 5.
- **Invariants** : un bouton d'action ntfy s'authentifie exclusivement par le
  jeton `confirm.py` (URL de capacité), jamais par un en-tête
  `Authorization` porté dans `Actions`.
- **Verify** : `grep -rn "headers.Authorization\|Bearer.*API_TOKEN" src/notifier/_ntfy.py src/managed_devices.py src/messages.py | wc -l` doit valoir `0` ; test dédié qui publie une notification de chaque type (INFO/WARNING/CRITICAL/escalade/confirmation) et `grep -i` le payload complet à la recherche de la valeur d'`API_TOKEN` configurée dans l'environnement de test.
- **Fix** : si une occurrence apparaît, la retirer immédiatement — ce n'est
  jamais un détail, c'est le risque n°2 du PRD (§ 11).

## Le jeton de confirmation n'est jamais journalisé en clair

- **Owner** : `src/http_server.py` (`log_message`), `src/confirm.py`
- **Preconditions** : `log_message()` journalise la requête complète en
  `logging.debug`, y compris le chemin de l'URL — donc le jeton s'il n'est
  pas masqué.
- **Postconditions** : toute requête vers `/api/confirm/<action>/<jeton>` est
  journalisée avec le jeton remplacé par `***`, y compris en
  `LOG_LEVEL=DEBUG`.
- **Invariants** : c'est le durcissement D4 du PRD (§ 4.2.3) — sans lui, un
  jeton à 256 bits perd tout son intérêt dès qu'il transite par un fichier de
  log avec une rétention plus longue que son TTL.
- **Verify** : test sur `log_message` qui appelle la méthode avec un chemin
  `/api/confirm/tplink_reboot/<jeton-de-test>` et vérifie que le jeton
  n'apparaît **pas** dans la sortie capturée (seul `***` apparaît).
- **Fix** : ajouter le masquage dans `log_message`, jamais dans l'appelant.

## `/api/confirm/*` n'est jamais exposé via Cloudflare — revue manuelle

- **Owner** : opérateur (infrastructure bbh-network, hors dépôt), décision
  Q7 du 2026-08-23 (soir)
- **Preconditions** : le tunnel Cloudflare `https://ntfy.bbhome.wf` sert déjà
  l'abonnement ntfy des téléphones (Q1). Il ne sert **jamais** de route vers
  un des 4 Pi Vigil.
- **Postconditions** : aucune règle de tunnel Cloudflare, aucun reverse
  proxy, aucune redirection de port ne fait pointer une URL publique vers
  `POST /api/confirm/*` sur un des 4 Pi. Toutes les URL d'action publiées
  dans les boutons `Actions` ntfy utilisent un nom ou une IP Tailscale
  (`100.x.y.z` ou nom MagicDNS), jamais une IP LAN ni une IP publique.
- **Invariants** : ce n'est **pas automatiquement vérifiable depuis le
  dépôt** — c'est une propriété de la configuration Cloudflare/bbh-network,
  hors du code Vigil. D'où « revue manuelle », pas un `grep`.
- **Verify** : (a) automatisable — `grep -rn "http://" src/managed_devices.py src/http_server.py | grep -v "100\.\|tailscale\|localhost\|127\.0\.0\.1"` ne doit renvoyer que des faux positifs documentés (aucune IP publique ou LAN en dur dans les URL d'action) ; (b) manuel — revue de la configuration du tunnel Cloudflare de bbh-network (hors dépôt) avant chaque sprint touchant § 4, consignée dans le journal de vérification réelle (sprint 5).
- **Fix** : si une règle de tunnel expose `/api/confirm/*`, la retirer
  immédiatement et considérer tout jeton émis depuis comme compromis
  (purge + rotation `CONFIRM_TTL`).

## Les 8 commandes Telegram restent intactes jusqu'au sprint de débranchement

- **Owner** : `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/managed_devices.py` (couche `/lte`)
- **Preconditions** : le PRD § 6.1 pose un principe non négociable —
  « on ne débranche jamais le canal qui marche avant d'avoir prouvé que le
  nouveau marche ». La décision Q4 (bascule sèche, pas de double-run de
  7 jours) ne change **pas** ce principe, elle change seulement le mécanisme
  de preuve (§ 6.2 encart daté).
- **Postconditions** : pendant les sprints 1 à 4, les 8 commandes du bot
  (`/status`, `/pause`, `/resume`, `/reboot`, `/ddns`, `/backup`,
  `/tailscale`, `/help`) plus `/lte` restent fonctionnelles et inchangées.
  Aucun de ces 4 sprints ne touche `src/telegram_bot.py` ni
  `src/notifier/_telegram.py`.
- **Invariants** : Telegram n'est débranché qu'au sprint 5, et seulement
  après que le gate `verification-reelle-avant-debranchement` de
  `progress.json` est satisfait.
- **Verify** : `git diff --stat main -- src/telegram_bot.py src/notifier/_telegram.py` doit être vide pour tout sprint 1 à 4 (identifiable par sa branche/worktree) ; sur le sprint 5, doit montrer une suppression complète des deux fichiers.
- **Fix** : si un sprint antérieur au 5 touche ces fichiers, sortir le
  changement — ce n'est pas son périmètre.

## Après débranchement (sprint 5) : zéro résidu Telegram/Pushover/Discord/Slack

- **Owner** : sprint 5 (`sprints/05-verification-debranchement-release.md`)
- **Preconditions** : décision Q3 du 2026-08-23 (soir) élargit le
  démantèlement à Pushover, Discord et Slack, en plus de Telegram (PRD § 2.1
  encart daté, § 9 point 2 révisé).
- **Postconditions** : à la fin du sprint 5, aucune trace de code applicatif
  de ces 4 canaux ne subsiste dans le dépôt, hors documentation historique
  (`docs/adr/`, `docs/RELEASE-NOTES-1.8.*`, `docs/RELEASE-NOTES-2.0.0.md`,
  `docs/tasks/**`).
- **Invariants** : seuls **Ntfy**, **Email SMTP** et **MQTT** restent comme
  canaux de notification actifs après ce PRD.
- **Verify** : `grep -riI "telegram\|pushover\|discord\|slack" src/ tests/ scripts/ updater/ requirements.txt | wc -l` doit valoir `0`
- **Fix** : tout résidu trouvé après le sprint 5 est un défaut de
  démantèlement — le retirer, ne pas le documenter comme exception.

## `CONFIRM_TTL` par défaut est 600s, pas 120s (décision Q5)

- **Owner** : `src/confirm.py`
- **Preconditions** : le jeton de confirmation, historiquement tapé par un
  humain dans un chat Telegram authentifié (TTL 120s suffisant), devient une
  URL de capacité cliquée depuis une notification mobile qui doit d'abord
  réveiller le téléphone — 120s est jugé trop court (PRD § 12 Q5, décision
  § 0bis).
- **Postconditions** : `DEFAULT_TTL_SECONDS` dans `src/confirm.py` vaut
  `600.0` à partir du sprint 2. `_get_ttl_seconds()` retombe sur cette
  valeur quand `CONFIRM_TTL` n'est pas positionné dans l'environnement.
- **Invariants** : tout test ou message qui assume encore un TTL de 120s
  après le sprint 2 (ex. section "expiration" du sprint 4) doit être mis à
  jour pour refléter 600s — un test qui vérifie une expiration à 120s alors
  que le défaut est 600s donnerait un faux négatif de sécurité (le jeton
  n'aurait pas encore expiré).
- **Verify** : `grep -n "DEFAULT_TTL_SECONDS" src/confirm.py` doit montrer `600.0` (ou toute valeur strictement supérieure si une décision ultérieure le modifie à nouveau — jamais un retour silencieux à 120.0) ; `python3 -m pytest tests/test_confirm.py -k ttl -q` vert.
- **Fix** : si `DEFAULT_TTL_SECONDS` repasse à `120.0` sans décision
  utilisateur documentée, c'est une régression — revert.

## Le tag `v2.2.0` n'est posé qu'après la vérification réelle renforcée

- **Owner** : opérateur (sprint 5), `VERSION`
- **Preconditions** : décision Q4 du 2026-08-23 (soir) remplace le
  double-run de 7 jours par une checklist resserrée (PRD § 6.2 encart daté) :
  publication de test reçue sur chaque topic à chaque niveau, **et** un test
  end-to-end d'un bouton de confirmation depuis le LAN.
- **Postconditions** : le tag `v2.2.0` n'est poussé qu'après que ce journal
  daté est rempli **et** que Telegram/Pushover/Discord/Slack ont été
  effectivement retirés des 4 `.env` de production.
- **Invariants** : `parse_version("2.2.0") > parse_version("2.1.x")` — dès
  que le tag existe, les updaters le tirent à 03:00 (même mécanisme de
  risque que le grand renommage). Poser le tag avant la vérification réelle
  bascule silencieusement les 4 Pi sur un canal de notification jamais
  éprouvé en conditions réelles — c'est le risque n°1 du PRD (§ 11), le plus
  grave.
- **Verify** : `git tag -l 'v2.2.0' | wc -l` doit valoir `0` tant que le gate `verification-reelle-avant-debranchement` de `progress.json` n'est pas `satisfied: true` (vérification manuelle, consignée dans le sprint 5, pas automatisable depuis le poste de dev seul)
- **Fix** : si le tag existe sans que le journal de vérification réelle soit
  rempli, ne **pas** propager sur les Pi restants — investiguer et
  documenter l'incident avant de continuer la migration.

## Le contrat de `confirm.py` (hors TTL) ne change pas

- **Owner** : `src/confirm.py`
- **Preconditions** : `request_confirmation(action, context, ttl) -> str`,
  `validate(token, action) -> dict | None`, `purge_expired() -> int` sont
  déjà agnostiques du canal (PRD § 2.2).
- **Postconditions** : ces trois signatures ne changent pas. Seuls
  l'entropie du jeton (D1 : `token_hex(4)` → `token_urlsafe(32)`), la
  comparaison de l'action (D2 : `hmac.compare_digest`) et le TTL par défaut
  (Q5 : 120 → 600) évoluent.
- **Invariants** : usage unique (`pop` inconditionnel), absence de
  persistance disque, verrou global — inchangés.
- **Verify** : `python3 -m pytest tests/test_confirm.py -q` vert après
  chaque sprint qui touche `src/confirm.py` (sprints 2 et 4).
- **Fix** : si une signature publique de `confirm.py` change, c'est hors
  périmètre — revert et documenter séparément.
