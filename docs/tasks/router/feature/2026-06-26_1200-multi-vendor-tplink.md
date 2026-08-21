> ⚠️ **SUPERSEDED le 2026-08-12** par
> [2026-08-12_1451-tplink-backup-lines/spec.md](2026-08-12_1451-tplink-backup-lines/spec.md).
> Trois hypothèses de ce PRD se sont révélées fausses : les TP-Link sont des
> **lignes de secours** (pas des liens principaux à rebooter automatiquement),
> le parc compte **4 instances watchdog** en paires HA sur 2 sites (pas un
> watchdog central), et le modèle réel est un **TL-MR110 indoor**, absent des
> modèles testés de `tplinkrouterc6u`. Conservé pour l'historique et pour les
> contraintes C1→C4, qui restent valides et sont reprises dans le nouveau PRD.

# PRD — Support multi-vendor : routeurs TP-Link 4G

- **Catégorie** : feature
- **Date** : 2026-06-26
- **Auteur** : Jerome Soyer
- **ADR** : [docs/adr/0001-multi-vendor-router-monitoring.md](../../../adr/0001-multi-vendor-router-monitoring.md)
- **Version cible** : 1.9.0 (minor — feature)
- **Branche** : `dev` → PR → `main`

---

## 1. Problème & objectif

USG Watchdog ne surveille qu'un USG. De nouveaux **routeurs 4G TP-Link** (série
Archer MR) sont au parc, sur **sites indépendants**. Objectif : leur appliquer
le même service (reboot auto sur perte de connexion) **+** remonter leurs
métriques 4G (RSRP, RSRQ, SNR, type réseau, état SIM, opérateur, conso data),
via la lib `tplinkrouterc6u`, **sans casser la surveillance USG existante** et
**sans renommer le projet**.

## 2. Correctness Discovery

- **Audience** : l'opérateur (toi) qui consulte dashboard/notifications/metrics
  pour savoir quel lien est down et agir. Décision pilotée : faut-il intervenir
  physiquement sur un site, ou le reboot auto a-t-il suffi ?
- **Vérification** : (a) un déploiement existant sans `TARGET_*` se comporte à
  l'identique (non-régression) ; (b) un TP-Link MR injecté en mock déclenche
  reboot quand son lien tombe ; (c) `get_lte_status` mocké → RSRP/RSRQ/SNR
  visibles dans `/api/state`, dashboard, `/metrics`.
- **Failure definition** : un lien réellement down n'est pas rebooté, OU un
  reboot intempestif sur lien sain, OU la surveillance USG régresse.
- **Danger definition** : reboot en boucle d'un TP-Link (circuit-breaker
  doit s'appliquer par cible), lock de session admin TP-Link (logout manquant),
  fuite du mot de passe TP-Link dans les logs.
- **Uncertainty policy** : si `get_lte_status` échoue/champs absents (firmware),
  dégrader proprement (métriques `None`), ne jamais lever, ne pas fausser le
  score santé.
- **Risk tolerance** : zéro régression USG (priorité absolue). Métriques 4G
  best-effort acceptables.

## 3. Scope

### In scope
- Abstraction `RouterDriver` + `UsgDriver` (refactor) + `TplinkDriver` (neuf).
- Moteur multi-cible : N cibles, score/circuit-breaker **par cible**.
- Config cibles (env numérotées) + rétro-compat mono-USG auto-synthétisée.
- Métriques 4G dans state / dashboard / Prometheus / notifications.
- Tests (unit + intégration mockée) ≥ 80 %, docs/migration.

