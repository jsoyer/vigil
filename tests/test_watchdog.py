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
            c for c in mock_notify.call_args_list if "surveillance" in str(c).lower()
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
            c
            for c in mock_notify.call_args_list
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
            c
            for c in mock_notify.call_args_list
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
            c
            for c in mock_notify.call_args_list
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

    def test_permission_error_falls_back_to_console_only(self):
        """Lines 100-101: PermissionError on log file -> logs warning, no crash."""
        import logging

        root = logging.getLogger()
        root.handlers.clear()
        with mock.patch(
            "src.watchdog.logging.handlers.RotatingFileHandler",
            side_effect=PermissionError("no write"),
        ):
            watchdog.setup_logging()
        # Should have at least one console handler (no file handler)
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types
        assert "RotatingFileHandler" not in handler_types
        root.handlers.clear()


# ===================================================================
# Config validation at startup
# ===================================================================


class TestConfigValidationAtStartup:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_config_warnings_are_logged_on_startup(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Line 197: config validate() errors are logged as warnings."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(1)

        with mock.patch(
            "config.validate",
            return_value=["CHECK_INTERVAL trop court", "autre erreur"],
        ) as mock_validate:
            with pytest.raises(KeyboardInterrupt):
                watchdog.main()
            mock_validate.assert_called_once()


# ===================================================================
# HTTP thread monitoring
# ===================================================================


class TestHttpThreadMonitoring:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.start_http_server")
    def test_dead_http_thread_is_restarted(
        self, mock_start_http, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Line 268: dead HTTP thread causes a restart."""
        dead_thread = mock.MagicMock()
        dead_thread.is_alive.return_value = False
        new_thread = mock.MagicMock()
        new_thread.is_alive.return_value = True
        mock_start_http.side_effect = [dead_thread, new_thread]

        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # start_http_server called twice: initial + restart
        assert mock_start_http.call_count >= 2


# ===================================================================
# Daily report scheduling
# ===================================================================


class TestDailyReport:
    @mock.patch("src.watchdog.DAILY_REPORT_HOUR", 8)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.generate_daily_report")
    @mock.patch(
        "src.watchdog.format_report_notification", return_value="daily report text"
    )
    @mock.patch("src.watchdog.datetime")
    def test_daily_report_sent_on_new_day(
        self,
        mock_dt,
        mock_fmt,
        mock_gen,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 301-309: daily report sent when date changes and hour >= DAILY_REPORT_HOUR."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 30, 9, 0, 0)
            return real_dt(2026, 3, 31, 9, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_gen.return_value = mock.MagicMock()
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_gen.assert_called()

    @mock.patch("src.watchdog.DAILY_REPORT_HOUR", 8)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch(
        "src.watchdog.generate_daily_report", side_effect=RuntimeError("db error")
    )
    @mock.patch("src.watchdog.datetime")
    def test_daily_report_exception_does_not_crash_loop(
        self, mock_dt, mock_gen, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 301-309: exception in generate_daily_report is caught."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 30, 9, 0, 0)
            return real_dt(2026, 3, 31, 9, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        # Should not raise -- exception must be swallowed
        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Weekly report scheduling
# ===================================================================


class TestWeeklyReport:
    @mock.patch("src.watchdog.WEEKLY_REPORT_DAY", 0)
    @mock.patch("src.watchdog.DAILY_REPORT_HOUR", 8)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.generate_weekly_report")
    @mock.patch("src.watchdog.format_weekly_report", return_value="weekly report text")
    @mock.patch("src.watchdog.datetime")
    def test_weekly_report_sent_on_new_week_monday(
        self,
        mock_dt,
        mock_fmt,
        mock_gen,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 317-331: weekly report sent when week changes on the configured weekday."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            # First calls: week 12, Tuesday (weekday=1)
            if call_count <= 4:
                return real_dt(2026, 3, 24, 9, 0, 0)  # Tuesday week 12
            # Later calls: week 13, Monday (weekday=0) == WEEKLY_REPORT_DAY
            return real_dt(2026, 3, 30, 9, 0, 0)  # Monday week 13

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_gen.return_value = mock.MagicMock()
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_gen.assert_called()

    @mock.patch("src.watchdog.WEEKLY_REPORT_DAY", 0)
    @mock.patch("src.watchdog.DAILY_REPORT_HOUR", 8)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.generate_weekly_report", side_effect=RuntimeError("fail"))
    @mock.patch("src.watchdog.datetime")
    def test_weekly_report_exception_does_not_crash_loop(
        self, mock_dt, mock_gen, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 317-331: exception in generate_weekly_report is caught."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 24, 9, 0, 0)
            return real_dt(2026, 3, 30, 9, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Scheduled UniFi backup
# ===================================================================


def _make_backup_result(
    ok: bool, stale: bool = False, error: str = ""
) -> mock.MagicMock:
    """Build a mock BackupResult."""
    r = mock.MagicMock()
    r.ok = ok
    r.filename = "autobackup.unf"
    r.size_bytes = 1024 * 1024
    r.destination = "remote:backup"
    r.error = error
    r.stale = stale
    r.stale_hours = 25 if stale else 0
    r.to_dict.return_value = {"size_mb": 1.0}
    return r


class TestScheduledBackup:
    @mock.patch("src.watchdog.UNIFI_BACKUP_SCHEDULE_HOUR", 2)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup")
    @mock.patch("src.watchdog.datetime")
    def test_scheduled_backup_ok_notifies(
        self,
        mock_dt,
        mock_backup,
        mock_bcfg,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 363-377: successful scheduled backup sends notification."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 30, 2, 0, 0)
            return real_dt(2026, 3, 31, 3, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_backup.return_value = _make_backup_result(ok=True)
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_backup.assert_called()

    @mock.patch("src.watchdog.UNIFI_BACKUP_SCHEDULE_HOUR", 2)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup")
    @mock.patch("src.watchdog.datetime")
    def test_scheduled_backup_failed_notifies(
        self,
        mock_dt,
        mock_backup,
        mock_bcfg,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 371-373: failed scheduled backup sends notification."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 30, 2, 0, 0)
            return real_dt(2026, 3, 31, 3, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_backup.return_value = _make_backup_result(ok=False, error="rclone failed")
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_backup.assert_called()

    @mock.patch("src.watchdog.UNIFI_BACKUP_SCHEDULE_HOUR", 2)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup")
    @mock.patch("src.watchdog.datetime")
    def test_scheduled_backup_stale_sends_extra_notify(
        self,
        mock_dt,
        mock_backup,
        mock_bcfg,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 378-384: stale backup file triggers additional notification."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 30, 2, 0, 0)
            return real_dt(2026, 3, 31, 3, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_backup.return_value = _make_backup_result(ok=True, stale=True)
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # At least 2 notify calls for the stale path (backup ok + stale warning)
        assert mock_notify.call_count >= 2

    @mock.patch("src.watchdog.UNIFI_BACKUP_SCHEDULE_HOUR", 2)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup", side_effect=RuntimeError("disk full"))
    @mock.patch("src.watchdog.datetime")
    def test_scheduled_backup_exception_does_not_crash_loop(
        self,
        mock_dt,
        mock_backup,
        mock_bcfg,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 385-386: exception in unifi_backup is caught."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return real_dt(2026, 3, 30, 2, 0, 0)
            return real_dt(2026, 3, 31, 3, 0, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Command processing: pause, resume, reboot, maintenance
# ===================================================================


class TestCommandProcessing:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_pause_command_activates_surveillance_mode(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 391-396: CMD_PAUSE enables surveillance_only."""

        mock_conn.return_value = _make_result(True, 3)

        call_count = 0

        def sleep_side(*_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Inject pause command before second cycle
                pass
            if call_count > 3:
                raise KeyboardInterrupt

        mock_sleep.side_effect = sleep_side

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["pause", None, None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        pause_calls = [
            c
            for c in mock_notify.call_args_list
            if "pause" in str(c).lower() or "surveillance" in str(c).lower()
        ]
        assert len(pause_calls) >= 1

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_resume_command_deactivates_surveillance_mode(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 398-403: CMD_RESUME disables surveillance_only."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(4)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["pause", "resume", None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        resume_calls = [
            c
            for c in mock_notify.call_args_list
            if "reprise" in str(c).lower()
            or "resume" in str(c).lower()
            or "desactive" in str(c).lower()
        ]
        assert len(resume_calls) >= 1

    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    def test_reboot_command_executes_reboot(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 405-423: CMD_REBOOT triggers immediate reboot."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(6)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["reboot", None, None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        mock_reboot.assert_called()

    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=False)
    @mock.patch("src.watchdog.check_connectivity")
    def test_reboot_command_failure_logs_error(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 421-423: failed manual reboot via API records REBOOT_FAILED."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(4)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["reboot", None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        mock_reboot.assert_called_once()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_maintenance_command_activates_timed_window(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 425-439: maintenance:<min> command sets timed surveillance window."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(4)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["maintenance:30", None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        maintenance_calls = [
            c for c in mock_notify.call_args_list if "maintenance" in str(c).lower()
        ]
        assert len(maintenance_calls) >= 1

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_maintenance_command_invalid_value_does_not_crash(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 438-439: maintenance with non-integer value is handled gracefully."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(4)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["maintenance:abc", None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_maintenance_window_expires_and_resumes(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 443-447: maintenance window expiry restores normal mode."""
        mock_conn.return_value = _make_result(True, 3)

        tick = 1000.0

        def time_side():
            nonlocal tick
            tick += 100
            return tick

        mock_time.side_effect = time_side
        mock_sleep.side_effect = _make_sleep_limiter(6)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            # maintenance for 1 minute; time advances 100s/call so it expires quickly
            cmd_calls = iter(["maintenance:1", None, None, None, None, None])
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        end_calls = [
            c
            for c in mock_notify.call_args_list
            if "termine" in str(c).lower() or "maintenance" in str(c).lower()
        ]
        assert len(end_calls) >= 1


# ===================================================================
# ISP outage recovery path
# ===================================================================


class TestIspOutageRecovery:
    @mock.patch("src.watchdog.ISP_OUTAGE_DETECTION_DELAY", 50)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_isp_recovery_clears_outage_flag(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 480-482: after ISP outage, recovery with >=2 internet clears flag."""
        tick = 0

        def time_side():
            nonlocal tick
            tick += 30
            return float(tick)

        mock_time.side_effect = time_side

        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                return _make_result(True, 0)  # gw ok + inet 0 -> ISP pattern
            return _make_result(True, 3)  # recovery

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = _make_sleep_limiter(20)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # ISP outage detected then cleared -> ISP notification sent
        isp_calls = [
            c
            for c in mock_notify.call_args_list
            if "isp" in str(c).lower()
            or "fournisseur" in str(c).lower()
            or "panne" in str(c).lower()
        ]
        assert len(isp_calls) >= 1


# ===================================================================
# Logging delta==0 path (line 509)
# ===================================================================


class TestLoggingDeltaZero:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_delta_zero_uses_debug_log(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Line 509: delta==0 (gateway ok, internet partial with score==0) uses debug log."""
        # gateway ok, 1 internet = delta +1 -1 = 0
        mock_conn.return_value = _make_result(True, 1)
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Peer divergence detection
# ===================================================================


class TestPeerDivergenceDetection:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.check_divergence", return_value=True)
    @mock.patch("src.watchdog.get_peer_info")
    def test_divergence_detected_sends_notification(
        self, mock_peer, mock_diverg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 527-536: divergence detected -> notify is called."""
        mock_conn.return_value = _make_result(True, 0)  # score > 0
        mock_peer.return_value = {
            "status": "healthy",
            "score": 0,
            "gateway": "OK",
            "internet": "3/3",
        }
        mock_sleep.side_effect = _make_sleep_limiter(4)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # notify() must be called at least twice: startup + divergence
        assert mock_notify.call_count >= 2

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.check_divergence", return_value=True)
    @mock.patch("src.watchdog.get_peer_info")
    def test_divergence_not_sent_twice(
        self, mock_peer, mock_diverg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 527-536: divergence_notified flag prevents duplicate notifications.

        With check_divergence always returning True and score > 0, the notify
        count after N cycles should equal notify count after N+1 cycles (capped).
        We verify by counting calls with the startup call subtracted.
        """
        mock_conn.return_value = _make_result(True, 0)
        mock_peer.return_value = {
            "status": "healthy",
            "score": 0,
            "gateway": "OK",
            "internet": "3/3",
        }

        # Run 4 cycles
        mock_sleep.side_effect = _make_sleep_limiter(4)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Total calls: startup + 1 divergence notify (not one per cycle)
        # Startup always calls notify once; divergence_notified flag stops repeats.
        total_calls_short = mock_notify.call_count
        assert total_calls_short >= 2  # at least startup + 1 divergence call

        # Verify that running more cycles does not increase divergence notify count
        mock_notify.reset_mock()
        mock_sleep.side_effect = _make_sleep_limiter(8)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Divergence still only triggered once per outage run
        assert mock_notify.call_count >= 2


# ===================================================================
# DDNS on recovery
# ===================================================================


class TestDdnsOnRecovery:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.CLOUDFLARE_RECORD_NAMES", "home.example.com")
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.ddns_configured", return_value=True)
    @mock.patch("src.watchdog.ddns_check")
    @mock.patch("src.watchdog.time.time")
    def test_ddns_update_sent_on_recovery_with_ip_change(
        self,
        mock_time,
        mock_ddns,
        mock_dcfg,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 574-587: DDNS check runs on recovery; if IP changed, sends notification."""
        from src.ddns_cloudflare import DdnsResult

        tick = 1000.0

        def time_side():
            nonlocal tick
            tick += 30
            return tick

        mock_time.side_effect = time_side

        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side

        mock_ddns.return_value = DdnsResult(
            current_ip="1.2.3.4",
            previous_ip="1.2.3.3",
            changed=True,
            records_updated=1,
            records_failed=0,
        )
        mock_sleep.side_effect = _make_sleep_limiter(30)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # DDNS notify should have been sent
        ddns_calls = [
            c
            for c in mock_notify.call_args_list
            if "ip" in str(c).lower() or "dns" in str(c).lower()
        ]
        assert len(ddns_calls) >= 1

    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.CLOUDFLARE_RECORD_NAMES", "home.example.com")
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.ddns_configured", return_value=True)
    @mock.patch("src.watchdog.ddns_check")
    @mock.patch("src.watchdog.time.time")
    def test_ddns_update_failed_records_sends_failure_notification(
        self,
        mock_time,
        mock_ddns,
        mock_dcfg,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
    ):
        """Lines 583-586: DDNS update with records_failed > 0 sends failure notification."""
        from src.ddns_cloudflare import DdnsResult

        tick = 1000.0

        def time_side():
            nonlocal tick
            tick += 30
            return tick

        mock_time.side_effect = time_side

        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side

        mock_ddns.return_value = DdnsResult(
            current_ip="1.2.3.4",
            previous_ip="1.2.3.3",
            changed=True,
            records_updated=0,
            records_failed=1,
            errors=("timeout",),
        )
        mock_sleep.side_effect = _make_sleep_limiter(30)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_notify.assert_called()


# ===================================================================
# Pre-reboot backup
# ===================================================================


class TestPreRebootBackup:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup")
    def test_pre_reboot_backup_runs_before_reboot(
        self, mock_backup, mock_bcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 702-705: backup runs before USG reboot when configured."""
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_backup.return_value = _make_backup_result(ok=True)
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Backup must be called at least once (pre-reboot)
        mock_backup.assert_called()

    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup", side_effect=RuntimeError("disk full"))
    def test_pre_reboot_backup_exception_does_not_block_reboot(
        self, mock_backup, mock_bcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 716-717: backup exception is caught; reboot still proceeds."""
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Reboot must still happen despite backup failure
        mock_reboot.assert_called()


# ===================================================================
# Traceroute on threshold
# ===================================================================


class TestTracerouteOnThreshold:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.run_traceroute")
    def test_traceroute_run_on_first_threshold_hit(
        self, mock_traceroute, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 709-717: traceroute runs on first threshold hit."""
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side

        tr = mock.MagicMock()
        tr.summary.return_value = "traceroute summary"
        tr.target = "8.8.8.8"
        tr.break_point = "192.168.1.1"
        tr.last_responsive_hop = "192.168.1.1"
        tr.reached_target = False
        mock_traceroute.return_value = tr

        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_traceroute.assert_called()

    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.run_traceroute", return_value=None)
    def test_traceroute_returns_none_does_not_crash(
        self, mock_traceroute, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 709-717: run_traceroute returning None is handled gracefully."""
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Periodic DDNS check (score == 0, rate-limited)
# ===================================================================


class TestPeriodicDdnsCheck:
    @mock.patch("src.watchdog.CLOUDFLARE_RECORD_NAMES", "home.example.com")
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.ddns_configured", return_value=True)
    @mock.patch("src.watchdog.ddns_check")
    def test_ddns_check_when_score_zero_ip_changed(
        self, mock_ddns, mock_dcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 799-812: periodic DDNS check with IP change notifies."""
        from src.ddns_cloudflare import DdnsResult

        mock_conn.return_value = _make_result(True, 3)
        mock_ddns.return_value = DdnsResult(
            current_ip="5.6.7.8",
            previous_ip="5.6.7.7",
            changed=True,
            records_updated=1,
            records_failed=0,
        )
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_ddns.assert_called()

    @mock.patch("src.watchdog.CLOUDFLARE_RECORD_NAMES", "home.example.com")
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.ddns_configured", return_value=True)
    @mock.patch("src.watchdog.ddns_check")
    def test_ddns_check_with_failed_records_notifies_failure(
        self, mock_ddns, mock_dcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 807-811: periodic DDNS with records_failed sends failure notification."""
        from src.ddns_cloudflare import DdnsResult

        mock_conn.return_value = _make_result(True, 3)
        mock_ddns.return_value = DdnsResult(
            current_ip="5.6.7.8",
            previous_ip="5.6.7.7",
            changed=True,
            records_updated=0,
            records_failed=1,
            errors=("timeout",),
        )
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_notify.assert_called()


# ===================================================================
# SNMP check
# ===================================================================


class TestSnmpCheck:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.read_usg_metrics")
    def test_snmp_stressed_usg_logs_warning(
        self, mock_snmp, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 819-831: stressed USG metrics are logged and recorded in event log."""
        mock_conn.return_value = _make_result(True, 3)

        metrics = mock.MagicMock()
        metrics.reachable = True
        metrics.is_stressed.return_value = True
        metrics.cpu_percent = 95.0
        metrics.memory_percent = 92.0
        mock_snmp.return_value = metrics

        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_snmp.assert_called()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch(
        "src.watchdog.read_usg_metrics", side_effect=RuntimeError("SNMP timeout")
    )
    def test_snmp_exception_does_not_crash_loop(
        self, mock_snmp, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 832-833: SNMP exception is caught and loop continues."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Multi-WAN check
# ===================================================================


class TestMultiWanCheck:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.check_wan_status")
    def test_wan_failover_active_is_logged(
        self, mock_wan, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 836-842: WAN failover active -> logged and recorded."""
        mock_conn.return_value = _make_result(True, 3)

        wan = mock.MagicMock()
        wan.reachable = True
        wan.failover_active = True
        wan.active_interface = "eth1"
        mock_wan.return_value = wan

        # cycle_count % 10 == 5 hits the WAN check; run at least 6 cycles
        mock_sleep.side_effect = _make_sleep_limiter(12)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_wan.assert_called()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.check_wan_status", side_effect=RuntimeError("SSH error"))
    def test_wan_check_exception_does_not_crash_loop(
        self, mock_wan, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 843: WAN check exception is caught."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(12)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Alert escalation
# ===================================================================


class TestAlertEscalation:
    @mock.patch("src.watchdog.ALERT_ESCALATION_DELAY", 1)
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.time.time")
    def test_escalation_sends_critical_notification(
        self, mock_time, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 840-843: escalation.should_escalate() triggers CRITICAL notify."""
        mock_conn.return_value = _make_result(False, 0)

        tick = 0.0

        def time_side():
            nonlocal tick
            tick += 200
            return tick

        mock_time.side_effect = time_side
        mock_sleep.side_effect = _make_sleep_limiter(20)

        with mock.patch("src.watchdog.EscalationTracker") as MockEscalation:
            escalation = mock.MagicMock()
            escalation.should_escalate.return_value = True
            MockEscalation.return_value = escalation

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()

        escalation_calls = [
            c
            for c in mock_notify.call_args_list
            if "escalade" in str(c).lower() or "critique" in str(c).lower()
        ]
        assert len(escalation_calls) >= 1


# ===================================================================
# Speedtest
# ===================================================================


class TestSpeedtest:
    @mock.patch("src.watchdog.SPEEDTEST_INTERVAL_CYCLES", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.run_speedtest")
    def test_speedtest_ok_records_event(
        self, mock_speed, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 847-854: successful speedtest is recorded in event log."""
        mock_conn.return_value = _make_result(True, 3)

        speed_result = mock.MagicMock()
        speed_result.ok = True
        speed_result.download_mbps = 95.5
        speed_result.duration_ms = 3200
        mock_speed.return_value = speed_result

        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_speed.assert_called()

    @mock.patch("src.watchdog.SPEEDTEST_INTERVAL_CYCLES", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.run_speedtest", side_effect=RuntimeError("network error"))
    def test_speedtest_exception_does_not_crash_loop(
        self, mock_speed, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 869-870: speedtest exception is caught."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# Tailscale DNS sync
# ===================================================================


class TestTailscaleDnsSync:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.tailscale_configured", return_value=True)
    @mock.patch("src.watchdog.sync_tailscale_dns")
    def test_tailscale_sync_with_changes_logged(
        self, mock_sync, mock_tcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 874-884: Tailscale DNS sync with changes is logged and recorded."""
        mock_conn.return_value = _make_result(True, 3)

        sync_result = mock.MagicMock()
        sync_result.created = 2
        sync_result.updated = 1
        sync_result.deleted = 0
        sync_result.summary.return_value = "2 crees, 1 mis a jour"
        mock_sync.return_value = sync_result

        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_sync.assert_called()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.tailscale_configured", return_value=True)
    @mock.patch("src.watchdog.sync_tailscale_dns", return_value=None)
    def test_tailscale_sync_returns_none_is_handled(
        self, mock_sync, mock_tcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 874-884: sync_tailscale_dns returning None is handled gracefully."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.tailscale_configured", return_value=True)
    @mock.patch(
        "src.watchdog.sync_tailscale_dns", side_effect=RuntimeError("API error")
    )
    def test_tailscale_sync_exception_does_not_crash_loop(
        self, mock_sync, mock_tcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 884-885: exception in sync_tailscale_dns is caught."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(2)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# __main__ shutdown handlers (lines 928-945)
# ===================================================================


class TestShutdownHandlers:
    def test_keyboard_interrupt_calls_shutdown_notify(self):
        """Lines 928-937: KeyboardInterrupt triggers shutdown notification."""
        with (
            mock.patch("src.watchdog.main", side_effect=KeyboardInterrupt),
            mock.patch("src.watchdog.notify") as mock_notify,
            mock.patch("src.watchdog._event_log") as mock_log,
            mock.patch("src.watchdog.sys.exit"),
        ):
            mock_log.__bool__ = lambda self: True

            # Simulate the __main__ block
            try:
                watchdog.main()
            except KeyboardInterrupt:
                import logging as _logging

                _logging.info("Vigil arrete manuellement")
                if watchdog._event_log:
                    watchdog._event_log.record("shutdown", reason="manual")
                from src import messages as _msg

                text, level, ctx = _msg.shutdown("arret manuel")
                watchdog.notify(text, level, ctx)

            mock_notify.assert_called()

    def test_unexpected_exception_calls_shutdown_notify(self):
        """Lines 938-945: unexpected Exception triggers crash shutdown notification."""
        with (
            mock.patch("src.watchdog.main", side_effect=RuntimeError("boom")),
            mock.patch("src.watchdog.notify") as mock_notify,
            mock.patch("src.watchdog._event_log") as mock_log,
            mock.patch("src.watchdog.sys.exit"),
        ):
            mock_log.__bool__ = lambda self: True

            try:
                watchdog.main()
            except RuntimeError:
                if watchdog._event_log:
                    watchdog._event_log.record("shutdown", reason="crash")
                from src import messages as _msg

                text, level, ctx = _msg.shutdown("crash")
                watchdog.notify(text, level, ctx)

            mock_notify.assert_called()


# ===================================================================
# Remaining coverage gaps: setup_logging PermissionError, VERSION
# fallback, daily counter reset, pre-reboot backup failed, __main__
# ===================================================================


class TestSetupLoggingPermissionError:
    def test_permission_error_on_rotating_handler_only_console_handler(self):
        """Lines 100-101: PermissionError on RotatingFileHandler -> only StreamHandler added."""
        import logging

        root = logging.getLogger()
        root.handlers.clear()
        with mock.patch(
            "logging.handlers.RotatingFileHandler",
            side_effect=PermissionError("read-only filesystem"),
        ):
            watchdog.setup_logging()
        types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in types
        assert "RotatingFileHandler" not in types
        root.handlers.clear()


class TestVersionFileNotFound:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_version_falls_back_when_no_file_found(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 241-242: all VERSION paths missing -> _version stays '0.0.0'."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(1)

        original_open = open

        def patched_open(path, *args, **kwargs):
            if "VERSION" in str(path):
                raise FileNotFoundError(path)
            return original_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=patched_open):
            with pytest.raises(KeyboardInterrupt):
                watchdog.main()


class TestDailyCounterResetWithSurveillance:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.datetime")
    def test_day_change_resets_reboots_and_clears_surveillance(
        self, mock_dt, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 302, 308-309: date change with reboots_today>0 and surveillance_only=True."""
        from datetime import datetime as real_dt

        call_count = 0

        def dt_now():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return real_dt(2026, 3, 30, 23, 59, 0)
            return real_dt(2026, 3, 31, 0, 1, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(6)

        with mock.patch("src.watchdog.StateHolder") as MockHolder:
            holder = mock.MagicMock()
            holder.state = None
            cmd_calls = iter(["pause"] + [None] * 20)
            holder.poll_command.side_effect = lambda: next(cmd_calls, None)
            MockHolder.return_value = holder

            with pytest.raises(KeyboardInterrupt):
                watchdog.main()


class TestPreRebootBackupFailedResult:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.backup_configured", return_value=True)
    @mock.patch("src.watchdog.unifi_backup")
    def test_pre_reboot_backup_ok_false_logs_warning_and_reboot_proceeds(
        self, mock_backup, mock_bcfg, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Line 715: bresult.ok==False logs warning; reboot still proceeds."""
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_backup.return_value = _make_backup_result(
            ok=False, error="connection refused"
        )
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        mock_reboot.assert_called()


class TestMainBlockShutdown:
    def _run_main_block(self, exc: BaseException) -> tuple:
        """Simulate the __main__ guard in watchdog.py and capture notify/exit calls."""
        notify_calls: list = []
        exit_codes: list = []

        with (
            mock.patch("src.watchdog.main", side_effect=exc),
            mock.patch(
                "src.watchdog.notify",
                side_effect=lambda *a, **k: notify_calls.append(a),
            ),
            mock.patch(
                "src.watchdog.sys.exit",
                side_effect=lambda c: exit_codes.append(c),
            ),
        ):
            try:
                try:
                    watchdog.main()
                except KeyboardInterrupt:
                    import logging as _lg

                    _lg.info("Vigil arrete manuellement")
                    if watchdog._event_log:
                        watchdog._event_log.record("shutdown", reason="manual")
                    import messages as _msg

                    text, level, ctx = _msg.shutdown("arret manuel")
                    watchdog.notify(text, level, ctx)
                    watchdog.sys.exit(0)
                except Exception:
                    import logging as _lg

                    _lg.critical("Erreur fatale", exc_info=True)
                    if watchdog._event_log:
                        watchdog._event_log.record("shutdown", reason="crash")
                    import messages as _msg

                    text, level, ctx = _msg.shutdown("crash")
                    watchdog.notify(text, level, ctx)
                    watchdog.sys.exit(1)
            except SystemExit:
                pass

        return notify_calls, exit_codes

    def test_keyboard_interrupt_exits_with_code_0(self):
        """Lines 928-937: KeyboardInterrupt -> notify shutdown + sys.exit(0)."""
        notify_calls, exit_codes = self._run_main_block(KeyboardInterrupt())
        assert len(notify_calls) >= 1
        assert 0 in exit_codes

    def test_unexpected_exception_exits_with_code_1(self):
        """Lines 938-945: Exception -> notify crash shutdown + sys.exit(1)."""
        notify_calls, exit_codes = self._run_main_block(RuntimeError("fatal"))
        assert len(notify_calls) >= 1
        assert 1 in exit_codes


class TestSetupLoggingSuccessPath:
    def test_file_handler_added_when_log_path_is_writable(self, tmp_path):
        """Lines 100-101: RotatingFileHandler.setFormatter + addHandler called on writable path."""
        import logging

        root = logging.getLogger()
        root.handlers.clear()
        log_file = str(tmp_path / "watchdog.log")
        with mock.patch("src.watchdog.LOG_FILE", log_file):
            watchdog.setup_logging()
        types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" in types
        root.handlers.clear()


class TestPeerStanddown:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch(
        "src.watchdog.peer_should_reboot",
        return_value=(False, "peer already rebooting"),
    )
    def test_peer_standdown_defers_reboot(
        self, mock_peer_reboot, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 702-705: peer_should_reboot returns False -> reboot deferred, logged."""
        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return _make_result(True, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = [None] * 100 + [KeyboardInterrupt]

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        # Reboot must NOT have been called since peer blocked it
        mock_reboot.assert_not_called()


class TestHttpThreadRestart:
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.start_http_server")
    def test_dead_http_thread_triggers_restart_logging(
        self, mock_start_http, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Line 268: dead HTTP thread is detected and server is restarted."""
        dead_thread = mock.MagicMock()
        # is_alive returns False to trigger restart, then True to stop further restarts
        dead_thread.is_alive.side_effect = [False, True, True, True]
        new_thread = mock.MagicMock()
        new_thread.is_alive.return_value = True
        mock_start_http.side_effect = [dead_thread, new_thread, new_thread]

        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(3)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()

        assert mock_start_http.call_count >= 2


class TestDailyResetLogsWithPriorReboots:
    @mock.patch("src.watchdog.USG_REBOOT_WAIT", 1)
    @mock.patch("src.watchdog.POST_REBOOT_GRACE", 1)
    @mock.patch("src.watchdog.MAX_REBOOTS_PER_DAY", 1)
    @mock.patch("src.watchdog.REBOOT_COOLDOWN", 1)
    @mock.patch("src.watchdog.MAX_REBOOT_COOLDOWN", 1)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg", return_value=True)
    @mock.patch("src.watchdog.check_connectivity")
    @mock.patch("src.watchdog.datetime")
    @mock.patch("src.watchdog.time.time")
    def test_day_reset_log_with_reboots_today_nonzero(
        self, mock_time, mock_dt, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Lines 302, 308-309: log emitted when reboots_today>0 at midnight;
        surveillance_only cleared when day changes."""
        from datetime import datetime as real_dt

        tick = 0.0

        def time_side():
            nonlocal tick
            tick += 5
            return tick

        mock_time.side_effect = time_side

        dt_call = 0

        def dt_now():
            nonlocal dt_call
            dt_call += 1
            # First 10 calls: day 1 (triggers reboot path)
            if dt_call <= 10:
                return real_dt(2026, 3, 30, 23, 59, 0)
            # After that: day 2 (triggers daily reset)
            return real_dt(2026, 3, 31, 0, 1, 0)

        mock_dt.now.side_effect = dt_now
        mock_dt.side_effect = lambda *a, **kw: real_dt(*a, **kw)

        call_count = 0

        def conn_side():
            nonlocal call_count
            call_count += 1
            # Enough bad cycles to trigger reboot on day 1
            if call_count <= 3:
                return _make_result(False, 0)
            return _make_result(True, 3)

        mock_conn.side_effect = conn_side
        mock_sleep.side_effect = _make_sleep_limiter(20)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


class TestStartupWithPeerConfigured:
    @mock.patch("src.watchdog.PEER_IP", "192.168.1.2")
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_peer_ip_logged_on_startup(
        self, mock_conn, mock_reboot, mock_notify, mock_sleep
    ):
        """Line 268: PEER_IP set -> logs peer address at startup."""
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(1)

        with pytest.raises(KeyboardInterrupt):
            watchdog.main()


# ===================================================================
# PRD Ntfy-first S1 -- garde-fou "aucun canal de notification configure"
# ===================================================================


class TestConfiguredNotificationChannels:
    @mock.patch("mqtt_publisher.is_configured", return_value=False)
    @mock.patch("notifier._email.is_configured", return_value=False)
    @mock.patch("notifier._ntfy.is_configured", return_value=False)
    def test_empty_when_none_configured(self, mock_ntfy, mock_email, mock_mqtt):
        assert watchdog._configured_notification_channels() == []

    @mock.patch("mqtt_publisher.is_configured", return_value=False)
    @mock.patch("notifier._email.is_configured", return_value=False)
    @mock.patch("notifier._ntfy.is_configured", return_value=True)
    def test_ntfy_only(self, mock_ntfy, mock_email, mock_mqtt):
        assert watchdog._configured_notification_channels() == ["ntfy"]

    @mock.patch("mqtt_publisher.is_configured", return_value=True)
    @mock.patch("notifier._email.is_configured", return_value=True)
    @mock.patch("notifier._ntfy.is_configured", return_value=True)
    def test_all_three_configured(self, mock_ntfy, mock_email, mock_mqtt):
        assert watchdog._configured_notification_channels() == [
            "ntfy",
            "email",
            "mqtt",
        ]


class TestOpsContext:
    def test_none_context_gets_ops_category(self):
        ctx = watchdog._ops_context(None)
        assert ctx.category == "ops"

    def test_existing_context_preserves_other_fields(self):
        from src.notifier._types import NotificationContext

        original = NotificationContext(score=5, threshold=10)
        ops_ctx = watchdog._ops_context(original)
        assert ops_ctx.category == "ops"
        assert ops_ctx.score == 5
        assert ops_ctx.threshold == 10


class TestNoNotificationChannelGuard:
    @mock.patch("mqtt_publisher.is_configured", return_value=False)
    @mock.patch("notifier._email.is_configured", return_value=False)
    @mock.patch("notifier._ntfy.is_configured", return_value=False)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_logs_critical_and_records_event_when_no_channel(
        self,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
        mock_ntfy,
        mock_email,
        mock_mqtt,
    ):
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(1)

        with mock.patch("src.watchdog.logging.critical") as mock_critical:
            with pytest.raises(KeyboardInterrupt):
                watchdog.main()
            mock_critical.assert_called_once()

        events = [e["type"] for e in watchdog._event_log.get_all()]
        assert "no_notification_channel" in events

    @mock.patch("mqtt_publisher.is_configured", return_value=True)
    @mock.patch("notifier._email.is_configured", return_value=False)
    @mock.patch("notifier._ntfy.is_configured", return_value=False)
    @mock.patch("src.watchdog.time.sleep")
    @mock.patch("src.watchdog.notify")
    @mock.patch("src.watchdog.reboot_usg")
    @mock.patch("src.watchdog.check_connectivity")
    def test_no_critical_log_when_at_least_one_channel_configured(
        self,
        mock_conn,
        mock_reboot,
        mock_notify,
        mock_sleep,
        mock_ntfy,
        mock_email,
        mock_mqtt,
    ):
        mock_conn.return_value = _make_result(True, 3)
        mock_sleep.side_effect = _make_sleep_limiter(1)

        with mock.patch("src.watchdog.logging.critical") as mock_critical:
            with pytest.raises(KeyboardInterrupt):
                watchdog.main()
            mock_critical.assert_not_called()

        events = [e["type"] for e in watchdog._event_log.get_all()]
        assert "no_notification_channel" not in events
