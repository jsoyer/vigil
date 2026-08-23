# INVARIANTS — A1, pilotage TP-Link

Contrats transverses vérifiables machine. Un sprint qui viole un invariant est
en échec, quel que soit l'état de ses propres tests.

Contexte : **4 instances** (Dijon master+slave, Nice master+slave) qui se
mettent à jour **automatiquement** depuis `main`. La plupart de ces invariants
existent parce qu'une violation se traduirait par une panne silencieuse sur ces
4 instances, sans humain dans la boucle.

---

## Import vendor paresseux (C1)

- **Owner** : `src/drivers/`
- **Preconditions** : tout module driver est importable là où la lib vendor n'est
  pas installée.
- **Postconditions** : l'`ImportError` ne survient qu'à l'usage effectif d'un
  équipement de ce vendor.
- **Invariants** : `import tplinkrouterc6u` n'apparaît **jamais** au niveau
  module. Aucune chaîne `watchdog → … → lib vendor` au niveau module.
- **Verify** : `python3 -c "import sys; sys.path.insert(0,'src'); import watchdog, drivers"`
- **Fix** : déplacer l'import dans le corps de la méthode qui l'utilise.

## Le cœur mono-cible n'est pas touché

- **Owner** : `src/watchdog.py`, `src/state.py`
- **Preconditions** : A1 ajoute des équipements pilotables, pas des cibles de la
  boucle de surveillance.
- **Postconditions** : boucle de scoring, circuit-breaker et format de
  `WatchdogState` strictement inchangés par rapport à la 1.8.
- **Invariants** : c'est ce qui rend A1 quasi sans risque de régression USG, et
  ce qui satisfait C3 par construction. Le refactor appartient au PRD B.
- **Verify** : `git diff --quiet $(git describe --tags --abbrev=0 --match 'v2.0*') -- src/watchdog.py src/state.py`
- **Fix** : sortir le changement d'A1. S'il est indispensable, c'est le découpage
  qui est à revoir — le remonter, pas le contourner.

## Aucun équipement déclaré ⇒ comportement identique à la 1.8

- **Owner** : `src/config.py`, `src/managed_devices.py`
- **Preconditions** : un déploiement existant n'a aucune variable `TPLINK_*`.
- **Postconditions** : API, boucle et sorties se comportent comme en 1.8 ; aucun
  driver n'est instancié.
- **Invariants** : les 4 instances reçoivent la 1.9.0 **automatiquement**. La
  mise à jour ne doit rien changer tant qu'un humain n'a pas déclaré un
  équipement, site par site.
- **Verify** : `python3 -m pytest tests/ -k "no_tplink_configured" -q`
- **Fix** : conditionner strictement l'activation à la déclaration.

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
- **Fix** : envelopper l'appel fautif, retourner la valeur dégradée documentée.

## Une panne est attribuée au bon saut

- **Owner** : `src/drivers/tplink.py`
- **Preconditions** : le chemin comporte trois sauts — watchdog → Pi Zero →
  WiFi → MR110.
- **Postconditions** : toute indisponibilité renseigne `failed_hop`
  (`BRIDGE` / `WIRELESS` / `DEVICE` / `ROUTE`) et produit un message distinct.
- **Invariants** : « secours injoignable » sans dire **où** oblige à tout
  re-diagnostiquer à la main. Une cause non attribuable n'est **jamais** imputée
  au MR110 par défaut. Sur `BRIDGE`, le Pi Zero étant en PoE, la cause peut être
  le Pi, son port de switch, le budget PoE ou le câble : le message le reflète.
- **Verify** : `python3 -m pytest tests/test_drivers_tplink.py -k "failed_hop" -q`
- **Fix** : compléter la sonde étagée ; ne pas replier plusieurs sauts sur une
  cause générique.

## Une route absente n'est pas une panne de secours (C8)

- **Owner** : `src/drivers/tplink.py`
- **Preconditions** : l'accès au MR110 dépend d'une route et d'un NAT posés hors
  du dépôt.
- **Postconditions** : route ou NAT manquants produisent `Hop.ROUTE` — défaut de
  configuration, pas panne d'équipement.
