# Sprint 1 — Quota data et détection d'usage du secours

- **PRD** : A2 — Exposition & Home Assistant (2026-08-20)
- **Dépend de** : A1 livré (`src/managed_devices.py`, `src/drivers/tplink.py`)
- **Bloque** : sprints 2, 3

## Contexte (autoportant)

A1 a rendu les lignes de secours **TP-Link TL-MR110** de Dijon et Nice
pilotables : `src/drivers/tplink.py` lit leur état (métriques 4G, readiness,
`data_used_bytes`, débits rx/tx, clients associés) et `src/managed_devices.py`
sert de registre avec cache court et verrou par équipement.

Deux informations manquent, et **aucune ne se déduit d'une lecture isolée** —
elles demandent de comparer des relevés dans le temps :

1. **La conso sur le cycle de facturation.** Un forfait épuisé rend le secours
   inutile, exactement comme une SIM morte.
2. **Le fait que le secours soit en train de servir.**

Le projet dispose déjà d'un mécanisme d'historique persisté : `src/history.py`.

## Objectifs

1. Suivi de quota robuste aux remises à zéro du compteur.
2. Détection d'usage à trois états.

## Travail

### 1.1 Quota data

- Source : `data_used_bytes` du driver (compteur `total_statistics` du routeur).
- Config par équipement : volume du forfait, seuil d'alerte en % du forfait,
  **jour de reset de facturation**.
- **Détection de remise à zéro — le point délicat.** Le compteur du routeur
  repart de zéro à un reboot, et selon le firmware. Une **décroissance** entre
  deux relevés doit être interprétée comme un reset, **jamais** comme une conso
  négative. La conso du cycle se maintient côté watchdog par **accumulation de
  deltas positifs**, pas par lecture directe du compteur brut.
- Persistance via `src/history.py`, pour survivre à un redémarrage du service.
- Sortie : conso du cycle, % du forfait, date du prochain reset.

**Règles du jour de facturation (C20).** Un compteur de conso faux ne lève
jamais d'erreur — il affiche simplement un chiffre plausible et faux. Quatre
règles à implémenter explicitement, chacune couverte par un test :

| Cas | Règle |
|---|---|
| **Fuseau** | Le cycle bascule à minuit **heure locale de l'hôte**, pas UTC. C'est ainsi que l'opérateur facture. Les horodatages restent stockés en UTC ; seule la comparaison de date se fait en local |
| **Mois courts** | Jour de reset au 31 dans un mois de 30 jours ⇒ **dernier jour du mois**. Idem pour 29/30 en février. Ne jamais échouer silencieusement à basculer |
| **Changement d'heure** | La bascule se calcule sur la **date calendaire**, jamais sur un nombre d'heures écoulées : un jour de DST fait 23 ou 25 h, et « + 30 jours » dériverait |
| **Reset manqué** | Si le service était arrêté au moment de la bascule, le démarrage suivant doit **constater que la date est passée et clôturer le cycle** — pas l'ignorer jusqu'au mois suivant |

> Un reboot d'équipement — que A1 rend possible à la demande — remet
> potentiellement le compteur à zéro. Le suivi doit donc être correct **par
> construction**, pas seulement dans le cas nominal.

### 1.2 Détection d'usage

