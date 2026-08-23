"""Tests for alert_escalation.py -- EscalationTracker logic."""

import time
from unittest import mock

import pytest

from src.alert_escalation import EscalationTracker


class TestEscalationTrackerOnCritical:
    def test_records_timestamp_on_first_critical(self):
        tracker = EscalationTracker()
        assert tracker._critical_at == 0.0
        with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
            tracker.on_critical()
        assert tracker._critical_at == 1000.0

    def test_second_on_critical_does_not_overwrite_timestamp(self):
        tracker = EscalationTracker()
        with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
            tracker.on_critical()
        with mock.patch("src.alert_escalation.time.time", return_value=2000.0):
            tracker.on_critical()
        assert tracker._critical_at == 1000.0

    def test_escalated_flag_starts_false(self):
        tracker = EscalationTracker()
        with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
            tracker.on_critical()
        assert tracker._escalated is False


class TestEscalationTrackerShouldEscalate:
    def test_returns_true_after_delay_passes(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 5),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            # 5 minutes + 1 second later
            with mock.patch(
                "src.alert_escalation.time.time", return_value=1000.0 + 5 * 60 + 1
            ):
                result = tracker.should_escalate()
        assert result is True

    def test_returns_false_when_not_enough_time_elapsed(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 5),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            # Only 1 minute has passed, delay is 5
            with mock.patch("src.alert_escalation.time.time", return_value=1060.0):
                result = tracker.should_escalate()
        assert result is False

    def test_returns_false_when_no_critical_recorded(self):
        tracker = EscalationTracker()
        with mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True):
            result = tracker.should_escalate()
        assert result is False

    def test_returns_false_when_disabled_via_config(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", False),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 1),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            with mock.patch(
                "src.alert_escalation.time.time", return_value=1000.0 + 60 + 1
            ):
                result = tracker.should_escalate()
        assert result is False

    def test_fires_only_once(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 1),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            far_future = 1000.0 + 10 * 60
            with mock.patch("src.alert_escalation.time.time", return_value=far_future):
                first = tracker.should_escalate()
                second = tracker.should_escalate()
        assert first is True
        assert second is False

    def test_escalated_flag_set_after_trigger(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 1),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0 + 61):
                tracker.should_escalate()
        assert tracker._escalated is True


class TestEscalationTrackerOnRecovery:
    def test_resets_all_state(self):
        tracker = EscalationTracker()
        with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
            tracker.on_critical()
        tracker._escalated = True
        tracker.on_recovery()
        assert tracker._critical_at == 0.0
        assert tracker._escalated is False

    def test_should_escalate_returns_false_after_recovery(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 1),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            tracker.on_recovery()
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0 + 61):
                result = tracker.should_escalate()
        assert result is False

    def test_can_escalate_again_after_recovery_and_new_critical(self):
        tracker = EscalationTracker()
        with (
            mock.patch("src.alert_escalation.ALERT_ESCALATION_ENABLED", True),
            mock.patch("src.alert_escalation.ALERT_ESCALATION_DELAY", 1),
        ):
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0):
                tracker.on_critical()
            with mock.patch("src.alert_escalation.time.time", return_value=1000.0 + 61):
                tracker.should_escalate()  # fires once
            tracker.on_recovery()
            # New incident
            with mock.patch("src.alert_escalation.time.time", return_value=2000.0):
                tracker.on_critical()
            with mock.patch("src.alert_escalation.time.time", return_value=2000.0 + 61):
                result = tracker.should_escalate()
        assert result is True
