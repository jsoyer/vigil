# Sprint 4 — Documentation et release 2.3.0

> **Mise à jour 2026-08-23** : version cible révisée de `1.10.0` à `2.3.0` —
> les releases 2.1.x (TP-Link) et 2.2.0 (Ntfy-first) sont sorties entre-temps.

- **PRD** : A2 — Exposition & Home Assistant (2026-08-20)
- **Dépend de** : Sprints 1, 2, 3
- **Bloque** : rien (dernier sprint d'A2)

## Contexte (autoportant)

A2 est fonctionnellement complet : quota, détection d'usage, dashboard,
métriques Prometheus labellisées, et intégration Home Assistant avec capteurs
par équipement et bouton de reboot armé.

Reste à livrer sur **4 instances** (Dijon master+slave, Nice master+slave) qui se
mettent à jour **automatiquement** depuis `main`.

A2 n'ajoute **aucune dépendance** (contrairement à A1) : le mécanisme
`pip install` de l'auto-updater, livré en A1, n'est pas sollicité ici. Le risque
de livraison porte donc surtout sur la documentation d'une nouvelle surface
d'attaque.

## Travail

- `README.md` :
  - section Home Assistant : entités publiées par équipement, `device_class` /
    `state_class`, et **le fonctionnement du bouton armé** — un opérateur qui
    presse un bouton sans effet et sans explication conclura à un bug ;
  - configuration du quota (forfait, seuil, jour de facturation) et des seuils
    d'usage ;
  - nouvelles métriques Prometheus labellisées, **et rappel explicite que les
    `usg_watchdog_*` existantes sont inchangées** (les utilisateurs de Grafana
    doivent pouvoir le lire, pas le déduire).
- `DEPLOY.md` :
  - **avertissement de sécurité sur le chemin de commande MQTT** : activer
    l'écoute ouvre une voie vers une action destructive. Le broker **doit** être
    authentifié ; sur un broker anonyme, laisser l'écoute désactivée. À écrire
    comme un avertissement, pas comme une note de bas de page ;
  - note de migration : A2 est transparente sans équipement déclaré ;
  - rappel du pré-requis 1.8.1 (identité MQTT) et de sa conséquence — **les
    entités HA ont été recréées**, les anciennes sont orphelines et se
    suppriment à la main.
- `CLAUDE.md` : intégration HA bidirectionnelle ; préciser que le moteur reste
  mono-cible jusqu'au PRD B.
- `docs/adr/0001-*.md` : statut → `Accepté` pour A1 + A2 une fois livré.

## Release

- Bump `VERSION` → 2.3.0 ; `dev` → PR → `main` ; tag `v2.3.0`.
- Ouvrir (ou mettre à jour) l'issue de suivi du **PRD B** — moteur multi-cible.
- Ouvrir une issue de suivi pour les **améliorations MQTT restantes** :
  `availability_topic` / LWT, et exposition du topic `{prefix}/state` déjà publié
  mais non déclaré en discovery.
  *(Le `device_class` / `state_class` / `retain` des 8 capteurs existants,
  initialement dans ce backlog, est traité au Sprint 3 — C14.)*

## Tests

- Suite complète verte, coverage ≥ 80 %.
- Aucun secret dans `/api/config`, `/api/state`, `/api/tplink/*`, les payloads
  MQTT, ni les logs.
- `python -c "import watchdog"` sans `tplinkrouterc6u` (C1, toujours actif).
- `/metrics` : métriques legacy sans label toujours présentes (C4).

## Critères d'acceptation

- [ ] README : entités HA, bouton armé expliqué, quota, métriques
- [ ] README : mention explicite que les métriques `usg_watchdog_*` sont inchangées
- [ ] DEPLOY : **avertissement de sécurité** sur le chemin de commande MQTT
- [ ] DEPLOY : note de migration + conséquence du bugfix 1.8.1 sur les entités HA
- [ ] `CLAUDE.md` à jour ; ADR-0001 passé à `Accepté`
- [ ] Issues ouvertes : PRD B, et améliorations MQTT hors périmètre
- [ ] Aucun secret exposé
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, VERSION = 2.3.0

## Frontières de fichiers

- **Modifier** : `README.md`, `DEPLOY.md`, `CLAUDE.md`, `VERSION`,
  `docs/adr/0001-multi-vendor-router-monitoring.md`
- **Lecture seule** : `src/` (aucun changement fonctionnel dans ce sprint)
