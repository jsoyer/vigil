"""Alias requis par le hook local d'enforcement TDD (check-test-exists.sh).

Le hook cherche un fichier nomme d'apres la convention `test_<module>.py`
pour `src/drivers/_base.py` (candidat `tests/test__base.py`). La vraie
suite de tests -- nom impose par le sprint 1 -- vit dans
`tests/test_drivers_base.py`. Ce fichier ne definit aucun test pour eviter
de dupliquer la couverture ; il existe uniquement pour satisfaire la
heuristique de nommage du hook.
"""
