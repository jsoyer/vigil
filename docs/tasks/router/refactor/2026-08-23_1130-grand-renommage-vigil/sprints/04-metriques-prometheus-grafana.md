# Sprint 4 — Métriques Prometheus et Grafana (bascule sèche)

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil.md` (§ 2.6, § 0bis Q2, § 7 S4)
- **Dépend de** : Sprint 1, Sprint 2, Sprint 3 (conventions de chemin et de libellé stabilisées)
- **Taille estimée** : 30-40 min (sprint le plus court — simplifié par la décision Q2)
- **Isolation** : worktree

## Objectif — décision Q2 du 2026-08-23 : BASCULE SÈCHE

Le PRD initial (§ 2.6) recommandait une **double émission transitoire**
(`vigil_*` canonique + `usg_watchdog_*` déprécié, retrait en 2.1.0).
**L'utilisateur a tranché pour une bascule sèche le 2026-08-23** (§ 0bis du
PRD, décision Q2) : `vigil_*` seul dès la 2.0.0, **aucune double émission**.
Confirmé à cette date : aucune règle d'alerte Prometheus/Alertmanager hors
dépôt ne dépend des séries actuelles — la question complémentaire du § 10 Q2
est donc close sans inventaire à mener.

**Ce sprint est un renommage direct**, pas une implémentation de mécanisme de
dépréciation. Ne pas ajouter de commentaire `DEPRECATED`, ne pas prévoir de
retrait en 2.1.0 — il n'y a rien à retirer plus tard, tout est fait ici.

## Étapes concrètes

1. **`src/metrics.py`** : renommer directement le préfixe des 19 séries
   `usg_watchdog_*` → `vigil_*` :
   `_up`, `_uptime_seconds`, `_failure_score`, `_score_threshold`,
   `_gateway_up`, `_internet_targets_{up,total}`, `_gateway_rtt_ms`,
   `_internet_avg_rtt_ms`, `_latency_degraded`, `_reboots_total`,
   `_reboots_today`, `_surveillance_mode`, `_isp_outage`, `_ssh_failures`,
   `_peer_{up,score}`, `_instance_priority`. Simple remplacement du préfixe de
   chaîne, aucun changement de type de métrique, de labels ou de logique de
   calcul.

2. **`tests/test_metrics.py`** : les 34 occurrences passent de
   `usg_watchdog_*` à `vigil_*`. Ne pas dupliquer les assertions pour couvrir
   « les deux familles » — il n'y a qu'une famille après ce sprint.

3. **`grafana/dashboard.json`** : les 8 références aux séries deviennent
   `vigil_*`. Pas de panel de transition, pas de requête qui interroge les
   deux préfixes.

4. **Documentation des métriques** (si elle existe en dehors de
   `grafana/dashboard.json` — vérifier `README.md`/`DEPLOY.md` pour une
   section Prometheus qui listerait les noms de séries ; sinon rien à faire
   ici, ces fichiers sont déjà couverts par le sprint 1).

5. **Notes de version** : ne pas rédiger `docs/RELEASE-NOTES-2.0.0.md` dans ce
   sprint (c'est le sprint 5) — mais noter dans le message de commit que la
   rupture d'historique Prometheus est **assumée et documentée**, pour que le
   sprint 5 la reprenne mot pour mot dans les notes de version.

## Fichiers

- **files_to_modify** : `src/metrics.py`, `tests/test_metrics.py`,
  `grafana/dashboard.json`
- **files_read_only** : `src/config.py`
- **forbidden** : `src/mqtt_publisher.py`, `tests/test_mqtt_publisher.py`
  (identité HA figée, hors périmètre de ce sprint et de tout ce PRD)

## Critères d'acceptation

- [ ] `/metrics` (serveur de test local) expose les 19 séries `vigil_*`
- [ ] `curl -s http://localhost:$HTTP_PORT/metrics | grep -c '^usg_watchdog_'`
      = **0** (bascule sèche — aucune série héritée résiduelle)
- [ ] `tests/test_metrics.py` : toutes les assertions portent sur `vigil_*`,
      aucune assertion sur `usg_watchdog_*`
- [ ] `grep -c usg_watchdog grafana/dashboard.json` = 0
- [ ] Aucun commentaire `DEPRECATED` ni logique de double émission dans
      `src/metrics.py` (`grep -n DEPRECATED src/metrics.py` vide)
- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] `git diff --stat -- src/mqtt_publisher.py tests/test_mqtt_publisher.py`
      vide
