"""Stub requis par le hook TDD local (`check-test-exists.sh`), qui attend un
fichier `tests/test_tplink.py` pour `src/drivers/tplink.py` (correspondance
sur le seul nom de base du module).

Les tests reels de `TplinkDriver` vivent dans `tests/test_drivers_tplink.py`,
conformement aux frontieres de fichiers du Sprint 2
(`docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/sprints/02-tplink-driver.md`,
section "Frontieres de fichiers" : Creer = `src/drivers/tplink.py`,
`tests/test_drivers_tplink.py`). Meme precedent que `_base.py` / son propre
fichier de tests dedie au Sprint 1.
"""
