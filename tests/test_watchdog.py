"""Tests for watchdog.py -- scoring engine, circuit breaker, main loop."""

from unittest import mock

import pytest

from src import watchdog
from src.connectivity import ConnectivityResult


# ===================================================================
# Unit tests: pure functions
# ===================================================================


class TestClamp:
    def test_within_range(self):
        assert watchdog.clamp(5, 0, 10) == 5

    def test_below_min(self):
        assert watchdog.clamp(-3, 0, 10) == 0

    def test_above_max(self):
        assert watchdog.clamp(20, 0, 15) == 15

    def test_at_boundaries(self):
        assert watchdog.clamp(0, 0, 10) == 0
        assert watchdog.clamp(10, 0, 10) == 10


class TestComputeCycleDelta:
    def test_all_ok(self):
        assert watchdog.compute_cycle_delta(True, 3) == -2

    def test_gw_ok_2_of_3(self):
        assert watchdog.compute_cycle_delta(True, 2) == -2

    def test_gw_ok_1_of_3(self):
        assert watchdog.compute_cycle_delta(True, 1) == 0

    def test_gw_ok_0_of_3(self):
        assert watchdog.compute_cycle_delta(True, 0) == 3

    def test_gw_ko_0_of_3(self):
        assert watchdog.compute_cycle_delta(False, 0) == 7

    def test_gw_ko_1_of_3(self):
        assert watchdog.compute_cycle_delta(False, 1) == 5

    def test_gw_ko_3_of_3(self):
        assert watchdog.compute_cycle_delta(False, 3) == 4


class TestComputeEffectiveCooldown:
    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 900)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 14400)
    def test_first_reboot(self):
        assert watchdog.compute_effective_cooldown(0) == 900

    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 900)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 14400)
    def test_second_reboot_doubles(self):
        assert watchdog.compute_effective_cooldown(1) == 1800

    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 900)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 14400)
    def test_third_reboot_quadruples(self):
        assert watchdog.compute_effective_cooldown(2) == 3600

    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 900)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 14400)
    def test_caps_at_max(self):
        assert watchdog.compute_effective_cooldown(10) == 14400


class TestComputeSshRetryDelay:
    @mock.patch("src.watchdog.SSH_FAILURE_BACKOFF_START", 3)
    @mock.patch("src.watchdog.SSH_FAILURE_COOLDOWN", 300)
    @mock.patch("src.watchdog.MAX_SSH_COOLDOWN", 3600)
    def test_no_delay_below_threshold(self):
        assert watchdog.compute_ssh_retry_delay(0) == 0
        assert watchdog.compute_ssh_retry_delay(2) == 0

    @mock.patch("src.watchdog.SSH_FAILURE_BACKOFF_START", 3)
    @mock.patch("src.watchdog.SSH_FAILURE_COOLDOWN", 300)
    @mock.patch("src.watchdog.MAX_SSH_COOLDOWN", 3600)
    def test_delay_at_threshold(self):
        assert watchdog.compute_ssh_retry_delay(3) == 300

    @mock.patch("src.watchdog.SSH_FAILURE_BACKOFF_START", 3)
    @mock.patch("src.watchdog.SSH_FAILURE_COOLDOWN", 300)
    @mock.patch("src.watchdog.MAX_SSH_COOLDOWN", 3600)
    def test_delay_doubles_at_paliers(self):
        assert watchdog.compute_ssh_retry_delay(6) == 600

    @mock.patch("src.watchdog.SSH_FAILURE_BACKOFF_START", 3)
    @mock.patch("src.watchdog.SSH_FAILURE_COOLDOWN", 300)
    @mock.patch("src.watchdog.MAX_SSH_COOLDOWN", 3600)
    def test_caps_at_max(self):
        assert watchdog.compute_ssh_retry_delay(100) == 3600


