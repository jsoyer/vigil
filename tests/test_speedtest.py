"""Tests for speedtest.py -- download speed measurement."""

import urllib.error
from unittest import mock

import pytest

from src.speedtest import SpeedtestResult, run_speedtest, _TEST_URLS


class TestSpeedtestResult:
    def test_defaults_are_failed(self):
        r = SpeedtestResult()
        assert r.ok is False
        assert r.download_mbps is None
        assert r.duration_ms is None

    def test_to_dict_successful(self):
        r = SpeedtestResult(download_mbps=42.5, duration_ms=200, url="http://x.com", ok=True)
        d = r.to_dict()
        assert d["ok"] is True
        assert d["download_mbps"] == 42.5
        assert d["duration_ms"] == 200

    def test_to_dict_rounds_mbps(self):
        r = SpeedtestResult(download_mbps=12.3456789, duration_ms=100, url="http://x.com", ok=True)
        d = r.to_dict()
        assert d["download_mbps"] == round(12.3456789, 2)

    def test_to_dict_none_mbps_when_not_ok(self):
        r = SpeedtestResult(ok=False)
        d = r.to_dict()
        assert d["download_mbps"] is None
        assert d["ok"] is False


class TestRunSpeedtest:
    def _make_mock_response(self, content: bytes):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = content
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        return mock_resp

    @mock.patch("src.speedtest.urllib.request.urlopen")
    @mock.patch("src.speedtest.time.monotonic")
    def test_success_returns_ok_result(self, mock_mono, mock_urlopen):
        # 100_000 bytes downloaded in 0.1 seconds = 8 Mbps
        mock_mono.side_effect = [0.0, 0.1]
        mock_urlopen.return_value = self._make_mock_response(b"x" * 100_000)

        result = run_speedtest(url="http://fake-speed-test/file")
        assert result.ok is True
        assert result.download_mbps is not None
        assert result.download_mbps > 0
        assert result.duration_ms == 100
        assert result.url == "http://fake-speed-test/file"

    @mock.patch("src.speedtest.urllib.request.urlopen")
    @mock.patch("src.speedtest.time.monotonic")
    def test_uses_default_url_when_none_given(self, mock_mono, mock_urlopen):
        mock_mono.side_effect = [0.0, 0.2]
        mock_urlopen.return_value = self._make_mock_response(b"x" * 50_000)

        result = run_speedtest()
        assert result.url == _TEST_URLS[0]
        assert result.ok is True

    @mock.patch("src.speedtest.urllib.request.urlopen")
    def test_url_error_returns_failed_result(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection timed out")

        result = run_speedtest(url="http://unreachable.example.com")
        assert result.ok is False
        assert result.download_mbps is None
        assert result.url == "http://unreachable.example.com"

    @mock.patch("src.speedtest.urllib.request.urlopen")
    def test_generic_exception_returns_failed_result(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("unexpected error")

        result = run_speedtest(url="http://broken.example.com")
        assert result.ok is False
        assert result.download_mbps is None

    @mock.patch("src.speedtest.urllib.request.urlopen")
    @mock.patch("src.speedtest.time.monotonic")
    def test_zero_elapsed_does_not_divide_by_zero(self, mock_mono, mock_urlopen):
        mock_mono.side_effect = [0.0, 0.0]
        mock_urlopen.return_value = self._make_mock_response(b"x" * 1000)

        result = run_speedtest(url="http://instant.example.com")
        assert result.ok is True
        assert result.download_mbps == 0.0

    @mock.patch("src.speedtest.urllib.request.urlopen")
    @mock.patch("src.speedtest.time.monotonic")
    def test_mbps_calculation_is_correct(self, mock_mono, mock_urlopen):
        # 1_000_000 bytes in 1 second = 8 Mbps
        mock_mono.side_effect = [0.0, 1.0]
        mock_urlopen.return_value = self._make_mock_response(b"x" * 1_000_000)

        result = run_speedtest(url="http://test.example.com")
        assert result.ok is True
        assert abs(result.download_mbps - 8.0) < 0.01

    @mock.patch("src.speedtest.urllib.request.urlopen")
    def test_url_error_with_none_url_uses_default(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("timeout")

        result = run_speedtest(url=None)
        assert result.ok is False
        assert result.url == _TEST_URLS[0]
