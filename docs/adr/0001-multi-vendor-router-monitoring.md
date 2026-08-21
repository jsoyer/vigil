# ADR-0001 — Surveillance multi-vendor : abstraction driver + moteur multi-cible

- **Statut** : Proposé — **amendé les 2026-08-12 et 2026-08-20** (voir § Amendement en fin de document)
- **Date** : 2026-06-26
- **Décideurs** : Jerome Soyer
- **Version projet au moment de la décision** : 1.8.0
- **Tickets liés** : (à créer — `feat: support routeurs TP-Link 4G`)

---

## Contexte

USG Watchdog surveille **un seul** routeur (un USG Ubiquiti) : il ping la
gateway + des cibles internet, calcule un score de défaillance, et redémarre le
USG via SSH (`paramiko`) quand le seuil est atteint.

De nouveaux routeurs **4G TP-Link** (série Archer MR : MR200 / MR400 / MR600 /
MR6400…) ont été ajoutés au parc. Ils sont sur des **sites/connexions
indépendants** (pas de relation de failover entre eux ni avec l'USG) et doivent
bénéficier du même service : reboot automatique sur perte de connexion +
remontée de métriques propres au 4G (RSRP, RSRQ, SNR, type réseau, état SIM,
opérateur, conso data).

La librairie Python **`tplinkrouterc6u`** gère nativement ces routeurs (auth
chiffrée, `reboot()`, `get_lte_status()`), ce qui évite de réimplémenter le
protocole web TP-Link.

### Contraintes issues du code actuel

Le couplage « mono-cible » est structurel, pas cosmétique :

| Fichier | Couplage mono-USG |
|---|---|
| `connectivity.py` | Lit `USG_IP` au niveau module ; trackers de latence **singletons** (`gateway_latency`, `internet_latency`) |
| `usg.py` | Lit `USG_IP`/`USG_USER`/`USG_SSH_KEY`… au niveau module ; action = SSH only |
| `state.py` | `WatchdogState` = **un** snapshot plat (score, cooldowns, ISP, latence) pour **un** device |
| `watchdog.py` | Boucle unique : 1 check → 1 score → 1 circuit-breaker → 1 reboot |
| `http_server.py`, `dashboard.py`, `metrics.py`, `messages.py` | Présupposent un device unique |

### Forces en présence

- **Sécurité/robustesse** (priorité 1-3 du système) : ne pas casser la
  surveillance USG existante en production.
- **Évolutivité** : demain d'autres vendors (MikroTik, autre TP-Link…).
- **Coût opérationnel** : éviter de multiplier les process/configs systemd.
- **Connectivité distante** : un seul Pi watchdog ne peut pas forcément router
  du trafic *à travers* le lien WAN de chaque site indépendant — il faut une
  stratégie de santé adaptée par vendor.
- **Licence** : `tplinkrouterc6u` est **GPLv3+**. Le projet n'a pas de fichier
  LICENSE (usage personnel / non distribué) → pas de conflit pratique
  aujourd'hui, mais à tracer si le projet devient distribué.

---

## Décision

Adopter **deux changements structurels combinés**, sans renommer le projet.

### 1. Abstraction `RouterDriver` (pattern Strategy / Protocol)

Introduire un contrat commun pour « piloter un routeur », indépendant du vendor :

```python
# src/drivers/_base.py
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class RouterHealth:
    """Santé d'un lien, telle qu'évaluée par le driver."""
    reachable: bool                 # le routeur lui-même répond
    internet_ok: bool               # le lien WAN porte du trafic
    rtt_ms: float | None = None
    detail: str = ""

@dataclass(frozen=True)
class RouterMetrics:
    """Métriques optionnelles, dépendantes du vendor (toutes nullable)."""
    cpu_usage: float | None = None        # USG (SNMP) + TP-Link
    mem_usage: float | None = None
    wan_ip: str | None = None
    clients_total: int | None = None
    # --- spécifique 4G/LTE ---
    network_type: str | None = None       # "4G LTE", "5G NR"…
    sim_status: str | None = None
    signal_bars: int | None = None
    rsrp: int | None = None
    rsrq: int | None = None
    snr: int | None = None
    isp_name: str | None = None
    data_used_bytes: int | None = None

class RouterDriver(Protocol):
    vendor: str                                   # "usg" | "tplink"
    def health(self) -> RouterHealth: ...         # never raise
    def metrics(self) -> RouterMetrics: ...       # never raise → champs None si indispo
    def reboot(self) -> bool: ...                 # never raise
    def test_connection(self) -> bool: ...        # diagnostic
```

Implémentations :

- **`UsgDriver`** — extrait le code existant de `usg.py` derrière l'interface.
  `health()` = ping ICMP (gateway + cibles internet, logique actuelle) ;
  `reboot()` = SSH `paramiko` existant ; `metrics()` = SNMP optionnel
  (`snmp_monitor.py`).
- **`TplinkDriver`** — encapsule `tplinkrouterc6u`. `reboot()` =
  `authorize()` → `reboot()` → `logout()` (try/finally, **session unique**) ;
  `health()` = `get_lte_status().connect_status` + reachability HTTP ;
  `metrics()` = mapping `LTEStatus` → `RouterMetrics` + `get_status()`.

**Stratégie de santé par driver (point clé) :** l'USG est local → ICMP
ping-through. Le TP-Link 4G peut être distant → la santé s'appuie sur l'**état
WAN auto-reporté** par le routeur (`connect_status`, `network_type`) + sa
joignabilité de management, et non sur du trafic ICMP routé à travers le lien.
Chaque driver décide comment évaluer `RouterHealth`.

### 2. Moteur multi-cible (un process, N cibles)

- Une cible surveillée = `MonitoredTarget` : `{ id, label, driver,
  score_state, circuit_breaker_state, latency_trackers, thresholds }`.
- `WatchdogState` devient **par cible** ; l'état global publié est un
  `dict[target_id -> WatchdogState]` (+ un agrégat). `connectivity.py` perd ses
  singletons module-level (trackers déplacés dans la cible).
- La boucle principale itère les cibles (séquentiel d'abord ; parallélisable
  plus tard). Chaque cible a son score, son circuit-breaker, ses cooldowns.
- **Config** : liste de cibles via env vars numérotées. **Rétro-compat
  obligatoire** : si aucune cible n'est déclarée, le système synthétise **une**
  cible USG à partir des `USG_*` actuels → déploiements existants inchangés.

```
# Cible historique (auto-synthétisée si TARGETS vide)
TARGET_0_TYPE=usg     TARGET_0_HOST=192.168.1.1   TARGET_0_LABEL="USG principal"
# Nouvelles cibles 4G
TARGET_1_TYPE=tplink  TARGET_1_HOST=192.168.2.1   TARGET_1_PASSWORD=… TARGET_1_LABEL="Site B 4G"
```

### 3. Nom du projet : inchangé

On **garde `usg-watchdog`**. TP-Link devient un driver parmi d'autres.
Justification : pas de rupture de packaging/systemd/auto-updater/tags git, et le
nom reste un identifiant historique. *Trigger de révision* : si ≥ 3 vendors ou
si le projet est publié/distribué, rouvrir la question du renommage (cf.
« Alternatives »).

---

## Alternatives considérées

### A. Multi-instance (N services systemd, 1 par routeur) — **rejeté**
Déployer un process watchdog par routeur.
- ➖ Lourd : N units systemd, N `.env`, N ports HTTP, N dashboards.
- ➖ La coordination peer (`peer.py`) modélise le **failover du même device**,
  pas des sites indépendants → sémantique inadaptée.
- ➖ Pas de vue agrégée native.
- ➕ Zéro refactor du cœur.
> Rejeté : le coût opérationnel et la sémantique peer ne collent pas à « sites
> indépendants ».

### B. Fork / branche par vendor — **rejeté**
Dupliquer le code pour TP-Link.
- ➖ Duplication massive, divergence garantie, double maintenance.
> Rejeté frontalement (anti-DRY).

### C. Driver abstraction + moteur multi-cible (un process) — **CHOISI**
- ➕ Un seul service, une seule config, une vue agrégée.
- ➕ Extensible (ajouter un vendor = un fichier driver).
- ➕ Sépare proprement « piloter un routeur » de « logique de scoring ».
- ➖ Refactor non trivial du cœur mono-cible (state, connectivity, boucle).
> Choisi : meilleur compromis évolutivité / coût opérationnel, aligné sur la
> contrainte « sites indépendants ».

### D. Renommer en `router-watchdog` maintenant — **reporté**
- ➕ Nom honnête vis-à-vis du multi-vendor.
- ➖ Casse tags git (`vX.Y.Z`), unit systemd, chemins `/opt/usg-watchdog`,
  auto-updater, docs. Risque > bénéfice pour l'instant.
> Reporté derrière un trigger explicite (≥3 vendors ou distribution publique).

---

## Conséquences

### Positives
- USG et TP-Link partagent scoring, circuit-breaker, notifications, dashboard,
  metrics — sans duplication.
- Ajout futur d'un vendor = implémenter `RouterDriver` uniquement.
- Métriques 4G (RSRP/RSRQ/SNR/SIM/conso) first-class.

### Négatives / risques
- **Refactor du cœur** : `state.py`, `connectivity.py`, `watchdog.py`,
  `http_server.py`, `dashboard.py`, `metrics.py` touchés. Mitigation :
  rétro-compat mono-USG verrouillée par tests de non-régression.
- **Nouvelle dépendance** `tplinkrouterc6u` (+ `pycryptodome`, `macaddress`).
  Mitigation : pin de version, imports paresseux (driver TP-Link chargé seulement
  si une cible `tplink` existe), `never raise`.
- **Licence GPLv3+** de la lib. Aujourd'hui sans impact (projet non distribué,
  pas de LICENSE). *À tracer* si distribution future. Échappatoire possible :
  isoler le driver TP-Link dans un sous-process si la contrainte devient réelle.
