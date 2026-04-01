"""Tests for src/tailscale_dns.py"""

import json
import time
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured:
    def test_returns_true_when_all_set(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "token"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"):
            from tailscale_dns import is_configured
            assert is_configured() is True

    def test_returns_false_when_api_key_missing(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", ""), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "token"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"):
            from tailscale_dns import is_configured
            assert is_configured() is False

    def test_returns_false_when_tailnet_missing(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", ""), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "token"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"):
            from tailscale_dns import is_configured
            assert is_configured() is False

    def test_returns_false_when_cf_token_missing(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", ""), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"):
            from tailscale_dns import is_configured
            assert is_configured() is False

    def test_returns_false_when_zone_id_missing(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "token"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", ""):
            from tailscale_dns import is_configured
            assert is_configured() is False


# ---------------------------------------------------------------------------
# _build_fqdn
# ---------------------------------------------------------------------------

class TestBuildFqdn:
    def test_no_subdomain_no_prefix_no_postfix(self):
        with patch("tailscale_dns.TAILSCALE_DNS_PREFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_POSTFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_SUBDOMAIN", ""):
            from tailscale_dns import _build_fqdn
            assert _build_fqdn("myhost") == "myhost"

    def test_with_subdomain(self):
        with patch("tailscale_dns.TAILSCALE_DNS_PREFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_POSTFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_SUBDOMAIN", "ts"):
            from tailscale_dns import _build_fqdn
            assert _build_fqdn("myhost") == "myhost.ts"

    def test_with_prefix(self):
        with patch("tailscale_dns.TAILSCALE_DNS_PREFIX", "ts-"), \
             patch("tailscale_dns.TAILSCALE_DNS_POSTFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_SUBDOMAIN", ""):
            from tailscale_dns import _build_fqdn
            assert _build_fqdn("myhost") == "ts-myhost"

    def test_with_postfix(self):
        with patch("tailscale_dns.TAILSCALE_DNS_PREFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_POSTFIX", "-vpn"), \
             patch("tailscale_dns.TAILSCALE_DNS_SUBDOMAIN", ""):
            from tailscale_dns import _build_fqdn
            assert _build_fqdn("myhost") == "myhost-vpn"

    def test_with_all(self):
        with patch("tailscale_dns.TAILSCALE_DNS_PREFIX", "ts-"), \
             patch("tailscale_dns.TAILSCALE_DNS_POSTFIX", "-vpn"), \
             patch("tailscale_dns.TAILSCALE_DNS_SUBDOMAIN", "local"):
            from tailscale_dns import _build_fqdn
            assert _build_fqdn("server") == "ts-server-vpn.local"


# ---------------------------------------------------------------------------
# _ts_get_devices
# ---------------------------------------------------------------------------

def _make_urlopen_ctx(body: bytes):
    """Return a mock context manager for urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    return mock_resp


class TestTsGetDevices:
    def test_returns_devices_with_tailscale_ip(self):
        payload = {
            "devices": [
                {
                    "hostname": "server",
                    "name": "server.mynet.ts.net",
                    "addresses": ["100.64.0.1", "fd7a::1"],
                }
            ]
        }
        mock_resp = _make_urlopen_ctx(json.dumps(payload).encode("utf-8"))
        with patch("tailscale_dns.TAILSCALE_API_KEY", "tskey"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            from tailscale_dns import _ts_get_devices
            devices = _ts_get_devices()
            assert devices is not None
            ips = [d["ip"] for d in devices]
            assert "100.64.0.1" in ips

    def test_skips_non_tailscale_ips(self):
        payload = {
            "devices": [
                {
                    "hostname": "server",
                    "name": "server",
                    "addresses": ["1.2.3.4"],
                }
            ]
        }
        mock_resp = _make_urlopen_ctx(json.dumps(payload).encode("utf-8"))
        with patch("tailscale_dns.TAILSCALE_API_KEY", "tskey"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            from tailscale_dns import _ts_get_devices
            devices = _ts_get_devices()
            assert devices == []

    def test_adds_name_alias_when_different(self):
        payload = {
            "devices": [
                {
                    "hostname": "server-full",
                    "name": "server.mynet.ts.net",
                    "addresses": ["100.64.0.5"],
                }
            ]
        }
        mock_resp = _make_urlopen_ctx(json.dumps(payload).encode("utf-8"))
        with patch("tailscale_dns.TAILSCALE_API_KEY", "tskey"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            from tailscale_dns import _ts_get_devices
            devices = _ts_get_devices()
            hostnames = [d["hostname"] for d in devices]
            assert "server-full" in hostnames
            assert "server" in hostnames

    def test_returns_none_on_error(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", "tskey"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("urllib.request.urlopen", side_effect=Exception("network error")):
            from tailscale_dns import _ts_get_devices
            assert _ts_get_devices() is None

    def test_returns_none_on_invalid_json(self):
        mock_resp = _make_urlopen_ctx(b"not json")
        with patch("tailscale_dns.TAILSCALE_API_KEY", "tskey"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "mynet"), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            from tailscale_dns import _ts_get_devices
            assert _ts_get_devices() is None


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------

class TestSyncResult:
    def test_summary_nothing_to_do(self):
        from tailscale_dns import SyncResult
        r = SyncResult()
        assert "rien" in r.summary()

    def test_summary_with_created(self):
        from tailscale_dns import SyncResult
        r = SyncResult(created=2)
        assert "2 crees" in r.summary()

    def test_summary_with_all_fields(self):
        from tailscale_dns import SyncResult
        r = SyncResult(created=1, updated=2, deleted=3, unchanged=4, errors=1)
        s = r.summary()
        assert "1 crees" in s
        assert "2 mis a jour" in s
        assert "3 supprimes" in s
        assert "4 inchanges" in s
        assert "1 erreurs" in s

    def test_to_dict_contains_all_fields(self):
        from tailscale_dns import SyncResult
        r = SyncResult(created=1, errors=1, ok=False)
        d = r.to_dict()
        assert d["created"] == 1
        assert d["errors"] == 1
        assert d["ok"] is False


# ---------------------------------------------------------------------------
# sync_tailscale_dns -- rate limiting
# ---------------------------------------------------------------------------

class TestSyncTailscaleDnsRateLimit:
    def test_returns_none_when_not_configured(self):
        with patch("tailscale_dns.TAILSCALE_API_KEY", ""), \
             patch("tailscale_dns.TAILSCALE_TAILNET", ""), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", ""), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", ""):
            from tailscale_dns import sync_tailscale_dns
            assert sync_tailscale_dns() is None

    def test_rate_limited_returns_none(self):
        import tailscale_dns
        tailscale_dns._last_sync_time = time.time()
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "net"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "tok"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"), \
             patch("tailscale_dns.TAILSCALE_SYNC_INTERVAL", 600):
            from tailscale_dns import sync_tailscale_dns
            result = sync_tailscale_dns(force=False)
            assert result is None
        tailscale_dns._last_sync_time = 0.0

    def test_force_bypasses_rate_limit(self):
        import tailscale_dns
        tailscale_dns._last_sync_time = time.time()
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "net"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "tok"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"), \
             patch("tailscale_dns.TAILSCALE_SYNC_INTERVAL", 600), \
             patch("tailscale_dns._ts_get_devices", return_value=None):
            from tailscale_dns import sync_tailscale_dns
            result = sync_tailscale_dns(force=True)
            assert result is not None
            assert result.ok is False
        tailscale_dns._last_sync_time = 0.0


# ---------------------------------------------------------------------------
# sync_tailscale_dns -- create/update/delete scenarios
# ---------------------------------------------------------------------------

def _patch_configured():
    return {
        "tailscale_dns.TAILSCALE_API_KEY": "key",
        "tailscale_dns.TAILSCALE_TAILNET": "net",
        "tailscale_dns.CLOUDFLARE_API_TOKEN": "tok",
        "tailscale_dns.CLOUDFLARE_ZONE_ID": "zone",
        "tailscale_dns.TAILSCALE_DNS_PREFIX": "",
        "tailscale_dns.TAILSCALE_DNS_POSTFIX": "",
        "tailscale_dns.TAILSCALE_DNS_SUBDOMAIN": "",
        "tailscale_dns.TAILSCALE_SYNC_INTERVAL": 600,
        "tailscale_dns.CLOUDFLARE_TTL": 120,
    }


class TestSyncTailscaleDnsScenarios:
    def _run_sync(self, devices, cf_records, cf_request_side_effect=None):
        import tailscale_dns
        tailscale_dns._last_sync_time = 0.0

        cf_response = {"success": True, "result": {"id": "newid"}}
        cf_req = cf_request_side_effect or MagicMock(return_value=cf_response)

        patches = _patch_configured()
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "net"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "tok"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"), \
             patch("tailscale_dns.TAILSCALE_DNS_PREFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_POSTFIX", ""), \
             patch("tailscale_dns.TAILSCALE_DNS_SUBDOMAIN", ""), \
             patch("tailscale_dns.TAILSCALE_SYNC_INTERVAL", 600), \
             patch("tailscale_dns.CLOUDFLARE_TTL", 120), \
             patch("tailscale_dns._ts_get_devices", return_value=devices), \
             patch("tailscale_dns._get_zone_records", return_value=cf_records), \
             patch("tailscale_dns._cf_request", cf_req):
            from tailscale_dns import sync_tailscale_dns
            return sync_tailscale_dns(force=True), cf_req

    def test_creates_new_record(self):
        devices = [{"hostname": "server", "ip": "100.64.0.1"}]
        cf_records = []
        result, cf_req = self._run_sync(devices, cf_records)
        assert result is not None
        assert result.created == 1
        assert result.ok is True

    def test_unchanged_when_ip_matches(self):
        devices = [{"hostname": "server", "ip": "100.64.0.1"}]
        cf_records = [
            {"name": "server", "content": "100.64.0.1", "id": "rec1"},
        ]
        result, _ = self._run_sync(devices, cf_records)
        assert result.unchanged == 1
        assert result.created == 0

    def test_updates_record_when_ip_changes(self):
        devices = [{"hostname": "server", "ip": "100.64.0.2"}]
        cf_records = [
            {"name": "server", "content": "100.64.0.1", "id": "rec1"},
        ]
        result, cf_req = self._run_sync(devices, cf_records)
        assert result.updated == 1

    def test_deletes_orphaned_record(self):
        devices = []
        cf_records = [
            {"name": "oldhost", "content": "100.64.0.9", "id": "rec9"},
        ]
        result, cf_req = self._run_sync(devices, cf_records)
        assert result.deleted == 1

    def test_error_when_create_fails(self):
        devices = [{"hostname": "server", "ip": "100.64.0.1"}]
        cf_records = []
        result, _ = self._run_sync(devices, cf_records, cf_request_side_effect=MagicMock(return_value=None))
        assert result.errors == 1
        assert result.ok is False

    def test_devices_api_failure(self):
        import tailscale_dns
        tailscale_dns._last_sync_time = 0.0
        with patch("tailscale_dns.TAILSCALE_API_KEY", "key"), \
             patch("tailscale_dns.TAILSCALE_TAILNET", "net"), \
             patch("tailscale_dns.CLOUDFLARE_API_TOKEN", "tok"), \
             patch("tailscale_dns.CLOUDFLARE_ZONE_ID", "zone"), \
             patch("tailscale_dns._ts_get_devices", return_value=None):
            from tailscale_dns import sync_tailscale_dns
            result = sync_tailscale_dns(force=True)
            assert result is not None
            assert result.ok is False
            assert result.errors == 1

    def test_skips_invalid_hostname(self):
        devices = [{"hostname": "bad hostname!", "ip": "100.64.0.1"}]
        cf_records = []
        result, cf_req = self._run_sync(devices, cf_records)
        assert result.created == 0
        cf_req.assert_not_called()
