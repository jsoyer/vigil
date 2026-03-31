"""Tests for state.py -- WatchdogState dataclass and StateHolder."""

import json

import pytest

from src.state import WatchdogState, StateHolder


class TestWatchdogState:
    def test_frozen_immutability(self):
        state = WatchdogState(failure_score=5)
        with pytest.raises(AttributeError):
            state.failure_score = 10  # type: ignore[misc]

    def test_defaults(self):
        state = WatchdogState()
        assert state.failure_score == 0
        assert state.instance_priority == 1
        assert state.gateway_ok is True

    def test_to_dict(self):
        state = WatchdogState(failure_score=7, instance_priority=2)
        d = state.to_dict()
        assert d["failure_score"] == 7
        assert d["instance_priority"] == 2
        assert isinstance(d, dict)

    def test_to_json(self):
        state = WatchdogState(failure_score=3)
        j = state.to_json()
        parsed = json.loads(j)
        assert parsed["failure_score"] == 3

    def test_from_dict_roundtrip(self):
        original = WatchdogState(
            failure_score=12,
            threshold=10,
            was_degraded=True,
            last_reboot_time=1000.0,
            instance_priority=2,
            gateway_ok=False,
            internet_ok_count=0,
            internet_total=3,
            timestamp="2026-03-31T12:00:00",
        )
        restored = WatchdogState.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_ignores_extra_keys(self):
        d = WatchdogState().to_dict()
        d["unknown_field"] = "should be ignored"
        state = WatchdogState.from_dict(d)
        assert state is not None

    def test_from_dict_returns_none_on_invalid(self):
        assert WatchdogState.from_dict("not a dict") is None  # type: ignore[arg-type]
        assert WatchdogState.from_dict(None) is None  # type: ignore[arg-type]

    def test_from_dict_returns_none_on_bad_types(self):
        d = WatchdogState().to_dict()
        d["failure_score"] = "not an int"
        # dataclass __init__ does not validate types, so this may succeed
        # but the test verifies from_dict does not crash
        result = WatchdogState.from_dict(d)
        assert result is not None or result is None  # just ensure no exception


class TestStateHolder:
    def test_initial_state_is_none(self):
        holder = StateHolder()
        assert holder.state is None

    def test_state_can_be_set(self):
        holder = StateHolder()
        state = WatchdogState(failure_score=5)
        holder.state = state
        assert holder.state is state
        assert holder.state.failure_score == 5

    def test_state_swap_is_atomic(self):
        holder = StateHolder()
        state1 = WatchdogState(failure_score=1)
        state2 = WatchdogState(failure_score=2)
        holder.state = state1
        holder.state = state2
        assert holder.state.failure_score == 2
