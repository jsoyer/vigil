# Sprint 2 — `TplinkDriver` : wrapper de lib, session, sonde étagée

- **PRD** : A1 — Pilotage des lignes de secours TP-Link MR110 (2026-08-20)
- **Dépend de** : Sprint 1 (chemin réseau + contrat + **verdict du spike**)
- **Bloque** : sprints 3 et 4
- **Pré-requis bloquant** : lire `docs/spikes/2026-08-XX-mr110-compat.md`. Si le
  verdict est `UNSUPPORTED`, **ne pas exécuter ce sprint** tel quel — appliquer
  le plan B du rapport.

## Contexte (autoportant)

Dijon et Nice ont chacun une ligne de secours 4G **TP-Link TL-MR110**, sur son
propre réseau WiFi, atteinte depuis les hôtes watchdog **à travers un Pi Zero 2 W**
(pont de management : route statique + NAT, mis en place au Sprint 1). Le
chemin comporte donc trois sauts : `watchdog → Pi Zero → WiFi → MR110`.

Le Sprint 1 a défini `src/drivers/_base.py` : `RouterDriver` (Protocol),
`RouterHealth` (avec `failed_hop`), `RouterMetrics`, `RouterReadiness`,
`Readiness`, `RouterRole`, `Hop`.

La lib `tplinkrouterc6u` expose `TplinkRouterProvider.get_client(host, password)`
(auto-détection du chiffrement CBC/GCM), puis `authorize()`, `get_status()`,
`get_lte_status()`, `get_firmware()`, `reboot()`, `logout()`, et selon firmware
les commandes SMS/USSD. **Les routeurs MR n'acceptent qu'une seule session
d'administration à la fois.**

Ce sprint construit le driver. **Il n'expose rien à l'opérateur** — c'est le
Sprint 3 qui câble les commandes. Et il ne touche **ni** `watchdog.py`, **ni**
`state.py` : le cœur mono-cible reste intact sur tout A1.

## Objectifs

1. `src/drivers/tplink.py` : `TplinkDriver` conforme au contrat, **import de la
   lib strictement paresseux**.
2. **Sonde étagée** avec attribution de panne au bon saut.
3. Lecture des métriques 4G et du compteur de conso.

## Travail

### 2.1 Cycle de vie et robustesse

- `requirements.txt` : `tplinkrouterc6u==<version validée au spike>` (pin strict).
- **C1 — import paresseux, non négociable** : `import tplinkrouterc6u`
  uniquement **dans le corps des méthodes**, jamais au niveau module. Motif :
  `updater/preflight.py` importe `watchdog` ; si la chaîne d'import tire la lib
  et qu'elle n'est pas installée, l'auto-update échoue et rollback **sur les 4
  instances de production**.
- Session : `get_client()` → `authorize()` → appels → `logout()` dans un
  **`finally`**, systématiquement, y compris sur exception. Une session laissée
  ouverte verrouille l'admin du routeur.
- Toutes les exceptions de la lib (`AuthorizeError`, `ClientException`, réseau,
  timeout) sont attrapées → valeur dégradée retournée, **jamais propagée**.
- Timeouts explicites sur tous les appels : le chemin passe par un lien WiFi, un
  appel bloquant sans timeout gèlerait l'appelant.

### 2.2 Sonde étagée — attribution de panne (le point clé)

`health()` ne se contente pas de dire « joignable ou non ». Il exécute les
étapes dans l'ordre et **s'arrête à la première qui échoue**, en renseignant
`failed_hop` :

| Étape | Échec ⇒ `failed_hop` | Sens pour l'opérateur |
|---|---|---|
| 1. Pont — `remote` : ping de son IP LAN ; `bridged` : état et association de l'interface sans fil **locale** | `Hop.BRIDGE` | Le premier maillon est en cause — le secours ne l'est pas forcément. En `remote`, le pont étant **alimenté en PoE**, ça peut être le Pi, son port de switch, le budget PoE ou le câble : rester prudent sur la cause, ne pas annoncer « pont mort » |
| 2. Ping de l'IP du MR110 (traverse le WiFi) | `Hop.WIRELESS` | Le Pi Zero répond mais plus le MR110 : lien WiFi décroché, ou routeur éteint |
| 3. `authorize()` sur le MR110 | `Hop.DEVICE` | Le routeur répond au ping mais pas à l'admin |
| 4. Lecture de l'état WAN | — | Chemin d'audit sain ; c'est l'état 4G qui est évalué |

- **C8 — sans objet en mode `bridged`** (ni route ni NAT à omettre). En mode
  `remote`, distinguer un défaut de configuration d'une panne. Si le pont
  répond mais que le MR110 est injoignable **et** qu'il n'a jamais été joignable
  depuis cette instance, c'est un `Hop.ROUTE` (route statique ou NAT absents),
  pas une panne du secours. Sinon, la première mise à jour système qui efface
  une route déclencherait une fausse alerte critique.
