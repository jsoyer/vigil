# Sprint 2 — `TplinkDriver` : wrapper de lib, session, sonde étagée

- **PRD** : Lignes de secours TP-Link MR110 — phase A (management) — 2026-08-12
- **Dépend de** : Sprint 1 (chemin réseau + contrat + **verdict du spike**)
- **Bloque** : sprints 3, 4, 5
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
`state.py` : le cœur mono-cible reste intact en phase A.

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
| 1. Ping de l'IP LAN du Pi Zero | `Hop.BRIDGE` | Le pont ne répond pas — le secours n'est pas forcément en cause. Le Pi Zero étant **alimenté en PoE**, ça peut être le Pi, son port de switch, le budget PoE ou le câble : le message doit rester prudent sur la cause, pas annoncer « Pi Zero mort » |
| 2. Ping de l'IP du MR110 (traverse le WiFi) | `Hop.WIRELESS` | Le Pi Zero répond mais plus le MR110 : lien WiFi décroché, ou routeur éteint |
| 3. `authorize()` sur le MR110 | `Hop.DEVICE` | Le routeur répond au ping mais pas à l'admin |
| 4. Lecture de l'état WAN | — | Chemin d'audit sain ; c'est l'état 4G qui est évalué |

- **C8 — distinguer un défaut de configuration d'une panne.** Si le Pi Zero
  répond mais que le MR110 est injoignable **et** qu'il n'a jamais été joignable
  depuis cette instance, c'est un `Hop.ROUTE` (route statique ou NAT absents),
  pas une panne du secours. Sinon, la première mise à jour système qui efface
  une route déclencherait une fausse alerte critique.
- `internet_ok` s'appuie sur l'état WAN **auto-reporté** par le routeur
  (`connect_status` / `network_type`). On ne route **pas** de trafic de test à
  travers la ligne de secours : ça consommerait du quota.
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

L'**alerting** sur ces états appartient à la phase B — ici on calcule et on
expose, on ne notifie pas encore en boucle.

### 2.5 Reboot

`reboot()` implémenté, retourne un `bool`, ne lève jamais. **Aucun appel
automatique depuis ce module** : il ne sera déclenché que par une commande
opérateur explicite, câblée au Sprint 3.

## Tests

`tests/test_drivers_tplink.py`, lib **entièrement mockée** (aucun accès réseau) :

- **C1 (bloquant)** : `python -c "import drivers.tplink"` réussit **sans** la lib
  installée ; l'`ImportError` ne survient qu'à l'usage effectif.
- `logout()` appelé même quand un appel intermédiaire lève (assert sur le mock).
- **Attribution de panne** : Pi Zero muet → `Hop.BRIDGE` ; Pi Zero OK et MR110
  muet → `Hop.WIRELESS` ; ping OK et `authorize()` KO → `Hop.DEVICE` ; jamais
  joignable depuis cette instance → `Hop.ROUTE` (C8).
- `get_lte_status()` complet → mapping correct de tous les champs.
- `get_lte_status()` partiel (champs manquants, comme relevé au spike) → champs
  `None`, readiness dégradée proprement, **pas de `KeyError`**.
- Readiness : SIM KO → `DEGRADED` + raison ; RSRP sous seuil → `DEGRADED` +
  raison chiffrée ; tout OK → `OK` ; champ absent → **n'entraîne pas** `DEGRADED`.
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
  `usg.py` — le cœur mono-cible n'est pas touché en phase A