### Out of scope (loggé, non traité)
- Failover WAN entre cibles (sites indépendants → pas de coordination).
- SMS / USSD TP-Link (la lib le permet — feature future).
- DDNS/Tailscale/Backup pour TP-Link (USG-spécifiques pour l'instant).
- Renommage du projet (cf. ADR, trigger explicite).
- HA peer multi-cible (la logique peer reste mono-device pour le moment).

## 4. Contraintes techniques

- Python ≥ 3.11 (projet) ∩ ≥ 3.10 (lib) → OK.
- Nouvelles deps : `tplinkrouterc6u==5.24.0` (pin), tire `pycryptodome`,
  `macaddress`, `requests`. Import **paresseux** : chargé seulement si ≥1 cible
  `tplink`.
- `TplinkDriver` : `TplinkRouterProvider.get_client(host, password)`
  (auto-détecte CBC/GCM), `authorize()`/`logout()` en try/finally (session
  unique), tous les appels wrappés (jamais de raise propagé).
- Immutabilité : `RouterHealth`, `RouterMetrics`, `WatchdogState` = frozen.
- Secrets : mot de passe TP-Link via env, `.env` 600, jamais loggé.
- `never raise` pour tout driver (convention existante des notifiers/usg).

### 4bis. Contraintes de compatibilité PROD (auto-updater) — BLOQUANTES

Vérifié dans le code : l'auto-updater tire `main` automatiquement, donc 1.9.0
sera déployé sur la box USG existante **sans intervention**. Trois contraintes
non négociables en découlent :

- **C1 — Import 100 % paresseux de `tplinkrouterc6u`.** `import tplinkrouterc6u`
  ne doit JAMAIS être au niveau module — uniquement dans le corps des méthodes
  de `TplinkDriver`. Raison : `updater/preflight.py` fait `import usg`,
  `import watchdog`, `import connectivity`. Si le refactor crée une chaîne
  `watchdog → targets → drivers/tplink → import lib` au niveau module, le
  preflight **échoue sur la box USG** (lib absente) → auto-update avorté +
  rollback. Test dédié : `python -c "import watchdog"` doit réussir **sans** la
  lib installée.
- **C2 — L'auto-updater n'installe pas les deps.** `updater/update.py` ne fait
  aucun `pip install` (seul `deploy.sh` le fait à l'install fraîche). Donc après
  auto-update, la lib n'est PAS dans le venv USG. Il faut **enrichir l'updater**
  pour relancer `pip install -r requirements.txt` quand `requirements.txt`
  change (hash/diff), idempotent et loggé. Sans ça, ajouter une cible TP-Link
  sur la box plante. → traité Sprint 5.
- **C3 — Contrat `/api/state` rétro-compatible.** `failure_score` (et les champs
  lus par `peer.py` : `threshold`, `gateway`, `internet`) doivent rester au
  **top-level** pour la cible USG. Raison : `peer.py` parse
  `WatchdogState.from_dict(get /api/state)` ; `from_dict` tolère les champs
  **ajoutés** mais pas **déplacés**. Garantit le rollout HA sans version-skew
  (1.8 ↔ 1.9). Idem métriques Prometheus : voir C4.
- **C4 — Métriques Prometheus legacy préservées.** La cible USG continue
  d'émettre `usg_watchdog_*` **sans label** (Grafana/alertes existantes
  intactes) ; les métriques labellisées `target="..."` sont **ajoutées** à côté,
  pas substituées.

## 5. Critères d'acceptation (globaux)

- [ ] Déploiement sans `TARGET_*` : comportement USG **identique** (test de
      non-régression vert).
- [ ] `RouterDriver` implémenté par `UsgDriver` et `TplinkDriver` ; aucun ne lève.
- [ ] Config N cibles parsée + validée au startup (IP/type valides).
- [ ] Score + circuit-breaker **indépendants par cible**.
- [ ] Reboot TP-Link via lib (mocké en test) déclenché au seuil, avec
      cooldown/backoff par cible.
- [ ] Métriques 4G (RSRP/RSRQ/SNR/network_type/sim/isp/data) dans `/api/state`,
      dashboard et `/metrics` (labels par cible).
- [ ] Notifications incluent le label de la cible concernée.
- [ ] **C1** : `python -c "import watchdog"` réussit **sans** `tplinkrouterc6u`
      installé (preflight USG survit à l'auto-update).
- [ ] **C2** : l'auto-updater installe les deps quand `requirements.txt` change.
- [ ] **C3** : `peer.py` parse `/api/state` d'une instance 1.9.0 sans erreur
      (`failure_score` top-level préservé).
- [ ] **C4** : `/metrics` expose toujours les `usg_watchdog_*` sans label.
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %.
- [ ] README + DEPLOY mis à jour (section multi-cible + migration).

---

## 6. Décomposition en sprints

> Ordre = dépendances (N+1 dépend de N). 5 sprints max. Chaque sprint :
> état buildable + tests verts.

### Sprint 1 — Abstraction `RouterDriver` + extraction `UsgDriver`
**But** : poser le contrat sans changer le comportement.
- `src/drivers/_base.py` : `RouterDriver` (Protocol), `RouterHealth`,
  `RouterMetrics` (frozen, champs nullable).
- `src/drivers/usg.py` : `UsgDriver` encapsulant le code SSH/ping existant
  (déplacé/wrappé depuis `usg.py` + `connectivity.py`), comportement identique.
- Tests : `UsgDriver` respecte le contrat, ne lève jamais, reboot/health
  inchangés.
- **C1 dès maintenant** : aucun nouveau module ne doit faire d'import
  vendor-lourd en tête. `python -c "import usg; import watchdog"` reste vert.
- **AC** : suite existante verte, nouveaux tests drivers verts.
- *Boundaries* : crée `src/drivers/*` ; modifie `usg.py` (façade de compat).

### Sprint 2 — `TplinkDriver` (lib `tplinkrouterc6u`)
**But** : piloter un MR 4G.
- `requirements.txt` : `tplinkrouterc6u==5.24.0`.
- `src/drivers/tplink.py` : `TplinkDriver` — `get_client` auto, `authorize`/
  `logout` try/finally, `reboot()`, `health()` (via `connect_status` +
  reachability), `metrics()` (mapping `LTEStatus`→`RouterMetrics` +
  `get_status`). Import paresseux.
- Tests : lib **mockée** (auth ok/ko, reboot, lte status complet/partiel,
  exceptions `AuthorizeError`/`ClientException` → jamais propagées).
- **C1 (bloquant)** : `import tplinkrouterc6u` **uniquement** dans le corps des
  méthodes de `TplinkDriver`, jamais au niveau module. Test :
  `python -c "import drivers.tplink"` réussit sans la lib installée (l'erreur
  d'import ne survient qu'à l'instanciation/usage d'une cible tplink).
- **AC** : `TplinkDriver` respecte le contrat ; logout garanti même sur erreur ;
  C1 vérifié.
- *Boundaries* : crée `src/drivers/tplink.py`, `tests/test_drivers_tplink.py` ;
  modifie `requirements.txt`.

### Sprint 3 — Moteur multi-cible (cœur)
**But** : passer de 1 à N cibles, score/circuit-breaker par cible. **Sprint le
plus risqué.**
- `src/config.py` : parsing `TARGET_<n>_*` + validation ; rétro-compat (aucune
  cible → synthèse USG depuis `USG_*`).
- `src/targets.py` : `MonitoredTarget` (id, label, driver, trackers, état
  scoring/CB).
- `src/state.py` : `WatchdogState` par cible ; holder = `dict[id->state]` +
  agrégat. Suppression des singletons latence de `connectivity.py`.
- `src/watchdog.py` : boucle itérant les cibles (séquentiel).
- Tests : non-régression mono-USG (**critère bloquant**) + 2 cibles divergentes
  (une down → reboot ciblé, l'autre intacte).
- **AC** : non-régression verte + reboot ciblé prouvé.
- *Boundaries* : modifie `config.py`, `state.py`, `connectivity.py`,
  `watchdog.py` ; crée `targets.py`.

### Sprint 4 — Observabilité multi-cible
**But** : rendre les N cibles + le 4G visibles.
- `src/http_server.py` : `/api/state` multi-cible. **C3** : `failure_score` +
  champs lus par `peer.py` restent au **top-level** pour la cible USG (clé
  legacy) ; les cibles s'ajoutent sous une clé `targets`.
- `src/dashboard.py` : carte par cible + bloc signal 4G (RSRP/RSRQ/SNR/réseau/
  SIM/conso).
- `src/metrics.py` : **C4** — `usg_watchdog_*` **sans label** conservés pour la
  cible USG ; métriques labellisées `target="..."` **ajoutées** à côté + champs
  4G.
- `src/messages.py` / notifier : label de cible dans les messages.
- Tests : endpoints + rendu metrics avec 2 cibles ; **C3** : `peer.parse` OK sur
  le nouveau `/api/state` ; **C4** : assert présence des métriques legacy.
- **AC** : dashboard et `/metrics` exposent le 4G ; C3 + C4 verts ; format state
  versionné.
- *Boundaries* : modifie `http_server.py`, `dashboard.py`, `metrics.py`,
  `messages.py`, notifier ; lecture seule `peer.py` (contrat à ne pas casser).

### Sprint 5 — Auto-updater, docs, migration, release
**But** : livrable propre + survie de la box USG à l'auto-update.
- **C2 (bloquant)** : `updater/update.py` — relancer `pip install -r
  requirements.txt` dans le venv quand `requirements.txt` change (diff/hash
  entre release courante et nouvelle), idempotent, loggé, échec → rollback.
- `updater/preflight.py` : valider les nouveaux modules (`drivers`, `targets`)
  **sans** tirer `tplinkrouterc6u` (preflight reste vert sans la lib).
- `README.md` + `DEPLOY.md` : section multi-cible, exemples `TARGET_*`, prérequis
  TP-Link (Local Password, single-session, HTTPS optionnel), **note migration
  prod** (auto-update transparent USG-only ; `pip install` géré par l'updater).
- `CLAUDE.md` : architecture drivers + moteur multi-cible.
- `scripts/validate.sh` : vérifie import lib si cible tplink.
- Bump 1.9.0, sync `dev`→PR→`main`.
- Tests : C2 — l'updater détecte un `requirements.txt` modifié et déclenche le
  `pip install` (mocké) ; preflight vert sans la lib.
- **AC** : `validate.sh` vert, C2 vert, preflight vert sans lib, docs à jour,
  version bumpée.
- *Boundaries* : modifie `updater/update.py`, `updater/preflight.py`, docs,
  `scripts/validate.sh`, `VERSION`.

---

## 7. Risques & mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Régression surveillance USG | Critique | Test non-régression bloquant (Sprint 3) ; rétro-compat verrouillée |
| Lock session admin TP-Link | Moyen | `logout()` en try/finally systématique |
| Mismatch cipher CBC/GCM | Moyen | `TplinkRouterProvider.get_client()` auto-détecte |
| Champs LTE absents (firmware) | Faible | Champs `None`, dégradation propre |
| Fuite mot de passe TP-Link | Élevé | Env only, `.env` 600, jamais loggé |
| Reboot en boucle TP-Link | Moyen | Circuit-breaker + cooldown **par cible** |
| Lib GPLv3 vs distribution | Faible (perso) | Tracé dans l'ADR ; sous-process si distribution future |
| **Preflight casse à l'auto-update** (import lib en tête) | **Critique** | C1 : import paresseux + test `import watchdog` sans lib |
| **Lib absente après auto-update** (pas de pip) | **Élevé** | C2 : updater relance `pip install` sur diff `requirements.txt` |
| **HA peer cassé par nouveau /api/state** | Moyen | C3 : `failure_score` top-level préservé |
| **Grafana/alertes cassées par labels** | Moyen | C4 : métriques `usg_watchdog_*` legacy conservées |

## 8. Definition of Done
- Tous les AC §5 cochés, 5 sprints verts, coverage ≥ 80 %, `validate.sh` vert,
  docs à jour, v1.9.0 taggée, `dev` synchronisé avec `main`.
