# Sprint 3 — Dashboard : réparer l'authentification, combler les commandes manquantes

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram.md` (§ 4.3, § 4.5 en entier, § 8 S3, § 9 AC fonctionnel)
- **Dépend de** : Sprint 1 (aucun couplage fichier direct), Sprint 2 (partage la convention d'authentification `Authorization: Bearer API_TOKEN` — gardés séquentiels par choix du PRD § 8, pas par nécessité technique stricte)
- **Taille estimée** : 60-75 min
- **Isolation** : worktree

## Objectif

Corriger un bug bloquant découvert pendant la rédaction du PRD (§ 4.5) : les
3 boutons existants du dashboard (pause/resume/reboot) renvoient **403** dès
qu'`API_TOKEN` est configuré, c'est-à-dire en production — la « surface de
commande de repli » sur laquelle repose toute la sortie de Telegram ne
fonctionne pas aujourd'hui. Puis ajouter les boutons manquants pour couvrir
les 8 commandes historiques du bot (§ 4.5, tableau).

## Contexte technique vérifié

- `src/dashboard.py` : fonction `sendCommand(cmd)` (L506-522) :
  ```js
  async function sendCommand(cmd) {
    var feedback = document.getElementById('cmd-feedback');
    try {
      var res = await fetch('/api/' + cmd, { method: 'POST' });
      var data = await res.json();
      if (data.ok) { ... }
    } catch(err) { ... }
  }
  ```
  **Aucun en-tête `Authorization`** dans le `fetch`. `_check_auth()`
  (`http_server.py` L107-118) est fail-closed : `403` si `API_TOKEN` est
  vide, `401` si le header ne correspond pas — ici, le header est absent, la
  route bascule en 401 (pas 403, à corriger dans le libellé du PRD si
  besoin, mais le comportement observable reste un refus systématique).
  Boutons actuels : `btn-pause` (L164), `btn-resume` (L165), un bouton
  reboot appelant `confirmReboot()` (L526-530, qui appelle `sendCommand
  ('reboot')` après confirmation JS locale).
- Titre/header dashboard : `<title>Vigil</title>` (L9), `<h1>Vigil</h1>`
  (L160) — déjà corrects (renommage 2.0.0), rien à faire ici.
- Aucune section TP-Link n'existe dans `dashboard.py` aujourd'hui (aucune
  occurrence de `tplink`) — à créer entièrement.
- Endpoints déjà disponibles côté serveur (aucun n'est à créer dans ce
  sprint, seulement à câbler côté dashboard) : `POST /api/ddns/update`,
  `POST /api/backup/unifi`, `POST /api/tailscale/sync`,
  `POST /api/maintenance`, `POST /api/config/reload`,
  `GET /api/tplink`, `GET /api/tplink/<id>[/status]`,
  `POST /api/tplink/<id>/check`, `POST /api/tplink/<id>/reboot`,
  `POST /api/tplink/<id>/reboot/confirm`.

## Étapes concrètes

### 1. Corriger `sendCommand()` — le bug bloquant

- Le jeton `API_TOKEN` est saisi **une fois** par l'opérateur (prompt JS ou
  petit formulaire dans le dashboard), conservé en `sessionStorage`
  (**jamais `localStorage`** — pas de persistance après fermeture de
  l'onglet, exigence explicite du PRD).
- `sendCommand()` (et toute nouvelle fonction de commande ajoutée à l'étape
  2) injecte l'en-tête `Authorization: Bearer <jeton>` sur chaque `fetch`
  POST.
- Retour d'erreur explicite en `401` : message clair invitant à re-saisir le
  jeton (pas un échec silencieux).

### 2. Boutons manquants (§ 4.5 tableau)

Ajouter, dans une section « Actions » du dashboard existant :

| Bouton | Endpoint |
|---|---|
| DDNS | `POST /api/ddns/update` |
| Backup UniFi | `POST /api/backup/unifi` |
| Sync Tailscale | `POST /api/tailscale/sync` |
| Maintenance (optionnel selon le PRD, mais listé) | `POST /api/maintenance` |

Et une **nouvelle section TP-Link** complète :

- Liste des équipements gérés (`GET /api/tplink`).
- Statut par équipement (`GET /api/tplink/<id>/status`).
- Bouton « Vérifier » (`POST /api/tplink/<id>/check`).
- Bouton « Redémarrer » (`POST /api/tplink/<id>/reboot`) suivi du flux de
  confirmation existant (`POST /api/tplink/<id>/reboot/confirm`) — ce
  sprint réutilise le mécanisme HTTP déjà livré par A1 Sprint 3, il ne crée
  pas de nouveau mécanisme de confirmation (celui du sprint 2 de ce PRD est
  pour les boutons **ntfy**, pas pour le dashboard, qui a déjà son propre
  flux via `/api/tplink/*`).

### 3. Test bout-en-bout

- Depuis le dashboard (navigateur ou test Playwright/équivalent), avec
  `API_TOKEN` configuré : saisir le jeton, cliquer chacun des boutons
  existants et nouveaux, vérifier une réponse `200` et un retour visuel.
- Vérifier explicitement qu'aucun jeton n'apparaît en `localStorage` (test
  d'inspection du storage après interaction).

## Ne pas toucher

- `src/telegram_bot.py` : intact jusqu'au sprint 5.
- `src/confirm.py` : sprint 2, pas retouché ici — la confirmation TP-Link
  côté dashboard passe par `/api/tplink/*` existant, pas par
  `/api/confirm/*` (qui est réservé au flux ntfy → capacité, § 4.2).

## Fichiers

- **files_to_create** : aucun
- **files_to_modify** : `src/dashboard.py`, `tests/test_dashboard.py`
- **files_read_only** : `src/http_server.py`, `src/managed_devices.py`
- **forbidden** : `src/telegram_bot.py`, `src/confirm.py`

## Critères d'acceptation

- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] Les 3 boutons existants (pause/resume/reboot) fonctionnent avec
      `API_TOKEN` configuré (régression corrigée — aujourd'hui : 403/401)
- [ ] Chacune des 8 commandes historiques du bot (`/status`, `/pause`,
      `/resume`, `/reboot`, `/ddns`, `/backup`, `/tailscale`, `/lte`) a un
      équivalent cliquable dans le dashboard (`/status` : affichage passif
      déjà présent, § 4.3, rien à ajouter)
- [ ] Test bout-en-bout du reboot TP-Link depuis le dashboard (check →
      reboot → confirmation)
- [ ] Aucun jeton en `localStorage` (test), présent uniquement en
      `sessionStorage`
- [ ] Message d'erreur clair en `401` (jeton absent ou invalide)
