"""Tests for events.py -- EventLog ring buffer and persistence."""

import json

import pytest

from src.events import Event, EventLog, REBOOT, RECOVERY, ISP_OUTAGE


class TestEvent:
    def test_to_dict(self):
        e = Event(ts="2026-03-31T12:00:00", type="reboot", data={"attempt": 1})
        d = e.to_dict()
        assert d["ts"] == "2026-03-31T12:00:00"
        assert d["type"] == "reboot"
        assert d["data"]["attempt"] == 1

    def test_frozen(self):
        e = Event(ts="2026-03-31T12:00:00", type="test")
        with pytest.raises(AttributeError):
            e.type = "other"  # type: ignore[misc]

    def test_default_data(self):
        e = Event(ts="2026-03-31T12:00:00", type="test")
        assert e.data == {}


class TestEventLog:
    def test_record_and_get_all(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record("reboot", attempt=1)
        log.record("recovery", duration="5min")

        events = log.get_all()
        assert len(events) == 2
        assert events[0]["type"] == "reboot"
        assert events[0]["data"]["attempt"] == 1
        assert events[1]["type"] == "recovery"
        assert events[1]["data"]["duration"] == "5min"

    def test_ring_buffer_evicts_oldest(self, tmp_path):
        log = EventLog(max_events=3, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record("a")
        log.record("b")
        log.record("c")
        log.record("d")  # "a" should be evicted

        events = log.get_all()
        assert len(events) == 3
        assert events[0]["type"] == "b"
        assert events[2]["type"] == "d"

    def test_get_recent(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        for i in range(10):
            log.record(f"event_{i}")

        recent = log.get_recent(3)
        assert len(recent) == 3
        assert recent[0]["type"] == "event_7"
        assert recent[2]["type"] == "event_9"

    def test_get_by_type(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record(REBOOT, attempt=1)
        log.record(RECOVERY, duration="5min")
        log.record(REBOOT, attempt=2)

        reboots = log.get_by_type(REBOOT)
        assert len(reboots) == 2
        assert all(e["type"] == REBOOT for e in reboots)

    def test_persist_and_reload(self, tmp_path):
        path = str(tmp_path / "events.json")
        log1 = EventLog(max_events=10, persist_path=path, persist_interval=9999)
        log1.record(REBOOT, attempt=1)
        log1.record(ISP_OUTAGE, duration="30min")
        log1.persist_now()

        # Verify file exists
        assert (tmp_path / "events.json").exists()

        # Load into new EventLog
        log2 = EventLog(max_events=10, persist_path=path, persist_interval=9999)
        events = log2.get_all()
        assert len(events) == 2
        assert events[0]["type"] == REBOOT
        assert events[1]["type"] == ISP_OUTAGE

    def test_persist_handles_permission_error(self, tmp_path):
        # Non-writable path should not crash
        log = EventLog(max_events=10, persist_path="/root/nope/events.json", persist_interval=9999)
        log.record("test")
        log.persist_now()  # should not raise

    def test_load_handles_missing_file(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "nonexistent.json"))
        assert log.get_all() == []

    def test_load_handles_corrupt_file(self, tmp_path):
        path = tmp_path / "events.json"
        path.write_text("not valid json", encoding="utf-8")
        log = EventLog(max_events=10, persist_path=str(path))
        assert log.get_all() == []

    def test_serialize_non_primitive(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record("test", some_list=[1, 2, 3])
        events = log.get_all()
        # Non-primitive values get str() conversion
        assert events[0]["data"]["some_list"] == "[1, 2, 3]"

    def test_count_today(self, tmp_path):
        log = EventLog(max_events=10, persist_path=str(tmp_path / "e.json"), persist_interval=9999)
        log.record(REBOOT, attempt=1)
        log.record(REBOOT, attempt=2)
        log.record(RECOVERY)

        assert log.count_today(REBOOT) == 2
        assert log.count_today(RECOVERY) == 1
        assert log.count_today("nonexistent") == 0
