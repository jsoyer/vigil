# INVARIANTS — usg-watchdog, phase A (management TP-Link)

Contrats transverses vérifiables machine. Un sprint qui viole un invariant est
en échec, quel que soit l'état de ses propres tests.

Contexte de production : **4 instances** (Dijon master+slave, Nice
master+slave) qui se mettent à jour **automatiquement** depuis `main`. La
plupart de ces invariants existent parce qu'une violation se traduirait par une
panne silencieuse sur ces 4 instances, sans humain dans la boucle.

---

## Import vendor paresseux (C1)

- **Owner** : `src/drivers/`
- **Preconditions** : tout module driver est importable dans un environnement où
  la lib vendor n'est pas installée.
- **Postconditions** : l'`ImportError` d'une lib vendor ne survient qu'à
  l'instanciation ou à l'usage effectif d'un équipement de ce vendor.
- **Invariants** : `import tplinkrouterc6u` n'apparaît **jamais** au niveau
  module — uniquement dans le corps des méthodes. Aucune chaîne d'import
  `watchdog → … → lib vendor` au niveau module.
- **Verify** : `! grep -rn --include='*.py' -E '^[[:space:]]*(import|from)[[:space:]]+tplinkrouterc6u' src/ | grep -qv 'src/drivers/tplink.py' && python3 -c "import sys; sys.path.insert(0,'src'); import watchdog, drivers"`
- **Fix** : déplacer l'import dans le corps de la méthode qui l'utilise.

## Le cœur mono-cible n'est pas touché en phase A

- **Owner** : `src/watchdog.py`, `src/state.py`
- **Preconditions** : la phase A ajoute des équipements pilotables, pas des
  cibles de la boucle de surveillance.
- **Postconditions** : la boucle de scoring, le circuit-breaker et le format de
  `WatchdogState` sont strictement inchangés par rapport à la 1.8.
- **Invariants** : c'est ce qui rend la phase A quasi sans risque de régression
  USG, et ce qui satisfait C3 par construction. Le refactor appartient à la
  phase B, où il sera jugé sur ses propres mérites.
- **Verify** : `git diff --quiet $(git describe --tags --abbrev=0 --match 'v1.8*') -- src/watchdog.py src/state.py`
- **Fix** : sortir le changement de la phase A ; s'il est indispensable,
  c'est que le découpage en phases est à revoir — le remonter, pas le contourner.

## Aucun équipement déclaré ⇒ comportement identique à la 1.8

- **Owner** : `src/config.py`, `src/managed_devices.py`
- **Preconditions** : un déploiement existant n'a aucune variable `TPLINK_*`.
- **Postconditions** : dashboard, API, `/metrics` et boucle se comportent
  exactement comme en 1.8 ; aucun driver n'est instancié.
- **Invariants** : les 4 instances reçoivent la 1.9.0 **automatiquement**. La
  mise à jour ne doit rien changer tant qu'un humain n'a pas déclaré un
  équipement, site par site.
- **Verify** : `python3 -m pytest tests/ -k "no_tplink_configured" -q`
- **Fix** : rendre l'activation strictement conditionnée à la déclaration.

## Les drivers ne lèvent jamais

- **Owner** : `src/drivers/_base.py`
- **Preconditions** : l'appelant ne met aucun `try/except` autour des méthodes.
- **Postconditions** : `health()`, `metrics()`, `readiness()`, `reboot()`,
  `test_connection()` retournent toujours une valeur — panne réseau, auth
  refusée, timeout, firmware inattendu.
- **Invariants** : aucune exception ne franchit la frontière d'un driver ;
  l'information indisponible se traduit par `None` ou `Readiness.UNKNOWN`, pas
  par une valeur inventée ni par un état sain par défaut.
- **Verify** : `python3 -m pytest tests/test_drivers_base.py tests/test_drivers_tplink.py -q`
- **Fix** : envelopper l'appel fautif et retourner la valeur dégradée documentée.

## Une panne est attribuée au bon saut

- **Owner** : `src/drivers/tplink.py`
- **Preconditions** : le chemin comporte trois sauts — watchdog → Pi Zero →
  WiFi → MR110.
- **Postconditions** : toute indisponibilité renseigne `failed_hop`
  (`BRIDGE` / `WIRELESS` / `DEVICE` / `ROUTE`) et produit un message opérateur
  distinct.
- **Invariants** : « secours injoignable » sans dire **où** oblige à tout
  re-diagnostiquer à la main — l'alerte ne fait alors que déplacer le travail.
  Une cause non attribuable n'est **jamais** imputée au MR110 par défaut.
- **Verify** : `python3 -m pytest tests/test_drivers_tplink.py -k "failed_hop" -q`
- **Fix** : compléter la sonde étagée ; ne pas replier plusieurs sauts sur une
  cause générique.

## Une route absente n'est pas une panne de secours (C8)