- **Fragilité TP-Link** : session unique (lock si autre admin connecté),
  mismatch cipher CBC/GCM selon firmware, champs signal parfois absents selon
  firmware. Mitigation : `TplinkRouterProvider.get_client()` (auto-détection),
  try/finally `logout()`, champs métriques nullable.
- **Sécurité secrets** : mots de passe TP-Link en clair dans `.env`
  (la lib n'accepte pas de hash pour les MR). Mitigation : `.env` chmod 600
  (déjà la convention projet), jamais loggé.

### Neutres
- Endpoints API et format de state évoluent vers le multi-cible (versionné).
- Bot Telegram / rapports devront prendre un argument « cible ».

---

## Vérification (machine-checkable)

- `pytest` : un test de non-régression prouve qu'avec **aucune** `TARGET_*`,
  le comportement mono-USG est identique (même score, même reboot).
- `pytest tests/test_drivers.py` : `UsgDriver` et `TplinkDriver` respectent le
  contrat `RouterDriver` (health/metrics/reboot ne lèvent jamais).
- Coverage ≥ 80 % maintenu.

---

## Références
- Lib : `tplinkrouterc6u` 5.24.0 — https://github.com/AlexandrErohin/TP-Link-Archer-C6U (GPLv3+, Python ≥3.10, deps `requests`/`pycryptodome`/`macaddress`)
- `LTEStatus` : `rsrp`, `rsrq`, `snr`, `network_type`(+`network_type_info`), `sim_status`(+`sim_status_info`), `sig_level`, `isp_name`, `total_statistics`, `cur_rx_speed`, `cur_tx_speed`, `sms_unread_count`
- Clients 4G : `TPLinkMRClient` (CBC) / `TPLinkMRClientGCM` (GCM) / `TPLinkMR200Client` / `TPLinkMR6400v7Client`
- PRD associés (2026-08-20) :
  - `docs/tasks/router/bugfix/2026-08-20_1618-mqtt-instance-identity.md` (1.8.1, pré-requis)
  - `docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/spec.md` (1.9.0)
  - `docs/tasks/router/feature/2026-08-20_1618-a2-exposition-ha/spec.md` (1.10.0)
  - PRD B — moteur multi-cible (~1.11.0), à rédiger
  - *superseded* : `2026-06-26_1200-multi-vendor-tplink.md`, `2026-08-12_1451-tplink-backup-lines/`

---

## Amendement — 2026-08-12

Trois faits établis après rédaction invalident des prémisses de cet ADR. La
**décision de fond ne change pas** (abstraction `RouterDriver` + moteur
multi-cible, nom du projet inchangé), mais son cadrage et ses risques évoluent.

### A1 — Les TP-Link sont des lignes de SECOURS, pas des liens principaux

Le § Contexte affirme : *« Ils sont sur des sites/connexions indépendants (pas
de relation de failover) »*. **Faux.** Les MR110 de Dijon et Nice sont des
**standby** derrière le lien principal de chaque site.

Conséquences :

- Introduction d'un **rôle de cible** dans le contrat : `primary` (scoring +
  circuit-breaker + reboot automatique — comportement USG actuel) et `backup`
  (**audit uniquement, jamais de reboot automatique**).
