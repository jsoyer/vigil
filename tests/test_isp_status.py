"""Tests for isp_status.py -- FAI status page scraping."""

import json
import urllib.error
from unittest import mock

import pytest

from src.isp_status import (
    ISP_CONFIGS,
    IspCheckResult,
    IspStatus,
    _check_single_isp,
    _get_effective_urls,
    check_isp_status,
    is_configured,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(content: str, encoding: str = "utf-8"):
    """Create a mock urllib response returning the given HTML content."""
    raw = content.encode(encoding)
    mock_resp = mock.Mock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
    mock_resp.__exit__ = mock.Mock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# is_configured()
# ---------------------------------------------------------------------------


class TestIsConfigured:
    @mock.patch("src.isp_status.config")
    def test_returns_true_when_enabled(self, mock_cfg):
        mock_cfg.ISP_STATUS_ENABLED = True
        assert is_configured() is True

    @mock.patch("src.isp_status.config")
    def test_returns_false_when_disabled(self, mock_cfg):
        mock_cfg.ISP_STATUS_ENABLED = False
        assert is_configured() is False


# ---------------------------------------------------------------------------
# _get_effective_urls()
# ---------------------------------------------------------------------------


class TestGetEffectiveUrls:
    @mock.patch("src.isp_status.config")
    def test_returns_defaults_when_no_override(self, mock_cfg):
        mock_cfg.ISP_STATUS_URLS = ""
        urls = _get_effective_urls()
        for isp_name in ISP_CONFIGS:
            assert isp_name in urls
            assert urls[isp_name] == str(ISP_CONFIGS[isp_name]["url"])

    @mock.patch("src.isp_status.config")
    def test_overrides_specific_isp_url(self, mock_cfg):
        mock_cfg.ISP_STATUS_URLS = json.dumps({"Free": "https://custom.free.example.com"})
        urls = _get_effective_urls()
        assert urls["Free"] == "https://custom.free.example.com"
        # Other ISPs keep their defaults
        assert urls["Orange"] == str(ISP_CONFIGS["Orange"]["url"])

    @mock.patch("src.isp_status.config")
    def test_invalid_json_falls_back_to_defaults(self, mock_cfg):
        mock_cfg.ISP_STATUS_URLS = "not-valid-json{"
        urls = _get_effective_urls()
        for isp_name in ISP_CONFIGS:
            assert urls[isp_name] == str(ISP_CONFIGS[isp_name]["url"])

    @mock.patch("src.isp_status.config")
    def test_non_dict_json_falls_back_to_defaults(self, mock_cfg):
        mock_cfg.ISP_STATUS_URLS = json.dumps(["not", "a", "dict"])
        urls = _get_effective_urls()
        for isp_name in ISP_CONFIGS:
            assert urls[isp_name] == str(ISP_CONFIGS[isp_name]["url"])


# ---------------------------------------------------------------------------
# IspStatus dataclass
# ---------------------------------------------------------------------------


class TestIspStatus:
    def test_frozen(self):
        status = IspStatus(
            name="Free",
            url="https://free.fr",
            has_incident=False,
            keywords_found=[],
            error=None,
            checked_at="2026-01-01T00:00:00+00:00",
        )
        with pytest.raises(Exception):
            status.has_incident = True  # type: ignore[misc]

    def test_has_incident_true_when_keywords_found(self):
        status = IspStatus(
            name="Orange",
            url="https://orange.fr",
            has_incident=True,
            keywords_found=["incident"],
            error=None,
            checked_at="2026-01-01T00:00:00+00:00",
        )
        assert status.has_incident is True
        assert "incident" in status.keywords_found


# ---------------------------------------------------------------------------
# IspCheckResult dataclass
# ---------------------------------------------------------------------------


class TestIspCheckResult:
    def test_frozen(self):
        result = IspCheckResult(statuses=[], any_incident=False, summary="ok")
        with pytest.raises(Exception):
            result.any_incident = True  # type: ignore[misc]

    def test_any_incident_reflects_statuses(self):
        statuses = [
            IspStatus("Free", "u", True, ["panne"], None, "2026-01-01T00:00:00+00:00"),
            IspStatus("Orange", "u", False, [], None, "2026-01-01T00:00:00+00:00"),
        ]
        result = IspCheckResult(statuses=statuses, any_incident=True, summary="Incident: Free")
        assert result.any_incident is True


# ---------------------------------------------------------------------------
# _check_single_isp()
# ---------------------------------------------------------------------------


class TestCheckSingleIsp:
    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_no_keywords_returns_no_incident(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.return_value = _make_mock_response(
            "<html><body>Tout fonctionne normalement.</body></html>"
        )
        result = _check_single_isp("Free", "https://free.fr", ["incident", "panne"])
        assert result.has_incident is False
        assert result.keywords_found == []
        assert result.error is None
        assert result.name == "Free"

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_keyword_in_page_returns_incident(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.return_value = _make_mock_response(
            "<html><body>Un incident en cours affecte votre connexion.</body></html>"
        )
        result = _check_single_isp("Orange", "https://orange.fr", ["incident en cours", "panne"])
        assert result.has_incident is True
        assert "incident en cours" in result.keywords_found
        assert result.error is None

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_keyword_matching_is_case_insensitive(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.return_value = _make_mock_response(
            "<html><body>INCIDENT DETECTE SUR LE RESEAU.</body></html>"
        )
        result = _check_single_isp("SFR", "https://sfr.fr", ["incident"])
        assert result.has_incident is True
        assert "incident" in result.keywords_found

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_http_error_returns_no_incident_with_error(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://sfr.fr", code=503, msg="Service Unavailable",
            hdrs=None, fp=None,
        )
        result = _check_single_isp("SFR", "https://sfr.fr", ["incident"])
        assert result.has_incident is False
        assert result.error is not None
        assert "503" in result.error

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_url_error_returns_no_incident_with_error(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        result = _check_single_isp("Bouygues", "https://bouygues.fr", ["incident"])
        assert result.has_incident is False
        assert result.error is not None
        assert "timed out" in result.error

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_generic_exception_returns_no_incident_with_error(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.side_effect = RuntimeError("unexpected error")
        result = _check_single_isp("Free", "https://free.fr", ["incident"])
        assert result.has_incident is False
        assert result.error is not None

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_multiple_keywords_all_detected(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.return_value = _make_mock_response(
            "<html><body>incident et panne detectes sur le reseau SFR.</body></html>"
        )
        result = _check_single_isp("SFR", "https://sfr.fr", ["incident", "panne", "perturbation"])
        assert result.has_incident is True
        assert "incident" in result.keywords_found
        assert "panne" in result.keywords_found
        assert "perturbation" not in result.keywords_found

    @mock.patch("src.isp_status.config")
    @mock.patch("src.isp_status.urllib.request.urlopen")
    def test_checked_at_is_iso_format(self, mock_urlopen, mock_cfg):
        mock_cfg.ISP_STATUS_TIMEOUT = 10
        mock_urlopen.return_value = _make_mock_response("<html>ok</html>")
        result = _check_single_isp("Free", "https://free.fr", [])
        # Should parse as ISO datetime without raising
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(result.checked_at)
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# check_isp_status()
# ---------------------------------------------------------------------------


class TestCheckIspStatus:
    def _mock_single_isp(self, name: str, has_incident: bool, error: str | None = None):
        return IspStatus(
            name=name,
            url=f"https://{name.lower()}.example.com",
            has_incident=has_incident,
            keywords_found=["incident"] if has_incident else [],
            error=error,
            checked_at="2026-01-01T00:00:00+00:00",
        )

    @mock.patch("src.isp_status._check_single_isp")
    @mock.patch("src.isp_status._get_effective_urls")
    def test_no_incidents_any_incident_false(self, mock_urls, mock_check):
        mock_urls.return_value = {name: f"https://{name}.example.com" for name in ISP_CONFIGS}
        mock_check.return_value = self._mock_single_isp("Free", False)

        result = check_isp_status()
        assert result.any_incident is False
        assert isinstance(result.statuses, list)
        assert len(result.statuses) == len(ISP_CONFIGS)

    @mock.patch("src.isp_status._check_single_isp")
    @mock.patch("src.isp_status._get_effective_urls")
    def test_one_incident_any_incident_true(self, mock_urls, mock_check):
        mock_urls.return_value = {name: f"https://{name}.example.com" for name in ISP_CONFIGS}

        def side_effect(name, url, keywords):
            return self._mock_single_isp(name, name == "Free")

        mock_check.side_effect = side_effect

        result = check_isp_status()
        assert result.any_incident is True
        assert "Free" in result.summary

    @mock.patch("src.isp_status._check_single_isp")
    @mock.patch("src.isp_status._get_effective_urls")
    def test_summary_lists_incident_isps(self, mock_urls, mock_check):
        mock_urls.return_value = {name: f"https://{name}.example.com" for name in ISP_CONFIGS}

        def side_effect(name, url, keywords):
            return self._mock_single_isp(name, name in ("Free", "SFR"))

        mock_check.side_effect = side_effect

        result = check_isp_status()
        assert "Free" in result.summary
        assert "SFR" in result.summary

    @mock.patch("src.isp_status._check_single_isp")
    @mock.patch("src.isp_status._get_effective_urls")
    def test_partial_errors_still_returns_result(self, mock_urls, mock_check):
        mock_urls.return_value = {name: f"https://{name}.example.com" for name in ISP_CONFIGS}

        def side_effect(name, url, keywords):
            return self._mock_single_isp(name, False, error="HTTP 503" if name == "Orange" else None)

        mock_check.side_effect = side_effect

        result = check_isp_status()
        assert len(result.statuses) == len(ISP_CONFIGS)
        orange = next(s for s in result.statuses if s.name == "Orange")
        assert orange.error == "HTTP 503"

    @mock.patch("src.isp_status._check_single_isp")
    @mock.patch("src.isp_status._get_effective_urls")
    def test_returns_isp_check_result_type(self, mock_urls, mock_check):
        mock_urls.return_value = {name: f"https://{name}.example.com" for name in ISP_CONFIGS}
        mock_check.return_value = self._mock_single_isp("Free", False)

        result = check_isp_status()
        assert isinstance(result, IspCheckResult)

    @mock.patch("src.isp_status._check_single_isp")
    @mock.patch("src.isp_status._get_effective_urls")
    def test_all_errors_produces_no_incident_summary(self, mock_urls, mock_check):
        mock_urls.return_value = {name: f"https://{name}.example.com" for name in ISP_CONFIGS}
        mock_check.return_value = self._mock_single_isp("Free", False, error="timeout")

        result = check_isp_status()
        assert result.any_incident is False
        # Summary should mention that pages were inaccessible
        assert "inaccessibles" in result.summary or "aucun" in result.summary.lower()