**Rappel de l'hypothèse H1 du PRD A1** : le Pi Zero est un pont de management,
il ne route pas le trafic de production. Le watchdog ne peut donc **pas**
observer la bascule depuis le lien principal, et `src/multiwan.py` (détection du
WAN actif de l'USG) n'est pas exploitable tant que le MR n'est pas câblé sur le
WAN2.

**Conception retenue** : détecter l'usage **depuis le MR110 lui-même** —
`rx_speed_bps` / `tx_speed_bps`, clients associés, conso qui décolle. Ce signal
vaut **quel que soit** le mécanisme de bascule, y compris manuel.

Trois états à distinguer :

| État | Signal | Pourquoi le distinguer |
|---|---|---|
| **inactif** | débit nul, pas de client | Le secours est en veille |
| **en service** | débit significatif / clients associés | Le site tourne sur le secours |
| **saturé** | débit proche du plafond Cat 4 | Le secours sert **mal** — information différente de « il sert » |

- Calibrer sur du **LTE Cat 4** (~150 Mb/s descendants, ~50 montants en
  théorique), pas sur le plafond du lien principal. Autre borne utile : le
  MR110 accepte **32 appareils** maximum.
- **Anti-rebond** : un pic isolé de trafic de management ne doit pas déclencher
  l'alerte.
- Événements `tplink_in_use` / `tplink_saturated` / `tplink_idle` + notification
  **au changement d'état**, jamais à chaque cycle.
- **Le message doit dire ce qu'il sait.** C'est une détection *a posteriori*
  (« le secours sert »), pas une détection d'événement de bascule : ne pas
  laisser croire qu'on a vu le lien principal tomber.

### 1.3 Sonde périodique de bout en bout (C11)

A1 a livré la sonde à la demande (`/lte check`) : une commande SSH ponctuelle sur
le Pi Zero qui prouve que le lien 4G porte réellement du trafic. Elle distingue
*attaché* (auto-reporté par le routeur, peu fiable) de *data qui passe*.

Point clé hérité d'A1 : le Pi Zero est **à double rattachement** (`eth0` vers le
LAN et la fibre, `wlan0` vers le MR110). Lier l'interface ne prouve pas le
chemin — la sonde **porte sa propre preuve** : IP publique observée différente de
celle du site (via `get_public_ip()`), **et** compteurs du MR110 en mouvement.
Elle retourne quatre valeurs : `OK` / `FAIL` / `LEAK` / `UNKNOWN`.

Ce sprint la rend périodique et en fait un signal d'alerte.

- **Opt-in par équipement**, désactivée par défaut ; intervalle configurable,
  horaire par défaut (~0,7 Mo/mois). Rien ne consomme du forfait sans activation
  explicite.
- Alimente `internet_ok` et la readiness : **lien attaché mais sonde en échec →
  `DEGRADED`**, jamais `OK`. C'est le scénario du forfait épuisé.
- Sonde `UNKNOWN` (Pi Zero injoignable) → `internet_ok` à `None`, readiness
  **non** dégradée : on ne sait pas, on ne prétend pas savoir.
- Sonde `LEAK` (sortie par la fibre) → **défaut de configuration**, notifié comme
  tel et distinct d'une panne du secours. Ne dégrade pas la readiness, mais ne
  vaut **jamais** `OK` : tant qu'il dure, la surveillance du lien est aveugle —
  le dire est le minimum.
- Événements `tplink_link_down` / `tplink_link_up` + notification **au changement
  d'état**. Message distinct de « routeur injoignable » : « le MR110 répond mais
  sa 4G ne porte plus de trafic » est un diagnostic différent, et actionnable
  différemment (vérifier le forfait plutôt que se déplacer).
- **Ne jamais faire d'échec de sonde une raison de reboot automatique** — C6
  reste entière.

### 1.3bis Niveaux de notification (C18)

Les nouveaux événements passent par `notify()` et sont diffusés **tels quels**
vers les 7 canaux configurés (`_dispatch.py`), chacun filtrant par son
`*_MIN_LEVEL`. Rien de spécifique à un canal n'est à écrire — mais le **niveau**
de chaque événement doit être choisi délibérément : il n'y en a que trois, et
`NTFY_MIN_LEVEL` vaut `INFO` par défaut, donc un événement mal noté part
directement sur le téléphone.

| Événement | Niveau | Raison |
|---|---|---|
| `tplink_link_down` — attaché mais la data ne passe pas | `WARNING` † | Le secours est inutilisable, mais rien n'est tombé |
| `backup_degraded` — SIM, signal ou readiness | `WARNING` † | Idem : à traiter, pas en urgence |
| `data_quota_warning` — seuil de forfait franchi | `WARNING` † | Le secours a une date de péremption |
| `tplink_saturated` — le secours sert mais plafonne | `WARNING` | Il sert **mal**, information distincte de « il sert » |
| `tplink_in_use` — le site tourne **sur son secours** | `CRITICAL` | Le lien principal est tombé ; le site est sur du Cat 4 facturé au volume |
| Sonde `LEAK` — défaut de configuration du chemin | `WARNING` | Pas une panne, mais **la surveillance est aveugle** : le taire serait pire |
| `Hop.BRIDGE` / `Hop.ROUTE` en échec | `WARNING` | Le premier maillon ou la config est en cause, pas forcément le secours |
| `tplink_link_up`, `backup_ready`, `tplink_idle` | `INFO` | Retours à la normale : utiles à tracer, pas à réveiller |