- Un standby au repos ne doit pas être interprété comme dégradé : la notion
  pertinente n'est pas le score de connectivité mais la **readiness**
  (`OK` / `DEGRADED` / `UNKNOWN`) — SIM, attach LTE, seuils de signal.
- Rebooter automatiquement un secours **pendant qu'il porte le trafic**
  couperait le site. C'est le risque le plus grave introduit par la feature, et
  il est éliminé structurellement (pas par configuration).
- Ajout au périmètre : **suivi du quota data** par SIM (un forfait épuisé rend
  le secours inutile) et **détection de bascule** sur secours.

### A2 — 4 instances en paires HA, pas un watchdog central

Le § Forces évoque un watchdog potentiellement distant des routeurs. **La
topologie réelle** est : Dijon (master + slave) et Nice (master + slave), chaque
instance **en LAN** avec ses cibles.

Conséquences :

- Le problème de joignabilité distante **disparaît** : chaque instance parle à
  son MR110 en local.
- Un **nouveau risque, absent de l'ADR initial, apparaît** : les routeurs MR
  n'acceptent **qu'une seule session d'administration**. Master et slave d'un
  même site interrogeant le même MR110 se déconnecteraient mutuellement en
  boucle. → règle d'**exclusivité de polling** : une seule instance interroge la
  cible `backup`, l'autre republie l'état du peer avec l'âge de la donnée.
