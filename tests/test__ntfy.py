"""Marqueur TDD pour notifier/_ntfy.py.

La suite de tests complete du canal Ntfy enrichi vit dans
tests/test_ntfy_notifier.py (nom impose par la spec du Sprint 1 du PRD
Ntfy-first). Ce fichier ne fait qu'un sanity check minimal pour satisfaire
la convention de nommage attendue par le hook TDD (test__<module>.py).
"""

from unittest import mock


def test_is_configured_false_when_unset():
    with (
        mock.patch("src.notifier._ntfy.NTFY_URL", ""),
        mock.patch("src.notifier._ntfy.NTFY_TOPIC", ""),
    ):
        from src.notifier._ntfy import is_configured

        assert is_configured() is False