- **Owner** : `src/drivers/tplink.py`
- **Preconditions** : l'accès au MR110 dépend d'une route statique et d'un NAT
  posés hors du dépôt.
- **Postconditions** : une route ou un NAT manquants produisent `Hop.ROUTE` —
  un défaut de configuration du chemin d'audit, pas une panne de l'équipement.
- **Invariants** : sans ça, la première mise à jour système qui efface une route
  déclenche une fausse alerte critique sur un secours parfaitement sain.
- **Verify** : `python3 -m pytest tests/test_drivers_tplink.py -k "route_misconfig" -q`
- **Fix** : distinguer « jamais joignable depuis cette instance » de « joignable
  avant, plus maintenant ».

## Aucune action destructive automatique (C6)

- **Owner** : `src/managed_devices.py`, `src/http_server.py`, `src/telegram_bot.py`
- **Preconditions** : `reboot()`, `send_sms()`, `send_ussd()` existent dans le driver.
- **Postconditions** : elles ne sont déclenchées que par une commande opérateur
  explicite, avec confirmation pour le reboot, et tracées dans l'`EventLog` avec
  leur origine.
- **Invariants** : rebooter un secours **pendant qu'il porte le trafic** couperait
  le site — c'est le pire scénario de cette feature. SMS et USSD coûtent de
  l'argent : jamais implicites, jamais en réessai automatique.
- **Verify** : `python3 -m pytest tests/test_managed_devices.py -k "no_auto_destructive or reboot_requires_confirmation" -q`
- **Fix** : remonter la garde en amont du chemin d'appel, pas dans une branche
  enfouie.

## Session admin unique par équipement (C5, phase A)

- **Owner** : `src/managed_devices.py`
- **Preconditions** : un routeur MR n'accepte **qu'une** session d'administration.
- **Postconditions** : les accès à un même équipement sont sérialisés par un
  verrou ; `logout()` est garanti ; une session refusée donne un message clair
  et **un seul** réessai.
- **Invariants** : une session laissée ouverte verrouille l'admin du routeur ;
  une boucle de réessai transformerait une collision en déni de service.
  L'exclusivité **entre instances** (master/slave) appartient à la phase B, où
  le polling devient continu.
- **Verify** : `python3 -m pytest tests/test_managed_devices.py -k "session_lock or logout_guaranteed" -q`
- **Fix** : verrou par équipement + `logout()` en `finally`.

## Métriques Prometheus legacy préservées (C4)

- **Owner** : `src/metrics.py`
- **Preconditions** : des dashboards Grafana et des règles d'alerte consomment
  déjà `usg_watchdog_*` sans label.
- **Postconditions** : ces métriques restent émises **sans label** ; les
  métriques par équipement sont ajoutées à côté.
- **Invariants** : ajouter un label à une métrique existante casse
  silencieusement les requêtes et les alertes qui la consomment.
- **Verify** : `python3 -m pytest tests/test_metrics.py -k "legacy_unlabeled" -q`
- **Fix** : émettre les deux familles ; ne jamais substituer.

## Rien sur le Pi Zero (C7)

- **Owner** : `docs/runbooks/pi-zero-mr110-access.md`
- **Preconditions** : le Pi Zero est un pont de management (IP forwarding + NAT).
- **Postconditions** : aucune dépendance Python, aucun service applicatif,
  aucun code du projet n'est déployé sur le Pi Zero ; la route est posée sur les
  hôtes watchdog uniquement — jamais sur l'USG, jamais en DHCP.
- **Invariants** : c'est ce qui évite un composant supplémentaire à maintenir sur
  deux sites, **et** ce qui rend la future migration vers le WAN2 sans impact sur
  le code. Poser la route côté USG exposerait l'admin du MR110 à tout le LAN.
- **Verify** : revue manuelle du runbook (invariant de procédure, non
  automatisable depuis le dépôt).
- **Fix** : si du code devient nécessaire sur le Pi Zero, c'est un changement
  d'architecture — rouvrir C7 dans l'ADR, ne pas le décider dans un sprint.

## Secrets jamais exposés

- **Owner** : `src/config.py`, `src/http_server.py`, `src/drivers/tplink.py`
- **Preconditions** : les mots de passe TP-Link viennent de l'environnement
  (`.env` en 600).
- **Postconditions** : ils n'apparaissent ni dans les logs, ni dans
  `/api/config`, ni dans `/api/tplink/*`, ni dans le dashboard, ni dans les
  rapports de spike ou le runbook.
- **Invariants** : aucun secret ne franchit une frontière d'observabilité.
- **Verify** : `! grep -rn --include='*.py' -E 'TPLINK_[0-9]+_PASSWORD|tplink_password' src/ | grep -iE 'log|print|debug'`
- **Fix** : masquer à la source ; ne jamais journaliser l'objet de config entier.