- **Invariants** : sans ça, la première mise à jour système qui efface une route
  déclenche une fausse alerte critique sur un secours parfaitement sain.
- **Verify** : `python3 -m pytest tests/test_drivers_tplink.py -k "route_misconfig" -q`
- **Fix** : distinguer « jamais joignable depuis cette instance » de « joignable
  avant, plus maintenant ».

## Aucune action destructive automatique (C6)

- **Owner** : `src/managed_devices.py`, `src/http_server.py`, `src/telegram_bot.py`
- **Preconditions** : `reboot()`, `send_sms()`, `send_ussd()` existent dans le
  driver.
- **Postconditions** : déclenchées uniquement par une commande opérateur
  explicite **et confirmée**, tracées dans l'`EventLog` avec leur origine.
- **Invariants** : rebooter un secours **pendant qu'il porte le trafic**
  couperait le site — pire scénario de la feature. SMS et USSD coûtent de
  l'argent : jamais implicites, jamais en réessai automatique.
- **Verify** : `python3 -m pytest tests/test_managed_devices.py -k "no_auto_destructive or requires_confirmation" -q`
- **Fix** : remonter la garde en amont du chemin d'appel, pas dans une branche
  enfouie.

## Les commandes Telegram existantes ne régressent pas

- **Owner** : `src/telegram_bot.py`
- **Preconditions** : le dispatcher ne parsait aucun argument ; A1 l'étend.
- **Postconditions** : `/status`, `/pause`, `/resume`, `/reboot`, `/ddns`,
  `/backup`, `/tailscale`, `/help` se comportent **exactement** comme avant.
- **Invariants** : le parsing d'arguments est un prérequis technique, pas une
  occasion de refondre le dispatch. `allowed_updates` reste inchangé.
- **Verify** : `python3 -m pytest tests/test_telegram_bot.py -q`
- **Fix** : isoler le parsing en amont du `if/elif` existant, sans le réécrire.

## Session admin unique par équipement (C5, A1)

- **Owner** : `src/managed_devices.py`
- **Preconditions** : un routeur MR n'accepte **qu'une** session d'administration.
- **Postconditions** : accès sérialisés par un verrou ; `logout()` garanti ;
  session refusée → message clair et **un seul** réessai.
- **Invariants** : une session laissée ouverte verrouille l'admin du routeur ;
  une boucle de réessai transformerait une collision en déni de service.
  L'exclusivité **entre instances** appartient au PRD B.
- **Verify** : `python3 -m pytest tests/test_managed_devices.py -k "session_lock or logout_guaranteed" -q`
- **Fix** : verrou par équipement + `logout()` en `finally`.

## La sonde de bout en bout sort par le lien 4G (C11)

- **Owner** : `src/drivers/tplink.py`, `docs/runbooks/pi-zero-mr110-access.md`
- **Preconditions** : l'hôte qui exécute la sonde est **à double rattachement** —
  une patte vers le LAN du site (donc la fibre), une vers le MR110. Vrai que la
  sonde tourne en local (mode `bridged`) ou par SSH sur un pont dédié
  (`remote`) : **le risque de fuite est identique dans les deux modes**.
- **Postconditions** : un succès n'est retenu que si **deux preuves
  indépendantes** concordent — l'IP publique observée **diffère** de celle du
  site, **et** les compteurs de trafic du MR110 ont bougé pendant la sonde.
- **Invariants** : lier la requête à `wlan0` **ne prouve pas** qu'elle est
  sortie par là — l'option peut ne pas être honorée, une route peut avoir
  changé, le DNS peut emprunter l'autre patte. Une sonde qui fuit vers la fibre
  **réussit**, et signale un secours sain quoi qu'il arrive : c'est le pire mode
  de défaillance du projet, un faux OK silencieux sur la seule chose qu'on
  cherche à vérifier. La sonde doit donc **porter sa preuve de chemin**, jamais
  se fier à sa configuration. Une fuite détectée est un **défaut de
  configuration** — même traitement que `Hop.ROUTE` (C8) — pas une panne du
  secours. Et un lien attaché sans data ressort `DEGRADED`, jamais `OK`.
