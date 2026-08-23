# Notes de version -- Vigil 2.0.0

Date : 2026-08-23
Type : renommage majeur (breaking : contrat d'exploitation)

> ⚠️ **AVERTISSEMENT PERMANENT** : ne **jamais** recréer un dépôt nommé
> `jsoyer/usg-watchdog`. Cela annulerait la redirection GitHub mise en place
> par le renommage et casserait instantanément tout updater non migré qui
> interroge encore l'ancien nom.

## Résumé

**USG Watchdog devient Vigil.** Le logiciel change de nom ; le routeur
surveillé reste un Ubiquiti USG (les variables `USG_*`, `src/usg.py`, la clé
`usg_ed25519` et tout ce qui désigne le matériel ne changent pas).

Aucun changement de comportement fonctionnel : scoring, circuit breaker,
notifications, HA, API — identiques à la 1.8.3.

## Ce qui change (contrat d'exploitation)

| Élément | Avant (1.8.3) | Après (2.0.0) |
|---|---|---|
| Dépôt GitHub | `jsoyer/usg-watchdog` | `jsoyer/vigil` (redirection active) |
| Répertoire d'installation | `/opt/usg-watchdog` | `/opt/vigil` |
| Service systemd | `usg-watchdog.service` | `vigil.service` |
| Updater | `usg-watchdog-updater.{service,timer}` | `vigil-updater.{service,timer}` |
| Utilisateur système | `usg-watchdog` | `vigil` (nouveau compte, jamais `usermod -l`) |
| Log | `/var/log/usg-watchdog.log` | `/var/log/vigil.log` |
| Événements persistés | `/var/log/usg-watchdog-events.json` (**jamais fonctionnel** : l'écriture atomique `.tmp` + `rename` exige un répertoire inscriptible, interdit par `ProtectSystem=strict`) | `/var/lib/vigil/events.json` (fix inclus : `StateDirectory=vigil` dans le unit) |
| Défaut `MQTT_TOPIC_PREFIX` | `usg-watchdog` | `vigil` (les 4 instances de prod ont des préfixes explicites `vigil/<site>-<role>`) |
| Métriques Prometheus | `usg_watchdog_*` (19 séries) | `vigil_*` — **bascule sèche** (décision du 2026-08-23) |

**Ce qui ne change PAS** : les `unique_id` Home Assistant (`vigil_*` depuis la
1.8.2 — aucune recréation d'entités), les variables d'environnement de
configuration existantes, le nom de fichier `src/watchdog.py`, l'historique git.

## Bascule sèche des métriques (décision Q2, 2026-08-23)

Les séries `usg_watchdog_*` **n'existent plus** à partir de la 2.0.0. Aucune
double émission, aucune période de dépréciation. La rupture d'historique
Prometheus est assumée ; le dashboard Grafana du dépôt est migré. Aucune règle
d'alerte hors dépôt n'existait. Il n'y a donc rien à retirer en 2.1.0.

## Migration : intervention manuelle par hôte (OBLIGATOIRE)

**L'updater n'applique pas cette version tout seul** (et ne doit pas — le tag
`v2.0.0` n'a été poussé qu'après migration complète de la flotte). Procédure
par Pi (runbook détaillé :
`docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil/sprints/05-migration-flotte-release.md`) :

1. Gel de l'updater (`disable --now usg-watchdog-updater.timer`), sauvegarde
   `.env`/`.ssh`, épinglage des chemins courants dans `.env` ;
2. Clone renommé (`~/github/vigil`, remote `jsoyer/vigil`), pull ;
3. Pré-copie de `.env`/`.ssh` vers `/opt/vigil` ;
4. `sudo ~/github/vigil/scripts/deploy.sh` — crée l'utilisateur `vigil`, le
   venv (**recréé, jamais copié**), `releases/` + `current`, les unités, et
   démarre `vigil.service` ;
5. Bascule : `disable --now usg-watchdog` puis `restart vigil` (libère le port
   HTTP et le `client_id` MQTT tenus par l'ancien process) ;
6. Vérifications complètes (`/health` = 2.0.0, MQTT rc=0, `/metrics` en
   `vigil_*`, `vigil-events.json` non vide) ;
7. Dégel : `enable --now vigil-updater.timer`.

**Rollback** : l'ancien `/opt/usg-watchdog`, l'unité `usg-watchdog.service`
(désactivée mais présente) et l'utilisateur `usg-watchdog` sont **conservés 7
jours** après migration. Retour arrière = `disable --now vigil` +
`enable --now usg-watchdog`. La purge à J+7 est une opération séparée, sur
demande explicite.

## Ordre appliqué à la flotte (2026-08-23)

dijon-slave (cobaye) → dijon-master → vérif site Dijon → nice-slave →
nice-master → vérif site Nice → tag `v2.0.0` en tout dernier.