- `attached` s'appuie sur l'état WAN **auto-reporté** par le routeur
  (`connect_status` / `network_type`). **`attached` n'est pas `internet_ok`** :
  un MR110 peut être attaché en n'ayant plus de data (forfait épuisé, APN cassé,
  blocage opérateur). `internet_ok` n'est établi que par la **sonde de bout en
  bout** (2.6) ; sans sonde récente il vaut `None` — **jamais `True`** par
  défaut.
- `rtt_ms` mesuré sur l'étape 2 sert d'indicateur de **qualité du saut WiFi** —
  c'est le seul signal disponible sur ce lien sans installer de code sur le Pi Zero.

### 2.3 Métriques

`metrics()` : mapping `LTEStatus` → `RouterMetrics` (rsrp, rsrq, snr,
network_type, sim_status, signal_bars, isp_name, data_used_bytes, rx/tx speed)
+ champs de `get_status()` (wan_ip, clients_total, cpu, mem).

**Tout champ absent reste `None`.** Se référer au tableau des champs réellement
disponibles du rapport de spike — ne rien supposer du firmware.

### 2.4 Readiness (calcul, pas encore d'alerte)

`readiness()` répond à : *« ce secours peut-il prendre le relais maintenant ? »*

- `OK` — SIM prête, lien attaché, signal au-dessus des seuils, chemin d'audit sain.
- `DEGRADED` — au moins un critère en échec ; `reasons` liste les critères en
  échec **avec leur valeur et le seuil** (ex. `("rsrp=-118 < seuil -110",)`),
  pour que l'opérateur sache quoi aller regarder.
- `UNKNOWN` — information indisponible (champ absent, auth KO, saut coupé).
  **`UNKNOWN` n'est pas un état sain** : ne jamais le replier sur `OK`, ni le
  confondre avec `DEGRADED`.

Seuils configurables (RSRP, RSRQ, SNR), défauts documentés et justifiés dans le
code. Un champ non fourni par le firmware n'est pas évalué et ne peut pas à lui
seul provoquer un `DEGRADED`.

L'**alerting** automatique sur ces états appartient au PRD B — ici on calcule et on
expose, on ne notifie pas encore en boucle.

### 2.6 Sonde de bout en bout (C11)

Vérifie que le lien **porte réellement du trafic**, pas seulement qu'il est
attaché. C'est la seule réponse fiable à « est-ce que ce secours marche ? ».

- Exécution par **commande SSH ponctuelle sur le Pi Zero** (`paramiko`, déjà une
  dépendance), seul point du chemin situé derrière le MR110. Rien n'y est
  installé — C7 amendée en ce sens.
- **Deux modes d'exécution (C16)**, déclarés par équipement — le parc est mixte,
  et le mode peut différer entre le master et le slave d'un même site :

  | Mode | Exécution | Contexte |
  |---|---|---|
  | `bridged` | **locale**, liée à l'interface sans fil | le watchdog tourne sur la machine qui porte le WiFi vers le MR110 (Pi Zero) |
  | `remote` | **SSH ponctuel** sur le pont (`paramiko`) | le watchdog est ailleurs sur le LAN (Pi 4) |

  Isoler le mode derrière une petite abstraction « exécuter cette commande » : le
  reste de la sonde doit être **identique** dans les deux cas.
- **L'hôte est à double rattachement dans les deux modes** : une patte vers le
  LAN (donc la fibre), une vers le MR110. Lier la requête à l'interface sans fil
  **ne prouve pas** qu'elle est sortie par là — l'option peut ne pas être
  honorée, une route peut changer, le DNS peut emprunter l'autre patte. Utiliser
  la commande validée au Sprint 1, mais **ne jamais en déduire le chemin**. C'est
  vrai en local comme en SSH : la preuve de chemin ci-dessous ne dépend pas du
  mode.
- **La sonde porte sa preuve de chemin.** Un succès n'est retenu que si les deux
  concordent :
  1. **IP publique observée ≠ IP publique du site.** La sonde renvoie l'IP vue
     depuis le Pi Zero ; le driver la compare à celle du site via
     `get_public_ip()` (`src/ddns_cloudflare.py:72`, **à réutiliser**, endpoints
     de repli inclus). Identiques ⇒ **fuite par la fibre**. Le CGNAT mobile ne
     gêne pas : on cherche une différence, pas une correspondance avec
     `wan_ipv4_addr`.
  2. **Compteurs du MR110 en mouvement.** `total_statistics` relevé avant/après.
     Figés ⇒ la requête n'a pas traversé le routeur.

  Conserver la dernière IP publique connue du site en repli, pour le cas où la
  fibre serait down au moment de la sonde.
- Requête **légère** (~1 Ko), timeout court. À la demande en A1 ; périodique et
  opt-in en A2.
- Résultat à **quatre** valeurs :

  | Valeur | Sens | Effet |
  |---|---|---|
  | `OK` | data qui passe, chemin prouvé | `internet_ok = True` |
  | `FAIL` | pas de data sur le lien | `internet_ok = False` → `DEGRADED` |
  | `LEAK` | sortie par la fibre — **défaut de configuration** | `internet_ok = None` ; remonté comme problème du chemin de test, **pas** comme panne du secours (même philosophie que `Hop.ROUTE`, C8) |
  | `UNKNOWN` | Pi Zero injoignable, commande absente | `internet_ok = None`, readiness **non** dégradée |