- **Verify** : `python3 -m pytest tests/test_drivers_tplink.py -k "probe_path_proof or probe_leak or attached_without_data" -q`
- **Fix** : exiger les deux preuves avant de conclure au succès ; ne jamais
  déduire le chemin de la commande émise.

## Le mode d'accès est une propriété de la cible (C16)

- **Owner** : `src/drivers/tplink.py`, `src/config.py`
- **Preconditions** : le parc est mixte — certaines instances tournent sur la
  machine qui porte le WiFi vers le MR110 (Pi Zero, mode `bridged`), d'autres sur
  le LAN seulement (Pi 4, mode `remote`). Le mode peut différer entre le master
  et le slave d'un même site.
- **Postconditions** : le mode est déclaré **par équipement** ; les deux modes
  produisent les mêmes `failed_hop` et **exigent la même preuve de chemin**
  (C11) ; seule l'exécution de la commande diffère.
- **Invariants** : traiter le parc comme uniforme conduirait soit à exiger une
  route et un SSH là où l'hôte est déjà sur le bon réseau, soit à sonder en local
  depuis une machine sans patte vers le MR110. Le mode doit être isolé derrière
  une abstraction d'exécution — **jamais** dispersé en conditionnels dans la
  logique de sonde, sinon les deux chemins divergent avec le temps et un seul
  reste réellement testé.
- **Verify** : `python3 -m pytest tests/test_drivers_tplink.py -k "mode_bridged or mode_remote" -q`
- **Fix** : isoler « exécuter cette commande » ; paramétrer les tests sur les
  deux modes.

## Le pont n'est pas un composant applicatif (C7)

- **Owner** : `docs/runbooks/pi-zero-mr110-access.md`
- **Preconditions** : en mode `remote`, le pont est une machine dédiée
  (IP forwarding + NAT). En mode `bridged`, l'hôte du watchdog **est** le pont.
- **Postconditions** : en `remote`, aucune dépendance Python, aucun service,
  aucun fichier du projet déployé sur le pont ; route posée sur les hôtes
  watchdog uniquement — jamais sur l'USG, jamais en DHCP. Une **commande SSH
  ponctuelle** (sonde C11) est autorisée : elle n'installe rien et ne laisse rien
  derrière elle. En `bridged`, la contrainte est **sans objet** — l'hôte est déjà
  une machine gérée du parc.
- **Note** : en mode `bridged`, la lib TP-Link est nécessairement installée sur
  l'hôte — un **Pi Zero 2 W** (ARMv8, confirmé), ce qui écarte le cas ARMv6 où
  `pycryptodome` aurait dû être compilé sur place. L'installation réelle reste à
  valider au Sprint 1 selon la bitness de l'OS : **C2 relance `pip install` sur
  ces machines à chaque auto-update**, et un échec y provoquerait un rollback.
- **Invariants** : évite un composant de plus à maintenir sur deux sites, **et**
  rend la future migration WAN2 sans impact sur le code. Poser la route côté USG
  exposerait l'admin du MR110 à tout le LAN.
- **Verify** : revue manuelle du runbook (invariant de procédure).
- **Fix** : si du code devient nécessaire sur le Pi Zero, c'est un changement
  d'architecture — rouvrir C7 dans l'ADR, ne pas le décider dans un sprint.

## Secrets jamais exposés

- **Owner** : `src/config.py`, `src/http_server.py`, `src/drivers/tplink.py`
- **Preconditions** : les mots de passe TP-Link viennent de l'environnement
  (`.env` en 600).
- **Postconditions** : absents des logs, de `/api/config`, de l'export de config,
  du reload, de `/api/tplink/*`, des rapports de spike et du runbook.
- **Invariants** : aucun secret ne franchit une frontière d'observabilité. Les
  **trois** whitelists sont divergentes et se maintiennent séparément — un secret
  oublié dans l'une fuit par elle seule.
- **Verify** : `python3 -m pytest tests/ -k "secret_not_exposed" -q`
- **Fix** : masquer à la source ; ne jamais journaliser l'objet de config entier.
