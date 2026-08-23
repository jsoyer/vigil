# Notes de version -- Vigil 2.3.0

PRD source : `docs/tasks/router/feature/2026-08-20_1618-a2-exposition-ha/spec.md`
(A2 -- Exposition & Home Assistant). Livré sur les 4 instances de production
(Dijon master+slave, Nice master+slave) le 2026-08-23.

## Fonctionnalité

A2 expose les équipements TP-Link déclarés (A1) et le USG dans Home Assistant,
via auto-discovery MQTT (`retain`), et ouvre un chemin de commande armé pour
le reboot à distance.

- **Device `vigil_<site>_tplink_<id>`** -- un device HA par équipement TP-Link
  déclaré (21 entités : disponibilité, indicateurs 4G, conso/quota/reset,
  débits, état d'usage, sonde, diagnostic). Publié uniquement par l'instance
  élue (poller, C12) -- jamais par les deux instances d'un même site.
- **Device `USG <site>`** -- un device par site (pas par instance) pour les
  4 capteurs de **ligne** USG (`gateway`, `internet`, RTT gateway, RTT
  internet), alimenté par l'instance élue.
- **Device `Watchdog <instance>`** -- un device par instance pour les
  capteurs propres au watchdog : les 8 capteurs historiques (enrichis
  `device_class`/`state_class`, `unique_id` et type inchangés -- C14), plus
  7 nouveaux : divergence, état du peer (avec âge), et les métriques hôte
  (température CPU, disque libre, disque utilisé %, mémoire disponible,
  charge -- stdlib seule).
- **Commandes armées** : `switch` *Armer le reboot* + `button` *Reboot* +
  `sensor` *Dernière action*, sur le device de l'équipement TP-Link. Le
  reboot est refusé sans arm préalable ; l'entité *Dernière action* publie
  systématiquement un résultat et son motif, y compris sur un refus (C10).
  Le switch arm se désarme automatiquement après `MQTT_ARM_TIMEOUT`
  secondes (défaut 30 s).
- **Dashboard** : carte par équipement (badge readiness, saut en panne
  nommé, signal 4G, bandeau usage, quota avec barre de progression et date
  de reset, indicateur `from_peer` + âge de la donnée). Rendu sans
  équipement déclaré strictement inchangé.
- **Prometheus** : 16 séries `vigil_tplink_*` labellisées `device`/`label`,
  purement additives -- les métriques `usg_watchdog_*` restent émises sans
  label, à l'identique (C4).
- **Élection du poller (C12)** : l'instance en mode `bridged` joignable est
  prioritaire, repli sur `INSTANCE_PRIORITY` ; l'instance non élue lit
  l'état du peer avec son âge au lieu de sonder elle-même. Split-brain
  détecté et notifié.

Voir `README.md` (section « Home Assistant : entités par équipement ») pour
le détail des entités, `device_class`/`state_class` et variables.

## Migration C15 -- entités de ligne recréées

> **Avertissement** : les 4 capteurs de **ligne** USG (`gateway`,
> `internet`, RTT gateway, RTT internet) migrent d'un device par instance
> (`Watchdog <instance>`) vers un device unique **`USG <site>`**, avec de
> **nouveaux `unique_id`**. Home Assistant traite ce changement d'identité
> comme une recréation d'entité -- **c'est assumé, pas un bug**.

- Les nouvelles entités apparaissent automatiquement sous `USG <site>` dès
  que l'instance élue publie. Aucune action requise côté déploiement.
- Les anciennes entités de ligne (celles qui vivaient sous
  `Watchdog <instance>`) deviennent **orphelines** dans Home Assistant --
  `unavailable` indéfiniment, historique conservé. Elles ne se suppriment
  **pas** toutes seules : à purger à la main (Paramètres -> Appareils et
  services -> Entités -> filtrer « indisponible » -> supprimer).
- **Les 8 capteurs par instance ne bougent pas** (C14) : `score`, `status`,
  `reboots_today`, `uptime` et les 4 de ligne *avant* migration restent sur
  `Watchdog <instance>` avec leur `unique_id` historique inchangé pour tout
  ce qui n'est pas la ligne. Ne purgez que les entités de ligne orphelines,
  pas le device `Watchdog <instance>` entier.
- La déduplication du device de ligne fait perdre la comparaison directe
  des deux vues master/slave ; elle est compensée par le `binary_sensor`
  de divergence exposé sur le device watchdog -- un état de ligne qui
  diffère entre instances reste un symptôme observable, pas un signal
  supprimé.

## Configuration par instance

```bash
# Guardian (accès direct au MR110) -- déclare l'équipement ET les commandes
TPLINK_1_HOST=192.168.10.1
TPLINK_1_QUOTA_VOLUME_MB=110000
TPLINK_1_QUOTA_ALERT_PCT=80
TPLINK_1_QUOTA_RESET_DAY=27
MQTT_COMMANDS_ENABLED=true        # guardian uniquement -- voir Sécurité
MQTT_ARM_TIMEOUT=30

# Master/slave (pas de chemin réseau vers le MR110) -- rien à déclarer côté
# TP-Link ; SITE_ID suffit pour rattacher l'instance au bon device HA de site
SITE_ID=dijon                     # ou dérivé automatiquement de INSTANCE_ID
```

**Quotas Free configurés en production** : forfait 110 Go/mois
(`TPLINK_<n>_QUOTA_VOLUME_MB=110000`), reset le 27 du mois
(`TPLINK_<n>_QUOTA_RESET_DAY=27`), alerte à 80 % (défaut).

## Sécurité

> **C9 -- broker authentifié obligatoire pour les commandes** : activer
> `MQTT_COMMANDS_ENABLED=true` ouvre une voie de commande entrante capable
> de déclencher un reboot (la deuxième voie de commande entrante du
> projet, après l'API HTTP). Quiconque peut publier sur le broker peut
> déclencher une action. **Le broker MQTT doit être authentifié**
> (`MQTT_USERNAME`/`MQTT_PASSWORD`) avant d'activer cette variable. Sur un
> broker anonyme, laissez `MQTT_COMMANDS_ENABLED=false`.

**Recommandation opérateur** : n'activez `MQTT_COMMANDS_ENABLED` que sur
**une seule instance par site** -- le guardian. Armer les deux instances
d'un même site multiplie inutilement la surface de commande sans bénéfice
fonctionnel.

## Correctifs embarqués depuis 2.2.0

- **`scripts/deploy.sh`** : la migration emporte désormais aussi
  `~/.config` (rclone) -- cause de l'échec des backups UniFi post-
  renommage vers Vigil, réparé en production sur `bbh-network` (upload
  29,8 Mo vers `drive:Unifi` vérifié + prune OK).
- **Dashboard JS** : échappements Python non-raw qui cassaient
  silencieusement le JS TP-Link introduit en 2.2.0, corrigés avec test de
  régression (rendu sans équipement déclaré testé byte-identique).
- **Split-brain** : bug de code mort dans l'élection du poller trouvé et
  corrigé en route (Sprint 1, C12).

## Périmètre exclu de cette version

- **PRD B** -- moteur multi-cible (`UsgDriver`, rôles dans le scoring,
  alerting automatique sur la readiness, C5 exclusivité de polling
  généralisée). Suit A1/A2, non démarré.
- **Backlog MQTT** -- `availability_topic`/LWT, exposition du topic
  `{prefix}/state` déjà publié mais non déclaré en discovery.
- Statut ADR-0001 et ouverture des issues de suivi (PRD B, backlog MQTT) :
  à la charge de l'orchestrateur, hors de cette livraison de documentation.