- Ne lève jamais ; ne bloque pas au-delà du timeout.

### 2.5 Reboot

`reboot()` implémenté, retourne un `bool`, ne lève jamais. **Aucun appel
automatique depuis ce module** : il ne sera déclenché que par une commande
opérateur explicite, câblée au Sprint 3.

## Tests

`tests/test_drivers_tplink.py`, lib **entièrement mockée** (aucun accès réseau) :

- **C1 (bloquant)** : `python -c "import drivers.tplink"` réussit **sans** la lib
  installée ; l'`ImportError` ne survient qu'à l'usage effectif.
- `logout()` appelé même quand un appel intermédiaire lève (assert sur le mock).
- **Attribution de panne** : pont muet → `Hop.BRIDGE` ; pont OK et MR110 muet →
  `Hop.WIRELESS` ; ping OK et `authorize()` KO → `Hop.DEVICE` ; jamais joignable
  depuis cette instance → `Hop.ROUTE` (C8, mode `remote` uniquement).
- **C16** : les deux modes produisent les **mêmes** valeurs de `failed_hop` et
  **exigent la même preuve de chemin** ; seule l'exécution diffère — tests
  paramétrés sur les deux modes.
- Mode `bridged` : interface sans fil down ou non associée → `Hop.BRIDGE` ; et
  **aucun appel SSH n'est émis** (assertion sur le mock).
- `get_lte_status()` complet → mapping correct de tous les champs.
- `get_lte_status()` partiel (champs manquants, comme relevé au spike) → champs
  `None`, readiness dégradée proprement, **pas de `KeyError`**.
- Readiness : SIM KO → `DEGRADED` + raison ; RSRP sous seuil → `DEGRADED` +
  raison chiffrée ; tout OK → `OK` ; champ absent → **n'entraîne pas** `DEGRADED`.
- **Sonde (C11) — preuve de chemin** : IP observée identique à celle du site →
  `LEAK`, **jamais** `OK` ; compteurs du routeur figés → `LEAK`, même si l'IP
  diffère ; les deux preuves concordantes → `OK`.
- `LEAK` est rapporté comme **défaut de configuration du chemin de test**, pas
  comme panne du secours, et ne dégrade pas la readiness.
- **Lien attaché mais sonde en échec → `DEGRADED`, jamais `OK`.** C'est le
  scénario du forfait épuisé : le routeur se dit connecté, la data ne passe pas.
- Sonde `UNKNOWN` (SSH injoignable) → `internet_ok` à `None`, readiness non
  dégradée pour autant.
- IP publique du site indisponible (fibre down) → repli sur la dernière connue ;
  à défaut `UNKNOWN`, **jamais** `OK`.
- Sonde jamais exécutée → `internet_ok` à `None`, **jamais `True`**.
- Timeout réseau → valeur dégradée, jamais de blocage ni d'exception.
- Aucun mot de passe dans les logs (capture de logs + assertion).

## Critères d'acceptation

- [ ] `src/drivers/tplink.py` créé, conforme au contrat, aucune méthode ne lève
- [ ] `tplinkrouterc6u` pinné dans `requirements.txt` (version du spike)
- [ ] **C1 vérifié par test** : import du module OK sans la lib installée
- [ ] `logout()` garanti en `finally`, prouvé sur chemin d'erreur
- [ ] **Sonde étagée** : les 4 attributions de panne vérifiées par test
- [ ] **C8** : route absente → `Hop.ROUTE`, pas une panne du secours
- [ ] Métriques 4G mappées ; champs absents → `None`, jamais d'exception
- [ ] **C11** : sonde implémentée **portant sa preuve de chemin** (IP ≠ celle du
      site **et** compteurs en mouvement), résultat à quatre valeurs dont `LEAK`,
      ne lève jamais
- [ ] `get_public_ip()` de `ddns_cloudflare.py` **réutilisé**, pas réécrit
- [ ] **C16** : modes `bridged` et `remote` derrière une abstraction d'exécution ;
      comportement et preuve de chemin **identiques** (tests paramétrés)
- [ ] `attached` et `internet_ok` **distincts** ; lien attaché sans data →
      `DEGRADED`
- [ ] Readiness `OK` / `DEGRADED` (+ raisons chiffrées) / `UNKNOWN`
- [ ] Aucun appel automatique à `reboot()` dans ce module
- [ ] Mot de passe absent des logs
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Créer** : `src/drivers/tplink.py`, `tests/test_drivers_tplink.py`
- **Modifier** : `requirements.txt`, `src/config.py` (hôtes, identifiants,
  seuils de signal)
- **Lecture seule** : `src/drivers/_base.py`, `docs/spikes/`, `docs/runbooks/`
- **Interdit** : `watchdog.py`, `state.py`, `peer.py`, `connectivity.py`,
  `usg.py` — le cœur mono-cible n'est pas touché sur tout A1
