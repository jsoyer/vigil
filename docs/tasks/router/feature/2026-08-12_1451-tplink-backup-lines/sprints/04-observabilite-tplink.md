# Sprint 4 — Observabilité : dashboard, Prometheus, quota, usage du secours

- **PRD** : Lignes de secours TP-Link MR110 — phase A (management) — 2026-08-12
- **Dépend de** : Sprints 1, 2, 3
- **Bloque** : Sprint 5

## Contexte (autoportant)

Les équipements TP-Link sont désormais déclarables et pilotables par l'opérateur
(API `/api/tplink/*` + commandes Telegram `/lte`, Sprint 3), via
`src/managed_devices.py` qui instancie un `TplinkDriver` par équipement.

Il reste à les rendre **visibles sans avoir à taper une commande** : dashboard,
Prometheus, et deux informations qui ne se déduisent pas d'une lecture isolée —
la **conso de data sur le cycle de facturation** et le fait que le secours soit
**en train de servir**.

Contraintes de production à ne pas casser : le dashboard est en HTML/CSS
intégré, **zéro dépendance JS externe**, responsive mobile-first, dark mode. Les
métriques `usg_watchdog_*` sont consommées par des dashboards Grafana et des
règles d'alerte existantes.

## Objectifs

1. Suivi du quota data par SIM, robuste aux resets de compteur.
2. Détection de l'**usage** du secours.
3. Dashboard + Prometheus.

## Travail

### 4.1 Quota data (`src/history.py` + `src/managed_devices.py`)

- Source : `data_used_bytes` (compteur `total_statistics` du routeur).
- Config par équipement : volume du forfait, seuil d'alerte (% du forfait),
  **jour de reset de facturation**.
- **Détection de reset du compteur (le point délicat)** : le compteur du routeur
  repart de zéro à un reboot, et selon le firmware. Une **décroissance** entre
  deux relevés doit être interprétée comme un reset, **jamais** comme une conso
  négative. La conso du cycle est maintenue côté watchdog par accumulation de
  deltas positifs, pas déduite naïvement du compteur brut.
- Persistance via le mécanisme d'historique existant, pour survivre à un
  redémarrage du service.
- Sortie : conso du cycle, % du forfait, date du prochain reset.

### 4.2 Détection de l'usage du secours

**Hypothèse H1 du PRD** : le Pi Zero est un pont de management, il ne route pas
le trafic de production. Le watchdog ne peut donc **pas** observer la bascule
depuis le lien principal — l'approche « WAN2 de l'USG via `multiwan.py` » ne
s'applique pas tant que le MR n'est pas câblé sur le WAN2 (évolution prévue, non
court terme).

**Conception retenue** : détecter l'usage **depuis le MR110 lui-même** —
`rx_speed_bps` / `tx_speed_bps` non nuls au-delà d'un seuil, clients associés,
conso qui décolle. Ce signal vaut **quel que soit** le mécanisme de bascule, y
compris manuel.

- Événement `tplink_in_use` / `tplink_idle` + notification au **changement**
  d'état, jamais à chaque cycle.
- C'est une détection *a posteriori* (« le secours sert »), pas une détection
  d'événement de bascule. **Le documenter comme tel** dans le message : ne pas
  laisser croire à l'opérateur qu'on a vu le lien principal tomber.
