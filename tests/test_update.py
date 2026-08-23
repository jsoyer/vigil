"""Tests for updater/update.py -- health_check() only (Bug 1: version mismatch
after restart must be treated as an update failure, not silently reported as
success). See docs/tasks/router/bugfix/2026-08-23_1000-vigil-identity-systemd-layout.md
"""

import sys
import os
from unittest.mock import patch, MagicMock

# Add updater to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))

from update import health_check


def _mock_response(payload: bytes):
    """Build a mock urlopen() return value usable as a context manager."""
    resp = MagicMock()
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestHealthCheckSuccess:
    def test_version_matches_status_healthy(self):
        payload = b'{"status": "healthy", "version": "1.8.2"}'
        with patch(
            "update.urllib.request.urlopen", return_value=_mock_response(payload)
        ):
            assert health_check("1.8.2") is True

    def test_version_matches_status_degraded(self):
        payload = b'{"status": "degraded", "version": "1.8.2"}'
        with patch(
            "update.urllib.request.urlopen", return_value=_mock_response(payload)
        ):
            assert health_check("1.8.2") is True


class TestHealthCheckVersionMismatch:
    def test_version_mismatch_even_if_healthy_returns_false(self):
        """Core regression test: the service is healthy but still running the
        old code -- must be reported as a failed update, immediately, not
        retried until timeout."""
        payload = b'{"status": "healthy", "version": "1.8.1"}'
        with patch(
            "update.urllib.request.urlopen", return_value=_mock_response(payload)
        ):
            with patch("update.time.sleep") as mock_sleep:
                assert health_check("1.8.2") is False
                # Must fail fast on mismatch, not loop sleeping until deadline.
                mock_sleep.assert_not_called()


class TestHealthCheckTimeoutAndErrors:
    def test_status_never_healthy_times_out(self):
        payload = b'{"status": "starting", "version": "1.8.2"}'
        with patch("update.HEALTH_CHECK_TIMEOUT", 0.2):
            with patch(
                "update.urllib.request.urlopen", return_value=_mock_response(payload)
            ):
                with patch("update.time.sleep"):
                    assert health_check("1.8.2") is False

    def test_urlopen_always_raises_returns_false(self):
        with patch("update.HEALTH_CHECK_TIMEOUT", 0.2):
            with patch(
                "update.urllib.request.urlopen",
                side_effect=Exception("connection refused"),
            ):
                with patch("update.time.sleep"):
                    assert health_check("1.8.2") is False
