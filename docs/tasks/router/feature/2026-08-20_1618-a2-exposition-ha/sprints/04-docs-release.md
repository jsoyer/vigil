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

- [x] README : entités HA, bouton armé expliqué, quota, métriques — nouvelle
      section « Home Assistant : entités par équipement » (devices
      `vigil_<site>_tplink_<id>`, `USG <site>`, `Watchdog <instance>`,
      bouton armé, variables `SITE_ID`/`MQTT_COMMANDS_ENABLED`/
      `MQTT_ARM_TIMEOUT`, exemple quota 110 000 Mo / reset 27)
- [x] README : mention explicite que les métriques `usg_watchdog_*` sont
      inchangées — paragraphe « Nouveau en 2.3.0 » ajouté à la section
      Métriques Prometheus (16 séries `vigil_tplink_*` additives, legacy
      « à l'identique »)
- [x] DEPLOY : **avertissement de sécurité** sur le chemin de commande MQTT
      — bloc `> **Avertissement de sécurité — chemin de commande MQTT
      (C9)**` dans la nouvelle section « Migration vers 2.3.0 »
- [x] DEPLOY : note de migration + conséquence sur les entités HA — section
      « Entités Home Assistant recréées -- purge manuelle requise (C15) » :
      4 capteurs de ligne recréés/orphelins, 8 capteurs par instance
      inchangés, nouvelles variables .env par type d'instance (guardian vs
      master/slave)
- [x] `CLAUDE.md` à jour — QuotaStore (history.py), élection du poller
      (peer.py), commandes MQTT bidirectionnelles (mqtt_publisher.py,
      notifier/), note mono-cible/PRD B ajoutée en Vue d'ensemble
- [ ] ADR-0001 passé à `Accepté` — **hors périmètre de cet appel** (non
      demandé dans le mandat reçu de l'orchestrateur pour ce sprint) ;
      laissé à la charge de l'orchestrateur
- [ ] Issues ouvertes : PRD B, et améliorations MQTT hors périmètre —
      **hors périmètre de cet appel** (nécessite `gh issue create`, non
      inclus dans le mandat reçu) ; laissé à la charge de l'orchestrateur
- [x] Aucun secret exposé — les 6 fichiers modifiés/créés (README.md,
      DEPLOY.md, CLAUDE.md, RELEASE-NOTES-2.3.0.md, progress.json,
      INVARIANTS.md) ne contiennent que des noms de variables et des
      exemples de valeurs non sensibles (`TPLINK_1_QUOTA_VOLUME_MB=110000`
      etc.), aucun token/mot de passe/clé
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %, VERSION = 2.3.0 —
      `VERSION` **non modifié sur instruction explicite de l'orchestrateur**
      (reste `2.2.0`, le bump est géré à la release) ; `validate.sh` lancé
      en délégation pour confirmer l'absence de régression code (voir
      rapport de sprint) — aucun fichier sous `src/`, `tests/` ou
      `scripts/` modifié par ce sprint

## Frontières de fichiers

- **Modifier** : `README.md`, `DEPLOY.md`, `CLAUDE.md`, `VERSION`,
  `docs/adr/0001-multi-vendor-router-monitoring.md`
- **Lecture seule** : `src/` (aucun changement fonctionnel dans ce sprint)