- Seuil configurable, avec anti-rebond (un pic isolé de trafic de management ne
  doit pas déclencher l'alerte).
- **Calibrer sur du LTE Cat 4** (~150 Mb/s descendants, ~50 montants en
  théorique) : les seuils se raisonnent à cet ordre de grandeur, pas à celui du
  lien principal. Trois états valent la peine d'être distingués — inactif, en
  service, **saturé** : un secours qui plafonne est une information différente
  d'un secours qui sert. Le plafond de **32 appareils** du MR110 est l'autre
  borne utile côté `clients_total`.

### 4.3 Dashboard (`src/dashboard.py`)

- Une carte par équipement TP-Link déclaré, **à côté** de l'affichage USG
  existant — sans le modifier.
- Badge de readiness explicite : **prêt / dégradé / inconnu**. C'est
  l'information qu'on vient chercher en priorité sur un lien de secours.
- Quand ça ne va pas, afficher **le saut en panne** (Pi Zero / WiFi / routeur /
  route absente) — pas seulement « injoignable ».
- Bloc 4G : RSRP / RSRQ / SNR / type de réseau / SIM / opérateur.
- Bloc quota : conso du cycle, % du forfait, prochain reset.
- Bandeau visible quand un secours **est en train de servir**.
- Contraintes conservées : zéro dépendance JS externe, responsive mobile-first,
  dark mode.

### 4.4 Prometheus (`src/metrics.py`)

- **C4 — legacy préservé, non négociable** : les métriques `usg_watchdog_*`
  existantes restent émises **exactement à l'identique, sans label ajouté**.
  Ajouter un label à une métrique existante casse silencieusement les requêtes
  Grafana et les règles d'alerte qui la consomment.
- **Ajouter à côté** une famille dédiée, labellisée par équipement : rsrp, rsrq,
  snr, readiness (numérisée), data utilisée, % de quota, débit rx/tx,
  joignabilité par saut, RTT du saut WiFi.

### 4.5 Notifications (`src/messages.py`, `src/notifier/`)

- Structure existante conservée : quoi / pourquoi / quoi faire.
- Chaque message porte le **label de l'équipement**.
- Nouveaux messages : quota franchi, secours en cours d'utilisation, secours
  redevenu inactif. Les raisons de dégradation sont **chiffrées** (quel critère,
  quelle valeur, quel seuil).
- **Anti-spam** : notifier les **changements d'état**, pas chaque cycle. Un
  secours dégradé pendant deux jours ne doit pas produire deux jours d'alertes.

> L'alerting automatique sur la readiness (secours dégradé / redevenu prêt) et
> son intégration au scoring appartiennent à la **phase B**. Ici, on notifie sur
> le quota et l'usage, et on **affiche** la readiness.

## Tests

- Quota : conso croissante → % correct ; **compteur qui décroît → traité comme
  reset**, pas comme conso négative ; franchissement du jour de facturation →
  nouveau cycle ; persistance après redémarrage simulé.
- Usage : débit au-dessus du seuil → `tplink_in_use` ; pic isolé → **pas**
  d'événement (anti-rebond) ; retour à zéro → `tplink_idle` ; maintien en usage
  sur 10 cycles → **une seule** notification.
- **C4** : `/metrics` contient toujours les `usg_watchdog_*` **sans label**, en
  plus des métriques labellisées (assertion explicite sur chaque métrique legacy).
- Dashboard : rendu avec 1 et 2 équipements ; badge de readiness ; **saut en
  panne affiché** ; bandeau d'usage ; rendu **sans** équipement déclaré
  strictement identique à aujourd'hui.
- Aucun secret dans le rendu du dashboard.

## Critères d'acceptation

- [ ] Quota : conso, %, jour de reset, **détection de reset de compteur**,
      persistant après redémarrage
- [ ] Usage du secours détecté avec anti-rebond → événement + notification au
      changement
- [ ] Dashboard : carte par équipement, badge readiness, **saut en panne**,
      bloc 4G, bloc quota, bandeau d'usage
- [ ] Dashboard **sans** équipement déclaré : rendu inchangé
- [ ] **C4** vérifié : métriques legacy sans label toujours présentes
- [ ] Métriques labellisées ajoutées (4G + qualité du chemin d'audit)
- [ ] Notifications sur **changement** d'état, avec label et raisons chiffrées
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Créer** : `tests/test_tplink_quota.py`
- **Modifier** : `src/dashboard.py`, `src/metrics.py`, `src/messages.py`,
  `src/history.py`, `src/managed_devices.py`, `src/notifier/`, `src/events.py`
- **Lecture seule** : `src/drivers/`, `src/http_server.py`
- **Interdit** : `watchdog.py`, `state.py`, `peer.py`, `multiwan.py`
- **Contrats partagés** : noms des métriques Prometheus — interface publique de
  fait, consommée par Grafana
