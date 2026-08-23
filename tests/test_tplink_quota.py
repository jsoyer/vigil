"""Tests -- suivi de quota data TP-Link, robuste aux remises a zero du
compteur et aux bascules de cycle de facturation (C20, Sprint 1 A2)."""

import sys
import os
import tempfile
import time
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _tmp_quota_path():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # QuotaStore doit tolerer un fichier absent au demarrage
    return path


class TestQuotaAccumulation:
    def test_growing_counter_produces_correct_percentage(self):
        from history import QuotaStore

        path = _tmp_quota_path()
        store = QuotaStore(persist_path=path)
        now = time.time()

        store.record_reading("1", 1_000_000, reset_day=1, now=now)
        state = store.record_reading("1", 3_000_000, reset_day=1, now=now + 60)

        assert state.accumulated_bytes == 2_000_000

    def test_counter_decrease_is_treated_as_reset_not_negative_consumption(self):
        from history import QuotaStore

        path = _tmp_quota_path()
        store = QuotaStore(persist_path=path)
        now = time.time()

        store.record_reading("1", 5_000_000, reset_day=1, now=now)
        state = store.record_reading("1", 500_000, reset_day=1, now=now + 60)

        assert state.accumulated_bytes == 5_000_000 + 500_000
        assert state.accumulated_bytes >= 0

    def test_reset_from_commanded_reboot_preserves_cycle_consumption(self):
        """Un reboot commande (A1) remet le compteur routeur a zero -- le
        cycle de facturation n'est PAS reinitialise pour autant, la conso
        deja comptee reste acquise."""
        from history import QuotaStore

        path = _tmp_quota_path()
        store = QuotaStore(persist_path=path)
        now = time.time()

        state_before = store.record_reading("1", 2_000_000, reset_day=1, now=now)
        cycle_start_before = state_before.cycle_start

        state_after_reset = store.record_reading(
            "1", 100_000, reset_day=1, now=now + 30
        )

        assert state_after_reset.cycle_start == cycle_start_before
        assert state_after_reset.accumulated_bytes == 2_000_000 + 100_000

    def test_missing_counter_field_creates_no_state(self):
        from history import QuotaStore

        path = _tmp_quota_path()
        store = QuotaStore(persist_path=path)

        result = store.record_reading("1", None, reset_day=1)

        assert result is None
        assert store.get_state("1") is None


class TestQuotaPersistence:
    def test_survives_simulated_service_restart(self):
        from history import QuotaStore

        path = _tmp_quota_path()
        now = time.time()

        store1 = QuotaStore(persist_path=path)
        store1.record_reading("1", 1_000_000, reset_day=1, now=now)
        store1.record_reading("1", 2_500_000, reset_day=1, now=now + 60)

        store2 = QuotaStore(persist_path=path)
        state = store2.get_state("1")

        assert state is not None
        assert state.accumulated_bytes == 1_500_000
        assert state.last_raw_counter == 2_500_000


class TestBillingCycleC20:
    """C20 -- les quatre regles du jour de facturation."""

    def test_cycle_switches_at_local_midnight_not_utc(self):
        from history import _cycle_boundary_for

        boundary_before = _cycle_boundary_for(date(2026, 3, 14), reset_day=15)
        boundary_on = _cycle_boundary_for(date(2026, 3, 15), reset_day=15)

        assert boundary_before == date(2026, 2, 15)
        assert boundary_on == date(2026, 3, 15)

    def test_reset_day_31_in_30_day_month_clamps_to_last_day(self):
        from history import _clamp_reset_day

        assert _clamp_reset_day(2026, 4, 31) == 30
        assert _clamp_reset_day(2026, 2, 31) == 28
        assert _clamp_reset_day(2024, 2, 31) == 29

    def test_boundary_computed_on_calendar_date_not_elapsed_hours(self):
        """Un jour de changement d'heure fait 23 ou 25h -- la bascule ne
        doit jamais deriver d'un calcul en secondes/heures ecoulees."""
        from history import _cycle_boundary_for, _local_midnight_epoch

        boundary = _cycle_boundary_for(date(2026, 3, 30), reset_day=29)
        assert boundary == date(2026, 3, 29)
        epoch = _local_midnight_epoch(boundary)
        assert isinstance(epoch, float)

    def test_missed_reset_while_service_stopped_closes_cycle_on_restart(self):
        """Le service etait arrete au moment de la bascule -- le premier
        releve au redemarrage doit constater que la date est passee et
        cloturer le cycle, meme des mois plus tard, pas l'ignorer."""
        from history import QuotaStore

        path = _tmp_quota_path()
        store = QuotaStore(persist_path=path)

        jan_1 = time.mktime(datetime(2026, 1, 1, 10, 0, 0).timetuple())
        store.record_reading("1", 1_000_000, reset_day=1, now=jan_1)

        march_5 = time.mktime(datetime(2026, 3, 5, 9, 0, 0).timetuple())
        state = store.record_reading("1", 42, reset_day=1, now=march_5)

        assert state.accumulated_bytes == 0
        boundary = datetime.fromtimestamp(state.cycle_start).date()
        assert boundary == date(2026, 3, 1)

    def test_crossing_billing_day_starts_new_cycle(self):
        from history import QuotaStore

        path = _tmp_quota_path()
        store = QuotaStore(persist_path=path)

        day1 = time.mktime(datetime(2026, 5, 1, 12, 0, 0).timetuple())
        store.record_reading("1", 5_000_000, reset_day=1, now=day1)

        day2_next_cycle = time.mktime(datetime(2026, 6, 1, 12, 0, 0).timetuple())
        state = store.record_reading("1", 100, reset_day=1, now=day2_next_cycle)

        assert state.accumulated_bytes == 0
