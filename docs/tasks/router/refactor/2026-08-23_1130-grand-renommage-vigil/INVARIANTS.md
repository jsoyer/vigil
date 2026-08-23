# INVARIANTS — Grand renommage Vigil (2.0.0)

Contrats transverses vérifiables machine. Un sprint qui viole un invariant est
en échec, quel que soit l'état de ses propres tests. Contexte : **4 instances
de production** (Dijon master+slave, Nice master+slave) qui se mettent à jour
**automatiquement** depuis `main` — la plupart de ces invariants existent parce
qu'une violation se traduirait par une panne silencieuse sur ces 4 instances,
potentiellement sans humain dans la boucle avant 03:00.

---

## L'identité MQTT / Home Assistant ne bouge pas

- **Owner** : `src/mqtt_publisher.py`
- **Preconditions** : la 1.8.2 a déjà posé `device.identifiers` `vigil_{instance}`,
  `device.name` « Vigil {instance} », `unique_id` `vigil_{instance}_{sensor}`,
  `client_id` `vigil-{instance}`, topics `homeassistant/sensor/vigil_{instance}/…`.
- **Postconditions** : ce PRD ne touche **ni le fichier ni les valeurs**. Les
  `unique_id` HA sont immuables ; la purge des entités orphelines a déjà été
  payée une fois en 1.8.1/1.8.2, elle ne se repaie pas ici.
- **Invariants** : `src/mqtt_publisher.py` et `tests/test_mqtt_publisher.py`
  ont un diff vide sur tout le PRD.
- **Verify** : `git diff --stat main -- src/mqtt_publisher.py tests/test_mqtt_publisher.py | wc -l` doit valoir `0`
- **Fix** : si un sprint touche ce fichier, c'est hors périmètre — retirer le
  changement, pas l'adapter.

## Le routeur Ubiquiti reste « usg »

- **Owner** : `src/usg.py`, `src/config.py` (variables `USG_*`), `src/messages.py`
- **Preconditions** : le renommage concerne le **produit** (le logiciel de
  surveillance), pas la **cible** (le routeur Ubiquiti USG).
- **Postconditions** : `src/usg.py`, `reboot_usg()`, `test_ssh_connection()`,
  les variables d'environnement `USG_IP`, `USG_USER`, `USG_SSH_KEY`,
  `USG_SSH_PASSWORD`, `USG_KNOWN_HOSTS`, `USG_REBOOT_COMMAND`,
  `USG_REBOOT_WAIT`, le nom de fichier de clé `usg_ed25519` et son
  `known_hosts`, ainsi que les messages qui nomment le routeur (« Gateway
  USG », « redémarrage du routeur USG ») restent inchangés dans leur
  vocabulaire.
- **Invariants** : aucun sprint ne renomme une variable, un fichier ou un
  libellé qui désigne le matériel Ubiquiti. Seul le **répertoire parent**
  (`/opt/vigil/.ssh/usg_ed25519` au lieu de `/opt/usg-watchdog/.ssh/usg_ed25519`)
  change — jamais le nom du fichier lui-même.
- **Verify** : `grep -rn 'USG_IP\|USG_USER\|USG_SSH_KEY\|USG_SSH_PASSWORD\|USG_KNOWN_HOSTS\|USG_REBOOT_COMMAND\|USG_REBOOT_WAIT' src/config.py | wc -l` doit rester égal au décompte d'avant le PRD (8 occurrences au 2026-08-23) ; `basename $(grep -o '/opt/[a-z-]*/.ssh/[a-z0-9_]*' src/config.py | tail -1)` doit valoir `usg_ed25519`
- **Fix** : si un sprint a renommé une variable `USG_*` ou le fichier de clé,
  revert — c'est une violation de la frontière § 3 du PRD, pas un détail.

## Jamais de recréation d'un dépôt `usg-watchdog`

- **Owner** : opérateur (hors code), consigné dans `docs/RELEASE-NOTES-2.0.0.md`
- **Preconditions** : GitHub redirige `jsoyer/usg-watchdog` → `jsoyer/vigil`
  (API REST, tarballs, remotes git) tant qu'aucun nouveau dépôt ne réutilise le
  nom `usg-watchdog` sous le compte `jsoyer`.
- **Postconditions** : la redirection reste active pendant toute la fenêtre de
  migration progressive de la flotte (§ 5 du PRD) et au-delà.