**† Escalade conditionnelle.** Ces trois événements passent à **`CRITICAL`** si
l'équipement est **en cours d'utilisation** au moment du constat. Un secours
dégradé pendant que le site s'appuie dessus n'est plus un avertissement : c'est
la panne en cours. C'est le seul endroit du plan où le niveau dépend du contexte,
et il le mérite.

**Pas de doublon entre instances** : l'élection (C12) fait qu'une seule instance
poll et notifie un équipement donné. Combiné à la notification **au changement
d'état** uniquement, un secours dégradé pendant deux jours produit **une** alerte,
pas deux jours d'alertes sur quatre machines.

L'opérateur qui veut moins de bruit sur un canal relève son `*_MIN_LEVEL` —
mécanisme existant, rien à ajouter.

### 1.4 Élection du poller (C12)

**Pourquoi ici.** A1 n'interrogeait les équipements qu'**à la demande** : une
collision de session entre master et slave y était improbable. Ce sprint
introduit le **polling périodique** (quota, usage, sonde). Or un routeur MR
n'accepte **qu'une session d'administration** : deux instances qui l'interrogent
en continu se déconnectent mutuellement en boucle. L'exclusivité, initialement
prévue en PRD B, devient donc nécessaire dès maintenant.

- **Une seule instance interroge un équipement.** **Réutiliser la logique de
  priorité de `peer.py`** — ne pas écrire une seconde logique de failover.
- **Préférer l'instance en mode `bridged`** quand elle est joignable. Son chemin
  est plus court et plus fiable : ni route, ni NAT, ni SSH. Ce critère est
  **distinct de la priorité HA** de `peer.py`, qui décide qui redémarre l'USG —
  deux questions différentes qu'il ne faut pas confondre. À défaut d'instance
  `bridged` joignable, retomber sur la priorité habituelle.
- **Le repli suppose que l'autre instance ait un chemin configuré.** Si seule
  l'instance `bridged` peut joindre le MR110, la surveillance du secours meurt
  avec elle — faible pour un dispositif censé survivre aux pannes. Le Sprint 1
  d'A1 a tranché ce point par site ; s'y conformer.
- L'instance non élue lit l'état via `/api/state` du peer et l'expose **avec
  l'âge de la donnée**. Une valeur reprise du peer ne doit jamais être présentée
  comme un relevé direct.
- Perte du peer → reprise du polling après `PEER_TAKEOVER_DELAY` (délai existant).
- **Split-brain** : si les deux instances se croient seules, elles pollent toutes
  deux. Traiter comme la divergence déjà gérée par `peer.py` — détecter et
  alerter, ne pas résoudre silencieusement.
- Le polling de la cible USG reste fait par **les deux** instances : c'est le
  comportement actuel, il n'y a pas de session exclusive à protéger, et le
  supprimer casserait la détection de divergence.

## Tests

- Conso croissante → % correct.
- **Compteur qui décroît → traité comme reset**, pas comme conso négative.
- Reset consécutif à un reboot commandé → cycle préservé, conso non perdue.
- Franchissement du jour de facturation → nouveau cycle.
- **C20** — les quatre cas : bascule à minuit **local** ; jour 31 dans un mois de
  30 jours → dernier jour ; jour de changement d'heure → bascule sur la date, pas
  sur les heures écoulées ; **service arrêté pendant la bascule** → cycle clôturé
  au redémarrage, pas sauté.
- Persistance : redémarrage simulé du service → conso du cycle conservée.
- Usage : débit au-dessus du seuil → `tplink_in_use` ; pic isolé → **pas**
  d'événement ; débit proche du plafond → `tplink_saturated` ; retour à zéro →
  `tplink_idle`.
- Maintien en usage sur 10 cycles → **une seule** notification.
- Champs absents (firmware) → aucun état inventé, pas d'exception.
- **Sonde désactivée par défaut** : aucun équipement déclaré ne sonde tant qu'on
  ne l'active pas (assertion sur l'absence d'appel SSH).
- **Lien attaché + sonde en échec → `DEGRADED`** et `tplink_link_down` émis.
- Sonde indéterminée → `internet_ok` à `None`, **pas** de `DEGRADED`, pas d'alerte.
- **Preuve de chemin** : IP observée identique à celle du site → `LEAK` et
  **aucune** alerte de type « secours HS » ; compteurs figés → `LEAK` ; les deux
  preuves concordantes → `OK`.
- `LEAK` persistant → notifié comme défaut de configuration, une seule fois.
- Échec de sonde répété sur 10 cycles → **une seule** notification.
- **C18** : chaque événement part au niveau prévu ; `tplink_in_use` est
  `CRITICAL` ; `backup_degraded` est `WARNING` hors usage et **`CRITICAL` en
  usage** (escalade conditionnelle).