- Le rollout 1.8 → 1.9 **n'est pas atomique** sur une paire HA : la contrainte
  de rétro-compatibilité de `/api/state` (C3) passe de « prudence » à
  « obligation ».

### A3 — Le modèle réel est un TL-MR110 indoor, non testé par la lib

Le § Contexte cite la « série Archer MR (MR200/MR400/MR600/MR6400) ». Le parc
réel utilise des **TL-MR110 indoor N300**. La liste des modèles testés de
`tplinkrouterc6u` contient le **TL-MR110-Outdoor v1.0**, ainsi que TL-MR100 /
MR105 / MR150 / MR6400 / Archer MR200/400/550/600 — **mais pas** le TL-MR110
indoor.

Conséquences :

- Le support n'est **pas acquis**. Un **spike go/no-go sur matériel réel**
  devient bloquant avant toute écriture de driver, avec plan B écrit (audit par
  joignabilité seule, sans métriques LTE).
- Le pin de version de la lib est décidé **à l'issue du spike**, sur la version
  qui aura réellement fonctionné — et non choisi a priori.

### A4 — Aucun chemin réseau vers les MR110 ; pont Pi Zero

Le § Contexte suppose des routeurs joignables. **Aucun MR110 n'est sur le LAN
d'un site.** Chacun est sur **son propre réseau WiFi**, et le seul point de
contact est un **Pi Zero 2 W** par site : `eth0` sur le LAN, `wlan0` associé au
WiFi du MR110. Il sert de **pont de management uniquement** — il ne route pas le
trafic de production.