- **Invariants** : recréer un dépôt `jsoyer/usg-watchdog` **annule
  instantanément** la redirection et casse tout updater non encore migré — un
  point de non-retour explicite du PRD (§ 8). Aucun sprint, aucun test, aucun
  script de ce PRD ne doit créer un tel dépôt, même temporairement (ex. test
  d'intégration `gh repo create`).
- **Verify** : `gh repo view jsoyer/usg-watchdog --json url 2>&1 | grep -qi 'vigil\|not found' && echo OK` (doit confirmer la redirection ou l'absence d'un dépôt concurrent, jamais un dépôt `usg-watchdog` actif indépendant)
- **Fix** : si un dépôt `jsoyer/usg-watchdog` existe et n'est pas la redirection
  GitHub automatique, le supprimer immédiatement et documenter l'incident.

## Le tag v2.0.0 n'est posé qu'après la migration des 4 Pi

- **Owner** : opérateur (sprint 5, runbook), `VERSION`
- **Preconditions** : `parse_version("2.0.0") > parse_version("1.8.3")` — dès
  que le tag `v2.0.0` existe sur `main`, **tout updater non migré** (encore sur
  l'ancien nom, l'ancien chemin, l'ancien unit) le tirera à la prochaine
  fenêtre 03:00 ± 10 min.
- **Postconditions** : le tag `v2.0.0` n'est poussé qu'après que les 4 Pi
  (bbh-dij-guardian, bbh-nce-guardian, bbh-network, penelope) ont individuellement
  validé `/health` = `2.0.0` sous `vigil.service`.
- **Invariants** : c'est le risque n°1 du PRD (§ 8), le plus grave — un tag
  pushé trop tôt provoque une boucle de redémarrage sur un Pi non préparé,
  potentiellement de nuit, sans humain dans la boucle. Combiné au gel des
  timers (invariant suivant), c'est la double mitigation qui rend la migration
  progressive sûre.
- **Verify** : `git tag -l 'v2.0.0' | wc -l` doit valoir `0` tant que les 4
  Pi n'ont pas confirmé `/health` = `2.0.0` (vérification manuelle consignée
  dans le runbook § 5.3, pas automatisable depuis le poste de dev seul)
- **Fix** : si le tag existe et qu'un Pi n'est pas encore migré, geler
  immédiatement son timer updater (`systemctl disable --now
  usg-watchdog-updater.timer`) avant qu'il n'atteigne 03:00.

## Les timers updater sont gelés pendant toute la fenêtre de migration

- **Owner** : opérateur (sprint 5, runbook §§ 1 et 8 par Pi)
- **Preconditions** : la migration flotte dure plusieurs heures (4 Pi, ~10 min
  chacun + 30 min d'observation entre les deux Pi d'un même site).
- **Postconditions** : `usg-watchdog-updater.timer` est désactivé sur **les 4
  Pi** avant la première bascule (étape 1 du runbook, premier Pi) ; chaque Pi
  migré réactive son timer sous le nom `vigil-updater.timer` **seulement** une
  fois ses propres vérifications validées (étape 8) — pas avant, et pas les
  4 en bloc à la fin.
- **Invariants** : un timer actif sur un Pi non encore migré pendant la
  fenêtre peut tirer une release intermédiaire ou, pire, la 2.0.0 elle-même
  dès que le tag existe (cf. invariant précédent) — combinaison qui matérialise
  le risque n°1 du PRD.
- **Verify** : pendant la fenêtre de migration, sur un Pi pas encore validé :
  `ssh <pi> systemctl is-enabled usg-watchdog-updater.timer` doit renvoyer
  `disabled` (jamais `enabled`) ; sur un Pi validé : `ssh <pi> systemctl
  is-enabled vigil-updater.timer` doit renvoyer `enabled`
- **Fix** : `systemctl disable --now usg-watchdog-updater.timer` immédiatement
  sur tout Pi où il tourne encore pendant la fenêtre.

## Aucune variable d'environnement existante renommée ou supprimée

- **Owner** : `src/config.py`
- **Preconditions** : les `.env` de production des 4 Pi ne sont **pas**
  réédités par ce PRD au-delà des ajouts explicites du § 5.1 (`LOG_FILE`,
  `USG_SSH_KEY`, `USG_KNOWN_HOSTS` épinglés).
- **Postconditions** : la liste des clés `os.getenv`/`_get_env` de
  `src/config.py` après le PRD est un **sur-ensemble** strict de la liste
  avant — aucune clé retirée, aucune renommée.
- **Invariants** : un `.env` de production doit rester valide **tel quel**
  après migration (invariant n°4 du PRD § 4).
- **Verify** : `git diff main -- src/config.py | grep -E '^-.*getenv\(' | grep -v '^-#'` doit être vide (aucune ligne `getenv(...)` supprimée sans être remplacée par une ligne équivalente)
- **Fix** : restaurer la clé retirée ; si un renommage semblait nécessaire,
  ajouter la nouvelle clé en plus, jamais à la place.

## Le repli de chemin protège un déploiement partiellement migré

- **Owner** : `src/config.py`
- **Preconditions** : entre le merge de S3 et la validation du dernier Pi
  (S5), un service 2.0.0 peut démarrer sur une machine où seul
  `/opt/usg-watchdog` existe encore.
- **Postconditions** : si `/opt/vigil` est absent et `/opt/usg-watchdog`
  présent, les chemins par défaut (`.ssh`, `LOG_FILE`, fichier d'événements,
  `.env` lu par `http_server.py`) retombent sur l'ancien emplacement — le
  service démarre au lieu de tomber en boucle de redémarrage.
- **Invariants** : c'est le filet de sécurité qui rend le risque n°1 du § 8
  tolérable même en cas d'erreur d'ordonnancement. Il est **temporaire** —
  retrait prévu en 2.1.0, pas dans ce PRD.
- **Verify** : `python3 -m pytest tests/test_path_fallback.py -q`
- **Fix** : compléter le repli dans `config.py`, jamais dans un appelant.

## `MQTT_TOPIC_PREFIX` par défaut change, jamais les `.env` de production

- **Owner** : `src/config.py`
- **Preconditions** : le défaut passe de `usg-watchdog` à `vigil` ; les 4
  instances de production portent déjà un préfixe **explicite**
  `vigil/<site>-<role>` depuis la 1.8.2 — le changement de défaut ne les
  affecte donc pas.
- **Postconditions** : `grep MQTT_TOPIC_PREFIX /opt/usg-watchdog/.env` sur les
  4 Pi confirme un préfixe explicite avant toute bascule (gate
  `env-mqtt-prefix-audit` de `progress.json`).
- **Invariants** : un déploiement tiers qui aurait laissé le défaut verrait ses
  topics changer de racine et ses entités HA passer en `unavailable` — c'est
  documenté comme breaking dans les notes de version, pas silencieusement
  corrigé.
- **Verify** : `for h in bbh-network bbh-dij-guardian penelope bbh-nce-guardian; do echo $h; ssh $h grep MQTT_TOPIC_PREFIX /opt/usg-watchdog/.env; done` — chaque ligne doit montrer une valeur explicite `vigil/...`, jamais une absence de la clé
- **Fix** : ajouter la clé explicitement dans le `.env` concerné avant de
  poursuivre la migration de ce Pi.

## Bascule sèche des métriques : aucune double émission (décision Q2, 2026-08-23)

- **Owner** : `src/metrics.py`
- **Preconditions** : le PRD envisageait initialement une double émission
  (`vigil_*` + `usg_watchdog_*` déprécié) ; l'utilisateur a tranché pour une
  bascule sèche le 2026-08-23 (§ 0bis du PRD).
- **Postconditions** : `/metrics` expose les 19 séries `vigil_*` et
  **aucune** série `usg_watchdog_*`, dès le merge du sprint 4 — pas de
  fenêtre de coexistence, pas de retrait différé en 2.1.0.
- **Invariants** : un sprint qui réintroduirait une logique de double émission
  ou un commentaire `DEPRECATED` sur une métrique irait à l'encontre d'une
  décision utilisateur explicite et daterait le sprint sur une version
  obsolète du PRD.
- **Verify** : `curl -s http://localhost:$HTTP_PORT/metrics | grep -c '^usg_watchdog_'` doit valoir `0` ; `grep -c usg_watchdog grafana/dashboard.json` doit valoir `0`
- **Fix** : si une série `usg_watchdog_*` apparaît, c'est un résidu de
  l'ancienne recommandation § 2.6 — la retirer, ne pas la garder « au cas où ».

## La logique métier ne change pas

- **Owner** : `src/watchdog.py`, `src/state.py`, `src/peer.py`
- **Preconditions** : ce PRD est un renommage, pas une refonte.
- **Postconditions** : scoring, circuit breaker, détection ISP, escalade,
  DDNS, backup se comportent à l'identique avant/après, à l'exception du
  `ReadWritePaths` du fichier d'événements (bug latent corrigé au passage,
  § 2.2 du PRD, explicitement dans le périmètre).
- **Invariants** : `git diff --stat main -- src/watchdog.py src/state.py src/peer.py` ne doit contenir que des changements de libellé (docstring, logs de démarrage/arrêt) — aucun changement de logique de scoring ou de circuit breaker.
- **Verify** : `python3 -m pytest tests/test_watchdog.py tests/test_state.py tests/test_peer.py -q` (tests inchangés fonctionnellement, seuls les libellés attendus évoluent)
- **Fix** : si un sprint a modifié la logique, sortir le changement — ce n'est
  pas le périmètre de ce PRD.
