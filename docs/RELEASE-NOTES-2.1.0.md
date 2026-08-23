# Notes de version -- Vigil 2.1.0

PRD A1 -- Pilotage des lignes de secours TP-Link MR110 (2026-08-20).

## Fonctionnalité

Pilotage manuel de routeurs 4G TP-Link (modèle validé : MR110) utilisés comme
lignes de secours sur les sites Dijon et Nice.

- **Driver** `src/drivers/tplink.py` (`TplinkDriver`) : sonde étagée avec
  attribution de panne par saut (`Hop.BRIDGE` / `WIRELESS` / `DEVICE` /
  `ROUTE`), métriques 4G (signal, SIM, opérateur, IP WAN, trafic), readiness
  calculée sur seuils configurables, `reboot()`.
- **Sonde de bout en bout** (C11) : un succès n'est retenu que si l'IP
  publique observée diffère de celle du site **et** que les compteurs de
  trafic du MR110 ont bougé pendant la sonde -- deux preuves indépendantes,
  pour éviter le faux OK silencieux d'une sonde qui fuit par la fibre.
- **Registre** `src/managed_devices.py` : verrou de session par équipement
  (un MR n'accepte qu'une session admin), cache court, un seul réessai sur
  refus de session.
- **Confirmation** `src/confirm.py` : jeton court, usage unique, TTL court --
  aucune action destructive (reboot, SMS, USSD) n'est jamais automatique.
- **Commandes Telegram** `/lte` (état, détail, sonde à la demande, reboot
  confirmé) et **endpoints API** `/api/tplink/*` (voir README.md).

## Verdict du spike matériel (2026-08-23)

**FULL** sur les deux sites, bibliothèque `tplinkrouterc6u==5.31.1` validée
sur MR110 réels (Dijon 192.168.10.1, Nice 192.168.30.1). Rapport complet :
`docs/spikes/2026-08-23-mr110-compat.md`.

## Topologie de déploiement

La topologie réelle diffère de l'hypothèse initiale (pas de Pi Zero pont
dédié) : ce sont les **guardians** (instances slave) qui portent le lien
direct vers leur MR110 -- mode `bridged`. Les **masters** n'ont pas de route
vers le MR110 depuis cette topologie.

**Conséquence pour le déploiement** : les variables `TPLINK_<n>_*` ne doivent
être déclarées que sur les guardians. Voir `DEPLOY.md`, section "Migration
vers 2.1.0".

## Nouvelle dépendance -- première fois en conditions réelles

`requirements.txt` gagne `tplinkrouterc6u==5.31.1`. C'est la **première fois**
que l'auto-updater (`updater/update.py::install_requirements`, livré en
1.8.3) installe une nouvelle dépendance sur les 4 instances de production, et
pas seulement en test/CI. L'installation se fait avant la bascule du
symlink et le restart du service : un échec de `pip install` annule la mise
à jour avant tout impact sur l'instance en cours (voir `updater/update.py`,
fonction `main()`).

Le `preflight.py` (`ExecStartPre` systemd) vérifie désormais aussi que
`drivers` et `managed_devices` s'importent -- sans jamais exiger
`tplinkrouterc6u` (invariant C1, import vendor paresseux).

## Rappel API_TOKEN

Dès qu'un équipement TP-Link est déclaré, `API_TOKEN` devient nécessaire pour
**toute** interaction API avec `/api/tplink/*`, y compris en lecture (`GET`) --
divergence volontaire avec le reste de l'API. Sans `API_TOKEN`, seul Telegram
reste utilisable pour piloter les équipements déclarés.

## Périmètre exclu de cette version

- Pas de bascule automatique du trafic vers un secours TP-Link.
- Pas de commandes SMS / USSD (la librairie vendor les expose, rien ne les
  pilote encore -- pas validé au spike).
- Pas d'exposition Home Assistant / MQTT de ces équipements -- prévu au PRD
  A2 (`docs/tasks/router/feature/2026-08-20_1618-a2-exposition-ha/spec.md`).
- Le moteur de surveillance reste mono-cible (USG uniquement) -- refonte
  prévue au PRD B (moteur multi-cible).
