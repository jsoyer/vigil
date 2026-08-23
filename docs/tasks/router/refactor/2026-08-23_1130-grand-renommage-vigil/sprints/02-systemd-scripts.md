# Sprint 2 — Unités systemd, scripts et arborescence `/opt/vigil`

- **PRD parent** : `docs/tasks/router/refactor/2026-08-23_1130-grand-renommage-vigil.md` (§ 2.2, § 2.3, § 2.4, § 7 S2)
- **Dépend de** : Sprint 1 (nom de dépôt et URLs stabilisés)
- **Taille estimée** : 60-90 min
- **Isolation** : worktree

## Objectif

Créer les 4 nouvelles unités systemd (`vigil.service`, `vigil-updater.service`,
`vigil-updater.timer`, `vigil.logrotate`), adapter les 7 scripts de
`scripts/` aux nouveaux noms/chemins, corriger au passage le bug latent
`ReadWritePaths` du fichier d'événements (§ 2.2 du PRD), et rendre
`uninstall.sh` capable de nettoyer l'ancien nom. Les anciennes unités
`systemd/usg-watchdog*` **restent dans le dépôt**, non supprimées — elles
documentent le service encore actif sur les Pi non migrés pendant la fenêtre
de rollback.

## Étapes concrètes

1. **Créer `systemd/vigil.service`** (nouveau fichier, copie adaptée de
   `systemd/usg-watchdog.service`) :
   - `Description=Vigil -- surveillance de connexion et reboot automatique du routeur USG Ubiquiti`
     (garder la mention explicite du routeur USG, cf. PRD § 3).
   - `User=`/`Group=` → `vigil`.
   - `WorkingDirectory=/opt/vigil/current/src`.
   - `ExecStart=/opt/vigil/venv/bin/python /opt/vigil/current/src/watchdog.py`
     (le fichier reste `watchdog.py`, décision Q8).
   - `EnvironmentFile=-/opt/vigil/.env`.
   - `SyslogIdentifier=vigil`.
   - `ReadOnlyPaths=/opt/vigil`.
   - `ReadWritePaths=/var/log/vigil.log /var/log/vigil-events.json` — **les
     deux chemins**, c'est le fix du bug latent : l'ancien unit n'autorisait en
     écriture que le log principal, pas le fichier d'événements JSON persisté
     par `src/events.py:46`, qui échouait donc probablement en silence sous
     `ProtectSystem=strict` depuis toujours.

2. **Créer `systemd/vigil-updater.service`** (copie adaptée de
   `systemd/usg-watchdog-updater.service`) : `Description`, `After=…
   vigil.service`, `WorkingDirectory`, `ExecStart`, `EnvironmentFile`,
   `SyslogIdentifier=vigil-updater`.

3. **Créer `systemd/vigil-updater.timer`** (copie adaptée) : `Description`
   seulement change, la fenêtre 03:00 ± 10 min reste identique.

4. **Créer `systemd/vigil.logrotate`** (copie adaptée de
   `systemd/usg-watchdog.logrotate`) : chemin `/var/log/vigil.log`, `create
   0640 vigil adm`, `systemctl kill -s HUP vigil.service`.

5. **`scripts/deploy.sh`** :
   - `:10 INSTALL_DIR` → `/opt/vigil`.
   - `:11 SERVICE_NAME` → `vigil`.
   - `:12 SERVICE_USER` → `vigil`.
   - **Créer un nouvel utilisateur** `vigil` (`useradd` classique), ne
     **jamais** utiliser `usermod -l` sur le compte `usg-watchdog` existant —
     décision Q1 explicite : l'ancien compte reste utilisable pendant toute la
     fenêtre de rollback, et n'est supprimé qu'à J+7 par une opération séparée
     (sprint 5, § 5.4 du PRD).
   - `:173-178` (log), `:182` (logrotate), `:188-196` (noms des units),
     `:206-207` (timer), `:233-235` (messages) → adapter aux nouveaux noms.
   - Le venv doit être **recréé** (`python3 -m venv` + `pip install -r
     requirements.txt`), jamais copié — c'est un invariant opérationnel du
     PRD § 5.1 (paramiko/paho-mqtt cassent en silence si le `pyvenv.cfg`
     pointe sur l'ancien chemin).

6. **`scripts/uninstall.sh`** :
   - `:8-10` (service/user/dir), `:71-73` (logs) → adapter à `vigil`.
   - **Ajouter la capacité de désinstaller l'ancien nom** : le script doit
     pouvoir détecter et nettoyer `usg-watchdog.service`,
     `/opt/usg-watchdog`, l'utilisateur `usg-watchdog` (avec la même
     précaution `find -xdev -user usg-watchdog` avant `userdel`, cf. PRD
     § 5.4) — utile pour la purge finale J+7 du sprint 5, sans dupliquer le
     runbook ailleurs.

