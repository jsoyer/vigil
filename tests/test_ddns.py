"""Tests for ddns_cloudflare.py -- Cloudflare DNS update."""

from unittest import mock

import pytest

from src.ddns_cloudflare import (
    get_public_ip,
    check_and_update,
    is_configured,
    DdnsResult,
    _cf_api,
)


class TestIsConfigured:
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_API_TOKEN", "")
    def test_not_configured_without_token(self):
        assert is_configured() is False

    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_API_TOKEN", "token")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_ZONE_ID", "zone")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_RECORD_NAMES", "example.com")
    def test_configured_with_all(self):
        assert is_configured() is True


class TestGetPublicIp:
    @mock.patch("src.ddns_cloudflare.urllib.request.urlopen")
    def test_returns_valid_ip(self, mock_urlopen):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = b"82.123.45.67"
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ip = get_public_ip()
        assert ip == "82.123.45.67"

    @mock.patch("src.ddns_cloudflare.urllib.request.urlopen")
    def test_returns_none_on_failure(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        assert get_public_ip() is None

    @mock.patch("src.ddns_cloudflare.urllib.request.urlopen")
    def test_rejects_invalid_ip(self, mock_urlopen):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = b"not an ip"
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        assert get_public_ip() is None


class TestDdnsResult:
    def test_summary_no_change(self):
        r = DdnsResult(current_ip="1.2.3.4", previous_ip="1.2.3.4", changed=False, records_updated=0, records_failed=0)
        assert "inchangee" in r.summary()

    def test_summary_changed(self):
        r = DdnsResult(current_ip="5.6.7.8", previous_ip="1.2.3.4", changed=True, records_updated=1, records_failed=0)
        assert "mise a jour" in r.summary()
        assert "5.6.7.8" in r.summary()

    def test_summary_with_failures(self):
        r = DdnsResult(current_ip="5.6.7.8", previous_ip="1.2.3.4", changed=True, records_updated=1, records_failed=1)
        assert "echoues" in r.summary()

    def test_to_dict(self):
        r = DdnsResult(current_ip="1.2.3.4", previous_ip="0.0.0.0", changed=True, records_updated=2, records_failed=0)
        d = r.to_dict()
        assert d["current_ip"] == "1.2.3.4"
        assert d["changed"] is True


class TestCheckAndUpdate:
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_API_TOKEN", "")
    def test_returns_none_if_not_configured(self):
        assert check_and_update() is None

    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_API_TOKEN", "token")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_ZONE_ID", "zone")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_RECORD_NAMES", "test.example.com")
    @mock.patch("src.ddns_cloudflare.get_public_ip", return_value=None)
    @mock.patch("src.ddns_cloudflare._last_check_time", 0.0)
    def test_returns_none_if_ip_unavailable(self, mock_ip):
        assert check_and_update(force=True) is None

    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_API_TOKEN", "token")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_ZONE_ID", "zone")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_RECORD_NAMES", "test.example.com")
    @mock.patch("src.ddns_cloudflare.get_public_ip", return_value="1.2.3.4")
    def test_no_change(self, mock_ip):
        import src.ddns_cloudflare as ddns_mod
        ddns_mod._last_known_ip = "1.2.3.4"
        ddns_mod._last_check_time = 0.0
        result = check_and_update(force=True)
        assert result is not None
        assert result.changed is False
        ddns_mod._last_known_ip = ""

    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_API_TOKEN", "token")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_ZONE_ID", "zone")
    @mock.patch("src.ddns_cloudflare.CLOUDFLARE_RECORD_NAMES", "test.example.com")
    @mock.patch("src.ddns_cloudflare._last_known_ip", "1.2.3.4")
    @mock.patch("src.ddns_cloudflare.get_public_ip", return_value="5.6.7.8")
    @mock.patch("src.ddns_cloudflare._get_record_id", return_value="rec123")
    @mock.patch("src.ddns_cloudflare._update_record", return_value=True)
    @mock.patch("src.ddns_cloudflare._last_check_time", 0.0)
    def test_ip_changed_and_updated(self, mock_update, mock_get_id, mock_ip):
        result = check_and_update(force=True)
        assert result is not None
        assert result.changed is True
        assert result.current_ip == "5.6.7.8"
        assert result.records_updated == 1
        assert result.records_failed == 0