**Décision — C7 : routage + NAT sur le Pi Zero, aucun code dessus.** IP
forwarding + NAT sur le Pi Zero, route statique posée **sur les hôtes watchdog
uniquement** (ni sur l'USG, ni en DHCP).

Alternatives écartées :

- *Agent HTTP sur le Pi Zero* — règle nativement l'exclusivité de session, mais
  ajoute un composant à déployer, mettre à jour et sécuriser sur deux sites.
- *Exécution SSH sur le Pi Zero* — pas de changement réseau, mais impose
  d'installer et de maintenir la lib TP-Link sur le Pi Zero, et de versionner un
  script distant.
- *Instance watchdog sur le Pi Zero* — réutilise tout l'existant, mais fait du
  Pi Zero un cinquième et sixième nœud à opérer.

Le routage l'emporte parce qu'il laisse **tout le code sur les hôtes watchdog** :
le driver parle à une IP et ignore l'existence du Pi Zero.

**Le pont Pi Zero est conservé** (décision du 2026-08-12), y compris après le
câblage sur WAN2 (A6). Deux raisons, au-delà de la préférence exprimée :

- il **préserve C7** — l'admin du MR110 n'est joignable que depuis les hôtes
  watchdog, via une route dédiée ; un raccordement direct du MR110 au LAN
  l'exposerait à tout le site ;
- il constitue un **chemin de management hors bande**, indépendant de l'USG. Une
  fois le MR sur le WAN2, la voie naturelle pour l'atteindre passerait par l'USG,
  c'est-à-dire par l'équipement dont on surveille la défaillance. Le pont permet
  d'interroger et de redémarrer le secours **pendant** une panne de l'USG — le
  moment précis où on en a besoin.

Reste ouverte, et tranchée au Sprint 1 site par site : la **nature du saut**
Pi Zero ↔ MR110 (WiFi 2,4 GHz actuel, ou Ethernet si les deux équipements sont
adjacents — le MR110 a 2 ports LAN). Le Pi Zero étant alimenté en **PoE**, sa
position est figée par le câblage, alors que celle du MR110 l'est par la
réception 4G : l'adjacence ne se décrète pas, elle se relève.

Conséquences :

- Le chemin comporte **trois sauts** (watchdog → Pi Zero → WiFi → MR110). Une
  sonde qui dit seulement « injoignable » est inutilisable → **attribution de
  panne par saut** (`Hop.BRIDGE` / `WIRELESS` / `DEVICE` / `ROUTE`) intégrée au
  contrat `RouterHealth`.
- Le **Pi Zero devient un SPOF** du chemin d'audit, et le lien WiFi un point de
  défaillance silencieux : tous deux sondés explicitement.
- **C8** : une route ou un NAT absents doivent être rapportés comme défaut de
  configuration, jamais comme « secours HS » — sinon la première mise à jour
  système qui efface une route lève une fausse alerte critique.
- Risque de sécurité à contenir : poser la route côté USG exposerait
  l'interface d'administration du MR110 à tout le LAN du site.

### A5 — Livraison en deux phases ; le management d'abord

Le besoin prioritaire exprimé est d'avoir des **commandes de management**, pas
l'audit automatique. L'ADR initial poussait directement au refactor du cœur
mono-cible, qui est la partie la plus risquée.

**Décision** : livrer en deux phases.

- **Phase A (1.9.0)** — chemin réseau, `TplinkDriver`, commandes opérateur (API
  + Telegram), dashboard, Prometheus, quota, usage. Les TP-Link y sont des
  **équipements pilotables déclarés**, pas des cibles de la boucle de
  surveillance. **`watchdog.py` et `state.py` ne sont pas modifiés** → risque de
  régression USG quasi nul, et C3 satisfaite par construction.
- **Phase B (~1.10.0)** — moteur multi-cible, `UsgDriver`, rôles intégrés au
  scoring, alerting automatique sur la readiness, exclusivité de polling complète.

La phase A livrant déjà l'essentiel de la valeur, la phase B pourra être jugée
sur ses propres mérites — **y compris la décision de ne pas la faire**.

### A6 — Évolution prévue : câblage du MR sur le WAN2 de l'USG

Souhaité à terme, **hors court terme**. Impact sur le code : **nul** — c'est
exactement ce que garantit C7. Le jour du câblage, on supprime la route statique
et le NAT ; driver, commandes, dashboard et métriques continuent à l'identique.

Ce que ce câblage apporterait en plus : disparition du Pi Zero et du saut WiFi
du chemin d'audit (deux points de défaillance en moins), et exploitation de
`src/multiwan.py` (déjà présent) pour une **vraie détection d'événement de
bascule** — à ajouter **en plus** de la détection d'usage, pas à la place.

*Modèle* : **MR-110** ici aussi (confirmé le 2026-08-12). L'évolution WAN2
repose donc sur le même matériel que la phase A, et hérite du même gate de
compatibilité : il n'existe aucun scénario de repli où le matériel serait un
modèle déjà couvert par la lib.

### A7 — Intégration Home Assistant : ouverture d'un chemin de commande entrant

Décision du 2026-08-20 : l'intégration Home Assistant comporte **des capteurs
et un bouton de reboot**, et non des capteurs seuls.

C'est un changement de nature, pas d'ampleur. `src/mqtt_publisher.py` est
aujourd'hui strictement **sortant** : aucun `subscribe`, aucun `on_message`,
aucun `command_topic`. Ajouter un bouton crée le **premier chemin de commande
entrant du projet**, vers une action destructive. Quiconque peut publier sur le
broker peut déclencher un reboot.

Deux gardes en découlent :

- **C9** — l'écoute est désactivable indépendamment de la publication, le
  parsing des messages est strict, et le broker **doit** être authentifié
  (`MQTT_USERNAME` / `MQTT_PASSWORD` existent déjà). Sur un broker anonyme,
  l'écoute reste désactivée.
- **C10** — aucun échec silencieux : toute commande reçue produit un résultat
  observable dans une entité dédiée, refus compris, avec son motif. Un `button`
  Home Assistant n'a pas de retour visuel natif ; sans ça, un refus est
  indistinguable d'un message perdu.

**Confirmation** : la confirmation en deux temps retenue pour Telegram (jeton
court, usage unique) n'a pas d'équivalent dans une interface Home Assistant — un
bouton se presse en un geste. Pattern retenu : une entité *switch* « armer »,
à désarmement automatique, sans laquelle le bouton refuse de s'exécuter.

**L'état « en service » est remonté, pas bloquant.** On reboote parfois
précisément un équipement qui dysfonctionne pendant qu'il sert. Le refuser
serait paternaliste ; le taire serait dangereux. L'information est publiée, la
décision reste à l'opérateur.

### A8 — Découpage en trois livrables, précédés d'un bugfix

Le découpage en deux phases (A5) ne contenait plus la matière une fois A7 décidé
et le code analysé. Trois briques supposées présentes n'existent pas : le
dispatcher Telegram ne parse **aucun argument** (`telegram_bot.py:48`), aucune
**confirmation côté serveur** n'existe (seul précédent : un `confirm()` JS dans
le dashboard), et MQTT est en **lecture seule**.

