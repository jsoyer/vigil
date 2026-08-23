# Notes de version -- USG Watchdog 1.8.2

Date : 2026-08-23
Type : bugfix (patch)

## Resume

Ce patch corrige deux bugs decouverts lors de la verification du deploiement
1.8.1 sur le Pi `dijon-master` (2026-08-22) :

1. **Les mises a jour automatiques etaient des no-ops silencieux depuis la
   1.7.6.** L'updater (`updater/update.py`) telecharge, valide, extrait dans
   `releases/vX.Y.Z/` et bascule le symlink `current`, mais le unit systemd
   (`systemd/usg-watchdog.service`) demarrait le code depuis l'ancien layout
   a plat `/opt/usg-watchdog/src` -- le symlink `current` n'etait lu par
   personne. Toutes les "mises a jour" depuis ce deploiement etaient sans
   effet : le code qui tournait restait celui du premier deploiement a plat.
   Le unit pointe maintenant sur `/opt/usg-watchdog/current/src`, `deploy.sh`
   installe desormais dans le meme layout `releases/vX.Y.Z/` + symlink
   `current` que l'updater, et l'updater verifie en plus que la version
   annoncee par `/health` apres redemarrage correspond bien a la version
   cible (mismatch = echec de mise a jour, rollback automatique).

2. **Identite MQTT / Home Assistant renommee `vigil` (fenetre d'opportunite).**
   Le logiciel sera renomme **Vigil**. Comme le bug 1 ci-dessus a empeche
   toute instance de production d'executer effectivement la 1.8.1 (identite
   MQTT par instance), aucune entite Home Assistant `usg_watchdog_{instance}_*`
   n'a jamais ete creee. L'identite MQTT passe donc directement a `vigil`
   maintenant, pour eviter une double migration d'entites plus tard.

## Intervention manuelle requise sur chaque Pi (OBLIGATOIRE)

L'updater automatique ne peut pas reparer lui-meme le unit systemd qui
l'empeche d'agir (bug 1) : une intervention manuelle unique est necessaire
sur chaque instance de production.

1. **Mettre a jour le unit systemd et redemarrer** :

   ```bash
   cd <repo> && git pull
   sudo install -m 644 systemd/usg-watchdog.service /etc/systemd/system/usg-watchdog.service
   sudo systemctl daemon-reload && sudo systemctl restart usg-watchdog
   curl -s http://127.0.0.1:<port>/health   # doit annoncer la version de current/
   ```

   (ou `sudo ./scripts/deploy.sh` une fois le repo a jour, qui fait tout :
   installation en `releases/vX.Y.Z/`, bascule du symlink `current`, unit
   systemd, redemarrage.)

2. **Purger les anciennes entites Home Assistant `usg_watchdog*`.** Ces
   entites (partagees, sans distinction d'instance) deviennent orphelines a
   la premiere connexion MQTT de l'instance mise a jour -- suppression
   manuelle a faire dans Home Assistant. L'historique associe n'est pas
   transfere. Cette operation est **irreversible**. (Reprise de la note de
   migration 1.8.1, qui n'avait en pratique jamais ete declenchee a cause du
   bug 1.)

3. **Pas de seconde purge a prevoir.** Les nouvelles entites naissent
   directement sous l'identite `vigil_{instance}` -- aucune entite
   `usg_watchdog_{instance}` (identite par instance, 1.8.1) n'a jamais existe
   en production, il n'y a donc **pas** de migration intermediaire a gerer.

## Detail des changements

- `systemd/usg-watchdog.service` : `WorkingDirectory` et `ExecStart` pointent
  sur `/opt/usg-watchdog/current/src` au lieu de `/opt/usg-watchdog/src`.
- `scripts/deploy.sh` : installe desormais dans
  `${INSTALL_DIR}/releases/v$(cat VERSION)/` (`src/` + `VERSION`) puis
  bascule le symlink `current` de maniere atomique -- meme mecanisme que
  `updater/update.py`. Un ancien layout a plat `${INSTALL_DIR}/src` est
  deplace vers `${INSTALL_DIR}/src.flat-backup` (jamais supprime).
- `updater/update.py` : le health check post-redemarrage compare desormais
  le champ `version` du JSON `/health` a la version cible de la mise a jour ;
  un ecart est traite comme un echec (rollback + notification), au meme
  titre qu'un statut non healthy.
- `src/mqtt_publisher.py` : identite Home Assistant / MQTT entierement
  `vigil_{instance_id}` (device, `unique_id`, topic de discovery) et
  `client_id` MQTT `vigil-{instance_id}`.
- `src/config.py` : le fallback de `_normalize_instance_id()` (identifiant
  d'instance vide ou entierement non-alphanumerique) passe de
  `"usg_watchdog"` a `"vigil"`.

## Hors perimetre (volontairement)

- `MQTT_TOPIC_PREFIX` : le defaut `usg-watchdog` est conserve. Le renommer
  fait partie du grand renommage (repo, service, `/opt`), pas de ce patch.
  Les instances de production utilisent deja des prefixes explicites.
- Nom du service systemd, chemins `/opt/usg-watchdog`, nom du repo :
  idem, reserve au grand renommage.
- `retain` / `availability` / `device_class` MQTT : toujours hors perimetre.
