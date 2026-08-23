# Sprint 4 — Escalade re-priorisée, gabarits messages re-ciblés, TTL 600s

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1500-ntfy-first-sortie-telegram.md` (§ 5 en entier, § 3.4, § 8 S4, § 9 AC fonctionnel, § 0bis Q4/Q5/Q6)
- **Dépend de** : Sprint 1 (priorités/tags ntfy), Sprint 2 (`CONFIRM_TTL` 600s, boutons ntfy), Sprint 3 (dashboard, indépendant sur les fichiers)
- **Taille estimée** : 60-75 min
- **Isolation** : worktree

## Objectif important — ce que ce sprint N'EST PAS

Le PRD § 8 (table S1-S5 originale) décrivait ce sprint comme portant aussi
« déploiement manuel de `2.2.0-rc1` sur les 4 Pi et exécution du protocole du
§ 6.2 » (double-run de 7 jours). **Décision du 2026-08-23 (soir), Q4** :
il n'y a **pas** de double-run. Ce sprint livre uniquement le code de
l'escalade re-priorisée et des gabarits — la vérification en conditions
réelles est le sprint 5, avant le démantèlement. Ne pas reconstruire de
mécanisme de double-run ici.

## Objectif réel

1. Re-prioriser l'escalade d'alertes (§ 5) : `Priority: 5` + tag `sos` +
   titre `[RELANCE]`, **sans bouton d'action**, sur Ntfy, avec Email comme
   second canal garanti.
2. Purger `src/messages.py` du rendu HTML orienté Telegram, le remplacer par
   un rendu texte structuré conforme au sous-ensemble Markdown dégradable
   (§ 3.4, décision Q6).
3. Propager la conséquence du TTL 600s (sprint 2, décision Q5) dans les
   messages/tests qui assumaient encore 120s.

## Contexte technique vérifié

- `src/alert_escalation.py` (49 lignes) : `EscalationTracker` — totalement
  agnostique du canal (`on_critical()` L25-29, `on_recovery()` L31-34,
  `should_escalate()` L36-49). **Aucun changement de logique requis** dans
  ce fichier — le PRD le confirme explicitement (§ 5.1 : « n'a rien à
  recâbler »). Ce sprint ne touche ce fichier que si un test doit être
  ajouté, pas la logique elle-même.
- La ré-émission de l'escalade se fait dans `watchdog.py` via `notify()` —
  c'est là que le formatage `[RELANCE]` + `Priority: 5` + tag `sos` +
  absence de bouton doit être injecté (probablement via
  `NotificationContext`, cohérent avec le pattern `category` introduit au
  sprint 1 — envisager `category="escalation"` ou un champ dédié
  `no_action_buttons: bool` si `_ntfy.py` doit savoir ne pas générer de
  boutons pour ce message).
- `src/messages.py` (499 lignes) : gabarits « quoi / pourquoi / quoi faire »
  à conserver comme structure. Le rendu HTML Telegram doit disparaître (il
  n'est plus consommé par aucun canal après ce sprint, mais **ne pas encore
  supprimer `_telegram.py` lui-même** — ça reste le sprint 5).
- `src/confirm.py` : `DEFAULT_TTL_SECONDS` déjà à `600.0` depuis le sprint
  2. Ce sprint vérifie qu'aucun message ou test résiduel n'annonce encore
  « 120 secondes » à l'utilisateur (ex. un gabarit qui dirait « ce lien
  expire dans 2 minutes »).

## Étapes concrètes

### 1. Escalade re-priorisée (`src/watchdog.py`, `src/alert_escalation.py` si un test est nécessaire)

- Quand `should_escalate()` renvoie `True`, le message de ré-émission passe
  avec un contexte qui fait produire à `_ntfy.py` : `Priority: 5`, tag
  `sos` en plus des tags habituels, titre préfixé `[RELANCE]`, **et aucun
  bouton `Actions`** (contrairement à une notification de confirmation
  normale du sprint 2).
- Vérifier que l'email reçoit bien l'escalade (`SMTP_MIN_LEVEL=WARNING`
  déjà suffisant par défaut, § 5.1) — pas de changement de code requis côté
  email, seulement un test qui le confirme.
- **Pas d'ACK, pas de bouton sur l'escalade** (§ 5.3) : confirmer par test
  qu'aucune `Actions` n'est générée pour un message de catégorie escalade.

### 2. Gabarits `messages.py` conformes au Markdown dégradable

- Retirer tout rendu HTML orienté Telegram des gabarits (balises `<b>`,
  `<i>`, etc. si présentes).
- Sous-ensemble autorisé (§ 3.4, décision Q6) : `**gras**`, listes `-`,
  blocs de code courts. **Interdits** : tableaux Markdown, liens
  `[texte](url)` dans le corps.
- Ajouter un test qui parcourt tous les gabarits de `messages.py` et vérifie
  qu'aucun ne contient de motif de tableau (`|---|`) ni de lien Markdown
  (`\[.+\]\(.+\)`).
- Vérifier qu'aucun message généré ne dépasse 4 096 octets (la troncature
  vit dans `_ntfy.py` depuis le sprint 1, mais un test ici doit confirmer
  qu'aucun gabarit « nu » avant troncature n'induit une perte d'information
  critique — ex. le nom de l'action à confirmer ne doit jamais être dans la
  partie tronquée).

### 3. Cohérence du TTL 600s

- `grep -rn "120" src/messages.py tests/` pour repérer toute référence
  résiduelle à l'ancien TTL en dur (documentation utilisateur dans un
  message, assertion de test) et la mettre à jour vers 600s ou vers une
  référence dynamique à `CONFIRM_TTL`/`DEFAULT_TTL_SECONDS` plutôt qu'une
  valeur en dur dupliquée.

## Ne pas toucher

- `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/notifier/_pushover.py`, `src/notifier/_discord.py`,
  `src/notifier/_slack.py` : intacts jusqu'au sprint 5.
- Ne pas introduire de logique de déploiement `2.2.0-rc1` ni de protocole de
  double-run — obsolète (décision Q4).

## Fichiers

- **files_to_create** : aucun
- **files_to_modify** : `src/alert_escalation.py` (tests seulement, a
  priori), `src/watchdog.py`, `src/messages.py`, `src/notifier/_ntfy.py`
  (si `category`/`no_action_buttons` nécessite un ajustement), 
  `tests/test_alert_escalation.py`, `tests/test_messages.py`,
  `tests/test_watchdog.py`
- **files_read_only** : `src/confirm.py`, `src/config.py`
- **forbidden** : `src/telegram_bot.py`, `src/notifier/_telegram.py`,
  `src/notifier/_pushover.py`, `src/notifier/_discord.py`,
  `src/notifier/_slack.py`

## Critères d'acceptation

- [ ] `./scripts/validate.sh` vert, coverage ≥ 80 %
- [ ] Escalade simulée → reçue en `Priority: 5`, tag `sos`, titre
      `[RELANCE]`, **sans** `Actions`, sur ntfy **et** par email (test)
- [ ] Aucun gabarit de `messages.py` hors sous-ensemble Markdown dégradable
      (test automatisé, pas une revue manuelle)
- [ ] Aucun message généré > 4 096 octets (test)
- [ ] Aucune référence résiduelle à un TTL de 120s dans les messages ou les
      tests (grep + revue)
- [ ] `grep -rn "2.2.0-rc1\|double-run" src/ tests/` ne renvoie aucune
      occurrence introduite par ce sprint