Découpage retenu :

| Livrable | Version | Contenu |
|---|---|---|
| **Bugfix** | 1.8.1 | Identité MQTT par instance (bug existant, cf. A9) |
| **A1 — Pilotage** | 1.9.0 | Chemin réseau, `TplinkDriver`, sonde étagée, commandes API + Telegram, masquage des secrets |
| **A2 — Exposition** | 1.10.0 | Quota, usage, dashboard, Prometheus, Home Assistant |
| **PRD B — Moteur** | ~1.11.0 | Multi-cible, `UsgDriver`, rôles dans le scoring, C5 complète |

A1 et A2 ne modifient **ni `watchdog.py` ni `state.py`** — invariant vérifiable
par `git diff`. Le refactor risqué reste isolé dans le PRD B, jugeable sur ses
propres mérites, **y compris la décision de ne pas le faire**.

### A9 — Bug d'identité MQTT découvert pendant la planification

`src/mqtt_publisher.py` code en dur `identifiers: ["usg_watchdog"]` (`:29-34`) et
`unique_id: f"usg_watchdog_{sensor_id}"` (`:51`), alors que le projet supporte
explicitement le multi-instance (`INSTANCE_PRIORITY`, `PEER_IP`). **Les 4
instances de production écrasent donc le même device Home Assistant et les mêmes
entités.**

Traité en **patch séparé (1.8.1)**, bloquant pour A2 : ajouter des entités par
équipement sur une identité déjà en collision rendrait le résultat intestable.
Conséquence assumée et à documenter — changer les `unique_id` fait que Home
Assistant **recrée les entités** ; les anciennes deviennent orphelines.

### A10 — Masquage des secrets

Le projet n'a **aucun mécanisme de masquage** : 11 secrets lus en
`os.getenv(X, "")`, et une protection reposant sur **trois whitelists
divergentes** (`http_server.py:290-311`, `:356-366`, `:384-391`) construites à la
main. Les mots de passe TP-Link seront le douzième secret.

Décision : ajouter un **helper de redaction réutilisable** sur motif de nom
(`*_PASSWORD`, `*_TOKEN`, `*_KEY`, `*_WEBHOOK_URL`), appliqué aux logs — bénéfice
sur les 11 secrets existants, pas seulement TP-Link.

Limites **documentées plutôt que masquées** : le mot de passe TP-Link existe en
clair (la lib n'accepte pas de hash sur les MR), en **4 copies** (master + slave
× 2 sites), sans rotation outillée.

### A11 — Sonde active de bout en bout ; C7 assouplie

**Défaut corrigé.** Les amendements précédents établissaient `internet_ok` à
partir de `connect_status` / `network_type`, **auto-reportés par le routeur**,
en justifiant le refus d'un test actif par la consommation de forfait.

Ce raisonnement était faux sur les deux plans :

- **Attaché ≠ data qui passe.** Un MR110 peut être attaché au réseau sans data
  utilisable (forfait épuisé, APN cassé, blocage opérateur). Le routeur se
  déclare connecté, et le plan aurait affiché « secours prêt » — un **faux OK
  sur la seule chose qui compte** pour une ligne de secours.
- **Le coût était surestimé d'un facteur mille.** Une requête légère pèse ~1 Ko ;
  en horaire, ~0,7 Mo/mois. Négligeable devant n'importe quel forfait.

**Décision** : ajouter une **sonde active de bout en bout**, à la demande en A1
(`/lte check`), périodique et **opt-in** en A2. `attached` et `internet_ok`
deviennent deux notions distinctes ; sans sonde récente, `internet_ok` vaut
`None` — **jamais `True` par défaut**.

**Chemin d'exécution** : commande **SSH ponctuelle sur le Pi Zero**, seul point
du chemin situé derrière le MR110. Alternative écartée : une route source sur
les hôtes watchdog, plus propre vis-à-vis de C7 mais exigeant une configuration
réseau fine, avec le risque qu'une règle mal posée envoie du trafic de
production sur un lien facturé au volume.

**C7 est assouplie en conséquence** : elle interdisait *tout* code sur le Pi
Zero, elle interdit désormais tout ce qui y est **déployé** — dépendance,
service, fichier du projet. Une commande ponctuelle n'installe rien et ne laisse
rien derrière elle ; le Pi Zero reste un équipement d'infrastructure, pas un
composant applicatif.