- Deux instances simulées → **une seule** notifie (C12).
- Échec de sonde → **aucun** reboot déclenché (C6).
- **C12** : deux instances simulées du même site → **une seule** interroge le
  driver ; la non élue expose l'état du peer avec un âge **non nul**.
- **C12** : entre une instance `bridged` et une `remote` toutes deux joignables,
  c'est la `bridged` qui est élue, **même si sa priorité HA est plus basse**.
- Instance `bridged` injoignable → la `remote` prend le relais si son chemin est
  configuré ; sinon l'état passe `UNKNOWN`, **jamais** un faux sain.
- Perte du peer → la restante reprend le polling après le délai.
- Split-brain simulé → détecté et alerté, pas résolu en silence.
- La cible USG reste pollée par les deux instances (non-régression).

## Critères d'acceptation

- [x] Conso du cycle, %, jour de reset, **détection de remise à zéro** —
      `QuotaStore` (`src/history.py`), accumulation par deltas positifs
      uniquement, reset de compteur traité comme un nouveau cycle (commit
      `ace8497`)
- [x] Conso persistée, survit à un redémarrage du service — persistance
      atomique via `QuotaStore` (commit `ace8497`)
- [x] **C20** : fuseau local, mois courts, changement d'heure et reset manqué
      couverts par des tests dédiés — `tests/test_tplink_quota.py` (157
      lignes ajoutées, commit `ace8497`)
- [x] Trois états d'usage distingués, calibrés Cat 4, avec anti-rebond —
      idle/in_use/saturated, anti-rebond 2 cycles (commit `ace8497`)
- [x] Notification **au changement** d'état uniquement — niveaux C18 câblés
      via `notify()` (commit `ace8497`)
- [x] **C18** : niveaux conformes au tableau ; escalade en `CRITICAL` quand
      l'équipement est en cours d'utilisation — `in_use=CRITICAL`, escalades
      conditionnelles (commit `ace8497`)
- [x] Aucun doublon d'alerte entre master et slave (conséquence de C12) —
      conditionné à l'élection du poller (commit `ace8497`)
- [x] **C11** : sonde périodique opt-in, désactivée par défaut, **preuve de
      chemin exigée** ; `LEAK` distingué d'une panne du secours —
      `tests/test_tplink_usage.py` (826 lignes ajoutées, commit `ace8497`)
- [x] Lien attaché sans data → `DEGRADED` + `tplink_link_down`, message distinct
      de « routeur injoignable » — `src/messages.py` (154 lignes ajoutées,
      commit `ace8497`)
- [x] Sonde indéterminée → `internet_ok` à `None`, aucune alerte (commit
      `ace8497`)
- [x] Un échec de sonde ne déclenche **jamais** de reboot (C6) (commit
      `ace8497`)
- [x] **C12** : une seule instance poll un équipement ; l'autre expose l'état du
      peer **avec son âge** ; reprise après `PEER_TAKEOVER_DELAY` —
      `src/peer.py` (109 lignes ajoutées), bridged joignable prioritaire puis
      `INSTANCE_PRIORITY` (commit `ace8497`)
- [x] Split-brain détecté et alerté — bug de code mort trouvé et corrigé en
      route (commit `ace8497`)
- [x] Polling de la cible USG inchangé (les deux instances) — `src/peer.py`
      seul modifié pour l'élection, aucun changement à la boucle USG (commit
      `ace8497`)

**Preuve globale** : 56 nouveaux tests, suite complète à 1152 tests,
`./scripts/validate.sh` vert (commit `ace8497`).
- [ ] Messages explicites sur la nature *a posteriori* de la détection
- [ ] `watchdog.py` et `state.py` **non modifiés**
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %

## Frontières de fichiers

- **Créer** : `tests/test_tplink_quota.py`, `tests/test_tplink_usage.py`
- **Modifier** : `src/managed_devices.py`, `src/history.py`, `src/config.py`,
  `src/events.py`, `src/messages.py`, `src/peer.py` (élection du poller —
  **réutiliser** la priorité existante, ne pas dupliquer le failover)
- **Lecture seule** : `src/drivers/`
- **Interdit** : `watchdog.py`, `state.py`, `multiwan.py`, `dashboard.py`,
  `metrics.py`, `mqtt_publisher.py`
