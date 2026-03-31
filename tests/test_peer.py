"""Tests for peer.py -- peer coordination and reboot decision logic."""

import json
from unittest import mock

from src.state import WatchdogState
from src.peer import query_peer, should_reboot, get_peer_info, check_divergence


def _make_state(**kwargs) -> WatchdogState:
    """Helper to create a WatchdogState with overrides."""
    defaults = {
        "failure_score": 12,
        "threshold": 10,
        "instance_priority": 1,
        "threshold_reached_time": 1000.0,
        "gateway_ok": True,
    }
    defaults.update(kwargs)
    return WatchdogState(**defaults)


class TestQueryPeer:
    @mock.patch("src.peer.urllib.request.urlopen")
    def test_returns_state_on_success(self, mock_urlopen):
        state = _make_state()
        mock_response = mock.Mock()
        mock_response.read.return_value = state.to_json().encode()
        mock_response.__enter__ = mock.Mock(return_value=mock_response)
        mock_response.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = query_peer("192.168.1.11", 9000)
        assert result is not None
        assert result.failure_score == 12

    @mock.patch("src.peer.urllib.request.urlopen")
    def test_returns_none_after_retries(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        result = query_peer("192.168.1.11", 9000, retries=2, timeout=1)
        assert result is None
        assert mock_urlopen.call_count == 2

    @mock.patch("src.peer.urllib.request.urlopen")
    def test_returns_none_on_invalid_json(self, mock_urlopen):
        mock_response = mock.Mock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = mock.Mock(return_value=mock_response)
        mock_response.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = query_peer("192.168.1.11", 9000, retries=1)
        assert result is None


class TestShouldReboot:
    @mock.patch("src.peer.PEER_IP", "")
    def test_standalone_mode_always_proceeds(self):
        state = _make_state()
        proceed, reason = should_reboot(state, gateway_ok=True)
        assert proceed is True
        assert "standalone" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_peer_higher_priority_stands_down(self, mock_query):
        # Peer is priority 1, I am priority 2
        peer_state = _make_state(
            instance_priority=1,
            failure_score=12,
            surveillance_only=False,
        )
        mock_query.return_value = peer_state

        my_state = _make_state(instance_priority=2)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is False
        assert "priorite" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    @mock.patch("src.peer.time.time", return_value=1100.0)
    def test_peer_rebooted_recently_stands_down(self, mock_time, mock_query):
        peer_state = _make_state(
            instance_priority=1,
            failure_score=0,  # score reset after reboot
            last_reboot_time=1000.0,  # 100s ago, within grace
        )
        mock_query.return_value = peer_state

        my_state = _make_state(instance_priority=2)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is False
        assert "reboote" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_i_have_higher_priority_proceeds(self, mock_query):
        peer_state = _make_state(instance_priority=2, failure_score=5)
        mock_query.return_value = peer_state

        my_state = _make_state(instance_priority=1)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is True

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer", return_value=None)
    def test_peer_unreachable_gateway_down_skips(self, mock_query):
        my_state = _make_state(instance_priority=2)
        proceed, reason = should_reboot(my_state, gateway_ok=False)
        assert proceed is False
        assert "local" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer", return_value=None)
    def test_peer_unreachable_primary_proceeds(self, mock_query):
        my_state = _make_state(instance_priority=1)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is True
        assert "primary" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.PEER_TAKEOVER_DELAY", 180)
    @mock.patch("src.peer.query_peer", return_value=None)
    @mock.patch("src.peer.time.time", return_value=1100.0)
    def test_secondary_waits_takeover_delay(self, mock_time, mock_query):
        # threshold_reached_time=1000.0, now=1100.0, delay=180s -> 80s remaining
        my_state = _make_state(instance_priority=2, threshold_reached_time=1000.0)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is False
        assert "takeover" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.PEER_TAKEOVER_DELAY", 180)
    @mock.patch("src.peer.query_peer", return_value=None)
    @mock.patch("src.peer.time.time", return_value=1200.0)
    def test_secondary_takes_over_after_delay(self, mock_time, mock_query):
        # threshold_reached_time=1000.0, now=1200.0, delay=180s -> elapsed 200s > 180s
        my_state = _make_state(instance_priority=2, threshold_reached_time=1000.0)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is True
        assert "takeover" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_peer_in_surveillance_secondary_takes_over(self, mock_query):
        peer_state = _make_state(
            instance_priority=1,
            failure_score=15,
            surveillance_only=True,
        )
        mock_query.return_value = peer_state

        my_state = _make_state(instance_priority=2)
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is True
        assert "surveillance" in reason

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer", side_effect=Exception("boom"))
    def test_peer_check_error_defaults_to_proceed(self, mock_query):
        my_state = _make_state()
        proceed, reason = should_reboot(my_state, gateway_ok=True)
        assert proceed is True


class TestGetPeerInfo:
    @mock.patch("src.peer.PEER_IP", "")
    def test_standalone_mode(self):
        info = get_peer_info()
        assert info["status"] == "standalone"

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer", return_value=None)
    def test_unreachable(self, mock_query):
        info = get_peer_info()
        assert info["status"] == "unreachable"

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_healthy_peer(self, mock_query):
        mock_query.return_value = _make_state(failure_score=0, threshold=10)
        info = get_peer_info()
        assert info["status"] == "healthy"
        assert info["score"] == 0

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_critical_peer(self, mock_query):
        mock_query.return_value = _make_state(failure_score=12, threshold=10)
        info = get_peer_info()
        assert info["status"] == "critical"
        assert info["score"] == 12

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_degraded_peer(self, mock_query):
        mock_query.return_value = _make_state(failure_score=5, threshold=10)
        info = get_peer_info()
        assert info["status"] == "degraded"


class TestCheckDivergence:
    @mock.patch("src.peer.PEER_IP", "")
    def test_no_divergence_standalone(self):
        assert check_divergence(10, True, 0) is None

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer", return_value=None)
    def test_no_divergence_peer_unreachable(self, mock_query):
        assert check_divergence(10, True, 0) is None

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_no_divergence_similar_scores(self, mock_query):
        mock_query.return_value = _make_state(failure_score=8, threshold=10)
        assert check_divergence(10, True, 0) is None  # gap = 2 < 6

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_divergence_local_problem(self, mock_query):
        mock_query.return_value = _make_state(failure_score=0, threshold=10, gateway_ok=True)
        result = check_divergence(10, True, 0)
        assert result is not None
        assert "cette machine" in result

    @mock.patch("src.peer.PEER_IP", "192.168.1.11")
    @mock.patch("src.peer.query_peer")
    def test_divergence_peer_problem(self, mock_query):
        mock_query.return_value = _make_state(failure_score=12, threshold=10, gateway_ok=False)
        result = check_divergence(0, True, 3)
        assert result is not None
        assert "peer" in result