**C11 — la sonde porte sa preuve de chemin.** Le Pi Zero est **à double
rattachement** : `eth0` vers le LAN du site (donc la fibre), `wlan0` vers le
MR110. Une première version de cette contrainte se contentait de **lier la
requête à `wlan0`. C'était insuffisant** : le binding ne garantit pas le chemin
réellement emprunté — l'option peut ne pas être honorée par l'outil, une règle
de routage peut changer, la résolution DNS peut sortir par l'autre patte. Et une
sonde qui fuit vers la fibre **réussit**, donc signale un secours sain quoi
qu'il arrive. Vérifier la commande émise ne teste que la commande, pas le trajet.

La sonde doit donc **prouver son chemin dans son résultat**. Deux preuves
indépendantes, exigées ensemble :

1. **IP publique observée ≠ IP publique du site.** La sonde renvoie l'IP vue
   depuis le Pi Zero ; le watchdog la compare à celle du site via
   `get_public_ip()` (`src/ddns_cloudflare.py:72`, déjà présent, endpoints de
   repli inclus). Identiques ⇒ fuite par la fibre. Le CGNAT mobile n'est pas un
   obstacle : on cherche une différence, pas une correspondance avec
   `wan_ipv4_addr`.
2. **Compteurs de trafic du MR110 en mouvement** pendant la sonde
   (`total_statistics` avant/après). Figés ⇒ la requête n'a pas traversé le
   routeur, quelle que soit l'IP renvoyée.

Isolée, chaque preuve est contournable ; ensemble, elles rendent une fuite
**détectable au lieu de silencieuse**. Le résultat de la sonde passe donc à
quatre valeurs : `OK`, `FAIL`, `LEAK` (fuite — **défaut de configuration**, même
traitement que `Hop.ROUTE` en C8, jamais une panne du secours) et `UNKNOWN`.

**Propriété utile** : le faux OK n'est possible que si la fibre est *up* —
c'est-à-dire précisément quand la référence existe pour le détecter. Fibre down,
une fuite échoue au lieu de mentir. Conserver néanmoins la dernière IP publique
connue du site en repli.

**Sur Tether et l'API cloud TP-Link — écartés.** La demande initiale était de
récupérer l'état « hors ligne » affiché par l'application Tether.
`tplinkrouterc6u` parle à l'API locale et n'expose aucun champ cloud (vérifié :
ni `Status` ni `LTEStatus` n'en contiennent). Les voies alternatives ont été
examinées et **toutes écartées** :

| Voie | Verdict |
|---|---|
| API cloud officielle | **Inexistante** pour les routeurs — TP-Link n'en publie aucune |
| Bibliothèques cloud rétro-ingénierées (`tplink-cloud-api`, équivalent npm) | Visent les **équipements domotiques Kasa** (prises, ampoules), pas les routeurs |
| Protocole Tether rétro-ingénieré (`tmpcli`) | **Risque de briquer le routeur**, signalé par le projet lui-même. Disqualifiant sur un site distant |
| Gestion distante via TP-Link ID | Suppose de lier un compte cloud (support MR110 incertain) et de stocker des identifiants TP-Link ID sur 4 instances |

Au-delà de la faisabilité, le signal lui-même serait **inférieur à la sonde** :
binaire, sans cause, et dépendant de l'infrastructure TP-Link — une panne de
leur cloud deviendrait une fausse alerte chez nous. La sonde active dit
*pourquoi* le lien ne marche pas, sans dépendance externe.

**Une piste locale reste ouverte** : si le firmware expose son état de liaison
cloud dans son **API locale**, on obtiendrait « Tether m'afficherait hors ligne »
gratuitement, sans appeler le cloud ni stocker d'identifiants. Ajouté au spike
du Sprint 1 comme recherche opportuniste (coût nul, les réponses brutes sont
déjà capturées). Si rien n'existe, la sonde reste la source de vérité.

### A12 — Un routeur = un device Home Assistant ; exclusivité de polling remontée dans A2

Décision du 2026-08-21, déclenchée par la question « quels capteurs remonte-t-on
dans HA ? ».

**Le problème.** Le bugfix 1.8.1 (A9) donne une identité MQTT **par instance** —
correct pour les capteurs du watchdog, qui sont bien quatre watchdogs distincts.
Mais un MR110 est **un équipement physique vu par deux instances**. Indexer son
device HA sur l'instance produirait deux devices pour un seul routeur ;
l'indexer sur l'équipement seul ferait publier les deux instances dans les mêmes
entités — la collision que le patch corrige, réintroduite ailleurs.

**Décision** : device indexé sur **site + équipement**, publication réservée à
**une seule instance élue**.

**Conséquence non anticipée : C5 remonte de PRD B vers A2.** Réserver la
publication ne suffit pas — si l'instance non publiante continuait d'interroger
le routeur pour son propre dashboard, la contention de session admin
subsisterait. L'élection doit donc gouverner le **polling**, pas seulement la
publication : c'est C5 complète.

En y regardant, ce placement était de toute façon erroné. A1 n'interroge les
équipements **qu'à la demande** ; **A2 introduit le polling périodique** (quota,
usage, sonde, capteurs HA). Un routeur MR n'acceptant qu'une session
d'administration, la contention devenait certaine dès A2 — indépendamment de
Home Assistant. L'élection réutilise la priorité et `PEER_TAKEOVER_DELAY`
existants de `peer.py` ; l'instance non élue expose l'état du peer **avec l'âge
de la donnée**.

