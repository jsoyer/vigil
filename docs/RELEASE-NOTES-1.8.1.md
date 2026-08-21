# Notes de version -- 1.8.1

**Date** : 2026-08-21
**Type** : bugfix (patch)
**Branche** : `main`

## Correctif : identite MQTT/Home Assistant partagee entre les instances

`src/mqtt_publisher.py` codait en dur l'identite du device Home Assistant,
les `unique_id` de chaque entite, les topics de discovery, et le `client_id`
MQTT. Les quatre instances de production (Dijon master/slave, Nice
master/slave) publiaient donc sous la **meme identite** : elles ecrasaient
mutuellement le meme device et les memes 8 entites Home Assistant, et se
deconnectaient en boucle sur le broker MQTT (un broker n'accepte qu'une seule
connexion par `client_id`).

### Ce qui change

- Nouvelle option **`INSTANCE_ID`** (`src/config.py`), avec un defaut derive
  du hostname de la machine si rien n'est configure -- aucune action manuelle
  n'est requise pour que les instances existantes obtiennent une identite
  distincte.
- Le device Home Assistant, les `unique_id` des entites, les topics de
  discovery (`homeassistant/sensor/usg_watchdog_<instance>/...`) et le
  `client_id` MQTT (`usg-watchdog-<instance>`) sont desormais derives de cet
  identifiant.
- Nouvelle fonction `mqtt_publisher.is_configured()`, alignee sur les autres
  modules optionnels du projet (`telegram_bot`, `ddns_cloudflare`,
  `backup_unifi`).

### IMPORTANT -- Migration Home Assistant (irreversible)

**Changer les `unique_id` fait que Home Assistant recree les entites.** Les
anciennes entites (celles crees avant ce patch, sous l'identite partagee
`usg_watchdog`) deviennent **orphelines** : Home Assistant ne les met plus a
jour et elles doivent etre **supprimees manuellement** (Parametres >
Appareils et services > Entites, ou via l'appareil "USG Watchdog" existant).

**L'historique rattache aux anciennes entites n'est PAS transfere** aux
nouvelles. Les graphiques/statistiques bases sur l'ancien `unique_id`
s'arretent au moment de la mise a jour ; les nouvelles entites redemarrent un
historique vide.

**C'est irreversible.** Revenir en arriere sur le code (rollback) restaure le
comportement precedent, mais **ne defait pas** la recreation des entites deja
effectuee par Home Assistant : les anciennes entites resteront orphelines et
leur historique reste perdu, meme apres un rollback du code.

En consequence : deployer ce patch quand on est pret a supprimer les
anciennes entites a la main sur chacune des instances (Dijon master/slave,
Nice master/slave), pas "pour voir".

### Configuration recommandee

Definir explicitement `INSTANCE_ID` sur chaque instance plutot que de
dependre du hostname (ex: `dijon_master`, `dijon_slave`, `nice_master`,
`nice_slave`) :

```
INSTANCE_ID=dijon_master
```

Sans cette variable, l'identifiant est derive automatiquement du hostname de
la machine (minuscules, caracteres non alphanumeriques remplaces par `_`).

### Hors perimetre de ce patch

- Pas de device `USG <site>` unique regroupant plusieurs instances (prevu
  pour le PRD A2, avec election de publieur).
- Pas de `device_class` / `state_class` sur les capteurs, pas de `retain` sur
  les etats publies, pas d'`availability_topic` / LWT.
- Pas de variable d'environnement `MQTT_DISCOVERY_PREFIX`.

Voir `docs/tasks/router/bugfix/2026-08-20_1618-mqtt-instance-identity.md`
pour le detail complet de l'analyse et du correctif.
