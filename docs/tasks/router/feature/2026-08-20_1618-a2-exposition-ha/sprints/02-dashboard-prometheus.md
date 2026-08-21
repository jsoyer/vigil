# Sprint 2 — Dashboard et métriques Prometheus

- **PRD** : A2 — Exposition & Home Assistant (2026-08-20)
- **Dépend de** : Sprint 1
- **Bloque** : Sprint 4

## Contexte (autoportant)

Les lignes de secours TP-Link sont pilotables (A1) et leur quota comme leur état
d'usage sont suivis (Sprint 1). Rien n'est encore **visible passivement** : il
faut taper une commande.

Deux consommateurs existants à ne pas casser :

- `src/dashboard.py` — HTML/CSS intégré, **zéro dépendance JS externe**,
  responsive mobile-first, dark mode. Contraintes structurantes du projet.
- `src/metrics.py` — les métriques `usg_watchdog_*` sont consommées par des
  **dashboards Grafana et des règles d'alerte existants**.

## Objectifs

Rendre l'état des équipements lisible d'un coup d'œil, et historisable.

## Travail

### 2.1 Dashboard

- Une carte par équipement TP-Link déclaré, **à côté** de l'affichage USG
  existant — sans le modifier.
- **Badge de readiness** explicite : prêt / dégradé / inconnu. C'est
  l'information qu'on vient chercher en priorité sur un lien de secours.
- Quand ça ne va pas, afficher **le saut en panne** (pont Pi Zero / lien sans fil
  / routeur / route absente), pas seulement « injoignable ». Sur une panne du
  pont, rester prudent sur la cause : le Pi Zero est alimenté en PoE, ça peut
  être le Pi, son port de switch, le budget PoE ou le câble.
- Bloc 4G : RSRP / RSRQ / SNR / type de réseau / SIM / opérateur.
- Bloc quota : conso du cycle, % du forfait, prochain reset.
- Bandeau visible quand un secours **est en service**, distinct de **saturé**.
- **Aucun équipement déclaré → rendu strictement inchangé.**

### 2.2 Prometheus

- **C4 — legacy préservé, non négociable.** Les métriques `usg_watchdog_*`
  existantes restent émises **exactement à l'identique, sans label ajouté**.
  Ajouter un label à une métrique existante casse silencieusement les requêtes
  Grafana et les règles d'alerte qui la consomment — le symptôme n'est pas une
  erreur, c'est une courbe qui devient vide.
- **Ajouter à côté** une famille labellisée par équipement : rsrp, rsrq, snr,
  readiness (numérisée), data utilisée, % de quota, débits rx/tx, état d'usage,
  joignabilité par saut, RTT du saut vers le routeur.

## Tests

- Rendu du dashboard avec 1 puis 2 équipements ; badge de readiness ; **saut en
  panne affiché** ; bandeau d'usage ; distinction en service / saturé.
- Rendu **sans** équipement déclaré : strictement identique à l'existant.
- **C4** : `/metrics` contient toujours les `usg_watchdog_*` **sans label** —
  assertion explicite **par métrique legacy**, pas un test global.
- Métriques labellisées présentes et correctement valuées avec 2 équipements.
- Aucun secret dans le rendu du dashboard.

## Critères d'acceptation

- [ ] Carte par équipement : badge readiness, saut en panne, bloc 4G, bloc quota
- [ ] Bandeau d'usage, avec « en service » et « saturé » distincts
- [ ] Dashboard sans équipement déclaré : rendu inchangé
- [ ] **C4 vérifié métrique par métrique** : legacy sans label toujours présent
- [ ] Métriques labellisées ajoutées
- [ ] Zéro dépendance JS externe, responsive, dark mode conservés
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Modifier** : `src/dashboard.py`, `src/metrics.py`
- **Lecture seule** : `src/managed_devices.py`, `src/drivers/`, `src/http_server.py`
- **Interdit** : `watchdog.py`, `state.py`, `peer.py`, `mqtt_publisher.py`
- **Contrats partagés** : noms des métriques Prometheus — interface publique de
  fait, consommée par Grafana