class TestFormatDuration:
    def test_seconds(self):
        assert watchdog._format_duration(45) == "45s"

    def test_minutes(self):
        assert watchdog._format_duration(300) == "5min"

    def test_hours(self):
        assert watchdog._format_duration(7200) == "2h"

    def test_hours_and_minutes(self):
        assert watchdog._format_duration(5400) == "1h30"


# ===================================================================
# Scoring scenarios (stateless simulation)
# ===================================================================


class TestScoringScenarios:
    def _run_scenario(self, cycles: list[tuple[bool, int]]) -> list[int]:
        score = 0
        history = []
        for gw, inet in cycles:
            delta = watchdog.compute_cycle_delta(gw, inet)
            score = watchdog.clamp(score + delta, 0, 15)
            history.append(score)
        return history

    def test_micro_coupure(self):
        cycles = [(True, 3), (True, 0), (True, 2), (True, 3), (True, 3)]
        history = self._run_scenario(cycles)
        assert max(history) < 10
        assert history[-1] == 0

    def test_wan_mort(self):
        cycles = [(True, 0)] * 5
        history = self._run_scenario(cycles)
        assert history[-1] >= 10

    def test_usg_fige(self):
        cycles = [(False, 0)] * 2
        history = self._run_scenario(cycles)
        assert history[1] >= 10

    def test_internet_instable(self):
        cycles = [(True, 1), (True, 3), (True, 0), (True, 2), (True, 3), (True, 1)]
        history = self._run_scenario(cycles)
        assert max(history) < 10
        assert history[-1] == 0

    def test_capped_at_max(self):
        cycles = [(False, 0)] * 10
        history = self._run_scenario(cycles)
        assert all(s <= 15 for s in history)

    def test_never_negative(self):
        cycles = [(True, 3)] * 10
        history = self._run_scenario(cycles)
        assert all(s >= 0 for s in history)


# ===================================================================
# Main loop integration tests
# ===================================================================


def _make_result(gateway_ok: bool, internet_ok: int) -> ConnectivityResult:
    return ConnectivityResult(
        gateway_ok=gateway_ok,
        internet_ok_count=internet_ok,
        internet_total=3,
    )


def _make_sleep_limiter(max_calls: int):
    """Return a sleep side-effect that raises KeyboardInterrupt after max_calls."""
    calls = 0

    def side_effect(*_args):
        nonlocal calls
        calls += 1
        if calls > max_calls:
            raise KeyboardInterrupt

    return side_effect