7. **`scripts/setup_ssh.sh`** : `:15 SSH_DIR`, `:18 KEY_COMMENT` (→
   `vigil@$(hostname)`, cf. PRD § 3 cas limites — identifie la machine
   émettrice), `:52` (bannière).

8. **`scripts/test.sh`** : `:10 INSTALL_DIR`, `:28 ENV_FILE`, `:44`, `:102`
   (bannières/messages).

9. **`scripts/release.sh`** : `:3` (commentaire uniquement).

10. **`scripts/lib/logging.sh`** : `:3` (commentaire uniquement).

## Fichiers

- **files_to_create** : `systemd/vigil.service`,
  `systemd/vigil-updater.service`, `systemd/vigil-updater.timer`,
  `systemd/vigil.logrotate`
- **files_to_modify** : `scripts/deploy.sh`, `scripts/uninstall.sh`,
  `scripts/setup_ssh.sh`, `scripts/test.sh`, `scripts/validate.sh`,
  `scripts/release.sh`, `scripts/lib/logging.sh`
- **files_read_only** : `systemd/usg-watchdog.service`,
  `systemd/usg-watchdog-updater.service`, `systemd/usg-watchdog-updater.timer`,
  `systemd/usg-watchdog.logrotate` (ne pas supprimer, ne pas modifier)
- **forbidden** : `src/`, `updater/update.py` (sprint 3)

## Critères d'acceptation

- [ ] `bash -n` passe sur les 7 scripts modifiés
- [ ] `systemd-analyze verify systemd/vigil.service
      systemd/vigil-updater.service systemd/vigil-updater.timer` ne retourne
      aucune erreur
- [ ] `systemd/vigil.service` liste `/var/log/vigil.log` **et**
      `/var/log/vigil-events.json` dans `ReadWritePaths`
- [ ] `scripts/deploy.sh` crée un nouvel utilisateur `vigil` via `useradd` —
      `grep -n 'usermod -l' scripts/deploy.sh` ne renvoie rien
- [ ] `scripts/deploy.sh` recrée le venv (`python3 -m venv` présent, aucune
      commande `cp -a .../venv` ou équivalent)
- [ ] `scripts/uninstall.sh` sait désinstaller à la fois `vigil` et
      `usg-watchdog` (deux chemins de nettoyage distincts, avec la garde
      `find -xdev -user` avant `userdel` sur les deux)
- [ ] `systemd/usg-watchdog*` (4 fichiers) : diff vide, toujours présents
- [ ] Déploiement réel sur le Pi cobaye (dijon-slave, `bbh-dij-guardian`) :
      `sudo scripts/deploy.sh` termine sans erreur, `curl -s :PORT/health`
      répond (peut encore annoncer une version antérieure à ce stade — la
      version 2.0.0 complète n'est livrée qu'au sprint 5 ; ce sprint vérifie
      seulement que les units et le script de déploiement fonctionnent
      mécaniquement, pas que le code applicatif est déjà migré)

**Important — nettoyage après le test de déploiement sur le Pi cobaye** : ce
déploiement est un test mécanique des scripts/units, pas la migration réelle
(qui a son propre runbook au sprint 5, avec gel des timers et ordre
slave→master). Une fois `/health` vérifié : `systemctl disable --now vigil`
sur `bbh-dij-guardian` avant de clore le sprint, pour ne pas laisser un
`vigil.service` actif en parallèle de `usg-watchdog.service` en dehors de la
fenêtre de migration contrôlée du sprint 5. Ne pas supprimer `/opt/vigil`
(peut être réutilisé tel quel au sprint 5) ; ne pas toucher au timer updater
de ce Pi (`usg-watchdog-updater.timer` reste tel qu'il était avant ce test).