**C13 — stabilité de la liste d'entités.** La discovery HA est *retained* : des
entités qui apparaissent et disparaissent au fil des cycles cassent les
automatisations et trouent les historiques. La liste est figée **une fois**,
d'après les champs relevés par le spike sur ce firmware ; un champ ensuite
illisible passe `unavailable`, jamais dépublié — et **jamais publié à zéro**, un
zéro se confondant avec une vraie valeur. Même famille d'erreur que le faux `OK`
corrigé en A11.

**Capteurs retenus** : readiness, secours dégradé, lien attaché, résultat de
sonde, dernière sonde, RSRP/RSRQ/SNR, niveau de signal, type de réseau, état
SIM, opérateur, conso du cycle, % de forfait, prochain reset, débits rx/tx, état
d'usage, saut en panne, RTT, âge de la donnée. « Lien attaché » et « résultat de
sonde » restent **deux entités distinctes** : les confondre annulerait le
bénéfice de C11.

### A13 — Un seul device USG par site

Décision du 2026-08-21, prolongement direct de A12.

A12 a établi qu'un MR110 est un équipement physique unique et doit apparaître
comme **un** device Home Assistant, alimenté par une seule instance. Le même
raisonnement vaut pour l'USG : les 8 capteurs actuels sont publiés par les deux
instances d'un site, qui font donc apparaître **deux USG** là où il n'y en a
qu'un.

**Décision** : répartir les capteurs selon ce qu'ils **décrivent**.

| Device | Un par | Publié par | Capteurs |
|---|---|---|---|
| `USG <site>` | site | l'instance élue | `gateway`, `internet`, `gateway_rtt`, `internet_rtt` |
| `Watchdog <site> <rôle>` | instance | chaque instance | `score`, `status`, `reboots_today`, `uptime` |

La ligne de partage n'est pas arbitraire : les quatre premiers décrivent **l'état
de la ligne**, les quatre suivants décrivent **le watchdog qui l'observe**. Un
score qui diffère entre master et slave est normal ; un état de ligne qui diffère
est un symptôme.

**Compensation obligatoire.** Publier une seule vue de la ligne supprime la
possibilité de comparer les deux — ce qui servait, en creux, à repérer un
désaccord entre instances. `peer.py` détecte déjà cette divergence sans
l'exposer. Un `binary_sensor` *divergence* et un capteur *état du peer* sont
donc ajoutés sur le device watchdog. Le signal est restitué sous une forme
meilleure : une alerte explicite plutôt que deux courbes à comparer à l'œil. Sans
cette compensation, on supprimerait un signal de sécurité au nom de la cosmétique.

**Séquencement.** Cette bascule appartient à **A2**, pas au bugfix 1.8.1, bien
que celui-ci recrée déjà les entités et rendrait le changement « gratuit ». Des
entités indexées par site **sans publieur unique** feraient écrire les deux
instances dedans — le bug corrigé, reproduit ailleurs. L'élection (C12) n'existe
qu'à partir d'A2. Coût assumé : les 4 capteurs de ligne sont recréés une seconde
fois. L'alternative, faire entrer une élection de publieur dans un patch,
violerait la séparation bug/feature du projet.

### Ce qui reste inchangé

- Décision structurelle : abstraction `RouterDriver` + moteur multi-cible dans
  un seul process (alternatives A, B, D toujours rejetées/reportées) — le moteur
  multi-cible étant simplement **repoussé en phase B** (cf. A5).
- Contraintes de compatibilité production C1→C4 (import paresseux, `pip install`
  par l'auto-updater, `/api/state` rétro-compatible, métriques Prometheus
  legacy) : toutes vérifiées dans le code et toujours valides.
- **Nom du projet** : `usg-watchdog` conservé, renommage reporté. Confirmé
  explicitement le 2026-08-12 (« pas urgent »). Trigger de réouverture inchangé
  (≥ 3 vendors, ou distribution publique). Note ajoutée : le renommage devra se
  faire **en deux temps** (alias systemd + double émission des métriques, puis
  suppression une version plus tard), car le préfixe `usg_watchdog_*` est
  consommé par des dashboards Grafana existants et 4 instances se mettent à jour
  automatiquement.