class TestMainLoopReboot:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    def test_reboots_when_threshold_reached(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)  # +3/cycle -> 12 at cycle 4
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_reboot.assert_called_once()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_no_reboot_on_micro_coupure(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_reboot.assert_not_called()

    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    def test_usg_freeze_reboots_in_2_cycles(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _make_result(False, 0)  # +7/cycle -> 14 at cycle 2
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_reboot.assert_called_once()


class TestExponentialBackoff:
    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 100)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 1000)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_cooldown_doubles_after_each_reboot(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        mock_conn.return_value = _make_result(False, 0)  # +7/cycle

        # Time progresses 50s per call. First reboot at cycle 2.
        # After reboot 1: cooldown = 100*2^1 = 200s.
        # We need enough time calls for 2 reboots.
        tick = 0

        def time_side():
            nonlocal tick
            tick += 50
            return float(tick)

        mock_time.side_effect = time_side
        mock_sleep.side_effect = _make_sleep_limiter(40)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Should have rebooted at least twice with backoff
        assert mock_reboot.call_count >= 2

        # Verify backoff: check that compute_effective_cooldown grows
        assert watchdog.compute_effective_cooldown(0) == 100
        assert watchdog.compute_effective_cooldown(1) == 200
        assert watchdog.compute_effective_cooldown(2) == 400


class TestMaxRebootsPerDay:
    @mock.patch("src.watchdog.MAX_REBOOTS_PER_DAY", 2)
    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 10)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 100)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_stops_rebooting_after_daily_cap(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        mock_conn.return_value = _make_result(False, 0)

        tick = 0

        def time_side():
            nonlocal tick
            tick += 30
            return float(tick)

        mock_time.side_effect = time_side
        mock_sleep.side_effect = _make_sleep_limiter(50)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Should cap at MAX_REBOOTS_PER_DAY = 2
        assert mock_reboot.call_count == 2

        # Should have sent surveillance mode notification
        surveillance_calls = [
            c for c in mock_notify.call_args_list
            if "surveillance" in str(c).lower()
        ]
        assert len(surveillance_calls) >= 1


class TestSshBackoff:
    @mock.patch("src.watchdog.SSH_FAILURE_BACKOFF_START", 2)
    @mock.patch("src.watchdog.SSH_FAILURE_COOLDOWN", 100)
    @mock.patch("src.watchdog.MAX_SSH_COOLDOWN", 500)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=False)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_ssh_backoff_limits_retry_rate(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        mock_conn.return_value = _make_result(False, 0)

        # Time advances 10s per call -- SSH backoff kicks in at 2 failures
        tick = 0

        def time_side():
            nonlocal tick
            tick += 10
            return float(tick)

        mock_time.side_effect = time_side
        mock_sleep.side_effect = _make_sleep_limiter(30)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # With backoff, SSH should be attempted far fewer times than 30
        # First 2 attempts happen, then backoff of 100s delays further attempts
        assert mock_reboot.call_count < 10


class TestIspOutageDetection:
    @mock.patch("src.watchdog.ISP_OUTAGE_DETECTION_DELAY", 100)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 10)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 10)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_stops_rebooting_on_isp_pattern(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        # gw OK + inet 0/3 for a long time -> ISP outage detected
        mock_conn.return_value = _make_result(True, 0)

        tick = 0

        def time_side():
            nonlocal tick
            tick += 20  # 20s per call, ISP detection at 100s
            return float(tick)

        mock_time.side_effect = time_side
        mock_sleep.side_effect = _make_sleep_limiter(40)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # After ISP detection, no more reboots even though score >= threshold
        # First reboot happens before ISP detection, then it should stop
        # The key test: reboot count should be very limited
        assert mock_reboot.call_count <= 2

        # ISP notification should have been sent
        isp_calls = [
            c for c in mock_notify.call_args_list
            if "fournisseur" in str(c).lower() or "panne" in str(c).lower()
        ]
        assert len(isp_calls) >= 1


class TestRecoverySummary:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_sends_summary_on_recovery(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        # Time must advance past grace (1s) quickly
        tick = 1000

        def time_side():
            nonlocal tick
            tick += 30
            return float(tick)

        mock_time.side_effect = time_side

        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)  # +3/cycle -> threshold at 4
            return _make_result(True, 3)  # recovery (-2/cycle)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = _make_sleep_limiter(50)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Find recovery summary notification
        recovery_calls = [
            c for c in mock_notify.call_args_list
            if "retablie" in str(c) and "redemarrage" in str(c).lower()
        ]
        assert len(recovery_calls) >= 1

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_recovery_without_reboot(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _make_result(True, 0)  # score goes up but stays < threshold
            return _make_result(True, 3)  # recovery

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = _make_sleep_limiter(10)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_reboot.assert_not_called()

        # Recovery notification should mention no reboot needed
        recovery_calls = [
            c for c in mock_notify.call_args_list
            if "redemarrage" in str(c).lower() and "retablie" in str(c).lower()
        ]
        assert len(recovery_calls) >= 1


class TestSetupLogging:
    def test_no_duplicate_handlers(self):
        import logging
        root = logging.getLogger()
        root.handlers.clear()
        watchdog.setup_logging()
        count = len(root.handlers)
        watchdog.setup_logging()
        assert len(root.handlers) == count
        root.handlers.clear()
